#!/usr/bin/env python3
"""
Deterministic merge of shard findings for the shard protocol (zero LLM tokens, stdlib only).

A whole-repo review / security_audit is split into shards (`repo_inventory.py shards`); one
reviewer/auditor subagent per shard writes its verdict to a findings JSON file:

  {"shard": "<id>",
   "verdict": "approve | request_changes",
   "findings": [{"severity": "critical | major | minor | nit",
                 "file": "<path>", "line": <int|null>, "title": "...", "detail": "..."}]}

This script merges those files into one report — without the LLM, so the merged verdict cannot be
softened in prose:

  - deduplication by (file, line, normalized title), where the title is stripped, whitespace
    collapsed and lowercased; duplicates collapse into one finding carrying
    `occurrences: [<shard ids>]` (sorted, unique);
  - sorting by severity (critical -> major -> minor -> nit), then file, then line (null last),
    then normalized title — so the merged order never depends on the input order;
  - summary: per-severity counts, shard count, and the merged verdict — request_changes when at
    least one shard returned request_changes OR any critical finding exists, else approve.

CLI:
  merge_findings.py --inputs f1.json f2.json ... [--report merged.json] [--md merged.md]
      The merged JSON always goes to stdout (and to --report when given); a human-readable
      markdown report is written to --md when given.
      Exit 0 = merged verdict approve, 1 = request_changes, 2 = broken input (stderr names the
      file and what is wrong) or an unwritable output path.

Determinism: the same shard files in any order produce a byte-identical merged report. Findings
that differ only in severity or detail are collapsed picking the most severe record and, among
equals, the lowest shard id, then the smallest detail.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

SEVERITIES = ("critical", "major", "minor", "nit")
VERDICTS = ("approve", "request_changes")
SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}
# Merged verdict is request_changes when any shard asks for it or any critical finding exists.
BLOCKING_SEVERITY = "critical"


class InputError(Exception):
    """A findings file does not match the shard findings contract."""


def normalize_title(title: str) -> str:
    """Dedup/ordering part of the key: stripped, whitespace-collapsed, lowercased."""
    return re.sub(r"\s+", " ", title).strip().lower()


def _validate_finding(raw: object, label: str, index: int) -> dict:
    """One validated finding record; raises InputError naming the file and the problem."""
    where = f"findings[{index}]"
    if not isinstance(raw, dict):
        raise InputError(f"{label}: {where} must be a JSON object, got {type(raw).__name__}")
    severity = raw.get("severity")
    if severity not in SEVERITIES:
        raise InputError(f"{label}: {where}.severity must be one of {list(SEVERITIES)}, "
                         f"got {severity!r}")
    file = raw.get("file")
    if not isinstance(file, str) or not file.strip():
        raise InputError(f"{label}: {where}.file must be a non-empty string, got {file!r}")
    line = raw.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
        raise InputError(f"{label}: {where}.line must be an integer or null, got {line!r}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InputError(f"{label}: {where}.title must be a non-empty string, got {title!r}")
    detail = raw.get("detail", "")
    if not isinstance(detail, str):
        raise InputError(f"{label}: {where}.detail must be a string, got {type(detail).__name__}")
    return {"severity": severity, "file": file.strip(), "line": line,
            "title": title.strip(), "detail": detail}


def load_shard_file(path: pathlib.Path) -> dict:
    """Read, parse and validate one shard findings file."""
    label = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"{label}: cannot be read: {exc}") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{label}: invalid JSON at line {exc.lineno} column {exc.colno}: "
                         f"{exc.msg}") from None
    if not isinstance(payload, dict):
        raise InputError(f"{label}: top level must be a JSON object, "
                         f"got {type(payload).__name__}")
    shard = payload.get("shard")
    if not isinstance(shard, str) or not shard.strip():
        raise InputError(f"{label}: shard must be a non-empty string, got {shard!r}")
    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        raise InputError(f"{label}: verdict must be one of {list(VERDICTS)}, got {verdict!r}")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise InputError(f"{label}: findings must be a list, "
                         f"got {type(raw_findings).__name__}")
    return {"shard": shard.strip(), "verdict": verdict,
            "findings": [_validate_finding(raw, label, i) for i, raw in enumerate(raw_findings)]}


def _sort_key(finding: dict) -> tuple:
    """Severity, then file, then line (null last), then normalized title."""
    line = finding["line"]
    return (SEVERITY_RANK[finding["severity"]], finding["file"],
            float("inf") if line is None else line, normalize_title(finding["title"]))


def merge(shards: list[dict]) -> dict:
    """Merged report for already validated shard payloads, independent of their order."""
    verdicts: dict[str, str] = {}
    groups: dict[tuple, list[tuple[str, dict]]] = {}
    for payload in shards:
        shard = payload["shard"]
        if verdicts.get(shard) != "request_changes":
            verdicts[shard] = payload["verdict"]
        for finding in payload["findings"]:
            key = (finding["file"], finding["line"], normalize_title(finding["title"]))
            groups.setdefault(key, []).append((shard, finding))

    findings: list[dict] = []
    for (file, line, _), records in groups.items():
        # Most severe first, then lowest shard id, then smallest detail: order-stable choice.
        records.sort(key=lambda pair: (SEVERITY_RANK[pair[1]["severity"]], pair[0],
                                       pair[1]["detail"]))
        chosen = records[0][1]
        findings.append({"severity": chosen["severity"], "file": file, "line": line,
                         "title": chosen["title"], "detail": chosen["detail"],
                         "occurrences": sorted({pair[0] for pair in records})})
    findings.sort(key=_sort_key)

    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding["severity"]] += 1
    shard_ids = sorted(verdicts)
    blocked = counts[BLOCKING_SEVERITY] > 0 or any(v == "request_changes" for v in verdicts.values())
    return {"verdict": "request_changes" if blocked else "approve",
            "total_shards": len(shard_ids),
            "shards": [{"shard": shard, "verdict": verdicts[shard]} for shard in shard_ids],
            "total_findings": len(findings),
            "counts": counts,
            "findings": findings}


def _location(finding: dict) -> str:
    return finding["file"] if finding["line"] is None else f"{finding['file']}:{finding['line']}"


def render_markdown(report: dict) -> str:
    """Human-readable merged report (deterministic: same report -> same text)."""
    lines = ["# Merged shard findings", "",
             f"- verdict: **{report['verdict']}**",
             f"- shards: {report['total_shards']} "
             f"({', '.join(s['shard'] for s in report['shards'])})",
             f"- findings: {report['total_findings']} ("
             + ", ".join(f"{severity}: {report['counts'][severity]}" for severity in SEVERITIES)
             + ")"]
    if report["shards"]:
        lines += ["", "## Shard verdicts", ""]
        lines += [f"- {s['shard']}: {s['verdict']}" for s in report["shards"]]
    for severity in SEVERITIES:
        group = [f for f in report["findings"] if f["severity"] == severity]
        if not group:
            continue
        lines += ["", f"## {severity}", ""]
        for finding in group:
            lines.append(f"- **{_location(finding)}** — {finding['title']}")
            lines.append(f"  - occurrences: {', '.join(finding['occurrences'])}")
            detail = " ".join(finding["detail"].split())
            if detail:
                lines.append(f"  - detail: {detail}")
    return "\n".join(lines) + "\n"


def write_text(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 with LF newlines on every platform (byte-identical output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", nargs="+", required=True, metavar="FINDINGS",
                    help="Shard findings JSON files (one per shard)")
    ap.add_argument("--report", metavar="PATH",
                    help="Also write the merged JSON report to this path")
    ap.add_argument("--md", metavar="PATH",
                    help="Also write a human-readable markdown report to this path")
    args = ap.parse_args()

    payloads: list[dict] = []
    for name in args.inputs:
        try:
            payloads.append(load_shard_file(pathlib.Path(name)))
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    report = merge(payloads)
    text = json.dumps(report, indent=2, sort_keys=True)
    try:
        if args.report:
            write_text(pathlib.Path(args.report), text + "\n")
        if args.md:
            write_text(pathlib.Path(args.md), render_markdown(report))
    except OSError as exc:
        print(f"error: cannot write output: {exc}", file=sys.stderr)
        return 2

    print(text)
    return 0 if report["verdict"] == "approve" else 1


if __name__ == "__main__":
    sys.exit(main())

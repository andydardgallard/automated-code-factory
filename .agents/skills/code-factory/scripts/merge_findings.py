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
    `occurrences: [<shard ids>]` (sorted in shard-id order, unique);
  - sorting by severity (critical -> major -> minor -> nit), then file, then line (null last),
    then normalized title — so the merged order never depends on the input order;
  - summary: per-severity counts, shard count, and the merged verdict — request_changes when at
    least one shard returned request_changes OR any critical finding exists, else approve,
  - FINDING DISPOSITION (`finding_disposition`: `accepted` | `refuted`, absent = accepted for legacy
    input): a REFUTED finding must carry `finding_evidence` — ONE repo-relative artifact path, which
    `--repo` additionally proves exists. A refuted finding stops counting toward the critical rule
    and is omitted from the follow-up task, but it is NEVER deleted from the merged report and the
    report states how many were refuted (`refuted`), so nothing disappears silently. A finding is
    refuted only when EVERY shard occurrence is (one dissenting shard keeps it alive).

CLI:
  merge_findings.py --inputs f1.json f2.json ... [--round <id>] [--report merged.json]
                    [--md merged.md]
      The merged JSON always goes to stdout (and to --report when given); a human-readable
      markdown report is written to --md when given. `--round <id>` stamps the review round the
      findings belong to into the report (`round`), the identity `delegation_gate.py settle`
      requires before it refunds the iteration that round consumed — ONE artifact, ONE round. The
      id must match the settlement grammar `[A-Za-z0-9._-]+` (full match): an identifier the
      settlement would refuse is refused here, so a stamped report can always settle its round.
      Exit 0 = merged verdict approve, 1 = request_changes, 2 = broken input (stderr names the
      file and what is wrong) or an unwritable output path.

Determinism: the same shard files in any order produce a byte-identical merged report. Findings
that differ only in severity or detail are collapsed picking the most severe record and, among
equals, the lowest shard id (shard ids compare numerically, so `shard-2` is lower than `shard-10`),
then the smallest detail.
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
# Finding disposition (P-8): a reviewer may REFUTE its own finding (the quote was wrong, the code
# path is unreachable, a later shard proved it mistaken) — and a refutation must carry evidence. A
# refuted finding stops counting toward the critical rule that forces request_changes, but it is
# never deleted: the merged report keeps it (with its evidence) and states how many were refuted, so
# nothing disappears silently. An ABSENT field is legacy input and normalizes to `accepted`.
DISPOSITIONS = ("accepted", "refuted")
DISPOSITION_ACCEPTED, DISPOSITION_REFUTED = DISPOSITIONS
# The evidence of a refutation is ONE repo-relative artifact path (no spaces, no `..` segment): a
# refutation is a claim about a concrete record (the review report, a log, a test output), and a
# free-text sentence cannot be checked.
EVIDENCE_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
# The review-round identifier: the SAME grammar `delegation_gate.py` settles by, so a report this
# command stamps can always be used to settle the round it names — an identifier the settlement
# would reject is refused HERE, where the mistake is made.
ROUND_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_disposition(raw: dict, label: str, where: str) -> tuple[str, str]:
    """`(disposition, evidence)` of one finding, validated; raises InputError naming the problem.

    `finding_disposition` is exactly `accepted` or `refuted` and defaults to `accepted` (legacy
    input); `finding_evidence` must be a single artifact path and is REQUIRED for a refutation —
    without it the refutation cannot be checked and the finding stays accepted instead of vanishing.
    """
    disposition = raw.get("finding_disposition", DISPOSITION_ACCEPTED)
    if disposition not in DISPOSITIONS:
        raise InputError(f"{label}: {where}.finding_disposition must be one of "
                         f"{list(DISPOSITIONS)}, got {disposition!r}")
    evidence = raw.get("finding_evidence", "")
    if not isinstance(evidence, str):
        raise InputError(f"{label}: {where}.finding_evidence must be a string, "
                         f"got {type(evidence).__name__}")
    evidence = evidence.strip()
    if disposition == DISPOSITION_REFUTED and not evidence:
        raise InputError(f"{label}: {where} is refuted without 'finding_evidence': a refutation "
                         f"must name the artifact that proves it (file, log or report), otherwise "
                         f"the finding is simply suppressed")
    if evidence and (not EVIDENCE_RE.match(evidence) or ".." in evidence.split("/")):
        raise InputError(f"{label}: {where}.finding_evidence must be ONE repo-relative artifact "
                         f"path (no spaces, no '..' segment), got {evidence!r}")
    return disposition, evidence



class InputError(Exception):
    """A findings file does not match the shard findings contract."""


def normalize_title(title: str) -> str:
    """Dedup/ordering part of the key: stripped, whitespace-collapsed, lowercased."""
    return re.sub(r"\s+", " ", title).strip().lower()


def shard_key(shard_id: str) -> tuple:
    """Natural sort key of a shard id: `shard-2` sorts before `shard-10`.

    A plain string comparison puts `shard-10` first, which would silently break the documented
    "lowest shard id wins" choice as soon as a review has ten or more shards. The id is split on
    digit runs and every digit run compares as an integer; text parts keep comparing as text
    (`(0, text)` / `(1, integer)` keeps the two kinds from ever being compared to each other).
    """
    return tuple((0, part) if not part.isdigit() else (1, int(part))
                 for part in re.split(r"(\d+)", shard_id))


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
    disposition, evidence = validate_disposition(raw, label, where)
    return {"severity": severity, "file": file.strip(), "line": line,
            "title": title.strip(), "detail": detail,
            "finding_disposition": disposition, "finding_evidence": evidence}


def load_shard_file(path: pathlib.Path, repo: pathlib.Path | None = None) -> dict:
    """Read, parse and validate one shard findings file.

    `repo` is the repository the review ran in; when it is given, every REFUTATION's evidence must
    name an artifact that really exists there (a refutation pointing at a file nobody can read is a
    suppression with a footnote). Without it the evidence is form-checked only.
    """
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
    findings = [_validate_finding(raw, label, i) for i, raw in enumerate(raw_findings)]
    if repo is not None:
        check_evidence(findings, pathlib.Path(repo), label)
    return {"shard": shard.strip(), "verdict": verdict, "findings": findings}


def check_evidence(findings: list[dict], repo: pathlib.Path, label: str) -> None:
    """Every REFUTED finding's evidence must exist inside `repo`; raise InputError otherwise."""
    for index, finding in enumerate(findings):
        if finding["finding_disposition"] != DISPOSITION_REFUTED:
            continue
        candidate = (repo / finding["finding_evidence"]).resolve()
        if not candidate.is_relative_to(repo.resolve()) or not candidate.is_file():
            raise InputError(f"{label}: findings[{index}] is refuted with evidence "
                             f"{finding['finding_evidence']!r}, which is not a file inside {repo}: "
                             f"the refutation must point at the artifact that proves it")


def _sort_key(finding: dict) -> tuple:
    """Severity, then file, then line (null last), then normalized title."""
    line = finding["line"]
    return (SEVERITY_RANK[finding["severity"]], finding["file"],
            float("inf") if line is None else line, normalize_title(finding["title"]))


def _occurrence_key(pair: tuple[str, dict]) -> tuple:
    """Which occurrence REPRESENTS a merged finding: an ACTIVE one wins over a refuted one.

    A finding is refuted only when EVERY shard occurrence is refuted (see `merge`), so the
    representative must be the active record whenever one exists — otherwise a single refuting shard
    would dress a live finding as refuted. Among the same disposition the documented order holds
    (most severe, lowest shard id, smallest detail).
    """
    shard, finding = pair
    refuted = 1 if finding["finding_disposition"] == DISPOSITION_REFUTED else 0
    return (refuted, SEVERITY_RANK[finding["severity"]], shard_key(shard), finding["detail"])


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
        records.sort(key=_occurrence_key)
        chosen = records[0][1]
        # REFUTED only when every occurrence is: a refutation must cover the whole finding, and one
        # dissenting shard keeps it alive (never silently suppressed by the minority).
        refuted = all(pair[1]["finding_disposition"] == DISPOSITION_REFUTED for pair in records)
        findings.append({"severity": chosen["severity"], "file": file, "line": line,
                         "title": chosen["title"], "detail": chosen["detail"],
                         "occurrences": sorted({pair[0] for pair in records}, key=shard_key),
                         "finding_disposition": (DISPOSITION_REFUTED if refuted
                                                 else DISPOSITION_ACCEPTED),
                         "finding_evidence": (chosen["finding_evidence"] if refuted else "")})
    findings.sort(key=_sort_key)

    counts = {severity: 0 for severity in SEVERITIES}
    refuted_count = 0
    for finding in findings:
        if finding["finding_disposition"] == DISPOSITION_REFUTED:
            refuted_count += 1
            continue                      # a refuted finding never counts toward the critical rule
        counts[finding["severity"]] += 1
    shard_ids = sorted(verdicts, key=shard_key)
    # A shard's `request_changes` blocks only while it still CONTRIBUTES an active finding: a round
    # whose every finding was refuted with evidence proved nothing and must not keep the merged
    # verdict red through the shard's original request. A shard that asked for changes and listed NO
    # findings stays blocking — that is the explicit "something is wrong, I could not enumerate it"
    # signal, and it is the one case no disposition can discharge.
    active_shards: set[str] = set()
    for finding in findings:
        if finding["finding_disposition"] != DISPOSITION_REFUTED:
            active_shards.update(finding["occurrences"])
    silent_requests = {payload["shard"] for payload in shards if not payload["findings"]}
    blocked = counts[BLOCKING_SEVERITY] > 0 or any(
        verdict == "request_changes" and (shard in active_shards or shard in silent_requests)
        for shard, verdict in verdicts.items())
    return {"verdict": "request_changes" if blocked else "approve",
            "total_shards": len(shard_ids),
            "shards": [{"shard": shard, "verdict": verdicts[shard]} for shard in shard_ids],
            "total_findings": len(findings),
            "counts": counts,
            "refuted": refuted_count,
            "findings": findings}


def _location(finding: dict) -> str:
    return finding["file"] if finding["line"] is None else f"{finding['file']}:{finding['line']}"


def render_markdown(report: dict) -> str:
    """Human-readable merged report (deterministic: same report -> same text)."""
    active = [finding for finding in report["findings"]
              if finding.get("finding_disposition") != DISPOSITION_REFUTED]
    refuted = [finding for finding in report["findings"]
               if finding.get("finding_disposition") == DISPOSITION_REFUTED]
    lines = ["# Merged shard findings", "",
             f"- verdict: **{report['verdict']}**",
             f"- shards: {report['total_shards']} "
             f"({', '.join(s['shard'] for s in report['shards'])})",
             f"- findings: {report['total_findings']} ("
             + ", ".join(f"{severity}: {report['counts'][severity]}" for severity in SEVERITIES)
             + (f"; refuted: {report['refuted']}" if report.get("refuted") else "") + ")"]
    if report["shards"]:
        lines += ["", "## Shard verdicts", ""]
        lines += [f"- {s['shard']}: {s['verdict']}" for s in report["shards"]]
    for severity in SEVERITIES:
        group = [f for f in active if f["severity"] == severity]
        if not group:
            continue
        lines += ["", f"## {severity}", ""]
        for finding in group:
            lines.append(f"- **{_location(finding)}** — {finding['title']}")
            lines.append(f"  - occurrences: {', '.join(finding['occurrences'])}")
            detail = " ".join(finding["detail"].split())
            if detail:
                lines.append(f"  - detail: {detail}")
    if refuted:
        lines += ["", "## refuted", ""]
        for finding in refuted:
            lines.append(f"- **{_location(finding)}** — {finding['title']}")
            lines.append(f"  - occurrences: {', '.join(finding['occurrences'])}")
            lines.append(f"  - evidence: {finding['finding_evidence']}")
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
    ap.add_argument("--round", metavar="ID", default=None,
                    help="the review round these findings belong to (stamped into the report; "
                         "`delegation_gate.py settle` requires it)")
    ap.add_argument("--report", metavar="PATH",
                    help="Also write the merged JSON report to this path")
    ap.add_argument("--md", metavar="PATH",
                    help="Also write a human-readable markdown report to this path")
    ap.add_argument("--repo", metavar="PATH", default=None,
                    help="Repository the review ran in: when given, a refuted finding's evidence "
                         "must be a file inside it")
    args = ap.parse_args()

    payloads: list[dict] = []
    for name in args.inputs:
        try:
            payloads.append(load_shard_file(pathlib.Path(name),
                                            pathlib.Path(args.repo) if args.repo else None))
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    report = merge(payloads)
    if args.round is not None:
        # The round identity travels WITH the merged report: `delegation_gate.py settle` refuses a
        # refund without it, so one artifact can settle exactly one round.
        # The RAW argument is judged: stripping first would silently accept `iter-1\n` and other
        # whitespace spellings the settlement refuses, and `fullmatch` (not `match`) rejects them
        # because `$` alone matches before a trailing newline.
        round_id = str(args.round)
        if not ROUND_RE.fullmatch(round_id):
            print(f"error: --round {round_id!r} is not a settlement identifier: it must match "
                  f"[A-Za-z0-9._-]+ in FULL (no whitespace, no trailing newline), the grammar "
                  f"`delegation_gate.py settle --round` accepts — a report stamped with anything "
                  f"else could never settle its round", file=sys.stderr)
            return 2
        report["round"] = round_id
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

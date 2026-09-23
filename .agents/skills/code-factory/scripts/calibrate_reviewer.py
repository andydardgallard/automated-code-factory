#!/usr/bin/env python3
"""
Deterministic golden-set scoring for the code reviewer (zero LLM tokens, stdlib only).

The reviewer is calibrated against a golden set — `skill-base/golden-set/cases/<id>/` holds a
small synthetic `diff.patch` and a flat `expected.yaml` (see `skill-base/golden-set/README.md`):

  verdict: approve | request_changes
  severities: [critical, major, minor, nit]     # `[]` = the ideal reviewer reports nothing

A run of the reviewer over those diffs writes one result file per case — `<results>/<id>.json` —
holding the reviewer's ordinary verdict for that case (`references/code-review.md` §6:
`{"verdict": ..., "findings": [{"file", "line", "severity", "issue", "quote", "fix"}, ...]}`; the
§1.1 shard shape with `title`/`detail` scores the same), and this script scores it. Scoring reads
ONLY `verdict` and the `severity` of every finding, so the other fields are free in both shapes:

  - per case: does the verdict match the golden one, and which severities did the reviewer report;
  - severity scoring: a severity is a HIT when it occurs in both expected and actual (set
    semantics, duplicates collapse); expected `[]` + actual `[]` is a perfect empty hit, so a
    severity missing from one side is a false negative and an unexpected one a false positive;
  - precision = hits / actual severities (1.0 when actual is empty), recall = hits / expected
    severities (1.0 when expected is empty); the summary reports the macro mean over cases and the
    pooled tp/fp/fn counts.

The metrics are data, not a gate: a successful scoring run always exits 0. Exit 2 means the run
could not be scored or reported — a golden case without a result (incomplete run, the missing ids
are listed), an unreadable/malformed case/result file (the file and the problem are named) or a
report that cannot be written (the path and the OS error are named).

Deterministic: the same inputs produce a byte-identical report (no timestamps; cases in sorted id
order; extra result files are reported, not scored).

Usage:
  python3 calibrate_reviewer.py score --golden skill-base/golden-set/cases \\
      --results .code-factory/logs/golden-results --out .code-factory/logs/reviewer-calibration.md
      [--run-id 20260922-442cd2f8]

`--run-id` (`scripts/run_id.py`) is optional and only adds the line `run_id: <id>` to the header of
the report, so the artifact names the run it belongs to; without it the output is unchanged.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

SEVERITIES = ("critical", "major", "minor", "nit")
VERDICTS = ("approve", "request_changes")


class InputError(Exception):
    """A golden case or a reviewer result does not match its contract."""


def _rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def _severity_list(value: str, label: str) -> list[str]:
    """`[critical, major]` / `[]` -> deduplicated severities in severity-scale order."""
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise InputError(f"{label}: expected a bracketed list like [critical, major], "
                         f"got {value!r}")
    items: list[str] = []
    for raw in text[1:-1].split(","):
        item = raw.strip().strip("\"'").strip()
        if item:
            items.append(item)
    for item in items:
        if item not in SEVERITIES:
            raise InputError(f"{label}: {item!r} is not one of {list(SEVERITIES)}")
    return sorted(set(items), key=_rank)


def parse_expected(text: str, label: str) -> dict:
    """Flat YAML subset: `key: value` lines; blank lines and `#` comments are ignored."""
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise InputError(f"{label}: line {number} is not `key: value`: {raw!r}")
        values[key.strip()] = value.strip()
    verdict = values.get("verdict")
    if verdict not in VERDICTS:
        raise InputError(f"{label}: verdict must be one of {list(VERDICTS)}, got {verdict!r}")
    return {"verdict": verdict,
            "severities": _severity_list(values.get("severities", "[]"), f"{label}: severities")}


def load_cases(golden: pathlib.Path) -> list[dict]:
    """Every golden case (id + expected verdict/severities), sorted by case id."""
    if not golden.is_dir():
        raise InputError(f"golden dir does not exist or is not a directory: {golden}")
    case_dirs = sorted((p for p in golden.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not case_dirs:
        raise InputError(f"no case directories in {golden}")
    cases: list[dict] = []
    for case_dir in case_dirs:
        expected_path = case_dir / "expected.yaml"
        if not expected_path.is_file():
            raise InputError(f"{expected_path}: missing expected.yaml for case {case_dir.name!r}")
        try:
            text = expected_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InputError(f"{expected_path}: cannot be read: {exc}") from None
        expected = parse_expected(text, str(expected_path))
        cases.append({"id": case_dir.name, **expected})
    return cases


def load_result_file(path: pathlib.Path) -> dict:
    """One validated reviewer result: verdict, deduplicated severities and finding count."""
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
    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        raise InputError(f"{label}: verdict must be one of {list(VERDICTS)}, got {verdict!r}")
    raw_findings = payload.get("findings", [])
    if not isinstance(raw_findings, list):
        raise InputError(f"{label}: findings must be a list, got {type(raw_findings).__name__}")
    severities: list[str] = []
    for index, finding in enumerate(raw_findings):
        severity = finding.get("severity") if isinstance(finding, dict) else None
        if severity not in SEVERITIES:
            raise InputError(f"{label}: findings[{index}].severity must be one of "
                             f"{list(SEVERITIES)}, got {severity!r}")
        severities.append(severity)
    return {"verdict": verdict, "severities": sorted(set(severities), key=_rank),
            "findings": len(raw_findings)}


def load_results(results: pathlib.Path) -> dict[str, dict]:
    """Reviewer results `<id>.json` -> {id: validated result}."""
    if not results.is_dir():
        raise InputError(f"results dir does not exist or is not a directory: {results}")
    loaded: dict[str, dict] = {}
    for path in sorted(results.glob("*.json"), key=lambda p: p.name):
        loaded[path.stem] = load_result_file(path)
    return loaded


def score_case(case: dict, result: dict) -> dict:
    """Deterministic per-case comparison of one golden case with the reviewer's result."""
    expected = set(case["severities"])
    actual = set(result["severities"])
    matched = sorted(expected & actual, key=_rank)
    missing = sorted(expected - actual, key=_rank)
    extra = sorted(actual - expected, key=_rank)
    return {
        "id": case["id"],
        "expected_verdict": case["verdict"],
        "actual_verdict": result["verdict"],
        "verdict_match": case["verdict"] == result["verdict"],
        "expected_severities": case["severities"],
        "actual_severities": result["severities"],
        "findings": result["findings"],
        "matched": matched, "missing": missing, "extra": extra,
        # Nothing on a side means nothing to get wrong there, so that ratio is 1.0.
        "precision": 1.0 if not actual else len(matched) / len(actual),
        "recall": 1.0 if not expected else len(matched) / len(expected),
    }


def build_report(cases: list[dict], results: dict[str, dict], golden, results_dir) -> dict:
    """Score every case (the caller has already proven that each one has a result)."""
    rows = [score_case(case, results[case["id"]]) for case in cases]
    total = len(rows)
    hits = sum(1 for row in rows if row["verdict_match"])
    tp = sum(len(row["matched"]) for row in rows)
    fp = sum(len(row["extra"]) for row in rows)
    fn = sum(len(row["missing"]) for row in rows)
    return {
        "golden": str(golden),
        "results": str(results_dir),
        "total_cases": total,
        "cases": rows,
        "unmatched_results": sorted(set(results) - {case["id"] for case in cases}),
        "verdict": {"matched": hits, "total": total,
                    "accuracy": hits / total if total else 1.0},
        "macro": {"precision": sum(r["precision"] for r in rows) / total if total else 1.0,
                  "recall": sum(r["recall"] for r in rows) / total if total else 1.0},
        "pooled": {"tp": tp, "fp": fp, "fn": fn,
                   "precision": 1.0 if not tp + fp else tp / (tp + fp),
                   "recall": 1.0 if not tp + fn else tp / (tp + fn)},
    }


def _list(severities: list[str]) -> str:
    return ", ".join(severities) if severities else "-"


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def case_issues(rows: list[dict]) -> list[str]:
    """Human-readable per-case mismatches (what a recalibration has to look at)."""
    issues: list[str] = []
    for row in rows:
        if not row["verdict_match"]:
            issues.append(f"`{row['id']}`: verdict expected `{row['expected_verdict']}`, "
                          f"got `{row['actual_verdict']}`")
        if row["missing"]:
            issues.append(f"`{row['id']}`: missing severities [{', '.join(row['missing'])}]")
        if row["extra"]:
            issues.append(f"`{row['id']}`: unexpected severities [{', '.join(row['extra'])}]")
    return issues


def render_markdown(report: dict, run_id: str = "") -> str:
    """Human-readable report (deterministic: the same report -> the same text).

    `run_id` is optional provenance (`scripts/run_id.py`): when given, the header names the run
    the report belongs to — the same contract as `verify_acceptance.py` — and without it the
    report is byte-identical to what the tool printed before the option existed.
    """
    lines = [
        "# Reviewer calibration report",
        "",
        f"- golden cases: {report['total_cases']} (`{report['golden']}`)",
        f"- results: `{report['results']}`",
    ]
    if run_id:  # run provenance: the artifact names the run it belongs to (see run_id.py)
        lines.append(f"- run_id: {run_id}")
    lines += [
        "",
        "## Summary",
        "",
        f"- verdict accuracy: {report['verdict']['matched']}/{report['verdict']['total']} "
        f"({_percent(report['verdict']['accuracy'])})",
        f"- macro precision (severity): {report['macro']['precision']:.3f}",
        f"- macro recall (severity): {report['macro']['recall']:.3f}",
        f"- pooled severities: tp={report['pooled']['tp']} fp={report['pooled']['fp']} "
        f"fn={report['pooled']['fn']} (precision {report['pooled']['precision']:.3f}, "
        f"recall {report['pooled']['recall']:.3f})",
        "",
        "## Cases",
        "",
        "| case | expected verdict | actual verdict | verdict match | expected severities | "
        "actual severities | precision | recall |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["cases"]:
        lines.append(
            f"| {row['id']} | {row['expected_verdict']} | {row['actual_verdict']} | "
            f"{'yes' if row['verdict_match'] else 'NO'} | {_list(row['expected_severities'])} | "
            f"{_list(row['actual_severities'])} | {row['precision']:.3f} | {row['recall']:.3f} |")
    issues = case_issues(report["cases"])
    if issues:
        lines += ["", "## Mismatches", ""] + [f"- {issue}" for issue in issues]
    if report["unmatched_results"]:
        lines += ["", "## Unmatched results", ""] + [
            f"- `{name}` has no golden case" for name in report["unmatched_results"]]
    return "\n".join(lines) + "\n"


def write_text(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 with LF newlines on every platform (byte-identical output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def cmd_score(args) -> int:
    golden = pathlib.Path(args.golden)
    results_dir = pathlib.Path(args.results)
    try:
        cases = load_cases(golden)
        results = load_results(results_dir)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    missing = [case["id"] for case in cases if case["id"] not in results]
    if missing:
        print("error: incomplete run — no reviewer result for golden case(s): "
              + ", ".join(missing), file=sys.stderr)
        return 2

    report = build_report(cases, results, golden, results_dir)
    for name in report["unmatched_results"]:
        print(f"warning: {name}.json does not match any golden case", file=sys.stderr)
    try:
        write_text(pathlib.Path(args.out), render_markdown(report, args.run_id))
    except OSError as exc:
        print(f"error: cannot write report {args.out}: {exc}", file=sys.stderr)
        return 2

    pooled = report["pooled"]
    print(f"cases: {report['total_cases']} | verdict accuracy: "
          f"{report['verdict']['matched']}/{report['verdict']['total']} "
          f"({_percent(report['verdict']['accuracy'])}) | "
          f"macro precision: {report['macro']['precision']:.3f} | "
          f"macro recall: {report['macro']['recall']:.3f} | "
          f"tp={pooled['tp']} fp={pooled['fp']} fn={pooled['fn']}")
    print(f"report: {args.out}")
    # Metrics are data, not a gate: a successful scoring run always exits 0.
    return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries
    non-ASCII characters (`§` and the em dash `—`), which that codec cannot encode: `print_help()`
    would raise UnicodeEncodeError and the user would get a traceback instead of the help.
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
    sub = ap.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="Score reviewer results against the golden set")
    score.add_argument("--golden", required=True, metavar="DIR", help="Golden cases directory")
    score.add_argument("--results", required=True, metavar="DIR",
                       help="Directory with one <case-id>.json reviewer result per case")
    score.add_argument("--out", required=True, metavar="PATH", help="Markdown report to write")
    score.add_argument("--run-id", default="", metavar="ID",
                       help="Run id (see run_id.py); when given it is recorded in the report")
    score.set_defaults(func=cmd_score)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

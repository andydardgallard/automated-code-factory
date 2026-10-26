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

`--log <path>` (optional) appends ONE `calibration:` line to the append-only calibration log —
`<repo>/skill-base/golden-set/calibration-log.md` by default — recording the SHA-256 of the
reviewer prompts, the number of run records the memory journal holds at that moment and the
metrics of the calibration. Without the flag nothing is written and the report is unchanged.

`status` turns the periodic obligation of `references/code-review.md` §7 ("re-calibrate after
EVERY edit to a reviewer prompt and at least once per 5 review runs") from prose into a
deterministic gate: it compares the CURRENT reviewer-prompt digest and the CURRENT number of run
records since the last recorded calibration with the last line of the log and fails LOUDLY when a
calibration is due.

  python3 calibrate_reviewer.py status [--repo <root>] [--log <path>] [--max-runs 5]

Exit 0 = the last recorded calibration is still current. Exit 1 = calibration is DUE (the prompt
changed, the run interval elapsed, or no calibration is recorded at all) — each reason is printed.
Exit 2 = the run could not be judged: an unreadable reviewer prompt, or a memory journal that
cannot be read as UTF-8 (ONLY an absent journal — a fresh project — counts as zero runs, so a
corrupt one can never make a due calibration look current). Every count comes from the files on
disk, so the check is deterministic and uses no LLM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

SEVERITIES = ("critical", "major", "minor", "nit")
VERDICTS = ("approve", "request_changes")

# The repository root this script lives in (scripts/ -> code-factory/ -> skills/ -> .agents/ -> root).
ROOT = pathlib.Path(__file__).resolve().parents[4]
# The reviewer PROMPTS: §7 makes an edit to EITHER one invalidate the last calibration.
REVIEWER_PROMPT_FILES = (
    ".agents/skills/code-factory/references/code-review.md",
    ".agents/agents/sub-agents/code-reviewer.md",
)
# The memory journal holds one record per run, so it is the deterministic run counter.
JOURNAL_REL = "memory/change-log.md"
# The append-only record of calibrations — one `calibration:` line per `score --log` run.
LOG_REL = "skill-base/golden-set/calibration-log.md"
# §7: at least one calibration per 5 runs that use the review gate.
MAX_RUNS_SINCE_CALIBRATION = 5
RECORD_PREFIX = "calibration:"
REVIEW_TASK_TYPE = "review"
# One record of the journal opens with `## <ISO timestamp> — <title>` (see memory/change-log.md).
RECORD_HEADING_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}T\S*", re.M)
# The journal fields the run count needs: `run_id:` addresses a run, `task_type:` grades the run.
RECORD_KEYS = ("run_id", "task_type")


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


# ---------------------------------------------------------------------------------------------
# The periodic-calibration gate (§7 of references/code-review.md) — deterministic, no LLM.
# ---------------------------------------------------------------------------------------------
def active_run_id(root: pathlib.Path) -> str:
    """The run_id of the run in progress (`.code-factory/state/pipeline.yaml`), "" when none.

    Read line-wise on purpose (stdlib has no YAML parser); a missing or unreadable checkpoint
    simply means "no active run" — the calibration gate then stays conservative.
    """
    pipeline = root / ".code-factory" / "state" / "pipeline.yaml"
    try:
        for line in pipeline.read_text(encoding="utf-8").splitlines():
            if line.startswith("run_id:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def prompt_digest(root: pathlib.Path) -> str:
    """SHA-256 over the reviewer prompts: path + LF-normalized content of every prompt file.

    A digest, not an mtime: the same text hashes the same on every platform, a touched-but-unchanged
    file does not look like an edit, and a genuine edit cannot hide behind a restored timestamp.
    An unreadable prompt is an InputError — the gate must not answer "current" without its input.
    """
    parts: list[str] = []
    for rel in REVIEWER_PROMPT_FILES:
        try:
            data = (root / rel).read_bytes().replace(b"\r\n", b"\n")
        except OSError as exc:
            raise InputError(f"{rel}: the reviewer prompt cannot be read "
                             f"({exc.strerror or exc})") from None
        parts.append(f"{rel}:{hashlib.sha256(data).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def journal_runs(root: pathlib.Path) -> list[dict[str, str]]:
    """The run records of `memory/change-log.md`, in journal order (one record per run).

    A record opens with `## <ISO timestamp> — <title>`; only `run_id` and `task_type` are read.

    ONLY a genuinely ABSENT journal is the fresh-project case (no run has happened yet), and only
    that one yields an empty list. Every other failure to read it — a permission error, a directory
    in its place, invalid UTF-8 — is an InputError: counting an unreadable journal as "zero runs"
    would let a due calibration report itself as CURRENT on no evidence at all, which is exactly the
    silent-green failure the gate exists to prevent. `status` turns the InputError into exit 2.
    """
    path = root / JOURNAL_REL
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:                    # permissions, a directory, a vanished drive, …
        raise InputError(f"{JOURNAL_REL}: the memory journal cannot be read "
                         f"({exc.strerror or exc})") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"{JOURNAL_REL}: the memory journal cannot be read (not UTF-8: "
                         f"{exc.reason} at byte {exc.start})") from None
    starts = [m.start() for m in RECORD_HEADING_RE.finditer(text)]
    records: list[dict[str, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        fields: dict[str, str] = {}
        for line in text[start:end].splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in RECORD_KEYS:
                fields[key.strip()] = value.strip()
        records.append(fields)
    return records


def runs_since(records: list[dict[str, str]],
               calibration_run_id: str) -> tuple[int, int, bool]:
    """(runs, review runs, found) recorded AFTER the calibration's own run record.

    The calibration names the run it belongs to, so the count is positional and survives any
    number of intervening runs. When that record is no longer in the journal (it was compacted
    away after more than the kept tail of runs) `found` is False and EVERY record counts as
    "since": a calibration that old is overdue by definition, so the conservative answer is the
    safe one. Every run passes the review gate (rule `review-gate-policy`), which is why the plain
    run count is the §7 interval; the review-typed records are a subset and are reported for
    context.
    """
    index = None
    if calibration_run_id:
        for position, record in enumerate(records):
            if record.get("run_id") == calibration_run_id:
                index = position
    found = index is not None
    tail = records if index is None else records[index + 1:]
    return (len(tail),
            sum(1 for record in tail if record.get("task_type") == REVIEW_TASK_TYPE),
            found)


def parse_log(text: str) -> list[dict[str, str]]:
    """Every `calibration:` record of the log, in file order (last one = the current calibration)."""
    records: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(RECORD_PREFIX):
            continue
        fields: dict[str, str] = {}
        for token in line[len(RECORD_PREFIX):].split():
            key, sep, value = token.partition("=")
            if sep and key and key not in fields:
                fields[key.strip()] = value.strip()
        records.append(fields)
    return records


def read_log(path: pathlib.Path) -> list[dict[str, str]]:
    """The records of the calibration log; a missing log is "no calibration recorded", not an error."""
    try:
        return parse_log(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []


def calibration_status(root: pathlib.Path, log_path: pathlib.Path,
                       max_runs: int) -> dict:
    """Judge the recorded calibration against the tree: is a (re-)calibration due?

    Two triggers, both from `references/code-review.md` §7 and both computed from files on disk:
    the reviewer prompt digest changed since the recorded calibration, or `max_runs` run records
    of the journal were written after it. A log with no record is the third, honest answer: the
    obligation was never discharged, so a calibration is due.
    """
    digest = prompt_digest(root)
    records = journal_runs(root)
    total_runs, total_review_runs, _ = runs_since(records, "")
    entries = read_log(log_path)
    recorded = entries[-1] if entries else None
    reasons: list[str] = []
    runs, review_runs, found = total_runs, total_review_runs, True
    if recorded is None:
        reasons.append(f"no calibration is recorded in {log_path}: the §7 obligation has never "
                       f"been discharged in this repository")
    else:
        if recorded.get("prompt_sha256") != digest:
            reasons.append("the reviewer prompt changed since the last recorded calibration ("
                           + ", ".join(REVIEWER_PROMPT_FILES) + ") — re-calibrate after EVERY "
                           "prompt edit")
        runs, review_runs, found = runs_since(records, recorded.get("run_id", ""))
        if not found:
            # The calibration's own run record is absent from the journal. The zeroing fallback
            # is the SAME-RUN case only, proven by identity, not by count equality: the recorded
            # run_id is the ACTIVE run of `.code-factory/state/pipeline.yaml` (its memory record
            # lands at the finish gate, so it cannot be in the journal yet). Every other miss — a
            # journal compacted past the record, with or without an equal surviving count —
            # counts every surviving record conservatively: an old calibration is due, never
            # laundered into "current".
            if (recorded.get("run_id", "") and recorded.get("run_id") == active_run_id(root)
                    and recorded.get("runs", "").isdigit()
                    and int(recorded["runs"]) == total_runs):
                runs = 0
                review_runs = 0
        if runs >= max_runs:
            reasons.append(f"{runs} run(s) since the last recorded calibration (limit {max_runs})")
    return {
        "log": str(log_path),
        "log_exists": log_path.is_file(),
        "recorded": recorded,
        "prompt_sha256": digest,
        "runs_since": runs,
        "review_runs_since": review_runs,
        "run_record_found": found,
        "max_runs": max_runs,
        "reasons": reasons,
        "due": bool(reasons),
    }


def calibration_record(root: pathlib.Path, report: dict, run_id: str) -> str:
    """The one `calibration:` line `score --log` appends (paths, counts and metrics only)."""
    records = journal_runs(root)
    runs, review_runs, _ = runs_since(records, "")
    verdict = report["verdict"]
    return (f"{RECORD_PREFIX} run_id={run_id or '-'} prompt_sha256={prompt_digest(root)} "
            f"runs={runs} review_runs={review_runs} "
            f"verdict_accuracy={verdict['matched']}/{verdict['total']} "
            f"accuracy={_percent(verdict['accuracy'])} "
            f"macro_precision={report['macro']['precision']:.3f}\n")


LOG_HEADER = """\
# Reviewer calibration log — the append-only record of `references/code-review.md` §7

`calibrate_reviewer.py score --log <this file>` appends ONE `calibration:` line per calibration;
`calibrate_reviewer.py status` reads the LAST one and fails loudly when a calibration is due — the
reviewer prompt changed since it, or `5` runs were recorded since it. The line is data, not prose:

`calibration: run_id=<id|-> prompt_sha256=<64 hex> runs=<journal run count at calibration> review_runs=<review-typed subset> verdict_accuracy=<matched>/<total> accuracy=<percent> macro_precision=<0.000>`

The log is append-only: a record is never edited or removed, so the history of what the reviewer was
calibrated against stays readable. A repository with no record yet has never discharged the
obligation — `status` says so and exits 1.
"""


def append_record(log_path: pathlib.Path, line: str) -> None:
    """Append one record to the log, creating the file (and its documented header) when absent."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        write_text(log_path, LOG_HEADER + "\n")
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def cmd_status(args) -> int:
    root = pathlib.Path(args.repo).resolve() if args.repo else ROOT
    log_path = pathlib.Path(args.log) if args.log else root / LOG_REL
    if args.max_runs < 1:
        print("error: --max-runs must be at least 1", file=sys.stderr)
        return 2
    try:
        status = calibration_status(root, log_path, args.max_runs)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if status["due"]:
        print(f"FAIL - reviewer calibration is DUE ({log_path}):", file=sys.stderr)
        for reason in status["reasons"]:
            print(f"  - {reason}", file=sys.stderr)
        print("  re-calibrate: python .agents/skills/code-factory/scripts/calibrate_reviewer.py "
              "score --golden skill-base/golden-set/cases --results <results dir> "
              f"--out <report> --log {log_path}", file=sys.stderr)
        return 1

    recorded = status["recorded"] or {}
    note = "" if status["run_record_found"] else (
        " (the calibration's run record is no longer in the journal: every journal record counts)")
    print(f"PASS - reviewer calibration is current: prompt {status['prompt_sha256'][:12]}… matches "
          f"the record of run {recorded.get('run_id', '-')}, "
          f"{status['runs_since']} run(s) since (of them {status['review_runs_since']} review) — "
          f"limit {status['max_runs']}{note}.")
    return 0


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

    # Recording the calibration is OPTIONAL: `--log` appends one record so `status` can judge the
    # §7 interval; without it nothing is written and the CLI behaves exactly as before.
    if args.log:
        root = pathlib.Path(args.repo).resolve() if args.repo else ROOT
        log_path = pathlib.Path(args.log)
        try:
            append_record(log_path, calibration_record(root, report, args.run_id))
        except (OSError, InputError) as exc:
            print(f"error: cannot record the calibration in {log_path}: {exc}", file=sys.stderr)
            return 2
        print(f"calibration log: {log_path}")

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
    score.add_argument("--log", default="", metavar="PATH",
                       help="Append this calibration to the calibration log (append-only; the "
                            "record feeds `status`)")
    score.add_argument("--repo", default=None, metavar="ROOT",
                       help="Repository root the log record is computed against (default: this repo)")
    score.set_defaults(func=cmd_score)

    status = sub.add_parser("status", help="Fail loudly when a reviewer calibration is due (§7)")
    status.add_argument("--repo", default=None, metavar="ROOT",
                        help="Repository root the prompts and the memory journal resolve against "
                             "(default: this repo)")
    status.add_argument("--log", default="", metavar="PATH",
                        help=f"Calibration log (default: <repo>/{LOG_REL})")
    status.add_argument("--max-runs", type=int, default=MAX_RUNS_SINCE_CALIBRATION, metavar="N",
                        help="Runs allowed since the last recorded calibration "
                             f"(default: {MAX_RUNS_SINCE_CALIBRATION})")
    status.set_defaults(func=cmd_status)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

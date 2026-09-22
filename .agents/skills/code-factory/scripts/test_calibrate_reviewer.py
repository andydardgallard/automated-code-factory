#!/usr/bin/env python3
"""
Deterministic self-test for `calibrate_reviewer.py` and the golden set it scores (zero LLM
tokens, stdlib only).

Two halves:

1. The SHIPPED golden set (`skill-base/golden-set/`) is data, so it is checked like code: seven
   case directories with `diff.patch` + `expected.yaml`, the expected values from the calibration
   brief, every `expected.yaml` consistent with the severity/verdict policy (approve <=> no
   critical/major), and every `diff.patch` a 10-40 line unified diff whose hunk headers agree with
   their bodies.
2. The SCORER is exercised on throwaway fixtures in a temp dir: a perfect match (precision =
   recall = 1, accuracy = 1), a verdict mismatch (accuracy < 1, visible in the report) and an
   incomplete run (no result for a case -> exit 2 naming it), plus the CLI contract (report file
   with the table, deterministic output, the optional `--run-id` header line, broken input ->
   exit 2). Finally the real golden set is scored end to end against synthetic perfect results.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

import calibrate_reviewer as cr

SCRIPTS = pathlib.Path(__file__).resolve().parent
# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
ROOT = SCRIPTS.parents[3]
GOLDEN_SET = ROOT / "skill-base" / "golden-set"
GOLDEN = GOLDEN_SET / "cases"
TOOL = SCRIPTS / "calibrate_reviewer.py"

# The golden set as specified by the calibration brief: case id -> (verdict, expected severities).
GOLDEN_EXPECTED = {
    "clean-refactor": ("approve", []),
    "deleted-test": ("request_changes", ["major"]),
    "missing-error-handling": ("request_changes", ["major"]),
    "nit-naming": ("approve", []),
    "secret-in-code": ("request_changes", ["critical"]),
    "sql-injection": ("request_changes", ["critical"]),
    "weakened-check": ("request_changes", ["critical"]),
}
BLOCKING = ("critical", "major")

TINY_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def hunk_problems(text: str) -> list[str]:
    """Structural check: every hunk body carries exactly the lines its header declares."""
    lines = text.splitlines()
    problems: list[str] = []
    index = 0
    hunks = 0
    while index < len(lines):
        match = HUNK_RE.match(lines[index])
        if not match:
            index += 1
            continue
        hunks += 1
        declared_old, declared_new = int(match.group(2) or 1), int(match.group(4) or 1)
        old = new = 0
        index += 1
        while (index < len(lines) and not lines[index].startswith("@@ ")
               and not lines[index].startswith("diff --git ")):
            line = lines[index]
            if line.startswith("+"):
                new += 1
            elif line.startswith("-"):
                old += 1
            elif line.startswith(" ") or line == "":
                old += 1
                new += 1
            else:
                problems.append(f"line {index + 1}: unexpected patch line {line!r}")
            index += 1
        if (old, new) != (declared_old, declared_new):
            problems.append(f"hunk {hunks} declares -{declared_old} +{declared_new} "
                            f"but carries -{old} +{new}")
    if not hunks:
        problems.append("no @@ hunk header")
    return problems


def write_case(root: pathlib.Path, case_id: str, verdict: str, severities: list[str],
               diff: str = TINY_DIFF) -> pathlib.Path:
    """One minimal golden case on disk (the scorer only reads expected.yaml)."""
    case_dir = root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
    (case_dir / "expected.yaml").write_text(
        f"# fixture\nverdict: {verdict}\nseverities: [{', '.join(severities)}]\n",
        encoding="utf-8", newline="\n")
    return case_dir


def write_result(root: pathlib.Path, case_id: str, verdict: str, severities: list[str],
                 findings: int | None = None) -> pathlib.Path:
    """One reviewer result file in the reviewer's own JSON contract."""
    count = len(severities) if findings is None else findings
    payload = {"verdict": verdict,
               "findings": [{"severity": severities[min(i, len(severities) - 1)],
                             "file": "src/x.py", "line": 1,
                             "title": f"finding {i + 1}", "detail": "detail"}
                            for i in range(count)]}
    path = root / f"{case_id}.json"
    path.write_bytes(json.dumps(payload, indent=2).encode("utf-8"))
    return path


def expect_parsed_case(case_dir: pathlib.Path, case_id: str,
                       verdict: str, severities: list[str]) -> None:
    path = case_dir / "expected.yaml"
    expect(path.is_file(), f"{case_id}: expected.yaml is missing")
    parsed = cr.parse_expected(path.read_text(encoding="utf-8"), str(path))
    expect(parsed == {"verdict": verdict, "severities": severities},
           f"{case_id}: expected.yaml parsed as {parsed}")


def check_golden_set() -> None:
    """The shipped golden set is checked data: cases, contract values, diffs, the documented rule."""
    expect(GOLDEN.is_dir(), f"golden cases dir missing: {GOLDEN}")
    expect((GOLDEN_SET / "README.md").is_file(), "skill-base/golden-set/README.md is missing")
    readme = (GOLDEN_SET / "README.md").read_text(encoding="utf-8")
    for needle in ("diff.patch", "expected.yaml", "calibrate_reviewer.py score"):
        expect(needle in readme, f"README.md must document {needle!r}")

    found = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
    expect(found == sorted(GOLDEN_EXPECTED), f"golden cases are {found}")

    for case_id, (verdict, severities) in sorted(GOLDEN_EXPECTED.items()):
        case_dir = GOLDEN / case_id
        expect_parsed_case(case_dir, case_id, verdict, severities)
        # The golden expectation itself must obey the review-gate policy (code-review.md §3).
        blocking = [s for s in severities if s in BLOCKING]
        expect((verdict == "request_changes") == bool(blocking),
               f"{case_id}: verdict {verdict} disagrees with severities {severities}")

        diff_path = case_dir / "diff.patch"
        expect(diff_path.is_file(), f"{case_id}: diff.patch is missing")
        text = diff_path.read_text(encoding="utf-8")
        size = len(text.splitlines())
        expect(10 <= size <= 40, f"{case_id}: diff.patch must be 10-40 lines, got {size}")
        expect("--- " in text and "+++ " in text and "@@ " in text,
               f"{case_id}: diff.patch is not a unified diff")
        problems = hunk_problems(text)
        expect(not problems, f"{case_id}: diff.patch is structurally broken: {problems}")


def check_scorer_helpers() -> None:
    """The flat-YAML subset and the deterministic per-case arithmetic."""
    expect(cr.parse_expected("verdict: approve\nseverities: []\n", "t")
           == {"verdict": "approve", "severities": []}, "an empty severities list must parse")
    expect(cr.parse_expected("# c\nverdict: request_changes\nseverities: [major, critical]\n", "t")
           == {"verdict": "request_changes", "severities": ["critical", "major"]},
           "severities must be deduplicated into severity-scale order")
    for bad in ("verdict: lgtm\nseverities: []\n",              # unknown verdict
                "severities: []\n",                            # verdict missing
                "verdict: approve\nseverities: [blocker]\n",   # unknown severity
                "verdict: approve\nseverities: critical\n",    # not a bracketed list
                "verdict: approve\nseverities:\n  - critical\n"):  # nested list is not the subset
        try:
            cr.parse_expected(bad, "bad.yaml")
        except cr.InputError:
            continue
        raise AssertionError(f"parse_expected must reject {bad!r}")

    perfect = cr.score_case({"id": "a", "verdict": "approve", "severities": []},
                            {"verdict": "approve", "severities": [], "findings": 0})
    expect(perfect["verdict_match"] and perfect["precision"] == 1.0 and perfect["recall"] == 1.0,
           f"an empty expected/actual pair must be a perfect hit: {perfect}")
    mixed = cr.score_case({"id": "b", "verdict": "request_changes", "severities": ["major"]},
                         {"verdict": "request_changes", "severities": ["major", "nit"],
                          "findings": 2})
    expect(mixed["matched"] == ["major"] and mixed["extra"] == ["nit"] and mixed["missing"] == [],
           f"severity sets must compare by set membership: {mixed}")
    expect(abs(mixed["precision"] - 0.5) < 1e-9 and mixed["recall"] == 1.0,
           f"precision/recall: {mixed}")


def check_fixtures() -> None:
    """Temp-dir fixtures: perfect match, verdict mismatch, incomplete run, CLI contract."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        golden = root / "cases"
        results = root / "results"
        golden.mkdir()
        results.mkdir()
        write_case(golden, "perfect-clean", "approve", [])
        write_case(golden, "perfect-major", "request_changes", ["major"])
        write_case(golden, "mismatch", "approve", [])
        write_result(results, "perfect-clean", "approve", [])
        write_result(results, "perfect-major", "request_changes", ["major"])
        write_result(results, "mismatch", "request_changes", ["critical"])

        out = root / "nested" / "deeper" / "calibration.md"
        res = run("score", "--golden", str(golden), "--results", str(results), "--out", str(out))
        expect(res.returncode == 0, f"a complete run must exit 0: {res.stderr!r}")
        expect(out.is_file(), f"the report must be created (parents too): {out}")
        report = out.read_text(encoding="utf-8")
        expect("\r" not in report, "the report must use LF newlines")

        # 1. The perfect cases score 1 and the mismatch drags the accuracy below it.
        expect("| case |" in report and "|---|" in report, f"report needs a table: {report!r}")
        expect("verdict accuracy: 2/3 (66.7%)" in report, f"accuracy: {report!r}")
        expect("| perfect-clean | approve | approve | yes | - | - | 1.000 | 1.000 |" in report,
               f"a perfect empty case must score 1.000/1.000: {report!r}")
        expect("| mismatch | approve | request_changes | NO | - | critical | 0.000 | 1.000 |"
               in report, f"the mismatch must be visible in the table: {report!r}")
        expect("## Mismatches" in report and "`mismatch`: verdict expected `approve`" in report,
               f"the mismatch must be listed: {report!r}")
        expect("`mismatch`: unexpected severities [critical]" in report,
               f"the unexpected severity must be listed: {report!r}")
        expect("verdict accuracy: 2/3" in res.stdout and "tp=1 fp=1 fn=0" in res.stdout,
               f"the stdout summary: {res.stdout!r}")
        expect(str(out) in res.stdout, "stdout must name the report file")

        # 2. Library view: the perfect cases alone are a clean 1.0 run.
        cases = cr.load_cases(golden)
        loaded = cr.load_results(results)
        rows = {row["id"]: row for row in cr.build_report(cases, loaded, golden, results)["cases"]}
        expect(all(rows[case_id]["verdict_match"] for case_id in ("perfect-clean", "perfect-major")),
               "the perfect fixtures must match the golden verdicts")
        expect(all(rows[case_id]["precision"] == 1.0 and rows[case_id]["recall"] == 1.0
                   for case_id in ("perfect-clean", "perfect-major")),
               "the perfect fixtures must score precision = recall = 1.0")
        expect(not rows["mismatch"]["verdict_match"], "the mismatch fixture must not match")

        # 3. Determinism: the same inputs give byte-identical stdout and report bytes.
        before = out.read_bytes()
        again = run("score", "--golden", str(golden), "--results", str(results), "--out", str(out))
        expect(again.stdout == res.stdout, "stdout must be deterministic")
        expect(out.read_bytes() == before, "the report must be deterministic")

        # 4. An extra result file is reported, not scored (still exit 0).
        write_result(results, "orphan", "approve", [])
        res = run("score", "--golden", str(golden), "--results", str(results), "--out", str(out))
        expect(res.returncode == 0, f"an unmatched result must not fail the run: {res.stderr!r}")
        expect("orphan" in res.stderr, f"an unmatched result must warn: {res.stderr!r}")
        expect("## Unmatched results" in out.read_text(encoding="utf-8"),
               "the report must list unmatched results")
        (results / "orphan.json").unlink()

        # 5. Incomplete run: no result for one golden case -> exit 2 naming the missing case.
        (results / "mismatch.json").unlink()
        out_missing = root / "incomplete.md"
        res = run("score", "--golden", str(golden), "--results", str(results),
                  "--out", str(out_missing))
        expect(res.returncode == 2, f"an incomplete run must exit 2: {res.returncode}")
        expect("mismatch" in res.stderr and "incomplete" in res.stderr,
               f"stderr must list the missing case: {res.stderr!r}")
        expect(not out_missing.exists(), "an incomplete run must not write a report")
        write_result(results, "mismatch", "request_changes", ["critical"])

        # 6. Broken input -> exit 2; the offender and the problem are named.
        broken_cases = {
            "bad-verdict.yaml": ("verdict: lgtm\nseverities: []\n", "verdict must be one of"),
            "bad-severity.yaml": ("verdict: approve\nseverities: [blocker]\n", "is not one of"),
            "nested.yaml": ("verdict: approve\nseverities:\n  - critical\n",
                            "is not `key: value`"),
            "no-expected.yaml": ("", "missing expected.yaml"),
        }
        for name, (text, needle) in broken_cases.items():
            golden_dir = root / "broken-cases" / name.replace(".yaml", "")
            case_dir = golden_dir / "case-broken"
            case_dir.mkdir(parents=True, exist_ok=True)
            if text:
                (case_dir / "expected.yaml").write_text(text, encoding="utf-8", newline="\n")
            res = run("score", "--golden", str(golden_dir), "--results", str(results),
                      "--out", str(root / "broken.md"))
            expect(res.returncode == 2, f"{name}: must exit 2, got {res.returncode}")
            expect("case-broken" in res.stderr, f"{name}: stderr must name the offender: {res.stderr!r}")
            expect(needle in res.stderr, f"{name}: stderr {res.stderr!r} lacks {needle!r}")
        # A case whose name is absent from results is only one way to fail: a malformed result
        # file for a present case is the other one.
        for name, payload, needle in (
                ("bad-json.json", "{not json", "invalid JSON"),
                ("bad-verdict-result.json", json.dumps({"verdict": "lgtm", "findings": []}),
                 "verdict must be one of"),
                ("bad-severity-result.json", json.dumps(
                    {"verdict": "approve", "findings": [{"severity": "blocker"}]}),
                 "severity must be one of"),
                ("bad-findings-result.json", json.dumps({"verdict": "approve", "findings": {}}),
                 "findings must be a list")):
            (results / name).write_bytes(payload.encode("utf-8"))
            res = run("score", "--golden", str(golden), "--results", str(results),
                      "--out", str(root / "broken.md"))
            expect(res.returncode == 2, f"{name}: must exit 2, got {res.returncode}")
            expect(name in res.stderr and needle in res.stderr,
                   f"{name}: stderr {res.stderr!r} lacks {needle!r}")
            (results / name).unlink()

        # 7. The optional --run-id names the run in the report header (provenance, like
        #    verify_acceptance.py) and changes NOTHING when it is absent — the report stays
        #    byte-identical to what the tool wrote before the option existed.
        plain = root / "plain.md"
        tagged = root / "tagged.md"
        res_plain = run("score", "--golden", str(golden), "--results", str(results),
                        "--out", str(plain))
        expect(res_plain.returncode == 0, f"--run-id must not change the exit code: {res_plain.stderr!r}")
        res_tagged = run("score", "--golden", str(golden), "--results", str(results),
                         "--out", str(tagged), "--run-id", "20260922-442cd2f8")
        expect(res_tagged.returncode == 0, f"scoring with --run-id must exit 0: {res_tagged.stderr!r}")
        tagged_text = tagged.read_text(encoding="utf-8")
        expect("- run_id: 20260922-442cd2f8\n" in tagged_text,
               f"the report must carry the run id line: {tagged_text!r}")
        plain_text = plain.read_text(encoding="utf-8")
        expect("run_id" not in plain_text, "without --run-id the report must not mention a run id")
        expect(tagged_text.replace("- run_id: 20260922-442cd2f8\n", "") == plain_text,
               "the run id line must be the ONLY difference the option makes")

        # Missing dirs and a missing subcommand are usage errors, not silent success.
        res = run("score", "--golden", str(root / "nope"), "--results", str(results),
                  "--out", str(root / "broken.md"))
        expect(res.returncode == 2 and "golden dir does not exist" in res.stderr,
               f"a missing golden dir must exit 2: {res.stderr!r}")
        res = run("score", "--golden", str(golden), "--results", str(root / "nope"),
                  "--out", str(root / "broken.md"))
        expect(res.returncode == 2 and "results dir does not exist" in res.stderr,
               f"a missing results dir must exit 2: {res.stderr!r}")
        expect(run("score", "--golden", str(golden)).returncode != 0,
               "--results/--out are required")


def check_real_golden_set() -> None:
    """End to end on the shipped golden set: perfect synthetic results must score 1.0 / 100%."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        results = root / "results"
        results.mkdir()
        for case_id, (verdict, severities) in GOLDEN_EXPECTED.items():
            write_result(results, case_id, verdict, severities)
        out = root / "calibration.md"
        res = run("score", "--golden", str(GOLDEN), "--results", str(results), "--out", str(out))
        expect(res.returncode == 0, f"scoring the golden set must exit 0: {res.stderr!r}")
        report = out.read_text(encoding="utf-8")
        expect("verdict accuracy: 7/7 (100.0%)" in report, f"accuracy: {report!r}")
        expect("macro precision (severity): 1.000" in report
               and "macro recall (severity): 1.000" in report, f"macro metrics: {report!r}")
        expect("## Mismatches" not in report, f"a perfect run has no mismatches: {report!r}")
        expect(report.count("\n| ") == len(GOLDEN_EXPECTED) + 1,
               f"the table must hold a header and one row per case: {report!r}")


def main() -> int:
    check_scorer_helpers()
    check_golden_set()
    check_fixtures()
    check_real_golden_set()

    # stdlib-only contract (no third-party imports).
    src = pathlib.Path(cr.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    allowed = {"__future__", "argparse", "json", "pathlib", "sys"}
    expect(imported <= allowed, f"calibrate_reviewer must be stdlib-only, imports={imported}")

    print("PASS - calibrate_reviewer.py scores the golden set deterministically (verdict accuracy, "
          "macro precision/recall, exit 0 for data, exit 2 for incomplete runs) and the 7 shipped "
          "golden cases match the calibration brief.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Deterministic self-test for `merge_findings.py` (zero LLM tokens, stdlib only).

Builds three synthetic shard findings files in a temp dir — overlapping findings (same
file/line/title with different spacing/case and different details), several severities, a
`line: null` finding, an approve set and a request_changes set — and verifies:
  - title normalization and deduplication with sorted, unique `occurrences`,
  - the deterministic order (severity -> file -> line, null last),
  - the summary (per-severity counts, shard count) and the merged verdict rules
    (any shard request_changes OR any critical finding -> request_changes, else approve),
  - the CLI contract (JSON on stdout, --report/--md files, exit 0/1/2, broken input names the
    file and the problem),
  - determinism: every permutation of the input order yields a byte-identical report.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import re
import subprocess
import sys
import tempfile

import merge_findings as mf

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "merge_findings.py"


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write_findings(root: pathlib.Path, name: str, shard: str, verdict: str,
                   findings: list[dict]) -> pathlib.Path:
    """Write one shard findings file with exact UTF-8 bytes (LF newlines)."""
    path = root / name
    path.write_bytes(json.dumps({"shard": shard, "verdict": verdict, "findings": findings},
                                indent=2).encode("utf-8"))
    return path


def finding(severity: str, file: str, line: int | None, title: str, detail: str = "") -> dict:
    return {"severity": severity, "file": file, "line": line, "title": title, "detail": detail}


def write_raw(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.write_bytes(text.encode("utf-8"))
    return path


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def build_shards(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """shard-1 request_changes, shard-2 approve, shard-3 approve — with cross-shard duplicates."""
    one = write_findings(root, "shard-1.json", "shard-1", "request_changes", [
        finding("critical", "src/core.py", 42, "Unbounded recursion in parser", "no depth guard"),
        finding("minor", "src/util.py", None, "Typo in docstring", "docstring typo"),
    ])
    two = write_findings(root, "shard-2.json", "shard-2", "approve", [
        # Duplicate of shard-1's critical: different spacing/case, different detail.
        finding("critical", "src/core.py", 42, "  Unbounded   RECURSION in parser ", "seen too"),
        finding("major", "src/core.py", 10, "Missing timeout", "no timeout"),
        finding("minor", "src/util.py", 7, "Unused import", "import os unused"),
        finding("nit", "docs/readme.md", 3, "Trailing whitespace", "trailing spaces"),
    ])
    three = write_findings(root, "shard-3.json", "shard-3", "approve", [
        # Duplicate of shard-1's minor, duplicated again inside the same shard.
        finding("minor", "src/util.py", None, "typO in DOCSTRING", "slightly different detail"),
        finding("minor", "src/util.py", None, "TYPO   IN docstring", "third wording"),
        finding("major", "src/core.py", 5, "Missing timeout", "same title, other line"),
    ])
    return one, two, three


EXPECTED_ORDER = [
    ("critical", "src/core.py", 42),
    ("major", "src/core.py", 5),
    ("major", "src/core.py", 10),
    ("minor", "src/util.py", 7),
    ("minor", "src/util.py", None),
    ("nit", "docs/readme.md", 3),
]
EXPECTED_COUNTS = {"critical": 1, "major": 2, "minor": 2, "nit": 1}


def main() -> int:
    # 1-2. Pure helpers: title normalization and the empty input.
    expect(mf.normalize_title("  Fix   THE bug\n") == "fix the bug",
           "normalize_title must strip, collapse whitespace and lowercase")
    expect(mf.normalize_title("A\tB") == "a b", "normalize_title must collapse tabs too")
    empty = mf.merge([])
    expect(empty["verdict"] == "approve" and empty["total_shards"] == 0
           and empty["total_findings"] == 0 and empty["findings"] == [],
           f"an empty input must merge to a clean approve: {empty}")
    expect(list(empty["counts"]) == list(mf.SEVERITIES), "counts must list every severity")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        one, two, three = build_shards(root)
        inputs = [str(one), str(two), str(three)]

        # 3. Library merge of the three shards.
        report = mf.merge([mf.load_shard_file(p) for p in (one, two, three)])
        expect(report["total_shards"] == 3, f"total_shards: {report['total_shards']}")
        expect([s["shard"] for s in report["shards"]] == ["shard-1", "shard-2", "shard-3"],
               f"shards must be sorted by id: {report['shards']}")
        expect([s["verdict"] for s in report["shards"]]
               == ["request_changes", "approve", "approve"],
               f"shard verdicts must be preserved: {report['shards']}")

        # 4. Dedup + sorting.
        expect([(f["severity"], f["file"], f["line"]) for f in report["findings"]]
               == EXPECTED_ORDER, f"sorting is wrong: {report['findings']}")
        expect(report["counts"] == EXPECTED_COUNTS, f"counts: {report['counts']}")
        expect(report["total_findings"] == len(EXPECTED_ORDER),
               f"total_findings: {report['total_findings']}")

        # 5. Occurences: sorted, unique, and the deterministic record choice on duplicates.
        by_key = {(f["file"], f["line"], mf.normalize_title(f["title"])): f
                  for f in report["findings"]}
        crit = by_key[("src/core.py", 42, "unbounded recursion in parser")]
        expect(crit["occurrences"] == ["shard-1", "shard-2"],
               f"critical occurrences: {crit['occurrences']}")
        expect(crit["title"] == "Unbounded recursion in parser" and crit["detail"] == "no depth guard",
               f"the lowest shard id must win the duplicate: {crit}")
        typo = by_key[("src/util.py", None, "typo in docstring")]
        expect(typo["occurrences"] == ["shard-1", "shard-3"],
               f"occurrences must be unique per shard: {typo['occurrences']}")
        expect(typo["title"] == "Typo in docstring",
               f"duplicates must keep one title: {typo['title']}")

        # 6. Verdict rules: any request_changes shard blocks; a critical finding blocks even when
        #    every shard said approve.
        expect(report["verdict"] == "request_changes", f"verdict: {report['verdict']}")
        approve_only = mf.merge([mf.load_shard_file(two), mf.load_shard_file(three)])
        expect(approve_only["verdict"] == "request_changes",
               "a critical finding must block even without a request_changes shard")
        # The merged verdict escalates on critical findings or an explicit shard
        # request_changes only — major/minor/nit alone stay approve (the per-shard reviewer
        # decides its own verdict from its severity policy).
        major_only = mf.merge([mf.load_shard_file(write_findings(
            root, "major.json", "shard-major", "approve",
            [finding("nit", "a.py", 1, "cosmetic", ""), finding("major", "b.py", 2, "big", "")]))])
        expect(major_only["verdict"] == "approve",
               f"major/nit alone must not change the merged verdict: {major_only['verdict']}")
        expect(major_only["counts"] == {"critical": 0, "major": 1, "minor": 0, "nit": 1},
               f"major findings must still be counted: {major_only['counts']}")
        soft = mf.merge([mf.load_shard_file(write_findings(
            root, "soft.json", "shard-soft", "approve", [finding("nit", "a.py", 1, "x", "")]))])
        expect(soft["verdict"] == "approve", f"a nit-only run must approve: {soft['verdict']}")
        silent = mf.merge([mf.load_shard_file(write_findings(
            root, "silent.json", "shard-silent", "request_changes", []))])
        expect(silent["verdict"] == "request_changes",
               "a request_changes shard with no findings must still block")

        # 7. Markdown rendering: deterministic, lists severities, locations and occurrences.
        md = mf.render_markdown(report)
        expect("verdict: **request_changes**" in md, f"md verdict: {md!r}")
        expect("## critical" in md and "## nit" in md, "md must group findings by severity")
        expect("- **src/core.py:42** — Unbounded recursion in parser" in md,
               f"md location line: {md!r}")
        expect("- **src/util.py** — Typo in docstring" in md,
               "a null line must render without a line number")
        expect("occurrences: shard-1, shard-2" in md, "md must show occurrences")
        expect(md == mf.render_markdown(mf.merge(
            [mf.load_shard_file(p) for p in (three, one, two)])),
            "markdown rendering must not depend on the input order")

        # 8-10. CLI: exit 1 with request_changes, JSON on stdout, --report/--md files.
        report_path = root / "out" / "merged.json"
        md_path = root / "out" / "merged.md"
        res = run("--inputs", *inputs, "--report", str(report_path), "--md", str(md_path))
        expect(res.returncode == 1, f"request_changes must exit 1: {res.stderr!r}")
        payload = json.loads(res.stdout)
        expect(payload == report, "the CLI report must equal the library merge")
        expect(report_path.read_text(encoding="utf-8") == res.stdout,
               "--report must hold exactly the stdout JSON")
        expect(md_path.read_text(encoding="utf-8") == md, "--md must hold the markdown report")
        expect("\r" not in md_path.read_text(encoding="utf-8"),
               "the markdown report must use LF newlines")

        # 11. Approve-only input: exit 0.
        clean = write_findings(root, "clean2.json", "shard-clean", "approve", [
            finding("minor", "a.py", 1, "style", "detail")])
        res = run("--inputs", str(clean))
        expect(res.returncode == 0, f"approve must exit 0: {res.stderr!r}")
        expect(json.loads(res.stdout)["verdict"] == "approve",
               f"CLI approve payload: {res.stdout!r}")

        # 12. Determinism: every permutation of the input order -> byte-identical report.
        baseline = run("--inputs", *inputs)
        for order in itertools.permutations(inputs):
            again = run("--inputs", *order)
            expect(again.stdout == baseline.stdout and again.returncode == baseline.returncode,
                   f"the merged report must not depend on the input order: {order}")
        permuted = root / "perm.json"
        run("--inputs", *reversed(inputs), "--report", str(permuted))
        expect(permuted.read_text(encoding="utf-8") == baseline.stdout,
               "the --report file must be identical under a permuted input order")

        # 13. Broken input -> exit 2, stderr names the file and the problem.
        bad = [
            (write_raw(root, "bad-json.json", "{not json"), "invalid JSON"),
            (write_raw(root, "bad-top.json", "[1, 2]"), "top level must be a JSON object"),
            (write_raw(root, "bad-shard.json", '{"verdict": "approve", "findings": []}'),
             "shard must be a non-empty string"),
            (write_raw(root, "bad-verdict.json",
                       '{"shard": "s1", "verdict": "lgtm", "findings": []}'),
             "verdict must be one of"),
            (write_raw(root, "bad-findings.json",
                       '{"shard": "s1", "verdict": "approve", "findings": {}}'),
             "findings must be a list"),
            (write_raw(root, "bad-severity.json", json.dumps(
                {"shard": "s1", "verdict": "approve",
                 "findings": [finding("blocker", "a.py", 1, "t", "")]})),
             "severity must be one of"),
            (write_raw(root, "bad-line.json", json.dumps(
                {"shard": "s1", "verdict": "approve",
                 "findings": [finding("nit", "a.py", "42", "t", "")]})),
             "line must be an integer or null"),
            (write_raw(root, "bad-title.json", json.dumps(
                {"shard": "s1", "verdict": "approve",
                 "findings": [{"severity": "nit", "file": "a.py", "line": 1, "title": " "}]})),
             "title must be a non-empty string"),
            (write_raw(root, "bad-file.json", json.dumps(
                {"shard": "s1", "verdict": "approve",
                 "findings": [{"severity": "nit", "file": "", "line": 1, "title": "t"}]})),
             "file must be a non-empty string"),
            (write_raw(root, "bad-detail.json", json.dumps(
                {"shard": "s1", "verdict": "approve",
                 "findings": [{"severity": "nit", "file": "a.py", "line": 1, "title": "t",
                               "detail": 5}]})),
             "detail must be a string"),
            (root / "missing.json", "cannot be read"),
        ]
        for path, needle in bad:
            res = run("--inputs", str(path))
            expect(res.returncode == 2, f"{path.name} must exit 2, got {res.returncode}")
            expect(needle in res.stderr, f"{path.name}: stderr {res.stderr!r} lacks {needle!r}")
            expect(path.name in res.stderr, f"{path.name}: stderr must name the file")
        # A broken file anywhere in the list is reported, not only the first one.
        res = run("--inputs", str(one), str(root / "missing.json"))
        expect(res.returncode == 2 and "missing.json" in res.stderr,
               f"a broken later input must be reported: {res.stderr!r}")
        expect(run("--inputs").returncode == 2, "a missing --inputs must exit 2")

    # 14. stdlib-only contract (no third-party imports).
    src = pathlib.Path(mf.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    allowed = {"__future__", "argparse", "json", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"merge_findings must be stdlib-only, imports={imported}")

    print("PASS - merge_findings.py deduplicates shard findings, sorts by severity, merges the "
          "verdict deterministically (any input order) and honours the exit-code contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

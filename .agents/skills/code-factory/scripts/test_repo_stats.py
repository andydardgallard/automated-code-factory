#!/usr/bin/env python3
"""
Deterministic self-test for `repo_stats.py` (zero LLM tokens, stdlib only).

Builds a small mixed-language repository (Python, JavaScript, package.json, Cargo.toml, an
excluded .git dir) and verifies `sizes`, `entry-points` and `imports` — including the ordering
rules, the ignored directories and the MAX_TEXT_BYTES skip — plus the CLI contract.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import repo_stats as rs

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "repo_stats.py"

SRC_APP = "src/app.py"
SRC_CLI = "src/cli.py"
TOOL_MAIN = "scripts/main.py"
JS = "web/index.js"
PKG = "web/package.json"
CARGO = "Cargo.toml"
TEST_APP = "tests/test_app.py"
ALL_FILES = [CARGO, TOOL_MAIN, SRC_APP, SRC_CLI, TEST_APP, JS, PKG]   # sorted by path
TOTAL_LINES = 8 + 5 + 1 + 3 + 7 + 7 + 3


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write(root: pathlib.Path, rel: str, text: str) -> None:
    """Write exact UTF-8 bytes (write_text would translate \\n to \\r\\n on Windows)."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def build_repo(root: pathlib.Path) -> None:
    write(root, SRC_APP, "import os\nimport sys\nfrom pathlib import Path\nimport os\n"
                         "def main():\n    return 0\n"
                         "if __name__ == \"__main__\":\n    main()\n")
    write(root, SRC_CLI, "import argparse\nimport os\n\ndef main():\n    return 0\n")
    write(root, TOOL_MAIN, "print('hello')\n")
    write(root, JS, "const fs = require('fs');\nrequire(\"./helper\");\n"
                    "const helper = require('./helper');\n")
    write(root, PKG, '{\n  "name": "demo",\n  "main": "index.js",\n  "bin": {\n'
                     '    "demo": "cli.js"\n  }\n}\n')
    write(root, CARGO, '[package]\nname = "demo"\nversion = "0.1.0"\n\n[[bin]]\nname = "demo"\n'
                       'path = "src/main.rs"\n')
    write(root, TEST_APP, "import unittest\nclass T(unittest.TestCase):\n    pass\n")
    # Ignored by repo_inventory -> must never be counted anywhere.
    write(root, ".git/config", "import excluded_mod\nif __name__ == \"__main__\":\n    pass\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_repo(root)

        # 1-3. sizes: biggest first, ties broken by path, totals over every file.
        sizes = rs.sizes(root, 20)
        expect(sizes["total_files"] == len(ALL_FILES), f"total_files: {sizes['total_files']}")
        expect(sizes["total_lines"] == TOTAL_LINES, f"total_lines: {sizes['total_lines']}")
        expect([f["path"] for f in sizes["files"]] == [SRC_APP, CARGO, PKG, SRC_CLI, TEST_APP, JS,
                                                       TOOL_MAIN],
               f"unexpected ranking: {[f['path'] for f in sizes['files']]}")
        expect(sizes["files"][0]["lines"] == 8, f"lines of the biggest file: {sizes['files'][0]}")
        expect([f["path"] for f in rs.sizes(root, 2)["files"]] == [SRC_APP, CARGO],
               "--top must truncate the ranking")
        expect(rs.sizes(root, 0)["files"] == [], "--top 0 must return an empty ranking")

        # 4-5. entry-points: reasons per file, ignored .git, non-entry files absent.
        eps = rs.entry_points(root)
        expect(eps["entry_points"] == [
            {"path": CARGO, "reasons": ["Cargo [[bin]]"]},
            {"path": TOOL_MAIN, "reasons": ["filename"]},
            {"path": SRC_APP, "reasons": ["dunder-main"]},
            {"path": SRC_CLI, "reasons": ["filename", "argparse"]},
            {"path": PKG, "reasons": ["package.json"]},
        ], f"unexpected entry points: {eps['entry_points']}")
        expect(eps["total_entry_points"] == 5, f"total_entry_points: {eps}")
        expect(all(p["path"] != TEST_APP for p in eps["entry_points"]),
               "a test file must not be reported as an entry point")

        # 6-8. imports: counts across files, ordering by count then module name.
        imp = rs.imports(root, 20)
        expect(imp["imports"] == [
            {"module": "os", "count": 3},
            {"module": "./helper", "count": 2},
            {"module": "argparse", "count": 1},
            {"module": "fs", "count": 1},
            {"module": "pathlib", "count": 1},
            {"module": "sys", "count": 1},
            {"module": "unittest", "count": 1},
        ], f"unexpected imports: {imp['imports']}")
        expect(imp["total_unique"] == 7, f"total_unique: {imp['total_unique']}")
        expect(imp["total_matches"] == 10, f"total_matches: {imp['total_matches']}")
        expect(rs.imports(root, 2)["total_unique"] == 7,
               "--top must truncate the list but not the totals")
        expect([i["module"] for i in rs.imports(root, 2)["imports"]] == ["os", "./helper"],
               "--top must keep the most frequent modules")
        expect("excluded_mod" not in [i["module"] for i in imp["imports"]],
               "an excluded directory must not contribute imports")

        # 9. Determinism: two runs -> identical JSON.
        dump = lambda: json.dumps({"s": rs.sizes(root, 20), "e": rs.entry_points(root),
                                  "i": rs.imports(root, 20)}, sort_keys=True)
        expect(dump() == dump(), "the analyzers must be deterministic")

        # 10-12. CLI: JSON on stdout, exit 0 per subcommand, identical output across runs.
        for cmd in ("sizes", "entry-points", "imports"):
            res = run(cmd, "--repo", str(root))
            expect(res.returncode == 0, f"{cmd} must exit 0: {res.stderr!r}")
            expect(json.loads(res.stdout), f"{cmd} must print JSON")
        res = run("imports", "--repo", str(root), "--top", "2")
        payload = json.loads(res.stdout)
        expect([i["module"] for i in payload["imports"]] == ["os", "./helper"]
               and payload["total_unique"] == 7, f"unexpected CLI payload: {res.stdout!r}")
        expect(run("imports", "--repo", str(root), "--top", "2").stdout == res.stdout,
               "the CLI output must be byte-identical across runs")
        expect(run("sizes", "--repo", str(root / "nope")).returncode == 1,
               "a missing repo must exit 1")

    # 13. MAX_TEXT_BYTES: huge files are still counted by `sizes` but skipped by the text
    #     analyzers (entry-points / imports).
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        huge = root / "huge.txt"
        huge.write_bytes(("import huge_module\nif __name__ == \"__main__\":\n" + "x\n" * 600000)
                         .encode("utf-8"))
        expect(huge.stat().st_size > rs.MAX_TEXT_BYTES, "the fixture must exceed MAX_TEXT_BYTES")
        expect([f["path"] for f in rs.sizes(root, 5)["files"]] == ["huge.txt"],
               "sizes must still count a huge file")
        expect(rs.imports(root, 5)["imports"] == [], "text analyzers must skip a huge file")
        expect(rs.imports(root, 5)["total_unique"] == 0, "huge file must not contribute imports")
        expect(rs.entry_points(root)["total_entry_points"] == 0,
               "huge file must not be reported as an entry point")

    print("PASS - repo_stats.py reports sizes, entry points and imports deterministically "
          "(ordering, exclusions, MAX_TEXT_BYTES skip, CLI contract).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

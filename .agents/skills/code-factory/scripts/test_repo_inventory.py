#!/usr/bin/env python3
"""
Deterministic self-test for `repo_inventory.py` (zero LLM tokens, stdlib only).

Builds a synthetic repository in a temp dir (nested tree, excluded directories at several depths,
a *.pyc, a binary file, a file without a trailing newline, a unicode name, a file longer than
`--max-lines`) and verifies:
  - the walk and its exclusions, line/byte counting and path sorting,
  - determinism (two runs -> byte-identical JSON),
  - greedy shard packing (no shard above the cap, oversized file alone, no file lost/duplicated),
  - an UNREADABLE file is skipped like a binary instead of failing the whole scan, and the count
    of such files is reported as `skipped_unreadable`,
  - the CLI contract (JSON on stdout, exit 0; exit 1 for a missing repo or a bad --max-lines).

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

import repo_inventory as ri

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "repo_inventory.py"

BIG = "big.py"                 # 25 lines -> oversized for --max-lines 15
NOTES = "docs/notes.md"        # 3 lines, no trailing newline
A_PY = "src/a.py"              # 10 lines
B_PY = "src/b.py"              # 5 lines
UNI = "src/\u00fcn\u00efcode.txt"  # 2 lines, non-ASCII name
LOCKED = "locked.txt"          # 3 lines, made unreadable in the temp fixture (chmod/monkeypatch)
EXPECTED = [BIG, NOTES, A_PY, B_PY, UNI]
TOTAL_LINES = 25 + 3 + 10 + 5 + 2


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def lines(n: int, prefix: str = "line") -> str:
    return "".join(f"{prefix}{i}\n" for i in range(1, n + 1))


def write(root: pathlib.Path, rel: str, text: str) -> None:
    """Write exact UTF-8 bytes (write_text would translate \\n to \\r\\n on Windows)."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def build_repo(root: pathlib.Path) -> None:
    write(root, BIG, lines(25))
    write(root, NOTES, "l1\nl2\nl3")            # no trailing newline -> still 3 lines
    write(root, A_PY, lines(10))
    write(root, B_PY, lines(5))
    write(root, UNI, "\u00fcnicode\n\u043f\u0440\u0438\u0432\u0435\u0442\n")
    # Excluded directories, at the root and nested.
    write(root, ".git/config", lines(2))
    write(root, ".code-factory/state/task.yaml", lines(2))
    write(root, "node_modules/pkg/index.js", lines(2))
    write(root, "src/node_modules/nested.js", lines(2))
    write(root, ".venv/lib/site.py", lines(2))
    write(root, "target/debug/build", lines(2))
    write(root, "dist/bundle.js", lines(2))
    write(root, "build/out.o", lines(2))
    write(root, "__pycache__/mod.py", lines(2))
    # Excluded files: a compiled file and two binaries (NUL byte heuristic).
    write(root, "cached.pyc", lines(2))
    (root / "bin.dat").write_bytes(b"\x00\x01\x02binary\x00payload\n")
    (root / "src" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00")


def pack(records: list[tuple[str, int]], max_lines: int) -> list[dict]:
    return ri.pack_shards([{"path": p, "lines": n, "bytes": n} for p, n in records], max_lines)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_repo(root)

        # 1-2. The walk keeps exactly the text files: excluded dirs (at any depth), *.pyc and
        #      binaries are gone, and the list is sorted by repo-relative posix path.
        inv = ri.inventory(root)
        paths = [f["path"] for f in inv["files"]]
        expect(paths == EXPECTED, f"unexpected file set: {paths}")
        expect(paths == sorted(paths), "files must be sorted by path")
        expect(inv["total_files"] == len(EXPECTED), f"total_files: {inv['total_files']}")
        expect(inv["total_lines"] == TOTAL_LINES, f"total_lines: {inv['total_lines']}")

        # 3-4. Line and byte counting (trailing newline does not add a line, no trailing newline
        #      does not lose one).
        by_path = {f["path"]: f for f in inv["files"]}
        expect(by_path[A_PY]["lines"] == 10, f"{A_PY} lines: {by_path[A_PY]['lines']}")
        expect(by_path[NOTES]["lines"] == 3, f"{NOTES} lines: {by_path[NOTES]['lines']}")
        expect(by_path[UNI]["lines"] == 2, f"{UNI} lines: {by_path[UNI]['lines']}")
        expect(by_path[NOTES]["bytes"] == len("l1\nl2\nl3".encode("utf-8")),
               f"{NOTES} bytes: {by_path[NOTES]['bytes']}")
        expect(ri.count_lines(b"") == 0, "an empty file must have 0 lines")
        expect(ri.count_lines(b"a\nb\n") == 2, "a trailing newline must not add a line")
        expect(ri.count_lines(b"a\r\nb\r\n") == 2, "CRLF must count as one line break")
        expect(ri.count_lines(b"a\nb") == 2, "a missing trailing newline must not lose a line")

        # 5. Binary heuristic.
        expect(ri.is_binary(b"\x00\x01"), "a NUL byte must mark a binary file")
        expect(not ri.is_binary(b"plain text\n"), "plain text must not be binary")

        # 6. Determinism: two runs of the same tree -> identical JSON.
        first = json.dumps(ri.inventory(root), sort_keys=True)
        second = json.dumps(ri.inventory(root), sort_keys=True)
        expect(first == second, "inventory must be deterministic")
        plan_a = json.dumps(ri.shards(root, 15), sort_keys=True)
        plan_b = json.dumps(ri.shards(root, 20000), sort_keys=True)
        expect(plan_a == json.dumps(ri.shards(root, 15), sort_keys=True),
               "shards must be deterministic")
        expect(plan_b == json.dumps(ri.shards(root, 20000), sort_keys=True),
               "shards must be deterministic at the default cap")

        # 7. Greedy packing, synthetic: filling to exactly the cap is allowed.
        shards = pack([("a", 10), ("b", 5), ("c", 3)], 15)
        expect(shards == [{"id": "shard-1", "files": ["a", "b"], "lines": 15},
                          {"id": "shard-2", "files": ["c"], "lines": 3}],
               f"greedy packing is wrong: {shards}")

        # 8. A file longer than the cap gets a shard of its own, flagged oversized.
        shards = pack([("big", 20), ("small", 5)], 15)
        expect(shards == [{"id": "shard-1", "files": ["big"], "lines": 20, "oversized": True},
                          {"id": "shard-2", "files": ["small"], "lines": 5}],
               f"oversized packing is wrong: {shards}")
        expect("oversized" not in shards[1], "plain shards must not carry the oversized flag")

        # 9. Synthetic packing never exceeds the cap, never loses a file.
        shards = pack([("a", 8), ("big", 40), ("b", 7), ("c", 8)], 15)
        expect([s["lines"] for s in shards] == [8, 40, 15],
               f"unexpected shard sizes: {[s['lines'] for s in shards]}")
        expect([s["files"] for s in shards] == [["a"], ["big"], ["b", "c"]],
               f"unexpected shard contents: {[s['files'] for s in shards]}")
        try:
            ri.pack_shards([], 0)
            expect(False, "max_lines < 1 must be rejected")
        except ValueError:
            pass

        # 10. Shards of the synthetic repo (max-lines 15): oversized lone shard, then greedy.
        plan = ri.shards(root, 15)
        expect(plan["total_shards"] == len(plan["shards"]), "total_shards must match the list")
        expect(plan["shards"] == [
            {"id": "shard-1", "files": [BIG], "lines": 25, "oversized": True},
            {"id": "shard-2", "files": [NOTES, A_PY], "lines": 13},
            {"id": "shard-3", "files": [B_PY, UNI], "lines": 7},
        ], f"unexpected shard plan: {plan['shards']}")

        # 11. Invariants: every file exactly once, order preserved, lines add up, cap respected.
        packed = [p for s in plan["shards"] for p in s["files"]]
        expect(packed == EXPECTED, f"shards must cover every file once: {packed}")
        expect(sum(s["lines"] for s in plan["shards"]) == TOTAL_LINES,
               "shard lines must add up to total_lines")
        for shard in plan["shards"]:
            if not shard.get("oversized"):
                expect(shard["lines"] <= 15, f"shard above the cap: {shard}")
        # Greedy must be maximal: the next shard's first file never fits into the current one.
        for cur, nxt in zip(plan["shards"], plan["shards"][1:]):
            if not cur.get("oversized") and not nxt.get("oversized"):
                first = by_path[nxt["files"][0]]["lines"]
                expect(cur["lines"] + first > 15,
                       f"packing is not greedy: {cur} + {first} lines would fit")

        # 12. A cap equal to the longest file: one plain (non-oversized) shard per group.
        plan = ri.shards(root, 25)
        expect([s["files"] for s in plan["shards"]] == [[BIG], [NOTES, A_PY, B_PY, UNI]],
               f"unexpected plan at cap 25: {plan['shards']}")
        expect("oversized" not in plan["shards"][0], "a file equal to the cap is not oversized")

        # 13. The default cap packs the whole fixture into a single shard.
        plan = ri.shards(root, 20000)
        expect(plan["total_shards"] == 1, f"default cap must give 1 shard: {plan['total_shards']}")
        expect(plan["shards"][0]["files"] == EXPECTED, "the single shard must list every file")

        # 14. An empty directory: no files, no shards, exit 0.
        empty = pathlib.Path(td + "_empty")
        empty.mkdir()
        try:
            expect(ri.inventory(empty)["total_files"] == 0, "an empty repo must have 0 files")
            expect(ri.shards(empty, 20000) == {"shards": [], "total_shards": 0},
                   "an empty repo must have 0 shards")
        finally:
            empty.rmdir()

    # 15-17. CLI contract.
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_repo(root)

        res = run("inventory", "--repo", str(root))
        expect(res.returncode == 0, f"inventory must exit 0: {res.stderr!r}")
        payload = json.loads(res.stdout)
        expect(payload["total_files"] == len(EXPECTED) and payload["total_lines"] == TOTAL_LINES,
               f"unexpected inventory payload: {res.stdout!r}")
        expect([f["path"] for f in payload["files"]] == EXPECTED,
               "CLI inventory must list the same sorted files")

        res = run("shards", "--repo", str(root), "--max-lines", "15")
        expect(res.returncode == 0, f"shards must exit 0: {res.stderr!r}")
        payload = json.loads(res.stdout)
        expect(payload["total_shards"] == 3 and payload["shards"][0]["oversized"] is True,
               f"unexpected shards payload: {res.stdout!r}")

        # Determinism of the CLI itself (byte-identical stdout across runs).
        again = run("shards", "--repo", str(root), "--max-lines", "15")
        expect(again.stdout == res.stdout, "the CLI output must be byte-identical across runs")

        expect(run("shards", "--repo", str(root), "--max-lines", "0").returncode == 1,
               "--max-lines 0 must exit 1")
        expect(run("inventory", "--repo", str(root / "does-not-exist")).returncode == 1,
               "a missing repo must exit 1")

    # 15. An UNREADABLE file is skipped instead of failing the whole scan, and is counted.
    #     POSIX: chmod 000 really denies the read. Windows has no such bit (and root ignores it),
    #     so there `read_bytes` is made to fail for exactly that one file — the policy under test
    #     (OSError -> skip + count) is the same either way.
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_repo(root)
        write(root, LOCKED, lines(3))
        locked = root / LOCKED
        original_read_bytes = pathlib.Path.read_bytes
        try:
            locked.chmod(0o000)
            try:
                locked.read_bytes()
                os_denies = False          # Windows / root: the permission bit decides nothing
            except OSError:
                os_denies = True
            if not os_denies:
                def deny_one(self: pathlib.Path) -> bytes:
                    if self.name == LOCKED:
                        raise PermissionError(13, "Permission denied", str(self))
                    return original_read_bytes(self)

                pathlib.Path.read_bytes = deny_one
            inv = ri.inventory(root)
            expect(inv["skipped_unreadable"] == 1,
                   f"the unreadable file must be counted: {inv.get('skipped_unreadable')}")
            expect([f["path"] for f in inv["files"]] == EXPECTED,
                   f"the unreadable file must stay out of the inventory: {inv['files']}")
            expect(inv["total_files"] == len(EXPECTED) and inv["total_lines"] == TOTAL_LINES,
                   f"the rest of the scan must be untouched: {inv}")
            # `shards` walks the same tree: the unreadable file is skipped there too, no crash.
            expect(ri.shards(root, 20000)["shards"][0]["files"] == EXPECTED,
                   "shards must survive an unreadable file")
        finally:
            pathlib.Path.read_bytes = original_read_bytes
            locked.chmod(0o600)             # Windows: drop the read-only bit before cleanup
        if os_denies:
            res = run("inventory", "--repo", str(root))
            expect(res.returncode == 0 and json.loads(res.stdout)["skipped_unreadable"] == 1,
                   f"the CLI must report skipped_unreadable: {res.stdout!r} {res.stderr!r}")

    # 16. stdlib-only contract (no third-party imports).
    src = pathlib.Path(ri.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    allowed = {"__future__", "argparse", "json", "pathlib", "sys"}
    expect(imported <= allowed, f"repo_inventory must be stdlib-only, imports={imported}")

    print("PASS - repo_inventory.py walks, counts, sorts, packs shards and stays deterministic "
          "(exclusions, oversized shards, unreadable files skipped and counted, CLI contract, "
          "stdlib only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

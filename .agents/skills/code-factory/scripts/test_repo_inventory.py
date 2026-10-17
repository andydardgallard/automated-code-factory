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
  - the CLI contract (JSON on stdout, exit 0; exit 1 for a missing repo or a bad --max-lines),
  - the `--tracked` mode (inventory AND shards) against a REAL temp repository: the file set is the
    NUL-safe tracked set (`git ls-files -z`), so an untracked machine-local config, an untracked
    credentials file and an ignored directory never enter the inventory, while the flag-less walk
    still sees them; counting/filtering are identical in both modes; the NUL-safety of the parsing is
    proven on a stubbed git call with names a Windows fixture cannot hold; and `--tracked` fails with
    an explicit non-zero exit (no silent fallback to the walk) when git is missing or the path is not
    a repository.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import repo_inventory as ri

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "repo_inventory.py"
# A commit identity per command: the test never depends on the machine's git config and a globally
# enabled commit signing cannot hang the fixture commit.
GIT_IDENTITY = ("-c", "commit.gpgsign=false", "-c", "user.name=Factory Test",
                "-c", "user.email=factory@example.invalid")

BIG = "big.py"                 # 25 lines -> oversized for --max-lines 15
NOTES = "docs/notes.md"        # 3 lines, no trailing newline
A_PY = "src/a.py"              # 10 lines
B_PY = "src/b.py"              # 5 lines
UNI = "src/\u00fcn\u00efcode.txt"  # 2 lines, non-ASCII name
LOCKED = "locked.txt"          # 3 lines, made unreadable in the temp fixture (chmod/monkeypatch)
EXPECTED = [BIG, NOTES, A_PY, B_PY, UNI]
TOTAL_LINES = 25 + 3 + 10 + 5 + 2

# The `--tracked` fixture: a real repository whose tracked set is deliberately SMALLER than what a
# walk of the same directory finds (untracked + ignored paths) and larger than what the walk
# accepts (a tracked binary, a tracked *.pyc). A non-ASCII name is deliberately NOT part of this
# fixture: git-for-Windows passes non-ASCII filenames through the ANSI code page, so the stored name
# depends on the host locale — the NUL-safety of the parsing is proven by a stubbed git call below.
TRACKED_PY = "src/tracked.py"                 # 4 lines
TRACKED_SPACE = "docs/with space.md"          # 2 lines, no trailing newline, a space in the name
TRACKED_BIN = "assets/logo.bin"               # tracked, binary (NUL) -> filtered like the walk
TRACKED_PYC = "stale.pyc"                     # tracked, *.pyc -> filtered like the walk
UNTRACKED_SECRET = "machine.config.local"     # machine-local config, never committed
UNTRACKED_ENV = ".env.local"                  # untracked credentials
IGNORED_DIR = "ignored-dir"
IGNORED_FILE = f"{IGNORED_DIR}/private.notes.txt"
GITIGNORE = ".gitignore"
TRACKED_FIXTURE = [TRACKED_PY, TRACKED_SPACE, TRACKED_BIN, TRACKED_PYC]
TRACKED_TEXT = sorted([TRACKED_PY, TRACKED_SPACE])
TRACKED_TOTAL_LINES = 4 + 2
# A tracked name with a NEWLINE inside it (legal in git, impossible to create on Windows) and a
# non-ASCII name: line-separated parsing would split the first and quote/mangle the second.
NUL_NAME_NEWLINE = "docs/new\nline.md"
NUL_NAME_UNI = "src/\u00fcn\u00efcode.txt"
# Present in the walk, never in a tracked inventory: filtered content, untracked and ignored paths.
OUTSIDE_TRACKED = [TRACKED_BIN, TRACKED_PYC, UNTRACKED_SECRET, UNTRACKED_ENV, IGNORED_FILE]


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


def run_env(env: dict, *args: str) -> subprocess.CompletedProcess[str]:
    """The CLI with an explicit environment (used to pin git's repository discovery)."""
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", env=env)


def run_without_git(cmd: str, repo: pathlib.Path, tracked: bool = True) -> subprocess.CompletedProcess[str]:
    """The CLI as if the git executable were missing — the portable way to simulate that.

    `repo_inventory.main()` runs in-process with `subprocess.run` replaced by a raiser, so the
    missing-git branch is exercised exactly where the tool invokes git: no PATH juggling and no
    dependency on what the host happens to have installed, while the exit code and stderr asserted
    below are still the real CLI contract.
    """
    argv = ["repo_inventory.py", cmd, "--repo", str(repo)] + (["--tracked"] if tracked else [])
    code = ("import sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "import repo_inventory as ri\n"
            "def boom(*args, **kwargs):\n"
            "    raise FileNotFoundError(2, 'No such file or directory', 'git')\n"
            "ri.subprocess.run = boom\n"
            f"sys.argv = {argv!r}\n"
            "raise SystemExit(ri.main())\n")
    return subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, errors="replace")


def git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`git -C <repo> <args>` — every repository this test touches is its own temp fixture."""
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, errors="replace")


def git_ok(repo: pathlib.Path, *args: str) -> str:
    res = git(repo, *args)
    expect(res.returncode == 0, f"git -C {repo} {' '.join(args)} must succeed: {res.stderr!r}")
    return res.stdout


def remove_tree(path: pathlib.Path, attempts: int = 3) -> None:
    """Best-effort removal: git writes its objects read-only and Windows may hold a file briefly."""
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    try:
                        os.chmod(pathlib.Path(root) / name, stat.S_IWRITE)
                    except OSError:
                        pass
            if attempt < attempts:
                time.sleep(0.5)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        print(f"WARNING - could not remove the temporary tracked-mode fixture {path}")


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


def build_git_repo(root: pathlib.Path) -> None:
    """A REAL repository: tracked text files, a tracked binary and *.pyc, an untracked machine-local
    config, an untracked credentials file and an IGNORED directory (the last three exist on disk but
    stay outside the tracked set — exactly the paths a review must not see).
    """
    write(root, TRACKED_PY, lines(4))
    write(root, TRACKED_SPACE, "intro\noutro")           # no trailing newline -> still 2 lines
    write(root, TRACKED_PYC, lines(2))
    asset = root / TRACKED_BIN
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x00binary\x00tracked\n")
    write(root, UNTRACKED_SECRET, "API_KEY=do-not-ship\n")
    write(root, UNTRACKED_ENV, "TOKEN=local-only\n")
    write(root, IGNORED_FILE, lines(2))
    write(root, GITIGNORE, f"{IGNORED_DIR}/\n")
    git_ok(root, "init", "-q")
    # Only the intended set enters the index: the untracked config and credentials and the ignored
    # directory stay out of it. `docs` and `assets` are added as DIRECTORIES so that the
    # space-containing name is discovered by git itself rather than passed as an argument.
    for rel in ("src", "docs", "assets", TRACKED_PYC):
        git_ok(root, "add", "--", rel)
    git_ok(root, *GIT_IDENTITY, "commit", "-q", "-m", "tracked-mode fixture")


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

    # 16. --tracked: the file set is the TRACKED set (`git ls-files -z`, NUL-safe) — not the
    #     filesystem walk. A review/audit of "the repository" must not be able to see a machine-local
    #     config or an ignored scratch directory that happens to sit in the working tree.
    expect(shutil.which("git") is not None, "git must be on PATH: --tracked is defined by git")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="repo-inventory-tracked-"))
    try:
        root = tmp / "repo"
        root.mkdir()
        build_git_repo(root)
        listed = sorted(p for p in git_ok(root, "ls-files", "-z").split("\0") if p)
        expect(listed == sorted(TRACKED_FIXTURE), f"fixture: unexpected tracked set {listed}")
        for rel in (UNTRACKED_SECRET, UNTRACKED_ENV, IGNORED_FILE):
            expect((root / rel).is_file(), f"fixture: {rel} must exist on disk")

        inv = ri.inventory(root, tracked=True)
        paths = [f["path"] for f in inv["files"]]
        expect(paths == TRACKED_TEXT,
               f"--tracked must list exactly the tracked text files: {paths} != {TRACKED_TEXT}")
        expect(inv["total_files"] == len(TRACKED_TEXT) and inv["total_lines"] == TRACKED_TOTAL_LINES,
               f"unexpected tracked totals: {inv['total_files']}/{inv['total_lines']}")
        for rel in OUTSIDE_TRACKED:
            expect(rel not in paths, f"{rel} must never enter a tracked inventory: {paths}")
        # Equality with an INDEPENDENT restatement: raw `git ls-files -z` output, split on NULs and
        # filtered by the documented content rules (the filter is the walk's, the set is git's).
        expected_from_git = [rel for rel in listed
                             if rel != TRACKED_PYC
                             and not (root / rel).is_symlink()
                             and b"\x00" not in (root / rel).read_bytes()[:ri.BINARY_SNIFF_BYTES]]
        expect(paths == sorted(expected_from_git),
               f"--tracked must equal the NUL-safe tracked set: {paths} != {expected_from_git}")

        # 17. Counting is IDENTICAL to the walk: the same file yields the same record in both modes,
        #     and the flag-less walk still sees the untracked and ignored paths (escape hatch).
        by_path = {f["path"]: f for f in inv["files"]}
        expect(by_path[TRACKED_SPACE]["lines"] == 2,
               f"a file without a trailing newline must count 2: {by_path[TRACKED_SPACE]}")
        expect(by_path[TRACKED_SPACE]["bytes"] == (root / TRACKED_SPACE).stat().st_size,
               f"unexpected tracked record: {by_path[TRACKED_SPACE]}")
        expect(by_path[TRACKED_PY]["lines"] == 4
               and by_path[TRACKED_PY]["bytes"] == (root / TRACKED_PY).stat().st_size,
               f"unexpected tracked record: {by_path[TRACKED_PY]}")
        walk = {f["path"]: f for f in ri.inventory(root)["files"]}
        expect(all(walk[rel] == record for rel, record in by_path.items()),
               "tracked mode must count exactly like the walk")
        for rel in (UNTRACKED_SECRET, UNTRACKED_ENV, IGNORED_FILE, GITIGNORE):
            expect(rel in walk, f"without --tracked the walk must still see {rel}")

        # 18. Determinism, and the tracked shard plan: same records, same packing, no file lost.
        expect(json.dumps(ri.inventory(root, tracked=True), sort_keys=True)
               == json.dumps(ri.inventory(root, tracked=True), sort_keys=True),
               "the tracked inventory must be deterministic")
        plan = ri.shards(root, 20000, tracked=True)
        expect([s["files"] for s in plan["shards"]] == [TRACKED_TEXT],
               f"the default cap must give one tracked shard: {plan}")
        packed = ri.pack_shards(inv["files"], 4)
        expect(ri.shards(root, 4, tracked=True) == {"shards": packed, "total_shards": len(packed)},
               "tracked shards must pack exactly the tracked records")
        expect(sum(len(s["files"]) for s in packed) == len(TRACKED_TEXT),
               f"every tracked file must appear in exactly one shard: {packed}")

        # 19. The NUL-safety of the tracked set, proven directly: git writes names RAW and
        #     NUL-separated, so a name containing a newline arrives as ONE name (a line-based parse
        #     would split it) and a non-ASCII name is neither quoted nor mangled. A Windows fixture
        #     cannot hold such names, so the git call itself is stubbed with exactly the bytes git
        #     would print.
        raw = f"{NUL_NAME_NEWLINE}\0{NUL_NAME_UNI}\0".encode("utf-8")
        original_run = ri.subprocess.run
        try:
            ri.subprocess.run = lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=raw)
            names = ri.git_ls_files(root)
            expect(names == [NUL_NAME_NEWLINE, NUL_NAME_UNI],
                   f"the tracked set must be parsed NUL-safely: {names}")
        finally:
            ri.subprocess.run = original_run

        # 20. The CLI contract of --tracked: exit 0, the tracked set (inventory AND shards), stable
        #     output — and the flag alone decides the file set.
        res = run("inventory", "--repo", str(root), "--tracked")
        expect(res.returncode == 0, f"inventory --tracked must exit 0: {res.stderr!r}")
        payload = json.loads(res.stdout)
        expect([f["path"] for f in payload["files"]] == TRACKED_TEXT,
               f"CLI --tracked must list the tracked set: {res.stdout!r}")
        expect(payload["total_lines"] == TRACKED_TOTAL_LINES and payload["skipped_unreadable"] == 0,
               f"unexpected --tracked payload: {res.stdout!r}")
        walk_paths = [f["path"]
                      for f in json.loads(run("inventory", "--repo", str(root)).stdout)["files"]]
        expect(UNTRACKED_SECRET in walk_paths
               and UNTRACKED_SECRET not in [f["path"] for f in payload["files"]],
               "the flag alone must decide which file set is inventoried")

        res = run("shards", "--repo", str(root), "--tracked", "--max-lines", "4")
        expect(res.returncode == 0, f"shards --tracked must exit 0: {res.stderr!r}")
        again = run("shards", "--repo", str(root), "--tracked", "--max-lines", "4")
        expect(res.stdout == again.stdout, "tracked shard output must be byte-identical across runs")
        shard_payload = json.loads(res.stdout)
        expect(json.dumps(shard_payload, sort_keys=True)
               == json.dumps(ri.shards(root, 4, tracked=True), sort_keys=True),
               f"CLI shards --tracked must match the module: {res.stdout!r}")
        for rel in OUTSIDE_TRACKED:
            expect(all(rel not in s["files"] for s in shard_payload["shards"]),
                   f"{rel} must never enter a tracked shard: {shard_payload}")

        # 21. --tracked is NEVER a silent fallback. Outside a repository the CLI exits non-zero with
        #     a reason on stderr and no JSON; the module raises a named error; and the flag-less walk
        #     keeps working without git at all (that escape hatch is untouched).
        plain = tmp / "plain"                    # a directory that is not a repository
        plain.mkdir()
        write(plain, UNTRACKED_SECRET, "API_KEY=do-not-ship\n")
        # Pin git's discovery so a repository ABOVE the temp directory can never answer instead.
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(plain.parent))
        precondition = subprocess.run(["git", "-C", str(plain), "rev-parse", "--git-dir"],
                                      capture_output=True, text=True, env=env)
        expect(precondition.returncode != 0,
               f"fixture precondition: {plain} must not be inside a repository: {precondition.stdout!r}")
        for cmd, extra in (("inventory", ()), ("shards", ("--max-lines", "10"))):
            res = run_env(env, cmd, "--repo", str(plain), "--tracked", *extra)
            expect(res.returncode == 1,
                   f"{cmd} --tracked outside a repository must exit 1: {res.returncode} {res.stdout!r}")
            expect(res.stdout.strip() == "",
                   f"a failed --tracked must print no inventory: {res.stdout!r}")
            expect("Traceback" not in res.stderr and "git" in res.stderr.lower(),
                   f"{cmd} --tracked outside a repository must name the reason: {res.stderr!r}")
        try:
            ri.inventory(plain, tracked=True)
            expect(False, "tracked mode outside a repository must raise")
        except ri.TrackedUnavailable as exc:
            expect("git" in str(exc).lower(), f"the failure reason must name git: {exc}")
        res = run_env(env, "inventory", "--repo", str(plain))
        expect(res.returncode == 0
               and [f["path"] for f in json.loads(res.stdout)["files"]] == [UNTRACKED_SECRET],
               f"without --tracked the walk must still work without git: {res.stdout!r} {res.stderr!r}")

        # 22. A MISSING git executable: same explicit failure for both commands, and the flag-less
        #     walk keeps working (it never consults git).
        for cmd in ("inventory", "shards"):
            res = run_without_git(cmd, root)
            expect(res.returncode == 1,
                   f"{cmd} --tracked without the git executable must exit 1: {res.stderr!r}")
            expect(res.stdout.strip() == "",
                   f"{cmd} --tracked without git must print no JSON: {res.stdout!r}")
            expect("Traceback" not in res.stderr and "git" in res.stderr.lower(),
                   f"{cmd} --tracked without git must name the reason: {res.stderr!r}")
        res = run_without_git("inventory", root, tracked=False)
        expect(res.returncode == 0
               and [f["path"] for f in json.loads(res.stdout)["files"]] == sorted(walk_paths),
               f"the walk must not need git at all: {res.stdout!r} {res.stderr!r}")
    finally:
        remove_tree(tmp)

    # 23. stdlib-only contract (no third-party imports).
    src = pathlib.Path(ri.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    # `subprocess` (stdlib) carries the single `git ls-files -z` call of --tracked.
    allowed = {"__future__", "argparse", "json", "pathlib", "subprocess", "sys"}
    expect(imported <= allowed, f"repo_inventory must be stdlib-only, imports={imported}")
    if hasattr(sys, "stdlib_module_names"):      # Python 3.10+: the whitelist is verified, not trusted
        expect(imported <= set(sys.stdlib_module_names),
               f"every import must come from the stdlib: {imported - set(sys.stdlib_module_names)}")

    print("PASS - repo_inventory.py walks, counts, sorts, packs shards and stays deterministic "
          "(exclusions, oversized shards, unreadable files skipped and counted, CLI contract, "
          "stdlib only), and its --tracked mode inventories exactly the NUL-safe `git ls-files` "
          "tracked set, never an untracked or ignored path, failing explicitly when git cannot "
          "answer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

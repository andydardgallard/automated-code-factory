#!/usr/bin/env python3
"""
Deterministic self-test for `precedent_index.py` (zero LLM tokens, stdlib only).

A throwaway project tree is indexed — `memory/change-log.md` with three `## ` records,
`memory/summary.md`, two Python modules, plus the four things that must stay OUT of the index
(a binary file, a file over 200 KiB, `.code-factory/` runtime state and `skill-base/golden-set/`
calibration data) — and every claimed property is checked: records per source, the `## `
splitting, one unique marker per source found there and nowhere else, an FTS5 operator query with
`--limit`, `--out`, a rebuild that reproduces the same rows in the same order, the git scan and
the directory walk agreeing on the same records (a tracked symbolic link included: git lists it
while the walk skips it, so the index must skip it in BOTH modes), and the CLI contract (`--help`,
a missing argument, a missing/corrupt database, a broken MATCH expression and `--limit 0` all
answer with a message, never a traceback).

Creating a symbolic link needs privileges on Windows (Administrator or Developer Mode): when the OS
refuses, the test prints a note and skips only that sub-check instead of failing.

If this interpreter's sqlite3 was built without FTS5 the tool cannot exist at all, so the test
prints SKIP and exits 0 instead of failing on an environment it does not control.

Exit code 0 = all assertions pass (or SKIP), 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import precedent_index as pi

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "precedent_index.py"

CHANGE_LOG = """# Журнал прогонов

Формат записи: `## <timestamp> — <title>`, признак проекта — `project: <имя>`.

## 2026-09-22T10:00:00+03:00 — Калибровка ревьюера на golden-set
project: demo
alphamarker: verdict accuracy 7/7, macro precision 0.619 / recall 0.857.
Метрики считает calibrate_reviewer.py по диффам golden-set.

## 2026-09-23T00:19:00+03:00 — Сквозной run_id в артефактах
project: demo
run_id = YYYYMMDD-<sha256(task.yaml)[:8]> проставляется в pipeline.yaml и acceptance.md.

## 2026-09-24T09:00:00+03:00 — Вакцинация: тест до фикса
project: demo
Баг после приёмки сначала получает воспроизводящий регрессионный тест, и только потом фикс.
"""

SUMMARY = """project: demo
repo_path: .

## Возможности
Собран FTS5-индекс памяти и кодовой базы (betamarker).

## Незакрытое
Остался committee при двойном rejection плана.
"""

MODULE_ALPHA = '''"""Demo module for the index self-test (gammamarker)."""


def doubled(value: int) -> int:
    """Return twice the value."""
    return value * 2
'''

MODULE_BETA = '''"""Second demo module: no marker of its own."""

BETA = 2
'''

# marker -> (the one source that must carry it, sources that must NOT appear in its output)
POSITIVE = (("alphamarker", "memory/change-log.md", ("memory/summary.md", "module_alpha.py")),
            ("betamarker", "memory/summary.md", ("memory/change-log.md", "module_alpha.py")),
            ("gammamarker", "pkg/module_alpha.py", ("memory/change-log.md", "module_beta.py")))
# marker -> why it must be invisible (it only lives in something the index excludes)
NEGATIVE = (("deltamarker", "the binary file"),
            ("hugemarker", "the file over the size cap"),
            ("stateleakmarker", ".code-factory/ state"),
            ("goldenleakmarker", "skill-base/golden-set/"),
            ("quokkaxylophone", "text that is nowhere in the tree"))

EXPECTED_SOURCES = {"change-log": 4, "summary": 3, "code": 2}  # 2 preambles + 3 + 2 + 2 modules
EXPECTED_RECORDS = 9
EXPECTED_PATHS = {"memory/change-log.md", "memory/summary.md",
                  "pkg/module_alpha.py", "pkg/module_beta.py"}
# A tracked symbolic link planted in the fixture: `git ls-files` lists it as a tracked path and its
# target exists, so `is_file()` would happily follow it — while the shard-protocol walk skips
# symbolic links. The index must skip it in BOTH modes, or `git scan == walk` breaks on one tree.
SYMLINK_NAME = "alias_alpha.py"
SYMLINK_REL = "pkg/" + SYMLINK_NAME


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def counter(text: str, key: str) -> str:
    """The first whitespace-separated token after `key: ` (record counters carry a breakdown)."""
    for line in text.splitlines():
        if line.startswith(key + ": "):
            return line.split(": ", 1)[1].split(" ", 1)[0]
    raise AssertionError(f"missing counter {key!r} in output: {text!r}")


def write(path: pathlib.Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def rows(db: pathlib.Path) -> list[tuple[str, str, str, str]]:
    """Every indexed row in insertion order (rowid), read straight from the database."""
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT source, path, title, content FROM {pi.TABLE} "
                            "ORDER BY rowid").fetchall()
    finally:
        conn.close()


def table_sql(db: pathlib.Path) -> str:
    """The CREATE statement of the index table (empty when it is absent)."""
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (pi.TABLE,)).fetchone()
    finally:
        conn.close()
    return "" if row is None else row[0]


def write_fixture(root: pathlib.Path) -> None:
    """The throwaway project: memory, code, and the four things that must stay out of the index."""
    (root / "memory").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "skill-base" / "golden-set" / "cases").mkdir(parents=True)
    (root / ".code-factory" / "state").mkdir(parents=True)
    write(root / "memory" / "change-log.md", CHANGE_LOG)
    write(root / "memory" / "summary.md", SUMMARY)
    write(root / "pkg" / "module_alpha.py", MODULE_ALPHA)
    write(root / "pkg" / "module_beta.py", MODULE_BETA)
    write(root / ".code-factory" / "state" / "notes.md", "# state\nstateleakmarker\n")
    write(root / "skill-base" / "golden-set" / "cases" / "leak.md", "# golden\ngoldenleakmarker\n")
    (root / "pkg" / "blob.bin").write_bytes(b"\x00\x01deltamarker\x00binary\x01\x00payload")
    write(root / "pkg" / "huge.py", "# hugemarker\n" + "padding = 1  # padding padding\n" * 9000)


def maybe_git_init(root: pathlib.Path) -> bool:
    """Put the fixture under git when git is available, so `git ls-files` is exercised too.

    Both scan modes must yield the very same records (asserted below); without git the build
    falls back to the directory walk and the assertions hold just the same.
    """
    if shutil.which("git") is None:
        return False
    init = subprocess.run(["git", "init", "-q", str(root)], capture_output=True)
    add = subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    return init.returncode == 0 and add.returncode == 0


def maybe_symlink(root: pathlib.Path) -> bool:
    """Plant a symbolic link in the fixture; False when this OS/user cannot create one.

    The link points at an existing text file, so `is_file()` follows it and the git scan would
    index it — while the shard-protocol walk skips symbolic links, which is exactly the divergence
    the index must not have. Creating a symbolic link needs a privilege on Windows (Administrator or
    Developer Mode), so an OSError only skips this sub-check, it never fails the run.
    """
    link = root / SYMLINK_REL
    try:
        link.symlink_to("module_alpha.py")  # relative: resolves to pkg/module_alpha.py
    except (OSError, NotImplementedError):
        return False
    return True


def check_library() -> None:
    """The `## ` splitting and the file filter — rules the CLI alone cannot pin down."""
    expect(pi.split_sections("no headings here\n") == [(None, "no headings here")],
           "text without headings is one preamble block")
    expect(pi.split_sections("## A\nbody\n") == [("A", "body")],
           "an empty preamble is not a record")
    expect(pi.split_sections("## A\none\n\n## B\ntwo\n") == [("A", "one"), ("B", "two")],
           "every `## ` heading starts a record")

    records = pi.section_records("memory/summary.md", SUMMARY, "summary")
    expect([record[2] for record in records] == ["(preamble)", "Возможности", "Незакрытое"],
           f"summary sections: {[record[2] for record in records]}")
    expect(records[0][3].startswith("project: demo"),
           "the preamble record keeps the declared project")
    expect(records[1][3].startswith("## Возможности"),
           "a section record's content carries its heading, so a title-only match still shows it")

    with tempfile.TemporaryDirectory() as td:
        probe = pathlib.Path(td) / "pkg"
        probe.mkdir()
        write(probe / "text.py", "x = 1\n")
        (probe / "blob.bin").write_bytes(b"\x00\x01binary\x00")
        write(probe / "huge.py", "padding\n" * 30000)
        expect(pi.read_text(probe / "text.py") == "x = 1\n", "a text file is read")
        expect(pi.read_text(probe / "blob.bin") is None, "a binary file is skipped")
        expect(pi.read_text(probe / "huge.py") is None, "a file over 200 KiB is skipped")
        expect(pi.read_text(probe / "missing.py") is None, "an unreadable file is skipped")
        expect(pi.read_text(probe / "huge.py", max_bytes=None) is not None,
               "the memory files are exempt from the size cap")

        # The file filter itself: a symbolic link is NOT code, even though `is_file()` follows it
        # (and the target really exists) — this is the unit-level half of the git-vs-walk invariant.
        link = probe / "alias.py"
        try:
            link.symlink_to("text.py")
        except (OSError, NotImplementedError):
            print("note - this OS/user cannot create a symbolic link; the symlink filter of "
                  "indexable_code_paths is covered by the fixture sub-check only.")
        else:
            expect(pi.indexable_code_paths(pathlib.Path(td), ["pkg/alias.py", "pkg/text.py"])
                   == ["pkg/text.py"],
                   "a symbolic link must never be indexed as code (is_file() would follow it)")


def check_cli(root: pathlib.Path, db: pathlib.Path) -> None:
    """The usage contract: every misuse is a message and exit 2, never a traceback."""
    res = run("--help")
    expect(res.returncode == 0, f"--help must exit 0: {res.stderr!r}")
    expect("usage" in res.stdout.lower(), f"--help must print usage: {res.stdout!r}")
    expect("Traceback" not in res.stderr, f"--help must not traceback: {res.stderr!r}")

    for args, needle in ((("build", "--repo", str(root / "nope")), "not a directory"),
                         (("query", "--repo", str(root), "alphamarker", "--limit", "0"),
                          "--limit must be >= 1"),
                         (("query", "--repo", str(root), "("), "invalid FTS5 MATCH expression"),
                         (("query", "--repo", str(root), ""), "empty"),
                         (("build", "--repo", str(root), "--bogus"), "usage:")):
        res = run(*args)
        expect(res.returncode == 2, f"{args}: must exit 2, got {res.returncode}")
        expect(needle in res.stderr, f"{args}: stderr {res.stderr!r} lacks {needle!r}")
        expect("Traceback" not in res.stderr, f"{args}: must not traceback: {res.stderr!r}")

    for args in ((), ("build",), ("query", "--repo", str(root)), ("query", str(root))):
        res = run(*args)
        expect(res.returncode == 2, f"missing arguments {args}: must exit 2")
        expect("usage:" in res.stderr and "Traceback" not in res.stderr,
               f"missing arguments {args}: {res.stderr!r}")

    # A query on a repository with no index must say so and must NOT create one.
    with tempfile.TemporaryDirectory() as other:
        fresh = pathlib.Path(other)
        res = run("query", "--repo", str(fresh), "anything")
        expect(res.returncode == 2 and "not found" in res.stderr,
               f"a missing index must exit 2: {res.stderr!r}")
        expect(not (fresh / ".code-factory").exists(), "a query must never create an index")
        (fresh / ".code-factory" / "state").mkdir(parents=True)
        (fresh / ".code-factory" / "state" / pi.DEFAULT_DB.name).write_bytes(b"not a database")
        res = run("query", "--repo", str(fresh), "anything")
        expect(res.returncode == 2 and "Traceback" not in res.stderr,
               f"a corrupt index must exit 2 cleanly: {res.stderr!r}")

    expect(db.is_file(), "the CLI checks must not disturb the index they query")


def main() -> int:
    # 0. Without FTS5 the tool cannot exist: report SKIP instead of failing on the environment.
    unsupported = pi.fts5_error()
    if unsupported is not None:
        print(f"SKIP - sqlite3 in {sys.executable} has no FTS5 ({unsupported}); "
              f"precedent_index.py cannot be exercised here.")
        return 0

    check_library()

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        write_fixture(root)
        symlink_made = maybe_symlink(root)  # before `git add`, so the link is a TRACKED path
        if not symlink_made:
            print("note - this OS/user cannot create a symbolic link (Windows needs Administrator or "
                  "Developer Mode); the tracked-symlink sub-check is skipped.")
        under_git = maybe_git_init(root)
        db = root / pi.DEFAULT_DB

        # 1. build writes the index to the documented default path and reports what went in.
        res = run("build", "--repo", str(root))
        expect(res.returncode == 0, f"build must exit 0: {res.stderr!r}")
        expect("Traceback" not in res.stderr, f"a build must not traceback: {res.stderr!r}")
        expect(db.is_file(), f"build must write {db}")
        expect(counter(res.stdout, "records") == str(EXPECTED_RECORDS),
               f"record count: {res.stdout!r}")
        counts = re.search(r"change-log: (\d+), summary: (\d+), code: (\d+)", res.stdout)
        expect(counts is not None, f"the per-source counts must be reported: {res.stdout!r}")
        expect([int(value) for value in counts.groups()]
               == [EXPECTED_SOURCES[source] for source in pi.SOURCES],
               f"per-source counts: {res.stdout!r}")
        expect(("git ls-files" in res.stdout) == under_git,
               f"the scan mode must be reported: {res.stdout!r}")

        # 2. The table is an FTS5 virtual table with the four documented columns.
        schema = table_sql(db)
        expect(schema.startswith("CREATE VIRTUAL TABLE"), f"schema: {schema!r}")
        expect("USING fts5" in schema, f"schema must be FTS5: {schema!r}")
        expect(all(column in schema for column in pi.COLUMNS), f"schema columns: {schema!r}")

        # 3. The `## ` splitting is the documented one: preamble + one record per heading.
        indexed = rows(db)
        titles = [row[2] for row in indexed if row[0] == "change-log"]
        expect(titles[0] == "(preamble)", f"the first change-log record is the preamble: {titles}")
        expect(any(title.endswith("Калибровка ревьюера на golden-set") for title in titles),
               f"every `## ` heading becomes a record title: {titles}")
        expect(len(titles) == EXPECTED_SOURCES["change-log"], f"change-log records: {titles}")

        # 4. Nothing that must stay out got in.
        paths = {row[1] for row in indexed}
        expect(paths == EXPECTED_PATHS, f"indexed paths: {sorted(paths)}")
        expect(all(row[2] for row in indexed), "every record carries a title")
        #    A symbolic link whose target exists is followed by `is_file()` and listed by
        #    `git ls-files`, so it is the one thing that could make the git scan and the walk
        #    disagree — the index must skip it (sub-check skipped when the link cannot be created).
        if symlink_made:
            expect(SYMLINK_REL not in paths,
                   f"a tracked symbolic link must not be indexed as code: {sorted(paths)}")
            expect(pi.indexable_code_paths(root, [SYMLINK_REL]) == [],
                   "the file filter must drop a symbolic link even when its target exists")

        # 5. Each marker is found in exactly its own source and in no other one.
        for marker, path, others in POSITIVE:
            res = run("query", "--repo", str(root), marker)
            expect(res.returncode == 0, f"query {marker}: {res.stderr!r}")
            expect(counter(res.stdout, "matches") == "1", f"{marker} must hit once: {res.stdout!r}")
            expect(path in res.stdout, f"{marker} must name {path}: {res.stdout!r}")
            expect(f"[{marker}]" in res.stdout,
                   f"the snippet must bracket {marker}: {res.stdout!r}")
            for other in others:
                expect(other not in res.stdout,
                       f"{marker} must not surface {other}: {res.stdout!r}")

        # 6. The excluded material stays invisible: a binary file, an oversized file, runtime
        #    state and calibration data are never precedents.
        for marker, reason in NEGATIVE:
            res = run("query", "--repo", str(root), marker)
            expect(res.returncode == 0, f"query {marker}: {res.stderr!r}")
            expect(counter(res.stdout, "matches") == "0",
                   f"{marker} lives only in {reason} and must not be indexed: {res.stdout!r}")

        # 7. Raw FTS5 syntax works and --limit truncates the hit list.
        res = run("query", "--repo", str(root), "betamarker OR gammamarker")
        expect(res.returncode == 0 and counter(res.stdout, "matches") == "2",
               f"an OR query must hit both records: {res.stdout!r}")
        res = run("query", "--repo", str(root), "betamarker OR gammamarker", "--limit", "1")
        expect(counter(res.stdout, "matches") == "1" and res.stdout.count("\n#") == 1,
               f"--limit 1 must truncate to one hit: {res.stdout!r}")

        # 8. Rebuild determinism: the same working tree gives the same rows in the same order.
        before = rows(db)
        expect(len(before) == EXPECTED_RECORDS, f"indexed rows: {len(before)}")
        res = run("build", "--repo", str(root))
        expect(res.returncode == 0, f"a rebuild must exit 0: {res.stderr!r}")
        expect(counter(res.stdout, "records") == str(EXPECTED_RECORDS),
               f"a rebuild must re-index the same records: {res.stdout!r}")
        expect(rows(db) == before, "a rebuild must reproduce the same rows in the same order")

        # 9. The git listing and the directory walk agree record for record — including for the
        #    tracked symbolic link, which only the git listing knows about (-z listing, no follow).
        git_records, git_mode = pi.collect_records(root)
        original_git_files = pi.git_files
        pi.git_files = lambda path: None  # force the fallback the CLI documents
        try:
            walked_records, walk_mode = pi.collect_records(root)
        finally:
            pi.git_files = original_git_files
        expect(git_mode == ("git" if under_git else "walk"), f"scan mode: {git_mode}")
        expect(walk_mode == "walk", f"forced scan mode: {walk_mode}")
        expect(walked_records == git_records,
               "the git scan and the directory walk must yield identical records")
        if symlink_made and under_git:
            expect(SYMLINK_REL in pi.git_files(root),
                   "the fixture link must be a TRACKED path, or this invariant proves nothing")

        # 10. --out (relative to the repo root) is honoured by build and by query.
        custom = root / "custom" / "idx.db"
        res = run("build", "--repo", str(root), "--out", "custom/idx.db")
        expect(res.returncode == 0 and custom.is_file(), f"--out build: {res.stderr!r}")
        expect(str(custom) in res.stdout, f"--out must name the database it wrote: {res.stdout!r}")
        res = run("query", "--repo", str(root), "alphamarker", "--out", "custom/idx.db")
        expect(res.returncode == 0 and "memory/change-log.md" in res.stdout,
               f"--out query must read the custom index: {res.stderr!r}")

        check_cli(root, db)

    # 11. stdlib-only contract (`repo_inventory` is the sibling script shared with the shard
    #     protocol: one implementation of the walk and the binary heuristic).
    source = pathlib.Path(pi.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", source, flags=re.M))
    allowed = {"__future__", "argparse", "hashlib", "pathlib", "repo_inventory", "sqlite3",
               "subprocess", "sys"}
    expect(imported <= allowed, f"precedent_index.py must be stdlib-only, imports={imported}")

    print("PASS - precedent_index.py builds a deterministic FTS5 precedent index of memory/ and "
          "the code base (git ls-files or walk — a tracked symbolic link skipped by both), finds "
          "each marker in exactly its own source, and answers every misuse with a message and "
          "exit 2 instead of a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

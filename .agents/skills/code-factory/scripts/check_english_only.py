#!/usr/bin/env python3
"""
Deterministic proof that no Cyrillic is left in the tracked files of a repository and in the
memory records that are NEW by the documented predicate (stdlib only, zero LLM tokens).

The repository lives under an English-only rule: code, comments, messages and test output that
ship must be English, while a few carriers may legitimately keep another language — the
append-only `CHANGELOG.md` (older entries were written in that language and are never rewritten),
the long-term memory of the target project (`memory/`), the business task file (`task*.yaml`) and
the factory runtime state (`.code-factory/`). This script checks the rule with a command instead of
by reading everything: it scans exactly what the repository ships (`git ls-files`; untracked scratch
files are out of scope, as in `project_fingerprint.py`) and prints every line that still carries a
Cyrillic letter as `<path>:<lineno>: <line>`.

The MEMORY PASS runs by default and closes the hole `memory/` used to be: the exemption belongs to
HISTORY ("history is never rewritten"), not to a record written today. `memory/change-log.md` is
therefore parsed into records by the sibling helper (`memory_project.journal_blocks`, imported —
never re-implemented), and only the records that are NEW by the same documented predicate
(`memory_project.is_v2_record`) are scanned, each over its own line range (`start`..`end`). A record
whose heading is listed in `memory/.english-freeze` is history the owner accepted verbatim and stays
silent. `memory/summary.md` is scanned WHOLE: every run rewrites it, so it holds no frozen history and
nothing else may go unchecked. The pass prints
`memory: N v2 record(s) + summary scanned, M hit(s)` and its hits join the SAME FAIL verdict as the
generic pass.

`--freeze` (re)writes `memory/.english-freeze` from the CURRENT journal — a one-line header comment
plus one record heading per v2 record that still carries Cyrillic — and exits. That file is the
committed freeze on history: it is written once, for records that already exist, and never grows on
its own. A Cyrillic NEW record therefore still fails the gate.

Usage:
  python check_english_only.py --root .
  python check_english_only.py --root . --exclude "assets/*.md"
  python check_english_only.py --root . --freeze     # (re)write memory/.english-freeze, then exit
  python check_english_only.py --root . --no-memory  # deliberate escape: skip the memory pass

A pattern excludes a path when it equals a path prefix (`memory/` also covers `memory/x.md`, and
`CHANGELOG.md` covers that exact file), or when it fnmatch-matches the whole path or its basename
(`task*.yaml` catches `task.yaml` wherever it lives). `--exclude` narrows the GENERIC pass only: the
memory pass reads the journal directly, so the rule cannot be silenced behind a pattern. `--no-memory`
is the ONE documented opt-out — a deliberate escape, never a default: it disables the memory pass (the
journal records AND the summary) and says so on stderr. A repository with no `memory/` at all is a
note and exit 0 (there is nothing to scan), while an INTERNAL reason the memory pass cannot run — an
unimportable `memory_project`, an unparsable journal, an unreadable memory file — is an
INFRASTRUCTURE error: `FAIL - the memory pass could not run: <reason>`, exit 3, never a false
"clean". A file whose bytes are not UTF-8 (binary blob) or that cannot be read is skipped, and the
count of skipped files is printed on stderr at the end, never hidden: "clean" must not be able to
mean "nothing was readable".
Exit codes: 0 — no Cyrillic outside the exceptions, 1 — hits found (every one printed), 2 — argument
error (argparse), 3 — infrastructure error (no git, `--root` is not a repository, the memory pass
could not run for an internal reason, `--freeze` with no journal or an unwritable freeze file), which
is never reported as clean.
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import re
import subprocess
import sys

# The sibling memory helper owns the record parser AND the "new record" predicate; importing both
# keeps ONE definition of a v2 record (a local copy would drift away from the ownership gate). An
# unimportable sibling degrades the memory pass to a note — it must never crash the whole gate.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import memory_project  # noqa: E402  (needs the sys.path line above)
except Exception as exc:  # noqa: BLE001 - any import failure means "no memory pass", not a crash
    memory_project = None
    MEMORY_IMPORT_ERROR = f"cannot import memory_project: {exc}"
else:
    MEMORY_IMPORT_ERROR = ""

# The Cyrillic block (U+0400-U+04FF: CYRILLIC CAPITAL/SMALL LETTER A..YA, IO, i.e. the whole
# block, not just the two common ranges) written with `\u` escapes on purpose — the source of this
# checker is itself a tracked file that the checker scans, so it must not contain a Cyrillic
# literal.
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
DEFAULT_EXCLUDES = ("CHANGELOG.md", "memory/", "task*.yaml", ".code-factory/", ".git/")
MAX_LINE = 120
MEMORY_DIR = "memory"
MEMORY_JOURNAL = "change-log.md"
MEMORY_REL = f"{MEMORY_DIR}/{MEMORY_JOURNAL}"
# The summary is rewritten by EVERY run, so it is memory that is NEW by construction: it gets no
# v2-record predicate and no freeze — the whole file is scanned (it is English by contract).
MEMORY_SUMMARY = "summary.md"
MEMORY_SUMMARY_REL = f"{MEMORY_DIR}/{MEMORY_SUMMARY}"
FREEZE_NAME = ".english-freeze"
FREEZE_HEADER = ("# Frozen memory records - history kept verbatim; "
                 "`check_english_only.py --freeze` rewrites this list.\n")


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


def tracked_files(root: pathlib.Path) -> list[str]:
    """Tracked paths (relative, POSIX, sorted) from `git ls-files -z`.

    `-z` keeps git from C-quoting non-ASCII paths. Raises RuntimeError when git cannot answer —
    no git on PATH or `root` is not a repository: an empty listing would print as a clean scan,
    the exact silent pass this script exists to prevent.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"git exit {proc.returncode}"
        raise RuntimeError(f"git ls-files failed in {root}: {detail}")
    return sorted(path for path in proc.stdout.decode("utf-8", "replace").split("\0") if path)


def is_excluded(path: str, patterns: tuple[str, ...]) -> bool:
    """True when a tracked path matches an exception pattern (path prefix or fnmatch)."""
    basename = path.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.rstrip("/")
        if not pattern:
            continue
        if path == pattern or path.startswith(pattern + "/"):
            return True
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def scan_file(root: pathlib.Path, rel: str) -> tuple[list[tuple[int, str]], bool]:
    """Cyrillic hits of one tracked file as `(lineno, line)`, plus `skipped`.

    A file that cannot be read or whose bytes are not UTF-8 is skipped (`skipped=True`, no hits):
    a binary blob has no language, and pretending to have scanned it would be a false proof.
    """
    try:
        raw = (root / rel).read_bytes()
    except OSError:
        return [], True
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [], True
    hits = [(lineno, line.strip()[:MAX_LINE])
            for lineno, line in enumerate(text.splitlines(), 1)
            if CYRILLIC.search(line)]
    return hits, False


def journal_path(root: pathlib.Path) -> pathlib.Path:
    """The journal of the target project's long-term memory (`memory/change-log.md`)."""
    return root / MEMORY_DIR / MEMORY_JOURNAL


def summary_path(root: pathlib.Path) -> pathlib.Path:
    """The summary of the target project's long-term memory (`memory/summary.md`)."""
    return root / MEMORY_DIR / MEMORY_SUMMARY


def freeze_path(root: pathlib.Path) -> pathlib.Path:
    """The committed freeze on history (`memory/.english-freeze`)."""
    return root / MEMORY_DIR / FREEZE_NAME


def read_freeze(path: pathlib.Path) -> set[str]:
    """Frozen record headings; an absent or unreadable file freezes nothing.

    A line is an entry when it is a record heading (`## ...`); every other non-blank line is a
    comment, so the one-line header can explain the file without being mistaken for a record.
    """
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {line.strip() for line in text.splitlines() if line.strip().startswith("## ")}


def record_hits(lines: list[str], record: dict) -> list[tuple[int, str]]:
    """Cyrillic hits of ONE record, inside its own line range (`start`..`end`, 1-based)."""
    first = max(record["start"], 1)
    last = min(record["end"], len(lines))
    return [(lineno, lines[lineno - 1].strip()[:MAX_LINE])
            for lineno in range(first, last + 1)
            if CYRILLIC.search(lines[lineno - 1])]


def memory_scan(root: pathlib.Path) -> tuple[int, list[tuple[str, int, str]], str, bool]:
    """Scan the NEW memory records AND memory/summary.md: `(records scanned, hits, reason, infra)`.

    In scope for the journal: a record that is v2 by `memory_project.is_v2_record` AND whose
    heading is not frozen. A pre-v2 record and a frozen heading are history — never rewritten,
    therefore never scanned. `memory/summary.md` is scanned WHOLE: the summary is rewritten by every
    run, so there is no history in it to freeze, and skipping it let a fresh Cyrillic paragraph pass.

    `infra` is True when the pass could not run for an INTERNAL reason — `memory_project` cannot be
    imported, the journal cannot be parsed, a file cannot be read — and the caller then exits 3 with
    `reason`. A repository without `memory/` is NOT such a reason: there is nothing to scan, and the
    note says so. A memory/ with no journal is the same kind of empty pass: the summary (if any) is
    still scanned.
    """
    if memory_project is None:
        return 0, [], MEMORY_IMPORT_ERROR, True
    if not (root / MEMORY_DIR).is_dir():
        return 0, [], (f"memory pass skipped: no {MEMORY_DIR}/ in this repository "
                       f"(nothing to scan)"), False
    journal = journal_path(root)
    records: list[dict] = []
    if journal.is_file():
        try:
            records = memory_project.journal_blocks(journal)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return 0, [], f"cannot parse {MEMORY_REL}: {exc}", True
    scanned = 0
    hits: list[tuple[str, int, str]] = []
    if records:
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            return 0, [], f"cannot read {MEMORY_REL}: {exc}", True
        frozen = read_freeze(freeze_path(root))
        for record in records:
            if not memory_project.is_v2_record(record["fields"]):
                continue
            if record["heading"].strip() in frozen:
                continue
            scanned += 1
            hits.extend((MEMORY_REL, lineno, line) for lineno, line in record_hits(lines, record))
    summary = summary_path(root)
    if summary.is_file():
        found, was_skipped = scan_file(root, MEMORY_SUMMARY_REL)
        if was_skipped:
            return 0, [], f"cannot read {MEMORY_SUMMARY_REL} (not UTF-8 or unreadable)", True
        hits.extend((MEMORY_SUMMARY_REL, lineno, line) for lineno, line in found)
    return scanned, hits, "", False


def freeze_history(root: pathlib.Path) -> int:
    """(Re)write `memory/.english-freeze` from the CURRENT journal and report what was frozen.

    Only v2 records that already hold Cyrillic are listed: the file records a decision about the
    past, so it must be written once and read afterwards — a new Cyrillic record is not covered.
    """
    if memory_project is None:
        print(f"error: cannot freeze: {MEMORY_IMPORT_ERROR}", file=sys.stderr)
        return 3
    journal = journal_path(root)
    if not journal.is_file():
        print(f"error: cannot freeze: no {MEMORY_REL}", file=sys.stderr)
        return 3
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
        records = memory_project.journal_blocks(journal)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: cannot freeze: cannot parse {MEMORY_REL}: {exc}", file=sys.stderr)
        return 3
    frozen: list[str] = []
    for record in records:
        heading = record["heading"].strip()
        if heading in frozen:
            continue
        if memory_project.is_v2_record(record["fields"]) and record_hits(lines, record):
            frozen.append(heading)
    target = freeze_path(root)
    try:
        target.write_text(FREEZE_HEADER + "".join(h + "\n" for h in frozen), encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {MEMORY_DIR}/{FREEZE_NAME}: {exc}", file=sys.stderr)
        return 3
    print(f"froze {len(frozen)} memory record(s) into {MEMORY_DIR}/{FREEZE_NAME}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root)
    try:
        files = tracked_files(root)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    patterns = tuple(DEFAULT_EXCLUDES) + tuple(args.exclude or [])
    hits: list[tuple[str, int, str]] = []
    scanned = 0
    skipped = 0
    for rel in files:
        if is_excluded(rel, patterns):
            continue
        found, was_skipped = scan_file(root, rel)
        if was_skipped:
            skipped += 1
            continue
        scanned += 1
        hits.extend((rel, lineno, line) for lineno, line in found)
    memory_scanned = 0
    memory_hits: list[tuple[str, int, str]] = []
    note = ""
    infra = False
    if args.no_memory:
        note = "memory pass disabled by --no-memory (deliberate escape)"
    else:
        memory_scanned, memory_hits, note, infra = memory_scan(root)
        hits.extend(memory_hits)
    if hits:
        for rel, lineno, line in hits:
            print(f"{rel}:{lineno}: {line}")
    if infra:
        # An internal reason to skip the memory pass is an INFRASTRUCTURE error, exactly like "not
        # a git repository": the run must never print the language proof it could not make.
        print(f"FAIL - the memory pass could not run: {note}", file=sys.stderr)
        return 3
    if not note:
        print(f"memory: {memory_scanned} v2 record(s) + summary scanned, {len(memory_hits)} hit(s)")
    if note:
        # A pass that did not run prints no count at all: "0 hit(s)" would read as a clean proof.
        print(f"note: {note}", file=sys.stderr)
    if hits:
        files_with_hits = len({rel for rel, _, _ in hits})
        print(f"FAIL - {len(hits)} cyrillic line(s) in {files_with_hits} file(s)", file=sys.stderr)
    else:
        print(f"ok - no cyrillic outside exceptions (scanned {scanned} files)")
    if skipped:
        print(f"note: skipped {skipped} binary/unreadable file(s)", file=sys.stderr)
    return 1 if hits else 0


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".",
                    help="Repository to scan (default: the current directory)")
    ap.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                    help="Extra exception (path prefix or fnmatch); repeatable")
    ap.add_argument("--no-memory", action="store_true",
                    help="Skip the memory pass (deliberate escape: memory records go unchecked)")
    ap.add_argument("--freeze", action="store_true",
                    help="(Re)write memory/.english-freeze from the current journal, then exit")
    args = ap.parse_args()
    if args.freeze:
        return freeze_history(pathlib.Path(args.root))
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

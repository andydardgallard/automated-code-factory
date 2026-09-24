#!/usr/bin/env python3
"""
Deterministic proof that no Cyrillic is left in the tracked files of a repository (stdlib only,
zero LLM tokens).

The repository lives under an English-only rule: code, comments, messages and test output that
ship must be English, while a few carriers may legitimately keep another language — the
append-only `CHANGELOG.md` (older entries were written in that language and are never rewritten),
the long-term memory of the target project (`memory/`), the business task file (`task*.yaml`) and
the factory runtime state (`.code-factory/`). This script checks the rule with a command instead of
by reading everything: it scans exactly what the repository ships (`git ls-files`; untracked scratch
files are out of scope, as in `project_fingerprint.py`) and prints every line that still carries a
Cyrillic letter as `<path>:<lineno>: <line>`.

Usage:
  python check_english_only.py --root .
  python check_english_only.py --root . --exclude "assets/*.md"

A pattern excludes a path when it equals a path prefix (`memory/` also covers `memory/x.md`, and
`CHANGELOG.md` covers that exact file), or when it fnmatch-matches the whole path or its basename
(`task*.yaml` catches `task.yaml` wherever it lives). A file whose bytes are not UTF-8 (binary
blob) or that cannot be read is skipped, and the count of skipped files is printed on stderr at the
end, never hidden: "clean" must not be able to mean "nothing was readable". Exit codes: 0 — no
Cyrillic outside the exceptions, 1 — hits found (every one printed), 2 — argument error
(argparse), 3 — infrastructure error (no git, `--root` is not a repository), which is never
reported as clean.
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import re
import subprocess
import sys

# The Cyrillic block (U+0400-U+04FF: CYRILLIC CAPITAL/SMALL LETTER A..YA, IO, i.e. the whole
# block, not just the two common ranges) written with `\u` escapes on purpose — the source of this
# checker is itself a tracked file that the checker scans, so it must not contain a Cyrillic
# literal.
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
DEFAULT_EXCLUDES = ("CHANGELOG.md", "memory/", "task*.yaml", ".code-factory/", ".git/")
MAX_LINE = 120


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
    if hits:
        for rel, lineno, line in hits:
            print(f"{rel}:{lineno}: {line}")
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
    args = ap.parse_args()
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

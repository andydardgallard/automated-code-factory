#!/usr/bin/env python3
r"""
Deterministic proof that a translation changed only text, not structure (stdlib only, zero LLM
tokens).

A translation rewrites prose. The skeleton around that prose — headings, list items, code fences,
factory-rule markers, mermaid arrows, function and class definitions, CLI arguments, raised errors
and printed messages — must come out of the translation unchanged: same counts, same order-neutral
skeleton, only the words differ. This script compares every file that differs from a git base
(`git diff --name-only <base> --`; the old side comes from `git show <base>:<path>`, the new side
from the worktree) by counting those markers on both sides and printing each difference as
`<path>: <marker> old=N new=M`, so "the translation kept the structure" is a command, not an
opinion.

Usage:
  python check_translation_structure.py --root .
  python check_translation_structure.py --root . --base HEAD~3

Markers are counted per extension:
  - `.md` (per line): headings (`^#{1,6}\s`), unordered list items (`^\s*[-*]\s`), ordered list
    items (`^\s*\d+\.\s`), code fences (a line whose content starts with three backticks),
    factory-rule markers (`<!-- factory-rule:`)
    and arrows (`-->`, the mermaid edges and the closing half of an HTML comment);
  - `.py` (per occurrence): `def`/`async def`, `class`, `.add_argument(`, `raise`, `print(`;
  - `.yaml`/`.yml`/`.sh`/`.ps1`/`.cmd` (per line): non-empty lines and `#` comment lines — the two
    things a translated script or config cannot legitimately change;
  - any other extension carries no skeleton, so such a changed file is skipped and counted on
    stderr instead of being silently compared against nothing.

New files (absent at the base) are skipped with a note — there is nothing to compare them with;
deleted files are listed and fail the check, because a translation never removes a file. Files
that are not UTF-8 are compared on replaced characters and counted on stderr. Exit codes: 0 —
every compared file matches (`ok - ...`), 1 — a mismatch or a deleted file, 2 — argument error
(argparse), 3 — infrastructure error (no git, `--root` is not a repository, unknown `--base`),
which is never reported as "preserved".

A run that DELIBERATELY adds a new rule declares it with `--allow-added-rule <id>` (repeatable):
the marker lines and the `## <id>` heading of that rule are stripped from BOTH sides before
counting, so the intentional addition is neutralized without weakening the gate for anything
else — without the flag, an added rule block still fails the check.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

MD_SUFFIXES = frozenset({".md"})
PY_SUFFIXES = frozenset({".py"})
TEXT_SUFFIXES = frozenset({".yaml", ".yml", ".sh", ".ps1", ".cmd"})

# Markdown: counted per line — a heading, a fence or an arrow line is one structural element
# whatever it wraps. `-->` also closes an HTML comment, which is why it doubles as the mermaid
# edge counter (as the brief prescribes).
MD_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("headings", re.compile(r"^#{1,6}\s")),
    ("list_items", re.compile(r"^\s*[-*]\s")),
    ("ordered_items", re.compile(r"^\s*\d+\.\s")),
    ("code_fences", re.compile(r"^\s*```")),
    ("factory_rules", re.compile(r"<!--\s*factory-rule:")),
    ("arrows", re.compile(r"-->")),
)
# Python: counted per occurrence — `raise` and `print(` can appear twice on one line.
PY_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("defs", re.compile(r"^\s*(?:async\s+)?def\s", re.MULTILINE)),
    ("classes", re.compile(r"^\s*class\s", re.MULTILINE)),
    ("arguments", re.compile(r"\.add_argument\(")),
    ("raises", re.compile(r"raise\s")),
    ("prints", re.compile(r"print\(")),
)
COMMENT = re.compile(r"^\s*#")


def strip_allowed_rule(path: str, text: str, rule_ids: tuple[str, ...]) -> str:
    """Drop the marker lines and the `## <id>` heading of deliberately added rules.

    Applied to BOTH sides of the comparison, so a rule added on purpose (declared via
    `--allow-added-rule`) is neutralized instead of weakening the gate for everything else.
    """
    if not rule_ids or family(path) != "md":
        return text
    patterns = tuple(
        (re.compile(r"<!--\s*factory-rule:\s*" + re.escape(rid) + r"\s+(?:begin|end)\s*-->"),
         re.compile(r"#{1,6}\s+" + re.escape(rid) + r"\s*$"))
        for rid in rule_ids
    )
    return "\n".join(line for line in text.splitlines()
                     if not any(marker.search(line) or heading.fullmatch(line)
                                for marker, heading in patterns))


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


def run_git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run one git command in `root`; raises RuntimeError when git itself cannot be started."""
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}") from exc


def changed_files(root: pathlib.Path, base: str) -> list[str]:
    """Paths that differ from `base` (worktree side), sorted, from `git diff --name-only -z`.

    `-z` keeps git from C-quoting non-ASCII paths. Raises RuntimeError when git cannot answer —
    no git on PATH, `root` is not a repository, `base` is not a revision: an empty listing would
    print as "structure preserved", the exact silent pass this script exists to prevent.
    """
    proc = run_git(root, "diff", "--name-only", "-z", base, "--")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"git exit {proc.returncode}"
        raise RuntimeError(f"git diff {base} failed in {root}: {detail}")
    return sorted(path for path in proc.stdout.decode("utf-8", "replace").split("\0") if path)


def base_content(root: pathlib.Path, base: str, path: str) -> bytes | None:
    """Bytes of `path` at `base`, or None when the file does not exist there (a new file)."""
    proc = run_git(root, "show", f"{base}:{path}")
    return proc.stdout if proc.returncode == 0 else None


def decode(raw: bytes) -> tuple[str, bool]:
    """Decode UTF-8; `lossy=True` when the bytes are not UTF-8, so a file that could not really
    be read is counted on stderr instead of being compared on replaced characters in silence."""
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), True


def family(path: str) -> str | None:
    """Skeleton family of a path from its extension: "md", "py", "text" or None (no skeleton)."""
    suffix = pathlib.PurePosixPath(path).suffix.lower()
    if suffix in MD_SUFFIXES:
        return "md"
    if suffix in PY_SUFFIXES:
        return "py"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return None


def marker_counts(path: str, text: str) -> dict[str, int]:
    """Marker counts of one side of the comparison; empty when the extension has no skeleton."""
    kind = family(path)
    if kind is None:
        return {}
    lines = text.splitlines()
    if kind == "md":
        return {name: sum(1 for line in lines if pattern.search(line))
                for name, pattern in MD_MARKERS}
    if kind == "py":
        return {name: len(pattern.findall(text)) for name, pattern in PY_MARKERS}
    return {"non_empty_lines": sum(1 for line in lines if line.strip()),
            "comment_lines": sum(1 for line in lines if COMMENT.search(line))}


def print_notes(notes: dict[str, int], base: str) -> None:
    """Report what was NOT compared, on stderr: skipping must never look like a match."""
    if notes["new"]:
        print(f"note: skipped {notes['new']} new file(s) (absent at {base})", file=sys.stderr)
    if notes["unsupported"]:
        print(f"note: skipped {notes['unsupported']} changed file(s) of a type without a skeleton",
              file=sys.stderr)
    if notes["excluded"]:
        print(f"note: skipped {notes['excluded']} excluded file(s) (declared --exclude)",
              file=sys.stderr)
    if notes["lossy"]:
        print(f"note: {notes['lossy']} file(s) are not UTF-8 (compared on replaced characters)",
              file=sys.stderr)


def excluded(path: str, patterns: tuple[str, ...]) -> bool:
    """True when `path` falls under a declared --exclude (prefix or fnmatch on path/basename)."""
    import fnmatch
    name = pathlib.PurePosixPath(path).name
    return any(path.startswith(pat) or fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(name, pat)
               for pat in patterns)


def cmd_check(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root)
    try:
        changed = changed_files(root, args.base)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    mismatches: list[str] = []
    deleted: list[str] = []
    notes = {"new": 0, "unsupported": 0, "lossy": 0, "excluded": 0}
    compared = 0
    for path in changed:
        if excluded(path, tuple(args.exclude)):
            notes["excluded"] += 1
            continue
        if family(path) is None:
            notes["unsupported"] += 1
            continue
        old_raw = base_content(root, args.base, path)
        if old_raw is None:
            notes["new"] += 1
            continue
        new_path = root / path
        if not new_path.is_file():
            deleted.append(path)
            continue
        try:
            new_raw = new_path.read_bytes()
        except OSError as exc:
            print(f"error: cannot read {new_path}: {exc}", file=sys.stderr)
            return 3
        old_text, old_lossy = decode(old_raw)
        new_text, new_lossy = decode(new_raw)
        if old_lossy or new_lossy:
            notes["lossy"] += 1
        allowed = tuple(args.allow_added_rule)
        old_counts = marker_counts(path, strip_allowed_rule(path, old_text, allowed))
        new_counts = marker_counts(path, strip_allowed_rule(path, new_text, allowed))
        compared += 1
        for name, old_value in old_counts.items():
            new_value = new_counts.get(name, 0)
            if old_value != new_value:
                mismatches.append(f"{path}: {name} old={old_value} new={new_value}")
    if mismatches or deleted:
        for path in deleted:
            print(f"{path}: deleted (a translation never removes a file)")
        for line in mismatches:
            print(line)
        print(f"FAIL - {len(mismatches)} structural mismatch(es), {len(deleted)} deleted file(s)",
              file=sys.stderr)
        code = 1
    else:
        print(f"ok - structure preserved (checked {compared} changed files)")
        code = 0
    print_notes(notes, args.base)
    return code


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".",
                    help="Repository to check (default: the current directory)")
    ap.add_argument("--base", default="HEAD",
                    help="Git revision the unchanged structure is compared against (default: HEAD)")
    ap.add_argument("--allow-added-rule", action="append", default=[], metavar="RULE_ID",
                    help="A deliberately added factory rule whose markers/heading are stripped "
                         "from both sides before counting (repeatable)")
    ap.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                    help="Path prefix or fnmatch pattern left out of the comparison — for files "
                         "that are SUPPOSED to grow during the run (history: CHANGELOG.md, "
                         "memory/); skipped files are counted on stderr (repeatable)")
    args = ap.parse_args()
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

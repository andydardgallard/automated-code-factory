#!/usr/bin/env python3
"""
Deterministic documentation validator for the factory-documenter subagent (zero LLM tokens).

Checks that the documenter touched ONLY documentation:
  1. No protected file (tests, configs, build manifests, lockfiles) may be modified. A test/spec
     file is recognized by a path SEGMENT (a `tests/`, `spec/` directory) AND by its file NAME/STEM,
     so the `test_*.py` files that live next to the code they test are protected too.
  2. Markdown/plain-text files are documentation by definition and are allowed.
  3. Source files may change only doc-comment/docstring lines — any changed code line is a
     violation. Lines are classified by their POSITION in the two versions (the diff hunk maps
     old↔new), so duplicated text (a code line repeated inside a docstring) cannot mask a change.

Usage:
  python3 validate_documentation.py check --repo <root> --baseline <dir> --files f1 f2 ... [--derive]
  python3 validate_documentation.py snapshot --repo <root> --baseline <dir> --files f1 f2 ...

`snapshot` copies the listed files into <dir> preserving relative paths (the documenter runs it
BEFORE editing). `check` compares the current files against that snapshot.

The doc-line classifier is LANGUAGE-AWARE: a leading `#` counts as a comment only in the languages
where it is one (shell/python/ruby/...), never in the C family (a changed `#define`/`#include` is a
code change); `;` counts only where it is a comment (Clojure), `%` only in MATLAB-style `.m`, `--`
only in SQL/Lua/Haskell, and `//` only in the C/Java/JS family.

With `check --derive` the validator does not take the declared file list on faith: it computes the
changed TRACKED files itself from `git -C <repo> status --porcelain` and FAILS when a changed file
is missing from `--files` (an edit to an unlisted source/test/config file cannot hide). When git
is unavailable or <repo> is not a git repository the mode degrades with a message and exit code 2
(never a traceback).

Exit code 0 = PASS, 1 = FAIL (each violation printed to stderr), 2 = the deriving mode could not
run (git unavailable / not a repository). stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import shutil
import subprocess
import sys

PROTECTED_SUFFIXES = {
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".lock", ".csproj", ".sln", ".gradle", ".pom", ".xml", ".cargo",
}
TEST_PATH_PARTS = {"test", "tests", "spec", "specs", "__tests__", "conftest"}
# File-NAME markers of a test/spec file. Directory segments alone missed every `test_*.py` living
# next to the code it tests (e.g. `scripts/test_validate_documentation.py`), so a protected file is
# recognized by its name/stem too: `test_x.py`, `conftest.py`, `conftest_extra.py` (stem prefix),
# `x_test.go`, `x_spec.rb`, `x.test.ts`, `x.spec.js` (stem / name suffix).
TEST_STEM_PREFIXES = ("test_", "spec_", "conftest")
TEST_NAME_SUFFIXES = ("_test", "_spec", ".test", ".spec")

MARKDOWN_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc", ".textile"}

SOURCE_SUFFIXES = {
    ".py", ".rs", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".sql", ".lua", ".ex", ".exs", ".hs", ".clj", ".r", ".m", ".zig", ".nim",
}

# Line-comment / doc markers recognized for "this changed line is documentation", PER LANGUAGE:
# a `#define`/`#include` in a C file is a preprocessor (code) line, not a comment, so `#` counts
# only where it is one; the same holds for `;` (Clojure), `%` (MATLAB-style .m) and `--`
# (SQL/Lua/Haskell). Markup tags are language-neutral (no source code line starts with one).
_MARKUP_DOC_PREFIXES = ("<!--", "-->")
_HASH_COMMENT_SUFFIXES = {".py", ".sh", ".bash", ".rb", ".r", ".nim", ".ex", ".exs", ".php"}
_SLASH_COMMENT_SUFFIXES = {".rs", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".h",
                           ".cpp", ".hpp", ".cc", ".cs", ".swift", ".kt", ".scala", ".php",
                           ".zig", ".m"}
_DASHDASH_COMMENT_SUFFIXES = {".sql", ".lua", ".hs"}
_SEMI_COMMENT_SUFFIXES = {".clj"}
_PERCENT_COMMENT_SUFFIXES = {".m"}  # MATLAB flavour of .m; Objective-C is covered by `//`


def _doc_prefixes(rel: str) -> tuple[str, ...]:
    """Line-comment prefixes valid for the language `rel` is written in (by suffix)."""
    suffix = pathlib.PurePosixPath(rel).suffix.lower()
    prefixes = list(_MARKUP_DOC_PREFIXES)
    if suffix in _HASH_COMMENT_SUFFIXES:
        prefixes.append("#")
    if suffix in _SLASH_COMMENT_SUFFIXES:
        prefixes += ["//", "///", "//!"]
    if suffix in _DASHDASH_COMMENT_SUFFIXES:
        prefixes.append("--")
    if suffix in _SEMI_COMMENT_SUFFIXES:
        prefixes.append(";")
    if suffix in _PERCENT_COMMENT_SUFFIXES:
        prefixes.append("%")
    return tuple(prefixes)

_DOCSTRING_DELIMS = ('"""', "'''")
_BLOCK_START = "/*"          # `/*`, `/**` and `/*!` all open a C-style comment block
_BLOCK_END = "*/"


def _is_protected(rel: str) -> bool:
    """A file is out of scope for the documenter when a path SEGMENT marks a test/spec directory,
    when its NAME/STEM marks a test/spec file, or when its suffix is a config/build kind."""
    p = pathlib.PurePosixPath(rel)
    if {x.lower() for x in p.parts[:-1]} & TEST_PATH_PARTS:
        return True
    name = p.name.lower()
    stem = p.stem.lower()
    if stem in TEST_PATH_PARTS or stem.startswith(TEST_STEM_PREFIXES):
        return True
    # `x_test.go` / `x_spec.rb` / `x.test.ts` / `x.spec.js` end the STEM once the language suffix
    # is dropped; a file literally named `x.test` / `x.spec` ends the name.
    if name.endswith(TEST_NAME_SUFFIXES) or stem.endswith(TEST_NAME_SUFFIXES):
        return True
    return p.suffix.lower() in PROTECTED_SUFFIXES


def _is_markdown(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in MARKDOWN_SUFFIXES


def _is_source(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in SOURCE_SUFFIXES


def _doc_mask(lines: list[str], rel: str = "") -> list[bool]:
    """Return, per line, whether that line is inside a doc comment/docstring (or is a line
    comment). Heuristic but conservative: a changed non-doc, non-blank line is treated as code.
    `rel` selects the language: a `#`/`;`/`%`/`--` prefix only counts as a comment where it is one."""
    mask: list[bool] = []
    prefixes = _doc_prefixes(rel)
    in_triple = False
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            mask.append(True)  # blank lines never count as a code change
            continue
        is_doc = False
        # C-style block comment state: `/*`, `/**`, `/*!` open it, `*/` closes it. A `*`
        # continuation line is documentation ONLY while this state is on — outside a block it is
        # code (`*ptr = 1;`), so there is no bare-`*` fallback any more.
        if in_block:
            is_doc = True
            if _BLOCK_END in s:
                in_block = False
        # Python triple-quoted docstring state
        elif in_triple:
            is_doc = True
            if s.startswith(_DOCSTRING_DELIMS) or s.endswith(_DOCSTRING_DELIMS):
                in_triple = False
        else:
            if s.startswith(_BLOCK_START):
                is_doc = True
                if _BLOCK_END not in s[len(_BLOCK_START):]:
                    in_block = True
            elif s.startswith(_DOCSTRING_DELIMS):
                is_doc = True
                if s.count('"""') + s.count("'''") < 2:
                    in_triple = True
            elif s.startswith(prefixes):
                is_doc = True
            # No fallback for a bare `*` or `|` line: outside a block/docstring/markdown file it
            # is code (`*ptr = 1;`, `| mask = 2;`), and treating it as documentation let a code
            # edit through.
        mask.append(is_doc)
    return mask


def _changed_lines(old: list[str], new: list[str]) -> list[tuple[str, int, int]]:
    """Return the changed lines as `(text, old_index, new_index)` triples.

    The indices are taken from the diff opcodes themselves: a removed line carries its index in
    `old`, an added line its index in `new`, the other index is -1. A changed line is therefore
    located by POSITION, never by a content search: the same text may occur several times in a file
    (for example once as real code and once inside a docstring) and only the diff knows which
    occurrence changed.
    """
    out: list[tuple[str, int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.extend((old[i], i, -1) for i in range(i1, i2))
        out.extend((new[j], -1, j) for j in range(j1, j2))
    return out


def snapshot(root: pathlib.Path, baseline: pathlib.Path, files: list[str]) -> None:
    for rel in files:
        src = root / rel
        if not src.is_file():
            continue
        dst = baseline / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def check(root: pathlib.Path, baseline: pathlib.Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if _is_protected(rel):
            errors.append(f"{rel}: PROTECTED file modified (tests/configs/build manifests are out of scope)")
            continue
        if _is_markdown(rel):
            continue
        if not _is_source(rel):
            errors.append(f"{rel}: unknown file kind (neither markdown nor known source suffix)")
            continue
        cur = root / rel
        base = baseline / rel
        if not cur.is_file():
            errors.append(f"{rel}: documented file does not exist after edit")
            continue
        if not base.is_file():
            # Untracked/new source file: allow only if every non-blank line is a doc line.
            mask = _doc_mask(cur.read_text(encoding="utf-8", errors="replace").splitlines(), rel)
            bad = [i + 1 for i, d in enumerate(mask) if not d]
            if bad:
                errors.append(f"{rel}: new source file contains non-doc lines {bad[:5]}")
            continue
        old = base.read_text(encoding="utf-8", errors="replace").splitlines()
        new = cur.read_text(encoding="utf-8", errors="replace").splitlines()
        changed = _changed_lines(old, new)
        if not changed:
            continue
        # A changed line is a code change if it is non-blank and not a doc line in BOTH versions.
        old_mask = _doc_mask(old, rel)
        new_mask = _doc_mask(new, rel)
        for ln, oi, ni in changed:
            if not ln.strip():
                continue
            # conservatively treat a line as code if it is code in either version; the indices
            # come from the diff hunk, so a duplicate of the same text elsewhere (e.g. inside a
            # docstring, or a doc copy inside code) can neither hide nor invent a code change.
            in_old = oi >= 0 and not old_mask[oi]
            in_new = ni >= 0 and not new_mask[ni]
            if in_old or in_new:
                errors.append(f"{rel}: code line changed: {ln.strip()[:80]}")
                break
    return errors


def derive_changed_files(root: pathlib.Path) -> tuple[list[str], str]:
    """Return the changed TRACKED files of `root` from `git status --porcelain`.

    The second tuple element is "" on success, otherwise a human-readable reason (git missing,
    `root` not a repository) — the caller degrades with a message, never a traceback. Untracked
    (`??`) and ignored (`!!`) entries are out of scope: the mode polices edits to tracked files.
    """
    try:
        # `-z` + an explicit UTF-8 decode: NUL-separated and never C-quoted, so a non-ASCII path
        # arrives as the real name. `text=True` would decode git's output with the LOCALE code page
        # (cp1251 on a Russian Windows), so a name with a diacritic would come back as mojibake
        # that no declared path can match.
        proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git status could not run: {exc}"
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return [], f"git status failed (rc={proc.returncode}): {stderr}"
    changed: list[str] = []
    entries = (proc.stdout or b"").decode("utf-8", "replace").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4 or entry[:2] in ("??", "!!"):
            continue
        path = entry[3:]
        if entry[0] in "RC" and index < len(entries):
            index += 1          # `-z` puts the ORIGINAL path in the next record
        if path:
            changed.append(path)
    return changed, ""


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


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("check", "snapshot"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", default=".", help="Project root (default: cwd)")
        sp.add_argument("--baseline", required=True, help="Baseline snapshot directory")
        sp.add_argument("--files", nargs="+", required=True, help="Files touched by the documenter")
        if name == "check":
            sp.add_argument("--derive", action="store_true",
                            help="Do not take --files on faith: compute the changed TRACKED files "
                                 "from `git -C <repo> status --porcelain` and FAIL when a changed "
                                 "file is missing from --files (exit 2 when git cannot answer)")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    baseline = pathlib.Path(args.baseline).resolve()

    if args.cmd == "snapshot":
        snapshot(root, baseline, args.files)
        print(f"PASS - snapshot of {len(args.files)} file(s) saved to {baseline}")
        return 0

    errors = check(root, baseline, args.files)
    if args.derive:
        changed, reason = derive_changed_files(root)
        if reason:
            print(f"error: --derive cannot compute the changed set: {reason}", file=sys.stderr)
            return 2
        declared = {pathlib.PurePath(f).as_posix() for f in args.files}
        for rel in sorted(set(changed) - declared):
            errors.append(f"{rel}: changed in the repository but not declared via --files")
    if errors:
        print("FAIL - documentation validation:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    print(f"PASS - documentation changes are documentation-only ({len(args.files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

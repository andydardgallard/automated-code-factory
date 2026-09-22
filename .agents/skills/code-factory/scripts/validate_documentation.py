#!/usr/bin/env python3
"""
Deterministic documentation validator for the factory-documenter subagent (zero LLM tokens).

Checks that the documenter touched ONLY documentation:
  1. No protected file (tests, configs, build manifests, lockfiles) may be modified.
  2. Markdown/plain-text files are documentation by definition and are allowed.
  3. Source files may change only doc-comment/docstring lines — any changed code line is a
     violation.

Usage:
  python3 validate_documentation.py check --repo <root> --baseline <dir> --files f1 f2 ...
  python3 validate_documentation.py snapshot --repo <root> --baseline <dir> --files f1 f2 ...

`snapshot` copies the listed files into <dir> preserving relative paths (the documenter runs it
BEFORE editing). `check` compares the current files against that snapshot.

Exit code 0 = PASS, 1 = FAIL (each violation printed to stderr). stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import shutil
import sys

PROTECTED_SUFFIXES = {
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".lock", ".csproj", ".sln", ".gradle", ".pom", ".xml", ".cargo",
}
TEST_PATH_PARTS = {"test", "tests", "spec", "specs", "__tests__", "conftest"}

MARKDOWN_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc", ".textile"}

SOURCE_SUFFIXES = {
    ".py", ".rs", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".sql", ".lua", ".ex", ".exs", ".hs", ".clj", ".r", ".m", ".zig", ".nim",
}

# Line-comment / doc markers recognized for "this changed line is documentation".
_LINE_DOC_PREFIXES = ("#", "//", "///", "//!", "--", "<!--", "-->", ">", "%", ";")

_DOCSTRING_DELIMS = ('"""', "'''")
_BLOCK_START = "/**"
_BLOCK_END = "*/"


def _is_protected(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    parts = {x.lower() for x in p.parts}
    if parts & TEST_PATH_PARTS:
        return True
    return p.suffix.lower() in PROTECTED_SUFFIXES


def _is_markdown(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in MARKDOWN_SUFFIXES


def _is_source(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in SOURCE_SUFFIXES


def _doc_mask(lines: list[str]) -> list[bool]:
    """Return, per line, whether that line is inside a doc comment/docstring (or is a line
    comment). Heuristic but conservative: a changed non-doc, non-blank line is treated as code."""
    mask: list[bool] = []
    in_triple = False
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            mask.append(True)  # blank lines never count as a code change
            continue
        is_doc = False
        # C-style block comment state
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
            elif s.startswith(_LINE_DOC_PREFIXES):
                is_doc = True
            elif s.startswith("*") and s.endswith("*/"):
                is_doc = True
            elif s.startswith("*") or s.startswith("|"):
                is_doc = True  # continuation of a block doc / markdown table
        mask.append(is_doc)
    return mask


def _changed_lines(old: list[str], new: list[str]) -> list[str]:
    """Return the non-`?` lines of a unified diff (added `+` and removed `-`)."""
    out: list[str] = []
    for ln in difflib.unified_diff(old, new, lineterm="", n=0):
        if ln.startswith(("+++", "---", "@@")):
            continue
        if ln.startswith("+") or ln.startswith("-"):
            out.append(ln[1:])
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
            mask = _doc_mask(cur.read_text(encoding="utf-8", errors="replace").splitlines())
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
        old_mask = _doc_mask(old)
        new_mask = _doc_mask(new)
        for ln in changed:
            if not ln.strip():
                continue
            # conservatively treat a line as code if it is code in either version;
            # first occurrence wins and a missing line is simply "not code" (no IndexError).
            oi = next((i for i, x in enumerate(old) if x == ln), -1)
            ni = next((i for i, x in enumerate(new) if x == ln), -1)
            in_old = oi >= 0 and not old_mask[oi]
            in_new = ni >= 0 and not new_mask[ni]
            if in_old or in_new:
                errors.append(f"{rel}: code line changed: {ln.strip()[:80]}")
                break
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("check", "snapshot"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", default=".", help="Project root (default: cwd)")
        sp.add_argument("--baseline", required=True, help="Baseline snapshot directory")
        sp.add_argument("--files", nargs="+", required=True, help="Files touched by the documenter")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    baseline = pathlib.Path(args.baseline).resolve()

    if args.cmd == "snapshot":
        snapshot(root, baseline, args.files)
        print(f"PASS - snapshot of {len(args.files)} file(s) saved to {baseline}")
        return 0

    errors = check(root, baseline, args.files)
    if errors:
        print("FAIL - documentation validation:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    print(f"PASS - documentation changes are documentation-only ({len(args.files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

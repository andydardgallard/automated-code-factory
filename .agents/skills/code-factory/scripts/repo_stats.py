#!/usr/bin/env python3
"""
Typical repository analyzers — "Think in Code" instead of reading files into the context
(zero LLM tokens, stdlib only).

Counting lines, spotting entry points or grouping imports needs no judgment, so the factory asks
this script and reads the answer instead of pulling whole files into the LLM context. The file
walk itself comes from `repo_inventory.py` (same exclusions: VCS/factory/build dirs, *.pyc,
binaries).

Commands (all print JSON, all deterministic — sorted by path / by count):
  sizes --repo <path> [--top 20]      biggest files by line count
  entry-points --repo <path>          entry-point heuristics, language-agnostic
  imports --repo <path> [--top 20]    most frequent imported modules, best-effort regexes

entry-point heuristics (a file is listed when at least one reason applies):
  filename       stem is main/cli/__main__/__init__
  dunder-main    `if __name__ ==`
  argparse       `argparse` mentioned
  package.json   a "main"/"bin" key
  Cargo [[bin]]  a `[[bin]]` table
imports regexes: `^import X`, `^from X import`, `require('X')`, `#include <X>`, `^using X`.
This is a language-agnostic approximation, never a parser: it is deliberately best-effort.
Text analyzers skip files larger than MAX_TEXT_BYTES (1 MiB); `sizes` covers every file.
Exit code 0 = success, 1 = error (the `--repo` path is not a directory).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import repo_inventory

MAX_TEXT_BYTES = 1024 * 1024

MAIN_STEMS = {"main", "cli", "__main__", "__init__"}

MAIN_FILE_RE = re.compile(r"^\s*if\s+__name__\s*==", re.M)
ARGPARSE_RE = re.compile(r"\bargparse\b")
PACKAGE_JSON_RE = re.compile(r'"(?:main|bin)"\s*:')
CARGO_BIN_RE = re.compile(r"^\s*\[\[bin\]\]", re.M)

IMPORT_RES = (
    re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.M),
    re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\b", re.M),
    re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"^\s*#include\s*[<\"]([^>\"]+)[>\"]", re.M),
    re.compile(r"^\s*using\s+([A-Za-z_][\w.]*)\s*;", re.M),
)


def _records(root: pathlib.Path) -> list[dict]:
    return repo_inventory.file_records(root)


def _text(root: pathlib.Path, record: dict) -> str | None:
    """Decoded file text, or None for a file the text analyzers must skip."""
    if record["bytes"] > MAX_TEXT_BYTES:
        return None
    return (root / record["path"]).read_bytes().decode("utf-8", errors="replace")


def sizes(root: pathlib.Path, top: int) -> dict:
    """Biggest files by line count (ties broken by path)."""
    records = _records(root)
    ranked = sorted(records, key=lambda r: (-r["lines"], r["path"]))
    return {"files": ranked[:max(top, 0)],
            "total_files": len(records),
            "total_lines": sum(r["lines"] for r in records)}


def entry_points(root: pathlib.Path) -> dict:
    """Entry-point candidates with the reason that flagged them."""
    found: list[dict] = []
    for record in _records(root):
        reasons: list[str] = []
        name = pathlib.PurePosixPath(record["path"]).name
        if pathlib.PurePosixPath(name).stem in MAIN_STEMS:
            reasons.append("filename")
        text = _text(root, record)
        if text is not None:
            if MAIN_FILE_RE.search(text):
                reasons.append("dunder-main")
            if ARGPARSE_RE.search(text):
                reasons.append("argparse")
            if name == "package.json" and PACKAGE_JSON_RE.search(text):
                reasons.append("package.json")
            if name == "Cargo.toml" and CARGO_BIN_RE.search(text):
                reasons.append("Cargo [[bin]]")
        if reasons:
            found.append({"path": record["path"], "reasons": reasons})
    return {"entry_points": found, "total_entry_points": len(found)}


def imports(root: pathlib.Path, top: int) -> dict:
    """Most frequent imported modules, counted across every text file."""
    counts: dict[str, int] = {}
    total_matches = 0
    for record in _records(root):
        text = _text(root, record)
        if text is None:
            continue
        for regex in IMPORT_RES:
            for match in regex.finditer(text):
                module = match.group(1)
                counts[module] = counts.get(module, 0) + 1
                total_matches += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"imports": [{"module": module, "count": count} for module, count in ranked[:max(top, 0)]],
            "total_unique": len(counts),
            "total_matches": total_matches}


def _dump(payload: dict) -> None:
    # ensure_ascii (the default) keeps the output encodable in any console code page.
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sizes", help="biggest files by lines")
    ps.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    ps.add_argument("--top", type=int, default=20, help="How many files to list (default: 20)")

    pe = sub.add_parser("entry-points", help="entry-point heuristics")
    pe.add_argument("--repo", default=".", help="Repository root (default: cwd)")

    pm = sub.add_parser("imports", help="most frequent imported modules")
    pm.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    pm.add_argument("--top", type=int, default=20, help="How many modules to list (default: 20)")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    if args.cmd == "sizes":
        _dump(sizes(root, args.top))
        return 0
    if args.cmd == "entry-points":
        _dump(entry_points(root))
        return 0
    if args.cmd == "imports":
        _dump(imports(root, args.top))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

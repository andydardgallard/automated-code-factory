#!/usr/bin/env python3
"""
Deterministic repository inventory for the shard protocol (zero LLM tokens, stdlib only).

A whole-repo review / security_audit cannot put an entire repository into one context, so the
tree is walked here — deterministically, without the LLM — and the sorted file list is packed
into shards of at most N lines each. The agent then reads one shard at a time.

Excluded while walking (directory names, at any depth): .git, .code-factory, __pycache__,
node_modules, .venv, target, dist, build. Excluded files: *.pyc, binaries (a NUL byte within
the first 8192 bytes) and files that cannot be read at all (OSError: an unreadable file is skipped
and counted, it never fails the whole scan). Symbolic links are never followed (a cycle would make
the walk endless).

Commands:
  inventory --repo <path>
      JSON {"files": [{"path", "lines", "bytes"}, ...], "total_files", "total_lines",
            "skipped_unreadable"}
      `path` is repo-relative and posix; `files` is sorted by path; `skipped_unreadable` counts
      the files the walk could not read (same skip policy as the unreadable directories).
  shards --repo <path> [--max-lines N]        (default: 20000)
      JSON {"shards": [{"id", "files", "lines"}, ...], "total_shards"}
      Greedy packing of the sorted list: a shard never exceeds N lines, and a single file
      longer than N lines becomes a shard of its own flagged with `oversized: true` (the flag
      is present only on such shards). `files` holds repo-relative paths.

Lines are counted as `\\n`-separated lines, so a trailing newline adds no empty line.
Both commands are deterministic: the same working tree always yields identical JSON.
Exit code 0 = success, 1 = error (the `--repo` path is not a directory, or `--max-lines < 1`).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Directory names never traversed (matched by name at any depth).
EXCLUDE_DIRS = {".git", ".code-factory", "__pycache__", "node_modules", ".venv",
                "target", "dist", "build"}
# File suffixes never inventoried.
EXCLUDE_SUFFIXES = {".pyc"}
# A NUL byte within this many leading bytes marks the file as binary.
BINARY_SNIFF_BYTES = 8192


def count_lines(data: bytes) -> int:
    """Number of `\\n`-separated lines; an empty file has zero lines."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def is_binary(data: bytes) -> bool:
    """Heuristic: a NUL byte in the first BINARY_SNIFF_BYTES bytes."""
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


def iter_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every inventoried file, sorted by repo-relative posix path (deterministic)."""
    found: list[pathlib.Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue  # unreadable directory: skip it, never fail the whole scan
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in EXCLUDE_DIRS:
                    stack.append(entry)
            elif entry.is_file() and entry.suffix not in EXCLUDE_SUFFIXES:
                found.append(entry)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def read_bytes(path: pathlib.Path) -> bytes | None:
    """Content of `path`, or None when it cannot be read.

    An unreadable file (permissions, a vanished mount, an I/O error) is skipped exactly like an
    unreadable directory: one bad file never fails the whole scan.
    """
    try:
        return path.read_bytes()
    except OSError:
        return None


def file_record(root: pathlib.Path, path: pathlib.Path, data: bytes) -> dict:
    """Inventory record for one readable, non-binary file."""
    return {"path": path.relative_to(root).as_posix(),
            "lines": count_lines(data),
            "bytes": len(data)}


def scan_files(root: pathlib.Path) -> tuple[list[dict], int]:
    """(text-file records, number of unreadable files skipped)."""
    records: list[dict] = []
    skipped = 0
    for path in iter_files(root):
        data = read_bytes(path)
        if data is None:
            skipped += 1
        elif not is_binary(data):
            records.append(file_record(root, path, data))
    return records, skipped


def file_records(root: pathlib.Path) -> list[dict]:
    """Sorted text-file records: [{"path", "lines", "bytes"}, ...]; unreadable files are skipped."""
    return scan_files(root)[0]


def inventory(root: pathlib.Path) -> dict:
    """Full inventory of the repository."""
    records, skipped = scan_files(root)
    return {"files": records,
            "total_files": len(records),
            "total_lines": sum(r["lines"] for r in records),
            "skipped_unreadable": skipped}


def _shard(index: int, records: list[dict], oversized: bool = False) -> dict:
    shard = {"id": f"shard-{index}",
             "files": [r["path"] for r in records],
             "lines": sum(r["lines"] for r in records)}
    if oversized:
        shard["oversized"] = True
    return shard


def pack_shards(records: list[dict], max_lines: int) -> list[dict]:
    """Greedy packing of already sorted records into shards of at most `max_lines` lines."""
    if max_lines < 1:
        raise ValueError(f"max_lines must be >= 1, got {max_lines}")
    shards: list[dict] = []
    current: list[dict] = []
    current_lines = 0
    for record in records:
        if record["lines"] > max_lines:
            if current:
                shards.append(_shard(len(shards) + 1, current))
                current, current_lines = [], 0
            shards.append(_shard(len(shards) + 1, [record], oversized=True))
            continue
        if current and current_lines + record["lines"] > max_lines:
            shards.append(_shard(len(shards) + 1, current))
            current, current_lines = [], 0
        current.append(record)
        current_lines += record["lines"]
    if current:
        shards.append(_shard(len(shards) + 1, current))
    return shards


def shards(root: pathlib.Path, max_lines: int) -> dict:
    """Shard plan for the repository."""
    plan = pack_shards(file_records(root), max_lines)
    return {"shards": plan, "total_shards": len(plan)}


def _dump(payload: dict) -> None:
    # ensure_ascii (the default) keeps the output encodable in any console code page.
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inventory", help="list files with line/byte counts")
    pi.add_argument("--repo", default=".", help="Repository root (default: cwd)")

    ps = sub.add_parser("shards", help="pack the file list into shards")
    ps.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    ps.add_argument("--max-lines", type=int, default=20000,
                    help="Maximum lines per shard (default: 20000)")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    if args.cmd == "inventory":
        _dump(inventory(root))
        return 0

    if args.cmd == "shards":
        if args.max_lines < 1:
            print(f"error: --max-lines must be >= 1, got {args.max_lines}", file=sys.stderr)
            return 1
        _dump(shards(root, args.max_lines))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

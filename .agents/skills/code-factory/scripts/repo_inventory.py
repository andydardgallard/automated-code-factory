#!/usr/bin/env python3
"""
Deterministic repository inventory for the shard protocol (zero LLM tokens, stdlib only).

A whole-repo review / security_audit cannot put an entire repository into one context, so the
tree is walked here — deterministically, without the LLM — and the sorted file list is packed
into shards of at most N lines each. The agent then reads one shard at a time.

Excluded while walking (directory names, at any depth): .git, .code-factory, __pycache__,
node_modules, .venv, target, dist, build. Excluded files: *.pyc, binaries (a NUL byte within
the first 8192 bytes), symbolic links (never followed: a cycle would make the walk endless) and
files that cannot be read at all (OSError: an unreadable file is skipped and counted, it never
fails the whole scan).

`--tracked` replaces the walk with the TRACKED set: `git ls-files -z` at the `--repo` root,
parsed NUL-safely, so a review / audit whose contract is "the repository" can never see an
untracked or ignored path that happens to sit in the working tree (a machine-local config, a
scratch directory, editor debris). It requires git and a git repository at `--repo`: when either
is missing the command exits 1 with the reason on stderr and invents nothing — it never falls back
to the walk, because that fallback would silently re-admit exactly the paths this mode excludes.
The content filter is the walk's (*.pyc, binaries, unreadable and symlinked paths are skipped with
the same counting), but the directory-name exclusions do NOT apply: a tracked file under `build/`
or `node_modules/` is part of the tracked tree. Without the flag the filesystem walk stays the
documented default — the escape hatch for callers that must also see untracked files
(`repo_stats.py`, `precedent_index.py`).

Commands:
  inventory --repo <path> [--tracked]
      JSON {"files": [{"path", "lines", "bytes"}, ...], "total_files", "total_lines",
            "skipped_unreadable"}
      `path` is repo-relative and posix; `files` is sorted by path; `skipped_unreadable` counts
      the files the scan could not read (same skip policy as the unreadable directories).
  shards --repo <path> [--max-lines N] [--tracked]        (default: 20000)
      JSON {"shards": [{"id", "files", "lines"}, ...], "total_shards"}
      Greedy packing of the sorted list: a shard never exceeds N lines, and a single file
      longer than N lines becomes a shard of its own flagged with `oversized: true` (the flag
      is present only on such shards). `files` holds repo-relative paths.

Lines are counted as `\\n`-separated lines, so a trailing newline adds no empty line.
Both commands are deterministic: the same working tree always yields identical JSON.
Exit code 0 = success, 1 = error (the `--repo` path is not a directory, `--max-lines < 1`, or
`--tracked` requested while the git executable / the git repository is unavailable).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
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


class TrackedUnavailable(RuntimeError):
    """`--tracked` was requested but the tracked set cannot be determined.

    Raised when the git executable is missing or `--repo` is not inside a git repository. The
    tracked mode has a contract — a silent fallback to the filesystem walk would put exactly the
    untracked and ignored paths back into the review — so the caller reports the reason and fails.
    """


def git_ls_files(root: pathlib.Path) -> list[str]:
    """Repo-relative posix paths of every TRACKED file at `root`, via `git ls-files -z`.

    NUL-separated rather than line-separated: a path with a space, a quote, a newline or a
    non-ASCII name survives verbatim, where line parsing would split, quote or mangle it. Raises
    TrackedUnavailable — never returning a partial or empty list — when git is not installed, when
    `root` is not inside a repository, or when git refuses for any other reason.
    """
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    except OSError as exc:                       # git not installed / not executable
        raise TrackedUnavailable(f"git is unavailable ({exc.__class__.__name__}: {exc}); the "
                                 f"tracked set cannot be read") from exc
    if result.returncode != 0:
        reported = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        reason = reported[0] if reported else f"git ls-files exited {result.returncode}"
        raise TrackedUnavailable(f"git ls-files failed in {root}: {reason}")
    with_nul = result.stdout.decode("utf-8", errors="replace")
    return [name for name in with_nul.split("\0") if name]


def tracked_paths(root: pathlib.Path) -> list[pathlib.Path]:
    """The tracked files at `root`, sorted by repo-relative posix path (like `iter_files`)."""
    paths: list[pathlib.Path] = []
    for name in git_ls_files(root):
        relative = pathlib.PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            continue        # a tracked path outside the root can never be inventoried there
        paths.append(root.joinpath(*relative.parts))
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def file_record(root: pathlib.Path, path: pathlib.Path, data: bytes) -> dict:
    """Inventory record for one readable, non-binary file."""
    return {"path": path.relative_to(root).as_posix(),
            "lines": count_lines(data),
            "bytes": len(data)}


def scan_paths(root: pathlib.Path, paths: list[pathlib.Path]) -> tuple[list[dict], int]:
    """(records for the listed files, number of unreadable files skipped).

    The filter is shared by both modes, so a file yields the same record whether it came from the
    walk or from the tracked set: *.pyc and symbolic links are skipped, an unreadable file is
    counted and skipped, a binary is skipped.
    """
    records: list[dict] = []
    skipped = 0
    for path in paths:
        if path.suffix in EXCLUDE_SUFFIXES or path.is_symlink():
            continue
        data = read_bytes(path)
        if data is None:
            skipped += 1
        elif not is_binary(data):
            records.append(file_record(root, path, data))
    return records, skipped


def scan_files(root: pathlib.Path, tracked: bool = False) -> tuple[list[dict], int]:
    """(text-file records, number of unreadable files skipped).

    The default walk is filesystem-based; `tracked=True` takes the file set from `git ls-files -z`
    at `root` and raises TrackedUnavailable when that set cannot be read.
    """
    return scan_paths(root, tracked_paths(root) if tracked else iter_files(root))


def file_records(root: pathlib.Path) -> list[dict]:
    """Sorted text-file records: [{"path", "lines", "bytes"}, ...]; unreadable files are skipped."""
    return scan_files(root)[0]


def inventory(root: pathlib.Path, tracked: bool = False) -> dict:
    """Full inventory of the repository: the walk, or the tracked set when `tracked` is set."""
    records, skipped = scan_files(root, tracked)
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


def shards(root: pathlib.Path, max_lines: int, tracked: bool = False) -> dict:
    """Shard plan for the repository: the walk, or the tracked set when `tracked` is set."""
    plan = pack_shards(scan_files(root, tracked)[0], max_lines)
    return {"shards": plan, "total_shards": len(plan)}


def _dump(payload: dict) -> None:
    # ensure_ascii (the default) keeps the output encodable in any console code page.
    print(json.dumps(payload, indent=2, sort_keys=True))


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

    pi = sub.add_parser("inventory", help="list files with line/byte counts")
    pi.add_argument("--repo", default=".", help="Repository root (default: cwd)")

    ps = sub.add_parser("shards", help="pack the file list into shards")
    ps.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    ps.add_argument("--max-lines", type=int, default=20000,
                    help="Maximum lines per shard (default: 20000)")

    for parser in (pi, ps):
        parser.add_argument("--tracked", action="store_true",
                            help="File set from `git ls-files -z` at --repo (tracked files only); "
                                 "fails when git or the repository is unavailable instead of "
                                 "falling back to the walk (default: walk the filesystem)")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    try:
        if args.cmd == "inventory":
            _dump(inventory(root, args.tracked))
            return 0

        if args.cmd == "shards":
            if args.max_lines < 1:
                print(f"error: --max-lines must be >= 1, got {args.max_lines}", file=sys.stderr)
                return 1
            _dump(shards(root, args.max_lines, args.tracked))
            return 0
    except TrackedUnavailable as exc:
        print(f"error: --tracked failed: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Tail a long test/build log without pulling all of it into the LLM context (stdlib only).

A full test log can be thousands of lines, yet the agent needs only the size, the number of
failures and the tail. This prints the counters, the match count for every --grep pattern and
then the last N lines — nothing more.

Usage:
  python log_tail.py <file> [--lines 50] [--grep PATTERN]...

Output:
  file: <path>
  total_lines: <N>
  total_bytes: <N>
  grep 'FAILED|ERROR': <N>          (one line per --grep)
  --- last <N> lines ---
  <tail>

Exit code 0 whenever the file can be read (even when it is empty); 1 if it is missing/unreadable,
`--lines` is negative, or a --grep pattern is not a valid regex. Text is decoded as UTF-8 with
replacement, so binary-ish logs never break the output.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys


def read_log(path: pathlib.Path) -> tuple[bytes, list[str]]:
    """Raw bytes plus the decoded lines of the log."""
    data = path.read_bytes()
    return data, data.decode("utf-8", errors="replace").splitlines()


def count_lines(data: bytes) -> int:
    """Number of `\\n`-separated lines; an empty file has zero lines."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def count_matches(lines: list[str], patterns: list[str]) -> list[tuple[str, int]]:
    """(pattern, match count) for every pattern; raises re.error on an invalid pattern."""
    out: list[tuple[str, int]] = []
    for pattern in patterns:
        regex = re.compile(pattern)
        out.append((pattern, sum(1 for line in lines if regex.search(line))))
    return out


def render(path: pathlib.Path, total_lines: int, total_bytes: int,
           matches: list[tuple[str, int]], tail: list[str], lines: int) -> str:
    out = [f"file: {path}",
           f"total_lines: {total_lines}",
           f"total_bytes: {total_bytes}"]
    out += [f"grep '{pattern}': {count}" for pattern, count in matches]
    if lines > 0:
        out.append(f"--- last {lines} lines ---")
        out.extend(tail)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="Log file to inspect")
    ap.add_argument("--lines", type=int, default=50,
                    help="How many trailing lines to print (default: 50; 0 prints no tail)")
    ap.add_argument("--grep", action="append", default=[], metavar="PATTERN",
                    help="Regex whose match count is reported; repeatable")
    args = ap.parse_args()

    path = pathlib.Path(args.file)
    # A build log may contain bytes that the console code page cannot encode (e.g. cp1251 on
    # Windows): print replacement characters instead of dying on the tail.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.lines < 0:
        print(f"error: --lines must be >= 0, got {args.lines}", file=sys.stderr)
        return 1
    try:
        data, lines = read_log(path)
    except OSError as exc:
        print(f"error: cannot read log: {exc}", file=sys.stderr)
        return 1
    try:
        matches = count_matches(lines, args.grep)
    except re.error as exc:
        print(f"error: invalid --grep pattern: {exc}", file=sys.stderr)
        return 1

    tail = lines[-args.lines:] if args.lines else []
    sys.stdout.write(render(path, count_lines(data), len(data), matches, tail, args.lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

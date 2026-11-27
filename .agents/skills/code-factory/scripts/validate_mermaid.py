#!/usr/bin/env python3
"""
Deterministic Mermaid flowchart syntax check for the Code Factory's SKILL.md (zero LLM tokens).

Validates the `flowchart` block structurally, without requiring mmdc/npm:
  1. a ```mermaid code block exists and starts with `flowchart` (or `graph`);
  2. the shape delimiters `[`/`]`, `{`/`}` and `(`/`)` open and close in ORDER and NEST they
     stack on every line (a closer must match the innermost still-open opener);
  3. every edge (`-->`) has a non-empty source AND target (after stripping `-->|label|`).

In Mermaid a bare node id is valid (an edge implicitly defines its endpoints), so this checker
catches shape/bracket typos and dangling edges — the two structural failures that break rendering —
without rejecting legitimate bare connector nodes.

Counting brackets per kind is not enough: `A] --> B[` (reversed) and `A([)]` (crossed) have equal
counts yet render nothing. The check therefore walks a stack, and text inside `"..."` — where a
backslash escapes the next character — is label content, so brackets there neither open nor close a
shape and a legitimately quoted or escaped label never fails.

Usage:
  python3 validate_mermaid.py [--file <path>]

Exit code 0 = valid, 1 = violations (printed to stderr). stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

EDGE_SPLIT = re.compile(r"-->")
LABEL = re.compile(r"-->\|[^|\n]*\|")

DELIMITERS = {"[": "]", "{": "}", "(": ")"}          # opener -> its closer
CLOSERS = {closer: opener for opener, closer in DELIMITERS.items()}


def extract_block(text: str) -> str | None:
    lines = text.splitlines()
    in_block = False
    out: list[str] = []
    for ln in lines:
        if ln.strip() == "```mermaid":
            in_block = True
            continue
        if in_block and ln.strip() == "```":
            break
        if in_block:
            out.append(ln)
    return "\n".join(out) if in_block else None


def delimiter_errors(line_no: int, s: str) -> list[str]:
    """Report the first delimiter order/nesting fault of one line; quoted text is exempt.

    The stack holds the still-open delimiters with their column. A closer must match the top of the
    stack: a stray `]` (`A] --> B[`) closes nothing, and `)` over an open `[` (`A([)]`) is crossed
    nesting. One fault is reported per line — the rest of a broken line is not worth cascading.
    """
    stack: list[tuple[str, int]] = []
    in_quote = escaped = False
    for pos, ch in enumerate(s):
        if escaped:                              # the escaped character is label text, not syntax
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_quote = not in_quote
        elif in_quote:
            continue
        elif ch in DELIMITERS:
            stack.append((ch, pos))
        elif ch in CLOSERS:
            if not stack:
                return [f"line {line_no}: unbalanced '{ch}' closes no open delimiter: {s[:80]}"]
            opener, opened_at = stack[-1]
            if opener != CLOSERS[ch]:
                return [f"line {line_no}: unbalanced nesting: '{ch}' closes '{opener}' opened at "
                        f"column {opened_at + 1} (expected '{DELIMITERS[opener]}'): {s[:80]}"]
            stack.pop()
    if stack:
        opener, opened_at = stack[-1]
        return [f"line {line_no}: unbalanced '{opener}' opened at column {opened_at + 1} "
                f"and never closed: {s[:80]}"]
    return []


def check_block(block: str) -> list[str]:
    errors: list[str] = []
    lines = [ln for ln in block.splitlines() if ln.strip()]
    header_ok = False
    for idx, ln in enumerate(lines, start=1):
        s = ln.strip()
        if s.startswith("flowchart") or s.startswith("graph"):
            header_ok = True
            continue
        if s.startswith("%%"):
            continue
        # delimiter order and nesting
        errors.extend(delimiter_errors(idx, s))
        # edges must have non-empty endpoints
        stripped = LABEL.sub("-->", s)
        if "-->" in stripped:
            parts = EDGE_SPLIT.split(stripped)
            for part in parts:
                if not part.strip():
                    errors.append(f"line {idx}: edge with empty endpoint: {s[:80]}")
                    break
    if not header_ok:
        errors.append("flowchart block must start with 'flowchart' or 'graph'")
    return errors


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
    ap.add_argument("--file", default=".agents/skills/code-factory/SKILL.md",
                    help="Path to SKILL.md (default: .agents/skills/code-factory/SKILL.md)")
    args = ap.parse_args()

    path = pathlib.Path(args.file)
    text = path.read_text(encoding="utf-8")
    block = extract_block(text)
    if block is None:
        print("FAIL - no ```mermaid block found", file=sys.stderr)
        return 1

    errors = check_block(block)
    if errors:
        print("FAIL - mermaid flowchart has syntax problems:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1

    n_edges = sum(1 for ln in block.splitlines() if "-->" in ln)
    print(f"PASS - mermaid flowchart is structurally valid ({n_edges} edge lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

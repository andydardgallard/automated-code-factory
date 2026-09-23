#!/usr/bin/env python3
"""
Deterministic Mermaid flowchart syntax check for the Code Factory's SKILL.md (zero LLM tokens).

Validates the `flowchart` block structurally, without requiring mmdc/npm:
  1. a ```mermaid code block exists and starts with `flowchart` (or `graph`);
  2. `[`, `{`, `(` are balanced on every line (no unclosed shapes);
  3. every edge (`-->`) has a non-empty source AND target (after stripping `-->|label|`).

In Mermaid a bare node id is valid (an edge implicitly defines its endpoints), so this checker
catches shape/bracket typos and dangling edges — the two structural failures that break rendering —
without rejecting legitimate bare connector nodes.

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
        # bracket balance
        if s.count("[") != s.count("]"):
            errors.append(f"line {idx}: unbalanced '[' / ']': {s[:80]}")
        if s.count("{") != s.count("}"):
            errors.append(f"line {idx}: unbalanced '{{' / '}}': {s[:80]}")
        if s.count("(") != s.count(")"):
            errors.append(f"line {idx}: unbalanced '(' / ')': {s[:80]}")
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

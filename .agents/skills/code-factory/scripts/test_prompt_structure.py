#!/usr/bin/env python3
"""
Verify the factory's prompt files follow the append-only structure required for DeepSeek
automatic context caching:

  [static prefix]  = YAML frontmatter (name/description/tools/model_preference) + static body
  [dynamic suffix] = turn history, error logs, dynamic data  (appended at call time, NOT baked in)

Checks (deterministic, zero LLM):
  1. Every prompt .md starts with a YAML frontmatter block (--- ... ---).
  2. The frontmatter contains only known static keys (no dynamic keys mixed into the prefix).
  3. The frontmatter has no per-run placeholders (${...} / {{...}}).

Exit code 0 = all files OK, 1 = violation (printed to stderr).
"""
from __future__ import annotations

import pathlib
import re
import sys

FACTORY_ROOT = pathlib.Path(__file__).resolve().parents[3]  # .agents/

PROMPT_FILES = [
    FACTORY_ROOT / "skills" / "code-factory" / "SKILL.md",
    FACTORY_ROOT / "agents" / "code-factory.md",
    *sorted((FACTORY_ROOT / "agents" / "sub-agents").glob("*.md")),
]

# Static frontmatter keys allowed in the immutable prompt prefix.
ALLOWED_KEYS = {
    "name", "description", "whenToUse", "tools", "disallowedTools",
    "model_preference", "type", "subagents",
}

# Per-run/dynamic markers that must never appear in the static prefix.
DYNAMIC_RE = re.compile(r"(\$\{[^}]*\}|\{\{[^}]*\}\})")


def frontmatter_lines(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    return lines[1:end] if end is not None else []


def check_file(path: pathlib.Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    fm = frontmatter_lines(text)
    if not fm:
        return [f"{path}: missing YAML frontmatter (--- ... ---) as static prefix"]

    for lineno, line in enumerate(fm, start=2):
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key not in ALLOWED_KEYS:
            errors.append(f"{path}:{lineno}: unknown frontmatter key '{key}' (dynamic in prefix?)")
        if DYNAMIC_RE.search(line):
            errors.append(f"{path}:{lineno}: dynamic placeholder in static prefix: {line.strip()}")
    return errors


def main() -> int:
    all_errors: list[str] = []
    for f in PROMPT_FILES:
        if not f.exists():
            all_errors.append(f"{f}: not found")
            continue
        all_errors.extend(check_file(f))

    if all_errors:
        print("FAIL - prompt structure is NOT append-only safe:", file=sys.stderr)
        for e in all_errors:
            print("  " + e, file=sys.stderr)
        return 1

    print(f"PASS - {len(PROMPT_FILES)} prompt files have a static frontmatter prefix "
          "(static prefix -> dynamic suffix).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

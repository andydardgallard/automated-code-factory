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
  4. Orchestration flow regression: the `flowchart` block of SKILL.md is parsed as a graph and
     BOTH entry branches must pass through the pre-flight node `PF` before the backup node `K` —
     the HITL plan-approval branch (J --Approve--> ... --> K) and the auto branch
     (G --auto--> L --> ... --> K). Pre-flight probes the real environment (python command, git,
     bash, secondary-model flag), so a branch that reaches backup without it is a capability
     probe that never ran. Every edge entering `K` therefore has to come from `PF`.

Exit code 0 = all files OK, 1 = violation (printed to stderr).
"""
from __future__ import annotations

import collections
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

# The orchestration flowchart lives in the skill prompt; its flow is an invariant, not prose.
SKILL_FILE = FACTORY_ROOT / "skills" / "code-factory" / "SKILL.md"
MERMAID_RE = re.compile(r"```mermaid\r?\n(.*?)\r?\n```", re.DOTALL)
# `J -->|Approve| PF` / `PF --> K[Backup ...]`; the label is optional, the node the identifier.
EDGE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\s*(?:\|([^|\n]*)\|)?\s*([A-Za-z0-9_]+)")

# (start node, label of the first hop, target node) of every branch that ends at the backup node.
# Both branches must visit the pre-flight node on the way — a HITL approval is not a capability probe.
REQUIRED_ROUTES = (
    ("J", "Approve", "K"),
    ("G", "auto", "K"),
)
PREFLIGHT_NODE = "PF"
BACKUP_NODE = "K"


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


def parse_edges(block: str) -> dict[str, list[tuple[str | None, str]]]:
    """Adjacency of the mermaid block: node -> [(label, target)]; the label is None when bare."""
    edges: dict[str, list[tuple[str | None, str]]] = {}
    for line in block.splitlines():
        match = EDGE_RE.match(line)
        if not match:
            continue
        source, label, target = match.group(1), match.group(2), match.group(3)
        edges.setdefault(source, []).append((label.strip() if label else None, target))
    return edges


def first_route(edges: dict[str, list[tuple[str | None, str]]], start: str, label: str,
                target: str) -> list[str] | None:
    """Shortest node sequence start -> target; the FIRST hop must carry `label`, the rest are bare.

    A branch is read as the flowchart draws it: the labelled decision edge (Approve / auto)
    followed by the unlabelled work-package nodes. BFS keeps the walk terminating even though the
    graph has cycles (the error-routing branches loop back to the implement node).
    """
    queue = collections.deque([(start, [start])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        for edge_label, neighbour in edges.get(node, []):
            if node == start:
                if edge_label != label:
                    continue
            elif edge_label is not None:
                continue
            if neighbour in seen:
                continue
            if neighbour == target:
                return path + [neighbour]
            seen.add(neighbour)
            queue.append((neighbour, path + [neighbour]))
    return None


def check_flow(path: pathlib.Path) -> list[str]:
    """Assert every branch reaching the backup node passes through pre-flight first."""
    if not path.exists():
        return [f"{path}: not found"]
    text = path.read_text(encoding="utf-8")
    block = MERMAID_RE.search(text)
    if block is None:
        return [f"{path}: no ```mermaid block — the orchestration flow cannot be checked"]

    edges = parse_edges(block.group(1))
    errors: list[str] = []
    for start, label, target in REQUIRED_ROUTES:
        route = first_route(edges, start, label, target)
        if route is None:
            errors.append(f"{path}: no route {start} --{label}--> ... --> {target} in the "
                          "orchestration flowchart")
            continue
        if PREFLIGHT_NODE not in route:
            errors.append(f"{path}: the {label} branch {' -> '.join(route)} reaches {target} "
                          f"without {PREFLIGHT_NODE} (pre-flight probes the environment first)")

    flat = [(source, edge_label, neighbour)
            for source, neighbours in edges.items() for edge_label, neighbour in neighbours]
    intruders = sorted({source for source, _label, target in flat
                        if target == BACKUP_NODE and source != PREFLIGHT_NODE})
    if intruders:
        errors.append(f"{path}: {BACKUP_NODE} (backup) is entered from {', '.join(intruders)} "
                      f"as well — only {PREFLIGHT_NODE} may lead into it")
    return errors


def main() -> int:
    all_errors: list[str] = []
    for f in PROMPT_FILES:
        if not f.exists():
            all_errors.append(f"{f}: not found")
            continue
        all_errors.extend(check_file(f))

    flow_errors = check_flow(SKILL_FILE)

    if all_errors:
        print("FAIL - prompt structure is NOT append-only safe:", file=sys.stderr)
        for e in all_errors:
            print("  " + e, file=sys.stderr)
    if flow_errors:
        print("FAIL - the orchestration flow violates the pre-flight invariant:", file=sys.stderr)
        for e in flow_errors:
            print("  " + e, file=sys.stderr)
    if all_errors or flow_errors:
        return 1

    print(f"PASS - {len(PROMPT_FILES)} prompt files have a static frontmatter prefix "
          "(static prefix -> dynamic suffix); both branches of the orchestration flow reach the "
          f"backup node through {PREFLIGHT_NODE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  5. NEGATIVE PROBE: the same guard runs over a throwaway copy of SKILL.md whose auto branch is
     re-pointed to reach `K` directly; check_flow MUST report an error naming `PF` there while the
     unmodified file stays silent — a guard that accepts the broken copy is a tautology.
  6. Tool vocabulary: every tool a workflow carrier pins (frontmatter `tools:`/`disallowedTools:`)
     or invokes (backticked PascalCase name, or `call`/`invoke`/`use`/`via` + name) must exist in
     the pinned Kimi Code 2.4.1 tool set — a dead call such as `EnterPlanMode` is reported as
     `file:line`. Reviewed non-tool identifiers are exempted explicitly, never by a loose pattern.
  7. CLI vocabulary: every `--flag` and `/command` of a Kimi / start-launcher command span must be
     classified; the pinned flags, `/skill:code-factory` and the secondary-model env var must stay
     documented.
  8. Approval gate: flow node `I`, `code-factory.md` Phase 3 and planning-guide §6 must each keep
     the plan in `.code-factory/state/plan.md` and ask via `AskUserQuestion`, and no approval
     section may name a plan-mode tool; the flow must keep the route
     `H --> I --> J -->|Approve| PF --> K` and the auto branch.

Exit code 0 = all files OK, 1 = violation (printed to stderr).
"""
from __future__ import annotations

import collections
import pathlib
import re
import shutil
import sys
import tempfile

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
APPROVAL_NODE = "I"     # `I[Present the full plan for approval: ...]` — the HITL approval gate
PLAN_GATE_NODE = "J"    # `J{Plan approved?}` — its Approve edge leads to pre-flight
ENTRY_NODE = "G"        # `G -->|hitl| H` / `G -->|auto| L` — the mode split before the gate

# ---------------------------------------------------------------------------------------------
# Kimi Code 2.4.1 vocabulary and the executable HITL approval gate (review finding major 6)
# ---------------------------------------------------------------------------------------------
# The tool set of Kimi Code 2.4.1, padded out exactly. A name outside it is either a typo or a tool
# the CLI no longer ships: `EnterPlanMode` is gone (plan mode is user-only — Shift-Tab or `/plan`),
# so an agent following such an instruction hits a dead call BEFORE the approval gate.
# `ExitPlanMode` survives in the set, but it only leaves a plan mode the USER entered; on its own it
# approves nothing, which is why the gate below is a plan FILE plus an explicit question.
KIMI_2_4_1_TOOLS = frozenset({
    "Agent", "AgentSwarm", "AskUserQuestion", "Bash", "CreateGoal", "CronCreate", "CronDelete",
    "CronList", "Edit", "ExitPlanMode", "FetchURL", "GetGoal", "Glob", "Grep", "Read",
    "ReadMediaFile", "SetGoalBudget", "Skill", "TaskList", "TaskOutput", "TaskStop", "TodoList",
    "UpdateGoal", "WaitFor", "WebSearch", "Write",
})

# REVIEWED exemptions: backticked identifiers that LOOK like tool names but are not tools. Every
# entry says what it really is — this set is never a place to park a dead tool.
NON_TOOL_IDENTIFIERS = frozenset({
    "CloudFormation",       # an IaC template family in the security-audit artifact table
    "FeedError",            # an error family `error_router.py` routes (learned pattern)
    "ModuleNotFound",       # the prefix of the import-error pattern family
    "ModuleNotFoundError",  # the Python exception that pattern family matches
    "UnicodeEncodeError",   # the Python console exception the scripts must not crash with
})

# A project-level MCP server's tools live outside the CLI's built-in set; only the prefix is
# accepted (a bare name could be mistaken for a built-in one).
MCP_TOOL_PREFIX = "mcp__"

# Every prompt/operator carrier whose PROSE names tools, CLI flags or the approval gate. The globs
# are expanded against the tree under test, so a probe can run on a throwaway copy of the carriers.
WORKFLOW_CARRIERS = (
    "AGENTS.md",
    "README.md",
    ".agents/README.md",
    ".example.task.yaml",
    ".agents/agents/code-factory.md",
    ".agents/skills/code-factory/SKILL.md",
    ".agents/skills/code-factory/assets/task-template.yaml",
)
WORKFLOW_CARRIER_GLOBS = (
    ".agents/agents/sub-agents/*.md",
    ".agents/skills/code-factory/references/*.md",
)

# The CLI vocabulary of Kimi Code 2.4.1 and the factory's launchers, pinned: a flag or slash command
# in a command span that is not classified here is rejected — an invented flag is as dead as an
# invented tool. `--auto`/`--yolo`/`--agent-file` and `/skill:code-factory` are documented in the
# carriers and must stay documented; `/plan` is the tool-less way the USER enters plan mode, so it
# is classified without any carrier being obliged to invoke it (the factory never enters plan mode).
CLI_COMMANDS = ("kimi", "start.cmd", "start.sh", "prepare_factory.cmd", "prepare_factory.sh")
PINNED_CLI_FLAGS = frozenset({"--auto", "--yolo", "--agent-file"})
CLI_FLAGS = PINNED_CLI_FLAGS | frozenset({"-m", "-p"})   # the short forms the carriers document
PINNED_SLASH_COMMANDS = frozenset({"/skill:code-factory", "/plan"})
SLASH_COMMANDS = PINNED_SLASH_COMMANDS | frozenset({"/model", "/mcp"})
PINNED_ENV = "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL"

# `kimi --auto` / `./start.sh --auto` / `./<project>/start.sh`: the command token starts a span that
# runs to the end of its line — the span a reader copies into a shell.
COMMAND_SPAN_RE = re.compile(
    r"(?<![\w./-])(?:\./)?(?:<[^>\s]+>/)?(?:"
    + "|".join(re.escape(command) for command in CLI_COMMANDS) + r")\b")
FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
# `/skill:code-factory`, `/plan`; never the `/` of a path. A path keeps a segment after the token
# (`/path/to/your-project`, `~/.kimi-code/config.toml`), which the lookahead rejects.
SLASH_COMMAND_RE = re.compile(r"(?<![\w/.:-])/[a-z][\w-]*(?::[\w-]+)?(?![\w/.-])")
FENCE_RE = re.compile(r"^\s*```")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# A multi-hump PascalCase identifier (`AskUserQuestion`, `ExitPlanMode`, `ModuleNotFoundError`): the
# shape a tool name has. A single-hump name is only judged in frontmatter or in an invocation form.
PASCAL_RE = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+$")
INVOCATION_RE = re.compile(r"\b(?:call|invoke|use|via)\b\s+`?([A-Z][A-Za-z0-9_]*)`?")
TOOL_LIST_KEYS = ("tools", "disallowedTools")

# The executable approval gate — a FILE plus an explicit question, not a plan-mode transition.
PLAN_FILE = ".code-factory/state/plan.md"
APPROVAL_QUESTION_TOOL = "AskUserQuestion"
DEAD_PLAN_TOOLS = ("EnterPlanMode", "ExitPlanMode")

SKILL_CARRIER = ".agents/skills/code-factory/SKILL.md"
AGENT_CARRIER = ".agents/agents/code-factory.md"
PLANNING_GUIDE = ".agents/skills/code-factory/references/planning-guide.md"
REPO_ROOT = FACTORY_ROOT.parent


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


# --------------------------------------------------------------------------------------------
# Tool vocabulary, CLI vocabulary and the executable approval gate (review finding major 6)
# --------------------------------------------------------------------------------------------
def carrier_files(root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    """(path, repo-relative posix path) of every workflow carrier under `root`."""
    rels = list(WORKFLOW_CARRIERS)
    for pattern in WORKFLOW_CARRIER_GLOBS:
        rels.extend(path.relative_to(root).as_posix() for path in sorted(root.glob(pattern)))
    return [(root / rel, rel) for rel in rels]


def frontmatter_tool_entries(text: str) -> list[tuple[int, str]]:
    """(1-based line, name) of every `tools:`/`disallowedTools:` entry of the frontmatter."""
    entries: list[tuple[int, str]] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return entries
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return entries
    listing = False
    for offset, line in enumerate(lines[1:end], start=2):
        if line.strip() and not line[:1].isspace():        # the next top-level frontmatter key
            key = line.split(":", 1)[0].strip() if ":" in line else ""
            listing = key in TOOL_LIST_KEYS
            if listing:
                for item in line.split(":", 1)[1].strip().strip("[]").split(","):
                    if item.strip():
                        entries.append((offset, item.strip().strip("'\"")))
            continue
        if listing and line.strip().startswith("- "):
            name = line.strip()[2:].strip().strip("'\"")
            if name:
                entries.append((offset, name))
    return entries


def _read(root: pathlib.Path, rel: str, problems: list[str]) -> str:
    """The text of `rel` under `root`, or "" plus a problem when the carrier is missing."""
    path = root / rel
    if not path.is_file():
        problems.append(f"{rel}:1: file is missing — the contract cannot be checked")
        return ""
    return path.read_text(encoding="utf-8")


def check_tool_vocabulary(root: pathlib.Path) -> list[str]:
    """Every tool a carrier pins or invokes exists in Kimi Code 2.4.1 — dead calls are named.

    Three statement classes are scanned, because each one can prescribe a call: a sub-agent's
    frontmatter `tools:`/`disallowedTools:` list, a backticked multi-hump PascalCase identifier
    (`ExitPlanMode`), and the invocation forms `call`/`invoke`/`use`/`via` + identifier — which is
    how the dead `call EnterPlanMode` instruction was written. Everything outside the pinned tool
    set is reported as `file:line` unless it is one of the REVIEWED `NON_TOOL_IDENTIFIERS`.
    """
    problems: list[str] = []
    for path, rel in carrier_files(root):
        if not path.is_file():
            problems.append(f"{rel}:1: workflow carrier is missing — the tool vocabulary cannot "
                            "be checked")
            continue
        text = path.read_text(encoding="utf-8")
        candidates: set[tuple[int, str]] = set()
        for lineno, name in frontmatter_tool_entries(text):
            if not name.startswith(MCP_TOOL_PREFIX):       # an MCP server's tools, not the CLI's
                candidates.add((lineno, name))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in BACKTICK_RE.finditer(line):
                token = match.group(1).strip()
                if PASCAL_RE.match(token):                 # the shape a tool name has
                    candidates.add((lineno, token))
            for match in INVOCATION_RE.finditer(line):
                candidates.add((lineno, match.group(1)))
        for lineno, name in sorted(candidates):
            if name in KIMI_2_4_1_TOOLS or name in NON_TOOL_IDENTIFIERS:
                continue
            problems.append(f"{rel}:{lineno}: {name!r} is not a Kimi Code 2.4.1 tool — a dead "
                            "call in the workflow prose (plan mode is user-only: Shift-Tab or "
                            "/plan)")
    return problems


def check_cli_vocabulary(root: pathlib.Path) -> list[str]:
    """Every flag/command of a Kimi or launcher command span is classified, and the pins survive.

    A command span starts at the `kimi`/`start.*`/`prepare_factory.*` token and runs to the end of
    its line — the text a reader copies into a shell — so an unclassified `--flag` in it is an
    invented CLI feature, exactly as dead as an invented tool. A script's OWN flags are never in
    such a span (they follow a `.py`/`git`/`pytest` token), which is why the scan is span-bound
    rather than line-bound. Slash commands are additionally read in code fences, where the carriers
    keep their chat transcripts (`rem in the chat: /skill:code-factory`).
    """
    problems: list[str] = []
    carried: list[str] = []
    for path, rel in carrier_files(root):
        if not path.is_file():
            problems.append(f"{rel}:1: workflow carrier is missing — the CLI vocabulary cannot be "
                            "checked")
            continue
        text = path.read_text(encoding="utf-8")
        carried.append(text)
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            match = COMMAND_SPAN_RE.search(line)
            span = line[match.start():] if match else ""
            for flag in FLAG_RE.findall(span):
                if flag not in CLI_FLAGS:
                    problems.append(f"{rel}:{lineno}: unclassified CLI flag {flag!r} in a command "
                                    "span — the Kimi CLI/launcher vocabulary is pinned "
                                    f"({', '.join(sorted(CLI_FLAGS))})")
            for source in [span] + ([line] if in_fence else []):
                for command in SLASH_COMMAND_RE.findall(source):
                    if command not in SLASH_COMMANDS:
                        problems.append(f"{rel}:{lineno}: unclassified slash command {command!r} — "
                                        "the pinned commands are "
                                        f"{', '.join(sorted(SLASH_COMMANDS))}")

    documented = "\n".join(carried)
    for flag in sorted(PINNED_CLI_FLAGS):
        if flag not in documented:
            problems.append(f"workflow carriers:1: the pinned CLI flag {flag!r} is documented "
                            "nowhere — an automation entry point silently disappeared")
    # `/plan` is deliberately NOT required: plan mode belongs to the USER (Shift-Tab or `/plan`), so
    # no carrier has to invoke it — it only has to be classified, never rejected as invented.
    if "/skill:code-factory" not in documented:
        problems.append("workflow carriers:1: the pinned command '/skill:code-factory' is "
                        "documented nowhere — the factory's only entry point disappeared")
    if PINNED_ENV not in documented:
        problems.append(f"workflow carriers:1: {PINNED_ENV} is pinned by the pre-flight probe and "
                        "must stay documented")
    return problems


def heading_section(text: str, heading_re: str) -> tuple[int, str]:
    """(1-based line, body) of the section a heading opens; (0, "") when the heading is absent."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(heading_re, line)), None)
    if start is None:
        return 0, ""
    body: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^#{1,3}\s", line):
            break
        body.append(line)
    return start + 1, "\n".join(body)


def approval_node_body(text: str) -> tuple[int, str]:
    """(1-based line, body) of the `H --> I[...]` approval node of the mermaid flow."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*H\s*-->\s*I\[(.*)\]\s*$", line)
        if match:
            return lineno, match.group(1)
    return 0, ""


def _plan_gate_problems(rel: str, line: int, body: str, what: str) -> list[str]:
    """The three demands on an approval section: the plan FILE, the QUESTION, no plan-mode tool."""
    if not body:
        return [f"{rel}:1: no {what} — the approval gate cannot be checked"]
    problems: list[str] = []
    for needle, why in ((PLAN_FILE, "keep the plan in the plan file"),
                        (APPROVAL_QUESTION_TOOL, "ask the user explicitly via the question tool")):
        if needle not in body:
            problems.append(f"{rel}:{line}: {what} must {why} ({needle})")
    for dead in DEAD_PLAN_TOOLS:
        if dead in body:
            problems.append(f"{rel}:{line}: {what} invokes {dead} — Kimi Code 2.4.1 has no "
                            "plan-mode tool; the gate is the plan file plus an explicit question")
    return problems


def check_plan_approval(root: pathlib.Path) -> list[str]:
    """The HITL gate is `.code-factory/state/plan.md` + AskUserQuestion in all three carriers.

    Kimi Code 2.4.1 plan mode is USER-only (Shift-Tab or `/plan`): there is no `EnterPlanMode` tool,
    and `ExitPlanMode` outside a user-entered plan mode approves nothing. The executable gate is
    therefore the plan FILE plus an explicit question, and the flow has to keep routing it
    (H --> I --> J -->|Approve| PF --> K) while the auto branch stays reachable.

    SCOPE: the ban on the two plan-mode tools applies to the APPROVAL SECTION of each carrier (flow
    node I, Phase 3, planning-guide §6), never to whole files. `ExitPlanMode` is a real tool: it is
    part of the pinned vocabulary of this very test and legitimately appears where plan mode is
    described as a USER action, so a whole-file ban would outlaw an honest mention instead of a dead
    instruction.
    """
    problems: list[str] = []
    skill = _read(root, SKILL_CARRIER, problems)
    line, body = approval_node_body(skill)
    problems.extend(_plan_gate_problems(SKILL_CARRIER, line, body, f"flow node {APPROVAL_NODE}"))

    agent = _read(root, AGENT_CARRIER, problems)
    line, body = heading_section(agent, r"^###\s+Phase 3\b")
    problems.extend(_plan_gate_problems(AGENT_CARRIER, line, body, "Phase 3"))

    guide = _read(root, PLANNING_GUIDE, problems)
    line, body = heading_section(guide, r"^##\s+6\.\s")
    problems.extend(_plan_gate_problems(PLANNING_GUIDE, line, body, "planning-guide §6"))

    block = MERMAID_RE.search(skill)
    if block is None:
        problems.append(f"{SKILL_CARRIER}: no ```mermaid block — the approval route cannot be read")
        return problems
    edges = parse_edges(block.group(1))
    for source, target in (("H", APPROVAL_NODE), (APPROVAL_NODE, PLAN_GATE_NODE),
                           (PLAN_GATE_NODE, PREFLIGHT_NODE), (PREFLIGHT_NODE, BACKUP_NODE)):
        label = "Approve" if (source, target) == (PLAN_GATE_NODE, PREFLIGHT_NODE) else None
        if not any(neighbour == target and edge_label == label
                   for edge_label, neighbour in edges.get(source, [])):
            hop = f"{source} -->|{label}| {target}" if label else f"{source} --> {target}"
            problems.append(f"{SKILL_CARRIER}: the approval route lost the edge `{hop}` "
                            "(required: H --> I --> J -->|Approve| PF --> K)")
    if first_route(edges, ENTRY_NODE, "auto", BACKUP_NODE) is None:
        problems.append(f"{SKILL_CARRIER}: the auto route {ENTRY_NODE} --auto--> ... --> "
                        f"{BACKUP_NODE} is gone — the non-interactive branch must stay")
    return problems


def negative_probe() -> None:
    """NEGATIVE PROBE: the flow guard must be able to fail.

    A throwaway copy of SKILL.md gets its auto branch re-pointed so it reaches the backup node
    WITHOUT the pre-flight node — the exact regression the guard exists to catch. check_flow MUST
    report an error naming the pre-flight node for the broken copy and stay silent for the
    unmodified file; a guard that accepts the broken copy is a tautology, and that fails HERE.
    """
    text = SKILL_FILE.read_text(encoding="utf-8")
    old, new = "L --> PF[", "L --> K["
    if old not in text:
        raise AssertionError(f"probe setup: {SKILL_FILE} carries no {old!r} edge — the probe "
                             "would be a no-op, not a vaccination")
    with tempfile.TemporaryDirectory() as raw_tmp:
        broken = pathlib.Path(raw_tmp) / "SKILL.md"
        broken.write_text(text.replace(old, new), encoding="utf-8")
        errors = check_flow(broken)
    if not errors:
        raise AssertionError("probe: check_flow ACCEPTED a SKILL.md whose auto branch reaches "
                             f"{BACKUP_NODE} without {PREFLIGHT_NODE} — the assertion is a "
                             "tautology")
    if not any(f"without {PREFLIGHT_NODE}" in error for error in errors):
        raise AssertionError(f"probe: check_flow failed for the wrong reason (expected an error "
                             f"naming {PREFLIGHT_NODE}): {errors}")
    if check_flow(SKILL_FILE):
        raise AssertionError(f"probe: the UNMODIFIED {SKILL_FILE} must stay silent: "
                             f"{check_flow(SKILL_FILE)}")


def _carrier_tree(dst: pathlib.Path) -> pathlib.Path:
    """A throwaway root holding copies of every workflow carrier, so a check can run on it."""
    for path, rel in carrier_files(REPO_ROOT):
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return dst


def _broken_carrier(check, rel: str, mutate, expected: str) -> None:
    """Break one carrier on a throwaway tree; `check` MUST report `expected` there."""
    broken_text = mutate((REPO_ROOT / rel).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as raw_tmp:
        tree = _carrier_tree(pathlib.Path(raw_tmp) / "repo")
        (tree / rel).write_text(broken_text, encoding="utf-8")
        found = check(tree)
    if not found:
        raise AssertionError(f"probe {rel}: the checker ACCEPTED the broken carrier — the "
                             "assertion is a tautology")
    report = "\n".join(found)
    if expected not in report:
        raise AssertionError(f"probe {rel}: the checker failed for the wrong reason (expected "
                             f"{expected!r}): {report}")


def insert_after(text: str, needle: str, extra: str) -> str:
    """`text` with `extra` on its own line directly after the first line containing `needle`."""
    lines = text.splitlines()
    index = next((i for i, line in enumerate(lines) if needle in line), None)
    if index is None:
        raise AssertionError(f"probe setup: no line contains {needle!r} — the probe would be a "
                             "no-op, not a vaccination")
    lines.insert(index + 1, extra)
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str) -> str:
    """`text` with its first `old` replaced by `new`; a missing `old` makes the probe a no-op."""
    if old not in text:
        raise AssertionError(f"probe setup: the carrier does not contain {old!r} — the probe "
                             "would be a no-op, not a vaccination")
    return text.replace(old, new, 1)


def vocabulary_probes() -> None:
    """NEGATIVE PROBES: the vocabulary and approval-gate checks must be able to fail.

    Each probe re-introduces exactly ONE regression on a throwaway copy of the carriers: the dead
    plan-mode instruction inside Phase 3, the question tool removed from flow node I, an invented
    tool in a sub-agent's `tools:` list, and an invented CLI flag in a `kimi` command span. Every
    one MUST be reported while the corrected real tree stays silent — otherwise the checks are
    tautologies.
    """
    _broken_carrier(check_plan_approval, AGENT_CARRIER,
                    lambda text: insert_after(text, "### Phase 3",
                                              "Present the plan via `EnterPlanMode` + "
                                              "`ExitPlanMode` and WAIT for approval."),
                    "EnterPlanMode")
    _broken_carrier(check_plan_approval, SKILL_CARRIER,
                    lambda text: replace_once(text, "via AskUserQuestion whether to approve",
                                              "whether to approve"),
                    "AskUserQuestion")
    _broken_carrier(check_tool_vocabulary, ".agents/agents/sub-agents/coder.md",
                    lambda text: insert_after(text, "tools:", "  - EnterPlanMode"), "EnterPlanMode")
    _broken_carrier(check_cli_vocabulary, "AGENTS.md",
                    lambda text: replace_once(text, "`kimi --auto`", "`kimi --turbo`"), "--turbo")
    for check in (check_plan_approval, check_tool_vocabulary, check_cli_vocabulary):
        errors = check(REPO_ROOT)
        if errors:
            raise AssertionError(f"probe: the CORRECTED real tree must pass {check.__name__}: "
                                 f"{errors}")


def main() -> int:
    all_errors: list[str] = []
    for f in PROMPT_FILES:
        if not f.exists():
            all_errors.append(f"{f}: not found")
            continue
        all_errors.extend(check_file(f))

    flow_errors = check_flow(SKILL_FILE)
    vocabulary_errors = check_tool_vocabulary(REPO_ROOT)
    cli_errors = check_cli_vocabulary(REPO_ROOT)
    approval_errors = check_plan_approval(REPO_ROOT)
    negative_probe()
    vocabulary_probes()

    if all_errors:
        print("FAIL - prompt structure is NOT append-only safe:", file=sys.stderr)
        for e in all_errors:
            print("  " + e, file=sys.stderr)
    if flow_errors:
        print("FAIL - the orchestration flow violates the pre-flight invariant:", file=sys.stderr)
        for e in flow_errors:
            print("  " + e, file=sys.stderr)
    if vocabulary_errors:
        print("FAIL - the workflow prose names a tool that Kimi Code 2.4.1 does not ship:",
              file=sys.stderr)
        for e in vocabulary_errors:
            print("  " + e, file=sys.stderr)
    if cli_errors:
        print("FAIL - the workflow prose names an unclassified CLI flag or command:",
              file=sys.stderr)
        for e in cli_errors:
            print("  " + e, file=sys.stderr)
    if approval_errors:
        print("FAIL - the executable HITL approval gate is broken:", file=sys.stderr)
        for e in approval_errors:
            print("  " + e, file=sys.stderr)
    if all_errors or flow_errors or vocabulary_errors or cli_errors or approval_errors:
        return 1

    print(f"PASS - {len(PROMPT_FILES)} prompt files have a static frontmatter prefix "
          "(static prefix -> dynamic suffix); both branches of the orchestration flow reach the "
          f"backup node through {PREFLIGHT_NODE}; every tool the workflow prose names exists in "
          "Kimi Code 2.4.1; every CLI flag/command of a Kimi or launcher command span is "
          "classified; the HITL gate is the plan file plus an explicit question in node I, Phase 3 "
          "and planning-guide §6 — and the negative probes prove each guard can fail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

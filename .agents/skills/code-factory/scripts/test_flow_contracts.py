#!/usr/bin/env python3
"""
Text-contract self-test for the factory flow (zero LLM tokens, stdlib only).

Several promises of this release live in PROSE that no other test reads: the Finish node of the
orchestration flow must really invoke compaction, the memory gate and the model attribution; the
precedent index must be BUILT by the flow and described as a build product; the briefing template
must carry the memory facts; the task templates must agree with the rulebook; the model precedence
must not be restated in a third voice; and the memory contract must have exactly ONE
implementation. Nothing else reads that prose, so a careless edit could delete the wiring while
every other self-test stayed green.

The reviewer CALIBRATION gate is pinned the same way (`references/code-review.md` §7): the review
nodes `CR`/`CR0` of the flow must invoke `calibrate_reviewer.py status` BEFORE the reviewer, name
the golden-set calibration that discharges a due one and the append-only log it writes, and the
agent instruction (Phase 8b) and the reference must carry the invocation too — a gate nobody runs
protects nothing.

The Advisor agreement gate is pinned the same way (flow nodes `ADR`/`ARO`): the Advisor's verdict is
the AGREEMENT first and the recommended role only inside the `agree` edge, so the documented
disagreement path — show both diagnoses in hitl, stop the fix loop and record it in `report.md` in
auto — stays reachable in the flowchart an agent actually follows. Three routing/operator contracts
follow the same rule: the §2 table may not keep a `WRONG_RESULTS` -> CODER row the JSON-first router
never takes, the provider guide may not send model/format to PLANNER, and the operator manual must
describe the executable HITL gate (the plan file plus `AskUserQuestion`) instead of the abstract
`presents the plan for approval`.

The conditional Farukon path is pinned the same way: every carrier of its Web GUI twin — the
reference-file list, the specialist roster, the `--farukon` pre-flight probe, the routing sentence of
the implement node, `models.farukon_expert` and its `models_used.farukon_expert` logging, the
tester-owned replay acceptance and the infrastructure rows F1–F2 — must exist where the mechanism
lives, and the reference file itself must state the safety and degradation defaults.

This test pins those strings — always against the REAL shipped file — and then proves the pins are
not tautologies: each contract is broken on a throwaway copy in the way a careless future edit
would break it (delete the command name, restore `open: 0`, drop the `Memory facts` heading, drop
`repo_path` required, re-add `warning, not a blocker`, re-add `_validate_entry`, rename the
calibration command, re-branch the Advisor on its recommended role, re-add the dead routing rows,
drop the question tool from the manual, unwire the Farukon routing), and the checker must FAIL on
that copy.

Invariant: every command and every constraint pinned below is present in the shipped file, at the
place where the mechanism lives (a flow node, a named section, a template block) — absence, or a
restored old wording, is reported as `<file>:<line>: <what is missing>`.

Exit code 0 = every contract holds and every probe is caught, 1 = a contract or a probe failed.
"""
from __future__ import annotations

import collections
import pathlib
import re
import shutil
import sys
import tempfile

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

SKILL = ".agents/skills/code-factory/SKILL.md"
CODE_FACTORY = ".agents/agents/code-factory.md"
AGENTS = "AGENTS.md"
README = ".agents/README.md"
BRIEFING = ".agents/skills/code-factory/references/handoff-briefing.md"
PROVIDERS = ".agents/skills/code-factory/references/providers.md"
ERROR_ROUTING = ".agents/skills/code-factory/references/error-routing.md"
EXAMPLE_TASK = ".example.task.yaml"
TASK_TEMPLATE = ".agents/skills/code-factory/assets/task-template.yaml"
CHECK_MODEL = ".agents/skills/code-factory/scripts/check_factory_model.py"
MEMORY = ".agents/skills/code-factory/scripts/memory_project.py"
ENGLISH = ".agents/skills/code-factory/scripts/check_english_only.py"
RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
CODE_REVIEW = ".agents/skills/code-factory/references/code-review.md"
FARUKON_REF = ".agents/skills/code-factory/references/farukon-mcp.md"
DELEGATION_GATE = ".agents/skills/code-factory/scripts/delegation_gate.py"
TESTER = ".agents/agents/sub-agents/tester.md"

# Every file a contract reads: a probe copies exactly these, then breaks one of them.
FILES = (SKILL, CODE_FACTORY, AGENTS, README, BRIEFING, PROVIDERS, ERROR_ROUTING, EXAMPLE_TASK,
         TASK_TEMPLATE, CHECK_MODEL, MEMORY, ENGLISH, RULEBOOK, CODE_REVIEW, FARUKON_REF,
         DELEGATION_GATE, TESTER)

FINISH_NODE = "Y"      # `Y[Finish: ...]` — the only place compaction/attribution are invoked
CODER_NODE = "M"       # `M[Implement: ...]` — the coder delegation and its briefing
PREFLIGHT_NODE = "PF"  # `PF[Pre-flight: ...]` — where the model matrix is resolved
ACCEPTANCE_NODE = "S"  # `S[Business tests: ...]` — where acceptance is owned by the tester

# The Advisor gate: the agreement decision, and the role decision INSIDE `agree`.
ADVISOR_NODE = "ADR"
ADVISOR_ROLE_NODE = "ARO"
ADVISOR_ROLE_EDGES = (("coder", "P"), ("ba", "P2"), ("planner", "P2"),
                      ("infrastructure", "AI"), ("human", "U2"))
# (mode, target, what the disagreement branch must do) of the two `disagree` edges.
ADVISOR_DISAGREE_EDGES = (("hitl", "U2", "show both diagnoses to the user"),
                          ("auto", "Y",
                           "stop the fix loop and record the disagreement in report.md"))

MERMAID_FENCE = "```mermaid"
# `Y[body]` / `PF(body)` / `DOC{body}`; the leading class keeps an arrow or an edge label from
# being read as part of a node id.
NODE_RE = re.compile(r"(?:^|[\s>|])([A-Za-z][A-Za-z0-9_]*)\s*([\[\{\(])")
CLOSING = {"[": "]", "{": "}", "(": ")"}
# `ADR -->|agree| ARO{...}` / `ADR -->|disagree, hitl| U2`: source, optional label, raw target.
EDGE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*-->\s*(?:\|([^|\n]*)\|)?\s*(\S.*)$")
Edge = collections.namedtuple("Edge", "line source label target")

FACTORY_RULE_BLOCK_RE = re.compile(
    r"<!--\s*factory-rule:[^>]*?begin\s*-->.*?<!--\s*factory-rule:[^>]*?end\s*-->", re.S)
# The mermaid flow is not "surrounding prose": a node is checked as a node, never as prose.
MERMAID_BLOCK_RE = re.compile(
    rf"^[ \t]*{re.escape(MERMAID_FENCE)}[ \t]*$[\s\S]*?^[ \t]*```[ \t]*$", re.M)
MEMORY_FACTS_HEADING_RE = re.compile(r"^#{2,4}\s+Memory facts\s*$", re.I)
OPEN_ZERO_RE = re.compile(r"open\s*:\s*0(?!\d)")
NEGATION_RE = re.compile(
    r"\b(?:never|not|no longer|instead of|rather than|forbidden|invalid|rejected)\b", re.I)
# `memory_project.py check` must be paired with `--run-id`: a check without the run id cannot
# require exactly ONE record for this run.
RUN_ID_RE = re.compile(r"memory_project\.py\s+check\b(.{0,200})", re.S)


# --------------------------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------------------------
def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so a comparison report survives a legacy Windows console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def prose_only(doc: "Doc") -> "Doc":
    """The document without its `factory-rule` blocks and without the mermaid flow."""
    return doc.stripped(FACTORY_RULE_BLOCK_RE).stripped(MERMAID_BLOCK_RE)


class Doc:
    """One shipped file, with the line-number and paragraph lookups the contracts need."""

    def __init__(self, rel: str, text: str):
        self.rel = rel
        self.text = text
        self.lines = text.splitlines()

    @classmethod
    def load(cls, root: pathlib.Path, rel: str, problems: list[str]) -> "Doc":
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}:1: file is missing — the contract cannot be pinned")
            return cls(rel, "")
        return cls(rel, path.read_text(encoding="utf-8"))

    def line_of(self, index: int) -> int:
        """1-based line number of a character offset."""
        return self.text.count("\n", 0, max(0, index)) + 1

    def paragraphs(self) -> list[tuple[int, str]]:
        """(1-based line of its first line, text) for every block separated by a blank line."""
        blocks: list[tuple[int, str]] = []
        start: int | None = None
        buffer: list[str] = []
        for i, line in enumerate(self.lines):
            if line.strip():
                if start is None:
                    start = i + 1
                buffer.append(line)
            elif start is not None:
                blocks.append((start, "\n".join(buffer)))
                start, buffer = None, []
        if start is not None:
            blocks.append((start, "\n".join(buffer)))
        return blocks

    def stripped(self, pattern: re.Pattern[str]) -> "Doc":
        """A view with every match of `pattern` blanked out, line numbers preserved."""
        blanked = pattern.sub(lambda m: "\n" * m.group(0).count("\n"), self.text)
        return Doc(self.rel, blanked)


def node_body(line: str, open_index: int) -> str:
    """The text between the node's brackets, nesting counted (a node may hold `[--config x]`)."""
    stack: list[str] = []
    for k in range(open_index, len(line)):
        char = line[k]
        if char in CLOSING:
            stack.append(CLOSING[char])
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return line[open_index + 1:k]
    return line[open_index + 1:]      # unbalanced in prose: take the rest of the line


def flow_nodes(doc: Doc) -> tuple[int, list[tuple[int, str, str]]]:
    """(1-based line of the first block line, [(line, id, body), ...]); 0 = no mermaid block."""
    fence = next((i for i, line in enumerate(doc.lines) if line.strip() == MERMAID_FENCE), None)
    if fence is None:
        return 0, []
    first = fence + 2                                     # the fence itself is `fence + 1`
    nodes: list[tuple[int, str, str]] = []
    for offset, line in enumerate(doc.lines[fence + 1:]):
        if line.strip() == "```":
            break
        for match in NODE_RE.finditer(line):
            nodes.append((first + offset, match.group(1), node_body(line, match.start(2))))
    return first, nodes


def find_node(doc: Doc, node_id: str) -> tuple[int, str]:
    """(1-based line, body) of the definition of `node_id`; (0, "") when the node is absent."""
    _first, nodes = flow_nodes(doc)
    for line, ident, body in nodes:
        if ident == node_id:
            return line, body
    return 0, ""


def flow_edges(doc: Doc) -> tuple[int, list["Edge"]]:
    """(1-based line of the flow's first block line, every edge); 0 = no mermaid block.

    An edge is read as `source -->|label| target`, the target being its LEADING identifier, so a
    node definition (`P[Rollback: ...]`) and a bare reference (`P`) name the same node.
    """
    fence = next((i for i, line in enumerate(doc.lines) if line.strip() == MERMAID_FENCE), None)
    if fence is None:
        return 0, []
    edges: list[Edge] = []
    for offset, line in enumerate(doc.lines[fence + 1:]):
        if line.strip() == "```":
            break
        match = EDGE_RE.match(line.strip())
        if match:
            target = re.match(r"[A-Za-z][A-Za-z0-9_]*", match.group(3))
            edges.append(Edge(fence + 2 + offset, match.group(1),
                              match.group(2).strip() if match.group(2) else None,
                              target.group(0) if target else ""))
    return fence + 2, edges


def edges_from(doc: Doc, source: str) -> list["Edge"]:
    """Every edge out of `source` in the flow."""
    return [edge for edge in flow_edges(doc)[1] if edge.source == source]


def open_zero_demands(body: str) -> list[str]:
    """Fragments of `body` that demand `open: 0` without negating it (the old, wrong contract)."""
    demands: list[str] = []
    for match in OPEN_ZERO_RE.finditer(body):
        clause = re.split(r"[.;]\s+|—\s*", body[:match.start()])[-1]
        if not NEGATION_RE.search(clause):
            demands.append(body[max(0, match.start() - 50):match.end() + 50].replace("\n", " "))
    return demands


def indented_block(doc: Doc, key: str) -> list[tuple[int, str]]:
    """(1-based line, line) of the indented body of a top-level `key:` entry, comments skipped."""
    body: list[tuple[int, str]] = []
    started = False
    for i, line in enumerate(doc.lines):
        if not started:
            if re.match(rf"^{re.escape(key)}\s*:", line):
                started = True
            continue
        if not line.strip():
            continue
        if re.match(r"^\S", line):                       # the next top-level key ends the block
            break
        if line.lstrip().startswith("#"):
            continue
        body.append((i + 1, line))
    return body


# --------------------------------------------------------------------------------------------
# A. The Finish node wires the memory mechanisms
# --------------------------------------------------------------------------------------------
def check_finish_node(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    line, body = find_node(skill, FINISH_NODE)
    if not body:
        problems.append(f"{SKILL}:1: no Finish node `{FINISH_NODE}[...]` in the mermaid flow")
    else:
        for needle, what in (("memory_project.py compact",
                              "the compaction command `memory_project.py compact`"),
                             ("model_attribution.py",
                              "the model-attribution command `model_attribution.py`"),
                             ("memory_project.py backlog",
                              "the finish-gate command `memory_project.py backlog --check`")):
            if needle not in body:
                problems.append(f"{SKILL}:{line}: the Finish node must invoke {what}")
        if "memory_project.py check" not in body:
            problems.append(f"{SKILL}:{line}: the Finish node must close the memory gate with "
                            "`memory_project.py check`")
        elif not any("--run-id" in found.group(1) for found in RUN_ID_RE.finditer(body)):
            problems.append(f"{SKILL}:{line}: `memory_project.py check` in the Finish node must "
                            "carry `--run-id <run_id>` (exactly ONE record for this run)")
        for fragment in open_zero_demands(body):
            problems.append(f"{SKILL}:{line}: the Finish node must NOT demand that `backlog "
                            f"--check` mean `open: 0` (a carried item is legal): {fragment!r}")

    # The agent instruction names the same three commands (the role card is what the main agent
    # actually reads while closing the run).
    card = Doc.load(root, CODE_FACTORY, problems)
    for needle, what in (("memory_project.py compact", "`memory_project.py compact`"),
                         ("model_attribution.py", "`model_attribution.py`")):
        if needle not in card.text:
            problems.append(f"{CODE_FACTORY}:1: the agent instruction must name {what} too")
    checks = list(RUN_ID_RE.finditer(card.text))
    if not checks:
        problems.append(f"{CODE_FACTORY}:1: the agent instruction must name "
                        "`memory_project.py check`")
    elif not any("--run-id" in found.group(1) for found in checks):
        problems.append(f"{CODE_FACTORY}:{card.line_of(checks[0].start())}: "
                        "`memory_project.py check` must be paired with `--run-id <run_id>`")
    return problems


# --------------------------------------------------------------------------------------------
# B. The precedent index is built by the flow
# --------------------------------------------------------------------------------------------
def check_precedent_index(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    first, nodes = flow_nodes(skill)
    if not nodes:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the index build cannot be wired into it")
    elif not any("precedent_index.py build" in body and "--fresh" in body
                 for _line, _ident, body in nodes):
        problems.append(f"{SKILL}:{first}: no flow node names both `precedent_index.py build` and "
                        "`--fresh` — the index must be BUILT by the flow, not only described in "
                        "prose outside the mermaid block")

    for rel in (AGENTS, README):
        doc = Doc.load(root, rel, problems)
        described = [(line, text) for line, text in doc.paragraphs() if "precedents.db" in text]
        if not described:
            problems.append(f"{rel}:1: the precedent index `state/precedents.db` is not described")
            continue
        built = [(line, text) for line, text in described if re.search(r"\bbuild", text, re.I)]
        if not built:
            problems.append(f"{rel}:{described[0][0]}: `state/precedents.db` must be described as "
                            "a BUILD product (the word `build` in the same paragraph), not as "
                            "standing runtime state")
            continue
        named = "precedent_index.py build" in doc.text or all(
            word in " ".join(text for _line, text in built) for word in ("build", "status"))
        if not named:
            problems.append(f"{rel}:{built[0][0]}: the description must name the command that "
                            "builds the index (`precedent_index.py build`) and its `status`")
    return problems


# --------------------------------------------------------------------------------------------
# C. The briefing carries memory facts
# --------------------------------------------------------------------------------------------
def check_briefing_memory_facts(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    briefing = Doc.load(root, BRIEFING, problems)
    heading = next((i for i, line in enumerate(briefing.lines)
                    if MEMORY_FACTS_HEADING_RE.match(line.strip())), None)
    if heading is None:
        problems.append(f"{BRIEFING}:1: the briefing template must carry a `Memory facts` section "
                        "heading (a subagent must never re-derive the project's history)")
    else:
        body = []
        for line in briefing.lines[heading + 1:]:
            if line.lstrip().startswith("#"):
                break
            body.append(line)
        if "open backlog" not in "\n".join(body).lower():
            problems.append(f"{BRIEFING}:{heading + 1}: the `Memory facts` section must name the "
                            "`open backlog` items it carries")

    skill = Doc.load(root, SKILL, problems)
    line, body = find_node(skill, CODER_NODE)
    coder_ok = bool(body) and all(word in body.lower() for word in
                                  ("briefing", "memory facts", "open backlog"))
    if not coder_ok:
        prose_ok = any("briefing" in text.lower()
                       and ("memory facts" in text.lower() or "open backlog" in text.lower())
                       for _line, text in prose_only(skill).paragraphs())
        if not prose_ok:
            where = f"{SKILL}:{line}" if line else f"{SKILL}:1"
            problems.append(f"{where}: the coder node (or the prose around it) must say that a "
                            "briefing carries the memory facts / open backlog")
    return problems


# --------------------------------------------------------------------------------------------
# D. The templates agree with the rulebook
# --------------------------------------------------------------------------------------------
def check_templates(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    example = Doc.load(root, EXAMPLE_TASK, problems)
    if not any(_says_repo_path_required(text) for _line, text in example.paragraphs()):
        problems.append(f"{EXAMPLE_TASK}:1: `repo_path` must be stated as REQUIRED for every task "
                        "except a green-field one (a missing field is a parsing error)")
    criteria = indented_block(example, "acceptance_criteria")
    if not criteria:
        problems.append(f"{EXAMPLE_TASK}:1: the example must carry an `acceptance_criteria` block "
                        "with a `verify:` and a `derived: true` criterion")
    else:
        if not any(re.match(r"^\s+verify\s*:\s*\S", text) for _line, text in criteria):
            problems.append(f"{EXAMPLE_TASK}:{criteria[0][0]}: at least one criterion must carry "
                            "`verify:` (a command executed for real)")
        if not any(re.match(r"^\s+derived\s*:\s*true\b", text, re.I) for _line, text in criteria):
            problems.append(f"{EXAMPLE_TASK}:{criteria[0][0]}: at least one criterion must be "
                            "marked `derived: true`")
    for words, what in ((("report-only", "review"),
                         "`review` must be described as REPORT-ONLY"),
                        (("follow-up task file", "review"),
                         "`review` must deliver a follow-up task file"),
                        (("unmodified tree", "review"),
                         "a `review` criterion must be satisfiable on the UNMODIFIED tree")):
        if not any(all(word in text.lower() for word in words)
                   for _line, text in example.paragraphs()):
            problems.append(f"{EXAMPLE_TASK}:1: {what}")

    template = Doc.load(root, TASK_TEMPLATE, problems)
    if not any("review" in text.lower() and "verify" in text.lower()
               and "unmodified" in text.lower() for _line, text in template.paragraphs()):
        problems.append(f"{TASK_TEMPLATE}:1: the template must state that in a `task_type: review` "
                        "task every `verify` must hold on the UNMODIFIED tree")
    if "review_followup_task.py" not in template.text:
        problems.append(f"{TASK_TEMPLATE}:1: the template must name `review_followup_task.py`, the "
                        "generator of the review's follow-up task file")
    return problems


def _says_repo_path_required(paragraph: str) -> bool:
    """A sentence that makes `repo_path` required and carves out the green-field case."""
    for sentence in re.split(r"[.;]\s+", paragraph):
        if "repo_path" not in sentence.lower():
            continue
        if re.search(r"\brequired\b", sentence, re.I) and re.search(r"green[- ]?field",
                                                                    sentence, re.I):
            return True
    return False


# --------------------------------------------------------------------------------------------
# E. Model precedence is not restated in three voices
# --------------------------------------------------------------------------------------------
def check_model_precedence(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    providers = Doc.load(root, PROVIDERS, problems)
    for needle in ("model_matrix.py", "model_attribution.py"):
        if needle not in providers.text:
            problems.append(f"{PROVIDERS}:1: the document must name `{needle}` — the precedence has "
                            "one implementation and one proof, never three voices")
    stripped = providers.stripped(FACTORY_RULE_BLOCK_RE)
    for line, text in stripped.paragraphs():
        lowered = text.lower()
        if re.search(r"warning,\s*not a blocker", lowered):
            problems.append(f"{PROVIDERS}:{line}: `warning, not a blocker` is the retired wording "
                            "of the precedence rule — the task matrix case is an ERROR/warning "
                            "decided by the resolver, not a third voice")
        if "deterministic" in lowered and "famil" in lowered and "model_matrix.py" not in text:
            problems.append(f"{PROVIDERS}:{line}: the family check may not be called deterministic "
                            "without naming its resolver (`scripts/model_matrix.py`)")

    skill = Doc.load(root, SKILL, problems)
    line, body = find_node(skill, PREFLIGHT_NODE)
    if not body:
        problems.append(f"{SKILL}:1: no pre-flight node `{PREFLIGHT_NODE}[...]` in the mermaid "
                        "flow")
    elif "model_matrix.py resolve" not in body:
        problems.append(f"{SKILL}:{line}: the pre-flight node must resolve the matrix by command "
                        "(`model_matrix.py resolve`), never by hand")
    return problems


# --------------------------------------------------------------------------------------------
# F. The memory contract is single
# --------------------------------------------------------------------------------------------
def check_single_memory_contract(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    model = Doc.load(root, CHECK_MODEL, problems)
    if not re.search(r"^[ \t]*(?:import\s+memory_project\b|from\s+memory_project\s+import\b)",
                     model.text, re.M):
        problems.append(f"{CHECK_MODEL}:1: must import `memory_project` — the per-entry contract "
                        "has ONE implementation")
    for match in re.finditer(r"^[ \t]*def\s+_validate_entry\b", model.text, re.M):
        problems.append(f"{CHECK_MODEL}:{model.line_of(match.start())}: must NOT define its own "
                        "`_validate_entry` — that copy is what made the two entry points diverge")

    memory = Doc.load(root, MEMORY, problems)
    if not re.search(r"^[ \t]*def\s+validate_memory\b", memory.text, re.M):
        problems.append(f"{MEMORY}:1: must define `validate_memory`, the single entry validator")

    english = Doc.load(root, ENGLISH, problems)
    if not re.search(r"^[ \t]*(?:import\s+memory_project\b|from\s+memory_project\s+import\b)",
                     english.text, re.M):
        problems.append(f"{ENGLISH}:1: must import `memory_project` (the journal is parsed into "
                        "records by the sibling helpers, not by a second parser)")
    if "english-freeze" not in english.text:
        problems.append(f"{ENGLISH}:1: must honour `memory/.english-freeze` — frozen history is "
                        "never re-judged")
    if "--no-memory" not in english.text:
        problems.append(f"{ENGLISH}:1: must offer the documented escape `--no-memory`")
    elif not re.search(r'"--no-memory"\s*,[\s\S]{0,40}?action\s*=\s*"store_true"',
                       english.text):
        problems.append(f"{ENGLISH}:1: the memory pass must run BY DEFAULT — `--no-memory` is an "
                        "opt-out flag, not an opt-in one")
    return problems


# --------------------------------------------------------------------------------------------
# G. The destructive-action gate is run by the flow, not only shipped
# --------------------------------------------------------------------------------------------
def check_destructive_action_gate(root: pathlib.Path) -> list[str]:
    """A shipped safety control must be INVOKED by the governed flow, and the rule must be quoted.

    The finding this pins: `action_gate.py` was advertised in the layout lists while no flow node,
    no phase and no rule told the main agent to call it — a safety control that protected nothing.
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    first, nodes = flow_nodes(skill)
    if not nodes:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the destructive-action gate cannot be "
                        "wired into it")
    else:
        preflight = [(line, body) for line, ident, body in nodes if ident == PREFLIGHT_NODE]
        if not preflight:
            problems.append(f"{SKILL}:{first}: no pre-flight node `{PREFLIGHT_NODE}[...]` — the gate "
                            "has no phase to run in")
        elif not any("action_gate.py check" in body for _line, body in preflight):
            problems.append(f"{SKILL}:{preflight[0][0]}: the pre-flight node must classify a "
                            "destructive command with `action_gate.py check` before it runs — a "
                            "shipped gate nobody runs protects nothing")
        rollback = [(line, body) for line, _ident, body in nodes
                    if body.startswith("Rollback")]
        if not rollback:
            problems.append(f"{SKILL}:{first}: no Rollback node — the rollback procedure must "
                            "classify the commands it restores with")
        elif not any("action_gate.py" in body for _line, body in rollback):
            problems.append(f"{SKILL}:{rollback[0][0]}: the Rollback node must classify its "
                            "restoring commands with `action_gate.py check` (rule "
                            "`destructive-action-gate`)")

    agent = Doc.load(root, CODE_FACTORY, problems)
    if not any("action_gate.py check" in text for _line, text in agent.paragraphs()):
        problems.append(f"{CODE_FACTORY}:1: no phase tells the main agent to run "
                        "`action_gate.py check` before a destructive command")

    book = Doc.load(root, RULEBOOK, problems)
    if "## destructive-action-gate" not in book.text:
        problems.append(f"{RULEBOOK}:1: the rulebook carries no `destructive-action-gate` rule")
    # The VERBATIM carriers of the rule. The root AGENTS.md is not among them any more: it POINTS at
    # the rulebook (a `Rule <id>: canonical wording ...` line) instead of quoting the block, so what
    # it must keep is the pointer, not the markers.
    for rel in (RULEBOOK, SKILL, CODE_FACTORY, README):
        carrier = Doc.load(root, rel, problems)
        for edge in ("begin", "end"):
            marker = f"<!-- factory-rule: destructive-action-gate {edge} -->"
            if carrier.text.count(marker) != 1:
                problems.append(f"{rel}:1: the canonical block marker "
                                f"`{marker}` must appear exactly once")
    agents = Doc.load(root, AGENTS, problems)
    if "`destructive-action-gate`" not in agents.text:
        problems.append(f"{AGENTS}:1: the root manual must still POINT at the rule "
                        "`destructive-action-gate` in the rulebook (it no longer quotes it)")
    return problems


# --------------------------------------------------------------------------------------------
# H. The reviewer gate is bounded — no unconditional loop back into implementation
# --------------------------------------------------------------------------------------------
def check_review_gate_budget(root: pathlib.Path) -> list[str]:
    """RCR must split into retry / stop (hitl) / conditional-pass (auto) edges.

    The finding this pins: an unconditional `RCR --> M` edge let the flow restart coding even
    after the reviewer budget was exhausted with critical findings still open, defeating the
    bounded review gate (rule `review-gate-policy`).
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    first, flow = flow_edges(skill)
    if not flow:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the reviewer gate cannot be wired")
        return problems
    edges = edges_from(skill, "RCR")
    if not edges:
        problems.append(f"{SKILL}:{first}: no edges out of RCR — the review-gate policy has "
                        "no routing at all")
        return problems
    for edge in edges:
        if edge.label is None and edge.target == "M":
            problems.append(f"{SKILL}:{edge.line}: an unconditional `RCR --> M` edge restarts "
                            "coding even when the reviewer budget is exhausted with critical "
                            "findings open — split RCR into retry / stop (hitl) / "
                            "conditional-pass (auto)")
    required = (("budget not exhausted", "M"),
                ("budget exhausted, hitl", "U2"),
                ("budget exhausted, auto", "W"))
    for label, target in required:
        if not any(label in (edge.label or "") and edge.target == target for edge in edges):
            problems.append(f"{SKILL}:{edges[0].line}: RCR needs a `{label}` edge to {target} — "
                            "the bounded review gate (rule `review-gate-policy`) must route the "
                            "exhausted-budget case away from the coder")
    return problems


def check_retry_budget_gate(root: pathlib.Path) -> list[str]:
    """The retry budget must be counted by the pre-delegation gate, and the rulebook must say so.

    The finding this pins (violations N-1/N-2, proposal P-2): the counter in `pipeline.yaml` was
    written by whoever reported the retry, so nothing refused the delegation that exceeded the
    budget. `scripts/delegation_gate.py check` is now the one place that increments a counter and
    refuses; the two carriers that define the counting rule must name it, and the budget table of
    the script must still be the table the canonical rule states (one source, no drift).
    """
    problems: list[str] = []
    review = Doc.load(root, CODE_REVIEW, problems)
    rules = Doc.load(root, RULEBOOK, problems)
    gate = Doc.load(root, DELEGATION_GATE, problems)
    for doc in (review, rules):
        for needle, what in (("delegation_gate.py check", "name the pre-delegation command"),
                             ("--owner-authorized", "state the one explicit override"),
                             ("retry_counters", "name the counter it increments"),
                             ("REFUSES", "state that an exhausted budget REFUSES the delegation")):
            if doc.text and needle not in doc.text:
                problems.append(f"{doc.rel}:1: the counting rule must {what} ({needle!r} is "
                                "missing) — a budget counted by the reporter is not a budget")
    # One budget table: the canonical rule's `role=N` pairs must be exactly the script's BUDGETS.
    block = re.search(r"<!--\s*factory-rule:\s*retry-budgets\s*begin\s*-->(.*?)"
                      r"<!--\s*factory-rule:\s*retry-budgets\s*end\s*-->", rules.text, re.S)
    if block is None:
        problems.append(f"{RULEBOOK}:1: no canonical `retry-budgets` block — the budgets have no "
                        "single home")
    elif gate.text:
        pairs = dict(re.findall(r"\b([a-z]+)=(\d+)", block.group(1)))
        if not pairs:
            problems.append(f"{RULEBOOK}:1: the `retry-budgets` block states no `role=N` budget")
        for role, budget in sorted(pairs.items()):
            if not re.search(rf'"{re.escape(role)}":\s*{budget}\b', gate.text):
                problems.append(f"{DELEGATION_GATE}:1: role {role!r} must be budgeted {budget} — "
                                "the gate and the canonical rule must state ONE budget table")
    return problems


# The W2/W3 wiring: every mechanism built in those workstreams must be REACHABLE from the flow, in
# BOTH carriers (SKILL.md draws it, code-factory.md executes it), with the honest limits stated.
# (relative path, whitespace-normalized fragment, what the carrier must say)
W2_W3_TOKENS = (
    (SKILL, "delegation_gate.py check", "the pre-delegation budget gate before a delegation"),
    (SKILL, "the budget is counted by whoever EXECUTES", "who counts the budget"),
    (SKILL, "permit_gate.py add", "the permit registration step"),
    (SKILL, "permit_gate.py verdict", "the recorded supervisor verdict"),
    (SKILL, "permit_gate.py bind", "the spawned agent id bound to its permit"),
    (SKILL, "permit_gate.py audit", "the deterministic permit backstop"),
    (SKILL, "MODEL-ENFORCED", "the honest limits of the supervisor verdict"),
    (SKILL, "DETECTED, not intercepted", "that a bypassing agent is detected, not stopped"),
    (SKILL, "manifest.py require", "the blocking pre-edit manifest gate"),
    (SKILL, "manifest.py add", "the per-change manifest registration"),
    (SKILL, "manifest.py audit", "the finish manifest audit"),
    (SKILL, "gate_all.py --repo", "the deterministic gate aggregator"),
    (SKILL, "--phase K", "the pre-implementation gate checkpoint"),
    (SKILL, "--phase Y", "the finish gate checkpoint"),
    (SKILL, "factory-business-tester", "the adversarial business tester"),
    (SKILL, "business-adversarial", "its own evidence tree"),
    (SKILL, "finding_disposition", "the accepted|refuted finding disposition"),
    (SKILL, "delegation_gate.py settle", "the wholly-refuted round settlement"),
    (SKILL, "project_fingerprint.py --write-state", "the derived fingerprint state"),
    (SKILL, "--check-state", "the fingerprint comparison"),
    (SKILL, "no embedded fingerprint marker", "that AGENTS.md carries no hash of itself"),
    (SKILL, "task_type and required_roles", "the checkpoint contract strict attribution needs"),
    (SKILL, "Phase-role exit table", "the phase -> role -> mandatory subagent table"),
    (CODE_FACTORY, "delegation_gate.py check", "the pre-delegation gate in the executable order"),
    (CODE_FACTORY, "permit_gate.py add", "the permit step in the executable order"),
    (CODE_FACTORY, "permit_gate.py audit", "the permit backstop in the executable order"),
    (CODE_FACTORY, "manifest.py require", "the blocking manifest gate in the executable order"),
    (CODE_FACTORY, "manifest.py audit", "the finish manifest audit in the executable order"),
    (CODE_FACTORY, "gate_all.py", "the gate aggregator in the executable order"),
    (CODE_FACTORY, "factory-business-tester", "the adversarial business tester"),
    (CODE_FACTORY, "business-adversarial", "its own evidence tree"),
    (CODE_FACTORY, "task_type` and `required_roles`", "the checkpoint contract at pre-flight"),
)


def check_w2_w3_wiring(root: pathlib.Path) -> list[str]:
    """The W2/W3 machinery is REACHABLE: both carriers name every step, with the honest limits.

    A gate nobody runs protects nothing, and a permit step nobody executes is prose. This section
    pins the wiring itself — the pre-delegation budget gate, the supervisor permit lifecycle, the
    manifest enforcement, the two gate checkpoints, the adversarial business tester at node S, the
    finding disposition and its settlement, the derived fingerprint state and the phase-role table —
    in the flow carrier AND in the executable order the agent follows.
    """
    problems: list[str] = []
    docs = {SKILL: Doc.load(root, SKILL, problems), CODE_FACTORY: Doc.load(root, CODE_FACTORY,
                                                                        problems)}
    bodies = {rel: " ".join(doc.text.split()) for rel, doc in docs.items()}
    for rel, needle, what in W2_W3_TOKENS:
        if docs[rel].text and needle not in bodies[rel]:
            problems.append(f"{rel}:1: the flow must name {what} ({needle!r} is missing) — a "
                            "mechanism the flow never reaches is not a control")
    return problems


def check_reviewer_calibration(root: pathlib.Path) -> list[str]:
    """The §7 calibration gate must be RUN before the reviewer, in the flow and in the agent.

    The finding this pins: `calibrate_reviewer.py status` existed but no node invoked it, so the
    periodic obligation stayed prose at the only point where it matters. The check is positional as
    well as textual — the command has to precede `factory-code-reviewer` inside the review node —
    because "run it somewhere nearby" is what a due calibration is supposed to stop.
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    _first, nodes = flow_nodes(skill)
    by_id = {ident: (line, body) for line, ident, body in nodes}
    if not by_id:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the calibration gate cannot be wired")
    for node_id in ("CR", "CR0"):
        node = by_id.get(node_id)
        if node is None:
            problems.append(f"{SKILL}:1: the review node {node_id} is gone — the calibration gate "
                            "has no place to run")
            continue
        line, body = node
        if "calibrate_reviewer.py status" not in body:
            problems.append(f"{SKILL}:{line}: node {node_id} must invoke "
                            "`calibrate_reviewer.py status --repo <resolved repo_path>` BEFORE the "
                            "reviewer runs (a due calibration is prose no more)")
            continue
        if node_id == "CR":
            reviewer = body.find("factory-code-reviewer")
            if reviewer == -1:
                problems.append(f"{SKILL}:{line}: node CR no longer names `factory-code-reviewer`")
            elif body.find("calibrate_reviewer.py status") > reviewer:
                problems.append(f"{SKILL}:{line}: node CR invokes the calibration gate AFTER the "
                                "reviewer — it must run first")
            for needle, why in (("score", "the golden-set calibration that clears the gate"),
                                ("calibration-log.md", "the append-only record it writes")):
                if needle not in body:
                    problems.append(f"{SKILL}:{line}: node CR must name {why} "
                                    f"({needle!r}) — a due calibration has to be discharged, not "
                                    "just reported")

    agent = Doc.load(root, CODE_FACTORY, problems)
    for needle, where in (("calibrate_reviewer.py status", "invoke the calibration gate"),
                          ("calibration-log.md", "name the calibration log"),
                          ("score", "discharge a due calibration with the golden-set run")):
        if needle not in agent.text:
            problems.append(f"{CODE_FACTORY}:1: Phase 8b must {where} ({needle!r}) — the agent "
                            "instruction is where the reviewer is actually launched")

    review = Doc.load(root, CODE_REVIEW, problems)
    if "calibrate_reviewer.py status" not in review.text:
        problems.append(f"{CODE_REVIEW}:1: §7 must show the `calibrate_reviewer.py status` "
                        "invocation — the rule's own reference cannot leave it implicit")
    elif not re.search(r"before the reviewer", review.text, re.I):
        problems.append(f"{CODE_REVIEW}:1: §7 must say the gate runs BEFORE the reviewer")
    return problems


# --------------------------------------------------------------------------------------------
# J. The Advisor gate branches on agreement first
# --------------------------------------------------------------------------------------------
def check_advisor_agreement(root: pathlib.Path) -> list[str]:
    """`ADR` must ask about the AGREEMENT; the recommended role is chosen inside the `agree` edge.

    The finding this pins: `ADR` branched straight on the Advisor's `recommended_role`, so the
    documented disagreement path (`agreement: disagree` -> the user in hitl, stop the fix loop and
    record it in `report.md` in auto) was unreachable in the flowchart an agent follows — the
    contract in `code-factory.md` and the picture had drifted apart.
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    first, flow = flow_edges(skill)
    if not flow:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the Advisor agreement gate cannot be "
                        "checked")
        return problems
    line, body = find_node(skill, ADVISOR_NODE)
    if not body:
        problems.append(f"{SKILL}:{first}: no Advisor decision node `{ADVISOR_NODE}{{...}}`")
        return problems
    if "agreement" not in body.lower():
        problems.append(f"{SKILL}:{line}: `{ADVISOR_NODE}` must branch on the Advisor's AGREEMENT "
                        f"(`{ADVISOR_NODE}{{Advisor agreement?}}`), not on its recommended role — "
                        "otherwise `agreement: disagree` never stops the retries")
    adr = edges_from(skill, ADVISOR_NODE)
    agree = next((edge for edge in adr if edge.label == "agree"), None)
    if agree is None or agree.target != ADVISOR_ROLE_NODE:
        problems.append(f"{SKILL}:{line}: `{ADVISOR_NODE}` must keep the `agree` edge to "
                        f"`{ADVISOR_ROLE_NODE}` — the recommended role is chosen only when the "
                        "Advisor agrees with the Diagnostician")
    else:
        roles = {(edge.label, edge.target) for edge in edges_from(skill, ADVISOR_ROLE_NODE)}
        for label, target in ADVISOR_ROLE_EDGES:
            if (label, target) not in roles:
                problems.append(f"{SKILL}:{agree.line}: `{ADVISOR_ROLE_NODE}` must keep the "
                                f"`{label}` edge to {target} — an agreed route still has to reach "
                                "its role")
    for mode, target, what in ADVISOR_DISAGREE_EDGES:
        edge = next((candidate for candidate in adr
                     if (candidate.label or "").startswith(f"disagree, {mode}")), None)
        if edge is None or edge.target != target:
            problems.append(f"{SKILL}:{line}: `{ADVISOR_NODE}` needs the `disagree, {mode}` edge "
                            f"to {target} — on disagreement the flow must {what}")
        elif mode == "auto" and "report.md" not in (edge.label or ""):
            problems.append(f"{SKILL}:{edge.line}: the auto disagreement edge must record the "
                            "disagreement in report.md")
    for edge in adr:
        if edge.target in {"P", "P2", "AI"}:
            problems.append(f"{SKILL}:{edge.line}: `{ADVISOR_NODE} --> {edge.target}` routes "
                            "straight to a role — a role may only be chosen behind the `agree` "
                            "edge")
    return problems


# --------------------------------------------------------------------------------------------
# K. The routing prose carries no route the router cannot take
# --------------------------------------------------------------------------------------------
def check_routing_prose(root: pathlib.Path) -> list[str]:
    """§2 must not keep a WRONG_RESULTS -> CODER row and the provider guide may not say PLANNER.

    The findings these pin: the JSON-first router sends EVERY WRONG_RESULTS match (its pattern
    contains `regression`) to DIAGNOSTICIAN, so the "with regression" -> CODER row was an operator
    instruction the factory cannot execute; and the authoritative provider rows D/F route
    PROVIDER_MODEL / PROVIDER_FORMAT to INFRASTRUCTURE, so `model/format → PLANNER` advertised a
    second, wrong retry path.
    """
    problems: list[str] = []
    routing = Doc.load(root, ERROR_ROUTING, problems)
    documented = 0
    for lineno, line in enumerate(routing.lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or not cells[0].upper().startswith("WRONG_RESULTS"):
            continue
        documented += 1
        if cells[1].upper() != "DIAGNOSTICIAN":
            problems.append(f"{ERROR_ROUTING}:{lineno}: every WRONG_RESULTS match routes to "
                            "DIAGNOSTICIAN under JSON-first classification (the `regression` "
                            f"alternative belongs to the same row) — `{cells[0]} | {cells[1]}` "
                            "advertises a route the router never takes")
    if not documented:
        problems.append(f"{ERROR_ROUTING}:1: §2 carries no WRONG_RESULTS row — the wrong-results "
                        "route must stay documented")

    providers = Doc.load(root, PROVIDERS, problems)
    if "model/format" not in providers.text:
        problems.append(f"{PROVIDERS}:1: the provider guide no longer routes `model/format` — "
                        "provider failures must stay documented")
    for lineno, line in enumerate(providers.lines, start=1):
        if re.search(r"model/format\s*→\s*PLANNER", line):
            problems.append(f"{PROVIDERS}:{lineno}: `model/format → PLANNER` is a dead route — "
                            "provider rows D/F send PROVIDER_MODEL / PROVIDER_FORMAT to "
                            "INFRASTRUCTURE (config repair, no code rollback)")
    return problems


# --------------------------------------------------------------------------------------------
# L. The operator manual describes the executable HITL gate
# --------------------------------------------------------------------------------------------
README_GATE_TOKENS = ((".code-factory/state/plan.md", "name the plan file the user decides on"),
                      ("AskUserQuestion", "name the tool that asks the decision"),
                      ("approve, revise, or reject",
                       "state the three answers the user actually chooses"))


def check_readme_approval(root: pathlib.Path) -> list[str]:
    """The `hitl` bullet must describe the gate the carriers execute, not "present the plan".

    The finding this pins: `.agents/README.md` said the factory "presents the plan for approval",
    while flow node I, Phase 3 and planning-guide §6 keep the plan in `.code-factory/state/plan.md`
    and ask via `AskUserQuestion` — the operator manual drifted from the mechanism a reader follows.
    """
    problems: list[str] = []
    readme = Doc.load(root, README, problems)
    line, bullet = next(((start, text) for start, text in readme.paragraphs()
                         if "**hitl (default)**" in text), (0, ""))
    if not bullet:
        problems.append(f"{README}:1: the `hitl (default)` bullet is gone — the operator manual "
                        "no longer describes the interactive mode")
        return problems
    for needle, what in README_GATE_TOKENS:
        if needle not in bullet:
            problems.append(f"{README}:{line}: the `hitl` bullet must {what} ({needle!r}) — the "
                            "manual has to describe the executable gate, not the plan abstractly")
    if "presents the plan for approval" in bullet:
        problems.append(f"{README}:{line}: `presents the plan for approval` is the retired "
                        "abstract wording — the gate is the plan file plus an explicit question")
    return problems


# --------------------------------------------------------------------------------------------
# M. The conditional Farukon path is wired exactly where its Web GUI twin is
# --------------------------------------------------------------------------------------------
# (needle, what the carrier must say) of the IMPLEMENT node: the routing decision, the specialist,
# the task-named model and the model that is logged.
FARUKON_M_NODE_TOKENS = (
    ("farukon_mcp.py decide", "route on the deterministic applicability decision"),
    ("factory-farukon-expert", "name the specialist that does the work"),
    ("models.farukon_expert", "honor the task-named role model"),
    ("models_used.farukon_expert", "log the model actually used"),
)
# The agent instruction carries the same wiring one phase at a time; each entry is checked against
# the whole document, because the phases are prose, not flow nodes.
FARUKON_AGENT_TOKENS = (
    ("  - factory-farukon-expert", "register the specialist as a subagent"),
    ("references/farukon-mcp.md", "list the Farukon reference file"),
    ("farukon_mcp.py decide", "decide applicability with the deterministic script"),
    ("--farukon", "add the conditional `--farukon` pre-flight probe"),
    ("models.farukon_expert", "honor the task-named role model"),
    ("models_used.farukon_expert", "log the model actually used"),
    ("mcp__farukon__*", "give the platform tools to the specialist and the tester"),
    ("F1–F2", "route a cargo/MCP failure through the Farukon infrastructure rows"),
)


def check_farukon_wiring(root: pathlib.Path) -> list[str]:
    """The Farukon twin of every GUI/chrome carrier, checked where the mechanism lives.

    The finding this pins: a conditional specialist is only real when the flow ROUTES to it, the
    pre-flight PROBES for it, the task key names its model, the model actually used is LOGGED and
    the tester OWNS the acceptance. A reference file describing all of that while no node, phase or
    role card mentions the role would be a capability nobody reaches.
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    prose = prose_only(skill)
    for needle, what in (("references/farukon-mcp.md", "the Farukon reference file"),
                         (".agents/agents/sub-agents/farukon-expert.md", "the specialist role card")):
        if needle not in prose.text:
            problems.append(f"{SKILL}:1: the reference-file list must name {what} ({needle!r})")
    line, body = find_node(skill, PREFLIGHT_NODE)
    if not body:
        problems.append(f"{SKILL}:1: no pre-flight node `{PREFLIGHT_NODE}[...]` — the conditional "
                        "Farukon probe has no phase to run in")
    elif "--farukon" not in body:
        problems.append(f"{SKILL}:{line}: an applicable Farukon run must add `--farukon` to the "
                        "pre-flight probe (a capability nobody probes is a run that guesses)")
    line, body = find_node(skill, CODER_NODE)
    if not body:
        problems.append(f"{SKILL}:1: no implement node `{CODER_NODE}[...]` — the Farukon path cannot "
                        "be routed")
    else:
        for needle, what in FARUKON_M_NODE_TOKENS:
            if needle not in body:
                problems.append(f"{SKILL}:{line}: the implement node must {what} ({needle!r})")
    line, body = find_node(skill, ACCEPTANCE_NODE)
    if not body:
        problems.append(f"{SKILL}:1: no business-test node `{ACCEPTANCE_NODE}[...]` — the tester-owned "
                        "Farukon acceptance cannot be wired")
    else:
        for needle, what in (("mcp__farukon__*", "name the platform tools the tester drives"),
                             ("ACCEPTANCE", "mark the artifacts the tester owns as ACCEPTANCE"),
                             ("never MET", "leave a missing capability UNVERIFIED, never MET")):
            if needle not in body:
                problems.append(f"{SKILL}:{line}: the business-test node must {what} ({needle!r})")
    line, body = find_node(skill, "MS")
    if body and "farukon_expert" not in body:
        problems.append(f"{SKILL}:{line}: the provider-failure node must name `farukon_expert` "
                        "among the delegated roles — a task-named platform model stops the run too")
    if not any("models.farukon_expert" in text and "models_used.farukon_expert" in text
               for _line, text in prose.paragraphs()):
        problems.append(f"{SKILL}:1: the models paragraph must carry `models.farukon_expert` as the "
                        "optional task key AND its `models_used.farukon_expert` logging")

    agent = Doc.load(root, CODE_FACTORY, problems)
    for needle, what in FARUKON_AGENT_TOKENS:
        if needle not in agent.text:
            problems.append(f"{CODE_FACTORY}:1: the agent instruction must {what} ({needle!r})")

    tester = Doc.load(root, TESTER, problems)
    if re.search(r"^[ \t]*-[ \t]+mcp__farukon__\*\s*$", tester.text, re.M) is None:
        problems.append(f"{TESTER}:1: the tester's tool list must carry `mcp__farukon__*` exactly "
                        "as it carries `mcp__chrome-devtools__*` — the acceptance run needs the tools")
    acceptance = [text for _line, text in tester.paragraphs()
                  if "mcp__farukon__*" in text and "ACCEPTANCE" in text]
    if not acceptance:
        problems.append(f"{TESTER}:1: the tester must own the final replay acceptance: the "
                        "`mcp__farukon__*` paragraph marks its artifacts ACCEPTANCE and keeps them "
                        "distinct from the specialist's diagnostic set")

    reference = Doc.load(root, FARUKON_REF, problems)
    for needle, what in (("merge-config", "name the idempotent config merge"),
                         ("validate-config", "name the config validator"),
                         ("farukon_build", "name the tools the platform is driven through"),
                         ("order_capable", "state the read-only safety default (no order path)"),
                         ("UNVERIFIED", "state the degradation contract (never a fabricated MET)")):
        if reference.text and needle not in reference.text:
            problems.append(f"{FARUKON_REF}:1: the reference must {what} ({needle!r})")
    return problems



# --------------------------------------------------------------------------------------------
# P. The pre-delegation gate binds EVERY budgeted delegation, the adversarial node is a real fork,
#    the manifest is created before it is required, and every role is registered with the orchestrator
# --------------------------------------------------------------------------------------------
# (flow node id, the role it delegates) — the gate must be a PRE-STEP of each of these nodes, so the
# clause sits inside the node itself and the graph can prove it: a hitl/auto run that reaches one of
# them without the check would spend a budget nobody counted.
DELEGATION_SITES = (("E", "analyzer"), ("SC", "analyzer"), ("F", "planner"), ("PC", "planner"),
                    ("M", "coder"), ("N", "tester"), ("Q", "tester"), ("S", "tester"),
                    ("BT", "business_tester"), ("CR", "reviewer"), ("CR0", "reviewer"),
                    ("DG", "diagnostician"), ("ADV", "advisor"), ("DOC2", "documenter"),
                    ("SA", "security_auditor"), ("BTR0", "business_tester"),
                    ("BTR1", "business_tester"))
# The fork/join of the business leg and the task-type paths into the adversarial node.
FORK_EDGES = (("S", "TST"), ("S", "BT"), ("TST", "T"), ("BT", "T"))
ADVERSARIAL_PATHS = (("CR0", "BTR0", "CRV0"), ("RF", "BTR1", "L"))
# A write node the adversarial review/refactor branches must NOT reach (review-report-only).
WRITE_NODES = ("M",)


def _edges(doc: Doc) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    _first, nodes = flow_nodes(doc)
    by_line: dict[int, list[tuple[str, str]]] = {}
    for line, ident, _body in nodes:
        by_line.setdefault(line, []).append((ident, _body))
    for number, line in enumerate(doc.lines, 1):
        match = EDGE_RE.match(line.strip())
        if not match:
            continue
        raw = match.group(3).strip()
        target = NODE_RE.match(raw)
        if target:
            pairs.add((match.group(1), target.group(1)))
            continue
        bare = re.match(r"([A-Za-z][A-Za-z0-9_]*)", raw)
        if bare:
            pairs.add((match.group(1), bare.group(1)))
    return pairs


def _reachable(edges: set[tuple[str, str]], start: str) -> set[str]:
    seen: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop()
        for source, target in edges:
            if source == node and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def check_delegation_gates(root: pathlib.Path) -> list[str]:
    """The pre-delegation gate is a PRE-STEP of EVERY delegation, in the graph, not in prose.

    The finding this pins: node DG1 hung off the implement path only, so a run that delegated the
    analyzer, the planner, the tester, the reviewer, the diagnostician, the advisor, the documenter or
    the auditor never reached the budget gate or the permit lifecycle at all — a mechanism the flow
    never reaches is not a control. The adversarial node is pinned the same way: it must be a real
    FORK of node S (joined before the verdict) and reachable from `review` and `refactor` too, while
    a review/refactor adversarial branch may never reach a write node.
    """
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    agent = Doc.load(root, CODE_FACTORY, problems)
    _first, nodes = flow_nodes(skill)
    by_id = {ident: (line, body) for line, ident, body in nodes}
    for node_id, role in DELEGATION_SITES:
        if node_id not in by_id:
            problems.append(f"{SKILL}:1: the delegating node {node_id} is gone — the "
                            f"pre-delegation gate has no place to run for {role}")
            continue
        line, body = by_id[node_id]
        flattened = " ".join(body.split())
        for needle, what in ((f"delegation_gate.py check --role {role}", "the budget check"),
                             (f"permit_gate.py add --role {role}", "the permit registration")):
            if needle not in flattened:
                problems.append(f"{SKILL}:{line}: node {node_id} must run {what} \'{needle}\' BEFORE "
                                f"its {role} delegation — a delegation that skips the gate spends a "
                                f"budget nobody counted")
    if "DG1" not in by_id:
        problems.append(f"{SKILL}:1: node DG1 is gone — the shared pre-delegation gate has no "
                        f"place to run")
    for node_id, body in (("DG1", by_id.get("DG1", (0, ""))[1]),) if "DG1" in by_id else ():
        flattened = " ".join(body.split())
        for role in ("coder", "planner", "tester", "reviewer", "diagnostician", "advisor",
                     "documenter", "security_auditor", "business_tester"):
            if role not in flattened:
                problems.append(f"{SKILL}:{by_id['DG1'][0]}: node DG1 must name the {role} "
                                f"delegation it covers, so the shared pre-step is stated once")
    edges = _edges(skill)
    for source, target in FORK_EDGES:
        if (source, target) not in edges:
            problems.append(f"{SKILL}:1: the business leg must be a real FORK — the \'{source} --> "
                            f"{target}\' edge is missing (the tester and the adversarial tester run "
                            f"IN PARALLEL and JOIN before a verdict)")
    for source, middle, target in ADVERSARIAL_PATHS:
        for pair in ((source, middle), (middle, target)):
            if pair not in edges:
                problems.append(f"{SKILL}:1: the {source} path must reach the adversarial node — "
                                f"the \'{pair[0]} --> {pair[1]}\' edge is missing (the adversarial "
                                f"business tester is never security_audit's, and never a rework order)")
        for write_node in WRITE_NODES:
            if (middle, write_node) in edges:
                problems.append(f"{SKILL}:1: the {middle} branch leads straight into the write node "
                                f"{write_node} — a review/refactor adversarial report is diagnostic "
                                f"and may never authorise a code change")
    if "BT" in by_id and "security_audit" not in " ".join(by_id["BT"][1].split()):
        problems.append(f"{SKILL}:{by_id['BT'][0]}: the adversarial node must exclude "
                        f"security_audit explicitly")
    # The manifest is CREATED before it is REQUIRED: require-before-init blocks every fresh run.
    for doc in (skill, agent):
        if not doc.text:
            continue
        created = doc.text.find("manifest.py init")
        required = doc.text.find("manifest.py require")
        if created < 0 or required < 0:
            problems.append(f"{doc.rel}:1: the carrier must name both `manifest.py init` and "
                            f"`manifest.py require`")
        elif created > required:
            problems.append(f"{doc.rel}:{doc.line_of(required)}: `manifest.py require` is documented "
                            f"BEFORE `manifest.py init` — the pre-edit gate would block every "
                            f"fresh run on a manifest nobody has written yet")
    # Every role the factory can resolve is registered with the orchestrator.
    orchestrator = agent.text.split("\n---", 1)[0]
    for role, profile in _model_roles():
        if profile not in orchestrator:
            problems.append(f"{CODE_FACTORY}:1: {profile} is a resolvable role but the orchestrator "
                            f"does not register it in its `subagents:` list — an unregistered role "
                            f"cannot be delegated")
    return problems


def _model_roles() -> tuple[tuple[str, str], ...]:
    """`(role, subagent profile)` from `model_matrix.py` (the registry IS the contract, not a copy)."""
    scripts = str(pathlib.Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import model_matrix  # noqa: PLC0415  (deliberately lazy: the module resolves the matrix)
        pairs = []
        for role in model_matrix.ROLES:
            card = model_matrix.ROLE_FILES.get(role, f"{role}.md")
            pairs.append((role, f"factory-{card[:-3].replace('_', '-')}"))
        return tuple(pairs)
    finally:
        if scripts in sys.path:
            sys.path.remove(scripts)


SECTIONS = (
    ("A", "the Finish node wires the memory mechanisms", check_finish_node),
    ("B", "the precedent index is built by the flow", check_precedent_index),
    ("C", "the briefing carries memory facts", check_briefing_memory_facts),
    ("D", "the templates agree with the rulebook", check_templates),
    ("E", "model precedence is not restated in three voices", check_model_precedence),
    ("F", "the memory contract is single", check_single_memory_contract),
    ("G", "the destructive-action gate is run by the flow", check_destructive_action_gate),
    ("H", "the reviewer gate is bounded", check_review_gate_budget),
    ("I", "the reviewer calibration gate runs before the reviewer", check_reviewer_calibration),
    ("J", "the Advisor gate branches on agreement first", check_advisor_agreement),
    ("K", "the routing prose carries no dead route", check_routing_prose),
    ("L", "the operator manual describes the executable HITL gate", check_readme_approval),
    ("M", "the conditional Farukon path is wired like its Web GUI twin", check_farukon_wiring),
    ("N", "the retry budget is counted by the pre-delegation gate", check_retry_budget_gate),
    ("O", "the W2/W3 machinery is reachable from the flow", check_w2_w3_wiring),
    ("P", "the pre-delegation gate binds every delegation and the adversarial leg is a fork",
     check_delegation_gates),
)


# --------------------------------------------------------------------------------------------
# G. Negative / vaccination probes: the pins must not be tautologies
# --------------------------------------------------------------------------------------------
def locate_root(start: pathlib.Path) -> pathlib.Path:
    """The repository root: the directory holding AGENTS.md and the code-factory SKILL.md.

    The depth is DERIVED, not assumed: `scripts/ -> code-factory/ -> skills/ -> .agents/ -> root`
    is three levels above the script directory, but a layout change must not silently point the
    contracts at `.agents/`.
    """
    for parent in (start, *start.parents):
        if (parent / "AGENTS.md").is_file() and (parent / SKILL).is_file():
            return parent
    return start.parents[2]


ROOT = locate_root(SCRIPT_DIR)


def make_tree(dst: pathlib.Path) -> pathlib.Path:
    """A throwaway root holding byte-identical copies of every file the contracts read."""
    if dst.exists():
        shutil.rmtree(dst)
    for rel in FILES:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return dst


def probe(name: str, section, edits, expected: str) -> str:
    """Break the contract on a copy the way a careless edit would; the checker must catch it."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = make_tree(pathlib.Path(tmp) / "repo")
        for rel, old, new in edits:
            path = tree / rel
            text = path.read_text(encoding="utf-8")
            if old is None:                       # a hand-written copy of the logic grows back
                path.write_text(text + new, encoding="utf-8")
                continue
            if old not in text:
                raise AssertionError(f"probe {name!r}: {rel} does not contain {old!r} — the probe "
                                     "would be a no-op, not a vaccination")
            path.write_text(text.replace(old, new), encoding="utf-8")
        found = section(tree)
        if not found:
            raise AssertionError(f"probe {name!r}: the checker ACCEPTED the broken copy — the "
                                 "assertion is a tautology")
        report = "\n".join(found)
        if expected not in report:
            raise AssertionError(f"probe {name!r}: the checker failed for the wrong reason "
                                 f"(expected {expected!r}): {report}")
        return found[0]


PROBES = (
    ("G: the flow stops invoking the action gate", check_destructive_action_gate,
     ((SKILL, "action_gate.py check --action", "action_gate.py classify --action"),),
     "action_gate.py check"),
    ("A: the compaction command is deleted from the Finish node", check_finish_node,
     ((SKILL, "memory_project.py compact", "memory_project.py tighten"),),
     "memory_project.py compact"),
    ("A: the model-attribution command is deleted from the Finish node", check_finish_node,
     ((SKILL, "model_attribution.py --session auto", "model_attrib.py --session auto"),),
     "model_attribution.py"),
    ("A: `backlog --check` is made to mean `open: 0` again", check_finish_node,
     ((SKILL, "— never open: 0", "— exit 0 means open: 0"),),
     "open: 0"),
    ("B: the flow stops building the precedent index", check_precedent_index,
     ((SKILL, "precedent_index.py build", "precedent_index.py make"),),
     "precedent_index.py build"),
    ("B: `--fresh` disappears from the flow node", check_precedent_index,
     ((SKILL, "precedent_index.py query --repo <resolved repo_path> --fresh <terms>",
       "precedent_index.py query --repo <resolved repo_path> <terms>"),
      (SKILL, "and --fresh refuses a stale index with exit 3",
       "a stale index is refused with exit 3")),
     "--fresh"),
    ("B: the index is described as standing runtime state", check_precedent_index,
     ((AGENTS, "a BUILD PRODUCT, not standing runtime state", "standing runtime state"),
      (AGENTS, "the flow builds it at analysis time (`precedent_index.py build`)",
       "the flow keeps it in sync")),
     "BUILD product"),
    ("C: the `Memory facts` section disappears from the briefing", check_briefing_memory_facts,
     ((BRIEFING, "### Memory facts", "### Notes"),),
     "Memory facts"),
    ("D: `repo_path` is no longer required except green-field", check_templates,
     ((EXAMPLE_TASK, "`repo_path` is REQUIRED for every task except a green-field one",
       "`repo_path` is optional"),
      (EXAMPLE_TASK, "Required, EXCEPT for a green-field task", "Optional")),
     "REQUIRED"),
    ("D: the `verify:` criterion is renamed away", check_templates,
     ((EXAMPLE_TASK, '    verify: "python -m pytest -q tests/test_si_regression.py"',
       '    check: "python -m pytest -q tests/test_si_regression.py"'),),
     "`verify:`"),
    ("E: the retired `warning, not a blocker` wording comes back", check_model_precedence,
     ((PROVIDERS, "a WARNING naming both roles and both models:",
       "a **warning, not a blocker**: the run continues on the configured models:"),),
     "warning, not a blocker"),
    ("E: the family check is called deterministic without its resolver", check_model_precedence,
     ((PROVIDERS, "**The family check is one command (deterministic, zero LLM)**: "
                  "`scripts/model_matrix.py` resolves",
       "**The family check is one deterministic command**: the resolver"),),
     "deterministic"),
    ("F: `check_factory_model.py` grows its own `_validate_entry` again",
     check_single_memory_contract,
     ((CHECK_MODEL, None, "\n\ndef _validate_entry(entry):\n    return [], []\n"),),
     "_validate_entry"),
    ("H: the exhausted-budget stop edge is removed from RCR",
     check_review_gate_budget,
     ((SKILL, "budget exhausted, hitl", "user decides, hitl"),),
     "budget exhausted, hitl"),
    ("I: the calibration gate stops being invoked by the review node",
     check_reviewer_calibration,
     ((SKILL, "calibrate_reviewer.py status --repo <resolved repo_path> BEFORE the reviewer",
       "calibrate_reviewer.py info --repo <resolved repo_path> BEFORE the reviewer"),),
     "calibrate_reviewer.py status"),
    ("I: the agent instruction drops the calibration gate", check_reviewer_calibration,
     ((CODE_FACTORY, "calibrate_reviewer.py status --repo <resolved repo_path>",
       "calibrate_reviewer.py inspect --repo <resolved repo_path>"),),
     "calibrate_reviewer.py status"),
    ("J: the role decision is put back in front of the agreement gate", check_advisor_agreement,
     ((SKILL, "    ADR -->|agree| ARO{Advisor recommended role}\n    ARO -->|coder| P\n",
       "    ADR -->|coder| P\n"),),
     "`agree` edge to `ARO`"),
    ("J: the auto disagreement branch is deleted", check_advisor_agreement,
     ((SKILL, "    ADR -->|disagree, auto: stop the fix loop and record the disagreement in "
              "report.md| Y\n", ""),),
     "disagree, auto"),
    ("K: the WRONG_RESULTS-to-CODER row comes back", check_routing_prose,
     ((ERROR_ROUTING, "| WRONG_RESULTS | DIAGNOSTICIAN | deep analysis needed |",
       '| WRONG_RESULTS (without "regression") | DIAGNOSTICIAN | deep analysis needed |\n'
       '| WRONG_RESULTS (with "regression") | CODER | code changed behavior incorrectly |'),),
     "WRONG_RESULTS (with"),
    ("K: the provider guide routes model/format to PLANNER again", check_routing_prose,
     ((PROVIDERS, "model/format → INFRASTRUCTURE (repair the alias",
       "model/format → PLANNER (fix the alias"),),
     "model/format → PLANNER"),
    ("L: the operator manual loses the question tool", check_readme_approval,
     ((README, "user explicitly via `AskUserQuestion` whether to approve",
       "user whether to approve"),),
     "AskUserQuestion"),
    ("M: the Farukon routing sentence is dropped from the implement node", check_farukon_wiring,
     ((SKILL, "Conditional Farukon routing: when the Phase 1 applicability decision "
              "(farukon_mcp.py decide) is applicable",
       "Conditional Farukon routing: when a Farukon task is applicable"),),
     "farukon_mcp.py decide"),
    ("M: the conditional `--farukon` pre-flight probe disappears", check_farukon_wiring,
     ((SKILL, "--farukon, which appends the cargo", "--rust, which appends the cargo"),),
     "--farukon"),
    ("M: the tester stops owning the replay acceptance", check_farukon_wiring,
     ((TESTER, "and marked ACCEPTANCE", "and marked DIAGNOSTIC"),),
     "must own the final replay acceptance"),
    ("N: the reviewer budget stops being counted by the pre-delegation gate", check_retry_budget_gate,
     ((CODE_REVIEW, "scripts/delegation_gate.py check --repo <resolved repo_path> --role reviewer",
       "scripts/count_reviews.py --repo <resolved repo_path> --role reviewer"),),
     "delegation_gate.py check"),
    ("N: the rulebook's operational note loses the refusal", check_retry_budget_gate,
     ((RULEBOOK, "REFUSES it once the budget is exhausted", "records it once the budget is "
       "exhausted"),),
     "REFUSES"),
    ("N: the gate's budget table drifts from the canonical rule", check_retry_budget_gate,
     ((DELEGATION_GATE, '"reviewer": 2', '"reviewer": 3'),),
     "must be budgeted 2"),
    ("O: the flow stops naming the pre-delegation budget gate", check_w2_w3_wiring,
     ((SKILL, "delegation_gate.py check", "count_the_retries.py check"),),
     "delegation_gate.py check"),
    ("O: the adversarial business tester disappears from the flow", check_w2_w3_wiring,
     ((SKILL, "factory-business-tester", "factory-tester-extra"),),
     "factory-business-tester"),
    ("O: the executable order loses the blocking manifest gate", check_w2_w3_wiring,
     ((CODE_FACTORY, "manifest.py require", "manifest.py maybe"),),
     "manifest.py require"),
    ("O: the permit step disappears from the executable order", check_w2_w3_wiring,
     ((CODE_FACTORY, "permit_gate.py add", "permit_gate.py imagine"),),
     "permit_gate.py add"),
    ("P: the implement node stops running the pre-delegation gate", check_delegation_gates,
     ((SKILL, "delegation_gate.py check --role coder",
       "delegation_gate.py maybe --role coder"),),
     "node M must run the budget check"),
    ("P: the business leg collapses back into a sequential step", check_delegation_gates,
     ((SKILL, "TST --> T{Business results match?", "TST --> T9{Business results match?"),),
     "the business leg must be a real FORK"),
    ("P: the review adversarial branch is wired straight into a write node", check_delegation_gates,
     ((SKILL, "BTR0 --> CRV0", "BTR0 --> M"),),
     "leads straight into the write node M"),
    ("P: a resolvable role disappears from the orchestrator's registry", check_delegation_gates,
     ((CODE_FACTORY, "  - factory-supervisor\n", ""),),
     "factory-supervisor is a resolvable role"),
)


def main() -> int:
    use_utf8_output()
    root = ROOT
    failures: list[str] = []
    print(f"flow contracts under {root}")

    for key, title, section in SECTIONS:
        found = section(root)
        if found:
            failures.extend(found)
            print(f"FAIL - {key}. {title}", file=sys.stderr)
            for item in found:
                print("  " + item, file=sys.stderr)
        else:
            print(f"ok   - {key}. {title}")

    caught = 0
    for name, section, edits, expected in PROBES:
        try:
            first = probe(name, section, edits, expected)
        except AssertionError as exc:
            failures.append(f"probe {name}: {exc}")
            print(f"FAIL - probe {name}: {exc}", file=sys.stderr)
            continue
        caught += 1
        print(f"ok   - probe {name} -> {first}")

    if failures:
        print(f"FAIL - {len(failures)} contract violation(s)", file=sys.stderr)
        return 1

    print(f"PASS - the flow's prose keeps its mechanisms wired: the Finish node invokes "
          f"compaction, the memory gate and the model attribution; the precedent index is built "
          f"by the flow and described as a build product; the briefing carries the memory facts; "
          f"the templates agree with the rulebook; the model precedence has one voice; the memory "
          f"contract has one implementation; the reviewer calibration gate runs BEFORE the "
          f"reviewer in the flow, the agent and the reference; the Advisor gate branches on "
          f"agreement before it names a role; the routing prose carries no route the router "
          f"cannot take; the operator manual describes the executable HITL gate; the conditional "
          f"Farukon path is wired like its Web GUI twin (routing, `--farukon` probe, "
          f"`models.farukon_expert`, logged `models_used.farukon_expert`, tester-owned acceptance) "
          f"— the retry budget is counted by the pre-delegation gate that increments the counter "
          f"and refuses when exhausted, in both carriers that define the counting rule and with the "
          f"gate's budget table equal to the canonical one; and the W2/W3 machinery is REACHABLE "
          f"from the flow: the pre-delegation budget gate, the supervisor permit lifecycle "
          f"(add → verdict → spawn → bind, with the model-enforced verdict and the deterministic "
          f"audit backstop), the blocking manifest gate, the K/Y gate aggregation, the "
          f"factory-business-tester at node S with its own evidence tree, the finding disposition "
          f"and its settlement, the derived fingerprint state and the phase-role table — and all "
          f"{caught} deliberately broken copies were caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

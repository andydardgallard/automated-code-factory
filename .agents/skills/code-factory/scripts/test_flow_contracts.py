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

This test pins those strings — always against the REAL shipped file — and then proves the pins are
not tautologies: each contract is broken on a throwaway copy in the way a careless future edit
would break it (delete the command name, restore `open: 0`, drop the `Memory facts` heading, drop
`repo_path` required, re-add `warning, not a blocker`, re-add `_validate_entry`), and the checker
must FAIL on that copy.

Invariant: every command and every constraint pinned below is present in the shipped file, at the
place where the mechanism lives (a flow node, a named section, a template block) — absence, or a
restored old wording, is reported as `<file>:<line>: <what is missing>`.

Exit code 0 = every contract holds and every probe is caught, 1 = a contract or a probe failed.
"""
from __future__ import annotations

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
EXAMPLE_TASK = ".example.task.yaml"
TASK_TEMPLATE = ".agents/skills/code-factory/assets/task-template.yaml"
CHECK_MODEL = ".agents/skills/code-factory/scripts/check_factory_model.py"
MEMORY = ".agents/skills/code-factory/scripts/memory_project.py"
ENGLISH = ".agents/skills/code-factory/scripts/check_english_only.py"

# Every file a contract reads: a probe copies exactly these, then breaks one of them.
FILES = (SKILL, CODE_FACTORY, AGENTS, README, BRIEFING, PROVIDERS, EXAMPLE_TASK, TASK_TEMPLATE,
         CHECK_MODEL, MEMORY, ENGLISH)

FINISH_NODE = "Y"      # `Y[Finish: ...]` — the only place compaction/attribution are invoked
CODER_NODE = "M"       # `M[Implement: ...]` — the coder delegation and its briefing
PREFLIGHT_NODE = "PF"  # `PF[Pre-flight: ...]` — where the model matrix is resolved

MERMAID_FENCE = "```mermaid"
# `Y[body]` / `PF(body)` / `DOC{body}`; the leading class keeps an arrow or an edge label from
# being read as part of a node id.
NODE_RE = re.compile(r"(?:^|[\s>|])([A-Za-z][A-Za-z0-9_]*)\s*([\[\{\(])")
CLOSING = {"[": "]", "{": "}", "(": ")"}

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


SECTIONS = (
    ("A", "the Finish node wires the memory mechanisms", check_finish_node),
    ("B", "the precedent index is built by the flow", check_precedent_index),
    ("C", "the briefing carries memory facts", check_briefing_memory_facts),
    ("D", "the templates agree with the rulebook", check_templates),
    ("E", "model precedence is not restated in three voices", check_model_precedence),
    ("F", "the memory contract is single", check_single_memory_contract),
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
          f"contract has one implementation — and all {caught} deliberately broken copies were "
          f"caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

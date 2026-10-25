#!/usr/bin/env python3
"""
Pin the `security_audit` guarantee where it already lived, and pin that the new report-only
`review` rule REFERENCES it instead of duplicating it.

INVARIANT this test protects: a `task_type: review` run is report-only, which is exactly the
guarantee `security_audit` already carried — so the review rule hands it over as a cross-reference
and the audit's own guarantee is preserved verbatim in its original documents.

  1. THE GUARANTEE IS STATED WHERE IT ALREADY LIVED.
     - the `SA` node of the orchestration flowchart: the auditor is read-only, the deliverables are
       the reports plus a generated fix-task file, and "No code change and no auto-fixing";
     - `references/security-audit.md`: the factory does not fix vulnerabilities itself, and the
       deliverables are the report and the fix-task file in the factory task format
       (`task_type: implement`);
     - `.agents/agents/code-factory.md`: the auditor subagent is read-only with no code change and
       no auto-fixing.
  2. THE FLOW KEEPS IT. `SA --> W` still reaches acceptance, and the acceptance-failure edge for a
     `review`/`security_audit` run is the stop-and-ask node (`X -->|No, review/security_audit| XR`),
     never error routing's coder branch: the unscoped `X -->|No| RR` edge must not exist.
  3. IT IS NOT DUPLICATED. The canonical `review-report-only` block mentions `security_audit` at
     most once and only as a cross-reference — it never names the audit's own artifacts
     (`audit/report`, `audit/fix-tasks`), which belong to `references/security-audit.md`. The review
     follow-up file `.code-factory/review/fix-tasks.yaml` and the audit file
     `.code-factory/audit/fix-tasks.yaml` are two distinct artifacts, and neither document borrows
     the other's directory.
  4. THE USER-FACING PROMISE IS UNCHANGED. `.agents/README.md` and `.example.task.yaml` still state
     the audit guarantee, and their review entries reference it once instead of re-stating it.

Every assertion matches STABLE SUBSTRINGS, case-insensitively, with markdown emphasis (`*`,
backticks) and line wrapping normalized away: light copy-editing keeps the pin green, a removal or
a duplication turns it red, and every failure names `file:line`.

The real documents are only read. The vaccination probes work on throwaway copies in a temp
directory: the guarantee sentence is deleted from a copied `SA` node, the review block is made to
restate the audit artifacts, and the unscoped `X -->|No| RR` edge is put back — each copy must make
the check FAIL and name the file, and restoring the copy must make it pass again.

Exit code 0 = every assertion holds, 1 = the guarantee was removed, duplicated or misrouted.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]        # scripts/ -> code-factory/ -> skills/ -> .agents/ -> repo root
sys.path.insert(0, str(SCRIPTS))
# The mermaid contract is the sibling's, not a second copy of it: the same block regex, the same
# edge regex and the same adjacency parser, so a change to the flowchart syntax is made once.
from test_prompt_structure import EDGE_RE, MERMAID_RE, parse_edges  # noqa: E402

# The documents that carry the guarantee or the review rule that must reference it.
SKILL = ".agents/skills/code-factory/SKILL.md"
AUDIT_DOC = ".agents/skills/code-factory/references/security-audit.md"
RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
AGENT_DOC = ".agents/agents/code-factory.md"
README_DOC = ".agents/README.md"
EXAMPLE_TASK = ".example.task.yaml"
DOCUMENTS = (SKILL, AUDIT_DOC, RULEBOOK, AGENT_DOC, README_DOC, EXAMPLE_TASK)

# The two artifacts that must never be confused: different directories, different owners.
AUDIT_DIR = ".code-factory/audit/"
AUDIT_REPORT = ".code-factory/audit/report.md"
AUDIT_FIX_TASKS = ".code-factory/audit/fix-tasks.yaml"
REVIEW_FIX_TASKS = ".code-factory/review/fix-tasks.yaml"

RULE_ID = "review-report-only"
RULE_BEGIN = f"<!-- factory-rule: {RULE_ID} begin -->"
RULE_END = f"<!-- factory-rule: {RULE_ID} end -->"

# What the `SA` node must still promise (stable substrings, never whole sentences).
SA_NODE_FACTS = (
    ("read-only", "the auditor must still be named read-only"),
    ("reports", "the node must still name the reports it produces"),
    ("fix-task file", "the node must still name the generated fix-task file"),
    ("no code change", "the node must still promise no code change"),
    ("no auto-fixing", "the node must still promise no auto-fixing"),
    ("references/security-audit.md", "the node must still point at the audit reference"),
)

# The audit reference: the guarantee, then the deliverables it produces.
AUDIT_GOAL_FACTS = (
    ("does not fix vulnerabilities",
     "the audit doc must still say the factory does not fix vulnerabilities itself"),
    ("reports", "the goal must still name the reports deliverable"),
    ("fix-task file", "the goal must still name the generated fix-task file"),
)
AUDIT_DELIVERABLE_FACTS = (
    (AUDIT_DIR, "the deliverables must still live under the audit directory"),
    ("report.md", "the report deliverable must still be named"),
    ("fix-tasks.yaml", "the generated fix-task deliverable must still be named"),
    ("factory task format", "the fix-task file must still be in the factory task format"),
    ("task_type: implement", "the generated task must still carry task_type: implement"),
)

# The security-audit phase of the main agent prompt.
AGENT_PHASE_FACTS = (
    ("references/security-audit.md", "the phase must still point at the audit reference"),
    ("factory-security-auditor", "the auditor subagent must still be named"),
    ("read-only", "the auditor must still be named read-only"),
    ("no code change", "the phase must still promise no code change"),
    ("no auto-fixing", "the phase must still promise no auto-fixing"),
    ("reports", "the phase must still name the audit reports"),
    ("fix-task file", "the phase must still name the generated fix-task file"),
)

# The canonical review block: one cross-reference, no restated audit artifact.
RULE_BLOCK_FACTS = (
    (REVIEW_FIX_TASKS, "the review follow-up file must still live in the review directory"),
    ("keeps its own guarantee",
     "the block must still hand the audit guarantee over as a cross-reference"),
    ("does not restate it", "the block must still say it does not restate the audit guarantee"),
)

# The user-facing promise (README + the commented example task).
USER_PROMISE_FACTS = (
    ("reports", "the promise must still name the reports"),
    ("fix-task", "the promise must still name the generated fix-task file"),
    ("does not fix vulnerabilities",
     "the promise must still say the factory does not fix vulnerabilities"),
)
README_PROMISE_FACTS = USER_PROMISE_FACTS + (
    ("references/security-audit.md", "the entry must still point at the audit reference"),
)
USER_REVIEW_FACTS = (
    (REVIEW_FIX_TASKS, "the review follow-up file must stay in .code-factory/review/"),
    ("report-only", "the review entry must still say the run is report-only"),
    ("unmodified tree",
     "the review entry must still require the criteria to hold on the unmodified tree"),
)
README_REVIEW_FACTS = USER_REVIEW_FACTS + (
    ("keeps its own guarantee", "the entry must reference the audit guarantee, not restate it"),
)
EXAMPLE_REVIEW_FACTS = USER_REVIEW_FACTS + (
    ("the same guarantee",
     "the entry must say it is the SAME guarantee security_audit has, not a new one"),
)

README_AUDIT_ENTRY_RE = re.compile(r"^`task_type: security_audit`\s+[—–-]")
README_REVIEW_ENTRY_RE = re.compile(r"^`task_type: review`\s+[—–-]")
EXAMPLE_ENTRY_RE = re.compile(r"^#\s+(?:implement|review|refactor|security_audit)\s+[—–-]")
EXAMPLE_AUDIT_ENTRY_RE = re.compile(r"^#\s+security_audit\s+[—–-]")
EXAMPLE_REVIEW_ENTRY_RE = re.compile(r"^#\s+review\s+[—–-]")
AGENT_AUDIT_HEADING_RE = re.compile(r"^\*\*Security audit task\*\*")
DELIVERABLES_HEADING_RE = re.compile(r"^#{1,6}\s*\d*\.?\s*Deliverables\b", re.I)
SA_NODE_RE = re.compile(r"(?<![A-Za-z0-9_])SA\s*\[")
XR_NODE_RE = re.compile(r"(?<![A-Za-z0-9_])XR\s*\[")


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so a path or a quoted sentence survives a legacy console.

    A Windows console defaults to a legacy code page (cp866/cp1251) and this report carries file
    paths and pinned substrings with `—` in them, which that codec cannot encode: printing them
    would raise UnicodeEncodeError and the user would get a traceback instead of the verdict.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


class Slice:
    """Lines of one document, normalized for stable substring matching.

    Markdown emphasis/code markers (`*`, backticks) and whitespace runs are dropped, so `**not**`
    matches `not` and a sentence re-wrapped across lines still matches. Every normalized character
    keeps the ORIGINAL line number, so a failure names `file:line` instead of a fuzzy location.
    """

    def __init__(self, path: pathlib.Path, label: str, first_line: int, lines: list[str]) -> None:
        self.path = path
        self.label = label
        self.first_line = first_line
        self.lines = lines
        chars: list[str] = []
        line_map: list[int] = []
        gap = True
        for offset, line in enumerate(lines):
            number = first_line + offset
            for char in line:
                if char in "*`":                  # markdown emphasis / code markers, not content
                    continue
                if char.isspace():
                    if not gap:
                        chars.append(" ")
                        line_map.append(number)
                        gap = True
                    continue
                chars.append(char.lower())
                line_map.append(number)
                gap = False
            if not gap:                           # a line break is a soft space: wrapping is safe
                chars.append(" ")
                line_map.append(number)
                gap = True
        self.text = "".join(chars)
        self.line_map = line_map

    def has(self, needle: str) -> bool:
        return needle.lower() in self.text

    def count(self, needle: str) -> int:
        return self.text.count(needle.lower())

    def line_of(self, needle: str) -> int:
        """1-based source line of the first match; the slice start when absent."""
        index = self.text.find(needle.lower())
        return self.first_line if index < 0 else self.line_map[index]

    def require(self, needle: str, why: str) -> str | None:
        """None when `needle` is still there, else a `file:line` failure."""
        if self.has(needle):
            return None
        return (f"{self.path}:{self.first_line}: {self.label} — {why}; "
                f"the substring {needle!r} is gone")

    def forbid(self, needle: str, why: str) -> str | None:
        """None when `needle` is absent, else a `file:line` failure at its position."""
        if not self.has(needle):
            return None
        return (f"{self.path}:{self.line_of(needle)}: {self.label} — {why}; "
                f"the substring {needle!r} must not appear here")


def load(root: pathlib.Path, rel: str, errors: list[str]) -> Slice | None:
    """The whole document as a Slice, or a `not found` failure appended to `errors`."""
    path = root / rel
    if not path.is_file():
        errors.append(f"{path}: not found — the document carrying the security_audit guarantee "
                      "is missing")
        return None
    return Slice(path, rel, 1, path.read_text(encoding="utf-8").splitlines())


def sub(full: Slice, bounds: tuple[int, int], label: str) -> Slice:
    """A slice of `full` over the inclusive 0-based line `bounds`."""
    start, end = bounds
    return Slice(full.path, label, start + 1, full.lines[start:end + 1])


def find_line(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    """0-based index of the first line MATCHING `pattern` anywhere in the line ("`^` anchors it)."""
    for index, line in enumerate(lines):
        if pattern.search(line):
            return index
    return None


def line_with(lines: list[str], needle: str) -> int | None:
    """0-based index of the first line CONTAINING `needle` (case-insensitive)."""
    low = needle.lower()
    for index, line in enumerate(lines):
        if low in line.lower():
            return index
    return None


def paragraph(lines: list[str], index: int) -> tuple[int, int]:
    """Inclusive 0-based bounds of the blank-line-delimited paragraph holding `index`."""
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start, end


def section(lines: list[str], index: int) -> tuple[int, int]:
    """Inclusive 0-based bounds of the markdown section whose heading is at `index`."""
    end = index
    for probe in range(index + 1, len(lines)):
        if re.match(r"^#{1,6}\s", lines[probe]):
            break
        end = probe
    return index, end


def entry(lines: list[str], index: int, stops: re.Pattern[str]) -> tuple[int, int]:
    """Inclusive 0-based bounds of a commented entry: down to the next entry or a non-comment."""
    end = index
    for probe in range(index + 1, len(lines)):
        if stops.match(lines[probe]) or not lines[probe].lstrip().startswith("#"):
            break
        end = probe
    return index, end


def flat(label: str) -> str:
    """An edge label with its spacing removed, so `No, review/security_audit` compares safely."""
    return re.sub(r"\s+", "", label).lower()


def flow_block(path: pathlib.Path) -> tuple[str | None, int]:
    """(mermaid text, 1-based line of its first line) of the flowchart that carries the `SA` node."""
    text = path.read_text(encoding="utf-8")
    for match in MERMAID_RE.finditer(text):
        block = match.group(1)
        if "SA" in parse_edges(block):
            return block, text.count("\n", 0, match.start(1)) + 1
    return None, 1


def edge_line(block: str, first_line: int, source: str, target: str) -> int:
    """1-based document line of the drawing line `source --> ... target` (sibling EDGE_RE)."""
    for index, line in enumerate(block.splitlines()):
        match = EDGE_RE.match(line)
        if match and match.group(1) == source and match.group(3) == target:
            return first_line + index
    return first_line


def node_line(block: str, first_line: int, node: str) -> int:
    """1-based document line where `node` is DEFINED (`SA[...]`, `X{...}`, `XR[...]`)."""
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(node)}\s*[\[{{]")
    index = find_line(block.splitlines(), pattern)
    return first_line + index if index is not None else first_line


def collect_facts(target: Slice, facts: tuple[tuple[str, str], ...]) -> list[str]:
    return [error for error in (target.require(needle, why) for needle, why in facts) if error]


# --------------------------------------------------------------------------------------
# 1. The guarantee is stated where it already lived.
# --------------------------------------------------------------------------------------
def check_sa_node(root: pathlib.Path) -> list[str]:
    """The `SA` node still carries the read-only / reports / no-auto-fixing promise."""
    path = root / SKILL
    if not path.is_file():
        return [f"{path}: not found — the orchestration flowchart is missing"]
    block, first = flow_block(path)
    if block is None:
        return [f"{path}:1: no ```mermaid block with the `SA` node — the security_audit guarantee "
                "cannot be checked"]
    index = find_line(block.splitlines(), SA_NODE_RE)
    if index is None:
        return [f"{path}:{first}: the security_audit node `SA` is gone from the orchestration "
                "flowchart — the guarantee lost its home"]
    node = Slice(path, "the `SA` (security_audit) node", first + index, [block.splitlines()[index]])
    return collect_facts(node, SA_NODE_FACTS)


def check_audit_doc(root: pathlib.Path) -> list[str]:
    """`references/security-audit.md` still refuses to auto-fix and still names both deliverables."""
    errors: list[str] = []
    full = load(root, AUDIT_DOC, errors)
    if full is None:
        return errors

    anchor = line_with(full.lines, "Goal:")
    if anchor is None:
        errors.append(f"{full.path}:1: the audit doc must still open with its goal — `Goal:` is gone")
    else:
        goal = sub(full, paragraph(full.lines, anchor), "the goal paragraph")
        errors.extend(collect_facts(goal, AUDIT_GOAL_FACTS))

    heading = find_line(full.lines, DELIVERABLES_HEADING_RE)
    if heading is None:
        errors.append(f"{full.path}:1: the deliverables section is gone — no `Deliverables` heading")
    else:
        deliverables = sub(full, section(full.lines, heading), "the deliverables section")
        errors.extend(collect_facts(deliverables, AUDIT_DELIVERABLE_FACTS))

    error = full.forbid(".code-factory/review/",
                        "the audit must not adopt the review artifact directory")
    if error:
        errors.append(error)
    return errors


def check_agent_doc(root: pathlib.Path) -> list[str]:
    """The security-audit phase of the main agent prompt is still read-only with no auto-fixing."""
    errors: list[str] = []
    full = load(root, AGENT_DOC, errors)
    if full is None:
        return errors
    heading = find_line(full.lines, AGENT_AUDIT_HEADING_RE)
    if heading is None:
        errors.append(f"{full.path}:1: the `**Security audit task**` phase is gone — the guarantee "
                      "lost its home in the main agent prompt")
        return errors
    phase = sub(full, paragraph(full.lines, heading), "the security-audit phase")
    errors.extend(collect_facts(phase, AGENT_PHASE_FACTS))
    error = phase.forbid(".code-factory/review/",
                         "the audit phase must not adopt the review artifact directory")
    if error:
        errors.append(error)
    return errors


# --------------------------------------------------------------------------------------
# 2. The flow keeps it.
# --------------------------------------------------------------------------------------
def check_flow(root: pathlib.Path) -> list[str]:
    """`SA --> W` survives, and an unmet review/security_audit criterion stops in `XR`."""
    path = root / SKILL
    if not path.is_file():
        return [f"{path}: not found — the orchestration flowchart is missing"]
    block, first = flow_block(path)
    if block is None:
        return [f"{path}:1: no ```mermaid block with the `SA` node — the flow cannot be checked"]
    edges = parse_edges(block)
    errors: list[str] = []

    if (None, "W") not in edges.get("SA", []):
        errors.append(
            f"{path}:{edge_line(block, first, 'SA', 'W')}: the audit must still flow into the "
            f"shared acceptance node — the bare edge `SA --> W` is gone (SA now leads to "
            f"{edges.get('SA')})")

    outcomes = edges.get("X")
    if not outcomes:
        errors.append(f"{path}:{first}: the acceptance decision node `X` has no outgoing edge — "
                      "the stop-and-ask branch cannot be checked")
        return errors
    x_line = node_line(block, first, "X")

    if not any(target == "XR" and label is not None and flat(label) == "no,review/security_audit"
               for label, target in outcomes):
        errors.append(
            f"{path}:{x_line}: the acceptance-failure edge for security_audit must be "
            f"`X -->|No, review/security_audit| XR` (stop and ask the owner); `X` currently leads "
            f"to {outcomes}")

    unscoped = [target for label, target in outcomes if label is not None and flat(label) == "no"]
    if unscoped:
        errors.append(
            f"{path}:{x_line}: the unscoped edge `X -->|No| ...` must not exist — it routes a "
            f"review/security_audit acceptance failure into error routing (targets {unscoped}); "
            "scope it to implement/refactor")

    into_routing = [(label, target) for label, target in outcomes
                    if target == "RR" and "implement" not in (label or "").lower()]
    if into_routing:
        errors.append(
            f"{path}:{x_line}: only an implement/refactor acceptance failure may enter error "
            f"routing — every `X --> RR` edge must name implement/refactor, got {into_routing}")

    index = find_line(block.splitlines(), XR_NODE_RE)
    if index is None:
        errors.append(f"{path}:{x_line}: the stop-and-ask node `XR` is gone")
    else:
        node = Slice(path, "the `XR` (stop-and-ask) node", first + index, [block.splitlines()[index]])
        for needle, why in (
            ("stop and ask", "the unmet-criterion branch must still stop and ask the owner"),
            ("review-report-only", "the branch must still point at the report-only rule"),
        ):
            error = node.require(needle, why)
            if error:
                errors.append(error)
    return errors


# --------------------------------------------------------------------------------------
# 3. It is not duplicated.
# --------------------------------------------------------------------------------------
def check_rulebook_block(root: pathlib.Path) -> list[str]:
    """The canonical `review-report-only` block references the audit guarantee exactly once."""
    errors: list[str] = []
    full = load(root, RULEBOOK, errors)
    if full is None:
        return errors
    text = "\n".join(full.lines)
    if text.count(RULE_BEGIN) != 1 or text.count(RULE_END) != 1:
        errors.append(f"{full.path}:{line_with(full.lines, RULE_ID) or 1}: the rulebook must hold "
                      f"exactly one marked `{RULE_ID}` block — the review rule has no single home")
        return errors
    begin = line_with(full.lines, RULE_BEGIN)
    end = line_with(full.lines, RULE_END)
    block = sub(full, (begin, end), f"the canonical `{RULE_ID}` block")

    errors.extend(collect_facts(block, RULE_BLOCK_FACTS))

    mentions = block.count("security_audit")
    if mentions == 0:
        errors.append(f"{block.path}:{block.first_line}: the `{RULE_ID}` block no longer mentions "
                      "`security_audit` — the relation to the audit guarantee is unstated")
    elif mentions > 1:
        errors.append(f"{block.path}:{block.line_of('security_audit')}: the `{RULE_ID}` block "
                      f"mentions `security_audit` {mentions} times — at most ONE cross-reference is "
                      "allowed, the guarantee itself stays in references/security-audit.md")

    restated = block.text.replace(REVIEW_FIX_TASKS, "")
    if "fix-tasks" in restated:
        errors.append(f"{block.path}:{block.line_of('fix-tasks')}: the `{RULE_ID}` block restates "
                      "the audit fix-task artifact — `fix-tasks` outside "
                      f"{REVIEW_FIX_TASKS!r} belongs to references/security-audit.md")
    error = block.forbid("audit/", "the `review-report-only` block must not name the audit artifacts "
                                   "(audit/report, audit/fix-tasks) — they belong to "
                                   "references/security-audit.md")
    if error:
        errors.append(error)
    return errors


def check_distinct_artifacts() -> list[str]:
    """The review and audit fix-task files are two different artifacts in two different folders.

    The cross-directory bans themselves live with the documents that own them: the audit reference
    must not name `.code-factory/review/` (check_audit_doc), and every review statement must not
    name `.code-factory/audit/` (the block, the README and the example task).
    """
    if AUDIT_FIX_TASKS == REVIEW_FIX_TASKS or AUDIT_REPORT == REVIEW_FIX_TASKS:
        return [f"{AUDIT_FIX_TASKS} / {REVIEW_FIX_TASKS}: the audit and the review must not share "
                "a follow-up artifact — an audit fix task and a review follow-up are different "
                "runs and different files"]
    return []


# --------------------------------------------------------------------------------------
# 4. The user-facing promise is unchanged.
# --------------------------------------------------------------------------------------
def check_readme(root: pathlib.Path) -> list[str]:
    """The README still promises the audit guarantee; its review entry references it once."""
    errors: list[str] = []
    full = load(root, README_DOC, errors)
    if full is None:
        return errors

    anchor = find_line(full.lines, README_AUDIT_ENTRY_RE)
    if anchor is None:
        errors.append(f"{full.path}:1: the `task_type: security_audit` entry is gone — the "
                      "user-facing promise disappeared")
    else:
        promise = sub(full, paragraph(full.lines, anchor), "the security_audit entry")
        errors.extend(collect_facts(promise, README_PROMISE_FACTS))

    anchor = find_line(full.lines, README_REVIEW_ENTRY_RE)
    if anchor is None:
        errors.append(f"{full.path}:1: the `task_type: review` entry is gone — the cross-reference "
                      "to the audit guarantee disappeared")
        return errors
    review = sub(full, paragraph(full.lines, anchor), "the review entry")
    errors.extend(collect_facts(review, README_REVIEW_FACTS))

    mentions = review.count("security_audit")
    if mentions != 1:
        errors.append(f"{full.path}:{review.line_of('security_audit')}: the review entry must "
                      f"reference the audit guarantee exactly once, found {mentions} — a second "
                      "mention restates it instead of pointing at it")
    error = review.forbid(".code-factory/audit/",
                          "the review entry must not adopt the audit artifact directory")
    if error:
        errors.append(error)
    return errors


def check_example_task(root: pathlib.Path) -> list[str]:
    """The commented example task still promises the audit guarantee and references it once."""
    errors: list[str] = []
    full = load(root, EXAMPLE_TASK, errors)
    if full is None:
        return errors

    anchor = find_line(full.lines, EXAMPLE_AUDIT_ENTRY_RE)
    if anchor is None:
        errors.append(f"{full.path}:1: the `security_audit` entry of the task_type list is gone — "
                      "the user-facing promise disappeared")
    else:
        promise = sub(full, entry(full.lines, anchor, EXAMPLE_ENTRY_RE), "the security_audit entry")
        errors.extend(collect_facts(promise, USER_PROMISE_FACTS))

    anchor = find_line(full.lines, EXAMPLE_REVIEW_ENTRY_RE)
    if anchor is None:
        errors.append(f"{full.path}:1: the `review` entry of the task_type list is gone — the "
                      "cross-reference to the audit guarantee disappeared")
        return errors
    review = sub(full, entry(full.lines, anchor, EXAMPLE_ENTRY_RE), "the review entry")
    errors.extend(collect_facts(review, EXAMPLE_REVIEW_FACTS))

    mentions = review.count("security_audit")
    if mentions != 1:
        errors.append(f"{full.path}:{review.line_of('security_audit')}: the review entry must "
                      f"reference the audit guarantee exactly once, found {mentions} — a second "
                      "mention restates it instead of pointing at it")
    error = review.forbid(".code-factory/audit/",
                          "the review entry must not adopt the audit artifact directory")
    if error:
        errors.append(error)
    return errors


CHECKS = (
    check_sa_node,
    check_audit_doc,
    check_agent_doc,
    check_flow,
    check_rulebook_block,
    check_readme,
    check_example_task,
)


def collect(root: pathlib.Path) -> list[str]:
    """Every violation of the security_audit guarantee found under `root`."""
    errors = check_distinct_artifacts()
    for check in CHECKS:
        errors.extend(check(root))
    return errors


# --------------------------------------------------------------------------------------
# 5. Vaccination: prove the pin bites, on throwaway copies only.
# --------------------------------------------------------------------------------------
def fresh_tree(root: pathlib.Path, tree: pathlib.Path) -> None:
    """Rebuild `tree` as a byte copy of the documents the checks read."""
    if tree.exists():
        shutil.rmtree(tree)
    for rel in DOCUMENTS:
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)


def restore(root: pathlib.Path, tree: pathlib.Path, rel: str) -> None:
    shutil.copyfile(root / rel, tree / rel)


def mutate(tree: pathlib.Path, rel: str, old: str, new: str) -> bool:
    """Replace `old` with `new` in the copy; False when the anchor is gone (the probe cannot bite)."""
    path = tree / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def vaccinate(root: pathlib.Path, tmp: pathlib.Path) -> list[str]:
    """Delete / duplicate / misroute the guarantee in copies and require the check to fail."""
    errors: list[str] = []
    tree = tmp / "repo"
    fresh_tree(root, tree)
    baseline = collect(tree)
    if baseline:
        errors.append("the untouched copy of the documents must pass — the check reads only the "
                      f"documents: {baseline}")

    # (a) MANDATORY: delete the guarantee sentence from the copied `SA` node.
    skill = tree / SKILL
    if not mutate(tree, SKILL, "No code change and no auto-fixing.",
                  "The audit is thorough."):
        errors.append(f"{SKILL}: the probe cannot bite — the `SA` node no longer carries the "
                      "'No code change and no auto-fixing.' sentence to delete")
    else:
        found = collect(tree)
        if not found:
            errors.append(f"{SKILL}: DELETING the guarantee sentence from the `SA` node was NOT "
                          "caught — the pin does not bite")
        elif not any(str(skill) in error for error in found):
            errors.append(f"{SKILL}: the failure for a deleted `SA` guarantee must name the file, "
                          f"got {found}")
        elif not any("no auto-fixing" in error for error in found):
            errors.append(f"{SKILL}: the failure must name the removed fact 'no auto-fixing', "
                          f"got {found}")
    restore(root, tree, SKILL)
    after = collect(tree)
    if after:
        errors.append(f"{SKILL}: restoring the real document must make the check pass again, "
                      f"got {after}")

    # (b) the review block must not restate the audit artifacts.
    rulebook = tree / RULEBOOK
    restating = ("The audit writes `.code-factory/audit/report.md` and its fix-task file in "
                 "`.code-factory/audit/`.\n")
    if not mutate(tree, RULEBOOK, RULE_END, restating + RULE_END):
        errors.append(f"{RULEBOOK}: the probe cannot bite — the `{RULE_ID}` end marker is gone")
    else:
        found = collect(tree)
        if not any(str(rulebook) in error for error in found):
            errors.append(f"{RULEBOOK}: making the `{RULE_ID}` block RESTATE the audit artifacts "
                          f"was NOT caught — duplication of the guarantee is unpinned, got {found}")
    restore(root, tree, RULEBOOK)

    # (c) the unscoped acceptance-failure edge must come back as a failure, not as a green run.
    skill = tree / SKILL
    text = skill.read_text(encoding="utf-8")
    unscoped = re.sub(r"(?m)^(\s*X\s*-->\s*)\|No, implement/refactor\|", r"\1|No|", text)
    if unscoped == text:
        errors.append(f"{SKILL}: the probe cannot bite — no `X -->|No, implement/refactor|` edge to "
                      "unscope")
    else:
        skill.write_text(unscoped, encoding="utf-8")
        found = collect(tree)
        if not any(str(skill) in error for error in found):
            errors.append(f"{SKILL}: re-introducing the unscoped `X -->|No| RR` edge was NOT "
                          f"caught — error routing is open to review/security_audit again, got {found}")
    restore(root, tree, SKILL)
    if collect(tree):
        errors.append(f"{SKILL}: restoring the real flowchart must make the check pass again")

    return errors


def main() -> int:
    use_utf8_output()
    errors = collect(ROOT)
    with tempfile.TemporaryDirectory() as raw:
        errors.extend(vaccinate(ROOT, pathlib.Path(raw)))

    if errors:
        print("FAIL - the security_audit guarantee is NOT preserved / not deduplicated:",
              file=sys.stderr)
        for error in errors:
            print("  " + error, file=sys.stderr)
        return 1

    print("PASS - the security_audit guarantee is stated in the `SA` node, in "
          "references/security-audit.md and in the security-audit phase; `SA --> W` still reaches "
          "acceptance and an unmet review/security_audit criterion stops in `XR`, never in error "
          "routing; the canonical review-report-only block references the guarantee once without "
          "restating its artifacts; README and .example.task.yaml still promise it; and deleting, "
          "duplicating or misrouting it is caught by the vaccination probes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Self-test for the canonical rule `review-report-only` (zero LLM tokens, stdlib only).

INVARIANT under test: a `task_type: review` run NEVER edits the project —

  no review verdict, in either mode, reaches a node that starts a coder, writes a backup or
  changes a tracked source, test, config, documentation or data file; the deliverable is the
  report (`.code-factory/logs/code-review.md` + `.code-factory/report.md`) plus a generated
  follow-up task file (`.code-factory/review/fix-tasks.yaml`, produced by
  `scripts/review_followup_task.py`) that the owner runs later as a separate `implement` task;
  a review criterion that is not MET stops the run and asks the owner; and because nothing is
  edited, every `verify:` criterion of a review task must hold on the unmodified tree.

The rule is prose in `references/factory-rules.md`, but the WRITES it forbids are drawn as edges in
the orchestration flowchart of `SKILL.md`. Prose cannot be executed; a graph can be walked. This
test walks it, label-aware, in a REVIEW context:

  FLOW GUARD       from each review start node, a REVIEW context may not traverse an edge whose
                   label explicitly scopes it to `implement/refactor`, and MUST reach a
                   delivery/stop node instead of a write node.
  DELIVERY GUARD   the delivery node `RD` exists, both `CRV0` labels point at it, its node text
                   names the report plus the generated follow-up task file, and `XR` (stop and ask
                   the owner) is fed by the `review/security_audit` acceptance-failure label.
  TEXT GUARD       no document may bring the old promise back (`become the plan`,
                   `become the work plan`, `rework list is produced` outside a `factory-rule`
                   block), and `rework list` may only appear where `implement`/`refactor`/`scope`
                   qualifies it.
  GENERATOR        `review_followup_task.py` really advertises its CLI and really turns the merged
                   findings into a deterministic `task_type: implement` file — twice, byte-identical.
  ACCEPTANCE-STOP  `verify_acceptance.py --help` lists `--task-type` and its own suite exists.
  NEGATIVE PROBE   the SAME guard, run over a copy of the tree with the PRE-FIX edges restored,
                   FAILS and names the forbidden node — the guard is not a tautology.

"Review start nodes" and their delivery requirement (`SKILL.md`):
  CRV0  the review-verdict node of a review task           -> must reach RD
  CRV   the end-of-task review gate, only its labels that  -> must reach RD
        contain `request_changes`
  X     the acceptance-failure gate, only its labels that  -> must reach RD or XR
        start with `No`
Forbidden (write) targets: M (coder), K (backup), P (rollback into the coder), RCR (the
implement/refactor rework loop), H/I/J (the plan-approval entry), PF/G/L (the pre-flight /
implement entries that lead to the backup and the coder).

WHAT THIS GUARD CANNOT SEE (honest limits):
  - It reads labels and node ids, not prose: a node inside a traversed branch that EDITS a file
    without being in the forbidden set (the version bump `VER1..VER3` under `DOC -->|Yes| DOC2`
    writes `VERSION`) is invisible to it. The version rule is guarded by `test_factory_rules.py`.
  - A label that names no task type is traversed: `approve`/`request_changes` on `CRV0` name no
    task type, and blocking them would make the delivery unreachable. Only an explicit
    `implement/refactor` scope is treated as "not a review path".
  - The `rework list` qualifier is checked per markdown paragraph, and inside a fenced diagram the
    whole diagram is one paragraph — a node label is not a sentence. The diagram itself is guarded
    by the FLOW GUARD, which is stricter and label-aware.
  - It proves the FLOW and the hand-over, never a real run: whether a running agent obeys the
    diagram is a property of the model, not of these files.

Every case prints `PASS <case>` or `FAIL <case>` plus one `<file>:<line>: <reason>` line per
violation. Exit code 0 = the rule still holds and its guard is proven non-vacuous, 1 = violation.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Callable, Iterator, NamedTuple

HERE = Path(__file__).resolve().parent
# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root (the deployment root)
ROOT = HERE.parents[3]
SKILL = ROOT / ".agents" / "skills" / "code-factory" / "SKILL.md"

if str(HERE) not in sys.path:                     # the sibling parser lives next to this file
    sys.path.insert(0, str(HERE))
from test_prompt_structure import EDGE_RE, MERMAID_RE, parse_edges  # noqa: E402  (path first)

# --- the review context ---------------------------------------------------------------------
# A label is "not a review path" only when it explicitly scopes itself to the write flow. A bare
# edge and a label naming the review flow stay traversable; so does a neutral verdict label
# (`approve`, `request_changes`), because blocking it would leave `RD` unreachable from `CRV0` and
# the delivery check would be checking a graph nobody can walk.
IMPLEMENT_SCOPE = "implement/refactor"

FORBIDDEN = {
    "M": "starts factory-coder subagents, so the tracked tree is edited",
    "K": "writes .code-factory/backups/ before a modification",
    "P": "rolls the tree back and hands it to the coder",
    "RCR": "the implement/refactor rework loop (RCR --> M)",
    "H": "the plan-approval entry (H --> I --> J --> PF/backup)",
    "I": "the plan-approval gate that leads to a coder",
    "J": "the plan-approval gate that leads to a coder",
    "PF": "the pre-flight entry that leads to the backup and the coder",
    "G": "the implement entry node",
    "L": "the implement (auto) entry node that leads to pre-flight, backup and the coder",
}


class Start(NamedTuple):
    """One review start node: which of its edges the REVIEW context may take, and where it must end."""

    name: str
    why: str
    takes: Callable[[str | None], bool]
    delivery: tuple[str, ...]


def label_names_review(label: str | None) -> bool:
    return label is not None and "review/security_audit" in label.lower()


START_NODES = (
    Start("CRV0", "the review-verdict node of a review task", lambda label: True, ("RD",)),
    Start("CRV", "the end-of-task review gate",
          lambda label: label is not None and "request_changes" in label.lower(), ("RD",)),
    Start("X", "the acceptance-failure node",
          lambda label: label is not None and label.lower().startswith("no"), ("RD", "XR")),
)

# --- text guard -----------------------------------------------------------------------------
TEXT_FILES = (
    ".agents/skills/code-factory/SKILL.md",
    ".agents/agents/code-factory.md",
    "AGENTS.md",
    ".agents/README.md",
    ".agents/skills/code-factory/references/planning-guide.md",
    ".agents/skills/code-factory/references/code-review.md",
)
# The promise the rule retired: the findings of a review USED to become the run's own work plan.
LEGACY_PHRASES = ("become the plan", "become the work plan", "rework list is produced")
QUALIFIERS = ("implement", "refactor", "scope")
RULE_BLOCK_RE = re.compile(
    r"<!--\s*factory-rule:\s*([A-Za-z0-9_.-]+)\s+begin\s*-->.*?"
    r"<!--\s*factory-rule:\s*\1\s+end\s*-->", re.DOTALL)

# --- the hand-over --------------------------------------------------------------------------
GENERATOR = HERE / "review_followup_task.py"
REVIEW_FINDINGS = ROOT / ".code-factory" / "logs" / "code-review-merged.json"
ACCEPTANCE = HERE / "verify_acceptance.py"
ACCEPTANCE_TEST = HERE / "test_verify_acceptance.py"
SYNTHETIC_FINDINGS = {
    "verdict": "request_changes",
    "counts": {"critical": 1, "major": 0, "minor": 0, "nit": 0},
    "findings": [{"severity": "critical", "file": "probe/example.py", "line": 7,
                  "title": "probe finding",
                  "detail": "synthetic finding: it only exercises the generator contract",
                  "occurrences": ["probe-1"]}],
}

# The three edges the rule retired, as the flowchart drew them BEFORE the fix. The probe REBUILDS
# them from the current lines: if the shipped edge is gone, the probe says so instead of silently
# proving nothing.
PREFIX_EDGES = (
    # (current source, current label, current target, the pre-fix edge text)
    ("CRV0", "request_changes", "RD", "CRV0 -->|request_changes| G"),
    ("CRV", "request_changes, review/security_audit", "RD", "CRV -->|request_changes| RCR"),
    ("X", "No, review/security_audit", "XR", "X -->|No| RR"),
)
# The probe copy also carries the parser the guard imports, so the fixture tree is self-contained.
PROBE_EXTRA_FILE = ".agents/skills/code-factory/scripts/test_prompt_structure.py"


class ProbeError(RuntimeError):
    """The pre-fix probe cannot be built from the shipped text."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the messages survive a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def display(path: Path) -> str:
    """The path as the repository sees it (temp fixtures keep their absolute path)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def line_text(text: str, lineno: int) -> str:
    lines = text.splitlines()
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


# =============================================================================================
# FLOW GUARD
# =============================================================================================
def read_flow(path: Path) -> tuple[dict[str, list[tuple[str | None, str]]], str, int]:
    """(adjacency, mermaid block, 1-based file line of the block's first line).

    The adjacency comes from the sibling parser, so this test and `test_prompt_structure.py` walk
    exactly the same graph; the block offset is what turns a node id into `SKILL.md:<line>`.
    """
    text = path.read_text(encoding="utf-8")
    match = MERMAID_RE.search(text)
    if match is None:
        raise ValueError(f"{display(path)}: no ```mermaid block — the orchestration flow cannot "
                         "be checked")
    block = match.group(1)
    return parse_edges(block), block, line_of(text, match.start(1))


def edge_lines(block: str, first: int) -> dict[tuple[str, str | None, str], int]:
    """(source, label, target) -> 1-based file line, so a violation names a real line."""
    lines: dict[tuple[str, str | None, str], int] = {}
    for offset, raw in enumerate(block.splitlines()):
        match = EDGE_RE.match(raw)
        if not match:
            continue
        source, label, target = match.group(1), match.group(2), match.group(3)
        key = (source, label.strip() if label else None, target)
        lines.setdefault(key, first + offset)
    return lines


def node_text(block: str, node: str) -> str | None:
    """The bracketed label of a node definition; None when the node is never defined.

    The label is taken to the end of its line: node texts in this diagram carry nested `[...]`,
    and a balanced scan would buy nothing here.
    """
    match = re.search(rf"\b{re.escape(node)}\[", block)
    if match is None:
        return None
    end = block.find("\n", match.end())
    return block[match.end():] if end == -1 else block[match.end():end]


def blocks_implement(label: str | None) -> bool:
    """True when the label scopes itself to the write flow, i.e. a REVIEW context cannot take it."""
    return label is not None and IMPLEMENT_SCOPE in label.lower()


def edge_text(source: str, label: str | None, target: str) -> str:
    """The edge as the diagram writes it — a bare edge has no label to print."""
    return f"{source} --> {target}" if label is None else f"{source} -->|{label}| {target}"


def walk_review(edges: dict[str, list[tuple[str | None, str]]], first_hops: list[tuple[str, str | None, str]]
                ) -> dict[str, tuple[str, str | None]]:
    """BFS in a REVIEW context: node -> (incoming source, incoming label) of the BFS tree."""
    reached: dict[str, tuple[str, str | None]] = {}
    queue: deque[str] = deque()
    for _source, _label, target in first_hops:
        if target not in reached:
            reached[target] = (_source, _label)
            queue.append(target)
    while queue:
        node = queue.popleft()
        for label, target in edges.get(node, ()):
            if target in reached or blocks_implement(label):
                continue
            reached[target] = (node, label)
            queue.append(target)
    return reached


def path_to(reached: dict[str, tuple[str, str | None]], start: str, node: str) -> list[str]:
    """The BFS-tree path start -> ... -> node (cycles cannot occur in a tree)."""
    chain = [node]
    current = node
    for _ in range(len(reached) + 1):
        parent = reached.get(current)
        if parent is None:
            break
        chain.append(parent[0])
        if parent[0] == start:
            break
        current = parent[0]
    return list(reversed(chain))


def audit_flow(path: Path) -> list[str]:
    """Walk every review start node and report everything that leaves the report-only path."""
    edges, block, first = read_flow(path)
    lines = edge_lines(block, first)
    where = display(path)
    errors: list[str] = []

    for start in START_NODES:
        # The start restriction: only the labels that belong to this start node are entered, and a
        # label scoping itself to implement/refactor is not a review path in the first place — that
        # is what lets `X` follow `No, review/security_audit` and ignore `No, implement/refactor`.
        hops = [(start.name, label, target)
                for label, target in edges.get(start.name, [])
                if start.takes(label) and not blocks_implement(label)]
        if not hops:
            errors.append(f"review start {start.name}: {where}: no traversable edge out of "
                          f"{start.name} ({start.why}) — the delivery cannot be reached at all")
            continue

        reached = walk_review(edges, hops)
        intruders = sorted(node for node in reached if node in FORBIDDEN)
        if intruders:
            # The reached set is printed ONCE per start node: the offending path of every intruder
            # is on its own line below, the set is what shows an editor which branch was entered.
            errors.append(
                f"review start {start.name}: {where}: the reached set {sorted(reached)} holds "
                f"{len(intruders)} forbidden write node(s) ({', '.join(intruders)}) — {start.why}")
        for node in intruders:
            source, label = reached[node]
            lineno = lines.get((source, label, node))
            at = f"{where}:{lineno}" if lineno else f"{where}: (no edge line for {node})"
            errors.append(
                f"review start {start.name}: {at}: forbidden node {node} — {FORBIDDEN[node]}; "
                f"entered by {edge_text(source, label, node)}; "
                f"path: {' -> '.join(path_to(reached, start.name, node))}")

        if not any(node in reached for node in start.delivery):
            errors.append(
                f"review start {start.name}: {where}: reaches no delivery/stop node "
                f"({' or '.join(start.delivery)}) — {start.why}; reached set: {sorted(reached)}")
    return errors


def check_flow_guard() -> tuple[list[str], list[str]]:
    """The REVIEW context rule itself, then the walk over the real flowchart."""
    errors: list[str] = []
    # Pin the three-case context model: inverting `blocks_implement` would turn the guard into the
    # opposite guard (it would forbid the review path and allow the write path) and the walk alone
    # could still look green on some future diagram.
    for label, blocked, why in (
        (None, False, "a bare edge carries no scope and is part of every branch"),
        ("request_changes, review/security_audit", False,
         "the review/security_audit label is the review path"),
        ("request_changes, implement/refactor", True,
         "the implement/refactor label is the write path"),
    ):
        if blocks_implement(label) != blocked:
            errors.append(f"{display(Path(__file__))}: the REVIEW context model is inverted for "
                          f"label {label!r} — {why}")
    errors.extend(audit_flow(SKILL))
    return [], errors


# =============================================================================================
# DELIVERY GUARD
# =============================================================================================
def check_delivery_guard() -> tuple[list[str], list[str]]:
    """`RD` is the delivery, `XR` the stop-and-ask-owner node; both must be wired as promised."""
    errors: list[str] = []
    edges, block, first = read_flow(SKILL)
    lines = edge_lines(block, first)
    where = display(SKILL)

    # 1. RD exists and its text is the report + the generated follow-up task file.
    text = node_text(block, "RD")
    if text is None:
        errors.append(f"{where}: the delivery node RD is not defined — a review run has no "
                      "report-only exit")
    else:
        lineno = lines.get(("CRV0", "approve", "RD"), first)
        for needle, why in (
            ("the report", "the deliverable is the report"),
            (".code-factory/review/fix-tasks.yaml", "the deliverable names the follow-up task file"),
            ("scripts/review_followup_task.py", "the follow-up task file is GENERATED, not written "
                                                "by hand"),
        ):
            if needle.lower() not in text.lower():
                errors.append(f"{where}:{lineno}: the RD delivery does not name {needle!r} — {why}")

    # 2. Both CRV0 labels point at the delivery, not at a coder.
    crv0 = edges.get("CRV0", [])
    labels = sorted((label or "").lower() for label, _target in crv0)
    if labels != ["approve", "request_changes"]:
        errors.append(f"{where}:{lines.get(('CRV0', 'approve', 'RD'), first)}: CRV0 must carry "
                      f"exactly the labels ['approve', 'request_changes'], found {labels} — the "
                      "review verdict pair changed")
    for label, target in crv0:
        if target != "RD":
            lineno = lines.get(("CRV0", label, target), first)
            errors.append(f"{where}:{lineno}: CRV0 -->|{label}| {target}: every review verdict must "
                          "land on the report-only delivery RD, never on a write node")

    # 3. XR exists and is fed by the review/security_audit acceptance-failure label.
    if node_text(block, "XR") is None and not any(
            target == "XR" for neighbours in edges.values() for _l, target in neighbours):
        errors.append(f"{where}: the stop-and-ask-owner node XR is missing — an unmet review "
                      "criterion would have nowhere to stop")
    feeders = [(source, label) for source, neighbours in edges.items()
               for label, target in neighbours
               if target == "XR" and label_names_review(label)
               and (label or "").lower().startswith("no")]
    if not feeders:
        errors.append(f"{where}:{lines.get(('X', 'No, review/security_audit', 'XR'), first)}: XR is "
                      "fed by no acceptance-failure label naming review/security_audit — an unmet "
                      "review criterion would fall back into the implement branch")
    return [], errors


# =============================================================================================
# TEXT GUARD
# =============================================================================================
def mask_rule_blocks(text: str) -> str:
    """Blank every `factory-rule` block, keeping the newlines so line numbers stay true.

    The canonical wording is guarded by `check_factory_rules.py` (byte-identical carriers), which
    is stricter than anything this test could say; here only the PROSE around it matters.
    """
    return RULE_BLOCK_RE.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)), text)


def unit_index(lines: list[str]) -> list[int]:
    """Unit id per line: a markdown paragraph, and a fenced block (the diagram) as ONE unit.

    A node label inside the flowchart is not a sentence, so the diagram is one unit; it is guarded
    by the FLOW GUARD instead, which reads labels and edges rather than prose.
    """
    ids: list[int] = []
    unit = -1
    is_open = False
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if in_fence:
            ids.append(unit)
            if stripped.startswith("```"):
                in_fence = False
                is_open = False
            continue
        if stripped.startswith("```"):
            if not is_open:
                unit += 1
                is_open = True
            in_fence = True
            ids.append(unit)
            continue
        if not stripped:
            is_open = False
            ids.append(unit)
            continue
        if not is_open:
            unit += 1
            is_open = True
        ids.append(unit)
    return ids


def units(lines: list[str], ids: list[int]) -> Iterator[tuple[int, str]]:
    """(unit id, joined text) for every unit, in line order."""
    current: int | None = None
    buffer: list[str] = []
    for index, line in enumerate(lines):
        if ids[index] != current:
            if current is not None:
                yield current, "\n".join(buffer)
            current, buffer = ids[index], []
        buffer.append(line)
    if current is not None:
        yield current, "\n".join(buffer)


def check_text_guard() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    for relative in TEXT_FILES:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"{relative}: not found — the document that must not contradict the "
                          "rule is missing")
            continue
        text = mask_rule_blocks(path.read_text(encoding="utf-8"))
        lowered = text.lower()

        for phrase in LEGACY_PHRASES:
            for match in re.finditer(re.escape(phrase), lowered):
                lineno = line_of(text, match.start())
                errors.append(f"{relative}:{lineno}: the retired promise {phrase!r} is back: "
                              f"{line_text(text, lineno)}")

        ids = unit_index(text.splitlines())
        unit_text = dict(units(text.splitlines(), ids))
        for match in re.finditer(r"rework list", lowered):
            lineno = line_of(text, match.start())
            context = unit_text.get(ids[lineno - 1], "")
            if not any(word in context.lower() for word in QUALIFIERS):
                errors.append(
                    f"{relative}:{lineno}: 'rework list' is not qualified by implement/refactor/"
                    f"scope in its sentence, so it reads as this run's own work: "
                    f"{line_text(text, lineno)}")
    return [], errors


# =============================================================================================
# GENERATOR CONTRACT
# =============================================================================================
def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """A CLI run of a sibling script with the CURRENT interpreter, UTF-8 decoded."""
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def check_generator(tmp: Path) -> tuple[list[str], list[str]]:
    """The hand-over is a REAL file: advertised CLI, real input, deterministic output."""
    tmp.mkdir(parents=True, exist_ok=True)          # every write stays inside `tempfile`
    notes: list[str] = []
    errors: list[str] = []
    if not GENERATOR.is_file():
        return notes, [f"{display(GENERATOR)}: not found — a review run would have no hand-over"]

    help_run = run_cli(str(GENERATOR), "--help")
    if help_run.returncode != 0:
        errors.append(f"{display(GENERATOR)}: --help exited {help_run.returncode}: "
                      f"{(help_run.stderr or help_run.stdout).strip()[:200]}")
    usage = f"{help_run.stdout}\n{help_run.stderr}"
    for flag in ("--findings", "--repo", "--out"):
        if flag not in usage:
            errors.append(f"{display(GENERATOR)}: --help does not advertise {flag}")

    synthetic = tmp / "synthetic-findings.json"
    synthetic.write_text(json.dumps(SYNTHETIC_FINDINGS, indent=2), encoding="utf-8")
    source = REVIEW_FINDINGS if REVIEW_FINDINGS.is_file() else synthetic
    if source == synthetic:
        notes.append(f"{display(REVIEW_FINDINGS)} is absent (runtime state): the contract is proven "
                     "on a synthetic findings file, not on the shipped review")

    out = tmp / "fix-tasks.yaml"
    first = _generate(source, out)
    if not out.is_file():
        if source != synthetic:
            notes.append(f"{display(REVIEW_FINDINGS)} yields no follow-up file (the review "
                         "accepted the tree and found nothing) — falling back to a synthetic "
                         "findings file to prove the contract")
            source = synthetic
            out.unlink(missing_ok=True)
            first = _generate(source, out)
    if first.returncode != 0 or not out.is_file():
        errors.append(f"{display(GENERATOR)}: the end-to-end run did not produce "
                      f"{display(out)}: exit {first.returncode}, "
                      f"{(first.stderr or first.stdout).strip()[:200]}")
        return notes, errors

    raw = out.read_bytes()                          # bytes to bytes: the newline policy cannot lie
    body = raw.decode("utf-8", "replace")
    # The generator emits EVERY scalar as a YAML double-quoted string, so the task type reads
    # `task_type: "implement"`: the key is checked quote-tolerantly instead of as a substring.
    for pattern, why in (
        (r"^task_type:\s*\"?implement\"?\s*$", "a review hands its findings over as an implement task"),
        (r"^repo_path:", "the owner must know which repository the task targets"),
        (r"^acceptance_criteria:", "every finding must become a verifiable criterion"),
        (r"^\s+derived:\s*true\s*$", "a derived criterion is not evidence and must be labelled"),
    ):
        if not re.search(pattern, body, re.MULTILINE):
            errors.append(f"{display(out)}: the generated task has no line matching {pattern!r} — "
                          f"{why}")

    second = _generate(source, out)
    if second.returncode != 0:
        errors.append(f"{display(GENERATOR)}: the second run exited {second.returncode}: "
                      f"{(second.stderr or second.stdout).strip()[:200]}")
    elif out.read_bytes() != raw:
        errors.append(f"{display(GENERATOR)}: two runs on the same input are NOT byte-identical — "
                      "the hand-over is not deterministic")
    return notes, errors


def _generate(source: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return run_cli(str(GENERATOR), "--findings", str(source), "--repo", str(ROOT), "--out", str(out))


# =============================================================================================
# ACCEPTANCE-STOP
# =============================================================================================
def check_acceptance_stop() -> tuple[list[str], list[str]]:
    """A review criterion that is not MET stops the run — the tool must know it judges a review."""
    errors: list[str] = []
    if not ACCEPTANCE.is_file():
        return [], [f"{display(ACCEPTANCE)}: not found — an unmet criterion could not be detected"]
    help_run = run_cli(str(ACCEPTANCE), "--help")
    if help_run.returncode != 0:
        errors.append(f"{display(ACCEPTANCE)}: --help exited {help_run.returncode}: "
                      f"{(help_run.stderr or help_run.stdout).strip()[:200]}")
    if "--task-type" not in f"{help_run.stdout}\n{help_run.stderr}":
        errors.append(f"{display(ACCEPTANCE)}: --help does not list --task-type, so a review run "
                      "cannot be told its failure is an authoring error instead of a rework order")
    if not ACCEPTANCE_TEST.is_file():
        errors.append(f"{display(ACCEPTANCE_TEST)}: not found — the acceptance-stop semantics have "
                      "no pinning suite")
    return [], errors


# =============================================================================================
# NEGATIVE / VACCINATION PROBE
# =============================================================================================
def restore_prefix_edges(text: str) -> str:
    """Rewrite the three current edges into the edges the rule retired (probe fixture only)."""
    for source, label, target, prefix in PREFIX_EDGES:
        pattern = re.compile(rf"^([ \t]*){re.escape(source)}[ \t]*-->[ \t]*\|{re.escape(label)}\|"
                             rf"[ \t]*{re.escape(target)}\b", re.MULTILINE)
        text, count = pattern.subn(lambda match: f"{match.group(1)}{prefix}", text)
        if count != 1:
            raise ProbeError(
                f"the pre-fix probe cannot be built: the edge {source} -->|{label}| {target} "
                f"occurs {count} times in {display(SKILL)} — the flowchart changed, update "
                "PREFIX_EDGES to the edges the rule retires")
    return text


def check_negative_probe(tmp: Path) -> tuple[list[str], list[str]]:
    """The guard must FAIL on the pre-fix graph — otherwise it proves nothing."""
    errors: list[str] = []
    notes: list[str] = []
    tree = tmp / "probe-tree"
    for relative in (*TEXT_FILES, PROBE_EXTRA_FILE):
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    probe_skill = tree / ".agents" / "skills" / "code-factory" / "SKILL.md"

    # The copy as shipped must pass, so a failure below comes from the restored edges only.
    pristine = audit_flow(probe_skill)
    if pristine:
        errors.append(f"{display(probe_skill)}: the unmodified copy already fails the flow guard "
                      f"({len(pristine)} violation(s)) — the probe could not be attributed")
        return notes, errors

    try:
        probe_skill.write_text(restore_prefix_edges(probe_skill.read_text(encoding="utf-8")),
                               encoding="utf-8")
    except ProbeError as exc:
        return notes, [str(exc)]

    caught = audit_flow(probe_skill)
    if not caught:
        errors.append(f"{display(probe_skill)}: the PRE-FIX graph passes the flow guard — the guard "
                      "is a tautology and would not notice the rule being undone")
        return notes, errors

    for start in START_NODES:
        hits = [message for message in caught if message.startswith(f"review start {start.name}:")]
        if not hits:
            errors.append(f"{display(probe_skill)}: the pre-fix graph is not caught from review "
                          f"start {start.name} ({start.why}) — that start node is unguarded")
        elif not any(re.search(r"forbidden node ([A-Z0-9]+)", message) for message in hits):
            errors.append(f"{display(probe_skill)}: the pre-fix graph is caught from {start.name} "
                          "but no violation names a forbidden node")
    # A stable, side-effect-free summary of the proof: how many violations, which nodes, one path.
    reached_nodes = sorted({node for message in caught
                            for node in re.findall(r"forbidden node ([A-Z0-9]+)", message)})
    first_path = next((message for message in caught if "path: " in message), caught[0])
    notes.append(f"pre-fix probe: {len(caught)} violation(s) on the restored (pre-fix) graph; "
                 f"forbidden nodes caught: {', '.join(reached_nodes)}; first path: "
                 f"{first_path.replace(tree.as_posix(), '<probe-tree>')}")
    return notes, errors


# =============================================================================================
def main() -> int:
    use_utf8_output()
    cases: list[tuple[str, Callable[[], tuple[list[str], list[str]]]]] = [
        ("flow-guard", check_flow_guard),
        ("delivery-guard", check_delivery_guard),
        ("text-guard", check_text_guard),
        ("generator-contract", lambda: _with_tmp(check_generator)),
        ("acceptance-stop", check_acceptance_stop),
        ("negative-probe", lambda: _with_tmp(check_negative_probe)),
    ]

    failed = 0
    for name, case in cases:
        try:
            notes, errors = case()
        except Exception as exc:                  # a broken guard must be loud, never silent
            notes, errors = [], [f"{name}: the check itself crashed: {exc!r}"]
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
        if errors:
            failed += 1
            print(f"FAIL {name} - {len(errors)} violation(s):", file=sys.stderr)
            for message in errors:
                print(f"  {message}", file=sys.stderr)
        else:
            print(f"PASS {name}")

    if failed:
        print(f"FAIL - {failed} of {len(cases)} checks failed: `review-report-only` is not "
              "guaranteed by the shipped files", file=sys.stderr)
        return 1
    print(f"PASS - `review-report-only` holds in {len(cases)} checks: no review verdict reaches a "
          "write node, the delivery is the report plus the generated fix-tasks file, the retired "
          "promise is gone, the unmet criterion stops the owner, and the pre-fix graph IS caught")
    return 0


def _with_tmp(case: Callable[[Path], tuple[list[str], list[str]]]
              ) -> tuple[list[str], list[str]]:
    """Run a case that needs a scratch tree; every mutation stays inside `tempfile`."""
    with tempfile.TemporaryDirectory(prefix="review-report-only-") as tmp:
        return case(Path(tmp))


if __name__ == "__main__":
    sys.exit(main())

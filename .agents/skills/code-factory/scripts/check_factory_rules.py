#!/usr/bin/env python3
"""
Deterministic consistency checker for the factory rulebook (zero LLM tokens).

`references/factory-rules.md` is the ONE home of the factory's mandatory rules. Each rule is a
section `## <id>` with a machine-readable `carriers:` line and a marked canonical block:

    <!-- factory-rule: <id> begin -->
    ...canonical wording...
    <!-- factory-rule: <id> end -->

The same marked block is quoted VERBATIM in every carrier document. Prose copies drift, a
machine-checked copy does not: this script parses the rulebook, pulls the marked block out of
every carrier and fails when a carrier is missing the block, carries it twice, or holds a block
that differs by even one byte after `.strip()` from the rulebook's canonical wording (the
canonical wordings are single lines, so CRLF files compare equal). Rules may additionally declare
REQUIRED_MARKERS — sentences that must survive inside the canonical block, so a gate cannot be
watered down by rewriting the rulebook and all carriers at once.

A marked block covers only the rule's canonical sentence, so the WORKFLOW PROSE around it — Mermaid
node wording, tool names, the order of an approval step — escapes that check. `check_workflow_prose`
closes that gap for the three carriers of the HITL approval gate (SKILL.md, code-factory.md,
planning-guide.md): it reads their FULL text, rejects the dead `EnterPlanMode` tool anywhere, and
requires each approval section to name `.code-factory/state/plan.md` and `AskUserQuestion` BEFORE it
waits for the answer. A missing or unreadable carrier is a named problem of the report, never a
traceback.

Usage:
  python3 check_factory_rules.py [--rule <id>] [--root <path>]

  --rule   check a single rule id (default: every rule of the rulebook)
  --root   repository root the rulebook and the carrier paths resolve against
           (default: the root this script lives in)

Exit code 0 = every checked rule is consistent everywhere, 1 = the list of discrepancies.
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import sys

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
ROOT = pathlib.Path(__file__).resolve().parents[4]

RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"

RULE_RE = re.compile(r"^##\s+(\S+)\s*$")
CARRIERS_RE = re.compile(r"^carriers:\s*(.+?)\s*$")

# Sentences the canonical wording of a rule must keep, whatever else it says.
REQUIRED_MARKERS = {
    "review-gate-policy": ("unverified_review", "conditional pass", "hitl", "auto"),
    # The stop rule must keep saying WHAT happens (a stop, with the two modes), that no role work is
    # handed over or substituted, and that an unknown role is an error rather than a degradation.
    "model-unavailable-stop": ("STOPS", "NEVER substitutes", "`ROLES`"),
}

# Kimi Code ships no `EnterPlanMode` tool (plan mode is user-only, Shift-Tab or /plan): an
# instruction to call it is a dead call an agent would follow straight into a tool error.
FORBIDDEN_TOOL = "EnterPlanMode"
# What every approval section must present to the user BEFORE it waits for the answer: the plan
# file the user is deciding on, and the tool that asks the decision.
APPROVAL_TOKENS = (".code-factory/state/plan.md", "AskUserQuestion")
# The wait/revision step of an approval section. Case-insensitive and wording-tolerant on purpose:
# this pass judges the ORDER of the gate, not the exact sentence a carrier chose.
APPROVAL_WAIT_RE = re.compile(r"wait for (the )?(answer|approval)", re.I)


@dataclasses.dataclass(frozen=True)
class Rule:
    """One rulebook entry: id, the documents that must quote it, its canonical wording."""

    rule_id: str
    carriers: tuple[str, ...]
    text: str


def markers(rule_id: str) -> tuple[str, str]:
    return (f"<!-- factory-rule: {rule_id} begin -->",
            f"<!-- factory-rule: {rule_id} end -->")


@dataclasses.dataclass(frozen=True)
class ApprovalSection:
    """One HITL approval section: the carrier and the span of prose the gate is read from."""

    carrier: str
    name: str
    section_re: re.Pattern[str]   # names the section body as group "body"


# The three carriers of the HITL approval gate. Each section is the prose a reader (or an agent)
# actually follows, so its step order is a contract: present the plan file, ask via AskUserQuestion,
# THEN wait.
APPROVAL_SECTIONS = (
    ApprovalSection(
        carrier=".agents/skills/code-factory/SKILL.md",
        name="flowchart node I",
        section_re=re.compile(r"^ *H --> I\[(?P<body>[^\]]*)\]", re.M),
    ),
    ApprovalSection(
        carrier=".agents/agents/code-factory.md",
        name="Phase 3 approval step",
        section_re=re.compile(r"^### Phase 3[^\n]*\n(?P<body>.*?)(?=^#{2,3} |\Z)", re.M | re.S),
    ),
    ApprovalSection(
        carrier=".agents/skills/code-factory/references/planning-guide.md",
        name="section 6 (present the plan)",
        section_re=re.compile(r"^## 6\.[^\n]*\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S),
    ),
)


def extract_block(text: str, rule_id: str) -> str | None:
    """Inner text of the single marked block of `rule_id`; None when absent/duplicated/empty."""
    begin, end = markers(rule_id)
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    if stop <= start:
        return None
    return text[start:stop].strip() or None


def parse_rulebook(text: str) -> tuple[list[Rule], list[str]]:
    """Parse the rulebook into rules; return (rules, registry problems)."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        match = RULE_RE.match(line)
        if match:
            sections.append((match.group(1), []))
        elif sections:
            sections[-1][1].append(line)

    rules: list[Rule] = []
    problems: list[str] = []
    seen: set[str] = set()
    for rule_id, body in sections:
        if rule_id in seen:
            problems.append(f"{RULEBOOK}: rule {rule_id!r} is declared twice")
            continue
        seen.add(rule_id)
        joined = "\n".join(body)
        block = extract_block(joined, rule_id)
        if block is None:
            problems.append(f"{RULEBOOK}: rule {rule_id!r} has no marked canonical block")
            continue
        carriers: tuple[str, ...] = ()
        for line in body:
            match = CARRIERS_RE.match(line)
            if match:
                carriers = tuple(c.strip() for c in match.group(1).split(";") if c.strip())
                break
        if not carriers:
            problems.append(f"{RULEBOOK}: rule {rule_id!r} declares no carriers")
            continue
        rules.append(Rule(rule_id, carriers, block))
    return rules, problems


def check_rule(root: pathlib.Path, rule: Rule) -> list[str]:
    """Compare the rule's canonical wording with the marked block of every carrier."""
    problems: list[str] = []
    for marker in REQUIRED_MARKERS.get(rule.rule_id, ()):
        if marker not in rule.text:
            problems.append(f"{RULEBOOK}: canonical block of {rule.rule_id!r} lost the "
                            f"marker {marker!r}")
    for carrier in rule.carriers:
        path = root / carrier
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{carrier}: block {rule.rule_id!r} is missing "
                            f"(file unreadable: {exc.strerror or exc})")
            continue
        block = extract_block(body, rule.rule_id)
        if block is None:
            problems.append(f"{carrier}: block {rule.rule_id!r} is missing, duplicated or empty")
        elif block != rule.text:
            problems.append(f"{carrier}: block {rule.rule_id!r} differs from the {RULEBOOK} "
                            "canonical wording")
    return problems


def dead_tool_problems(carrier: str, text: str) -> list[str]:
    """Every line of `text` that names the dead tool, as a `file:line` problem."""
    return [f"{carrier}:{number}: names the dead tool {FORBIDDEN_TOOL!r}, which Kimi Code does not "
            "provide; the approval gate writes the plan file and asks via AskUserQuestion"
            for number, line in enumerate(text.splitlines(), 1) if FORBIDDEN_TOOL in line]


def approval_problems(section: ApprovalSection, text: str) -> list[str]:
    """The section must exist, state its wait step, and name both approval tokens before it."""
    match = section.section_re.search(text)
    if match is None:
        return [f"{section.carrier}: the HITL approval section ({section.name}) is missing"]
    body = match.group("body")
    wait = APPROVAL_WAIT_RE.search(body)
    problems: list[str] = []
    if wait is None:
        problems.append(f"{section.carrier}: the {section.name} states no wait step "
                        f"({APPROVAL_WAIT_RE.pattern!r}), so the user is never waited for")
    limit = wait.start() if wait else len(body)
    for token in APPROVAL_TOKENS:
        at = body.find(token)
        if at < 0:
            problems.append(f"{section.carrier}: the {section.name} does not name {token!r} before "
                            "the wait step")
        elif at >= limit:
            problems.append(f"{section.carrier}: the {section.name} names {token!r} only AFTER the "
                            "wait step; the approval gate must present the plan and ask the user "
                            "before it waits")
    return problems


def check_workflow_prose(root: pathlib.Path) -> list[str]:
    """Validate the approval prose of the workflow carriers, outside their factory-rule blocks.

    `check_rule()` reduces a carrier to one marked block, so the flowchart node text, the tool
    names and the step order around it were never validated. This pass reads the FULL text of the
    three carriers: a dead tool anywhere is rejected, and every approval section must present
    `.code-factory/state/plan.md` and `AskUserQuestion` before it waits for the answer. A missing or
    unreadable carrier is reported as its own problem instead of raising.
    """
    problems: list[str] = []
    texts: dict[str, str] = {}
    for carrier in dict.fromkeys(section.carrier for section in APPROVAL_SECTIONS):
        try:
            texts[carrier] = (root / carrier).read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{carrier}: workflow prose is unreadable ({exc.strerror or exc}), so "
                            "its HITL approval section cannot be checked")
            continue
        problems.extend(dead_tool_problems(carrier, texts[carrier]))
    for section in APPROVAL_SECTIONS:
        if section.carrier in texts:
            problems.extend(approval_problems(section, texts[section.carrier]))
    return problems


def check(root: pathlib.Path, rule_ids: list[str]) -> tuple[int, list[str], int]:
    """Return (how many rules were checked, problems, how many carrier blocks were compared)."""
    try:
        text = (root / RULEBOOK).read_text(encoding="utf-8")
    except OSError as exc:
        return 0, [f"{RULEBOOK}: cannot read the rulebook under {root} "
                   f"({exc.strerror or exc})"], 0

    rules, problems = parse_rulebook(text)
    if not rules:
        problems.append(f"{RULEBOOK}: the rulebook declares no rule with carriers")

    if rule_ids:
        known = {rule.rule_id for rule in rules}
        for rule_id in rule_ids:
            if rule_id not in known:
                problems.append(f"{rule_id!r}: unknown rule; the rulebook declares "
                                f"{', '.join(sorted(known)) or 'no rules'}")
        rules = [rule for rule in rules if rule.rule_id in rule_ids]

    checked_carriers = 0
    for rule in rules:
        checked_carriers += len(rule.carriers)
        problems.extend(check_rule(root, rule))
    # The marked blocks do not cover the workflow prose around them: the approval gate is validated
    # by its own pass, always, in addition to the per-rule reconciliation.
    problems.extend(check_workflow_prose(root))
    return len(rules), problems, checked_carriers


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so printed rule ids, paths and messages survive a legacy console.

    A Windows console defaults to a legacy code page (cp866/cp1251) and this report carries rule
    ids, file paths and messages that codec may not encode: printing them would raise
    UnicodeEncodeError and the user would get a traceback instead of the report. `errors="replace"`
    keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main(argv: list[str]) -> int:
    use_utf8_output()
    parser = argparse.ArgumentParser(description="Check the factory rulebook against its carriers.")
    parser.add_argument("--rule", action="append", default=[], metavar="ID",
                        help="rule id to check (repeatable; default: every rule)")
    parser.add_argument("--root", default=None,
                        help="repository root the paths resolve against (default: this repo)")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else ROOT
    checked_rules, problems, carriers = check(root, args.rule)
    if problems:
        print(f"FAIL - {len(problems)} factory-rule/workflow discrepancy(ies) under {root}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    # `checked_rules` is a COUNT, not a collection: the scope phrase and the count phrase both
    # name it, so a reader cannot mistake the first number for a number of rule sets.
    scope = ", ".join(args.rule) if args.rule else f"all {checked_rules} rules"
    print(f"PASS - {scope}: {checked_rules} rule(s) checked, byte-identical in {carriers} "
          f"carrier block(s) ({root}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

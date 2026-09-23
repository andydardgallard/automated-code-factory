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
}


@dataclasses.dataclass(frozen=True)
class Rule:
    """One rulebook entry: id, the documents that must quote it, its canonical wording."""

    rule_id: str
    carriers: tuple[str, ...]
    text: str


def markers(rule_id: str) -> tuple[str, str]:
    return (f"<!-- factory-rule: {rule_id} begin -->",
            f"<!-- factory-rule: {rule_id} end -->")


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


def check(root: pathlib.Path, rule_ids: list[str]) -> tuple[int, list[str], int]:
    """Return (checked rules, problems, checked carriers) for `rule_ids` under `root`."""
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
    rules, problems, carriers = check(root, args.rule)
    if problems:
        print(f"FAIL - {len(problems)} factory-rule discrepancy(ies) under {root}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    scope = ", ".join(args.rule) if args.rule else f"all {rules} rules"
    print(f"PASS - {scope}: {rules} rule(s) byte-identical in {carriers} carrier block(s) "
          f"({root}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

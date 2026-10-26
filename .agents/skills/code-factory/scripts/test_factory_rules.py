#!/usr/bin/env python3
"""
Deterministic self-test for the factory rulebook and its consistency checker (zero LLM tokens).

`references/factory-rules.md` is the single home of the factory's mandatory rules; every rule
declares its carriers and a marked `<!-- factory-rule: <id> begin/end -->` canonical block that
must be quoted VERBATIM in those documents. `check_factory_rules.py` is that check, and this test
verifies both halves of the contract:

  - the registry parses: every rule has at least one carrier, every carrier path exists in the
    repository, every rule carries exactly one marked block in the rulebook, and the review-gate
    rule still points at its four canonical documents;
  - the checker PASSES on the real repository for EVERY rule (the carrier migration is complete),
    and the review-gate rule still points at its four canonical documents;
  - the root `AGENTS.md` is a POINTER, not a carrier: it quotes no `factory-rule` block at all, it
    names every rule it relies on with a pointer line into the rulebook (a rule silently dropped
    from the map is caught), and it stays under the 32 KB AGENTS.md size gate; this is what keeps
    the hand-authored manual a map instead of a 38 KB second copy of the rulebook;
  - the PASS line names the count of checked rules as a COUNT (`all <n> rules: <n> rule(s)
    checked, byte-identical in <m> carrier block(s) (<root>).`), never as a collection;
  - the mechanics are proven on throwaway copies (tempdir, `--root`): a clean tree passes, a
    carrier with one extra clause fails as "differs", a carrier without the block fails as
    "missing", a duplicated block is rejected too, watering the gate down in ALL carriers at once
    is still caught (the rulebook keeps the canonical wording), an unknown rule id fails and a
    missing rulebook fails instead of silently passing.

Negative checks always run on tempdir copies, never on the real documents.

Exit code 0 = all assertions pass, 1 = the checker did not behave as expected.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
TOOL = SCRIPTS / "check_factory_rules.py"

RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
RULE = "review-gate-policy"
GATE_CARRIERS = (
    ".agents/README.md",
    ".agents/agents/code-factory.md",
    ".agents/skills/code-factory/SKILL.md",
    ".agents/skills/code-factory/references/code-review.md",
)
# The root AGENTS.md is a hand-authored MAP, not a carrier: it must NOT quote any rule (that is how
# it grew past the size gate) and must keep a pointer line for every rule it relies on.
AGENTS = "AGENTS.md"
AGENTS_POINTER_RULES = (
    "artifacts-first", "commit-exclude", "destructive-action-gate", "documentation",
    "english-only", "evidence-ledger", "git-native", "handoff-briefing", "memory-actuality",
    "memory-ownership", "memory-provenance", "models-generator-ne-judge",
    "no-shared-tree-git-mutations", "plan-committee", "repo-scoping", "retry-budgets",
    "review-gate-policy", "review-report-only", "run-id", "shard-protocol", "task-format",
    "vaccination", "verified-acceptance", "versioning",
)
AGENTS_SIZE_FAIL_BYTES = 32 * 1024
REQUIRED_MARKERS = ("unverified_review", "conditional pass", "hitl", "auto")
LEGACY_MARKER = "<!-- review-gate-policy:"
RULE_HEADING_RE = re.compile(r"^##\s+(\S+)\s*$")
CARRIERS_RE = re.compile(r"^carriers:\s*(.+?)\s*$")
# The pass lines the checker prints. The count of rules must appear as a COUNT of rules
# (`<n> rule(s) checked`), never as if the first number were a number of collections.
RULE_PASS_RE = re.compile(
    rf"^PASS - {re.escape(RULE)}: (\d+) rule\(s\) checked, byte-identical in "
    rf"(\d+) carrier block\(s\) \(.+\)\.$", flags=re.M)
FULL_PASS_RE = re.compile(
    r"^PASS - all (\d+) rules: (\d+) rule\(s\) checked, byte-identical in "
    r"(\d+) carrier block\(s\) \(.+\)\.$", flags=re.M)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def markers(rule_id: str) -> tuple[str, str]:
    return (f"<!-- factory-rule: {rule_id} begin -->",
            f"<!-- factory-rule: {rule_id} end -->")


def parse_registry(text: str) -> dict[str, list[str]]:
    """`{rule_id: [carrier, ...]}` as declared by the rulebook headings and `carriers:` lines."""
    registry: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = RULE_HEADING_RE.match(line)
        if heading:
            current = heading.group(1)
            registry.setdefault(current, [])
            continue
        carriers = CARRIERS_RE.match(line)
        if current and carriers and not registry[current]:
            registry[current] = [c.strip() for c in carriers.group(1).split(";") if c.strip()]
    return registry


def canonical_block(text: str, rule_id: str) -> str:
    """The rulebook's canonical wording of `rule_id` (single marked block)."""
    begin, end = markers(rule_id)
    expect(text.count(begin) == 1 and text.count(end) == 1,
           f"the rulebook must hold exactly one marked block for {rule_id!r}")
    return text[text.index(begin) + len(begin):text.index(end)].strip()


def make_tree(dst: pathlib.Path) -> list[pathlib.Path]:
    """(Re)build a throwaway root: the rulebook plus the review-gate carriers, byte-identical."""
    if dst.exists():
        shutil.rmtree(dst)
    (dst / RULEBOOK).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / RULEBOOK, dst / RULEBOOK)
    copies = []
    for carrier in GATE_CARRIERS:
        target = dst / carrier
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / carrier, target)
        copies.append(target)
    return copies


def main() -> int:
    # 1. the registry parses and every rule is complete: carriers declared and resolvable.
    book = (ROOT / RULEBOOK).read_text(encoding="utf-8")
    registry = parse_registry(book)
    expect(len(registry) >= 19, f"the rulebook must declare the whole registry: {len(registry)}")
    for rule_id, carriers in registry.items():
        expect(carriers, f"rule {rule_id!r} must declare at least one carrier")
        for carrier in carriers:
            expect((ROOT / carrier).is_file(),
                   f"carrier {carrier!r} of rule {rule_id!r} does not exist in the repository")
        block = canonical_block(book, rule_id)
        expect(block, f"rule {rule_id!r} must carry a non-empty marked block")
    expect(RULE in registry, f"the rulebook must declare the rule {RULE!r}")
    expect(set(registry[RULE]) == set(GATE_CARRIERS),
           f"{RULE!r} must point at its four canonical documents: {registry[RULE]}")
    gate_block = canonical_block(book, RULE)

    # 1b. The root AGENTS.md is a MAP, not a carrier: it quotes nothing and points at every rule it
    #     relies on (a rule silently dropped from the map is caught), inside the size gate.
    agents_text = (ROOT / AGENTS).read_text(encoding="utf-8")
    declared = {carrier for carriers in registry.values() for carrier in carriers}
    expect(AGENTS not in declared,
           f"{AGENTS} must not be declared a verbatim carrier of any rule: it points, it does not "
           "quote (a second verbatim copy only drifts and doubles the file)")
    expect("factory-rule:" not in agents_text,
           f"{AGENTS} must not quote a factory-rule block: the rulebook is the single verbatim home")
    for rule_id in AGENTS_POINTER_RULES:
        expect(rule_id in registry, f"the pinned pointer {rule_id!r} is no longer a rulebook rule")
        expect(f"- Rule `{rule_id}`: canonical wording — `{RULEBOOK}` (`## {rule_id}`)." in agents_text,
               f"{AGENTS} must keep its pointer to rule {rule_id!r}: guidance must not vanish "
               "when a quote is replaced by a reference")
    agents_size = len(agents_text.encode("utf-8"))
    expect(agents_size < AGENTS_SIZE_FAIL_BYTES,
           f"{AGENTS} is {agents_size} bytes, over the 32 KB size gate: trim verbatim text into "
           "references/ and keep pointers")

    # 2. the migrated rule is consistent on the real repository, and the old marker is gone.
    res = run("--rule", RULE)
    expect(res.returncode == 0,
           f"check_factory_rules.py --rule {RULE} must exit 0: {res.stdout!r} {res.stderr!r}")
    expect("PASS" in res.stdout, f"the checker must report PASS: {res.stdout!r}")
    # The pass line names the count ONCE as a count, never as if it were a collection of rules:
    # `PASS - <id>: 1 rule(s) checked, byte-identical in <m> carrier block(s) (<root>).`
    expect("rule(s) checked" in res.stdout,
           f"the pass line must say what was checked: {res.stdout!r}")
    single = RULE_PASS_RE.search(res.stdout)
    expect(single is not None,
           f"the --rule pass line must read `1 rule(s) checked, byte-identical in ...`: "
           f"{res.stdout!r}")
    expect(single.group(1) == "1",
           f"a single --rule run checks exactly one rule: {res.stdout!r}")
    expect(int(single.group(2)) >= len(GATE_CARRIERS),
           f"the carrier block count must be printed: {res.stdout!r}")
    for carrier in GATE_CARRIERS:
        expect(LEGACY_MARKER not in (ROOT / carrier).read_text(encoding="utf-8"),
               f"{carrier}: the legacy review-gate marker must be migrated to factory-rule")

    # 3. a full run (no --rule) must PASS: the carrier migration is complete, every rule of the
    #    rulebook is byte-identical in all of its carriers (the checker stays a plain 0/1 verdict).
    full = run()
    expect(full.returncode == 0,
           f"a full run must exit 0 (all rules are consistent): {full.stdout!r} {full.stderr!r}")
    # The count of checked rules is a COUNT of rules, not a number of collections: both numbers of
    # the summary are the same integer, and the sentence says `rule(s) checked`.
    expect("rule(s) checked" in full.stdout,
           f"the pass line must say what was checked: {full.stdout!r}")
    wide = FULL_PASS_RE.search(full.stdout)
    expect(wide is not None,
           f"the pass line must read `PASS - all <n> rules: <n> rule(s) checked, "
           f"byte-identical in <m> carrier block(s) (<root>).`: {full.stdout!r}")
    expect(wide.group(1) == wide.group(2) == str(len(registry)),
           f"the checked count must be printed once as that count: {full.stdout!r}")
    expect(int(wide.group(3)) >= len(registry),
           f"the carrier block count must be printed: {full.stdout!r}")
    expect(full.stdout.count("PASS - ") == 1,
           f"a full run prints exactly one PASS line: {full.stdout!r}")

    # 4. positive on a throwaway root proves --root resolves the rulebook and the carriers.
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp) / "repo"
        copies = make_tree(tree)
        clean = run("--root", str(tree), "--rule", RULE)
        expect(clean.returncode == 0, f"a clean tree must pass: {clean.stdout!r}")

        # 4a. one extra clause inside one carrier's block -> drift is reported.
        copies[1].write_text(
            copies[1].read_text(encoding="utf-8").replace(gate_block,
                                                          gate_block + " extra clause"),
            encoding="utf-8")
        drift = run("--root", str(tree), "--rule", RULE)
        expect(drift.returncode == 1, "a tampered carrier must exit 1")
        expect("differs" in drift.stdout, f"the drift must be reported: {drift.stdout!r}")

        # 4b. a carrier without the block -> missing.
        copies = make_tree(tree)
        without = copies[0]
        begin, end = markers(RULE)
        without.write_text(without.read_text(encoding="utf-8")
                           .replace(begin, "no block here").replace(end, "no block here"),
                           encoding="utf-8")
        missing = run("--root", str(tree), "--rule", RULE)
        expect(missing.returncode == 1, "a carrier without the block must exit 1")
        expect("missing" in missing.stdout, f"the missing block must be reported: {missing.stdout!r}")

        # 4c. a duplicated block is rejected, not silently accepted.
        copies = make_tree(tree)
        duplicated = copies[3]
        text = duplicated.read_text(encoding="utf-8")
        duplicated.write_text(f"{text}\n{begin}\n{gate_block}\n{end}\n", encoding="utf-8")
        twice = run("--root", str(tree), "--rule", RULE)
        expect(twice.returncode == 1, "a duplicated block must exit 1")
        expect("missing" in twice.stdout, f"the duplicated block must be reported: {twice.stdout!r}")

        # 4d. watering the gate down in ALL carriers at once is still caught (the rulebook wins).
        copies = make_tree(tree)
        for copy in copies:
            copy.write_text(copy.read_text(encoding="utf-8")
                            .replace(REQUIRED_MARKERS[0], "TODO"), encoding="utf-8")
        weakened = run("--root", str(tree), "--rule", RULE)
        expect(weakened.returncode == 1, "a gate weakened everywhere must still exit 1")
        expect("differs" in weakened.stdout,
               f"the weakened block must be reported: {weakened.stdout!r}")

        # 4e. an unknown rule id and a missing rulebook fail loudly, they never pass silently.
        unknown = run("--root", str(tree), "--rule", "no-such-rule")
        expect(unknown.returncode == 1, "an unknown rule id must exit 1")
        expect("unknown" in unknown.stdout, f"the unknown rule must be named: {unknown.stdout!r}")

        empty = pathlib.Path(tmp) / "empty"
        empty.mkdir()
        nowhere = run("--root", str(empty), "--rule", RULE)
        expect(nowhere.returncode == 1, "a missing rulebook must exit 1")
        expect("cannot read" in nowhere.stdout,
               f"the unreadable rulebook must be reported: {nowhere.stdout!r}")

    # 5. stdlib-only contract (no third-party imports).
    source = TOOL.read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", source, flags=re.M))
    allowed = {"__future__", "argparse", "dataclasses", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"check_factory_rules must be stdlib-only, imports={imported}")

    print(f"PASS - the rulebook declares {len(registry)} rules, every rule has resolvable carriers, "
          f"check_factory_rules.py keeps {RULE} byte-identical in {len(GATE_CARRIERS)} documents "
          "while catching drift, deletion, duplication and a gate watered down everywhere, and the "
          f"root {AGENTS} is a POINTER map: {len(AGENTS_POINTER_RULES)} rules referenced, no quote "
          "copied, under the 32 KB size gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

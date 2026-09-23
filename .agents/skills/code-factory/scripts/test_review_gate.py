#!/usr/bin/env python3
"""
Deterministic self-test for the canonical review-gate policy (zero LLM tokens).

The review gate is the rule `review-gate-policy` of the factory rulebook
(`references/factory-rules.md`), quoted VERBATIM into five documents: `references/code-review.md`,
`agents/code-factory.md`, `skills/code-factory/SKILL.md`, `AGENTS.md` and `.agents/README.md`.
Five prose copies drift, one machine-checked copy does not — the rulebook is the single home and
`check_factory_rules.py --rule review-gate-policy` is the checker, so this test is a THIN WRAPPER
around it (subprocess, assert exit 0) that keeps the historical name and the blast radius of the
gate. It adds the checks a pure pass/fail wrapper would lose:

  - the rulebook still states the policy's key markers (`unverified_review`, `conditional pass`,
    `hitl`, `auto`), so the gate cannot be watered down by rewriting rulebook and carriers at once;
  - the legacy `<!-- review-gate-policy: ... -->` marker is gone from all five carriers;
  - a negative self-check on throwaway copies in a temp directory (never the real documents)
    proves drift, a deleted block, a duplicated block and an everywhere-weakened gate ARE caught.

Usage:
  python3 test_review_gate.py

Exit code 0 = the canonical gate is intact and drift-detection works, 1 = a discrepancy.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
CHECKER = SCRIPTS / "check_factory_rules.py"

RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
RULE = "review-gate-policy"
DEFAULT_FILES = (
    "AGENTS.md",
    ".agents/README.md",
    ".agents/agents/code-factory.md",
    ".agents/skills/code-factory/SKILL.md",
    ".agents/skills/code-factory/references/code-review.md",
)
REQUIRED_MARKERS = ("unverified_review", "conditional pass", "hitl", "auto")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def check(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the rulebook checker; every path argument is relative to the repository root."""
    return subprocess.run([sys.executable, str(CHECKER), *args],
                          capture_output=True, text=True, errors="replace")


def make_tree(dst: pathlib.Path) -> list[pathlib.Path]:
    """A throwaway root with the rulebook plus byte-identical copies of the five documents."""
    if dst.exists():
        shutil.rmtree(dst)
    (dst / RULEBOOK).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / RULEBOOK, dst / RULEBOOK)
    copies = []
    for name in DEFAULT_FILES:
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        copies.append(target)
    return copies


def main() -> int:
    # 1. the rulebook still states the policy: one marked block carrying every key marker.
    begin, end = (f"<!-- factory-rule: {RULE} begin -->", f"<!-- factory-rule: {RULE} end -->")
    book = (ROOT / RULEBOOK).read_text(encoding="utf-8")
    expect(book.count(begin) == 1 and book.count(end) == 1,
           "the rulebook must carry exactly one marked review-gate block")
    canonical = book[book.index(begin) + len(begin):book.index(end)].strip()
    expect(canonical, "the canonical review-gate block must not be empty")
    for marker in REQUIRED_MARKERS:
        expect(marker in canonical, f"canonical review-gate block must mention {marker!r}")

    # 2. the checker passes on the real repository (positive) ...
    res = check("--rule", RULE)
    expect(res.returncode == 0,
           f"check_factory_rules.py --rule {RULE} must exit 0: {res.stdout!r} {res.stderr!r}")
    expect("PASS" in res.stdout, f"the checker must report PASS: {res.stdout!r}")

    # ... and the five documents no longer carry the legacy marker.
    for name in DEFAULT_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        expect("<!-- review-gate-policy:" not in text,
               f"{name}: the legacy review-gate marker must be migrated to factory-rule")

    # 3. negative self-check on throwaway copies: drift and deletion ARE detected.
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp) / "repo"
        copies = make_tree(tree)
        clean = check("--root", str(tree), "--rule", RULE)
        expect(clean.returncode == 0,
               f"identical fixture copies must pass: {clean.stdout!r} {clean.stderr!r}")

        copies[0].write_text(
            copies[0].read_text(encoding="utf-8").replace(canonical, canonical + " extra clause"),
            encoding="utf-8")
        drift = check("--root", str(tree), "--rule", RULE)
        expect(drift.returncode == 1, "a tampered copy must exit 1")
        expect("differs" in drift.stdout, f"a drifted copy must be reported: {drift.stdout!r}")

        copies = make_tree(tree)
        empty = copies[4]
        empty.write_text(empty.read_text(encoding="utf-8")
                         .replace(begin, "no block").replace(end, "no block"), encoding="utf-8")
        deleted = check("--root", str(tree), "--rule", RULE)
        expect(deleted.returncode == 1, "a copy without the block must exit 1")
        expect("missing" in deleted.stdout,
               f"a deleted block must be reported as missing: {deleted.stdout!r}")

        copies = make_tree(tree)
        twice = copies[2]
        twice.write_text(f"{twice.read_text(encoding='utf-8')}\n{begin}\n{canonical}\n{end}\n",
                        encoding="utf-8")
        duplicated = check("--root", str(tree), "--rule", RULE)
        expect(duplicated.returncode == 1, "a duplicated block must exit 1")

        copies = make_tree(tree)
        for copy in copies:
            copy.write_text(copy.read_text(encoding="utf-8")
                            .replace(REQUIRED_MARKERS[0], "TODO"), encoding="utf-8")
        weakened = check("--root", str(tree), "--rule", RULE)
        expect(weakened.returncode == 1,
               "a gate weakened in every document must still exit 1 (the rulebook wins)")

    print(f"PASS - the canonical review-gate block is intact in the rulebook and byte-identical in "
          f"{len(DEFAULT_FILES)} documents ({len(canonical)} chars); drift, deletion, duplication "
          "and a diluted gate are detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

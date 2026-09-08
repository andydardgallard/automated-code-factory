#!/usr/bin/env python3
"""
Deterministic self-test for the factory's model scripts (zero LLM tokens).

Builds a synthetic project, then verifies `check_factory_model.py`:
  - a correct 8-section AGENTS.md + fingerprint + memory passes (exit 0),
  - corrupting each invariant fails (exit 1),
  - the `unfinished` memory section is validated (no-debt, with-debt, incomplete -> fail,
    legacy -> warning), and `factory_version` is validated.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import check_factory_model
import project_fingerprint

SCRIPTS = pathlib.Path(__file__).resolve().parent
CHECKER = SCRIPTS / "check_factory_model.py"

SECTIONS = check_factory_model.CANONICAL_SECTIONS

VALID_ENTRY = """\
## 2026-09-01T00:00:00Z — First run
title: First run
timestamp: 2026-09-01T00:00:00Z
branch: main
commit: abc1234
task_type: implement
goal: Make the checker pass.
changed_files: src/main.py
created_files: memory/change-log.md
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: regenerate AGENTS.md
assumptions: (none)
models_used: analyzer=primary; coder=secondary
unfinished: нет незавершённых элементов
factory_version: 12.5.0
"""

# Same entry but WITHOUT the two newer keys -> a legacy entry that must pass with warnings.
LEGACY_ENTRY = VALID_ENTRY.replace("unfinished: нет незавершённых элементов\n", "").replace(
    "factory_version: 12.5.0\n", "")

ENTRY_WITH_DEBT = """\
## 2026-09-02T00:00:00Z — Debt run
title: Debt run
timestamp: 2026-09-02T00:00:00Z
branch: main
commit: deadbeef
task_type: implement
goal: Record debt.
changed_files: src/main.py
created_files: (none)
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: reviewer findings accepted as-is
assumptions: (none)
models_used: analyzer=primary
unfinished:
  - item: замечания ревьюера приняты как есть
    reason: бюджет ревьюера исчерпан
    severity: warning
    follow_up: false
factory_version: 12.5.0
"""

# An unfinished item with missing fields -> must FAIL.
ENTRY_INCOMPLETE = """\
## 2026-09-03T00:00:00Z — Incomplete debt
title: Incomplete debt
timestamp: 2026-09-03T00:00:00Z
branch: main
commit: badc0de
task_type: implement
goal: Incomplete debt.
changed_files: src/main.py
created_files: (none)
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: (none)
assumptions: (none)
models_used: analyzer=primary
unfinished:
  - item: замечание без причины
    follow_up: true
factory_version: 12.5.0
"""

CHANGE_LOG_HEADER = "# Change Log — Code Factory\n\n<!-- code-factory-memory: change-log -->\n\n"
SUMMARY = "# Project Summary — Code Factory\n\n<!-- code-factory-memory: summary -->\n\n"


def build(root: pathlib.Path, entry: str = VALID_ENTRY) -> None:
    """Write a synthetic but valid project model into `root`."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "memory" / "change-log.md").write_text(CHANGE_LOG_HEADER + entry, encoding="utf-8")
    (root / "memory" / "summary.md").write_text(SUMMARY, encoding="utf-8")

    fp = project_fingerprint.compute_fingerprint(root)
    lines = ["<!-- code-factory-fingerprint: %s -->" % fp, "# Demo — Project Model", ""]
    for s in SECTIONS:
        lines += [f"## {s}", "", f"Content of {s}.", ""]
    (root / "AGENTS.md").write_text("\n".join(lines), encoding="utf-8")


def run_cli(*args: str) -> int:
    return subprocess.run([sys.executable, str(CHECKER), *args],
                          capture_output=True, text=True).returncode


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def mem_errors(root: pathlib.Path) -> list[str]:
    return check_factory_model.validate_memory(root)[0]


def mem_warnings(root: pathlib.Path) -> list[str]:
    return check_factory_model.validate_memory(root)[1]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)

        # 1. Valid model -> PASS (functions + CLI).
        build(root)
        expect(check_factory_model.check_agents(root) == [], "valid AGENTS.md should pass check_agents")
        expect(mem_errors(root) == [], "valid memory should pass validate_memory")
        expect(run_cli("--repo", td) == 0, "valid model should exit 0")

        # 2. Missing section -> FAIL.
        build(root)
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        (root / "AGENTS.md").write_text(text.replace("## Technology Stack\n", "", 1), encoding="utf-8")
        expect(check_factory_model.check_agents(root) != [], "missing section must fail")
        expect(run_cli("--repo", td) != 0, "missing section must exit != 0")

        # 3. Wrong fingerprint -> FAIL.
        build(root)
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        bad = "<!-- code-factory-fingerprint: " + "0" * 64 + " -->" + "\n" + "\n".join(text.splitlines()[1:])
        (root / "AGENTS.md").write_text(bad, encoding="utf-8")
        expect(check_factory_model.check_agents(root) != [], "wrong fingerprint must fail")

        # 4. Corrupt memory entry (remove a required key) -> FAIL.
        build(root)
        (root / "memory" / "change-log.md").write_text(
            CHANGE_LOG_HEADER + VALID_ENTRY.replace("commit: abc1234\n", ""), encoding="utf-8")
        expect(mem_errors(root) != [], "missing entry key must fail")

        # 5. Missing summary.md -> FAIL.
        build(root)
        (root / "memory" / "summary.md").unlink()
        expect(mem_errors(root) != [], "missing summary must fail")

        # 6. Empty (header-only) change-log is valid.
        build(root)
        (root / "memory" / "change-log.md").write_text(CHANGE_LOG_HEADER, encoding="utf-8")
        expect(mem_errors(root) == [], "header-only journal should be valid")

        # 7. Entry with NO debt (explicit marker) -> PASS, no warning about unfinished.
        build(root)
        expect(mem_errors(root) == [], "no-debt entry must pass")
        expect(not any("unfinished" in w for w in mem_warnings(root)),
               "no-debt entry must not warn about unfinished")

        # 8. Entry WITH debt (valid items) -> PASS.
        build(root, ENTRY_WITH_DEBT)
        expect(mem_errors(root) == [], "with-debt entry must pass")

        # 9. Entry with incomplete unfinished item -> FAIL.
        build(root, ENTRY_INCOMPLETE)
        expect(mem_errors(root) != [], "incomplete unfinished item must fail")

        # 10. Legacy entry (no unfinished/factory_version) -> PASS with warnings.
        build(root, LEGACY_ENTRY)
        expect(mem_errors(root) == [], "legacy entry must pass (no error)")
        expect(any("unfinished" in w for w in mem_warnings(root)),
               "legacy entry must warn about missing 'unfinished'")
        expect(any("factory_version" in w for w in mem_warnings(root)),
               "legacy entry must warn about missing 'factory_version'")

        # 11. Invalid factory_version -> FAIL.
        build(root, VALID_ENTRY.replace("factory_version: 12.5.0", "factory_version: twelve"))
        expect(mem_errors(root) != [], "invalid factory_version must fail")

        # 12. Invalid unfinished severity -> FAIL.
        build(root, ENTRY_WITH_DEBT.replace("severity: warning", "severity: fatal"))
        expect(mem_errors(root) != [], "invalid unfinished severity must fail")

    # 13. Fingerprint must be stable across committing AGENTS.md (regression: it must NOT
    #     include the git tree SHA, or the embedded fingerprint goes stale after the very
    #     commit that carries it).
    with tempfile.TemporaryDirectory() as gtd:
        groot = pathlib.Path(gtd)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=groot, check=True)
        build(groot)
        expect(check_factory_model.check_agents(groot) == [], "fixture should pass before commit")
        before = project_fingerprint.compute_fingerprint(groot)
        subprocess.run(["git", "-C", gtd, "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", gtd, "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-q", "-m", "commit AGENTS.md + memory"], check=True)
        after = project_fingerprint.compute_fingerprint(groot)
        expect(before == after, "fingerprint changed after committing AGENTS.md/memory (git tree SHA leak)")
        expect(check_factory_model.check_agents(groot) == [], "model should still pass after commit")

    print("PASS - factory model scripts behave as expected (valid passes, corruptions fail, "
          "unfinished/factory_version validated).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

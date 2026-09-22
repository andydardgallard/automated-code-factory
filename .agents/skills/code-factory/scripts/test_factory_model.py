#!/usr/bin/env python3
"""
Deterministic self-test for the factory's model scripts (zero LLM tokens).

Builds a synthetic project, then verifies `check_factory_model.py`:
  - a correct 8-section AGENTS.md + fingerprint + memory passes (exit 0),
  - corrupting each invariant fails (exit 1),
  - the `unfinished` memory section is validated (no-debt, with-debt, incomplete -> fail,
    legacy -> warning), and `factory_version` is validated,
  - project ownership is validated (entry + summary declaring one project -> pass, a missing
    `project` -> warning only, different `project` values in one journal -> fail, an empty
    `project` value -> fail, and a `project:` example inside a code block is not a declaration),
  - the memory format v2 (run_id + provenance marks) is enforced on the records of a
    current-generation factory: a missing or malformed `run_id`, or a missing provenance mark in
    `decisions`/`results`, fails, while records written before the format and legacy records
    without `project` only warn,
  - the WIP checkpoint `.code-factory/state/pipeline.yaml` is validated when it exists (required
    keys, `status` enum, `run_id` format, list/mapping types of the optional keys) and a missing
    one is a SKIP, never a failure,
  - the two-level fingerprint line is validated: the `... content: <hash>` format passes, a
    forged or stale CONTENT hash fails, and a legacy single-hash line only warns.

`project_fingerprint.py` is covered as well:
  - the content fingerprint catches a change to an EXISTING file at depth >= 2 that the
    structural fingerprint cannot see (git index and git-less fallback), which is the confirmed
    defect reported by the code reviewer on 2026-09-23,
  - both fingerprints stay stable across a commit of the factory's own artifacts,
  - the CLI modes (default = structural only, `--content`, `--all`) behave as documented.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import check_factory_model
import project_fingerprint

SCRIPTS = pathlib.Path(__file__).resolve().parent
CHECKER = SCRIPTS / "check_factory_model.py"
FP = SCRIPTS / "project_fingerprint.py"

SECTIONS = check_factory_model.CANONICAL_SECTIONS

VALID_ENTRY = """\
## 2026-09-01T00:00:00Z — First run
title: First run
project: demo
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

# Same entry but WITHOUT the newer keys -> a legacy entry that must pass with warnings.
LEGACY_ENTRY = VALID_ENTRY.replace("unfinished: нет незавершённых элементов\n", "").replace(
    "factory_version: 12.5.0\n", "")

# Legacy entry without the project ownership marker either -> warning about 'project'.
LEGACY_ENTRY_NO_PROJECT = LEGACY_ENTRY.replace("project: demo\n", "")

# The same journal but owned by a DIFFERENT project -> the memory mixes projects (error).
FOREIGN_ENTRY = VALID_ENTRY.replace("# First run", "# Second run").replace(
    "project: demo", "project: other_project")

ENTRY_WITH_DEBT = """\
## 2026-09-02T00:00:00Z — Debt run
title: Debt run
project: demo
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
project: demo
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

# A record written in the memory format v2 (factory newer than the one that introduced it):
# `run_id` + a provenance mark in BOTH `decisions` and `results` -> must PASS.
V2_ENTRY = """\
## 2026-09-25T00:00:00Z — Verified run
title: Verified run
project: demo
timestamp: 2026-09-25T00:00:00Z
run_id: 20260922-442cd2f8
branch: main
commit: abc1234
task_type: implement
goal: Record a run in the memory format v2.
changed_files: src/main.py
created_files: (none)
results: integration=PASS [verified: .code-factory/logs/code-results.md]; regression=PASS; business=PASS; review=approve
decisions: keep the two-level fingerprint [verified: scripts/test_factory_model.py]; P2 postponed [inferred]
assumptions: (none)
models_used: analyzer=primary
unfinished: нет незавершённых элементов
factory_version: 12.9.0
"""

# The same v2 record with one v2 element missing / malformed -> the format is violated.
V2_NO_RUN_ID = V2_ENTRY.replace("run_id: 20260922-442cd2f8\n", "")
V2_BAD_RUN_ID = V2_ENTRY.replace("20260922-442cd2f8", "2026-09-22")
V2_NO_MARKS = (V2_ENTRY.replace("integration=PASS [verified: .code-factory/logs/code-results.md]",
                                "integration=PASS")
               .replace(
    "decisions: keep the two-level fingerprint [verified: scripts/test_factory_model.py]; "
    "P2 postponed [inferred]", "decisions: keep the two-level fingerprint"))
# A record that already carries a v2 field must satisfy the REST of the format, even when its
# factory_version still predates it (half-migrated record).
V2_HALF = V2_NO_RUN_ID.replace("factory_version: 12.9.0", "factory_version: 12.8.0")

# A record whose `factory_version` ALONE puts it in the format v2: no `run_id`, no provenance marks
# — only the captured version tuple can catch it (a non-capturing VERSION_RE would let it pass).
V2_BY_VERSION_ENTRY = VALID_ENTRY.replace("factory_version: 12.5.0", "factory_version: 12.9.0")

# A record of a pre-v2 factory: no run_id, no marks -> must PASS and stay silent, so memories
# written before the format are never broken.
PRE_V2_ENTRY = VALID_ENTRY.replace("factory_version: 12.5.0", "factory_version: 12.8.0")

VALID_PIPELINE = """\
run_id: 20260922-442cd2f8
task: .code-factory/state/task.yaml
phase: implement-wave-2
status: in_progress
branch: feature/example
files_touched:
  - src/main.py
  - memory/change-log.md
pending_decision: нет
resume_hint: continue with wave 2
updated_at: 2026-09-22T23:05:00+03:00
retry_counters:
  coder: 0
  reviewer: 0
models_used:
  analyzer: primary
"""

CHANGE_LOG_HEADER = "# Change Log — Code Factory\n\n<!-- code-factory-memory: change-log -->\n\n"
SUMMARY = ("# Project Summary — Code Factory\n\n<!-- code-factory-memory: summary -->\n"
           "project: demo\nrepo_path: .\n\n")
# Legacy summary without the `project:` declaration -> warning, but never an error.
SUMMARY_NO_PROJECT = SUMMARY.replace("project: demo\nrepo_path: .\n", "")


def build(root: pathlib.Path, entry: str = VALID_ENTRY) -> None:
    """Write a synthetic but valid project model into `root` (fingerprints stamped on top)."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "memory" / "change-log.md").write_text(CHANGE_LOG_HEADER + entry, encoding="utf-8")
    (root / "memory" / "summary.md").write_text(SUMMARY, encoding="utf-8")

    lines = ["<!-- code-factory-fingerprint: (unstamped) -->", "# Demo — Project Model", ""]
    for s in SECTIONS:
        lines += [f"## {s}", "", f"Content of {s}.", ""]
    (root / "AGENTS.md").write_text("\n".join(lines), encoding="utf-8")
    stamp(root)


def stamp(root: pathlib.Path) -> None:
    """Rewrite AGENTS.md line 1 with the CURRENT structural + content fingerprints.

    Called after every project change that the check itself cannot anticipate (e.g. `git add`,
    which is what the content level reads), so a stale model is never mistaken for a broken one.
    """
    agents = root / "AGENTS.md"
    body = agents.read_text(encoding="utf-8").splitlines()[1:]  # drop the old fingerprint line
    line = "<!-- code-factory-fingerprint: %s content: %s -->" % (
        project_fingerprint.compute_fingerprint(root),
        project_fingerprint.compute_content_fingerprint(root))
    agents.write_text("\n".join([line, *body]), encoding="utf-8")


def fingerprint_line(root: pathlib.Path) -> str:
    """Return the raw first (fingerprint) line of AGENTS.md."""
    return (root / "AGENTS.md").read_text(encoding="utf-8").splitlines()[0]


def replace_line1(root: pathlib.Path, line: str) -> None:
    """Replace AGENTS.md line 1 (the fingerprint line) with `line`."""
    lines = (root / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    (root / "AGENTS.md").write_text("\n".join([line, *lines[1:]]), encoding="utf-8")


def parsed_fingerprint(root: pathlib.Path) -> re.Match:
    """Match AGENTS.md line 1 against the checker's regex (structural [+ content] hashes)."""
    m = check_factory_model.FINGERPRINT_RE.match(fingerprint_line(root).strip())
    expect(m is not None, f"line 1 must carry a fingerprint: {fingerprint_line(root)!r}")
    return m


def run_cli(*args: str) -> int:
    return subprocess.run([sys.executable, str(CHECKER), *args],
                          capture_output=True, text=True).returncode


def run_cli_out(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the checker as a CLI and keep stdout/stderr (for the SKIP / ok lines)."""
    return subprocess.run([sys.executable, str(CHECKER), *args], capture_output=True, text=True)


def pipeline_errors(root: pathlib.Path, text: str) -> list[str]:
    """Write `text` as the WIP checkpoint of `root` and return the errors the checker reports."""
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "pipeline.yaml").write_text(text, encoding="utf-8")
    return check_factory_model.check_pipeline_checkpoints(root)[0]


def run_fp(*args: str) -> subprocess.CompletedProcess:
    """Run project_fingerprint.py as a CLI (default / --content / --all) and capture stdout."""
    return subprocess.run([sys.executable, str(FP), *args], capture_output=True, text=True)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def agents_warnings(root: pathlib.Path) -> list[str]:
    return check_factory_model.check_agents_model(root)[1]


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

        # 3. Wrong (structural AND content) fingerprint -> FAIL.
        build(root)
        replace_line1(root, "<!-- code-factory-fingerprint: " + "0" * 64
                            + " content: " + "0" * 64 + " -->")
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

        # 13. Canonical single-project memory (entry + summary both declare `project`) -> PASS
        #     with no warnings at all.
        build(root)
        expect(mem_errors(root) == [], "single-project memory must pass")
        expect(mem_warnings(root) == [], f"canonical memory must not warn: {mem_warnings(root)}")
        expect(run_cli("--repo", td, "--memory-only") == 0, "canonical memory must exit 0")

        # 14. Legacy entry WITHOUT `project` -> PASS (warning only): old journals keep working.
        build(root, LEGACY_ENTRY_NO_PROJECT)
        expect(mem_errors(root) == [], "entry without 'project' must pass (no error)")
        expect(any("missing key 'project'" in w for w in mem_warnings(root)),
               "entry without 'project' must warn about the missing 'project' key")
        expect(run_cli("--repo", td, "--memory-only") == 0, "legacy entry must exit 0")

        # 15. Two entries with DIFFERENT `project:` -> FAIL: one memory belongs to one project.
        build(root, VALID_ENTRY + FOREIGN_ENTRY)
        expect(any("mixes projects" in e and "other_project" in e for e in mem_errors(root)),
               "two different 'project' values must fail with 'mixes projects'")
        expect(run_cli("--repo", td, "--memory-only") != 0, "mixed memory must exit != 0")

        # 16. summary.md without a `project:` declaration -> warning, NOT an error.
        build(root)
        (root / "memory" / "summary.md").write_text(SUMMARY_NO_PROJECT, encoding="utf-8")
        expect(mem_errors(root) == [], "summary without 'project' must not be an error")
        expect(any("does not declare" in w and "project" in w for w in mem_warnings(root)),
               "summary without 'project' must warn about the missing declaration")
        expect(run_cli("--repo", td, "--memory-only") == 0,
               "summary without 'project' must still exit 0")

        # 17. summary.md declaring a foreign project while the journal belongs to `demo` -> FAIL.
        build(root)
        (root / "memory" / "summary.md").write_text(
            SUMMARY.replace("project: demo", "project: other_project"), encoding="utf-8")
        expect(any("other_project" in e and "demo" in e for e in mem_errors(root)),
               "summary declaring another project than the journal must fail")

        # 18. An entry carrying the `project` key with an EMPTY value -> FAIL (never silent legacy).
        build(root, VALID_ENTRY.replace("project: demo\n", "project:\n"))
        expect(any("empty 'project' value" in e for e in mem_errors(root)),
               "an empty 'project' value must fail")
        expect(run_cli("--repo", td, "--memory-only") != 0,
               "an empty 'project' value must exit != 0")

        # 19. A `project:` example inside a fenced code block below a `## ` section is NOT the
        #     declaration: only the area between the canonical marker and the first `## ` section
        #     declares the owner, so the example never causes a project mismatch.
        example = "## Format examples\n\n```\nproject: {0}\nrepo_path: /some/path\n```\n"
        for name in ("demo", "other_project"):
            build(root)
            (root / "memory" / "summary.md").write_text(SUMMARY + example.format(name),
                                                        encoding="utf-8")
            expect(mem_errors(root) == [],
                   f"a 'project: {name}' example in a code block must not fail")
            expect(run_cli("--repo", td, "--memory-only") == 0,
                   f"a 'project: {name}' example in a code block must still exit 0")
        #     Same but WITHOUT any real declaration: the block example must not be read as one
        #     (only the legacy warning, never a mismatch with the journal).
        build(root)
        (root / "memory" / "summary.md").write_text(
            SUMMARY_NO_PROJECT + example.format("other_project"), encoding="utf-8")
        expect(mem_errors(root) == [],
               "a 'project:' example in a code block must not be read as a declaration")
        expect(any("does not declare" in w for w in mem_warnings(root)),
               "a summary without a real declaration must still warn")
        expect(run_cli("--repo", td, "--memory-only") == 0,
               "a 'project:' example in a code block must still exit 0")

        # 23. Two-hash format (structural + content): accepted without warnings, and a FORGED
        #     content hash fails — a content-only drift is an error, not a warning.
        build(root)
        expect(check_factory_model.check_agents(root) == [], "two-hash model must pass")
        expect(agents_warnings(root) == [], f"two-hash model must not warn: {agents_warnings(root)}")
        replace_line1(root, "<!-- code-factory-fingerprint: %s content: %s -->"
                            % (parsed_fingerprint(root).group(1), "0" * 64))
        expect(any("content fingerprint mismatch" in e for e in check_factory_model.check_agents(root)),
               "a forged content hash must fail with a content mismatch")
        expect(run_cli("--repo", td) != 0, "a forged content hash must exit != 0")

        # 23b. A REAL content-only change (structural signals untouched, hash left stale) must fail
        #      the model check as well — this is what makes "skip regeneration" safe.
        build(root)
        struct = project_fingerprint.compute_fingerprint(root)
        (root / "src" / "main.py").write_text("print('changed')\n", encoding="utf-8")
        expect(project_fingerprint.compute_fingerprint(root) == struct,
               "editing src/main.py must not move the structural hash")
        expect(any("content fingerprint mismatch" in e for e in check_factory_model.check_agents(root)),
               "a stale content hash must fail the model check")

        # 24. Legacy single-hash fingerprint line: accepted with a WARNING, never an error, so
        #     models generated before the two-level fingerprint keep working.
        build(root)
        legacy = "<!-- code-factory-fingerprint: %s -->" % parsed_fingerprint(root).group(1)
        replace_line1(root, legacy)
        expect(check_factory_model.check_agents(root) == [], "legacy line must not be an error")
        expect(any("legacy" in w and "content" in w for w in agents_warnings(root)),
               "legacy line must warn about the missing content hash")
        expect(run_cli("--repo", td) == 0, "legacy line must still exit 0 (warning only)")

        # 25. project_fingerprint.py CLI contract: no flag -> structural only (backwards
        #     compatible), --content -> content only, --all -> both labelled lines.
        build(root)
        struct = project_fingerprint.compute_fingerprint(root)
        content = project_fingerprint.compute_content_fingerprint(root)
        default_out = run_fp("--repo", td).stdout.split()
        expect(default_out == [struct],
               f"default CLI output must be the structural hash only: {default_out}")
        expect(run_fp("--repo", td, "--content").stdout.split() == [content],
               "--content must print the content hash only")
        all_out = run_fp("--repo", td, "--all").stdout.splitlines()
        expect(all_out == [f"structural: {struct}", f"content: {content}"],
               f"--all must print both labelled hashes: {all_out}")

        # 26. Memory format v2 (run_id + provenance marks). A record of a current-generation
        #     factory must carry them: a missing or malformed `run_id`, or a missing mark in
        #     `decisions`/`results`, is an error that also fails the CLI. A record written before
        #     the format stays valid AND silent, and a legacy record (no `project`) only warns.
        build(root, V2_ENTRY)
        expect(mem_errors(root) == [], f"a v2 record must pass: {mem_errors(root)}")
        expect(run_cli("--repo", td, "--memory-only") == 0, "a v2 record must exit 0")

        build(root, V2_NO_RUN_ID)
        expect(any("run_id" in e for e in mem_errors(root)), "a v2 record without run_id must fail")
        expect(run_cli("--repo", td, "--memory-only") != 0,
               "a v2 record without run_id must exit != 0")

        build(root, V2_BAD_RUN_ID)
        expect(any("invalid run_id" in e for e in mem_errors(root)),
               "a malformed run_id must fail")
        expect(run_cli("--repo", td, "--memory-only") != 0, "a malformed run_id must exit != 0")

        build(root, V2_NO_MARKS)
        expect(any("provenance mark" in e for e in mem_errors(root)),
               "a v2 record without provenance marks must fail")
        expect(run_cli("--repo", td, "--memory-only") != 0,
               "a v2 record without provenance marks must exit != 0")

        #     A record that already carries one v2 field is held to the whole format, even when its
        #     factory_version still predates it (half-migrated record).
        build(root, V2_HALF)
        expect(any("run_id" in e for e in mem_errors(root)),
               "a half-migrated v2 record must fail on the missing field")

        #     The factory_version TRIGGER alone must select the format v2: a record of a factory
        #     newer than 12.8.0 without run_id and without marks carries no v2 field at all, so only
        #     the captured version tuple can catch it (a non-capturing VERSION_RE silently accepts
        #     it). Both the predicate and the end-to-end memory verdict are asserted.
        expect(check_factory_model._v2_record({"project": "demo", "factory_version": "12.9.0"}),
               "factory_version 12.9.0 must select the memory format v2")
        expect(check_factory_model._v2_record({"project": "demo", "factory_version": "13.0.0"}),
               "a major bump must stay a v2 record")
        expect(not check_factory_model._v2_record({"project": "demo", "factory_version": "12.8.0"}),
               "12.8.0 is the version the format is introduced AFTER, not a v2 record")
        build(root, V2_BY_VERSION_ENTRY)
        version_issues = mem_errors(root)
        expect(any("run_id" in e for e in version_issues)
               and any("provenance mark" in e for e in version_issues),
               f"a 12.9.0 record without run_id/marks must fail the format: {version_issues}")
        expect(run_cli("--repo", td, "--memory-only") != 0,
               "a 12.9.0 record without run_id/marks must exit != 0")
        #     Positive control: the same factory_version WITH run_id and marks passes.
        build(root, V2_BY_VERSION_ENTRY.replace(
            "decisions: regenerate AGENTS.md",
            "run_id: 20260922-442cd2f8\ndecisions: regenerate AGENTS.md [verified: "
            "scripts/test_factory_model.py]").replace(
            "results: integration=PASS; regression=PASS; business=PASS; review=approve",
            "results: integration=PASS [verified: .code-factory/logs/code-results.md]; "
            "regression=PASS; business=PASS; review=approve"))
        expect(mem_errors(root) == [], f"12.9.0 with run_id and marks must pass: {mem_errors(root)}")
        expect(run_cli("--repo", td, "--memory-only") == 0,
               "12.9.0 with run_id and marks must exit 0")

        #     Pre-v2 record: no error and no warning, so memories written before the format keep
        #     passing untouched (the format is never retroactive).
        build(root, PRE_V2_ENTRY)
        expect(mem_errors(root) == [], f"a pre-v2 record must pass: {mem_errors(root)}")
        expect(mem_warnings(root) == [], f"a pre-v2 record must not warn: {mem_warnings(root)}")
        expect(run_cli("--repo", td, "--memory-only") == 0, "a pre-v2 record must exit 0")

        #     Legacy record without `project`: -> warnings only, never an error.
        build(root, LEGACY_ENTRY_NO_PROJECT)
        expect(mem_errors(root) == [], "a legacy record must not fail")
        expect(any("run_id" in w for w in mem_warnings(root)),
               "a legacy record must warn about the missing run_id")
        expect(any("provenance mark" in w for w in mem_warnings(root)),
               "a legacy record must warn about the missing provenance marks")
        expect(run_cli("--repo", td, "--memory-only") == 0,
               "a legacy record must still exit 0 (warnings only)")

    # 20. Both fingerprints must be stable across committing the factory's own artifacts. The
    #     structural level excludes AGENTS.md/memory/ and never included the git tree SHA (or the
    #     embedded hash would go stale after the very commit that carries it); the content level
    #     reads the git INDEX via `git ls-files -s`, which a commit does not modify. So the two
    #     hashes embedded in AGENTS.md survive the commit — the "skip regeneration" branch stays
    #     reachable (regression guard).
    with tempfile.TemporaryDirectory() as gtd:
        groot = pathlib.Path(gtd)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=groot, check=True)
        build(groot)
        subprocess.run(["git", "-C", gtd, "add", "-A"], check=True)
        stamp(groot)  # the index just appeared -> the content hash changed, restamp the model
        expect(check_factory_model.check_agents(groot) == [], "fixture should pass before commit")
        before = project_fingerprint.compute_fingerprint(groot)
        before_content = project_fingerprint.compute_content_fingerprint(groot)
        subprocess.run(
            ["git", "-C", gtd, "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-q", "-m", "commit AGENTS.md + memory"], check=True)
        after = project_fingerprint.compute_fingerprint(groot)
        after_content = project_fingerprint.compute_content_fingerprint(groot)
        expect(before == after, "fingerprint changed after committing AGENTS.md/memory (git tree SHA leak)")
        expect(before_content == after_content,
               "content fingerprint changed after committing AGENTS.md/memory (index must be commit-stable)")
        expect(check_factory_model.check_agents(groot) == [], "model should still pass after commit")

    # 21. Confirmed defect (code review 2026-09-23): a change to an EXISTING file at depth >= 2 is
    #     invisible to the structural fingerprint. The content fingerprint MUST catch it. Tmp repo
    #     with `git init` + `git add` only — `git ls-files -s` reads the index, no commit needed.
    with tempfile.TemporaryDirectory() as gtd:
        groot = pathlib.Path(gtd)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=groot, check=True)
        (groot / "src" / "a" / "b").mkdir(parents=True)
        (groot / "pyproject.toml").write_text("[project]\nname = \"deep\"\n", encoding="utf-8")
        (groot / "README.md").write_text("# Deep\n", encoding="utf-8")
        nested = groot / "src" / "a" / "b" / "c.py"
        nested.write_text("print('one')\n", encoding="utf-8")
        subprocess.run(["git", "-C", gtd, "add", "-A"], check=True)
        struct_before = project_fingerprint.compute_fingerprint(groot)
        content_before = project_fingerprint.compute_content_fingerprint(groot)
        nested.write_text("print('two')\n", encoding="utf-8")
        subprocess.run(["git", "-C", gtd, "add", "-A"], check=True)
        expect(project_fingerprint.compute_fingerprint(groot) == struct_before,
               "structural hash must NOT react to a depth-3 change of an existing file (blind spot)")
        expect(project_fingerprint.compute_content_fingerprint(groot) != content_before,
               "content hash MUST react to a depth-3 change of an existing file (git index)")

    # 22. Git-less fallback of the content level: with no repository it hashes the working-tree
    #     files (same exclusions), catches the same depth-3 change, and stays blind to the factory
    #     artifacts (AGENTS.md/memory) — which is what lets AGENTS.md embed its own hash pair.
    with tempfile.TemporaryDirectory() as ftd:
        froot = pathlib.Path(ftd)
        expect(project_fingerprint._git_index_records(froot) is None,
               "the fallback fixture must not be inside a git repository")
        (froot / "src" / "a" / "b").mkdir(parents=True)
        (froot / "pyproject.toml").write_text("[project]\nname = \"deep\"\n", encoding="utf-8")
        (froot / "README.md").write_text("# Deep\n", encoding="utf-8")
        nested = froot / "src" / "a" / "b" / "c.py"
        nested.write_text("print('one')\n", encoding="utf-8")
        struct_before = project_fingerprint.compute_fingerprint(froot)
        content_before = project_fingerprint.compute_content_fingerprint(froot)
        nested.write_text("print('two')\n", encoding="utf-8")
        expect(project_fingerprint.compute_fingerprint(froot) == struct_before,
               "structural hash must not react to a depth-3 change either")
        content_after = project_fingerprint.compute_content_fingerprint(froot)
        expect(content_after != content_before,
               "the git-less fallback MUST catch a depth-3 content change")
        (froot / "AGENTS.md").write_text("# model\n", encoding="utf-8")
        (froot / "memory").mkdir()
        (froot / "memory" / "summary.md").write_text("x\n", encoding="utf-8")
        expect(project_fingerprint.compute_content_fingerprint(froot) == content_after,
               "factory artifacts (AGENTS.md/memory) must be excluded from the content hash")
        expect(run_fp("--repo", ftd, "--content").stdout.split() == [content_after],
               "the fallback must be what --content prints without a repository")

    # 27. WIP checkpoints: `.code-factory/state/pipeline.yaml` is validated when it exists — the
    #     required keys, the `status` enum, the `run_id` format and the shape of the optional
    #     keys — and its absence is a SKIP, never a failure (a project without a run in flight
    #     has no checkpoint). The fixture carries a valid memory and AGENTS.md, so only the
    #     checkpoint decides the exit code of the CLI.
    with tempfile.TemporaryDirectory() as ptd:
        proot = pathlib.Path(ptd)
        build(proot, V2_ENTRY)

        p_errors, p_skip = check_factory_model.check_pipeline_checkpoints(proot)
        expect(p_errors == [] and p_skip, "a missing checkpoint must be a SKIP, not an error")
        res = run_cli_out("--repo", ptd, "--memory-only")
        expect(res.returncode == 0, f"a missing checkpoint must exit 0: {res.stderr!r}")
        expect("SKIP" in res.stderr, f"the check must report the skip: {res.stderr!r}")
        expect("no WIP checkpoint" in res.stdout,
               f"the PASS line must say there is no checkpoint: {res.stdout!r}")

        expect(pipeline_errors(proot, VALID_PIPELINE) == [], "a valid checkpoint must pass")
        p_errors, p_skip = check_factory_model.check_pipeline_checkpoints(proot)
        expect(p_errors == [] and not p_skip, f"a valid checkpoint must pass: {p_errors}")
        res = run_cli_out("--repo", ptd, "--memory-only")
        expect(res.returncode == 0, f"a valid checkpoint must exit 0: {res.stderr!r}")
        expect("WIP checkpoint" in res.stdout and "is valid" in res.stdout,
               f"the valid checkpoint must be reported: {res.stdout!r}")

        #     A missing required key, an unknown status and a malformed run_id are errors.
        missing_key = VALID_PIPELINE.replace("phase: implement-wave-2\n", "")
        expect(any("'phase'" in e for e in pipeline_errors(proot, missing_key)),
               "a missing required key must fail")
        expect(run_cli("--repo", ptd, "--memory-only") != 0,
               "a missing required key must exit != 0")
        unknown_status = VALID_PIPELINE.replace("status: in_progress", "status: finished")
        expect(any("invalid status" in e for e in pipeline_errors(proot, unknown_status)),
               "an unknown status must fail")
        expect(run_cli("--repo", ptd, "--memory-only") != 0, "an unknown status must exit != 0")
        bad_run_id = VALID_PIPELINE.replace("run_id: 20260922-442cd2f8", "run_id: 2026-09-22")
        expect(any("invalid run_id" in e for e in pipeline_errors(proot, bad_run_id)),
               "a malformed run_id must fail")
        #     `files_touched` is a list by contract; a scalar there is a format error.
        scalar_touched = VALID_PIPELINE.replace(
            "files_touched:\n  - src/main.py\n  - memory/change-log.md\n",
            "files_touched: src/main.py\n")
        expect(any("files_touched" in e for e in pipeline_errors(proot, scalar_touched)),
               "a scalar files_touched must fail")
        #     Every required status of the schema is accepted.
        for status in ("ok", "failed", "in_progress"):
            expect(pipeline_errors(proot, VALID_PIPELINE.replace("status: in_progress",
                                                                 f"status: {status}")) == [],
                   f"the status '{status}' must be accepted")
        expect(run_cli("--repo", ptd, "--memory-only") == 0,
               "the last valid checkpoint must exit 0")

    print("PASS - factory model scripts behave as expected (valid passes, corruptions fail, "
          "unfinished/factory_version/project validated, memory format v2 (run_id + provenance "
          "marks) enforced on current-generation records, WIP checkpoints validated, "
          "structural+content fingerprints distinguish depth>=2 content changes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

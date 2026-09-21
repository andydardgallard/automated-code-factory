#!/usr/bin/env python3
"""
Deterministic self-test for `memory_project.py` (zero LLM tokens).

`memory/` is the long-term memory of ONE target project, so this verifies that the helper:
  - `name` prints the project name (basename of the resolved path),
  - `init` creates both memory files once and never rewrites them (idempotent),
  - the templates carry the canonical markers and declare the owning project,
  - `check` passes for empty/single-project memory and takes the owner from summary.md while
    the journal has no records yet, fails on a mixed journal, on a summary/journal mismatch
    and on a project mismatch (`--expect`), tolerates a missing journal (fresh project), and
    reports a record-free-of-`project` journal as legacy (never as a mismatch).

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "memory_project.py"

CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def journal_entry(timestamp: str, project: str = "") -> str:
    """A minimal but format-valid journal record belonging to `project`.

    `project=""` builds a legacy record without the `project:` field.
    """
    name = project or "legacy"
    project_line = f"project: {project}\n" if project else ""
    return f"""\
## {timestamp} — Run on {name}
title: Run on {name}
{project_line}timestamp: {timestamp}
branch: main
commit: abc1234
task_type: implement
goal: Demo record.
changed_files: (none)
created_files: (none)
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: (none)
assumptions: (none)
models_used: analyzer=primary
"""


def write_journal(root: pathlib.Path, *entries: str) -> None:
    """Reset the journal to its header (up to the canonical marker) plus the given records."""
    path = root / "memory" / "change-log.md"
    header = path.read_text(encoding="utf-8").split(CHANGE_LOG_MARKER, 1)[0]
    path.write_text(header + CHANGE_LOG_MARKER + "\n\n" + "".join(entries), encoding="utf-8")


def declares_project(text: str, project: str) -> bool:
    return any(line.strip() == f"project: {project}" for line in text.splitlines())


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        # A fixed directory name so the default project name (basename) is predictable.
        root = tmp / "demo_proj"
        root.mkdir()
        change_log = root / "memory" / "change-log.md"
        summary = root / "memory" / "summary.md"

        # 1. `name` prints the basename of the resolved path.
        res = run("name", "--repo", str(root))
        expect(res.returncode == 0, "name must exit 0")
        expect(res.stdout.strip() == "demo_proj", f"name must print the basename, got {res.stdout!r}")

        # 2. `init` creates both files, both carry the canonical markers, and `summary.md`
        #    declares `project:` with the correct (default) name.
        res = run("init", "--repo", str(root))
        expect(res.returncode == 0, "init must exit 0")
        expect(res.stdout.count("created:") == 2, f"init must report 2 creations: {res.stdout!r}")
        expect(change_log.is_file() and summary.is_file(), "init must create both memory files")
        clog_text = change_log.read_text(encoding="utf-8")
        sum_text = summary.read_text(encoding="utf-8")
        expect(CHANGE_LOG_MARKER in clog_text, "change-log.md must carry the canonical marker")
        expect(SUMMARY_MARKER in sum_text, "summary.md must carry the canonical marker")
        expect(declares_project(sum_text, "demo_proj"), "summary.md must declare 'project: demo_proj'")
        expect(clog_text.splitlines()[0] == "# Change Log — demo_proj",
               f"unexpected change-log title: {clog_text.splitlines()[0]!r}")
        for section in ("## Current state", "## Key decisions", "## Recent history"):
            expect(section in sum_text, f"summary.md must stub the section '{section}'")

        # 3. `init` is idempotent: existing files are never changed, not even partially.
        write_journal(root, journal_entry("2026-09-01T00:00:00Z", "demo_proj"))
        summary.write_text(sum_text.replace("## Current state", "## Current state\nhand-written"), encoding="utf-8")
        before = (change_log.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
        res = run("init", "--repo", str(root))
        expect(res.returncode == 0, "repeated init must exit 0")
        expect(res.stdout.count("exists:") == 2, f"repeated init must report 2 existing files: {res.stdout!r}")
        expect((change_log.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")) == before,
               "repeated init must not modify existing memory files")

        # 4. `check` on a single-project journal -> exit 0 and names the owner.
        res = run("check", "--repo", str(root))
        expect(res.returncode == 0, "single-project memory must exit 0")
        expect("project 'demo_proj'" in res.stdout, f"check must name the owner: {res.stdout!r}")
        expect("(1 entries)" in res.stdout, f"check must count the entries: {res.stdout!r}")

        # 5. `check --expect <same project>` -> exit 0.
        expect(run("check", "--repo", str(root), "--expect", "demo_proj").returncode == 0,
               "matching --expect must exit 0")

        # 6. `check` on a memory that mixes two projects -> exit 1 + explicit message.
        write_journal(root, journal_entry("2026-09-01T00:00:00Z", "demo_proj"),
                      journal_entry("2026-09-02T00:00:00Z", "other_project"))
        res = run("check", "--repo", str(root))
        expect(res.returncode == 1, "mixed memory must exit 1")
        expect("mixes projects" in res.stderr, f"mixed memory must say 'mixes projects': {res.stderr!r}")
        expect("demo_proj" in res.stderr and "other_project" in res.stderr,
               "mixed memory must name both projects")

        # 7. `check --expect` with a foreign project -> exit 1.
        write_journal(root, journal_entry("2026-09-02T00:00:00Z", "demo_proj"))
        res = run("check", "--repo", str(root), "--expect", "some_other_project")
        expect(res.returncode == 1, "foreign --expect must exit 1")
        expect("expected" in res.stderr, f"foreign --expect must explain the mismatch: {res.stderr!r}")

        # 8. `check` on a fresh project (no journal at all) -> exit 0 with a note.
        empty = tmp / "fresh_proj"
        empty.mkdir()
        res = run("check", "--repo", str(empty))
        expect(res.returncode == 0, "missing journal must exit 0")
        expect("not found (fresh project)" in res.stdout, f"missing journal must note it: {res.stdout!r}")

        # 9. A freshly initialised memory (no records yet) -> exit 0; the owner is taken from
        #    the `project:` declaration in summary.md, never mistaken for a legacy memory.
        expect(run("init", "--repo", str(empty), "--project", "fresh_proj").returncode == 0,
               "init of a fresh project must exit 0")
        res = run("check", "--repo", str(empty))
        expect(res.returncode == 0, "journal without records must exit 0")
        expect("(0 entries)" in res.stdout, f"empty journal must report 0 entries: {res.stdout!r}")
        expect("project 'fresh_proj'" in res.stdout,
               f"a record-free memory must take its owner from summary.md: {res.stdout!r}")
        expect(run("check", "--repo", str(empty), "--expect", "fresh_proj").returncode == 0,
               "matching --expect on a record-free memory must exit 0")
        expect(run("check", "--repo", str(empty), "--expect", "wrong_proj").returncode == 1,
               "foreign --expect on a record-free memory must exit 1")
        expect(declares_project((empty / "memory" / "summary.md").read_text(encoding="utf-8"),
                                "fresh_proj"), "explicit --project must be used in the template")
        # The template must never contain a ready-made record (only the placeholder format).
        expect(not any(line.startswith("## 2") for line in
                       (empty / "memory" / "change-log.md").read_text(encoding="utf-8").splitlines()),
               "the change-log template must not contain a real record")

        # 10. A summary declaring a project other than the journal's -> exit 1.
        write_journal(root, journal_entry("2026-09-01T00:00:00Z", "demo_proj"))
        expect(run("check", "--repo", str(root)).returncode == 0,
               "an agreeing journal and summary must exit 0")
        sum_md = root / "memory" / "summary.md"
        sum_md.write_text(sum_md.read_text(encoding="utf-8").replace(
            "project: demo_proj", "project: another_project"), encoding="utf-8")
        res = run("check", "--repo", str(root))
        expect(res.returncode == 1, "a summary/journal project mismatch must exit 1")
        expect("another_project" in res.stderr and "demo_proj" in res.stderr,
               f"the mismatch must name both projects: {res.stderr!r}")

        # 11. Legacy memory: records WITHOUT `project:` and a summary WITHOUT the declaration ->
        #     exits 0 and is reported as legacy, never as a project mismatch. The `project:` line
        #     inside the fenced code block is an example, not a declaration (same rule as
        #     scripts/check_factory_model.py).
        legacy = tmp / "legacy_proj"
        (legacy / "memory").mkdir(parents=True)
        (legacy / "memory" / "change-log.md").write_text(
            "# Change Log — legacy\n\n" + CHANGE_LOG_MARKER + "\n\n"
            + journal_entry("2026-09-01T00:00:00Z") + journal_entry("2026-09-02T00:00:00Z"),
            encoding="utf-8")
        (legacy / "memory" / "summary.md").write_text(
            "# Project Summary — legacy\n\n" + SUMMARY_MARKER + "\n\n## Format examples\n\n"
            "```\nproject: other_proj\nrepo_path: /some/path\n```\n", encoding="utf-8")
        res = run("check", "--repo", str(legacy))
        expect(res.returncode == 0, "legacy memory (no project field) must exit 0")
        expect("(legacy, no project field)" in res.stdout,
               f"legacy memory must be reported as legacy: {res.stdout!r}")
        expect("(2 entries)" in res.stdout, f"check must count both records: {res.stdout!r}")
        expect(run("check", "--repo", str(legacy), "--expect", "legacy_proj").returncode == 0,
               "legacy memory must not be treated as a project mismatch")

    print("PASS - memory_project.py behaves as expected (init creates once, never rewrites, "
          "check passes/cli-fails on single/mixed/mismatched/missing/legacy memory).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    reports a record-free-of-`project` journal as legacy (never as a mismatch),
  - `check` enforces the owner by default: memory declaring another project than
    basename(resolved --repo) fails with a `rename` hint (`--no-owner-check` drops only that
    comparison) and passes again after `rename`,
  - `rename` rewrites every journal record and the summary declaration, leaves the template's
    fenced example untouched and is idempotent (second run reports 0 records, byte-identical),
  - `compact-check` fails when a severity=critical or follow_up=true item is missing after a
    compaction and passes when all of them survived,
  - `validate-fix-tasks` accepts a well-formed generated fix-task file and rejects a file that
    misses a required field or carries an invalid task_type, naming the offending line.

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


def journal_entry(timestamp: str, project: str = "", unfinished: str = "") -> str:
    """A minimal but format-valid journal record belonging to `project`.

    `project=""` builds a legacy record without the `project:` field; `unfinished` is an
    optional ready-made `unfinished:` block appended to the record.
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
{unfinished}"""


def unfinished_block(*items: tuple[str, str, str]) -> str:
    """Build an `unfinished:` block from (item, severity, follow_up) triples."""
    lines = ["unfinished:"]
    for item, severity, follow_up in items:
        lines += [f"  - item: {item}", "    reason: demo reason",
                  f"    severity: {severity}", f"    follow_up: {follow_up}"]
    return "\n".join(lines) + "\n"


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
        # The nit fix: the declaration carries the RESOLVED repo path, not the raw argument.
        expect(f"repo_path: {root.resolve()}" in sum_text,
               f"summary.md must declare the resolved repo_path: {sum_text!r}")
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

        # 12. Enforced owner: memory declaring (and recording) another project than
        #     basename(resolved --repo) fails with a rename hint; --no-owner-check drops only
        #     that comparison; --expect always wins.
        foreign = tmp / "foreign_proj"
        foreign.mkdir()
        f_clog = foreign / "memory" / "change-log.md"
        f_sum = foreign / "memory" / "summary.md"
        expect(run("init", "--repo", str(foreign), "--project", "renamed_proj").returncode == 0,
               "init of the mis-named project must exit 0")
        # The records are APPENDED to the freshly initialised journal, so the template's own
        # `project:` examples (fenced code block, prose) are still in the file and must survive
        # a rename untouched.
        f_clog.write_text(f_clog.read_text(encoding="utf-8") + "\n\n"
                          + journal_entry("2026-09-03T00:00:00Z", "renamed_proj")
                          + journal_entry("2026-09-04T00:00:00Z", "renamed_proj"),
                          encoding="utf-8")
        res = run("check", "--repo", str(foreign))
        expect(res.returncode == 1, "memory owned by another project must exit 1")
        expect("renamed_proj" in res.stderr and "foreign_proj" in res.stderr,
               f"the owner mismatch must name both projects: {res.stderr!r}")
        expect("rename" in res.stderr, f"the owner mismatch must hint at `rename`: {res.stderr!r}")
        expect("--no-owner-check" in res.stderr,
               f"the hint must cover the subdirectory case: {res.stderr!r}")
        expect(run("check", "--repo", str(foreign), "--no-owner-check").returncode == 0,
               "--no-owner-check must drop the basename comparison")
        expect(run("check", "--repo", str(foreign), "--expect", "renamed_proj").returncode == 0,
               "--expect must override the basename comparison")

        # 13. `rename` rewrites every record and the summary declaration, leaves the template's
        #     fenced example alone, and a second run is a byte-identical no-op (idempotent).
        res = run("rename", "--repo", str(foreign), "--to", "foreign_proj")
        expect(res.returncode == 0, "rename must exit 0")
        expect("2 record(s) rewritten" in res.stdout,
               f"rename must count the rewritten records: {res.stdout!r}")
        expect("declaration updated" in res.stdout,
               f"rename must report the updated declaration: {res.stdout!r}")
        clog_after = f_clog.read_text(encoding="utf-8")
        expect(clog_after.count("project: foreign_proj") == 2,
               f"rename must rewrite every record: {clog_after!r}")
        expect(declares_project(f_sum.read_text(encoding="utf-8"), "foreign_proj"),
               "rename must rewrite the summary declaration")
        expect(any(ln.startswith("project: <") and "renamed_proj" in ln
                   for ln in clog_after.splitlines()),
               "rename must not rewrite the template's fenced example")
        expect(run("check", "--repo", str(foreign)).returncode == 0,
               "check must pass after rename")

        renamed = (clog_after, f_sum.read_text(encoding="utf-8"))
        res = run("rename", "--repo", str(foreign), "--to", "foreign_proj")
        expect(res.returncode == 0, "repeated rename must exit 0")
        expect("0 record(s) rewritten" in res.stdout,
               f"repeated rename must rewrite nothing: {res.stdout!r}")
        expect("declaration unchanged" in res.stdout,
               f"repeated rename must leave the declaration: {res.stdout!r}")
        expect((f_clog.read_text(encoding="utf-8"), f_sum.read_text(encoding="utf-8")) == renamed,
               "repeated rename must be idempotent (byte-identical files)")
        expect(run("rename", "--repo", str(foreign), "--to", "").returncode == 1,
               "an empty --to must exit 1")

        # 14. Compact-preservation: every severity=critical / follow_up=true item must still be
        #     in the compacted file; a dropped one is an error listing it, the kept ones are not.
        before_file = tmp / "compact_before.md"
        after_file = tmp / "compact_after.md"
        before_file.write_text(
            "# Change Log — compact\n\n" + CHANGE_LOG_MARKER + "\n\n"
            + journal_entry("2026-09-05T00:00:00Z", "compact_proj", unfinished_block(
                ("critical review finding", "critical", "false"),
                ("small nit", "warning", "false"),
                ("idea for later", "info", "true"))), encoding="utf-8")
        after_file.write_text(
            "# Project Summary — compact\n\n" + SUMMARY_MARKER + "\n\n## Unfinished\n\n"
            + unfinished_block(("critical review finding", "critical", "false")), encoding="utf-8")
        res = run("compact-check", "--before", str(before_file), "--after", str(after_file))
        expect(res.returncode == 1, "a dropped follow_up item must exit 1")
        expect("idea for later" in res.stderr,
               f"the dropped item must be listed: {res.stderr!r}")
        expect("critical review finding" not in res.stderr,
               f"preserved items must not be reported: {res.stderr!r}")
        after_file.write_text(
            after_file.read_text(encoding="utf-8")
            + unfinished_block(("idea for later", "info", "true")), encoding="utf-8")
        res = run("compact-check", "--before", str(before_file), "--after", str(after_file))
        expect(res.returncode == 0, f"a lossless compaction must exit 0: {res.stderr!r}")
        expect("preserved all 2" in res.stdout,
               f"compact-check must count the preserved items: {res.stdout!r}")
        expect(run("compact-check", "--before", str(before_file),
                   "--after", str(tmp / "missing_after.md")).returncode == 1,
               "a missing file must exit 1")

        # 15. `validate-fix-tasks`: a well-formed generated file passes; a missing required field
        #     or an invalid task_type fails, naming the offending line.
        fix_ok = tmp / "fix-tasks.yaml"
        fix_ok.write_text(
            "# generated by the security_audit flow\n"
            "tasks:\n"
            '  - title: "Drop hardcoded credentials"\n'
            "    task_type: implement\n"
            '    description: "Read tokens from the environment."\n'
            "    acceptance_criteria:\n"
            '      - "No token in tracked files"\n'
            '      - "Deployment reads tokens from env"\n'
            "    commit_exclude: .env\n"
            '  - title: "Harden the container"\n'
            "    task_type: implement\n"
            '    description: "Run the app as a non-root user."\n'
            "    acceptance_criteria:\n"
            '      - "USER is not root in the image"\n', encoding="utf-8")
        res = run("validate-fix-tasks", str(fix_ok))
        expect(res.returncode == 0, f"a valid fix-task file must exit 0: {res.stderr!r}")
        expect("2 task(s)" in res.stdout,
               f"the validator must count the tasks: {res.stdout!r}")

        fix_bad = tmp / "fix-tasks-broken.yaml"
        fix_bad.write_text(
            "tasks:\n"
            '  - title: "Drop hardcoded credentials"\n'
            "    task_type: implement\n"
            '    description: "Read tokens from the environment."\n'
            "    acceptance_criteria:\n"
            '      - "No token in tracked files"\n'
            '  - title: "Harden the container"\n'
            "    task_type: patch\n"
            "    acceptance_criteria:\n"
            '      - "USER is not root in the image"\n', encoding="utf-8")
        res = run("validate-fix-tasks", str(fix_bad))
        expect(res.returncode == 1, "a fix-task file missing a required field must exit 1")
        expect("line 7: task 2 'Harden the container' missing required field 'description'"
               in res.stderr, f"the missing field must be reported with its line: {res.stderr!r}")
        expect("line 8: task 2 'Harden the container' has invalid task_type 'patch'" in res.stderr,
               f"the invalid task_type must be reported with its line: {res.stderr!r}")
        fix_empty = tmp / "fix-tasks-empty.yaml"
        fix_empty.write_text("# nothing was generated\n", encoding="utf-8")
        expect(run("validate-fix-tasks", str(fix_empty)).returncode == 1,
               "a task-less file must exit 1")
        expect(run("validate-fix-tasks", str(tmp / "missing.yaml")).returncode == 1,
               "a missing fix-task file must exit 1")

    print("PASS - memory_project.py behaves as expected (init creates once, never rewrites; "
          "check enforces a single owner and fails on mixed/mismatched/missing/legacy memory; "
          "rename rewrites the owner and is idempotent; compact-check keeps critical/follow_up "
          "items; validate-fix-tasks checks the fix-task schema).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

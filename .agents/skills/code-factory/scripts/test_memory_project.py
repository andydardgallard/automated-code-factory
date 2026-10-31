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
  - `backlog` folds the whole journal into the open items (critical or follow_up) minus the ones
    closed by a `closed:` element: an item neither repeated nor closed stays open with its source
    record, `--check` exits 0 only when nothing disappeared silently — every open item carried in
    the CURRENT record with a `reason:` (`carried`) or closed — and exits 1 on an unmentioned
    item, on a carried item without `reason:` and on every invalid `closed:` element (no
    `evidence:`, or an item no record ever declared); `--run-id` selects the current record,
    `--json` is machine-readable, and a `## Current state` claiming another version than VERSION
    only warns (stderr, exit untouched),
  - `compact` implements the 50/20 rule: it folds all but `--keep` records into
    memory/summary.md (`## Recent history` bullets + a `## Carried debt` section that carries every
    critical/follow_up item + a `## Closed with evidence` section that keeps the verbatim evidence
    of every folded closure), verifies in memory that nothing required — critical/follow_up items
    AND the closing protocol of the would-be files — is lost before writing, survives a SECOND fold
    whose records carry no open debt (a closure declares the item it closes, so resetting
    `## Carried debt` cannot orphan it), refuses to write a result that would report a
    closing-protocol error, stays byte-identical on a repeated run, and `--dry-run` writes nothing,
  - `validate-fix-tasks` accepts a well-formed generated fix-task file and rejects a file that
    misses a required field (including the mandatory `repo_path`) or carries an invalid
    task_type, naming the offending line,
  - the memory format v2 (run_id + provenance marks) is enforced on the records of a
    current-generation factory: a missing or malformed `run_id`, or a missing provenance mark in
    `decisions`/`results`, is an error, a missing `unfinished`/`factory_version` is an error on a
    v2 record and a warning only on a pre-v2 one, while records written before the format — with a
    `project:` or without one — only warn (exit 0),
  - the owner identity comes from the repository (the `project_id:` declaration = 12 hex chars of
    sha256 over the root commit), not from the deployment folder name: a renamed folder keeps its
    memory valid with a `project_id:` and fails without one (the negative probe of the old
    basename rule), a foreign `project_id:` is refused, and a `project_id:` that cannot be checked
    (no root commit) is never trusted as the identity — the name-based fallback decides and warns,
  - one run — one record: a duplicated `run_id` is an error, `check --run-id` demands exactly one
    matching record, `memory/` without `change-log.md` is an error (unless `--allow-fresh`) while an
    absent `memory/` stays a fresh-project note, `journal_blocks` carries 1-based `start`/`end`, and
    a `## Current state` whose open/closed/test counts diverge from the live state warns on `check`
    and fails under `--strict` (implied by `--run-id`).

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "memory_project.py"

CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
# A dated `## <timestamp>` line — the heading of a journal record.
ENTRY_PREFIX = re.compile(r"^## \d{4}-\d{2}-\d{2}")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def git_root_commit_repo(path: pathlib.Path, marker: str) -> None:
    """Create a git repository in `path` whose root commit is unique per `marker`.

    Only plumbing is used (`init`, `hash-object -w`, `mktree`, `commit-tree`, `update-ref`) and
    everything happens inside the fixture's own temporary directory: the identity of a repository
    is what `project_identity` derives from, so the fixture needs a real root commit, while the
    shared working tree of the factory is never touched.
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / "readme.txt").write_text(marker + "\n", encoding="utf-8")
    ident = dict(os.environ,
                 GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@example.com",
                 GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@example.com",
                 GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000",
                 GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000")

    def git(args: list[str], stdin: str = "",
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              errors="replace", input=stdin, env=env)
        expect(proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr!r}")
        return proc

    init = subprocess.run(["git", "init", "-q", "-b", "main", str(path)],
                          capture_output=True, text=True, errors="replace")
    expect(init.returncode == 0, f"git init failed: {init.stderr!r}")
    blob = git(["hash-object", "-w", "--stdin"], stdin=marker + "\n").stdout.strip()
    tree = git(["mktree"], stdin=f"100644 blob {blob}\treadme.txt\n").stdout.strip()
    commit = git(["commit-tree", tree, "-m", f"root {marker}"], env=ident).stdout.strip()
    git(["update-ref", "refs/heads/main", commit])


def journal_entry(timestamp: str, project: str = "", unfinished: str = "",
                  run_id: str = "", factory_version: str = "", marks: bool = False,
                  closed: str = "") -> str:
    """A minimal but format-valid journal record belonging to `project`.

    `project=""` builds a legacy record without the `project:` field; `unfinished` and `closed` are
    optional ready-made blocks appended to the record (`unfinished:` / `closed:`). The defaults keep
    every record written before the memory format v2 (no `run_id`, no provenance marks); `run_id`,
    `factory_version` and `marks=True` build a v2 record — marks=True puts a provenance mark
    into BOTH `decisions` and `results`, as the format requires.
    """
    name = project or "legacy"
    project_line = f"project: {project}\n" if project else ""
    run_id_line = f"run_id: {run_id}\n" if run_id else ""
    version_line = f"factory_version: {factory_version}\n" if factory_version else ""
    decisions = ("keep the two-level fingerprint [verified: scripts/test_memory_project.py]"
                 if marks else "(none)")
    results = ("integration=PASS [verified: .code-factory/logs/code-results.md]; regression=PASS; "
               "business=PASS; review=approve" if marks else
               "integration=PASS; regression=PASS; business=PASS; review=approve")
    # The debt section is always declared: an explicit no-debt marker unless the caller passes its
    # own `unfinished:` block — every real record carries the key (see the change-log template).
    debt = unfinished or "unfinished: no unfinished items\n"
    return f"""\
## {timestamp} — Run on {name}
title: Run on {name}
{project_line}timestamp: {timestamp}
{run_id_line}branch: main
commit: abc1234
task_type: implement
goal: Demo record.
changed_files: (none)
created_files: (none)
results: {results}
decisions: {decisions}
assumptions: (none)
models_used: analyzer=primary
{version_line}{debt}{closed}"""


def drop_fields(entry: str, *keys: str) -> str:
    """A copy of a journal record with the given top-level field lines removed.

    The negative probes of the record contract need a record that OMITS a mandatory key, which
    `journal_entry` always writes: dropping the line is the smallest way to build that shape.
    """
    dropped = set(keys)
    return "\n".join(line for line in entry.splitlines()
                     if line.split(":", 1)[0].strip() not in dropped) + "\n"


def unfinished_block(*items: tuple[str, str, str]) -> str:
    """Build an `unfinished:` block from (item, severity, follow_up) triples."""
    lines = ["unfinished:"]
    for item, severity, follow_up in items:
        lines += [f"  - item: {item}", "    reason: demo reason",
                  f"    severity: {severity}", f"    follow_up: {follow_up}"]
    return "\n".join(lines) + "\n"


def closed_block(*items: tuple[str, str]) -> str:
    """Build a `closed:` block from (item, evidence) pairs."""
    lines = ["closed:"]
    for item, evidence in items:
        lines += [f"  - item: {item}", f"    evidence: {evidence}"]
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

        # 8. `check` on a fresh project (no memory/ at all) -> exit 0 with the fresh-project note.
        #    (Item 3: the note now names the absent directory, since a memory/ WITHOUT its journal
        #    is a different, failing case — the next block probes exactly that.)
        empty = tmp / "fresh_proj"
        empty.mkdir()
        res = run("check", "--repo", str(empty))
        expect(res.returncode == 0, "missing journal must exit 0")
        expect("fresh project, memory/ absent" in res.stdout,
               f"missing journal must note it: {res.stdout!r}")
        # The partial memory is NEVER right: memory/ present without change-log.md fails.
        (empty / "memory").mkdir()
        res = run("check", "--repo", str(empty))
        expect(res.returncode == 1, "memory/ without change-log.md must exit 1")
        expect("memory directory exists without change-log.md" in res.stderr,
               f"the partial memory must be named: {res.stderr!r}")
        expect(run("check", "--repo", str(empty), "--allow-fresh").returncode == 0,
               "--allow-fresh must accept a deliberately journal-less memory")
        expect(run("check", "--repo", str(empty), "--run-id", "20261001-aaaabbbb").returncode == 1,
               "check --run-id without a journal must exit 1")
        (empty / "memory").rmdir()

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
        #     (incl. `repo_path`, mandatory for every non-green-field task) or an invalid task_type
        #     fails, naming the offending line.
        fix_ok = tmp / "fix-tasks.yaml"
        fix_ok.write_text(
            "# generated by the security_audit flow\n"
            "tasks:\n"
            '  - title: "Drop hardcoded credentials"\n'
            "    repo_path: .\n"
            "    task_type: implement\n"
            '    description: "Read tokens from the environment."\n'
            "    acceptance_criteria:\n"
            '      - "No token in tracked files"\n'
            '      - "Deployment reads tokens from env"\n'
            "    commit_exclude: .env\n"
            '  - title: "Harden the container"\n'
            "    repo_path: .\n"
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
        # C6: `repo_path` is mandatory for every non-green-field task, so a generated fix task
        # without it is unusable — it used to pass this validator and only fail at the finish gate.
        fix_no_repo = tmp / "fix-tasks-no-repo-path.yaml"
        fix_no_repo.write_text(
            "tasks:\n"
            '  - title: "Harden the container"\n'
            "    task_type: implement\n"
            '    description: "Run the app as a non-root user."\n'
            "    acceptance_criteria:\n"
            '      - "USER is not root in the image"\n', encoding="utf-8")
        res = run("validate-fix-tasks", str(fix_no_repo))
        expect(res.returncode == 1, "a fix task without repo_path must exit 1")
        expect("line 2: task 1 'Harden the container' missing required field 'repo_path'"
               in res.stderr,
               f"the missing repo_path must be reported with its line: {res.stderr!r}")
        fix_empty = tmp / "fix-tasks-empty.yaml"
        fix_empty.write_text("# nothing was generated\n", encoding="utf-8")
        expect(run("validate-fix-tasks", str(fix_empty)).returncode == 1,
               "a task-less file must exit 1")
        expect(run("validate-fix-tasks", str(tmp / "missing.yaml")).returncode == 1,
               "a missing fix-task file must exit 1")

        # 16. Memory format v2: the template documents `run_id` and the provenance marks; a
        #     record of a current-generation factory must carry a well-formed `run_id` and a mark
        #     in BOTH decisions and results (error otherwise), while a pre-v2 record stays valid
        #     and silent and a legacy record (no `project:`) only warns.
        v2 = tmp / "v2_proj"
        v2.mkdir()
        expect(run("init", "--repo", str(v2)).returncode == 0, "init of the v2 fixture must exit 0")
        template = (v2 / "memory" / "change-log.md").read_text(encoding="utf-8")
        expect("run_id: <YYYYMMDD-8hex" in template,
               "the change-log template must document the run_id field")
        expect("\\d{8}-[0-9a-f]{8}" in template,
               "the change-log template must document the run_id format")
        expect("[verified: " in template and "[inferred]" in template,
               "the change-log template must document both provenance marks")

        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       run_id="20260922-442cd2f8",
                                       factory_version="12.9.0", marks=True))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 0,
               f"a v2 record with run_id and marks must exit 0: {res.stderr!r}")

        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       factory_version="12.9.0", marks=True))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1, "a v2 record without run_id must exit 1")
        expect("run_id" in res.stderr, f"the missing run_id must be named: {res.stderr!r}")

        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       run_id="2026-09-22", factory_version="12.9.0", marks=True))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1, "a malformed run_id must exit 1")
        expect("invalid run_id" in res.stderr,
               f"the malformed run_id must be reported: {res.stderr!r}")

        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       run_id="20260922-442cd2f8", factory_version="12.9.0"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1, "a v2 record without provenance marks must exit 1")
        expect("provenance mark" in res.stderr,
               f"the missing marks must be reported: {res.stderr!r}")
        expect("decisions" in res.stderr and "results" in res.stderr,
               f"both marked fields must be named: {res.stderr!r}")

        #     A record that already carries one v2 field must satisfy the rest of the format even
        #     when its factory_version still predates it (half-migrated record).
        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       factory_version="12.8.0", marks=True))
        expect(run("check", "--repo", str(v2)).returncode == 1,
               "a half-migrated v2 record must still be an error")

        #     A one-time legacy migration backfills a SYNTHETIC run_id/factory_version: the value
        #     keeps the canonical form and carries the annotation ` (synthetic, backfilled
        #     YYYY-MM-DD)` — valid, so the migrated history passes without daily WARN lines.
        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       run_id="20260901-e9c0219e (synthetic, backfilled 2026-10-26)",
                                       factory_version="12.8.0 (synthetic, backfilled 2026-10-26)",
                                       marks=True))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 0,
               f"a synthetic backfilled run_id/factory_version must be valid: {res.stderr!r}")
        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       run_id="20260901-e9c0219e (synthetic)",
                                       factory_version="12.9.0", marks=True))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1 and "invalid run_id" in res.stderr,
               f"a truncated annotation must stay invalid: {res.stderr!r}")

        #     A record of a pre-v2 factory stays VALID but must WARN: the documented contract makes
        #     a record with `project:` that predates the format a warning (never rewritten, never an
        #     error) — item 2 closed the else-branch that used to accept it silently.
        write_journal(v2, journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                       factory_version="12.8.0"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 0, f"a pre-v2 record must exit 0: {res.stderr!r}")
        expect("WARN" in res.stderr and "run_id" in res.stderr,
               f"a pre-v2 record must warn: {res.stderr!r}")
        expect("pre-v2 format - never rewritten, a warning by contract" in res.stderr,
               f"the warning must name the pre-v2 format: {res.stderr!r}")

        #     A legacy record (no `project:`) is only warned about, never failed.
        write_journal(v2, journal_entry("2026-09-25T00:00:00Z"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 0, "a legacy record without run_id/marks must exit 0")
        expect("WARN" in res.stderr and "run_id" in res.stderr,
               f"a legacy record must warn about the missing run_id: {res.stderr!r}")
        expect("legacy format" in res.stderr,
               f"the warning must mark the record as legacy: {res.stderr!r}")

        #     C8: `unfinished` and `factory_version` are MANDATORY on a current-generation record.
        #     They used to be a legacy warning in every case, so a record PROVEN v2 by its own
        #     run_id could silently drop both. A v2 record -> error, a pre-v2 record -> warning.
        write_journal(v2, drop_fields(journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                                    run_id="20260922-442cd2f8", marks=True),
                                     "unfinished", "factory_version"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1,
               f"a v2 record without unfinished/factory_version must exit 1: {res.stderr!r}")
        expect("missing key 'unfinished' (required by the memory format v2" in res.stderr,
               f"the missing unfinished of a v2 record must be an error: {res.stderr!r}")
        expect("missing key 'factory_version' (required by the memory format v2" in res.stderr,
               f"the missing factory_version of a v2 record must be an error: {res.stderr!r}")
        #     One missing key is enough: a v2 record (proven by its version and marks) that omits
        #     only `unfinished` fails too.
        write_journal(v2, drop_fields(journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                                    run_id="20260922-442cd2f8",
                                                    factory_version="12.9.0", marks=True),
                                     "unfinished"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 1 and "missing key 'unfinished'" in res.stderr,
               f"a v2 record omitting only unfinished must exit 1: {res.stderr!r}")
        #     The genuinely pre-v2 branch keeps its warning: omitting both keys only WARNS.
        write_journal(v2, drop_fields(journal_entry("2026-09-25T00:00:00Z", "v2_proj",
                                                    factory_version="12.8.0"),
                                     "unfinished", "factory_version"))
        res = run("check", "--repo", str(v2))
        expect(res.returncode == 0,
               f"a pre-v2 record omitting both keys must only warn: {res.stderr!r}")
        expect("missing key 'unfinished' (legacy format)" in res.stderr
               and "missing key 'factory_version' (legacy format)" in res.stderr,
               f"the pre-v2 omission must stay a legacy warning: {res.stderr!r}")

        # 17. `backlog` fold: an item declared open by record 1 and neither repeated nor closed by
        #     record 2 stays open (the silent-disappearance bug this mechanism exists for): the
        #     report names the item and its source record, and `--check` fails. The template
        #     documents the closing protocol.
        bl = tmp / "backlog_proj"
        bl.mkdir()
        expect(run("init", "--repo", str(bl)).returncode == 0,
               "init of the backlog fixture must exit 0")
        bl_template = (bl / "memory" / "change-log.md").read_text(encoding="utf-8")
        expect("closed:" in bl_template and "evidence:" in bl_template,
               "the change-log template must document the `closed:`/`evidence:` protocol")
        write_journal(bl,
                      journal_entry("2026-09-26T00:00:00Z", "backlog_proj",
                                    unfinished=unfinished_block(("silent debt item", "warning",
                                                                 "true")),
                                    run_id="20260926-11112233", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-09-27T00:00:00Z", "backlog_proj",
                                    run_id="20260927-44556677", factory_version="12.9.0",
                                    marks=True))
        res = run("backlog", "--repo", str(bl))
        expect(res.returncode == 0, f"backlog without --check must exit 0: {res.stderr!r}")
        expect("open: 1" in res.stdout, f"the dropped item must stay open: {res.stdout!r}")
        expect("silent debt item" in res.stdout,
               f"the open item must be printed: {res.stdout!r}")
        expect("2026-09-26T00:00:00Z" in res.stdout,
               f"the source record must be printed: {res.stdout!r}")
        expect("legacy drift" in res.stdout,
               f"an unreconciled history must be marked as drift: {res.stdout!r}")
        res = run("backlog", "--repo", str(bl), "--check")
        expect(res.returncode == 1, "an open backlog must fail --check")
        expect("silent debt item" in res.stderr,
               f"the failing item must be named: {res.stderr!r}")

        # 18. The closing protocol: the same item closed by a `closed:` element WITH `evidence:` in
        #     record 2 -> open: 0, `--check` exits 0, and `check` (format/owner) still passes on a
        #     record carrying the new key.
        write_journal(bl,
                      journal_entry("2026-09-26T00:00:00Z", "backlog_proj",
                                    unfinished=unfinished_block(("silent debt item", "warning",
                                                                 "true")),
                                    run_id="20260926-11112233", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-09-27T00:00:00Z", "backlog_proj",
                                    closed=closed_block(("silent debt item",
                                                         "memory_project.py:120 -> exit 0")),
                                    run_id="20260927-44556677", factory_version="12.9.0",
                                    marks=True))
        res = run("backlog", "--repo", str(bl), "--check")
        expect(res.returncode == 0, f"a closed backlog must pass --check: {res.stderr!r}")
        expect("open: 0" in run("backlog", "--repo", str(bl)).stdout,
               "a closed item must not be open any more")
        expect(run("check", "--repo", str(bl)).returncode == 0,
               "a record with a `closed:` block must not break `check`")

        # 19. Closing without evidence is invalid: same fixture, `evidence:` dropped -> --check
        #     exits 1 and says why (the closure is not accepted).
        write_journal(bl,
                      journal_entry("2026-09-26T00:00:00Z", "backlog_proj",
                                    unfinished=unfinished_block(("silent debt item", "warning",
                                                                 "true")),
                                    run_id="20260926-11112233", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-09-27T00:00:00Z", "backlog_proj",
                                    closed="closed:\n  - item: silent debt item\n",
                                    run_id="20260927-44556677", factory_version="12.9.0",
                                    marks=True))
        res = run("backlog", "--repo", str(bl), "--check")
        expect(res.returncode == 1, "a closure without evidence must fail --check")
        expect("evidence" in res.stderr, f"the missing evidence must be named: {res.stderr!r}")
        expect("open: 1" in run("backlog", "--repo", str(bl)).stdout,
               "a closure without evidence must not close the item")

        # 20. `closed:` naming an item no record ever declared open -> --check exits 1.
        write_journal(bl,
                      journal_entry("2026-09-26T00:00:00Z", "backlog_proj",
                                    unfinished=unfinished_block(("silent debt item", "warning",
                                                                 "true")),
                                    run_id="20260926-11112233", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-09-27T00:00:00Z", "backlog_proj",
                                    closed=closed_block(("phantom item", "nowhere:1")),
                                    run_id="20260927-44556677", factory_version="12.9.0",
                                    marks=True))
        res = run("backlog", "--repo", str(bl), "--check")
        expect(res.returncode == 1, "closing an unknown item must fail --check")
        expect("phantom item" in res.stderr,
               f"the unknown item must be named: {res.stderr!r}")
        expect("matches no" in res.stderr,
               f"the unknown item must be reported as unmatched: {res.stderr!r}")
        expect("open: 1" in run("backlog", "--repo", str(bl)).stdout,
               "an unknown closed item must not close anything")

        # 21. An item is open by severity=critical even with follow_up=false (same predicate as
        #     compact-check: critical or follow_up), and `--json` is valid JSON carrying the count.
        crit = tmp / "critical_proj"
        crit.mkdir()
        expect(run("init", "--repo", str(crit)).returncode == 0,
               "init of the critical fixture must exit 0")
        write_journal(crit, journal_entry(
            "2026-09-28T00:00:00Z", "critical_proj",
            unfinished=unfinished_block(("critical but not a follow-up", "critical", "false")),
            run_id="20260928-88990011", factory_version="12.9.0", marks=True))
        res = run("backlog", "--repo", str(crit), "--check")
        # Item 6 changed the gate from "open: 0" to "no silent disappearance": an item carried in
        # the CURRENT record WITH a reason is accepted (the rule allows carrying debt), so this
        # fail-on-any-open-item assertion became a pass — while the next block proves that an item
        # mentioned nowhere still fails.
        expect(res.returncode == 0,
               f"an item carried in the current record with a reason must pass --check: {res.stderr!r}")
        expect("carried: 1 (reason in the current record)" in run(
            "backlog", "--repo", str(crit)).stdout,
            "the carried item must be counted as carried")
        res = run("backlog", "--repo", str(crit), "--json")
        expect(res.returncode == 0, f"backlog --json must exit 0: {res.stderr!r}")
        payload = json.loads(res.stdout)          # raises when the output is not valid JSON
        expect(payload["open"] == 1, f"the JSON must carry the open count: {payload!r}")
        expect(payload["items"][0]["item"] == "critical but not a follow-up",
               f"the JSON must carry the open item: {payload!r}")
        expect(payload["items"][0]["timestamp"] == "2026-09-28T00:00:00Z",
               f"the JSON must carry the source record: {payload!r}")
        expect(payload["errors"] == [], f"a valid journal must report no errors: {payload!r}")

        # 22. WARN when `## Current state` claims a factory version other than the repo's VERSION:
        #     printed on stderr, exit code untouched; a matching version stays silent.
        ver = tmp / "ver_proj"
        ver.mkdir()
        expect(run("init", "--repo", str(ver)).returncode == 0,
               "init of the version fixture must exit 0")
        (ver / "VERSION").write_text("12.10.2\n", encoding="utf-8")
        v_sum = ver / "memory" / "summary.md"
        v_sum.write_text(v_sum.read_text(encoding="utf-8").replace(
            "## Current state", "## Current state\nFactory v0.0.0: stale summary."),
            encoding="utf-8")
        res = run("backlog", "--repo", str(ver))
        expect(res.returncode == 0,
               f"the stale-version warning must not fail the run: {res.stderr!r}")
        expect("WARN" in res.stderr and "v0.0.0" in res.stderr and "12.10.2" in res.stderr,
               f"the stale summary version must be warned about: {res.stderr!r}")
        expect("open: 0" in res.stdout,
               f"the empty journal must report 0 open items: {res.stdout!r}")
        v_sum.write_text(v_sum.read_text(encoding="utf-8").replace("v0.0.0", "v12.10.2"),
                         encoding="utf-8")
        res = run("backlog", "--repo", str(ver), "--check")
        expect(res.returncode == 0, f"a summary matching VERSION must pass --check: {res.stderr!r}")
        expect("WARN" not in res.stderr, f"a matching version must not warn: {res.stderr!r}")

        # 23. A `closed:` block is not debt: it must not make `compact-check` believe a required
        #     item "survived" a compaction just because its text also appears in a closure.
        closed_before = tmp / "closed_before.md"
        closed_after = tmp / "closed_after.md"
        closed_before.write_text(
            "# Change Log — closed\n\n" + CHANGE_LOG_MARKER + "\n\n"
            + journal_entry("2026-09-29T00:00:00Z", "closed_proj",
                            unfinished=unfinished_block(("debt still open", "warning", "true"))),
            encoding="utf-8")
        closed_after.write_text(
            "# Project Summary — closed\n\n" + SUMMARY_MARKER + "\n\n## Unfinished\n\n"
            + journal_entry("2026-09-30T00:00:00Z", "closed_proj",
                            closed=closed_block(("debt still open", "nowhere:1"))),
            encoding="utf-8")
        res = run("compact-check", "--before", str(closed_before), "--after", str(closed_after))
        expect(res.returncode == 1,
               f"a closure must not satisfy the compaction check: {res.stdout!r}")
        expect("debt still open" in res.stderr,
               f"the dropped item must still be reported: {res.stderr!r}")

        # 24. The memory identity is derived from the REPOSITORY (its root commit), never from the
        #     deployment folder name: a renamed or versioned copy keeps its memory valid with a
        #     declared `project_id:`, while the same memory WITHOUT it fails on the basename rule
        #     (the defect probe), and a foreign `project_id:` is refused.
        ident_dir = tmp / "identity_origin"
        git_root_commit_repo(ident_dir, "identity-origin")
        expect(run("init", "--repo", str(ident_dir)).returncode == 0,
               "init of the identity fixture must exit 0")
        i_sum = ident_dir / "memory" / "summary.md"
        i_clog = ident_dir / "memory" / "change-log.md"
        i_lines = i_sum.read_text(encoding="utf-8").splitlines()
        repo_line = next(i for i, ln in enumerate(i_lines) if ln.startswith("repo_path: "))
        expect(i_lines[repo_line + 1].startswith("project_id: "),
               f"project_id must be declared right after repo_path: {i_lines[repo_line:repo_line + 2]!r}")
        project_id = i_lines[repo_line + 1].split("project_id: ", 1)[1].strip()
        expect(len(project_id) == 12 and all(c in "0123456789abcdef" for c in project_id),
               f"project_id must be 12 hex characters, got {project_id!r}")
        i_clog.write_text(i_clog.read_text(encoding="utf-8") + "\n\n"
                          + journal_entry("2026-10-01T00:00:00Z", "identity_origin",
                                          run_id="20261001-0a0b0c0d",
                                          factory_version="12.9.0", marks=True),
                          encoding="utf-8")
        expect(run("check", "--repo", str(ident_dir)).returncode == 0,
               "the memory of its own repository must pass check")
        renamed_ident = tmp / "identity_renamed_v2"
        ident_dir.rename(renamed_ident)
        r_sum = renamed_ident / "memory" / "summary.md"
        res = run("check", "--repo", str(renamed_ident))
        expect(res.returncode == 0,
               f"a renamed deployment folder must keep its memory valid via project_id: {res.stderr!r}")
        expect("basis: identity" in res.stdout,
               f"the identity basis must be reported: {res.stdout!r}")
        # The negative probe: the very same memory without `project_id:` — the pre-fix behaviour,
        # where the owner is the folder name — fails after the rename. The declaration keeps
        # `repo_path: .` (the shape the factory's own memory uses), because an absolute
        # `repo_path:` is itself a name-based declaration that would still name the old folder.
        no_id = "\n".join(ln for ln in r_sum.read_text(encoding="utf-8").splitlines()
                          if not ln.startswith("project_id: "))
        no_id = no_id.replace(f"repo_path: {ident_dir.resolve()}", "repo_path: .")
        r_sum.write_text(no_id + "\n", encoding="utf-8")
        res = run("check", "--repo", str(renamed_ident))
        expect(res.returncode == 1,
               "without project_id a renamed folder must fail the basename rule")
        expect("identity_renamed_v2" in res.stderr and "identity_origin" in res.stderr,
               f"the name-based mismatch must name both names: {res.stderr!r}")
        expect("project_id" in res.stderr,
               f"the failure must hint at the project_id migration: {res.stderr!r}")
        # A foreign identity (another repository's root commit) is refused, naming both ids.
        other_repo = tmp / "identity_other"
        git_root_commit_repo(other_repo, "identity-other")
        expect(run("init", "--repo", str(other_repo)).returncode == 0,
               "init of the other repository must exit 0")
        other_id = next(ln.split("project_id: ", 1)[1].strip() for ln in
                        (other_repo / "memory" / "summary.md").read_text(
                            encoding="utf-8").splitlines() if ln.startswith("project_id: "))
        expect(other_id != project_id,
               "two repositories with different histories must have different identities")
        r_sum.write_text(no_id.replace("repo_path: .",
                                       f"repo_path: .\nproject_id: {other_id}") + "\n",
                         encoding="utf-8")
        res = run("check", "--repo", str(renamed_ident))
        expect(res.returncode == 1, "a foreign project_id must be refused")
        expect("another repository" in res.stderr,
               f"the foreign repository must be named as such: {res.stderr!r}")
        expect(other_id in res.stderr and project_id in res.stderr,
               f"the refusal must name both identities: {res.stderr!r}")

        # 24b. C7: a declared `project_id:` that CANNOT be checked proves nothing. With no root
        #      commit to compare it with, any declared id used to BE the identity basis — so a
        #      foreign or arbitrary id passed exactly when nobody could verify it. Now the
        #      documented name-based fallback decides and the unverified declaration is reported.
        unver = tmp / "unverifiable_proj"
        unver.mkdir()
        expect(run("init", "--repo", str(unver), "--project", "claimed_proj").returncode == 0,
               "init of the unverifiable-identity fixture must exit 0")
        u_sum = unver / "memory" / "summary.md"
        u_sum.write_text(u_sum.read_text(encoding="utf-8").replace(
            "project_id: \n", "project_id: 0123456789ab\n"), encoding="utf-8")
        u_clog = unver / "memory" / "change-log.md"
        u_clog.write_text(u_clog.read_text(encoding="utf-8") + "\n\n"
                          + journal_entry("2026-10-02T12:00:00Z", "claimed_proj",
                                          run_id="20261002-0a0b0c0d",
                                          factory_version="12.9.0", marks=True),
                          encoding="utf-8")
        res = run("check", "--repo", str(unver))
        expect(res.returncode == 1,
               f"an unverifiable project_id must not become the identity basis: {res.stderr!r}")
        expect("project_id 0123456789ab" in res.stderr and "cannot be verified" in res.stderr,
               f"the unverified declaration must be reported: {res.stderr!r}")
        expect("memory belongs to project 'claimed_proj'" in res.stderr,
               f"the documented name-based fallback must decide: {res.stderr!r}")
        expect("basis: identity" not in res.stdout,
               f"an unverifiable id must not be reported as the identity basis: {res.stdout!r}")
        expect(run("check", "--repo", str(unver), "--expect", "claimed_proj").returncode == 0,
               "--expect must still accept an intentional subdirectory project")

        # 25. One run — one record: a `run_id` carried by two records is a hard error naming both.
        dup = tmp / "dup_proj"
        dup.mkdir()
        expect(run("init", "--repo", str(dup)).returncode == 0,
               "init of the duplicates fixture must exit 0")
        write_journal(dup,
                      journal_entry("2026-10-02T00:00:00Z", "dup_proj",
                                    run_id="20261002-aaaabbbb", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-10-03T00:00:00Z", "dup_proj",
                                    run_id="20261002-aaaabbbb", factory_version="12.9.0",
                                    marks=True))
        res = run("check", "--repo", str(dup))
        expect(res.returncode == 1, "a duplicated run_id must exit 1")
        expect("20261002-aaaabbbb" in res.stderr,
               f"the duplicated run_id must be named: {res.stderr!r}")
        expect("2026-10-02T00:00:00Z" in res.stderr and "2026-10-03T00:00:00Z" in res.stderr,
               f"both headings must be named: {res.stderr!r}")
        write_journal(dup,
                      journal_entry("2026-10-02T00:00:00Z", "dup_proj",
                                    run_id="20261002-aaaabbbb", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-10-03T00:00:00Z", "dup_proj",
                                    run_id="20261003-ccccdddd", factory_version="12.9.0",
                                    marks=True))
        expect(run("check", "--repo", str(dup)).returncode == 0,
               "distinct run_ids must pass the duplicate check")

        # 26. `check --run-id`: exactly ONE record must carry the run id; a missing or duplicated
        #     one fails with its own message, and legacy records without a run_id stay exempt.
        expect(run("check", "--repo", str(dup), "--run-id", "20261002-aaaabbbb").returncode == 0,
               "the record of that run must satisfy --run-id")
        res = run("check", "--repo", str(dup), "--run-id", "20261109-99999999")
        expect(res.returncode == 1, "a run without a memory record must exit 1")
        expect("run 20261109-99999999 produced no memory record" in res.stderr,
               f"the missing record must be named: {res.stderr!r}")
        write_journal(dup,
                      journal_entry("2026-10-04T00:00:00Z", "dup_proj",
                                    run_id="20261004-eeeeffff", factory_version="12.9.0",
                                    marks=True),
                      journal_entry("2026-10-05T00:00:00Z", "dup_proj",
                                    run_id="20261004-eeeeffff", factory_version="12.9.0",
                                    marks=True))
        res = run("check", "--repo", str(dup), "--run-id", "20261004-eeeeffff")
        expect(res.returncode == 1, "two records sharing a run id must exit 1")
        expect("two records share run 20261004-eeeeffff" in res.stderr,
               f"the shared run id must be named: {res.stderr!r}")
        write_journal(dup,
                      journal_entry("2026-10-06T00:00:00Z", "dup_proj",
                                    factory_version="12.8.0"),
                      journal_entry("2026-10-07T00:00:00Z", "dup_proj",
                                    factory_version="12.8.0"))
        expect(run("check", "--repo", str(dup)).returncode == 0,
               "legacy records without a run_id must stay exempt from the one-record rule")

        # 27. `journal_blocks` exposes 1-based start/end line numbers (another package needs them).
        api = tmp / "api_proj"
        api.mkdir()
        expect(run("init", "--repo", str(api)).returncode == 0,
               "init of the parser fixture must exit 0")
        write_journal(api,
                      journal_entry("2026-10-08T00:00:00Z", "api_proj"),
                      journal_entry("2026-10-09T00:00:00Z", "api_proj"))
        api_lines = (api / "memory" / "change-log.md").read_text(encoding="utf-8").splitlines()
        heads = [i + 1 for i, ln in enumerate(api_lines) if ENTRY_PREFIX.match(ln)]
        expect(len(heads) == 2, f"the parser fixture must hold 2 records: {heads!r}")
        expected_ranges = []
        for index, start in enumerate(heads):
            stop = heads[index + 1] - 1 if index + 1 < len(heads) else len(api_lines)
            while stop >= start and not api_lines[stop - 1].strip():
                stop -= 1
            expected_ranges.append(f"{start}-{stop}")
        probe = subprocess.run(
            [sys.executable, "-c",
             "import pathlib, sys; sys.path.insert(0, sys.argv[1]); import memory_project as m; "
             "print('|'.join(str(r['start']) + '-' + str(r['end']) "
             "for r in m.journal_blocks(pathlib.Path(sys.argv[2]))))",
             str(SCRIPTS), str(api / "memory" / "change-log.md")],
            capture_output=True, text=True, errors="replace")
        expect(probe.returncode == 0, f"the parser probe must run: {probe.stderr!r}")
        expect(probe.stdout.strip() == "|".join(expected_ranges),
               f"journal_blocks must carry 1-based start/end: {probe.stdout!r} != "
               f"{'|'.join(expected_ranges)!r}")

        # 28. `compact` implements the 50/20 rule: fold all but `--keep` into the summary, carry
        #     every critical/follow_up item, write atomically, be idempotent and honour --dry-run.
        cmp_dir = tmp / "compact_live"
        cmp_dir.mkdir()
        expect(run("init", "--repo", str(cmp_dir)).returncode == 0,
               "init of the compaction fixture must exit 0")
        write_journal(
            cmp_dir,
            journal_entry("2026-10-10T00:00:00Z", "compact_live", run_id="20261010-11112233",
                          factory_version="12.9.0", marks=True,
                          unfinished=unfinished_block(("critical folded item", "critical", "false"),
                                                      ("harmless folded note", "warning", "false"))),
            journal_entry("2026-10-11T00:00:00Z", "compact_live", run_id="20261011-22223333",
                          factory_version="12.9.0", marks=True,
                          unfinished=unfinished_block(("follow-up folded item", "info", "true"))),
            journal_entry("2026-10-12T00:00:00Z", "compact_live", run_id="20261012-33334444",
                          factory_version="12.9.0", marks=True),
            journal_entry("2026-10-13T00:00:00Z", "compact_live", run_id="20261013-44445555",
                          factory_version="12.9.0", marks=True))
        c_clog = cmp_dir / "memory" / "change-log.md"
        c_sum = cmp_dir / "memory" / "summary.md"
        original_journal = tmp / "compact_original.md"
        original_journal.write_text(c_clog.read_text(encoding="utf-8"), encoding="utf-8")
        res = run("compact", "--repo", str(cmp_dir), "--threshold", "2", "--keep", "1")
        expect(res.returncode == 0, f"compact must exit 0: {res.stderr!r}")
        for line in ("folded: 3", "kept: 1", "carried: 2"):
            expect(line in res.stdout, f"compact must print '{line}': {res.stdout!r}")
        clog_after = c_clog.read_text(encoding="utf-8")
        expect(clog_after.count("## 2026-") == 1,
               f"the journal must keep exactly --keep records: {clog_after!r}")
        expect("2026-10-13T00:00:00Z" in clog_after,
               "the newest record must survive the compaction")
        expect("2026-10-10T00:00:00Z" not in clog_after,
               "the folded records must leave the journal")
        expect(CHANGE_LOG_MARKER in clog_after,
               "the journal header must survive verbatim")
        sum_after = c_sum.read_text(encoding="utf-8")
        expect("## Recent history" in sum_after, "the summary must carry the history section")
        expect("- 2026-10-10T00:00:00Z — Run on compact_live" in sum_after,
               f"every folded record needs a history bullet: {sum_after!r}")
        expect("20261010-11112233" in sum_after,
               f"the bullet must carry the run_id: {sum_after!r}")
        expect("## Carried debt" in sum_after, "the summary must carry the carried-debt section")
        expect("critical folded item" in sum_after,
               f"the critical item must survive the compaction: {sum_after!r}")
        expect("follow-up folded item" in sum_after,
               f"the follow_up item must survive the compaction: {sum_after!r}")
        expect("harmless folded note" not in sum_after,
               "only critical/follow_up items are carried as debt")
        res = run("compact-check", "--before", str(original_journal), "--after", str(c_sum))
        expect(res.returncode == 0,
               f"the compaction must satisfy compact-check: {res.stderr!r}")
        # The second run is byte-identical: the journal is already under the threshold.
        snapshot = (clog_after, sum_after)
        res = run("compact", "--repo", str(cmp_dir), "--threshold", "2", "--keep", "1")
        expect(res.returncode == 0, f"the repeated compact must exit 0: {res.stderr!r}")
        expect("nothing to compact" in res.stdout,
               f"the repeated compact must report the idle state: {res.stdout!r}")
        expect((c_clog.read_text(encoding="utf-8"),
                c_sum.read_text(encoding="utf-8")) == snapshot,
               "the repeated compact must be byte-identical (idempotent)")
        # --dry-run prints the plan and writes NOTHING.
        dry = tmp / "compact_dry"
        dry.mkdir()
        expect(run("init", "--repo", str(dry)).returncode == 0,
               "init of the dry-run fixture must exit 0")
        write_journal(dry,
                      journal_entry("2026-10-14T00:00:00Z", "compact_dry"),
                      journal_entry("2026-10-15T00:00:00Z", "compact_dry"),
                      journal_entry("2026-10-16T00:00:00Z", "compact_dry"),
                      journal_entry("2026-10-17T00:00:00Z", "compact_dry"))
        dry_before = ((dry / "memory" / "change-log.md").read_bytes(),
                      (dry / "memory" / "summary.md").read_bytes())
        res = run("compact", "--repo", str(dry), "--threshold", "2", "--keep", "1", "--dry-run")
        expect(res.returncode == 0, f"a dry run must exit 0: {res.stderr!r}")
        expect("would fold: 3" in res.stdout and "nothing written" in res.stdout,
               f"the dry run must print the plan: {res.stdout!r}")
        expect(((dry / "memory" / "change-log.md").read_bytes(),
                (dry / "memory" / "summary.md").read_bytes()) == dry_before,
               "--dry-run must write nothing")
        # A compaction that cannot verify its own result (no summary to fold into) fails and
        # writes not a byte of the journal.
        broken = tmp / "compact_broken"
        shutil.copytree(dry, broken)
        (broken / "memory" / "summary.md").unlink()
        broken_journal = (broken / "memory" / "change-log.md").read_bytes()
        res = run("compact", "--repo", str(broken), "--threshold", "2", "--keep", "1")
        expect(res.returncode == 1, "a compaction without a summary must exit 1")
        expect((broken / "memory" / "change-log.md").read_bytes() == broken_journal,
               "a failing compaction must not write the journal")
        expect(run("compact", "--repo", str(dry), "--keep", "0").returncode == 1,
               "--keep 0 must exit 1")

        # 29. Carry-over vs disappearance: a debt carried in the CURRENT record with a reason
        #     passes `backlog --check`; an item mentioned nowhere, or carried without a reason,
        #     fails it — the rule allows carrying, never disappearing.
        carry = tmp / "carry_proj"
        carry.mkdir()
        expect(run("init", "--repo", str(carry)).returncode == 0,
               "init of the carry fixture must exit 0")
        written = journal_entry("2026-10-20T00:00:00Z", "carry_proj", run_id="20261020-11112233",
                                factory_version="12.9.0", marks=True,
                                unfinished=unfinished_block(("carried debt item", "critical",
                                                             "false")))
        carried = journal_entry(
            "2026-10-21T00:00:00Z", "carry_proj", run_id="20261021-22223333",
            factory_version="12.9.0", marks=True,
            unfinished="unfinished:\n  - item: carried debt item\n"
                       "    reason: waits for the owner's ruling\n"
                       "    severity: critical\n    follow_up: false\n")
        write_journal(carry, written, carried)
        res = run("backlog", "--repo", str(carry), "--check")
        expect(res.returncode == 0,
               f"a carried item with a reason must pass --check: {res.stderr!r}")
        out = run("backlog", "--repo", str(carry)).stdout
        expect("open: 1" in out, f"the carried item stays open: {out!r}")
        expect("carried: 1 (reason in the current record)" in out,
               f"the carried count must be printed: {out!r}")
        expect("unmentioned: 0" in out, f"nothing is unmentioned here: {out!r}")
        # Mentioned nowhere -> silent disappearance -> exit 1.
        write_journal(carry, written,
                      journal_entry("2026-10-22T00:00:00Z", "carry_proj",
                                    run_id="20261022-33334444", factory_version="12.9.0",
                                    marks=True))
        csres = run("backlog", "--repo", str(carry), "--check")
        expect(csres.returncode == 1, "an item mentioned nowhere must fail --check")
        expect("carried debt item" in csres.stderr,
               f"the disappeared item must be named: {csres.stderr!r}")
        expect("unmentioned: 1" in run("backlog", "--repo", str(carry)).stdout,
               "the unmentioned count must be printed")
        # Re-declared WITHOUT a reason -> exit 1.
        write_journal(carry, written, journal_entry(
            "2026-10-23T00:00:00Z", "carry_proj", run_id="20261023-44445555",
            factory_version="12.9.0", marks=True,
            unfinished="unfinished:\n  - item: carried debt item\n"
                       "    severity: critical\n    follow_up: false\n"))
        res = run("backlog", "--repo", str(carry), "--check")
        expect(res.returncode == 1, "a carried item without a reason must fail --check")
        expect("carried debt item" in res.stderr and "reason" in res.stderr,
               f"the reasonless carried item must be named: {res.stderr!r}")
        # `--run-id` picks the current record instead of the last one in file order.
        write_journal(carry, written, journal_entry(
            "2026-10-24T00:00:00Z", "carry_proj", run_id="20261024-55556666",
            factory_version="12.9.0", marks=True))
        expect(run("backlog", "--repo", str(carry), "--check").returncode == 1,
               "the last record does not mention the item, so --check must fail")
        expect(run("backlog", "--repo", str(carry), "--check",
                   "--run-id", "20261020-11112233").returncode == 0,
               "--run-id must select the record carrying the reason")

        # 30. `## Current state` actuality: the open/closed/test counts it claims are compared with
        #     the live state — a WARN on an ordinary check, an ERROR under --strict / --run-id.
        act = tmp / "actual_proj"
        act.mkdir()
        expect(run("init", "--repo", str(act)).returncode == 0,
               "init of the actuality fixture must exit 0")
        (act / "VERSION").write_text("12.10.2\n", encoding="utf-8")
        write_journal(act, journal_entry(
            "2026-10-30T00:00:00Z", "actual_proj", run_id="20261030-aaaabbbb",
            factory_version="12.9.0", marks=True,
            unfinished=unfinished_block(("open actuality item", "critical", "false"))))
        a_sum = act / "memory" / "summary.md"
        a_sum.write_text(a_sum.read_text(encoding="utf-8").replace(
            "## Current state",
            "## Current state\nFactory v12.10.2: current.\nOpen backlog: 0 items (0 closed).\n"
            "Self-tests: 0 files."), encoding="utf-8")
        res = run("check", "--repo", str(act))
        expect(res.returncode == 0, f"a divergence must only WARN on a plain check: {res.stderr!r}")
        expect("WARN" in res.stderr and "open backlog" in res.stderr,
               f"the stale open count must be warned about: {res.stderr!r}")
        res = run("check", "--repo", str(act), "--strict")
        expect(res.returncode == 1, "--strict must turn the divergence into an error")
        expect("FAIL" in res.stderr and "open backlog" in res.stderr,
               f"the strict failure must name the stale fact: {res.stderr!r}")
        expect(run("check", "--repo", str(act), "--run-id", "20261030-aaaabbbb").returncode == 1,
               "--run-id must imply --strict")
        # A stale test-file count is a divergence too.
        a_sum.write_text(a_sum.read_text(encoding="utf-8").replace(
            "Open backlog: 0 items (0 closed).", "Open backlog: 1 item (0 closed).").replace(
            "Self-tests: 0 files.", "Self-tests: 7 files."), encoding="utf-8")
        res = run("check", "--repo", str(act))
        expect(res.returncode == 0, "the test-count divergence must stay a warning")
        expect("test files" in res.stderr, f"the test-count divergence must be named: {res.stderr!r}")
        # An actual `## Current state` is silent — and `backlog --check` is actual too (the single
        # record carries its own item with a reason).
        a_sum.write_text(a_sum.read_text(encoding="utf-8").replace(
            "Self-tests: 7 files.", "Self-tests: 0 files."), encoding="utf-8")
        res = run("check", "--repo", str(act), "--strict")
        expect(res.returncode == 0, f"an actual `## Current state` must pass --strict: {res.stderr!r}")
        expect("WARN" not in res.stderr, f"an actual summary must not warn: {res.stderr!r}")
        expect(run("backlog", "--repo", str(act), "--check").returncode == 0,
               "the actuality fixture must also pass the backlog gate")

        # 31. A compaction must never turn a VALID memory into an INVALID one. The fixture is the
        #     smallest shape that carries both halves of the defect: record 1 declares two
        #     follow_up items, record 2 CLOSES one of them with evidence (both leave the journal),
        #     record 3 closes the other one (it stays). Before the fold every gate is green; after
        #     it the closure of record 3 must still find its declaration (now in `## Carried debt`)
        #     and the folded evidence must survive in `## Closed with evidence`, verbatim.
        fold = tmp / "compact_closed"
        fold.mkdir()
        expect(run("init", "--repo", str(fold)).returncode == 0,
               "init of the folded-closure fixture must exit 0")
        kept_evidence = "tests/test_kept.py:7 -> exit 0"
        folded_evidence = "scripts/test_folded.py:12 -> exit 0"
        write_journal(
            fold,
            journal_entry("2026-11-01T00:00:00Z", "compact_closed", run_id="20261101-11112233",
                          factory_version="12.9.0", marks=True,
                          unfinished=unfinished_block(("debt closed later", "critical", "true"),
                                                      ("debt closed in the fold", "info", "true"))),
            journal_entry("2026-11-02T00:00:00Z", "compact_closed", run_id="20261102-22223333",
                          factory_version="12.9.0", marks=True,
                          closed=closed_block(("debt closed in the fold", folded_evidence))),
            journal_entry("2026-11-03T00:00:00Z", "compact_closed", run_id="20261103-33334444",
                          factory_version="12.9.0", marks=True,
                          closed=closed_block(("debt closed later", kept_evidence))))
        f_clog = fold / "memory" / "change-log.md"
        f_sum = fold / "memory" / "summary.md"
        res = run("check", "--repo", str(fold))
        expect(res.returncode == 0, f"the folded-closure fixture must be valid before the fold: "
                                    f"{res.stderr!r}")
        res = run("backlog", "--repo", str(fold), "--check")
        expect(res.returncode == 0,
               f"the folded-closure fixture must pass backlog --check before the fold: {res.stderr!r}")
        res = run("compact", "--repo", str(fold), "--threshold", "1", "--keep", "1")
        expect(res.returncode == 0, f"the fold of the closed items must exit 0: {res.stderr!r}")
        f_clog_after = f_clog.read_text(encoding="utf-8")
        f_sum_after = f_sum.read_text(encoding="utf-8")
        # The defect: the KEPT record closes an item the fold carried away. `check` must stay green
        # — the declaration now lives in `## Carried debt`, which is read back as a folded record.
        res = run("check", "--repo", str(fold))
        expect(res.returncode == 0,
               f"the compaction must not invalidate the kept closure: {res.stderr!r}")
        expect("matches no" not in res.stderr,
               f"the kept closure must match its folded declaration: {res.stderr!r}")
        res = run("backlog", "--repo", str(fold), "--check")
        expect(res.returncode == 0,
               f"the compacted memory must still pass backlog --check: {res.stderr!r}")
        # The folded debt and the folded PROOF are both in the summary, the evidence verbatim.
        expect("## Carried debt" in f_sum_after and "## Closed with evidence" in f_sum_after,
               f"the summary must carry both fold sections: {f_sum_after!r}")
        expect("debt closed later" in f_sum_after,
               f"the folded declaration must stay visible in the summary: {f_sum_after!r}")
        expect("debt closed in the fold" in f_sum_after,
               f"the folded closure must name its item: {f_sum_after!r}")
        expect(folded_evidence in f_sum_after,
               f"the folded evidence must survive VERBATIM in the summary: {f_sum_after!r}")
        expect(folded_evidence not in f_clog_after,
               f"the folded record must have left the journal: {f_clog_after!r}")
        # The fold is recognised as a folded record: its closure is counted and named.
        payload = json.loads(run("backlog", "--repo", str(fold), "--json").stdout)
        expect(payload["open"] == 0, f"both closures are proven, so nothing stays open: {payload!r}")
        expect(payload["closed_in_summary"] == 1,
               f"the folded closure must be exposed by --json: {payload!r}")
        expect(payload["closed"] == 2,
               f"the closed count must stay truthful across the fold: {payload!r}")
        expect(payload["errors"] == [], f"the compacted memory must carry no error: {payload!r}")
        # A second fold changes nothing: the journal is under the threshold and the summary's
        # closure section is not rewritten (its age was computed when it was folded).
        snapshot = (f_clog.read_bytes(), f_sum.read_bytes())
        res = run("compact", "--repo", str(fold), "--threshold", "1", "--keep", "1")
        expect(res.returncode == 0, f"the repeated fold must exit 0: {res.stderr!r}")
        expect("nothing to compact" in res.stdout,
               f"the repeated fold must report the idle state: {res.stdout!r}")
        expect((f_clog.read_bytes(), f_sum.read_bytes()) == snapshot,
               "a second compact must leave the journal AND the summary byte-identical")

        # 32. TWO folds with ordinary records in between. `## Carried debt` is REPLACED on every
        #     fold while `## Closed with evidence` ACCUMULATES, so a later fold that finds no open
        #     debt used to rewrite the debt to `- none` and orphan the closure the earlier fold
        #     recorded (`closed item '<text>' matches no follow_up/critical item of the journal`) —
        #     after `compact` had already exited 0 and written both files. A closure is itself the
        #     declaration that the item existed and was open, so the folded record must keep it
        #     declared and BOTH gates must stay green after each fold.
        two = tmp / "compact_twice"
        two.mkdir()
        expect(run("init", "--repo", str(two)).returncode == 0,
               "init of the two-fold fixture must exit 0")
        t_clog = two / "memory" / "change-log.md"
        t_sum = two / "memory" / "summary.md"
        twice_item = "debt closed before the second fold"
        twice_evidence = "scripts/test_two_folds.py:21 -> exit 0"
        write_journal(
            two,
            journal_entry("2026-12-01T00:00:00Z", "compact_twice", run_id="20261201-11112233",
                          factory_version="12.9.0", marks=True,
                          unfinished=unfinished_block((twice_item, "critical", "true"))),
            journal_entry("2026-12-02T00:00:00Z", "compact_twice", run_id="20261202-22223333",
                          factory_version="12.9.0", marks=True,
                          closed=closed_block((twice_item, twice_evidence))),
            journal_entry("2026-12-03T00:00:00Z", "compact_twice", run_id="20261203-33334444",
                          factory_version="12.9.0", marks=True))
        res = run("compact", "--repo", str(two), "--threshold", "1", "--keep", "1")
        expect(res.returncode == 0, f"fold #1 must exit 0: {res.stderr!r}")
        for gate in (("check", "--repo", str(two)),
                     ("backlog", "--repo", str(two), "--check")):
            res = run(*gate)
            expect(res.returncode == 0,
                   f"fold #1 must leave `{gate[0]}` green: {res.stdout!r} {res.stderr!r}")
            expect("matches no" not in res.stderr,
                   f"fold #1 must not orphan the closure: {res.stderr!r}")
        expect(twice_evidence in t_sum.read_text(encoding="utf-8"),
               "fold #1 must keep the closure's evidence in the summary")
        # Three ORDINARY records in between, then a fold whose records carry no open debt: this is
        # the shape that rewrote `## Carried debt` to `- none` and orphaned the closure of fold #1.
        t_clog.write_text(t_clog.read_text(encoding="utf-8") + "".join(
            journal_entry(f"2026-12-{day:02d}T00:00:00Z", "compact_twice",
                          run_id=f"202612{day:02d}-4444555{day}",
                          factory_version="12.9.0", marks=True) for day in (4, 5, 6)),
            encoding="utf-8")
        res = run("compact", "--repo", str(two), "--threshold", "2", "--keep", "1")
        expect(res.returncode == 0, f"fold #2 must exit 0: {res.stderr!r}")
        for gate in (("check", "--repo", str(two)),
                     ("backlog", "--repo", str(two), "--check")):
            res = run(*gate)
            expect(res.returncode == 0,
                   f"fold #2 must leave `{gate[0]}` green: {res.stdout!r} {res.stderr!r}")
            expect("matches no" not in res.stderr,
                   f"fold #2 must not orphan the closure: {res.stderr!r}")
        sum_twice = t_sum.read_text(encoding="utf-8")
        expect("## Carried debt" in sum_twice and "## Closed with evidence" in sum_twice,
               f"the summary must keep both fold sections: {sum_twice!r}")
        expect(twice_evidence in sum_twice,
               f"fold #2 must keep the earlier closure's evidence: {sum_twice!r}")
        payload = json.loads(run("backlog", "--repo", str(two), "--json").stdout)
        expect(payload["open"] == 0,
               f"the folded closure must stay closed, not reappear as debt: {payload!r}")
        expect(payload["closed"] == 1 and payload["closed_in_summary"] == 1,
               f"the closure must be counted exactly once (no double count): {payload!r}")
        expect(payload["errors"] == [], f"the two folds must leave no error: {payload!r}")
        # A third fold has nothing to do and changes no byte of either file.
        snapshot = (t_clog.read_bytes(), t_sum.read_bytes())
        res = run("compact", "--repo", str(two), "--threshold", "2", "--keep", "1")
        expect(res.returncode == 0, f"fold #3 must exit 0: {res.stderr!r}")
        expect("nothing to compact" in res.stdout,
               f"fold #3 must report the idle state: {res.stdout!r}")
        expect((t_clog.read_bytes(), t_sum.read_bytes()) == snapshot,
               "a third compact must leave the journal AND the summary byte-identical")

        # 33. The pre-write verification is SEMANTIC, not a substring test: here the fold deletes
        #     the ONLY declaration of an item a KEPT `closed:` element closes (the item is warning
        #     debt, so the fold does not carry it), and a substring test does not notice — the item
        #     text survives inside the closure bullet itself. The pair already reports that orphan;
        #     the point is that a compaction must never WRITE a memory that reports a
        #     closing-protocol error (the old code wrote it and exited 0).
        orphan = tmp / "compact_orphan"
        orphan.mkdir()
        expect(run("init", "--repo", str(orphan)).returncode == 0,
               "init of the orphan fixture must exit 0")
        orphan_item = "warning debt closed after the fold"
        write_journal(
            orphan,
            journal_entry("2026-12-10T00:00:00Z", "compact_orphan", run_id="20261210-11112233",
                          factory_version="12.9.0", marks=True,
                          unfinished=unfinished_block((orphan_item, "warning", "false"))),
            journal_entry("2026-12-11T00:00:00Z", "compact_orphan", run_id="20261211-22223333",
                          factory_version="12.9.0", marks=True),
            journal_entry("2026-12-12T00:00:00Z", "compact_orphan", run_id="20261212-33334444",
                          factory_version="12.9.0", marks=True,
                          closed=closed_block((orphan_item, "log/orphan:1 -> exit 0"))))
        o_clog = orphan / "memory" / "change-log.md"
        o_sum = orphan / "memory" / "summary.md"
        before_pair = (o_clog.read_bytes(), o_sum.read_bytes())
        res = run("compact", "--repo", str(orphan), "--threshold", "1", "--keep", "1")
        expect(res.returncode == 1,
               f"a fold that would orphan a closure must be refused: {res.stdout!r} {res.stderr!r}")
        expect("FAIL - compaction would invalidate the memory:" in res.stderr,
               f"the refusal must name the semantic reason: {res.stderr!r}")
        expect("matches no" in res.stderr,
               f"the refusal must carry the closing-protocol error: {res.stderr!r}")
        expect((o_clog.read_bytes(), o_sum.read_bytes()) == before_pair,
               "a refused compaction must write nothing (both files byte-identical)")
        res = run("backlog", "--repo", str(orphan), "--check")
        expect(res.returncode == 1 and orphan_item in res.stderr,
               f"the refused fold must leave the orphan visible, not silently repaired: "
               f"{res.stderr!r}")

    print("PASS - memory_project.py behaves as expected (init creates once, never rewrites and "
          "pins the repository identity; check enforces one owner/repository — the identity, not "
          "the folder name — fails on mixed/mismatched/foreign memory, on a duplicated run_id, on "
          "check --run-id without exactly one record and on memory/ without its journal, and turns "
          "a stale `## Current state` into a warning or, under --strict, an error; rename rewrites "
          "the owner and is idempotent; compact folds the journal into the summary, keeps every "
          "critical/follow_up item byte-identically and carries the evidence of every folded "
          "closure so a kept `closed:` element still finds its declaration, survives a SECOND fold "
          "that resets `## Carried debt`, and refuses to write a result that would report a "
          "closing-protocol error; compact-check keeps critical/follow_up items; "
          "backlog folds the journal into the open items — carried only with a `reason:`, closed "
          "only by a `closed:` element with `evidence:`, never able to disappear silently — and "
          "warns on a stale summary version; validate-fix-tasks checks the fix-task schema "
          "(including the mandatory repo_path); the "
          "memory format v2 requires run_id + provenance marks + unfinished/factory_version on "
          "current-generation records and "
          "only warns on pre-v2 ones; an unverifiable project_id never becomes the identity).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Project-scoped long-term memory helper for the Code Factory (stdlib only, zero LLM tokens).

`memory/` is the durable memory of ONE target project — the project named by the
`repo_path` field of the task, NOT the factory itself. These subcommands make that
ownership explicit and machine-checkable:

  name  --repo <path>            print the project name = basename of the resolved path.
  init  --repo <deploy_root>     create memory/change-log.md and memory/summary.md from the
                                 canonical templates, but ONLY if they are missing; existing
                                 files are never overwritten or modified, not even partially.
                                 The summary declares `project_id:` — the repository identity,
                                 see project_identity() — right after its `repo_path:` line.
  check --repo <deploy_root>     verify that memory belongs to exactly one project AND that it
                                 is the memory of THIS repository. The whole contract lives in
                                 ONE public implementation, `validate_memory(root, expect,
                                 no_owner_check, strict, run_id)` -> (errors, warnings);
                                 `scripts/check_factory_model.py` delegates to it, so the two
                                 CLIs cannot disagree about the memory format. `check` prints
                                 exactly that tuple (`FAIL - …`, `WARN - …`, `ok - …`, exit 1 iff
                                 errors). The owner comes from a chain (see expected_owner):
                                 `--expect <name>` wins; else the summary's
                                 `project_id:` — a repository identity, so a renamed or
                                 versioned deployment folder does NOT invalidate memory nobody
                                 edited, while a DIFFERENT id is refused as a foreign
                                 repository; else the basename of the declared `repo_path:`; else
                                 the basename of `--repo`, with a warning that the identity
                                 basis is the directory name. A memory without `project_id:`
                                 keeps exactly that name-based rule plus a migration hint —
                                 nothing gets greener by accident. On top of the owner: the
                                 journal's `project:` values must agree with each other and with
                                 the summary declaration (always an error otherwise); a `run_id`
                                 may appear in ONE record only (one run — one record), and
                                 `--run-id <id>` additionally requires EXACTLY one record
                                 carrying that run id (implied by the Finish gate). A fresh
                                 project — no `memory/` at all — is a note and exit 0, while a
                                 `memory/` WITHOUT `change-log.md` is an error unless
                                 `--allow-fresh` declares the absence deliberate.
                                 `--no-owner-check` drops only the owner comparison. Legacy
                                 memory without a `project:` declaration stays a warning, never an
                                 error. The memory format v2 (see change_log_template) is enforced
                                 on the records of a current-generation factory: they must carry a
                                 well-formed `run_id` AND a provenance mark in `decisions` and in
                                 `results`; records that predate the format — with a `project:`
                                 but not v2 — only warn (never rewritten, a warning by contract),
                                 exactly like records without `project:`.
                                 The `## Current state` of the summary is compared with the live
                                 state (see summary_state_warnings): warnings on `check`, ERRORS
                                 under `--strict` (implied by `--run-id`), so the Finish gate can
                                 enforce actuality while an ordinary check stays informative.
  rename --repo <path> --to <n>  deterministically rewrite the `project:` field of every
                                 journal record and the `project:` declaration of the summary
                                 to <n> (atomic, idempotent: a second run changes nothing and
                                 reports 0 rewritten records). Records without the field stay
                                 legacy; `project:` examples inside the templates' fenced code
                                 blocks are never touched.
  backlog --repo <root>          fold the WHOLE journal into the set of items that are still open:
                                 every `unfinished` item with severity=critical or follow_up=true,
                                 in file order, minus the items closed by a `closed:` block of any
                                 record (matched by the normalized `item` text, whitespace
                                 collapsed and case-insensitive); a record closes an item with
                                 `- item: <text>` + the mandatory `evidence: <command/log/
                                 file:line>`. Each open item is printed with its source record
                                 (timestamp + factory_version): an item left open by a record that
                                 carries no `closed:` block at all is legacy drift — history that
                                 was never reconciled. `--json` prints the report machine-readably.
                                 The CURRENT record is the one whose `run_id` equals `--run-id`,
                                 else the last record in file order; the report counts `carried`
                                 (open items re-declared there with a non-empty `reason:`) and
                                 `unmentioned` (open items that record does not mention at all).
                                 `--check` exits 0 iff `unmentioned == 0` and every `closed:`
                                 element is valid — so the Finish node can accept a carried-over
                                 debt (an item in `unfinished` with a reason) while a debt that
                                 silently disappeared still fails: an open item mentioned nowhere,
                                 a carried item without `reason:`, a `closed:` element without
                                 `evidence:` or naming an item that no record ever declared open
                                 all exit 1. The validation of the `closed:` blocks runs always,
                                 on any record. The two sections `compact` writes into the summary —
                                 `## Carried debt` and `## Closed with evidence` — are read back as
                                 a synthetic FOLDED RECORD that precedes the journal (see
                                 folded_summary_record): the debt the fold carried stays visible as
                                 open debt, a closure that stayed in the journal still matches a
                                 declaration the fold carried away, and the closures the fold carried
                                 away stay counted (`closed` includes them exactly once,
                                 `closed_in_summary` names the folded part). A `closed:` element is
                                 ALSO a declaration — it proves the item existed and was open — so an
                                 item only a `## Closed with evidence` bullet names is declared and
                                 closed by that same folded record: a later fold that rewrites
                                 `## Carried debt` to `- none` can never orphan a recorded closure.
  compact --repo <root> [--threshold 50] [--keep 20] [--dry-run]
                                 implement the 50/20 rule in code instead of in prose: read the
                                 journal raw (line endings preserved), split it at the dated `## `
                                 headings, keep the header verbatim; while `records <= threshold`
                                 print `ok - nothing to compact (<n>/<threshold>)` and write no
                                 byte (idempotent). Otherwise fold `records[:-keep]` into
                                 memory/summary.md — a `## Recent history` section (one bullet per
                                 folded record: timestamp, short title, run_id, closed count), a
                                 `## Carried debt` section listing EVERY item
                                 must_survive_compaction() requires (item, reason, severity,
                                 follow_up, source timestamp) and a `## Closed with evidence` section
                                 with one bullet per folded `closed:` element (how long ago it was
                                 closed, the item, its VERBATIM evidence, the source timestamp),
                                 because dropping the proof of a closure would leave a closure
                                 without evidence — an invalid memory. The closures ACCUMULATE (the
                                 bullets of an earlier fold stay byte-identical; only the debt is
                                 rewritten), and an item a bullet names is declared by the folded
                                 record, so the accumulating section can never orphan itself.
                                 The result is verified in memory BEFORE writing: (1) the
                                 critical/follow_up items must survive byte-identically, and (2) the
                                 would-be journal + summary are fed through the SAME fold `check` and
                                 `backlog --check` use — a result that would report any
                                 closing-protocol error (`FAIL - compaction would invalidate the
                                 memory: <first error>`) exits 1 without writing a byte, because a
                                 substring test cannot see an orphaned closure (the item text is
                                 still inside the closure bullet itself). A folded `closed:` element
                                 without `evidence:` is refused the same way (an invalid closure is
                                 never laundered into a valid-looking bullet). `--dry-run` prints the
                                 plan and writes nothing.

  compact-check --before <f> --after <f>
                                 verify that every unfinished item with severity=critical or
                                 follow_up=true of <f> is still present in the compacted <f>
                                 (matched by the `item` field); every dropped item is an error.
  validate-fix-tasks <file>      validate the fix-task file generated by a security_audit run
                                 (see references/security-audit.md): a YAML list of tasks, each
                                 carrying the required factory-task fields. A schema violation
                                 is an error naming the offending line.

The templates carry the canonical markers required by scripts/check_factory_model.py and
declare `project: <name>`; `check` falls back to that declaration while the journal has no
records yet, so a fresh memory is never mistaken for a legacy one. `<name>` defaults to the
basename of the resolved deploy root; `init --project <name>` overrides it, e.g. when the
task's `repo_path` points to a SUBDIRECTORY of the deploy root — memory/ still lives in the
deploy root, but the project is named after that subdirectory. The summary's `project_id:` is the
repository's own identity (`project_identity`), never the folder name: that is what keeps a
renamed or versioned deployment copy from invalidating memory nobody edited.

Canon of the closing protocol (see the change-log template): an unfinished item NEVER disappears
silently. It is either carried as debt with its reason in the CURRENT record, or closed by a
`closed:` element whose `evidence:` names a real proof (command, test, log, `file:line`); a
`closed:` element without evidence does not close anything, and `backlog --check` fails on it,
exactly as it fails on an open item that no current record mentions. So `unmentioned: 0` and
valid closures are the only accepted state, and every historical item that was never closed shows
up as legacy drift.

RECORD KINDS (decided once, in `RECORD_KINDS`): a memory record's `task_type` is one of
`implement | review | refactor | security_audit | backlog`. `backlog` is a legitimate record kind
— it records the discovery of a defect that has no run yet (the factory itself writes such a
record), so instead of the four run sub-keys it declares
`results: finding=<what was found>; impact=<why it matters>`, each with a provenance mark, while
`implement`/`review`/`refactor`/`security_audit` keep
`integration=`/`regression=`/`business=`/`review=`. This WIDENS the documented format to cover a
record kind the factory already writes; it does NOT soften the format gate, because an unknown
kind (`patch`, `hotfix`, …) is still an error, and the v2 gate (run_id + provenance marks) applies
to every kind alike. The records already in the journal stay legal UNCHANGED — history is never
rewritten. Both validators apply this one rule (`validate_memory`), so a record kind cannot be
accepted by one CLI and rejected by the other.

A MISSING journal means two DIFFERENT things and both CLIs say which one they reported: for
`memory_project.py check` a `memory/` that does not exist at all is a FRESH project (a note,
exit 0), whereas a `memory/` WITHOUT `change-log.md` is a BROKEN memory (exit 1, `--allow-fresh`
overrides). For `check_factory_model.py` — the gate of a project that already has a modelled
AGENTS.md, i.e. one the factory has worked in — a missing journal stays a hard error. The shared
`validate_memory` reports it as an error; only the `memory_project.py` CLI decides the fresh case.

Exit codes: 0 = OK, 1 = FAIL (memory mixes projects, belongs to an unexpected or a foreign
repository, a record violates the record contract — a missing required key, an unknown
`task_type`, a missing `results` sub-key of the record's kind, an empty `project:` value, an
incomplete `unfinished` item — or the memory format v2, one run_id in two records,
`check --run-id` without exactly one such record, a `closed:` element without `evidence:` or
naming an unknown item, an open item re-declared without a `reason:`, `memory/` without
`change-log.md` without `--allow-fresh`, a `## Current state` divergence under `--strict`,
compaction would drop a critical/follow_up item, `backlog --check` found a silently disappeared
item, or a fix-task file violates its schema). This script imports nothing from the factory: it
runs from anywhere, and `scripts/check_factory_model.py` imports THIS one instead of duplicating
the contract.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
ENTRY_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}")
# Top-level `key: value` field; lines starting with indentation (unfinished items) never match.
FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
# One `unfinished` item and its sub-fields (indented under `unfinished:`).
ITEM_RE = re.compile(r"^\s*-\s*item:\s*(.*)$")
ITEM_FIELD_RE = re.compile(r"^\s*(reason|severity|follow_up|source):\s*(.*)$")
# Item blocks of a record body: `unfinished` (the debt) and `closed` (the closing protocol).
ITEM_SECTIONS = ("unfinished", "closed")
# The sub-field of a `closed:` element: the mandatory proof of the closure.
CLOSED_FIELD_RE = re.compile(r"^\s*(evidence):\s*(.*)$")
# `## Current state` of memory/summary.md and the factory version it claims as current.
SUMMARY_STATE_HEADING = "## Current state"
CLAIMED_VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b")
# The facts `## Current state` declares about the live state (see summary_state_warnings):
# `open backlog: <n>`, `<n> closed`, `<n> test files` / `<n> self-tests` (and the short
# `self-tests: <n>` form of a count column).
STATE_OPEN_BACKLOG_RE = re.compile(r"open backlog:\s*(\d+)", re.IGNORECASE)
STATE_CLOSED_RE = re.compile(r"\b(\d+)\s+closed\b", re.IGNORECASE)
STATE_TEST_FILES_RE = re.compile(r"\b(\d+)\s+(?:test files|self-tests)\b", re.IGNORECASE)
STATE_TEST_FILES_COLUMN_RE = re.compile(r"self-tests:\s*(\d+)", re.IGNORECASE)
# Directories never scanned when the declared test-file count is compared with the tree.
TEST_COUNT_PRUNE = (".code-factory", ".git", "backups")
# The `project_id:` declaration: the first 12 hex characters of sha256 over the root commit.
PROJECT_ID_LEN = 12
# Sections `compact` writes into memory/summary.md (see cmd_compact).
RECENT_HISTORY_HEADING = "## Recent history"
CARRIED_DEBT_HEADING = "## Carried debt"
# Every `closed:` element of a folded record, with its verbatim `evidence:` (see cmd_compact): the
# proof of a folded debt must survive the fold, so it is written out instead of a bare count.
CLOSED_WITH_EVIDENCE_HEADING = "## Closed with evidence"
# The two summary sections that stand in for the records folded out of the journal, in the order
# `backlog_report_text` reads them back (see folded_summary_record).
FOLDED_SECTIONS = (CARRIED_DEBT_HEADING, CLOSED_WITH_EVIDENCE_HEADING)
# The heading of the synthetic "folded record" those sections declare — a date-shaped heading, so
# the very parser that reads the journal (`journal_blocks_text`) reads the summary sections too.
FOLDED_HEADING = "## 0000-00-00 — folded records of memory/summary.md"
# One `## Closed with evidence` bullet: how long ago it was closed, the item, its VERBATIM evidence
# and the source record's timestamp. Read back by parse_closure_bullets().
CLOSURE_BULLET_RE = re.compile(
    r"^-\s+(?P<age>[^:]+):\s+closed\s+'(?P<item>.*)'\s+\u2014\s+evidence:\s+(?P<evidence>.*?)"
    r"\s+\[source:\s+(?P<source>[^\]]+)\]$")
# The placeholder of a section that has nothing to list yet (`## Carried debt`, `## Closed …`).
SECTION_NONE = "- none"
# The ISO date part of a record timestamp, used to say how long ago a closure was folded.
STAMP_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
# How much of a record title a compacted history bullet keeps.
HISTORY_TITLE_LIMIT = 120
# The YAML subset of a generated fix-task file: `- title:` starts a task, indented `key:`
# lines are its fields, indented `- value` lines are the items of the current field.
FIX_TASK_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<val>.*)$")
FIX_FIELD_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<val>.*)$")
FIX_LIST_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<val>.*)$")

# Memory format v2 (introduced after factory 12.8.0): `run_id` (see scripts/run_id.py) and a
# provenance mark — `[verified: <evidence>]` or `[inferred]` — in `decisions` and `results`.
# A record must carry them once it comes from a factory NEWER than MEMORY_V2_AFTER, or as soon
# as it already carries one of the v2 fields (so a half-migrated record is caught as well).
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
# A one-time, owner-authorized legacy migration backfills a synthetic run_id/factory_version:
# the canonical value plus the annotation ` (synthetic, backfilled YYYY-MM-DD)`. The annotation
# is stripped before validation, so the migrated history is valid without being rewritten.
SYNTHETIC_SUFFIX_RE = re.compile(r" \(synthetic, backfilled \d{4}-\d{2}-\d{2}\)$")


def unsynth(value: str) -> str:
    """The canonical value without a ` (synthetic, backfilled ...)` migration annotation."""
    return SYNTHETIC_SUFFIX_RE.sub("", value)
PROVENANCE_RE = re.compile(r"\[verified:[^\[\]]+\]|\[inferred\]")
MEMORY_V2_AFTER = (12, 8, 0)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

LEGACY_NO_PROJECT = "(legacy, no project field)"
# Task types of the factory task format (see references/security-audit.md, section 4).
TASK_TYPES = ("implement", "review", "refactor", "security_audit")
# Required by every generated fix task, per references/security-audit.md, section 4.
FIX_TASK_REQUIRED = ("title", "description", "task_type", "acceptance_criteria")

# RECORD KINDS — the `task_type` of a memory record, decided ONCE here (used by
# `record_contract_issues`, documented in the change-log template and in this docstring).
# `backlog` is a legitimate record kind: it records the DISCOVERY of a defect that has no run yet
# (the factory itself writes such a record), so it declares `results: finding=<what was found>;
# impact=<why it matters>` instead of the four run sub-keys. An unknown kind is still an error —
# the enum WIDENS the documented format, it never softens the format-v2 gate.
RECORD_KINDS = ("implement", "review", "refactor", "security_audit", "backlog")
# `results` sub-keys: of a RUN record (implement/review/refactor/security_audit)...
RESULT_KEYS_RUN = ("integration", "regression", "business", "review")
# ...and of a `backlog` record, which has no run to report (a defect without a run).
RESULT_KEYS_BACKLOG = ("finding", "impact")
# Keys every journal record must carry; a missing newer key (the last three) only WARNS, so the
# history written before the format evolved stays valid.
ENTRY_REQUIRED_KEYS = ("title", "timestamp", "branch", "commit", "task_type", "goal",
                       "changed_files", "created_files", "results", "decisions", "assumptions",
                       "models_used")
ENTRY_OPTIONAL_KEYS = ("unfinished", "factory_version", "project")
# Enums of an `unfinished` item (see the change-log template).
UNFINISHED_SEVERITIES = ("critical", "warning", "info")
UNFINISHED_BOOLS = ("true", "false")
# The `timestamp:` of a record must be ISO-date-like (same rule as the WIP checkpoint validator).
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Prefix of the owner-mismatch error, so a CLI can print the two legitimate fixes next to it
# (see owner_hints) without re-parsing the message.
OWNER_MISMATCH = "memory belongs to project"


def project_name(repo: str | pathlib.Path) -> str:
    """Return the project name: basename of the resolved path."""
    return pathlib.Path(repo).resolve().name


def project_identity(root: str | pathlib.Path) -> str:
    """Return the repository identity of `root`: 12 hex chars of sha256 over its root commit.

    The identity is derived from the repository's own history — `git rev-list --max-parents=0
    HEAD`, whose last non-empty line is the root commit — and NEVER from the folder name, so a
    renamed or versioned copy of the deployment directory keeps its memory valid although nobody
    edited it. Returns "" when git is unavailable, `root` is not a git repository or its history
    is empty; the caller then falls back to the documented name-based basis. Nothing is cached on
    disk: the value must follow the repository, not a stale file.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-list", "--max-parents=0", "HEAD"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""                                   # no git on PATH, or an unusable invocation
    if proc.returncode != 0:
        return ""                                   # not a git repository, or an empty history
    roots = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not roots:
        return ""
    return hashlib.sha256(roots[-1].encode("utf-8")).hexdigest()[:PROJECT_ID_LEN]


def declaration_value(summary: pathlib.Path, key: str) -> str:
    """Value of `<key>:` in the declaration area of memory/summary.md ("" when it declares none).

    Only the declaration area counts — right after the canonical marker and before the first
    `## ` section — so a `key: value` example inside a fenced code block is never mistaken for a
    declaration (same rule as scripts/check_factory_model.py).
    """
    if not summary.is_file():
        return ""
    lines = summary.read_text(encoding="utf-8").splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if SUMMARY_MARKER in ln), None)
    if start is None:
        return ""
    for line in lines[start:]:
        if line.startswith("## "):
            break
        m = FIELD_RE.match(line)
        if m and m.group(1) == key:
            return m.group(2).strip()
    return ""


def summary_project_id(summary: pathlib.Path) -> str:
    """The `project_id:` declared by memory/summary.md ("" when absent or empty)."""
    return declaration_value(summary, "project_id")


def expected_owner(root: pathlib.Path, expect: str = "",
                   no_owner_check: bool = False) -> tuple[str, str, list[str]]:
    """Return (expected_owner, basis, warnings) — the owner the memory under `root` may carry.

    Precedence, in this order:
      "expect"             `--expect <name>` wins over everything else;
      "no-owner-check"     `--no-owner-check` drops the owner comparison — and nothing else;
      "foreign-repository" the summary's `project_id:` names ANOTHER repository: the memory is
                           refused (the caller turns this basis into a hard error naming both ids);
      "identity"           the declared `project_id:` matches this repository, so the memory's own
                           `project:` declaration is the owner — no name-based comparison at all;
      "summary-repo-path"  no `project_id:` — the basename of the declared `repo_path:` line (a
                           memory that pins its own root keeps working, like before);
      "repo-dir"           nothing usable declared — the basename of `--repo`, with a warning that
                           the identity basis is the directory name (the fallback stays so nothing
                           passes by accident).
    A memory without `project_id:` keeps exactly the pre-identity, name-based rule and gets a
    migration hint; `warnings` carries those hints and never a "WARN" line.
    """
    if expect:
        return expect.strip(), "expect", []
    if no_owner_check:
        return "", "no-owner-check", []
    summary = root / "memory" / "summary.md"
    declared_id = summary_project_id(summary)
    computed = project_identity(root)
    if declared_id:
        if computed and computed != declared_id:
            return "", "foreign-repository", [
                f"hint: memory/summary.md declares project_id {declared_id} while this "
                f"repository's root commit gives {computed}"]
        return summary_project(summary), "identity", []
    basis, owner = "repo-dir", root.name
    declared_repo = declaration_value(summary, "repo_path")
    if declared_repo and declared_repo != ".":
        basis, owner = "summary-repo-path", pathlib.Path(declared_repo).name
    warnings: list[str] = []
    if basis == "repo-dir":
        warnings.append(
            f"hint: the identity basis is the directory name '{owner}' (no 'project_id:' and no "
            f"declared 'repo_path:' in memory/summary.md) - renaming or re-versioning the "
            f"deployment folder invalidates memory nobody edited")
    warnings.append(
        f"hint: memory/summary.md declares no 'project_id:' - pin the repository identity with "
        f"'memory_project.py init' or with a documented edit of the declaration area "
        f"('project_id: {computed or '<12 hex>'}')")
    return owner, basis, warnings


def owner_hints(repo: pathlib.Path, owner: str, expected: str) -> list[str]:
    """Fix suggestions printed next to an owner mismatch (see the module docstring).

    Two legitimate cases exist: the memory was migrated from another deployment directory
    (fix it with `rename`), or the project name is intentionally the basename of a
    SUBDIRECTORY of the deploy root (then `--expect <name>` / `--no-owner-check` are correct).
    """
    return [
        "hint: the expected owner is the basename of the resolved --repo path",
        f"hint: migrate the memory with: memory_project.py rename --repo \"{repo}\" "
        f"--to {expected}",
        f"hint: or, if the owner '{owner}' is intentional (repo_path points to a "
        f"subdirectory of the deploy root), re-run with --expect {owner} or --no-owner-check",
    ]


def write_text_atomic(path: pathlib.Path, text: str) -> None:
    """Write `text` to `path` atomically (same-dir temp file + os.replace), newlines as-is."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_text_raw(path: pathlib.Path) -> str:
    """Read a file without newline translation, so rewriting keeps the original line endings."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def split_eol(line: str) -> tuple[str, str]:
    """Split a raw line into (body, eol) so a rewrite can preserve the file's line endings."""
    for eol in ("\r\n", "\n"):
        if line.endswith(eol):
            return line[: -len(eol)], eol
    return line, ""


def change_log_template(project: str) -> str:
    """Canonical `memory/change-log.md` skeleton (append-only journal, no entries yet)."""
    return f"""# Change Log — {project}

{CHANGE_LOG_MARKER}

Append-only journal of the factory's runs on the project `{project}`. One entry per completed
task (success OR FAILED), written by the single writer — the main agent at the end of the task.
Entries are never deleted or reordered; once the threshold (50 entries) is exceeded the old ones
are folded into `memory/summary.md`, and the last 20 entries stay here.

The memory belongs to ONE project — the one named in the task's `repo_path` field. The
`project:` field = the basename of the `repo_path` directory (for this journal — `{project}`).
Different `project:` values in one journal are an error; entries without the `project:` field
are legacy (a warning, not an error). Checked by: `scripts/memory_project.py check` and
`scripts/check_factory_model.py`.

Entry format (flat, verified by `scripts/memory_project.py check` and
`scripts/check_factory_model.py` — one implementation, two CLIs):

```
## <ISO timestamp> — <title>
title: <string>
project: <project name — basename of the task's repo_path, always {project} here>
timestamp: <ISO8601 date>
run_id: <YYYYMMDD-8hex — run identifier, scripts/run_id.py>
branch: <branch or "(none)">
commit: <sha or "(none)">
task_type: implement | review | refactor | security_audit | backlog
goal: <brief goal>
changed_files: <list separated by "; ">
created_files: <list separated by "; ">
results: integration=<PASS|FAIL|SKIP>; regression=<...>; business=<...>; review=<approve|request_changes|SKIP> — key results with a [verified: <command/test/log>] or [inferred] mark
decisions: <decisions made; every key claim carries a [verified: <command/test/log>] or [inferred] mark>
assumptions: <assumptions>
models_used: analyzer=<model>; coder=<model>; tester=<model>; reviewer=<model>
factory_version: <X.Y.Z — factory version at the time of the run>
unfinished: no unfinished items
closed: (optional) one element per closed item — item: <item text> + evidence: <evidence>
```

A one-line example of an entry (one entry — one block, fields line by line):
`title: Short title | project: {project} | timestamp: 2026-01-01T00:00:00+0300 | task_type: implement | ...`

**Record kinds: `task_type` is `implement | review | refactor | security_audit | backlog`.** A
`backlog` record kind exists because the factory itself writes one: it records the DISCOVERY of a
defect that has no run yet, so it has no run to report and declares `results` differently — the
provenance marks are the same, the two sub-keys are not:

```
## <ISO timestamp> — Backlog: <the defect in one line>
...
task_type: backlog
run_id: <YYYYMMDD-8hex — the record is still a run-shaped record, v2 applies>
results: finding=<what was found> [verified: <command/file:line/log>]; impact=<why it matters> [verified: <evidence> or [inferred]>]
```

An unknown kind (`patch`, `hotfix`, …) is an ERROR, and the format v2 gate (run_id + provenance
marks) applies to every kind alike: widening the enum for `backlog` documents a record the factory
already writes, it does not soften the format.

**Format v2 (introduced after v12.8.0): `run_id` + provenance marks.** The `run_id` field is the
run identifier (`YYYYMMDD-<8 hex>`, see `scripts/run_id.py`); it ties the entry to the run's
artifacts. Every KEY claim of a new entry in the `decisions` and `results` fields carries an
inline mark right in the field value:
`[verified: <command/test/log proving the claim>]` — the claim is verified by evidence, or
`[inferred]` — inferred but not verified. Example:
`results: integration=PASS [verified: .code-factory/logs/code-results.md]; review=approve [inferred]`.
An entry written by a factory newer than v12.8.0 without `run_id` (or with a `run_id` not
matching `^\\d{{8}}-[0-9a-f]{{8}}$`) or without a mark in `decisions`/`results` is a format
ERROR; entries without the `project:` field and entries written by a factory no newer than
v12.8.0 are legacy (a warning, not an error). Verified by `scripts/memory_project.py check` and
`scripts/check_factory_model.py`.

If there is debt, the single `unfinished:` line is replaced by a multi-line list; every element
requires 4 fields (`item`, `reason`, `severity` critical|warning|info, `follow_up` true|false):

```
unfinished:
  - item: code reviewer findings accepted as-is
    reason: reviewer budget exhausted
    severity: warning
    follow_up: false
```

The `unfinished` section is filled in for every entry, even when empty (the explicit `no
unfinished items` marker). During compaction the elements with severity=critical or
follow_up=true are always preserved. Entries without `project`, `unfinished` or
`factory_version` pass validation with a warning (not an error) — this is legacy compatibility.

**Closing protocol: an item NEVER disappears without evidence.** When a debt is closed (fixed in
code or deemed obsolete), the closing entry carries a `closed:` block next to `unfinished:` —
one element per closed item; every element requires `item` (the item text it is matched to the
original by) and `evidence` (the command/test/log/`file:line` proving the closure):

```
closed:
  - item: code reviewer findings accepted as-is
    evidence: scripts/memory_project.py:120 -> exit 0 (closed v12.10.1)
```

A closure without `evidence:` is invalid, as is a `closed:` element naming an item that no
journal entry ever declared: both cases are an error of `scripts/memory_project.py backlog
--check` (on par with open items). The reconciliation runs over ALL journal entries, so
historical debts can be closed too: an item that was never closed stays open and is printed by
`backlog` as legacy drift together with its source entry. Memory actuality check:
`python scripts/memory_project.py backlog --repo . --check`.
"""


def summary_template(project: str, repo_path: str, identity: str = "") -> str:
    """Canonical `memory/summary.md` skeleton (owning project + repository identity + sections).

    `identity` is the repository identity (`project_identity`), declared on the `project_id:` line
    immediately after `repo_path:`; an empty value means it could not be computed (no git, no
    history), and the owner check then falls back to the documented name-based basis.
    """
    return f"""# Project Summary — {project}

{SUMMARY_MARKER}
project: {project}
repo_path: {repo_path}
project_id: {identity}

A compact summary of the project. Folded from the old entries of `memory/change-log.md` during
compaction (threshold of 50 entries, the last 20 stay in the journal) and read at the start of
every task so the project history is not replayed from scratch.

`project_id:` is the REPOSITORY identity — 12 hex characters of sha256 over the root commit —
and never the folder name, so a renamed or versioned copy of the deployment directory keeps its
memory valid. `## Current state` is actualized by every run (version, open backlog, closed items,
test files) and is compared with the live state by `memory_project.py check` (`--strict` turns a
divergence into an error).

## Current state

## Key decisions

## Recent history
"""


def cmd_name(args: argparse.Namespace) -> int:
    print(project_name(args.repo))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo).resolve()
    project = args.project or root.name
    identity = project_identity(root)
    memdir = root / "memory"
    memdir.mkdir(parents=True, exist_ok=True)
    templates = {
        "change-log.md": change_log_template(project),
        # The declared repo_path is always the resolved root, exactly like the project name.
        "summary.md": summary_template(project, str(root), identity),
    }
    for name, text in templates.items():
        path = memdir / name
        if path.is_file():
            print(f"exists: {path}")
            continue
        write_text_atomic(path, text)
        print(f"created: {path}")
    if not identity:
        print(f"note: no git root commit at {root} - memory/summary.md declares an empty "
              f"project_id (the owner check falls back to the directory name)")
    return 0


def journal_records(change_log: pathlib.Path) -> list[tuple[str, dict[str, str]]]:
    """Return (heading, top-level fields) of every journal record, in file order.

    Only lines after a dated `## ` heading count, and only non-indented `key: value` lines are
    fields — so the template's fenced examples and the `unfinished` sub-fields are never read
    as fields.
    """
    records: list[tuple[str, dict[str, str]]] = []
    heading: str | None = None
    fields: dict[str, str] = {}
    for line in change_log.read_text(encoding="utf-8").splitlines():
        if ENTRY_RE.match(line):
            if heading is not None:
                records.append((heading, fields))
            heading, fields = line.strip(), {}
            continue
        if heading is None:
            continue
        m = FIELD_RE.match(line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    if heading is not None:
        records.append((heading, fields))
    return records


def journal_projects(change_log: pathlib.Path) -> list[str]:
    """Return the distinct non-empty top-level `project:` values of all journal entries."""
    found: list[str] = []
    for _, fields in journal_records(change_log):
        value = fields.get("project", "")
        if value and value not in found:
            found.append(value)
    return found


def version_after(factory_version: str, base: tuple[int, int, int] = MEMORY_V2_AFTER) -> bool:
    """True when `factory_version` (X.Y.Z) is strictly newer than `base`."""
    m = VERSION_RE.match(unsynth(factory_version.strip()))
    return bool(m) and tuple(int(g) for g in m.groups()) > base


def is_v2_record(fields: dict[str, str]) -> bool:
    """True when a journal record has to satisfy the memory format v2 (see the template).

    That is the case once the record comes from a factory version NEWER than MEMORY_V2_AFTER,
    or as soon as it already carries a v2 field — `run_id` or a provenance mark — so a
    half-migrated record is never silently accepted. Records without `project:` are legacy and
    are only warned about, exactly like the other newer keys; records written before the format
    stay as they are.
    """
    if not fields.get("project", "").strip():
        return False
    return (version_after(fields.get("factory_version", ""))
            or "run_id" in fields
            or any(PROVENANCE_RE.search(fields.get(f, "")) for f in ("decisions", "results")))


def record_format_issues(change_log: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) of the memory format v2 over a whole journal.

    A v2 record must carry a well-formed `run_id` and at least one provenance mark in
    `decisions` AND in `results`; a miss is an error there, a warning in a legacy record.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for heading, fields in journal_records(change_log):
        problems: list[str] = []
        run_id = fields.get("run_id", "").strip()
        if not run_id:
            problems.append("missing or empty key 'run_id'")
        elif not RUN_ID_RE.match(unsynth(run_id)):
            problems.append(f"invalid run_id '{run_id}' (expected YYYYMMDD-<8 hex>)")
        for field in ("decisions", "results"):
            if not PROVENANCE_RE.search(fields.get(field, "")):
                problems.append(f"no provenance mark '[verified: <evidence>]' or '[inferred]' "
                                f"in '{field}'")
        if not problems:
            continue
        if is_v2_record(fields):
            errors += [f"entry '{heading}': {p}" for p in problems]
        elif not fields.get("project", "").strip():
            warnings += [f"entry '{heading}': {p} (legacy format)" for p in problems]
        else:
            # A record with `project:` that predates the format v2: the documented contract makes
            # this a WARNING, never an error — history is never rewritten.
            warnings += [f"entry '{heading}': {p} (pre-v2 format - never rewritten, a warning "
                         f"by contract)" for p in problems]
    return errors, warnings


def result_keys(fields: dict[str, str]) -> tuple[str, ...]:
    """The `results` sub-keys the record's KIND requires (see RECORD_KINDS)."""
    return (RESULT_KEYS_BACKLOG if fields.get("task_type", "").strip() == "backlog"
            else RESULT_KEYS_RUN)


def record_contract_issues(change_log: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) of the record CONTRACT over a whole journal.

    Every record must carry ENTRY_REQUIRED_KEYS and a `task_type` from RECORD_KINDS — an unknown
    kind is an ERROR, `backlog` is a member of the enum (see the module docstring). A missing
    newer key (`unfinished`, `factory_version`, `project`) only WARNS: legacy compatibility, so
    history written before the format evolved stays valid and is never rewritten. `results` must
    carry the sub-keys of the record's own kind: the four run keys for a run record, `finding=`
    and `impact=` for a `backlog` record. A `project:` key with an EMPTY value is an error,
    never silent legacy. The `unfinished` block is either the explicit no-debt marker or a list
    of complete items (`item`, `reason`, `severity` critical|warning|info, `follow_up`
    true|false).
    """
    errors: list[str] = []
    warnings: list[str] = []
    for record in journal_blocks(change_log):
        heading = record["heading"]
        fields = record["fields"]
        for key in ENTRY_REQUIRED_KEYS:
            if key not in fields:
                errors.append(f"entry '{heading}': missing key '{key}'")
        for key in ENTRY_OPTIONAL_KEYS:
            if key not in fields:
                warnings.append(f"entry '{heading}': missing key '{key}' (legacy format)")
        if "project" in fields and not fields["project"].strip():
            errors.append(f"entry '{heading}': empty 'project' value")
        kind = fields.get("task_type", "").strip()
        if "task_type" in fields and kind not in RECORD_KINDS:
            errors.append(f"entry '{heading}': invalid task_type '{kind}' (expected one of "
                          f"{', '.join(RECORD_KINDS)})")
        if "timestamp" in fields and not TIMESTAMP_RE.search(fields["timestamp"]):
            errors.append(f"entry '{heading}': timestamp not ISO-date-like "
                          f"'{fields['timestamp']}'")
        if "factory_version" in fields and not VERSION_RE.match(unsynth(fields["factory_version"])):
            errors.append(f"entry '{heading}': invalid factory_version "
                          f"'{fields['factory_version']}'")
        if "results" in fields:
            for sub in result_keys(fields):
                if f"{sub}=" not in fields["results"]:
                    errors.append(f"entry '{heading}': results missing '{sub}=' for a "
                                  f"'{kind or 'run'}' record")
        if ("unfinished" in fields and not fields["unfinished"]
                and not record["blocks"]["unfinished"]):
            errors.append(f"entry '{heading}': 'unfinished' is empty without items or a "
                          f"no-debt marker")
        for item in record["blocks"]["unfinished"]:
            for sub in ("reason", "severity", "follow_up"):
                if sub not in item:
                    errors.append(f"entry '{heading}': unfinished item "
                                  f"'{item.get('item', '')}' missing '{sub}'")
            if "severity" in item and item["severity"] not in UNFINISHED_SEVERITIES:
                errors.append(f"entry '{heading}': invalid unfinished severity "
                              f"'{item['severity']}'")
            if "follow_up" in item and item["follow_up"] not in UNFINISHED_BOOLS:
                errors.append(f"entry '{heading}': invalid unfinished follow_up "
                              f"'{item['follow_up']}'")
    return errors, warnings


def duplicate_run_id_errors(change_log: pathlib.Path) -> list[str]:
    """One error per `run_id` carried by more than one record — one run produces one record.

    Records without a `run_id` are legacy and stay exempt (exactly like the format-v2 check).
    """
    headings_by_run: dict[str, list[str]] = {}
    for heading, fields in journal_records(change_log):
        run_id = fields.get("run_id", "").strip()
        if run_id:
            headings_by_run.setdefault(run_id, []).append(heading)
    errors: list[str] = []
    for run_id, headings in headings_by_run.items():
        if len(headings) > 1:
            errors.append(f"run_id '{run_id}' is carried by {len(headings)} records ("
                          + " and ".join(f"'{h}'" for h in headings)
                          + ") - one run produces exactly one record, the memory record of that run")
    return errors


def run_id_record_errors(change_log: pathlib.Path, run_id: str) -> list[str]:
    """Errors of `check --run-id <id>`: EXACTLY one record must carry that run_id."""
    matching = [heading for heading, fields in journal_records(change_log)
                if fields.get("run_id", "").strip() == run_id]
    if not matching:
        return [f"run {run_id} produced no memory record (no record of "
                f"memory/change-log.md carries that run_id)"]
    if len(matching) > 1:
        return [f"two records share run {run_id}: "
                + " and ".join(f"'{h}'" for h in matching)]
    return []


def entry_count(change_log: pathlib.Path) -> int:
    """Number of journal entries (lines starting a dated `## <timestamp>` record)."""
    return sum(1 for line in change_log.read_text(encoding="utf-8").splitlines()
               if ENTRY_RE.match(line))


def summary_project(summary: pathlib.Path) -> str:
    """Return the `project:` declared by memory/summary.md ("" when it declares none).

    Only the declaration area counts — right after the canonical marker and before the first
    `## ` section — so a `project: <name>` example inside a fenced code block is never mistaken
    for a declaration (same rule as scripts/check_factory_model.py).
    """
    return declaration_value(summary, "project")


def validate_memory(root: str | pathlib.Path, expect: str = "", no_owner_check: bool = False,
                    strict: bool = False, run_id: str = "") -> tuple[list[str], list[str]]:
    """Return (errors, warnings) of the memory contract under `root` — THE single implementation.

    Both CLIs print this tuple: `memory_project.py check` and `check_factory_model.py`, whose
    `validate_memory` is a thin delegation to this function, so the contract cannot be
    implemented twice and diverge again. The axes, all enforced here:

      - the journal and the summary exist and carry their canonical marker;
      - the owner chain (`expected_owner`): `--expect` wins, then the summary's `project_id:`,
        then the declared `repo_path:`, then the directory name; a FOREIGN `project_id:` is
        refused and a memory of another project is an error — `--no-owner-check` drops only the
        comparison;
      - the journal's `project:` values agree with each other and with the summary declaration;
        a summary without a declaration and records without `project:` are the documented legacy
        WARNINGS, never errors;
      - the record contract (`record_contract_issues`): required keys, the record KIND
        (`RECORD_KINDS`), the `results` sub-keys of that kind and the `unfinished` items;
      - the memory format v2 (`record_format_issues`): `run_id` + provenance marks, with the
        pre-v2 and no-`project:` records kept as warnings and never rewritten;
      - one run — one record (`duplicate_run_id_errors`), plus `run_id_record_errors` when the
        caller passes the run id of the current run;
      - the closing protocol (`backlog_report`): a `closed:` element without `evidence:` or
        naming an unknown item is an error, and so is an open item re-declared without a reason;
      - the `## Current state` of the summary against the live state (`summary_state_warnings`):
        warnings, or ERRORS under `strict`.

    The advisory "hint:" lines of the owner chain are NOT part of the tuple: they are guidance
    for a human and are printed by the `memory_project.py check` CLI. The tuple carries the
    contract only, which is what makes the two CLIs comparable axis by axis.

    A MISSING journal is an ERROR here, because the two states behind it are the CLI's business:
    `memory/` absent entirely is a fresh project (a note + exit 0 from `memory_project.py check`),
    `memory/` WITHOUT `change-log.md` is a broken memory (exit 1, `--allow-fresh` overrides), and
    `check_factory_model.py` — which validates a project that already has a modelled AGENTS.md —
    always fails on a missing journal. Each CLI decides that asymmetry, neither one hides it.
    """
    root = pathlib.Path(root)
    memdir = root / "memory"
    change_log = memdir / "change-log.md"
    summary = memdir / "summary.md"
    errors: list[str] = []
    warnings: list[str] = []
    projects: list[str] = []

    if not change_log.is_file():
        errors.append(f"memory/change-log.md not found under {root}")
    else:
        if CHANGE_LOG_MARKER not in change_log.read_text(encoding="utf-8"):
            errors.append("memory/change-log.md missing canonical marker")
        projects = journal_projects(change_log)
        if len(projects) > 1:
            errors.append("memory/change-log.md mixes projects: " + ", ".join(sorted(projects))
                          + " (one memory belongs to exactly one project)")
        contract_errors, contract_warnings = record_contract_issues(change_log)
        warnings += contract_warnings
        errors += contract_errors
        fmt_errors, fmt_warnings = record_format_issues(change_log)
        warnings += fmt_warnings
        errors += fmt_errors
        errors += duplicate_run_id_errors(change_log)
        if run_id:
            errors += run_id_record_errors(change_log, run_id)
        # The closing protocol runs over the WHOLE journal: a closure without evidence is invalid
        # whatever the age of the record, and an invalid closure never closes (and so never hides)
        # the item it names.
        report = backlog_report(root, run_id)
        errors += [problem["message"] for problem in report["errors"]]

    declared = ""
    if not summary.is_file():
        errors.append(f"memory/summary.md not found under {root}")
    else:
        if SUMMARY_MARKER not in summary.read_text(encoding="utf-8"):
            errors.append("memory/summary.md missing canonical marker")
        declared = summary_project(summary)

    journal_owner = projects[0] if projects else ""
    if journal_owner and declared and journal_owner != declared:
        errors.append(f"memory/summary.md declares project '{declared}' but "
                      f"memory/change-log.md belongs to '{journal_owner}'")
    owner = journal_owner or declared
    if summary.is_file() and not declared:
        warnings.append(f"memory/summary.md does not declare 'project: <name>' (legacy memory, "
                        f"owner '{owner or LEGACY_NO_PROJECT}')")

    expected, basis, _hints = expected_owner(root, expect, no_owner_check)
    if basis == "foreign-repository":
        errors.append(f"memory belongs to another repository: memory/summary.md declares "
                      f"project_id {summary_project_id(summary)} but this repository's root "
                      f"commit gives {project_identity(root)} - the memory was created for a "
                      f"different repository and is refused")
    elif expected and owner and owner != expected:
        errors.append(f"{OWNER_MISMATCH} '{owner}', expected '{expected}'")

    state_warnings = summary_state_warnings(root)
    if strict:
        errors += state_warnings
    else:
        warnings += state_warnings
    return errors, warnings


def memory_owner(root: pathlib.Path) -> str:
    """The owner name the `check` CLI reports: the journal's `project:`, else the summary's."""
    change_log = root / "memory" / "change-log.md"
    projects = journal_projects(change_log) if change_log.is_file() else []
    return (projects[0] if projects else "") or summary_project(root / "memory" / "summary.md")


def cmd_check(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo).resolve()
    memdir = root / "memory"
    change_log = memdir / "change-log.md"
    run_id = getattr(args, "run_id", "") or ""
    strict = bool(getattr(args, "strict", False) or run_id)

    # A missing journal means two DIFFERENT things, and this CLI is what tells them apart (see the
    # module docstring): no memory/ at all is first contact with the project — a fresh project,
    # a note and exit 0 — while a memory/ WITHOUT its journal is a broken, partial memory. The
    # shared validate_memory() reports a missing journal as an error, which is what
    # check_factory_model.py — the gate of a project that already has a modelled AGENTS.md —
    # needs; the fresh/partial distinction below is this CLI's alone, and both states are named.
    if not change_log.is_file():
        if run_id:
            print(f"FAIL - run {run_id} produced no memory record (memory/change-log.md is "
                  f"missing)", file=sys.stderr)
            return 1
        if not memdir.is_dir():
            print("note: fresh project, memory/ absent - create it with init")
            return 0
        if not getattr(args, "allow_fresh", False):
            print(f"FAIL - memory directory exists without change-log.md: {memdir} holds a "
                  f"partial memory (create the journal with init, or re-run with --allow-fresh "
                  f"if the journal-less memory is deliberate)", file=sys.stderr)
            return 1
        print("note: memory/ exists without change-log.md (allowed by --allow-fresh)")
        return 0

    # The advisory part of the owner chain: how the expected owner was derived, printed as hints
    # (never as a WARN) — the contract itself comes from validate_memory().
    expected, basis, basis_warnings = expected_owner(root, args.expect, args.no_owner_check)
    for warning in basis_warnings:
        print(warning, file=sys.stderr)

    errors, warnings = validate_memory(root, args.expect, args.no_owner_check, strict, run_id)
    for warning in warnings:
        print(f"WARN - {warning}", file=sys.stderr)
    if errors:
        print("FAIL - memory is invalid:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        if any(error.startswith(OWNER_MISMATCH) for error in errors):
            for hint in owner_hints(root, memory_owner(root), expected):
                print(hint, file=sys.stderr)
        return 1

    print(f"ok - memory belongs to project '{memory_owner(root) or LEGACY_NO_PROJECT}' "
          f"({entry_count(change_log)} entries) [basis: {basis}]")
    return 0


def rewrite_journal_project(text: str, name: str) -> tuple[str, int]:
    """Rewrite the `project:` field of every journal record to `name`.

    Only record bodies count (lines after a dated `## ` heading), so the `project:` examples in
    the template's fenced code blocks are never touched. Records without the field stay legacy
    and are not counted, which makes a repeated run a no-op (idempotent). Returns
    (text, number of records actually rewritten); the file's line endings are preserved.
    """
    out: list[str] = []
    rewritten = 0
    in_entry = False
    for raw in text.splitlines(keepends=True):
        body, eol = split_eol(raw)
        if ENTRY_RE.match(body):
            in_entry = True
        elif in_entry:
            m = FIELD_RE.match(body)
            if m and m.group(1) == "project" and m.group(2).strip() != name:
                body = f"project: {name}"
                rewritten += 1
        out.append(body + eol)
    return "".join(out), rewritten


def rewrite_summary_project(text: str, name: str) -> tuple[str, str]:
    """Rewrite the `project:` declaration of summary.md; return (text, state).

    state is "absent" when the file declares no project at all (legacy memory), "unchanged" when
    it already names `name`, and "updated" otherwise. Only the declaration area counts — right
    after the canonical marker and before the first `## ` section — exactly like summary_project.
    """
    lines = text.splitlines(keepends=True)
    start = next((i + 1 for i, ln in enumerate(lines) if SUMMARY_MARKER in ln), None)
    if start is None:
        return text, "absent"
    for i in range(start, len(lines)):
        body, eol = split_eol(lines[i])
        if body.startswith("## "):
            break
        m = FIELD_RE.match(body)
        if m and m.group(1) == "project":
            if m.group(2).strip() == name:
                return text, "unchanged"
            lines[i] = f"project: {name}" + eol
            return "".join(lines), "updated"
    return text, "absent"


def cmd_rename(args: argparse.Namespace) -> int:
    new = args.to.strip()
    if len(new.split()) != 1:
        print("FAIL - --to must be a single non-empty project name", file=sys.stderr)
        return 1
    root = pathlib.Path(args.repo).resolve()
    memdir = root / "memory"
    change_log = memdir / "change-log.md"
    summary = memdir / "summary.md"
    if not change_log.is_file() and not summary.is_file():
        print(f"FAIL - no memory/change-log.md or memory/summary.md under {root}", file=sys.stderr)
        return 1

    if change_log.is_file():
        text, rewritten = rewrite_journal_project(read_text_raw(change_log), new)
        if rewritten:
            write_text_atomic(change_log, text)
        print(f"{change_log}: {rewritten} record(s) rewritten to project '{new}'")
    else:
        print(f"note: {change_log} not found (nothing to rewrite)")

    if summary.is_file():
        text, state = rewrite_summary_project(read_text_raw(summary), new)
        if state == "updated":
            write_text_atomic(summary, text)
        print(f"{summary}: project declaration {state}")
    else:
        print(f"note: {summary} not found (nothing to rewrite)")

    print(f"ok - memory owner is now '{new}' (expected by project_name({root}))")
    return 0


def unfinished_items_text(text: str) -> list[dict[str, str]]:
    """Return every `unfinished` item of journal/summary TEXT, in file order (see below).

    The text form exists so a compaction can verify its result IN MEMORY, before a single byte of
    either file is written.
    """
    items: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    in_closed = False
    for line in text.splitlines():
        m = FIELD_RE.match(line)
        if m:
            in_closed = m.group(1) == "closed" and not m.group(2).strip()
        elif line.startswith("## "):
            in_closed = False               # a new section always ends the `closed:` block
        m = ITEM_RE.match(line)
        if m:
            if in_closed:
                continue
            cur = {"item": m.group(1).strip()}
            items.append(cur)
            continue
        m = ITEM_FIELD_RE.match(line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip()
    return items


def unfinished_items(path: pathlib.Path) -> list[dict[str, str]]:
    """Return every `unfinished` item of a journal or a compacted summary, in file order.

    Works on both file kinds: an item is any `- item: <text>` line, and the following
    `reason:`/`severity:`/`follow_up:` lines belong to it (same rule as
    scripts/check_factory_model.py). Items inside a `closed:` block are skipped — they are
    closures, not debt, and counting them as "present" would weaken a compaction check. An item
    that belongs to no top-level block key (e.g. one under a `## Unfinished` heading) is still read,
    so files written before the `closed:` protocol keep behaving exactly as they did.
    """
    return unfinished_items_text(path.read_text(encoding="utf-8"))


def must_survive_compaction(items: list[dict[str, str]]) -> list[str]:
    """The `item` values a compaction must keep: severity=critical or follow_up=true."""
    return [i["item"] for i in items
            if i["item"] and (i.get("severity", "").lower() == "critical"
                              or i.get("follow_up", "").lower() == "true")]


def cmd_compact_check(args: argparse.Namespace) -> int:
    before, after = pathlib.Path(args.before), pathlib.Path(args.after)
    for path in (before, after):
        if not path.is_file():
            print(f"FAIL - file not found: {path}", file=sys.stderr)
            return 1

    required = must_survive_compaction(unfinished_items(before))
    present = {item["item"] for item in unfinished_items(after)}
    missing = [item for item in required if item not in present]
    if missing:
        print(f"FAIL - compaction dropped {len(missing)} of {len(required)} "
              f"critical/follow_up item(s):", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"ok - compaction preserved all {len(required)} critical/follow_up item(s) "
          f"({len(present)} item(s) in {after.name})")
    return 0


def shorten(text: str, limit: int = HISTORY_TITLE_LIMIT) -> str:
    """Collapse whitespace and cap a title so a folded history bullet stays one readable line."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def history_bullets(folded: list[dict]) -> list[str]:
    """One `## Recent history` bullet per folded record: timestamp, title, run_id, closed count."""
    bullets: list[str] = []
    for record in folded:
        title = record["fields"].get("title", "").strip()
        if not title:
            title = record["heading"].lstrip("#").strip()
        bullets.append(f"- {record_timestamp(record)} — {shorten(title)} "
                       f"(run_id: {record['fields'].get('run_id', '').strip() or 'none'}, "
                       f"closed: {len(record['blocks']['closed'])})")
    return bullets


def carried_debt_lines(folded: list[dict]) -> list[str]:
    """The `## Carried debt` body: EVERY must-survive item of the folded records, with its source.

    The `- item:` / `reason:` / `severity:` / `follow_up:` shape is the one
    `unfinished_items_text` reads, so `compact-check --before <old journal> --after <summary>`
    agrees with what this function writes.
    """
    lines: list[str] = []
    for record in folded:
        stamp = record_timestamp(record)
        for item in record["blocks"]["unfinished"]:
            if not is_open_item(item) or not item["item"]:
                continue
            lines += [f"- item: {item['item']}",
                      f"  reason: {item.get('reason', '').strip() or '(none recorded)'}",
                      f"  severity: {item.get('severity', '').strip() or 'warning'}",
                      f"  follow_up: {item.get('follow_up', '').strip() or 'false'}",
                      f"  source: {stamp}"]
    return lines


def closure_age(stamp: str) -> str:
    """How long ago the closure happened, e.g. `41 day(s) ago`, from a record timestamp.

    Only the ISO DATE part is compared with today's UTC date: a time zone shifts a fold by less than
    a day, which does not change the sentence. A timestamp without an ISO date (a hand-written one)
    degrades to `at an unrecorded time` instead of inventing a distance. The age is computed ONCE,
    when the closure is folded — an existing bullet is never rewritten by a later compaction.
    """
    match = STAMP_DATE_RE.match(stamp.strip())
    if not match:
        return "at an unrecorded time"
    try:
        when = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return "at an unrecorded time"
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return f"{max((today - when).days, 0)} day(s) ago"


def folded_closures(folded: list[dict]) -> list[dict[str, str]]:
    """Every `closed:` element of the folded records: item, VERBATIM evidence, source timestamp.

    Collected BEFORE anything is written, because the evidence is the only proof of the folded debt:
    `cmd_compact` verifies that both the item and its evidence survive into memory/summary.md.
    """
    closures: list[dict[str, str]] = []
    for record in folded:
        stamp = record_timestamp(record)
        for closed in record["blocks"]["closed"]:
            text = closed.get("item", "").strip()
            if not text:
                continue
            closures.append({"item": text,
                             "evidence": closed.get("evidence", "").strip(),
                             "timestamp": stamp})
    return closures


def closure_bullets(closures: list[dict[str, str]]) -> list[str]:
    """One `## Closed with evidence` bullet per closure: age, item, verbatim evidence, source."""
    return [f"- {closure_age(closure['timestamp'])}: closed '{closure['item']}' "
            f"\u2014 evidence: {closure['evidence']} [source: {closure['timestamp']}]"
            for closure in closures]


def parse_closure_bullets(body_lines: list[str]) -> list[dict[str, str]]:
    """The closures a `## Closed with evidence` body records; an unparsable line is not a closure."""
    closures: list[dict[str, str]] = []
    for line in body_lines:
        match = CLOSURE_BULLET_RE.match(line.strip())
        if match:
            closures.append({"item": match.group("item"),
                             "evidence": match.group("evidence").strip(),
                             "timestamp": match.group("source").strip()})
    return closures


def section_body(text: str, heading: str) -> list[str]:
    """Body lines of the `## ` section `heading` of a Markdown text ([] when the section is absent)."""
    body: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip() == heading:
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside:
            body.append(line)
    return body


def folded_summary_record(summary_text: str) -> dict | None:
    """The synthetic journal record the summary's two fold sections stand for (None when absent).

    `compact` moves records out of the journal, so the memory would otherwise lose two facts with
    them: the debt the fold carried (`## Carried debt`) and the proofs of the closures it carried
    (`## Closed with evidence`). This function turns those two sections back into a record shaped
    exactly like a journal record (`journal_blocks_text` parses it), which `backlog_report_text`
    reads as the OLDEST history — before the journal — so:
      - every folded `closed:` element is validated and counted like a journal closure,
      - a closure that stayed in the journal still matches a declaration the fold carried away,
      - the carried debt stays in the open backlog instead of disappearing from the report.

    A `closed:` element is ALSO a declaration: it records that the item EXISTED and was open, which
    is exactly what the closure proves. Every item a `## Closed with evidence` bullet names and
    `## Carried debt` does not already declare is therefore declared here, as an open item the same
    record then closes. Without that, a LATER fold that finds no open debt rewrites `## Carried
    debt` to `- none` (the section is REPLACED, never accumulated) and the recorded closure loses
    its declaration — `closed item '<text>' matches no follow_up/critical item of the journal`.

    The declarations come first and the closures after, so an item the fold both carried and closed
    reads as closed (it has evidence; the closing protocol makes a proven closure final), and an
    item listed in BOTH sections is declared once and counted once: `open`/`closed` stay truthful.
    """
    debt = [line for line in section_body(summary_text, CARRIED_DEBT_HEADING)
            if line.strip() != SECTION_NONE]
    closures = parse_closure_bullets(section_body(summary_text, CLOSED_WITH_EVIDENCE_HEADING))
    if not debt and not closures:
        return None
    parts = [FOLDED_HEADING, "timestamp: (folded into memory/summary.md)", "unfinished:"]
    parts += debt or [SECTION_NONE]
    parts.append("closed:")
    for closure in closures:
        parts += [f"- item: {closure['item']}", f"  evidence: {closure['evidence']}",
                  f"  source: {closure['timestamp']}"]
    records = journal_blocks_text("\n".join(parts) + "\n")
    if not records:
        return None
    record = records[0]
    declared = {normalize_item(item["item"]) for item in record["blocks"]["unfinished"]}
    for closure in closures:
        key = normalize_item(closure["item"])
        if not key or key in declared:
            continue
        declared.add(key)
        record["blocks"]["unfinished"].append(
            {"item": closure["item"], "severity": "critical", "follow_up": "true",
             "reason": "(declared by the folded closure - the item existed and was open)"})
    return record


def upsert_section(text: str, heading: str, body_lines: list[str]) -> str:
    """Insert `heading` or replace its body, keeping the rest of the file and its line endings."""
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    out: list[str] = []
    found = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == heading:
            found = True
            out.append(line)
            index += 1
            while index < len(lines) and not lines[index].startswith("## "):
                index += 1
            out.extend(body_lines)
            continue
        out.append(line)
        index += 1
    if not found:
        while out and not out[-1].strip():
            out.pop()
        if out:
            out.append("")
        out.append(heading)
        out.extend(body_lines)
    result = eol.join(out)
    return result + eol if text.endswith("\n") else result


def cmd_compact(args: argparse.Namespace) -> int:
    """Fold the oldest journal records into memory/summary.md (the 50/20 rule, in code)."""
    root = pathlib.Path(args.repo).resolve()
    change_log = root / "memory" / "change-log.md"
    summary = root / "memory" / "summary.md"
    for path in (change_log, summary):
        if not path.is_file():
            print(f"FAIL - file not found: {path}", file=sys.stderr)
            return 1
    if args.keep < 1:
        print("FAIL - --keep must be at least 1 (the journal always keeps its newest records)",
              file=sys.stderr)
        return 1

    raw = read_text_raw(change_log)
    lines = raw.splitlines(keepends=True)
    records = journal_blocks_text(raw)
    total = len(records)
    if total <= args.threshold or total <= args.keep:
        print(f"ok - nothing to compact ({total}/{args.threshold})")
        return 0

    folded = records[: total - args.keep]
    kept = records[total - args.keep:]
    history = history_bullets(folded)
    debt = carried_debt_lines(folded)
    closures = folded_closures(folded)
    required_folded = must_survive_compaction(
        [item for record in folded for item in record["blocks"]["unfinished"]])

    # A `closed:` element WITHOUT `evidence:` is an invalid closure in the journal (the closing
    # protocol), and moving it into the summary must not make it look valid: the fold refuses it.
    unproven = [closure["item"] for closure in closures if not closure["evidence"]]
    if unproven:
        print(f"FAIL - {len(unproven)} folded 'closed:' element(s) carry no 'evidence:' - nothing "
              f"was written (prove them with a new record; a closure without evidence closes "
              f"nothing):", file=sys.stderr)
        for item in unproven:
            print(f"  - {item}", file=sys.stderr)
        return 1

    # The kept records and the journal header stay byte-identical (line endings included).
    header = lines[: records[0]["start"] - 1]
    kept_lines = lines[kept[0]["start"] - 1: kept[-1]["end"]]
    tail = lines[kept[-1]["end"]:]
    new_journal = "".join(header + kept_lines + tail)
    summary_raw = read_text_raw(summary)
    new_summary = upsert_section(summary_raw, CARRIED_DEBT_HEADING, debt or [SECTION_NONE])
    # The closures ACCUMULATE: the bullets of an earlier fold stay byte-identical (their age was
    # computed then), the closures of this fold are appended — the proof of an older closure is
    # never rewritten by a later compaction.
    existing = [line for line in section_body(new_summary, CLOSED_WITH_EVIDENCE_HEADING)
                if line.strip() != SECTION_NONE]
    new_bullets = [bullet for bullet in closure_bullets(closures) if bullet not in existing]
    new_summary = upsert_section(new_summary, CLOSED_WITH_EVIDENCE_HEADING,
                                 existing + new_bullets or [SECTION_NONE])
    new_summary = upsert_section(new_summary, RECENT_HISTORY_HEADING, history)

    # Verify IN MEMORY that nothing required is lost — the folded items live in the summary, the
    # kept ones in the journal — and write nothing at all when the check fails. The
    # must_survive_compaction guarantee is a PRESENCE test, because such an item has to arrive
    # byte-identically; everything else is verified SEMANTICALLY (see the next block).
    searchable = normalize_item(new_journal + "\n" + new_summary)
    required = must_survive_compaction([item for record in records
                                        for item in record["blocks"]["unfinished"]])
    missing = [item for item in required if normalize_item(item) not in searchable]
    if missing:
        print(f"FAIL - compaction would drop {len(missing)} of {len(required)} "
              f"critical/follow_up item(s) - nothing was written:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1

    # The would-be files are fed through the SAME fold that `check` and `backlog --check` use. A
    # substring test cannot see an ORPHANED closure — the item text is still inside the closure
    # bullet itself — so the whole closing protocol is validated on the result instead: a memory
    # that would report a `closed item … matches no …` (or any other protocol) error is never
    # written.
    verdict = backlog_report_text(new_journal, new_summary)
    protocol_errors = [problem["message"] for problem in verdict["errors"]]
    if protocol_errors:
        print(f"FAIL - compaction would invalidate the memory: {protocol_errors[0]} - nothing was "
              f"written", file=sys.stderr)
        for message in protocol_errors[1:]:
            print(f"  {message}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"would fold: {len(folded)} record(s)")
        print(f"would keep: {len(kept)} record(s)")
        print(f"would carry: {len(required_folded)} item(s)")
        print(f"would close: {len(closures)} item(s) with evidence")
        print("dry-run - nothing written")
        return 0

    if new_journal != raw:
        write_text_atomic(change_log, new_journal)
    if new_summary != summary_raw:
        write_text_atomic(summary, new_summary)
    print(f"folded: {len(folded)}")
    print(f"kept: {len(kept)}")
    print(f"carried: {len(required_folded)}")
    print(f"closed: {len(closures)}")
    print(f"ok - journal compacted into {summary} "
          f"({len(folded)} record(s) folded, {len(kept)} kept)")
    return 0


def journal_blocks_text(text: str) -> list[dict]:
    """Parse journal TEXT into records carrying their fields, item blocks and line range.

    Every record is `{"heading": str, "start": int, "end": int, "fields": {key: value},
    "blocks": {"unfinished": [...], "closed": [...]}}`, where `start`/`end` are the 1-BASED line
    numbers of the record's `## ` heading and of its last non-blank line (so
    `text.splitlines(keepends=True)[start - 1:end]` is exactly one record, trailing blank lines
    excluded). An item block is opened by the top-level key of that name with an EMPTY value
    (`unfinished:`, `closed:`) and ends at the next top-level `key: value` line; inside it a
    `- item: <text>` line starts an element and the indented sub-fields belong to it (`reason`,
    `severity`, `follow_up` — and `evidence` for a `closed:` element). Lines before the first
    record and the template's fenced examples are never read, so the format examples stay inert.
    """
    records: list[dict] = []
    cur: dict | None = None
    section: str | None = None
    item: dict[str, str] | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if ENTRY_RE.match(line):
            cur = {"heading": line.strip(), "start": lineno, "end": lineno, "fields": {},
                   "blocks": {s: [] for s in ITEM_SECTIONS}}
            records.append(cur)
            section, item = None, None
            continue
        if cur is None:
            continue
        if line.strip():
            cur["end"] = lineno
        m = FIELD_RE.match(line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            cur["fields"][key] = value
            section = key if not value and key in ITEM_SECTIONS else None
            item = None
            continue
        if section is None:
            continue
        m = ITEM_RE.match(line)
        if m:
            item = {"item": m.group(1).strip()}
            cur["blocks"][section].append(item)
            continue
        m = ITEM_FIELD_RE.match(line) or CLOSED_FIELD_RE.match(line)
        if m and item is not None:
            item[m.group(1)] = m.group(2).strip()
    return records


def journal_blocks(change_log: pathlib.Path) -> list[dict]:
    """Records of a journal file (see journal_blocks_text for the record shape)."""
    return journal_blocks_text(change_log.read_text(encoding="utf-8"))


def normalize_item(text: str) -> str:
    """Item identity for matching: whitespace collapsed, case-insensitive (see `backlog`)."""
    return " ".join(text.split()).casefold()


def is_open_item(item: dict[str, str]) -> bool:
    """True when an `unfinished` item is debt that stays open: severity=critical or follow_up=true.

    The same predicate as `must_survive_compaction`, so "must survive a compaction" and "must
    appear in the backlog" can never drift apart.
    """
    return bool(must_survive_compaction([item]))


def record_timestamp(record: dict) -> str:
    """The `timestamp:` of a record, falling back to the date that opens its heading."""
    stamp = record["fields"].get("timestamp", "").strip()
    return stamp or (record["heading"][3:].split() or [""])[0]


def backlog_report(root: pathlib.Path, run_id: str = "") -> dict:
    """The fold of the memory UNDER `root` — the file-backed entry point (see backlog_report_text).

    Reading is all this wrapper does, so the SAME fold can be applied to a would-be memory that is
    not on disk yet (`cmd_compact` validates its result with `backlog_report_text` before writing).
    A missing journal is folded as an empty journal and a summary that cannot be read as a summary
    without fold sections, exactly like `folded_summary_record` always tolerated them.
    """
    change_log = root / "memory" / "change-log.md"
    summary = root / "memory" / "summary.md"
    journal_text = change_log.read_text(encoding="utf-8") if change_log.is_file() else ""
    try:
        summary_text = summary.read_text(encoding="utf-8") if summary.is_file() else ""
    except (OSError, UnicodeDecodeError):
        summary_text = ""
    return backlog_report_text(journal_text, summary_text, run_id)


def backlog_report_text(journal_text: str, summary_text: str, run_id: str = "") -> dict:
    """Fold a whole journal into the open item set and the validity of its `closed:` blocks.

    The fold runs over every record in FILE ORDER: a record first contributes its open items
    (severity=critical or follow_up=true) and then applies its own `closed:` elements, so an item
    declared again after an earlier closure is open again. An element closes the item whose
    normalized text matches one declared as open SOMEWHERE in the journal — an element naming an
    unknown item, or one without `evidence:`, is an error regardless of the record's age (the
    validation is never gated by a version) and closes NOTHING, so a broken closure can never hide
    a debt. Open items keep the record that declared them, which is what makes an unreconciled
    history readable as legacy drift.

    The records `compact` folded away are NOT gone: `memory/summary.md` keeps their debt
    (`## Carried debt`) and their closures with their evidence (`## Closed with evidence`), and
    `folded_summary_record` reads them back as the synthetic OLDEST record — before the journal, so
    a closure that stayed in the journal still matches a declaration the fold carried away, the
    carried debt stays in the open backlog, and the folded closures stay VALIDATED and COUNTED.

    The CURRENT record — the one whose `run_id` equals `run_id`, else the last record in file
    order — decides between a carried debt and a silent disappearance: every open item must be
    mentioned there, either re-declared in its `unfinished:` block WITH a non-empty `reason:`
    (`carried`) or named in a `closed:` element; an open item it does not mention at all is
    `unmentioned`, and a re-declared item without a reason is an error (`carried-without-reason`).

    Returns `{"open": int, "items": [...], "closed": int, "closed_in_summary": int,
    "legacy_drift": int, "carried": int, "unmentioned": int, "unmentioned_items": [...],
    "current": str, "errors": [...], "warnings": [...]}`; `items` keeps the file order of the
    declaring record. `closed` counts EVERY validatable closure (journal + summary) exactly once,
    and `closed_in_summary` names the part the fold carried into memory/summary.md, so the count
    stays truthful after a compaction and never double-counts a closure.
    """
    records = journal_blocks_text(journal_text) if journal_text else []
    folded = folded_summary_record(summary_text)
    # The summary's folded record is the OLDEST history: it precedes the journal.
    history = ([folded] if folded is not None else []) + records

    declared: set[str] = set()
    for record in history:
        for item in record["blocks"]["unfinished"]:
            if is_open_item(item) and item["item"]:
                declared.add(normalize_item(item["item"]))

    open_items: dict[str, dict] = {}
    errors: list[dict] = []
    closed_total = 0
    for record in history:
        heading = record["heading"]
        version = record["fields"].get("factory_version", "")
        has_closed_block = bool(record["blocks"]["closed"])
        for item in record["blocks"]["unfinished"]:
            if is_open_item(item) and item["item"]:
                open_items[normalize_item(item["item"])] = {
                    "item": item["item"],
                    "source": heading,
                    "timestamp": item.get("source", "").strip() or record_timestamp(record),
                    "factory_version": version,
                    "severity": item.get("severity", ""),
                    "follow_up": item.get("follow_up", ""),
                    "source_closed": has_closed_block,
                }
        for closed in record["blocks"]["closed"]:
            closed_total += 1
            text = closed.get("item", "")
            if not text:
                errors.append({"kind": "closed-without-item", "record": heading, "item": "",
                               "message": f"entry '{heading}': a 'closed:' element carries no "
                                          f"'item:' text"})
                continue
            key = normalize_item(text)
            evidence = closed.get("evidence", "").strip()
            if not evidence:
                errors.append({"kind": "closed-without-evidence", "record": heading, "item": text,
                               "message": f"entry '{heading}': closed item '{text}' carries no "
                                          f"'evidence:' (closing without evidence is invalid)"})
            if key not in declared:
                errors.append({"kind": "closed-unknown-item", "record": heading, "item": text,
                               "message": f"entry '{heading}': closed item '{text}' matches no "
                                          f"follow_up/critical item of the journal"})
            # Only a VALID closure (evidence + an item the journal declared) actually closes the
            # item: an unsupported `closed:` element leaves the debt open, so it cannot hide it.
            if evidence and key in declared:
                open_items.pop(key, None)

    # The CURRENT record: the one carrying --run-id, else the last one written (journal only — the
    # summary's folded record is never "current", it is the history behind the journal).
    current: dict | None = None
    for record in records:
        if not run_id or record["fields"].get("run_id", "").strip() == run_id:
            current = record
            if run_id:
                break
    carried: set[str] = set()
    mentioned: set[str] = set()
    if current is not None:
        heading = current["heading"]
        for section in ITEM_SECTIONS:
            for element in current["blocks"][section]:
                if element.get("item"):
                    mentioned.add(normalize_item(element["item"]))
        for element in current["blocks"]["unfinished"]:
            key = normalize_item(element.get("item", ""))
            if not key or key not in open_items:
                continue
            if element.get("reason", "").strip():
                carried.add(key)
                continue
            errors.append({"kind": "carried-without-reason", "record": heading,
                           "item": element["item"],
                           "message": f"entry '{heading}': the carried item "
                                      f"'{element['item']}' has no 'reason:' (a carried debt needs "
                                      f"a reason, a closed one needs 'evidence:')"})
    unmentioned_items = [item for key, item in open_items.items() if key not in mentioned]

    items = list(open_items.values())
    drift = sum(1 for item in items if not item["source_closed"])
    return {
        "open": len(items),
        "closed": closed_total,
        "closed_in_summary": len(folded["blocks"]["closed"]) if folded is not None else 0,
        "legacy_drift": drift,
        "carried": len(carried),
        "unmentioned": len(unmentioned_items),
        "unmentioned_items": [
            {k: v for k, v in item.items() if k != "source_closed"}
            for item in unmentioned_items],
        "current": current["heading"] if current is not None else "",
        "items": [{k: v for k, v in item.items() if k != "source_closed"} for item in items],
        "errors": errors,
        "warnings": [],
    }


def current_state_text(summary: pathlib.Path) -> str:
    """Body of the `## Current state` section of memory/summary.md ("" when the section is absent).

    Only that section counts: the rest of the summary (history, key decisions) is allowed to name
    older versions, exactly like the `project:` declaration area rule used by `check`.
    """
    if not summary.is_file():
        return ""
    lines = summary.read_text(encoding="utf-8").splitlines()
    start = next((i + 1 for i, ln in enumerate(lines)
                  if ln.startswith(SUMMARY_STATE_HEADING)), None)
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def test_file_count(root: pathlib.Path) -> int:
    """Number of `test_*.py` files under `root`, pruning `.code-factory`, `.git` and `backups`."""
    total = 0
    for _, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in TEST_COUNT_PRUNE]
        total += sum(1 for name in filenames
                     if name.startswith("test_") and name.endswith(".py"))
    return total


def summary_state_warnings(root: pathlib.Path, report: dict | None = None) -> list[str]:
    """WARN on every divergence between `## Current state` and the live state of the repository.

    Compared facts, each ONLY when the section actually declares it (so a summary that names none
    of them stays silent):
      - the factory version it claims as current (its first `vX.Y.Z` mention, e.g. "Factory
        v12.10.0: ...") vs the repo's VERSION; older versions name-dropped later are history;
      - `open backlog: <n>` vs the open count of the backlog fold;
      - `<n> closed` vs the closed count of the fold;
      - `<n> test files` / `<n> self-tests` (or a `self-tests: <n>` column) vs the number of
        `test_*.py` files in the tree.
    `report` is a `backlog_report` result when the caller already has one, so the journal is not
    folded twice.
    """
    body = current_state_text(root / "memory" / "summary.md")
    if not body:
        return []
    warnings: list[str] = []
    version_file = root / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        claimed = CLAIMED_VERSION_RE.search(body)
        if version and claimed and claimed.group(1) != version:
            warnings.append(f"memory/summary.md '{SUMMARY_STATE_HEADING}' claims factory version "
                            f"v{claimed.group(1)} but VERSION says {version} — the summary is "
                            f"stale, refresh '{SUMMARY_STATE_HEADING}'")
    if report is None:
        report = backlog_report(root)
    declared_open = STATE_OPEN_BACKLOG_RE.search(body)
    if declared_open and int(declared_open.group(1)) != report["open"]:
        warnings.append(f"memory/summary.md '{SUMMARY_STATE_HEADING}' claims 'open backlog: "
                        f"{declared_open.group(1)}' but the journal fold gives "
                        f"{report['open']} open item(s)")
    declared_closed = STATE_CLOSED_RE.search(body)
    if declared_closed and int(declared_closed.group(1)) != report["closed"]:
        warnings.append(f"memory/summary.md '{SUMMARY_STATE_HEADING}' claims "
                        f"{declared_closed.group(1)} closed item(s) but the journal fold gives "
                        f"{report['closed']}")
    declared_tests = STATE_TEST_FILES_RE.search(body) or STATE_TEST_FILES_COLUMN_RE.search(body)
    if declared_tests:
        live = test_file_count(root)
        if int(declared_tests.group(1)) != live:
            warnings.append(f"memory/summary.md '{SUMMARY_STATE_HEADING}' claims "
                            f"{declared_tests.group(1)} test files but the tree holds {live} "
                            f"'test_*.py' file(s)")
    return warnings


def summary_version_warnings(root: pathlib.Path) -> list[str]:
    """Backward-compatible alias of `summary_state_warnings` (kept so no import breaks)."""
    return summary_state_warnings(root)


def cmd_backlog(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo).resolve()
    run_id = getattr(args, "run_id", "") or ""
    report = backlog_report(root, run_id)
    # The `## Current state` warnings reuse the fold's open/closed counts: one fold per run.
    report["warnings"] = summary_state_warnings(root, report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"open: {report['open']}")
        for item in report["items"]:
            print(f"  - {item['item']} "
                  f"[source: {item['timestamp']}, "
                  f"factory_version={item['factory_version'] or '?'}]")
        print(f"carried: {report['carried']} (reason in the current record)")
        print(f"unmentioned: {report['unmentioned']}")
        if report["closed"]:
            print(f"closed: {report['closed']} item(s) with evidence"
                  + (f" ({report['closed_in_summary']} folded into memory/summary.md)"
                     if report["closed_in_summary"] else ""))
        if report["legacy_drift"]:
            print(f"note: {report['legacy_drift']} of these item(s) come from record(s) without a "
                  f"'closed:' block (legacy drift) — close them in a new record with 'closed:' "
                  f"+ 'evidence:'")

    for warning in report["warnings"]:
        print(f"WARN - {warning}", file=sys.stderr)
    # The `closed:` blocks are validated on every run, but they only fail under `--check`: without
    # it they are reported, exactly like the open items themselves.
    verdict = "FAIL" if args.check else "WARN"
    for problem in report["errors"]:
        print(f"{verdict} - {problem['message']}", file=sys.stderr)
    if not args.check:
        return 0

    # `--check` enforces the closing protocol, not "open: 0": an open item is fine as long as the
    # CURRENT record carries it with a reason, so the Finish gate can accept carried-over debt while
    # a debt that disappeared silently (mentioned nowhere) still fails.
    if report["unmentioned"]:
        print(f"FAIL - {report['unmentioned']} open item(s) are mentioned nowhere in the current "
              f"record ({report['current']}): a debt cannot disappear without proof of closure",
              file=sys.stderr)
        for item in report["unmentioned_items"]:
            print(f"  - {item['item']} [source: {item['timestamp']}]", file=sys.stderr)
    if report["unmentioned"] or report["errors"]:
        print(f"FAIL - backlog --check requires 'unmentioned: 0' and a valid closing protocol "
              f"(every open item carried in the current record with a 'reason:', every 'closed:' "
              f"element carrying 'evidence:' and naming an existing item)", file=sys.stderr)
        return 1

    print(f"ok - backlog is actual (unmentioned: 0, carried: {report['carried']} with a reason, "
          f"{report['closed']} closed item(s) with evidence)")
    return 0


def unquote(value: str) -> str:
    """Drop one pair of matching surrounding quotes from a scalar YAML value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_fix_tasks(text: str) -> list[dict]:
    """Parse the YAML subset of a generated fix-task file (no PyYAML in the factory).

    The file is a flat sequence of task mappings — `- title: ...` starts a task, deeper indented
    `key: value` lines are its fields, and deeper indented `- value` lines are the items of the
    current field (acceptance_criteria, models, commit_exclude). A top-level `tasks:` mapping is
    accepted too. Each task is {"line": int, "fields": {key: (value, line)}, "lists": {key: […]}}.
    """
    tasks: list[dict] = []
    task_indent: int | None = None
    cur: dict | None = None
    cur_key = ""
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        m = FIX_TASK_RE.match(line)
        if m and (task_indent is None or indent == task_indent):
            if task_indent is None:
                task_indent = indent
            cur = {"line": lineno, "fields": {}, "lists": {}}
            tasks.append(cur)
            cur_key = ""
            cur["fields"][m.group("key")] = (unquote(m.group("val").strip()), lineno)
            continue
        if cur is None:
            continue  # preamble before the first task (e.g. a version comment)
        lm = FIX_LIST_RE.match(line)
        if lm and cur_key:
            cur["lists"].setdefault(cur_key, []).append(unquote(lm.group("val").strip()))
            continue
        fm = FIX_FIELD_RE.match(line)
        if fm and indent > (task_indent or 0):
            cur_key = fm.group("key")
            val = unquote(fm.group("val").strip())
            if val:
                cur["fields"][cur_key] = (val, lineno)
            else:
                cur["lists"].setdefault(cur_key, [])
    return tasks


def validate_fix_tasks(text: str) -> tuple[list[dict], list[str]]:
    """Return (tasks, schema errors naming the offending lines) of a generated fix-task file."""
    tasks = parse_fix_tasks(text)
    if not tasks:
        return [], ["line 1: no fix tasks found (expected a YAML list, each task starting with "
                    "'- title:')"]

    errors: list[str] = []
    for index, task in enumerate(tasks, 1):
        line = task["line"]
        fields, lists = task["fields"], task["lists"]
        title = fields.get("title", ("", line))[0]
        for key in FIX_TASK_REQUIRED:
            present = bool(fields.get(key, ("", 0))[0] or lists.get(key))
            if not present:
                errors.append(f"line {line}: task {index} '{title}' missing required field "
                              f"'{key}'")
        task_type = fields.get("task_type")
        if task_type and task_type[0] not in TASK_TYPES:
            errors.append(f"line {task_type[1]}: task {index} '{title}' has invalid task_type "
                          f"'{task_type[0]}' (expected one of {', '.join(TASK_TYPES)})")
    return tasks, errors


def cmd_validate_fix_tasks(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.file)
    if not path.is_file():
        print(f"FAIL - file not found: {path}", file=sys.stderr)
        return 1

    tasks, errors = validate_fix_tasks(path.read_text(encoding="utf-8"))
    if errors:
        print("FAIL - invalid fix-task file:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"ok - {path.name} is a valid fix-task file ({len(tasks)} task(s))")
    return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_name = sub.add_parser("name", help="print the project name (basename of the resolved path)")
    p_name.add_argument("--repo", required=True, help="Path to the target project")
    p_name.set_defaults(func=cmd_name)

    p_init = sub.add_parser("init", help="create memory files if they are missing (never overwrites)")
    p_init.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_init.add_argument("--project", default="",
                        help="Project name (default: basename of the resolved deploy root)")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check",
                             help="verify that memory belongs to a single project and repository")
    p_check.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_check.add_argument("--expect", default="",
                         help="Expected project name (wins over the identity and name bases)")
    p_check.add_argument("--no-owner-check", action="store_true",
                         help="Do not compare the owner at all (the summary/journal agreement and "
                              "the format checks still run)")
    p_check.add_argument("--run-id", default="",
                         help="Require exactly one record carrying this run_id (implies --strict)")
    p_check.add_argument("--strict", action="store_true",
                         help="Turn every '## Current state' divergence from the live state into "
                              "an error instead of a warning")
    p_check.add_argument("--allow-fresh", action="store_true",
                         help="Accept a memory/ without change-log.md (deliberately journal-less)")
    p_check.set_defaults(func=cmd_check)

    p_rename = sub.add_parser("rename",
                              help="rewrite the project name in the journal and the summary")
    p_rename.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_rename.add_argument("--to", required=True, help="New project name")
    p_rename.set_defaults(func=cmd_rename)

    p_backlog = sub.add_parser("backlog",
                               help="fold the open critical/follow_up items and their closures")
    p_backlog.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_backlog.add_argument("--check", action="store_true",
                           help="Exit 1 unless no open item disappeared silently (every one carried "
                                "in the current record with a 'reason:', or closed) and every "
                                "'closed:' element is valid")
    p_backlog.add_argument("--run-id", default="",
                           help="Treat the record carrying this run_id as the current one "
                                "(default: the last record of the journal)")
    p_backlog.add_argument("--json", action="store_true", help="Print the report as JSON")
    p_backlog.set_defaults(func=cmd_backlog)

    p_compact_do = sub.add_parser("compact",
                                  help="fold the oldest journal records into memory/summary.md")
    p_compact_do.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_compact_do.add_argument("--threshold", type=int, default=50,
                              help="Compact only above this many records (default: 50)")
    p_compact_do.add_argument("--keep", type=int, default=20,
                              help="Records kept in the journal after compaction (default: 20)")
    p_compact_do.add_argument("--dry-run", action="store_true",
                              help="Print the plan and write nothing")
    p_compact_do.set_defaults(func=cmd_compact)

    p_compact = sub.add_parser("compact-check",
                               help="verify that compaction kept critical/follow_up items")
    p_compact.add_argument("--before", required=True, help="Journal or summary before compaction")
    p_compact.add_argument("--after", required=True, help="Compacted summary (or journal)")
    p_compact.set_defaults(func=cmd_compact_check)

    p_fix = sub.add_parser("validate-fix-tasks",
                           help="validate a generated security_audit fix-task file")
    p_fix.add_argument("file", help="Path to the generated fix-tasks.yaml")
    p_fix.set_defaults(func=cmd_validate_fix_tasks)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

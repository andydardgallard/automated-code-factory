#!/usr/bin/env python3
"""
Deterministic check of the Code Factory's project model (zero LLM tokens).

Checks six invariants of the durable project model:
  1. AGENTS.md exists and has EXACTLY the 8 canonical `##` sections.
  2. The fingerprint line embedded in AGENTS.md (line 1) matches the fingerprints recomputed
     from the project's current signals. The current format carries BOTH levels:
     `<!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->`.
     A structural mismatch means the project structure/stack/entry points changed, and a
     content mismatch means a tracked file changed without touching the structural signals
     (edits at depth >= 2) — both are errors, because either way the model is stale and must
     be regenerated. The LEGACY single-hash format is still accepted, but only with a WARNING
     (it cannot see content-only changes); its structural hash is still verified.
     The content level hashes the tracked WORKING-TREE content, so an untracked file does not show
     up in it: such a worktree is reported with a WARNING — never an error, because the model
     itself may well be up to date and untracked files are outside the tracked content by
     definition (exit code stays 0). `git add` lifts a file out of that blind spot into
     `git ls-files`, so a staged-new file DOES move the content hash from then on.
  3. The portable long-term memory is well-formed: `memory/change-log.md` is an
     append-only journal (each entry has the required keys, plus the optional
     `unfinished`, `factory_version` and `project` keys) and `memory/summary.md` exists with
     the canonical marker.
  4. One memory belongs to exactly ONE project: `memory/` is the long-term memory of the
     project from the task's `repo_path` field, whose name every entry carries as
     `project: <name>`. Entries without `project` are legacy (warning only), while DIFFERENT
     `project` values in the same journal — or a `summary.md` declaring another project — are
     errors, and so is a `project` key that is present but empty (never silent legacy).
  5. Memory format v2 (introduced after factory 12.8.0): the records of a current-generation
     factory carry `run_id: <YYYYMMDD>-<8 hex>` (`scripts/run_id.py`) and a provenance mark —
     `[verified: <evidence>]` or `[inferred]` — in BOTH `decisions` and `results`, so a claim
     in the memory is distinguishable from a guess. A v2 record without them (or with a
     malformed `run_id`) is an error; records that predate the format and legacy records
     without `project:` only warn, exactly like the other newer keys.
  6. The WIP checkpoint `.code-factory/state/pipeline.yaml`, when it exists, carries the
     required top-level keys `run_id`, `phase`, `status`, `updated_at` (plus the optional
     `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`, `models_used`),
     with `status` in ok/failed/in_progress and a well-formed `run_id`. A project without a
     checkpoint is a SKIP, never a failure.

Usage:
  python check_factory_model.py [--repo <path>] [--memory-only]

  --memory-only   skip the AGENTS.md checks (sections + fingerprints) and only validate
                  the memory files and the WIP checkpoint.

The factory's OWN root is auto-detected by THREE signals that must hold together: line 1 of
`AGENTS.md` carries NO `code-factory-fingerprint` marker, it DOES carry the factory's own
`code-factory-version` marker (the hand-authored manual starts with
`<!-- code-factory-version: X.Y.Z -->`), and `<repo>/.agents/skills/code-factory/SKILL.md` is
deployed next to it. Such a root holds the factory's hand-authored manual, not a generated
8-section model — the AGENTS.md checks are then a SKIP with a note (memory and the WIP checkpoint
are still validated), so the factory's own root passes without `--memory-only`. The version marker
is what keeps that detector narrow: `prepare_factory` deploys the flow skill into EVERY target
project, so the skill alone would turn an ordinary target project with a hand-authored AGENTS.md
into a SKIP instead of the documented `line 1 must be …` error. Every project without the
fingerprint is still an error, and a fingerprint that is PRESENT but stale stays an error
everywhere (the model exists and must be regenerated).

Exit code 0 = PASS, 1 = FAIL (each failure printed to stderr). Warnings are printed to
stderr but do not fail (legacy memory missing the newer optional keys or the `project:`
ownership declaration; legacy single-hash fingerprint line; UNTRACKED files, which the
tracked-content fingerprint does not cover). A project without a WIP checkpoint prints
`SKIP - …`, which is not a failure either. stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from project_fingerprint import compute_content_fingerprint, compute_fingerprint, untracked_files

CANONICAL_SECTIONS = [
    "Project Overview",
    "Technology Stack",
    "Architecture Overview",
    "Directory Structure",
    "Key Configuration Files",
    "Build & Run Instructions",
    "Dependencies & Integrations",
    "Known Constraints & Limitations",
]

# Line 1 of a generated AGENTS.md. The `content:` part is optional so a legacy (single-hash)
# model is still accepted — with a warning, see `check_agents_model`.
FINGERPRINT_RE = re.compile(
    r"^<!--\s*code-factory-fingerprint:\s*([0-9a-f]{64})"
    r"(?:\s+content:\s*([0-9a-f]{64}))?\s*-->$"
)
FINGERPRINT_HINT = "<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->"
# Marker that identifies a GENERATED AGENTS.md model. Its absence in line 1 is what makes a model
# hand-authored — see `_is_factory_own_root`.
FINGERPRINT_MARKER = "code-factory-fingerprint"
# The factory's OWN version marker: the hand-authored manual at the factory's root starts with
# `<!-- code-factory-version: X.Y.Z -->`. It is a REQUIRED signal of the factory-own-root detector
# (see `_is_factory_own_root`), because no generated model and no target project carries it.
VERSION_MARKER = "code-factory-version"
# The factory's flow skill. Its presence next to a version-marked, fingerprint-less AGENTS.md is the
# third signal of the factory-own-root detector: a target project the factory still has to model
# lacks the version marker, and that one must stay an error. The skill ALONE is useless as a signal
# — `prepare_factory` deploys it into EVERY target project.
FACTORY_SKILL_REL = ".agents/skills/code-factory/SKILL.md"
CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
ENTRY_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}.*)$")
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Three CAPTURING groups on purpose: `_v2_record` compares the version tuple against
# MEMORY_V2_AFTER, so a non-capturing pattern would silently disable the version trigger
# (empty `groups()` -> never newer). Kept identical to `memory_project.py`.
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# Memory format v2: `run_id` (see scripts/run_id.py) and provenance marks. A record must carry
# them once it comes from a factory NEWER than 12.8.0 (the release the format is introduced
# after) — or as soon as it already carries a v2 field, so a half-migrated record is caught too
# (see `_record_format_issues`).
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
PROVENANCE_RE = re.compile(r"\[verified:[^\[\]]+\]|\[inferred\]")
MEMORY_V2_AFTER = (12, 8, 0)
# The optional WIP checkpoint of a run in flight (see scripts/run_id.py ARTIFACT_GLOBS). The
# optional keys — `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`,
# `models_used` — are validated when present, but only the required ones are listed here.
PIPELINE_REL = ".code-factory/state/pipeline.yaml"
PIPELINE_REQUIRED = ("run_id", "phase", "status", "updated_at")
PIPELINE_STATUSES = {"ok", "failed", "in_progress"}
# `project: <name>` declaration of the owning project in memory/summary.md. It counts ONLY
# inside the declaration area (right after the canonical marker, before the first `## ` section),
# so a `project: <name>` example inside a fenced code block is never mistaken for a declaration.
SUMMARY_PROJECT_RE = re.compile(r"^project:\s*(\S.*)$", re.MULTILINE)

ENTRY_REQUIRED_KEYS = [
    "title", "timestamp", "branch", "commit", "task_type", "goal",
    "changed_files", "created_files", "results", "decisions", "assumptions",
    "models_used",
]
# Newer keys. Missing in a legacy entry is a WARNING (never an error), so the project
# history is not broken when the format evolves. `project` names the project that OWNS the
# memory (basename of the task's resolved `repo_path`): its absence in an old entry is just a
# legacy warning, but DIFFERENT `project` values inside the same journal are an error —
# one memory belongs to exactly one project. `run_id` is NOT listed here on purpose: its
# legacy warning is gated by the v2 rule (`_record_format_issues`), otherwise every record
# written before the format would warn and canonical memories would stop being warning-free.
ENTRY_OPTIONAL_KEYS = ["unfinished", "factory_version", "project"]
TASK_TYPES = {"implement", "review", "refactor", "security_audit"}
RESULT_SUBKEYS = ["integration", "regression", "business", "review"]
UNFINISHED_SEVERITIES = {"critical", "warning", "info"}
UNFINISHED_BOOLS = {"true", "false"}


def _is_factory_own_root(root: pathlib.Path, first_line: str) -> bool:
    """True when `root` is the factory's OWN root, whose AGENTS.md is a hand-authored manual.

    Three signals, ALL required: line 1 of AGENTS.md carries no `code-factory-fingerprint` marker
    (a generated model always does), it DOES carry the factory's own `code-factory-version` marker
    (the hand-authored manual starts with `<!-- code-factory-version: X.Y.Z -->`), and the factory's
    flow skill `<root>/.agents/skills/code-factory/SKILL.md` is deployed next to it. The skill alone
    would be far too wide a signal: `prepare_factory` deploys it into EVERY target project, so a
    target project with a hand-authored AGENTS.md would silently become a SKIP instead of the
    documented `line 1 must be …` error — the version marker is what separates the two. A project
    whose fingerprint IS there takes the normal path, where a stale fingerprint is an error — the
    skip never swallows an existing-but-stale model.
    """
    return (FINGERPRINT_MARKER not in first_line
            and VERSION_MARKER in first_line
            and (root / FACTORY_SKILL_REL).is_file())


def check_agents_model(root: pathlib.Path) -> tuple[list[str], list[str], str]:
    """Return (errors, warnings, skip note) for the AGENTS.md model (empty lists/note = OK).

    The factory's own root has no generated model to validate — its AGENTS.md is the factory's
    hand-authored manual, not an 8-section model with a fingerprint — so it yields a non-empty skip
    note instead of errors (see `_is_factory_own_root`); the caller prints `SKIP - …`. Memory and
    the WIP checkpoint are out of scope here and are still validated by the caller.

    A WARNING (never an error) is added when the worktree holds UNTRACKED files: the content level
    hashes the tracked working-tree content, so untracked files are legitimately outside the model
    and the model may still be up to date.
    """
    errors: list[str] = []
    warnings: list[str] = []
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md not found"], warnings, ""

    lines = agents.read_text(encoding="utf-8").splitlines()
    first = lines[0] if lines else ""

    if _is_factory_own_root(root, first):
        return [], warnings, (f"AGENTS.md is the factory's own hand-authored manual "
                              f"(no '{FINGERPRINT_MARKER}' marker, '{VERSION_MARKER}' present, "
                              f"{FACTORY_SKILL_REL} present): AGENTS.md model checks skipped")

    m = FINGERPRINT_RE.match(first.strip())
    if not m:
        errors.append(f"AGENTS.md line 1 must be '{FINGERPRINT_HINT}'")
    else:
        embedded, embedded_content = m.group(1), m.group(2)
        current = compute_fingerprint(root)
        if embedded != current:
            errors.append(f"fingerprint mismatch: embedded={embedded[:12]}… != current={current[:12]}…")
        if embedded_content is None:
            warnings.append("AGENTS.md line 1 uses the legacy single-hash fingerprint (no "
                            "'content:' part): content-only changes are invisible to the model "
                            f"— regenerate AGENTS.md as '{FINGERPRINT_HINT}'")
        else:
            current_content = compute_content_fingerprint(root)
            if embedded_content != current_content:
                errors.append("content fingerprint mismatch: "
                              f"embedded={embedded_content[:12]}… != current={current_content[:12]}…")
            # The content level hashes the TRACKED working-tree content (see
            # project_fingerprint.py), so untracked files are outside it: report them, don't fail.
            untracked = untracked_files(root)
            if untracked:
                warnings.append(f"worktree holds {len(untracked)} untracked file(s): the content "
                                "fingerprint hashes the tracked content (git ls-files) and does not "
                                "cover them (add them to git to make them visible)")

    headings = [ln.strip() for ln in lines if ln.startswith("## ")]
    missing = [s for s in CANONICAL_SECTIONS if f"## {s}" not in headings]
    extra = [h for h in headings if h not in {f"## {s}" for s in CANONICAL_SECTIONS}]
    if missing:
        errors.append(f"missing sections: {missing}")
    if extra:
        errors.append(f"unexpected sections: {extra}")
    return errors, warnings, ""


def check_agents(root: pathlib.Path) -> list[str]:
    """Errors only for the AGENTS.md model (empty = OK); see `check_agents_model` for warnings
    and for the skip note of the factory's own root."""
    return check_agents_model(root)[0]


def _parse_entry_body(body: list[str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Parse an entry body into flat KV fields plus the structured `unfinished` item list."""
    fields: dict[str, str] = {}
    items: list[dict[str, str]] = []
    cur_item: dict[str, str] | None = None
    in_unfinished = False
    for raw in body:
        line = raw.rstrip()
        if not line.strip():
            continue
        m = KV_RE.match(line)
        if m and not line.startswith((" ", "\t", "-")):
            key, val = m.group(1), m.group(2).strip()
            fields[key] = val
            in_unfinished = (key == "unfinished" and val == "")
            cur_item = None
            continue
        if in_unfinished:
            item_m = re.match(r"^\s*-\s*item:\s*(.*)$", line)
            if item_m:
                cur_item = {"item": item_m.group(1).strip()}
                items.append(cur_item)
                continue
            sub_m = re.match(r"^\s*(reason|severity|follow_up):\s*(.*)$", line)
            if sub_m and cur_item is not None:
                cur_item[sub_m.group(1)] = sub_m.group(2).strip()
    return fields, items


def _v2_record(fields: dict[str, str]) -> bool:
    """True when an entry has to satisfy the memory format v2 (run_id + provenance marks).

    That is the case once the entry comes from a factory version NEWER than the one that
    introduced the format (MEMORY_V2_AFTER), or as soon as it already carries a v2 field —
    `run_id` or a provenance mark — so a half-migrated record is not silently accepted.
    Entries without `project` are legacy and are only ever warned about, like the other
    newer keys; entries written before the format stay as they are (no error, no warning).
    """
    if not fields.get("project", "").strip():
        return False
    version = VERSION_RE.match(fields.get("factory_version", "") or "")
    newer = bool(version) and tuple(int(g) for g in version.groups()) > MEMORY_V2_AFTER
    return newer or "run_id" in fields or any(
        PROVENANCE_RE.search(fields.get(f, "")) for f in ("decisions", "results"))


def _record_format_issues(heading: str, fields: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) of the memory format v2 for one entry (see `_v2_record`).

    A v2 entry must carry a well-formed `run_id` and at least one provenance mark in
    `decisions` AND in `results`; a miss is an error there, a warning in a legacy entry.
    """
    problems: list[str] = []
    run_id = fields.get("run_id", "").strip()
    if not run_id:
        problems.append("missing or empty key 'run_id'")
    elif not RUN_ID_RE.match(run_id):
        problems.append(f"invalid run_id '{run_id}' (expected YYYYMMDD-<8 hex>)")
    for field in ("decisions", "results"):
        if not PROVENANCE_RE.search(fields.get(field, "")):
            problems.append(f"no provenance mark '[verified: <evidence>]' or '[inferred]' "
                            f"in '{field}'")
    if not problems:
        return [], []
    if _v2_record(fields):
        return [f"entry '{heading}': {p}" for p in problems], []
    if not fields.get("project", "").strip():
        return [], [f"entry '{heading}': {p} (legacy format)" for p in problems]
    return [], []


def _validate_entry(heading: str, fields: dict[str, str],
                    items: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ENTRY_REQUIRED_KEYS:
        if key not in fields:
            errors.append(f"entry '{heading}': missing key '{key}'")
    for key in ENTRY_OPTIONAL_KEYS:
        if key not in fields:
            warnings.append(f"entry '{heading}': missing key '{key}' (legacy format)")
    if "project" in fields and not fields["project"].strip():
        errors.append(f"entry '{heading}': empty 'project' value")
    if "task_type" in fields and fields["task_type"] not in TASK_TYPES:
        errors.append(f"entry '{heading}': invalid task_type '{fields['task_type']}'")
    if "timestamp" in fields and not TIMESTAMP_RE.search(fields["timestamp"]):
        errors.append(f"entry '{heading}': timestamp not ISO-date-like '{fields['timestamp']}'")
    if "results" in fields:
        for sub in RESULT_SUBKEYS:
            if f"{sub}=" not in fields["results"]:
                errors.append(f"entry '{heading}': results missing '{sub}='")
    if "factory_version" in fields and not VERSION_RE.match(fields["factory_version"]):
        errors.append(f"entry '{heading}': invalid factory_version '{fields['factory_version']}'")
    fmt_errors, fmt_warnings = _record_format_issues(heading, fields)
    errors.extend(fmt_errors)
    warnings.extend(fmt_warnings)

    if "unfinished" in fields and fields["unfinished"] == "" and not items:
        errors.append(f"entry '{heading}': 'unfinished' is empty without items or a no-debt marker")
    for it in items:
        for sub in ("item", "reason", "severity", "follow_up"):
            if sub not in it:
                errors.append(f"entry '{heading}': unfinished item missing '{sub}'")
        if "severity" in it and it["severity"] not in UNFINISHED_SEVERITIES:
            errors.append(f"entry '{heading}': invalid unfinished severity '{it['severity']}'")
        if "follow_up" in it and it["follow_up"] not in UNFINISHED_BOOLS:
            errors.append(f"entry '{heading}': invalid unfinished follow_up '{it['follow_up']}'")
    return errors, warnings


def _summary_declaration_area(text: str) -> str:
    """Return the part of memory/summary.md that may declare the owning project.

    It spans from the canonical summary marker to the first `## ` section (or EOF); anything
    below — e.g. a `project: <name>` example inside a fenced code block — is ignored.
    """
    lines = text.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if SUMMARY_MARKER in ln), None)
    if start is None:
        return ""
    area: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("## "):
            break
        area.append(ln)
    return "\n".join(area)


def validate_memory(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the memory files (empty lists = OK)."""
    errors: list[str] = []
    warnings: list[str] = []
    memdir = root / "memory"
    change_log = memdir / "change-log.md"
    summary = memdir / "summary.md"
    # Projects declared by the journal entries (empty = legacy memory without `project`).
    journal_projects: set[str] = set()

    if not change_log.is_file():
        errors.append("memory/change-log.md not found")
    else:
        text = change_log.read_text(encoding="utf-8")
        if CHANGE_LOG_MARKER not in text:
            errors.append("memory/change-log.md missing canonical marker")
        # Parse entries: each `## ` line starts an entry; body = lines until the next.
        lines = text.splitlines()
        entries: list[tuple[str, list[str]]] = []
        cur_head: str | None = None
        cur_body: list[str] = []
        for ln in lines:
            m = ENTRY_RE.match(ln.strip())
            if m:
                if cur_head is not None:
                    entries.append((cur_head, cur_body))
                cur_head = m.group(1)
                cur_body = []
            elif cur_head is not None:
                cur_body.append(ln)
        if cur_head is not None:
            entries.append((cur_head, cur_body))
        for head, body in entries:
            fields, items = _parse_entry_body(body)
            project = fields.get("project", "").strip()
            if project:
                journal_projects.add(project)
            e, w = _validate_entry(head, fields, items)
            errors.extend(e)
            warnings.extend(w)
        if len(journal_projects) > 1:
            errors.append("memory/change-log.md mixes projects: "
                          + ", ".join(sorted(journal_projects))
                          + " (one memory belongs to exactly one project)")

    if not summary.is_file():
        errors.append("memory/summary.md not found")
    else:
        summary_text = summary.read_text(encoding="utf-8")
        if SUMMARY_MARKER not in summary_text:
            errors.append("memory/summary.md missing canonical marker")
        declared = SUMMARY_PROJECT_RE.search(_summary_declaration_area(summary_text))
        declared_project = declared.group(1).strip() if declared else ""
        if not declared_project:
            warnings.append("memory/summary.md does not declare 'project: <name>' (legacy format)")
        elif len(journal_projects) == 1 and declared_project not in journal_projects:
            errors.append(f"memory/summary.md declares project '{declared_project}' but "
                          f"memory/change-log.md belongs to "
                          f"'{next(iter(journal_projects))}'")
    return errors, warnings


def _scalar_or_none(value: str) -> object:
    """Turn the inline value of a `key: value` line into its Python form.

    An empty value stays `None`, which the validators report as missing. The empty flow
    collections `[]` and `{}` are the empty list / mapping they spell, not opaque strings, so a
    checkpoint writing `files_touched: []` satisfies the contract of that key instead of failing
    the type check.
    """
    if value == "[]":
        return []
    if value == "{}":
        return {}
    return value or None


def _parse_flat_yaml(text: str) -> dict[str, object]:
    """Parse the flat YAML subset the pipeline checkpoint uses (no PyYAML in the factory).

    A top-level `key: value` is a scalar (or an empty flow collection, see `_scalar_or_none`); a
    top-level `key:` without a value opens a block of indented children — `- item` lines make it a
    list, `sub: value` lines a mapping. Comments and blank lines are skipped, and anything nested
    deeper is folded into the same block (`retry_counters`/`models_used` are one level deep by
    contract). A key declared with an empty value and no children stays `None`, which the validators
    report as missing.
    """
    data: dict[str, object] = {}
    cur: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            m = KV_RE.match(line)
            if m:
                cur = m.group(1)
                data[cur] = _scalar_or_none(m.group(2).strip())
            continue
        if cur is None:
            continue
        body = line.strip()
        if body.startswith("- "):
            block = data.get(cur)
            if not isinstance(block, list):
                block = []
                data[cur] = block
            block.append(body[2:].strip())
        else:
            m = KV_RE.match(body)
            if m:
                block = data.get(cur)
                if not isinstance(block, dict):
                    block = {}
                    data[cur] = block
                block[m.group(1)] = m.group(2).strip()
    return data


def check_pipeline_checkpoints(root: pathlib.Path) -> tuple[list[str], str]:
    """Return (errors, skip note) for the WIP checkpoint of a run in flight.

    Everything wrong with a checkpoint is an ERROR (there is nothing to warn about), so the
    function returns no warning list. `.code-factory/state/pipeline.yaml` is optional — a project
    without a run in progress has none — so an absent file yields a non-empty skip note and never
    an error. When it exists it must carry the required top-level keys `run_id`, `phase`,
    `status`, `updated_at`, with `status` in ok/failed/in_progress and `run_id` shaped
    `YYYYMMDD-<8 hex>` (scripts/run_id.py). The optional keys (`files_touched` list,
    `pending_decision`, `resume_hint`, `retry_counters` and `models_used` mappings) are validated
    when present; unknown keys are tolerated, so a checkpoint may carry extra run state.
    """
    path = root / PIPELINE_REL
    if not path.is_file():
        return [], f"{PIPELINE_REL} not found (no WIP checkpoint to validate)"

    data = _parse_flat_yaml(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key in PIPELINE_REQUIRED:
        if data.get(key) is None:
            errors.append(f"{PIPELINE_REL}: missing or empty required key '{key}'")
    run_id = data.get("run_id")
    if isinstance(run_id, str) and not RUN_ID_RE.match(run_id):
        errors.append(f"{PIPELINE_REL}: invalid run_id '{run_id}' (expected YYYYMMDD-<8 hex>)")
    status = data.get("status")
    if isinstance(status, str) and status not in PIPELINE_STATUSES:
        errors.append(f"{PIPELINE_REL}: invalid status '{status}' (expected one of "
                      f"{', '.join(sorted(PIPELINE_STATUSES))})")
    updated_at = data.get("updated_at")
    if isinstance(updated_at, str) and not TIMESTAMP_RE.search(updated_at):
        errors.append(f"{PIPELINE_REL}: updated_at is not ISO-date-like '{updated_at}'")
    for key, kind, kind_name in (("files_touched", list, "list"),
                                 ("retry_counters", dict, "mapping"),
                                 ("models_used", dict, "mapping")):
        block = data.get(key)
        if block is not None and not isinstance(block, kind):
            errors.append(f"{PIPELINE_REL}: optional key '{key}' must be a {kind_name}")
    return errors, ""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries
    non-ASCII characters (the em dash `—` and the ellipsis `…`), which that codec cannot encode:
    `print_help()` would raise UnicodeEncodeError and the user would get a traceback instead of
    the help. `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
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
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    ap.add_argument("--memory-only", action="store_true",
                    help="Only validate memory files + the WIP checkpoint, skip AGENTS.md checks")
    args = ap.parse_args()

    root = pathlib.Path(args.repo).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    a_skip = ""
    if args.memory_only:
        errors, warnings = validate_memory(root)
    else:
        a_errs, a_warns, a_skip = check_agents_model(root)
        m_errs, m_warns = validate_memory(root)
        errors += a_errs
        errors += m_errs
        warnings += a_warns
        warnings += m_warns

    # A hand-authored AGENTS.md at the factory's own root is a SKIP: there is no generated model to
    # validate there. Memory and the WIP checkpoint are still checked below.
    if a_skip:
        print("SKIP - " + a_skip, file=sys.stderr)

    # The WIP checkpoint is validated in both modes: it belongs to the run, not to the model.
    p_errs, p_skip = check_pipeline_checkpoints(root)
    errors += p_errs
    if p_skip:
        print("SKIP - " + p_skip, file=sys.stderr)
    elif not p_errs:
        print(f"ok - WIP checkpoint {PIPELINE_REL} is valid")

    for w in warnings:
        print("WARN - " + w, file=sys.stderr)

    if errors:
        print("FAIL - factory model check:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1

    scope = "memory" if (args.memory_only or a_skip) else "AGENTS.md + memory"
    if a_skip:
        scope += " — AGENTS.md check skipped"
    checkpoint = "no WIP checkpoint" if p_skip else f"WIP checkpoint {PIPELINE_REL} valid"
    print(f"PASS - factory model is consistent ({scope}; {checkpoint}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

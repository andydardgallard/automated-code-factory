#!/usr/bin/env python3
"""
Deterministic check of the Code Factory's project model (zero LLM tokens).

Checks six invariants of the durable project model:
  1. AGENTS.md exists, is not oversized and has EXACTLY the 8 canonical `##` sections. The SIZE
     gate (`project_fingerprint.agents_size_issues`, one implementation for both paths) warns over
     28 KB and FAILS over 32 KB — it runs before the factory-own-root skip, because the factory's
     own hand-authored manual is the file that once grew to 38 KB. An instruction file nobody can
     load is not a model, it is a book.
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
     append-only journal (each record satisfies the record contract: its required keys, a
     `task_type` from the record kinds, the `results` sub-keys of that kind) and
     `memory/summary.md` exists with the canonical marker. This check is NOT implemented here:
     `validate_memory` below is a thin delegation to `memory_project.validate_memory`, so the
     memory contract exists exactly once and the two CLIs cannot diverge again (they used to
     implement it twice by hand and disagreed on six axes — owner, `task_type: backlog`,
     required keys, `results` sub-keys, an empty `project:` and `closed:` without `evidence:`).
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

A MISSING journal is a hard error here: this checker validates a project that already has a
modelled AGENTS.md, i.e. one the factory has worked in. `memory_project.py check` is the CLI that
tells the two states apart — a `memory/` that does not exist at all is a FRESH project (a note,
exit 0) while a `memory/` WITHOUT `change-log.md` is broken (exit 1, `--allow-fresh` overrides).
The shared `validate_memory` reports a missing journal as an error, and each CLI decides only its
own asymmetry; neither one hides it.

Usage:
  python check_factory_model.py [--repo <path>] [--memory-only]
                                [--expect <name>] [--no-owner-check] [--strict]

  --memory-only   skip the AGENTS.md checks (sections + fingerprints) and only validate
                  the memory files and the WIP checkpoint.
  --expect        Expected memory owner; wins over the summary's `project_id:`, the declared
                  `repo_path:` and the directory name (same flag as `memory_project.py check`).
  --no-owner-check do not compare the memory owner at all (the rest of the memory contract, the
                  journal/summary agreement included, still runs).
  --strict        turn a `## Current state` divergence from the live state into an error instead
                  of a warning (same flag as `memory_project.py check`).

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
ownership declaration; a memory record written before the format v2 — warned, never rewritten;
legacy single-hash fingerprint line; UNTRACKED files, which the tracked-content fingerprint does
not cover). A project without a WIP checkpoint prints `SKIP - …`, which is not a failure either.
stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import memory_project
from project_fingerprint import (agents_size_issues, compute_content_fingerprint,
                                 compute_fingerprint, untracked_files)

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
# The flat-YAML subset of the WIP checkpoint (`_parse_flat_yaml`): a `key: value` line.
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# `run_id` (see scripts/run_id.py): validated on the checkpoint below and on the memory records by
# `memory_project.record_format_issues` (the memory contract lives there, not here).
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
# The optional WIP checkpoint of a run in flight (see scripts/run_id.py ARTIFACT_GLOBS). The
# optional keys — `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`,
# `models_used` — are validated when present, but only the required ones are listed here.
PIPELINE_REL = ".code-factory/state/pipeline.yaml"
PIPELINE_REQUIRED = ("run_id", "phase", "status", "updated_at")
PIPELINE_STATUSES = {"ok", "failed", "in_progress"}


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

    The SIZE gate runs FIRST and applies to every root, the factory's own hand-authored manual
    included: an AGENTS.md over 28 KB is a WARNING, over 32 KB an ERROR (validation side of
    `project_fingerprint.agents_size_issues`). It is measured before the factory-own-root SKIP on
    purpose — a skip must never hide an oversized instruction file, which is exactly the file the
    owner complained about.
    """
    errors: list[str] = []
    warnings: list[str] = []
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md not found"], warnings, ""

    size_warning, size_error = agents_size_issues(agents.stat().st_size)
    if size_error:
        errors.append(size_error)
    elif size_warning:
        warnings.append(size_warning)

    lines = agents.read_text(encoding="utf-8").splitlines()
    first = lines[0] if lines else ""

    if _is_factory_own_root(root, first):
        return errors, warnings, (f"AGENTS.md is the factory's own hand-authored manual "
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


def _v2_record(fields: dict[str, str]) -> bool:
    """True when a record has to satisfy the memory format v2 (run_id + provenance marks).

    A THIN ALIAS of `memory_project.is_v2_record` — the predicate has exactly one implementation,
    on the memory side, and this name is kept because the self-tests pin it (they prove the
    version TRIGGER works: a record of a factory newer than 12.8.0 without a single v2 field is
    still a v2 record). Do not grow a second copy of the rule here.
    """
    return memory_project.is_v2_record(fields)


def validate_memory(root: pathlib.Path, expect: str = "", no_owner_check: bool = False,
                    strict: bool = False, run_id: str = "") -> tuple[list[str], list[str]]:
    """Return (errors, warnings) of the memory contract — a THIN DELEGATION, not a copy.

    The contract itself (required keys, the record kinds, the `results` sub-keys of a kind, the
    owner chain, the format v2, one run — one record, the `closed:`/`evidence:` protocol and the
    `## Current state` actuality) lives in `memory_project.validate_memory`, which is the ONE
    implementation both CLIs print. This wrapper keeps the historical entry point and the flags
    identical between the two scripts (`--expect`, `--no-owner-check`, `--strict`), so the model
    check can never disagree with `memory_project.py check` again.

    A missing journal is an error here (see the module docstring): this checker validates a
    project that already has a modelled AGENTS.md, so its memory must exist — the fresh-project
    case is `memory_project.py check`'s alone.
    """
    return memory_project.validate_memory(root, expect, no_owner_check, strict, run_id)


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
    # The same flags as `memory_project.py check`: the memory contract is ONE implementation, so
    # a project must not have to remember which of the two CLIs accepts which switch.
    ap.add_argument("--expect", default="",
                    help="Expected memory owner; wins over the summary's project_id:, the declared "
                         "repo_path: and the directory name")
    ap.add_argument("--no-owner-check", action="store_true",
                    help="Do not compare the memory owner (the rest of the memory contract, the "
                         "journal/summary agreement included, still runs)")
    ap.add_argument("--strict", action="store_true",
                    help="Turn every '## Current state' divergence from the live state into an "
                         "error instead of a warning")
    args = ap.parse_args()

    root = pathlib.Path(args.repo).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    a_skip = ""
    mem_args = (args.expect, args.no_owner_check, args.strict)
    if args.memory_only:
        errors, warnings = validate_memory(root, *mem_args)
    else:
        a_errs, a_warns, a_skip = check_agents_model(root)
        m_errs, m_warns = validate_memory(root, *mem_args)
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

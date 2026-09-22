#!/usr/bin/env python3
"""
Deterministic check of the Code Factory's project model (zero LLM tokens).

Checks four invariants of the durable project model:
  1. AGENTS.md exists and has EXACTLY the 8 canonical `##` sections.
  2. The fingerprint line embedded in AGENTS.md (line 1) matches the fingerprints recomputed
     from the project's current signals. The current format carries BOTH levels:
     `<!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->`.
     A structural mismatch means the project structure/stack/entry points changed, and a
     content mismatch means a tracked file changed without touching the structural signals
     (edits at depth >= 2) — both are errors, because either way the model is stale and must
     be regenerated. The LEGACY single-hash format is still accepted, but only with a WARNING
     (it cannot see content-only changes); its structural hash is still verified.
  3. The portable long-term memory is well-formed: `memory/change-log.md` is an
     append-only journal (each entry has the required keys, plus the optional
     `unfinished`, `factory_version` and `project` keys) and `memory/summary.md` exists with
     the canonical marker.
  4. One memory belongs to exactly ONE project: `memory/` is the long-term memory of the
     project from the task's `repo_path` field, whose name every entry carries as
     `project: <name>`. Entries without `project` are legacy (warning only), while DIFFERENT
     `project` values in the same journal — or a `summary.md` declaring another project — are
     errors, and so is a `project` key that is present but empty (never silent legacy).

Usage:
  python check_factory_model.py [--repo <path>] [--memory-only]

  --memory-only   skip the AGENTS.md checks (sections + fingerprints) and only validate
                  the memory files. Useful for the factory's own root, whose AGENTS.md
                  is a hand-authored manual rather than a generated 8-section model.

Exit code 0 = PASS, 1 = FAIL (each failure printed to stderr). Warnings are printed to
stderr but do not fail (legacy memory missing the newer optional keys or the `project:`
ownership declaration; legacy single-hash fingerprint line). stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from project_fingerprint import compute_content_fingerprint, compute_fingerprint

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
CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
ENTRY_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}.*)$")
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
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
# one memory belongs to exactly one project.
ENTRY_OPTIONAL_KEYS = ["unfinished", "factory_version", "project"]
TASK_TYPES = {"implement", "review", "refactor", "security_audit"}
RESULT_SUBKEYS = ["integration", "regression", "business", "review"]
UNFINISHED_SEVERITIES = {"critical", "warning", "info"}
UNFINISHED_BOOLS = {"true", "false"}


def check_agents_model(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the AGENTS.md model (empty lists = OK)."""
    errors: list[str] = []
    warnings: list[str] = []
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md not found"], warnings

    lines = agents.read_text(encoding="utf-8").splitlines()
    first = lines[0] if lines else ""

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

    headings = [ln.strip() for ln in lines if ln.startswith("## ")]
    missing = [s for s in CANONICAL_SECTIONS if f"## {s}" not in headings]
    extra = [h for h in headings if h not in {f"## {s}" for s in CANONICAL_SECTIONS}]
    if missing:
        errors.append(f"missing sections: {missing}")
    if extra:
        errors.append(f"unexpected sections: {extra}")
    return errors, warnings


def check_agents(root: pathlib.Path) -> list[str]:
    """Errors only for the AGENTS.md model (empty = OK); see `check_agents_model` for warnings."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    ap.add_argument("--memory-only", action="store_true",
                    help="Only validate memory files, skip AGENTS.md checks")
    args = ap.parse_args()

    root = pathlib.Path(args.repo).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if args.memory_only:
        errors, warnings = validate_memory(root)
    else:
        a_errs, a_warns = check_agents_model(root)
        m_errs, m_warns = validate_memory(root)
        errors += a_errs
        errors += m_errs
        warnings += a_warns
        warnings += m_warns

    for w in warnings:
        print("WARN - " + w, file=sys.stderr)

    if errors:
        print("FAIL - factory model check:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1

    scope = "memory" if args.memory_only else "AGENTS.md + memory"
    print(f"PASS - factory model is consistent ({scope}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

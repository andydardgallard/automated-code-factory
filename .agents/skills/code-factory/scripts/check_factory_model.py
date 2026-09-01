#!/usr/bin/env python3
"""
Deterministic check of the Code Factory's project model (zero LLM tokens).

Checks three invariants of the durable project model:
  1. AGENTS.md exists and has EXACTLY the 8 canonical `##` sections.
  2. The fingerprint embedded in AGENTS.md matches the fingerprint recomputed from the
     project's current structural signals (project unchanged -> model is current).
  3. The portable long-term memory is well-formed: `memory/change-log.md` is an
     append-only journal (each entry has the required keys) and `memory/summary.md`
     exists with the canonical marker.

Usage:
  python3 check_factory_model.py [--repo <path>] [--memory-only]

  --memory-only   skip the AGENTS.md checks (sections + fingerprint) and only validate
                  the memory files. Useful for the factory's own root, whose AGENTS.md
                  is a hand-authored manual rather than a generated 8-section model.

Exit code 0 = PASS, 1 = FAIL (each failure printed to stderr). stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from project_fingerprint import compute_fingerprint

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

FINGERPRINT_RE = re.compile(r"^<!--\s*code-factory-fingerprint:\s*([0-9a-f]{64})\s*-->$")
CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
ENTRY_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}.*)$")
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

ENTRY_KEYS = [
    "title", "timestamp", "branch", "commit", "task_type", "goal",
    "changed_files", "created_files", "results", "decisions", "assumptions",
    "models_used",
]
TASK_TYPES = {"implement", "review", "refactor", "security_audit"}
RESULT_SUBKEYS = ["integration", "regression", "business", "review"]


def check_agents(root: pathlib.Path) -> list[str]:
    """Return a list of errors for the AGENTS.md model (empty = OK)."""
    errors: list[str] = []
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md not found"]

    lines = agents.read_text(encoding="utf-8").splitlines()
    first = lines[0] if lines else ""

    m = FINGERPRINT_RE.match(first.strip())
    if not m:
        errors.append("AGENTS.md line 1 must be '<!-- code-factory-fingerprint: <64-hex> -->'")
    else:
        embedded = m.group(1)
        current = compute_fingerprint(root)
        if embedded != current:
            errors.append(f"fingerprint mismatch: embedded={embedded[:12]}… != current={current[:12]}…")

    headings = [ln.strip() for ln in lines if ln.startswith("## ")]
    missing = [s for s in CANONICAL_SECTIONS if f"## {s}" not in headings]
    extra = [h for h in headings if h not in {f"## {s}" for s in CANONICAL_SECTIONS}]
    if missing:
        errors.append(f"missing sections: {missing}")
    if extra:
        errors.append(f"unexpected sections: {extra}")
    return errors


def _parse_entry_body(body: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in body:
        m = KV_RE.match(line.rstrip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def _validate_entry(heading: str, fields: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key in ENTRY_KEYS:
        if key not in fields:
            errors.append(f"entry '{heading}': missing key '{key}'")
    if "task_type" in fields and fields["task_type"] not in TASK_TYPES:
        errors.append(f"entry '{heading}': invalid task_type '{fields['task_type']}'")
    if "timestamp" in fields and not TIMESTAMP_RE.search(fields["timestamp"]):
        errors.append(f"entry '{heading}': timestamp not ISO-date-like '{fields['timestamp']}'")
    if "results" in fields:
        for sub in RESULT_SUBKEYS:
            if f"{sub}=" not in fields["results"]:
                errors.append(f"entry '{heading}': results missing '{sub}='")
    return errors


def validate_memory(root: pathlib.Path) -> list[str]:
    """Return a list of errors for the memory files (empty = OK)."""
    errors: list[str] = []
    memdir = root / "memory"
    change_log = memdir / "change-log.md"
    summary = memdir / "summary.md"

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
            errors.extend(_validate_entry(head, _parse_entry_body(body)))

    if not summary.is_file():
        errors.append("memory/summary.md not found")
    elif SUMMARY_MARKER not in summary.read_text(encoding="utf-8"):
        errors.append("memory/summary.md missing canonical marker")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    ap.add_argument("--memory-only", action="store_true",
                    help="Only validate memory files, skip AGENTS.md checks")
    args = ap.parse_args()

    root = pathlib.Path(args.repo).resolve()
    errors: list[str] = []
    if args.memory_only:
        errors = validate_memory(root)
    else:
        errors = check_agents(root) + validate_memory(root)

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

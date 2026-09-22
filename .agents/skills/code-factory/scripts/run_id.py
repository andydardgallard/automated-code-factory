#!/usr/bin/env python3
"""
Deterministic run id of a Code Factory run, plus the artifact-provenance check.

The run id is `<YYYYMMDD>-<first 8 hex of the SHA-256 of the task file bytes>`: the local date the
run started plus a content-derived suffix. It is reproducible from the artifacts alone (no clock
state is stored) and two different tasks never share an id, so every artifact of a run can be
traced back to the exact task it came from. Scripts that write artifacts embed it as
`run_id: <id>` in the header of the file they produce.

Usage:
  python run_id.py gen --task .code-factory/state/task.yaml
  python run_id.py check --dir .code-factory

`gen` prints the run id and exits 0 (an unreadable task file is an error, exit 1). `check` scans
the artifacts a run carries — `state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`,
`report.md` — and exits 1 after listing every EXISTING artifact that has no `run_id: <id>` or
`run_id=<id>` line. Any id counts: the goal is that the artifact is attributed to a run, not that
it matches the current one. Missing artifacts and an empty or absent directory are not an error
(exit 0), so a run passes the check until it writes its first artifact. stdlib only, Windows/POSIX.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys
from datetime import date

# An artifact is marked when it carries `run_id: <id>` or `run_id=<id>` (any id, not the current one).
RUN_ID_LINE = re.compile(r"run_id\s*[:=]\s*\S+")
ARTIFACT_GLOBS = ("state/pipeline.yaml", "state/acceptance.md", "logs/*.md", "report.md")


def compute_run_id(task: pathlib.Path, today: date | None = None) -> str:
    """Run id of the task file: local date + first 8 hex of the SHA-256 of its bytes.

    Raises ValueError with a human-readable cause when the task file cannot be read — an id
    derived from a missing file would be a silently wrong provenance, exactly what this module
    exists to prevent.
    """
    try:
        digest = hashlib.sha256(task.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"cannot read task file {task}: {exc}") from exc
    return f"{(today or date.today()):%Y%m%d}-{digest[:8]}"


def artifact_paths(root: pathlib.Path) -> list[pathlib.Path]:
    """Existing artifacts of a run, in the fixed order of ARTIFACT_GLOBS."""
    found: list[pathlib.Path] = []
    for pattern in ARTIFACT_GLOBS:
        found.extend(sorted(root.glob(pattern)))
    return found


def has_run_id(text: str) -> bool:
    """True when the artifact text carries a `run_id: <id>` / `run_id=<id>` line."""
    return bool(RUN_ID_LINE.search(text))


def unmarked_artifacts(root: pathlib.Path) -> list[str]:
    """Relative paths of existing artifacts without a run_id line, sorted and de-duplicated.

    An unreadable artifact counts as unmarked: provenance that cannot be verified is not proven.
    """
    unmarked: set[str] = set()
    for path in artifact_paths(root):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if not has_run_id(text):
            unmarked.add(rel)
    return sorted(unmarked)


def cmd_gen(args: argparse.Namespace) -> int:
    try:
        print(compute_run_id(pathlib.Path(args.task)))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.dir)
    unmarked = unmarked_artifacts(root)
    if not unmarked:
        total = len([p for p in artifact_paths(root) if p.is_file()])
        print(f"run_id: every existing artifact under {root} carries a run_id "
              f"({total} checked)")
        return 0
    for rel in unmarked:
        print(rel)
    print(f"run_id: {len(unmarked)} existing artifact(s) without a run_id: "
          f"expected a 'run_id: <id>' or 'run_id=<id>' line", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen", help="Print the run id derived from a task file")
    gen.add_argument("--task", required=True, help="Task file (task.yaml) the run id derives from")
    gen.set_defaults(func=cmd_gen)

    check = sub.add_parser("check", help="List existing .code-factory artifacts without a run_id")
    check.add_argument("--dir", required=True, help=".code-factory directory of the run")
    check.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

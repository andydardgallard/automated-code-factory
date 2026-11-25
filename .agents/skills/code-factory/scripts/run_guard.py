#!/usr/bin/env python3
"""
Deterministic single-active-run guard: ONE active run per TARGET REPO, enforced repo-side.

The factory works with the repository named by the task's `repo_path`, not the folder it was
launched from. Two factories launched from the SAME folder into DIFFERENT repositories must both
run, so single occupancy is a property of the TARGET REPO, and it must fail closed LOUDLY before
the first checkpoint write instead of being discovered halfway through a phase.

Usage:
  python run_guard.py claim --repo <root> --run-id <YYYYMMDD-8hex>
  python run_guard.py status --repo <root>

`claim` decides whether `--run-id` may work in the target repo: no checkpoint, a TERMINAL
checkpoint (`status: ok` / `failed`) or the run's OWN resume (`run_id` equal to `--run-id`) is
CLAIMED (exit 0); a DIFFERENT active run is REFUSED (exit 1) with a message naming the blocking
run, its phase, its `updated_at` and the resolution (finish or roll back that run first). An active
checkpoint without a `run_id` is UNIDENTIFIABLE, so it can never be "the same run": it fails closed
with the same refusal. A status that is neither terminal nor `in_progress` is treated as ACTIVE
(an unknown state must never free a repository). `status` is the read-only probe (exit 0, free or
occupied).

The guard is a CHECK, not a lock: it writes NOTHING (no lock file, no migrated checkpoint, no
`.code-factory/` conjured into a bare repo), which is what lets two runs into two repos share one
launch folder. The TOCTOU window is a deliberate minimal choice; the hard fail-closed backstops
stay downstream (bind-run destination refusal, activate single-owner, `init --repo` refusal).

The checkpoint is read through `delegation_gate`'s shared reader (ONE contract, CRLF preserved);
only the top-level scalars this guard needs are picked out of that text. A malformed `--run-id` or
an unusable `--repo` is exit 2 with an actionable message and never a traceback: a bad id must
never silently claim a repo. stdlib only, Windows/POSIX.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The guard may be loaded BY PATH (a test harness): the shared checkpoint reader must be
    # importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
import delegation_gate  # noqa: E402  (the ONE checkpoint reader, imported after the path setup)

RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
TOP_LEVEL = re.compile(r"^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$")
TERMINAL_STATUSES = frozenset({"ok", "failed"})
FIELDS = ("run_id", "phase", "status", "updated_at")


class GuardError(ValueError):
    """An input this script cannot honour: a message + exit 2, never a traceback."""


def _scalar(text: str, key: str) -> str | None:
    """The top-level `key: <scalar>` value of the checkpoint text, quotes removed (None: absent)."""
    for line in text.splitlines():
        entry = TOP_LEVEL.match(line)
        if entry and entry.group(1) == key:
            value = entry.group(2)
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                return value[1:-1]
            return value.split(" #")[0].strip()
    return None


def _checked_repo(repo: str) -> pathlib.Path:
    if not repo.strip():                         # blank would silently mean the caller's cwd
        raise GuardError("--repo is blank: pass the target repository root (the task's repo_path)")
    root = pathlib.Path(repo).resolve()
    if not root.is_dir():
        raise GuardError(f"--repo is not a directory: {root} (pass the target repository root)")
    return root


def _checked_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise GuardError(f"--run-id {run_id!r} is not a run id: expected YYYYMMDD-<8 lowercase "
                         f"hex> (for example 20261125-5beb8e51), the id `run_id.py gen` prints")
    return run_id


def read_checkpoint(root: pathlib.Path) -> dict[str, str | None] | None:
    """The checkpoint's top-level scalars, or None when the repo has no checkpoint at all."""
    path = root / delegation_gate.PIPELINE_REL
    if not path.is_file():
        return None
    try:
        text = delegation_gate._read_pipeline(path)
    except delegation_gate.GateError as exc:     # exists but unreadable: fail closed, not open
        raise GuardError(str(exc)) from exc
    return {key: _scalar(text, key) for key in FIELDS}


def describe(state: dict[str, str | None]) -> str:
    """The checkpoint's run, phase, status and timestamp as one readable phrase."""
    run_id = state.get("run_id") or "<unidentified run>"
    return (f"run {run_id} (phase {state.get('phase') or 'unknown'}, "
            f"status {state.get('status') or 'unknown'}, "
            f"updated_at {state.get('updated_at') or 'unknown'})")


def blocking_owner(state: dict[str, str | None], run_id: str) -> str:
    """Why `run_id` may not claim this checkpoint, or "" when the claim is free."""
    if (state.get("status") or "") in TERMINAL_STATUSES:
        return ""
    if (state.get("run_id") or "") == run_id:
        return ""
    return (f"another run is active in this repository: {describe(state)} has not finished - "
            f"finish or roll back that run first, then claim again")


def cmd_claim(args: argparse.Namespace) -> int:
    root = _checked_repo(args.repo)
    run_id = _checked_run_id(args.run_id)
    state = read_checkpoint(root)
    reason = "" if state is None else blocking_owner(state, run_id)
    if reason:
        print(f"REFUSED - {reason} (nothing was written)", file=sys.stderr)
        return 1
    print(f"CLAIMED - {run_id} may work in {root} (the guard is a check, not a lock: "
          f"nothing was written)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = _checked_repo(args.repo)
    state = read_checkpoint(root)
    if state is None:
        print(f"FREE - no WIP checkpoint in {root}: an active run may claim it")
    elif (state.get("status") or "") in TERMINAL_STATUSES:
        print(f"FREE - {describe(state)} is finished: an active run may claim {root}")
    else:
        print(f"OCCUPIED - {describe(state)} is active in {root}: a different run must wait")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    claim = sub.add_parser("claim", help="Decide whether a run may work in the target repository")
    claim.add_argument("--repo", required=True, metavar="ROOT",
                       help="Target repository root (the task's repo_path)")
    claim.add_argument("--run-id", required=True, metavar="ID",
                       help="The claiming run's id: YYYYMMDD-<8 lowercase hex>")
    claim.set_defaults(func=cmd_claim)

    status = sub.add_parser("status", help="Report the active run of a repository (read-only)")
    status.add_argument("--repo", required=True, metavar="ROOT",
                        help="Target repository root (the task's repo_path)")
    status.set_defaults(func=cmd_status)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

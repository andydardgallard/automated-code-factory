#!/usr/bin/env python3
"""
Rollback of the factory's change set (zero LLM tokens, stdlib only, portable).

WHY THIS EXISTS

`references/verification-strategy.md` §4.3 requires a rollback that removes the files a run
CREATED and restores the ones it CHANGED from their backups. The documented example did it in
Bash: it joined `created_files` as STRINGS although `manifest.py` stores OBJECTS
(`{"path", "sha256"}` — a TypeError against the first real manifest), and it used process
substitution (`<(...)`) that cmd.exe does not have. A rollback that crashes on the real manifest,
or that only exists on one shell, is no rollback. This helper is the ONE implementation: pure
Python, so it behaves the same under cmd.exe, PowerShell and every POSIX shell.

THE CONTRACT

  `python rollback.py --repo <root> [--dry-run]`
      reads `<root>/.code-factory/manifest.json` (the object manifest `manifest.py` writes),
      extracts every `created_files`/`changed_files` entry's `path`, and validates EVERY path as
      confined to the repository — reusing `manifest.py`'s own confinement — BEFORE a single byte
      is touched: an absolute, drive-qualified, `..`-carrying or symlink-escaping entry, or a
      changed file whose backup is missing, BLOCKS the whole operation (exit 1). There is no
      partial rollback. Only then does it delete the created files (an already-absent one is
      reported, not an error) and restore each changed file from
      `.code-factory/backups/<same relative path>` through a temp file + atomic replace, so a
      failed restore never leaves a truncated target.
  `--dry-run` runs the SAME validation and prints the plan without touching the tree.

  The git side of the rollback (reset/switch/branch deletion) stays with the main agent, as
  §4.3 documents; this helper is the file side only.

EXIT CODES

  0  rolled back (or, with --dry-run, the plan validated)
  1  BLOCKED: an unconfined manifest entry or a missing backup — nothing was touched
  2  usage/input error: a bad `--repo`, a missing/unparsable manifest (a message, never a
     traceback)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The helper may be loaded BY PATH (a test harness): the sibling module it reuses must be
    # importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from manifest import (BACKUP_REL, MANIFEST_REL, Blocked, ManifestError,  # noqa: E402
                      confined_relpath, read_manifest, use_utf8_output)


def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise ManifestError(f"repository root does not exist: {root}")
    return root


def _posix(root: pathlib.Path, relpath: str) -> pathlib.Path:
    return root / pathlib.PurePosixPath(relpath)


# -------------------------------------------------------------------------------------------- plan

def validate(root: pathlib.Path) -> dict:
    """The WHOLE rollback plan, validated before anything destructive happens.

    Every manifest path is re-confined to the repository (a manifest is a file on disk: an entry
    may have been written by hand or by an older version, and an absolute, traversal or
    symlinked path must never be joined to the repo and deleted as if it were confined), and
    every changed file must still have its backup. One bad entry blocks EVERYTHING: a partial
    rollback leaves the tree in a state no step of the flow knows.
    """
    manifest = read_manifest(root)
    problems: list[str] = []
    created: list[str] = []
    changed: list[str] = []
    for entry in manifest["created_files"]:
        try:
            created.append(confined_relpath(root, entry["path"]))
        except ManifestError as exc:
            problems.append(f"unconfined created_files entry {entry['path']!r}: {exc}")
    for entry in manifest["changed_files"]:
        try:
            relpath = confined_relpath(root, entry["path"])
        except ManifestError as exc:
            problems.append(f"unconfined changed_files entry {entry['path']!r}: {exc}")
            continue
        backup = root / BACKUP_REL / pathlib.PurePosixPath(relpath)
        if not backup.is_file():
            problems.append(f"{relpath}: registered as changed but its backup "
                            f"{backup} is missing — restoring it is impossible")
            continue
        changed.append(relpath)
    if problems:
        listing = "\n  ".join(problems)
        raise Blocked(f"the rollback was NOT performed — {len(problems)} blocking problem(s) in "
                      f"{root / MANIFEST_REL}, and no file was touched:\n  {listing}")
    return {"created": created, "changed": changed}


# -------------------------------------------------------------------------------------------- execute

def _delete_created(root: pathlib.Path, relpath: str) -> str:
    """Delete one created file; `absent` when it is already gone (idempotent, not an error)."""
    target = _posix(root, relpath)
    try:
        if target.is_symlink() or target.is_file():
            target.unlink()
            return "deleted"
        if not target.exists():
            return "absent"
    except OSError as exc:
        raise ManifestError(f"cannot remove the created file {target}: {exc}") from exc
    raise ManifestError(f"{relpath}: registered as created but {target} is not a plain file")


def _restore_changed(root: pathlib.Path, relpath: str) -> None:
    """Restore one changed file from its backup, atomically (temp file + replace)."""
    backup = root / BACKUP_REL / pathlib.PurePosixPath(relpath)
    target = _posix(root, relpath)
    temp = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = backup.read_bytes()
        fd, temp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".",
                                    suffix=".tmp")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, target)
    except OSError as exc:
        if temp:
            pathlib.Path(temp).unlink(missing_ok=True)
        raise ManifestError(f"cannot restore {relpath} from {backup}: {exc}") from exc


def rollback(repo: str | pathlib.Path, dry_run: bool = False) -> dict:
    root = _checked_repo(repo)
    plan = validate(root)
    deleted: list[str] = []
    absent: list[str] = []
    restored: list[str] = []
    for relpath in plan["created"]:
        if dry_run:
            (deleted if _posix(root, relpath).exists() else absent).append(relpath)
        elif _delete_created(root, relpath) == "deleted":
            deleted.append(relpath)
        else:
            absent.append(relpath)
    for relpath in plan["changed"]:
        if not dry_run:
            _restore_changed(root, relpath)
        restored.append(relpath)
    return {"status": "dry-run" if dry_run else "rolled-back", "dry_run": dry_run,
            "repo": str(root), "manifest": str(root / MANIFEST_REL),
            "deleted": deleted, "already_absent": absent, "restored": restored}


# -------------------------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rollback.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and print the plan without touching the tree")
    return ap


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        print(json.dumps(rollback(args.repo, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    except Blocked as exc:
        print(f"rollback.py: BLOCKED - {exc}", file=sys.stderr)
        return 1
    except ManifestError as exc:
        print(f"rollback.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

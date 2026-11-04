#!/usr/bin/env python3
"""
Manifest enforcement for the factory's change set (zero LLM tokens, stdlib only).

WHY THIS EXISTS

The rulebook requires `.code-factory/manifest.json` — the list of files a run CHANGED and CREATED —
before the first source edit, and a backup of every file that will be changed (rule
`artifacts-first`). Until this script the manifest was written BY HAND by the main agent: nothing
refused a run that edited a source file with no manifest at all, nothing proved a changed file had a
backup, and the hashes could be typed instead of computed. A claim about what the run touched is not
evidence; this script computes it.

THE CONTRACT

  `.code-factory/manifest.json` is JSON:
      {"run_id": "<YYYYMMDD>-<8 hex>",
       "changed_files": [{"path": "<repo-relative>", "sha256": "<64 lowercase hex>"}, ...],
       "created_files": [...]}
  Entries are sorted by path, so the file is byte-deterministic for the same change set.

  `init --repo <root>`      create the manifest from the run's checkpoint (`run_id` is read from
                            `.code-factory/state/pipeline.yaml` and format-checked). An existing
                            manifest WITH entries is never overwritten (exit 1); an empty skeleton
                            is reusable, so a restarted run may re-init it.
  `require --repo <root>`   the PRE-EDIT gate the flow calls before it touches a source file:
                            exit 1 with an actionable message when the manifest is absent.
  `add --repo <root> --changed <path>` / `--created <path>`
                            register exactly ONE repo-relative path per call, with the sha256 this
                            script computes from the file's current bytes (never typed by hand).
                            A CHANGED file must already have its backup at
                            `.code-factory/backups/<same relative path>` — editing without a backup
                            is a BLOCKING error (exit 1), because rollback impossible is worse than a
                            red gate. A CREATED file must not be an existing tracked file and must
                            not have a backup (both mean it predates the run: register it as
                            changed), and a path is changed OR created, never both.
  `audit --repo <root>`     the FINISH audit: the manifest exists and parses, every entry has a
                            repo-relative path and a 64-hex hash, no path is listed twice, every
                            registered file still exists, every CHANGED file still has its backup,
                            and every hash still matches the working tree (drift is named).

PATH CONFINEMENT: every `--changed`/`--created` path must be a plain repository-relative path — an
absolute path, a drive letter, a `..` segment, or a path that resolves (through a symlink) outside
the repository is refused with exit 2 and nothing is written.

EXIT CODES

  0  success (init/require/add/audit passed; `add` may report `unchanged`)
  1  a BLOCKING violation: a missing manifest on `require`/`add`, a changed file without its
     backup, a created file that predates the run, a conflicting registration, an existing manifest
     that `init` refuses to overwrite, or an `audit` drift
  2  usage/input error: a bad `--repo`, a path that is not a confined repository-relative path, a
     malformed or missing `run_id`, an unreadable/unparsable manifest (a message, never a traceback)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

MANIFEST_REL = pathlib.Path(".code-factory") / "manifest.json"
BACKUP_REL = pathlib.Path(".code-factory") / "backups"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
CHANGED, CREATED = "changed", "created"


class ManifestError(ValueError):
    """An input this script cannot honour: reported as a message + exit 2, never a traceback."""


class Blocked(Exception):
    """A BLOCKING violation (exit 1): the run must not proceed as it asked."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the messages survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise ManifestError(f"repository root does not exist: {root}")
    return root


def _resolved(path: str | pathlib.Path) -> str:
    """`path` with every symlink resolved; a path that does not exist YET resolves through its
    nearest existing ancestor (so a target under a symlinked directory is still seen)."""
    current = pathlib.Path(os.path.abspath(str(path)))
    missing: list[str] = []
    while not os.path.lexists(str(current)) and current.parent != current:
        missing.append(current.name)
        current = current.parent
    resolved = pathlib.Path(os.path.realpath(str(current)))
    for name in reversed(missing):
        resolved = resolved / name
    return os.path.normcase(str(resolved))


def _within(child: str | pathlib.Path, parent: str | pathlib.Path) -> bool:
    """`True` when the RESOLVED `child` is strictly inside the RESOLVED `parent`."""
    child_s, parent_s = _resolved(child), _resolved(parent)
    if child_s == parent_s:
        return False
    try:
        return os.path.commonpath([child_s, parent_s]) == parent_s
    except ValueError:                             # different drive letters on Windows
        return False


def confined_relpath(root: pathlib.Path, raw: str) -> str:
    """The repo-relative POSIX path of `raw`, or an input error naming why it is not confined.

    Absolute paths, drive letters, `..` segments and paths that resolve outside the repository
    (through a symlink) are refused: the manifest of a run may only describe files of THAT
    repository, and a path that escapes it cannot be backed up or audited.
    """
    text = (raw or "").strip().replace("\\", "/")
    if not text:
        raise ManifestError("a path is required (repo-relative, e.g. src/main.py)")
    candidate = pathlib.PurePosixPath(text)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", text):
        raise ManifestError(f"{raw!r} is an absolute path: the manifest records repository-relative "
                            f"paths only")
    if any(part == ".." for part in candidate.parts):
        raise ManifestError(f"{raw!r} contains a '..' segment: a path that leaves the repository "
                            f"cannot be backed up or audited")
    if any(part in ("", ".") for part in candidate.parts):
        raise ManifestError(f"{raw!r} is not a plain file path")
    target = root / candidate
    if not _within(target, root):
        raise ManifestError(f"{raw!r} resolves outside the repository root {root} (a symlinked "
                            f"directory?): the manifest may only describe files of this repository")
    return candidate.as_posix()


def sha256_file(path: pathlib.Path) -> str:
    """The lowercase 64-hex sha256 of a file's CURRENT bytes (computed here, never typed)."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def pipeline_run_id(root: pathlib.Path) -> str:
    """The run's `run_id`, read from the checkpoint and format-checked."""
    path = root / PIPELINE_REL
    if not path.is_file():
        raise ManifestError(f"no WIP checkpoint at {path}: the flow writes it (with the run_id) at "
                            f"the start of a run, before a manifest can be created")
    run_id = ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = RUN_ID_LINE.match(line.rstrip())
            if match and not run_id:
                run_id = match.group(1).strip().strip("'\"")
                break
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if not RUN_ID_RE.match(run_id):
        raise ManifestError(f"{path} carries run_id {run_id!r}, which is not "
                            f"YYYYMMDD-<8 lowercase hex> (scripts/run_id.py gen computes it)")
    return run_id


# ----------------------------------------------------------------------------------------- manifest

def _empty_manifest(run_id: str) -> dict:
    return {"run_id": run_id, "changed_files": [], "created_files": []}


def read_manifest(root: pathlib.Path) -> dict:
    """The parsed manifest; an absent/malformed/ill-shaped one is an input error (exit 2)."""
    path = root / MANIFEST_REL
    if not path.is_file():
        raise ManifestError(f"no manifest at {path}: run `manifest.py init --repo {root}` first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    for kind in (CHANGED, CREATED):
        key = f"{kind}_files"
        entries = data.get(key)
        if not isinstance(entries, list):
            raise ManifestError(f"{path}: '{key}' must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ManifestError(f"{path}: every '{key}' entry must be an object with a 'path'")
    data.setdefault("run_id", "")
    return data


def _entries(manifest: dict, kind: str) -> list[dict]:
    return manifest[f"{kind}_files"]


def _write_manifest(root: pathlib.Path, manifest: dict) -> pathlib.Path:
    """Write the manifest deterministically and ATOMICALLY (skeleton preserved, entries sorted).

    A filesystem failure is DATA: it names the path and the OS reason and exits 2, and the manifest
    the run already had stays byte-identical — a half-written change set is worse than none.
    """
    payload = {"run_id": manifest.get("run_id", "")}
    for kind in (CHANGED, CREATED):
        payload[f"{kind}_files"] = sorted(
            ({"path": entry["path"], "sha256": entry["sha256"]} for entry in _entries(manifest, kind)),
            key=lambda entry: entry["path"])
    path = root / MANIFEST_REL
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    except OSError as exc:
        raise ManifestError(f"cannot write the manifest {path}: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise ManifestError(f"cannot write the manifest {path} (the previous one is untouched): "
                            f"{exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise
    return path


def _backup_path(root: pathlib.Path, relpath: str) -> pathlib.Path:
    return root / BACKUP_REL / pathlib.Path(relpath)


def require(root: pathlib.Path) -> dict:
    """The pre-edit gate: a run may not touch a source file before its manifest exists."""
    root = _checked_repo(root)
    try:
        manifest = read_manifest(root)
    except ManifestError as exc:
        raise Blocked(f"{exc}; the run must not edit a source file before "
                      f"{MANIFEST_REL.as_posix()} exists (rule artifacts-first)") from exc
    return {"status": "present", "run_id": manifest.get("run_id", ""),
            "manifest": str(root / MANIFEST_REL)}


def init(root: pathlib.Path) -> dict:
    """Create the manifest; an existing one with entries is never overwritten."""
    root = _checked_repo(root)
    run_id = pipeline_run_id(root)
    path = root / MANIFEST_REL
    if path.is_file():
        existing = read_manifest(root)
        entries = len(_entries(existing, CHANGED)) + len(_entries(existing, CREATED))
        if entries:
            raise Blocked(f"{path} already lists {entries} file(s): a manifest is created ONCE per "
                          f"run — a second init would forget the change set the run already "
                          f"registered")
        if existing.get("run_id") == run_id:
            return {"status": "unchanged", "run_id": run_id, "manifest": str(path),
                    "changed": 0, "created": 0}
        _write_manifest(root, _empty_manifest(run_id))
        return {"status": "reinitialized", "run_id": run_id, "manifest": str(path),
                "changed": 0, "created": 0}
    _write_manifest(root, _empty_manifest(run_id))
    return {"status": "created", "run_id": run_id, "manifest": str(path), "changed": 0,
            "created": 0}


def _tracked(root: pathlib.Path, relpath: str) -> bool | None:
    """Is `relpath` tracked by git? `None` when git cannot answer (no git, or not a repository)."""
    try:
        res = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--",
                              relpath], capture_output=True)
    except OSError:
        return None
    if res.returncode == 0:
        return True
    if res.returncode == 1:                        # git answered: not tracked
        return False
    return None                                    # not a repository / a git error


def add(root: pathlib.Path, kind: str, raw_path: str) -> dict:
    """Register ONE file with the sha256 of its current bytes (the `kind` is changed or created)."""
    root = _checked_repo(root)
    if kind not in (CHANGED, CREATED):
        raise ManifestError(f"unknown kind {kind!r}: use --changed or --created")
    relpath = confined_relpath(root, raw_path)
    try:
        manifest = read_manifest(root)
    except ManifestError as exc:
        raise Blocked(f"{exc}; the run must not edit a source file before "
                      f"{MANIFEST_REL.as_posix()} exists (rule artifacts-first)") from exc
    target = root / pathlib.PurePosixPath(relpath)
    if not target.is_file():
        raise Blocked(f"{relpath} is not a file under {root}: the manifest records the files the run "
                       f"touched, and a path that does not exist cannot be hashed")
    other = CREATED if kind == CHANGED else CHANGED
    if any(entry["path"] == relpath for entry in _entries(manifest, other)):
        raise Blocked(f"{relpath} is already registered as {other}: a file is CHANGED or CREATED, "
                       f"never both")
    backup = _backup_path(root, relpath)
    if kind == CHANGED:
        if not backup.is_file():
            raise Blocked(f"{relpath} has no backup at {backup}: a file is only registered as "
                          f"changed after `.code-factory/backups/<same relative path>` holds its "
                          f"pre-edit bytes — rollback without a backup is impossible, so the run "
                          f"must back the file up before editing it (rule artifacts-first)")
    else:
        if backup.exists():
            raise Blocked(f"{relpath} has a backup at {backup}: a file that predates the run is "
                          f"CHANGED, not created — register it with --changed")
        tracked = _tracked(root, relpath)
        if tracked:
            raise Blocked(f"{relpath} is tracked by git, so it existed before this run: register it "
                          f"with --changed (and keep its backup), never as created")
    digest = sha256_file(target)
    entries = _entries(manifest, kind)
    existing = next((entry for entry in entries if entry["path"] == relpath), None)
    status = "added"
    if existing is not None:
        if existing.get("sha256") == digest:
            return {"status": "unchanged", "kind": kind, "path": relpath, "sha256": digest,
                    "manifest": str(root / MANIFEST_REL)}
        existing["sha256"] = digest
        status = "rehashed"
    else:
        entries.append({"path": relpath, "sha256": digest})
    path = _write_manifest(root, manifest)
    return {"status": status, "kind": kind, "path": relpath, "sha256": digest,
            "manifest": str(path)}


def audit(root: pathlib.Path) -> dict:
    """The finish audit: the manifest exists, is well formed, hashed, backed up and undrifted."""
    root = _checked_repo(root)
    path = root / MANIFEST_REL
    if not path.is_file():
        raise Blocked(f"no manifest at {path}: the change set of the run is unrecorded — run "
                      f"`manifest.py init --repo {root}` and register every file")
    manifest = read_manifest(root)
    problems: list[str] = []
    if not RUN_ID_RE.match(str(manifest.get("run_id", ""))):
        problems.append(f"run_id {manifest.get('run_id')!r} is not YYYYMMDD-<8 lowercase hex>")
    seen: dict[str, str] = {}
    for kind in (CHANGED, CREATED):
        for entry in _entries(manifest, kind):
            relpath = entry["path"]
            digest = entry.get("sha256", "")
            # The audit revalidates the path it is about to join to the repo: a manifest entry may
            # have been written by hand (or by an older version), and an absolute, traversal or
            # symlinked path must never be read as if it were confined.
            try:
                relpath = confined_relpath(root, relpath)
            except ManifestError as exc:
                problems.append(f"unconfined manifest entry {entry['path']!r}: {exc}")
                continue
            if relpath in seen:
                problems.append(f"{relpath} is listed twice ({seen[relpath]} and {kind})")
                continue
            seen[relpath] = kind
            if not SHA256_RE.match(str(digest)):
                problems.append(f"{relpath}: sha256 is not 64 lowercase hex ({digest!r})")
                continue
            target = root / pathlib.PurePosixPath(relpath)
            if not target.is_file():
                problems.append(f"{relpath}: registered as {kind} but missing from the working tree")
                continue
            if sha256_file(target) != digest:
                problems.append(f"{relpath}: DRIFT — the working tree no longer matches the "
                                f"registered sha256 (the file changed after it was registered)")
            if kind == CHANGED and not _backup_path(root, relpath).is_file():
                problems.append(f"{relpath}: registered as changed but its backup "
                                f"{_backup_path(root, relpath)} is missing")
    result = {"status": "failed" if problems else "ok", "manifest": str(path),
              "run_id": manifest.get("run_id", ""),
              "changed": len(_entries(manifest, CHANGED)),
              "created": len(_entries(manifest, CREATED)), "problems": problems}
    return result


# -------------------------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="manifest.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create .code-factory/manifest.json for this run")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("require", help="pre-edit gate: fail when the manifest is absent")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_require)

    p = sub.add_parser("add", help="register ONE changed or created file with its sha256")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--changed", metavar="PATH",
                       help="a pre-existing file the run modified (its backup must exist first)")
    group.add_argument("--created", metavar="PATH", help="a file the run created")
    p.set_defaults(func=_cmd_add)

    p = sub.add_parser("audit", help="finish audit: hashes, backups and completeness")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_audit)
    return ap


def _cmd_init(args: argparse.Namespace) -> int:
    print(json.dumps(init(args.repo), ensure_ascii=False))
    return 0


def _cmd_require(args: argparse.Namespace) -> int:
    print(json.dumps(require(args.repo), ensure_ascii=False))
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    kind = CHANGED if args.changed is not None else CREATED
    raw = args.changed if args.changed is not None else args.created
    print(json.dumps(add(args.repo, kind, raw), ensure_ascii=False))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    result = audit(args.repo)
    print(json.dumps(result, ensure_ascii=False))
    if result["problems"]:
        print(f"manifest.py: BLOCKED - the manifest audit found {len(result['problems'])} "
              f"problem(s):", file=sys.stderr)
        for problem in result["problems"]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    use_utf8_output()
    ap = build_parser()
    args = ap.parse_args()
    try:
        return args.func(args)
    except Blocked as exc:
        print(f"manifest.py: BLOCKED - {exc}", file=sys.stderr)
        return 1
    except ManifestError as exc:
        print(f"manifest.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Contract test for `manifest.py` — the run's change set, computed instead of claimed (zero tokens).

WHY THIS EXISTS

`.code-factory/manifest.json` is the list of files a run CHANGED and CREATED, and the rulebook
requires it before the first source edit together with a backup of every changed file. Until this
script the manifest was written by hand: nothing refused a run that edited a source file with no
manifest at all, nothing proved a changed file had a backup, and a hash could be typed instead of
computed. This test pins the enforcement:

  - `require` fails (exit 1, actionable) while the manifest is absent — the pre-edit gate;
  - `init` takes the run_id from the checkpoint (format-checked), is deterministic, reuses an EMPTY
    skeleton, and never overwrites a manifest that already lists files;
  - `add --changed` BLOCKS a file with no backup at `.code-factory/backups/<same path>`, records the
    sha256 the script computed (64 lowercase hex) and re-hashes a re-edited file;
  - `add --created` refuses a path that predates the run (tracked by git, or one that has a backup)
    and refuses a file already registered under the other kind;
  - every path is confined to the repository: absolute, drive-qualified, `..`-escaping and
    symlink-escaping paths are refused (exit 2) and nothing is written;
  - `audit` reports drift, a missing file, a missing backup and a malformed entry, and exits 1;
  - the argparse contract: `--help` exit 0 for every subcommand, a usage error exit 2, no traceback.

Exit code 0 = every assertion passes, 1 = the script did not behave as the contract says.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("manifest.py")
MANIFEST_REL = pathlib.Path(".code-factory") / "manifest.json"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
RUN_ID = "20261103-8e939171"
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr and "Traceback" not in res.stdout,
          f"{label}: no traceback allowed: {res.stderr!r}")


def payload(res: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}


def repo(tmp: pathlib.Path, name: str, run_id: str | None = RUN_ID) -> pathlib.Path:
    """A throwaway repository holding a checkpoint (and optionally a run_id)."""
    root = tmp / name
    (root / ".code-factory" / "state").mkdir(parents=True, exist_ok=True)
    lines = ["phase: w2", "status: in_progress"]
    if run_id is not None:
        lines.insert(0, f"run_id: {run_id}")
    (root / PIPELINE_REL).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def write_file(root: pathlib.Path, relpath: str, text: str) -> pathlib.Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def backup(root: pathlib.Path, relpath: str, text: str) -> pathlib.Path:
    return write_file(root, (pathlib.Path(".code-factory") / "backups" / relpath).as_posix(), text)


def manifest(root: pathlib.Path) -> dict:
    return json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_directory_link(link: pathlib.Path, target: pathlib.Path) -> bool:
    """Create a directory link; `False` when this host cannot (Windows needs a junction)."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True, errors="replace")
    return res.returncode == 0 and link.is_dir()


# --------------------------------------------------------------------------------------------
# require: the run may not edit before the manifest exists
# --------------------------------------------------------------------------------------------

def test_require(tmp: pathlib.Path) -> None:
    root = repo(tmp, "require")
    write_file(root, "src/a.py", "a = 1\n")
    res = run("require", "--repo", str(root))
    expect_clean_cli(res, 1, "require without a manifest")
    check("manifest.json" in res.stderr and "artifacts-first" in res.stderr,
          f"the refusal must name the manifest and the rule: {res.stderr!r}")

    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    res = run("require", "--repo", str(root))
    expect_clean_cli(res, 0, "require with a manifest")
    check(payload(res)["run_id"] == RUN_ID, f"require reports the run id: {res.stdout!r}")


# --------------------------------------------------------------------------------------------
# init: run_id from the checkpoint, deterministic, never destructive
# --------------------------------------------------------------------------------------------

def test_init(tmp: pathlib.Path) -> None:
    root = repo(tmp, "init")
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init")
    body = payload(res)
    check(body["status"] == "created" and body["run_id"] == RUN_ID, f"init creates: {body}")
    data = manifest(root)
    check(data == {"run_id": RUN_ID, "changed_files": [], "created_files": []},
          f"the skeleton is documented: {data!r}")

    # Deterministic bytes and an idempotent second run.
    before = (root / MANIFEST_REL).read_bytes()
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init (second run)")
    check(payload(res)["status"] == "unchanged", f"a second init is idempotent: {res.stdout!r}")
    check((root / MANIFEST_REL).read_bytes() == before, "init must not rewrite a fresh skeleton")

    # An existing manifest WITH entries is never overwritten.
    write_file(root, "src/a.py", "a = 1\n")
    backup(root, "src/a.py", "a = 0\n")
    expect_clean_cli(run("add", "--repo", str(root), "--changed", "src/a.py"), 0, "add for init")
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 1, "init over a populated manifest")
    check("already lists" in res.stderr, f"the refusal must explain it: {res.stderr!r}")
    check(len(manifest(root)["changed_files"]) == 1,
          "a refused init must leave the manifest untouched")

    # An EMPTY skeleton of another run is reusable (a restarted run), with the new run id.
    other = repo(tmp, "init-restart", run_id="20261104-11111111")
    (other / ".code-factory").mkdir(parents=True, exist_ok=True)
    (other / MANIFEST_REL).write_text(
        json.dumps({"run_id": "20261103-aaaaaaaa", "changed_files": [], "created_files": []}),
        encoding="utf-8")
    res = run("init", "--repo", str(other))
    expect_clean_cli(res, 0, "init over an empty skeleton")
    check(payload(res)["status"] == "reinitialized" and manifest(other)["run_id"] ==
          "20261104-11111111", f"an empty skeleton is reusable: {res.stdout!r}")

    # The run id is taken from the checkpoint and format-checked.
    no_id = repo(tmp, "init-no-run-id", run_id=None)
    res = run("init", "--repo", str(no_id))
    expect_clean_cli(res, 2, "init without a run_id in the checkpoint")
    check("run_id" in res.stderr and "YYYYMMDD" in res.stderr,
          f"the error must name the expected shape: {res.stderr!r}")
    check(not (no_id / MANIFEST_REL).exists(), "a refused init writes nothing")

    bad_id = repo(tmp, "init-bad-run-id", run_id="2026-11-03")
    res = run("init", "--repo", str(bad_id))
    expect_clean_cli(res, 2, "init with a malformed run_id")
    check("YYYYMMDD" in res.stderr, f"the error must name the shape: {res.stderr!r}")

    no_pipeline = tmp / "init-no-pipeline"
    no_pipeline.mkdir()
    res = run("init", "--repo", str(no_pipeline))
    expect_clean_cli(res, 2, "init without a checkpoint")
    check("pipeline.yaml" in res.stderr, f"the error must name the checkpoint: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# add: the computed hash, and the backup a changed file must have
# --------------------------------------------------------------------------------------------

def test_add_changed(tmp: pathlib.Path) -> None:
    root = repo(tmp, "changed")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    target = write_file(root, "src/a.py", "a = 1\n")

    # THE blocking pin: no backup, no registration.
    res = run("add", "--repo", str(root), "--changed", "src/a.py")
    expect_clean_cli(res, 1, "add --changed without a backup")
    check("no backup" in res.stderr and "backups" in res.stderr,
          f"the refusal must name the missing backup: {res.stderr!r}")
    check(manifest(root)["changed_files"] == [], "a refused add writes nothing")

    backup(root, "src/a.py", "a = 0\n")
    res = run("add", "--repo", str(root), "--changed", "src/a.py")
    expect_clean_cli(res, 0, "add --changed with a backup")
    body = payload(res)
    check(body["status"] == "added" and body["kind"] == "changed", f"the add: {body}")
    entry = manifest(root)["changed_files"][0]
    check(entry["path"] == "src/a.py" and entry["sha256"] == sha256(target),
          f"the sha256 must be the one of the file's CURRENT bytes: {entry}")
    check(len(entry["sha256"]) == 64 and entry["sha256"] == entry["sha256"].lower(),
          f"the sha256 must be 64 lowercase hex: {entry['sha256']!r}")

    # Re-adding the same content is `unchanged`; a further edit re-hashes the entry.
    res = run("add", "--repo", str(root), "--changed", "src/a.py")
    expect_clean_cli(res, 0, "add --changed twice")
    check(payload(res)["status"] == "unchanged", f"an identical file is unchanged: {res.stdout!r}")
    check(len(manifest(root)["changed_files"]) == 1, "no duplicate entry")
    target.write_text("a = 2\n", encoding="utf-8")
    res = run("add", "--repo", str(root), "--changed", "src/a.py")
    expect_clean_cli(res, 0, "add --changed after a further edit")
    check(payload(res)["status"] == "rehashed"
          and manifest(root)["changed_files"][0]["sha256"] == sha256(target),
          f"the entry must follow the file: {res.stdout!r}")

    # A path is changed OR created, never both.
    res = run("add", "--repo", str(root), "--created", "src/a.py")
    expect_clean_cli(res, 1, "add --created of a changed file")
    check("already registered as changed" in res.stderr,
          f"the conflict must be explained: {res.stderr!r}")

    # A path that does not exist cannot be hashed.
    res = run("add", "--repo", str(root), "--changed", "src/missing.py")
    expect_clean_cli(res, 1, "add of a missing file")
    check("not a file" in res.stderr, f"the refusal must say why: {res.stderr!r}")


def test_add_created(tmp: pathlib.Path) -> None:
    root = repo(tmp, "created")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    target = write_file(root, "src/new.py", "new = 1\n")
    res = run("add", "--repo", str(root), "--created", "src/new.py")
    expect_clean_cli(res, 0, "add --created")
    check(payload(res)["kind"] == "created"
          and manifest(root)["created_files"][0]["sha256"] == sha256(target),
          f"the created entry must carry the computed hash: {res.stdout!r}")

    # A file that PREDATES the run is a changed file, not a created one: git says it is tracked.
    if shutil.which("git"):
        tracked = repo(tmp, "created-tracked")
        expect_clean_cli(run("init", "--repo", str(tracked)), 0, "init (tracked fixture)")
        res = subprocess.run(["git", "init", "-q", str(tracked)], capture_output=True)
        check(res.returncode == 0, "git init must succeed")
        write_file(tracked, "src/old.py", "old = 1\n")
        subprocess.run(["git", "-C", str(tracked), "add", "-A"], capture_output=True)
        res = run("add", "--repo", str(tracked), "--created", "src/old.py")
        expect_clean_cli(res, 1, "add --created of a tracked file")
        check("tracked by git" in res.stderr and "--changed" in res.stderr,
              f"the refusal must point at --changed: {res.stderr!r}")

    # …and a file that already has a backup predates the run too.
    backed = repo(tmp, "created-backed")
    expect_clean_cli(run("init", "--repo", str(backed)), 0, "init (backup fixture)")
    write_file(backed, "src/pre.py", "pre = 1\n")
    backup(backed, "src/pre.py", "pre = 0\n")
    res = run("add", "--repo", str(backed), "--created", "src/pre.py")
    expect_clean_cli(res, 1, "add --created of a backed-up file")
    check("predates the run" in res.stderr or "--changed" in res.stderr,
          f"the refusal must point at --changed: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# Path confinement: the manifest may only describe files of THIS repository
# --------------------------------------------------------------------------------------------

def test_path_confinement(tmp: pathlib.Path) -> None:
    root = repo(tmp, "confine")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    write_file(root, "src/a.py", "a = 1\n")
    for label, value in (("absolute POSIX", "/etc/passwd"),
                         ("absolute Windows", "C:/Windows/system32/drivers/etc/hosts"),
                         ("parent escape", "../outside.py"),
                         ("nested escape", "src/../../outside.py"),
                         ("empty", "   ")):
        res = run("add", "--repo", str(root), "--changed", value)
        expect_clean_cli(res, 2, f"a {label} path")
        check(payload(res) == {}, f"a refused path prints no verdict ({label})")
    check(manifest(root)["changed_files"] == [], "no refused path may reach the manifest")

    outside = tmp / "confine-outside"
    outside.mkdir()
    write_file(outside, "secret.py", "secret = 1\n")
    link = root / "linked"
    if not make_directory_link(link, outside):
        print("note: skipping the symlink-escape case — this host cannot create a directory link")
        return
    res = run("add", "--repo", str(root), "--changed", "linked/secret.py")
    expect_clean_cli(res, 2, "a symlink-escaping path")
    check("outside the repository" in res.stderr, f"the refusal must say why: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# audit: the finish gate
# --------------------------------------------------------------------------------------------

def test_audit(tmp: pathlib.Path) -> None:
    root = repo(tmp, "audit")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    changed = write_file(root, "src/a.py", "a = 1\n")
    backup(root, "src/a.py", "a = 0\n")
    created = write_file(root, "src/new.py", "new = 1\n")
    expect_clean_cli(run("add", "--repo", str(root), "--changed", "src/a.py"), 0, "add changed")
    expect_clean_cli(run("add", "--repo", str(root), "--created", "src/new.py"), 0, "add created")

    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 0, "audit of a clean manifest")
    body = payload(res)
    check(body["status"] == "ok" and body["changed"] == 1 and body["created"] == 1,
          f"the audit reports the change set: {body}")
    check(body["problems"] == [], f"no problems expected: {body['problems']}")

    # Drift: the working tree no longer matches the registered hash.
    changed.write_text("a = 2\n", encoding="utf-8")
    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 1, "audit after an unregistered edit")
    check("DRIFT" in res.stderr and "src/a.py" in res.stderr,
          f"the drift must be named: {res.stderr!r}")

    # Re-registering clears it.
    expect_clean_cli(run("add", "--repo", str(root), "--changed", "src/a.py"), 0, "re-add")
    expect_clean_cli(run("audit", "--repo", str(root)), 0, "audit after the re-registration")

    # A missing backup is a violation.
    (root / ".code-factory" / "backups" / "src" / "a.py").unlink()
    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 1, "audit without the backup")
    check("backup" in res.stderr, f"the missing backup must be named: {res.stderr!r}")

    # A registered file that disappeared is a violation.
    backup(root, "src/a.py", "a = 0\n")
    created.unlink()
    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 1, "audit with a missing created file")
    check("missing from the working tree" in res.stderr, f"the miss must be named: {res.stderr!r}")

    # A malformed entry (bad hash) and a duplicated path are violations.
    created.write_text("new = 1\n", encoding="utf-8")
    data = manifest(root)
    data["created_files"][0]["sha256"] = "not-a-hash"
    (root / MANIFEST_REL).write_text(json.dumps(data), encoding="utf-8")
    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 1, "audit with a malformed hash")
    check("64 lowercase hex" in res.stderr, f"the hash rule must be named: {res.stderr!r}")

    data["created_files"][0]["sha256"] = sha256(created)
    data["created_files"].append({"path": "src/a.py", "sha256": sha256(changed)})
    (root / MANIFEST_REL).write_text(json.dumps(data), encoding="utf-8")
    res = run("audit", "--repo", str(root))
    expect_clean_cli(res, 1, "audit with a duplicated path")
    check("listed twice" in res.stderr, f"the duplication must be named: {res.stderr!r}")

    # No manifest at all: the audit cannot pass.
    missing = repo(tmp, "audit-missing")
    res = run("audit", "--repo", str(missing))
    expect_clean_cli(res, 1, "audit without a manifest")
    check("no manifest" in res.stderr, f"the absence must be named: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# The argparse contract
# --------------------------------------------------------------------------------------------

def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("init", "require", "add", "audit"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("init"), 2, "init without --repo")
    expect_clean_cli(run("add", "--repo", "."), 2, "add without a kind")
    expect_clean_cli(run("add", "--repo", ".", "--changed", "a", "--created", "b"), 2,
                     "add with both kinds")
    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def test_audit_revalidates_paths(tmp: pathlib.Path) -> None:
    """(R1-04) The audit re-confines every manifest entry: a hand-edited escape is a violation.

    The manifest is a file on disk, so an entry may have been written by hand or by an older
    version. The audit must never join an absolute, traversal or drive-letter path to the
    repository and read it as if it were confined — it reports the entry instead.
    """
    root = repo(tmp, "audit-confined")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    write_file(root, "src/a.py", "a = 1\n")
    backup(root, "src/a.py", "a = 0\n")
    expect_clean_cli(run("add", "--repo", str(root), "--changed", "src/a.py"), 0, "add")
    data = manifest(root)
    host_file = tmp / "outside.txt"
    host_file.write_text("not part of this repository\n", encoding="utf-8")
    for name, raw in (("absolute", str(host_file).replace("\\", "/")),
                      ("traversal", "../../outside.txt"),
                      ("drive", "C:/Windows/win.ini")):
        edited = {"run_id": data["run_id"],
                  "changed_files": [{"path": raw, "sha256": "0" * 64}] + data["changed_files"],
                  "created_files": []}
        (root / MANIFEST_REL).write_text(json.dumps(edited), encoding="utf-8")
        res = run("audit", "--repo", str(root))
        expect_clean_cli(res, 1, f"audit of a manifest holding a {name} path")
        check("unconfined manifest entry" in res.stderr and raw in res.stderr,
              f"the {name} entry must be named as a violation: {res.stderr!r}")
    (root / MANIFEST_REL).write_text(json.dumps(data), encoding="utf-8")
    expect_clean_cli(run("audit", "--repo", str(root)), 0, "audit after restoring the manifest")


def test_atomic_write_failure(tmp: pathlib.Path) -> None:
    """(R1-05) An unwritable manifest is an actionable exit 2 and leaves the old one untouched."""
    blocked = tmp / "manifest-write-blocked"
    (blocked / ".code-factory").mkdir(parents=True)
    (blocked / ".code-factory" / "state").mkdir()
    (blocked / ".code-factory" / "state" / "pipeline.yaml").write_text(
        f"run_id: {RUN_ID}" + chr(10), encoding="utf-8")
    # A directory where manifest.json belongs: `os.replace` fails after the temp write.
    (blocked / ".code-factory" / "manifest.json").mkdir()
    res = run("init", "--repo", str(blocked))
    expect_clean_cli(res, 2, "init on an unwritable manifest path")
    check("cannot write the manifest" in res.stderr,
          f"init must name the write failure: {res.stderr!r}")

    frozen = repo(tmp, "manifest-write-frozen")
    expect_clean_cli(run("init", "--repo", str(frozen)), 0, "init")
    write_file(frozen, "src/new.py", "new = 1" + chr(10))
    path = frozen / MANIFEST_REL
    before = path.read_bytes()
    os.chmod(path, 0o444)
    try:
        res = run("add", "--repo", str(frozen), "--created", "src/new.py")
        expect_clean_cli(res, 2, "add onto a read-only manifest")
        check("cannot write the manifest" in res.stderr,
              f"add must name the write failure: {res.stderr!r}")
        check(path.read_bytes() == before,
              "a failed write must leave the manifest byte-identical")
    finally:
        os.chmod(path, 0o644)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_require(tmp)
        test_init(tmp)
        test_add_changed(tmp)
        test_add_created(tmp)
        test_path_confinement(tmp)
        test_audit(tmp)
        test_audit_revalidates_paths(tmp)
        test_atomic_write_failure(tmp)
        test_cli_contract()

    print("PASS - manifest.py enforces the run's change set: `require` blocks a run that has no "
          "manifest (the pre-edit gate), `init` takes the run_id from the checkpoint, is "
          "deterministic, reuses an empty skeleton and never overwrites a populated manifest, "
          "`add` computes the sha256 itself and BLOCKS a changed file without its backup and a "
          "created file that predates the run, every path is confined to the repository (absolute "
          "/ drive / '..' / symlink escapes refused), and `audit` reports drift, a missing file, a "
          "missing backup, a malformed hash and a duplicated path with exit 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

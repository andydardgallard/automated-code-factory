#!/usr/bin/env python3
"""
Contract test for `rollback.py` — the confined, portable rollback of the run's change set.

WHY THIS EXISTS

The rollback example in `references/verification-strategy.md` §4.3 joined `created_files` as
STRINGS although `manifest.py` stores OBJECTS (`{"path", "sha256"}` — a TypeError against the
first real manifest) and used Bash process substitution (`<(...)`) that cmd.exe does not have.
`rollback.py` is the fix, and this test pins its contract:

  - the OBJECT manifest is read: each entry's `path` is extracted, created files are deleted and
    changed files are restored byte-identically from `.code-factory/backups/<same path>`; a
    legacy STRING entry is a clean exit-2 message, never a TypeError/traceback;
  - WHOLE-OPERATION validation: one unconfined entry (absolute, drive, `..`, symlink escape) or
    one missing backup BLOCKS the rollback with exit 1 and NOTHING is deleted or restored —
    never a partial rollback, and a file outside the repository is never touched;
  - `--dry-run` runs the same validation, prints the plan and changes nothing;
  - cmd.exe compatibility: the helper is invoked as `python rollback.py ...` with no shell at
    all, and the documented rollback section uses it instead of Bash-only syntax;
  - the argparse contract: `--help` exit 0, a usage error exit 2, no traceback ever.

Exit code 0 = every assertion passes, 1 = the script did not behave as the contract says.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("rollback.py")
DOC = pathlib.Path(__file__).resolve().parents[1] / "references" / "verification-strategy.md"
MANIFEST_REL = pathlib.Path(".code-factory") / "manifest.json"
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


def repo(tmp: pathlib.Path, name: str) -> pathlib.Path:
    root = tmp / name
    (root / ".code-factory" / "backups").mkdir(parents=True, exist_ok=True)
    return root


def write_file(root: pathlib.Path, relpath: str, text: str) -> pathlib.Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def backup(root: pathlib.Path, relpath: str, text: str) -> pathlib.Path:
    return write_file(root, (pathlib.Path(".code-factory") / "backups" / relpath).as_posix(), text)


def write_manifest(root: pathlib.Path, changed: list, created: list) -> None:
    """An OBJECT manifest like `manifest.py` writes; pass a plain string to emulate a legacy one."""
    def entries(values: list) -> list:
        return [v if isinstance(v, dict) else {"path": v, "sha256": "0" * 64} for v in values]
    payload_ = {"run_id": "20261105-11a026da",
                "changed_files": entries(changed), "created_files": entries(created)}
    (root / MANIFEST_REL).write_text(json.dumps(payload_), encoding="utf-8")


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
# The object manifest: extraction, deletion, byte-identical restore
# --------------------------------------------------------------------------------------------

def test_roundtrip(tmp: pathlib.Path) -> None:
    root = repo(tmp, "roundtrip")
    changed = write_file(root, "src/a.py", "a = 1\n")          # the run's edit
    backup(root, "src/a.py", "a = 0\n")                        # its pre-edit bytes
    created = write_file(root, "src/new.py", "new = 1\n")
    nested = write_file(root, "tests/gen_report.py", "print(1)\n")
    gone = root / "src" / "already_removed.py"                 # deleted before the rollback ran
    write_manifest(root, ["src/a.py"],
                   ["src/new.py", "tests/gen_report.py", "src/already_removed.py"])

    res = run("--repo", str(root))
    expect_clean_cli(res, 0, "rollback")
    body = payload(res)
    check(body["status"] == "rolled-back" and body["dry_run"] is False, f"the verdict: {body}")
    check(body["deleted"] == ["src/new.py", "tests/gen_report.py"],
          f"both created files are reported deleted: {body}")
    check(body["already_absent"] == ["src/already_removed.py"],
          f"an already-absent created file is reported, not an error: {body}")
    check(body["restored"] == ["src/a.py"], f"the changed file is restored: {body}")
    check(not created.exists() and not nested.exists() and not gone.exists(),
          "the created files are gone from the tree")
    check(changed.read_bytes() == b"a = 0\n",
          f"the changed file is byte-identical to its backup: {changed.read_bytes()!r}")


def test_legacy_string_manifest_is_a_clean_error(tmp: pathlib.Path) -> None:
    """(C14) The old example's string manifest is a message + exit 2, never a TypeError."""
    root = repo(tmp, "legacy")
    created = write_file(root, "src/new.py", "new = 1\n")
    (root / MANIFEST_REL).write_text(json.dumps(
        {"run_id": "20261105-11a026da", "changed_files": [], "created_files": ["src/new.py"]}),
        encoding="utf-8")
    res = run("--repo", str(root))
    expect_clean_cli(res, 2, "a legacy string manifest")
    check("object" in res.stderr, f"the message must name the expected shape: {res.stderr!r}")
    check(created.is_file(), "a refused rollback deletes nothing")


# --------------------------------------------------------------------------------------------
# Whole-operation validation: one bad entry blocks EVERYTHING
# --------------------------------------------------------------------------------------------

def test_unconfined_paths_block_everything(tmp: pathlib.Path) -> None:
    outside = tmp / "outside"
    outside.mkdir()
    host_file = write_file(outside, "secret.txt", "not part of this repository\n")
    for label, bad in (("absolute", str(host_file).replace("\\", "/")),
                       ("traversal", "../../outside/secret.txt"),
                       ("drive", "C:/Windows/win.ini")):
        root = repo(tmp, f"block-{label}")
        changed = write_file(root, "src/a.py", "a = 1\n")
        backup(root, "src/a.py", "a = 0\n")
        created = write_file(root, "src/new.py", "new = 1\n")
        write_manifest(root, ["src/a.py"], [bad, "src/new.py"])
        res = run("--repo", str(root))
        expect_clean_cli(res, 1, f"a manifest holding an {label} path")
        check("BLOCKED" in res.stderr and "unconfined" in res.stderr,
              f"the refusal must name the unconfined entry ({label}): {res.stderr!r}")
        check(created.is_file(), f"a blocked rollback deletes nothing ({label})")
        check(changed.read_bytes() == b"a = 1\n", f"a blocked rollback restores nothing ({label})")
        check(host_file.read_bytes() == b"not part of this repository\n",
              f"the file outside the repository is never touched ({label})")


def test_symlink_escape_blocks_everything(tmp: pathlib.Path) -> None:
    root = repo(tmp, "block-symlink")
    outside = tmp / "outside-symlink"
    outside.mkdir()
    secret = write_file(outside, "secret.py", "secret = 1\n")
    link = root / "linked"
    if not make_directory_link(link, outside):
        print("note: skipping the symlink-escape case — this host cannot create a directory link")
        return
    created = write_file(root, "src/new.py", "new = 1\n")
    write_manifest(root, [], ["linked/secret.py", "src/new.py"])
    res = run("--repo", str(root))
    expect_clean_cli(res, 1, "a symlink-escaping created entry")
    check("outside the repository" in res.stderr,
          f"the refusal must name the escape: {res.stderr!r}")
    check(created.is_file(), "a blocked rollback deletes nothing")
    check(secret.read_bytes() == b"secret = 1\n", "the escape target is never touched")


def test_missing_backup_blocks_everything(tmp: pathlib.Path) -> None:
    root = repo(tmp, "block-backup")
    write_file(root, "src/a.py", "a = 1\n")                    # changed, but NO backup
    created = write_file(root, "src/new.py", "new = 1\n")
    write_manifest(root, ["src/a.py"], ["src/new.py"])
    res = run("--repo", str(root))
    expect_clean_cli(res, 1, "a changed file without its backup")
    check("backup" in res.stderr, f"the missing backup must be named: {res.stderr!r}")
    check(created.is_file(), "the created file must survive: rollback is all-or-nothing")


# --------------------------------------------------------------------------------------------
# Dry run: the same validation, no change
# --------------------------------------------------------------------------------------------

def test_dry_run(tmp: pathlib.Path) -> None:
    root = repo(tmp, "dry-run")
    changed = write_file(root, "src/a.py", "a = 1\n")
    backup(root, "src/a.py", "a = 0\n")
    created = write_file(root, "src/new.py", "new = 1\n")
    write_manifest(root, ["src/a.py"], ["src/new.py"])
    res = run("--repo", str(root), "--dry-run")
    expect_clean_cli(res, 0, "--dry-run")
    body = payload(res)
    check(body["status"] == "dry-run" and body["dry_run"] is True, f"the verdict: {body}")
    check(body["deleted"] == ["src/new.py"] and body["restored"] == ["src/a.py"],
          f"the plan names what WOULD happen: {body}")
    check(created.is_file() and changed.read_bytes() == b"a = 1\n",
          "a dry run touches nothing")
    # …and the same validation blocks a bad plan with nothing touched.
    write_manifest(root, ["src/a.py"], ["../escape.py", "src/new.py"])
    res = run("--repo", str(root), "--dry-run")
    expect_clean_cli(res, 1, "--dry-run over an unconfined plan")
    check(created.is_file(), "a blocked dry run touches nothing either")


# --------------------------------------------------------------------------------------------
# cmd.exe compatibility: the helper and the doc carry no Bash-only syntax
# --------------------------------------------------------------------------------------------

def test_doc_uses_the_helper() -> None:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### 4.3 Rollback steps", 1)[1]
    check("scripts/rollback.py" in section,
          "the rollback steps must name the portable helper")
    check("<(" not in section and "while read" not in section,
          "no Bash-only process substitution or read-loop may remain in the rollback steps")
    check('"created_files": [{"path":' in text,
          "the manifest example must show the OBJECT entries manifest.py writes")


# --------------------------------------------------------------------------------------------
# The argparse contract
# --------------------------------------------------------------------------------------------

def test_cli_contract(tmp: pathlib.Path) -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    check("--repo" in res.stdout and "--dry-run" in res.stdout,
          f"the help must document the interface: {res.stdout!r}")
    expect_clean_cli(run(), 2, "no --repo")
    expect_clean_cli(run("--repo", str(tmp / "does-not-exist")), 2, "a missing repository root")
    empty = repo(tmp, "no-manifest")
    res = run("--repo", str(empty))
    expect_clean_cli(res, 2, "no manifest")
    check("manifest.json" in res.stderr, f"the error must name the manifest: {res.stderr!r}")
    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_roundtrip(tmp)
        test_legacy_string_manifest_is_a_clean_error(tmp)
        test_unconfined_paths_block_everything(tmp)
        test_symlink_escape_blocks_everything(tmp)
        test_missing_backup_blocks_everything(tmp)
        test_dry_run(tmp)
        test_cli_contract(tmp)
    test_doc_uses_the_helper()

    print("PASS - rollback.py rolls the change set back: the OBJECT manifest's `path` fields are "
          "extracted (a legacy string entry is a clean exit 2, never a TypeError), created files "
          "are deleted and changed files are restored byte-identically from their backups, every "
          "path is validated as confined to the repository BEFORE anything is touched (absolute / "
          "drive / '..' / symlink escapes and a missing backup block the WHOLE rollback with exit "
          "1 — never a partial one), --dry-run validates and plans without changing a byte, and "
          "the helper runs as plain `python rollback.py` with no Bash-only syntax.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

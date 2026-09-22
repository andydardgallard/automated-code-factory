#!/usr/bin/env python3
"""
Deterministic self-test for `factory_preflight.py` (zero LLM tokens).

Verifies that the probe:
  - exits 0 on a machine with a working Python and git, and writes valid JSON to `--out`
    (creating missing parent directories),
  - reports exactly the documented capability keys with sane values: `python_cmd` is one of the
    known candidates, actually STARTS and prints a version (the whole point of the probe),
    `git`/`git_version` agree with reality, `os` mirrors `platform`, and the secondary-model flag
    follows KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL,
  - prints a human-readable summary naming python, git, bash/sh, the OS and the flag,
  - degrades explicitly: with a PATH that contains no tools it exits 1 and records nulls instead
    of inventing a command.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import json
import os
import pathlib
import platform
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "factory_preflight.py"

KEYS = ("python_cmd", "python_version", "git", "git_version", "bash", "sh", "os",
        "secondary_model_env")
PYTHON_CANDIDATES = ("python", "python3", "py")


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", env=env)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)

        # 1. Real environment: exit 0, JSON written into a not-yet-existing nested directory.
        out = tmp / "state" / "preflight.json"
        res = run("--out", str(out))
        expect(res.returncode == 0,
               f"preflight must exit 0 when python and git are usable: {res.stderr!r}")
        expect(out.is_file(), "preflight must write the capability file (creating parent dirs)")
        caps = json.loads(out.read_text(encoding="utf-8"))

        # 2. Exactly the documented keys, with usable values.
        for key in KEYS:
            expect(key in caps, f"capabilities must contain {key!r}: {sorted(caps)}")
        expect(isinstance(caps["python_cmd"], str) and caps["python_cmd"] in PYTHON_CANDIDATES,
               f"python_cmd must be one of {PYTHON_CANDIDATES}: {caps['python_cmd']!r}")
        expect(isinstance(caps["python_version"], str) and "python" in caps["python_version"].lower(),
               f"python_version must name the interpreter: {caps['python_version']!r}")
        expect(caps["git"] is True, "git must be detected as usable on this machine")
        expect("git" in (caps["git_version"] or "").lower(),
               f"git_version must be the git version line: {caps['git_version']!r}")
        expect(isinstance(caps["os"], dict) and caps["os"].get("system") == platform.system(),
               f"os must mirror the platform module: {caps['os']!r}")
        expect(isinstance(caps["secondary_model_env"], bool),
               f"secondary_model_env must be a boolean: {caps['secondary_model_env']!r}")

        # 3. The reported command really runs (that is what factory instructions embed).
        version = subprocess.run([caps["python_cmd"], "--version"],
                                 capture_output=True, text=True, errors="replace")
        expect(version.returncode == 0,
               f"python_cmd {caps['python_cmd']!r} must actually run: {version.stderr!r}")
        expect("python" in ((version.stdout or "") + (version.stderr or "")).lower(),
               "the reported python_cmd must print a Python version")

        # 4. Human-readable summary covers every capability class.
        for needle in ("python:", "git:", "bash:", "sh:", "os:", "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL"):
            expect(needle in res.stdout, f"summary must mention {needle!r}: {res.stdout!r}")

        # 5. The secondary-model flag follows the environment variable.
        for value, expected in (("1", True), ("0", False)):
            env = dict(os.environ, KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=value)
            target = tmp / f"env-{value}.json"
            res = run("--out", str(target), env=env)
            expect(res.returncode == 0, f"probe must exit 0 with the flag set to {value!r}")
            flagged = json.loads(target.read_text(encoding="utf-8"))
            expect(flagged["secondary_model_env"] is expected,
                   f"flag {value!r} must map to secondary_model_env={expected}: {flagged!r}")

        # 6. Degraded environment (PATH without any tool): exit 1 and explicit nulls.
        empty = tmp / "empty-bin"
        empty.mkdir()
        degraded_env = dict(os.environ, PATH=str(empty))
        degraded_path = tmp / "degraded.json"
        res = run("--out", str(degraded_path), env=degraded_env)
        expect(res.returncode == 1,
               f"without python and git the probe must exit 1: rc={res.returncode} {res.stdout!r}")
        degraded = json.loads(degraded_path.read_text(encoding="utf-8"))
        expect(degraded["python_cmd"] is None and degraded["python_version"] is None,
               f"a missing interpreter must be recorded as null: {degraded!r}")
        expect(degraded["git"] is False and degraded["git_version"] is None,
               f"missing git must be recorded as false/null: {degraded!r}")
        expect(degraded["bash"] is None and degraded["sh"] is None,
               f"missing shells must be recorded as null: {degraded!r}")
        expect("FAIL" in res.stderr, f"a degraded probe must say what is missing: {res.stderr!r}")

    print("PASS - factory_preflight.py reports the real python/git/shell/os capabilities "
          "(file + summary), follows the secondary-model flag, and degrades to nulls with exit 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Deterministic environment probe ("pre-flight") for the Code Factory — zero LLM tokens.

The factory's instructions hand shell commands to whatever machine the task runs on, and that
machine may or may not expose `python`, `python3` or the Windows `py` launcher. This script probes
the REAL environment once and writes the capability file that the instructions (and the prompts
they generate) read before emitting any command — which closes the python3-vs-py mismatch on
Windows and makes the degradation explicit instead of silent.

Probed capabilities (JSON, see `--out`):
  python_cmd            command that actually runs a Python interpreter ("python" / "python3" /
                        "py"), or null when none of them starts
  python_version        first line of its `--version` output, or null
  git                   true when git is on PATH AND `git --version` succeeds
  git_version           first line of `git --version`, or null
  bash / sh             absolute path of the POSIX shell when present, else null
  os                    {system, release, machine} from the stdlib `platform` module
  secondary_model_env   true when KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL is set to a truthy value
                        (the launcher sets it; without it the primary/secondary model split is off)

Usage:
  python factory_preflight.py [--out .code-factory/state/preflight.json]

Exit code 0 when at least one Python runs AND git is usable, 1 otherwise (a capability file with
nulls is still written, so the caller can see exactly what is missing).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile

PYTHON_CANDIDATES = ["python", "python3", "py"]
SECONDARY_MODEL_ENV = "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL"
DEFAULT_OUT = ".code-factory/state/preflight.json"
PROBE_TIMEOUT = 30

FALSY = {"", "0", "false", "no", "off", "none"}


def _try_run(argv: list[str]) -> str | None:
    """First output line of `argv`, or None when it cannot be started / fails / prints nothing."""
    try:
        res = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                             timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    out = (res.stdout or "").strip() or (res.stderr or "").strip()
    return out.splitlines()[0].strip() if out else None


def probe_python() -> tuple[str | None, str | None]:
    """First usable Python command among the candidates, plus its `--version` line."""
    for name in PYTHON_CANDIDATES:
        exe = shutil.which(name)
        if not exe:
            continue
        version = _try_run([exe, "--version"])
        if version:
            return name, version
    return None, None


def probe_git() -> tuple[bool, str | None]:
    exe = shutil.which("git")
    if not exe:
        return False, None
    version = _try_run([exe, "--version"])
    return (version is not None), version


def probe_shell(name: str) -> str | None:
    return shutil.which(name)


def env_flag(name: str) -> bool:
    """True when the environment variable is set to a truthy value (1/true/yes/on/...)."""
    return os.environ.get(name, "").strip().lower() not in FALSY


def collect_capabilities() -> dict:
    python_cmd, python_version = probe_python()
    git, git_version = probe_git()
    return {
        "python_cmd": python_cmd,
        "python_version": python_version,
        "git": git,
        "git_version": git_version,
        "bash": probe_shell("bash"),
        "sh": probe_shell("sh"),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "secondary_model_env": env_flag(SECONDARY_MODEL_ENV),
    }


def write_json(path: pathlib.Path, data: dict) -> None:
    """Atomic write (temp file in the target directory + replace), UTF-8, LF endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def format_summary(caps: dict, out: pathlib.Path) -> str:
    python = f"{caps['python_cmd']} ({caps['python_version']})" if caps["python_cmd"] else "NOT FOUND"
    git = caps["git_version"] if caps["git"] else "NOT FOUND"
    osinfo = " ".join(str(v) for v in caps["os"].values() if v)
    env_state = "set (model split active)" if caps["secondary_model_env"] else "not set (model split inactive)"
    return "\n".join([
        "code-factory preflight",
        f"  python: {python}",
        f"  git: {git}",
        f"  bash: {caps['bash'] or 'not found'}",
        f"  sh: {caps['sh'] or 'not found'}",
        f"  os: {osinfo}",
        f"  {SECONDARY_MODEL_ENV}: {env_state}",
        f"  capabilities: {out}",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"capabilities JSON path (default: {DEFAULT_OUT})")
    args = ap.parse_args()

    caps = collect_capabilities()
    out = pathlib.Path(args.out)
    write_json(out, caps)
    print(format_summary(caps, out))

    missing = [name for name, ok in (("python", caps["python_cmd"]), ("git", caps["git"])) if not ok]
    if missing:
        print(f"FAIL: required tool(s) missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

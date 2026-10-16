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
  python factory_preflight.py [--out .code-factory/state/preflight.json] [--repo <root>]
  python factory_preflight.py --web-gui [--simulate-missing <name>] [--out ...] [--repo <root>]

`--web-gui` is OPT-IN and meant only for a run whose task is an applicable Web GUI task: it appends
a nested `web_gui` capability block (node/npm/npx versions, Chrome / Chrome for Testing presence,
MCP server start feasibility) by delegating to the sibling `chrome_devtools_mcp.py` probe logic —
fail-soft and timeout-guarded, so a missing browser capability is DATA carrying a reason and never
changes the exit code (which stays python+git only). WITHOUT the flag the output schema and the
exit-code contract are exactly what they were before the flag existed.
`--simulate-missing <name>` (repeatable, only meaningful together with `--web-gui`) forces one
capability to report missing (`node`, `npm`, `npx`, `chrome`, `chrome-for-testing`, `mcp-server`),
so the degraded behavior is testable without touching the host.

`--repo <root>` (a synonym: `--root`) is the resolved repo_path of the run and is OPTIONAL. When
it is given, a RELATIVE `--out` is resolved against it — an absolute path is always taken as it is
— so the capability file lands in the target repository, not in the launch directory. Without the
flag nothing changes: `--out` stays relative to the caller's working directory.

Exit code 0 when at least one Python runs AND git is usable, 1 otherwise (a capability file with
nulls is still written, so the caller can see exactly what is missing).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile

PYTHON_CANDIDATES = ["python", "python3", "py"]
SECONDARY_MODEL_ENV = "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL"
DEFAULT_OUT = ".code-factory/state/preflight.json"
PROBE_TIMEOUT = 30
# The conditional browser block: only `--web-gui` appends it, and its sub-probes are bounded so an
# unresponsive node/npm cannot stretch the pre-flight indefinitely.
WEB_GUI_KEY = "web_gui"
WEB_GUI_CAPABILITIES = ("node", "npm", "npx", "chrome", "chrome_for_testing", "mcp_server")
WEB_GUI_PROBE_TIMEOUT = 10
CHROME_HELPER = "chrome_devtools_mcp.py"

FALSY = {"", "0", "false", "no", "off", "none"}

REPO_HELP = ("Resolved repo_path of the run: a RELATIVE --out is resolved against it "
             "(default: the caller's working directory — unchanged without the flag)")


def anchored(path: str | pathlib.Path, repo: str | None) -> pathlib.Path:
    """`path` resolved against the explicit `--repo` root; an absolute path is taken as it is.

    Without `--repo` the path is returned unchanged, so the caller's working directory stays the
    base and the probe writes exactly where it did before the flag existed (fail-safe default: a
    missing anchor must never silently re-point an output at the wrong repository).
    """
    resolved = pathlib.Path(path)
    if repo and not resolved.is_absolute():
        return pathlib.Path(repo) / resolved
    return resolved


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


def _load_chrome_helper():
    """The sibling `chrome_devtools_mcp.py` module, loaded by path (no package, no side effects).

    The definition of "browser capability present" has ONE home — that script — so the pre-flight
    must not re-implement `which`/version/config checks. Loading by path keeps the probe independent
    of the caller's cwd and of `sys.path`.
    """
    helper_path = pathlib.Path(__file__).resolve().parent / CHROME_HELPER
    spec = importlib.util.spec_from_file_location("chrome_devtools_mcp", helper_path)
    if spec is None or spec.loader is None:
        raise OSError(f"cannot load {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def web_gui_version(reason: str) -> str | None:
    """The version token the probe embeds in its reason (`node is available (v20.11.0)`), or null.

    Best-effort by design: an unexpected reason shape yields null DATA instead of an error.
    """
    match = re.search(r"\(([^()]*)\)\s*$", reason or "")
    if not match:
        return None
    return match.group(1).strip() or None


def collect_web_gui_capabilities(simulate_missing: list[str] | tuple[str, ...] = ()) -> dict:
    """Nested `web_gui` block for an APPLICABLE Web GUI run — delegated, fail-soft, time-bounded.

    Delegates to `chrome_devtools_mcp.py`'s probe (import, no subprocess, no Chrome launch, no MCP
    server start) so a missing Node.js/npm/npx, Chrome/Chrome for Testing or MCP server is DATA with
    a reason: the block never raises and never changes the exit code, which stays python+git only.
    `simulate_missing` forces a capability to report missing without touching the host.
    """
    block: dict = {"source": CHROME_HELPER, "simulate_missing": sorted(simulate_missing)}
    result: dict = {}
    try:
        helper = _load_chrome_helper()
        helper.PROBE_TIMEOUT = min(helper.PROBE_TIMEOUT, WEB_GUI_PROBE_TIMEOUT)
        result = helper.probe_capabilities(simulate_missing=list(simulate_missing),
                                           check_mcp_start=False)
        raw = result.get("capabilities")
        caps = raw if isinstance(raw, dict) else {}
    except Exception as exc:       # a broken probe is DATA: never a failed pre-flight
        block["probe_error"] = f"{type(exc).__name__}: {exc}"
        caps = {}
    reported: dict[str, dict] = {}
    for name in WEB_GUI_CAPABILITIES:
        entry = caps.get(name)
        cap = entry if isinstance(entry, dict) else {}
        reason = str(cap.get("reason") or "not reported by the probe")
        reported[name] = {
            "present": cap.get("present") is True,
            # The MCP entry reports its managed config, not a version.
            "version": None if name == "mcp_server" else web_gui_version(reason),
            "reason": reason,
        }
    block.update({
        "capabilities": reported,
        "missing": [name for name in WEB_GUI_CAPABILITIES if not reported[name]["present"]],
        "browser_usable": bool(result.get("browser_usable")),
        "mcp_usable": bool(result.get("mcp_usable")),
        "verdict": ("browser path usable" if result.get("mcp_usable") else
                    "browser path unavailable — affected browser criteria must stay UNVERIFIED"),
    })
    return block


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
    lines = [
        "code-factory preflight",
        f"  python: {python}",
        f"  git: {git}",
        f"  bash: {caps['bash'] or 'not found'}",
        f"  sh: {caps['sh'] or 'not found'}",
        f"  os: {osinfo}",
        f"  {SECONDARY_MODEL_ENV}: {env_state}",
    ]
    block = caps.get(WEB_GUI_KEY)
    if isinstance(block, dict):
        # Only with `--web-gui`: the conditional browser capability class, one line per capability
        # plus the reason of every missing one — DATA that never changes the exit code.
        lines.append("  web gui (conditional browser path):")
        for name in WEB_GUI_CAPABILITIES:
            entry = (block.get("capabilities") or {}).get(name) or {}
            state = "present" if entry.get("present") else "missing"
            version = f" {entry['version']}" if entry.get("version") else ""
            lines.append(f"    {name}: {state}{version}")
            if not entry.get("present"):
                lines.append(f"      reason: {entry.get('reason')}")
        lines.append(f"  web gui verdict: {block.get('verdict')}")
    lines.append(f"  capabilities: {out}")
    return "\n".join(lines)


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def canonical_web_gui_name(name: str, ap: argparse.ArgumentParser) -> str:
    """`node` / `chrome-for-testing` … -> the probe's own spelling; an unknown name is a usage error."""
    key = str(name).strip().lower().replace("-", "_")
    if key not in WEB_GUI_CAPABILITIES:
        ap.error(f"unknown --simulate-missing capability {name!r}; known: "
                 + ", ".join(WEB_GUI_CAPABILITIES))
    return key


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"capabilities JSON path (default: {DEFAULT_OUT})")
    ap.add_argument("--repo", "--root", dest="repo", metavar="ROOT", default=None, help=REPO_HELP)
    ap.add_argument("--web-gui", action="store_true", dest="web_gui",
                    help=("OPT-IN: append the nested `web_gui` capability block (node/npm/npx, "
                          "Chrome / Chrome for Testing, MCP server start feasibility) — only for a "
                          "run whose task is an applicable Web GUI task"))
    ap.add_argument("--simulate-missing", action="append", default=[], metavar="NAME",
                    dest="simulate_missing",
                    help=("with --web-gui: force one browser capability to report missing "
                          f"({', '.join(WEB_GUI_CAPABILITIES)}); a dashed spelling is accepted too"))
    args = ap.parse_args()
    if args.simulate_missing and not args.web_gui:
        ap.error("--simulate-missing requires --web-gui")
    args.simulate_missing = [canonical_web_gui_name(name, ap) for name in args.simulate_missing]

    caps = collect_capabilities()
    if args.web_gui:
        caps[WEB_GUI_KEY] = collect_web_gui_capabilities(args.simulate_missing)
    out = anchored(args.out, args.repo)
    write_json(out, caps)
    print(format_summary(caps, out))

    missing = [name for name, ok in (("python", caps["python_cmd"]), ("git", caps["git"])) if not ok]
    if missing:
        print(f"FAIL: required tool(s) missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

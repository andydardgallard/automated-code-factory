#!/usr/bin/env python3
"""
Vaccination self-test: the USER-SCOPE agent catalog is a durable, portable fallback (stdlib only).

THE DEFECT THIS PINS

The Kimi Code CLI has repeatedly reported "Unknown agent type" for a factory role although the
profile was on disk: its project-scoped profile registry reloaded and lost the entry. The
repository-side answer (`agent_catalog_check.py`, rule `model-unavailable-stop`) detects that case,
but detection alone does not keep a run possible. The owner's real CLI (2.7.3) proved the supported
route: a role profile copied into the CLI's USER-SCOPE catalog — `<KIMI_CODE_HOME>/agents/` when
`KIMI_CODE_HOME` is set, else `~/.kimi-code/agents/` — launched `factory-documenter` from a
directory with NO project catalog at all. That route works, but the copy was made BY HAND: it lives
on one machine and in no repository, so it is not portable.

THE CONTRACT PINNED HERE (what `prepare_factory.*` and the generated launchers must do)

  1. BOTH deployers (`prepare_factory.sh`, `prepare_factory.ps1`/`.cmd`) install the user-scope
     fallback at deployment time: every factory role is copied BYTE-FOR-BYTE from
     `<project>/.agents/agents/sub-agents/<file>.md` to the user catalog, under the file names the
     CLI reads (the same 16 names the source directory carries, resolved through
     `model_matrix.ROLES` / `ROLE_FILES` — never a third roster copy). A copy that is already there
     but STALE is refreshed; a profile the factory does not manage is left untouched, byte for byte.
  2. BOTH generated launchers refresh that catalog BEFORE the CLI starts, so a project catalog lost
     between runs cannot leave the CLI with a stale copy. The refresh happens first: a launcher that
     launched the CLI and only then synced would leave the CLI with whatever was on disk at start.
  3. A launch still works when the project's own `.agents/agents/sub-agents/` is ABSENT (the owner's
     real scenario: the project catalog disappeared, the user-scope copies carried the run) — but
     ONLY over a COMPLETE user-scope fallback: every role of the roster must already be there, and a
     half-filled catalog refuses the launch instead of starting a session with missing roles.
  4. A fallback that cannot be refreshed ABORTS the launch: nonzero exit, no CLI started, and a
     message under the factory's own "Code Factory:" branding that names the profile catalog and the
     failure. Starting a run into an unknown-role session silently is the very failure this fallback
     exists to prevent. The same refusal covers a PARTIAL project catalog (a role the project no
     longer ships would stay whatever an older release left in the user scope) and any role copy that
     cannot be refreshed BYTE-FOR-BYTE — the refresh is proven with a comparison of the two files,
     never with the copy command's exit code alone.
  5. NO interpreter dependency: the refresh uses native shell / cmd commands only. The launcher must
     not name `python`/`python3`/`py` at all, and must work on a machine where all of them fail.
  6. `KIMI_CODE_HOME` is followed by BOTH sides: the CLI relocates its whole data root there, so a
     copy written under `~/.kimi-code/agents` while the variable is set would sit where that CLI
     never looks — a fallback that is not a fallback.
  7. The role list the launchers verify against is model_matrix's roster, checked here: the launcher
     carries it as plain text (`CF_AGENT_ROLES=...`) because it must work without an interpreter, so
     the copy is pinned to the registry instead of trusted.

HOW IT IS PROVEN (and why the test is a VACCINATION)

Every check runs the REAL generated files: a throwaway project is deployed by the real deployer,
then the real launcher is executed with a FAKE `kimi` first on PATH. The fake CLI never starts a
session; it records how it was reached and snapshots the fallback catalog AS IT WAS AT LAUNCH TIME
(name + size), which is what makes the "refresh BEFORE the launch" order checkable. HOME,
USERPROFILE and KIMI_CODE_HOME all point into a temporary root, so no check can touch the machine's
own `~/.kimi-code` (the PowerShell side must therefore resolve the user home from `%USERPROFILE%`,
never from `$HOME`, which PowerShell derives from the profile registry and env overrides cannot
redirect). The deployments run offline through the documented seam
`CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`.

On the PRE-FIX tree the launchers do not sync at all, so these checks fail with the actionable line
that says what is missing; the implementation turns them green without weakening any of them. The
adversarial findings (an absent project catalog over a half-filled fallback, a partial project
catalog leaving a stale role, a role copy that could not be refreshed) are pinned the same way: on
the tree before their correction the launcher starts the CLI, so the check FAILS.
A project deployed by the factory contains `.agents/` and the generated launchers, not the deployers,
so there the test SKIPs cleanly instead of failing.

Exit code 0 = every check passed (skips are fine), 1 = at least one check failed.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    # The role roster is the SIBLING registry the catalog probe already uses; it must be importable
    # from any working directory (this file is also loaded by path from a test runner).
    sys.path.insert(0, str(SCRIPTS))
from model_matrix import ROLE_FILES, ROLES  # noqa: E402

SH_NAME = "prepare_factory.sh"
PS1_NAME = "prepare_factory.ps1"
CMD_NAME = "prepare_factory.cmd"
DEPLOYER_FILES = (SH_NAME, PS1_NAME, CMD_NAME)

# The CLI's data root: `KIMI_CODE_HOME` when set, else `~/.kimi-code`; the user-scope profiles are
# FLAT `<file>.md` files inside its `agents/` directory (not `agents/sub-agents/`).
CATALOG_ENV = "KIMI_CODE_HOME"
CATALOG_REL = pathlib.Path(".kimi-code") / "agents"
# The documented offline seam of the MCP step: never reach npm or the network from a test.
VENDOR_OFFLINE_ENV = "CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE"

# A role the factory MANAGES that the fixture leaves behind in an OUTDATED version: the deployers and
# the launchers must overwrite it with the exact profile (a stale copy carries the old instructions
# and therefore the old model preference).
STALE_ROLE = "coder"
STALE_PROFILE = (b"---\nname: factory-coder\ndescription: OUT OF DATE copy left by an older "
                 b"factory release\n---\n\nstale\n")
# A profile the factory does NOT manage: it must survive byte for byte, never refreshed, never
# deleted (the user's own agents share this directory).
UNRELATED_PROFILE_NAME = "my-private-agent.md"
UNRELATED_PROFILE = b"---\nname: my-private-agent\ndescription: the user's own profile\n---\n\nMine.\n"

# The fake CLI records its invocation and the catalog it SAW, through these variables.
MARKER_ENV = "FAKE_KIMI_MARKER"
FAKE_CATALOG_ENV = "FAKE_KIMI_CATALOG"

DEPLOY_TIMEOUT = 600
LAUNCH_TIMEOUT = 300

# An interpreter named on an executable line: the launcher must be native-only (`py` and `python`
# with an optional `.exe`, as a whole token - `copy`/`pythonic` must not match).
INTERPRETER_RE = re.compile(r"(?<![\w./\\-])(?:python3?(?:\.exe)?|py(?:\.exe)?)(?![\w.-])", re.I)
FAILURE_WORDS = ("fail", "could not", "cannot", "can not", "unable", "refus", "error")

REPO_FILES = DEPLOYER_FILES


def find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    """The directory holding the deployers, or `None` inside a project deployed by the factory."""
    for path in (start, *start.parents):
        if all((path / name).is_file() for name in REPO_FILES):
            return path
    return None


FOUND_REPO = find_repo_root(SCRIPTS)
REPO = FOUND_REPO or SCRIPTS


# --- small helpers ------------------------------------------------------------------------------


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def tail(text: str | None, limit: int = 1500) -> str:
    body = (text or "").strip()
    return "(no output)" if not body else (body if len(body) <= limit else "... " + body[-limit:])


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "") + (result.stderr or "")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def remove_tree(path: pathlib.Path) -> None:
    """Best-effort removal (git and Windows can leave read-only entries behind)."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chmod(pathlib.Path(root) / name, stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def bash_exe() -> str | None:
    return shutil.which("bash")


def cmd_exe() -> str | None:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "cmd.exe"
    if native.is_file():
        return str(native)
    return shutil.which("cmd.exe") or shutil.which("cmd")


def powershell_exe() -> str | None:
    found = shutil.which("powershell.exe") or shutil.which("powershell")
    if found:
        return found
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(native) if native.is_file() else None


def sh_prerequisite() -> str | None:
    if not bash_exe():
        return "bash was not found on PATH - the .sh deployer/launcher cannot be exercised"
    if not shutil.which("git"):
        return "git was not found on PATH - the .sh deployer initializes a repository"
    return None


def cmd_prerequisite() -> str | None:
    if os.name != "nt":
        return f"os.name={os.name!r} - the .cmd/.ps1 deployer only runs on Windows"
    missing = [name for name, found in (("cmd.exe", cmd_exe()),
                                        ("powershell.exe", powershell_exe()),
                                        ("git", shutil.which("git"))) if not found]
    if missing:
        return "not available on this machine: " + ", ".join(missing)
    return None


# --- the env a fixture runs in: nothing may reach the machine's own catalog ---------------------


def hermetic_env(home: pathlib.Path, *, kimi_home: pathlib.Path | None = None,
                 path_prefix: str | None = None, extra: dict | None = None) -> dict:
    """The child environment of every fixture run: the CLI's data root lives inside the temp dir.

    `HOME` drives the bash side, `USERPROFILE` the Windows one (start.cmd/PowerShell have no HOME),
    and `KIMI_CODE_HOME` is removed unless the check is about it. Without this a deployment would
    write profiles into the machine's real `~/.kimi-code/agents` - this test never does that.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop(CATALOG_ENV, None)
    if kimi_home is not None:
        env[CATALOG_ENV] = str(kimi_home)
    env[VENDOR_OFFLINE_ENV] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if path_prefix:
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def catalog_dir(home: pathlib.Path, kimi_home: pathlib.Path | None = None) -> pathlib.Path:
    """Where the CLI reads the user-scope profiles for this fixture."""
    return (kimi_home / "agents") if kimi_home is not None else (home / CATALOG_REL)


def run(argv: list[str], *, cwd: pathlib.Path, env: dict, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)


def expected_roles(repo: pathlib.Path) -> dict[str, pathlib.Path]:
    """The roster the fallback must carry: file name -> source profile, straight from the registry.

    `model_matrix.ROLES`/`ROLE_FILES` are the factory's ONE roster (the catalog probe uses the same
    pair); a profile the roster does not know is reported instead of silently copied or skipped.
    """
    source = repo / ".agents" / "agents" / "sub-agents"
    expect(source.is_dir(),
           f"the factory's sub-agent profiles must live in {source} - the fallback copies are made "
           "from there, so a missing source directory cannot be tested")
    expected: dict[str, pathlib.Path] = {}
    missing: list[str] = []
    for role in ROLES:
        name = ROLE_FILES.get(role, f"{role}.md")
        path = source / name
        if path.is_file():
            expected[name] = path
        else:
            missing.append(name)
    expect(not missing,
           f"the roster names {len(ROLES)} roles but these profiles are missing from {source}: "
           f"{missing} - the fallback can only be as complete as the source catalog")
    extra = sorted(p.name for p in source.glob("*.md") if p.name not in expected)
    expect(not extra,
           f"{source} carries profiles that are not factory roles: {extra} - every profile there is "
           "copied into the user-scope catalog, so an unregistered one must never appear")
    return expected


# --- fixture: deploy a throwaway project, then launch the REAL generated launcher ---------------


class Fixture:
    def __init__(self, kind: str, project: pathlib.Path, home: pathlib.Path,
                 env: dict, result: subprocess.CompletedProcess[str]) -> None:
        self.kind = kind
        self.project = project
        self.home = home
        self.env = env
        self.result = result

    @property
    def launcher(self) -> pathlib.Path:
        return self.project / ("start.sh" if self.kind == "sh" else "start.cmd")


class Launch:
    def __init__(self, result: subprocess.CompletedProcess[str], marker: pathlib.Path,
                 catalog: pathlib.Path) -> None:
        self.result = result
        self.marker = marker
        self.catalog = catalog


FIXTURES: dict[str, Fixture] = {}
ROOT: pathlib.Path = SCRIPTS          # replaced by the temp root in main()

DEPLOYER_NAMES = {"sh": SH_NAME, "cmd": f"{CMD_NAME} / {PS1_NAME}"}
LAUNCHER_NAMES = {"sh": "start.sh", "cmd": "start.cmd"}


def names(kind: str) -> tuple[str, str]:
    return DEPLOYER_NAMES[kind], LAUNCHER_NAMES[kind]


def deploy_argv(kind: str, project: pathlib.Path) -> list[str]:
    if kind == "sh":
        bash = bash_exe()
        expect(bash is not None, "bash must be on PATH for the .sh backend")
        return [str(bash), SH_NAME, str(project)]
    cmd = cmd_exe()
    expect(cmd is not None, "cmd.exe must be available for the .cmd backend")
    return [cmd, "/c", CMD_NAME, str(project)]


def launch_argv(kind: str, project: pathlib.Path) -> list[str]:
    if kind == "sh":
        bash = bash_exe()
        expect(bash is not None, "bash must be on PATH for the .sh backend")
        return [str(bash), "start.sh", "--auto"]
    cmd = cmd_exe()
    expect(cmd is not None, "cmd.exe must be available for the .cmd backend")
    return [cmd, "/c", "start.cmd", "--auto"]


def new_fixture_dirs(name: str) -> tuple[pathlib.Path, pathlib.Path]:
    base = ROOT / name
    home = base / "home"
    project = base / "project"
    home.mkdir(parents=True)
    project.mkdir(parents=True)
    return home, project


def seed_user_catalog(home: pathlib.Path, *, kimi_home: pathlib.Path | None = None) -> pathlib.Path:
    """The user's catalog BEFORE any factory run: one stale managed copy, one unrelated profile."""
    catalog = catalog_dir(home, kimi_home)
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / f"{STALE_ROLE}.md").write_bytes(STALE_PROFILE)
    (catalog / UNRELATED_PROFILE_NAME).write_bytes(UNRELATED_PROFILE)
    return catalog


def fixture(kind: str, repo: pathlib.Path) -> Fixture:
    """Deploy ONCE per backend into a project whose user catalog starts out stale + unrelated."""
    cached = FIXTURES.get(kind)
    if cached is not None:
        return cached
    home, project = new_fixture_dirs(f"{kind}-deployment")
    seed_user_catalog(home)
    env = hermetic_env(home)
    result = run(deploy_argv(kind, project), cwd=repo, env=env, timeout=DEPLOY_TIMEOUT)
    FIXTURES[kind] = Fixture(kind, project, home, env, result)
    return FIXTURES[kind]


def deployed(fixture: Fixture) -> str:
    """Assert the deployment itself succeeded; return its output."""
    deployer, _ = names(fixture.kind)
    text = output_of(fixture.result)
    expect(fixture.result.returncode == 0,
           f"{deployer} must deploy into an empty project successfully, got exit "
           f"{fixture.result.returncode} - the deployment is the only thing that installs the "
           f"portable fallback, so nothing below can be trusted. Output tail:\n{tail(text)}")
    return text


# --- assertions on the catalog ------------------------------------------------------------------


def catalog_files(catalog: pathlib.Path) -> list[str]:
    if not catalog.is_dir():
        return []
    return sorted(p.name for p in catalog.iterdir() if p.is_file())


def assert_catalog(catalog: pathlib.Path, expected: dict[str, pathlib.Path], label: str,
                   *, extra_allowed: tuple[str, ...] = ()) -> None:
    """The user-scope catalog is EXACTLY the factory's profiles: complete, byte-identical, no more."""
    files = catalog_files(catalog)
    expect(catalog.is_dir(),
           f"{label}: the CLI's user-scope profile catalog must exist at {catalog} - the user scope "
           f"is the durable fallback for the intermittent project-catalog loss, and an absent "
           f"directory is exactly the state that makes every role 'Unknown agent type'")
    missing = sorted(set(expected) - set(files))
    expect(not missing,
           f"{label}: the user-scope catalog {catalog} is missing {len(missing)} factory role(s) "
           f"{missing} - ALL {len(expected)} roles must be installed, otherwise a run that loses "
           "its project catalog still cannot start the missing role")
    stale = sorted(name for name, source in expected.items()
                   if sha256(catalog / name) != sha256(source))
    source_dir = next(iter(expected.values())).parent if expected else "(the project catalog)"
    expect(not stale,
           f"{label}: the user-scope copies {stale} differ from {source_dir} - the fallback must "
           "be a BYTE-FOR-BYTE copy (a stale profile carries old instructions and the old "
           "model_preference, so the run would silently use the wrong model)")
    unexpected = sorted(set(files) - set(expected) - set(extra_allowed))
    expect(not unexpected,
           f"{label}: the factory wrote files it does not manage into {catalog}: {unexpected} - the "
           "user-scope directory is shared with the user's own agents; only the 16 factory profiles "
           "may be written, and everything else must be left alone")


def assert_unrelated_untouched(catalog: pathlib.Path, label: str) -> None:
    path = catalog / UNRELATED_PROFILE_NAME
    expect(path.is_file(),
           f"{label}: the user's own profile {path} was DELETED - the factory manages only its own "
           "role copies in the shared user-scope directory")
    expect(path.read_bytes() == UNRELATED_PROFILE,
           f"{label}: the user's own profile {path} was modified - it must survive byte for byte")


def marker_text(launch: Launch) -> str:
    """The fake CLI's record, or an actionable failure when the launcher never reached it."""
    expect(launch.marker.is_file(),
           "the launcher must start the Kimi CLI (a fake `kimi` on PATH writes a marker file) - it "
           f"was never reached; exit {launch.result.returncode}. Output tail:\n"
           f"{tail(output_of(launch.result))}")
    return launch.marker.read_text(encoding="utf-8", errors="replace")


def launched_profiles(text: str) -> dict[str, int]:
    profiles: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^profile=(\d+)\s+(\S+)\s*$", line.strip())
        if match:
            profiles[match.group(2)] = int(match.group(1))
    return profiles


def assert_launched(launch: Launch, expected: dict[str, pathlib.Path], label: str) -> None:
    """The catalog AS THE CLI SAW IT at start-up was complete and current (the order is the point)."""
    text = marker_text(launch)
    expect("args=--auto" in text,
           f"{label}: the launcher must forward its arguments to the CLI unchanged (expected "
           f"'args=--auto' in the fake CLI's record); got:\n{tail(text)}")
    seen = launched_profiles(text)
    want = {name: source.stat().st_size for name, source in expected.items()}
    missing = sorted(set(want) - set(seen))
    wrong = sorted(name for name in set(want) & set(seen) if want[name] != seen[name])
    extra = sorted(set(seen) - set(want) - {UNRELATED_PROFILE_NAME})
    expect(not (missing or wrong or extra),
           f"{label}: the CLI started BEFORE the fallback catalog was complete/current - at launch "
           f"it saw {len(seen)} profile(s); missing {missing}, stale (wrong size) {wrong}, "
           f"unexpected {extra}. The refresh must run BEFORE the CLI is started: a launch that "
           "syncs afterwards hands the session the old catalog")


def assert_no_interpreter(launcher: pathlib.Path, kind: str, label: str) -> None:
    """The refresh must be native shell/cmd only - a launcher that needs python is not a fallback."""
    expect(launcher.is_file(), f"{label}: {launcher.name} was not created by the deployer")
    text = launcher.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if kind == "sh":
            if stripped.startswith("#"):
                continue
        elif lowered.startswith("rem ") or lowered == "rem" or stripped.startswith("::"):
            continue
        if INTERPRETER_RE.search(line):
            hits.append(stripped)
    expect(not hits,
           f"{label}: {launcher.name} must refresh the fallback with native commands only, but it "
           f"names an interpreter on: {hits[:3]} - the factory has to start on a machine without "
           "python, so the launcher may not depend on it")


# --- the fake CLI and the interpreter shadow ----------------------------------------------------

FAKE_KIMI_SH = """#!/usr/bin/env bash
# Fake Kimi Code CLI written by test_stable_agent_catalog.py: no session is ever started.
# It records HOW it was reached and the fallback catalog it saw AT LAUNCH TIME, so a launcher that
# syncs after starting the CLI (or not at all) cannot pass the ordering assertion.
set -u
{
    printf 'args=%s\\n' "$*"
    printf 'launch_dir=%s\\n' "${KIMI_FACTORY_LAUNCH_DIR:-}"
    printf 'cwd=%s\\n' "$(pwd)"
    if [ -n "${FAKE_KIMI_CATALOG:-}" ] && [ -d "${FAKE_KIMI_CATALOG}" ]; then
        for profile in "${FAKE_KIMI_CATALOG}"/*.md; do
            [ -f "$profile" ] || continue
            printf 'profile=%s %s\\n' "$(wc -c < "$profile" | tr -d ' \\r\\n')" "$(basename "$profile")"
        done
    fi
} > "${FAKE_KIMI_MARKER:-/dev/null}"
exit 0
"""

FAKE_KIMI_CMD = """@echo off
rem Fake Kimi Code CLI written by test_stable_agent_catalog.py: no session is ever started.
rem It records HOW it was reached and the fallback catalog it saw AT LAUNCH TIME, so a launcher
rem that syncs after starting the CLI (or not at all) cannot pass the ordering assertion.
> "%FAKE_KIMI_MARKER%" echo args=%*
>> "%FAKE_KIMI_MARKER%" echo launch_dir=%KIMI_FACTORY_LAUNCH_DIR%
>> "%FAKE_KIMI_MARKER%" echo cwd=%CD%
if defined FAKE_KIMI_CATALOG (
    for %%F in ("%FAKE_KIMI_CATALOG%\\*.md") do >> "%FAKE_KIMI_MARKER%" echo profile=%%~zF %%~nxF
)
exit /b 0
"""

SH_PY_STUB = "#!/bin/sh\nexit 1\n"
CMD_PY_STUB = "@rem test stub: a python that never works\r\n@exit /b 1\r\n"


def fake_cli_dir(base: pathlib.Path, kind: str) -> pathlib.Path:
    directory = base / "fake kimi"
    directory.mkdir(parents=True, exist_ok=True)
    if kind == "sh":
        path = directory / "kimi"
        path.write_bytes(FAKE_KIMI_SH.encode("utf-8"))
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    else:
        (directory / "kimi.cmd").write_bytes(FAKE_KIMI_CMD.encode("utf-8"))
    return directory


def python_stub_dir(base: pathlib.Path, kind: str) -> pathlib.Path:
    """A PATH-shadowing directory whose python/python3/py all fail (the no-python fixture)."""
    directory = base / "no python"
    directory.mkdir(parents=True, exist_ok=True)
    suffixes = [""] if kind == "sh" else [".cmd"]
    text = SH_PY_STUB if kind == "sh" else CMD_PY_STUB
    for name in ("python", "python3", "py"):
        for suffix in suffixes:
            path = directory / (name + suffix)
            path.write_bytes(text.encode("utf-8"))
            if kind == "sh":
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


def launch(fixture_: Fixture, base: pathlib.Path, *, home: pathlib.Path,
           kimi_home: pathlib.Path | None = None, python_shadow: bool = False) -> Launch:
    """Run the REAL generated launcher with a fake CLI first on PATH."""
    marker = base / "kimi-marker.txt"
    if marker.exists():
        marker.unlink()
    prefix = [str(fake_cli_dir(base, fixture_.kind))]
    if python_shadow:
        prefix.insert(0, str(python_stub_dir(base, fixture_.kind)))
    extra = {MARKER_ENV: str(marker), FAKE_CATALOG_ENV: str(catalog_dir(home, kimi_home))}
    env = hermetic_env(home, kimi_home=kimi_home, path_prefix=os.pathsep.join(prefix), extra=extra)
    result = run(launch_argv(fixture_.kind, fixture_.project), cwd=fixture_.project, env=env,
                 timeout=LAUNCH_TIMEOUT)
    return Launch(result, marker, catalog_dir(home, kimi_home))


def launch_dirs(name: str, *, seed: bool) -> tuple[pathlib.Path, pathlib.Path]:
    base = ROOT / name
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    if seed:
        seed_user_catalog(home)
    return base, home


# --- checks (each backend runs the same set against its own real launcher) ----------------------


def check_deployer_installs(repo: pathlib.Path, kind: str) -> None:
    deployer, _ = names(kind)
    fixture_ = fixture(kind, repo)
    deployed(fixture_)
    expected = expected_roles(repo)
    catalog = catalog_dir(fixture_.home)
    assert_catalog(catalog, expected,
                   f"{deployer}: preparation must install the portable user-scope catalog "
                   f"({len(expected)} roles)",
                   extra_allowed=(UNRELATED_PROFILE_NAME,))
    assert_unrelated_untouched(catalog, f"{deployer}: preparation")


def check_launcher_installs_before_launch(repo: pathlib.Path, kind: str) -> None:
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    expected = expected_roles(repo)
    base, home = launch_dirs(f"{kind}-launch-fresh", seed=False)
    result = launch(fixture_, base, home=home)
    expect(result.result.returncode == 0,
           f"{launcher_name}: a launch must succeed with an empty user-scope catalog (the launcher "
           f"installs it), got exit {result.result.returncode}. Output tail:\n"
           f"{tail(output_of(result.result))}")
    assert_catalog(result.catalog, expected, f"{launcher_name}: before the CLI starts")
    assert_launched(result, expected, f"{launcher_name}: first launch")


def check_launcher_refreshes_stale(repo: pathlib.Path, kind: str) -> None:
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    expected = expected_roles(repo)
    base, home = launch_dirs(f"{kind}-launch-seeded", seed=True)
    result = launch(fixture_, base, home=home)
    expect(result.result.returncode == 0,
           f"{launcher_name}: a launch must succeed with a STALE managed profile in the user "
           f"catalog (it is refreshed), got exit {result.result.returncode}. Output tail:\n"
           f"{tail(output_of(result.result))}")
    assert_catalog(result.catalog, expected, f"{launcher_name}: refreshing a stale managed profile",
                   extra_allowed=(UNRELATED_PROFILE_NAME,))
    assert_unrelated_untouched(result.catalog, f"{launcher_name}: refreshing")
    assert_launched(result, expected, f"{launcher_name}: launch over a stale profile")


def check_launcher_without_project_catalog(repo: pathlib.Path, kind: str) -> None:
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    expected = expected_roles(repo)
    base, home = launch_dirs(f"{kind}-launch-absent", seed=False)
    # A COPY of the deployed project: deleting the project catalog here must not affect the other
    # checks (they share the deployed fixture, and each one needs its project catalog intact).
    project = base / "project"
    shutil.copytree(fixture_.project, project, symlinks=True)
    absent = Fixture(kind, project, home, fixture_.env, fixture_.result)
    first = launch(absent, base, home=home)
    expect(first.result.returncode == 0,
           f"{launcher_name}: the first launch (which installs the fallback) must succeed, got exit "
           f"{first.result.returncode}. Output tail:\n{tail(output_of(first.result))}")
    source = project / ".agents" / "agents" / "sub-agents"
    expect(source.is_dir(), f"the deployed project must carry its own catalog at {source}")
    remove_tree(source)                     # the CLI's project-scoped catalog disappears
    result = launch(absent, base, home=home)
    expect(result.result.returncode == 0,
           f"{launcher_name}: a launch must still succeed when the PROJECT catalog is absent "
           f"({source} was deleted) - that is exactly what the user-scope fallback is for; got exit "
           f"{result.result.returncode}. Output tail:\n{tail(output_of(result.result))}")
    assert_catalog(result.catalog, expected, f"{launcher_name}: launch without a project catalog")
    assert_launched(result, expected, f"{launcher_name}: launch without a project catalog")


def check_launcher_sync_failure_aborts(repo: pathlib.Path, kind: str) -> None:
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    base, home = launch_dirs(f"{kind}-launch-blocked", seed=False)
    catalog = catalog_dir(home)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_bytes(b"not a directory\n")     # the catalog CANNOT be created or refreshed
    result = launch(fixture_, base, home=home)
    text = output_of(result.result)
    expect(result.result.returncode != 0,
           f"{launcher_name}: an un-refreshable user-scope catalog ({catalog} is a FILE) must abort "
           "the launch with a nonzero exit - starting a session whose roles may be missing or stale "
           f"is the failure this fallback prevents; got exit {result.result.returncode}. "
           f"Output tail:\n{tail(text)}")
    expect(not result.marker.exists(),
           f"{launcher_name}: the CLI must NOT be started when the fallback could not be refreshed "
           f"(the fake CLI wrote {result.marker}); exit was {result.result.returncode}")
    low = text.lower()
    expect("code factory" in low and "agent" in low and any(word in low for word in FAILURE_WORDS),
           f"{launcher_name}: the failure must be REPORTED by the launcher itself - a message that "
           "names the profile catalog and what went wrong, starting with the factory's own "
           f"branding ('Code Factory:'), never a silent exit and never raw shell noise. Got:\n"
           f"{tail(text)}")


def project_catalog(repo: pathlib.Path) -> pathlib.Path:
    """The factory's own sub-agent profiles, i.e. what a deployment copies into the project."""
    return repo / ".agents" / "agents" / "sub-agents"


# Roles the incomplete-fallback check leaves OUT of the user catalog.
INCOMPLETE_ROLE_FILES = ("analyzer.md", "coder.md", "tester.md")
# The role whose stale user-scope copy the partial-project-catalog check leaves behind.
STALE_ROLE_FILE = "coder.md"
# The role whose user-scope copy cannot be refreshed (the name is occupied by a directory).
BLOCKED_ROLE_FILE = "skill-manager.md"


def assert_launch_refused(launch_: Launch, launcher_name: str, label: str,
                          mentions: tuple[str, ...] = ()) -> str:
    """The launcher aborted: nonzero exit, no CLI, the factory's own branded message, named cause."""
    text = output_of(launch_.result)
    low = text.lower()
    expect(launch_.result.returncode != 0,
           f"{launcher_name}: {label} — the launch must be REFUSED with a nonzero exit, got exit "
           f"{launch_.result.returncode}. Output tail:\n{tail(text)}")
    expect(not launch_.marker.exists(),
           f"{launcher_name}: {label} — the CLI must NOT be started (the fake CLI wrote "
           f"{launch_.marker}); the session would have missing or stale roles. Output tail:\n"
           f"{tail(text)}")
    expect("code factory" in low and "agent" in low and any(word in low for word in FAILURE_WORDS),
           f"{launcher_name}: {label} — the refusal must be REPORTED by the launcher itself, under "
           f"its own 'Code Factory:' branding and naming the agent catalog; got:\n{tail(text)}")
    if mentions:
        expect(any(name in text for name in mentions),
               f"{launcher_name}: {label} — the message must name the role profile(s) at fault "
               f"{list(mentions)}; got:\n{tail(text)}")
    return text


def check_absent_project_incomplete_fallback_aborts(repo: pathlib.Path, kind: str) -> None:
    """BT-CAT-02: an absent project catalog is legal ONLY over a COMPLETE user-scope fallback."""
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    deployed(fixture_)
    expected = expected_roles(repo)
    base, home = launch_dirs(f"{kind}-launch-incomplete", seed=False)
    catalog = catalog_dir(home)
    catalog.mkdir(parents=True, exist_ok=True)
    source = project_catalog(repo)
    for name in expected:
        if name not in INCOMPLETE_ROLE_FILES:
            shutil.copyfile(source / name, catalog / name)
    project = base / "project"
    shutil.copytree(fixture_.project, project, symlinks=True)
    absent = Fixture(kind, project, home, fixture_.env, fixture_.result)
    remove_tree(project / ".agents" / "agents" / "sub-agents")
    result = launch(absent, base, home=home)
    assert_launch_refused(result, launcher_name,
                          f"the project catalog is absent and the user-scope fallback lacks "
                          f"{list(INCOMPLETE_ROLE_FILES)}", INCOMPLETE_ROLE_FILES)


def check_partial_project_catalog_aborts(repo: pathlib.Path, kind: str) -> None:
    """BT-CAT-03: a partial project catalog must abort, never leave a role stale and launch."""
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    deployed(fixture_)
    expected_roles(repo)
    base, home = launch_dirs(f"{kind}-launch-partial", seed=False)
    project = base / "project"
    shutil.copytree(fixture_.project, project, symlinks=True)
    partial = Fixture(kind, project, home, fixture_.env, fixture_.result)
    first = launch(partial, base, home=home)
    expect(first.result.returncode == 0,
           f"{launcher_name}: the first launch (which installs the fallback) must succeed, got exit "
           f"{first.result.returncode}. Output tail:\n{tail(output_of(first.result))}")
    (first.catalog / STALE_ROLE_FILE).write_bytes(STALE_PROFILE)
    source = project / ".agents" / "agents" / "sub-agents"
    expect((source / STALE_ROLE_FILE).is_file(),
           f"the deployed project must carry {STALE_ROLE_FILE} at {source}")
    (source / STALE_ROLE_FILE).unlink()
    result = launch(partial, base, home=home)
    assert_launch_refused(result, launcher_name,
                          f"the project catalog is missing {STALE_ROLE_FILE} while the user-scope "
                          f"copy of it is stale", (STALE_ROLE_FILE,))
    expect((result.catalog / STALE_ROLE_FILE).read_bytes() == STALE_PROFILE,
           f"{launcher_name}: the stale copy {result.catalog / STALE_ROLE_FILE} was neither "
           "refreshed nor refused — the role would have run with an older release's instructions "
           "and model preference")


def check_unrefreshable_role_aborts(repo: pathlib.Path, kind: str) -> None:
    """A role copy that cannot be refreshed byte-exactly is a launch refusal, not a warning."""
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    deployed(fixture_)
    base, home = launch_dirs(f"{kind}-launch-blocked-role", seed=False)
    catalog = catalog_dir(home)
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / BLOCKED_ROLE_FILE).mkdir()      # the copy cannot land: the name is a directory
    result = launch(fixture_, base, home=home)
    assert_launch_refused(result, launcher_name,
                          f"{catalog / BLOCKED_ROLE_FILE} cannot be replaced by the factory's copy",
                          (BLOCKED_ROLE_FILE,))


def check_launcher_roster_matches(repo: pathlib.Path, kind: str) -> None:
    """The launcher's native role list IS model_matrix's roster — one roster, verified not assumed."""
    _, launcher_name = names(kind)
    launcher = fixture(kind, repo).launcher
    expect(launcher.is_file(), f"{launcher_name}: {launcher} was not created by the deployer")
    lines = [line for line in launcher.read_text(encoding="utf-8", errors="replace").splitlines()
             if "CF_AGENT_ROLES=" in line]
    expect(len(lines) == 1,
           f"{launcher_name}: exactly one `CF_AGENT_ROLES=` line is expected (the native copy of the "
           f"roster), got {lines}")
    roster = set(lines[0].split("CF_AGENT_ROLES=", 1)[1].strip().strip('"').split())
    want = {ROLE_FILES.get(role, f"{role}.md")[:-3] for role in ROLES}
    expect(roster == want,
           f"{launcher_name}: the native role list must be model_matrix's roster — "
           f"missing {sorted(want - roster)}, unexpected {sorted(roster - want)}. A launcher that "
           "checks the wrong set of roles either refuses a healthy catalog or accepts a broken one")


def check_launcher_is_interpreter_free(repo: pathlib.Path, kind: str) -> None:
    _, launcher_name = names(kind)
    fixture_ = fixture(kind, repo)
    expected = expected_roles(repo)
    assert_no_interpreter(fixture_.launcher, kind, launcher_name)
    base, home = launch_dirs(f"{kind}-launch-no-python", seed=False)
    result = launch(fixture_, base, home=home, python_shadow=True)
    expect(result.result.returncode == 0,
           f"{launcher_name}: a launch must succeed on a machine where python/python3/py all fail - "
           f"the fallback refresh has to be native; got exit {result.result.returncode}. Output "
           f"tail:\n{tail(output_of(result.result))}")
    assert_catalog(result.catalog, expected, f"{launcher_name}: refresh without an interpreter")
    assert_launched(result, expected, f"{launcher_name}: refresh without an interpreter")


def check_kimi_code_home(repo: pathlib.Path, kind: str) -> None:
    deployer, launcher_name = names(kind)
    expected = expected_roles(repo)
    base = ROOT / f"{kind}-kimi-home"
    home = base / "home"
    project = base / "project"
    kimi_home = base / "relocated home"
    for path in (home, project, kimi_home):
        path.mkdir(parents=True)
    env = hermetic_env(home, kimi_home=kimi_home)
    result = run(deploy_argv(kind, project), cwd=repo, env=env, timeout=DEPLOY_TIMEOUT)
    expect(result.returncode == 0,
           f"{deployer}: deployment with KIMI_CODE_HOME set must succeed, got exit "
           f"{result.returncode}. Output tail:\n{tail(output_of(result))}")
    relocated = catalog_dir(home, kimi_home)
    assert_catalog(relocated, expected,
                   f"{deployer}: with KIMI_CODE_HOME set the CLI reads its profiles from "
                   f"{relocated} (the variable relocates the whole data root)")
    stray = sorted(name for name in expected if (catalog_dir(home) / name).is_file())
    expect(not stray,
           f"{deployer}: with KIMI_CODE_HOME set the fallback was written to "
           f"{catalog_dir(home)} instead - that CLI never looks there, so those copies are dead "
           f"weight and the real catalog stays empty ({stray[:3]}...)")
    remove_tree(relocated)                  # the launcher must be able to rebuild it on its own
    fixture_ = Fixture(kind, project, home, env, result)
    launched = launch(fixture_, base, home=home, kimi_home=kimi_home)
    expect(launched.result.returncode == 0,
           f"{launcher_name}: with KIMI_CODE_HOME set the launcher must refresh that catalog and "
           f"start, got exit {launched.result.returncode}. Output tail:\n"
           f"{tail(output_of(launched.result))}")
    assert_catalog(launched.catalog, expected,
                   f"{launcher_name}: with KIMI_CODE_HOME set")
    assert_launched(launched, expected, f"{launcher_name}: with KIMI_CODE_HOME set")


# --- runner -------------------------------------------------------------------------------------


class Checker:
    """One PASS/FAIL/SKIP line per logical check; a failure never aborts the remaining checks."""

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []

    def check(self, label: str, run_check: Callable[[], object]) -> None:
        try:
            run_check()
        except AssertionError as exc:
            self._fail(label, str(exc) or "assertion failed")
        except Exception as exc:          # infrastructure trouble is still just one failed check
            self._fail(label, f"{type(exc).__name__}: {exc}")
        else:
            self.passed += 1
            print(f"PASS - {label}")

    def _fail(self, label: str, message: str) -> None:
        self.failed.append((label, message))
        print(f"FAIL - {label}")
        for line in message.splitlines() or [""]:
            print(f"       {line}")

    def skip(self, label: str, reason: str) -> None:
        self.skipped += 1
        print(f"SKIP - {label} ({reason})")

    def finish(self) -> int:
        print("")
        print(f"SUMMARY - {self.passed} PASS, {len(self.failed)} FAIL, {self.skipped} SKIP "
              f"(repo {REPO})")
        for label, message in self.failed:
            print(f"  FAILED: {label}")
            print(f"          {message.splitlines()[0] if message.splitlines() else ''}")
        if self.failed:
            print(f"FAIL - stable agent catalog: {len(self.failed)} check(s) failed.")
            return 1
        print("PASS - the user-scope agent catalog is a portable, durable fallback: both deployers "
              "install the exact role copies at preparation time, both launchers refresh them "
              "BEFORE the CLI starts with native commands only, an unrelated user profile and the "
              "user's own agents survive, a launch works with the project catalog absent ONLY over "
              "a complete user-scope catalog, an incomplete fallback / a partial project catalog / "
              "a role copy that cannot be refreshed byte-for-byte each REFUSE the launch (nonzero "
              "exit, no CLI, branded message naming the role), the native role list is the "
              "registry's roster, a failed refresh aborts the launch loudly, and KIMI_CODE_HOME is "
              "followed by both sides.")
        return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr (a legacy Windows code page would mangle the messages)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


CHECKS: tuple[tuple[str, Callable[[pathlib.Path, str], None]], ...] = (
    ("{deployer}: installs the exact user-scope catalog ({count} roles), refreshes a stale managed "
     "profile, preserves an unrelated user profile", check_deployer_installs),
    ("{launcher}: fills an EMPTY user-scope catalog BEFORE the CLI starts (all roles present at "
     "launch)", check_launcher_installs_before_launch),
    ("{launcher}: refreshes a stale managed profile and leaves the user's own profile untouched",
     check_launcher_refreshes_stale),
    ("{launcher}: starts when the project's own catalog is ABSENT (the fallback carries the run)",
     check_launcher_without_project_catalog),
    ("{launcher}: an un-refreshable fallback aborts the launch (nonzero exit, no CLI, actionable "
     "message)", check_launcher_sync_failure_aborts),
    ("{launcher}: refuses the launch when the project catalog is ABSENT and the user-scope fallback "
     "is incomplete", check_absent_project_incomplete_fallback_aborts),
    ("{launcher}: refuses the launch over a PARTIAL project catalog (a role would stay stale)",
     check_partial_project_catalog_aborts),
    ("{launcher}: refuses the launch when a role copy cannot be refreshed byte-for-byte",
     check_unrefreshable_role_aborts),
    ("{launcher}: no interpreter dependency (native refresh; still works with python/python3/py "
     "failing)", check_launcher_is_interpreter_free),
    ("{launcher}: the native role list is model_matrix's roster (one roster, no drift)",
     check_launcher_roster_matches),
    ("KIMI_CODE_HOME: {deployer} and {launcher} follow the CLI's relocated data root",
     check_kimi_code_home),
)


def backend_checks(checker: Checker, repo: pathlib.Path, kind: str,
                   reason: str | None) -> None:
    deployer, launcher = names(kind)
    count = len(ROLES)
    try:
        expected_roles(repo)
    except AssertionError as exc:
        checker._fail("the role roster is complete", str(exc))
    for template, check in CHECKS:
        label = template.format(deployer=deployer, launcher=launcher, count=count)
        if reason:
            checker.skip(label, reason)
        else:
            checker.check(label, lambda c=check, k=kind: c(repo, k))


def main() -> int:
    global ROOT
    use_utf8_output()
    checker = Checker()
    if FOUND_REPO is None:
        checker.skip("all stable-agent-catalog checks",
                     f"the factory repo root was not found above {SCRIPTS} "
                     f"({', '.join(REPO_FILES)} must live in one directory) - this looks like a "
                     "project deployed by the factory, not the factory repo itself")
        return checker.finish()

    ROOT = pathlib.Path(tempfile.mkdtemp(prefix="cf catalog fallback "))
    try:
        backend_checks(checker, REPO, "sh", sh_prerequisite())
        backend_checks(checker, REPO, "cmd", cmd_prerequisite())
    finally:
        remove_tree(ROOT)
    return checker.finish()


if __name__ == "__main__":
    sys.exit(main())

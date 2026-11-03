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
  - keeps that BASE schema byte-compatible WITHOUT the OPT-IN `--web-gui` flag, and with it appends
    the nested `web_gui` browser block (node/npm/npx versions, Chrome / Chrome for Testing presence,
    MCP server start feasibility, delegated to `chrome_devtools_mcp.py`) — where a missing
    capability or a `--simulate-missing <name>` forced miss is DATA with a reason, never a change of
    the exit code (only python+git are fatal),
  - never calls the browser path usable on the strength of the shipped template alone: the resolved
    repository (`--repo`) is threaded into the delegated probe, and `mcp_usable` may only be true
    when that repository's OWN `.kimi-code/mcp.json` exists, passes the safety invariants of
    `chrome_devtools_mcp.py` AND the pinned vendored entry the managed server launches is on disk —
    anything else reports the exact missing capability (a clean repository without a deployed config
    must never claim a usable browser path),
  - prints a human-readable summary naming python, git, bash/sh, the OS and the flag,
  - appends the OPT-IN `farukon` block only with `--farukon` (cargo, whether the repository hosts
    the Farukon platform, the managed Farukon MCP config), delegated to `farukon_mcp.py` WITHOUT a
    build and WITHOUT an MCP server start — pinned with a stand-in `cargo` that records every
    invocation, so `cargo run`/`build`/`test` reaching the host fails the suite — and with the
    verdict `usable` / `degraded` / `not_applicable` (a missing cargo is forced through the same
    `--simulate-missing` seam the browser block uses), never a change of the exit code — the
    `not_applicable` case is probed against a CLEAN fixture root, so the suite never depends on
    whether this machine's own (untracked, gitignored) `.kimi-code/mcp.json` carries a `farukon`
    entry,
  - anchors a RELATIVE `--out` at the OPTIONAL `--repo`/`--root` anchor (the run's resolved
    repo_path) instead of the launch directory, while an absolute `--out` stays as it is and the
    flag-less invocation keeps resolving against the cwd,
  - degrades explicitly: with a PATH that contains no tools it exits 1 and records nulls instead
    of inventing a command.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import pathlib
import platform
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "factory_preflight.py"
HELPER = SCRIPTS / "chrome_devtools_mcp.py"
FARUKON_HELPER = SCRIPTS / "farukon_mcp.py"
# The managed-config contract of `.kimi-code/mcp.json` (validity + the pinned vendored entry) lives in
# `chrome_devtools_mcp.py`, so the fixtures below are built with ITS functions instead of a second,
# hand-written copy of the config that could drift.
MCP_RELPARTS = (".kimi-code", "mcp.json")

# The BASE schema — exactly these keys are written WITHOUT `--web-gui`, so a non-Web-GUI run keeps
# the byte-compatible capability file it had before the flag existed.
KEYS = ("python_cmd", "python_version", "git", "git_version", "bash", "sh", "os",
        "secondary_model_env")
# The OPT-IN nested block (`--web-gui`) and the browser capabilities it reports, delegated to the
# sibling `chrome_devtools_mcp.py` probe; a missing capability is DATA with a reason, never fatal.
WEB_GUI_KEYS = ("source", "managed_config", "simulate_missing", "capabilities", "missing",
                "browser_usable", "mcp_usable", "verdict")
WEB_GUI_CAPABILITIES = ("node", "npm", "npx", "chrome", "chrome_for_testing", "mcp_server")
# The OPT-IN nested block of the Farukon path (`--farukon`) and the capabilities it reports; the
# verdict is one of these three tokens.
FARUKON_KEYS = ("source", "repo", "managed_config", "simulate_missing", "capabilities", "missing",
                "farukon_usable", "verdict", "verdict_reason")
FARUKON_CAPABILITIES = ("cargo", "platform", "mcp_config")
FARUKON_VERDICTS = ("usable", "degraded", "not_applicable")
PYTHON_CANDIDATES = ("python", "python3", "py")


def load_helper():
    """The sibling `chrome_devtools_mcp.py`, loaded by path (no package, no side effects)."""
    spec = importlib.util.spec_from_file_location("chrome_devtools_mcp_fixture", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deploy(repo: pathlib.Path, helper) -> pathlib.Path:
    """Deploy the managed MCP layout of `repo` WITHOUT npm (the documented offline seam).

    Returns the managed config path. `vendor-install --offline` writes the pinned package skeleton and
    `merge-config` then writes the config that points at it — the two steps the deployers run.
    """
    config = repo.joinpath(*MCP_RELPARTS)
    installed = helper.vendor_install(helper.vendor_dir_for(config), offline=True)
    expect(installed["installed"] is True,
           f"the offline vendor-install seam must write the pinned entry: {installed!r}")
    merged = helper.merge_config(config)
    expect(merged["status"] == "created" and config.is_file(),
           f"merge-config must create the managed config: {merged!r}")
    return config


def web_gui(tmp: pathlib.Path, *args: str, name: str) -> dict:
    """Run the pre-flight with `--web-gui` and return its nested block (always exit 0 here)."""
    out = tmp / name
    res = run("--web-gui", *args, "--out", str(out))
    expect(res.returncode == 0,
           f"--web-gui must exit 0 while python+git are present: rc={res.returncode} {res.stderr!r}")
    return json.loads(out.read_text(encoding="utf-8"))["web_gui"]


def load_farukon_helper():
    """The sibling `farukon_mcp.py`, loaded by path (the managed-config contract stays in ONE home)."""
    spec = importlib.util.spec_from_file_location("farukon_mcp_fixture", FARUKON_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_preflight_module():
    """The `factory_preflight.py` under test, loaded by path so a seam can be injected in-process."""
    spec = importlib.util.spec_from_file_location("factory_preflight_fixture", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def failing_farukon_helper(module, message: str):
    """Make the delegated Farukon probe EXPLODE, the way a broken helper or a hostile site would."""
    original = module._load_farukon_helper

    def explode():
        raise RuntimeError(message)

    module._load_farukon_helper = explode
    try:
        yield
    finally:
        module._load_farukon_helper = original


def platform_repo(root: pathlib.Path, helper, with_config: bool = True) -> pathlib.Path:
    """A minimal Farukon platform fixture: the crate manifest, the workspace member and (optionally)
    the managed config, built with `farukon_mcp.py`'s own `managed_entry` so the fixture cannot drift
    from the definition the probe validates."""
    (root / "farukon_mcp").mkdir(parents=True, exist_ok=True)
    (root / "farukon_mcp" / "Cargo.toml").write_text(
        '[package]\nname = "farukon_mcp"\nversion = "0.1.0"\n', encoding="utf-8")
    (root / "Cargo.toml").write_text('[workspace]\nmembers = ["farukon_mcp"]\n', encoding="utf-8")
    if with_config:
        config = root.joinpath(*MCP_RELPARTS)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"mcpServers": {helper.SERVER_NAME: helper.managed_entry(root)}},
                                     indent=2) + "\n", encoding="utf-8")
    return root


def fake_cargo(bin_dir: pathlib.Path, marker: pathlib.Path) -> pathlib.Path:
    """A stand-in `cargo` that LOGS every invocation and answers only `--version`.

    The pre-flight may read the toolchain version, but it must never build the platform or start the
    MCP server: every argv handed to cargo lands in `marker`, so the case below can assert that no
    `run`/`build`/`test` invocation was ever made (a real cargo could build for half an hour).
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = bin_dir / "cargo.bat"
        body = (f'@echo off\r\necho %*>>"{marker}"\r\n'
                'if "%1"=="--version" echo cargo 1.99.0\r\n'
                'if "%1"=="--version" exit /b 0\r\nexit /b 1\r\n')
    else:
        script = bin_dir / "cargo"
        body = (f'#!/bin/sh\necho "$@" >> "{marker}"\n'
                'if [ "$1" = "--version" ]; then echo "cargo 1.99.0"; exit 0; fi\nexit 1\n')
    script.write_text(body, encoding="utf-8", newline="")
    if os.name != "nt":
        script.chmod(0o755)
    return script


def farukon_env(bin_dir: pathlib.Path) -> dict:
    """The environment of the faked-toolchain runs: the stand-in cargo FIRST, everything else intact."""
    return dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))


def farukon(tmp: pathlib.Path, *args: str, name: str,
            env: dict | None = None) -> dict:
    """Run the pre-flight with `--farukon` and return its nested block (always exit 0 here)."""
    out = tmp / name
    res = run("--farukon", *args, "--out", str(out), env=env)
    expect(res.returncode == 0,
           f"--farukon must exit 0 while python+git are present: rc={res.returncode} {res.stderr!r}")
    return json.loads(out.read_text(encoding="utf-8"))["farukon"]


def run(*args: str, env: dict | None = None,
        cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", env=env, cwd=cwd)


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

        # 7. `--repo`/`--root` anchors a RELATIVE --out at the resolved repo_path, so the capability
        #    file lands in the target repository and never in the launch directory; without the flag
        #    the cwd stays the base (case 1 uses an absolute --out and is unaffected), and an
        #    absolute --out is never re-anchored.
        launch = tmp / "launch"
        launch.mkdir()
        repo = tmp / "target" / "repo"
        res = run("--repo", str(repo), "--out", "state/preflight.json", cwd=str(launch))
        expect(res.returncode == 0, f"--repo must anchor a relative --out: {res.stderr!r}")
        anchored = repo / "state" / "preflight.json"
        expect(anchored.is_file(),
               "--repo must write a relative --out under the resolved repo_path")
        expect(str(anchored) in res.stdout,
               f"the summary must name the file actually written: {res.stdout!r}")
        expect(not (launch / "state").exists(),
               "nothing may be written into the launch directory when --repo is given")
        res = run("--root", str(repo), "--out", "alias.json", cwd=str(launch))
        expect(res.returncode == 0 and (repo / "alias.json").is_file(),
               f"--root must be accepted as a synonym of --repo: {res.stderr!r}")
        res = run("--out", "state/preflight.json", cwd=str(launch))
        expect(res.returncode == 0 and (launch / "state" / "preflight.json").is_file(),
               f"without --repo the cwd stays the base: {res.stderr!r}")
        res = run("--repo", str(repo), "--out", str(tmp / "abs.json"), cwd=str(launch))
        expect(res.returncode == 0 and (tmp / "abs.json").is_file(),
               "an absolute --out must be taken as it is, flag or not")

        # 8. The OPT-IN `--web-gui` block: without the flag the schema of cases 1/2 is untouched (no
        #    `web_gui` key), with it a nested browser capability class is appended — node/npm/npx,
        #    Chrome / Chrome for Testing and the MCP server start feasibility — and the exit code
        #    still depends on python+git alone.
        expect("web_gui" not in caps,
               f"without --web-gui the schema must stay exactly as before: {sorted(caps)}")
        gui_out = tmp / "web-gui.json"
        res = run("--web-gui", "--out", str(gui_out))
        expect(res.returncode == 0, f"--web-gui must exit 0 with python+git present: {res.stderr!r}")
        gui = json.loads(gui_out.read_text(encoding="utf-8"))
        for key in KEYS:
            expect(key in gui, f"--web-gui must keep every base capability {key!r}: {sorted(gui)}")
        block = gui["web_gui"]
        for key in WEB_GUI_KEYS:
            expect(key in block, f"the web_gui block must contain {key!r}: {sorted(block)}")
        expect(set(block["capabilities"]) == set(WEB_GUI_CAPABILITIES),
               f"exactly the documented capabilities must be reported: {sorted(block['capabilities'])}")
        for name, entry in block["capabilities"].items():
            expect(isinstance(entry["present"], bool) and entry["reason"].strip(),
                   f"capability {name} must carry presence + a reason: {entry!r}")
        expect(block["source"] == "chrome_devtools_mcp.py",
               f"the block must name the delegated probe: {block['source']!r}")
        expect(isinstance(block["mcp_usable"], bool) and isinstance(block["browser_usable"], bool),
               f"the block must report the aggregate verdicts: {block!r}")
        #    Without --repo no managed config of a CONCRETE project could be inspected, so the server
        #    must be reported missing WITH that reason: the shipped template is a launch shape, never
        #    a deployment, and it must not be able to turn the browser path usable on its own.
        expect(block["managed_config"] is None,
               f"without --repo no managed config may be assumed: {block['managed_config']!r}")
        expect(block["mcp_usable"] is False,
               f"the shipped template alone must never make mcp_usable true: {block!r}")
        server = block["capabilities"]["mcp_server"]
        expect(server["present"] is False and "mcp_server" in block["missing"],
               f"an unchecked managed config must report the server missing: {server!r}")
        expect("--repo" in server["reason"] and "UNVERIFIED" in block["verdict"],
               f"the miss must name what to do (--repo) and the verdict must degrade: "
               f"{server!r} {block['verdict']!r}")
        for needle in ("web gui", "node:", "npx:", "chrome:", "web gui verdict:"):
            expect(needle in res.stdout,
                   f"the summary must report the browser class ({needle!r}): {res.stdout!r}")

        # 9. A capability present on this machine reports the version token the delegated probe
        #    embedded in its reason (null is allowed when the probe cannot read one — that is DATA).
        present = [name for name in ("node", "npm", "npx") if block["capabilities"][name]["present"]]
        if present:
            name = present[0]
            expect(isinstance(block["capabilities"][name]["version"], str),
                   f"a present Node.js tool must report its version: {block['capabilities'][name]!r}")

        # 10. Degraded browser capabilities are DATA with a reason (mirrors case 6): forcing every
        #     capability missing must not touch the exit code — only python+git are fatal — and the
        #     verdict must refuse to claim browser verification.
        degraded_gui = tmp / "web-gui-degraded.json"
        res = run("--web-gui", "--simulate-missing", "node", "--simulate-missing", "npm",
                  "--simulate-missing", "npx", "--simulate-missing", "chrome",
                  "--simulate-missing", "chrome-for-testing", "--out", str(degraded_gui))
        expect(res.returncode == 0,
               f"missing browser capabilities must not change the exit code: rc={res.returncode} "
               f"{res.stderr!r}")
        forced = json.loads(degraded_gui.read_text(encoding="utf-8"))["web_gui"]
        expect(all(not entry["present"] for entry in forced["capabilities"].values()),
               f"every simulated capability must report missing: {forced['capabilities']!r}")
        expect(sorted(forced["missing"]) == sorted(WEB_GUI_CAPABILITIES),
               f"the missing list must name them: {forced['missing']!r}")
        expect(forced["mcp_usable"] is False and forced["browser_usable"] is False,
               f"the aggregate verdicts must follow: {forced!r}")
        for name in ("node", "npm", "npx", "chrome", "chrome_for_testing"):
            expect("simulate-missing" in forced["capabilities"][name]["reason"],
                   f"the simulated miss of {name} must carry its reason: "
                   f"{forced['capabilities'][name]!r}")
        #    The MCP server is not simulated here: it is reported missing because ITS TOOLCHAIN is,
        #    which is exactly the degradation the run must see.
        expect("cannot start" in forced["capabilities"]["mcp_server"]["reason"],
               f"an unavailable toolchain must explain the MCP miss: "
               f"{forced['capabilities']['mcp_server']!r}")
        expect("UNVERIFIED" in forced["verdict"],
               f"the verdict must refuse to claim browser verification: {forced['verdict']!r}")

        # 11. A PATH without any tool (mirrors case 6) keeps exit 1 with --web-gui — the browser
        #     class is DATA even then, and the base schema survives.
        empty_gui = tmp / "web-gui-empty-path.json"
        res = run("--web-gui", "--out", str(empty_gui), env=degraded_env)
        expect(res.returncode == 1,
               f"a PATH without python/git must stay exit 1: rc={res.returncode} {res.stdout!r}")
        empty_caps = json.loads(empty_gui.read_text(encoding="utf-8"))
        for key in KEYS:
            expect(key in empty_caps, f"the base schema must survive: {sorted(empty_caps)}")
        empty_block = empty_caps["web_gui"]
        node = empty_block["capabilities"]["node"]
        expect(node["present"] is False and "not found" in node["reason"],
               f"a missing node must be DATA with its reason: {node!r}")
        expect(empty_block["mcp_usable"] is False,
               f"without the Node.js toolchain the MCP server cannot be usable: {empty_block!r}")

        # 12. F4 regression: the managed MCP configuration of the RESOLVED repository decides the
        #     browser path. `--repo` is threaded into the delegated probe, so `mcp_usable` may only be
        #     true when that repository's OWN `.kimi-code/mcp.json` exists, passes the safety
        #     invariants and the pinned vendored entry it launches is on disk. A clean clone with no
        #     config, a half-deployed repo whose entry is gone, and a drifted config each report the
        #     exact missing capability instead of a usable browser path.
        helper = load_helper()
        clean = tmp / "clean-repo"
        clean.mkdir()
        clean_cfg = clean.joinpath(*MCP_RELPARTS)
        block = web_gui(tmp, "--repo", str(clean), name="managed-clean.json")
        expect(block["managed_config"] == str(clean_cfg),
               f"the block must name the config it checked: {block['managed_config']!r}")
        server = block["capabilities"]["mcp_server"]
        expect(block["mcp_usable"] is False and server["present"] is False,
               f"a repository without a deployed config must report the server missing: {server!r}")
        expect("mcp_server" in block["missing"] and str(clean_cfg) in server["reason"]
               and "does not exist" in server["reason"],
               f"the miss must name the missing config: {block['missing']!r} {server!r}")
        expect("UNVERIFIED" in block["verdict"],
               f"a missing managed config must refuse browser verification: {block['verdict']!r}")

        #    (b) config present, pinned vendored entry GONE (the package was never installed, or was
        #    removed): the server cannot start from a missing file, so it is reported missing and the
        #    reason names the entry plus the vendor-install step that fixes it.
        deployed = tmp / "deployed-repo"
        deployed_cfg = deploy(deployed, helper)
        entry = helper.vendored_entry_path(deployed_cfg)
        expect(entry.is_file(), f"the deployed fixture must carry the vendored entry: {entry}")
        entry.unlink()
        block = web_gui(tmp, "--repo", str(deployed), name="managed-no-entry.json")
        server = block["capabilities"]["mcp_server"]
        expect(block["mcp_usable"] is False and server["present"] is False,
               f"a config without its vendored entry must report the server missing: {server!r}")
        expect(str(entry) in server["reason"] and "vendor-install" in server["reason"],
               f"the miss must name the entry and the fix: {server!r}")

        #    (c) fully deployed (valid config + pinned vendored entry on disk): the managed server is
        #    reported present, and `mcp_usable` then follows the HOST capabilities alone (Chrome and
        #    the Node.js toolchain) — never the template.
        again = helper.vendor_install(helper.vendor_dir_for(deployed_cfg), offline=True)
        expect(again["installed"] is True, f"the offline seam must restore the entry: {again!r}")
        block = web_gui(tmp, "--repo", str(deployed), name="managed-deployed.json")
        server = block["capabilities"]["mcp_server"]
        expect(server["present"] is True and str(deployed_cfg) in server["reason"],
               f"a fully deployed repository must report the server present: {server!r}")
        host_ready = (all(block["capabilities"][n]["present"] for n in ("node", "npm", "npx"))
                      and block["browser_usable"])
        expect(block["mcp_usable"] is host_ready,
               f"a deployment may only be usable when the host capabilities are: {block['mcp_usable']} "
               f"vs {host_ready} {server!r}")

        #    (d) a drifted config (not the managed launch shape) is invalid, not usable: the safety
        #    invariants of the managed contract are enforced on the REPOSITORY's file too.
        drifted = tmp / "drifted-repo"
        drifted_cfg = drifted.joinpath(*MCP_RELPARTS)
        drifted_cfg.parent.mkdir(parents=True)
        drifted_cfg.write_text(json.dumps({"mcpServers": {"chrome-devtools": {
            "command": "npx", "args": ["-y", "chrome-devtools-mcp"]}}}), encoding="utf-8")
        block = web_gui(tmp, "--repo", str(drifted), name="managed-drifted.json")
        server = block["capabilities"]["mcp_server"]
        expect(block["mcp_usable"] is False and server["present"] is False,
               f"a config violating the invariants must report the server missing: {server!r}")
        expect("safety invariants" in server["reason"] and "command" in server["reason"],
               f"the miss must name the violated invariant: {server!r}")

        # 13. The OPT-IN `--farukon` block: without the flag neither conditional block may appear
        #     (the base schema is byte-compatible with the pre-flag output), with it a nested
        #     `farukon` capability class is appended and the exit code still depends on python+git
        #     alone. Nothing is built and no MCP server is started, so the block is static DATA.
        expect(set(caps) == set(KEYS),
               f"without --farukon/--web-gui the base schema must stay exactly {set(KEYS)}: "
               f"{sorted(caps)}")
        expect("farukon" not in caps, f"without --farukon no block may be appended: {sorted(caps)}")
        #    The not_applicable probe runs against a CLEAN fixture directory, never the live cwd: a
        #    deployment's own `.kimi-code/mcp.json` is untracked, gitignored, machine-local state
        #    (a run may legitimately register the `farukon` server there so the CLI can spawn it),
        #    and this suite must not depend on whether the machine happens to carry it. The fixture
        #    holds no `farukon_mcp/Cargo.toml`, no workspace member and no config entry.
        clean = tmp / "farukon-clean"
        clean.mkdir()
        far_out = tmp / "farukon.json"
        res = run("--farukon", "--repo", str(clean), "--out", str(far_out))
        expect(res.returncode == 0, f"--farukon must exit 0 with python+git present: {res.stderr!r}")
        far = json.loads(far_out.read_text(encoding="utf-8"))
        for key in KEYS:
            expect(key in far, f"--farukon must keep every base capability {key!r}: {sorted(far)}")
        expect("web_gui" not in far, f"--farukon must not append the browser block: {sorted(far)}")
        block = far["farukon"]
        for key in FARUKON_KEYS:
            expect(key in block, f"the farukon block must contain {key!r}: {sorted(block)}")
        expect(set(block["capabilities"]) == set(FARUKON_CAPABILITIES),
               f"exactly the documented capabilities must be reported: {sorted(block['capabilities'])}")
        for name, entry in block["capabilities"].items():
            expect(isinstance(entry["present"], bool) and entry["reason"].strip(),
                   f"capability {name} must carry presence + a reason: {entry!r}")
        expect(block["source"] == "farukon_mcp.py",
               f"the block must name the delegated probe: {block['source']!r}")
        expect(block["verdict"] in FARUKON_VERDICTS,
               f"the verdict must be one of {FARUKON_VERDICTS}: {block['verdict']!r}")
        expect(block["farukon_usable"] is (block["verdict"] == "usable"),
               f"farukon_usable must follow the verdict: {block!r}")
        #    The probe is pointed at the CLEAN fixture: it hosts no Farukon platform, so the block
        #    must say so instead of guessing a deployment.
        expect(block["verdict"] == "not_applicable",
               f"a repository that hosts no Farukon platform must be not_applicable: {block!r}")
        expect(block["capabilities"]["platform"]["present"] is False
               and "farukon_mcp/Cargo.toml" in block["capabilities"]["platform"]["reason"],
               f"the not-applicable verdict must name the missing signature: {block!r}")
        for needle in ("farukon (conditional platform path):", "cargo:", "platform:",
                       "farukon verdict:"):
            expect(needle in res.stdout,
                   f"the summary must report the platform class ({needle!r}): {res.stdout!r}")

        # 14. A real platform fixture with a stand-in `cargo`: cargo present with its version, the
        #     host signature and the managed config all in place -> `usable`; and the invocation log
        #     proves that ONLY `cargo --version` ran — the pre-flight never builds the platform and
        #     never starts the MCP server (a `cargo run` here would cost a cold build and leave the
        #     platform process behind).
        helper_far = load_farukon_helper()
        bin_dir = tmp / "fake-rust"
        marker = tmp / "cargo-calls.txt"
        fake_cargo(bin_dir, marker)
        rust_env = farukon_env(bin_dir)
        farukon_root = platform_repo(tmp / "platform", helper_far)
        block = farukon(tmp, "--repo", str(farukon_root), name="farukon-usable.json", env=rust_env)
        expect(block["verdict"] == "usable" and block["farukon_usable"] is True,
               f"a fully configured platform must be usable: {block!r}")
        expect(block["missing"] == [], f"nothing may be missing: {block['missing']!r}")
        expect(block["capabilities"]["cargo"]["present"] is True
               and "1.99.0" in (block["capabilities"]["cargo"]["version"] or ""),
               f"a present cargo must report its version: {block['capabilities']['cargo']!r}")
        expect(block["capabilities"]["platform"]["present"] is True
               and "farukon_mcp" in block["capabilities"]["platform"]["reason"],
               f"the platform signature must be reported: {block['capabilities']['platform']!r}")
        expect(block["managed_config"] == str(farukon_root.joinpath(*MCP_RELPARTS)),
               f"the block must name the config it checked: {block['managed_config']!r}")
        expect(block["capabilities"]["mcp_config"]["present"] is True,
               f"the managed config of the fixture is valid: {block['capabilities']['mcp_config']!r}")
        calls = [line.strip() for line in marker.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        expect(calls and all("--version" in call for call in calls),
               f"the pre-flight must only read the cargo VERSION, never build or start: {calls!r}")
        expect(not any(word in call for call in calls for word in ("run", "build", "test")),
               f"no cargo build/run/test may ever be launched by the pre-flight: {calls!r}")

        # 15. Degraded is DATA: a stand-in toolchain without cargo (the same `--simulate-missing`
        #     seam the browser block uses) makes the block report the capability missing with its
        #     reason and refuses the usable verdict — the exit code stays 0.
        block = farukon(tmp, "--repo", str(farukon_root), "--simulate-missing", "cargo",
                        name="farukon-degraded.json", env=rust_env)
        expect(block["verdict"] == "degraded" and block["farukon_usable"] is False,
               f"a missing cargo must degrade the block: {block!r}")
        expect("cargo" in block["missing"], f"the missing list must name cargo: {block['missing']!r}")
        cargo = block["capabilities"]["cargo"]
        expect(cargo["present"] is False and "simulate-missing" in cargo["reason"],
               f"the simulated miss must carry its reason: {cargo!r}")
        expect("UNVERIFIED" in block["verdict_reason"],
               f"a degraded block must refuse platform verification: {block['verdict_reason']!r}")

        #    A platform repository WITHOUT the managed config is degraded too — the platform exists,
        #    the managed Farukon server does not, and the reason names the merge-config step.
        bare = platform_repo(tmp / "platform-bare", helper_far, with_config=False)
        block = farukon(tmp, "--repo", str(bare), name="farukon-no-config.json", env=rust_env)
        expect(block["verdict"] == "degraded" and block["farukon_usable"] is False,
               f"a platform without the managed config must degrade: {block!r}")
        config_cap = block["capabilities"]["mcp_config"]
        expect(config_cap["present"] is False
               and str(bare.joinpath(*MCP_RELPARTS)) in config_cap["reason"]
               and "not found" in config_cap["reason"],
               f"the miss must name the config it looked for: {config_cap!r}")
        expect(block["capabilities"]["platform"]["present"] is True,
               f"the platform itself is present (only the deployment is missing): {block!r}")

        #    A CONFIG-ONLY repository: the managed `farukon` entry is registered but no buildable
        #    crate exists (no `farukon_mcp/Cargo.toml`, no workspace member). Every reported
        #    capability then looks present, so the usable verdict has to come from the delegated
        #    probe — `cargo run -p farukon_mcp` cannot resolve a crate that is not there.
        config_only = tmp / "platform-config-only"
        config_only.joinpath(*MCP_RELPARTS).parent.mkdir(parents=True)
        config_only.joinpath(*MCP_RELPARTS).write_text(
            json.dumps({"mcpServers": {helper_far.SERVER_NAME:
                                       helper_far.managed_entry(config_only)}}, indent=2) + "\n",
            encoding="utf-8")
        block = farukon(tmp, "--repo", str(config_only), name="farukon-config-only.json",
                        env=rust_env)
        expect(block["capabilities"]["platform"]["present"] is True,
               f"the managed entry is a host signature: {block['capabilities']!r}")
        expect(block["capabilities"]["cargo"]["present"] is True
               and block["capabilities"]["mcp_config"]["present"] is True,
               f"the fixture must have every REPORTED capability present: {block['capabilities']!r}")
        expect(block["missing"] == [],
               f"no reported capability is missing here: {block['missing']!r}")
        expect(block["verdict"] == "degraded" and block["farukon_usable"] is False,
               f"a config-only repository has no buildable crate, so it must not be usable: {block!r}")
        expect("farukon_mcp" in block["verdict_reason"] and "UNVERIFIED" in block["verdict_reason"],
               f"the degraded verdict must name the missing buildable crate: "
               f"{block['verdict_reason']!r}")
        expect(block["verdict"] in FARUKON_VERDICTS,
               f"the verdict must stay one of {FARUKON_VERDICTS}: {block['verdict']!r}")

        #    …and the same holds when the workspace DECLARES the crate but the member manifest is not
        #    on disk: a `members = [...]` entry alone builds nothing, so a valid managed config plus a
        #    working cargo must still be degraded, never usable.
        declared_only = tmp / "platform-declared-only"
        declared_only.mkdir(parents=True)
        (declared_only / "Cargo.toml").write_text(
            '[workspace]\nmembers = ["crates/farukon_mcp"]\n', encoding="utf-8")
        declared_only.joinpath(*MCP_RELPARTS).parent.mkdir(parents=True)
        declared_only.joinpath(*MCP_RELPARTS).write_text(
            json.dumps({"mcpServers": {helper_far.SERVER_NAME:
                                       helper_far.managed_entry(declared_only)}}, indent=2) + "\n",
            encoding="utf-8")
        block = farukon(tmp, "--repo", str(declared_only), name="farukon-declared-only.json",
                        env=rust_env)
        expect(block["capabilities"]["platform"]["present"] is True,
               f"the declaration is a host signature: {block['capabilities']!r}")
        expect(block["capabilities"]["cargo"]["present"] is True
               and block["capabilities"]["mcp_config"]["present"] is True,
               f"the fixture must have every REPORTED capability present: {block['capabilities']!r}")
        expect(block["verdict"] == "degraded" and block["farukon_usable"] is False,
               f"a declared member whose manifest is missing is not buildable, so the platform path "
               f"must be degraded: {block!r}")
        expect("manifest" in block["verdict_reason"] and "UNVERIFIED" in block["verdict_reason"],
               f"the degraded verdict must name the missing member manifest: "
               f"{block['verdict_reason']!r}")

        #    A repository that hosts nothing Farukon is `not_applicable` — never degraded and never
        #    usable: a configured MCP path alone never activates the role.
        empty_repo = tmp / "not-farukon"
        empty_repo.mkdir()
        block = farukon(tmp, "--repo", str(empty_repo), name="farukon-na.json", env=rust_env)
        expect(block["verdict"] == "not_applicable" and block["farukon_usable"] is False,
               f"a non-platform repository must be not_applicable: {block!r}")
        expect("does not host the Farukon platform" in block["capabilities"]["platform"]["reason"],
               f"the verdict must name why: {block['capabilities']['platform']!r}")

        #    A probe that cannot RUN proves nothing about the repository: "the inspection failed" is
        #    not "the repository lacks the platform". An exception in the delegated helper must
        #    therefore be DEGRADED (unknown, criteria UNVERIFIED) — never `not_applicable`, which
        #    would let an applicable run skip the required degraded handling.
        preflight_module = load_preflight_module()
        with failing_farukon_helper(preflight_module, "the probe exploded"):
            failed = preflight_module.collect_farukon_capabilities(repo=str(empty_repo))
        expect(failed["verdict"] == "degraded" and failed["farukon_usable"] is False,
               f"a crashed probe must be degraded, never not_applicable: {failed!r}")
        expect(failed.get("probe_error") == "RuntimeError: the probe exploded",
               f"the probe error must be preserved: {failed.get('probe_error')!r}")
        expect("RuntimeError: the probe exploded" in failed["verdict_reason"]
               and "UNVERIFIED" in failed["verdict_reason"],
               f"the degraded reason must carry the error and the UNVERIFIED guidance: "
               f"{failed['verdict_reason']!r}")
        expect(all(entry["present"] is False for entry in failed["capabilities"].values()),
               f"an unrun probe reports every capability as DATA-absent: {failed['capabilities']!r}")
        expect(failed["verdict"] in FARUKON_VERDICTS,
               f"the verdict must stay one of {FARUKON_VERDICTS}: {failed['verdict']!r}")

        # 16. `--repo` defaults to the caller's cwd for THIS block (the run's own working directory),
        #     so a flag-less applicable run still reports the repository it probed.
        out = tmp / "farukon-cwd.json"
        res = run("--farukon", "--repo", str(farukon_root), "--out", str(out), env=rust_env,
                  cwd=str(farukon_root))
        expect(res.returncode == 0, f"--farukon with a cwd must exit 0: {res.stderr!r}")
        expect(json.loads(out.read_text(encoding="utf-8"))["farukon"]["repo"]
               == str(pathlib.Path(os.path.abspath(str(farukon_root)))),
               "the block must report the repository it probed")
        out = tmp / "farukon-default.json"
        res = run("--farukon", "--out", str(out), env=rust_env, cwd=str(farukon_root))
        expect(res.returncode == 0
               and pathlib.Path(json.loads(out.read_text(encoding="utf-8"))["farukon"]["repo"]
                                ).name == farukon_root.name,
               f"without --repo the cwd must be probed: {res.stdout!r}")

        # 17. The simulation seam stays fail-loud: a name of the other block, an unknown name, or
        #     `--simulate-missing` without either flag is a usage error (exit 2), never a silently
        #     ignored simulation.
        for args in (("--simulate-missing", "cargo"),
                     ("--web-gui", "--simulate-missing", "cargo"),
                     ("--farukon", "--simulate-missing", "node"),
                     ("--farukon", "--simulate-missing", "nope")):
            res = run(*args, "--out", str(tmp / "usage.json"))
            expect(res.returncode == 2,
                   f"{args} must be a usage error, got {res.returncode}: {res.stderr!r}")

    print("PASS - factory_preflight.py reports the real python/git/shell/os capabilities "
          "(file + summary), follows the secondary-model flag, anchors a relative --out at --repo, "
          "degrades to nulls with exit 1, and appends the OPT-IN `web_gui` browser block "
          "(--web-gui / --simulate-missing) while the base schema and the exit-code contract stay "
          "as they were; `mcp_usable` follows the resolved repository's own managed config and its "
          "pinned vendored entry (clean / entry-missing / drifted repos report the exact miss). The "
          "OPT-IN `farukon` block reports cargo / the platform signature / the managed Farukon MCP "
          "config, decides usable/degraded/not_applicable, and never builds the platform or starts "
          "an MCP server (a stand-in cargo logs every invocation).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

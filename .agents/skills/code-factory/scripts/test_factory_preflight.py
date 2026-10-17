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
  - anchors a RELATIVE `--out` at the OPTIONAL `--repo`/`--root` anchor (the run's resolved
    repo_path) instead of the launch directory, while an absolute `--out` stays as it is and the
    flag-less invocation keeps resolving against the cwd,
  - degrades explicitly: with a PATH that contains no tools it exits 1 and records nulls instead
    of inventing a command.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

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

    print("PASS - factory_preflight.py reports the real python/git/shell/os capabilities "
          "(file + summary), follows the secondary-model flag, anchors a relative --out at --repo, "
          "degrades to nulls with exit 1, and appends the OPT-IN `web_gui` browser block "
          "(--web-gui / --simulate-missing) while the base schema and the exit-code contract stay "
          "as they were; `mcp_usable` follows the resolved repository's own managed config and its "
          "pinned vendored entry (clean / entry-missing / drifted repos report the exact miss).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

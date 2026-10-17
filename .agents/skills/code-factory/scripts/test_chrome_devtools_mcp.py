#!/usr/bin/env python3
"""
Deterministic contract test for `chrome_devtools_mcp.py` and its two shipped assets (zero LLM
tokens, no network, no real Chrome launch).

Covers, with tempfile fixtures:
  - the applicability decision (applicable for Web GUI implement/fix/change and green-field GUI;
    not_applicable for backend-only text, CLI/library work and a backend task inside a repository
    that DOES contain a Web frontend) — every decision carries a non-empty reason,
  - existing E2E stack discovery for Playwright Test, Cypress, Selenium and WebdriverIO fixtures
    plus the empty repository,
  - browser-matrix derivation (explicit Firefox+WebKit -> matrix; unrelated text -> chrome-only
    default, never invented),
  - `merge-config`: create when missing — and only with the per-installation vendored entry in place,
    because a config launched from a missing file breaks every session; byte-for-byte preservation of
    unrelated servers and settings (LF and CRLF files), idempotent second run, conflict preserved and
    reported with exit code 3, an invalid target left untouched, the template's own pin metadata
    never leaking into the deployed file,
  - `vendor-install`: the documented `npm install --prefix <vendor> --no-save --ignore-scripts
    --omit=dev <pinned>` command line, idempotency against an already installed package, the pin being
    enforced on disk, and the fail-soft degradations (a simulated/missing npm, a failing runner, a
    runner that reports success without creating the entry) — with an INJECTED runner and the offline
    seam `CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`, so the suite never reaches the network or npm,
  - `probe` with `--simulate-missing node` / `chrome` / `chrome-for-testing` / `mcp-server` /
    `vendor-entry` and with a concrete `--target`: the vendored entry of that project is checked and
    a missing one makes the browser path unusable (DATA, exit 0),
  - `validate_config` accepting the shipped template (placeholder entry) and a merged config, and
    rejecting npx/relative/wrong-version/unpinned variants, non-isolated, statistics/CrUX/update-check
    and blanket-permission variants,
  - the CLI contract: `--help` exit 0, usage error exit 2, no traceback.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "chrome_devtools_mcp.py"
ASSETS = SCRIPTS.parent / "assets"
MCP_ASSET = ASSETS / "chrome-devtools.mcp.json"
SMOKE_FIXTURE = ASSETS / "chrome-devtools-smoke.html"

sys.path.insert(0, str(SCRIPTS))
import chrome_devtools_mcp as cd  # noqa: E402  (the importable API under test)

COUNTER = {"checks": 0}

WEB_REPO_PACKAGE_JSON = {
    "name": "mixed-repo",
    "scripts": {"dev": "vite", "build": "vite build"},
    "dependencies": {"react": "18.2.0", "react-dom": "18.2.0"},
}
BACKEND_ONLY_TASK = (
    "Extend the billing backend: add a REST endpoint for invoices, a SQL migration for the new "
    "schema and a queue worker. Do not change the web UI."
)
GUI_TASKS = (
    "Implement the login form on the web UI page so the user can sign in.",
    "Fix the search form on the products page: submitting it does not update the results panel.",
    "Change the submit button colour and the layout of the checkout page.",
)


def check(cond: bool, msg: str) -> None:
    COUNTER["checks"] += 1
    if not cond:
        raise AssertionError(msg)


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", cwd=cwd)


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: stderr must not carry a traceback: {res.stderr!r}")


def written(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def inserted_member(name: str, entry: dict, indent: str = "    ", newline: str = "\n") -> str:
    """Independently computed expectation of the text `merge_config` must insert."""
    block = json.dumps({name: entry}, indent=2).replace("\n", newline)
    relative = [line[2:] for line in block.splitlines()[1:-1]]
    return "," + newline + indent + (newline + indent).join(relative)


# --- the per-installation vendored package (the deployers install it before they merge) --------

ENTRY_RELPARTS = ("node_modules", cd.PACKAGE, "build", "src", "bin", "chrome-devtools-mcp.js")


def project_assets(project: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """`(mcp.json, vendored entry file)` of a project directory."""
    return project / ".kimi-code" / "mcp.json", installed_entry(project)


def installed_entry(project: pathlib.Path) -> pathlib.Path:
    """The entry file the deployers install into `.kimi-code/vendor/<package>/`."""
    return vendor_prefix(project) / pathlib.Path(*ENTRY_RELPARTS)


def vendor_prefix(project: pathlib.Path) -> pathlib.Path:
    """The per-installation vendor directory (`vendor-install --target`)."""
    return project / ".kimi-code" / "vendor" / cd.PACKAGE


def seed_vendored_entry(project: pathlib.Path, version: str = cd.PINNED_VERSION) -> pathlib.Path:
    """Fake `npm install` result: the entry file plus the package manifest the pin is read from."""
    entry = project_assets(project)[1]
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("// fake vendored entry (never executed by the suite)\n", encoding="utf-8")
    manifest = entry.parents[3] / "package.json"
    manifest.write_text(json.dumps({"name": cd.PACKAGE, "version": version}, indent=2) + "\n",
                        encoding="utf-8")
    return entry


def template_entry() -> dict:
    return json.loads(MCP_ASSET.read_text(encoding="utf-8"))["mcpServers"]["chrome-devtools"]


def expected_entry(project: pathlib.Path) -> dict:
    """The managed server as it must exist for a project — computed WITHOUT the helper's code.

    The only substitution is the template's entry placeholder -> the absolute path of the package
    the deployers install into `.kimi-code/vendor/<package>/`.
    """
    template = template_entry()
    entry_path = project_assets(project)[1]
    args = [str(entry_path) if arg == cd.ENTRY_PLACEHOLDER else arg for arg in template["args"]]
    return {**template, "args": args}


# --------------------------------------------------------------------- applicability

def test_applicability(tmp: pathlib.Path) -> None:
    for text in GUI_TASKS:
        decision = cd.decide_applicability(text)
        check(decision["decision"] == cd.APPLICABLE,
              f"a Web GUI task must be applicable: {text!r} -> {decision['decision']} "
              f"({decision['reason']})")
        check(decision["reason"].strip() and "Web GUI scope detected" in decision["reason"],
              f"an applicable decision must carry its reason: {decision['reason']!r}")
        check(decision["evidence"]["gui_terms"], "the reason must cite the matched GUI terms")

    greenfield = tmp / "empty-repo"
    greenfield.mkdir()
    decision = cd.decide_applicability(GUI_TASKS[0], repo=greenfield)
    check(decision["decision"] == cd.APPLICABLE,
          f"a green-field Web GUI task in an empty repo must be applicable: {decision}")
    check("green-field" in decision["reason"],
          f"the reason must name the green-field situation: {decision['reason']!r}")

    cli = run("decide", "--text", GUI_TASKS[1])
    expect_clean_cli(cli, 0, "decide --text (web gui)")
    check(cli.stdout.splitlines()[0] == cd.APPLICABLE,
          f"the first stdout line must be the decision: {cli.stdout!r}")
    check("reason: " in cli.stdout, f"the output must carry a reason: {cli.stdout!r}")

    payload = json.loads(run("decide", "--text", GUI_TASKS[2], "--json").stdout)
    check(payload["decision"] == cd.APPLICABLE and payload["reason"],
          f"--json must expose decision + reason: {payload}")

    decision = cd.decide_applicability(BACKEND_ONLY_TASK)
    check(decision["decision"] == cd.NOT_APPLICABLE,
          f"backend-only work must not activate the browser path: {decision}")
    check(decision["evidence"]["exclusions"],
          "the explicit 'do not change the web UI' exclusion must be recorded as evidence")

    cli_task = "Add a --json flag to the CLI report generator and refactor the parser library."
    decision = cd.decide_applicability(cli_task)
    check(decision["decision"] == cd.NOT_APPLICABLE,
          f"CLI/library work must be not_applicable: {decision}")
    check(decision["reason"].strip(), "a negative decision must carry a reason too")
    check("no Web GUI deliverable keyword" in decision["reason"],
          f"the reason must explain the absence of GUI scope: {decision['reason']!r}")

    mixed = tmp / "mixed-repo"
    mixed.mkdir()
    written(mixed / "package.json", json.dumps(WEB_REPO_PACKAGE_JSON, indent=2))
    written(mixed / "index.html", "<!doctype html><html><body><div id=\"root\"></div></body></html>\n")
    written(mixed / "src" / "App.jsx", "export default function App() { return null; }\n")
    signals = cd.repo_web_signals(mixed)
    check(signals["has_web_ui"] and signals["web_entry_points"],
          f"the fixture repository must expose Web UI entry points: {signals}")
    decision = cd.decide_applicability(BACKEND_ONLY_TASK, repo=mixed)
    check(decision["decision"] == cd.NOT_APPLICABLE,
          f"a backend-only task in a Web repository must stay not_applicable: {decision}")
    check(decision["evidence"]["repo_signals"]["has_web_ui"],
          f"the Web UI signals must still be recorded as evidence: {decision['evidence']}")
    check("never force applicability" in decision["reason"] or decision["evidence"]["exclusions"],
          f"the reason must state why the repository signals do not force activation: "
          f"{decision['reason']!r}")

    task_file = written(tmp / "task.yaml", f"title: backend\ndescription: |\n  {BACKEND_ONLY_TASK}\n")
    cli = run("decide", "--task-file", str(task_file), "--repo", str(mixed))
    expect_clean_cli(cli, 0, "decide --task-file")
    check(cli.stdout.splitlines()[0] == cd.NOT_APPLICABLE,
          f"--task-file must be accepted and classified: {cli.stdout!r}")


# --------------------------------------------------------------------- E2E stack discovery

def test_e2e_discovery(tmp: pathlib.Path) -> None:
    fixtures = {
        "playwright": ("playwright.config.ts", "export default { testDir: 'tests' };\n"),
        "cypress": ("cypress.config.js", "module.exports = { e2e: {} };\n"),
        "webdriverio": ("wdio.conf.js", "exports.config = { specs: [] };\n"),
        "selenium": ("suite.selenium.js", "module.exports = { selenium: true };\n"),
    }
    for framework, (name, body) in fixtures.items():
        root = tmp / f"e2e-{framework}"
        root.mkdir()
        written(root / name, body)
        result = cd.discover_e2e_stack(root)
        check(result["framework"] == framework,
              f"{name} must be discovered as {framework}: {result}")
        check(result["config_path"] == name,
              f"the discovered config path must be repo-relative: {result}")
        cli = run("discover-e2e", "--repo", str(root))
        expect_clean_cli(cli, 0, f"discover-e2e {framework}")
        check(cli.stdout.splitlines()[0] == framework,
              f"the CLI must report the framework first: {cli.stdout!r}")
        check(f"config_path: {name}" in cli.stdout,
              f"the CLI must report the config path: {cli.stdout!r}")

    deps_root = tmp / "e2e-deps-only"
    deps_root.mkdir()
    written(deps_root / "package.json",
            json.dumps({"devDependencies": {"@playwright/test": "1.49.0"}}, indent=2))
    result = cd.discover_e2e_stack(deps_root)
    check(result["framework"] == "playwright" and result["config_path"] is None,
          f"a dependency-only stack must still be reported without inventing a config: {result}")

    empty = tmp / "e2e-empty"
    empty.mkdir()
    result = cd.discover_e2e_stack(empty)
    check(result["framework"] is None and result["config_path"] is None and result["detected"] == [],
          f"an empty repository must report no stack: {result}")
    cli = run("discover-e2e", "--repo", str(empty))
    expect_clean_cli(cli, 0, "discover-e2e empty")
    check(cli.stdout.splitlines()[0] == "none", f"an empty repo must report none: {cli.stdout!r}")


# --------------------------------------------------------------------- browser matrix

def test_browser_matrix() -> None:
    result = cd.derive_browser_matrix("The suite must pass in Firefox and WebKit.")
    check(result["matrix"] == ["firefox", "webkit"],
          f"an explicit Firefox+WebKit criterion must produce exactly that matrix: {result}")
    check(result["source"] == "acceptance_criteria",
          f"an explicit matrix must be sourced from the criteria: {result}")

    result = cd.derive_browser_matrix("All three engines must be green before acceptance.")
    check(result["matrix"] == ["chromium", "firefox", "webkit"],
          f"'all three engines' names the full matrix: {result}")

    result = cd.derive_browser_matrix("Chrome DevTools MCP must be available for debugging.")
    check(result["matrix"] == ["chromium"],
          f"a Chrome DevTools MCP mention alone must stay the default single engine: {result}")

    for text in ("", "The report must be deterministic and the CLI must stay backward compatible.",
                 "The run must be verified cross-browser before acceptance."):
        result = cd.derive_browser_matrix(text)
        check(result["matrix"] == ["chromium"] and result["source"] == "default",
              f"without a named browser the chrome-only default must apply: {text!r} -> {result}")
        check(result["evidence"] == [],
              f"the default matrix must not claim a criterion mention: {result}")

    cli = run("browser-matrix", "--text", "Chromium, Firefox and WebKit must all be exercised.")
    expect_clean_cli(cli, 0, "browser-matrix")
    check(cli.stdout.splitlines()[0] == "chromium, firefox, webkit",
          f"the CLI must print the matrix first: {cli.stdout!r}")


# --------------------------------------------------------------------- config merge

def test_merge_config(tmp: pathlib.Path) -> None:
    # 1. The vendored entry comes FIRST: without it nothing is written, because a managed server
    #    launched from a missing file would break every Kimi session in that project.
    bare = tmp / "no-vendor"
    bare_target = project_assets(bare)[0]
    res = run("merge-config", "--target", str(bare_target))
    expect_clean_cli(res, 1, "merge-config without the vendored entry")
    check("does not exist" in res.stderr and "vendor-install" in res.stderr,
          f"a missing vendored entry must be an error naming the fix: {res.stderr!r}")
    check(not bare_target.exists(), "no config may be created while its entry file is missing")
    empty_slot = tmp / "no-vendor-dry" / ".kimi-code" / "mcp.json"
    res = run("merge-config", "--target", str(empty_slot), "--dry-run")
    expect_clean_cli(res, 1, "merge-config --dry-run without the vendored entry")

    # 2. Missing file + installed entry -> create (nested directory created too).
    project = tmp / "created"
    entry_path = seed_vendored_entry(project)
    created = project_assets(project)[0]
    entry = expected_entry(project)
    res = run("merge-config", "--target", str(created))
    expect_clean_cli(res, 0, "merge-config create")
    check(created.is_file(), "a missing target must be created")
    check("created" in res.stdout, f"the create path must be reported: {res.stdout!r}")
    ok, problems = cd.validate_config(created)
    check(ok, f"the created config must satisfy the safety invariants: {problems}")
    text = created.read_text(encoding="utf-8")
    parsed = json.loads(text)
    check(parsed["mcpServers"][cd.SERVER_NAME] == entry,
          f"the created config must carry the managed server entry with the ABSOLUTE vendored "
          f"entry path {entry_path}: {parsed}")
    check(set(parsed) == {"mcpServers"},
          f"the created config must carry only mcpServers: the template's pin block is template "
          f"metadata, never part of a deployed config: {sorted(parsed)}")
    check(cd.ENTRY_PLACEHOLDER not in text and "codeFactory" not in text,
          f"the placeholder and the template metadata must never reach the deployed file: {text!r}")

    # 3. Existing unrelated server + settings survive byte-for-byte; second run is idempotent.
    original = (
        '{\n'
        '  "mcpServers": {\n'
        '    "unrelated-server": {\n'
        '      "command": "python",\n'
        '      "args": ["-m", "unrelated.server", "--port=1"]\n'
        '    }\n'
        '  },\n'
        '  "userSetting": {\n'
        '    "keep": true\n'
        '  }\n'
        '}\n'
    )
    preserve = tmp / "preserve"
    seed_vendored_entry(preserve)
    target = written(preserve / ".kimi-code" / "mcp.json", original)
    expected = expected_entry(preserve)
    head, sep, rest = original.partition("\n    }")
    check(sep == "\n    }", "the fixture must contain the expected closing brace")
    merged_expected = head + sep + inserted_member(cd.SERVER_NAME, expected) + rest
    res = run("merge-config", "--target", str(target))
    expect_clean_cli(res, 0, "merge-config preserve")
    merged = target.read_text(encoding="utf-8", newline="")
    check(merged == merged_expected,
          f"unrelated servers and settings must survive byte-for-byte:\n{merged!r}\n!=\n"
          f"{merged_expected!r}")
    check(res.stdout.startswith("updated"), f"the merge must be reported as updated: {res.stdout!r}")
    ok, problems = cd.validate_config(target)
    check(ok, f"the merged config must satisfy the safety invariants: {problems}")

    res = run("merge-config", "--target", str(target))
    expect_clean_cli(res, 0, "merge-config idempotent")
    check("unchanged" in res.stdout, f"the second run must be idempotent: {res.stdout!r}")
    check(target.read_text(encoding="utf-8", newline="") == merged,
          "the second run must not change a single byte")

    # 4. CRLF file: newline style and unrelated bytes are preserved.
    crlf_project = tmp / "crlf"
    seed_vendored_entry(crlf_project)
    crlf_original = original.replace("\n", "\r\n")
    crlf_target = written(project_assets(crlf_project)[0], crlf_original)
    head, sep, rest = crlf_original.partition("\r\n    }")
    crlf_expected = head + sep + inserted_member(cd.SERVER_NAME, expected_entry(crlf_project),
                                                 newline="\r\n") + rest
    res = run("merge-config", "--target", str(crlf_target))
    expect_clean_cli(res, 0, "merge-config crlf")
    check(crlf_target.read_text(encoding="utf-8", newline="") == crlf_expected,
          "a CRLF target must keep its line endings and its unrelated bytes")

    # 5. A conflicting chrome-devtools entry is preserved and reported with exit 3.
    conflict_text = (
        '{\n'
        '  "mcpServers": {\n'
        '    "chrome-devtools": {\n'
        '      "command": "npx",\n'
        '      "args": ["-y", "chrome-devtools-mcp@0.0.1"]\n'
        '    },\n'
        '    "unrelated-server": {\n'
        '      "command": "python"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    conflict_project = tmp / "conflict"
    seed_vendored_entry(conflict_project)
    conflict_target = written(project_assets(conflict_project)[0], conflict_text)
    res = run("merge-config", "--target", str(conflict_target))
    expect_clean_cli(res, cd.EXIT_CONFLICT, "merge-config conflict")
    check("CONFLICT" in res.stderr and "args" in res.stderr,
          f"the conflict must name the diverging setting: {res.stderr!r}")
    check(conflict_target.read_text(encoding="utf-8", newline="") == conflict_text,
          "a conflicting entry must be preserved byte-for-byte, never overwritten")
    payload = json.loads(run("merge-config", "--target", str(conflict_target), "--json").stdout)
    check(payload["status"] == "conflict" and payload["conflict"]["differences"],
          f"--json must expose the conflict and its differences: {payload}")

    # 6. An invalid target is never overwritten.
    broken_project = tmp / "broken"
    seed_vendored_entry(broken_project)
    broken_text = '{"mcpServers": {"other": {}}}\nnot json at all\n'
    broken = written(project_assets(broken_project)[0], broken_text)
    res = run("merge-config", "--target", str(broken))
    expect_clean_cli(res, 1, "merge-config invalid target")
    check("not valid JSON" in res.stderr, f"the invalid target must be explained: {res.stderr!r}")
    check(broken.read_text(encoding="utf-8", newline="") == broken_text,
          "an invalid target must be left untouched")

    # 7. A target without mcpServers gains the map; its own settings stay untouched.
    no_servers_project = tmp / "no-mcp"
    seed_vendored_entry(no_servers_project)
    no_servers = '{\n  "userSetting": {\n    "a": 1\n  }\n}\n'
    plain = written(project_assets(no_servers_project)[0], no_servers)
    res = run("merge-config", "--target", str(plain))
    expect_clean_cli(res, 0, "merge-config without mcpServers")
    merged = plain.read_text(encoding="utf-8", newline="")
    check('  "userSetting": {\n    "a": 1\n  }' in merged,
          f"an existing setting must survive byte-for-byte: {merged!r}")
    parsed = json.loads(merged)
    check(parsed["mcpServers"][cd.SERVER_NAME] == expected_entry(no_servers_project)
          and parsed["userSetting"] == {"a": 1},
          f"the merged file must carry both settings: {parsed}")
    res = run("merge-config", "--target", str(plain))
    expect_clean_cli(res, 0, "merge-config idempotent (no mcpServers)")
    check(res.stdout.startswith("unchanged"), f"the second run must be idempotent: {res.stdout!r}")

    # 8. An EMPTY mcpServers map (the shape a deployment fixture starts from) gains the entry and
    #    keeps the surrounding file's indentation.
    empty_project = tmp / "empty-servers"
    seed_vendored_entry(empty_project)
    empty_servers = '{\n  "mcpServers": {}\n}\n'
    empty_target = written(project_assets(empty_project)[0], empty_servers)
    res = run("merge-config", "--target", str(empty_target))
    expect_clean_cli(res, 0, "merge-config empty mcpServers")
    emptied = empty_target.read_text(encoding="utf-8", newline="")
    check(emptied.startswith('{\n  "mcpServers": {\n    "chrome-devtools": {\n'),
          f"the entry must be indented like its siblings: {emptied!r}")
    check(len(json.loads(emptied)["mcpServers"]) == 1,
          f"exactly one server must be added: {emptied!r}")
    res = run("merge-config", "--target", str(empty_target))
    expect_clean_cli(res, 0, "merge-config idempotent (empty mcpServers)")
    check(res.stdout.startswith("unchanged")
          and empty_target.read_text(encoding="utf-8", newline="") == emptied,
          "the second run must not change a single byte")

    empty_object_project = tmp / "empty-object"
    seed_vendored_entry(empty_object_project)
    empty_object = written(project_assets(empty_object_project)[0], "{}\n")
    res = run("merge-config", "--target", str(empty_object))
    expect_clean_cli(res, 0, "merge-config empty object")
    check(json.loads(empty_object.read_text(encoding="utf-8"))["mcpServers"][cd.SERVER_NAME]
          == expected_entry(empty_object_project),
          "an empty object target must receive the managed server")

    # 9. --dry-run never writes.
    dry_project = tmp / "dry-run"
    seed_vendored_entry(dry_project)
    dry = dry_project / ".kimi-code" / "mcp.json"
    res = run("merge-config", "--target", str(dry), "--dry-run")
    expect_clean_cli(res, 0, "merge-config --dry-run")
    check(not dry.exists(), "a dry run must not create the target")

    # 10. A custom --asset template is honoured (deployment may ship its own pinned variant); the
    #     placeholder it carries is what gets substituted.
    custom = json.loads(json.dumps(template_entry()))
    custom["args"].append("--slim")
    asset_path = written(tmp / "custom-asset.json",
                         json.dumps({"mcpServers": {cd.SERVER_NAME: custom}}, indent=2) + "\n")
    custom_project = tmp / "custom"
    custom_entry_path = seed_vendored_entry(custom_project)
    custom_target = custom_project / ".kimi-code" / "mcp.json"
    res = run("merge-config", "--target", str(custom_target), "--asset", str(asset_path))
    expect_clean_cli(res, 0, "merge-config --asset")
    merged_custom = json.loads(custom_target.read_text(encoding="utf-8"))["mcpServers"][cd.SERVER_NAME]
    check(merged_custom == expected_entry(custom_project) | {"args":
          [*expected_entry(custom_project)["args"], "--slim"]},
          f"the custom asset must be merged with the substituted entry path: {merged_custom}")
    check(merged_custom["args"][0] == str(custom_entry_path), "args[0] must be the absolute entry")
    res = run("merge-config", "--target", str(tmp / "x" / "mcp.json"), "--asset", str(tmp / "nope.json"))
    expect_clean_cli(res, 1, "merge-config with a missing asset")
    check("asset config not found" in res.stderr,
          f"a missing asset must be reported as an error: {res.stderr!r}")

    # 11. A template WITHOUT the placeholder cannot be deployed (nothing would launch).
    no_placeholder = json.loads(json.dumps(template_entry()))
    no_placeholder["args"] = no_placeholder["args"][1:]
    broken_asset = written(tmp / "broken-asset.json",
                           json.dumps({"mcpServers": {cd.SERVER_NAME: no_placeholder}}, indent=2) + "\n")
    broken_asset_project = tmp / "broken-asset-project"
    seed_vendored_entry(broken_asset_project)
    res = run("merge-config", "--target", str(project_assets(broken_asset_project)[0]),
              "--asset", str(broken_asset))
    expect_clean_cli(res, 1, "merge-config with a template without the entry placeholder")
    check("placeholder" in res.stderr, f"the missing placeholder must be explained: {res.stderr!r}")


# --------------------------------------------------------------------- validate_config

def test_validate_config(tmp: pathlib.Path) -> None:
    ok, problems = cd.validate_config(MCP_ASSET)
    check(ok and problems == [], f"the shipped template must satisfy every invariant: {problems}")
    res = run("validate-config", "--path", str(MCP_ASSET))
    expect_clean_cli(res, 0, "validate-config asset")
    check(cd.ENTRY_PLACEHOLDER in MCP_ASSET.read_text(encoding="utf-8"),
          "the template must carry the entry-path placeholder: the path is deployment-derived")

    project = tmp / "validated"
    entry_path = seed_vendored_entry(project)
    merged = project_assets(project)[0]
    run("merge-config", "--target", str(merged))
    ok, problems = cd.validate_config(merged)
    check(ok and problems == [], f"a merged config with its vendored entry must be valid: {problems}")
    res = run("validate-config", "--path", str(merged))
    expect_clean_cli(res, 0, "validate-config merged config")

    base = {"mcpServers": {cd.SERVER_NAME: expected_entry(project)}}

    def variant(mutate, label: str) -> tuple[bool, list[str]]:
        data = json.loads(json.dumps(base))
        mutate(data["mcpServers"][cd.SERVER_NAME])
        return cd.validate_config(tmp / "variant.json", data)

    def replace_arg(entry: dict, old: str, new: str | None) -> None:
        args = [new if a == old else a for a in entry["args"]]
        if new is None:
            args = [a for a in entry["args"] if a != old]
        entry["args"] = args

    cases = (
        ("npx command", lambda e: e.update({"command": "npx"}), "command must be 'node'"),
        ("npx.cmd command", lambda e: e.update({"command": "npx.cmd"}), "command must be 'node'"),
        ("missing entry argument", lambda e: e.pop("args"), "args must be a list of strings"),
        ("no entry argument at all", lambda e: e["args"].pop(0), "args[0]"),
        ("relative entry path", lambda e: e["args"].__setitem__(0, "node_modules/x.js"),
         "args[0]"),
        ("entry path of another package",
         lambda e: e["args"].__setitem__(0, str(tmp / "node_modules" / "other" / "build" / "src"
                                          / "bin" / "other.js")), "args[0]"),
        ("non-isolated", lambda e: replace_arg(e, "--isolated=true", None), "isolated"),
        ("statistics enabled", lambda e: (replace_arg(e, "--no-usage-statistics", None),
                                          e.pop("env")), "usage statistics"),
        ("crux enabled", lambda e: replace_arg(e, "--no-performance-crux", None), "CrUX"),
        ("update checks enabled", lambda e: e["env"].pop("CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"),
         "update checks"),
        ("headers not redacted", lambda e: replace_arg(e, "--redact-network-headers=true", None),
         "redact"),
        ("attach to a running session",
         lambda e: e["args"].append("--browser-url=http://127.0.0.1:9222"), "explicit opt-in"),
        ("blanket permission", lambda e: e.update({"autoApprove": ["*"]}), "blanket"),
        ("blanket allow rule", lambda e: e.update({"allowedTools": ["*"]}), "blanket"),
    )
    for label, mutate, needle in cases:
        ok, problems = variant(mutate, label)
        check(not ok, f"the {label} variant must be rejected")
        check(any(needle in p for p in problems),
              f"the {label} variant must explain {needle!r}: {problems}")

    # The version pin is enforced where it is visible: the package.json of the installed release.
    stale_project = tmp / "stale-pin"
    stale_entry = seed_vendored_entry(stale_project, version="0.0.1")
    stale = json.loads(json.dumps(base))
    stale["mcpServers"][cd.SERVER_NAME]["args"][0] = str(stale_entry)
    ok, problems = cd.validate_config(tmp / "stale.json", stale)
    check(not ok and any("0.0.1" in p for p in problems),
          f"a vendored release other than the pinned one must be rejected: {problems}")

    # ... and the template's own pin block must name that same release (one pin, one place).
    stale_asset = json.loads(MCP_ASSET.read_text(encoding="utf-8"))
    stale_asset["codeFactory"]["version"] = "0.0.1"
    ok, problems = cd.validate_config(tmp / "stale-asset.json", stale_asset)
    check(not ok and any("codeFactory" in p for p in problems),
          f"a template whose pin block drifts from the code must be rejected: {problems}")

    secret = json.loads(json.dumps(base))
    secret["mcpServers"][cd.SERVER_NAME]["env"]["SOME_TOKEN"] = "api_key: abc123"
    ok, problems = cd.validate_config(tmp / "secret.json", secret)
    check(not ok and any("secret" in p for p in problems),
          f"a credential-like value must be rejected: {problems}")
    check(all("abc123" not in p for p in problems),
          f"the report must never echo the environment value it rejects: {problems}")

    # A credential-like NAME with an OPAQUE value carries no keyword, so scanning values alone would
    # validate a shipped API key as safe: the name must be inspected on its own.
    opaque = json.loads(json.dumps(base))
    opaque["mcpServers"][cd.SERVER_NAME]["env"]["API_KEY"] = "opaque-value"
    ok, problems = cd.validate_config(tmp / "opaque-name.json", opaque)
    check(not ok, f"a credential-like env NAME must be rejected even with an opaque value: {problems}")
    check(any("API_KEY" in p for p in problems), f"the report must name the variable: {problems}")
    check(any("secret" in p for p in problems), f"the report must state the reason: {problems}")
    check(all("opaque-value" not in p for p in problems),
          f"the report must never echo the value it rejects: {problems}")

    # A malformed `env` is DATA: the fail-soft contract returns (ok, problems) instead of crashing on
    # `.values()`, and `null` means exactly the same as an absent env.
    for label, value in (("string", "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1"), ("list", ["A=1"]),
                         ("number", 7), ("boolean", True)):
        ok, problems = variant(lambda e, v=value: e.update({"env": v}), f"env as a {label}")
        check(not ok, f"the env-as-{label} variant must be rejected, not crash")
        check(any("env must be a JSON object" in p for p in problems),
              f"the env-as-{label} variant must explain the malformed env: {problems}")
    _, problems_null = variant(lambda e: e.update({"env": None}), "env null")
    _, problems_absent = variant(lambda e: e.pop("env"), "env absent")
    check(problems_null == problems_absent,
          f"a null env must mean the same as an absent env: {problems_null} vs {problems_absent}")

    malformed_env = json.loads(json.dumps(base))
    malformed_env["mcpServers"][cd.SERVER_NAME]["env"] = "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1"
    env_path = written(tmp / "env-string.json", json.dumps(malformed_env, indent=2) + "\n")
    res = run("validate-config", "--path", str(env_path))
    expect_clean_cli(res, 1, "validate-config with a string env")
    check("FAIL" in res.stdout, f"a malformed env must fail loudly, not crash: {res.stdout!r}")

    ok, problems = cd.validate_config(tmp / "missing.json", {"mcpServers": {"other": {}}})
    check(not ok and any(cd.SERVER_NAME in p for p in problems),
          f"a config without the managed server must be rejected: {problems}")

    ok, problems = cd.validate_config(tmp / "does-not-exist.json")
    check(not ok and "not found" in problems[0],
          f"a missing config must be reported, not crash: {problems}")

    bad = written(tmp / "bad" / "mcp.json", '{\n  "mcpServers": {\n')
    res = run("validate-config", "--path", str(bad))
    expect_clean_cli(res, 1, "validate-config invalid json")
    check("FAIL" in res.stdout, f"an invalid config must fail loudly: {res.stdout!r}")

    check(entry_path == cd.vendored_entry_path(merged),
          "the entry path of the fixture must be the one the helper derives from the config path")


# --------------------------------------------------------------------- vendor-install
#
# The install itself must never reach the network in this suite: the real command line is pinned as
# a value, and the installation is exercised through the injectable runner and the documented
# offline seam (`CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`), which writes a placeholder entry instead of
# calling npm — the same seam the end-to-end deployment tests use.

def test_vendor_install(tmp: pathlib.Path) -> None:
    project = tmp / "vendor-project"
    vendor = project / ".kimi-code" / "vendor" / cd.PACKAGE
    entry = project_assets(project)[1]
    expected_command = ["npm", "install", "--prefix", str(vendor), "--no-save", "--ignore-scripts",
                        "--omit=dev", f"{cd.PACKAGE}@{cd.PINNED_VERSION}"]
    check(cd.npm_install_command(vendor) == expected_command,
          f"the documented install command must be used verbatim: {cd.npm_install_command(vendor)}")
    check("--ignore-scripts" in cd.npm_install_command(vendor)
          and "--no-save" in cd.npm_install_command(vendor),
          "package scripts must never run at deploy time and the vendor prefix must stay throwaway")
    check(cd.npm_install_command(vendor, npm="/usr/bin/npm")[0] == "/usr/bin/npm",
          "the npm executable must be overridable")

    # 1. The offline seam: a placeholder entry + manifest, no npm call, idempotent afterwards.
    offline = cd.vendor_install(vendor, offline=True)
    check(offline["status"] == "offline" and offline["installed"] and entry.is_file(),
          f"the offline seam must create the vendored skeleton: {offline}")
    check(offline["command"] == [], f"the offline seam must not build a command: {offline}")
    check(cd.vendored_version(entry) == cd.PINNED_VERSION,
          f"the placeholder must carry the pinned version: {cd.vendored_version(entry)}")
    check(cd.vendor_install(vendor, offline=True)["status"] == "present",
          "a second install must be a no-op (idempotent)")

    # 2. A real install through an injected runner: the documented command, the pin enforced.
    fresh = tmp / "vendor-runner"
    calls: list[list[str]] = []

    def good_runner(argv: list[str], timeout: int) -> tuple[int, str]:
        calls.append(argv)
        seed_vendored_entry(fresh)
        return 0, "added 1 package"

    result = cd.vendor_install(fresh / ".kimi-code" / "vendor" / cd.PACKAGE, offline=False,
                               runner=good_runner)
    check(result["status"] == "installed" and result["installed"],
          f"a successful install must be reported as installed: {result}")
    check(calls and calls[0][1:4] == ["install", "--prefix", str(fresh / ".kimi-code" / "vendor"
                                                                  / cd.PACKAGE)],
          f"the runner must get the documented install command: {calls}")

    # 3. A failing runner is DATA: exit 1 with the LAST non-empty output line as the reason.
    def failing_runner(argv: list[str], timeout: int) -> tuple[int, str]:
        return 1, "npm ERR! code ENETUNREACH\nnpm ERR! network request failed"

    failed = cd.vendor_install(tmp / "vendor-failed", offline=False, runner=failing_runner)
    check(failed["status"] == "failed" and not failed["installed"],
          f"a failed install must be reported, not raised: {failed}")
    check("npm ERR! network request failed" in failed["message"],
          f"the reason must be the last non-empty output line: {failed['message']!r}")

    # 4. "Success" without the entry file is still a failure: nothing half-installed is trusted.
    ok_but_empty = cd.vendor_install(tmp / "vendor-empty", offline=False,
                                     runner=lambda argv, timeout: (0, "added 1 package"))
    check(ok_but_empty["status"] == "failed" and "missing" in ok_but_empty["message"],
          f"an install that leaves no entry must be rejected: {ok_but_empty}")

    # 5. A missing toolchain degrades (never installs, never raises) — simulated here, so the
    #    result does not depend on this machine having node/npm.
    skipped = cd.vendor_install(tmp / "vendor-skip", simulate_missing=["npm"])
    check(skipped["status"] == "skipped" and not skipped["installed"],
          f"a missing npm must degrade to a skip: {skipped}")
    check("simulate-missing" in skipped["message"] and "npm" in skipped["message"],
          f"the skip must carry its reason: {skipped['message']!r}")
    check(not (tmp / "vendor-skip" / "node_modules").exists(),
          "a skipped install must not create a fake tree")

    # 6. A stale vendored release is replaced by the pinned one (the pin is what is tested).
    stale = tmp / "vendor-stale"
    seed_vendored_entry(stale, version="0.0.1")
    replaced = cd.vendor_install(stale / ".kimi-code" / "vendor" / cd.PACKAGE, offline=True)
    check(replaced["status"] == "offline" and "0.0.1" in replaced["message"],
          f"a stale release must be reported and replaced: {replaced}")

    # 7. The CLI: the offline seam via the environment, `--json`, and the usage contract.
    cli_project = tmp / "cli-vendor"
    env = {**os.environ, cd.VENDOR_OFFLINE_ENV: "1"}
    cli = subprocess.run([sys.executable, str(TOOL), "vendor-install",
                          "--target", str(cli_project / ".kimi-code" / "vendor" / cd.PACKAGE),
                          "--json"], capture_output=True, text=True, errors="replace", env=env)
    expect_clean_cli(cli, 0, "vendor-install --json (offline seam)")
    payload = json.loads(cli.stdout)
    check(payload["status"] == "offline" and payload["installed"],
          f"the CLI must honour the offline seam: {payload}")
    check(project_assets(cli_project)[1].is_file(),
          "the CLI must leave the entry file the merge step needs")
    human = subprocess.run([sys.executable, str(TOOL), "vendor-install",
                            "--target", str(cli_project / ".kimi-code" / "vendor" / cd.PACKAGE)],
                           capture_output=True, text=True, errors="replace", env=env)
    expect_clean_cli(human, 0, "vendor-install (offline seam, human output)")
    check("present" in human.stdout and "pin:" in human.stdout,
          f"the summary must report the state and the pin: {human.stdout!r}")
    expect_clean_cli(run("vendor-install"), 2, "vendor-install without --target")
    res = run("vendor-install", "--target", str(tmp / "unknown-cap"), "--simulate-missing", "nope")
    expect_clean_cli(res, 2, "vendor-install --simulate-missing unknown")
    check("unknown capability" in res.stderr, f"an unknown capability must be a usage error: {res.stderr!r}")

    # 8. A template pinning ANOTHER package is refused: the entry path and the command would drift.
    other_asset = json.loads(MCP_ASSET.read_text(encoding="utf-8"))
    other_asset["codeFactory"]["package"] = "other-mcp"
    other_path = written(tmp / "other-package.json", json.dumps(other_asset, indent=2) + "\n")
    other = cd.vendor_install(tmp / "vendor-other", asset=other_path, offline=True)
    check(other["status"] == "failed" and "other-mcp" in other["message"],
          f"a template pinning another package must be refused: {other}")


# --------------------------------------------------------------------- probe

def test_probe(tmp: pathlib.Path) -> None:
    started = time.monotonic()
    res = run("probe", "--json")
    elapsed = time.monotonic() - started
    expect_clean_cli(res, 0, "probe")
    payload = json.loads(res.stdout)
    check(elapsed < 20,
          f"the default probe must not start a browser (it took {elapsed:.1f}s)" )
    for name in cd.CAPABILITY_NAMES:
        cap = payload["capabilities"][name]
        check(isinstance(cap["present"], bool) and cap["reason"].strip(),
              f"capability {name} must report presence + reason: {cap}")
    if shutil.which("node") is None:
        check(payload["capabilities"]["node"]["present"] is False,
              "a host without node must report node as missing, not crash")
    check(payload["missing"] == [n for n in cd.CAPABILITY_NAMES
                                 if not payload["capabilities"][n]["present"]],
          f"the missing list must match the capability states: {payload['missing']}")

    human = run("probe")
    expect_clean_cli(human, 0, "probe human output")
    for name in cd.CAPABILITY_NAMES:
        check(name.replace("_", "-") in human.stdout,
              f"the summary must mention {name}: {human.stdout!r}")

    launch = tmp / "launch"
    launch.mkdir()
    repo = tmp / "target-repo"
    res = run("probe", "--out", "state/mcp-probe.json", "--repo", str(repo), cwd=str(launch))
    expect_clean_cli(res, 0, "probe --out")
    check((repo / "state" / "mcp-probe.json").is_file(),
          "--repo must anchor a relative --out at the resolved repository")
    check(not (launch / "state").exists(),
          "nothing may be written into the working directory when --repo is given")

    simulated = (
        ("node", "node"),
        ("chrome", "chrome"),
        ("chrome-for-testing", "chrome_for_testing"),
        ("mcp-server", "mcp_server"),
        ("vendor-entry", "vendor_entry"),
        ("npm", "npm"),
    )
    for cli_name, key in simulated:
        res = run("probe", "--simulate-missing", cli_name, "--json")
        expect_clean_cli(res, 0, f"probe --simulate-missing {cli_name}")
        payload = json.loads(res.stdout)
        cap = payload["capabilities"][key]
        check(cap["present"] is False, f"--simulate-missing {cli_name} must force missing: {cap}")
        check("simulate-missing" in cap["reason"] and cli_name in cap["reason"],
              f"the simulated miss must carry its reason: {cap}")
        check(key in payload["missing"], f"the simulated miss must be listed as missing: {payload}")
        check(payload["simulated_missing"] == [key],
              f"the simulated names must be reported: {payload['simulated_missing']}")
    res = run("probe", "--simulate-missing", "mcp-server")
    expect_clean_cli(res, 0, "probe --simulate-missing mcp-server (human)")
    check("mcp_usable:" in res.stdout and "no" in res.stdout,
          f"a degraded probe must state that MCP is unusable: {res.stdout!r}")

    res = run("probe", "--simulate-missing", "not-a-capability")
    expect_clean_cli(res, 2, "probe --simulate-missing unknown")
    check("unknown capability" in res.stderr or "not-a-capability" in res.stderr,
          f"an unknown capability must be a usage error: {res.stderr!r}")

    # The vendored entry of a CONCRETE project: without it the managed server cannot start, so
    # `mcp_usable` must refuse to claim the browser path — the missing file is DATA (exit 0).
    project = tmp / "probe-project"
    config = project_assets(project)[0]
    check(cd.vendor_install(vendor_prefix(project), offline=True)["installed"],
          "the fixture must prepare the vendor directory")
    res = run("probe", "--target", str(config), "--json")
    expect_clean_cli(res, 0, "probe --target (entry installed)")
    payload = json.loads(res.stdout)
    check(payload["vendor"]["checked"] and payload["vendor"]["present"],
          f"the probe must check the vendored entry of the given project: {payload['vendor']}")

    empty_project = tmp / "probe-empty-project"
    empty_config = project_assets(empty_project)[0]
    res = run("probe", "--target", str(empty_config), "--json")
    expect_clean_cli(res, 0, "probe --target (no vendored entry)")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["vendor_entry"]["present"] is False
          and "vendor-entry" in [n.replace("_", "-") for n in payload["missing"]],
          f"a missing vendored entry must be reported as missing: {payload['missing']}")
    check(payload["mcp_usable"] is False,
          "a project whose entry file is missing cannot have a usable browser path")
    check("vendor-install" in payload["capabilities"]["vendor_entry"]["reason"],
          f"the reason must name the fix: {payload['capabilities']['vendor_entry']['reason']!r}")
    human = run("probe", "--repo", str(empty_project), "--target", ".kimi-code/mcp.json")
    expect_clean_cli(human, 0, "probe --repo + relative --target")
    check("vendor config:" in human.stdout and "vendor entry:" in human.stdout,
          f"the summary must report the checked vendor path: {human.stdout!r}")

    # Without a target there is nothing to inspect: the check says so instead of inventing a path.
    payload = json.loads(run("probe", "--json").stdout)
    check(payload["vendor"]["checked"] is False and payload["vendor"]["entry"] is None,
          f"without a target the vendored entry must not be inspected: {payload['vendor']}")
    check("not checked for a concrete installation"
          in payload["capabilities"]["vendor_entry"]["reason"],
          f"an unchecked vendor entry must say so: {payload['capabilities']['vendor_entry']}")


# --------------------------------------------------------------------- shipped assets

def test_shipped_assets() -> None:
    text = MCP_ASSET.read_text(encoding="utf-8")
    data = json.loads(text)
    entry = data["mcpServers"][cd.SERVER_NAME]
    check(cd.SERVER_NAME in data["mcpServers"],
          f"the server must be named {cd.SERVER_NAME}: {sorted(data['mcpServers'])}")
    check("type" not in entry,
          f"the 'type' field is not part of the documented Kimi mcp.json schema: {sorted(entry)}")
    check(entry["command"] == "node",
          f"the server must be launched as `node <vendored entry>` — a stdio spawn without a shell "
          f"cannot run npx/npx.cmd on Windows (ENOENT/EINVAL): {entry}")
    check(entry["args"][0] == cd.ENTRY_PLACEHOLDER,
          f"args[0] must be the entry-path placeholder (the path is deployment-derived): "
          f"{entry['args']}")
    check(cd.ENTRY_PLACEHOLDER not in " ".join(entry["args"][1:]),
          f"the placeholder must appear exactly once: {entry['args']}")
    check("@latest" not in text, "the shipped template must never use a floating @latest dependency")
    check("npx" not in text, "the shipped template must not launch through npx: the Kimi Code CLI "
                             "spawns stdio servers without a shell (ENOENT/EINVAL on Windows)")
    check(data.get(cd.ASSET_PIN_KEY, {}).get("package") == cd.PACKAGE
          and data.get(cd.ASSET_PIN_KEY, {}).get("version") == cd.PINNED_VERSION,
          f"the pin must live in the shipped asset: {data.get(cd.ASSET_PIN_KEY)}")
    check(cd.ENTRY_SUFFIX.endswith("chrome-devtools-mcp.js")
          and cd.ENTRY_SUFFIX in str(installed_entry(pathlib.Path("/tmp/project"))).replace("\\", "/"),
          f"the entry suffix must name the installed package entry: {cd.ENTRY_SUFFIX}")
    check(any(a.startswith("--isolated") for a in entry["args"]),
          f"an isolated temporary profile is mandatory: {entry['args']}")
    check(any(a.startswith("--headless") for a in entry["args"]),
          f"the documented headless mode must be encoded: {entry['args']}")
    check("--no-usage-statistics" in entry["args"],
          f"usage statistics must be disabled: {entry['args']}")
    check("--no-performance-crux" in entry["args"],
          f"CrUX lookups must be disabled: {entry['args']}")
    check(entry["env"]["CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"] == "1",
          f"update checks must be disabled: {entry.get('env')}")
    check(entry["env"]["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] == "1",
          f"usage statistics must be disabled in the environment too: {entry.get('env')}")
    for flag in ("--browserUrl", "--browser-url", "--wsEndpoint", "--autoConnect", "--auto-connect",
                 "--userDataDir", "--user-data-dir"):
        check(not any(a.split("=")[0] == flag for a in entry["args"]),
              f"the shipped config must not attach to a session or a personal profile: {flag}")
    check(not (set(entry) & set(cd._PERMISSION_KEYS)),
          f"no blanket MCP permission may be shipped: {sorted(entry)}")
    check(str(pathlib.Path.home()) not in text and "$HOME" not in text,
          "the shipped config must not reference a personal profile path")
    check(not cd._SECRET_PATTERN.search(text), "the shipped config must carry no credential-like value")

    html = SMOKE_FIXTURE.read_text(encoding="utf-8")
    check("<!DOCTYPE html>" in html and "<form" in html, "the fixture must be a standalone HTML page")
    for needle in ('id="name"', 'id="email"', 'type="email"', 'type="submit"'):
        check(needle in html, f"the fixture form must contain {needle}")
    check('id="result"' in html and 'id="result-text"' in html,
          "the fixture must expose a visible result panel")
    check("http://" not in html and "https://" not in html and "<script src" not in html,
          "the fixture must be dependency-free and make no network calls")
    check("fetch(" not in html and "XMLHttpRequest" not in html,
          "the fixture must not call the network")
    check("textContent" in html, "the fixture script must update the result panel")
    for needle in ('getElementById("contact-form")', 'getElementById("name")',
                   'getElementById("email")', "addEventListener(\"submit\""):
        check(needle in html, f"the fixture script must wire the business scenario: {needle}")
    document_ids = set(__import__("re").findall(r'id="([^"]+)"', html))
    script_ids = set(__import__("re").findall(r'getElementById\("([^"]+)"\)', html.split("<script>")[1]))
    dangling = sorted(script_ids - document_ids)
    if dangling:
        check("INTENTIONAL DEFECT" in html,
              f"a dangling element id must be declared as the intentional defect: {dangling}")
        check("Cannot set properties of null" in html or "returns null" in html,
              "the fixture comment must describe the defect the specialist must reproduce")
    else:
        check(script_ids and script_ids <= document_ids,
              "a fixed fixture must reference only existing elements")


# --------------------------------------------------------------------- CLI contract

def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("decide", "discover-e2e", "browser-matrix", "vendor-install", "merge-config",
                 "probe", "validate-config"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
    for name in ("decide", "discover-e2e", "browser-matrix", "vendor-install", "merge-config",
                 "probe", "validate-config", "matrix"):
        sub_help = run(name, "--help")
        expect_clean_cli(sub_help, 0, f"{name} --help")

    expect_clean_cli(run("merge-config"), 2, "merge-config without --target")
    expect_clean_cli(run("vendor-install"), 2, "vendor-install without --target")
    expect_clean_cli(run("decide"), 2, "decide without input")
    res = run("decide", "--task-file", "does-not-exist.yaml")
    expect_clean_cli(res, 1, "decide with a missing task file")
    check("ERROR" in res.stderr, f"a missing input must be reported as an error: {res.stderr!r}")

    legacy = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True,
                            errors="replace", env={**os.environ, "PYTHONIOENCODING": "cp1251"})
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_applicability(tmp)
        test_e2e_discovery(tmp)
        test_browser_matrix()
        test_merge_config(tmp)
        test_validate_config(tmp)
        test_vendor_install(tmp)
        test_probe(tmp)
        test_shipped_assets()
        test_cli_contract()

    print(f"PASS - chrome_devtools_mcp.py contract holds: {COUNTER['checks']} assertions over "
          "applicability decisions with reasons, E2E-stack discovery, requirement-driven browser "
          "matrix, the per-installation vendored package install (command line, pin, offline seam, "
          "fail-soft degradations), the byte-preserving idempotent mcp.json merge with explicit "
          "conflicts, fail-soft capability probes including the vendored entry of a project, the "
          "shipped template's safety invariants and the argparse CLI contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

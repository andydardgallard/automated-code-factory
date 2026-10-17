#!/usr/bin/env python3
"""
Deterministic Chrome DevTools MCP helpers for the Code Factory — zero LLM tokens.

The factory activates a browser path only when the CURRENT business task really creates, changes,
fixes or visually validates a browser-based Web GUI. This script decides that with a recorded
REASON, finds the project's existing browser/E2E stack, derives the required browser matrix from
the acceptance criteria, merges the managed `chrome-devtools` stdio server into a
`.kimi-code/mcp.json` without clobbering anything, probes the environment (fail-soft) and
validates the safety invariants of a managed config.

Subcommands (all deterministic, stdlib only):
  decide           applicability of the Chrome DevTools MCP path for a task (--text/--task-file)
  discover-e2e     existing browser/E2E stack of a repository (--repo <root>)
  browser-matrix   required browser matrix from the acceptance criteria (--text/--task-file)
  vendor-install   install the PINNED package into a per-installation vendor directory (--target)
  merge-config     merge the managed server into --target (--asset, --dry-run)
  probe            environment capabilities: node/npm/npx, Chrome/Chrome for Testing, MCP start,
                   the vendored package entry of a given project config (--target)
  validate-config  safety invariants of a managed config (--path)

Exit codes:
  0  success — including a `not_applicable` decision and a degraded `probe`: a missing capability
     or a closed browser path is DATA, never a crash or a failed run
  1  a real error: unreadable input, a missing/invalid asset, or a target that is not valid JSON
     (such a target is then NEVER overwritten); `merge-config` also refuses a target whose vendored
     entry file does not exist, and `vendor-install` reports a failed/skipped install this way —
     the deployers turn that into a SKIP and write no managed entry, so a deployment never fails
     because the browser path could not be prepared
  2  usage error (argparse, including an unknown `--simulate-missing` name)
  3  `merge-config` conflict: a DIFFERENT `chrome-devtools` entry already exists — it is
     preserved byte-for-byte and reported, never silently replaced

Launch shape: `node <ABSOLUTE path of the vendored package entry>` plus the pinned flags. The
deployer installs the PINNED release once per project into
`<project>/.kimi-code/vendor/chrome-devtools-mcp/`
(`npm install --prefix <dir> --no-save --ignore-scripts --omit=dev chrome-devtools-mcp@1.11.0`), and
the shipped asset carries that entry as the placeholder `{CHROME_DEVTOOLS_MCP_ENTRY}`, substituted
per installation by `merge-config`. Reason for the node-direct shape: the Kimi Code CLI spawns stdio
servers WITHOUT a shell, so `command: "npx"` fails with ENOENT and `command: "npx.cmd"` with EINVAL
on Windows (a `.cmd` is not an executable image) — `node` + the installed JavaScript entry starts on
POSIX and Windows alike. `--ignore-scripts` is mandatory: npm package scripts must never run at
deploy time.

Safety defaults encoded by the shipped asset `assets/chrome-devtools.mcp.json`: isolated temporary
Chrome profile (`--isolated`), pinned `chrome-devtools-mcp@1.11.0` (never `@latest`), usage
statistics and CrUX lookups disabled, update checks disabled through the documented environment
variables, sensitive network headers redacted, no blanket tool permission and no attaching to a
running browser session. Flag names come from the upstream package documentation
(`README.md`, `docs/configuration.md` of `chrome-devtools-mcp@1.11.0`).

Determinism and safety of the helpers themselves:
  - every decision carries a REASON and is keyword/rule based, never a model call;
  - `probe` never starts Chrome (a Windows `chrome.exe --version` would open a browser UI) and
    never runs the MCP server unless `--check-mcp-start` is passed explicitly;
  - an explicit exclusion phrase (`backend-only`, `no web UI`, `do not change the web UI`) wins over
    any GUI keyword: deactivating the browser path by mistake costs a missed browser run, activating
    it by mistake wastes a browser session on backend work — the conservative direction is deliberate.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
ASSETS = SCRIPTS.parent / "assets"
DEFAULT_ASSET = ASSETS / "chrome-devtools.mcp.json"

SERVER_NAME = "chrome-devtools"
PACKAGE = "chrome-devtools-mcp"
PINNED_VERSION = "1.11.0"
PROBE_TIMEOUT = 30
VERSION_PROBE_TIMEOUT = 5
VENDOR_INSTALL_TIMEOUT = 300
EXIT_CONFLICT = 3
EXIT_INSTALL = 1

# The launch shape: `node <vendored entry>` instead of `npx <package>`. The vendor directory is
# per-installation (`<project>/.kimi-code/vendor/chrome-devtools-mcp/`), and the entry path inside
# the managed config is therefore deployment-derived — the asset carries the placeholder instead.
VENDOR_DIR_NAME = "vendor"
ENTRY_RELPARTS = ("node_modules", PACKAGE, "build", "src", "bin", "chrome-devtools-mcp.js")
ENTRY_SUFFIX = "/".join(ENTRY_RELPARTS)
ENTRY_PLACEHOLDER = "{CHROME_DEVTOOLS_MCP_ENTRY}"
# The asset documents the pin (package + version) it was reviewed with; the constants above are the
# script's fallback and `validate-config` fails when the two disagree.
ASSET_PIN_KEY = "codeFactory"
# Deployment-test seam: create a placeholder entry instead of calling npm. NEVER set it in
# production — the placeholder is not a working browser server (see `vendor-install`).
VENDOR_OFFLINE_ENV = "CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE"

APPLICABLE = "applicable"
NOT_APPLICABLE = "not_applicable"
GUI_APPLICABLE_SCORE = 2

# Weighted GUI keywords (word-boundary matched, optional plural). 2 = the word alone names a Web
# GUI deliverable, 1 = a weak hint that only counts together with another hint. Keyword/rule based
# on purpose: the decision must be reproducible and auditable, never a model call.
GUI_TERMS: tuple[tuple[str, int], ...] = (
    ("web ui", 2), ("web gui", 2), ("web interface", 2), ("web app", 2), ("web application", 2),
    ("web page", 2), ("webpage", 2), ("web frontend", 2), ("ui", 2), ("gui", 2),
    ("user interface", 2), ("frontend", 2), ("front-end", 2), ("front end", 2), ("html", 2),
    ("css", 2), ("stylesheet", 2), ("javascript", 2), ("dom", 2), ("form", 2), ("button", 2),
    ("browser", 2), ("viewport", 2), ("screenshot", 2), ("responsive", 2), ("dropdown", 2),
    ("modal", 2), ("navbar", 2), ("dashboard", 2), ("react", 2), ("vue", 2), ("angular", 2),
    ("svelte", 2), ("client-side", 2), ("single-page", 2), ("index.html", 2), ("accessibility", 2),
    ("wireframe", 2), ("aria", 2),
    ("render", 1), ("rendering", 1), ("layout", 1), ("style", 1), ("styling", 1), ("theme", 1),
    ("design", 1), ("panel", 1), ("widget", 1), ("component", 1), ("screen", 1), ("click", 1),
    ("hover", 1), ("animation", 1), ("color", 1), ("font", 1), ("cursor", 1), ("focus", 1),
)

# Report-only keywords: they explain WHY a task is backend/CLI/library work but never decide on
# their own (the decision stays driven by the GUI weight above).
BACKEND_TERMS: tuple[tuple[str, int], ...] = (
    ("backend", 0), ("back-end", 0), ("back end", 0), ("api", 0), ("endpoint", 0), ("grpc", 0),
    ("sql", 0), ("database", 0), ("migration", 0), ("schema", 0), ("server-side", 0),
    ("microservice", 0), ("service layer", 0), ("cli", 0), ("command-line", 0), ("command line", 0),
    ("script", 0), ("library", 0), ("sdk", 0), ("daemon", 0), ("cron", 0), ("queue", 0),
    ("batch job", 0), ("etl", 0), ("parser", 0), ("worker", 0), ("docker", 0), ("kubernetes", 0),
    ("ci pipeline", 0), ("repository layer", 0),
)

# Explicit exclusions win over GUI keywords: a backend-only task in a Web repository must not
# activate browser automation just because the text mentions the existing frontend.
GUI_EXCLUSIONS: tuple[str, ...] = (
    r"\bbackend[-\s]?only\b",
    r"\bno\s+(web\s+)?(ui|gui|frontend|front-end)\b",
    r"\bwithout\s+(touching|changing|modifying)\s+the\s+(web\s+)?(ui|gui|frontend|front-end)\b",
    r"\bdo(es)?\s+not\s+(change|touch|modify|affect)\s+the\s+(web\s+)?(ui|gui|frontend|front-end)\b",
    r"\bthe\s+(web\s+)?(ui|gui|frontend|front-end)\s+(is|are)\s+out\s+of\s+scope\b",
    r"\b(ui|gui|frontend|front-end)\s+changes?\s+(is|are)\s+out\s+of\s+scope\b",
    r"\bno\s+browser\s+(work|automation|changes?)\b",
    r"\bnot\s+a\s+(web|gui|ui|browser)\s+task\b",
)

WEB_ENTRY_GLOBS: tuple[str, ...] = (
    "index.html", "public/index.html", "src/index.html", "*.html",
    "src/App.*", "src/app.*", "src/main.*", "src/index.jsx", "src/index.tsx",
    "app/page.*", "src/app/page.*", "pages/index.*", "src/pages/index.*",
)
WEB_SCRIPT_TOKENS: tuple[str, ...] = ("vite", "next dev", "next build", "react-scripts", "webpack",
                                      "parcel", "ng serve", "astro", "svelte-kit", "nuxt")
WEB_DEPENDENCIES: tuple[str, ...] = ("react", "react-dom", "vue", "next", "nuxt", "svelte",
                                     "@angular/core", "vite", "preact", "solid-js", "alpinejs")

E2E_FRAMEWORKS: tuple[dict, ...] = (
    {"framework": "playwright", "configs": ("playwright.config.*",), "dirs": ("playwright",),
     "deps": ("@playwright/test", "playwright")},
    {"framework": "cypress", "configs": ("cypress.config.*",), "dirs": ("cypress",),
     "deps": ("cypress",)},
    {"framework": "webdriverio", "configs": ("wdio.conf.*",), "dirs": (".wdio",),
     "deps": ("@wdio/cli", "webdriverio", "wdio")},
    {"framework": "selenium", "configs": ("*.selenium.*", "selenium.conf.*", "selenium.conf.js"),
     "dirs": (), "deps": ("selenium-webdriver", "selenium", "selenium-side-runner")},
)
PY_DEPENDENCY_FILES: tuple[str, ...] = ("requirements.txt", "requirements-dev.txt",
                                        "pyproject.toml", "setup.py", "Pipfile")

BROWSER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("chromium", r"\bchromiums?\b"),
    ("firefox", r"\bfirefoxs?\b"),
    ("webkit", r"\bwebkits?\b"),
    ("chromium", r"\bchrome\b(?![\s\-]?devtools)"),
    ("webkit", r"\bsafaris?\b"),
)
MATRIX_PHRASES: tuple[str, ...] = (r"\bthree[-\s]engines?\b", r"\ball[-\s]engines?\b",
                                   r"\ball\s+three\s+browsers\b")
CANONICAL_ORDER: tuple[str, ...] = ("chromium", "firefox", "webkit")
DEFAULT_MATRIX: tuple[str, ...] = ("chromium",)

CAPABILITY_NAMES: tuple[str, ...] = ("node", "npm", "npx", "chrome", "chrome_for_testing",
                                     "vendor_entry", "mcp_server")
FALSY = {"", "0", "false", "no", "off", "none"}

_DECODER = json.JSONDecoder()


class InputError(Exception):
    """A real error the CLI must report as a message + exit 1 (never a traceback)."""


# --------------------------------------------------------------------------- applicability

def _find_terms(text: str, terms: tuple[tuple[str, int], ...]) -> list[tuple[str, int]]:
    low = (text or "").lower()
    return [(term, weight) for term, weight in terms
            if re.search(r"\b" + re.escape(term) + r"s?\b", low)]


def repo_web_signals(repo: str | pathlib.Path) -> dict:
    """Web UI entry points of a repository — EVIDENCE only, never an applicability decision."""
    root = pathlib.Path(repo)
    entries: list[str] = []
    for pattern in WEB_ENTRY_GLOBS:
        for hit in sorted(root.glob(pattern)):
            rel = hit.relative_to(root).as_posix()
            if rel not in entries:
                entries.append(rel)
    web_scripts: list[str] = []
    web_deps: list[str] = []
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for name, command in sorted((data.get("scripts") or {}).items()):
                if isinstance(command, str) and any(t in command.lower() for t in WEB_SCRIPT_TOKENS):
                    web_scripts.append(name)
            found_deps: set[str] = set()
            for key in ("dependencies", "devDependencies"):
                block = data.get(key)
                if isinstance(block, dict):
                    found_deps.update(str(k) for k in block)
            web_deps = sorted(d for d in found_deps if d in WEB_DEPENDENCIES)
    return {
        "root": str(root),
        "web_entry_points": sorted(entries)[:10],
        "web_scripts": sorted(web_scripts),
        "web_dependencies": web_deps,
        "has_web_ui": bool(entries or web_scripts or web_deps),
    }


def _repo_sentence(signals: dict | None, applicable: bool) -> str:
    if signals is None:
        return "repo signals were not supplied, so the decision rests on the task text alone"
    if signals["web_entry_points"]:
        listed = ", ".join(signals["web_entry_points"][:3])
        if applicable:
            return f"the repository already exposes Web UI entry points ({listed}), which supports the decision"
        return (f"the repository does contain Web UI entry points ({listed}), but repository signals never "
                "force applicability: a backend-only task in a Web repository stays not_applicable")
    if applicable:
        return ("the repository has no Web UI entry point yet (green-field Web GUI task), so applicability "
                "comes from the task scope and not from existing files")
    return "the repository exposes no Web UI entry point either"


def decide_applicability(text: str, repo: str | pathlib.Path | None = None) -> dict:
    """Classify the Chrome DevTools MCP path as `applicable`/`not_applicable` WITH a reason."""
    low = (text or "").lower()
    exclusions = [pattern for pattern in GUI_EXCLUSIONS if re.search(pattern, low)]
    gui = _find_terms(text, GUI_TERMS)
    backend = _find_terms(text, BACKEND_TERMS)
    signals = repo_web_signals(repo) if repo is not None else None
    score = sum(weight for _, weight in gui)
    gui_terms = [term for term, _ in gui]
    backend_terms = [term for term, _ in backend]
    evidence = {
        "gui_terms": gui_terms,
        "backend_terms": backend_terms,
        "exclusions": exclusions,
        "gui_score": score,
        "repo_signals": signals,
    }
    if exclusions:
        reason = ("the task text explicitly excludes Web GUI/browser scope ("
                  + ", ".join(exclusions)
                  + "); the gui-expert, browser automation and any Chrome/Node requirement stay off")
        return {"decision": NOT_APPLICABLE, "reason": reason, "evidence": evidence}
    if score >= GUI_APPLICABLE_SCORE:
        terms = ", ".join(gui_terms[:6]) or "gui keywords"
        reason = (f"Web GUI scope detected in the task text ({terms}; gui_score={score}): the gui-expert "
                  "and the Chrome DevTools MCP browser path apply; "
                  + _repo_sentence(signals, True))
        return {"decision": APPLICABLE, "reason": reason, "evidence": evidence}
    detail = (f"no Web GUI deliverable keyword in the task text (gui_score={score}; backend/CLI/library "
              f"terms: {', '.join(backend_terms[:6]) or 'none'}); "
              + _repo_sentence(signals, False))
    return {"decision": NOT_APPLICABLE, "reason": detail, "evidence": evidence}


def format_decision(result: dict) -> str:
    evidence = result["evidence"]
    lines = [
        result["decision"],
        f"reason: {result['reason']}",
        "evidence: gui_terms={gui}; backend_terms={backend}; exclusions={excl}; gui_score={score}".format(
            gui=", ".join(evidence["gui_terms"]) or "-",
            backend=", ".join(evidence["backend_terms"]) or "-",
            excl=", ".join(evidence["exclusions"]) or "-",
            score=evidence["gui_score"],
        ),
    ]
    signals = evidence["repo_signals"]
    if signals is not None:
        lines.append("repo_signals: web_entry_points={entries}; web_scripts={scripts}; web_dependencies={deps}".format(
            entries=", ".join(signals["web_entry_points"]) or "-",
            scripts=", ".join(signals["web_scripts"]) or "-",
            deps=", ".join(signals["web_dependencies"]) or "-",
        ))
    return "\n".join(lines)


# --------------------------------------------------------------------------- E2E stack discovery

def _detected_dependencies(root: pathlib.Path) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    sources: list[str] = []
    pkg = root / "package.json"
    if pkg.is_file():
        sources.append("package.json")
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                block = data.get(key)
                if isinstance(block, dict):
                    names.update(str(k).lower() for k in block)
    for candidate in PY_DEPENDENCY_FILES:
        path = root / candidate
        if not path.is_file():
            continue
        sources.append(candidate)
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for name in ("selenium", "selenium-webdriver", "playwright", "pytest-playwright",
                     "webdriverio", "cypress"):
            if re.search(r"\b" + re.escape(name) + r"\b", text):
                names.add(name)
    return names, sorted(sources)


def discover_e2e_stack(repo: str | pathlib.Path = ".") -> dict:
    """Existing browser/E2E stack of a repository root: `{framework, config_path}` or none."""
    root = pathlib.Path(repo)
    if not root.is_dir():
        raise InputError(f"repository root does not exist: {root}")
    deps, sources = _detected_dependencies(root)
    detected: list[dict] = []
    for spec in E2E_FRAMEWORKS:
        config_path = None
        for pattern in spec["configs"]:
            hits = sorted(root.glob(pattern))
            if hits:
                config_path = hits[0].relative_to(root).as_posix()
                break
        evidence: list[str] = []
        if config_path:
            evidence.append(f"config file {config_path}")
        for directory in spec["dirs"]:
            if (root / directory).is_dir():
                evidence.append(f"directory {directory}/")
        matched = sorted(d for d in spec["deps"] if d.lower() in deps)
        if matched:
            evidence.append("dependency " + ", ".join(matched))
        if evidence:
            detected.append({"framework": spec["framework"], "config_path": config_path,
                             "evidence": evidence})
    primary = next((d for d in detected if d["config_path"]), detected[0] if detected else None)
    return {
        "root": str(root),
        "framework": primary["framework"] if primary else None,
        "config_path": primary["config_path"] if primary else None,
        "detected": detected,
        "dependency_sources": sources,
    }


def format_stack(result: dict) -> str:
    if not result["framework"]:
        return (f"none\nreason: no Playwright Test, Cypress, WebdriverIO or Selenium configuration or "
                f"dependency found under {result['root']} (scanned: config files in the repository root, "
                f"well-known directories and dependency manifests)")
    config = result["config_path"] or "no config file found (declared through dependencies/directories only)"
    lines = [
        result["framework"],
        f"config_path: {config}",
        f"reason: existing browser/E2E stack detected under {result['root']}",
    ]
    for entry in result["detected"]:
        lines.append(f"detected: {entry['framework']} — " + "; ".join(entry["evidence"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- browser matrix

def derive_browser_matrix(text: str) -> dict:
    """Required browser matrix from acceptance-criteria text — never invented without a mention."""
    low = (text or "").lower()
    engines: list[str] = []
    terms: list[str] = []
    for engine, pattern in BROWSER_PATTERNS:
        match = re.search(pattern, low)
        if not match:
            continue
        terms.append(match.group(0).strip())
        if engine not in engines:
            engines.append(engine)
    phrases = [pattern for pattern in MATRIX_PHRASES if re.search(pattern, low)]
    if phrases:
        terms.append("all three engines")
        for engine in CANONICAL_ORDER:
            if engine not in engines:
                engines.append(engine)
    if not engines:
        return {
            "matrix": list(DEFAULT_MATRIX),
            "source": "default",
            "reason": ("the acceptance criteria mention no explicit browser, so the default single-engine "
                       "matrix applies (chromium): Chrome DevTools MCP officially supports Google Chrome and "
                       "Chrome for Testing only, and a matrix is never invented without a requirement"),
            "evidence": [],
        }
    matrix = [engine for engine in CANONICAL_ORDER if engine in engines]
    reason = ("explicit browser requirement(s) in the acceptance criteria ("
              + ", ".join(dict.fromkeys(terms))
              + f") -> matrix: {', '.join(matrix)}; run it through the project's existing E2E framework, "
                "never by adding a second browser stack")
    return {"matrix": matrix, "source": "acceptance_criteria", "reason": reason,
            "evidence": list(dict.fromkeys(terms))}


def format_matrix(result: dict) -> str:
    return "\n".join([
        ", ".join(result["matrix"]),
        f"source: {result['source']}",
        f"reason: {result['reason']}",
    ])


# --------------------------------------------------------------------------- managed template

def load_asset(asset: str | pathlib.Path | None = None) -> dict:
    """Managed template (default: the shipped `assets/chrome-devtools.mcp.json`)."""
    path = pathlib.Path(asset) if asset else DEFAULT_ASSET
    if not path.is_file():
        raise InputError(f"asset config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"asset config is not valid JSON ({path}): {exc}") from exc
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict) or not isinstance(servers.get(SERVER_NAME), dict):
        raise InputError(f"asset config {path} must define mcpServers.{SERVER_NAME}")
    entry = servers[SERVER_NAME]
    args = entry.get("args")
    if not isinstance(args, list) or ENTRY_PLACEHOLDER not in args:
        raise InputError(f"asset config {path} must carry the entry-path placeholder "
                         f"{ENTRY_PLACEHOLDER!r} in mcpServers.{SERVER_NAME}.args: the entry path is "
                         "deployment-derived, not a template constant")
    return data


def asset_entry(asset: str | pathlib.Path | None = None) -> dict:
    """A deep copy of the template's managed entry (the placeholder stays in place)."""
    return json.loads(json.dumps(load_asset(asset)["mcpServers"][SERVER_NAME]))


def asset_pin(asset: str | pathlib.Path | None = None) -> tuple[str, str]:
    """`(package, version)` the asset pins — the constants above are only the fallback.

    One pin, one place: the shipped asset. The deployers pass the asset path around and never
    repeat the version, so bumping the asset is a single-file change.
    """
    block = load_asset(asset).get(ASSET_PIN_KEY)
    if not isinstance(block, dict):
        return PACKAGE, PINNED_VERSION
    package = block.get("package")
    version = block.get("version")
    return (str(package) if isinstance(package, str) and package else PACKAGE,
            str(version) if isinstance(version, str) and version else PINNED_VERSION)


# --------------------------------------------------------------------------- vendored package

def vendor_dir_for(target: str | pathlib.Path) -> pathlib.Path:
    """The per-installation vendor directory next to a managed config (`--target <mcp.json>`)."""
    parent = pathlib.Path(os.path.abspath(str(target))).parent
    return parent / VENDOR_DIR_NAME / PACKAGE


def vendored_entry(vendor_dir: str | pathlib.Path) -> pathlib.Path:
    """The installed package entry inside a vendor directory."""
    return pathlib.Path(os.path.abspath(str(vendor_dir))) / pathlib.Path(*ENTRY_RELPARTS)


def vendored_entry_path(target: str | pathlib.Path) -> pathlib.Path:
    """The ABSOLUTE entry file the managed server must launch for `--target <mcp.json>`."""
    return vendored_entry(vendor_dir_for(target))


def vendored_package_json(entry: str | pathlib.Path) -> pathlib.Path:
    """`.../node_modules/<package>/package.json` of a vendored entry file (the pin on disk)."""
    path = pathlib.Path(entry)
    # `<package>` is the directory len(ENTRY_RELPARTS) - 3 levels above the entry file, because only
    # `build/src/bin/<file>` sit between the two — the same parts list keeps both in sync.
    return path.parents[len(ENTRY_RELPARTS) - 3] / "package.json"


def read_json(path: str | pathlib.Path) -> object | None:
    """Parsed JSON or `None` — a missing/unreadable/invalid file is DATA, never a crash."""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def vendored_version(entry: str | pathlib.Path) -> str | None:
    """The version of the package a vendored entry belongs to, or `None` when unreadable."""
    data = read_json(vendored_package_json(entry))
    if isinstance(data, dict) and isinstance(data.get("version"), str) and data["version"].strip():
        return data["version"].strip()
    return None


def is_entry_absolute(value: object) -> bool:
    """`True` for an absolute filesystem path (the managed entry is never a relative one)."""
    return isinstance(value, str) and pathlib.Path(value).is_absolute()


def is_entry_path(value: object) -> bool:
    """`True` for a substituted entry path: absolute AND ending with the pinned entry suffix."""
    return is_entry_absolute(value) and str(value).replace("\\", "/").endswith("/" + ENTRY_SUFFIX)


def npm_install_command(vendor_dir: str | pathlib.Path, version: str = PINNED_VERSION,
                        npm: str = "npm") -> list[str]:
    """The documented install: pinned package, into the vendor prefix, WITHOUT running scripts.

    `--ignore-scripts` is not cosmetic: an npm package script is arbitrary code execution at
    deployment time, which a deployer of a non-developer project must never trigger. `--no-save`
    keeps the vendor directory a throwaway prefix (no manifest is rewritten), and `--omit=dev`
    drops development-only dependencies.
    """
    return [npm, "install", "--prefix", str(vendor_dir), "--no-save", "--ignore-scripts",
            "--omit=dev", f"{PACKAGE}@{version}"]


def offline_seam_enabled() -> bool:
    """`CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE` truthy → placeholder entry instead of an npm call."""
    value = os.environ.get(VENDOR_OFFLINE_ENV, "")
    return str(value).strip().lower() not in FALSY


def _write_offline_placeholder(entry: pathlib.Path, version: str) -> None:
    """Create the vendor skeleton the deployment tests (and air-gapped rehearsals) run against."""
    entry.parent.mkdir(parents=True, exist_ok=True)
    if not entry.is_file():
        entry.write_text("// Created by chrome_devtools_mcp.py vendor-install: the offline seam "
                         f"{VENDOR_OFFLINE_ENV} is set, so no npm install ran.\n"
                         "// This placeholder is NOT a working browser server - never ship it.\n",
                         encoding="utf-8")
    package_json = vendored_package_json(entry)
    if not package_json.is_file():
        package_json.write_text(json.dumps({"name": PACKAGE, "version": version,
                                            "private": True}, indent=2) + "\n", encoding="utf-8")


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _run_npm(argv: list[str], timeout: int) -> tuple[int | None, str]:
    """Run the install command: `(exit code, output)`, `None` for a code = it never ran."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"the install did not finish within {timeout}s"
    except OSError as exc:                     # npm is a .cmd on Windows, a script on POSIX
        return None, f"{type(exc).__name__}: {exc}"
    except subprocess.SubprocessError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return result.returncode, ((result.stdout or "").strip() or (result.stderr or "").strip())


def vendor_install(target: str | pathlib.Path, asset: str | pathlib.Path | None = None,
                   simulate_missing: tuple[str, ...] | list[str] = (), offline: bool | None = None,
                   npm: str | None = None, runner=None, timeout: int = VENDOR_INSTALL_TIMEOUT) -> dict:
    """Install the PINNED package into a per-installation vendor directory — fail-soft, idempotent.

    The deployment must never touch the target project's own dependency tree, so the package goes
    into the vendor prefix (`--prefix <target>`) instead of the project root. Everything that can go
    wrong here (no node, no npm, a failed or timed-out install, a registry that cannot be reached) is
    DATA with a reason and exit code 1: the deployer then writes NO managed entry at all, because a
    config launched from a missing entry breaks every Kimi session in that project — an absent
    server that is REPORTED is strictly better than a broken one nobody notices.

    `offline=True` (or `CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`) is the documented test seam: it
    writes a placeholder entry + package.json instead of calling npm. `runner` is the injectable
    command runner used by the tests (`_run_npm` by default), so the suite never reaches the network.
    """
    vendor = pathlib.Path(os.path.abspath(str(target)))
    entry = vendored_entry(vendor)
    package, version = asset_pin(asset)
    spec = f"{package}@{version}"
    simulated = sorted({_canonical_capability(name) for name in simulate_missing})
    result = {"target": str(vendor), "entry": str(entry), "package": package, "version": version,
              "status": "absent", "installed": False, "command": [], "message": "",
              "simulated_missing": simulated}
    if package != PACKAGE:
        return {**result, "status": "failed",
                "message": (f"the template pin {ASSET_PIN_KEY!r} names {package!r}, but the managed "
                            f"launch layout is {PACKAGE!r}: the entry path and the install command "
                            "would disagree, so nothing was installed")}
    note = ""
    if entry.is_file():
        on_disk = vendored_version(entry)
        if on_disk == version or on_disk is None:
            return {**result, "status": "present", "installed": True,
                    "message": (f"the pinned {spec} is already vendored at {vendor}"
                                + (f" (version on disk: {on_disk})" if on_disk else
                                   " (the version on disk is not readable; the entry is left as it is)")
                                + " — idempotent, no npm call")}
        note = f"replacing the vendored {package}@{on_disk} with the pinned {spec}; "
    use_offline = offline_seam_enabled() if offline is None else bool(offline)
    if use_offline:
        _write_offline_placeholder(entry, version)
        return {**result, "status": "offline", "installed": True,
                "message": (note + f"the offline seam {VENDOR_OFFLINE_ENV} is set: wrote a placeholder "
                            f"entry {entry} instead of calling npm — a deployment-test seam, never a "
                            "working browser server")}
    missing = [name for name in ("node", "npm") if name in simulated]
    if not missing:
        missing = [name for name in ("node", "npm") if shutil.which(name) is None]
    if missing:
        reasons = [(_simulated_reason(name) if name in simulated
                    else f"{name} was not found on PATH") for name in missing]
        return {**result, "status": "skipped",
                "message": ("; ".join(reasons) + f": the pinned {spec} cannot be installed, so no "
                            f"managed '{SERVER_NAME}' entry is written (an absent server is reported, "
                            "a config launched from a missing file is not)")}
    npm_path = npm or shutil.which("npm") or "npm"
    argv = npm_install_command(vendor, version, npm_path)
    rc, output = (runner or _run_npm)(argv, timeout)
    if rc != 0:
        return {**result, "command": argv, "status": "failed",
                "message": (note + f"`{' '.join(argv)}` failed "
                            f"({'timeout' if rc is None else f'exit code {rc}'}): "
                            f"{_last_line(output) or 'no output'}")}
    if not entry.is_file():
        return {**result, "command": argv, "status": "failed",
                "message": (f"npm reported success but the expected entry file {entry} is missing — "
                            "the package layout is not the reviewed one, so no managed entry is "
                            "written")}
    return {**result, "command": argv, "status": "installed", "installed": True,
            "message": (note + f"installed the pinned {spec} into {vendor} (--no-save, "
                        "--ignore-scripts, --omit=dev): the managed server launches "
                        f"{entry} with node")}


def format_vendor_install(result: dict) -> str:
    """Human summary — the MESSAGE comes last: the deployers report the last non-empty line."""
    lines = [result["status"],
             f"entry: {result['entry']}",
             f"pin: {result['package']}@{result['version']} (vendor dir {result['target']})"]
    if result["command"]:
        lines.append("command: " + " ".join(result["command"]))
    if result["simulated_missing"]:
        lines.append("simulated_missing: "
                     + ", ".join(_toggle(name) for name in result["simulated_missing"]))
    lines.append(f"message: {result['message']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- config validation

def _flag_true(args: list[str], *names: str) -> bool:
    for arg in args:
        for name in names:
            if arg == name or arg == f"{name}=true" or arg == f"{name}=1":
                return True
    return False


def _flag_false(args: list[str], *names: str) -> bool:
    for arg in args:
        for name in names:
            if arg == f"{name}=false" or arg == f"{name}=0":
                return True
    return False


def _env_true(entry: dict, name: str) -> bool:
    env = entry.get("env")
    if not isinstance(env, dict):
        return False
    value = env.get(name)
    return isinstance(value, str) and value.strip().lower() not in FALSY


_SECRET_PATTERN = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|credential|bearer)\b\s*[:=]?\s*\S")
# A credential-like NAME is disqualifying on its own: `"API_KEY": "opaque-value"` carries no keyword
# in the VALUE, so a value-only scan would declare a shipped API key safe.
_SECRET_NAME_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|token|secret|password|passwd|credential|bearer)\b")
_PERMISSION_KEYS = ("permissions", "autoApprove", "auto_approve", "alwaysAllow", "always_allow",
                    "allowedTools", "allowed_tools", "defaultPermissionMode", "default_permission_mode")
_ATTACH_FLAGS = ("--browser-url", "--browserurl", "--ws-endpoint", "--wsendpoint", "--auto-connect",
                 "--autoconnect")


def validate_entry_path(args: list[str]) -> list[str]:
    """Problems with `args[0]` — the placeholder (template) or the vendored entry path (installed).

    The entry path is deployment-derived, so a template legitimately carries the placeholder; an
    installed config must point at the ABSOLUTE vendored entry, and when the package next to it is
    readable its version must be the pinned, tested release (the pin is enforced only where it is
    visible — a hand-made tree without a package.json is not second-guessed here).
    """
    if not args:
        return [f"args[0] must be the template placeholder {ENTRY_PLACEHOLDER!r} or the absolute "
                f"path of the vendored package entry (ending with {ENTRY_SUFFIX!r})"]
    first = args[0]
    if first == ENTRY_PLACEHOLDER:
        return []
    if not is_entry_path(first):
        return [f"args[0] must be the template placeholder {ENTRY_PLACEHOLDER!r} or the absolute "
                f"path of the vendored package entry, i.e. an absolute path ending with "
                f"{ENTRY_SUFFIX!r} — found {first!r}"
                + ("" if is_entry_absolute(first) else " (a RELATIVE entry path would resolve "
                                                       "against the server's working directory)")]
    installed = vendored_version(first)
    if installed is not None and installed != PINNED_VERSION:
        return [f"the vendored package at {first} is version {installed}, but the tested release is "
                f"{PACKAGE}@{PINNED_VERSION}: reinstall it with `chrome_devtools_mcp.py "
                "vendor-install` (never run an unreviewed version)"]
    return []


def validate_config(path: str | pathlib.Path | None = DEFAULT_ASSET, data: dict | None = None
                    ) -> tuple[bool, list[str]]:
    """Safety invariants of a managed mcp.json: `(ok, problems)` — problems are data, not crashes.

    Every malformed input is reported as a problem: an absent `env` means "no environment", while a
    non-object `env` (string, list, number, boolean) is a violation instead of an AttributeError on
    `.values()`.
    """
    problems: list[str] = []
    if data is None:
        config = pathlib.Path(path) if path else DEFAULT_ASSET
        if not config.is_file():
            return False, [f"config not found: {config}"]
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, [f"config is not valid JSON: {exc}"]
    if not isinstance(data, dict):
        return False, ["config must be a JSON object"]
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False, ["mcpServers must be a JSON object"]
    entry = servers.get(SERVER_NAME)
    if not isinstance(entry, dict):
        return False, [f"server {SERVER_NAME!r} is missing from mcpServers"]
    pin = data.get(ASSET_PIN_KEY)
    if pin is not None:
        # The template documents the pin it was reviewed with; a drift between the two would install
        # one release and validate another.
        if (not isinstance(pin, dict) or pin.get("package") != PACKAGE
                or pin.get("version") != PINNED_VERSION):
            problems.append(f"the template block {ASSET_PIN_KEY!r} must pin exactly "
                            f"{{'package': {PACKAGE!r}, 'version': {PINNED_VERSION!r}}}, found {pin!r}")
    if entry.get("command") != "node":
        problems.append(f"command must be 'node' (launching the vendored package entry directly): the "
                        f"Kimi Code CLI spawns stdio servers without a shell, so an npx/npx.cmd "
                        f"command fails on Windows with ENOENT/EINVAL — found {entry.get('command')!r}")
    args = entry.get("args")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        problems.append("args must be a list of strings")
        args = []
    problems.extend(validate_entry_path(args))
    env = entry.get("env")
    if env is not None and not isinstance(env, dict):
        problems.append("env must be a JSON object mapping variable names to values: a non-object env "
                        f"reaches the server as a malformed environment (found {type(env).__name__})")
        env = None
    if not _flag_true(args, "--isolated"):
        problems.append("an isolated temporary profile is required (--isolated): the user's personal "
                        "browser profile, cookies and credentials must never be used")
    if not (_flag_true(args, "--no-usage-statistics") or _flag_false(args, "--usage-statistics",
                                                                    "--usageStatistics")
            or _env_true(entry, "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS")):
        problems.append("usage statistics must be disabled (--no-usage-statistics or "
                        "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS)")
    if not (_flag_true(args, "--no-performance-crux") or _flag_false(args, "--performance-crux",
                                                                    "--performanceCrux")):
        problems.append("CrUX lookups must be disabled (--no-performance-crux): performance traces must not "
                        "send URLs to the Google CrUX API")
    if not _env_true(entry, "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"):
        problems.append("update checks must be disabled (env CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1)")
    if not _flag_true(args, "--redact-network-headers", "--redactNetworkHeaders"):
        problems.append("sensitive network headers must be redacted (--redact-network-headers)")
    attach = [a for a in args if a.split("=")[0] in _ATTACH_FLAGS]
    if attach:
        problems.append("attaching to a running browser session is an explicit opt-in, never a default: "
                        f"remove {attach!r}")
    for key in _PERMISSION_KEYS:
        if key in entry or key in data:
            problems.append(f"no blanket MCP permission may be granted: remove the {key!r} setting")
    blob = json.dumps(data, ensure_ascii=False)
    if re.search(r'"[^"]*"\s*:\s*\[\s*"\*"\s*\]', blob) or re.search(r'"[^"]*"\s*:\s*"\*"', blob):
        problems.append("no blanket 'all tools/all servers' allow rule may appear in the configuration")
    for candidate in args:
        if _SECRET_PATTERN.search(candidate):
            problems.append("no secret may appear in the shipped configuration (found a "
                            f"credential-like value in {candidate!r})")
    for name, value in (env or {}).items():
        # The report names the variable and the reason — never the value, which may BE the secret.
        if value is None or value == "":
            continue
        if _SECRET_NAME_PATTERN.search(str(name)):
            problems.append("no secret may appear in the shipped configuration (the environment "
                            f"variable {name!r} is credential-like: the server must read it from the "
                            "user's own environment instead of the shipped config)")
        elif isinstance(value, str) and _SECRET_PATTERN.search(value):
            problems.append("no secret may appear in the shipped configuration (the value of the "
                            f"environment variable {name!r} looks like a credential)")
    return (not problems), problems


# --------------------------------------------------------------------------- config merge

def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _object_members(text: str, obj_open: int) -> list[tuple[str, int, int, int]]:
    """`(key, key_start, value_start, value_end)` for the depth-1 members of the object at `{`."""
    members: list[tuple[str, int, int, int]] = []
    index = _skip_ws(text, obj_open + 1)
    while index < len(text) and text[index] != "}":
        key_start = index
        key, index = _DECODER.raw_decode(text, index)
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] != ":":
            raise ValueError(f"expected ':' after key {key!r} at offset {index}")
        index = _skip_ws(text, index + 1)
        value_start = index
        _, index = _DECODER.raw_decode(text, index)
        members.append((str(key), key_start, value_start, index))
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ",":
            index = _skip_ws(text, index + 1)
    return members


def _root_span(text: str) -> tuple[int, int]:
    start = _skip_ws(text, 0)
    if start >= len(text) or text[start] != "{":
        raise ValueError("the config must be a JSON object")
    _, end = _DECODER.raw_decode(text, start)
    return start, end - 1


def _line_indent(text: str, index: int) -> str:
    line_start = text.rfind("\n", 0, index) + 1
    prefix = text[line_start:index]
    return prefix if prefix.strip() == "" else ""


def _indent_unit(text: str) -> str:
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped and stripped != line:
            indent = line[:len(line) - len(stripped)]
            if indent:
                return indent
    return "  "


def _member_block(key: str, value: dict, indent: str, newline: str) -> str:
    """`"key": value` serialized like the surrounding file (json indent 2, re-indented)."""
    serialized = json.dumps({key: value}, indent=2).replace("\n", newline)
    lines = serialized.splitlines()[1:-1]
    relative = [line[2:] if line.startswith("  ") else line for line in lines]
    return (newline + indent).join(relative)


def _insert_member(text: str, obj_open: int, obj_close: int, block: str, indent: str,
                   newline: str) -> str:
    """Insert a serialized member into an object, keeping every other byte of the file."""
    inner = text[obj_open + 1:obj_close]
    body = inner.rstrip()
    tail = inner[len(body):]
    if body.strip():
        new_inner = body + "," + newline + indent + block + tail
    else:
        if not tail.strip():
            tail = newline + (_line_indent(text, obj_open) or "")
        new_inner = newline + indent + block + tail
    return text[:obj_open + 1] + new_inner + text[obj_close:]


def _insert_managed_server(text: str, entry: dict) -> str:
    """Deep-merge ONLY the `mcpServers` map: every other byte of the target is preserved."""
    root_open, root_close = _root_span(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    unit = _indent_unit(text)
    root_members = _object_members(text, root_open)
    servers_member = next((m for m in root_members if m[0] == "mcpServers"), None)
    if servers_member is None:
        root_indent = _line_indent(text, root_members[0][1]) if root_members else unit
        block = _member_block("mcpServers", {SERVER_NAME: entry}, root_indent, newline)
        return _insert_member(text, root_open, root_close, block, root_indent, newline)
    servers_open = servers_member[2]
    if text[servers_open] != "{":
        raise ValueError("mcpServers must be a JSON object")
    _, servers_end = _DECODER.raw_decode(text, servers_open)
    servers_close = servers_end - 1
    servers_members = _object_members(text, servers_open)
    key_indent = _line_indent(text, servers_member[1])
    if servers_members:
        indent = _line_indent(text, servers_members[0][1]) or (key_indent + unit)
    else:
        indent = key_indent + unit
    block = _member_block(SERVER_NAME, entry, indent, newline)
    return _insert_member(text, servers_open, servers_close, block, indent, newline)


def _read_text_exact(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text_exact(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def managed_entry(target: str | pathlib.Path, asset: str | pathlib.Path | None = None) -> dict:
    """The managed server as it must exist for `--target`: node + the ABSOLUTE vendored entry.

    The path is per-installation, so it is substituted into the template HERE — a template that
    only carries the placeholder is never merged as it is, and regenerating the entry for the same
    target yields the identical bytes (that identity is what makes `merge-config` idempotent).
    """
    entry = asset_entry(asset)
    args = [str(vendored_entry_path(target)) if arg == ENTRY_PLACEHOLDER else arg
            for arg in entry.get("args", [])]
    return {**entry, "args": args}


def merge_config(target: str | pathlib.Path, asset: str | pathlib.Path | None = None,
                 dry_run: bool = False) -> dict:
    """Merge the managed `chrome-devtools` server into a mcp.json (create/preserve/conflict).

    The vendored entry of THIS target must exist first: a config that points at a missing file
    breaks every Kimi session in the project, so that is an error with nothing written — the
    deployers run `vendor-install` before this and report the skip when the install was not
    possible.
    """
    target_path = pathlib.Path(os.path.abspath(str(target)))
    entry = managed_entry(target_path, asset)
    entry_path = vendored_entry_path(target_path)
    base = {"path": str(target_path), "entry_path": str(entry_path), "server": SERVER_NAME,
            "written": False, "conflict": None, "dry_run": bool(dry_run), "entry": entry}
    if not entry_path.is_file():
        base.update(status="error",
                    message=(f"the vendored package entry {entry_path} does not exist: run "
                             f"`chrome_devtools_mcp.py vendor-install --target "
                             f"{vendor_dir_for(target_path)}` first. Nothing was written — a managed "
                             f"'{SERVER_NAME}' server launched from a missing file would break every "
                             "session in this project"))
        return base
    if not target_path.is_file():
        text = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2) + "\n"
        if not dry_run:
            _write_text_exact(target_path, text)
        base.update(status="created", written=not dry_run,
                    message=(f"created {target_path} with the managed server '{SERVER_NAME}' "
                             f"(node + vendored {PACKAGE}@{PINNED_VERSION} at {entry_path}, isolated "
                             "profile, statistics and CrUX disabled)"))
        return base
    try:
        text = _read_text_exact(target_path)
    except OSError as exc:
        base.update(status="error", message=f"cannot read {target_path}: {exc}")
        return base
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        base.update(status="error",
                    message=(f"{target_path} is not valid JSON ({exc}); the file is left untouched and is "
                             "never overwritten"))
        return base
    if not isinstance(data, dict):
        base.update(status="error", message=f"{target_path} must contain a JSON object; left untouched")
        return base
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        base.update(status="error",
                    message=f"mcpServers in {target_path} must be a JSON object; the file is left untouched")
        return base
    existing = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    if isinstance(existing, dict):
        if existing == entry:
            base.update(status="unchanged",
                        message=(f"unchanged {target_path}: server '{SERVER_NAME}' already matches the "
                                 "managed definition (idempotent, no diff)"))
            return base
        keys = sorted(set(existing) | set(entry))
        differences = [f"{k}: existing={existing.get(k)!r} managed={entry.get(k)!r}"
                       for k in keys if existing.get(k) != entry.get(k)]
        base.update(status="conflict",
                    conflict={"server": SERVER_NAME, "existing": existing, "managed": entry,
                              "differences": differences},
                    message=(f"conflict: '{SERVER_NAME}' already exists in {target_path} with a different "
                             "definition; the existing entry is preserved byte-for-byte and nothing is "
                             "overwritten — resolve it explicitly, then re-run. Differences — "
                             + "; ".join(differences)))
        return base
    try:
        merged_text = _insert_managed_server(text, entry)
        merged = json.loads(merged_text)
    except (ValueError, json.JSONDecodeError) as exc:
        base.update(status="error",
                    message=f"cannot merge into {target_path} ({exc}); the file is left untouched")
        return base
    expected = dict(data)
    expected["mcpServers"] = dict(servers or {})
    expected["mcpServers"][SERVER_NAME] = entry
    if merged != expected:
        base.update(status="error",
                    message=(f"internal merge verification failed for {target_path}; the file is left "
                             "untouched"))
        return base
    if not dry_run:
        _write_text_exact(target_path, merged_text)
    base.update(status="updated", written=not dry_run,
                message=(f"{'[dry-run] would update' if dry_run else 'updated'} {target_path}: merged server "
                         f"'{SERVER_NAME}' ({PACKAGE}@{PINNED_VERSION}); all existing servers and unrelated "
                         "settings are preserved byte-for-byte"))
    return base


# --------------------------------------------------------------------------- capability probe

def _try_run(argv: list[str], timeout: int = PROBE_TIMEOUT) -> str | None:
    """First output line of `argv`, or None when it cannot start / fails / prints nothing."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip() or (result.stderr or "").strip()
    return out.splitlines()[0].strip() if out else None


def _which_version(name: str) -> tuple[str | None, str | None]:
    path = shutil.which(name)
    if not path:
        return None, None
    return path, _try_run([path, "--version"])


def _chrome_version(path: str) -> str | None:
    """Best-effort Chrome version WITHOUT starting the browser.

    A Windows `chrome.exe --version` does not print and quit: it launches a browser UI, so the probe
    would hang until its timeout and open a real window. On Windows the version is therefore read
    from the versioned directory next to the executable; on POSIX, where `--version` prints and
    exits, a short timeout-guarded call is used.
    """
    if platform.system() == "Windows":
        directory = pathlib.Path(path).parent
        try:
            versions = [child.name for child in directory.iterdir() if child.is_dir()
                        and re.fullmatch(r"\d+(\.\d+){1,3}", child.name)]
        except OSError:
            return None
        if not versions:
            return None
        newest = max(versions, key=lambda v: [int(part) for part in v.split(".")])
        return f"Google Chrome {newest}"
    return _try_run([path, "--version"], timeout=VERSION_PROBE_TIMEOUT)


def _first_existing(candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _expanded(patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        found.extend(sorted(globmod.glob(pattern)))
    return found


def _chrome_candidates() -> list[str]:
    candidates = [os.environ.get(name, "") for name in ("CHROME_PATH", "GOOGLE_CHROME_PATH")]
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe", "chromium",
                 "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    system = platform.system()
    if system == "Windows":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(str(pathlib.Path(base) / "Google" / "Chrome" / "Application"
                                      / "chrome.exe"))
    elif system == "Darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        candidates += ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                       "/opt/google/chrome/chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                       "/snap/bin/chromium"]
    return candidates


def _chrome_for_testing_candidates() -> list[str]:
    candidates = [os.environ.get("CHROME_FOR_TESTING_PATH", "")]
    home = pathlib.Path.home()
    patterns = [
        str(home / ".cache" / "chrome-for-testing" / "*" / "chrome-*" / "chrome"),
        str(home / ".cache" / "chrome-for-testing" / "*" / "chrome-*" / "chrome.exe"),
        str(home / ".cache" / "puppeteer" / "chrome" / "*" / "chrome-*" / "chrome-linux64" / "chrome"),
        str(home / ".cache" / "puppeteer" / "chrome" / "*" / "chrome-*" / "chrome-win64" / "chrome.exe"),
        str(home / ".cache" / "puppeteer" / "chrome" / "*" / "chrome-*" / "chrome-mac-*" / "Google "
            "Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing"),
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(str(pathlib.Path(local) / "chrome-for-testing" / "*" / "chrome-*" / "chrome.exe"))
    candidates += _expanded(patterns)
    return candidates


def _capability(present: bool, reason: str, detail: str | None = None) -> dict:
    return {"present": bool(present), "reason": reason, "detail": detail}


def _simulated_reason(name: str) -> str:
    return (f"{name} is reported missing because --simulate-missing {name.replace('_', '-')} forces a "
            "degraded probe: no host capability was touched and the caller must treat browser "
            "verification as unavailable")


def _toggle(name: str) -> str:
    return name.replace("_", "-")


def _canonical_capability(name: str) -> str:
    key = str(name).strip().lower().replace("-", "_")
    if key in CAPABILITY_NAMES:
        return key
    raise InputError(f"unknown capability {name!r}; known: "
                     + ", ".join(_toggle(n) for n in CAPABILITY_NAMES))


def probe_capabilities(simulate_missing: tuple[str, ...] | list[str] = (),
                       asset: str | pathlib.Path | None = None,
                       check_mcp_start: bool = False,
                       target: str | pathlib.Path | None = None) -> dict:
    """Fail-soft environment probe; a missing capability is data, never a crash.

    `target` is the managed `mcp.json` of a CONCRETE project (optional): with it the probe also
    checks the vendored package entry that this project's managed server launches, and a missing
    entry counts against `mcp_usable` — the server cannot start from a file that is not there.
    Without a target there is no installation to inspect: the check reports itself as not performed
    instead of inventing a path (the deployer is what creates the layout).
    """
    simulated = sorted({_canonical_capability(name) for name in simulate_missing})
    caps: dict[str, dict] = {}
    for name in ("node", "npm", "npx"):
        if name in simulated:
            caps[name] = _capability(False, _simulated_reason(name))
            continue
        path, version = _which_version(name)
        if not path:
            caps[name] = _capability(False, f"{name} was not found on PATH; a Web GUI run cannot start "
                                            f"the {SERVER_NAME} MCP server without it")
        else:
            caps[name] = _capability(True, f"{name} is available ({version or 'version unknown'})", path)
    for name, candidates, description in (
            ("chrome", _chrome_candidates(), "Google Chrome"),
            ("chrome_for_testing", _chrome_for_testing_candidates(), "Chrome for Testing")):
        if name in simulated:
            caps[name] = _capability(False, _simulated_reason(name))
            continue
        path = _first_existing(candidates)
        if not path:
            caps[name] = _capability(False, f"{description} was not found (PATH, environment variables and "
                                            "platform default locations were checked); it is the official "
                                            "support target of Chrome DevTools MCP")
            continue
        version = _chrome_version(path)
        reported = version or "present, version not reported"
        caps[name] = _capability(True, f"{description} is available ({reported})", path)
    asset_path = pathlib.Path(asset) if asset else DEFAULT_ASSET
    config_ok, problems = validate_config(asset_path)
    config_path = pathlib.Path(os.path.abspath(str(target))) if target else None
    entry_path = vendored_entry_path(config_path) if config_path else None
    if "vendor_entry" in simulated:
        caps["vendor_entry"] = _capability(False, _simulated_reason("vendor_entry"))
    elif entry_path is None:
        caps["vendor_entry"] = _capability(
            True,
            "no project config was passed (--target/--repo), so the vendored package entry was not "
            "checked for a concrete installation; validating the shipped template only confirms the "
            "launch shape, not that the package is installed",
            str(asset_path))
    elif entry_path.is_file():
        installed = vendored_version(entry_path)
        caps["vendor_entry"] = _capability(
            True,
            f"the vendored package entry for {config_path} is in place ({entry_path}"
            + (f", {PACKAGE}@{installed})" if installed else ", version not reported)")
            + ("" if installed in (None, PINNED_VERSION) else
               f"; WARNING: the tested release is {PACKAGE}@{PINNED_VERSION}"),
            str(entry_path))
    else:
        caps["vendor_entry"] = _capability(
            False,
            f"the vendored package entry {entry_path} is missing: run `chrome_devtools_mcp.py "
            f"vendor-install --target {vendor_dir_for(config_path)}` (npm and node required) — "
            f"without it the managed '{SERVER_NAME}' server cannot start and browser criteria must "
            "stay explicitly UNVERIFIED",
            str(entry_path))
    toolchain_missing = [name for name in ("node", "npm", "npx") if not caps[name]["present"]]
    if "mcp_server" in simulated:
        caps["mcp_server"] = _capability(False, _simulated_reason("mcp_server"))
    elif toolchain_missing:
        caps["mcp_server"] = _capability(
            False,
            f"the stdio MCP server '{SERVER_NAME}' cannot start: missing {'/'.join(toolchain_missing)}; "
            "browser criteria must stay explicitly unverified instead of being reported as MET",
            str(asset_path))
    elif not config_ok:
        caps["mcp_server"] = _capability(
            False,
            f"the managed config {asset_path} fails its safety invariants: {problems[0]}",
            str(asset_path))
    else:
        present = True
        reason = (f"node and a safe managed config are available ({SERVER_NAME} -> node + the "
                  f"vendored {PACKAGE}@{PINNED_VERSION} entry, isolated profile, usage statistics/"
                  "CrUX/update checks disabled)")
        if check_mcp_start:
            if entry_path is None:
                reason += ("; --check-mcp-start needs a project config (--target/--repo) — the "
                           "vendored entry is what gets launched")
            else:
                node_path = caps["node"]["detail"] or "node"
                banner = _try_run([node_path, str(entry_path), "--help"], timeout=PROBE_TIMEOUT * 4)
                present = banner is not None
                reason += ("; the installed server answered --help" if present
                           else "; the installed server did not answer --help within the timeout")
        caps["mcp_server"] = _capability(present, reason, str(asset_path))
    browser_usable = caps["chrome"]["present"] or caps["chrome_for_testing"]["present"]
    toolchain_usable = all(caps[name]["present"] for name in ("node", "npm", "npx"))
    return {
        "capabilities": caps,
        "missing": [name for name in CAPABILITY_NAMES if not caps[name]["present"]],
        "simulated_missing": simulated,
        "browser_usable": browser_usable,
        "node_toolchain_usable": toolchain_usable,
        "mcp_usable": (browser_usable and toolchain_usable and caps["mcp_server"]["present"]
                       and caps["vendor_entry"]["present"]),
        "config": str(asset_path),
        "config_valid": config_ok,
        "config_problems": problems,
        "vendor": {
            "config": str(config_path) if config_path else None,
            "entry": str(entry_path) if entry_path else None,
            "checked": entry_path is not None,
            "present": caps["vendor_entry"]["present"],
        },
    }


def format_probe(result: dict) -> str:
    lines = ["chrome-devtools-mcp capability probe (fail-soft: a missing capability is data, never a crash)"]
    for name in CAPABILITY_NAMES:
        cap = result["capabilities"][name]
        lines.append(f"  {_toggle(name) + ':':<20}{'present' if cap['present'] else 'missing'} — {cap['reason']}")
    lines.append(f"  {'browser_usable:':<20}{'yes' if result['browser_usable'] else 'no'}")
    lines.append(f"  {'mcp_usable:':<20}{'yes' if result['mcp_usable'] else 'no'}")
    vendor = result.get("vendor") or {}
    if vendor.get("checked"):
        lines.append(f"  {'vendor config:':<20}{vendor['config']}")
        lines.append(f"  {'vendor entry:':<20}{vendor['entry']}")
    if result["simulated_missing"]:
        lines.append("  simulated_missing: " + ", ".join(_toggle(n) for n in result["simulated_missing"]))
    lines.append("  missing: " + (", ".join(_toggle(n) for n in result["missing"]) or "none"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so help and messages never crash a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def anchored(path: str | pathlib.Path, repo: str | None) -> pathlib.Path:
    resolved = pathlib.Path(path)
    if repo and not resolved.is_absolute():
        return pathlib.Path(repo) / resolved
    return resolved


def _task_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    path = pathlib.Path(args.task_file)
    if not path.is_file():
        raise InputError(f"task file not found: {path}")
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def _emit(args: argparse.Namespace, payload: dict, human: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if getattr(args, "as_json", False) else human)


def cmd_decide(args: argparse.Namespace) -> int:
    text = _task_text(args)
    result = decide_applicability(text, repo=args.repo)
    _emit(args, result, format_decision(result))
    return 0


def cmd_discover_e2e(args: argparse.Namespace) -> int:
    result = discover_e2e_stack(args.repo)
    _emit(args, result, format_stack(result))
    return 0


def cmd_browser_matrix(args: argparse.Namespace) -> int:
    result = derive_browser_matrix(_task_text(args))
    _emit(args, result, format_matrix(result))
    return 0


def cmd_merge_config(args: argparse.Namespace) -> int:
    result = merge_config(args.target, asset=args.asset, dry_run=args.dry_run)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["status"] in ("conflict", "error"):
        prefix = "CONFLICT" if result["status"] == "conflict" else "ERROR"
        print(f"{prefix}: {result['message']}", file=sys.stderr)
    elif args.dry_run:
        print("[dry-run] " + result["message"])
    else:
        print(result["message"])
    if result["status"] == "conflict":
        return EXIT_CONFLICT
    if result["status"] == "error":
        return 1
    return 0


def cmd_vendor_install(args: argparse.Namespace) -> int:
    target = anchored(args.target, args.repo)
    try:
        result = vendor_install(target, asset=args.asset, simulate_missing=args.simulate_missing,
                               timeout=args.timeout)
    except OSError as exc:
        result = {"target": str(target), "entry": str(vendored_entry(target)), "package": PACKAGE,
                  "version": PINNED_VERSION, "status": "failed", "installed": False,
                  "command": [], "simulated_missing": [], "message": f"cannot install: {exc}"}
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # One stream, message LAST: the deployers read the last non-empty line as the reason they
        # report, and the exit code carries the verdict.
        print(format_vendor_install(result))
    return 0 if result["installed"] else EXIT_INSTALL


def cmd_probe(args: argparse.Namespace) -> int:
    target = anchored(args.target, args.repo) if args.target else None
    result = probe_capabilities(simulate_missing=args.simulate_missing, asset=args.asset,
                                check_mcp_start=args.check_mcp_start, target=target)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_probe(result))
    if args.out:
        out = anchored(args.out, args.repo)
        try:
            _write_text_exact(out, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"ERROR: cannot write {out}: {exc}", file=sys.stderr)
            return 1
        if not args.as_json:
            print(f"  capabilities file: {out}")
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path) if args.path else DEFAULT_ASSET
    ok, problems = validate_config(path)
    if args.as_json:
        print(json.dumps({"path": str(path), "ok": ok, "problems": problems}, indent=2,
                         ensure_ascii=False))
        return 0 if ok else 1
    if ok:
        print(f"OK {path}: managed '{SERVER_NAME}' server — node + the vendored {PACKAGE}@{PINNED_VERSION} "
              "(or the entry-path placeholder of the shipped template), isolated temporary profile, "
              "usage statistics and CrUX disabled, update checks disabled, sensitive network headers "
              "redacted, no blanket permission, no session attach")
        return 0
    print(f"FAIL {path}: {len(problems)} safety invariant(s) violated")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="chrome_devtools_mcp.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_text_inputs(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--text", default=None, help="task/user-story/acceptance text")
        parser.add_argument("--task-file", dest="task_file", default=None,
                            help="file whose text is used (task.yaml or plain text)")

    p = sub.add_parser("decide", help="applicability of the browser path for a task text")
    add_text_inputs(p)
    p.add_argument("--repo", default=None, help="repository root for evidence-only Web UI signals")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("discover-e2e", help="existing browser/E2E stack of a repository")
    p.add_argument("--repo", default=".", help="repository root (default: the working directory)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_discover_e2e)

    p = sub.add_parser("browser-matrix", aliases=["matrix"],
                       help="required browser matrix from the acceptance criteria")
    add_text_inputs(p)
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_browser_matrix)

    p = sub.add_parser("merge-config", help="merge the managed server into a mcp.json")
    p.add_argument("--target", required=True, help="path to the mcp.json of the target project")
    p.add_argument("--asset", default=None, help=f"template (default: {DEFAULT_ASSET})")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="report what would happen without writing")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_merge_config)

    p = sub.add_parser("vendor-install",
                       help=f"install the pinned {PACKAGE} into a per-installation vendor directory")
    p.add_argument("--target", required=True,
                   help="directory of the vendored package (next to the managed mcp.json — the "
                        "deployers pass <project>/.kimi-code/vendor/chrome-devtools-mcp)")
    p.add_argument("--asset", default=None, help=f"template carrying the pin (default: {DEFAULT_ASSET})")
    p.add_argument("--simulate-missing", action="append", default=[], metavar="NAME",
                   dest="simulate_missing",
                   help="force a capability to report missing "
                        f"({', '.join(_toggle(n) for n in CAPABILITY_NAMES)})")
    p.add_argument("--timeout", type=int, default=VENDOR_INSTALL_TIMEOUT,
                   help=f"seconds before the install is abandoned (default: {VENDOR_INSTALL_TIMEOUT})")
    p.add_argument("--repo", default=None, help="anchor a RELATIVE --target at this repository root")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_vendor_install)

    p = sub.add_parser("probe", help="fail-soft capability probe (missing capabilities are data)")
    p.add_argument("--asset", default=None, help=f"managed config to validate (default: {DEFAULT_ASSET})")
    p.add_argument("--simulate-missing", action="append", default=[], metavar="NAME",
                   dest="simulate_missing",
                   help="force a capability to report missing "
                        f"({', '.join(_toggle(n) for n in CAPABILITY_NAMES)})")
    p.add_argument("--check-mcp-start", action="store_true", dest="check_mcp_start",
                   help="opt-in: actually start the installed server with --help (needs --target)")
    p.add_argument("--target", default=None,
                   help="the managed mcp.json of a concrete project: also check the vendored package "
                        "entry that this project's server launches")
    p.add_argument("--out", default=None, help="write the probe result as JSON to this path")
    p.add_argument("--repo", default=None,
                   help="anchor a RELATIVE --out and --target at this repository root")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("validate-config", help="safety invariants of a managed config")
    p.add_argument("--path", default=None, help=f"config to check (default: {DEFAULT_ASSET})")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_validate_config)
    return ap


def main() -> int:
    use_utf8_output()
    ap = build_parser()
    args = ap.parse_args()
    if args.cmd in ("decide", "browser-matrix", "matrix") and args.text is None and not args.task_file:
        ap.error(f"{args.cmd} requires --text or --task-file")
    for name in args.simulate_missing if args.cmd in ("probe", "vendor-install") else []:
        try:
            _canonical_capability(name)
        except InputError as exc:
            ap.error(str(exc))
    try:
        return args.func(args)
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

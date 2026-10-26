#!/usr/bin/env python3
"""
Deterministic self-test for the Windows launchers of Code Factory (zero LLM tokens).

The Windows deployment is a family of files that must stay in sync, and none of them can be
exercised by importing a module, so this pins them structurally AND end to end:

  - `prepare_factory.cmd` — the double-clickable entry point: finds PowerShell, forwards every
    argument to `prepare_factory.ps1`, propagates its exit code and prints the usage line. It
    must pause ONLY on a double-click (an unconditional `pause` would hang any automated run),
  - `prepare_factory.ps1` — the real deployer (PowerShell 5.1). It carries INLINE templates of
    `start.cmd` (CRLF) and of `start.sh` (LF) and writes both into the target project,
  - `start.cmd` — the Windows launcher it writes, committed at the repo root as the source of
    truth (the generated file must be byte-identical to it),
  - `prepare_factory.sh` — the bash deployer, which owns the `start.sh` here-doc and must stay
    untouched by the Windows work.

Verified here:
  1. existence, encoding (BOM only in the .ps1) and CRLF-only line endings (no lone CR/LF),
  2. the `prepare_factory.cmd` contract (PowerShell flags, argument forwarding, exit code,
     usage string) and that its `pause` really is guarded by the double-click detection,
  3. the `start.cmd` contract and its exact first line (`@echo off`),
  4. anti-drift: the inline `start.cmd` template in the .ps1 == the committed `start.cmd`,
  5. anti-drift: the inline `start.sh` template in the .ps1 == the here-doc of `prepare_factory.sh`,
  6. `prepare_factory.sh` generates no Windows launcher (the single mention of `start.cmd` allowed
     there is its `.gitignore` pattern - see 10),
  7. `.gitattributes` pins `*.cmd`/`*.ps1` to CRLF at checkout, so the CRLF-only checks above
     hold on a clone with `core.autocrlf=false` too (never an LF-only checked-out launcher), and
     pins `*.sh` to LF — the bash deployer is an LF file and the deployer writes `start.sh` as LF,
  8. end-to-end (Windows only, otherwise SKIPPED): `cmd.exe /c prepare_factory.cmd <fresh tmp>`
     into two fresh target paths — one with a space, one with non-ASCII characters — a real
     deployment each, then a second run to prove idempotency (existing project memory is never
     overwritten) and that the project name Python reported back is not mangled,
  9. the deployers' FAILURE paths stay business-like: the `.ps1` `Copy-Item` fallback turns a copy
     failure into a message via `Err` plus the hard-error flag (never raw PowerShell records),
     a failed memory init is reported in BOTH deployers as the short reason — the last non-empty
     line of the output — never as a dump of the whole output (a traceback) and never as its first
     line (`Traceback (most recent call last):`), and the `.ps1` git step falls back to plain
     `git init` + `symbolic-ref` on git < 2.28 (no `-b`) instead of hard-exiting,
  10. repo-path scoping hazards of a deployment: BOTH deployers ignore the factory's own
     `task.yaml` / `start.cmd` / `start.sh` (the pattern list AND the written `.gitignore` block —
     a leftover task file or launcher in a TARGET project must not be mistaken for a new task and
     must not be committed; a list that is only checked but never written re-appends the block on
     every run) AND the machine-local `.kimi-code/mcp.json`, whose managed entry carries the
     absolute path of the vendored package of THIS installation (ignoring the vendor directory alone
     protects the package, not the config pointing at it), and BOTH launcher templates export
     `KIMI_FACTORY_LAUNCH_DIR` — the absolute launch
     directory, the machine-checkable anchor for resolving the task's `repo_path`,
  11. the MCP deployment step of BOTH deployers: the PINNED package is installed into
     `<project>/.kimi-code/vendor/chrome-devtools-mcp/` through the interpreter they already probed
     (never a bare `python`) and only then is the managed `chrome-devtools` stdio server merged into
     the project's `.kimi-code/mcp.json` — launched as `node <absolute vendored entry>` (a stdio
     spawn without a shell cannot run npx/npx.cmd on Windows), with no working Python (or a failed
     install) nothing is created at all and the skip is reported,
  12. the MCP report contract: a conflicting pre-existing `chrome-devtools` entry is reported as
     such (never silently replaced), an uninstalled package is reported as
     `chrome-devtools MCP: package install skipped/failed — <reason>`, and both deployers document
     that the configuration takes effect in a NEW Kimi session where `/mcp` shows the connection
     status,
  13. end to end, against fixtures with PRE-EXISTING MCP settings (Windows only):
     an unrelated server and the user's own settings survive byte-for-byte while the managed entry
     is added with the vendored entry path of THAT project, a re-run changes nothing (idempotent), a
     conflicting entry is preserved verbatim and reported, a run without a working Python neither
     fails the deployment nor touches (or creates) the user's file, and an install that cannot be
     done writes no config at all while the deployment reports the reason. The pin itself lives
     ONLY in the shipped asset and the entry path only in the merge helper — both deployers must
     reference those instead of repeating the version or the path layout. The fixtures run the step
     through the documented offline seam (`CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`), so no test ever
     reaches npm or the network,
  14. the managed configuration of a deployment: a merge of the COMMITTED asset produces the managed
     shape (node + the project's absolute vendored entry + the required safety flags and
     environment switches, no permission/attach key). The expected flags, switches and forbidden
     keys are constants of THIS test, never values read back out of the asset under test, and a
     mutation case proves that (dropping one such switch from a copy of the asset fails the
     assertion). Nothing here reads the machine-local `.kimi-code/mcp.json`: it is per installation
     and gitignored, so the check is exercised against a clean-clone fixture in which that file does
     not exist,
  15. the start.sh guard is FATAL when it cannot keep its promise: a backup to `start.sh.bak` that
     fails used to be swallowed by an empty `catch { }` and the overwrite went ahead anyway,
     destroying the user's original launcher. The copy must be guarded, a failed backup must mark a
     hard deployment error, and the launcher write must sit inside that decision — pinned
     statically AND behaviourally (a `start.sh.bak` that is a DIRECTORY makes the copy throw: the
     deployment then exits 1 and leaves the user's launcher untouched),
  16. the memory CHECK line stays ONE line: `memory_project.py check` prints one WARN line per
     legacy-format entry and the verdict last, and the deployer used to interpolate the whole blob
     into the "Project memory: CHECK" warning and the readiness `memory/` line (~50 wrapped lines,
     burying the verdict — owner evidence: warnings.md). Only the trailing `ok -`/`FAIL -` verdict
     plus a WARN count may be printed; the full text stays available for PARSING. Pinned statically
     and, on Windows, against a real deployment into a fixture whose memory has a legacy record (the
     line after the `memory/` bullet must already be the next bullet),
  17. the pre-fix negation probe does not rot: the base commit is resolved with `git log -S
     start.sh.bak` (the OLDEST commit that introduced the guard, minus one) instead of `HEAD`, so
     the very guard assertions are proven to FAIL on the tree before the fix.
  18. the start.sh guard runs FOR REAL where the network is available (a network-gated behavioural
     deployment of a project with a hand-written launcher: it is announced, kept as `start.sh.bak`
     and only then replaced, and a re-run adds no second backup). Offline the case SKIPs with the
     reason instead of failing.

A project deployed by the factory contains only `.agents/` (plus the generated launchers), so
there this test SKIPs cleanly instead of failing on a missing factory repo root.

Exit code 0 = every check passed (skips are fine), 1 = at least one check failed.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable

BOM = b"\xef\xbb\xbf"

SCRIPTS = pathlib.Path(__file__).resolve().parent

PS1_NAME = "prepare_factory.ps1"
CMD_NAME = "prepare_factory.cmd"
START_CMD_NAME = "start.cmd"
SH_NAME = "prepare_factory.sh"

GITATTRIBUTES_NAME = ".gitattributes"
# Pinned at checkout whatever the machine's core.autocrlf says: an LF-only `*.cmd`/`*.ps1`
# working copy is a broken launcher, and the CRLF-only checks below only hold if the checkout
# forced CRLF (a clone with core.autocrlf=false would otherwise hand out LF).
EOL_PINS = ("*.cmd text eol=crlf", "*.ps1 text eol=crlf")
# The bash side is pinned the other way round: bash scripts are LF files, and the deployer itself
# writes start.sh with LF, so a CRLF checkout would only diverge from what the deployer produces.
SH_EOL_PIN = "*.sh text eol=lf"

# Deployment-failure markers, pinned by name (this file never hard-codes a line number).
PS1_COPY_FUNCTION = "Copy-FactoryTree"
# The fallback branch itself: the recursive copy of every top-level entry, and the SAME Copy-Item
# invocation with the failure turned terminating - the flag has to sit ON the call, so a comment
# that merely mentions it does not satisfy the check (comments are dropped before matching).
PS1_FALLBACK_TOKENS = ("Get-ChildItem -LiteralPath $Source -Force",
                       "Copy-Item -LiteralPath $_.FullName -Destination $Destination "
                       "-Recurse -Force -ErrorAction Stop",
                       "$script:HardError = $true",
                       'Err "')
SH_MEM_FAIL_MARKER = "Project memory: failed to create"
# The reason shown for a failed init must be the LAST NON-EMPTY line of the output: the whole
# blob (an interpreter traceback) drowns the actual message, the exception line does not.
SH_REASON_TOKENS = ("$MEM_INIT_OUT", "awk", "NF", "END", "print last")

# The Windows twins of the two markers above (the .ps1 must not drift from the .sh contract).
PS1_MEM_FAIL_MARKER = "Project memory: failed to create"
# ... and the last non-empty line is the reason, not the first: a traceback OPENS with
# `Traceback (most recent call last):`, which names no cause at all.
PS1_REASON_TAIL = "Select-Object -Last 1"
PS1_REASON_FILTER_TOKENS = ("Where-Object", ".Trim()", "-ne ''")
# The git step: `git init -b main` exists only since git 2.28. On older git the first attempt
# fails with `unknown switch 'b'`, so the deployer has to fall back to plain init + symbolic-ref
# (the unborn branch is renamed without a commit) and may hard-exit only when THAT fails too.
PS1_GIT_ATTEMPT = "init -b main"
PS1_GIT_FALLBACK = "symbolic-ref HEAD refs/heads/main"
PS1_GIT_HARD_ERROR = "failed to create the repository"
PS1_HARD_EXIT = re.compile(r"\bexit\s+1\b")

# --- the start.sh guard: the user's original launcher is preserved -----------------------------
# A pre-existing `start.sh` that differs from the template is announced, copied to `start.sh.bak`
# and only then replaced. The promise is "the user's original launcher is preserved", so a backup
# that CANNOT be created must abort the overwrite: an empty `catch { }` around the copy destroyed
# the very file the step promises to keep.
SH_BACKUP_SUFFIX = "start.sh.bak"
SH_DIFFERS_MARKER = "differs from the template"
# Where each deployer writes the launcher (the line the backup has to come BEFORE).
SH_WRITE_MARKERS = {SH_NAME: '> "$LAUNCHER"', PS1_NAME: "Write-FileStrict -Path $LauncherSh"}
PS1_SH_BACKUP_COPY = '[System.IO.File]::Copy($LauncherSh, "$LauncherSh.bak", $true)'
PS1_SH_BACKUP_FLAG = "$ShBackupOk"
PS1_SH_BACKUP_GUARD = f"if ({PS1_SH_BACKUP_FLAG}) {{"
# The words a failed backup must be REPORTED with, and the file the deployment must then abort.
PS1_SH_BACKUP_ABORT = "could not be created"
PS1_HARD_ERROR_FILE = "$script:HardError = $true"
PS1_HARD_ERROR_BANNER = "Deployment incomplete"

# --- the memory CHECK line ----------------------------------------------------------------------
# `memory_project.py check` prints ONE WARN line per legacy-format entry and the verdict last, so a
# deployer may print only the verdict line plus a WARN count - never the whole blob (owner evidence:
# warnings.md, ~50 wrapped lines with the verdict buried in them).
MEM_LINES_VAR = "$MemCheckLines"
MEM_CHECK_OUT_VAR = "$MemCheckOut"
MEM_VERDICT_VAR = "$MemVerdict"
MEM_WARN_COUNT_VAR = "$MemWarnCount"
MEM_REPORT_VAR = "$MemReport"
# The verdict is the LAST line the helper prefixes with `ok - ` / `FAIL - `.
MEM_VERDICT_SPLIT = r"'^(ok|FAIL)\s*-'"
MEM_WARN_FILTER = "'WARN -*'"
MEM_WARNINGS_HINT = "legacy warnings — run memory_project.py check for details"
MEM_CHECK_MARKER = "Project memory: CHECK"
MEM_READINESS_LABEL = "• memory/:"
MEM_READINESS_CHECK = "CHECK ✗"

# The deployers must produce exactly these files in a fresh project (without a working Python
# the two memory files are the only expected gap - see MEMORY_RELS).
CREATED_RELS = (
    ".agents/skills/code-factory/SKILL.md",
    "memory/change-log.md",
    "memory/summary.md",
    ".gitignore",
    ".git",
    "start.cmd",
    "start.sh",
    ".kimi-code/mcp.json",
)
MEMORY_RELS = ("memory/change-log.md", "memory/summary.md")
GITIGNORE_PATTERNS = (".agents/", ".code-factory/", ".kimi-code/mcp.json", ".kimi-code/vendor/",
                      "__pycache__/", "*.pyc",
                      ".env", ".env.*", "*.env", "*.pem", "*.key",
                      "task.yaml", "start.cmd", "start.sh")

# The launchers export the absolute directory they live in: the machine-checkable anchor the
# instruction layer resolves the task's `repo_path` against (the launch directory is never guessed).
LAUNCH_DIR_VAR = "KIMI_FACTORY_LAUNCH_DIR"
SH_LAUNCH_DIR_TOKENS = ("export " + LAUNCH_DIR_VAR + "=", "BASH_SOURCE", "pwd")
# The value is `%CD%` right after `cd /d "%~dp0"` - the same anchor with cmd's own normalization
# (absolute, no trailing backslash); the `cd` must come first, so it is checked in the function.
CMD_LAUNCH_DIR_TOKENS = (LAUNCH_DIR_VAR, "%CD%")
CMD_LAUNCH_DIR_SOURCE = 'cd /d "%~dp0"'
# The factory's OWN files inside a deployed project: a leftover task file or launcher left in a
# TARGET project must not look like a new task and must not be committed by either deployer.
DEPLOYER_HAZARD_PATTERNS = ("task.yaml", "start.cmd", "start.sh")

CMD_USAGE = "Usage: prepare_factory.cmd <path-to-project>"
PS_INVOCATION = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_factory.ps1" %*'

CMD_TOKENS = ("chcp 65001", "-NoProfile", "-ExecutionPolicy Bypass", "-File",
              "%~dp0prepare_factory.ps1", "%*", "exit /b")
START_CMD_TOKENS = ("chcp 65001", 'cd /d "%~dp0"',
                    "set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1",
                    "where kimi", "kimi %*", "exit /b")

# --- managed Chrome DevTools MCP deployment ----------------------------------------------------
# The Kimi Code CLI reads its stdio MCP servers from `.kimi-code/mcp.json`. The factory manages
# exactly ONE entry there, launched as `node <absolute vendored entry>` (a stdio spawn without a
# shell cannot run npx/npx.cmd on Windows: ENOENT/EINVAL). The PIN lives only in the shipped asset
# and the entry-path layout only in the merge helper — the deployers reference both, they never
# repeat the version or the path (anti-drift by construction).
MCP_REL = ".kimi-code/mcp.json"
# The same path as a `.gitignore` pattern of a deployed project: the managed entry carries the
# ABSOLUTE path of the vendored package of THIS installation, so a committed config would hand a
# fresh clone a launch path that does not exist there. Ignoring `.kimi-code/vendor/` alone protects
# the package, not the config pointing at it — both deployers ignore the pattern (F12).
MCP_CONFIG_PATTERN = MCP_REL
MCP_ASSET_REL = ".agents/skills/code-factory/assets/chrome-devtools.mcp.json"
MCP_SERVER = "chrome-devtools"
MCP_PACKAGE = "chrome-devtools-mcp"
MCP_VERSION = "1.11.0"
MCP_PIN = f"{MCP_PACKAGE}@{MCP_VERSION}"
# The per-installation vendored package: `<project>/.kimi-code/vendor/<package>/`.
MCP_VENDOR_REL = ".kimi-code/vendor/" + MCP_PACKAGE
MCP_ENTRY_REL = MCP_VENDOR_REL + "/node_modules/" + MCP_PACKAGE + "/build/src/bin/" + MCP_PACKAGE + ".js"
# The tail every absolute entry path ends with (the merge derives the rest from `--target`).
MCP_ENTRY_SUFFIX = "/node_modules/" + MCP_PACKAGE + "/build/src/bin/" + MCP_PACKAGE + ".js"
# The entry path is DEPLOYMENT-derived, so the shipped template carries this placeholder.
MCP_ENTRY_PLACEHOLDER = "{CHROME_DEVTOOLS_MCP_ENTRY}"
# The documented test seam of `vendor-install`: write a placeholder entry instead of calling npm.
MCP_VENDOR_OFFLINE_ENV = "CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE"
# The safety defaults a deployed configuration must carry: an isolated temporary browser profile, no
# usage statistics, no CrUX lookups, redacted network headers and no update checks. These are the
# REQUIRED flags/switches, pinned here INDEPENDENTLY of the asset: an expectation read back out of
# the file under test travels through every mutation of that file (F14 — see
# `mcp_safety_switches_are_load_bearing`).
MCP_REQUIRED_FLAGS = ("--isolated=true", "--headless=true", "--channel=stable",
                      "--no-usage-statistics", "--no-performance-crux", "--redact-network-headers=true")
MCP_UPDATE_CHECK_ENV = "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"
MCP_USAGE_ENV = "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"
MCP_SAFETY_ENV = {MCP_UPDATE_CHECK_ENV: "1", MCP_USAGE_ENV: "1"}
# A blanket MCP permission (a wildcard allow rule) and attaching to an already running browser
# session are explicit opt-ins, never defaults: none of these keys may appear in a managed entry.
MCP_FORBIDDEN_KEYS = ("autoApprove", "permissions", "allowedTools", "browserUrl", "wsEndpoint")
# The numbered section both deployers carry the step in, and the exact paths of the two files
# the step works with (the merge helper and the pinned template), per deployer syntax.
MCP_SECTION = "Chrome DevTools MCP configuration"
READINESS_SECTION = "Readiness check"
MCP_MERGE_PS = "Join-Path $ProjectAgents 'skills\\code-factory\\scripts\\chrome_devtools_mcp.py'"
MCP_ASSET_PS = "Join-Path $ProjectAgents 'skills\\code-factory\\assets\\chrome-devtools.mcp.json'"
MCP_MERGE_SH = "$PROJECT_DIR/.agents/skills/code-factory/scripts/chrome_devtools_mcp.py"
MCP_ASSET_SH = "$PROJECT_DIR/.agents/skills/code-factory/assets/chrome-devtools.mcp.json"
# The vendor directory next to the config (`vendor-install --target`) and the two helper calls.
MCP_VENDOR_PS = "Join-Path $McpDir 'vendor\\chrome-devtools-mcp'"
MCP_VENDOR_SH = '"$MCP_DIR/vendor/chrome-devtools-mcp"'
MCP_VENDOR_CALL_PS = "@($McpMerge, 'vendor-install', '--target', $McpVendor, '--asset', $McpAsset)"
MCP_VENDOR_CALL_SH = '"$PY_BIN" "$MCP_MERGE" vendor-install --target "$MCP_VENDOR" --asset "$MCP_ASSET"'
MCP_MERGE_CALL_PS = "@($McpMerge, 'merge-config', '--target', $McpFile, '--asset', $McpAsset)"
MCP_MERGE_CALL_SH = '"$PY_BIN" "$MCP_MERGE" merge-config --target "$MCP_FILE" --asset "$MCP_ASSET"'
MCP_VENDOR_RC_PS = "$vendorRes.ExitCode -ne 0"
MCP_VENDOR_RC_SH = '"$VENDOR_RC" -ne 0'
MCP_EXISTING_PS = "if (Test-Path -LiteralPath $McpFile -PathType Leaf) {"
MCP_EXISTING_SH = 'if [[ -f "$MCP_FILE" ]]; then'
# The superseded fallback: copying the template as the configuration. The template carries the
# entry-path PLACEHOLDER now, so a copy is not a working config — neither deployer may do it.
MCP_TEMPLATE_COPY_PS = "Copy-Item -LiteralPath $McpAsset -Destination $McpFile"
MCP_TEMPLATE_COPY_SH = 'cp "$MCP_ASSET" "$MCP_FILE"'
# The conflict / skip / documentation contract, worded identically in both deployers.
MCP_CONFLICT_MARKER = "MCP config: CONFLICT"
MCP_VENDOR_SKIP_MARKER = "chrome-devtools MCP: package install skipped/failed"
MCP_SKIP_SOURCE = "MCP config: skipped — "
MCP_SKIP_RUNTIME = "MCP config: skipped — python not found"
MCP_LEFT_UNTOUCHED = "left untouched"
MCP_NO_PYTHON = "python not found"
MCP_NEW_SESSION_MARKER = "takes effect in a NEW Kimi session"
MCP_STATUS_TOKEN = "/mcp"
MCP_READINESS_LABEL = "• .kimi-code/mcp.json:"
MCP_READINESS_STATE = re.compile(r"•\s*\.kimi-code/mcp\.json:\s*(?P<state>\S+)")


REPO_FILES = (PS1_NAME, CMD_NAME, SH_NAME, START_CMD_NAME)


def find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    """The deployment root: the one directory holding the .ps1/.cmd/.sh deployer + start.cmd.

    `None` when there is none - a project deployed BY the factory receives only `.agents/` plus
    the generated launchers, so these files are absent there and the test cannot run (main()
    reports that as a SKIP instead of a failure).
    """
    for path in (start, *start.parents):
        if all((path / name).is_file() for name in REPO_FILES):
            return path
    return None


FOUND_REPO = find_repo_root(SCRIPTS)      # None inside a project deployed by the factory
REPO = FOUND_REPO or SCRIPTS              # keep the module-level paths defined for the summary
PS1 = REPO / PS1_NAME
CMD = REPO / CMD_NAME
START_CMD = REPO / START_CMD_NAME
SH = REPO / SH_NAME
GITATTRIBUTES = REPO / GITATTRIBUTES_NAME


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def assertion_error(run: Callable[[], object]) -> str | None:
    """The message of the AssertionError `run` raises, or `None` when it passes.

    A mutation check needs BOTH outcomes: the unmutated control must pass, and the mutation must
    FAIL the very assertion that is supposed to detect it.
    """
    try:
        run()
    except AssertionError as exc:
        return str(exc) or "assertion failed"
    return None


def read_text(path: pathlib.Path) -> str:
    """UTF-8 text of a file, with a possible BOM stripped."""
    return path.read_bytes().decode("utf-8-sig")


def normalize_newlines(text: str) -> str:
    """Compare-ready form: no BOM, LF only, no trailing newline noise."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").rstrip("\n")


def check_text_file(path: pathlib.Path, *, bom: bool, crlf_only: bool = True) -> str:
    """Existence, UTF-8 validity, BOM presence/absence and line endings.

    `crlf_only=True` (the Windows files) demands that every `\\r` and every `\\n` belongs to a
    `\\r\\n` pair. The bash deployer is checked with `crlf_only=False` instead: its canonical state
    is LF-only (`.gitattributes` pins `*.sh` to `eol=lf`), but a checkout with `core.autocrlf=true`
    still hands it out with CRLF - both whole-file states are fine, a file with MIXED line endings
    never is.
    """
    expect(path.is_file(), f"{path} must exist")
    data = path.read_bytes()
    if bom:
        expect(data.startswith(BOM),
               f"{path.name} must start with the UTF-8 BOM (EF BB BF), got {data[:3]!r}")
    else:
        expect(not data.startswith(BOM),
               f"{path.name} must NOT start with a BOM (cmd.exe would choke on it), got {data[:3]!r}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(f"{path.name} must be valid UTF-8: {exc}") from None
    # A lone \r is never right: it is not a line ending on its own, in any of these files.
    expect(text.count("\r\n") == text.count("\r"),
           f"{path.name} has a lone CR (not part of CRLF): {text.count(chr(13))} CR vs "
           f"{text.count(chr(13) + chr(10))} CRLF")
    if crlf_only:
        expect(text.count("\r\n") == text.count("\n"),
               f"{path.name} has a lone LF (not part of CRLF): {text.count(chr(10))} LF vs "
               f"{text.count(chr(13) + chr(10))} CRLF")
    else:
        crlf, lf = text.count("\r\n"), text.count("\n")
        expect(crlf == 0 or crlf == lf,
               f"{path.name} mixes line endings: {crlf} CRLF vs {lf} LF - a file is either all LF "
               "(what `.gitattributes` pins) or all CRLF (what core.autocrlf=true checks out), "
               "never a mix")
    return text


# --- PowerShell template extraction (no line numbers hard-coded anywhere) ------------------

_PS_ARRAY_HEAD = re.compile(r"^\s*\$\w+\s*=\s*@\(\s*$")
_PS_ARRAY_TAIL = re.compile(r"^\s*\)\s*$")
_PS_ARRAY_ONE_LINE = re.compile(r"^\s*\$\w+\s*=\s*@\((?P<body>.+)\)\s*$")
_PS_SQ_ELEMENT = re.compile(r"^\s*'((?:[^']|'')*)'\s*,?\s*$")
_PS_SQ_ITEM = re.compile(r"'((?:[^']|'')*)'")
_PS_HERE_HEAD = re.compile(r"^\s*@(['\"])\s*$")
_PS_HERE_TAIL = re.compile(r"^\s*['\"]@\s*$")


def ps_one_line_array(text: str) -> list[str] | None:
    """The elements of a single-line `$name = @('a', 'b')` literal, or `None` for anything else.

    Only a plain list of single-quoted strings qualifies: as soon as a comma-separated part is not
    such a string (an expression, code), this returns `None` and the caller skips the line.
    """
    match = _PS_ARRAY_ONE_LINE.match(text)
    if match is None:
        return None
    body = match.group("body").strip()
    items = _PS_SQ_ITEM.findall(body)
    if not items:
        return None
    # Whatever is left between the quoted items must be separators only, never code.
    if _PS_SQ_ITEM.sub("", body).replace(",", "").strip():
        return None
    return [item.replace("''", "'") for item in items]


def ps_string_arrays(text: str) -> list[list[str]]:
    """Every `$name = @( 'a', 'b' )` literal in `text`, as a list of its string elements.

    Both shapes count: the multi-line block (one element per line) and the one-liner. A block whose
    elements are not all plain single-quoted strings (nested expressions, code) is skipped
    entirely, so unrelated arrays in the script never produce a bogus template.
    """
    lines = text.splitlines()
    out: list[list[str]] = []
    i = 0
    while i < len(lines):
        if not _PS_ARRAY_HEAD.match(lines[i]):
            one_line = ps_one_line_array(lines[i])
            if one_line:
                out.append(one_line)
            i += 1
            continue
        j = i + 1
        items: list[str] | None = []
        while j < len(lines) and not _PS_ARRAY_TAIL.match(lines[j]):
            match = _PS_SQ_ELEMENT.match(lines[j])
            if match is None:
                items = None
                break
            items.append(match.group(1).replace("''", "'"))
            j += 1
        if items:
            out.append(items)
        i = j + 1
    return out


def ps_here_strings(text: str) -> list[list[str]]:
    """Every PowerShell here-string (`@' ... '@`, `@" ... "@`) in `text`, line by line."""
    lines = text.splitlines()
    out: list[list[str]] = []
    i = 0
    while i < len(lines):
        if not _PS_HERE_HEAD.match(lines[i]):
            i += 1
            continue
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not _PS_HERE_TAIL.match(lines[j]):
            body.append(lines[j])
            j += 1
        if j < len(lines):
            out.append(body)
        i = j + 1
    return out


def ps_function_body(text: str, name: str) -> list[str]:
    """The lines inside `function <name> {`, brace-counted (the body may contain `{ ... }` blocks).

    Braces inside strings or comments would confuse the counter, so this stays limited to the
    functions pinned here - none of them contains one.
    """
    lines = text.splitlines()
    head = re.compile(r"^\s*function\s+" + re.escape(name) + r"\s*\{\s*$")
    for i, line in enumerate(lines):
        if not head.match(line):
            continue
        body: list[str] = []
        depth = 1
        for later in lines[i + 1:]:
            depth += later.count("{") - later.count("}")
            if depth == 0:
                return body
            body.append(later)
        raise AssertionError(f"{PS1_NAME}: function {name} is never closed")
    raise AssertionError(f"{PS1_NAME} has no `function {name} {{` definition")


def extract_ps_template(text: str, first_line: str) -> list[str]:
    """The launcher template inlined in the .ps1 whose first line is exactly `first_line`.

    Both shapes are recognised (a single-quoted here-string and a single-quoted string array),
    so a future refactor of the script keeps working — only the template content is pinned.
    """
    for body in ps_here_strings(text) + ps_string_arrays(text):
        if body and body[0] == first_line:
            return body
    raise AssertionError(
        f"{PS1_NAME} has no inline template starting with {first_line!r} "
        "(expected a single-quoted here-string `@'...'@` or a string array `@( '...' )`)")


def extract_heredoc(text: str, marker: str) -> list[str]:
    """The body of the `<<'EOF'` / `<<EOF` here-document terminated by `marker`."""
    lines = text.splitlines()
    opener = re.compile(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z0-9_]*)'?\"?\s*$")
    for i, line in enumerate(lines):
        match = opener.search(line)
        if not match or match.group(1) != marker:
            continue
        body: list[str] = []
        for later in lines[i + 1:]:
            if later.strip() == marker:
                return body
            body.append(later)
        raise AssertionError(f"{SH_NAME}: here-doc <<{marker}> is never terminated")
    raise AssertionError(f"{SH_NAME} has no <<{marker} here-document")


def describe_diff(expected: list[str], actual: list[str],
                  expected_name: str, actual_name: str) -> str:
    """A short, explicit drift report pointing at the first differing line."""
    if len(expected) != len(actual):
        head = f"line count differs: {expected_name} has {len(expected)}, {actual_name} has {len(actual)}"
    else:
        head = f"line count matches ({len(expected)} lines)"
    for number, (left, right) in enumerate(zip(expected, actual), 1):
        if left != right:
            return (f"{head}; first difference on line {number}:\n"
                    f"  {expected_name}: {left!r}\n"
                    f"  {actual_name}: {right!r}")
    return head


# --- individual static checks ----------------------------------------------------------------


def prepare_cmd_contract() -> None:
    text = check_text_file(CMD, bom=False)
    for token in CMD_TOKENS:
        expect(token in text, f"{CMD_NAME} must contain {token!r}")
    expect(PS_INVOCATION in text,
           f"{CMD_NAME} must launch the deployer exactly as {PS_INVOCATION!r}")
    # cmd.exe prints the usage line; `<>` are caret-escaped in batch, so compare unescaped.
    unescaped = text.replace("^<", "<").replace("^>", ">")
    expect("echo " + CMD_USAGE in unescaped,
           f"{CMD_NAME} must print {CMD_USAGE!r}")


def prepare_cmd_pause_guard() -> None:
    text = check_text_file(CMD, bom=False)
    lines = text.splitlines()
    pauses = [i for i, line in enumerate(lines) if line.strip() == "pause"]
    expect(pauses, f"{CMD_NAME} must still pause on a double-click (no 'pause' line found)")
    guards = [i for i, line in enumerate(lines) if "%cmdcmdline%" in line]
    expect(guards, f"{CMD_NAME}: 'pause' is unguarded - no %cmdcmdline% double-click detection; "
                   "an unconditional pause hangs automated runs")
    guard = guards[0]
    for index in pauses:
        expect(index > guard,
               f"{CMD_NAME}: 'pause' on line {index + 1} comes BEFORE the %cmdcmdline% guard on "
               f"line {guard + 1}: it would hang an automated run")
    expect(any("goto :no_pause" in line for line in lines[guard:pauses[0]]),
           f"{CMD_NAME}: the double-click guard must jump over the pause (`goto :no_pause`)")
    expect(any(line.strip().startswith(":no_pause") for line in lines[pauses[-1]:]),
           f"{CMD_NAME}: the :no_pause label must follow the pause")
    # Second half of the double-click test: timeout.exe fails on redirected input, so an
    # automated run (stdin=DEVNULL) also skips the pause.
    expect(any("timeout.exe" in line for line in lines[guard:pauses[0]]),
           f"{CMD_NAME}: the guard must also check that stdin is an interactive console "
           "(timeout.exe refuses redirected input) before pausing")


def start_cmd_contract() -> None:
    text = check_text_file(START_CMD, bom=False)
    first = text.splitlines()[0] if text.splitlines() else ""
    expect(first == "@echo off",
           f"{START_CMD_NAME} must start with exactly '@echo off', got {first!r}")
    for token in START_CMD_TOKENS:
        expect(token in text, f"{START_CMD_NAME} must contain {token!r}")


def antidrift_start_cmd() -> None:
    template = extract_ps_template(read_text(PS1), "@echo off")
    actual = normalize_newlines(read_text(START_CMD)).split("\n")
    expect(template == actual,
           "the inline start.cmd template in " + PS1_NAME + " drifted from " + START_CMD_NAME
           + ": " + describe_diff(template, actual, "template in " + PS1_NAME, START_CMD_NAME))


def antidrift_start_sh() -> None:
    template = extract_ps_template(read_text(PS1), "#!/usr/bin/env bash")
    heredoc = extract_heredoc(read_text(SH), "EOF")
    expect(template == heredoc,
           "the inline start.sh template in " + PS1_NAME + " drifted from the here-doc in "
           + SH_NAME + ": " + describe_diff(template, heredoc, "template in " + PS1_NAME + " (start.sh)",
                                            "here-doc in " + SH_NAME))


def bash_deployer_untouched() -> None:
    text = check_text_file(SH, bom=False, crlf_only=False)
    # The bash deployer generates NO Windows launcher. Its one legitimate mention of `start.cmd` is
    # the `.gitignore` pattern of the deployed project (a leftover launcher in a TARGET project must
    # not be committed) - anything else would be the Windows work leaking into the bash path.
    allowed = re.compile(r'^for\s+pat\s+in\b.*$|^echo\s+"start\.cmd"$')
    offenders = [line.strip() for line in text.splitlines()
                 if "start.cmd" in line and not allowed.match(line.strip())]
    expect(not offenders,
           f"{SH_NAME} must not create or reference start.cmd (that is {PS1_NAME}'s job); only its "
           f".gitignore pattern may be mentioned, got {offenders}")
    expect(extract_heredoc(text, "EOF")[0] == "#!/usr/bin/env bash",
           f"{SH_NAME}: the start.sh here-doc must still start with the bash shebang")


def git_show(rev_path: str) -> str | None:
    """`git show <rev>:<path>` of this repository, or `None` when git cannot serve it."""
    try:
        proc = subprocess.run(["git", "-C", str(REPO), "show", rev_path],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"INFO - git show {rev_path} was skipped: {exc!r}")
        return None
    if proc.returncode != 0:
        print(f"INFO - git show {rev_path} failed")
        return None
    return proc.stdout


def pre_guard_base(rel: str) -> str | None:
    """The commit that PREDATES the start.sh guard in `rel`, resolved deterministically.

    `git log -S` names exactly the commits whose diff changed the number of `start.sh.bak`
    occurrences; the OLDEST of them introduced the guard, so its parent is the pre-fix tree. Probing
    `HEAD` rots by construction: once the guard is committed, HEAD and the probe compare the same
    text, the negation can never fire again and the vaccine is dead.
    """
    try:
        proc = subprocess.run(["git", "-C", str(REPO), "log", "--format=%H", "--reverse",
                               "-S", SH_BACKUP_SUFFIX, "--", rel],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"INFO - the pre-fix base resolution was skipped: {exc!r}")
        return None
    if proc.returncode != 0:
        print("INFO - the pre-fix base resolution was skipped: git log failed")
        return None
    commits = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not commits:
        print(f"INFO - the pre-fix base resolution was skipped: no commit ever touched "
              f"{SH_BACKUP_SUFFIX} in {rel}")
        return None
    return f"{commits[0]}^"


def assert_start_sh_guard(name: str, text: str, write_marker: str) -> None:
    """(a) announce a differing launcher, (b) keep it as `start.sh.bak`, (c) both BEFORE the write."""
    expect(SH_BACKUP_SUFFIX in text,
           f"{name}: a pre-existing start.sh must be kept as {SH_BACKUP_SUFFIX}")
    expect(SH_DIFFERS_MARKER in text,
           f"{name}: a differing start.sh must be announced, not silently overwritten")
    guard_at = min((i for i, line in enumerate(text.splitlines())
                    if SH_BACKUP_SUFFIX in line), default=-1)
    write_at = text.find(write_marker)
    expect(guard_at != -1 and write_at != -1 and
           guard_at < text[:write_at].count(chr(10)),
           f"{name}: the backup/warning must run BEFORE the launcher is written")


def launcher_backup_guard() -> None:
    """A pre-existing, DIFFERING `start.sh` is announced and backed up, never silently truncated.

    Both deployers must (a) warn with the `differs from the template` sentence, (b) keep the old
    file as `start.sh.bak`, and (c) do it BEFORE the launcher is written. The guard is proven to
    bite: the SAME assertions run against the deployer of the PRE-FIX base commit (`pre_guard_base`,
    resolved from the history rather than from `HEAD`) and must FAIL there, so a revert of the fix
    cannot leave this check green.
    """
    for name, path in ((SH_NAME, SH), (PS1_NAME, PS1)):
        assert_start_sh_guard(name, read_text(path), SH_WRITE_MARKERS[name])

    # Vaccination: the pre-fix tree has no guard, so the assertions above must fail on it.
    for rel in (SH_NAME, PS1_NAME):
        base = pre_guard_base(rel)
        if base is None:
            return
        old = git_show(f"{base}:{rel}")
        if old is None:
            return
        failure = assertion_error(
            lambda: assert_start_sh_guard(rel, old, SH_WRITE_MARKERS[rel]))
        expect(failure is not None,
               f"{rel}: the pre-fix tree {base} PASSES the start.sh guard assertions "
               f"({SH_BACKUP_SUFFIX} / {SH_DIFFERS_MARKER!r}): the negation probe proves nothing "
               "about the fix; got {failure}")


def ps1_start_sh_backup_failure_is_fatal() -> None:
    """A backup that cannot be created must abort the overwrite, not precede it.

    The copy used to sit in `catch { }`: any failure (permissions, a directory named
    `start.sh.bak`) vanished and `Write-FileStrict` replaced the user's launcher anyway - destroying
    exactly the file this step promises to preserve. So: a real try/catch, a hard deployment error
    plus a report inside it, and the launcher write INSIDE the flag that the failure clears.
    """
    code = ps1_code_lines()
    copy_at = next((i for i, line in enumerate(code) if PS1_SH_BACKUP_COPY in line), None)
    expect(copy_at is not None,
           f"{PS1_NAME}: the start.sh backup is gone ({PS1_SH_BACKUP_COPY})")
    write_at = next((i for i, line in enumerate(code)
                     if SH_WRITE_MARKERS[PS1_NAME] in line), None)
    expect(write_at is not None and write_at > copy_at,
           f"{PS1_NAME}: the launcher write must follow the backup")
    between = "\n".join(code[copy_at:write_at])
    expect("catch { }" not in between,
           f"{PS1_NAME}: the backup sits in an empty `catch {{ }}` - a failed copy is swallowed and "
           "the overwrite proceeds, destroying the user's original launcher; the failed backup has "
           "to abort the overwrite and mark a hard deployment error")
    catch_at = between.find("catch {")
    expect(catch_at != -1, f"{PS1_NAME}: the backup copy must be guarded by a try/catch")
    catch_body = between[catch_at:]
    expect(PS1_HARD_ERROR_FILE in catch_body,
           f"{PS1_NAME}: a failed backup must mark a HARD deployment error "
           f"({PS1_HARD_ERROR_FILE}) - an incomplete deployment must not end with exit 0")
    expect(PS1_SH_BACKUP_ABORT in catch_body,
           f"{PS1_NAME}: a failed backup must be REPORTED ({PS1_SH_BACKUP_ABORT!r})")
    expect(re.search(r"\bErr\s+\"", catch_body) is not None,
           f"{PS1_NAME}: the failed backup needs an `Err` line (a business message, not a silent "
           "skip and not a raw engine record)")
    expect(f"{PS1_SH_BACKUP_FLAG} = $false" in catch_body,
           f"{PS1_NAME}: the failed backup must clear {PS1_SH_BACKUP_FLAG} so the overwrite is "
           "skipped")
    expect(PS1_SH_BACKUP_GUARD in between,
           f"{PS1_NAME}: the launcher write must be conditional on {PS1_SH_BACKUP_FLAG} "
           f"(`{PS1_SH_BACKUP_GUARD}`)")
    expect(code[write_at - 1].strip() == PS1_SH_BACKUP_GUARD,
           f"{PS1_NAME}: the launcher write must sit INSIDE `{PS1_SH_BACKUP_GUARD}` - otherwise a "
           f"failed backup still overwrites the original; got {code[write_at - 1].strip()!r}")


def ps1_gitignore_patterns() -> list[str]:
    """The `.gitignore` pattern list of `prepare_factory.ps1` (the one carrying `.agents/`)."""
    arrays = [array for array in ps_string_arrays(read_text(PS1)) if ".agents/" in array]
    expect(len(arrays) == 1,
           f"{PS1_NAME} must have exactly ONE .gitignore pattern list (the string array containing "
           f"'.agents/'), found {len(arrays)}: {arrays}")
    return arrays[0]


def ps1_ignores_deployer_hazards() -> None:
    """A leftover `task.yaml` / launcher in a TARGET project must never be committed there."""
    patterns = ps1_gitignore_patterns()
    missing = [pattern for pattern in DEPLOYER_HAZARD_PATTERNS if pattern not in patterns]
    expect(not missing,
           f"{PS1_NAME}: the .gitignore pattern list is missing {missing} - a leftover task file "
           f"or launcher of a previous run would be handed to the factory as a new task and would "
           f"be committed; got {patterns}")


def sh_gitignore_patterns() -> list[str]:
    """The `.gitignore` pattern list of `prepare_factory.sh` (`for pat in "..." ...`)."""
    text = check_text_file(SH, bom=False, crlf_only=False)
    lists = [line for line in text.splitlines() if re.match(r"\s*for\s+pat\s+in\b", line)]
    expect(len(lists) == 1,
           f"{SH_NAME} must have exactly ONE `for pat in ...` .gitignore pattern list, "
           f"found {len(lists)}")
    return re.findall(r'"([^"]*)"', lists[0])


def sh_ignores_deployer_hazards() -> None:
    """The bash twin of `ps1_ignores_deployer_hazards`, plus the writing half of the contract.

    The `for pat in ...` list only DECIDES whether the block is needed; the patterns the deployer
    actually appends are the `echo` lines below it. A list that is checked but never written makes
    the deployer re-append its block on every single run, so both halves are pinned here.
    """
    text = check_text_file(SH, bom=False, crlf_only=False)
    lines = [line.strip() for line in text.splitlines()]
    patterns = sh_gitignore_patterns()
    missing = [pattern for pattern in DEPLOYER_HAZARD_PATTERNS if pattern not in patterns]
    expect(not missing,
           f"{SH_NAME}: the .gitignore pattern list is missing {missing} - a leftover task file "
           f"or launcher of a previous run would be handed to the factory as a new task and would "
           f"be committed; got {patterns}")
    unwritten = [pattern for pattern in patterns if f'echo "{pattern}"' not in lines]
    expect(not unwritten,
           f"{SH_NAME}: the .gitignore patterns {unwritten} are checked but never written - the "
           "deployer would append them again on every run; every pattern of the list needs its own "
           "`echo \"<pattern>\"` line inside the appended block")


def mcp_config_is_gitignored() -> None:
    """BOTH deployers ignore the managed MCP config — the pattern list AND the block they write.

    The managed entry launches the vendored package by its ABSOLUTE per-installation path, so a
    committed `.kimi-code/mcp.json` would hand a fresh clone of the TARGET project a launch path
    that does not exist there (`chrome_devtools_mcp.py merge-config` derives it per deployment).
    Ignoring only `.kimi-code/vendor/` protects the package but not the config pointing at it. The
    written half is pinned too: the `.ps1` appends the whole `$CfPatterns` list in a loop, while the
    `.sh` needs its own `echo` line per pattern (a checked-but-unwritten pattern re-appends the
    block on every run).
    """
    ps_patterns = ps1_gitignore_patterns()
    expect(MCP_CONFIG_PATTERN in ps_patterns,
           f"{PS1_NAME}: the .gitignore pattern list is missing {MCP_CONFIG_PATTERN!r} - the managed "
           f"config carries the absolute entry path of THIS installation and must never be "
           f"committed; got {ps_patterns}")
    ps_text = read_text(PS1)
    expect("foreach ($pat in $CfPatterns)" in ps_text and "$add += $pat + $nl" in ps_text,
           f"{PS1_NAME}: the appended .gitignore block must be built from $CfPatterns (every "
           "pattern of the list is written back out)")
    sh_patterns = sh_gitignore_patterns()
    expect(MCP_CONFIG_PATTERN in sh_patterns,
           f"{SH_NAME}: the .gitignore pattern list is missing {MCP_CONFIG_PATTERN!r} - see the "
           f"{PS1_NAME} check above; got {sh_patterns}")
    sh_lines = [line.strip() for line in check_text_file(SH, bom=False, crlf_only=False).splitlines()]
    expect(f'echo "{MCP_CONFIG_PATTERN}"' in sh_lines,
           f"{SH_NAME}: {MCP_CONFIG_PATTERN!r} is checked but never written - the pattern would be "
           f"re-appended on every run; the appended block needs its own "
           f'`echo "{MCP_CONFIG_PATTERN}"` line')
    expect(MCP_CONFIG_PATTERN in GITIGNORE_PATTERNS,
           "this test's own expected pattern list (asserted against the .gitignore a real deployment "
           f"produces) must carry {MCP_CONFIG_PATTERN!r}")


def sh_template_exports_launch_dir() -> None:
    """The `start.sh` template must export the absolute directory the launcher lives in.

    `BASH_SOURCE` (not `$PWD`) is what makes the anchor the LAUNCHER's own directory: the task's
    `repo_path` is resolved relative to it, so a launcher started from another cwd must still
    report where it was installed. Both carriers of the template are pinned - the here-doc of
    `prepare_factory.sh` and the inline `$shLines` array of `prepare_factory.ps1` (the anti-drift
    check above ties them together, this one fails on whichever lost the export).
    """
    templates = {
        "the here-doc of " + SH_NAME: extract_heredoc(check_text_file(SH, bom=False, crlf_only=False),
                                                     "EOF"),
        "the inline template of " + PS1_NAME: extract_ps_template(read_text(PS1), "#!/usr/bin/env bash"),
    }
    for name, template in templates.items():
        line = next((entry for entry in template if f"export {LAUNCH_DIR_VAR}=" in entry), None)
        expect(line is not None,
               f"{name}: start.sh must export {LAUNCH_DIR_VAR} (the launch directory; the "
               "instruction layer resolves the task's repo_path against it) - no "
               f"`export {LAUNCH_DIR_VAR}=` line found; template:\n" + "\n".join(template))
        missing = [token for token in SH_LAUNCH_DIR_TOKENS if token not in line]
        expect(not missing,
               f"{name}: the {LAUNCH_DIR_VAR} export must be the launcher's OWN absolute directory "
               f"(missing {missing}) - `$PWD` would follow the caller's cwd; got {line.strip()!r}")


def cmd_template_exports_launch_dir() -> None:
    """The `start.cmd` template (and the committed `start.cmd`) must export the same anchor.

    `%~dp0` is the directory of the launcher FILE, so `cd /d "%~dp0"` plus `%CD%` is that directory
    in cmd's own normalized form - and a `rem` comment that merely mentions the variable is not the
    export, which is why the comment lines are skipped before matching.
    """
    templates = {
        START_CMD_NAME: read_text(START_CMD).splitlines(),
        "the inline template of " + PS1_NAME: extract_ps_template(read_text(PS1), "@echo off"),
    }
    for name, template in templates.items():
        code = [entry for entry in template if not entry.lstrip().lower().startswith("rem ")]
        index = next((i for i, entry in enumerate(code) if LAUNCH_DIR_VAR in entry), None)
        expect(index is not None,
               f"{name}: start.cmd must export {LAUNCH_DIR_VAR} (the launch directory; the "
               "instruction layer resolves the task's repo_path against it) - no mention of "
               f"{LAUNCH_DIR_VAR} on a code line; lines:\n" + "\n".join(template))
        line = code[index]
        missing = [token for token in CMD_LAUNCH_DIR_TOKENS if token not in line]
        expect(not missing,
               f"{name}: the {LAUNCH_DIR_VAR} export must hold the launcher's OWN directory "
               f"(missing {missing} in {line.strip()!r})")
        expect(any(CMD_LAUNCH_DIR_SOURCE in entry for entry in code[:index]),
               f"{name}: the {LAUNCH_DIR_VAR} export on code line {index + 1} must come AFTER "
               f"`{CMD_LAUNCH_DIR_SOURCE}` - otherwise %CD% is the CALLER's working directory, "
               "not the launch directory")


def bash_memory_failure_is_short() -> None:
    """A failed `memory_project.py init` must be reported by its REASON, not by its whole output.

    The deployer deliberately stays non-fatal there (the factory creates the memory on first use),
    so the one warning line is all the user sees: dumping the raw output puts a Python traceback
    into it, where the exception line alone says what went wrong.
    """
    text = check_text_file(SH, bom=False, crlf_only=False)
    fail_lines = [line for line in text.splitlines() if SH_MEM_FAIL_MARKER in line]
    expect(fail_lines, f"{SH_NAME} must still warn when the memory init fails")
    for line in fail_lines:
        expect("MEM_INIT_OUT" not in line,
               f"{SH_NAME}: the failure warning must not interpolate the whole init output "
               f"($MEM_INIT_OUT) - that is what puts a traceback there; got {line.strip()!r}")
    reason_lines = [line for line in text.splitlines() if "$MEM_INIT_OUT" in line and "awk" in line]
    expect(reason_lines,
           f"{SH_NAME} must derive a short reason from the init output "
           "(awk 'NF{last=$0}END{print last}' over $MEM_INIT_OUT)")
    for line in reason_lines:
        missing = [token for token in SH_REASON_TOKENS if token not in line]
        expect(not missing,
               f"{SH_NAME}: the reason must be the LAST NON-EMPTY line of the init output "
               f"(missing {missing}); got {line.strip()!r}")
        name = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
        expect(name is not None,
               f"{SH_NAME}: the short reason must be stored in a variable, got {line.strip()!r}")
        expect(any("${" + name.group(1) + "}" in fail or "${" + name.group(1) + ":-" in fail
                   for fail in fail_lines),
               f"{SH_NAME}: the failure warning must show the short reason "
               f"(${{{name.group(1)}}}...), got {fail_lines[0].strip()!r}")


def ps1_copy_fallback_is_guarded() -> None:
    """The non-robocopy fallback must turn a copy failure into a business message + exit 1.

    `Copy-Item` fails NON-terminating: outside a try/catch it prints raw engine records
    (CategoryInfo, FullyQualifiedErrorId) and the deployer would still end with the "Done"
    banner and exit 0 for a half-copied `.agents/` tree - the contract there is exit 1 and no banner.
    """
    body = ps_function_body(check_text_file(PS1, bom=True), PS1_COPY_FUNCTION)
    # Comments are dropped first: a comment that only *mentions* a token must not satisfy the pin.
    code = "\n".join(line for line in body if not line.lstrip().startswith("#"))
    for token in PS1_FALLBACK_TOKENS:
        expect(token in code, f"{PS1_NAME}: {PS1_COPY_FUNCTION} must contain {token!r}")
    positions = (code.find("try {"), code.find("Get-ChildItem -LiteralPath $Source -Force"),
                 code.find("catch {"))
    expect(-1 not in positions and positions[0] < positions[1] < positions[2],
           f"{PS1_NAME}: the fallback must sit in a try/catch "
           f"(`try {{` ... Get-ChildItem ... `}} catch {{`), got offsets {positions}")


def ps1_code_lines() -> list[str]:
    """`prepare_factory.ps1` without comment-only lines (a comment mentioning a token is not code)."""
    text = check_text_file(PS1, bom=True)
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def ps1_git_init_fallback() -> None:
    """`git init -b main` exists only since git 2.28 - on older git the deployer must not die.

    The bash deployer already falls back (`git init` + `symbolic-ref HEAD refs/heads/main`, the
    unborn branch renamed without a commit); the Windows one hard-exited on the very first failure,
    so every project on git < 2.28 got "unknown switch 'b'" and a broken deployment. The pin here
    is the ORDER: attempt -> (conditional) plain init -> symbolic-ref -> hard error only after that.
    """
    lines = ps1_code_lines()
    attempt = next((i for i, line in enumerate(lines) if PS1_GIT_ATTEMPT in line), None)
    expect(attempt is not None,
           f"{PS1_NAME} must still try `git init -b main` (one command on git >= 2.28)")
    fallback = next((i for i, line in enumerate(lines[attempt + 1:], attempt + 1)
                     if PS1_GIT_FALLBACK in line), None)
    expect(fallback is not None,
           f"{PS1_NAME}: after the `-b` attempt on line {attempt + 1} the git < 2.28 fallback "
           f"(`git symbolic-ref HEAD refs/heads/main`) is missing")
    plain = [i for i in range(attempt + 1, fallback)
             if re.search(r"\binit\b", lines[i]) and PS1_GIT_ATTEMPT not in lines[i]]
    expect(plain,
           f"{PS1_NAME}: the fallback must run plain `git init` first (nothing between lines "
           f"{attempt + 2} and {fallback} does) - `symbolic-ref` alone fails without a repository")
    expect(any(re.search(r"if\s*\(\s*\$LASTEXITCODE\s*-ne\s*0", lines[i])
               for i in range(attempt, plain[0])),
           f"{PS1_NAME}: the fallback must be conditional on the failed `-b` attempt "
           "(`if ($LASTEXITCODE -ne 0)`), never run next to it")
    early = [lines[i].strip() for i in range(attempt + 1, fallback)
             if PS1_HARD_EXIT.search(lines[i])]
    expect(not early,
           f"{PS1_NAME}: {early} - a hard exit sits between the `-b` attempt (line {attempt + 1}) "
           f"and its fallback (line {fallback + 1}): on git < 2.28 that is 'unknown switch b' plus "
           "a dead deployment instead of a repository")
    hard = next((i for i, line in enumerate(lines) if PS1_GIT_HARD_ERROR in line), None)
    expect(hard is not None,
           f"{PS1_NAME} must still report a git failure to the user (an `Err` line)")
    expect(hard > fallback,
           f"{PS1_NAME}: the git failure message on line {hard + 1} comes BEFORE the fallback on "
           f"line {fallback + 1} - it may fire only when the fallback failed too")
    exit_after = next((i for i in range(attempt, len(lines)) if PS1_HARD_EXIT.search(lines[i])), None)
    expect(exit_after is not None and exit_after > hard,
           f"{PS1_NAME}: a git failure that survives the fallback must stay a hard error "
           f"(Err + exit 1, like `set -e` in the bash version)")


def ps1_memory_failure_is_short() -> None:
    """The Windows twin of `bash_memory_failure_is_short`: the reason, not a traceback dump.

    The deployer stays non-fatal there (the factory creates the memory on first use), so the one
    warning line is all the user sees. It used to show the FIRST output line - for a Python crash
    that is `Traceback (most recent call last):`, which names no cause; the exception line is the
    LAST one.
    """
    lines = ps1_code_lines()
    fail_lines = [line for line in lines if PS1_MEM_FAIL_MARKER in line]
    expect(fail_lines, f"{PS1_NAME} must still warn when the memory init fails")
    for line in fail_lines:
        expect("Select-Object -First 1" not in line,
               f"{PS1_NAME}: the failure warning must not show the FIRST output line "
               f"(a traceback opens with 'Traceback (most recent call last):'); got {line.strip()!r}")
        expect("no output" in line,
               f"{PS1_NAME}: the failure warning must keep its fallback for empty output, "
               f"got {line.strip()!r}")
    reason_lines = [line for line in lines if "$initRes.Output" in line and PS1_REASON_TAIL in line]
    expect(reason_lines,
           f"{PS1_NAME} must derive a short reason from the init output "
           f"(@($initRes.Output) ... {PS1_REASON_TAIL})")
    for line in reason_lines:
        missing = [token for token in PS1_REASON_FILTER_TOKENS if token not in line]
        expect(not missing,
               f"{PS1_NAME}: the reason must be the LAST NON-EMPTY line of the init output "
               f"(missing {missing}), not merely the last one; got {line.strip()!r}")
        name = re.match(r"\s*(\$\w+)\s*=", line)
        expect(name is not None,
               f"{PS1_NAME}: the short reason must be stored in a variable, got {line.strip()!r}")
        expect(any(name.group(1) in fail for fail in fail_lines),
               f"{PS1_NAME}: the failure warning must show the short reason ({name.group(1)}), "
               f"got {fail_lines[0].strip()!r}")


def ps1_memory_check_line_is_single_line() -> None:
    """The memory CHECK line shows the VERDICT plus a warnings count, never the whole `check` output.

    `memory_project.py check` prints one WARN line per legacy-format entry and the verdict last. The
    deployer interpolated the whole blob into the "Project memory: CHECK" warning and the readiness
    `memory/` line, so ~50 wrapped lines buried the verdict (owner evidence: warnings.md). The full
    text stays available for PARSING (`$MemCheckOut`); every PRINTED line is built from
    `$MemReport` = the trailing `ok -`/`FAIL -` verdict + a WARN count.
    """
    code = ps1_code_lines()
    # (a) no line that reaches the console may interpolate the whole check output.
    offenders = [line.strip() for line in code
                 if MEM_CHECK_OUT_VAR in line
                 and (re.search(r"\b(Warn|Info|Err|Write-Host|Out-Host)\b", line)
                      or re.search(re.escape("$MemLine") + r"\s*=", line))]
    expect(not offenders,
           f"{PS1_NAME}: the memory CHECK line(s) interpolate the whole `check` output "
           f"({MEM_CHECK_OUT_VAR}) - one WARN line per legacy entry floods the console and buries "
           f"the verdict; got {offenders}")
    # (b) the output is split into lines first.
    expect(any(MEM_LINES_VAR in line and "ForEach-Object" in line for line in code),
           f"{PS1_NAME}: the check output must be split into lines ({MEM_LINES_VAR}) so the verdict "
           "and the WARN count can be derived from it")
    # (c) the verdict is the LAST `ok -`/`FAIL -` line.
    verdict_line = next((line for line in code
                         if MEM_VERDICT_SPLIT in line and PS1_REASON_TAIL in line), None)
    expect(verdict_line is not None,
           f"{PS1_NAME}: the verdict must be derived as the last line matching {MEM_VERDICT_SPLIT} "
           f"({PS1_REASON_TAIL}) - the trailing verdict line, not the whole dump")
    verdict_name = re.match(r"\s*(\$\w+)\s*=", verdict_line)
    expect(verdict_name is not None and verdict_name.group(1).startswith(MEM_VERDICT_VAR),
           f"{PS1_NAME}: the verdict must be stored in {MEM_VERDICT_VAR}*, "
           f"got {verdict_line.strip()!r}")
    # (d) the warning count comes from the WARN lines of the same output.
    count_line = next((line for line in code
                       if MEM_WARN_COUNT_VAR in line and MEM_WARN_FILTER in line
                       and ".Count" in line), None)
    expect(count_line is not None,
           f"{PS1_NAME}: the number of legacy warnings must be counted "
           f"({MEM_WARN_COUNT_VAR} from the {MEM_WARN_FILTER} lines)")
    # (e) the printed text is verdict + count + the documented hint, built once.
    report_line = next((line for line in code
                        if re.match(r"\s*" + re.escape(MEM_REPORT_VAR) + r"\s*=", line)), None)
    expect(report_line is not None, f"{PS1_NAME}: {MEM_REPORT_VAR} must be built once")
    missing = [token for token in (MEM_VERDICT_VAR, MEM_WARN_COUNT_VAR, MEM_WARNINGS_HINT)
               if token not in report_line]
    expect(not missing,
           f"{PS1_NAME}: {MEM_REPORT_VAR} must be the verdict plus a warnings count plus the hint "
           f"(missing {missing}); got {report_line.strip()!r}")
    # (f) all THREE report sites use it: the CHECK warning and the readiness `memory/` line.
    check_lines = [line for line in code if MEM_CHECK_MARKER in line]
    expect(check_lines, f"{PS1_NAME}: the memory CHECK warning is gone")
    for line in check_lines:
        expect(MEM_REPORT_VAR in line,
               f"{PS1_NAME}: the CHECK warning must show {MEM_REPORT_VAR}, got {line.strip()!r}")
    readiness_lines = [line for line in code if MEM_READINESS_CHECK in line]
    expect(readiness_lines,
           f"{PS1_NAME}: the readiness report must still distinguish the CHECK state")
    for line in readiness_lines:
        expect(MEM_REPORT_VAR in line,
               f"{PS1_NAME}: the readiness `memory/` CHECK line must show {MEM_REPORT_VAR}, "
               f"got {line.strip()!r}")
    expect(sum(1 for line in code if MEM_REPORT_VAR in line) >= 3,
           f"{PS1_NAME}: {MEM_REPORT_VAR} must feed the mixed warning, the CHECK warning AND the "
           "readiness line (all three used to dump the whole check output)")


def gitattributes_rules() -> set[str]:
    """Every rule line of .gitattributes (comments and blanks dropped, CRLF-agnostic)."""
    expect(GITATTRIBUTES.is_file(),
           f"{GITATTRIBUTES.name} must exist: it is what pins the deployer files' line endings")
    # splitlines() drops the CRLF terminator of a CRLF working copy as well - git strips that CR
    # itself, so the pins hold whether or not this machine rewrote the checkout.
    return {line.strip() for line in read_text(GITATTRIBUTES).splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def gitattributes_pins_crlf() -> None:
    """The CRLF-only checks above must hold on ANY clone, not just one with core.autocrlf=true.

    Without the pin, git hands the launchers out with LF where core.autocrlf=false, and LF-only
    .cmd/.ps1 files are broken (cmd.exe and PowerShell 5.1 both expect CRLF).
    """
    lines = gitattributes_rules()
    missing = [pin for pin in EOL_PINS if pin not in lines]
    expect(not missing,
           f"{GITATTRIBUTES.name} must contain {missing} - without the pin a clone with "
           "core.autocrlf=false checks the .cmd/.ps1 launchers out with LF, which no Windows "
           "shell can run")


def gitattributes_pins_sh_lf() -> None:
    """The bash side is pinned the other way round, for the mirrored reason.

    `*.sh` is checked out with CRLF wherever core.autocrlf=true, which is not what the deployer
    produces (it writes `start.sh` with LF) and not what bash expects: a CRLF shebang is a broken
    script, and the CRLF blob would follow the file into the repository.
    """
    lines = gitattributes_rules()
    expect(SH_EOL_PIN in lines,
           f"{GITATTRIBUTES.name} must contain {SH_EOL_PIN!r} - without the pin *.sh arrives with "
           "CRLF wherever core.autocrlf=true, so a Windows checkout diverges from the LF start.sh "
           "the deployer writes")


# --- managed Chrome DevTools MCP deployment (static contract) ---------------------------------


_SECTION_HEAD = re.compile(r"^# --- \d+\.")


def deployer_section(path: pathlib.Path, marker: str, *, bom: bool,
                     crlf_only: bool = True) -> str:
    """The body of one numbered section of a deployer (`# --- N. ...` up to the next header).

    Comments are kept: the caller drops them when it pins code tokens, and a section is small
    enough that a byte-level slice is more honest than a keyword soup over the whole file.
    """
    text = check_text_file(path, bom=bom, crlf_only=crlf_only)
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("# --- ") and marker in line), None)
    expect(start is not None, f"{path.name} must carry a numbered section mentioning {marker!r}")
    end = next((j for j in range(start + 1, len(lines)) if _SECTION_HEAD.match(lines[j])), len(lines))
    return "\n".join(lines[start:end])


def deployer_mcp_section(path: pathlib.Path, *, bom: bool, crlf_only: bool = True) -> str:
    """The deployer's dedicated MCP section: the deployment step is visible, not a side effect."""
    return deployer_section(path, MCP_SECTION, bom=bom, crlf_only=crlf_only)


def _code_of(section: str) -> str:
    """The section without its comment-only lines (a comment mentioning a token is not code)."""
    return "\n".join(line for line in section.splitlines()
                     if not line.lstrip().startswith(("#", "rem ")))


def _install_before_merge(code: str, install_token: str, merge_token: str,
                          name: str) -> None:
    """The vendored install must run FIRST and a failed install must skip the merge.

    Merging an entry whose launch file does not exist would break every Kimi session in the
    project, so the order — install, report a failure, only then merge — is the contract, not an
    implementation detail.
    """
    install = code.find(install_token)
    merge = code.find(merge_token)
    expect(install != -1 and merge != -1 and install < merge,
           f"{name}: the vendored install (offset {install}) must run BEFORE the merge (offset "
           f"{merge}) — merging an entry that points at a file that does not exist breaks every "
           "Kimi session in the project")
    warn = code.find(MCP_VENDOR_SKIP_MARKER)
    expect(-1 < install < warn < merge,
           f"{name}: a failed install must be reported (offset {warn}) between the install and the "
           f"merge (offsets {install}/{merge}) so the merge is skipped")


def ps1_mcp_step() -> None:
    """The .ps1 installs the pinned package FIRST, merges the entry through the probed interpreter.

    Contracts pinned here: (1) `vendor-install` runs before `merge-config`; (2) the helper runs on
    the interpreter the deployer probed (`$PyExe`/`$PyPrefix`); (3) exit code 3 (a conflicting
    entry) stays a reported state; (4) the no-python branch only REPORTS a skip — the template
    carries the entry-path placeholder and is never copied as the configuration, so a user's own
    servers are never wiped.
    """
    code = _code_of(deployer_mcp_section(PS1, bom=True))
    for token in (MCP_MERGE_PS, MCP_ASSET_PS, MCP_VENDOR_PS, MCP_VENDOR_CALL_PS, MCP_VENDOR_RC_PS,
                  MCP_MERGE_CALL_PS, "@($PyExe) + @($PyPrefix)", "Invoke-Capture",
                  "mergeRes.ExitCode -eq 3", "$McpState = 'conflict'", "'vendor-skipped'",
                  MCP_VENDOR_SKIP_MARKER, MCP_SKIP_SOURCE, MCP_NO_PYTHON):
        expect(token in code, f"{PS1_NAME}: the MCP step must contain {token!r}")
    _install_before_merge(code, MCP_VENDOR_CALL_PS, MCP_MERGE_CALL_PS, PS1_NAME)
    expect(MCP_EXISTING_PS in code,
           f"{PS1_NAME}: the no-python branch must check for an EXISTING {MCP_REL} before it says "
           "the file was left untouched")
    full = check_text_file(PS1, bom=True)
    expect(MCP_TEMPLATE_COPY_PS not in full,
           f"{PS1_NAME}: the shipped template carries the entry-path PLACEHOLDER, so it must never "
           f"be copied as the configuration ({MCP_TEMPLATE_COPY_PS!r} found)")
    expect(MCP_ENTRY_PLACEHOLDER not in full,
           f"{PS1_NAME}: the per-installation entry path is derived by the merge helper, never by "
           "the deployer")


def sh_mcp_step() -> None:
    """The bash twin of `ps1_mcp_step`: same install-then-merge order, same never-clobber rule."""
    code = _code_of(deployer_mcp_section(SH, bom=False, crlf_only=False))
    for token in (MCP_MERGE_SH, MCP_ASSET_SH, MCP_VENDOR_SH, MCP_VENDOR_CALL_SH, MCP_VENDOR_RC_SH,
                  MCP_MERGE_CALL_SH, '"$PY_BIN"', "MCP_RC", 'MCP_STATE="conflict"',
                  'MCP_STATE="vendor-skipped"', MCP_VENDOR_SKIP_MARKER, MCP_SKIP_SOURCE,
                  MCP_NO_PYTHON):
        expect(token in code, f"{SH_NAME}: the MCP step must contain {token!r}")
    _install_before_merge(code, MCP_VENDOR_CALL_SH, MCP_MERGE_CALL_SH, SH_NAME)
    expect(MCP_EXISTING_SH in code,
           f"{SH_NAME}: the no-python branch must check for an EXISTING {MCP_REL} before it says "
           "the file was left untouched")
    full = check_text_file(SH, bom=False, crlf_only=False)
    expect(MCP_TEMPLATE_COPY_SH not in full,
           f"{SH_NAME}: the shipped template carries the entry-path PLACEHOLDER, so it must never "
           f"be copied as the configuration ({MCP_TEMPLATE_COPY_SH!r} found)")
    expect(MCP_ENTRY_PLACEHOLDER not in full,
           f"{SH_NAME}: the per-installation entry path is derived by the merge helper, never by "
           "the deployer")


def mcp_report_contract() -> None:
    """Both deployers must REPORT a preserved conflict / a skipped install and document the result.

    A silently missing managed server costs a browser run, and a silently replaced user entry is
    data loss, so the wording is pinned in both deployers: a conflict (never overwritten), a
    skipped install or a skip without python (each naming the reason), and the two facts the user
    needs — a NEW Kimi session picks the configuration up, `/mcp` shows the connection status.
    """
    for name, section in ((f"the MCP section of {PS1_NAME}", deployer_mcp_section(PS1, bom=True)),
                          (f"the MCP section of {SH_NAME}",
                           deployer_mcp_section(SH, bom=False, crlf_only=False))):
        for token in (MCP_CONFLICT_MARKER, MCP_VENDOR_SKIP_MARKER, MCP_SKIP_SOURCE, MCP_NO_PYTHON,
                      MCP_SERVER, MCP_REL, MCP_NEW_SESSION_MARKER, MCP_STATUS_TOKEN):
            expect(token in section, f"{name} must contain {token!r}")


def mcp_readiness_contract() -> None:
    """The MCP state must reach the readiness report — a conflict is not a log line only.

    Every state the step can end in has to be distinguishable there: created, updated, unchanged,
    a preserved conflict, an install that could not be done and a skipped merge without python (the
    last three are exactly the cases a user must not have to dig for). The line itself belongs to
    the readiness section, so that is what is sliced.
    """
    for name, section in ((f"{PS1_NAME} readiness section",
                           deployer_section(PS1, READINESS_SECTION, bom=True)),
                          (f"{SH_NAME} readiness section",
                           deployer_section(SH, READINESS_SECTION, bom=False, crlf_only=False))):
        expect(MCP_READINESS_LABEL in section,
               f"{name} must list {MCP_READINESS_LABEL!r} - a managed server that did not arrive "
               "(or a conflict that was preserved) has to be visible in the report")
        for state in ("created", "updated", "unchanged", "conflict"):
            expect(state in section,
                   f"{name}: the {MCP_REL} readiness line must distinguish the {state!r} state")
        expect("vendor-skipped" in section,
               f"{name}: the {MCP_REL} readiness line must distinguish an uninstalled package "
               "(state 'vendor-skipped') — that is the case where no managed entry exists at all")
        expect("skipped" in section,
               f"{name}: the {MCP_REL} readiness line must distinguish the no-python skip")


def mcp_pin_lives_in_the_asset_only() -> None:
    """One pinned version, one place: the shipped asset. The deployers must not repeat the pin.

    A version string copied into two deployers drifts the moment the asset is bumped, and the
    deployers would then install a release nobody tested. The same holds for the entry-path
    layout: only the merge helper derives it (the deployers pass the vendor directory around).
    """
    for path, bom, crlf_only in ((PS1, True, True), (SH, False, False)):
        text = check_text_file(path, bom=bom, crlf_only=crlf_only)
        expect(MCP_PIN not in text,
               f"{path.name} must not repeat the pin {MCP_PIN!r}: the single source of the managed "
               f"server is {MCP_ASSET_REL}, and only a reference to it may appear here")
        expect(MCP_VERSION not in text,
               f"{path.name} must not repeat the pinned version {MCP_VERSION!r} — the helper reads "
               f"it from {MCP_ASSET_REL}")
        for needle in ("build/src/bin", "build\\src\\bin", MCP_PACKAGE + ".js"):
            expect(needle not in text,
                   f"{path.name} must not spell out the entry path ({needle!r}): only "
                   "chrome_devtools_mcp.py derives it from --target")
    asset = read_text(REPO / MCP_ASSET_REL)
    expect(MCP_PACKAGE in asset and MCP_VERSION in asset,
           f"{MCP_ASSET_REL} must carry the pinned release {MCP_PIN!r} (package + version)")
    expect(MCP_ENTRY_PLACEHOLDER in asset,
           f"{MCP_ASSET_REL} must carry the entry-path placeholder {MCP_ENTRY_PLACEHOLDER!r}: the "
           "path is deployment-derived")
    expect('"npx"' not in asset and "npx" not in asset,
           f"{MCP_ASSET_REL} must launch `node <vendored entry>`, never npx/npx.cmd (the Kimi Code "
           "CLI spawns stdio servers without a shell: ENOENT/EINVAL on Windows)")


def read_asset_entry(asset_path: pathlib.Path) -> dict:
    """The `chrome-devtools` entry of an asset file: the committed template or a mutated copy."""
    data = load_json_or_none(asset_path)
    expect(isinstance(data, dict) and isinstance(data.get("mcpServers"), dict),
           f"{asset_path} must be a JSON object with an mcpServers map")
    entry = data["mcpServers"].get(MCP_SERVER)
    expect(isinstance(entry, dict), f"{asset_path} must define the {MCP_SERVER!r} server")
    return entry


def merged_entry_of_asset(asset_path: pathlib.Path, target: pathlib.Path) -> dict:
    """The entry `chrome_devtools_mcp.py merge-config --asset <asset_path>` writes for `target`.

    Computed here, without importing the helper: the asset entry with its entry-path placeholder
    replaced by the ABSOLUTE vendored entry of THAT project — the only value the merge substitutes.
    """
    entry = read_asset_entry(asset_path)
    args = list(entry.get("args") or [])
    expect(MCP_ENTRY_PLACEHOLDER in args,
           f"{asset_path} must carry the entry-path placeholder {MCP_ENTRY_PLACEHOLDER!r} in args "
           f"(the entry path is deployment-derived); got {args!r}")
    merged = {key: value for key, value in entry.items() if key != "args"}
    merged["args"] = [str(target / pathlib.Path(*MCP_ENTRY_REL.split("/"))),
                      *[arg for arg in args if arg != MCP_ENTRY_PLACEHOLDER]]
    return merged


def assert_managed_shape(entry: dict, label: str) -> None:
    """The managed entry a deployment must produce — checked against INDEPENDENT expectations.

    `label` names where the entry came from (the committed asset, a mutated copy of it, a real
    deployment). Nothing is read back out of the file under test: the required flags, the required
    environment switches and the forbidden permission/attach keys are constants of THIS test, so an
    asset that lost a safety switch FAILS instead of defining its own expectation (F14). The same
    assertion is what a real deployment is checked with, so the mutation proof below covers both.
    """
    expect(isinstance(entry, dict),
           f"{label}: the managed entry must be a JSON object; got {entry!r}")
    expect(entry.get("command") == "node",
           f"{label}: the managed server must be launched as `node <vendored entry>` (a stdio spawn "
           f"without a shell cannot run npx/npx.cmd on Windows); got {entry.get('command')!r}")
    expect("type" not in entry,
           f"{label}: 'type' is not part of the documented Kimi mcp.json schema; {sorted(entry)}")
    args = entry.get("args")
    expect(isinstance(args, list) and args,
           f"{label}: the managed entry needs its entry-path argument; got {args!r}")
    expect(os.path.isabs(str(args[0])),
           f"{label}: args[0] must be an ABSOLUTE path (a relative one would resolve against the "
           f"server's working directory); got {args[0]!r}")
    expect(str(args[0]).replace("\\", "/").endswith(MCP_ENTRY_SUFFIX),
           f"{label}: args[0] must be the installed package entry (...{MCP_ENTRY_SUFFIX}); "
           f"got {args[0]!r}")
    missing = [flag for flag in MCP_REQUIRED_FLAGS if flag not in args[1:]]
    expect(not missing,
           f"{label}: the required safety flags {missing} of {MCP_REQUIRED_FLAGS} are missing - a "
           f"deployment without them is not the reviewed configuration; got {args!r}")
    env = entry.get("env") or {}
    wrong = [f"{key}={env.get(key)!r} (required {value!r})" for key, value in MCP_SAFETY_ENV.items()
             if env.get(key) != value]
    expect(not wrong,
           f"{label}: the required environment switches are not set: {'; '.join(wrong)}; got {env!r}")
    granted = [key for key in MCP_FORBIDDEN_KEYS if key in entry]
    expect(not granted,
           f"{label}: no blanket MCP permission and no attachment to a running browser may be "
           f"granted by default; found {granted}")


def managed_shape_of_root(root: pathlib.Path, label: str) -> None:
    """The managed shape a deployment in `root` writes — derived from its COMMITTED asset alone.

    `.kimi-code/mcp.json` is machine-local: the managed entry carries the absolute entry path of the
    vendored package of THIS installation, and both deployers gitignore it, so a fresh clone only
    has the committed asset. The check therefore works from the template and never from gitignored
    machine state (F13).
    """
    assert_managed_shape(merged_entry_of_asset(root / MCP_ASSET_REL, root),
                         f"{label}: a merge of the committed {MCP_ASSET_REL}")


def mcp_asset_deploys_into_the_managed_shape() -> None:
    """The committed asset of this repository, once merged, IS a managed configuration."""
    managed_shape_of_root(REPO, "the factory repository")


def mcp_shape_check_needs_no_local_config() -> None:
    """F13: the configuration check must pass where `.kimi-code/mcp.json` does NOT exist.

    A fresh clone carries the committed asset and no managed config — that file is per installation
    and gitignored, so it can never be part of a clone. Requiring it made this suite fail there
    (reproduced as 80 PASS / 1 FAIL). The fixture below is exactly that state; the real local file
    is neither read nor deleted nor required.
    """
    with tempfile.TemporaryDirectory(prefix="cf clean clone ") as tmp:
        clone = pathlib.Path(tmp) / "clean-clone"
        (clone / MCP_ASSET_REL).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / MCP_ASSET_REL, clone / MCP_ASSET_REL)
        expect(not (clone / MCP_REL).exists(),
               f"the fixture must model a fresh clone: it must not carry {MCP_REL}")
        managed_shape_of_root(clone, "a fresh clone")


def mcp_safety_switches_are_load_bearing() -> None:
    """F14 mutation proof: dropping a safety switch from a COPY of the asset must fail the check.

    Every required flag, every required environment switch and every forbidden permission/attach key
    is removed from (or added to) a copy of the committed asset; the merge of that copy must be
    REJECTED by `assert_managed_shape`, the same assertion a real deployment goes through. An
    assertion that took its expectation out of the asset would stay green on every one of these
    mutations — that is the defect this case is the vaccine against.
    """
    clean = assertion_error(lambda: managed_shape_of_root(REPO, "the unmutated asset"))
    expect(clean is None, f"the unmutated control must PASS the managed-shape check; got: {clean}")

    def drop_flag(flag: str) -> Callable[[dict], None]:
        def mutate(entry: dict) -> None:
            entry["args"] = [arg for arg in entry.get("args", []) if arg != flag]
        return mutate

    def drop_env(name: str) -> Callable[[dict], None]:
        def mutate(entry: dict) -> None:
            entry.get("env", {}).pop(name, None)
        return mutate

    def add_forbidden(key: str) -> Callable[[dict], None]:
        def mutate(entry: dict) -> None:
            entry[key] = True
        return mutate

    mutations = ([(f"the required flag {flag!r} was removed", drop_flag(flag))
                  for flag in MCP_REQUIRED_FLAGS]
                 + [(f"the required environment switch {name!r} was removed", drop_env(name))
                    for name in sorted(MCP_SAFETY_ENV)]
                 + [(f"the forbidden key {key!r} was added", add_forbidden(key))
                    for key in MCP_FORBIDDEN_KEYS])
    asset_text = read_text(REPO / MCP_ASSET_REL)
    for label, mutate in mutations:
        data = json.loads(asset_text)
        mutate(data["mcpServers"][MCP_SERVER])
        with tempfile.TemporaryDirectory(prefix="cf mutated asset ") as tmp:
            mutated = pathlib.Path(tmp) / "mutated.mcp.json"
            mutated.write_text(json.dumps(data, indent=2), encoding="utf-8")
            derived = merged_entry_of_asset(mutated, pathlib.Path(tmp))
            failure = assertion_error(lambda: assert_managed_shape(derived, "a mutated asset"))
        expect(failure is not None,
               f"the managed-shape check passed although {label} in a copy of {MCP_ASSET_REL}: the "
               f"expectation must come from the independent constants {MCP_REQUIRED_FLAGS} / "
               f"{MCP_SAFETY_ENV} / {MCP_FORBIDDEN_KEYS}, never from the asset under test")


# --- end-to-end deployment (Windows only) -----------------------------------------------------


def sha256_or_none(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_bytes_or_none(path: pathlib.Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def tail(text: str | None, limit: int = 1200) -> str:
    body = (text or "").strip()
    if not body:
        return "(no output)"
    return body if len(body) <= limit else "(truncated) ...\n" + body[-limit:]


def find_cmd_exe() -> str | None:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "cmd.exe"
    if native.is_file():
        return str(native)
    return shutil.which("cmd.exe") or shutil.which("cmd")


def find_powershell() -> str | None:
    found = shutil.which("powershell.exe") or shutil.which("powershell")
    if found:
        return found
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(native) if native.is_file() else None


def remove_tree(path: pathlib.Path) -> None:
    """Best-effort removal of the temp deployment (git can leave read-only objects behind)."""
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
    if path.exists():
        print(f"WARNING - could not remove the temporary deployment directory {path}")


def deploy(cmd_exe: str, target: pathlib.Path, timeout: int = 180,
           env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """`cmd.exe /c prepare_factory.cmd <target>` - what a double-click does, minus stdin.

    `cmd.exe` has no absolute cmd.exe path in the command line: the script is named relatively
    (the process runs in the repo root), because cmd.exe strips the quotes around a quoted first
    token and would then fail if the factory path itself contained a space. The spaced TARGET is
    still passed as its own list element, so subprocess quotes it for us - that is the quoting
    the deployer has to survive. `env` is handed to the child only (the no-python case shadows
    PATH there, never in this test process).
    """
    return subprocess.run(
        [cmd_exe, "/c", CMD_NAME, str(target)],   # a LIST: subprocess quotes the spaced target
        cwd=str(REPO),                            # the deployer is run from the factory repo root
        stdin=subprocess.DEVNULL,                 # must never wait for a keypress
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def text_or_none(path: pathlib.Path) -> str | None:
    data = read_bytes_or_none(path)
    return None if data is None else data.decode("utf-8-sig", "replace")


def load_json_or_none(path: pathlib.Path) -> object | None:
    """The parsed JSON of a file, or `None` when it is missing, undecodable or invalid."""
    data = read_bytes_or_none(path)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def collect_deployment_facts(cmd_exe: str, target: pathlib.Path,
                             env: dict | None = None) -> dict:
    """Deploy twice into `target` and return plain values only (nothing left open for cleanup)."""
    facts: dict = {"target": str(target)}
    mcp = target / MCP_REL
    facts["mcp_seed_bytes"] = read_bytes_or_none(mcp)      # the fixture BEFORE the first run
    facts["vendor_entry"] = target / pathlib.Path(*MCP_ENTRY_REL.split("/"))
    started = time.monotonic()
    first = deploy(cmd_exe, target, env=env)
    facts["run1_rc"] = first.returncode
    facts["run1_output"] = (first.stdout or "") + (first.stderr or "")
    facts["created"] = {rel: (target / rel).exists() for rel in CREATED_RELS}
    facts["vendor_created"] = (target / MCP_VENDOR_REL).exists()
    facts["vendor_entry_present"] = (target / pathlib.Path(*MCP_ENTRY_REL.split("/"))).is_file()
    gitignore = target / ".gitignore"
    facts["gitignore_text"] = (gitignore.read_text(encoding="utf-8", errors="replace")
                               if gitignore.is_file() else "")
    facts["start_cmd_bytes"] = read_bytes_or_none(target / "start.cmd")
    facts["start_sh_bytes"] = read_bytes_or_none(target / "start.sh")
    facts["hashes_run1"] = {rel: sha256_or_none(target / rel) for rel in MEMORY_RELS}
    facts["mcp_bytes_run1"] = read_bytes_or_none(mcp)
    facts["mcp_text_run1"] = text_or_none(mcp)
    facts["mcp_json_run1"] = load_json_or_none(mcp)
    second = deploy(cmd_exe, target, env=env)
    facts["run2_rc"] = second.returncode
    facts["run2_output"] = (second.stdout or "") + (second.stderr or "")
    facts["hashes_run2"] = {rel: sha256_or_none(target / rel) for rel in MEMORY_RELS}
    facts["mcp_bytes_run2"] = read_bytes_or_none(mcp)
    facts["seconds"] = time.monotonic() - started
    return facts


# --- MCP fixtures: "deployment into a project with existing MCP settings" ----------------------

EXISTING_MCP_SETTINGS_SEED = """{
  "mcpServers": {
    "unrelated-server": {
      "type": "stdio",
      "command": "node",
      "args": ["keep-me.js"],
      "env": {
        "KEEP": "1"
      }
    }
  },
  "userSetting": {
    "theme": "dark",
    "nested": {
      "deep": [1, 2, 3]
    }
  }
}
"""
# Fragments of the fixture above that must still be there afterwards: they prove the user's block
# survived as TEXT (a re-serialized file can be semantically equal and still not be identical).
MCP_SEED_RAW_FRAGMENTS = ('"KEEP": "1"', '"args": ["keep-me.js"]', '"theme": "dark"')

CONFLICTING_MCP_SEED = """{
  "mcpServers": {
    "unrelated-server": {
      "type": "stdio",
      "command": "node"
    },
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@0.0.1-user-pinned"]
    }
  }
}
"""


def write_mcp_seed(target: pathlib.Path, text: str) -> None:
    path = target / MCP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


MCP_SEEDS = {
    "settings": lambda target: write_mcp_seed(target, EXISTING_MCP_SETTINGS_SEED),
    "conflict": lambda target: write_mcp_seed(target, CONFLICTING_MCP_SEED),
    "vendor_blocked": lambda target: write_blocked_vendor(target),
}


def write_blocked_vendor(target: pathlib.Path) -> None:
    """Make the vendored install impossible: a FILE where its directory must be created.

    The deployment must survive this: the install step reports the reason, the merge is skipped and
    nothing broken is written — a config whose launch file does not exist would be worse than none.
    """
    vendor = target / MCP_VENDOR_REL
    vendor.parent.mkdir(parents=True, exist_ok=True)
    vendor.write_bytes(b"not a directory\n")

# The deployers PROBE an interpreter (`-c pass`) before they use it, so a stub that ALWAYS fails is
# a faithful "machine without python": the steps must degrade, never fail and never clobber.
PY_PROBE_STUBS = ("python.cmd", "python3.cmd", "py.cmd")
PY_STUB_TEXT = "@rem Written by the Windows deployer test: a python that never works.\r\n@exit /b 1\r\n"


def make_python_shadow_dir() -> pathlib.Path:
    """A PATH-shadowing directory whose python/python3/py all fail (the no-python fixture)."""
    shadow = pathlib.Path(tempfile.mkdtemp(prefix="cf no-python shadow "))
    for name in PY_PROBE_STUBS:
        (shadow / name).write_bytes(PY_STUB_TEXT.encode("utf-8"))
    return shadow


def shadowed_env(shadow: pathlib.Path) -> dict:
    """A copy of this process' environment with the stub directory FIRST on PATH."""
    env = dict(os.environ)
    env["PATH"] = str(shadow) + os.pathsep + env.get("PATH", "")
    return env


def deploy_env(shadow: pathlib.Path | None = None) -> dict:
    """The environment of a fixture deployment: offline vendor install, optional python stubs.

    `CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1` is the documented seam of `vendor-install`: it writes a
    placeholder entry instead of calling npm, so a fixture run never reaches the network or a real
    package registry (and never takes a minute doing it).
    """
    env = shadowed_env(shadow) if shadow is not None else dict(os.environ)
    env[MCP_VENDOR_OFFLINE_ENV] = "1"
    return env


# --- what each MCP case must prove -------------------------------------------------------------


def same_path(left: str, right: str) -> bool:
    """Path equality that survives 8.3 short names, a case-insensitive filesystem and symlinks."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def expected_mcp_entry_path(target: pathlib.Path) -> pathlib.Path:
    """The absolute vendored entry path a deployment into `target` must launch (deployment layout)."""
    return target / pathlib.Path(*MCP_ENTRY_REL.split("/"))


def mcp_assert_managed(facts: dict) -> None:
    """The managed server is there - and everything the user already had is still there.

    Core of the business scenario "deployment into a project with existing MCP settings": an
    unrelated server and the user's own settings survive byte-for-byte while the managed
    `chrome-devtools` entry - `node` plus the ABSOLUTE vendored entry of THIS project - is added.
    The safety expectations are the INDEPENDENT constants of this test, not values read back out of
    the asset that was deployed (F14): the same assertion is proven load-bearing by
    `mcp_safety_switches_are_load_bearing`.
    """
    data = facts["mcp_json_run1"]
    expect(isinstance(data, dict),
           f"the deployment must leave a valid {MCP_REL} behind; got {facts['mcp_bytes_run1']!r}")
    servers = data.get("mcpServers")
    expect(isinstance(servers, dict), f"{MCP_REL} must keep its mcpServers map")
    entry = servers.get(MCP_SERVER)
    expect(isinstance(entry, dict),
           f"the managed {MCP_SERVER!r} server must be added; got {entry!r}")
    assert_managed_shape(entry, f"the deployed {MCP_REL}")
    expected_entry = expected_mcp_entry_path(pathlib.Path(facts["target"]))
    expect(same_path(str(entry["args"][0]), str(expected_entry)),
           f"args[0] must be the VENDORED entry of THIS project ({str(expected_entry)!r}); "
           f"got {entry['args'][0]!r}")
    vendored = facts["vendor_entry"]
    expect(facts["vendor_entry_present"],
           f"the vendored package must be installed next to the config: {vendored} is missing — "
           "the managed entry would point at a file that does not exist")
    seed = facts["mcp_seed_bytes"]
    if seed is None:
        return                          # a fresh project: there it is only about the managed entry
    before = json.loads(seed.decode("utf-8"))
    for name, existing in before.get("mcpServers", {}).items():
        expect(servers.get(name) == existing,
               f"the existing server {name!r} must survive the merge unchanged, got "
               f"{servers.get(name)!r}")
    for key, value in before.items():
        if key != "mcpServers":
            expect(data.get(key) == value,
                   f"the existing top-level setting {key!r} must survive the merge unchanged")
    text = facts["mcp_text_run1"] or ""
    missing = [fragment for fragment in MCP_SEED_RAW_FRAGMENTS if fragment not in text]
    expect(not missing,
           f"the existing {MCP_REL} must survive byte-for-byte (missing {missing}): the merge "
           "inserts the managed entry, it never re-serializes the user's file")


def mcp_assert_conflict(facts: dict) -> None:
    """A DIFFERENT pre-existing `chrome-devtools` entry: preserved byte-for-byte and REPORTED."""
    seed = facts["mcp_seed_bytes"]
    expect(seed is not None, f"this case starts from an existing {MCP_REL}")
    expect(facts["run1_rc"] == 0,
           f"a preserved conflict is a report, not a deployment failure (exit code "
           f"{facts['run1_rc']})")
    expect(facts["mcp_bytes_run1"] == seed,
           f"a conflicting {MCP_SERVER!r} entry must be preserved byte-for-byte, never replaced; got\n"
           + tail((facts["mcp_bytes_run1"] or b"").decode("utf-8", "replace")))
    output = facts["run1_output"]
    expect(MCP_CONFLICT_MARKER in output,
           f"the deployment must REPORT the conflict ({MCP_CONFLICT_MARKER!r}); output tail:\n"
           + tail(output))
    expect("preserved" in output and "nothing was overwritten" in output,
           "the report must say that the existing entry is preserved and nothing was overwritten; "
           f"output tail:\n{tail(output)}")
    match = MCP_READINESS_STATE.search(output)
    expect(match is not None and match.group("state").startswith("CONFLICT"),
           f"the readiness report must show {MCP_REL} as CONFLICT; output tail:\n{tail(output)}")
    expect(MCP_NEW_SESSION_MARKER in output and MCP_STATUS_TOKEN in output,
           "the report must document that the configuration takes effect in a NEW Kimi session "
           f"and that /mcp shows the connection status; output tail:\n{tail(output)}")


def mcp_assert_untouched_without_python(facts: dict) -> None:
    """No working Python: an existing mcp.json is left untouched and the skip is reported."""
    seed = facts["mcp_seed_bytes"]
    expect(seed is not None, f"this case starts from an existing {MCP_REL}")
    expect(facts["mcp_bytes_run1"] == seed,
           f"without python the existing {MCP_REL} must stay byte-for-byte as it was (a deployment "
           "may never clobber a user's own MCP servers); got\n"
           + tail((facts["mcp_bytes_run1"] or b"").decode("utf-8", "replace")))
    output = facts["run1_output"]
    expect(MCP_SKIP_RUNTIME in output,
           f"the deployment must report the skipped merge ({MCP_SKIP_RUNTIME!r}); output tail:\n"
           + tail(output))
    expect(MCP_LEFT_UNTOUCHED in output,
           f"the report must say the existing file was {MCP_LEFT_UNTOUCHED}; output tail:\n"
           + tail(output))
    expect(not facts["vendor_created"],
           "without python nothing may be installed into the vendor directory either")
    for misleading in ("MCP config: created", "MCP config: updated"):
        expect(misleading not in output,
               f"the deployment must not claim {misleading!r} although no working python is there; "
               f"output tail:\n{tail(output)}")
    match = MCP_READINESS_STATE.search(output)
    expect(match is not None and match.group("state").startswith("skipped"),
           f"the readiness report must show {MCP_REL} as skipped; output tail:\n{tail(output)}")


def mcp_assert_skipped_without_python(facts: dict) -> None:
    """No working Python and no file yet: NOTHING is created — a template copy would be broken.

    The shipped template carries the entry-path placeholder, so its launch file does not exist: a
    deployment that copied it would hand the user a config that breaks every Kimi session. The step
    must report the skip instead.
    """
    expect(facts["mcp_bytes_run1"] is None,
           f"without python no {MCP_REL} may be created (its managed entry path is per-installation "
           f"and only the helper derives it); got\n"
           + tail((facts["mcp_bytes_run1"] or b"").decode("utf-8", "replace")))
    expect(not facts["vendor_created"], "without python nothing may be installed either")
    output = facts["run1_output"]
    expect(MCP_SKIP_RUNTIME in output,
           f"the deployment must report the skip ({MCP_SKIP_RUNTIME!r}); output tail:\n"
           + tail(output))
    for misleading in ("MCP config: created", "MCP config: updated"):
        expect(misleading not in output,
               f"the deployment must not claim {misleading!r} although no working python is there; "
               f"output tail:\n{tail(output)}")
    match = MCP_READINESS_STATE.search(output)
    expect(match is not None and match.group("state").startswith("skipped"),
           f"the readiness report must show {MCP_REL} as skipped; output tail:\n{tail(output)}")


def mcp_assert_vendor_failure(facts: dict) -> None:
    """The install cannot be done: NOTHING is written, the reason is reported, exit code stays 0.

    The fixture blocks the vendor path with a file, so the helper cannot install (or even place the
    offline placeholder). A deployment must never fail because the browser path could not be
    prepared, and it must never leave a managed entry pointing at a file that does not exist.
    """
    expect(facts["run1_rc"] == 0,
           f"an impossible package install is a REPORTED skip, not a deployment failure (exit code "
           f"{facts['run1_rc']}); output tail:\n{tail(facts['run1_output'])}")
    expect(facts["mcp_bytes_run1"] is None,
           f"no {MCP_REL} may be written when the pinned package could not be installed; got\n"
           + tail((facts["mcp_bytes_run1"] or b"").decode("utf-8", "replace")))
    output = facts["run1_output"]
    expect(MCP_VENDOR_SKIP_MARKER in output,
           f"the deployment must report {MCP_VENDOR_SKIP_MARKER!r}; output tail:\n{tail(output)}")
    expect("Traceback" not in output,
           f"the reason must be a message, never a traceback; output tail:\n{tail(output)}")
    for misleading in ("MCP config: created", "MCP config: updated"):
        expect(misleading not in output,
               f"the deployment must not claim {misleading!r} although nothing was installed; "
               f"output tail:\n{tail(output)}")
    match = MCP_READINESS_STATE.search(output)
    expect(match is not None and match.group("state").startswith("skipped"),
           f"the readiness report must show {MCP_REL} as skipped; output tail:\n{tail(output)}")


MCP_CASE_CHECKS: dict = {
    "fresh": (f"the deployment installs the vendored package and creates {MCP_REL} launching it "
              f"with node", mcp_assert_managed),
    "managed": ("the managed server is merged in (node + the absolute vendored entry) while the "
                "unrelated server and the user settings survive byte-for-byte", mcp_assert_managed),
    "conflict": ("a conflicting pre-existing chrome-devtools entry is preserved byte-for-byte and "
                 "reported (never silently replaced)", mcp_assert_conflict),
    "untouched": (f"without python the existing {MCP_REL} is left untouched and the skip is reported",
                  mcp_assert_untouched_without_python),
    "skip": (f"without python a missing {MCP_REL} is NOT created (nothing broken is written) and the "
             "skip is reported", mcp_assert_skipped_without_python),
    "vendor-failure": (f"an impossible package install writes NO {MCP_REL} while the deployment still "
                       "finishes and reports the reason", mcp_assert_vendor_failure),
}


# Every target path is deployed for REAL, twice. The space proves the argument forwarding quotes the
# target; the non-ASCII name proves the child Python processes run in UTF-8 - in the local code page
# (cp1251) the project name they print back is garbled, or the print fails outright for a character
# outside cp1251. The last four cases are the MCP deployment scenarios: a project with pre-existing
# MCP settings, a conflicting managed entry, and both without a working Python, where a deployment
# must degrade and still never touch (or create) the user's file. The fixtures run the install step
# through the documented OFFLINE seam (`CHROME_DEVTOOLS_MCP_VENDOR_OFFLINE=1`, see the helper's
# `vendor-install`), so no test reaches npm or the network: the seam writes the placeholder entry
# the merge step needs.
DEPLOY_CASES = (
    {"case": "space in the path", "prefix": "cf windows deploy ", "mcp": "fresh"},
    {"case": "non-ASCII in the path", "prefix": "cf déploiement 部署 ", "mcp": "fresh"},
    {"case": "existing MCP settings", "prefix": "cf mcp existing ",
     "seed": "settings", "mcp": "managed"},
    {"case": "conflicting chrome-devtools entry", "prefix": "cf mcp conflict ",
     "seed": "conflict", "mcp": "conflict"},
    {"case": "no python, existing MCP settings", "prefix": "cf mcp no-python ",
     "seed": "settings", "mcp": "untouched", "no_python": True},
    {"case": "no python, no MCP file yet", "prefix": "cf mcp no-python-fresh ",
     "mcp": "skip", "no_python": True},
    {"case": "package install impossible", "prefix": "cf mcp vendor-fail ",
     "seed": "vendor_blocked", "mcp": "vendor-failure", "no_mcp": True},
)


def deploy_case(checker: "Checker", cmd_exe: str, spec: dict) -> None:
    """Deploy twice into a fresh temp dir (seeded for the case) and run the end-to-end checks."""
    case = str(spec["case"])
    has_python = not spec.get("no_python")
    expect_mcp = not spec.get("no_mcp")
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix=str(spec["prefix"])))
    shadow: pathlib.Path | None = None
    facts: dict = {"target": str(temp_root), "has_python": has_python}
    try:
        seed = MCP_SEEDS.get(str(spec.get("seed", "")))
        if seed is not None:
            seed(temp_root)
        if not has_python:
            shadow = make_python_shadow_dir()
        facts = {**facts, **collect_deployment_facts(
            cmd_exe, temp_root, env=deploy_env(shadow))}
    except Exception as exc:                     # timeout, missing binary, permission, ...
        facts["error"] = exc
    finally:
        remove_tree(temp_root)                   # never leave temp dirs behind, not even on failure
        if shadow is not None:
            remove_tree(shadow)

    if "error" in facts:
        print(f"INFO - end-to-end deployment never completed: {facts['error']!r}")
    else:
        print(f"INFO - end-to-end deployment [{case}]: prepare_factory.cmd ran twice in "
              f"{facts['seconds']:.1f}s against {facts['target']!r}")

    def fact(key: str):
        if "error" in facts:
            raise AssertionError(f"the deployment run never completed: {facts['error']!r}")
        return facts[key]

    def check(label: str, run: Callable[[], object]) -> None:
        checker.check(f"end-to-end [{case}]: {label}", run)

    check("'cmd.exe /c prepare_factory.cmd <target>' (stdin closed) exits 0",
          lambda: expect(fact("run1_rc") == 0,
                         f"exit code {fact('run1_rc')}, expected 0 (a 'pause' would have hung until "
                         f"the timeout); output tail:\n{tail(facts.get('run1_output'))}"))

    def artifacts() -> None:
        created = fact("created")
        # Without python the memory files AND the MCP config are the legitimate gaps, and a case
        # whose package install was impossible has no MCP config either: the deployer says what it
        # could not do instead of writing something broken.
        expected = [rel for rel in CREATED_RELS
                    if (has_python or rel not in (*MEMORY_RELS, MCP_REL))
                    and (expect_mcp or rel != MCP_REL)]
        for rel in expected:
            expect(created.get(rel), f"the deployment must create {rel}")
        text = fact("gitignore_text")
        absent = [pattern for pattern in GITIGNORE_PATTERNS if pattern not in text]
        expect(not absent,
               f".gitignore must contain all {len(GITIGNORE_PATTERNS)} factory patterns "
               f"(missing {absent}); got:\n{tail(text)}")

    check(f"the deployed project has SKILL.md, .gitignore ({len(GITIGNORE_PATTERNS)} patterns), "
          ".git/, start.cmd, start.sh"
          + (", .kimi-code/mcp.json" if expect_mcp else " (no MCP config: nothing was installed)")
          + (", memory/" if has_python else
             " (no python: no memory, no MCP config — only what the deployer reported)"), artifacts)

    def generated_start_cmd() -> None:
        data = fact("start_cmd_bytes")
        expect(data is not None, "the deployment must create start.cmd")
        reference = START_CMD.read_bytes()
        expect(data == reference,
               f"the generated start.cmd must be byte-identical to {START_CMD_NAME}: "
               f"{len(data)} bytes vs {len(reference)} bytes, "
               f"first difference at {next((i for i, (a, b) in enumerate(zip(data, reference)) if a != b), 'n/a')}; "
               f"generated head {data[:40]!r} vs reference head {reference[:40]!r}")

    check("the generated start.cmd is byte-identical to repo/start.cmd", generated_start_cmd)

    def generated_start_sh() -> None:
        data = fact("start_sh_bytes")
        expect(data is not None, "the deployment must create start.sh")
        expect(b"\r" not in data,
               f"the generated start.sh must use LF only, but contains "
               f"{data.count(bytes([13]))} CR byte(s)")
        expect(data.startswith(b"#!/usr/bin/env bash"),
               f"the generated start.sh must start with the bash shebang, got {data[:26]!r}")
        expect(f"export {LAUNCH_DIR_VAR}=".encode() in data,
               f"the generated start.sh must export {LAUNCH_DIR_VAR} (the launch directory the "
               f"instruction layer resolves the task's repo_path against); got:\n"
               + data.decode("utf-8", "replace"))

    check("the generated start.sh is LF-only, starts with the bash shebang and exports the "
          "launch directory", generated_start_sh)

    def idempotent() -> None:
        expect(fact("run2_rc") == 0,
               f"the second run must exit 0, got {fact('run2_rc')}; output tail:\n"
               f"{tail(facts.get('run2_output'))}")
        before, after = fact("hashes_run1"), fact("hashes_run2")
        for rel in MEMORY_RELS:
            if not has_python:
                expect(before[rel] is None and after[rel] is None,
                       f"{rel} must not exist without python - the deployment reports what it could "
                       "not do instead of pretending")
                continue
            expect(before[rel] is not None, f"{rel} must exist after the first run")
            expect(before[rel] == after[rel],
                   f"the second run rewrote {rel} (SHA256 {before[rel]} -> {after[rel]}); "
                   "existing project memory must never be overwritten")

    check("the second run exits 0 and both memory files keep their SHA256 (idempotent)"
          if has_python else
          "the second run exits 0 and without python no project memory is claimed", idempotent)

    def mcp_idempotent() -> None:
        first, second = fact("mcp_bytes_run1"), fact("mcp_bytes_run2")
        if not expect_mcp:
            expect(first is None and second is None,
                   f"this case installs nothing, so no {MCP_REL} may exist — not even after the "
                   "second run")
            return
        if not has_python and fact("mcp_seed_bytes") is None:
            expect(first is None and second is None,
                   f"without python no {MCP_REL} may be created — not even by the second run")
            return
        expect(first is not None, f"the deployment must leave {MCP_REL} in place")
        expect(second == first,
               f"the second run rewrote {MCP_REL} ({len(first)} -> {len(second)} bytes): the merge "
               "is idempotent, so a re-run must leave the managed file exactly as it was")

    check(f"the second run leaves {MCP_REL} byte-identical (no diff)", mcp_idempotent)

    def memory_name_reported() -> None:
        """The deployer must read Python's output back as UTF-8, not as mojibake.

        With a target path the child Python cannot encode, the deployer reports a failure the
        moment the memory is fine - so the readiness line, the project name and the absence of
        failure markers are all pinned here.
        """
        output = fact("run1_output")
        expect("failed to create" not in output,
               "the memory step reported a failure although Python is available (a child Python "
               "that cannot encode the project name looks exactly like this); output tail:\n"
               f"{tail(output)}")
        expect("MISSING" not in output,
               f"the deployment reported a missing artifact; output tail:\n{tail(output)}")
        match = re.search(r"•\s*memory/:\s+created ✓ \(project (.+)\)", output)
        expect(match is not None,
               "the readiness report must show the memory as 'created ✓ (project <name>)'; "
               f"output tail:\n{tail(output)}")
        expect(match.group(1) == temp_root.name,
               f"the project name Python reported back must be {temp_root.name!r}, got "
               f"{match.group(1)!r}: the child Python did not write UTF-8 (PYTHONUTF8), so its "
               "output was decoded as mojibake")

    def memory_unverified_without_python() -> None:
        """No interpreter: the deployment completes and says what it could not do (no false OK)."""
        output = fact("run1_output")
        expect("MISSING" not in output,
               f"the deployment reported a missing artifact; output tail:\n{tail(output)}")
        expect(MCP_NO_PYTHON in output,
               f"the report must name the missing interpreter ({MCP_NO_PYTHON!r}); output tail:\n"
               + tail(output))
        expect("not verified (no python)" in output,
               "the readiness report must show the memory as 'not verified (no python)'")

    if has_python:
        check("the memory step is reported as created and Python's project name survives as UTF-8",
              memory_name_reported)
    else:
        check("without python the deployment still finishes and reports the memory as unverified",
              memory_unverified_without_python)

    mcp_kind = str(spec.get("mcp", "fresh"))
    mcp_label, mcp_check = MCP_CASE_CHECKS[mcp_kind]
    check(mcp_label, lambda: mcp_check(facts))


# --- behavioural proof of the two console/lifecycle contracts (Windows only) ---------------------
# The checks above pin the deployer's TEXT; these deploy for real, because both defects are about
# what the user actually sees on the console and what survives on disk.

# A launcher the user wrote by hand before running prepare_factory — it must survive as start.sh.bak.
USER_START_SH = (b"#!/usr/bin/env bash\n"
                 b"# My own launcher, written before Code Factory was prepared.\n"
                 b"exec my-own-tool \"$@\"\n")

# A memory that belongs to ANOTHER project and carries one legacy (pre-v2) record: `check` then
# prints four WARN lines plus the verdict, which is the flood of warnings.md.
MEM_FOREIGN_PROJECT = "another-install"
MEM_LEGACY_RECORD = """
## 2020-01-01T00:00:00+0000 — legacy record of another install

title: legacy record
timestamp: 2020-01-01T00:00:00+0000
branch: main
commit: 0000000
task_type: implement
goal: legacy entry kept verbatim
changed_files: none
created_files: none
results: integration=pass regression=pass business=pass review=pass
decisions: legacy decision (pre-v2 format)
assumptions: none
models_used: unknown
unfinished: none
factory_version: 12.0.0
status: ok
"""

NETWORK_PROBES = (("1.1.1.1", 53), ("8.8.8.8", 53), ("registry.npmjs.org", 443))


def network_available(timeout: float = 3.0) -> bool:
    """True when a TCP connection to a public host succeeds.

    A REAL deployment installs the pinned MCP package with npm, so it needs the network; where
    there is none the behavioural case below SKIPs with that reason instead of failing.
    """
    for host, port in NETWORK_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def deploy_into(seed: Callable[[pathlib.Path], None], prefix: str, cmd_exe: str,
                env: dict | None, runs: int = 1, timeout: int = 300) -> dict:
    """Deploy into a fresh, seeded temp dir and keep plain values only (nothing left open).

    The temp tree is removed BEFORE any assertion runs, so the checks below work on captured bytes:
    a failure report can never leak a path that no longer exists.
    """
    root = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    facts: dict = {}
    try:
        seed(root)
        facts["seed_start_sh"] = read_bytes_or_none(root / "start.sh")
        started = time.monotonic()
        first = deploy(cmd_exe, root, timeout=timeout, env=env)
        facts["seconds"] = time.monotonic() - started
        facts["rc"] = first.returncode
        facts["output"] = (first.stdout or "") + (first.stderr or "")
        facts["start_sh"] = read_bytes_or_none(root / "start.sh")
        facts["start_sh_bak"] = read_bytes_or_none(root / "start.sh.bak")
        if runs > 1:
            second = deploy(cmd_exe, root, timeout=timeout, env=env)
            facts["rc2"] = second.returncode
            facts["output2"] = (second.stdout or "") + (second.stderr or "")
            facts["start_sh2"] = read_bytes_or_none(root / "start.sh")
            facts["start_sh_bak2"] = read_bytes_or_none(root / "start.sh.bak")
    except Exception as exc:                     # timeout, missing binary, permission, ...
        facts["error"] = exc
    finally:
        remove_tree(root)
    return facts


def completed(facts: dict) -> None:
    """Fail the check when the deployment itself never ran (a check may not pass on nothing)."""
    if "error" in facts:
        raise AssertionError(f"the deployment run never completed: {facts['error']!r}")


def seed_foreign_memory(root: pathlib.Path) -> None:
    """A `memory/` of ANOTHER project with one legacy record, created the documented way.

    `init --project <other>` writes the declaration area (and, because the fixture has a root
    commit, its `project_id`), so `check` reports the identity basis, the verdict `ok - ...` and one
    WARN block per legacy invariant the record does not satisfy.
    """
    helper = REPO / ".agents/skills/code-factory/scripts/memory_project.py"
    expect(helper.is_file(), f"{helper} must exist")

    def git(*args: str) -> None:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=120)
        expect(proc.returncode == 0,
               f"fixture git {' '.join(args)} failed: {(proc.stderr or '').strip()}")

    git("init", "-b", "main")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git("add", "seed.txt")
    git("-c", "user.email=deployer-test@example.com", "-c", "user.name=deployer-test",
        "commit", "-m", "seed")
    init = subprocess.run([sys.executable, str(helper), "init", "--repo", str(root),
                           "--project", MEM_FOREIGN_PROJECT],
                          capture_output=True, text=True, timeout=120)
    expect(init.returncode == 0,
           f"fixture memory init failed: {(init.stderr or '').strip()}")
    journal = root / "memory" / "change-log.md"
    journal.write_text(journal.read_text(encoding="utf-8") + MEM_LEGACY_RECORD, encoding="utf-8")


def memory_check_line_behaviour(checker: "Checker", cmd_exe: str) -> None:
    """A real deployment whose memory floods `check` with WARN lines: the CHECK line stays ONE line.

    The fixture's memory belongs to another project and holds a legacy record, so `check` prints its
    WARN block plus the verdict - exactly the state captured in warnings.md. Before the fix the whole
    blob was interpolated into the warning AND the readiness line (~50 wrapped lines).
    """
    label = ("end-to-end [memory]: the CHECK line stays ONE line (verdict + a warnings count, not "
             "the whole check output)")
    facts = deploy_into(seed_foreign_memory, "cf memory flood ", cmd_exe, deploy_env(), runs=1)

    def one_line() -> None:
        completed(facts)
        output = facts["output"]
        expect(facts["rc"] == 0,
               f"a memory of another project is a WARNING, not a deployment failure (exit code "
               f"{facts['rc']}); output tail:\n{tail(output)}")
        check_lines = [line for line in output.splitlines() if MEM_CHECK_MARKER in line]
        expect(check_lines,
               f"the deployment must report {MEM_CHECK_MARKER!r}; output tail:\n{tail(output)}")
        readiness = [line for line in output.splitlines() if MEM_READINESS_LABEL in line]
        expect(len(readiness) == 1,
               f"the readiness report must carry exactly one {MEM_READINESS_LABEL!r} line, "
               f"got {readiness}")
        for line in check_lines + readiness:
            expect(MEM_WARNINGS_HINT in line,
                   f"the CHECK line must name the verdict and a warnings count "
                   f"({MEM_WARNINGS_HINT!r}); got {line!r}")
            expect("WARN - " not in line,
                   f"the CHECK line must not carry the check output itself; got {line!r}")
        # The actual single-line proof: the line AFTER the memory bullet is already the next bullet.
        lines = output.splitlines()
        index = lines.index(readiness[0])
        following = lines[index + 1] if index + 1 < len(lines) else ""
        expect(following.lstrip().startswith("• "),
               "the memory/ readiness line must be ONE line - the whole `check` output was appended "
               f"to it; the next line is {following!r}")
        expect("WARN - entry" not in output,
               "the raw WARN lines of `memory_project.py check` leaked into the console report; "
               f"output tail:\n{tail(output)}")

    checker.check(label, one_line)


def start_sh_backup_failure_behaviour(checker: "Checker", cmd_exe: str) -> None:
    """A backup that cannot be created is a HARD error and the original launcher survives.

    A DIRECTORY named `start.sh.bak` makes `[System.IO.File]::Copy` throw, which is the one way to
    reach the failure branch on a healthy machine. The deployer must then exit 1 (an incomplete
    deployment, no "Done" banner) and must NOT have replaced the user's start.sh.
    """
    label = ("end-to-end [start.sh guard]: an impossible start.sh.bak aborts the overwrite with a "
             "hard error and the user's launcher survives")

    def seed(root: pathlib.Path) -> None:
        (root / "start.sh").write_bytes(USER_START_SH)
        (root / "start.sh.bak").mkdir()      # a directory: the backup copy cannot be written

    facts = deploy_into(seed, "cf start sh backup blocked ", cmd_exe, deploy_env(), runs=1)

    def aborted() -> None:
        completed(facts)
        output = facts["output"]
        expect(facts["start_sh"] == USER_START_SH,
               "the user's original start.sh must be left untouched when it could not be backed up "
               f"- it was overwritten by {facts['start_sh']!r}")
        expect(facts["rc"] == 1,
               f"a failed backup is a HARD deployment error (exit 1), got {facts['rc']}; output "
               f"tail:\n{tail(output)}")
        expect(PS1_SH_BACKUP_ABORT in output,
               f"the deployment must report the failed backup ({PS1_SH_BACKUP_ABORT!r}); output "
               f"tail:\n{tail(output)}")
        expect(PS1_HARD_ERROR_BANNER in output,
               f"the run must end with the hard-error banner ({PS1_HARD_ERROR_BANNER!r}), not with "
               f"a cheerful Done; output tail:\n{tail(output)}")

    checker.check(label, aborted)


def start_sh_guard_behaviour(checker: "Checker", cmd_exe: str) -> None:
    """A REAL deployment keeps the user's hand-written launcher — where the network is available.

    The static guard check and the pre-fix probe above only read text; this one runs the actual
    deployer against a project that already has a `start.sh`, which is the file the promise "the
    user's original launcher is preserved" is about. A real deployment installs the pinned MCP
    package with npm, so the case is gated: offline it SKIPs with the reason instead of failing.
    """
    label = ("end-to-end [start.sh guard]: a pre-existing launcher is announced, kept as "
             "start.sh.bak and only then replaced")
    if not network_available():
        checker.skip(label, "no network access (the real deployment installs the pinned MCP package "
                            "with npm) - this behavioural check runs where the network is available")
        return
    facts = deploy_into(lambda root: (root / "start.sh").write_bytes(USER_START_SH),
                        "cf start sh guard ", cmd_exe, None, runs=2)

    def backed_up() -> None:
        completed(facts)
        output = facts["output"]
        expect(facts["rc"] == 0,
               f"the deployment must finish (exit code {facts['rc']}); output tail:\n{tail(output)}")
        expect(facts["start_sh_bak"] == USER_START_SH,
               "the user's original start.sh must be preserved byte-for-byte as start.sh.bak; got\n"
               + tail((facts["start_sh_bak"] or b"").decode("utf-8", "replace")))
        expect(SH_DIFFERS_MARKER in output,
               f"the replacement must be announced ({SH_DIFFERS_MARKER!r}), never silent; output "
               f"tail:\n{tail(output)}")
        expect(facts["start_sh"] is not None
               and facts["start_sh"].startswith(b"#!/usr/bin/env bash")
               and facts["start_sh"] != USER_START_SH,
               "the launcher must be replaced by the factory template (bash shebang), got\n"
               + tail((facts["start_sh"] or b"").decode("utf-8", "replace")))

    checker.check(label, backed_up)

    def one_backup_only() -> None:
        completed(facts)
        expect(facts.get("rc2") == 0,
               f"the second run must exit 0, got {facts.get('rc2')}; output tail:\n"
               f"{tail(facts.get('output2'))}")
        expect(facts["start_sh2"] == facts["start_sh"],
               "the second run must leave the launcher as it is (it already equals the template)")
        expect(facts["start_sh_bak2"] == facts["start_sh_bak"],
               "the second run must not chain a new backup: start.sh.bak is one backup, not a "
               "growing chain")

    checker.check("end-to-end [start.sh guard]: a re-run reuses the single start.sh.bak "
                  "(no backup chain)", one_backup_only)


def end_to_end(checker: "Checker") -> None:
    label = "end-to-end deployment (Windows only: cmd.exe + PowerShell + git)"
    if os.name != "nt":
        checker.skip(label, f"os.name={os.name!r} - the .cmd/.ps1 deployer only runs on Windows")
        checker.skip("behavioural checks of the start.sh guard and the memory CHECK line",
                     "os.name is not 'nt' - they deploy for real through cmd.exe + PowerShell")
        return
    cmd_exe = find_cmd_exe()
    missing = [name for name, found in (("cmd.exe", cmd_exe),
                                        ("powershell.exe", find_powershell()),
                                        ("git", shutil.which("git"))) if not found]
    if missing:
        checker.skip(label, "not available on this machine: " + ", ".join(missing))
        return

    for spec in DEPLOY_CASES:
        deploy_case(checker, cmd_exe, spec)

    # The two contracts that are about the CONSOLE and about what survives on disk, proven for real.
    memory_check_line_behaviour(checker, cmd_exe)
    start_sh_backup_failure_behaviour(checker, cmd_exe)
    start_sh_guard_behaviour(checker, cmd_exe)


# --- runner -----------------------------------------------------------------------------------


class Checker:
    """One PASS/FAIL/SKIP line per logical check; a failure never aborts the remaining checks."""

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []

    def check(self, label: str, run: Callable[[], object]) -> None:
        try:
            run()
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
            print(f"FAIL - Windows launcher scripts: {len(self.failed)} check(s) failed.")
            return 1
        print("PASS - Windows launcher scripts behave as expected (encoding, .cmd/.ps1 contracts, "
              "CRLF pinned in .gitattributes, no drift in the inline start.cmd/start.sh templates, "
              "task.yaml/launcher patterns ignored, the machine-local .kimi-code/mcp.json ignored by "
              "both deployers, launch directory exported, real deployment "
              "idempotent, the pinned chrome-devtools-mcp installed into the per-installation vendor "
              "directory before the managed MCP entry is merged, existing settings preserved and "
              "the step degrading safely (and writing nothing broken) without python or package "
              "install, the merged shape of the committed asset checked against constants "
              "independent of it and mutation-proven, without any machine-local config; a pre-existing "
              "start.sh kept as start.sh.bak before it is replaced and the overwrite ABORTED with a "
              "hard error when that backup cannot be created (proven against the pre-fix base commit "
              "and by a real deployment); the memory CHECK line reduced to the verdict plus a WARN "
              "count and proven to stay ONE line).")
        return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so non-ASCII text survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251), which would replace the
    deployer's non-ASCII messages in failure reports with question marks - the .ps1 itself does
    the same thing for the same reason.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    checker = Checker()

    if FOUND_REPO is None:
        # A project deployed by the factory holds .agents/ + the generated launchers, never the
        # deployer itself: nothing to pin here, so this is a SKIP (exit 0), not a false red.
        checker.skip("all Windows launcher checks",
                     f"the factory repo root was not found above {SCRIPTS} "
                     f"({', '.join(REPO_FILES)} must live in one directory) - this looks like a "
                     "project deployed by the factory, not the factory repo itself")
        return checker.finish()

    # 1. Existence, encoding, CRLF-only line endings.
    checker.check("prepare_factory.ps1: exists, UTF-8 with BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(PS1, bom=True))
    checker.check("prepare_factory.cmd: exists, no BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(CMD, bom=False))
    checker.check("start.cmd: exists, no BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(START_CMD, bom=False))

    # 2. prepare_factory.cmd contract + guarded pause.
    checker.check("prepare_factory.cmd: contract (chcp, PowerShell flags, arg forwarding, "
                  "exit /b, usage string)", prepare_cmd_contract)
    checker.check("prepare_factory.cmd: the pause is guarded by the double-click detection "
                  "(never unconditional)", prepare_cmd_pause_guard)

    # 3. start.cmd contract.
    checker.check("start.cmd: contract (chcp, cd /d, KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1, "
                  "where kimi, kimi %*, exit /b) + first line '@echo off'", start_cmd_contract)

    # 4./5. Anti-drift guards for the two inlined launcher templates.
    checker.check("anti-drift: the inline start.cmd template in prepare_factory.ps1 == repo/start.cmd",
                  antidrift_start_cmd)
    checker.check("anti-drift: the inline start.sh template in prepare_factory.ps1 == the here-doc "
                  "in prepare_factory.sh", antidrift_start_sh)

    # 6. The bash deployer must not grow a Windows launcher.
    checker.check("prepare_factory.sh: generates no start.cmd (only its .gitignore pattern may "
                  "be mentioned), here-doc intact", bash_deployer_untouched)

    # 6b. A pre-existing, differing start.sh is announced and backed up (and the check is proven to
    #     fail on the pre-fix tree, resolved from the history rather than from HEAD).
    checker.check("both deployers: a differing start.sh is warned about and kept as start.sh.bak "
                  "BEFORE the launcher is written (probe: the PRE-FIX base commit must fail this)",
                  launcher_backup_guard)
    checker.check("prepare_factory.ps1: a start.sh.bak that cannot be created aborts the overwrite "
                  "and marks a hard deployment error (never an empty catch before the write)",
                  ps1_start_sh_backup_failure_is_fatal)

    # 7. The checkout itself must hand these files over with the right line endings, on any machine.
    checker.check(".gitattributes: pins *.cmd/*.ps1 to CRLF at checkout (any core.autocrlf)",
                  gitattributes_pins_crlf)
    checker.check(".gitattributes: pins *.sh to LF at checkout (any core.autocrlf)",
                  gitattributes_pins_sh_lf)

    # 8. Failure paths of both deployers: business message, honest exit code, no raw dumps.
    checker.check("prepare_factory.ps1: the Copy-Item fallback is in a try/catch (-ErrorAction "
                  "Stop, Err + $HardError, exit 1 without the banner)", ps1_copy_fallback_is_guarded)
    checker.check("prepare_factory.ps1: git init falls back to plain init + symbolic-ref on git "
                  "< 2.28 (`-b` unsupported) - hard error only if the fallback fails too",
                  ps1_git_init_fallback)
    checker.check("prepare_factory.ps1: a failed memory init is reported as a short reason "
                  "(last non-empty line, no raw output)", ps1_memory_failure_is_short)
    checker.check("prepare_factory.sh: a failed memory init is reported as a short reason "
                  "(last non-empty line, no raw output)", bash_memory_failure_is_short)
    checker.check("prepare_factory.ps1: the memory CHECK line is ONE line - the trailing verdict "
                  "plus a WARN count, never the whole `check` output",
                  ps1_memory_check_line_is_single_line)

    # 9. Repo-path scoping hazards: both deployers ignore their own task.yaml/launchers (or a
    # leftover one in a TARGET project is handed over as a new task / committed), and both launcher
    # templates export the launch directory the instruction layer resolves repo_path against.
    checker.check("prepare_factory.ps1: .gitignore patterns cover task.yaml/start.cmd/start.sh",
                  ps1_ignores_deployer_hazards)
    checker.check("prepare_factory.sh: .gitignore patterns cover task.yaml/start.cmd/start.sh "
                  "(and are really written)", sh_ignores_deployer_hazards)
    checker.check(f"BOTH deployers: .gitignore covers {MCP_CONFIG_PATTERN} (the managed entry "
                  "carries the absolute path of this installation's vendored package), list and "
                  "written block", mcp_config_is_gitignored)
    checker.check(f"start.sh template (both carriers): exports {LAUNCH_DIR_VAR} as the launcher's "
                  "own absolute directory", sh_template_exports_launch_dir)
    checker.check(f"start.cmd template + repo/start.cmd: exports {LAUNCH_DIR_VAR} "
                  "(%~dp0 via %CD%, after the cd)", cmd_template_exports_launch_dir)

    # 10. The managed Chrome DevTools MCP deployment: its own step in both deployers (install the
    # pinned package, then merge the entry), one reported conflict/skip/failure contract, the pin
    # only in the shipped asset, and the committed asset's merged shape (computed from constants
    # independent of it, mutation-proven, and never from the machine-local config).
    checker.check("prepare_factory.ps1: MCP step (vendor-install before merge-config via the probed "
                  "interpreter, nothing written when the install failed)", ps1_mcp_step)
    checker.check("prepare_factory.sh: MCP step (vendor-install before merge-config via the probed "
                  "interpreter, nothing written when the install failed)", sh_mcp_step)
    checker.check("both deployers: report a preserved MCP conflict / a skipped install / a skipped "
                  "merge and document the new-session /mcp check", mcp_report_contract)
    checker.check(f"both deployers: the {MCP_REL} readiness line distinguishes the created, "
                  "updated, unchanged, conflict, vendor-skipped and skipped states",
                  mcp_readiness_contract)
    checker.check(f"the pin {MCP_PIN} and the entry-path layout live only in {MCP_ASSET_REL} / the "
                  "merge helper (never duplicated into a deployer)", mcp_pin_lives_in_the_asset_only)
    checker.check(f"{MCP_ASSET_REL}: a merge of the COMMITTED asset is the managed shape (node + "
                  "absolute vendored entry + the required flags/env, no permission/attach key)",
                  mcp_asset_deploys_into_the_managed_shape)
    checker.check(f"that shape check needs no machine-local {MCP_REL} - it passes against a "
                  "clean-clone fixture in which the file does not exist",
                  mcp_shape_check_needs_no_local_config)
    checker.check("the MCP safety assertions are INDEPENDENT of the asset: dropping a required "
                  "flag/env switch from a copy of it (or adding a forbidden key) makes them FAIL",
                  mcp_safety_switches_are_load_bearing)

    # 11. Real deployment (Windows only): fresh, pre-existing MCP settings, conflicting entry and
    # the two no-python degradations.
    end_to_end(checker)

    return checker.finish()


if __name__ == "__main__":
    sys.exit(main())

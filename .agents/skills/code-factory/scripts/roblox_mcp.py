#!/usr/bin/env python3
"""
Deterministic Roblox Studio MCP helpers for the Code Factory — zero LLM tokens.

The factory activates the roblox-expert role only when the CURRENT business task really is Roblox
game-development work. Two independent conditions must hold, and each one alone is enough to keep
the role OFF:
  (a) the REPOSITORY is a Roblox project — a Rojo `*.project.json` descriptor, a `.luau`/`.lua`
      source that really references the Roblox API (`game:GetService(...)`, `Instance.new(...)`,
      `script.Parent`, a Roblox service), a place file (`*.rbxl`/`*.rbxlx`), or an existing
      `Roblox_Studio` entry in the project's own `.kimi-code/mcp.json`;
  (b) the METADATA-STRIPPED task text asks for Roblox work — an explicit Roblox SUBJECT term
      (`roblox`, `roblox studio`, `Studio`, `rojo`, `luau`, a place file, the Studio MCP
      server/tools) bound to an ACTION term (`add`, `create`, `build`, `fix`, `playtest`, `script`,
      `run`, …), where an action on DOCUMENTATION/media (`edit the markdown guide`, `update the
      README`) is not Roblox work and a `studio` naming another product or place (`Visual Studio`, a
      `studio apartment`) is not the Roblox IDE. The action/object binding is CLAUSE-level, so a
      documentation clause discards only its own action and never the game work of the next clause,
      while an action counts only inside the clause that ALSO names the Roblox subject — a subject
      in one clause and a generic verb in another never combine. Task-file METADATA (`models:`,
      `repo_path:`, `commit_exclude:`) is not scope and is
      stripped before classification, so `models.roblox_expert` alone (a MODEL pin), the repository
      identity alone, or the task text alone all stay `not_applicable`. Every decision carries a
      REASON naming the repository markers, the scope terms and the discarded ones. Never a model
      call.

Subcommands (all deterministic, stdlib only):
  decide           applicability of the roblox-expert role for a task (--repo, --text/--task-file)
  merge-config     idempotently register the built-in Roblox Studio stdio server (`Roblox_Studio`)
                   into the USER-SCOPE GLOBAL CLI config by default — `$KIMI_CODE_HOME/mcp.json`
                   when `KIMI_CODE_HOME` is set, else `~/.kimi-code/mcp.json` — or into an explicit
                   `--target` override (--dry-run)
  validate-config  invariants of a managed `Roblox_Studio` entry (--path)
  probe            fail-soft capability probe (Studio launcher, the managed config), with the
                   Studio/MCP start handshake STRICTLY opt-in via --check-mcp-start (--out)
  scenario run     the deterministic play-test scenario runner: bounded stdio MCP session against
                   the Studio server (or an injected --executable/--arg seam), the run's console
                   output captured to the evidence directory, and a STRUCTURED verdict JSON
  scenario verdict read back the stored verdict of one evidence directory
  scenario verify  strict gate: exit 0 only when the STORED verdict is honestly PASS

Exit codes:
  0  success — including a `not_applicable` decision, a DEGRADED `probe` (a missing capability is
     DATA, never a crash), and a PASS scenario verdict
  1  a real error or a recorded FAIL verdict: an unwritable/atomic-failing target, a config that is
     not valid JSON (such a target is then NEVER overwritten), a scenario verdict FAIL (a play-test
     that logged an error is LOUD), and a FAILED `scenario verify` gate
  2  usage error (argparse, or a validated argument: a `--repo` that is not a directory, a missing
     `--task-file`/`--scenario`/`--executable`, a `--target`/`--out` whose parent directory does not
     exist, an undeterminable or nonexistent data root, a zero-step scenario, a `--timeout-seconds`
     outside (0, 3600], an empty `--arg`)
  3  `merge-config` conflict: a DIFFERENT `Roblox_Studio` entry already exists — it is preserved
     byte-for-byte and reported, never silently replaced

Managed entry shape (deterministic, one definition — the built-in Studio server over stdio):
  {"command": "cmd.exe", "args": ["/c", <absolute expanded %LOCALAPPDATA%>\\Roblox\\mcp.bat]}
The `%LOCALAPPDATA%` of the REGISTERING host is expanded to an absolute, symlink-resolved path at
merge time: a config that carries an unexpanded variable launches nothing. Roblox Studio ships on
Windows, so that is the reviewed managed shape; on a host where `%LOCALAPPDATA%` cannot be resolved
the merge is refused (exit 2) instead of writing an entry that would not launch.

Determinism and safety of the helpers themselves:
  - every decision carries a REASON and is keyword/rule based, never a model call;
  - `merge-config` reads the target as text and inserts only the `mcpServers.Roblox_Studio` member,
    so every unrelated byte (other servers, settings, line endings) survives; an equal entry is
    `unchanged` (a second merge is byte-identical), a different one is a `conflict` with exit 3 and
    the target untouched; the write itself is ATOMIC (a same-directory temp file plus `os.replace`);
  - the DEFAULT registration target is the user-scope GLOBAL CLI config and is never typed by hand:
    the script resolves it, resolves every symlink in it, requires the resolved data root to EXIST
    (a typo'd `KIMI_CODE_HOME` must not create a stray tree) and echoes the resolved path — so the
    operator sees exactly which file was written. `--target` is the explicit override for
    tests/fixtures and follows the SAME contract;
  - no diagnostic echoes a value an MCP entry supplies (`command`, `args`, extra keys): this output
    lands in logs and evidence, and an entry may carry a credential — messages name the offending
    KEY and the managed shape, never the stored value;
  - the Studio start handshake is STRICTLY opt-in (`probe --check-mcp-start`) and BOUNDED, and the
    child process TREE is always terminated — even when the launcher it started has ALREADY exited,
    which is why the session's descendant cleanup never keys on the direct child's liveness — so a
    probe or a scenario never leaves a Studio session behind;
  - a scenario verdict is DERIVED from evidence, never asserted: PASS requires the scenario to have
    COMPLETED **and** the captured console output to contain no error log line — any error line is
    FAIL. A `tools/call` result only counts as answered when it is a well-formed MCP result whose
    `isError` is ABSENT, `false` or `true` — a PRESENT non-boolean `isError` (`"true"`, `"false"`,
    `1`, `0`, `null`) is refused, never coerced, so a string or numeric error signal can never
    produce a PASS. A screenshot may be attached and is recorded as an artifact; it is NEVER the
    verdict (`screenshot_is_verdict` is false in every verdict this helper writes), and `scenario
    verify` re-derives PASS from the stored console bytes (their sha256 included) instead of
    trusting the stored verdict field.
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import hashlib
import json
import math
import os
import pathlib
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # `factory_preflight.py` loads this helper BY PATH (deliberately independent of `sys.path`), so
    # the shared sibling modules have to be made importable here instead of being assumed.
    sys.path.insert(0, str(_SCRIPTS_DIR))
import mcp_json_merge  # noqa: E402  (the sibling path fix above must run first)
import task_parser  # noqa: E402  (the sibling path fix above must run first)

SERVER_NAME = "Roblox_Studio"
STUDIO_COMMAND = "cmd.exe"
STUDIO_BATCH_DIR = "Roblox"
STUDIO_BATCH_NAME = "mcp.bat"
CONFIG_RELPATH = pathlib.Path(".kimi-code") / "mcp.json"
CONFIG_FILE_NAME = "mcp.json"
PROBE_FILE_NAME = "roblox-mcp-probe.json"
DATA_ROOT_DIRNAME = ".kimi-code"

EXIT_CONFLICT = 3
TERMINATE_TIMEOUT = 10
STREAM_TAIL_LINES = 200
# How long an already-answered stage is watched for the death of the child before the stage is called
# green: a server that exits right after `tools/list` keeps its listing, so the listing alone is
# never the verdict.
LIVENESS_GRACE = 2.0
# How long the stderr capture must stay QUIET before the console is snapshotted. The drain thread
# reads the pipe asynchronously, so a line the server wrote a moment ago may not have landed yet; a
# short quiet window makes the capture complete without ever waiting on a still-running server.
CONSOLE_QUIET_WINDOW = 0.2
# The Windows job object that holds the session's child and its descendants (`_adopt_tree`), so the
# bounded stop reaches a server whose launcher is already gone. Lazily loaded, once. A host that
# cannot hand out that guarantee refuses the session: nothing starts (`_adopt_tree` returns the
# cause) rather than running a server no cleanup can reach.
_KERNEL32 = None

DEFAULT_SCENARIO_TIMEOUT = 600.0
MAX_SCENARIO_TIMEOUT = 3600.0
VERDICT_KIND = "roblox-scenario-verdict"
VERDICT_SCHEMA = 1
VERDICT_FILE = "verdict.json"
CONSOLE_FILE = "console.log"

CAPABILITY_NAMES: tuple[str, ...] = ("studio_launcher", "mcp_config")
HANDSHAKE_CAPABILITY = "mcp_start"

APPLICABLE = "applicable"
NOT_APPLICABLE = "not_applicable"

# --------------------------------------------------------------------------- repository identity

# A Rojo descriptor is `<name>.project.json`; a place is a binary or XML `.rbxl`/`.rbxlx`.
ROJO_SUFFIX = ".project.json"
PLACE_SUFFIXES: tuple[str, ...] = (".rbxl", ".rbxlx")
LUAU_SUFFIXES: tuple[str, ...] = (".luau", ".lua")
# Directories that are never the project's sources: VCS/dependency/build state and the factory's own
# runtime state (a `.code-factory/` fixture place must not make an unrelated repository Roblox).
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", ".kimi-code", ".code-factory", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build",
})
# The Roblox API references that make a `.luau`/`.lua` file a ROBLOX source rather than any other
# Lua dialect: the DataModel's service accessor, the Instance factory, a script's own hierarchy.
LUAU_ROBLOX_REFERENCE = re.compile(
    r"\bgame\s*[:.]\s*(?:GetService|Workspace|Players|ReplicatedStorage|ServerScriptService|"
    r"ServerStorage|StarterGui|StarterPack|Lighting|HttpService|RunService|TweenService|"
    r"UserInputService|CollectionService|TeleportService|DataStoreService|SoundService|"
    r"ReplicatedFirst|ServerStorage)\b"
    r"|\bInstance\s*\.\s*new\b"
    r"|\bscript\s*\.\s*(?:Parent|FindFirstChild|WaitForChild)\b",
    re.IGNORECASE)
# Bounds that keep the scan of a big tree deterministic and cheap.
MAX_SCANNED_FILES = 20000
MAX_SCANNED_SOURCES = 200
MAX_SOURCE_BYTES = 262144
MAX_LISTED_MARKERS = 5

# --------------------------------------------------------------------------- scope vocabulary

# Roblox SUBJECT terms: what the task is about. Naming the repository, the engine, the place format,
# the Studio IDE or the Studio MCP server is what makes a task Roblox work at all. `studio` alone
# counts because "playtest it in Studio" is exactly how a Roblox task is phrased (see
# NON_ROBLOX_STUDIO for the occurrences that name another product or place instead).
ROBLOX_SUBJECT_TERMS: tuple[str, ...] = (
    "roblox", "roblox studio", "rojo", "luau", "rbxl", "rbxlx", "place file", "studio mcp",
    "roblox_studio", "studio",
)
# ACTION terms: what the task does with that subject. A generic verb alone is somebody else's task.
ROBLOX_ACTION_TERMS: tuple[str, ...] = (
    "add", "create", "build", "implement", "fix", "change", "update", "edit", "refactor", "test",
    "run", "debug", "playtest", "play test", "publish", "script", "gui", "animation", "save",
    "open", "start", "stop", "migrate", "port", "review", "inspect", "read", "generate", "attach",
    "place", "instance", "gameplay",
)
# SUBJECT BINDING: an action whose object is documentation/media is not Roblox work — "update the
# Roblox README" documents the game instead of changing it. The object is bound inside the action's
# OWN CLAUSE, per OCCURRENCE, so an action in the task still counts:
#   "Update the Roblox changelog with the coin system changes." — `changelog` governs this whole
#     clause, so both `update` and `changes` are documentation work and not Roblox work;
#   "Fix the Roblox README typo and playtest the coin pickup in Studio." — the documentation clause
#     is discarded while the next clause really plays the game, so the task IS Roblox work.
# Clause-level, not distance-based: proximity let a neighbouring clause's `README` discard a real
# play-test and let a trailing clause escape a documentation action (both pinned by
# `test_roblox_mcp.py`, case 1.13).
NON_ROBLOX_OBJECTS: frozenset[str] = frozenset({
    "documentation", "doc", "docs", "readme", "manual", "guide", "changelog", "website", "site",
    "report", "diagram", "docstring", "note", "blog", "tutorial", "markdown", "markdown file",
})
# What closes a clause: a sentence terminator, a comma, or a coordinating conjunction. A deliberate
# SHALLOW rule — it decides which object an action governs, never the sentence's full grammar, so it
# stays deterministic and free of a natural-language dependency.
CLAUSE_BOUNDARY = re.compile(r"[.!?;,]|\b(?:and|but|then|so)\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z_-]*")

# `studio` alone is the Roblox IDE, but the word also names other PRODUCTS and PLACES: Visual Studio,
# a dance/recording/photo studio, a studio apartment. Those occurrences are blanked before the SUBJECT
# scan, so only a `studio` that can mean Roblox Studio makes a task Roblox work. The vocabulary is a
# reasonable list, not a taxonomy: a bare "in the studio" is still read as Roblox Studio when the text
# binds an action to it — the documented limitation of a keyword classifier.
NON_ROBLOX_STUDIO = re.compile(
    r"\b(?:visual|vs|android|obs|photo|photography|recording|music|film|television|tv|dance|art|"
    r"design|yoga|fitness|animation|unity|unreal|game\s+maker)\s+studios?\b"
    r"|\bstudios?\s+(?:apartments?|flats?|rooms?)\b",
    re.IGNORECASE)

# Explicit exclusions win over every Roblox keyword: activating the role by mistake puts a Studio
# session on unrelated work, so the conservative direction is deliberate.
ROBLOX_EXCLUSIONS: tuple[str, ...] = (
    r"\bno\s+roblox\b",
    r"\bwithout\s+(the\s+)?roblox\b",
    r"\bno\s+(studio\s+)?mcp\b",
    r"\bwithout\s+(the\s+)?(roblox\s+)?(studio\s+)?mcp\b",
    r"\broblox\s+is\s+not\s+involved\b",
    r"\bnot\s+a\s+roblox\s+task\b",
    r"\broblox\s+(work\s+)?(is|are|stays?)\s+out\s+of\s+scope\b",
    r"\bunrelated\s+to\s+(the\s+)?roblox\b",
)

# Task-file METADATA is not task SCOPE: `models:`, `repo_path:` and `commit_exclude:` describe how the
# run is WIRED, never what it operates. `models.roblox_expert` merely pins the specialist's model.
METADATA_KEYS: tuple[str, ...] = ("models", "repo_path", "commit_exclude", "mode", "task_type")
_METADATA_BLOCK = re.compile(
    r"^(?:" + "|".join(METADATA_KEYS) + r")\s*:[^\n]*(?:\n[ \t]+[^\n]*)*", re.MULTILINE)
_MODELS_TOKEN = re.compile(r"\bmodels(?:_used)?\.[a-z_]+\b", re.IGNORECASE)

# Console lines that are an ERROR log line. A play-test that logged one is never a PASS, so the
# pattern covers the Roblox/Luau failure spellings and the generic error/exception markers.
ERROR_LINE_PATTERN = re.compile(
    r"\berror\b|\bexception\b|\btraceback\b|\bstack traceback\b|stack begin|\bfatal\b|"
    r"\bfailed\b|\bassertion failed\b|infinite yield possible",
    re.IGNORECASE)


class InputError(Exception):
    """A real error the CLI must report as a message + exit 1 (never a traceback)."""


class UsageError(Exception):
    """A validated ARGUMENT problem the CLI must report as a message + exit 2 (never a traceback)."""


# --------------------------------------------------------------------------- paths

def _read_text(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: str | pathlib.Path) -> object | None:
    """Parsed JSON or `None` — a missing/unreadable/invalid file is DATA, never a crash."""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _realpath(path: str | pathlib.Path) -> str:
    """`path` with every symlink resolved; a path that does not exist YET resolves through its
    nearest existing ancestor, so a `--target` under a symlinked directory is still seen.

    `os.path.lexists` is deliberate: a DANGLING symlink counts as existing, and `realpath` then
    answers the path it points AT — writing through it would escape the directory that looked safe.
    """
    current = pathlib.Path(os.path.abspath(str(path)))
    missing: list[str] = []
    while not os.path.lexists(str(current)) and current.parent != current:
        missing.append(current.name)
        current = current.parent
    resolved = pathlib.Path(os.path.realpath(str(current)))
    for name in reversed(missing):
        resolved = resolved / name
    return str(resolved)


def _resolved(path: str | pathlib.Path) -> str:
    """The comparison form of `_realpath` (case-insensitive on Windows)."""
    return os.path.normcase(_realpath(path))


def _within(child: str | pathlib.Path, parent: str | pathlib.Path) -> bool:
    """`True` when the RESOLVED `child` is strictly inside the RESOLVED `parent`."""
    child_s = _resolved(child)
    parent_s = _resolved(parent)
    if child_s == parent_s:
        return False
    try:
        return os.path.commonpath([child_s, parent_s]) == parent_s
    except ValueError:                      # different drive letters on Windows
        return False


def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    """The repository root — an argument that is not an existing directory is a USAGE error."""
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise UsageError(f"--repo {root} is not an existing directory: applicability is decided "
                         "against a real project tree, so pass the resolved repository root")
    return root


def _write_text_exact(path: pathlib.Path, text: str) -> None:
    """Write `text` to `path` ATOMICALLY (a same-directory temp file plus `os.replace`).

    An interrupted or failing write must never leave half a config behind: the target either keeps
    every byte it had or receives the complete new text. `OSError` propagates to the caller, which
    turns it into the documented error result (exit 1) instead of a traceback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------- repository signals

def _skipped(directory: str) -> bool:
    """A directory the marker scan never enters (VCS/dependency/build state, hidden state dirs)."""
    name = os.path.basename(directory)
    return name in SKIP_DIRS


def _luau_references_roblox(path: pathlib.Path) -> bool:
    """`True` when a `.luau`/`.lua` file really uses the Roblox API (bounded read)."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES)
    except OSError:
        return False
    return bool(LUAU_ROBLOX_REFERENCE.search(raw.decode("utf-8", "replace")))


def _scan_markers(root: pathlib.Path) -> dict:
    """The Roblox markers of a project tree, collected in ONE bounded deterministic walk."""
    found: dict[str, list[str]] = {"rojo_projects": [], "place_files": [], "luau_sources": [],
                                   "service_sources": []}
    visited = 0
    sources = 0
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not _skipped(os.path.join(current, name)))
        for filename in sorted(filenames):
            visited += 1
            if visited > MAX_SCANNED_FILES:
                break
            path = pathlib.Path(current) / filename
            low = filename.lower()
            relative = os.path.relpath(str(path), str(root)).replace("\\", "/")
            if low.endswith(ROJO_SUFFIX):
                found["rojo_projects"].append(relative)
            if low.endswith(PLACE_SUFFIXES):
                found["place_files"].append(relative)
            if low.endswith(LUAU_SUFFIXES) and sources < MAX_SCANNED_SOURCES:
                sources += 1
                found["luau_sources"].append(relative)
                if _luau_references_roblox(path):
                    found["service_sources"].append(relative)
        if visited > MAX_SCANNED_FILES:
            break
    return found


def roblox_entry_present(path: str | pathlib.Path) -> bool:
    """`True` when a config file carries an object under `mcpServers.Roblox_Studio`."""
    return _roblox_entry(path) is not None


def roblox_repository_signals(repo: str | pathlib.Path) -> dict:
    """The Roblox markers of a repository — EVIDENCE, never a decision on its own."""
    root = pathlib.Path(os.path.abspath(str(repo)))
    found = _scan_markers(root)
    config = root / CONFIG_RELPATH
    mcp_entry = roblox_entry_present(config)
    details: list[str] = []
    if found["rojo_projects"]:
        details.append(f"Rojo descriptor(s) {_listed(found['rojo_projects'])}")
    if found["place_files"]:
        details.append(f"place file(s) {_listed(found['place_files'])}")
    if found["service_sources"]:
        details.append(f"Luau source(s) referencing the Roblox API "
                       f"{_listed(found['service_sources'])}")
    if mcp_entry:
        details.append(f"{CONFIG_RELPATH.as_posix()} already carries a {SERVER_NAME!r} server entry")
    roblox = bool(found["rojo_projects"] or found["place_files"] or found["service_sources"]
                  or mcp_entry)
    return {
        "root": str(root),
        "rojo_projects": _capped(found["rojo_projects"]),
        "place_files": _capped(found["place_files"]),
        "luau_sources": _capped(found["luau_sources"]),
        "service_sources": _capped(found["service_sources"]),
        "luau_source_count": len(found["luau_sources"]),
        "mcp_entry": mcp_entry,
        "roblox": roblox,
        "details": details,
    }


def _capped(items: list[str]) -> list[str]:
    return items[:MAX_LISTED_MARKERS]


def _listed(items: list[str]) -> str:
    shown = ", ".join(_capped(items))
    return shown + (f" (+{len(items) - MAX_LISTED_MARKERS} more)" if len(items) > MAX_LISTED_MARKERS
                    else "")


# --------------------------------------------------------------------------- applicability

def _present(low: str, term: str) -> bool:
    """`True` when `term` occurs in the already-lowercased `low` as a whole word (plural allowed)."""
    return bool(re.search(r"\b" + re.escape(term) + r"s?\b", low))


def _find_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return [term for term in terms if _present(low, term)]


def _object_key(word: str) -> str:
    """A word folded onto its object key: lowercase, `-` treated as a space, one plural `s` dropped."""
    key = word.lower().replace("-", " ").strip()
    return key[:-1] if len(key) > 3 and key.endswith("s") else key


def _clauses(text: str) -> list[str]:
    """The CLAUSES of an already-lowercased scope — the span one action governs.

    `CLAUSE_BOUNDARY` closes a clause, so a documentation word in a NEIGHBOURING clause can no longer
    discard this clause's action, and a documentation action cannot escape through a boundary.
    """
    return [clause for clause in CLAUSE_BOUNDARY.split(text or "") if clause.strip()]


def _names_documentation_object(clause: str) -> bool:
    """`True` when this clause names a documentation/media OBJECT (NON_ROBLOX_OBJECTS)."""
    return any(_object_key(word) in NON_ROBLOX_OBJECTS for word in _WORD.findall(clause))


def bound_actions(scope: str) -> list[str]:
    """The action terms BOUND to a Roblox subject in a METADATA-stripped scope.

    An action counts only inside the clause that ALSO names the Roblox subject, because that is the
    subject it governs. A subject in one clause and a generic verb in another ("Update the Roblox
    README, then fix the Python CI.") are two unrelated statements: the verb drives somebody else's
    task, so nothing is bound. A clause naming a documentation/media object is discarded before the
    binding, so it can neither bind nor discard a neighbouring clause's action.
    """
    game_clauses = [clause for clause in _clauses((scope or "").lower())
                    if not _names_documentation_object(clause) and subject_terms(clause)]
    return [term for term in ROBLOX_ACTION_TERMS
            if any(re.search(r"\b" + re.escape(term) + r"s?\b", clause) for clause in game_clauses)]


def scope_text(text: str) -> str:
    """The task text with its YAML METADATA removed — the scope is what the task OPERATES.

    A task file carries wiring next to its scope (`models:`, `repo_path:`, `commit_exclude:`,
    `mode:`, `task_type:`), and `models.roblox_expert` merely pins the specialist's model. Both are
    dropped before classification, so a task whose only mention of Roblox is a model key stays
    `not_applicable`.
    """
    without_metadata = _METADATA_BLOCK.sub(" ", text or "")
    return _MODELS_TOKEN.sub(" ", without_metadata)


def _exclusions(scope: str) -> list[str]:
    """Every explicit exclusion phrase the scope carries (they win over all Roblox keywords)."""
    low = (scope or "").lower()
    return [pattern for pattern in ROBLOX_EXCLUSIONS if re.search(pattern, low)]


def subject_terms(scope: str) -> list[str]:
    """The Roblox SUBJECT terms of a METADATA-stripped scope.

    A `studio` that names another product or place (`Visual Studio`, a `studio apartment`) is
    blanked first, so it never counts as the Roblox IDE.
    """
    return _find_terms(NON_ROBLOX_STUDIO.sub(" ", scope or ""), ROBLOX_SUBJECT_TERMS)


def _text_condition(scope: str) -> tuple[bool, str]:
    """`(asks_for_roblox_work, reason)` for a METADATA-stripped scope."""
    subjects = subject_terms(scope)
    actions = bound_actions(scope)
    if subjects and actions:
        return True, (f"the task text names a Roblox subject ({', '.join(subjects[:6])}) and an "
                      f"action bound to it ({', '.join(actions[:6])})")
    if not subjects:
        return False, ("the task text names no Roblox subject (roblox, roblox studio, Studio, rojo, "
                       "luau, a place file, the Studio MCP server): a task on another subject is not "
                       "Roblox work, however often it says add/build/fix")
    return False, (f"the task text names a Roblox subject ({', '.join(subjects[:6])}) but binds no "
                   "action to it in its own clause (an action on documentation/media such as a "
                   "README or a markdown guide is not Roblox work, and a subject in one clause "
                   "next to a generic verb in another is a mention in passing, not a task)")


def decide_applicability(text: str, repo: str | pathlib.Path) -> dict:
    """Classify the roblox-expert role as applicable/not applicable WITH reasons.

    The decision is a chain of focused steps so each stays readable on its own: the repository
    markers (`roblox_repository_signals`), the METADATA-stripped scope (`scope_text`), the explicit
    exclusions, the text condition (`_text_condition`) — and then BOTH conditions in one place.
    """
    root = _checked_repo(repo)
    signals = roblox_repository_signals(root)
    scope = scope_text(text)
    exclusions = _exclusions(scope)
    if exclusions:
        return _decision(False, [
            "the task text explicitly excludes Roblox/Studio scope ("
            + ", ".join(exclusions) + "); the roblox-expert role and the Studio MCP tools stay off",
            _repo_reason(signals),
        ], signals, scope)
    asks, text_reason = _text_condition(scope)
    applicable = bool(signals["roblox"] and asks)
    reasons = [_repo_reason(signals), text_reason]
    if applicable:
        reasons.insert(0, "BOTH conditions hold: the repository is a Roblox project AND the task "
                          "asks for Roblox work — the roblox-expert role and the "
                          f"{SERVER_NAME} MCP tools apply")
    else:
        reasons.append("the role needs BOTH conditions: repository identity alone, task text "
                       "alone and a `models.roblox_expert` model pin alone never activate it")
    return _decision(applicable, reasons, signals, scope)


def _decision(applicable: bool, reasons: list[str], signals: dict, scope: str) -> dict:
    return {"applicable": applicable, "reasons": reasons,
            "evidence": {"repository": signals, "scope_terms": subject_terms(scope)
                         + _find_terms(scope, ROBLOX_ACTION_TERMS)}}


def _repo_reason(signals: dict) -> str:
    if signals["roblox"]:
        return f"the repository {signals['root']} IS a Roblox project ({'; '.join(signals['details'])})"
    return (f"the repository {signals['root']} is not a Roblox project (no Rojo "
            f"`*{ROJO_SUFFIX}`, no `.rbxl`/`.rbxlx` place file, no `.luau`/`.lua` source using the "
            f"Roblox API, and no {SERVER_NAME!r} entry in {CONFIG_RELPATH.as_posix()})")


def format_decision(result: dict) -> str:
    verdict = "applicable" if result["applicable"] else "not applicable"
    return "\n".join([verdict] + [f"reason: {reason}" for reason in result["reasons"]])


# --------------------------------------------------------------------------- managed entry

def studio_batch_path() -> pathlib.Path:
    """The absolute Studio MCP launcher `%LOCALAPPDATA%\\Roblox\\mcp.bat` of THIS host.

    The variable is expanded and the result symlink-resolved at merge time: a config that stores the
    unexpanded `%LOCALAPPDATA%` launches nothing. A host where the location cannot be determined
    (no `%LOCALAPPDATA%` and not Windows) is a USAGE error — writing an entry that cannot launch
    would be worse than writing none.
    """
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if not local and os.name == "nt":
        profile = (os.environ.get("USERPROFILE") or "").strip()
        if profile:
            local = str(pathlib.Path(profile) / "AppData" / "Local")
    if not local:
        raise UsageError(
            "the Roblox Studio MCP launcher path cannot be determined: %LOCALAPPDATA% is not set on "
            "this host, and the reviewed managed shape is the Windows Studio server "
            f"`{STUDIO_COMMAND} /c <absolute %LOCALAPPDATA%>\\Roblox\\{STUDIO_BATCH_NAME}` — nothing "
            "was written")
    return pathlib.Path(_realpath(pathlib.Path(os.path.abspath(local)) / STUDIO_BATCH_DIR
                                  / STUDIO_BATCH_NAME))


def managed_entry() -> dict:
    """The deterministic `Roblox_Studio` server definition for THIS host."""
    return {"command": STUDIO_COMMAND, "args": ["/c", str(studio_batch_path())]}


# A managed entry is EXACTLY these keys: anything else (`env`, credentials, launch options) is an
# unreviewed launch setting, and the exact-managed-entry contract refuses it.
MANAGED_ENTRY_KEYS: tuple[str, ...] = ("command", "args")


# --------------------------------------------------------------------------- config target

def _data_root() -> pathlib.Path:
    """The resolved CLI data root: `$KIMI_CODE_HOME` when set, else `<home>/.kimi-code`.

    `KIMI_CODE_HOME` relocates the CLI's WHOLE data root, so the managed file lives directly inside
    it. Both inputs are NEW here and are therefore validated: the resolved path must be an existing
    directory (a typo'd environment must never make this helper create a stray data-root tree), and
    a host with neither variable nor home is refused loudly.
    """
    relocated = (os.environ.get("KIMI_CODE_HOME") or "").strip()
    if relocated:
        root = pathlib.Path(_realpath(os.path.abspath(relocated)))
        origin = "KIMI_CODE_HOME"
    else:
        home = _home_directory()
        root = pathlib.Path(_realpath(pathlib.Path(home) / DATA_ROOT_DIRNAME))
        origin = f"the home directory {home}"
    if not root.is_dir():
        raise UsageError(f"the CLI data root resolved from {origin} does not exist: {root}; the "
                         "managed registration is never written into a data root this helper would "
                         f"have to create — check {origin} (nothing was written)")
    return root


def _home_directory() -> str:
    """`%USERPROFILE%` on Windows, `$HOME` on POSIX — undeterminable is a USAGE error."""
    names = ("USERPROFILE", "HOME") if os.name == "nt" else ("HOME", "USERPROFILE")
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    raise UsageError("neither %USERPROFILE% nor $HOME is set, so the user-scope global MCP config "
                     "cannot be located: set KIMI_CODE_HOME to the CLI data root or pass --target "
                     "(nothing was written)")


def default_config_path() -> pathlib.Path:
    """The USER-SCOPE GLOBAL CLI config: `<data root>/mcp.json`, symlink-resolved."""
    return _data_root() / CONFIG_FILE_NAME


def resolve_target(value: str | None) -> pathlib.Path:
    """The config the merge writes: the resolved global default, or a validated `--target`.

    An explicit `--target` is the tests/fixtures override and follows ONE contract with the default:
    symlink-resolved, and its PARENT directory must already exist — a mistyped fixture path fails
    loudly instead of creating directories the operator never named.
    """
    if value is None:
        return default_config_path()
    raw = pathlib.Path(os.path.abspath(str(value)))
    if not raw.parent.is_dir():
        raise UsageError(f"--target {raw}: the parent directory {raw.parent} does not exist; create "
                         "only the directories you mean and re-run (nothing was written)")
    return pathlib.Path(_realpath(raw))


# --------------------------------------------------------------------------- config validation

def _roblox_entry(path: str | pathlib.Path) -> dict | None:
    """The `mcpServers.Roblox_Studio` object of a config FILE, or `None` when absent/malformed."""
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    entry = servers.get(SERVER_NAME)
    return entry if isinstance(entry, dict) else None


def _expected_managed() -> dict | None:
    """The managed entry this host would write, or `None` when the launcher path is unknown."""
    try:
        return managed_entry()
    except UsageError:
        return None


def validate_config(path: str | pathlib.Path) -> tuple[bool, list[str]]:
    """Invariants of a managed `Roblox_Studio` entry: `(ok, problems)` — data, not crashes.

    The entry is validated only when it is PRESENT: a config without the Studio server is valid (it
    simply does not use that path), while a PRESENT entry must be exactly the managed definition — a
    hand-edited variant would launch something other than the reviewed Studio server.

    NO diagnostic echoes a value the entry supplies: an MCP entry may carry credentials in
    `command`, `args` or another key, and this output goes to stdout, logs and evidence. The
    messages name the offending KEY and the managed shape, never the stored value.
    """
    data, problem = _config_object(path)
    if problem is not None:
        return False, [problem]
    problem, entry = _managed_entry_of(data)
    if problem is not None:
        return False, [problem]
    if entry is None:
        return True, []
    problems = _entry_problems(entry)
    return (not problems), problems


def _config_object(path: str | pathlib.Path) -> tuple[object | None, str | None]:
    """`(parsed config, None)`, or `(None, message)` when no config can be read at all."""
    config = pathlib.Path(path)
    if not config.is_file():
        return None, f"config not found: {config}"
    try:
        return json.loads(config.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"config is not valid JSON: {exc}"


def _managed_entry_of(data: object) -> tuple[str | None, dict | None]:
    """`(problem, entry)` — `(None, None)` when the config legitimately carries no entry."""
    if not isinstance(data, dict):
        return "config must be a JSON object", None
    servers = data.get("mcpServers")
    if servers is None:
        return None, None
    if not isinstance(servers, dict):
        return "mcpServers must be a JSON object", None
    entry = servers.get(SERVER_NAME)
    if entry is None:
        return None, None
    if not isinstance(entry, dict):
        return f"mcpServers.{SERVER_NAME} must be a JSON object", None
    return None, entry


def _entry_problems(entry: dict) -> list[str]:
    """Every invariant a PRESENT managed entry violates (it never echoes a stored value)."""
    extra = sorted(str(key) for key in entry if key not in MANAGED_ENTRY_KEYS)
    problems: list[str] = []
    if extra:
        problems.append(f"mcpServers.{SERVER_NAME} must carry exactly the managed keys "
                        f"{', '.join(MANAGED_ENTRY_KEYS)}: found the unmanaged key(s) "
                        f"{', '.join(extra)} — an unreviewed launch setting (env, credentials, "
                        "launch options) is never part of the managed entry (key names only: "
                        "values are never echoed)")
    if entry.get("command") != STUDIO_COMMAND:
        problems.append(f"mcpServers.{SERVER_NAME}.command must be {STUDIO_COMMAND!r} (the built-in "
                        "Studio server is launched through the Windows launcher): found a different "
                        "command (value omitted: an entry may carry credentials)")
    problem = _args_problem(entry)
    return problems + ([problem] if problem else [])


def _args_problem(entry: dict) -> str | None:
    """`args` must be `["/c", <absolute …\\Roblox\\mcp.bat>]` — the reviewed Studio launch."""
    args = entry.get("args")
    shape = (f'a two-element list: the shell switch "/c" followed by the ABSOLUTE, expanded path '
             f'…\\{STUDIO_BATCH_DIR}\\{STUDIO_BATCH_NAME} of this host')
    if not isinstance(args, list) or len(args) != 2 or not all(isinstance(arg, str) for arg in args):
        return (f"mcpServers.{SERVER_NAME}.args must be exactly {shape}: found a different argument "
                "list (values omitted: an entry may carry credentials)")
    switch, batch = args
    if switch != "/c":
        return (f"mcpServers.{SERVER_NAME}.args must be exactly {shape}: the first argument must be "
                "the shell switch \"/c\" (values omitted: an entry may carry credentials)")
    path = pathlib.Path(batch)
    if not path.is_absolute():
        return (f"mcpServers.{SERVER_NAME}.args must be exactly {shape}: the launcher path must be "
                "ABSOLUTE, because an unexpanded %LOCALAPPDATA% launches nothing (value omitted: an "
                "entry may carry credentials)")
    if path.name.lower() != STUDIO_BATCH_NAME or path.parent.name.lower() != STUDIO_BATCH_DIR.lower():
        return (f"mcpServers.{SERVER_NAME}.args must be exactly {shape}: the launcher path is not "
                f"`…{os.sep}{STUDIO_BATCH_DIR}{os.sep}{STUDIO_BATCH_NAME}` (value omitted: an entry "
                "may carry credentials)")
    expected = _expected_managed()
    if expected is not None and _resolved(batch) != _resolved(expected["args"][1]):
        return (f"mcpServers.{SERVER_NAME}.args must launch THIS host's Studio server "
                f"({json.dumps(expected)}): the stored launcher path names another location (value "
                "omitted: an entry may carry credentials) — re-run `merge-config`")
    return None


def managed_config_problems(path: str | pathlib.Path) -> tuple[bool, list[str], bool]:
    """`(ok, problems, entry_present)` for a concrete config — shared by probe and CLI."""
    ok, problems = validate_config(path)
    present = roblox_entry_present(path)
    problems = list(problems)
    if not problems and not present:
        problems.append(f"mcpServers.{SERVER_NAME} is missing from {path}: register the built-in "
                        "Studio server with `roblox_mcp.py merge-config`")
    return (ok and present), problems, present


# --------------------------------------------------------------------------- config merge

def merge_config(target: str | pathlib.Path | None = None, dry_run: bool = False) -> dict:
    """Idempotently merge the managed `Roblox_Studio` server into the resolved config.

    Nothing the caller can get wrong becomes a traceback: an invalid JSON target is `error` (exit 1)
    and stays untouched byte-for-byte, an equal existing entry is `unchanged`, and a DIFFERENT one
    is `conflict` (exit 3) and is never replaced — the operator decides. The resolved path is part
    of every result, so the operator sees exactly which file was (or would be) written.

    The work is split into focused steps: the creation of a missing config (`_created_result`), the
    parse of an existing one (`_parse_target`), the existing-entry decision (`_existing_result`),
    the text-surgery merge (`_merged_text`) and the atomic persistence (`_persisted_result`).
    """
    target_path = pathlib.Path(resolve_target(str(target) if target is not None else None))
    entry = managed_entry()
    base = {"path": str(target_path), "server": SERVER_NAME, "entry": entry, "written": False,
            "conflict": None, "dry_run": bool(dry_run)}
    if not target_path.is_file():
        return _created_result(base, target_path, entry, dry_run)
    try:
        text = target_path.read_text(encoding="utf-8", newline="")
    except (OSError, UnicodeDecodeError) as exc:
        return {**base, "status": "error", "message": f"cannot read {target_path}: {exc}"}
    data, problem = _parse_target(target_path, text)
    if problem is not None:
        return {**base, "status": "error", "message": problem}
    # `_parse_target` guarantees `data` is an object and `mcpServers` (when present) is an object.
    servers = data.get("mcpServers") or {}
    existing = servers.get(SERVER_NAME)
    if existing is not None:
        return _existing_result(base, target_path, existing, entry)
    merged_text, problem = _merged_text(target_path, text, entry, data, servers)
    if problem is not None:
        return {**base, "status": "error", "message": problem}
    return _persisted_result(base, target_path, merged_text, entry, dry_run)


def _created_result(base: dict, target_path: pathlib.Path, entry: dict, dry_run: bool) -> dict:
    """The result of writing a brand-new managed config (or of the dry run that would)."""
    text = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2) + "\n"
    if not dry_run:
        try:
            _write_text_exact(target_path, text)
        except OSError as exc:
            return {**base, "status": "error",
                    "message": (f"cannot write {target_path}: {exc}; nothing was written (the write "
                                "is atomic, so no partial config was left behind)")}
    return {**base, "status": "created", "written": not dry_run,
            "message": (f"{'[dry-run] would create' if dry_run else 'created'} {target_path} with "
                        f"the managed server {SERVER_NAME!r} "
                        f"({json.dumps(entry)})")}


def _parse_target(target_path: pathlib.Path, text: str) -> tuple[dict | None, str | None]:
    """`(data, None)` for a usable config object, `(None, message)` for a refused one — untouched."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (f"{target_path} is not valid JSON ({exc}); the file is left untouched and is "
                      "never overwritten")
    if not isinstance(data, dict):
        return None, f"{target_path} must contain a JSON object; left untouched"
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        return None, f"mcpServers in {target_path} must be a JSON object; the file is left untouched"
    return data, None


def _existing_result(base: dict, target_path: pathlib.Path, existing: object, entry: dict) -> dict:
    """`unchanged` for an equal entry, `conflict` (exit 3) for a different one — never replaced."""
    if existing == entry:
        return {**base, "status": "unchanged",
                "message": (f"unchanged {target_path}: server {SERVER_NAME!r} already matches the "
                            "managed definition (idempotent, no diff, no write)")}
    if not isinstance(existing, dict):
        return {**base, "status": "conflict",
                "conflict": {"server": SERVER_NAME, "existing_type": type(existing).__name__,
                             "managed": entry,
                             "differences": [f"existing entry is a {type(existing).__name__}, not a "
                                             "JSON object"]},
                "message": (f"conflict: mcpServers.{SERVER_NAME} in {target_path} is not a JSON "
                            "object; the existing value is preserved byte-for-byte and nothing is "
                            "overwritten, and it is not echoed here (an MCP entry may carry "
                            "credentials) — resolve it explicitly, then re-run")}
    keys = sorted(set(existing) | set(entry))
    differences = [key for key in keys if existing.get(key) != entry.get(key)]
    return {**base, "status": "conflict",
            "conflict": {"server": SERVER_NAME, "existing_keys": sorted(existing),
                         "managed": entry, "differences": differences},
            "message": (f"conflict: {SERVER_NAME!r} already exists in {target_path} with a different "
                        "definition; the existing entry is preserved byte-for-byte and nothing is "
                        "overwritten — resolve it explicitly, then re-run. Differing keys — "
                        + ", ".join(differences)
                        + " (values withheld: an MCP entry may carry credentials)")}


def _merged_text(target_path: pathlib.Path, text: str, entry: dict, data: dict,
                 servers: dict | None) -> tuple[str | None, str | None]:
    """`(merged text, None)` after a verified text-surgery merge, `(None, message)` when it refuses."""
    try:
        merged_text = mcp_json_merge.insert_managed_server(text, SERVER_NAME, entry)
        merged = json.loads(merged_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, f"cannot merge into {target_path} ({exc}); the file is left untouched"
    expected = dict(data)
    expected["mcpServers"] = dict(servers or {})
    expected["mcpServers"][SERVER_NAME] = entry
    if merged != expected:
        return None, (f"internal merge verification failed for {target_path}; the file is left "
                      "untouched")
    return merged_text, None


def _persisted_result(base: dict, target_path: pathlib.Path, merged_text: str, entry: dict,
                      dry_run: bool) -> dict:
    """Write the merged text atomically (unless a dry run) and report the `updated` status."""
    if not dry_run:
        try:
            _write_text_exact(target_path, merged_text)
        except OSError as exc:
            return {**base, "status": "error",
                    "message": (f"cannot write {target_path}: {exc}; the existing file keeps every "
                                "byte it had (the write is atomic and nothing partial was left "
                                "behind)")}
    return {**base, "status": "updated", "written": not dry_run,
            "message": (f"{'[dry-run] would update' if dry_run else 'updated'} {target_path}: merged "
                        f"server {SERVER_NAME!r} ({json.dumps(entry)}); all existing servers and "
                        "unrelated settings are preserved byte-for-byte")}


# --------------------------------------------------------------------------- stdio MCP session

def _forward(server: "_StdioServer", stream) -> None:
    """Forward every line of a child stdout pipe to the queue (EOF -> `None`).

    Non-JSON noise is skipped by the waiter, never fatal: a server may print a banner before it takes
    over the stream, and the number of PROTOCOL frames is evidence a failure report needs.
    """
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            server.lines.put(line)
            server.stdout_tail.append(line.rstrip("\r\n"))
            try:
                json.loads(line)
            except (ValueError, TypeError):
                continue
            server.frames += 1
    except (OSError, ValueError):
        pass
    finally:
        server.lines.put(None)


def _drain(sink: "collections.deque", stream) -> None:
    """Keep only the last few stderr lines: a server may be chatty, a report must not be."""
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            sink.append(line.rstrip("\r\n"))
    except (OSError, ValueError):
        pass


def _kernel32():
    """kernel32 with the job-object bindings this module needs (loaded once, Windows only)."""
    global _KERNEL32
    if _KERNEL32 is None:
        lib = ctypes.WinDLL("kernel32", use_last_error=True)
        lib.CreateJobObjectW.restype = ctypes.c_void_p
        lib.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        lib.AssignProcessToJobObject.restype = ctypes.c_int
        lib.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        lib.TerminateJobObject.restype = ctypes.c_int
        lib.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        lib.CloseHandle.restype = ctypes.c_int
        lib.CloseHandle.argtypes = (ctypes.c_void_p,)
        _KERNEL32 = lib
    return _KERNEL32


def _job_refusal(cause: str) -> str:
    """The refusal of a session whose process-tree cleanup cannot be guaranteed past leader exit."""
    return (f"cannot start the Studio session: {cause}, so nothing would hold the server it spawns "
            "once its launcher exits (`taskkill /T` only walks the tree of a LIVE pid); a session "
            "whose cleanup cannot be guaranteed is refused instead of started")


def _adopt_tree(proc: subprocess.Popen) -> tuple[int | None, str | None]:
    """Put the child in a JOB OBJECT, so its DESCENDANTS stay reachable after the child exits.

    `taskkill /T` walks the tree of a LIVE pid, so a launcher that starts the server and exits
    (exactly what a batch launcher may do) would put its surviving server out of reach. The job does
    not: it is adopted immediately after creation, so the processes a real launcher spawns — a shell
    reading a batch file, Studio itself, milliseconds later — are created INSIDE it.

    `(job, refusal)`: `(None, None)` on a host without job objects (a POSIX process group already
    outlives its leader), `(job, None)` once the child is adopted, and `(None, cause)` when a Windows
    host REFUSES the assignment (a job that permits no nesting, an unusable job API). Fail-CLOSED:
    without the job the only remaining cleanup is the leader-dependent `taskkill`, so the caller
    terminates the still-live tree and refuses the session — it never serves one whose bounded stop
    cannot be guaranteed.
    """
    if os.name != "nt":
        return None, None
    try:
        kernel32 = _kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None, _job_refusal("the host could not create a Windows job object")
        if kernel32.AssignProcessToJobObject(job, ctypes.c_void_p(int(proc._handle))):
            return job, None
        kernel32.CloseHandle(job)
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError) as exc:
        return None, _job_refusal(f"the Windows job-object API failed "
                                  f"({type(exc).__name__}: {exc})")
    return None, _job_refusal("the host refused to assign the session child to a job object")


def _terminate_job(job: int | None) -> None:
    """Kill every process still in the session's job object and release it (two API calls)."""
    if job is None or os.name != "nt":
        return
    try:
        kernel32 = _kernel32()
        kernel32.TerminateJobObject(job, 1)
        kernel32.CloseHandle(job)
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass


def _group_signal(proc: subprocess.Popen, sig: int) -> None:
    """Send `sig` to the group the child was started in — a group OUTLIVES its leader.

    `_StdioServer.start` starts the child in a NEW SESSION, so its pid IS the group id; `getpgid`
    cannot answer for an already reaped pid, so the child's own pid is the fallback group id.
    """
    try:
        group = os.getpgid(proc.pid)
    except OSError:
        group = proc.pid
    try:
        os.killpg(group, sig)
    except OSError:
        pass


def _terminate_tree(proc: subprocess.Popen, job: int | None = None) -> None:
    """Terminate the child AND everything it spawned (the Studio launcher starts a server).

    The direct child's liveness is NO proof that its tree is gone: a launcher can exit while the
    server it started survives, so the descendant cleanup below runs EVEN when `proc` has already
    exited. Windows: `taskkill /F /T` for a live leader, then the session's job object (`_adopt_tree`)
    for the surviving descendants; POSIX: SIGTERM, then SIGKILL, to the process group. Every step is
    bounded by TERMINATE_TIMEOUT.
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=TERMINATE_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        _group_signal(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=TERMINATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            _group_signal(proc, signal.SIGKILL)
        try:
            proc.kill()
        except OSError:
            pass
    _terminate_job(job)


def _close_stdin(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except (OSError, ValueError):
        pass


def _write_line(stream, payload: dict) -> bool:
    try:
        stream.write(json.dumps(payload) + "\n")
        stream.flush()
        return True
    except (OSError, ValueError):
        return False


def _stderr_hint(lines: list[str]) -> str:
    return f" (last stderr line: {lines[-1]})" if lines else ""


class _StdioServer:
    """ONE bounded stdio JSON-RPC session: start, request, stop — every read bounded by `budget`.

    The budget is the TOTAL wall-clock window of the session: each request waits at most what is
    left of it, so a scenario can never hang past `--timeout-seconds`.
    """

    def __init__(self, argv: list[str], cwd: str, budget: float) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.budget = float(budget)
        self.deadline = time.monotonic() + float(budget)
        self.proc: subprocess.Popen | None = None
        self.lines: "queue.Queue" = queue.Queue()
        self.stdout_tail: "collections.deque" = collections.deque(maxlen=STREAM_TAIL_LINES)
        self.stderr_tail: "collections.deque" = collections.deque(maxlen=STREAM_TAIL_LINES)
        self.frames = 0
        self.protocol_version = None
        self.server_name = None
        self.exit_code = None
        self.stage = None
        self.job: int | None = None
        self._threads: list[threading.Thread] = []

    def start(self) -> str | None:
        """Start the child; `None` on success, the failure message otherwise (never an exception).

        Fail-CLOSED on Windows: the job object is the only cleanup that reaches a server whose
        launcher already exited, so a host that refuses it gets its still-live tree terminated here
        and the refusal returned — a session whose bounded stop cannot be guaranteed never starts.
        """
        try:
            self.proc = subprocess.Popen(self.argv, cwd=self.cwd, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                         encoding="utf-8", errors="replace", bufsize=1,
                                         start_new_session=(os.name != "nt"))
        except (OSError, subprocess.SubprocessError) as exc:
            return f"cannot start `{' '.join(self.argv)}` in {self.cwd}: {type(exc).__name__}: {exc}"
        self.job, refusal = _adopt_tree(self.proc)
        if refusal is not None:
            # Kill what the launcher already spawned while the launcher is still reachable, then
            # leave no session behind: a live child here would be exactly the leak the refusal names.
            _close_stdin(self.proc)
            _terminate_tree(self.proc)
            self.exit_code = self.proc.poll()
            self.proc = None
            return refusal
        self._threads = [
            threading.Thread(target=_forward, args=(self, self.proc.stdout), daemon=True),
            threading.Thread(target=_drain, args=(self.stderr_tail, self.proc.stderr), daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        return None

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def settle(self, grace: float) -> int | None:
        """The child's exit code when it exited within `grace` seconds, else `None`."""
        assert self.proc is not None
        deadline = time.monotonic() + max(0.0, float(grace))
        while True:
            code = self.proc.poll()
            if code is not None:
                self.exit_code = code
                return code
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            time.sleep(min(0.05, left))

    def notify(self, method: str) -> bool:
        assert self.proc is not None
        return _write_line(self.proc.stdin, {"jsonrpc": "2.0", "method": method})

    def request(self, request_id: int, method: str, params: dict, stage: str
                ) -> tuple[dict | None, str | None]:
        """`(message, None)` or `(None, problem)` — a timeout is never a traceback."""
        assert self.proc is not None
        self.stage = stage
        if not _write_line(self.proc.stdin, {"jsonrpc": "2.0", "id": request_id, "method": method,
                                             "params": params}):
            return None, f"the server closed stdin before the {method} request (stage {stage})"
        message = self._await(request_id, self.remaining())
        if message is not None:
            return message, None
        code = self.settle(LIVENESS_GRACE)
        if code is not None:
            return None, (f"the server exited with code {code} during {stage}"
                          + _stderr_hint(list(self.stderr_tail))
                          + f"; it wrote only {self.frames} protocol frame(s), so this is a "
                            "launch/startup failure — not a slow Studio start")
        return None, (f"no {method} response within the {int(self.budget)}s budget (stage {stage})"
                      + _stderr_hint(list(self.stderr_tail))
                      + "; the studio session was stopped")

    def _await(self, request_id: int, timeout: float) -> dict | None:
        """The first JSON-RPC message carrying `request_id` within `timeout` seconds, or `None`."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                line = self.lines.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if line is None:
                return None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message

    def stop(self) -> None:
        """Close stdin, terminate the process TREE and let the readers drain — bounded."""
        if self.proc is None:
            return
        _close_stdin(self.proc)
        _terminate_tree(self.proc, self.job)
        self.job = None
        if self.exit_code is None:
            self.exit_code = self.proc.poll()
        for thread in self._threads:
            thread.join(timeout=LIVENESS_GRACE)

    def capture_stderr(self) -> list[str]:
        """The stderr lines the session produced SO FAR — taken BEFORE any teardown.

        The drain thread reads the pipe asynchronously, so a line the server wrote a moment ago may
        not have landed in the tail yet: the capture waits until no NEW line arrived for
        CONSOLE_QUIET_WINDOW (bounded by LIVENESS_GRACE) and returns at once when the pipe is already
        at EOF. What the session prints as it DIES stays out of scope by construction: a shutdown
        that logs "WebSocket error from proxy ... Connection reset without closing handshake" is a
        fact about the teardown, not about the scenario under test.
        """
        if self.proc is None:
            return []
        reader = self._threads[1] if len(self._threads) > 1 else None
        deadline = time.monotonic() + LIVENESS_GRACE
        seen = len(self.stderr_tail)
        while reader is not None and reader.is_alive():
            left = deadline - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(CONSOLE_QUIET_WINDOW, left))
            current = len(self.stderr_tail)
            if current == seen:                     # a quiet window: nothing new to wait for
                break
            seen = current
        return self.stderr_lines()

    def stderr_lines(self) -> list[str]:
        return [line for line in self.stderr_tail if line.strip()]


def _mcp_result_problem(value: object) -> str | None:
    """Why a `tools/call` RESULT is not a well-formed MCP answer, or `None` when it is.

    A JSON-RPC envelope without an `error` member says nothing about the TOOL: an MCP result carries
    `content` blocks and `isError` may mark a tool-level failure. `isError` is a BOOLEAN by contract,
    so every PRESENT value that is not one (`"true"`, `"false"`, `1`, `0`, `null`, a list) leaves the
    tool-level outcome unknown — it is refused instead of being coerced into a success.
    """
    if not isinstance(value, dict):
        return (f"the response carries a {type(value).__name__} instead of the MCP result object, so "
                "the answer cannot be read")
    if "isError" in value and not isinstance(value["isError"], bool):
        return ("the MCP result carries a non-boolean `isError`, so a tool-level failure cannot be "
                "ruled out")
    if value.get("isError") is True:
        return "the MCP result carries isError: true — the tool reported a FAILURE"
    content = value.get("content")
    if not isinstance(content, list) or not content:
        return "the MCP result carries no `content` list of content blocks, so the call answered nothing"
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str) \
                or not block.get("type").strip():
            return "the MCP result carries a malformed `content` block (no `type`)"
    return None


def _content_texts(value: object) -> list[str]:
    """The text of every `text` content block of an MCP result (the captured console lines)."""
    if not isinstance(value, dict) or not isinstance(value.get("content"), list):
        return []
    texts: list[str] = []
    for block in value["content"]:
        if isinstance(block, dict) and block.get("type") == "text" \
                and isinstance(block.get("text"), str):
            texts.extend(block["text"].splitlines())
    return texts


def _content_image_count(value: object) -> int:
    """The number of `image` content blocks — a screenshot is an ARTIFACT, never a verdict."""
    if not isinstance(value, dict) or not isinstance(value.get("content"), list):
        return 0
    return sum(1 for block in value["content"]
               if isinstance(block, dict) and block.get("type") == "image")


def _initialize(server: _StdioServer) -> str | None:
    """`initialize` + the initialized notification; `None` on success, the problem otherwise."""
    message, problem = server.request(
        1, "initialize",
        {"protocolVersion": "2024-11-05", "capabilities": {},
         "clientInfo": {"name": "code-factory", "version": "1"}},
        "initialize")
    if problem is not None:
        return problem
    if "error" in message:
        return (f"the server answered initialize with a JSON-RPC error: "
                f"{json.dumps(message.get('error'))}")
    result = message.get("result") if isinstance(message.get("result"), dict) else {}
    server.protocol_version = result.get("protocolVersion")
    info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
    server.server_name = info.get("name")
    if not server.notify("notifications/initialized"):
        return "the server closed stdin before the initialized notification"
    return None


def _list_tools(server: _StdioServer, probe_tool: str | None) -> tuple[list[str], str | None]:
    """`tools/list` (plus the opt-in presence assertion); `(names, None)` or `([], problem)`."""
    message, problem = server.request(2, "tools/list", {}, "tools/list")
    if problem is not None:
        return [], problem
    if "error" in message:
        return [], f"the server answered tools/list with a JSON-RPC error: {json.dumps(message.get('error'))}"
    result = message.get("result") if isinstance(message.get("result"), dict) else {}
    tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    names = [tool.get("name") for tool in tools
             if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
    if not names:
        return names, ("the server listed NO tools: an empty listing cannot run a play-test")
    if probe_tool is not None and probe_tool not in names:
        return names, (f"the tool {probe_tool!r} is not listed by the server (it lists "
                       f"{', '.join(names[:8]) or 'nothing'}): the injected probe tool must be "
                       "present for the scenario to be runnable")
    code = server.settle(min(LIVENESS_GRACE, server.remaining()))
    if code is not None:
        return names, (f"the server answered tools/list ({len(names)} tool(s) listed) and then "
                       f"exited with code {code}: the listing is green while the process is gone, "
                       "so every later tools/call fails with a closed connection")
    return names, None


# --------------------------------------------------------------------------- scenario runner

def _scenario_problems(document: object) -> list[str]:
    """Every defect that makes a scenario document unrunnable (empty when it is usable)."""
    if not isinstance(document, dict):
        return ["the scenario must be a JSON object with a `steps` list"]
    steps = document.get("steps")
    if not isinstance(steps, list):
        return ["the scenario needs a `steps` list"]
    if not steps:
        return ["a scenario with ZERO steps is not legitimate: a vacuous play-test would yield a "
                "PASS that proves nothing, so at least one step is required"]
    problems: list[str] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            problems.append(f"step {index} must be a JSON object with a `tool` name")
            continue
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            problems.append(f"step {index} needs a non-empty `tool` string (the MCP tool to call)")
        arguments = step.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            problems.append(f"step {index}: `arguments` must be a JSON object")
    screenshot = document.get("screenshot")
    if screenshot is not None and not isinstance(screenshot, str):
        problems.append("`screenshot` must be a path string when present (it is an artifact, never "
                        "the verdict)")
    return problems


def load_scenario(scenario: str | pathlib.Path) -> tuple[pathlib.Path, dict]:
    """The parsed scenario document — an unusable one is a USAGE error (exit 2)."""
    path = pathlib.Path(os.path.abspath(str(scenario)))
    if not path.is_file():
        raise UsageError(f"--scenario {path} is not an existing file: pass the scenario document "
                         "to run (nothing was started)")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"cannot read the scenario {path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"the scenario {path} is not valid JSON ({exc}); a scenario is a JSON "
                         "object with a non-empty `steps` list of {tool, arguments}") from exc
    problems = _scenario_problems(document)
    if problems:
        raise UsageError(f"the scenario {path} is not runnable: " + " ".join(problems))
    return path, document


def _timeout_problem(name: str, value: object) -> str | None:
    """Why `value` is not a usable scenario timeout, or `None` when it is.

    The contract is a BOUNDED wait, so the budget must be a real, finite number of seconds in
    (0, MAX]: zero would make every scenario fail instantly (which proves nothing), a negative value
    describes no wait at all, NaN/±inf defeat the bound, and a value beyond an hour is a hang.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (f"{name} must be a real number of seconds (found {type(value).__name__}): pass an int "
                "or a float, never a bool or a numeric string")
    try:
        float(value)
    except OverflowError:
        return (f"{name} must be convertible to a FINITE float (found {value!r}): an integer that "
                "overflows the float range cannot describe a bounded wait")
    if isinstance(value, float) and not math.isfinite(value):
        return (f"{name} must be FINITE (found {value!r}): an infinite or NaN budget would defeat "
                "the bounded wait this runner guarantees")
    if value <= 0:
        return (f"{name} must be GREATER THAN 0 (found {value!r}): a zero or negative budget would "
                "fail every scenario instantly, which proves nothing")
    if value > MAX_SCENARIO_TIMEOUT:
        return (f"{name} must be at most {int(MAX_SCENARIO_TIMEOUT)} (found {value!r}): a longer "
                "budget is a hang, not a play-test")
    return None


def scenario_argv(executable: str | None, extra_args: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The argv a scenario launch uses: the injected `--executable` seam, else the managed server.

    The managed `command` is ONE argv element (like the probe's handshake argv): `cmd.exe` is the
    executable and its `/c <…\\Roblox\\mcp.bat>` arguments follow it — never the command string
    unpacked into characters, which would launch nothing.
    """
    args = [str(arg) for arg in extra_args]
    if executable is None:
        entry = managed_entry()
        return [entry["command"], *entry["args"], *args]
    path = pathlib.Path(os.path.abspath(str(executable)))
    if not path.is_file():
        raise UsageError(f"--executable {path} is not an existing file: the injected server must be "
                         "a real executable on this host (nothing was started)")
    return [str(path), *args]


def _evidence_dir(evidence: str, create: bool) -> pathlib.Path:
    """The evidence directory: created by a runner, required to exist by a verifier."""
    path = pathlib.Path(os.path.abspath(str(evidence)))
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UsageError(f"cannot create the evidence directory {path}: {exc}") from exc
        return path
    if not path.is_dir():
        raise InputError(f"evidence directory not found: {path}; run the scenario with `roblox_mcp.py "
                         "scenario run --evidence <that directory>` before judging it")
    return path


def _call_step(server: _StdioServer, index: int, step: dict
               ) -> tuple[dict, list[str], int, bool]:
    """Run ONE scenario step; `(outcome, console lines, screenshot count, transport_failed)`.

    A transport failure (no answer, a dead server, a closed stdin) ends the session; a tool-level
    failure (`isError`, a JSON-RPC error, a malformed result) is recorded and the run continues, so
    the console capture still shows what the game logged.
    """
    tool = step["tool"].strip()
    message, problem = server.request(3 + index, "tools/call",
                                      {"name": tool, "arguments": step.get("arguments") or {}},
                                      f"tools/call {tool}")
    if problem is not None:
        return {"tool": tool, "ok": False, "error_code": None, "message": problem}, [], 0, True
    if "error" in message:
        error = message.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        return ({"tool": tool, "ok": False, "error_code": code,
                 "message": f"the server answered tools/call with a JSON-RPC error: "
                            f"{json.dumps(error)}"}, [], 0, False)
    result = message.get("result")
    texts = _content_texts(result)
    problem = _mcp_result_problem(result)
    return ({"tool": tool, "ok": problem is None, "error_code": None,
             "message": problem or "answered with a well-formed MCP result"},
            texts, _content_image_count(result), False)


def _run_steps(server: _StdioServer, steps: list[dict]
               ) -> tuple[list[dict], list[str], int]:
    """Every scenario step in order; a transport failure stops the run and marks the rest."""
    outcomes: list[dict] = []
    console: list[str] = []
    images = 0
    broken: str | None = None
    for index, step in enumerate(steps):
        if broken is not None:
            # Steps are numbered for humans: 1-based, like the printed step list, and the skipped
            # step is named as one the session never REACHED (the break happened earlier).
            outcomes.append({"tool": step["tool"], "ok": False, "error_code": None,
                             "message": f"not attempted: the session ended before step {index + 1}: "
                                        f"{broken}"})
            continue
        outcome, texts, step_images, transport_failed = _call_step(server, index, step)
        outcomes.append(outcome)
        console.extend(texts)
        images += step_images
        if transport_failed:
            broken = outcome["message"]
    return outcomes, console, images


def error_lines_of(console_lines: list[str]) -> list[str]:
    """Every line of the captured console output that is an ERROR log line."""
    return [line for line in console_lines if ERROR_LINE_PATTERN.search(line)]


def run_scenario(scenario: str | pathlib.Path, evidence: str, timeout_seconds: float,
                 executable: str | None = None, extra_args: list[str] | tuple[str, ...] = (),
                 probe_tool: str | None = None) -> dict:
    """Run ONE bounded play-test scenario and write its evidence + structured verdict.

    The verdict is DERIVED, never asserted: PASS requires the scenario to have COMPLETED (every step
    answered with a well-formed MCP result) AND the captured console output to carry no error log
    line. The console is captured BEFORE the session is stopped, so the noise a peer's own death
    prints (a proxy logging "Connection reset without closing handshake") can never become a FAIL,
    while every line logged WHILE it served still does. A screenshot may be attached and is recorded
    as an artifact only — `screenshot_is_verdict` is false in every verdict, so no run can be passed
    because an image looked right.

    A verdict is written even when nothing could be started (a missing launcher is DATA here): the
    FAIL verdict then names the reason, and `scenario verify` still judges the stored evidence.
    """
    problem = _timeout_problem("--timeout-seconds", timeout_seconds)
    if problem is not None:
        raise UsageError(problem)
    path, document = load_scenario(scenario)
    steps = document["steps"]
    argv = scenario_argv(executable, extra_args)
    directory = _evidence_dir(evidence, create=True)
    started = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(started))
    server = _StdioServer(argv, str(path.parent), timeout_seconds)
    reasons: list[str] = []
    tools: list[str] = []
    outcomes: list[dict] = []
    console: list[str] = []
    images = 0
    stderr_lines: list[str] = []
    start_problem = server.start()
    if start_problem is not None:
        reasons.append(start_problem)
        outcomes = [{"tool": step["tool"], "ok": False, "error_code": None,
                     "message": f"not attempted: {start_problem}"} for step in steps]
    else:
        try:
            handshake_problem = _initialize(server)
            if handshake_problem is not None:
                reasons.append(handshake_problem)
            else:
                tools, handshake_problem = _list_tools(server, probe_tool)
                if handshake_problem is not None:
                    reasons.append(handshake_problem)
            if reasons:
                outcomes = [{"tool": step["tool"], "ok": False, "error_code": None,
                             "message": f"not attempted: {reasons[0]}"} for step in steps]
            else:
                outcomes, console, images = _run_steps(server, steps)
        finally:
            # Snapshot the console BEFORE the stop: `stop` kills the process tree, and whatever the
            # dying peer logs afterwards is the SHUTDOWN talking, not the scenario under test.
            stderr_lines = server.capture_stderr()
            server.stop()
    console_lines = [line for line in console if line.strip()] + stderr_lines
    console_path = directory / CONSOLE_FILE
    console_text = "\n".join(console_lines) + ("\n" if console_lines else "")
    try:
        _write_text_exact(console_path, console_text)
    except OSError as exc:
        raise InputError(f"cannot write the console capture {console_path}: {exc}; no verdict can "
                         "be recorded without its evidence") from exc
    error_lines = error_lines_of(console_lines)
    completed = bool(outcomes) and all(outcome["ok"] for outcome in outcomes)
    if not completed and not reasons:
        reasons.append("the scenario did NOT complete: at least one step failed — "
                       + "; ".join(f"{outcome['tool']}: {outcome['message']}" for outcome in outcomes
                                   if not outcome["ok"])[:600])
    if error_lines:
        reasons.append(f"the captured console output logged {len(error_lines)} error line(s) — a run "
                       f"that logged an error is NEVER a pass (first: {error_lines[0][:200]})")
    verdict = "PASS" if completed and not error_lines else "FAIL"
    screenshot = document.get("screenshot")
    screenshots = ([{"path": str(_realpath(path.parent / screenshot)), "declared_by": "scenario"}]
                   if isinstance(screenshot, str) else [])
    if images:
        screenshots.append({"path": None, "declared_by": f"{images} image content block(s)"})
    record = {
        "kind": VERDICT_KIND, "schema": VERDICT_SCHEMA, "verdict": verdict,
        "completed": completed, "scenario": {"path": str(path), "name": document.get("name"),
                                             "steps": len(steps)},
        "command": argv, "cwd": server.cwd, "started_at": stamp,
        "duration_s": round(time.time() - started, 3),
        "timeout_seconds": float(timeout_seconds),
        "protocol_version": server.protocol_version, "server": server.server_name,
        "tools": tools,
        "steps": outcomes, "console": {"path": str(console_path), "lines": len(console_lines),
                                       "sha256": _sha256_text(console_text)},
        "error_lines": error_lines, "reasons": reasons or ["no failure was observed: the scenario "
                                                          "completed and its console output "
                                                          "logged no error"],
        "screenshots": screenshots, "screenshot_is_verdict": False,
        "server_exit_code": server.exit_code,
    }
    verdict_path = directory / VERDICT_FILE
    try:
        _write_text_exact(verdict_path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise InputError(f"cannot write the verdict {verdict_path}: {exc}") from exc
    return {"record": record, "verdict_path": str(verdict_path), "console_path": str(console_path),
            "verdict": verdict}


def _stored_verdict(evidence: str) -> tuple[dict, pathlib.Path]:
    """The stored verdict record of an evidence directory — a missing/broken one is an InputError."""
    directory = _evidence_dir(evidence, create=False)
    path = directory / VERDICT_FILE
    if not path.is_file():
        raise InputError(f"no verdict record in {directory}: run the scenario with `roblox_mcp.py "
                         "scenario run --evidence <that directory>` first (a missing verdict is "
                         "never a PASS)")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"the verdict record {path} cannot be read as JSON ({exc}): unreadable "
                         "evidence is never a PASS") from exc
    if not isinstance(record, dict) or record.get("kind") != VERDICT_KIND:
        raise InputError(f"{path} is not a {VERDICT_KIND!r} record: this directory holds no scenario "
                         "verdict")
    return record, directory


def scenario_verdict(evidence: str) -> dict:
    """The stored verdict as DATA: `(record, path)`; `ok` is the stored PASS/FAIL."""
    record, directory = _stored_verdict(evidence)
    return {"ok": record.get("verdict") == "PASS", "evidence": str(directory),
            "verdict": record.get("verdict"), "completed": record.get("completed"),
            "scenario": record.get("scenario"), "steps": record.get("steps"),
            "console": record.get("console"), "error_lines": record.get("error_lines") or [],
            "reasons": record.get("reasons") or [],
            "screenshot_is_verdict": record.get("screenshot_is_verdict")}


def verify_scenario(evidence: str) -> dict:
    """Strict gate: exit 0 only when the STORED verdict is HONESTLY PASS.

    The stored verdict field is not trusted: the gate re-reads the artifacts and re-derives the
    answer — the console capture must exist INSIDE this evidence directory, its sha256 must be the
    one the verdict recorded (so a later edit of the log invalidates the verdict), the capture must
    carry NO error log line, every step must be ok, and the record must state that the screenshot is
    not the verdict. A verdict that claims PASS while its own console logged an error is exactly the
    dishonesty this gate exists to refuse.
    """
    record, directory = _stored_verdict(evidence)
    problems: list[str] = []
    console = record.get("console") if isinstance(record.get("console"), dict) else {}
    console_path = console.get("path")
    if not isinstance(console_path, str) or not console_path.strip():
        problems.append("the verdict records no console capture path, so its behavioural evidence "
                        "cannot be re-read")
    else:
        path = pathlib.Path(console_path)
        if not path.is_file():
            problems.append(f"the recorded console capture {path} does not exist")
        elif not _within(path, directory):
            problems.append(f"the recorded console capture {path} is outside the evidence directory "
                            f"{directory}: a verdict must be judgeable from its own evidence")
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                problems.append(f"the recorded console capture {path} cannot be read: {exc}")
                text = None
            if text is not None:
                recorded_hash = console.get("sha256")
                if not isinstance(recorded_hash, str) or _sha256_text(text) != recorded_hash:
                    problems.append("the console capture on disk is not the one the verdict was "
                                    "derived from (sha256 mismatch): the stored verdict is STALE")
                found = error_lines_of(text.splitlines())
                if found:
                    problems.append(f"the captured console output logs {len(found)} error line(s), "
                                    f"so PASS is not honest (first: {found[0][:200]})")
    if record.get("verdict") != "PASS":
        problems.append(f"the stored verdict is {record.get('verdict')!r}, not 'PASS'")
    if record.get("completed") is not True:
        problems.append("the stored record does not prove that the scenario COMPLETED")
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    if not steps:
        problems.append("the stored record carries no step outcomes: nothing was proven")
    failed = [step.get("tool") for step in steps
              if isinstance(step, dict) and step.get("ok") is not True]
    if failed:
        problems.append("the stored record marks these steps as NOT ok: " + ", ".join(map(str, failed)))
    if record.get("screenshot_is_verdict") is not False:
        problems.append("the stored record does not state that a screenshot is never the verdict, "
                        "so a PASS invented from an image cannot be ruled out")
    if record.get("error_lines"):
        problems.append("the stored record itself records error line(s) in the console output, so "
                        "its PASS (if any) is not honest")
    return {"ok": not problems, "evidence": str(directory),
            "verdict": record.get("verdict"), "steps": len(steps), "problems": problems,
            "message": ("honest PASS: the scenario completed and its captured console output logged "
                        "no error" if not problems else
                        f"the stored verdict is NOT an honest PASS ({len(problems)} problem(s))")}


# --------------------------------------------------------------------------- capability probe

def _capability(present: bool, reason: str, detail: str | None = None) -> dict:
    return {"present": bool(present), "reason": reason, "detail": detail}


def _probe_target(target: str | None) -> tuple[pathlib.Path | None, str | None]:
    """The config the probe inspects: the resolved default, an explicit `--target`, or a reason.

    The probe is fail-soft, so an undeterminable data root is a MISSING capability with its reason
    instead of an abort — a probe never changes the exit code of the run.
    """
    try:
        return resolve_target(target), None
    except UsageError as exc:
        return None, str(exc)


def _unlocated_config_reason(problems: list[str]) -> str:
    """The `mcp_config` reason of a config location that could not be resolved.

    The cause is prefixed only when it does not already say the location is unknown: the data-root
    and home-directory refusals already carry that phrasing, and repeating it reads as a stutter.
    """
    cause = problems[0] if problems else "no target could be resolved"
    lead = "the user-scope global MCP config cannot be located"
    return cause if "cannot be located" in cause else f"{lead}: {cause}"


def probe_capabilities(repo: str | pathlib.Path, target: str | None = None,
                       check_mcp_start: bool = False) -> dict:
    """Fail-soft capability probe; a missing capability is data, never a crash.

    Static checks only (no Studio start) unless `check_mcp_start` is passed explicitly. The
    handshake is the ONLY path that starts a Studio server, and it is bounded and always terminated.
    """
    root = _checked_repo(repo)
    signals = roblox_repository_signals(root)
    caps: dict[str, dict] = {}

    batch: pathlib.Path | None = None
    try:
        batch = studio_batch_path()
    except UsageError as exc:
        caps["studio_launcher"] = _capability(False, str(exc))
    if batch is not None:
        if batch.is_file():
            caps["studio_launcher"] = _capability(
                True, f"the Studio MCP launcher is present ({batch})", str(batch))
        else:
            caps["studio_launcher"] = _capability(
                False, f"the Studio MCP launcher {batch} does not exist: Roblox Studio is not "
                       "installed here, or its MCP server was never enabled (Studio → Assistant → "
                       "Manage MCP Servers → Enable Studio as MCP server)", str(batch))

    target_path, target_problem = _probe_target(target)
    config_ok = False
    config_problems: list[str] = ([target_problem] if target_problem else [])
    entry_present = False
    if target_path is not None:
        config_ok, config_problems, entry_present = managed_config_problems(target_path)
        if config_ok:
            caps["mcp_config"] = _capability(
                True, f"the managed {SERVER_NAME!r} server entry in {target_path} matches the "
                      "definition", str(target_path))
        else:
            caps["mcp_config"] = _capability(
                False, f"the managed config {target_path} is not usable: {config_problems[0]}",
                str(target_path))
    else:
        # Fail-soft: an undeterminable config location is a MISSING capability with its reason, so
        # the probe never aborts and never reports a config it could not inspect.
        caps["mcp_config"] = _capability(False, _unlocated_config_reason(config_problems))

    handshake = None
    if check_mcp_start:
        argv = None
        if caps["studio_launcher"]["present"]:
            try:
                entry = managed_entry()
            except UsageError as exc:
                caps[HANDSHAKE_CAPABILITY] = _capability(False, str(exc))
            else:
                argv = [entry["command"], *entry["args"]]
        else:
            caps[HANDSHAKE_CAPABILITY] = _capability(
                False, f"--check-mcp-start cannot start the Studio server: "
                       f"{caps['studio_launcher']['reason']}")
        if argv is not None:
            handshake = _handshake(argv, str(root), DEFAULT_SCENARIO_TIMEOUT)
            caps[HANDSHAKE_CAPABILITY] = _capability(
                handshake["ok"], handshake["message"], handshake["cwd"])
    names = CAPABILITY_NAMES + ((HANDSHAKE_CAPABILITY,) if check_mcp_start else ())
    roblox_usable = (caps["studio_launcher"]["present"] and config_ok
                     and (not check_mcp_start or caps[HANDSHAKE_CAPABILITY]["present"]))
    return {
        "repo": str(root),
        "roblox_repository": signals["roblox"],
        "host_signals": signals,
        "capabilities": caps,
        "missing": [name for name in names if not caps[name]["present"]],
        "roblox_usable": roblox_usable,
        "check_mcp_start": bool(check_mcp_start),
        "config": str(target_path) if target_path is not None else None,
        "config_valid": config_ok,
        "config_problems": config_problems,
        "config_entry_present": entry_present,
        "handshake": handshake,
    }


def _handshake(argv: list[str], cwd: str, budget: float) -> dict:
    """One bounded initialize + tools/list session; the Studio start NEVER happens implicitly."""
    server = _StdioServer(argv, cwd, budget)
    result = {"ok": False, "stage": None, "message": "", "tools": [], "cwd": cwd,
              "command": argv, "protocol_version": None, "server": None, "exit_code": None,
              "stderr_tail": []}
    problem = server.start()
    if problem is not None:
        result["message"] = problem
        return result
    try:
        problem = _initialize(server)
        if problem is None:
            result["stage"] = "tools/list"
            result["tools"], problem = _list_tools(server, None)
        result["ok"] = problem is None
        result["message"] = (f"the Studio server answered initialize and tools/list with "
                             f"{len(result['tools'])} tool(s) and is still serving"
                             if problem is None else problem)
    finally:
        server.stop()
    result["protocol_version"] = server.protocol_version
    result["server"] = server.server_name
    result["exit_code"] = server.exit_code
    result["stderr_tail"] = server.stderr_lines()[-20:]
    return result


def format_probe(result: dict) -> str:
    lines = ["roblox-mcp capability probe (fail-soft: a missing capability is data, never a crash)",
             f"repo: {' '.join(result['host_signals']['details']) or 'no Roblox marker'}"]
    for name, cap in result["capabilities"].items():
        lines.append(f"  {name.replace('_', '-') + ':':<24}{'present' if cap['present'] else 'missing'}"
                     f" — {cap['reason']}")
    lines.append(f"  {'config:':<24}{result['config'] or 'undetermined'}")
    lines.append(f"  {'roblox_usable:':<24}{'yes' if result['roblox_usable'] else 'no'}")
    lines.append("  missing: " + (", ".join(name.replace("_", "-") for name in result["missing"])
                                 or "none"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so help and messages never crash a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# The fields of a PARSED task that say WHAT the task operates. Everything around them — YAML
# comments, `models`, `repo_path`, `mode`, launch instructions — is wiring, and the classifier never
# sees it: the shipped template's own instructional comments name Roblox, so classifying them would
# activate the specialist on an unrelated task.
BUSINESS_SCOPE_SCALARS: tuple[str, ...] = ("title", "description", "user_story")
BUSINESS_TEST_TEXT_KEYS: tuple[str, ...] = ("scenario", "expected_results")


def business_scope(task: dict) -> str:
    """The business-scope text of a PARSED task: only the fields that say WHAT the task operates."""
    parts = [str(task.get(key) or "") for key in BUSINESS_SCOPE_SCALARS]
    for item in task.get("acceptance_criteria") or []:
        parts.append(str(item.get("criterion") or "") if isinstance(item, dict) else str(item))
    for item in task.get("business_tests") or []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in BUSINESS_TEST_TEXT_KEYS)
    return "\n".join(part for part in parts if part.strip())


def _file_scope_text(raw: str) -> str:
    """The classification text of a task FILE read from disk.

    A file that parses as a task contributes only its normalized business-scope fields — comments
    and metadata are dropped by the canonical parser. A file that is NOT a task is classified
    verbatim; the downstream METADATA stripping of `scope_text` still applies to it.
    """
    try:
        task, _warnings = task_parser.parse_text(raw)
    except task_parser.TaskError:
        return raw
    return business_scope(task)


def _task_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    path = pathlib.Path(args.task_file)
    if not path.is_file():
        raise UsageError(f"--task-file {path} is not an existing file: pass the task to classify")
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise UsageError(f"cannot read the task file {path}: {exc}") from exc
    return _file_scope_text(raw)


def _emit(args: argparse.Namespace, payload: dict, human: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if getattr(args, "as_json", False)
          else human)


def _probe_out_path(value: str, evidence_root: pathlib.Path) -> pathlib.Path:
    """`--out` accepts a directory (writes the probe file inside) or a `*.json` file path.

    The RESOLVED path is validated exactly like `--target`: its parent directory must already exist
    and the symlinks are resolved, so a probe artifact never lands somewhere the operator never
    named. The resolved path is echoed by the caller.
    """
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = evidence_root / path
    path = pathlib.Path(os.path.abspath(str(path)))
    path = path if path.suffix.lower() == ".json" else path / PROBE_FILE_NAME
    if not path.parent.is_dir():
        raise UsageError(f"--out {path}: the parent directory {path.parent} does not exist; create "
                         "only the directories you mean and re-run (nothing was written)")
    resolved = pathlib.Path(_realpath(path))
    if not resolved.parent.is_dir():
        raise UsageError(f"--out {path} resolves outside an existing directory "
                         f"({resolved.parent}); nothing was written")
    return resolved


def cmd_decide(args: argparse.Namespace) -> int:
    result = decide_applicability(_task_text(args), repo=args.repo)
    _emit(args, {"applicable": result["applicable"], "reasons": result["reasons"]},
          format_decision(result))
    return 0


def cmd_merge_config(args: argparse.Namespace) -> int:
    result = merge_config(target=args.target, dry_run=args.dry_run)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["status"] in ("conflict", "error"):
        prefix = "CONFLICT" if result["status"] == "conflict" else "ERROR"
        print(f"{prefix}: {result['message']}", file=sys.stderr)
    else:
        print(result["message"])
    if result["status"] == "conflict":
        return EXIT_CONFLICT
    if result["status"] == "error":
        return 1
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    path = pathlib.Path(os.path.abspath(args.path))
    if not path.is_file():
        raise UsageError(f"--path {path} is not an existing file: pass the MCP config to validate "
                         "(a missing config is not a bad one)")
    ok, problems = validate_config(path)
    if args.as_json:
        print(json.dumps({"path": str(path), "ok": ok, "problems": problems}, indent=2,
                         ensure_ascii=False))
        return 0 if ok else 1
    if ok:
        print(f"OK {path}: the managed {SERVER_NAME!r} entry (if present) carries exactly the "
              f"managed keys — command {STUDIO_COMMAND!r} and the absolute "
              "…/Roblox/mcp.bat launcher argument")
        return 0
    print(f"FAIL {path}: {len(problems)} invariant(s) violated")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_probe(args: argparse.Namespace) -> int:
    result = probe_capabilities(args.repo, target=args.target,
                                check_mcp_start=args.check_mcp_start)
    out = _probe_out_path(args.out, pathlib.Path(result["repo"])) if args.out else None
    if out is not None:
        result["out"] = str(out)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_probe(result))
    if out is not None:
        try:
            _write_text_exact(out, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"ERROR: cannot write {out}: {exc}", file=sys.stderr)
            return 1
        if not args.as_json:
            print(f"  capabilities file: {out}")
    return 0


def cmd_scenario_run(args: argparse.Namespace) -> int:
    result = run_scenario(args.scenario, args.evidence, args.timeout_seconds,
                          executable=args.executable, extra_args=args.arg or (),
                          probe_tool=args.probe_tool)
    record = result["record"]
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{record['verdict']}: {record['scenario']['steps']} step(s) of "
              f"{record['scenario']['path']} in {record['duration_s']}s — "
              f"{record['console']['lines']} console line(s) captured, "
              f"{len(record['error_lines'])} error line(s)")
        for outcome in record["steps"]:
            print(f"  {'ok  ' if outcome['ok'] else 'FAIL'} {outcome['tool']}: {outcome['message']}")
        for reason in record["reasons"]:
            print(f"  - {reason}")
        print(f"  verdict: {result['verdict_path']}")
        print(f"  console: {result['console_path']}")
    return 0 if record["verdict"] == "PASS" else 1


def cmd_scenario_verdict(args: argparse.Namespace) -> int:
    verdict = scenario_verdict(args.evidence)
    if args.as_json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    else:
        print(f"{verdict['verdict']}: {verdict['evidence']} "
              f"(completed={verdict['completed']}, {len(verdict['steps'] or [])} step(s), "
              f"{len(verdict['error_lines'])} console error line(s); a screenshot is never the "
              "verdict)")
        for reason in verdict["reasons"]:
            print(f"  - {reason}")
    return 0 if verdict["ok"] else 1


def cmd_scenario_verify(args: argparse.Namespace) -> int:
    result = verify_scenario(args.evidence)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(("OK " if result["ok"] else "FAIL ") + result["message"])
        print(f"  evidence: {result['evidence']}")
        for problem in result["problems"]:
            print(f"  - {problem}")
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="roblox_mcp.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("decide", help="applicability of the Roblox Studio path for a task")
    p.add_argument("--repo", required=True,
                   help="repository root (must be an existing directory; its Roblox markers are "
                        "required)")
    p.add_argument("--text", default=None,
                   help="task/user-story/acceptance text (an EMPTY --text is legitimate: it means "
                        "no Roblox work is asked for)")
    p.add_argument("--task-file", dest="task_file", default=None,
                   help="file whose text is used (task.yaml or plain text)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("merge-config",
                       help=f"register the managed {SERVER_NAME} server in a mcp.json")
    p.add_argument("--target", default=None,
                   help="config to merge into (default: the USER-SCOPE GLOBAL CLI config, "
                        "$KIMI_CODE_HOME/mcp.json when set else <home>/.kimi-code/mcp.json); an "
                        "override is symlink-resolved and its parent directory must exist")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="report what would happen without writing")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_merge_config)

    p = sub.add_parser("validate-config", help=f"invariants of a managed {SERVER_NAME} entry")
    p.add_argument("--path", required=True, help="config to check (must be an existing file)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_validate_config)

    p = sub.add_parser("probe", help="fail-soft capability probe (missing capabilities are data)")
    p.add_argument("--repo", required=True, help="repository root of the Roblox project")
    p.add_argument("--target", default=None,
                   help="managed config to inspect (default: the user-scope global CLI config)")
    p.add_argument("--check-mcp-start", action="store_true", dest="check_mcp_start",
                   help="opt-in: start the Studio MCP server and verify a bounded JSON-RPC "
                        "handshake (never started implicitly)")
    p.add_argument("--out", default=None,
                   help=f"write the probe result as JSON here (a directory receives "
                        f"{PROBE_FILE_NAME}; a *.json path is used literally; the parent directory "
                        "must exist)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("scenario", help="the deterministic play-test scenario runner")
    scenarios = p.add_subparsers(dest="scenario_cmd", required=True)

    q = scenarios.add_parser("run", help="run ONE scenario and record its evidence + verdict")
    q.add_argument("--scenario", required=True,
                   help="scenario document (JSON: an object with a non-empty `steps` list of "
                        "{tool, arguments})")
    q.add_argument("--evidence", required=True,
                   help="evidence directory receiving console.log and verdict.json (created if "
                        "missing)")
    q.add_argument("--timeout-seconds", dest="timeout_seconds", type=float,
                   default=DEFAULT_SCENARIO_TIMEOUT,
                   help=f"total budget of the run, GREATER THAN 0 and at most "
                        f"{int(MAX_SCENARIO_TIMEOUT)} (default: {int(DEFAULT_SCENARIO_TIMEOUT)})")
    q.add_argument("--executable", default=None,
                   help="injected server executable (hermetic tests); must be an existing file")
    q.add_argument("--arg", action="append", default=[],
                   help="extra argument for the injected --executable (repeatable, empty rejected)")
    q.add_argument("--probe-tool", dest="probe_tool", default=None,
                   help="also assert this tool is present in the server's tools/list")
    q.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    q.set_defaults(func=cmd_scenario_run)

    q = scenarios.add_parser("verdict", help="read back the stored verdict of an evidence directory")
    q.add_argument("--evidence", required=True, help="evidence directory of one scenario run")
    q.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    q.set_defaults(func=cmd_scenario_verdict)

    q = scenarios.add_parser("verify",
                             help="strict gate: exit 0 only for an HONEST stored PASS verdict")
    q.add_argument("--evidence", required=True, help="evidence directory of one scenario run")
    q.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    q.set_defaults(func=cmd_scenario_verify)
    return ap


def _validate_args(args: argparse.Namespace) -> None:
    """Every validated argument boundary that argparse cannot express itself (exit 2)."""
    if args.cmd == "decide" and args.text is None and not args.task_file:
        raise UsageError("decide requires --text or --task-file (an EMPTY --text is legitimate: it "
                         "means no Roblox work is asked for, so the role stays off)")
    if args.cmd == "scenario" and args.scenario_cmd == "run":
        problem = _timeout_problem("--timeout-seconds", args.timeout_seconds)
        if problem is not None:
            raise UsageError(problem)
        for value in args.arg or ():
            if not str(value).strip():
                raise UsageError("--arg must not be empty: an empty argument is a mistake, never a "
                                 "meaningful server argument")


def main() -> int:
    use_utf8_output()
    ap = build_parser()
    args = ap.parse_args()
    try:
        _validate_args(args)
        return args.func(args)
    except UsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return 2
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

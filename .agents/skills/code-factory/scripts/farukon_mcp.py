#!/usr/bin/env python3
"""
Deterministic Farukon MCP helpers for the Code Factory — zero LLM tokens.

The factory activates the farukon-expert role only when the CURRENT business task really operates the
Farukon trading platform. Two independent conditions must hold, and each one alone is enough to keep
the role OFF:
  (a) the repository HOSTS the platform — a `farukon_mcp` crate (`farukon_mcp/Cargo.toml`, or a
      `farukon_mcp` workspace member of the root `Cargo.toml`) or an existing `.kimi-code/mcp.json`
      that already carries a `farukon` server entry; BUILDABILITY additionally needs a manifest on
      disk (`farukon_mcp/Cargo.toml` or the declared member's own `Cargo.toml`) — a `members = [...]`
      declaration whose directory is missing builds nothing;
  (b) the TASK SCOPE names a platform OPERATION (build/run/test/start/stop/debug, connectors,
      portfolio snapshots, message log, web health) bound to an explicit platform OBJECT — weighted
      keyword scoring that requires an explicit platform SUBJECT (`farukon`, the `farukon_mcp`
      crate, `platform`, the MCP server and its eight tools, connectors, portfolio/replay/web
      instances, cargo) AND an OPERATION term whose object is that subject, with at least ONE
      occurrence of that operation term unbound to a documentation/media object
      (`NON_PLATFORM_OBJECTS`, three words either side) AND a weighted score of at least
      `SCOPE_APPLICABLE_SCORE`: the project name alone, a task that only pins a model, an operation
      on some other subject ("run the parser test suite"), an operation whose only platform-ish word
      is a generic identity word ("run the integration tests for the parser", "update the runtime
      config of the logger") and an operation on DOCUMENTATION ("run the documentation build", even
      next to a Farukon README edit) all stay `not_applicable`; task-file METADATA (`models:`,
      `repo_path:`, `commit_exclude:`) is not scope and is stripped before classification. Every
      decision carries a REASON that names the platform subjects matched, the operation terms bound
      to the platform, the operation terms DISCARDED as bound elsewhere, the score and the host
      signals. Never a model call.

Subcommands (all deterministic, stdlib only):
  decide           applicability of the farukon-expert role for a task (--repo, --text/--task-file)
  merge-config     idempotently merge the `farukon` server into <repo>/.kimi-code/mcp.json
                   (--target, --dry-run)
  probe            fail-soft capability probe: cargo, farukon_mcp buildability, the managed config
                   (a DRIFTED registration is reported as drift with the differing KEY names, never
                   their values), and with --check-mcp-start a bounded newline-delimited JSON-RPC
                   handshake that verifies all eight Farukon MCP tools, reports the protocol version
                   the SERVER answers, the protocol STAGE a failure reached, the child's exit code,
                   its own stdout/stderr tails, the post-tools/list liveness and (with --probe-tool)
                   a real tools/call (--target, --out)
  validate-config  invariants of a managed `farukon` entry (--path)
  record-session   run ONE bounded live MCP session — the managed cargo entry, the project's OWN
                   registration (`--mode registration`: the shape the MCP client really launches,
                   e.g. `node .kimi-code/farukon-mcp-launcher.js`; only a REVIEWED `cargo` or `node`
                   launch is accepted, and a launcher script must live inside the platform root) or
                   an already-built binary inside the platform root (`--mode direct --executable`) —
                   and store it as an immutable evidence record (--repo, --evidence)
  verify-reproduction  strict gate over those records: an OBSERVED launch failure before a single
                   protocol frame (stage, exit code or JSON-RPC error, the launcher's own stderr) AND
                   a healthy eight-tool control session (--repo, --evidence)
  verify-sessions  strict gate over those records: five DISTINCT CONSECUTIVE healthy live sessions
                   of this project, EACH proving a real `tools/call` answered with a well-formed MCP
                   result (no `isError`, a `content` list, no JSON-RPC error) AND PRESERVING that
                   result in the record — a list-only record or one without `tool_result` never
                   counts, an unsuccessful attempt restarts the sequence, and evidence that cannot be
                   parsed fails closed naming the file (.log/.txt console captures are ignored)
                   (--repo, --evidence)

Exit codes:
  0  success — including a `not_applicable` decision, a DEGRADED `probe`, a FAILED recorded session
     (a missing capability or a dead server is DATA, never a crash or a failed run) and a passing
     verification gate
  1  a real error: an unreadable input, a `--repo` that is not a directory, a `--target` that escapes
     the repository, a `--repo` that is not a Farukon platform root (merge-config refuses to write a
     server into a project that does not host the platform), a config that is not valid JSON (such a
     target is then NEVER overwritten), a write that cannot happen (a directory or an unwritable
     target, reported instead of a traceback; the write is atomic, so an existing file keeps its
     bytes) — and a FAILED verification gate (`verify-reproduction`/`verify-sessions`: the live proof
     is missing, weak or belongs to another project; the problems name exactly what is missing)
  2  usage error (argparse)
  3  `merge-config` conflict: a DIFFERENT `farukon` entry already exists — it is preserved
     byte-for-byte and reported, never silently replaced

Managed entry shape (deterministic, one definition):
  {"command": "cargo", "args": ["run", "--quiet", "-p", "farukon_mcp", "--"], "cwd": <repo>}
`cwd` is the absolute, normalized repository path: `cargo run -p farukon_mcp` must resolve the
workspace from the platform root, not from whichever directory the Kimi session happens to use.

Determinism and safety of the helpers themselves:
  - every decision carries a REASON and is keyword/rule based, never a model call;
  - `merge-config` reads the target as text and inserts only the `mcpServers.farukon` member, so every
    unrelated byte (other servers, settings, line endings) survives; an equal entry is `unchanged`,
    a different one is a `conflict` with exit 3 and the file untouched; the write itself is ATOMIC
    (a same-directory temp file plus `os.replace`), so a failure never leaves half a config behind;
  - no diagnostic echoes a value an MCP entry supplies (`command`, `args`, extra keys): an entry may
    carry credentials, and this output lands in logs and evidence — the messages name the offending
    KEY and the managed shape, never the stored value;
  - `probe` never runs a build unless `--check-mcp-start` is passed, and that handshake is BOUNDED
    (30 s protocol reads, up to 30 min for a cold cargo build) and always terminates the child
    process TREE (a Node launcher's server is a grandchild); a cargo that is on PATH but cannot
    answer `--version` is UNUSABLE, not present. A DEAD server is DIAGNOSED, never misdiagnosed: the
    result carries the protocol stage that was reached, the child's exit code, its own stdout/stderr
    tails and the number of protocol frames, so a launcher whose build fails before `initialize` is
    reported as a launch/build failure instead of a slow cold build. A server that answers the WHOLE
    listing and then exits is not green either (`post_list_alive`), because the listing alone says
    nothing about whether a later `tools/call` can be answered;
  - the live proof is EVIDENCE, not a claim: `record-session` stores one bounded session as an
    immutable JSON record and `verify-reproduction` / `verify-sessions` judge those records
    STRICTLY (a failed launch must be OBSERVED, the healthy control must list all eight tools and
    still be serving, and five distinct CONSECUTIVE sessions are required, EACH of them proving a
    real `tools/call` answered with a well-formed MCP result — no `isError`, a `content` list, no
    JSON-RPC error. A listing alone never fills a slot and a failed or malformed attempt restarts the
    sequence). Both gates exit 1 naming what is missing;
  - an explicit exclusion phrase (`no mcp`, `without farukon`) wins over every platform keyword:
    deactivating the role by mistake costs a missed specialist run, activating it by mistake puts a
    cargo/MCP session on unrelated work — the conservative direction is deliberate.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import pathlib
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # `factory_preflight.py` loads this helper BY PATH (deliberately independent of `sys.path`), so the
    # shared sibling merge module has to be made importable here instead of being assumed.
    sys.path.insert(0, str(_SCRIPTS_DIR))
import mcp_json_merge  # noqa: E402  (the sibling path fix above must run first)
import task_parser  # noqa: E402  (the sibling path fix above must run first)

SERVER_NAME = "farukon"
CRATE = "farukon_mcp"
CRATE_MANIFEST = pathlib.Path(CRATE) / "Cargo.toml"
COMMAND = "cargo"
MANAGED_ARGS: list[str] = ["run", "--quiet", "-p", CRATE, "--"]
CONFIG_RELPATH = pathlib.Path(".kimi-code") / "mcp.json"
PROBE_FILE_NAME = "farukon-mcp-probe.json"

EXIT_CONFLICT = 3
VERSION_PROBE_TIMEOUT = 5
HANDSHAKE_TIMEOUT = 30
COLD_BUILD_TIMEOUT = 1800
TERMINATE_TIMEOUT = 10
STDERR_TAIL_LINES = 200
STDOUT_TAIL_LINES = 200
# How long an already-answered stage is watched for the death of the child before the stage is called
# green. A server that exits right after `tools/list` keeps its listing, so the listing alone is never
# the verdict; the process is gone and every later `tools/call` fails with a closed connection.
LIVENESS_GRACE = 2.0
# The number of distinct HEALTHY live sessions the platform proof requires (`verify-sessions`).
SESSIONS_REQUIRED = 5
SESSION_KIND = "farukon-mcp-session"
SESSION_MODES: tuple[str, ...] = ("managed", "registration", "direct")
SESSION_SCHEMA = 1
SESSION_STAMP = "%Y%m%dT%H%M%SZ"

# The eight tools the farukon-expert role is allowed to work through. A handshake that does not list
# all of them is a degraded platform path, never a green one.
FARUKON_TOOLS: tuple[str, ...] = (
    "farukon_build", "farukon_cargo_test", "farukon_start", "farukon_stop",
    "farukon_connector_state", "farukon_portfolio_snapshot", "farukon_message_log",
    "farukon_web_health",
)

CAPABILITY_NAMES: tuple[str, ...] = ("cargo", "farukon_mcp_buildable", "mcp_config")
HANDSHAKE_CAPABILITY = "mcp_start"
# The public refusal of an unusable handshake timeout: it must be greppable, and it states that
# nothing was launched (an unusable budget is refused BEFORE any Popen).
TIMEOUT_REFUSAL = "refused before starting"

APPLICABLE = "applicable"
NOT_APPLICABLE = "not_applicable"
SCOPE_APPLICABLE_SCORE = 3

# Weighted platform keywords (word-boundary matched, optional plural), split into the two things a
# decision needs. IDENTITY words name the platform or its packaging but never say what to DO with it:
# they carry ONE point each, so naming the project alone can never reach SCOPE_APPLICABLE_SCORE.
# OPERATION words name work on the running platform (3 = the word names the operation itself, 2 = a
# clear operation, 1 = a weak hint that only counts together with another one); plain `build` sits
# with `run`/`test`/`debug` because building the platform IS the specialist's work. A scope activates
# the role only when it carries BOTH an IDENTITY term and a SUBJECT-BOUND OPERATION term: "Run/Test/
# Debug/Build the platform" is a platform operation, an unrelated task that merely says run/test
# about its own subject ("run the parser test suite") names no identity, and an operation on
# DOCUMENTATION ("run the documentation build") is bound to the documentation, not to the platform
# (see `NON_PLATFORM_OBJECTS`). Keyword/rule based on purpose: the decision must be reproducible and
# auditable, never a model call.
FARUKON_IDENTITY_TERMS: tuple[tuple[str, int], ...] = (
    ("farukon", 1), ("farukon_mcp", 1), ("platform", 1), ("mcp server", 1), ("mcp tool", 1),
    ("mcp", 1), ("stdio", 1), ("tool", 1), ("integration", 1), ("runtime", 1),
)
FARUKON_OPERATION_TERMS: tuple[tuple[str, int], ...] = (
    ("platform operation", 3), ("connector state", 3), ("portfolio snapshot", 3),
    ("cargo build", 2), ("cargo test", 2), ("cargo run", 2), ("connector", 2), ("portfolio", 2),
    ("message log", 2), ("web health", 2), ("replay", 2), ("quik", 2), ("live session", 2),
    ("start", 2), ("stop", 2), ("deploy", 2), ("run", 2), ("test", 2), ("debug", 2), ("operate", 2),
    ("restart", 2), ("launch", 2), ("build", 2),
    ("cargo", 1), ("snapshot", 1), ("health", 1), ("session", 1), ("instance", 1),
)
FARUKON_TERMS: tuple[tuple[str, int], ...] = FARUKON_IDENTITY_TERMS + FARUKON_OPERATION_TERMS
# The operation words alone: a scope without one of them is identity only and keeps the role OFF.
FARUKON_OPERATION_NAMES: frozenset[str] = frozenset(term for term, _ in FARUKON_OPERATION_TERMS)
# The identity words alone: an operation word with no identity term is somebody else's task.
FARUKON_IDENTITY_NAMES: frozenset[str] = frozenset(term for term, _ in FARUKON_IDENTITY_TERMS)

# PLATFORM SUBJECTS. An operation is the platform's only when it is bound to an OBJECT the platform
# owns: the platform itself, the `farukon_mcp` crate, the MCP server and its eight tools, or a
# platform object (connectors, portfolio snapshot, message log, web health, replay, live session, a
# web instance, the crate's cargo). `integration` and `runtime` are NOT subjects — they name a topic,
# so "run the integration tests for the parser" or "update the runtime config of the logger" stays
# out of scope however many operation words it carries. `stdio` and a bare `tool` are transports and
# generic nouns, never the platform object itself.
FARUKON_PLATFORM_OBJECTS: tuple[str, ...] = (
    "farukon", "farukon_mcp", "platform", "mcp server", "mcp tool", "mcp",
    "connector", "portfolio", "message log", "web health", "replay", "quik",
    "live session", "snapshot", "instance", "cargo", *FARUKON_TOOLS,
)

# SUBJECT BINDING. An operation is about the object it operates. These words name documentation/media
# subjects, and a plural/`-ing` form folds onto them. When one of them sits within
# OPERATION_OBJECT_WINDOW words of an operation occurrence, THAT occurrence operates on the
# documentation, not on the platform — "update the Farukon README and run the documentation build"
# names the platform only as the thing being documented. Any other occurrence of the same verb (e.g.
# "run cargo test for the platform" in the same task) still binds to the platform.
NON_PLATFORM_OBJECTS: frozenset[str] = frozenset({
    "documentation", "doc", "readme", "manual", "guide", "changelog", "website", "site", "report",
    "diagram", "docstring", "note", "blog", "tutorial",
})
OPERATION_OBJECT_WINDOW = 3
_WORD = re.compile(r"[A-Za-z][A-Za-z_-]*")

# Explicit exclusions win over platform keywords: a task in a Farukon repository that is deliberately
# NOT about the platform must not activate the cargo/MCP path.
FARUKON_EXCLUSIONS: tuple[str, ...] = (
    r"\bno\s+mcp\b",
    r"\bwithout\s+(the\s+)?(farukon\s+)?mcp\b",
    r"\bwithout\s+(the\s+)?farukon\b",
    r"\bno\s+farukon\b",
    r"\bfarukon\s+is\s+not\s+involved\b",
    r"\bdo(es)?\s+not\s+(use|touch|change|modify)\s+(the\s+)?(farukon|mcp)\b",
    r"\bnot\s+a\s+farukon\s+task\b",
    r"\bfarukon\s+(operations?\s+)?(is|are|stays?)\s+out\s+of\s+scope\b",
    r"\bunrelated\s+to\s+(the\s+)?farukon\b",
)

# Task-file METADATA is not task SCOPE: `models:`, `repo_path:` and `commit_exclude:` describe how the
# run is WIRED, never what it operates. `models.farukon_expert` merely pins the specialist's model, so
# a task that names only that key must not read as platform operation.
METADATA_KEYS: tuple[str, ...] = ("models", "repo_path", "commit_exclude", "mode", "task_type")
_METADATA_BLOCK = re.compile(
    r"^(?:" + "|".join(METADATA_KEYS) + r")\s*:[^\n]*(?:\n[ \t]+[^\n]*)*", re.MULTILINE)
_MODELS_TOKEN = re.compile(r"\bmodels(?:_used)?\.[a-z_]+\b", re.IGNORECASE)
_MEMBER_ARRAY = re.compile(r"members\s*=\s*\[(.*?)\]", re.DOTALL)


class InputError(Exception):
    """A real error the CLI must report as a message + exit 1 (never a traceback)."""


# --------------------------------------------------------------------------- repository identity

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


def workspace_members(text: str) -> list[str]:
    """Every `members = [...]` entry of a Cargo.toml (multi-line arrays included)."""
    members: list[str] = []
    for match in _MEMBER_ARRAY.finditer(text or ""):
        members.extend(token.strip() for token in re.findall(r'"([^"]*)"', match.group(1)))
    return members


def _names_crate(member: str) -> bool:
    normalized = member.strip().replace("\\", "/").rstrip("/")
    return normalized == CRATE or normalized.endswith("/" + CRATE)


def farukon_entry_present(path: str | pathlib.Path) -> bool:
    """`True` when a config file carries an object under `mcpServers.farukon`."""
    return _farukon_entry(path) is not None


def _member_manifest(root: pathlib.Path, member: str) -> pathlib.Path | None:
    """The `Cargo.toml` a declared workspace member really has on disk, or `None`.

    A `members = [...]` ENTRY is only a declaration: `members = ["crates/farukon_mcp"]` builds
    nothing unless that directory and its manifest exist. The path is resolved under `root`, so a
    member may not point outside the repository.
    """
    relative = member.strip().replace("\\", "/").rstrip("/")
    candidate = pathlib.Path(os.path.abspath(str(root / relative / "Cargo.toml")))
    try:
        inside = os.path.commonpath([str(candidate), str(root)]) == str(root)
    except ValueError:                       # a Windows drive mismatch is not inside either
        return None
    return candidate if inside and candidate.is_file() else None


def farukon_platform_signals(repo: str | pathlib.Path) -> dict:
    """Host signature of a Farukon platform repository — EVIDENCE, never a decision on its own."""
    root = pathlib.Path(os.path.abspath(str(repo)))
    details: list[str] = []
    crate_manifest = root / CRATE_MANIFEST
    crate_present = crate_manifest.is_file()
    if crate_present:
        details.append(f"crate manifest {CRATE_MANIFEST.as_posix()} present")
    workspace_member = False
    workspace_manifest: pathlib.Path | None = None
    declared: list[str] = []
    root_manifest = root / "Cargo.toml"
    manifest_text = _read_text(root_manifest) if root_manifest.is_file() else None
    if manifest_text is not None:
        declared = [member for member in workspace_members(manifest_text) if _names_crate(member)]
        for member in declared:
            workspace_manifest = _member_manifest(root, member)
            if workspace_manifest is not None:
                break
        workspace_member = workspace_manifest is not None
        if workspace_member:
            details.append(f"root Cargo.toml lists the workspace member {declared[0]!r} and its "
                           f"manifest {workspace_manifest.relative_to(root).as_posix()!r} exists")
        elif declared:
            details.append(f"root Cargo.toml declares the workspace member {declared[0]!r} but its "
                           "Cargo.toml is MISSING: a declaration alone builds nothing")
    config = root / CONFIG_RELPATH
    mcp_entry = farukon_entry_present(config)
    if mcp_entry:
        details.append(f"{CONFIG_RELPATH.as_posix()} already carries a {SERVER_NAME!r} server entry")
    return {
        "root": str(root),
        "crate_manifest": CRATE_MANIFEST.as_posix() if crate_present else None,
        "workspace_member": workspace_member,
        "workspace_member_manifest": (workspace_manifest.relative_to(root).as_posix()
                                      if workspace_manifest is not None else None),
        "mcp_entry": mcp_entry,
        "platform": crate_present or bool(declared) or mcp_entry,
        "details": details,
    }


def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise InputError(f"repository root does not exist: {root}")
    return root


def _resolved(path: str | pathlib.Path) -> str:
    """`path` with every symlink resolved; a path that does not exist YET resolves through its
    nearest existing ancestor, so a `--target` under a symlinked directory is still seen.

    `os.path.lexists` is deliberate: a DANGLING symlink counts as existing, and `realpath` then
    answers the path it points AT — writing through it would escape the repository even though the
    lexical path looks contained.
    """
    current = pathlib.Path(os.path.abspath(str(path)))
    missing: list[str] = []
    while not os.path.lexists(str(current)) and current.parent != current:
        missing.append(current.name)
        current = current.parent
    resolved = pathlib.Path(os.path.realpath(str(current)))
    for name in reversed(missing):
        resolved = resolved / name
    return os.path.normcase(str(resolved))


def _within(child: str | pathlib.Path, parent: str | pathlib.Path) -> bool:
    """`True` when the RESOLVED `child` is strictly inside the RESOLVED `parent`.

    Both sides are resolved through `realpath` (case-insensitive paths on Windows), so a symlink that
    lives inside the repository but points outside it never passes for a contained target.
    """
    child_s = _resolved(child)
    parent_s = _resolved(parent)
    if child_s == parent_s:
        return False
    try:
        return os.path.commonpath([child_s, parent_s]) == parent_s
    except ValueError:                      # different drive letters on Windows
        return False


# --------------------------------------------------------------------------- applicability

def _present(low: str, name: str) -> bool:
    """`True` when `name` occurs in the already-lowercased `low` as a whole word (plural allowed)."""
    return bool(re.search(r"\b" + re.escape(name) + r"s?\b", low))


def _find_terms(text: str, terms: tuple[tuple[str, int], ...]) -> list[tuple[str, int]]:
    low = (text or "").lower()
    return [(term, weight) for term, weight in terms if _present(low, term)]


def _find_names(text: str, names: tuple[str, ...]) -> list[str]:
    """The `names` present in `text` as whole words (optional plural), in vocabulary order."""
    low = (text or "").lower()
    return [name for name in names if _present(low, name)]


def _object_key(word: str) -> str:
    """A word folded onto its object key: lowercase, `-` treated as a space, one plural `s` dropped."""
    key = word.lower().replace("-", " ").strip()
    return key[:-1] if len(key) > 3 and key.endswith("s") else key


def _operates_on_other_object(text: str, match: "re.Match[str]") -> bool:
    """`True` when THIS occurrence of an operation names a non-platform (documentation) object.

    `OPERATION_OBJECT_WINDOW` words before and after the verb are inspected: "run the documentation
    build" binds `run` (and `build`, whose preceding words hold the object) to the documentation.
    """
    before = _WORD.findall(text[:match.start()])[-OPERATION_OBJECT_WINDOW:]
    after = _WORD.findall(text[match.end():])[:OPERATION_OBJECT_WINDOW]
    return any(_object_key(word) in NON_PLATFORM_OBJECTS for word in before + after)


def bound_operations(scope: str) -> list[str]:
    """The operation terms of a METADATA-STRIPPED scope that operate on the platform itself.

    An operation term counts only when at least one of its occurrences survives the subject binding;
    a verb that merely shares the task with a platform name ("run the documentation build" next to a
    Farukon README edit) is not a platform operation.
    """
    low = (scope or "").lower()
    bound: list[str] = []
    for term, _weight in FARUKON_OPERATION_TERMS:
        if any(not _operates_on_other_object(low, match)
               for match in re.finditer(r"\b" + re.escape(term) + r"s?\b", low)):
            bound.append(term)
    return bound


def scope_text(text: str) -> str:
    """The task text with its YAML METADATA removed — the scope is what the task OPERATES.

    A task file carries wiring next to its scope (`models:`, `repo_path:`, `commit_exclude:`,
    `mode:`, `task_type:`), and `models.farukon_expert` merely pins the specialist's model. Both are
    dropped before classification, so a task whose only mention of the platform is a model key stays
    `not_applicable`.
    """
    without_metadata = _METADATA_BLOCK.sub(" ", text or "")
    return _MODELS_TOKEN.sub(" ", without_metadata)


def decide_applicability(text: str, repo: str | pathlib.Path) -> dict:
    """Classify the farukon-expert role as `applicable`/`not_applicable` WITH a reason.

    The decision is one chain of focused steps so each stays readable on its own: the host signature
    (`farukon_platform_signals`), the METADATA-stripped scope (`scope_text`), the matched vocabulary
    and its subject binding (`_scope_facts`), then the three refusal messages in their fixed order —
    an explicit exclusion, a repository that does not host the platform, a scope that names no
    platform operation — and finally the applicable reason.
    """
    signals = farukon_platform_signals(_checked_repo(repo))
    scope = scope_text(text)
    exclusions = _exclusions(scope)
    facts = _scope_facts(scope)
    evidence = {"host_signals": signals, "scope_terms": facts.terms, "exclusions": exclusions,
                "scope_score": facts.score}
    refusal = (_exclusion_refusal(exclusions) or _host_refusal(signals)
               or _scope_refusal(signals, facts))
    if refusal is not None:
        return {"decision": NOT_APPLICABLE, "evidence": evidence, "reason": refusal}
    return {"decision": APPLICABLE, "evidence": evidence,
            "reason": _applicable_reason(signals, facts)}


# The matched scope vocabulary of ONE task text: the weighted terms it names (`terms`), the bound
# platform `operations`, the operation terms `unbound` to the platform (bound elsewhere), the
# identity words, the explicit platform `subjects` and the weighted `score` of every term together.
ScopeFacts = collections.namedtuple(
    "ScopeFacts", "terms score operations unbound identity subjects")


def _exclusions(scope: str) -> list[str]:
    """Every explicit exclusion phrase the scope carries (they win over all platform keywords)."""
    low = (scope or "").lower()
    return [pattern for pattern in FARUKON_EXCLUSIONS if re.search(pattern, low)]


def _scope_facts(scope: str) -> ScopeFacts:
    """The matched vocabulary of a METADATA-stripped scope, with its subject binding resolved."""
    matched = _find_terms(scope, FARUKON_TERMS)
    terms = [term for term, _ in matched]
    operations = [term for term in bound_operations(scope) if term in terms]
    return ScopeFacts(
        terms=terms,
        score=sum(weight for _, weight in matched),
        operations=operations,
        unbound=[term for term in terms
                 if term in FARUKON_OPERATION_NAMES and term not in operations],
        identity=[term for term in terms if term in FARUKON_IDENTITY_NAMES],
        subjects=_find_names(scope, FARUKON_PLATFORM_OBJECTS),
    )


def _exclusion_refusal(exclusions: list[str]) -> str | None:
    """The refusal of an explicitly deactivated task, or `None` when no exclusion was named."""
    if not exclusions:
        return None
    return ("the task text explicitly excludes Farukon/MCP scope ("
            + ", ".join(exclusions) + "); the farukon-expert role and the eight Farukon "
            "MCP tools stay off")


def _host_refusal(signals: dict) -> str | None:
    """The refusal of a repository that does not host the platform, or `None` when it does."""
    if signals["platform"]:
        return None
    return (f"the repository {signals['root']} does not host the Farukon platform (no "
            f"{CRATE_MANIFEST.as_posix()}, no {CRATE} workspace member in the root "
            f"Cargo.toml and no {SERVER_NAME!r} server entry in "
            f"{CONFIG_RELPATH.as_posix()}): a configured MCP server alone never "
            "activates the role")


def _scope_refusal(signals: dict, facts: ScopeFacts) -> str | None:
    """The refusal of a scope without a bound platform operation, or `None` when it has one."""
    if (facts.score >= SCOPE_APPLICABLE_SCORE and facts.operations and facts.subjects):
        return None
    listed = ", ".join(facts.terms[:6]) or "none"
    elsewhere = (f"; operation terms bound to another subject ({', '.join(facts.unbound[:6])}) do "
                 "not count" if facts.unbound else "")
    return (f"the repository hosts the Farukon platform ({'; '.join(signals['details'])}), "
            f"but the task text carries no platform-operation scope (scope_score={facts.score}; "
            f"matched terms: {listed}; platform subjects: "
            f"{', '.join(facts.subjects[:6]) or 'none'}; operation terms: "
            f"{', '.join(facts.operations[:6]) or 'none'}; identity terms: "
            f"{', '.join(facts.identity[:6]) or 'none'}{elsewhere}); the scope needs BOTH an "
            "explicit platform subject (the platform, the crate, the MCP server, a "
            "connector, a portfolio snapshot, a replay, a web instance or one of the "
            "Farukon MCP tools) and an operation bound to it — naming the project, "
            "hosting the platform or pinning `models.farukon_expert` alone never "
            "activates the role, a generic identity word (`integration`, `runtime`) is "
            "no platform subject, and an operation on some other subject (a "
            "documentation build, a parser test suite) stays out of scope")


def _applicable_reason(signals: dict, facts: ScopeFacts) -> str:
    """The reason of an applicable decision: the host signature and the bound platform operation."""
    return (f"the repository hosts the Farukon platform ({'; '.join(signals['details'])}) and "
            f"the task text names a platform operation bound to the platform "
            f"({', '.join(facts.operations[:6])}; platform subjects: "
            f"{', '.join(facts.subjects[:6])}; identity: {', '.join(facts.identity[:6])}; "
            f"scope_score={facts.score}): the farukon-expert role and the eight Farukon MCP tools "
            "apply")


def format_decision(result: dict) -> str:
    evidence = result["evidence"]
    signals = evidence["host_signals"]
    return "\n".join([
        result["decision"],
        f"reason: {result['reason']}",
        "evidence: host_signals={host}; scope_terms={terms}; exclusions={excl}; scope_score={score}".format(
            host=", ".join(signals["details"]) or "none",
            terms=", ".join(evidence["scope_terms"]) or "-",
            excl=", ".join(evidence["exclusions"]) or "-",
            score=evidence["scope_score"],
        ),
    ])


# --------------------------------------------------------------------------- managed entry

def managed_entry(repo: str | pathlib.Path) -> dict:
    """The deterministic `farukon` server definition for a repository root."""
    return {"command": COMMAND, "args": list(MANAGED_ARGS),
            "cwd": os.path.abspath(str(repo))}


# A managed entry is EXACTLY these keys: anything else (`env`, credentials, launch options) is an
# unreviewed launch setting, and the exact-managed-entry contract refuses it.
MANAGED_ENTRY_KEYS: tuple[str, ...] = ("command", "args", "cwd")


# --------------------------------------------------------------------------- config validation

def _farukon_entry(path: str | pathlib.Path) -> dict | None:
    """The `mcpServers.farukon` object of a config FILE, or `None` when it is absent/malformed."""
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    entry = servers.get(SERVER_NAME)
    return entry if isinstance(entry, dict) else None


def _same_path(one: str | pathlib.Path, other: str | pathlib.Path) -> bool:
    """`True` when two spellings name ONE path once symlinks and case are resolved."""
    return _resolved(one) == _resolved(other)


def validate_config(path: str | pathlib.Path | None = None, data: object = None
                    ) -> tuple[bool, list[str]]:
    """Invariants of a managed `farukon` entry: `(ok, problems)` — problems are data, not crashes.

    The `farukon` entry is validated only when it is present: a project without the Farukon server is
    a valid config (it simply does not use the platform path), while a PRESENT entry must be exactly
    the managed definition — a hand-edited variant would launch something other than the reviewed
    platform crate. `cwd` must be an ABSOLUTE path to a directory that EXISTS: the launch resolves
    the workspace from it, so a path that cannot be entered cannot work.

    NO diagnostic echoes a value the entry supplies: an MCP entry may carry credentials in `command`,
    `args`, `cwd` or another key, and this output goes to stdout, logs and evidence. The messages
    name the offending KEY and the managed shape, never the stored value.

    The work is split into focused steps so each one stays readable on its own: reading the file
    (`_config_object`), locating the managed entry (`_managed_entry_of`) and the invariants of a
    PRESENT entry (`_entry_problems`, one helper per key).
    """
    if data is None:
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


def _config_object(path: str | pathlib.Path | None) -> tuple[object | None, str | None]:
    """`(parsed config, None)`, or `(None, message)` when no config can be read at all."""
    if path is None:
        return None, "a config path is required"
    config = pathlib.Path(path)
    if not config.is_file():
        return None, f"config not found: {config}"
    try:
        return json.loads(config.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"config is not valid JSON: {exc}"


def _managed_entry_of(data: object) -> tuple[str | None, dict | None]:
    """`(problem, farukon entry)` — `(None, None)` when the config legitimately carries no entry."""
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
    return (_key_problems(entry) + _command_problems(entry) + _args_problems(entry)
            + _cwd_problems(entry))


def _key_problems(entry: dict) -> list[str]:
    """The entry must carry ONLY the managed keys — an extra key is an unreviewed launch setting."""
    extra = sorted(str(key) for key in entry if key not in MANAGED_ENTRY_KEYS)
    if not extra:
        return []
    return [f"mcpServers.{SERVER_NAME} must carry exactly the managed keys "
            f"{', '.join(MANAGED_ENTRY_KEYS)}: found the unmanaged key(s) {', '.join(extra)} — an "
            "unreviewed launch setting (env, credentials, launch options) is never part of the "
            "managed entry (key names only: values are never echoed)"]


def _command_problems(entry: dict) -> list[str]:
    """The entry must launch the reviewed command (the platform crate runs through cargo)."""
    if entry.get("command") == COMMAND:
        return []
    return [f"mcpServers.{SERVER_NAME}.command must be {COMMAND!r} (the platform crate is run through "
            "cargo): found a different command (value omitted: an entry may carry credentials)"]


def _args_problems(entry: dict) -> list[str]:
    """The argument list must be exactly the managed one, in order and with no extra entry."""
    args = entry.get("args")
    if isinstance(args, list) and len(args) == len(MANAGED_ARGS) \
            and [a for a in args if isinstance(a, str)] == MANAGED_ARGS:
        return []
    return [f"mcpServers.{SERVER_NAME}.args must be exactly {json.dumps(MANAGED_ARGS)}: found a "
            "different argument list (values omitted: an entry may carry credentials)"]


def _cwd_problems(entry: dict) -> list[str]:
    """`cwd` must be a non-empty ABSOLUTE path to a directory that EXISTS (the workspace anchor)."""
    cwd = entry.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return [f"mcpServers.{SERVER_NAME}.cwd must be a non-empty absolute path: found no usable "
                "value (value omitted: an entry may carry credentials)"]
    if not pathlib.Path(cwd).is_absolute():
        return [f"mcpServers.{SERVER_NAME}.cwd must be ABSOLUTE (the platform workspace must resolve "
                "independently of the session's working directory): found a relative path (value "
                "omitted: an entry may carry credentials)"]
    if not pathlib.Path(cwd).is_dir():
        return [f"mcpServers.{SERVER_NAME}.cwd must be an EXISTING directory (the launch resolves the "
                "workspace from it, so a path that cannot be entered cannot work): found a path that "
                "is not an existing directory (value omitted: an entry may carry credentials)"]
    return []


def managed_config_problems(path: str | pathlib.Path, expected_cwd: str | pathlib.Path | None = None
                            ) -> tuple[bool, list[str], bool]:
    """`(ok, problems, entry_present)` for a concrete project config — shared by probe and CLI.

    `expected_cwd` is the platform root the CALLER is probing. An entry whose `cwd` names another
    (even a perfectly existing) directory launches the crate from the wrong workspace, so it is
    reported unusable here — `validate-config` alone cannot know the root it was meant for. The
    stored `cwd` is NOT echoed (an entry may carry a credential in any value); only the MANAGED root
    the caller expects is named.
    """
    ok, problems = validate_config(path)
    present = farukon_entry_present(path)
    problems = list(problems)
    if ok and expected_cwd is not None:
        cwd = (_farukon_entry(path) or {}).get("cwd")
        if isinstance(cwd, str) and not _same_path(cwd, expected_cwd):
            problems.append(
                f"mcpServers.{SERVER_NAME}.cwd does not point at the managed platform root "
                f"{os.path.abspath(str(expected_cwd))!r}: `{COMMAND} run --quiet -p {CRATE} --` would "
                "resolve the workspace from another directory (the stored value is not echoed: an "
                "entry may carry credentials), so this managed config is not usable for this "
                "repository")
            ok = False
    if not problems and not present:
        problems.append(f"mcpServers.{SERVER_NAME} is missing from {path}: run `farukon_mcp.py "
                        f"merge-config --repo <platform-repo> --target {path}`")
    return (ok and present), problems, present


# --------------------------------------------------------------------------- surgical JSON merge
# The text surgery lives in the shared stdlib sibling `mcp_json_merge.py`, which this helper imports
# and the Chrome DevTools twin imports as well: the merge machinery is identical, while each helper
# keeps its OWN semantics on top (server name, managed entry, refusals, conflict reporting, atomic
# persistence, redacted diagnostics).


def _read_text_exact(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


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


# --------------------------------------------------------------------------- config merge

def merge_config(repo: str | pathlib.Path, target: str | pathlib.Path | None = None,
                 dry_run: bool = False) -> dict:
    """Idempotently merge the managed `farukon` server into a project's `.kimi-code/mcp.json`.

    Everything the caller can get wrong is a REPORTED status, never a traceback: a repository that
    does not host the platform and a target outside the repository are `error` (exit 1, nothing
    written), an invalid JSON target is `error` and stays untouched byte-for-byte, an equal existing
    entry is `unchanged`, and a DIFFERENT one is `conflict` (exit 3) and is never replaced — the
    operator decides.

    The work is split into focused steps so each one stays small and testable on its own: the
    precondition refusal (`_merge_refusal`), the creation of a missing config (`_created_result`),
    the parse of an existing one (`_parse_target`), the existing-entry decision (`_existing_result`),
    the text-surgery merge (`_merged_text`) and the atomic persistence (`_persisted_result`).
    """
    root = pathlib.Path(os.path.abspath(str(repo)))
    target_path = (pathlib.Path(os.path.abspath(str(target))) if target
                   else root / CONFIG_RELPATH)
    entry = managed_entry(root)
    base = {"repo": str(root), "path": str(target_path), "server": SERVER_NAME, "entry": entry,
            "written": False, "conflict": None, "dry_run": bool(dry_run)}
    refusal = _merge_refusal(root, target_path)
    if refusal is not None:
        return {**base, "status": "error", "message": refusal}
    if not target_path.is_file():
        return _created_result(base, target_path, entry, dry_run)
    try:
        text = _read_text_exact(target_path)
    except OSError as exc:
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


def _merge_refusal(root: pathlib.Path, target_path: pathlib.Path) -> str | None:
    """The message of a refused merge (missing repo, not a platform root, escaping target), or None."""
    if not root.is_dir():
        return f"repository root does not exist: {root}; nothing was written"
    signals = farukon_platform_signals(root)
    if not signals["platform"]:
        return (f"{root} is not a Farukon platform root (no "
                f"{CRATE_MANIFEST.as_posix()}, no {CRATE} workspace member in the root "
                f"Cargo.toml and no {SERVER_NAME!r} entry in "
                f"{CONFIG_RELPATH.as_posix()}): a managed cargo server is never merged "
                "into a project that does not host the platform; nothing was written")
    if not _within(target_path, root):
        return (f"--target {target_path} is outside the repository root {root}: the "
                "managed config must stay inside the project it is managed for; nothing "
                "was written")
    return None


def _created_result(base: dict, target_path: pathlib.Path, entry: dict, dry_run: bool) -> dict:
    """The result of writing a brand-new managed config (or of the dry run that would)."""
    text = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2) + "\n"
    if not dry_run:
        try:
            _write_text_exact(target_path, text)
        except OSError as exc:
            return {**base, "status": "error",
                    "message": (f"cannot write {target_path}: {exc}; nothing was written (the "
                                "write is atomic, so no partial config was left behind)")}
    return {**base, "status": "created", "written": not dry_run,
            "message": (f"created {target_path} with the managed server {SERVER_NAME!r} "
                        f"(cargo run --quiet -p {CRATE} --, cwd {entry['cwd']})")}


def _parse_target(target_path: pathlib.Path, text: str) -> tuple[dict | None, str | None]:
    """`(data, None)` for a usable config object, `(None, message)` for a refused one — untouched."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (f"{target_path} is not valid JSON ({exc}); the file is left untouched and "
                      "is never overwritten")
    if not isinstance(data, dict):
        return None, f"{target_path} must contain a JSON object; left untouched"
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        return None, (f"mcpServers in {target_path} must be a JSON object; the file is left "
                      "untouched")
    return data, None


def _existing_result(base: dict, target_path: pathlib.Path, existing: object, entry: dict) -> dict:
    """`unchanged` for an equal entry, `conflict` (exit 3) for a different one — never replaced."""
    if existing == entry:
        return {**base, "status": "unchanged",
                "message": (f"unchanged {target_path}: server {SERVER_NAME!r} already matches the "
                            "managed definition (idempotent, no diff)")}
    if not isinstance(existing, dict):
        return {**base, "status": "conflict",
                "conflict": {"server": SERVER_NAME,
                             "existing_type": type(existing).__name__, "managed": entry,
                             "differences": [f"existing entry is a "
                                             f"{type(existing).__name__}, not a JSON object"]},
                "message": (f"conflict: mcpServers.{SERVER_NAME} in {target_path} is not a JSON "
                            "object; the existing value is preserved byte-for-byte and nothing is "
                            "overwritten, and it is not echoed here (an MCP entry may carry "
                            "credentials) — resolve it explicitly, then re-run")}
    keys = sorted(set(existing) | set(entry))
    differences = [k for k in keys if existing.get(k) != entry.get(k)]
    return {**base, "status": "conflict",
            "conflict": {"server": SERVER_NAME, "existing_keys": sorted(existing),
                         "managed": entry, "differences": differences},
            "message": (f"conflict: {SERVER_NAME!r} already exists in {target_path} with a "
                        "different definition; the existing entry is preserved byte-for-byte and "
                        "nothing is overwritten — resolve it explicitly, then re-run. Differing "
                        "keys — " + ", ".join(differences) + " (values withheld: an MCP entry may "
                        "carry credentials)")}


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
                        f"server {SERVER_NAME!r} (cargo run --quiet -p {CRATE} --, cwd "
                        f"{entry['cwd']}); all existing servers and unrelated settings are preserved "
                        "byte-for-byte")}


# --------------------------------------------------------------------------- stdio MCP handshake

def _pump(stream, sink: "queue.Queue", state: dict) -> None:
    """Forward every line of a child stdout pipe to a queue (EOF -> `None`).

    `state` is the evidence record of the stream: the number of PROTOCOL frames (parsable JSON
    lines) and the raw stdout tail. A failure report must be able to say that a dead server never
    wrote a single frame, instead of guessing that it is still building.
    """
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            sink.put(line)
            state["tail"].append(line.rstrip("\r\n"))
            try:
                json.loads(line)
            except (ValueError, TypeError):
                continue
            state["frames"] = int(state["frames"]) + 1
    except (OSError, ValueError):
        pass
    finally:
        sink.put(None)


def _drain(stream, sink: "collections.deque") -> None:
    """Keep only the last few stderr lines: a cold cargo build writes plenty, a report must not."""
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            sink.append(line)
    except (OSError, ValueError):
        pass


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Terminate the child AND the process it spawned (cargo run starts the platform binary)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=TERMINATE_TIMEOUT)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=TERMINATE_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass


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


def _await_response(lines: "queue.Queue", request_id: int, timeout: float) -> dict | None:
    """The first JSON-RPC message carrying `request_id` within `timeout` seconds, or `None`.

    Non-JSON noise on stdout (a build banner, a log line) is skipped, never fatal: MCP servers write
    protocol frames on stdout, but a cold `cargo run` may print before the binary takes over.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            line = lines.get(timeout=min(remaining, 1.0))
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


def _initialize_request(request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "code-factory", "version": "1"}}}


def _stderr_lines(errors: "collections.deque") -> list[str]:
    """The captured stderr lines as plain strings (empty lines dropped, newlines trimmed)."""
    return [line.rstrip("\r\n") for line in errors if line.strip()]


def _stderr_hint(lines: list[str]) -> str:
    return f" (last stderr line: {lines[-1]})" if lines else ""


def _exit_code(proc: subprocess.Popen, grace: float) -> int | None:
    """The child's exit code when it has exited within `grace` seconds, else `None`.

    The grace is bounded on purpose: an ALIVE server must not be mistaken for a dead one (it keeps
    the cold-build hint), and a dead one must not be mistaken for a slow build (that is exactly the
    misdiagnosis behind the owner-visible `-32000`).
    """
    deadline = time.monotonic() + max(0.0, float(grace))
    while True:
        code = proc.poll()
        if code is not None:
            return code
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.05, remaining))


def _timeout_problem(name: str, value: object) -> str | None:
    """Why `value` is not a usable handshake timeout, or `None` when it is.

    The handshake's contract is a BOUNDED wait, so the budget must be a real number of seconds:
    a bool is not a number of seconds, a numeric string is a caller's formatting mistake, and a NaN
    or an infinity would turn "give up after N seconds" into "never", which defeats the contract.
    Zero is LEGITIMATE: it means "make one immediate, no-wait attempt". Negative is not.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (f"{name} must be a real number of seconds (found {type(value).__name__}): pass an int "
                "or a float, never a bool or a numeric string")
    # Every accepted value is converted into a deadline (`float(timeout)`), so a value the conversion
    # cannot carry — an int larger than the float range — must be refused HERE, before a process is
    # started: the OverflowError would otherwise escape after the child is already running.
    try:
        float(value)
    except OverflowError:
        return (f"{name} must be convertible to a FINITE float (found {value!r}): an integer that "
                "overflows the float range cannot describe a bounded wait")
    # An int is always finite and exact; only a float can carry NaN/±inf (and converting a huge int to
    # float to test it would overflow, so it is never converted here).
    if isinstance(value, float) and not math.isfinite(value):
        return (f"{name} must be FINITE (found {value!r}): an infinite or NaN budget would defeat the "
                "bounded wait this handshake guarantees")
    if value < 0:
        return (f"{name} must be NON-NEGATIVE (found {value!r}): a negative budget cannot describe a "
                "wait — use 0 for an immediate, no-wait attempt")
    return None


def _tool_result_problem(value: object) -> str | None:
    """Why a `tools/call` RESULT is not a proven success, or `None` when it is.

    A JSON-RPC envelope without an `error` member says nothing about the TOOL: an MCP result carries
    `content` blocks, `isError` may mark a tool-level failure, and a server may answer an empty
    object, a bare string or no `result` at all. Any of those used to be recorded as a successful
    call — the exact `-32000` class hidden behind a well-formed envelope (review R4).
    """
    if value is None:
        return ("the response carries no `result` member at all: nothing answered the tools/call")
    if not isinstance(value, dict):
        return (f"`result` is a {type(value).__name__}, not the MCP object with a `content` list, so "
                "the answer cannot be read")
    if "isError" in value and not isinstance(value.get("isError"), bool):
        return ("the MCP result carries a non-boolean `isError`, so a tool-level failure cannot be "
                "ruled out")
    if value.get("isError") is True:
        return ("the MCP result carries isError: true — the server reported a TOOL-level failure, so "
                "the call did not succeed")
    content = value.get("content")
    if not isinstance(content, list) or not content:
        return ("the MCP result carries no `content` list of content blocks, so the call answered "
                "nothing")
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str) \
                or not block.get("type").strip():
            return ("the MCP result carries a malformed `content` block (no `type`), so the answer is "
                    "not a well-formed tool result")
    return None


def _bounded_result(value: object, limit: int = 4000) -> object:
    """The tool result as EVIDENCE, bounded so one huge answer cannot bloat the record.

    The response is preserved (the review asks for it): a value whose JSON exceeds `limit` characters
    is replaced by a marked prefix instead of being dropped silently.
    """
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"unserializable": type(value).__name__}
    if len(text) <= limit:
        return value
    return {"truncated": True, "characters": len(text), "json_prefix": text[:limit]}


def mcp_start_handshake(repo: str | pathlib.Path, argv: list[str] | None = None,
                        first_response_timeout: float = COLD_BUILD_TIMEOUT,
                        response_timeout: float = HANDSHAKE_TIMEOUT,
                        probe_tool: str | None = None,
                        env: dict | None = None) -> dict:
    """Bounded newline-delimited JSON-RPC handshake against a stdio Farukon MCP server.

    Starts the managed `cargo run --quiet -p farukon_mcp --`, an injected `argv` (the seam the offline
    tests use with a fake server), or the OWNER'S OWN registration — the platform really registers
    `node .kimi-code/farukon-mcp-launcher.js`, a Node wrapper that starts the server on the INHERITED
    stdio and exits with its status, so the probe must verify exactly the shape the client runs and
    not only the cargo shape the factory would like it to be.

    Then: `initialize`, the initialized notification, `tools/list` and — only when `probe_tool` names
    one of the eight tools — a real `tools/call`. `tools/list` says a tool EXISTS; only a call says
    the server can still answer, so that last stage is OPT-IN (a live platform may start an instance).

    Every read is bounded. DEATH IS EVIDENCE, never a guess: the result reports the protocol `stage`
    that was reached, the child's `exit_code` (None while it still runs), its own `stdout_tail` /
    `stderr_tail`, the number of `protocol_frames` it wrote and its `error_code` when it answered with
    a JSON-RPC error — so a launcher that dies before a single frame is reported as a launch/build
    failure (stage `initialize`, exit 1, its stderr lines), never as a slow cold build. A server that
    answers the WHOLE listing and then dies is not green either: `post_list_alive` records that the
    process was gone right after `tools/list`.

    The child process TREE is terminated on every path (a Node wrapper's server is a grandchild), so
    a probe never leaves a platform instance behind. Failures are DATA: `ok=False` with a message,
    never an exception.

    TIMEOUT POLICY (validated BEFORE any process is started, because a budget that defeats the
    bounded wait makes the probe hang instead of reporting): a timeout must be a real int/float
    (a bool or a numeric string is refused), FINITE (NaN and ±inf are refused) and NON-NEGATIVE.
    ZERO is legitimate and means "start the server and make one immediate, no-wait attempt": the
    handshake then reports the bounded failure ("no initialize response within 0s") like any other
    silent server. A negative value is refused — it describes no wait at all. A refused value yields
    the structured `ok=False` result naming the parameter, and no child process is launched.
    """
    command = list(argv) if argv else [COMMAND, *MANAGED_ARGS]
    result = {"command": command, "cwd": os.path.abspath(str(repo)), "ok": False,
              "protocol_version": None, "server": None, "tools": [],
              "missing_tools": list(FARUKON_TOOLS), "message": "",
              "stage": None, "exit_code": None, "error_code": None,
              "stdout_tail": [], "stderr_tail": [], "protocol_frames": 0,
              "post_list_alive": None, "probed_tool": None, "tool_result": None}
    problem = (_timeout_problem("first_response_timeout", first_response_timeout)
               or _timeout_problem("response_timeout", response_timeout))
    if problem is not None:
        result["message"] = f"{TIMEOUT_REFUSAL} `{' '.join(command)}`: {problem}"
        return result
    if probe_tool is not None and probe_tool not in FARUKON_TOOLS:
        # The probe only ever calls one of the eight platform tools: a name outside that contract is a
        # caller mistake, refused before a child is started instead of silently probing nothing.
        result["message"] = (f"probe_tool must name one of the {len(FARUKON_TOOLS)} Farukon tools "
                             f"({', '.join(FARUKON_TOOLS)}): found {probe_tool!r}; omit probe_tool to "
                             "skip the tools/call stage instead")
        return result
    try:
        proc = subprocess.Popen(command, cwd=str(repo), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", bufsize=1, env=env,
                                start_new_session=(os.name != "nt"))
    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = (f"cannot start `{' '.join(command)}` in {result['cwd']}: "
                             f"{type(exc).__name__}: {exc}")
        return result
    state = {"frames": 0, "tail": collections.deque(maxlen=STDOUT_TAIL_LINES)}
    lines: "queue.Queue" = queue.Queue()
    errors: "collections.deque" = collections.deque(maxlen=STDERR_TAIL_LINES)
    out_thread = threading.Thread(target=_pump, args=(proc.stdout, lines, state), daemon=True)
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, errors), daemon=True)
    out_thread.start()
    err_thread.start()

    def grace_of(budget: float) -> float:
        """The bounded window in which a stage watches for its child's death."""
        return min(LIVENESS_GRACE, max(float(budget), 0.0))

    def snapshot(grace: float) -> int | None:
        """Record the child's exit code and its OWN output; `None` while it still runs."""
        exit_code = _exit_code(proc, grace)
        if exit_code is not None:
            # The pipes are closed once the child is gone, so both readers finish; the join is bounded
            # anyway because a wrapper may have handed stdout to a process that is still alive.
            wait = max(LIVENESS_GRACE, grace)
            out_thread.join(timeout=wait)
            err_thread.join(timeout=wait)
        result["exit_code"] = exit_code
        result["stdout_tail"] = list(state["tail"])
        result["stderr_tail"] = _stderr_lines(errors)
        result["protocol_frames"] = int(state["frames"])
        return exit_code

    def died(stage: str, grace: float, what: str) -> bool:
        """`True` (and the failure is written into the result) when the child EXITED at `stage`."""
        code = snapshot(grace)
        result["stage"] = stage
        if code is None:
            return False
        result["message"] = (
            f"the server exited with code {code} during {what} (stage {stage}) from "
            f"`{' '.join(command)}` in {result['cwd']}"
            + _stderr_hint(result["stderr_tail"])
            + f"; it never answered and only {result['protocol_frames']} protocol frame(s) were "
              "written, so this is a launcher/build failure — not a slow cold build")
        return True

    try:
        if not _write_line(proc.stdin, _initialize_request(1)):
            result["stage"] = "initialize"
            result["message"] = "the server closed stdin before the initialize request"
            return result
        init = _await_response(lines, 1, first_response_timeout)
        if init is None:
            if died("initialize", grace_of(first_response_timeout), "initialize"):
                return result
            result["message"] = (f"no initialize response within {int(first_response_timeout)}s from "
                                 f"`{' '.join(command)}` in {result['cwd']}"
                                 + _stderr_hint(result["stderr_tail"])
                                 + "; the child is still running and a cold cargo build takes long — "
                                   "warm the target directory and re-run")
            return result
        if "error" in init:
            error = init.get("error")
            result["stage"] = "initialize"
            result["error_code"] = error.get("code") if isinstance(error, dict) else None
            result["message"] = (f"the server answered initialize with a JSON-RPC error: "
                                 f"{json.dumps(error)}")
            return result
        init_result = init.get("result") if isinstance(init.get("result"), dict) else {}
        result["protocol_version"] = init_result.get("protocolVersion")
        info = init_result.get("serverInfo") if isinstance(init_result.get("serverInfo"), dict) else {}
        result["server"] = info.get("name")
        _write_line(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        if not _write_line(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                        "params": {}}):
            result["stage"] = "tools/list"
            result["message"] = "the server closed stdin before the tools/list request"
            return result
        listing = _await_response(lines, 2, response_timeout)
        if listing is None:
            if died("tools/list", grace_of(response_timeout), "tools/list"):
                return result
            result["message"] = (f"no tools/list response within {int(response_timeout)}s"
                                 + _stderr_hint(result["stderr_tail"]))
            return result
        if "error" in listing:
            error = listing.get("error")
            result["stage"] = "tools/list"
            result["error_code"] = error.get("code") if isinstance(error, dict) else None
            result["message"] = (f"the server answered tools/list with a JSON-RPC error: "
                                 f"{json.dumps(error)}")
            return result
        listing_result = listing.get("result") if isinstance(listing.get("result"), dict) else {}
        tools = listing_result.get("tools") if isinstance(listing_result.get("tools"), list) else []
        names = [tool.get("name") for tool in tools
                 if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
        missing = [name for name in FARUKON_TOOLS if name not in names]
        result.update(tools=names, missing_tools=missing)
        # LIVENESS: the listing is green while the process may already be gone. Watch the child for a
        # bounded grace, so the verdict is never taken from the listing alone.
        post_exit = snapshot(grace_of(response_timeout))
        result["post_list_alive"] = post_exit is None
        if post_exit is not None:
            result["stage"] = "tools/list"
            result["message"] = (f"the server answered tools/list ({len(names)} tool(s) listed) and "
                                 f"then exited with code {post_exit}: the listing is green while the "
                                 "process is gone, so every later tools/call fails with a closed "
                                 "connection" + _stderr_hint(result["stderr_tail"]))
            return result
        if missing:
            result["stage"] = "tools/list"
            result["message"] = ("the server answered the handshake but does not expose every "
                                 f"Farukon tool: missing {', '.join(missing)}")
            return result
        if probe_tool is None:
            result["ok"] = True
            result["message"] = (f"all {len(FARUKON_TOOLS)} Farukon tools are listed by the server "
                                 f"({', '.join(FARUKON_TOOLS)}) and it is still serving after "
                                 "tools/list")
            return result
        # The OPT-IN tools/call stage: the only stage where a server that answers the listing can
        # still be dead, which is exactly the owner-visible `-32000` class.
        result["stage"] = "tools/call"
        if not _write_line(proc.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                        "params": {"name": probe_tool, "arguments": {}}}):
            result["message"] = "the server closed stdin before the tools/call request"
            return result
        call = _await_response(lines, 3, response_timeout)
        if call is None:
            if died("tools/call", grace_of(response_timeout), f"the tools/call to {probe_tool!r}"):
                return result
            result["message"] = (f"no tools/call response within {int(response_timeout)}s"
                                 + _stderr_hint(result["stderr_tail"]))
            return result
        if "error" in call:
            error = call.get("error")
            result["error_code"] = error.get("code") if isinstance(error, dict) else None
            exit_code = snapshot(grace_of(response_timeout))
            result["message"] = (
                f"the server answered tools/call for {probe_tool!r} with a JSON-RPC error: "
                f"{json.dumps(error)}"
                + (f"; it then exited with code {exit_code}" if exit_code is not None else "")
                + _stderr_hint(result["stderr_tail"]))
            return result
        # A well-formed ENVELOPE is not a successful CALL: the MCP RESULT is validated and preserved
        # as evidence, so isError/empty/malformed/absent results are failures, never a healthy proof.
        call_result = call.get("result")
        result["tool_result"] = _bounded_result(call_result)
        problem = _tool_result_problem(call_result)
        if problem is not None:
            result["stage"] = "tools/call"
            result["message"] = (f"the server answered tools/call for {probe_tool!r} without a usable "
                                 f"MCP result: {problem}")
            return result
        result["probed_tool"] = probe_tool
        result["stage"] = None
        result["ok"] = True
        result["message"] = (f"all {len(FARUKON_TOOLS)} Farukon tools are listed and a real "
                             f"tools/call to {probe_tool!r} was answered with a well-formed MCP "
                             "result")
        return result
    finally:
        _close_stdin(proc)
        _terminate_tree(proc)


# --------------------------------------------------------------------------- capability probe

def _which(name: str) -> str | None:
    """PATH lookup seam — the offline suite monkeypatches this to simulate a host without cargo."""
    return shutil.which(name)


def _try_run(argv: list[str], timeout: float = VERSION_PROBE_TIMEOUT) -> str | None:
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


def _capability(present: bool, reason: str, detail: str | None = None) -> dict:
    return {"present": bool(present), "reason": reason, "detail": detail}


def _toggle(name: str) -> str:
    return name.replace("_", "-")


def probe_capabilities(repo: str | pathlib.Path, target: str | pathlib.Path | None = None,
                       check_mcp_start: bool = False) -> dict:
    """Fail-soft capability probe; a missing capability is data, never a crash.

    Static checks only (no build, no server start) unless `check_mcp_start` is passed explicitly.
    `farukon_usable` requires a WORKING cargo (present AND answering `--version`), a buildable
    `farukon_mcp` crate, a managed config entry whose `cwd` is this very platform root, AND — when
    the handshake was requested — a green tools/list listing all eight Farukon tools: a green
    verdict is never fabricated from a partial environment or an unrelated directory.
    """
    root = _checked_repo(repo)
    target_path = (pathlib.Path(os.path.abspath(str(target))) if target
                   else root / CONFIG_RELPATH)
    if not _within(target_path, root):
        raise InputError(f"--target {target_path} is outside the repository root {root}: the probe "
                         "only inspects configs of the project it is given")
    signals = farukon_platform_signals(root)
    caps: dict[str, dict] = {}

    cargo_path = _which(COMMAND)
    if not cargo_path:
        caps["cargo"] = _capability(
            False, f"{COMMAND} was not found on PATH; the Farukon platform cannot be built, tested or "
                   "operated without the Rust toolchain")
    else:
        version = _try_run([cargo_path, "--version"])
        if version is None:
            # A cargo that is on PATH but cannot answer `--version` is an UNPROVEN toolchain: the
            # version invocation failing or timing out is not evidence of a working build path.
            caps["cargo"] = _capability(
                False, f"{COMMAND} was found at {cargo_path} but `{COMMAND} --version` failed or timed "
                       f"out within {VERSION_PROBE_TIMEOUT}s; an unproven toolchain cannot build, test "
                       "or operate the Farukon platform", cargo_path)
        else:
            caps["cargo"] = _capability(True, f"{COMMAND} is available ({version})", cargo_path)

    # Buildability needs a crate manifest ON DISK: `farukon_mcp/Cargo.toml`, or the manifest of a
    # workspace member that is really there. A `members = [...]` declaration whose directory is
    # missing builds nothing, so it never makes the capability present.
    buildable = signals["crate_manifest"] is not None or signals["workspace_member"]
    workspace_manifest = signals.get("workspace_member_manifest")
    if buildable and signals["crate_manifest"]:
        caps["farukon_mcp_buildable"] = _capability(
            True, f"the {CRATE} crate is present ({signals['crate_manifest']} in {signals['root']})",
            str(root / CRATE_MANIFEST))
    elif buildable:
        caps["farukon_mcp_buildable"] = _capability(
            True, f"the {CRATE} crate is a workspace member of {root / 'Cargo.toml'} "
                  f"(manifest {workspace_manifest!r} on disk)",
            str(root / str(workspace_manifest)))
    else:
        caps["farukon_mcp_buildable"] = _capability(
            False, (f"no buildable {CRATE} crate under {root} (no {CRATE_MANIFEST.as_posix()} and no "
                    f"{CRATE} workspace member with a manifest of its own in the root Cargo.toml): "
                    "the eight Farukon MCP tools cannot be built or served here"))

    config_ok, config_problems, entry_present = managed_config_problems(target_path, expected_cwd=root)
    # REGISTRATION DRIFT: an entry that EXISTS but is not the managed definition is a different
    # finding from a missing one — the client launches something the factory never reviewed (the
    # platform really registers `node .kimi-code/farukon-mcp-launcher.js`). Only the differing KEY
    # names are reported: an entry may carry a credential in any value.
    entry = _farukon_entry(target_path)
    managed = managed_entry(root)
    drift_keys = (sorted(key for key in set(entry) | set(managed) if entry.get(key) != managed.get(key))
                  if isinstance(entry, dict) else [])
    config_drift = bool(drift_keys)
    if config_ok:
        caps["mcp_config"] = _capability(
            True, f"the managed {SERVER_NAME!r} server entry in {target_path} matches the definition "
                  f"({json.dumps(managed)})", str(target_path))
    elif config_drift and any(key != "cwd" for key in drift_keys):
        # A launch DEFINITION that differs (command, args, an extra key) is DRIFT: the client would
        # start something other than the reviewed crate. A `cwd` that merely names another directory
        # keeps its own, more precise wording (the platform-root problem below).
        caps["mcp_config"] = _capability(
            False, f"drift: the managed config carries a {SERVER_NAME!r} entry that is NOT the "
                   f"managed definition — differing key(s): {', '.join(drift_keys)} (values withheld: "
                   f"an MCP entry may carry credentials). The factory manages command {COMMAND!r} "
                   f"with args {json.dumps(MANAGED_ARGS)} and cwd = the platform root, so this entry "
                   "launches a server the factory never reviewed", str(target_path))
    else:
        caps["mcp_config"] = _capability(
            False, f"the managed config {target_path} is not usable: {config_problems[0]}",
            str(target_path))

    handshake = None
    if check_mcp_start:
        if not caps["cargo"]["present"]:
            caps[HANDSHAKE_CAPABILITY] = _capability(
                False, f"--check-mcp-start cannot run `{COMMAND} run --quiet -p {CRATE} --`: cargo "
                       f"is missing or unusable ({caps['cargo']['reason']})")
        else:
            handshake = mcp_start_handshake(root)
            caps[HANDSHAKE_CAPABILITY] = _capability(
                handshake["ok"], handshake["message"], handshake["cwd"])
    names = CAPABILITY_NAMES + ((HANDSHAKE_CAPABILITY,) if check_mcp_start else ())
    farukon_usable = (caps["cargo"]["present"] and caps["farukon_mcp_buildable"]["present"]
                      and config_ok
                      and (not check_mcp_start or caps[HANDSHAKE_CAPABILITY]["present"]))
    return {
        "repo": str(root),
        "host_signals": signals,
        "capabilities": caps,
        "missing": [name for name in names if not caps[name]["present"]],
        "farukon_usable": farukon_usable,
        "check_mcp_start": bool(check_mcp_start),
        "config": str(target_path),
        "config_valid": config_ok,
        "config_problems": config_problems,
        "config_entry_present": entry_present,
        "config_drift": config_drift,
        "config_drift_keys": drift_keys,
        "handshake": handshake,
    }


def format_probe(result: dict) -> str:
    lines = ["farukon-mcp capability probe (fail-soft: a missing capability is data, never a crash)",
             f"repo: {' '.join(result['host_signals']['details']) or 'no Farukon platform signature'}"]
    for name, cap in result["capabilities"].items():
        lines.append(f"  {_toggle(name) + ':':<24}{'present' if cap['present'] else 'missing'} — "
                     f"{cap['reason']}")
    lines.append(f"  {'config:':<24}{result['config']}")
    lines.append(f"  {'farukon_usable:':<24}{'yes' if result['farukon_usable'] else 'no'}")
    lines.append("  missing: " + (", ".join(_toggle(n) for n in result["missing"]) or "none"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- live-session evidence
# The Farukon proof is a REAL session, not a unit test: a task that operates the platform is accepted
# only against captured live sessions. `record-session` runs one BOUNDED handshake against the shape
# the MCP client really launches (the managed cargo entry, the project's OWN registration — the
# platform registers `node .kimi-code/farukon-mcp-launcher.js` — or an explicitly supplied binary) and
# writes the result as one immutable record; `verify-reproduction` and `verify-sessions` then judge
# those records STRICTLY. Recording is DATA (a failed session is a finding, exit 0); verifying is a
# GATE (a missing or weak proof is exit 1, never a quiet pass). A counted session must prove the WORK,
# not just the listing: all eight tools AND a real `tools/call` with a validated MCP result (review
# R4), and the five must be CONSECUTIVE — an unsuccessful attempt restarts the sequence.

def _evidence_dir(evidence: str | pathlib.Path, create: bool) -> pathlib.Path:
    """The evidence directory: created by a recorder, required to exist by a verifier."""
    path = pathlib.Path(os.path.abspath(str(evidence)))
    if create:
        path.mkdir(parents=True, exist_ok=True)
        return path
    if not path.is_dir():
        raise InputError(f"evidence directory not found: {path}; capture the live sessions with "
                         "`farukon_mcp.py record-session` before verifying them")
    return path


def registration_argv(repo: str | pathlib.Path) -> list[str]:
    """The command the MCP client REALLY launches for this project, from its own `mcp.json`.

    The platform's registration is `node .kimi-code/farukon-mcp-launcher.js`: no cargo arguments
    describe it, so a probe that only knows the managed cargo shape cannot verify what the client
    runs. Only REVIEWED launch shapes are accepted — `cargo` with the managed argument list, or a
    `node` wrapper whose launcher script really exists INSIDE the platform root. `npx`, inline code
    evaluation and arbitrary scripts are refused: this helper launches what it is told, and an
    unreviewed registration is exactly what must never be launched. The stored values are read to
    BUILD the launch, never echoed into a diagnostic.
    """
    root = _checked_repo(repo)
    entry = _farukon_entry(root / CONFIG_RELPATH)
    if entry is None:
        raise InputError(f"{root / CONFIG_RELPATH} carries no {SERVER_NAME!r} server entry: there is "
                         "no registration to reproduce — inspect the project's own MCP config")
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        raise InputError(f"mcpServers.{SERVER_NAME}.command is not a usable executable name in "
                         f"{root / CONFIG_RELPATH} (the value is not echoed: an entry may carry "
                         "credentials)")
    args = entry.get("args")
    if args is not None and not isinstance(args, list):
        raise InputError(f"mcpServers.{SERVER_NAME}.args is not a list in {root / CONFIG_RELPATH} "
                         "(values are not echoed: an entry may carry credentials)")
    argv = [command] + [arg for arg in (args or []) if isinstance(arg, str)]
    _reviewed_registration(root, command, argv[1:])
    return argv


# The only launchers a registration may use: the managed cargo crate and the platform's Node wrapper.
REVIEWED_LAUNCHERS: tuple[str, ...] = ("cargo", "node")
# Node flags that INJECT code or read it from a string: a launcher script is a FILE inside the root.
INLINE_CODE_FLAGS: frozenset[str] = frozenset({"-e", "--eval", "-p", "--print", "--input-type"})


def _launcher_name(command: str) -> str:
    """The executable's bare name (`C:\\...\\node.exe` -> `node`), so a full path is still reviewed."""
    return pathlib.Path(command.strip().strip('"')).stem.lower()


def _reviewed_registration(root: pathlib.Path, command: str, args: list[str]) -> None:
    """Refuse a registration the factory never reviewed — BEFORE anything is launched.

    Diagnostics name the SHAPE, never a stored value: an MCP entry may carry a credential, and these
    messages land in logs and evidence.
    """
    name = _launcher_name(command)
    if name not in REVIEWED_LAUNCHERS:
        raise InputError(f"the registered command is not a reviewed launcher (one of "
                         f"{', '.join(REVIEWED_LAUNCHERS)}): npx, inline code and arbitrary scripts "
                         "are never launched by this probe (the command's value is not echoed: an "
                         "entry may carry credentials)")
    if name == "cargo":
        if args != MANAGED_ARGS:
            raise InputError(f"a cargo registration must use the managed argument list "
                             f"{json.dumps(MANAGED_ARGS)}: another cargo invocation is not the "
                             "reviewed platform launch (values are not echoed)")
        return
    inline = [flag for flag in args if flag.split("=", 1)[0] in INLINE_CODE_FLAGS]
    if inline:
        raise InputError("a node registration may not evaluate inline code "
                         f"({', '.join(sorted(inline))}): the platform launcher is a script file "
                         "inside the platform root")
    valued = [flag.split("=", 1)[0] for flag in args if flag.startswith("-") and "=" in flag]
    if valued:
        # A `--flag=value` keeps its value inside the record this probe writes, and an MCP entry may
        # carry a credential in any value: only the launcher script and value-less flags are reviewed.
        raise InputError("a node registration may not pass a value-carrying flag "
                         f"({', '.join(sorted(set(valued)))}): the reviewed launcher shape is the "
                         "script plus value-less flags (values withheld: an entry may carry "
                         "credentials)")
    scripts = [arg for arg in args if not arg.startswith("-")]
    if not scripts:
        raise InputError("a node registration must name its launcher script: no non-flag argument "
                         "was found (values are not echoed)")
    for script in scripts:
        path = pathlib.Path(os.path.abspath(str(root / script)))
        if not _within(path, root):
            raise InputError(f"a node registration must launch a script INSIDE the platform root "
                             f"{root}: an argument that is not a flag resolves outside it (the value "
                             "is not echoed: an entry may carry credentials)")
        if not path.is_file():
            raise InputError("a node registration must name an EXISTING launcher script inside the "
                             "platform root: an argument that is not a flag is not a file on disk "
                             "(the value is not echoed: an entry may carry credentials)")


def session_argv(repo: str | pathlib.Path, mode: str, executable: str | None = None,
                 extra_args: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The argv of one recorded session, per `mode` (one of `SESSION_MODES`)."""
    if mode == "managed":
        return [COMMAND, *MANAGED_ARGS]
    if mode == "registration":
        if executable is not None:
            raise InputError("--executable is the `direct` mode's argument: the `registration` mode "
                             "launches the project's own mcp.json entry")
        return registration_argv(repo)
    if mode == "direct":
        if not executable:
            raise InputError("the `direct` mode needs --executable: the path of an already-built "
                             f"{CRATE} server binary (the healthy control of the reproduction)")
        root = _checked_repo(repo)
        binary = pathlib.Path(os.path.abspath(str(executable)))
        if not binary.is_file():
            raise InputError(f"--executable must be an EXISTING file (the already-built {CRATE} "
                             "binary): no such file on this host")
        if not _within(binary, root):
            raise InputError(f"--executable must stay inside the platform root {root}: this probe "
                             "launches the project's own build, never an arbitrary program")
        return [str(binary), *[str(arg) for arg in extra_args]]
    raise InputError(f"--mode must be one of {', '.join(SESSION_MODES)}: found {mode!r}")


def record_session(repo: str | pathlib.Path, evidence: str | pathlib.Path, mode: str = "managed",
                   executable: str | None = None, extra_args: list[str] | tuple[str, ...] = (),
                   probe_tool: str | None = None,
                   first_response_timeout: float = COLD_BUILD_TIMEOUT,
                   response_timeout: float = HANDSHAKE_TIMEOUT) -> dict:
    """Run ONE bounded live session and store it as an immutable evidence record.

    The record is the handshake result plus the facts a verifier needs to be strict: `kind`,
    `mode`, `repo`, `session_id`, `started_at` and `duration_s`. A failed session is still a RECORD
    (exit 0): the verdict belongs to `verify-reproduction` / `verify-sessions`, which refuse a weak
    proof — an unrecordable session is never "no evidence needed".
    """
    root = _checked_repo(repo)
    command = session_argv(root, mode, executable=executable, extra_args=extra_args)
    directory = _evidence_dir(evidence, create=True)
    started = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(started))
    handshake = mcp_start_handshake(root, argv=command, first_response_timeout=first_response_timeout,
                                    response_timeout=response_timeout, probe_tool=probe_tool)
    session_id = f"{stamp}-{mode}"
    path = directory / f"{session_id}.json"
    index = 1
    while path.exists():                 # never overwrite an earlier session's evidence
        index += 1
        session_id = f"{stamp}-{mode}-{index}"
        path = directory / f"{session_id}.json"
    record = {
        "kind": SESSION_KIND, "schema": SESSION_SCHEMA, "session_id": session_id, "mode": mode,
        "repo": os.path.abspath(str(root)), "started_at": stamp,
        "duration_s": round(time.time() - started, 3), **handshake,
    }
    try:
        _write_text_exact(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise InputError(f"cannot write the session record {path}: {exc}") from exc
    return {"record": record, "path": str(path)}


def session_evidence(evidence: str | pathlib.Path, repo: str | pathlib.Path
                     ) -> tuple[list[dict], list[str]]:
    """`(records, problems)` — the session records of THIS repository and the defects of the DIRECTORY.

    FAIL CLOSED on unreadable evidence: a `*.json` file that cannot be parsed is NAMED in `problems`
    instead of being skipped, because a broken file can hide an attempt — including the failed one
    that has to restart the mandated sequence — and a skipped file would let the gate pass over it.
    Only `*.json` files are session evidence at all: a known console capture (`.log`/`.txt`) or any
    other artifact in the same directory is explicitly not evidence and is ignored. A parseable JSON
    file of another kind or of another project is another artifact too (it is not this platform's
    proof); duplicates stay distinct by `session_id`, and the verifiers de-duplicate them so one
    session can never satisfy two slots.
    """
    directory = _evidence_dir(evidence, create=False)
    wanted = os.path.normcase(os.path.abspath(str(repo)))
    records: list[dict] = []
    problems: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{path.name} is not readable session evidence ({type(exc).__name__}: "
                            f"{exc}): an unparseable record could hide an attempt, so the evidence "
                            "fails closed instead of being skipped")
            continue
        if not isinstance(data, dict) or data.get("kind") != SESSION_KIND:
            continue
        if not isinstance(data.get("session_id"), str) or not data["session_id"].strip():
            continue
        if os.path.normcase(os.path.abspath(str(data.get("repo") or ""))) != wanted:
            continue
        records.append(data)
    return records, problems


def _serving_session(record: dict) -> bool:
    """`True` when the record proves a COMPLETE eight-tool server that is still serving.

    This is the LISTING half of the proof: `initialize` answered, all eight tools listed, the process
    alive after `tools/list`. It says nothing about whether the server can answer a call.
    """
    tools = record.get("tools") if isinstance(record.get("tools"), list) else []
    return (record.get("ok") is True
            and record.get("missing_tools") == []
            and all(name in tools for name in FARUKON_TOOLS)
            and record.get("post_list_alive") is True
            and record.get("exit_code") is None)


def _recorded_result_problem(record: dict) -> str | None:
    """Why the PRESERVED `tools/call` result of a record is not proof of a successful call.

    A counted session keeps the answer it got (`tool_result`), and that answer must still be a
    well-formed MCP result. A record that does not preserve the answer cannot show that a call was
    ever validated, so the field is MANDATORY for a counted session — dropping it cannot bypass the
    call requirement (review R5). A TRUNCATION marker is accepted: `_bounded_result` only truncates,
    and the full answer was validated before it was stored.
    """
    if "tool_result" not in record or record.get("tool_result") is None:
        return ("the record does not preserve its `tools/call` result (`tool_result`), so no "
                "validated call is proven")
    value = record.get("tool_result")
    if isinstance(value, dict) and value.get("truncated") is True:
        return None
    return _tool_result_problem(value)


def _healthy_session(record: dict) -> bool:
    """`True` when the record proves the WHOLE session — including a real, successful `tools/call`.

    A listing is not a call: `tools/list` says a tool EXISTS, and the owner-visible `-32000` is a
    CALL failure. So a record only counts as one of the five sessions when the probe actually invoked
    one of the eight tools (`probed_tool`), the server ANSWERED it without a JSON-RPC error and with
    a well-formed MCP result (`isError` absent/false, a `content` list — re-checked when the answer
    was preserved), and it was still serving. A list-only or errored record never fills a slot
    (reviews R1/R4).
    """
    probed = record.get("probed_tool")
    return (_serving_session(record)
            and isinstance(probed, str) and probed in FARUKON_TOOLS
            and record.get("error_code") is None
            and _recorded_result_problem(record) is None)


def _schema_problem(record: dict) -> str | None:
    """`None` when the record's evidence schema is the one this helper writes."""
    return None if record.get("schema") == SESSION_SCHEMA else "unknown evidence schema"


def _stamp_of(record: dict) -> str | None:
    """The record's position in the ordered sequence, or `None` when it cannot be placed in time."""
    stamp = record.get("started_at")
    try:
        time.strptime(str(stamp), SESSION_STAMP)
    except (TypeError, ValueError):
        return None
    return str(stamp)


def _freshness_problem(record: dict) -> str | None:
    """Why a record is not placeable, run-associated evidence, or `None` when it is.

    A record of an unknown schema, or one whose start cannot be parsed, is AMBIGUOUS: it cannot be
    placed in this run, so it never fills one of the five session slots and it FAILS the gate (an
    unplaceable proof is not a proof). It is rejected BEFORE the sequence is evaluated, so an
    ambiguous file can never restart — or silently continue — the mandated run of five.
    """
    return _schema_problem(record) or (None if _stamp_of(record) is not None
                                       else "unparseable start timestamp")


def _observed_failure(record: dict) -> bool:
    """`True` when the record proves a failure that was OBSERVED (exit code or JSON-RPC error)."""
    return (record.get("ok") is False
            and record.get("stage") == "initialize"
            and record.get("protocol_frames") == 0
            and (record.get("exit_code") is not None or record.get("error_code") is not None))


def verify_reproduction(repo: str | pathlib.Path, evidence: str | pathlib.Path) -> dict:
    """Strict verdict on the reproduction evidence: the DEAD launch AND the healthy control.

    The reproduction the platform demanded is a pair: (a) the real launch fails BEFORE any protocol
    frame (stage `initialize`, zero frames, an observed exit code or JSON-RPC error such as `-32000`,
    the launcher's own stderr captured) and (b) a healthy control lists all eight tools and is still
    serving after `tools/list`. A missing half is a FAILURE of the gate, naming what is missing.
    The control is the LISTING half on purpose: this gate proves WHICH failure was reproduced, while
    the five-session gate below additionally requires a real `tools/call` in EVERY counted session.
    """
    root = _checked_repo(repo)
    records, evidence_problems = session_evidence(evidence, root)
    failures = [record for record in records if _observed_failure(record)]
    healthy = [record for record in records if _serving_session(record)]
    problems: list[str] = list(evidence_problems)
    if not failures:
        problems.append("no FAILED session record proves the real failure before initialize: expected "
                        "a record with stage 'initialize', 0 protocol frames and an observed exit "
                        "code or JSON-RPC error (capture it with `record-session --mode registration`)")
    if not healthy:
        problems.append("no HEALTHY control session proves the platform can serve: expected a record "
                        "listing all eight Farukon tools with the process still alive after "
                        "tools/list (capture it with `record-session --mode direct`)")
    return {
        "ok": not problems, "repo": str(root),
        "evidence": os.path.abspath(str(evidence)),
        "sessions": len(records),
        "failure_session": failures[0]["session_id"] if failures else None,
        "healthy_session": healthy[0]["session_id"] if healthy else None,
        "problems": problems,
        "message": ("reproduction proven: an observed pre-initialize launch failure AND a healthy "
                    "eight-tool control session" if not problems else
                    f"reproduction NOT proven ({len(problems)} missing piece(s))"),
    }


def verify_sessions(repo: str | pathlib.Path, evidence: str | pathlib.Path) -> dict:
    """Strict verdict on the five live sessions: DISTINCT, placeable, consecutive, EACH with a call.

    A counted session must prove the whole workflow, not just the listing: all eight tools listed, a
    real `tools/call` answered with a well-formed MCP result (no `isError`, a `content` list) and no
    JSON-RPC error, with the process still serving. On top of that the five must be CONSECUTIVE: the
    records are read in start order and every unsuccessful attempt (a dead launch, a list-only
    session, a malformed or error answer) RESETS the run, so five healthy sessions followed by a
    failure and one more healthy session are NOT five (review R4 — a failed attempt is diagnostic and
    restarts the mandated sequence). Every counted record must also PRESERVE the validated result it
    got (review R5): dropping `tool_result` proves nothing, and evidence that cannot be parsed fails
    closed naming the file instead of being skipped. Duplicates never fill a slot and an unplaceable
    record fails the gate.
    """
    root = _checked_repo(repo)
    records, problems = session_evidence(evidence, root)
    seen: set[str] = set()
    rejected: list[str] = []
    ordered: list[tuple[str, str, dict]] = []
    for record in records:
        session_id = record["session_id"]
        if session_id in seen:
            continue                    # one session cannot fill two slots
        seen.add(session_id)
        problem = _freshness_problem(record)
        if problem is not None:
            rejected.append(f"{session_id} ({problem})")
            continue
        ordered.append((_stamp_of(record) or "", session_id, record))
    ordered.sort(key=lambda item: (item[0], item[1]))
    consecutive: list[str] = []
    reset_at: str | None = None
    for _stamp, session_id, record in ordered:
        if _healthy_session(record):
            consecutive.append(session_id)
        else:
            consecutive = []            # an unsuccessful attempt restarts the mandated sequence
            reset_at = session_id
    if rejected:
        problems.append("these records are not FRESH, run-associated evidence and never fill a slot: "
                        + ", ".join(rejected))
    if len(consecutive) < SESSIONS_REQUIRED:
        where = f" AFTER the latest unsuccessful attempt ({reset_at})" if reset_at else ""
        problems.append(
            f"only {len(consecutive)} of the {SESSIONS_REQUIRED} required live sessions{where} prove "
            "the whole workflow — all eight tools listed, a SUCCESSFUL tools/call answered with a "
            "well-formed MCP result (no isError, a content list) that the record PRESERVES "
            "(`tool_result`) and no JSON-RPC error, and the process still serving: a listing alone is "
            "not a call, a record without its result proves nothing, and an unsuccessful attempt "
            "restarts the sequence, so five CONSECUTIVE sessions are required. Capture another one "
            "with `farukon_mcp.py record-session --mode registration --probe-tool <tool>` (or "
            "--mode direct for the built binary with --probe-tool)")
    return {
        "ok": not problems, "repo": str(root),
        "evidence": os.path.abspath(str(evidence)),
        "required": SESSIONS_REQUIRED, "healthy_sessions": consecutive,
        "rejected_sessions": rejected, "sequence_reset_at": reset_at, "sessions": len(records),
        "problems": problems,
        "message": (f"{len(consecutive)} consecutive live sessions proven" if not problems else
                    f"live-session proof NOT met ({len(problems)} problem(s))"),
    }


# --------------------------------------------------------------------------- CLI

def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so help and messages never crash a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# The fields of a PARSED task that say WHAT the task operates. Everything around them — YAML
# comments, `models`, `repo_path`, `mode`, launch instructions — is wiring, and the classifier
# never sees it: the shipped template's own instructional comments name the platform AND its
# operations, so classifying them would activate the specialist on an unrelated task.
BUSINESS_SCOPE_SCALARS: tuple[str, ...] = ("title", "description", "user_story")
BUSINESS_TEST_TEXT_KEYS: tuple[str, ...] = ("scenario", "expected_results")


def business_scope(task: dict) -> str:
    """The business-scope text of a PARSED task: only the fields that say WHAT the task operates.

    A criterion's `verify` (a shell command) and a business test's `config` (a path) are machine
    wiring, not business wording, so they stay out together with the metadata.
    """
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
    and metadata are dropped by the canonical parser, never re-parsed here. A file that is NOT a
    task (plain text, or a task the strict parser refuses) is classified verbatim, exactly as
    before; the downstream METADATA stripping of `scope_text` still applies to it.
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
        raise InputError(f"task file not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    return _file_scope_text(raw)


def _emit(args: argparse.Namespace, payload: dict, human: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if getattr(args, "as_json", False)
          else human)


def _probe_out_path(value: str, repo_root: pathlib.Path) -> pathlib.Path:
    """`--out` accepts a directory (writes probe.json inside) or a `*.json` file path.

    The RESOLVED path is confined to the repository exactly like `--target`: a traversal, an
    absolute path elsewhere or a symlink escape must never write the probe result outside the
    project it describes.
    """
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = pathlib.Path(os.path.abspath(str(path)))
    path = path if path.suffix.lower() == ".json" else path / PROBE_FILE_NAME
    if not _within(path, repo_root):
        raise InputError(f"--out {path} is outside the repository root {repo_root}: the probe "
                         "result must stay inside the project it describes; nothing was written")
    return path


def cmd_decide(args: argparse.Namespace) -> int:
    result = decide_applicability(_task_text(args), repo=args.repo)
    _emit(args, result, format_decision(result))
    return 0


def cmd_merge_config(args: argparse.Namespace) -> int:
    result = merge_config(args.repo, target=args.target, dry_run=args.dry_run)
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


def cmd_probe(args: argparse.Namespace) -> int:
    result = probe_capabilities(args.repo, target=args.target,
                                check_mcp_start=args.check_mcp_start)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_probe(result))
    if args.out:
        out = _probe_out_path(args.out, pathlib.Path(result["repo"]))
        try:
            _write_text_exact(out, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"ERROR: cannot write {out}: {exc}", file=sys.stderr)
            return 1
        if not args.as_json:
            print(f"  capabilities file: {out}")
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path)
    ok, problems = validate_config(path)
    if args.as_json:
        print(json.dumps({"path": str(path), "ok": ok, "problems": problems}, indent=2,
                         ensure_ascii=False))
        return 0 if ok else 1
    if ok:
        print(f"OK {path}: managed {SERVER_NAME!r} entry (if present) carries exactly the managed "
              f"keys — command {COMMAND!r}, args {json.dumps(MANAGED_ARGS)} and an absolute, "
              "existing cwd")
        return 0
    print(f"FAIL {path}: {len(problems)} invariant(s) violated")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_record_session(args: argparse.Namespace) -> int:
    recorded = record_session(args.repo, args.evidence, mode=args.mode,
                              executable=args.executable, extra_args=args.arg or (),
                              probe_tool=args.probe_tool,
                              first_response_timeout=args.first_response_timeout,
                              response_timeout=args.response_timeout)
    record = recorded["record"]
    if args.as_json:
        print(json.dumps(recorded, indent=2, ensure_ascii=False))
        return 0
    state = "HEALTHY" if _healthy_session(record) else "DEGRADED"
    hint = ("" if _healthy_session(record) else
            "  [this record cannot count as one of the five sessions: pass --probe-tool <tool> so the "
            "session proves a real tools/call]" if _serving_session(record) else "")
    print(f"{state}: session {record['session_id']} ({record['mode']}) on {record['repo']} — "
          f"stage {record['stage']}, exit code {record['exit_code']}, "
          f"{record['protocol_frames']} protocol frame(s), {len(record['tools'])} tool(s) listed; "
          f"{record['message']}{hint}")
    print(f"  evidence: {recorded['path']}")
    return 0


def cmd_verify_reproduction(args: argparse.Namespace) -> int:
    result = verify_reproduction(args.repo, args.evidence)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(("OK" if result["ok"] else "FAIL") + f" {result['message']}")
        print(f"  repo: {result['repo']}")
        print(f"  evidence: {result['evidence']} ({result['sessions']} session record(s))")
        print(f"  failure session: {result['failure_session'] or 'NONE'}")
        print(f"  healthy session: {result['healthy_session'] or 'NONE'}")
        for problem in result["problems"]:
            print(f"  - {problem}")
    return 0 if result["ok"] else 1


def cmd_verify_sessions(args: argparse.Namespace) -> int:
    result = verify_sessions(args.repo, args.evidence)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(("OK" if result["ok"] else "FAIL") + f" {result['message']}")
        print(f"  repo: {result['repo']}")
        print(f"  evidence: {result['evidence']} ({result['sessions']} session record(s))")
        print(f"  consecutive healthy sessions: {len(result['healthy_sessions'])}/"
              f"{result['required']} — " + (", ".join(result["healthy_sessions"]) or "NONE"))
        print(f"  latest unsuccessful attempt: {result.get('sequence_reset_at') or 'none'}")
        for problem in result["problems"]:
            print(f"  - {problem}")
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="farukon_mcp.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("decide", help="applicability of the Farukon platform path for a task text")
    p.add_argument("--repo", required=True, help="repository root (its host signature is required)")
    p.add_argument("--text", default=None, help="task/user-story/acceptance text")
    p.add_argument("--task-file", dest="task_file", default=None,
                   help="file whose text is used (task.yaml or plain text)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("merge-config", help="merge the managed farukon server into a mcp.json")
    p.add_argument("--repo", required=True, help="Farukon platform repository root")
    p.add_argument("--target", default=None,
                   help=f"config to merge into (default: <repo>/{CONFIG_RELPATH.as_posix()}); must "
                        "stay inside --repo")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="report what would happen without writing")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_merge_config)

    p = sub.add_parser("probe", help="fail-soft capability probe (missing capabilities are data)")
    p.add_argument("--repo", required=True, help="Farukon platform repository root")
    p.add_argument("--target", default=None,
                   help=f"managed config to validate (default: <repo>/{CONFIG_RELPATH.as_posix()})")
    p.add_argument("--check-mcp-start", action="store_true", dest="check_mcp_start",
                   help=f"opt-in: start `{COMMAND} run --quiet -p {CRATE} --` and verify the eight "
                        "Farukon tools through a bounded JSON-RPC handshake")
    p.add_argument("--out", default=None,
                   help=f"write the probe result as JSON here (a directory receives "
                        f"{PROBE_FILE_NAME}; a *.json path is used literally)")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("validate-config", help="invariants of a managed farukon entry")
    p.add_argument("--path", required=True, help="config to check")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_validate_config)

    p = sub.add_parser("record-session",
                       help="run ONE bounded live MCP session and store it as evidence")
    p.add_argument("--repo", required=True, help="Farukon platform repository root")
    p.add_argument("--evidence", required=True,
                   help="evidence directory receiving the session record (created if missing)")
    p.add_argument("--mode", default="managed", choices=list(SESSION_MODES),
                   help="managed = the reviewed cargo entry; registration = the project's OWN "
                        "mcp.json entry (the shape the MCP client really launches: reviewed `cargo` "
                        "or `node` launcher only); direct = an already-built binary given with "
                        "--executable")
    p.add_argument("--executable", default=None,
                   help="the server binary to launch in `direct` mode; it must be an existing file "
                        "inside the platform root")
    p.add_argument("--arg", action="append", default=[],
                   help="extra argument for the `direct` mode's binary (repeatable)")
    p.add_argument("--probe-tool", dest="probe_tool", default=None,
                   help="opt-in: also invoke this tools/call (one of the eight Farukon tools)")
    p.add_argument("--first-response-timeout", dest="first_response_timeout",
                   type=float, default=COLD_BUILD_TIMEOUT,
                   help=f"budget for the first response, a cold build included "
                        f"(default: {COLD_BUILD_TIMEOUT})")
    p.add_argument("--response-timeout", dest="response_timeout", type=float,
                   default=HANDSHAKE_TIMEOUT,
                   help=f"budget for the later protocol replies (default: {HANDSHAKE_TIMEOUT})")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_record_session)

    p = sub.add_parser("verify-reproduction",
                       help="strict gate: the observed launch failure AND a healthy control session")
    p.add_argument("--repo", required=True, help="Farukon platform repository root")
    p.add_argument("--evidence", required=True,
                   help="evidence directory with the session records to judge")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_verify_reproduction)

    p = sub.add_parser("verify-sessions",
                       help=f"strict gate: {SESSIONS_REQUIRED} distinct healthy live sessions")
    p.add_argument("--repo", required=True, help="Farukon platform repository root")
    p.add_argument("--evidence", required=True,
                   help="evidence directory with the session records to judge")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.set_defaults(func=cmd_verify_sessions)
    return ap


def main() -> int:
    use_utf8_output()
    ap = build_parser()
    args = ap.parse_args()
    if args.cmd == "decide" and args.text is None and not args.task_file:
        ap.error("decide requires --text or --task-file")
    try:
        return args.func(args)
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

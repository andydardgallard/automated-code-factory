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
  probe            fail-soft capability probe: cargo, farukon_mcp buildability, the managed config,
                   and with --check-mcp-start a bounded newline-delimited JSON-RPC handshake that
                   verifies all eight Farukon MCP tools and reports the protocol version the SERVER
                   answers (--target, --out)
  validate-config  invariants of a managed `farukon` entry (--path)

Exit codes:
  0  success — including a `not_applicable` decision and a DEGRADED `probe`: a missing capability or
     an unusable platform path is DATA, never a crash or a failed run
  1  a real error: an unreadable input, a `--repo` that is not a directory, a `--target` that escapes
     the repository, a `--repo` that is not a Farukon platform root (merge-config refuses to write a
     server into a project that does not host the platform), a config that is not valid JSON (such a
     target is then NEVER overwritten), or a write that cannot happen (a directory or an unwritable
     target, reported instead of a traceback; the write is atomic, so an existing file keeps its
     bytes)
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
    process tree; a cargo that is on PATH but cannot answer `--version` is UNUSABLE, not present;
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
    return (_command_problems(entry) + _args_problems(entry) + _cwd_problems(entry))


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

def _pump(stream, sink: "queue.Queue") -> None:
    """Forward every line of a child stdout pipe to a queue (EOF -> `None`)."""
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            sink.put(line)
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


def _stderr_hint(errors: "collections.deque") -> str:
    lines = [line.strip() for line in errors if line.strip()]
    return f" (last stderr line: {lines[-1]})" if lines else ""


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


def mcp_start_handshake(repo: str | pathlib.Path, argv: list[str] | None = None,
                        first_response_timeout: float = COLD_BUILD_TIMEOUT,
                        response_timeout: float = HANDSHAKE_TIMEOUT,
                        env: dict | None = None) -> dict:
    """Bounded newline-delimited JSON-RPC handshake against a stdio Farukon MCP server.

    Starts `cargo run --quiet -p farukon_mcp --` in the repository root (or the injected `argv`, the
    seam the offline tests use with a fake server), sends `initialize`, the initialized notification
    and `tools/list`, and verifies that all eight Farukon tools are listed. Every read is bounded:
    the first response may wait for a cold cargo build (up to 30 min), the protocol replies are
    awaited for 30 s. The child process TREE is terminated on every path, so a failed probe never
    leaves a platform instance behind. Failures are DATA: `ok=False` with a message, never an
    exception.

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
              "missing_tools": list(FARUKON_TOOLS), "message": ""}
    problem = (_timeout_problem("first_response_timeout", first_response_timeout)
               or _timeout_problem("response_timeout", response_timeout))
    if problem is not None:
        result["message"] = f"{TIMEOUT_REFUSAL} `{' '.join(command)}`: {problem}"
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
    lines: "queue.Queue" = queue.Queue()
    errors: "collections.deque" = collections.deque(maxlen=STDERR_TAIL_LINES)
    threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()
    threading.Thread(target=_drain, args=(proc.stderr, errors), daemon=True).start()
    try:
        if not _write_line(proc.stdin, _initialize_request(1)):
            result["message"] = "the server closed stdin before the initialize request"
            return result
        init = _await_response(lines, 1, first_response_timeout)
        if init is None:
            result["message"] = (f"no initialize response within {int(first_response_timeout)}s from "
                                 f"`{' '.join(command)}` in {result['cwd']}"
                                 + _stderr_hint(errors)
                                 + "; a cold cargo build takes long — warm the target directory and "
                                   "re-run")
            return result
        if "error" in init:
            result["message"] = (f"the server answered initialize with a JSON-RPC error: "
                                 f"{json.dumps(init.get('error'))}")
            return result
        init_result = init.get("result") if isinstance(init.get("result"), dict) else {}
        result["protocol_version"] = init_result.get("protocolVersion")
        info = init_result.get("serverInfo") if isinstance(init_result.get("serverInfo"), dict) else {}
        result["server"] = info.get("name")
        _write_line(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        if not _write_line(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                        "params": {}}):
            result["message"] = "the server closed stdin before the tools/list request"
            return result
        listing = _await_response(lines, 2, response_timeout)
        if listing is None:
            result["message"] = (f"no tools/list response within {int(response_timeout)}s"
                                 + _stderr_hint(errors))
            return result
        if "error" in listing:
            result["message"] = (f"the server answered tools/list with a JSON-RPC error: "
                                 f"{json.dumps(listing.get('error'))}")
            return result
        listing_result = listing.get("result") if isinstance(listing.get("result"), dict) else {}
        tools = listing_result.get("tools") if isinstance(listing_result.get("tools"), list) else []
        names = [tool.get("name") for tool in tools
                 if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
        missing = [name for name in FARUKON_TOOLS if name not in names]
        result.update(ok=not missing, tools=names, missing_tools=missing)
        if missing:
            result["message"] = ("the server answered the handshake but does not expose every "
                                 f"Farukon tool: missing {', '.join(missing)}")
        else:
            result["message"] = (f"all {len(FARUKON_TOOLS)} Farukon tools are listed by the server "
                                 f"({', '.join(FARUKON_TOOLS)})")
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
    if config_ok:
        caps["mcp_config"] = _capability(
            True, f"the managed {SERVER_NAME!r} server entry in {target_path} matches the definition "
                  f"({json.dumps(managed_entry(root))})", str(target_path))
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


# --------------------------------------------------------------------------- CLI

def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so help and messages never crash a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


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
    print(json.dumps(payload, indent=2, ensure_ascii=False) if getattr(args, "as_json", False)
          else human)


def _probe_out_path(value: str, repo_root: pathlib.Path) -> pathlib.Path:
    """`--out` accepts a directory (writes probe.json inside) or a `*.json` file path."""
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = pathlib.Path(os.path.abspath(str(path)))
    return path if path.suffix.lower() == ".json" else path / PROBE_FILE_NAME


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
        print(f"OK {path}: managed {SERVER_NAME!r} entry (if present) matches command {COMMAND!r}, "
              f"args {json.dumps(MANAGED_ARGS)} and an absolute, existing cwd")
        return 0
    print(f"FAIL {path}: {len(problems)} invariant(s) violated")
    for problem in problems:
        print(f"  - {problem}")
    return 1


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

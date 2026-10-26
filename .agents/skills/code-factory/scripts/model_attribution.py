#!/usr/bin/env python3
"""
Model attribution from the CLI's own session wire (zero LLM tokens, stdlib only).

WHY THIS EXISTS

`models_used` in `.code-factory/state/pipeline.yaml` and in `report.md` is SELF-REPORTED by the
main agent, so a silent model substitution — the CLI demoting a subagent to another model, or a
role quietly running on the primary model — is invisible in the factory's own artifacts. The owner
requires the models to be confirmed by an ARTIFACT, not by a claim. This script reads the one
artifact the factory cannot forge: the CLI's session wire, written by the harness outside the
repository (`~/.kimi-code/`), and compares it with the claim.

THE WIRE (measured on a real machine; re-checked before this script was written)

  ~/.kimi-code/session_index.jsonl      one JSON object per line: {"sessionId","sessionDir","workDir"}
  ~/.kimi-code/sessions/wd_<name>_<h>/session_<uuid>/
        state.json                      {"cwd","archived","agents":{"<id>":{"type","parentAgentId",
                                         "labels":{"profileName":"factory-analyzer"}}}}
        agents/<id>/wire.jsonl          one JSON event per line (`main`, `agent-0`, `agent-1`, ...)

  Model-bearing events are TOP-LEVEL typed objects, one per line:
    {"type":"llm.request","agentId":"main","model":"k3","modelAlias":"kimi-k3",...}
        `model` is the WIRE name (`k3`), `modelAlias` the CLI alias (`kimi-k3`,
        `kimi-code/k3`) — the alias wins, the wire name is only a fallback.
    {"type":"usage.record","agentId":"agent-0","model":"kimi-k3","usage":{...},...}
        carries the alias (or a provider-qualified name) plus the token counts.
    {"type":"subagent.spawned","subagentId":"agent-1","subagentName":"factory-analyzer",
     "parentAgentId":"main","model":"deepseek-flash",...}
        appears in the PARENT wire; `subagentName` is the role profile (`factory-<role>`).
  Error events: `subagent.failed`, `subagent.cancelled`, `turn.cancel`, `prompt.aborted`,
  `turn.step.retrying`.

  PITFALL: the string `"model"` also occurs inside tool-schema JSON embedded in prompt/message
  events (`context.append_message`, `llm.tools_snapshot`, ...). Counting occurrences of the
  substring would invent models that were never served, so ONLY top-level typed events with a
  `type` in MODEL_EVENTS / ERROR_EVENTS are read — the embedded JSON is never searched.

SESSION RESOLUTION

  There is no session-id environment variable. `--session auto` takes the candidates
  `sessions/*/session_*/state.json` whose `cwd` equals the resolved `--repo` (path-normalised,
  case-insensitively on Windows) and whose `archived` is not true, and picks the one with the
  NEWEST `agents/*/wire.jsonl` mtime; ties break on the highest sessionId so the choice is
  deterministic. The pick is corroborated with the LAST `session_index.jsonl` line whose
  `workDir` matches the repo; a disagreement is FLAGGED (`session.index_agrees: false`), never
  hidden. `--session <dir>` uses that session directory as-is (`resolved_by: "arg"`).

ALIAS NORMALISATION (the only two rules this script applies)

  1. `alias_of(event)`: `modelAlias` when present and non-empty, else `model`; lowercased; a
     provider-qualified name is reduced to its model part (`kimi-code/k3` -> `k3`). That is the
     key `models_served` counts are reported under.
  2. `canonical(alias)`: the COMPARISON key — the same reduction as (1), plus the vendor family
     word is folded off a version token (`kimi-k3` -> `k3`, `deepseek-v4-pro` -> `v4-pro`), so a
     claim written the way the pipeline writes it (`kimi-k3`) matches a wire that spells the same
     model differently (`k3`). Both sides of every comparison go through it, so the fold can
     never make two DIFFERENT models look equal (`kimi-k2` -> `k2` != `k3`).

ROLE RESOLUTION

  Per agent id: `state.json` `agents[id].labels.profileName` -> role (`factory-` prefix stripped,
  `code-reviewer`->`reviewer`, `gui-expert`->`gui_expert`, `security-auditor`->`security_auditor`,
  `skill-manager`->`skill_manager`, `main` stays `main`); when the state carries no profile, the
  parent wire's `subagent.spawned.subagentName` supplies it. Per role the script accumulates
  `models_served`, `tokens` (from `usage.record`), `errors` (by event type), `spawn_model` (the
  model the parent asked for) and the first/last event time.

PUBLIC API

  use_utf8_output()                       force UTF-8 on stdout/stderr (house convention)
  alias_of(event)                         the served alias of a model-bearing wire event
  canonical(alias)                        the comparison key of an alias (see above)
  role_from_profile(name)                 `factory-code-reviewer` -> `reviewer`, "" when unnamed
  session_candidates(home, repo)          matching, newest-last candidate sessions (auto mode)
  index_session_id(home, repo)            session id of the last matching session_index line
  resolve_session(repo, session, home)    {"session_dir","session_id","resolved_by",...}; raises
                                          Degraded when nothing matches
  read_models_used(path)                  (run_id, {role: claim}) of a pipeline.yaml
  analyse_session(session_dir)            per-agent records + spawn map of one session
  agent_roles(state, records, spawns)     agent id -> role
  compare_claims(claims, roles, degraded) (comparison, lines, flags) of claims vs wire
  verdict_of(comparison, reason, required) FAIL / DEGRADED / PASS of a comparison
  build_report(...) / write_artifact(...) the JSON artifact of the run

CLI

  python model_attribution.py --session <dir|auto> --repo <path> --out <json>
                              [--pipeline <pipeline.yaml>] [--home <wire root>] [--quiet]

  --session   a session directory, or `auto` (default) to resolve the current one from --repo
  --repo      the project whose sessions are resolved (required)
  --out       the JSON artifact to write (required; its parent directory is created)
  --pipeline  the run's `.code-factory/state/pipeline.yaml`; when present its `run_id` lands in
              the artifact and its `models_used` mapping is CROSS-CHECKED against the wire
  --home      the CLI's wire root (default `~/.kimi-code`); an explicit knob so tests never read
              the real sessions — the default is a module constant, never an environment variable
  --quiet     print only the final summary line (the per-role lines go silent)

  Per claimed role it prints one of:
    `role: match (claimed=X wire=[Y:N])`            the wire served exactly the claimed model
    `role: mismatch (claimed=X wire=[Y:N])`         the wire served something else
    `role: unverified (claimed but no wire agent)`  no session/wire at all to confirm the claim
    `role: degraded (no wire for this role)`        the session exists, the role left no evidence
    `role: mismatch (claimed=unused wire=[Y:N])`    the pipeline says `unused`, the wire disagrees
  The last line is always `PASS|FAIL|DEGRADED - <summary> (<out path>)`.

EXIT CODES

  0  the session was found and every claimed role matches the wire (with no --pipeline there is
     no claim side at all, so the run is a wire REPORT: it prints the roles and exits 0)
  1  at least one role MISMATCHES (a claim the wire disproves) — never hidden by a degradation
  2  input error: a bad path, an unreadable wire, an unwritable --out (message, no traceback)
  3  DEGRADED: no session/wire found, a claimed role left no wire evidence, or `--pipeline` was
     given and its `models_used` block names NO role — an empty claim set confirms nothing, so it
     is never a PASS. The artifact is still written with `attribution_degraded: true` and the
     reason goes to stderr as ONE line, so the flow can record `models_warning` instead of staying
     silent. A run never returns 0 without writing the artifact.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

# The CLI's wire root. A module-level constant on purpose: no environment variable may silently
# re-point the attribution at another root (the CLI has no session-id variable either); `--home`
# is the one explicit, visible override.
WIRE_HOME = pathlib.Path.home() / ".kimi-code"
SESSION_INDEX = "session_index.jsonl"
SESSIONS_DIR = "sessions"
STATE_FILE = "state.json"
AGENTS_DIR = "agents"
WIRE_FILE = "wire.jsonl"

# The only event types that may contribute a model. Everything else (prompt/message/tool-schema
# events, which embed arbitrary JSON that may contain a `"model"` key) is NOT searched.
MODEL_EVENTS = ("llm.request", "usage.record", "subagent.spawned")
ERROR_EVENTS = ("subagent.failed", "subagent.cancelled", "turn.cancel", "prompt.aborted",
                "turn.step.retrying")

# `models_used` sentinel: the pipeline stating that the role was not used at all.
UNUSED = "unused"
# The factory's sub-agent profiles are named `factory-<role>`; two roles do not follow the
# dash-to-underscore rule, so they are pinned here (the rest is `name.replace("-", "_")`).
PROFILE_PREFIX = "factory-"
ROLE_ALIASES = {"code-reviewer": "reviewer", "gui-expert": "gui_expert",
                "security-auditor": "security_auditor", "skill-manager": "skill_manager"}
# Vendor family words folded off a version token by `canonical()` (`kimi-k3` -> `k3`).
FAMILY_WORDS = ("kimi", "moonshot", "deepseek", "qwen", "dashscope")

# The flat `models_used:` block of a pipeline.yaml: `run_id` plus `role: alias` scalars. A
# deliberately small reader — the factory owns the checkpoint format and must not grow a YAML
# parser (mirrors `model_matrix.task_models`).
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
MODELS_HEADER = re.compile(r"^models_used:\s*(#.*)?$")
MODELS_ENTRY = re.compile(r"^(\s+)([A-Za-z0-9_]+)\s*:\s*(\S.*?)\s*$")
TRAILING_COMMENT = re.compile(r"\s+#.*$")
# A version token at the head of an alias remainder (`k3`, `v4-pro`, `k3.1`): the only case in
# which `canonical()` folds the vendor family word off, so `kimi-k3` and `k3` compare equal while
# `qwen-max` / `deepseek-flash` stay as they are.
VERSION_HEAD = re.compile(r"^[a-z]{0,2}\d")


class AttributionError(ValueError):
    """An input this script cannot read: a bad path, an unreadable wire, an unwritable artifact."""


class Degraded(RuntimeError):
    """No session/wire evidence exists — the attribution cannot confirm anything (exit 3)."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the messages may carry
    non-ASCII characters: `print_help()` would raise UnicodeEncodeError and the user would get a
    traceback instead of a usage line. `errors="replace"` keeps a stream that cannot be
    reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


# --------------------------------------------------------------------------------------------
# Aliases and roles
# --------------------------------------------------------------------------------------------

def _text(value) -> str:
    """A wire field as a stripped string; anything that is not a non-empty scalar is ""."""
    if value is None or isinstance(value, bool):
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def alias_of(event: dict) -> str:
    """The served alias of a model-bearing wire event (see rule 1 of the module docstring).

    `modelAlias` wins over `model`, because `model` is the WIRE name (`k3`) while the alias
    (`kimi-k3`) is the name the factory and the pipeline speak. A provider-qualified name
    (`kimi-code/k3`) is reduced to its model part, since a provider prefix is not part of the
    model identity.
    """
    alias = _text(event.get("modelAlias")) or _text(event.get("model"))
    alias = alias.lower()
    if "/" in alias:
        alias = alias.rsplit("/", 1)[1].strip()
    return alias


def canonical(alias: str) -> str:
    """The COMPARISON key of an alias (see rule 2 of the module docstring).

    Both sides of every claim-vs-wire comparison pass through it, so the vendor family word is
    folded off a VERSION token (`kimi-k3` -> `k3`, `deepseek-v4-pro` -> `v4-pro`) without ever
    making two DIFFERENT models equal (`kimi-k2` -> `k2` != `k3`, and a named model such as
    `deepseek-flash` or `qwen-max` is left untouched). An empty alias stays empty.
    """
    name = _text(alias).lower()
    if "/" in name:
        name = name.rsplit("/", 1)[1].strip()
    for family in FAMILY_WORDS:
        prefix = family + "-"
        if name.startswith(prefix) and VERSION_HEAD.match(name[len(prefix):]):
            return name[len(prefix):]
    return name


def role_from_profile(name: str) -> str:
    """The factory role a sub-agent profile name stands for; "" when the name is empty.

    `factory-code-reviewer` -> `reviewer`, `factory-gui-expert` -> `gui_expert`; the dash-to-
    underscore rule covers most profiles and ROLE_ALIASES pins the ones it cannot.
    """
    role = _text(name).lower()
    if role.startswith(PROFILE_PREFIX):
        role = role[len(PROFILE_PREFIX):]
    if not role:
        return ""
    return ROLE_ALIASES.get(role) or role.replace("-", "_")


# --------------------------------------------------------------------------------------------
# Session resolution
# --------------------------------------------------------------------------------------------

def norm_path(value) -> str:
    """A path normalised for comparison: absolute, forward slashes, case-folded on Windows.

    The wire stores the working directory exactly as the CLI saw it (`C:/x/y`), while `--repo`
    arrives as the shell spelled it (`C:\\x\\y`, `.`, a relative path), so both are resolved and
    flattened before they are compared. A path that cannot be resolved is only flattened.
    """
    raw = _text(value)
    if not raw:
        return ""
    try:
        raw = str(pathlib.Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):      # an unparsable or vanishing path
        pass
    text = raw.replace("\\", "/").rstrip("/")
    return text.casefold() if sys.platform == "win32" else text


def _wire_mtime(session_dir: pathlib.Path) -> float:
    """The newest `agents/*/wire.jsonl` mtime of a session (its own mtime when it has none)."""
    newest = 0.0
    agents = session_dir / AGENTS_DIR
    if agents.is_dir():
        for wire in agents.glob(f"*/{WIRE_FILE}"):
            try:
                newest = max(newest, wire.stat().st_mtime)
            except OSError:
                continue
    if newest:
        return newest
    try:
        return session_dir.stat().st_mtime
    except OSError:
        return 0.0


def session_candidates(home: pathlib.Path, repo: str) -> list[dict]:
    """Sessions whose `cwd` is `repo` and which are not archived, NEWEST LAST.

    Each candidate is `{"session_dir","session_id","state","wire_mtime"}`. Ordering is by wire
    mtime and then by sessionId, so the caller's `[-1]` pick is deterministic; the state object is
    carried along because the role labels live in it.
    """
    target = norm_path(repo)
    root = pathlib.Path(home) / SESSIONS_DIR
    if not target or not root.is_dir():
        return []
    found: list[dict] = []
    for state_path in root.glob(f"*/session_*/{STATE_FILE}"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):             # absent, a directory, a truncated write
            continue
        if not isinstance(state, dict) or state.get("archived") is True:
            continue
        if norm_path(state.get("cwd")) != target:
            continue
        session_dir = state_path.parent
        found.append({"session_dir": session_dir,
                      "session_id": _text(state.get("id")) or session_dir.name,
                      "state": state,
                      "wire_mtime": _wire_mtime(session_dir)})
    found.sort(key=lambda item: (item["wire_mtime"], item["session_id"]))
    return found


def index_session_id(home: pathlib.Path, repo: str) -> str:
    """The sessionId of the LAST `session_index.jsonl` line whose `workDir` is `repo` (else "")."""
    target = norm_path(repo)
    path = pathlib.Path(home) / SESSION_INDEX
    if not target or not path.is_file():
        return ""
    match = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and norm_path(entry.get("workDir")) == target:
            match = _text(entry.get("sessionId"))
    return match


def resolve_session(repo: str, session: str = "auto",
                    home: pathlib.Path | None = None) -> dict:
    """The session directory the attribution reads: an explicit one, or the current one.

    `session` is a directory (used as-is, `resolved_by: "arg"`) or `auto`. In auto mode the
    candidates of `session_candidates` are ranked and the newest one wins; the choice is
    corroborated with the last matching `session_index.jsonl` line, and a disagreement is recorded
    (`index_agrees: False`) instead of being hidden. Raises Degraded when auto finds nothing —
    the caller must then report DEGRADED (exit 3), never a silent success.
    """
    wire_home = pathlib.Path(home) if home is not None else WIRE_HOME
    wanted = _text(session) or "auto"
    result = {"resolved_by": "auto", "session_dir": None, "session_id": "", "state": {},
              "candidates": 0, "index_session_id": "", "index_agrees": False, "skipped": []}
    if wanted.lower() != "auto":
        directory = pathlib.Path(wanted).expanduser()
        if not directory.is_dir():
            raise AttributionError(f"session directory not found: {wanted}")
        result["resolved_by"] = "arg"
        result["session_dir"] = directory.resolve()
        result["session_id"] = directory.name
        state = _read_state(directory)
        if isinstance(state, dict):
            result["state"] = state
            result["session_id"] = _text(state.get("id")) or directory.name
        return result

    candidates = session_candidates(wire_home, repo)
    result["candidates"] = len(candidates)
    if not candidates:
        raise Degraded(f"no session under {wire_home / SESSIONS_DIR} whose state.json cwd is "
                       f"{pathlib.Path(repo)} (archived sessions excluded)")
    chosen = candidates[-1]
    result["session_dir"] = chosen["session_dir"]
    result["session_id"] = chosen["session_id"]
    result["state"] = chosen["state"]
    # The newest is the pick; a tie on mtime is broken by the highest sessionId (see the sort).
    result["skipped"] = [item["session_id"] for item in candidates[:-1]]
    indexed = index_session_id(wire_home, repo)
    result["index_session_id"] = indexed
    result["index_agrees"] = bool(indexed) and indexed == result["session_id"]
    return result


def _read_state(session_dir: pathlib.Path) -> dict:
    """`state.json` of a session as a dict ({} when absent or malformed — the wire decides)."""
    path = session_dir / STATE_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


# --------------------------------------------------------------------------------------------
# Reading the wire
# --------------------------------------------------------------------------------------------

def _blank() -> dict:
    """An empty per-agent accumulator."""
    return {"events": 0, "models_served": {}, "tokens": {}, "errors": {},
            "first_ms": None, "last_ms": None, "_usage": {}}


def _bump(counter: dict, key: str, amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


def _absorb(records: dict, spawns: dict, wire_agent: str, event: dict) -> None:
    """Fold ONE top-level wire event into the per-agent accumulators.

    The event is COUNTED and time-stamped whatever its type (so the artifact proves how much of the
    wire was read), but only a `type` in MODEL_EVENTS / ERROR_EVENTS can contribute a model:
    `llm.request` (the served model), `usage.record` (tokens + a model spelling),
    `subagent.spawned` (the role and the model the parent asked for) and the error events. That
    guard is the whole defence against the pitfall of the format — prompt and tools-snapshot events
    embed arbitrary JSON that may carry a `"model"` key, and such a decoy must never become a
    served model.
    """
    kind = event.get("type")
    if not isinstance(kind, str):
        return
    owner = records.setdefault(wire_agent, _blank())
    owner["events"] += 1
    at = event.get("time")
    if isinstance(at, (int, float)) and not isinstance(at, bool):
        owner["last_ms"] = at if owner["last_ms"] is None else max(owner["last_ms"], at)
        owner["first_ms"] = at if owner["first_ms"] is None else min(owner["first_ms"], at)
    if kind not in MODEL_EVENTS and kind not in ERROR_EVENTS:
        return                                     # read and counted, but never a model source

    if kind == "llm.request":
        alias = alias_of(event)
        if alias:
            _bump(owner["models_served"], alias)
        return
    if kind == "usage.record":
        alias = alias_of(event)
        if alias:
            _bump(owner["_usage"], alias)          # merged after the pass: evidence, not a count
        usage = event.get("usage")
        if isinstance(usage, dict):
            for name, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    _bump(owner["tokens"], str(name), int(value))
        return
    if kind == "subagent.spawned":
        subagent = _text(event.get("subagentId"))
        if subagent:
            spawns[subagent] = {"name": _text(event.get("subagentName")),
                                "model": alias_of(event),
                                "parent": _text(event.get("parentAgentId")) or wire_agent}
        return
    if kind in ERROR_EVENTS:
        # `subagent.failed` / `subagent.cancelled` live in the PARENT wire and name only the
        # subagent, so the subagent's own record is charged (falling back to the wire's agent).
        target = (_text(event.get("subagentId")) or _text(event.get("agentId")) or wire_agent)
        charged = records.setdefault(target, _blank())
        _bump(charged["errors"], kind)
        return


def analyse_session(session_dir: pathlib.Path) -> dict:
    """Read every `agents/*/wire.jsonl` of one session: per-agent records plus the spawn map.

    Returns `{"agents","spawns","skipped_lines","wires"}`. `skipped_lines` counts lines that are
    not a JSON object (a wire being appended to right now ends in a partial line) — they are
    reported, never fatal. A wire that cannot be READ at all is an input error (AttributionError,
    exit 2); a session with no wire at all is Degraded (exit 3).
    """
    agents_dir = pathlib.Path(session_dir) / AGENTS_DIR
    wires = sorted(wire for wire in agents_dir.glob(f"*/{WIRE_FILE}") if wire.is_file()) \
        if agents_dir.is_dir() else []
    if not wires:
        raise Degraded(f"session {pathlib.Path(session_dir).name} has no {AGENTS_DIR}/*/"
                       f"{WIRE_FILE}: no wire evidence to attribute models from")
    records: dict[str, dict] = {}
    spawns: dict[str, dict] = {}
    skipped = 0
    for wire in wires:
        agent_id = wire.parent.name
        try:
            text = wire.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AttributionError(f"cannot read the wire {wire}: {exc}") from exc
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                skipped += 1                       # a partial trailing line, or foreign content
                continue
            if not isinstance(event, dict):
                skipped += 1
                continue
            _absorb(records, spawns, agent_id, event)

    for record in records.values():
        # A usage.record whose alias never appeared in an llm.request is still evidence that the
        # model was served (some wires carry only usage records): count it once, not per record.
        for alias, count in record.pop("_usage", {}).items():
            if alias not in record["models_served"]:
                record["models_served"][alias] = count
        total = sum(record["tokens"].values())
        if total:
            record["tokens"]["total"] = total
    return {"agents": records, "spawns": spawns, "skipped_lines": skipped,
            "wires": [str(wire) for wire in wires]}


def agent_roles(state: dict, records: dict, spawns: dict) -> dict[str, str]:
    """Agent id -> factory role, from `state.json` labels first and `subagent.spawned` second.

    The state file is authoritative when it carries `labels.profileName`; a session whose state
    lacks the label (or an agent that only appears as a spawn target) falls back to the parent
    wire's `subagent.spawned.subagentName`. An id named `main` (or typed `main`) is always `main`;
    an agent nobody names stays `unknown` rather than being guessed into a role.
    """
    labels = state.get("agents") if isinstance(state, dict) else None
    labels = labels if isinstance(labels, dict) else {}
    roles: dict[str, str] = {}
    for agent_id in records:
        role = ""
        info = labels.get(agent_id)
        if isinstance(info, dict):
            profile = info.get("labels") if isinstance(info.get("labels"), dict) else {}
            role = role_from_profile(profile.get("profileName"))
            if not role and _text(info.get("type")).lower() == "main":
                role = "main"
        if not role:
            role = role_from_profile((spawns.get(agent_id) or {}).get("name"))
        if not role and agent_id == "main":
            role = "main"
        roles[agent_id] = role or "unknown"
    return roles


def _iso(ms) -> str:
    """An epoch-milliseconds wire timestamp as an ISO-8601 UTC string ("" when unusable)."""
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return ""
    try:
        stamp = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return stamp.isoformat().replace("+00:00", "Z")


def role_records(records: dict, spawns: dict, roles: dict[str, str]) -> dict[str, dict]:
    """Per-role aggregation of the per-agent records (the `roles` block of the artifact).

    Every agent keeps its own entry in `agents`; here the models, tokens, errors and times are
    summed per ROLE, because the claim (`models_used`) is per role. `spawn_model` is the model the
    PARENT asked for (empty for `main`, which nobody spawns) and `spawn_models` lists every
    distinct value, so a substitution requested by the parent is visible even when the subagent's
    own wire then served another model.
    """
    roles_out: dict[str, dict] = {}
    for agent_id, record in records.items():
        role = roles.get(agent_id, "unknown")
        entry = roles_out.setdefault(role, {
            "agents": [], "models_served": {}, "tokens": {}, "errors": {},
            "spawn_model": "", "spawn_models": [], "first_ms": None, "last_ms": None})
        entry["agents"].append(agent_id)
        for alias, count in record["models_served"].items():
            _bump(entry["models_served"], alias, count)
        for name, value in record["tokens"].items():
            _bump(entry["tokens"], name, value)
        for kind, count in record["errors"].items():
            _bump(entry["errors"], kind, count)
        spawned = (spawns.get(agent_id) or {}).get("model", "")
        if spawned:
            entry["spawn_model"] = entry["spawn_model"] or spawned
            if spawned not in entry["spawn_models"]:
                entry["spawn_models"].append(spawned)
        # Times are merged on the raw milliseconds, never on the formatted strings: two events in
        # the same second with and without microseconds must not order wrongly.
        for field, ms in (("first_ms", record["first_ms"]), ("last_ms", record["last_ms"])):
            if not ms:
                continue
            current = entry[field]
            if current is None:
                entry[field] = ms
            elif field == "last_ms":
                entry[field] = max(current, ms)
            else:
                entry[field] = min(current, ms)
    for entry in roles_out.values():
        entry["agents"].sort()
        entry["first_event"] = _iso(entry.pop("first_ms"))
        entry["last_event"] = _iso(entry.pop("last_ms"))
        total = sum(value for name, value in entry["tokens"].items() if name != "total")
        if total:
            entry["tokens"]["total"] = total
    return roles_out


def agent_block(records: dict, spawns: dict, roles: dict[str, str],
                state: dict) -> dict[str, dict]:
    """The `agents` block of the artifact: one entry per agent id, with its role and evidence."""
    labels = state.get("agents") if isinstance(state, dict) else None
    labels = labels if isinstance(labels, dict) else {}
    out: dict[str, dict] = {}
    for agent_id in sorted(records):
        record = records[agent_id]
        info = labels.get(agent_id) if isinstance(labels.get(agent_id), dict) else {}
        profile = info.get("labels") if isinstance(info.get("labels"), dict) else {}
        spawn = spawns.get(agent_id) or {}
        out[agent_id] = {
            "role": roles.get(agent_id, "unknown"),
            "profile": _text(profile.get("profileName")) or _text(spawn.get("name")),
            "parent": _text(info.get("parentAgentId")) or _text(spawn.get("parent")),
            "models_served": dict(sorted(record["models_served"].items())),
            "tokens": dict(sorted(record["tokens"].items())),
            "errors": dict(sorted(record["errors"].items())),
            "spawn_model": _text(spawn.get("model")),
            "events": record["events"],
            "first_event": _iso(record["first_ms"]),
            "last_event": _iso(record["last_ms"]),
        }
    return out


# --------------------------------------------------------------------------------------------
# The claim side
# --------------------------------------------------------------------------------------------

def _scalar(raw: str) -> str:
    """A YAML-ish scalar: trailing comment dropped, surrounding quotes removed."""
    value = TRAILING_COMMENT.sub("", raw).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def read_models_used(path: pathlib.Path) -> tuple[str, dict[str, str]]:
    """(run_id, {role: claim}) of a pipeline.yaml, read by hand — PyYAML is not a dependency.

    Only the two things the cross-check needs are read: the top-level `run_id` and the flat
    `models_used:` block of `role: value` scalars (the value may be quoted, carry a trailing
    comment, or be prose such as `deepseek-flash (plan written by the main agent)` — `claim_model`
    takes the model token out of it later). A missing file, an absent block or an empty block is
    not an error here; the caller decides what an empty claim set means.
    """
    run_id = ""
    claims: dict[str, str] = {}
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AttributionError(f"cannot read the pipeline checkpoint {path}: {exc}") from exc
    inside = False
    for line in text.splitlines():
        if not inside:
            match = RUN_ID_LINE.match(line.rstrip())
            if match and not run_id:
                run_id = _scalar(match.group(1))
            if MODELS_HEADER.match(line.rstrip()):
                inside = True
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = MODELS_ENTRY.match(line.rstrip())
        if not entry:
            break                                  # the block ended: another top-level key
        value = _scalar(entry.group(3))
        if value:
            claims[entry.group(2)] = value
    return run_id, claims


def claim_model(raw: str) -> str:
    """The model token of a `models_used` value: `"deepseek-flash (plan by main)"` -> the model.

    The pipeline writes prose behind the model sometimes, so the first whitespace/comma-delimited
    token is the claim. `unused` is kept as the sentinel it is (see `is_unused`).
    """
    text = _text(raw).strip("'\"")
    if not text:
        return ""
    return re.split(r"[\s,]+", text)[0].strip("'\"")


def is_unused(raw: str) -> bool:
    """True when the pipeline claims the role was not used at all."""
    return claim_model(raw).lower() == UNUSED


# --------------------------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------------------------

def _evidence(role_entry: dict | None) -> str:
    """`alias:count,alias:count` of the models a role was served, "": no model evidence."""
    served = (role_entry or {}).get("models_served") or {}
    return ",".join(f"{alias}:{count}" for alias, count in sorted(served.items()) if count)


def compare_claims(claims: dict[str, str], roles: dict[str, dict],
                   degraded_reason: str = "") -> tuple[dict[str, str], list[str], dict]:
    """Compare the pipeline's claims with what the wire served: (comparison, lines, flags).

    Statuses (the artifact's `comparison` mapping):
      `match`      the wire served exactly the claimed model (an `unused` claim with no evidence
                   also matches — the claim and the wire agree the role did not run);
      `mismatch`   the wire served another model — INCLUDING an `unused` claim whose role left
                   evidence, which is flagged in `flags.unused_but_wired` and never accepted;
      `degraded`   the session exists but this role left no model evidence;
      `unverified` there is no session at all, so nothing can be confirmed (`degraded_reason`).
    A role the pipeline does not claim at all is listed in `flags.unclaimed_roles` (the claim
    side is the factory's own contract, so an unclaimed wire role is informational, not a failure).
    """
    comparison: dict[str, str] = {}
    lines: list[str] = []
    flags: dict[str, list[str]] = {"unused_but_wired": [], "unclaimed_roles": []}
    for role in claims:
        raw = claims.get(role, "")
        claimed = claim_model(raw)
        evidence = _evidence(roles.get(role))
        if is_unused(raw):
            if evidence:
                comparison[role] = "mismatch"
                flags["unused_but_wired"].append(role)
                lines.append(f"{role}: mismatch (claimed=unused wire=[{evidence}]) -- the "
                             f"pipeline marks the role unused, but the wire served it")
            else:
                comparison[role] = "match"
                lines.append(f"{role}: match (claimed=unused, no wire agent)")
            continue
        if degraded_reason:
            comparison[role] = "unverified"
            lines.append(f"{role}: unverified (claimed but no wire agent) -- {degraded_reason}")
            continue
        if not evidence:
            comparison[role] = "degraded"
            lines.append(f"{role}: degraded (no wire for this role)")
            continue
        if not claimed:
            comparison[role] = "unverified"
            lines.append(f"{role}: unverified (claimed but no wire agent) -- the claim is empty")
            continue
        served = (roles.get(role) or {}).get("models_served") or {}
        if canonical(claimed) in {canonical(alias) for alias in served}:
            comparison[role] = "match"
            lines.append(f"{role}: match (claimed={claimed} wire=[{evidence}])")
        else:
            comparison[role] = "mismatch"
            lines.append(f"{role}: mismatch (claimed={claimed} wire=[{evidence}])")
    for role in sorted(roles):
        if role in claims or not _evidence(roles[role]):
            continue
        flags["unclaimed_roles"].append(role)
    return comparison, lines, flags


def verdict_of(comparison: dict[str, str], degraded_reason: str = "",
               claims_required: bool = True) -> str:
    """`FAIL` when a claim is disproven, else `DEGRADED` when anything is unconfirmed, else `PASS`.

    A proven mismatch is NEVER hidden by a degradation: the wire disproving a claim is the one
    finding the owner must not lose, so it wins.

    An EMPTY comparison is not a success while a claim set was required (`claims_required`, the
    default): with nothing compared, "every claimed role matches the wire" is vacuously true and
    the exit code would claim an artifact-backed confirmation of a model that was never named — so
    a pipeline that names no role in `models_used` is DEGRADED. Only a caller that asks for a
    claim-free wire report (no `--pipeline` at all, `claims_required=False`) may pass on nothing.
    """
    if any(status == "mismatch" for status in comparison.values()):
        return "FAIL"
    if degraded_reason or (claims_required and not comparison) or \
            any(status in ("degraded", "unverified") for status in comparison.values()):
        return "DEGRADED"
    return "PASS"


def write_artifact(path: pathlib.Path, report: dict) -> pathlib.Path:
    """Write the JSON artifact (creating its parent directory); raise AttributionError if it fails."""
    target = pathlib.Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    except OSError as exc:
        raise AttributionError(f"cannot write the artifact {target}: {exc}") from exc
    return target


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def build_report(repo: str, session: str, home: pathlib.Path | None,
                 pipeline) -> tuple[dict, list[str], str, str]:
    """Do the whole job: (artifact, printed lines, verdict, degraded reason).

    Raises AttributionError for an input error (exit 2). A missing session/wire is NOT an error:
    it yields an artifact with `attribution_degraded: true` and the reason, so the flow can record
    `models_warning` instead of staying silent.
    """
    wire_home = pathlib.Path(home) if home is not None else WIRE_HOME
    run_id = ""
    claims: dict[str, str] = {}
    pipeline_text = ""
    if pipeline is not None:
        run_id, claims = read_models_used(pipeline)
        pipeline_text = str(pipeline)

    degraded_reason = ""
    session_info: dict = {}
    analysis = {"agents": {}, "spawns": {}, "skipped_lines": 0, "wires": []}
    try:
        session_info = resolve_session(repo, session, wire_home)
        analysis = analyse_session(session_info["session_dir"])
    except Degraded as exc:
        degraded_reason = str(exc)
        if not session_info:
            session_info = {"resolved_by": "auto" if (_text(session) or "auto").lower() == "auto"
                            else "arg", "session_dir": None, "session_id": "",
                            "candidates": 0, "index_session_id": "", "index_agrees": False}

    state = session_info.get("state") or {}
    roles_by_agent = agent_roles(state, analysis["agents"], analysis["spawns"])
    roles = role_records(analysis["agents"], analysis["spawns"], roles_by_agent)
    if pipeline is not None and not claims:
        # A pipeline whose `models_used` block is empty or absent names no model to confirm: the
        # run would otherwise exit 0 on an empty comparison, i.e. claim "attributed" without one
        # single model checked. It is DEGRADED, exactly like a missing wire.
        degraded_reason = degraded_reason or (
            f"{pipeline} declares no models_used role: there is no claimed model to confirm "
            f"against the wire")
    comparison, lines, flags = compare_claims(claims, roles, degraded_reason)
    verdict = verdict_of(comparison, degraded_reason, claims_required=pipeline is not None)
    session_dir = session_info.get("session_dir")
    skipped_lines = analysis["skipped_lines"]

    report = {
        "run_id": run_id or None,
        "session": {
            "id": session_info.get("session_id") or None,
            "dir": str(session_dir) if session_dir else None,
            "cwd": _text(state.get("cwd")) or None,
            "archived": state.get("archived"),
            "candidates": session_info.get("candidates", 0),
            "superseded": session_info.get("skipped", []),
            "session_index": session_info.get("index_session_id") or None,
            "index_agrees": bool(session_info.get("index_agrees")),
            "wire_files": len(analysis["wires"]),
            "skipped_lines": skipped_lines,
            "home": str(wire_home),
            "repo": str(pathlib.Path(repo)),
        },
        "resolved_by": session_info.get("resolved_by", "auto"),
        "agents": agent_block(analysis["agents"], analysis["spawns"], roles_by_agent, state),
        "roles": roles,
        "claims": {
            "source": pipeline_text or None,
            "run_id": run_id or None,
            "models": dict(claims),
            "unused": [role for role, raw in claims.items() if is_unused(raw)],
            "compared": len(claims),
        },
        "comparison": comparison,
        "verdict": verdict,
        "attribution_degraded": bool(degraded_reason) or verdict == "DEGRADED",
        "degraded_reason": degraded_reason or None,
        "flags": flags,
        "report": lines,
        "generated_at": _iso(datetime.datetime.now(tz=datetime.timezone.utc).timestamp() * 1000),
    }
    return report, lines, verdict, degraded_reason


def _summary(verdict: str, report: dict, degraded_reason: str) -> str:
    """The one-line summary of the run, WITHOUT the verdict prefix (never a fake success)."""
    comparison = report["comparison"]
    if verdict == "FAIL":
        bad = []
        for role, status in comparison.items():
            if status != "mismatch":
                continue
            claimed = claim_model(report["claims"]["models"].get(role, ""))
            bad.append(f"{role} claimed={claimed} wire=[{_evidence(report['roles'].get(role))}]")
        return (f"{len(bad)} of {len(comparison)} claimed role(s) do not match the wire: "
                + "; ".join(bad))
    if verdict == "DEGRADED":
        if degraded_reason:
            return f"attribution is not possible: {degraded_reason}"
        unconfirmed = [role for role, status in comparison.items()
                       if status in ("degraded", "unverified")]
        return (f"{len(unconfirmed)} of {len(comparison)} claimed role(s) left no wire evidence: "
                + ", ".join(unconfirmed))
    if not comparison:
        return (f"session {report['session']['id']} read ({len(report['agents'])} agent(s), "
                f"{len(report['roles'])} role(s)); no models_used claim to cross-check")
    return (f"session {report['session']['id']}: every one of the {len(comparison)} claimed "
            f"role(s) matches the wire")


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="auto",
                    help="Session directory, or 'auto' to resolve the current session (default)")
    ap.add_argument("--repo", required=True, help="Path to the project (whose sessions are read)")
    ap.add_argument("--out", required=True, help="JSON artifact to write")
    ap.add_argument("--pipeline", default=None,
                    help="The run's pipeline.yaml: its run_id + models_used are cross-checked")
    ap.add_argument("--home", default=None,
                    help=f"The CLI's wire root (default: {WIRE_HOME})")
    ap.add_argument("--quiet", action="store_true", help="Print only the final summary line")
    args = ap.parse_args()

    try:
        report, lines, verdict, degraded_reason = build_report(
            args.repo, args.session, args.home, args.pipeline)
        out = write_artifact(pathlib.Path(args.out), report)
    except AttributionError as exc:
        print(f"model_attribution.py: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        for line in lines:
            print(line)
        flags = report["flags"]
        if flags["unclaimed_roles"]:
            print("NOTE - served by the wire but not claimed in models_used: "
                  + ", ".join(flags["unclaimed_roles"]))
        if not report["session"]["index_agrees"] and report["session"]["session_index"]:
            print(f"NOTE - session_index.jsonl names {report['session']['session_index']} for this "
                  f"repo, the wire mtime pick is {report['session']['id']}")
    if degraded_reason:
        print(f"model_attribution.py: DEGRADED - {degraded_reason}", file=sys.stderr)

    print(f"{verdict} - {_summary(verdict, report, degraded_reason)} ({out})")
    return {"PASS": 0, "FAIL": 1, "DEGRADED": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())

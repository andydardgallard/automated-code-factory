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

  There is no session-id environment variable, and the run's session `cwd` is NOT the resolved
  `--repo` whenever the factory is launched from its own directory for another project — the
  reported defect. `--session auto` is therefore bound to the run's OWN evidence in
  `pipeline.yaml` (`session_dir`, `launch_dir`, `started_at`, `run_id`): the declared
  `session_dir` wins when it exists, runs in the launch directory or the target repository and is
  not older than `started_at`; otherwise the candidates are the non-archived
  `sessions/*/session_*/state.json` whose `cwd` is one of those two (path-normalised,
  case-insensitively on Windows) AND whose newest `agents/*/wire.jsonl` mtime is at or after
  `started_at`. Zero candidates is DEGRADED (a wire from a finished run must never be audited),
  exactly one is the pick, and several are narrowed by the run's `run_id` occurring in the wire;
  anything still ambiguous is DEGRADED, never a guess. Without that evidence the historical rule
  stands (newest non-archived session of `--repo`). The pick is corroborated with the LAST
  `session_index.jsonl` line whose `workDir` matches the session's own `cwd`; a disagreement is
  FLAGGED (`session.index_agrees: false`), never hidden. An explicit `--session <dir>` is used
  as-is (`resolved_by: "arg"`) but validated as the current run when the pipeline dates the run
  (a wire written before `started_at` is DEGRADED), and a BLANK `--session` is an input error
  (exit 2) — "blank" is never a synonym for `auto`.

ALIAS NORMALISATION (the only two rules this script applies)

  1. `alias_of(event)`: `modelAlias` when present and non-empty, else `model`; lowercased; a
     provider-qualified name is reduced to its model part (`kimi-code/k3` -> `k3`). That is the
     key `models_served` counts are reported under.
  2. `canonical(alias)`: the COMPARISON key — the same reduction as (1), then normalized to
     `<vendor>/<version>` for a versioned alias (`kimi-k3` -> `kimi/k3`, `k3` -> `kimi/k3`), so a
     claim written the way the pipeline writes it (`kimi-k3`) matches a wire that spells the same
     model differently (`k3`). Only documented spellings of the SAME vendor are equivalent
     (`moonshot` IS the Kimi vendor, `dashscope` the qwen provider); the vendor itself is never
     folded away, so a cross-vendor same-version pair (`kimi-k3` vs `deepseek-k3`) can never look
     equal, and neither can two versions of one vendor (`kimi/k2` != `kimi/k3`).

ROLE RESOLUTION

  Per agent id: `state.json` `agents[id].labels.profileName` -> role (`factory-` prefix stripped,
  `code-reviewer`->`reviewer`, `gui-expert`->`gui_expert`, `farukon-expert`->`farukon_expert`,
  `roblox-expert`->`roblox_expert`,
  `security-auditor`->`security_auditor`, `skill-manager`->`skill_manager`, `main` stays `main`);
  when the state carries no profile, the
  parent wire's `subagent.spawned.subagentName` supplies it. Per role the script accumulates
  `models_served`, `tokens` (from `usage.record`), `errors` (by event type), `spawn_model` (the
  model the parent asked for) and the first/last event time.

PUBLIC API

  use_utf8_output()                       force UTF-8 on stdout/stderr (house convention)
  alias_of(event)                         the served alias of a model-bearing wire event
  canonical(alias)                        the comparison key of an alias (see above)
  role_from_profile(name)                 `factory-code-reviewer` -> `reviewer`, "" when unnamed
  session_candidates(home, repo, extra_dirs, since_ms)
                                          matching, non-stale, newest-last candidate sessions
  index_session_id(home, repo)            session id of the last matching session_index line
  resolve_session(repo, session, home, pipeline)
                                          {"session_dir","session_id","resolved_by",...}; the
                                          run-bound session, else Degraded (a blank session is
                                          an input error)
  read_models_used(path)                  (run_id, {role: claim}) of a pipeline.yaml
  read_pipeline_contract(path)            the same plus `task_type`, `required_roles` and the
                                          run binding (`launch_dir`/`session_dir`/`started_at`)
  strict_decision(task_type, declared)    (strict, reason): the DEFAULT is implement/refactor
  required_unbacked(comparison, claims, required_roles, strict, wired)
                                          REQUIRED roles the session wire never confirmed
  wired_roles(roles)                      the roles the wire actually traced (`spawn`/served)
  unknown_roles(claims)                   `models_used` keys the factory's registry does not have
  unknown_role_line(role)                 the one-line report of such a key (a run error)
  analyse_session(session_dir)            per-agent records + spawn map of one session
  agent_roles(state, records, spawns)     agent id -> role
  compare_claims(claims, roles, degraded) (comparison, lines, flags) of claims vs wire
  verdict_of(comparison, reason, required) FAIL / DEGRADED / PASS of a comparison
  build_report(...) / write_artifact(...) the JSON artifact of the run

STRICT ATTRIBUTION

  A run that declares `task_type: implement|refactor` in `pipeline.yaml` is STRICT BY DEFAULT:
  EVERY role listed in `required_roles` must be backed by session-wire evidence
  (`subagent.spawned`, or a model the wire served for that role). A role the wire never traced
  FAILS the run (exit 1, status `unbacked`, the role named in the summary), never DEGRADED — the
  run declared that role mandatory, so "no wire for this role" is the missing artifact, not a
  technical detail. The check is on the WIRE, not on the claim: a required role that is OMITTED
  from `models_used` is checked exactly like a claimed one, so dropping the claim is not a way to
  bypass strict attribution (the reported violation: a planner that was required, claimed, had no
  planner spawn, and whose claim could simply have been deleted to pass). A required role that IS
  on the wire needs no claim. `--strict` forces the same rule for `review`/`security_audit`
  runs, and there is deliberately NO opt-out that weakens it. A declared `task_type` outside the four
  is an input error (exit 2); a checkpoint without `task_type` keeps the historical behaviour. A
  CONDITIONAL role (`gui_expert`, `farukon_expert`, `roblox_expert`, `security_auditor`) never
  fails on its own: it must be claimed (`models_used`) AND required before its wire is demanded, so
  a task that does not use it produces no false failure. (business_tester is mandatory for
  implement/refactor via the checkpoint contract of check_factory_model.py, not conditional.)

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
    `role: unbacked (claimed=X|no models_used claim, no subagent.spawned trace)`
                                                    a REQUIRED role the strict run cannot confirm
    `role: run error -- not a role of the factory`  the pipeline invented a role (see below)
  The last line is always `PASS|FAIL|DEGRADED - <summary> (<out path>)`.

  A `models_used` key that is not a role of the factory — not in `model_matrix.ROLES`, with `main`
  the one non-matrix key the flow legitimately logs — is a RUN ERROR, never a degradation: it used
  to fall through to "no wire for this role" (DEGRADED, exit 3), which filed a contract breach as
  a technical detail. The registry is imported from `model_matrix`, so it has ONE source.

EXIT CODES

  0  the session was found and every claimed role matches the wire (with no --pipeline there is
     no claim side at all, so the run is a wire REPORT: it prints the roles and exits 0)
  1  a claim the wire disproves (a role MISMATCH) or a `models_used` role the factory does not
     have — never hidden by a degradation
  2  input error: a bad path, an unreadable wire, an unwritable --out (message, no traceback)
  3  DEGRADED: no session/wire found, a claimed role left no wire evidence, a malformed or
     foreign wire record was skipped (only a genuinely TRUNCATED, not newline-terminated final
     JSON record of a wire being written is tolerated — unparsed evidence could hide a served
     model), or `--pipeline` was
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

from model_matrix import ROLES      # the ONE role registry of the factory (`models_used` keys)

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
                "farukon-expert": "farukon_expert", "roblox-expert": "roblox_expert",
                "security-auditor": "security_auditor", "skill-manager": "skill_manager"}
# Vendor identity behind the alias spellings the CLI and the pipeline use. Spellings of the SAME
# vendor normalize to ONE vendor key (`kimi-k3` and `moonshot-k3` are one vendor's model; dashscope
# is the qwen provider), and `canonical()` keeps that vendor in the comparison key, so a
# cross-vendor same-version pair (`kimi-k3` vs `deepseek-k3`) can NEVER compare equal — reporting
# that substitution as a match was exactly the defect this table closes.
VENDOR_EQUIVALENTS = (("kimi", ("kimi", "moonshot")),
                      ("deepseek", ("deepseek",)),
                      ("qwen", ("qwen", "dashscope")))
# A BARE version token (`k3`, `k3.1`) is how the wire spells a Kimi-line model whose CLI alias is
# `kimi-k3` (see model_matrix's family table: a bare version token is a Kimi version). Every other
# vendor's model carries its vendor word, so the vendor-less default is the Kimi line and only it.
BARE_VERSION_VENDOR = "kimi"
# The role registry of the factory (`model_matrix.ROLES`) plus the one key that is NOT a matrix
# role: `models_used` also logs the main agent's own session model. A `models_used` key outside
# this set is a RUN ERROR, not a degradation — the pipeline named a role the factory does not have,
# and "no wire for this role" would file a contract breach as a technical detail.
NON_MATRIX_ROLES = ("main",)
KNOWN_ROLES = NON_MATRIX_ROLES + tuple(ROLES)
REGISTRY_HINT = "model_matrix.ROLES (" + ", ".join(ROLES) + ")"

# The flat `models_used:` block of a pipeline.yaml: `run_id` plus `role: alias` scalars. A
# deliberately small reader — the factory owns the checkpoint format and must not grow a YAML
# parser (mirrors `model_matrix.task_models`).
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
MODELS_HEADER = re.compile(r"^models_used:\s*(#.*)?$")
MODELS_ENTRY = re.compile(r"^(\s+)([A-Za-z0-9_]+)\s*:\s*(\S.*?)\s*$")
TRAILING_COMMENT = re.compile(r"\s+#.*$")
# The strict-attribution contract of the checkpoint: the run's `task_type` and the roles the run
# declares as REQUIRED. Both are read with the same deliberately small reader.
TASK_TYPE_LINE = re.compile(r"^task_type:\s*(.*)$")
REQUIRED_ROLES_LINE = re.compile(r"^required_roles:\s*(.*)$")
REQUIRED_ROLE_ITEM = re.compile(r"^\s+-\s+(.*\S)\s*$")
# The run's own evidence of WHERE it started and WHEN. `auto` session resolution is bound to these
# instead of assuming the run's `cwd` is `--repo`: the factory is launched from its deployment
# directory while `repo_path` points at another project, and the run's session carries the LAUNCH
# directory as its `cwd`.
LAUNCH_DIR_LINE = re.compile(r"^launch_dir:\s*(.*)$")
SESSION_DIR_LINE = re.compile(r"^session_dir:\s*(.*)$")
STARTED_AT_LINE = re.compile(r"^started_at:\s*(.*)$")
# A wire file written this long before the run's `started_at` cannot belong to the run (mtime
# granularity and a clock skew allowance).
FRESH_SLACK_MS = 5000.0
# The four task types the factory knows. Strict attribution is the DEFAULT for the two that
# produce or preserve code (`implement`, `refactor`); `--strict` forces it for the other two and
# there is no weakening opt-out — a claim the wire cannot confirm must never pass silently.
TASK_TYPES = ("implement", "review", "refactor", "security_audit")
STRICT_TASK_TYPES = ("implement", "refactor")
# Roles whose presence depends on the task: they may be listed in `required_roles`, and a
# conditional role that is NOT claimed in `models_used` never fails — its wire is demanded only when
# the run itself claims it ran. Every NON-conditional required role is checked against the wire even
# when `models_used` omits it. The model check validates the list; this script only applies it.
# business_tester is NOT here: implement/refactor runs always delegate it, so it sits in the
# mandatory set of check_factory_model.py instead.
CONDITIONAL_ROLES = ("gui_expert", "farukon_expert", "roblox_expert", "security_auditor")
# A version token at the head of an alias remainder (`k3`, `v4-pro`, `k3.1`): the only case in
# which `canonical()` normalizes an alias to its `<vendor>/<version>` key, so `kimi-k3` and `k3`
# compare equal while `qwen-max` / `deepseek-flash` stay as they are.
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

    Both sides of every claim-vs-wire comparison pass through it. The key is `<vendor>/<version>`
    for a versioned alias, where the vendor comes from `VENDOR_EQUIVALENTS` — the ONLY equivalence
    applied is between documented spellings of the same vendor (`kimi-k3` and `moonshot-k3` ->
    `kimi/k3`), and a bare version token belongs to the Kimi line (`k3` -> `kimi/k3`), so the
    pipeline spelling (`kimi-k3`) still matches the wire spelling (`k3`). The vendor is NEVER
    folded away: two DIFFERENT vendors can never compare equal (`kimi-k3` -> `kimi/k3` !=
    `deepseek/k3` <- `deepseek-k3`), and neither can two versions of one vendor (`kimi/k2` !=
    `kimi/k3`). A named model (`deepseek-flash`, `qwen-max`) is left untouched. An empty alias
    stays empty.
    """
    name = _text(alias).lower()
    if "/" in name:
        name = name.rsplit("/", 1)[1].strip()
    if not name:
        return ""
    for vendor, spellings in VENDOR_EQUIVALENTS:
        for spelling in spellings:
            prefix = spelling + "-"
            if name.startswith(prefix) and VERSION_HEAD.match(name[len(prefix):]):
                return f"{vendor}/{name[len(prefix):]}"
    if VERSION_HEAD.match(name):
        return f"{BARE_VERSION_VENDOR}/{name}"
    return name


def role_from_profile(name: str) -> str:
    """The factory role a sub-agent profile name stands for; "" when the name is empty.

    `factory-code-reviewer` -> `reviewer`, `factory-gui-expert` -> `gui_expert`,
    `factory-farukon-expert` -> `farukon_expert`, `factory-roblox-expert` -> `roblox_expert`;
    the dash-to-underscore rule covers most profiles and ROLE_ALIASES pins the ones it cannot.
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


def session_candidates(home: pathlib.Path, repo: str, extra_dirs=(),
                       since_ms: float | None = None) -> list[dict]:
    """Sessions whose `cwd` is `repo` (or one of `extra_dirs`) and which are not archived.

    Each candidate is `{"session_dir","session_id","state","wire_mtime"}`, NEWEST LAST: ordering is
    by wire mtime and then by sessionId, so the caller's `[-1]` pick is deterministic; the state
    object is carried along because the role labels live in it. `extra_dirs` widens the set to the
    run's LAUNCH directory (the factory launched outside the target repository records that path as
    the session `cwd`). `since_ms` keeps only a session whose newest wire was written at or after
    that epoch-millisecond instant — the run's `started_at` — so an older run can never be a
    candidate for the current one.
    """
    targets = [norm_path(value) for value in (repo, *extra_dirs)]
    targets = [value for value in targets if value]
    root = pathlib.Path(home) / SESSIONS_DIR
    if not targets or not root.is_dir():
        return []
    floor = (since_ms - FRESH_SLACK_MS) / 1000.0 if since_ms is not None else None
    found: list[dict] = []
    for state_path in root.glob(f"*/session_*/{STATE_FILE}"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):             # absent, a directory, a truncated write
            continue
        if not isinstance(state, dict) or state.get("archived") is True:
            continue
        if norm_path(state.get("cwd")) not in targets:
            continue
        session_dir = state_path.parent
        wire_mtime = _wire_mtime(session_dir)
        if floor is not None and wire_mtime < floor:
            continue                              # written before this run started: another run
        found.append({"session_dir": session_dir,
                      "session_id": _text(state.get("id")) or session_dir.name,
                      "state": state,
                      "wire_mtime": wire_mtime})
    found.sort(key=lambda item: (item["wire_mtime"], item["session_id"]))
    return found


def _epoch_ms(value) -> float | None:
    """An ISO-8601 timestamp (or an epoch number) as epoch MILLISECONDS, or None."""
    raw = _text(value)
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        number = float(raw)
        return number if number >= 1e11 else number * 1000.0
    try:
        stamp = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.timestamp() * 1000.0


def _binding_of(pipeline) -> dict:
    """The run binding of a pipeline (a contract dict, a path, or None — never a guess)."""
    empty = {"run_id": "", "launch_dir": "", "session_dir": "", "started_at": ""}
    if pipeline is None:
        return empty
    if isinstance(pipeline, dict):
        binding = pipeline.get("run_binding") if "run_binding" in pipeline else pipeline
        if not isinstance(binding, dict):
            return empty
        return {key: _text(binding.get(key)) for key in empty}
    try:
        return read_pipeline_contract(pathlib.Path(pipeline))["run_binding"]
    except AttributionError:
        return empty


def _candidate_at(session_dir: pathlib.Path) -> dict | None:
    """The `session_candidates` record of ONE session directory (None when it is unusable)."""
    session_dir = pathlib.Path(session_dir)
    state = _read_state(session_dir)
    if not isinstance(state, dict) or state.get("archived") is True:
        return None
    return {"session_dir": session_dir,
            "session_id": _text(state.get("id")) or session_dir.name,
            "state": state,
            "wire_mtime": _wire_mtime(session_dir)}


def _wire_contains(session_dir: pathlib.Path, needle: str) -> bool:
    """Whether any `agents/*/wire.jsonl` of the session carries `needle` (the run's `run_id`)."""
    if not needle:
        return False
    agents = pathlib.Path(session_dir) / AGENTS_DIR
    if not agents.is_dir():
        return False
    for wire in agents.glob(f"*/{WIRE_FILE}"):
        try:
            if needle in wire.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _run_bound(candidate: dict, repo: str, launch: str) -> bool:
    """Whether the candidate session runs in the target repository or the run's launch directory."""
    cwd = norm_path(candidate["state"].get("cwd"))
    return bool(cwd) and cwd in {norm_path(repo), norm_path(launch)} - {""}


def resolve_session(repo: str, session: str = "auto",
                    home: pathlib.Path | None = None, pipeline=None) -> dict:
    """The session directory the attribution reads: an explicit one, or the CURRENT RUN's one.

    `session` is a directory (used as-is, `resolved_by: "arg"`) or `auto`; a BLANK value is an
    input error — "blank" is not a synonym for `auto`. In auto mode the run is bound to its own
    session with the pipeline's evidence (`pipeline` is the contract dict of
    `read_pipeline_contract`, a pipeline path, or None):

      - `session_dir` names the run's own session: when it exists, runs in the launch directory or
        the target repository and is not older than `started_at`, it IS the pick;
      - otherwise only sessions whose `cwd` is the target repository OR the launch directory and
        whose newest wire was written at/after `started_at` are candidates. Zero of them is
        DEGRADED (never a confident audit of an older run's wire), exactly one is the pick, and
        several are narrowed by the run's `run_id` appearing in the wire — anything still
        ambiguous is DEGRADED rather than a guess.

    Without that evidence the historical behaviour stands (newest non-archived session of
    `--repo`). The choice is corroborated with `session_index.jsonl` for the session's own
    workDir, and a disagreement is recorded (`index_agrees: False`) instead of being hidden.
    Raises Degraded when no current-run session can be established — the caller must then report
    DEGRADED (exit 3), never a silent success.
    """
    wire_home = pathlib.Path(home) if home is not None else WIRE_HOME
    wanted = _text(session)
    if not wanted:
        raise AttributionError(
            "--session is empty: name the current run's session directory, or pass 'auto' — a "
            "blank value is never a synonym for auto")
    binding = _binding_of(pipeline)
    launch = binding["launch_dir"]
    since = _epoch_ms(binding["started_at"])
    run_bound = bool(binding["session_dir"] or launch or since)
    result = {"resolved_by": "auto", "session_dir": None, "session_id": "", "state": {},
              "candidates": 0, "index_session_id": "", "index_agrees": False, "skipped": [],
              "bound_by": "", "run_bound": run_bound}
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
        _require_current(result["session_dir"], binding, since)
        result["bound_by"] = "arg"
        return result

    declared = _text(binding["session_dir"])
    declared_dir = pathlib.Path(declared).expanduser() if declared else None
    if declared_dir is not None and not declared_dir.is_dir():
        declared_dir = None
        result["bound_by"] = "pipeline.session_dir missing"
    if declared_dir is not None:
        chosen = _candidate_at(declared_dir)
        if chosen is None:
            result["bound_by"] = "pipeline.session_dir unusable"
        elif not _run_bound(chosen, repo, launch):
            raise Degraded(
                f"the pipeline names {declared_dir} as the run's session, but that session runs in "
                f"{_text(chosen['state'].get('cwd')) or 'an unknown directory'}, not in {repo} or "
                f"{launch or repo}: it is another run's wire, so it must never be audited")
        elif since is not None and chosen["wire_mtime"] < (since - FRESH_SLACK_MS) / 1000.0:
            result["bound_by"] = "pipeline.session_dir too old"
        else:
            result["bound_by"] = "pipeline.session_dir"
            result["candidates"] = 1
            return _resolved(result, chosen, wire_home, repo, run_bound=True)

    candidates = session_candidates(wire_home, repo, (launch,) if launch else (), since)
    result["candidates"] = len(candidates)
    if not candidates:
        raise Degraded(_missing_reason(wire_home, repo, launch, since, run_bound))
    chosen = candidates[-1]
    if len(candidates) > 1:
        traced = [item for item in candidates if _wire_contains(item["session_dir"],
                                                               binding["run_id"])]
        if len(traced) != 1:
            raise Degraded(
                f"{len(candidates)} session(s) under {wire_home / SESSIONS_DIR} could be this run "
                f"({' and '.join(item['session_id'] for item in candidates)}): the run's evidence "
                f"(session_dir/run_id) does not single one out, and auditing the wrong wire must "
                f"never happen — name the run's session with --session")
        chosen = traced[0]
    result["bound_by"] = "pipeline.launch_dir" if launch else "wire mtime"
    return _resolved(result, chosen, wire_home, repo, run_bound,
                     gathered=[item["session_id"] for item in candidates])


def _resolved(result: dict, chosen: dict, wire_home: pathlib.Path, repo: str,
              run_bound: bool, gathered: tuple | list = ()) -> dict:
    """Fill the resolution result from the chosen candidate (the one place the pick is recorded)."""
    result["session_dir"] = chosen["session_dir"]
    result["session_id"] = chosen["session_id"]
    result["state"] = chosen["state"]
    result["run_bound"] = run_bound
    result["skipped"] = [item for item in gathered if item != chosen["session_id"]]
    work_dir = _text(chosen["state"].get("cwd")) or repo
    indexed = index_session_id(wire_home, work_dir)
    result["index_session_id"] = indexed
    result["index_agrees"] = bool(indexed) and indexed == result["session_id"]
    return result


def _require_current(session_dir: pathlib.Path, binding: dict, since: float | None) -> None:
    """An explicit session must be the current run's wire, not another run's (Degraded if not)."""
    if since is None:
        return
    declared = norm_path(binding["session_dir"]) if binding["session_dir"] else ""
    if declared and declared == norm_path(session_dir):
        return
    if _wire_mtime(pathlib.Path(session_dir)) < (since - FRESH_SLACK_MS) / 1000.0:
        raise Degraded(
            f"the session {session_dir} was last written before this run started "
            f"({binding['started_at']}): it belongs to another run, so its wire must not be "
            f"audited as the current one")


def _missing_reason(wire_home: pathlib.Path, repo: str, launch: str, since: float | None,
                    run_bound: bool) -> str:
    """Why `auto` found no candidate — naming the run evidence that was actually required."""
    if not run_bound:
        return (f"no session under {wire_home / SESSIONS_DIR} whose state.json cwd is "
                f"{pathlib.Path(repo)} (archived sessions excluded)")
    where = " or ".join(path for path in (repo, launch) if path)
    started = _iso(since) if since is not None else "the run start"
    return (f"no session under {wire_home / SESSIONS_DIR} started with this run (cwd {where} and a "
            f"wire written since {started}): the current run's wire is missing, and an older "
            f"run's wire must never be audited in its place")



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


def is_truncated_record(line: str) -> bool:
    """True when `line` looks like a JSON OBJECT that was CUT OFF mid-record.

    A wire being appended to right now can end in a half-written record, and that one case is
    tolerated. Everything else is unparsed evidence. The shape is what separates the two: a
    truncated record starts like a JSON object (`{` and, usually, a quoted key) and its braces never
    balance — the writer died or had not finished. A line that merely fails to parse while looking
    complete (`<garbage>`, `{...} trailing`) or that closes its object but still is not JSON is
    malformed, never truncated.
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return False
    return stripped.count("{") > stripped.count("}")


def analyse_session(session_dir: pathlib.Path) -> dict:
    """Read every `agents/*/wire.jsonl` of one session: per-agent records plus the spawn map.

    Returns `{"agents","spawns","skipped_lines","malformed_lines","wires"}`. The ONE tolerated
    skip is a genuinely TRUNCATED final JSON record of a wire that is not newline-terminated
    (`skipped_lines`): a wire being appended to right now can end in a half-written object
    (`{"type": "llm.request", "model": "ki`). Everything else — an unparsable line ANYWHERE ELSE, an
    unparsable final line that is newline-terminated (the writer finished that line) or that does
    not even start like a JSON object, or a valid JSON value that is not an event object — is a
    malformed/foreign record and lands in `malformed_lines`: unparsed evidence could contain another
    served model or a substitution, so the caller turns ANY such record into a DEGRADED verdict,
    never a PASS. A wire that cannot be READ at all is an input error (AttributionError, exit 2); a
    session with no wire at all is Degraded (exit 3).
    """
    agents_dir = pathlib.Path(session_dir) / AGENTS_DIR
    wires = sorted(wire for wire in agents_dir.glob(f"*/{WIRE_FILE}") if wire.is_file()) \
        if agents_dir.is_dir() else []
    if not wires:
        raise Degraded(f"session {pathlib.Path(session_dir).name} has no {AGENTS_DIR}/*/"
                       f"{WIRE_FILE}: no wire evidence to attribute models from")
    records: dict[str, dict] = {}
    spawns: dict[str, dict] = {}
    partial = 0
    malformed = 0
    for wire in wires:
        agent_id = wire.parent.name
        try:
            text = wire.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AttributionError(f"cannot read the wire {wire}: {exc}") from exc
        terminated = text.endswith(("\n", "\r"))
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
            except ValueError:
                # Only a NOT-newline-terminated final line that was CUT OFF mid-object is the
                # half-written record of a wire being appended to; a terminated final line was
                # written completely, and any other unparsable text is malformed.
                if index == len(lines) - 1 and not terminated and is_truncated_record(line):
                    partial += 1
                else:
                    malformed += 1
                continue
            if not isinstance(event, dict):
                malformed += 1             # valid JSON but no wire event: foreign content
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
    return {"agents": records, "spawns": spawns, "skipped_lines": partial,
            "malformed_lines": malformed, "wires": [str(wire) for wire in wires]}


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
    return _parse_models_used(_pipeline_text(path))


def _pipeline_text(path: pathlib.Path) -> str:
    """The checkpoint TEXT (an unreadable file is an AttributionError -> exit 2)."""
    try:
        return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AttributionError(f"cannot read the pipeline checkpoint {path}: {exc}") from exc


def _parse_models_used(text: str) -> tuple[str, dict[str, str]]:
    run_id = ""
    claims: dict[str, str] = {}
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


def _parse_task_type(text: str) -> tuple[str, bool]:
    """`(task_type, declared)` — `declared` is True when the key is there, even with no value."""
    for line in text.splitlines():
        if line[:1].isspace():
            continue                               # a nested key is not the run's task_type
        match = TASK_TYPE_LINE.match(line.rstrip())
        if match:
            return _scalar(match.group(1)), True
    return "", False


def _parse_required_roles(text: str) -> list[str]:
    """The roles the run declares as required — a block list or a bracketed flow list, or []."""
    roles: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line[:1].isspace():
            continue
        match = REQUIRED_ROLES_LINE.match(line.rstrip())
        if not match:
            continue
        scalar = _scalar(match.group(1))
        if scalar.startswith("["):
            body = scalar.strip("[]")
            roles = [_scalar(item) for item in body.split(",")]
        else:
            for child in lines[index + 1:]:
                if child.strip() and not child[:1].isspace():
                    break
                item = REQUIRED_ROLE_ITEM.match(child)
                if item:
                    roles.append(_scalar(item.group(1)))
        break
    return [role for role in roles if role]


def _parse_run_binding(text: str) -> dict:
    """`{run_id, launch_dir, session_dir, started_at}` — the run's own session evidence, or ""."""
    binding = {"run_id": "", "launch_dir": "", "session_dir": "", "started_at": ""}
    for line in text.splitlines():
        if line[:1].isspace():
            continue                               # a nested key is not the run's own evidence
        for key, pattern in (("run_id", RUN_ID_LINE), ("launch_dir", LAUNCH_DIR_LINE),
                             ("session_dir", SESSION_DIR_LINE),
                             ("started_at", STARTED_AT_LINE)):
            match = pattern.match(line.rstrip())
            if match and not binding[key]:
                binding[key] = _scalar(match.group(1))
    return binding


def read_pipeline_contract(path: pathlib.Path) -> dict:
    """`{run_id, claims, task_type, task_type_declared, required_roles, run_binding}`.

    ONE reader for the whole strict-attribution contract: the claim side (`models_used`), the run's
    `task_type` (the default that decides whether strict attribution runs), `required_roles` (the
    roles whose claim the wire MUST confirm under strict attribution) and `run_binding` (where the
    run started, which session it is and when it started — the evidence `auto` resolution needs).
    """
    text = _pipeline_text(path)
    run_id, claims = _parse_models_used(text)
    task_type, declared = _parse_task_type(text)
    return {"run_id": run_id, "claims": claims, "task_type": task_type,
            "task_type_declared": declared, "required_roles": _parse_required_roles(text),
            "run_binding": _parse_run_binding(text)}


def strict_decision(task_type: str, declared: bool, forced: bool = False) -> tuple[bool, str]:
    """`(strict, reason)` — strict attribution is the DEFAULT for implement/refactor.

    `--strict` forces it for every task type; a declared `task_type` must be one of the four (an
    unknown or empty value is an input error, because the strict default cannot be decided from
    it); a checkpoint with no `task_type` at all keeps the historical non-strict behaviour. There is
    deliberately NO weakening opt-out: the only switch is the one that turns strictness ON.
    """
    if forced:
        return True, "--strict was requested: strict attribution runs whatever the task_type is"
    if not declared:
        return False, ("the checkpoint declares no task_type, so strict attribution stays off "
                       "(a flow that writes task_type gets it by default)")
    if task_type not in TASK_TYPES:
        raise AttributionError(
            f"the pipeline checkpoint declares task_type {task_type!r}, which is not one of "
            f"{', '.join(TASK_TYPES)}: a run must declare one of the four task types (or none, "
            f"which keeps strict attribution off)")
    if task_type in STRICT_TASK_TYPES:
        return True, f"task_type {task_type} requires strict attribution by default"
    return False, (f"task_type {task_type} is not strict by default — pass --strict to force it")


def wired_roles(roles: dict[str, dict]) -> set[str]:
    """The roles the session wire actually traced: a spawn, or a model it served for that role.

    A role entry exists for every agent the wire mentions, including one that only produced error
    events, so bare presence in `roles` is NOT evidence of a delegation. What counts is the artifact
    strict attribution happens to require: the `subagent.spawned` record (`spawn_model`) or a served
    model (`models_served`).
    """
    return {role for role, entry in roles.items()
            if (entry or {}).get("spawn_model") or _evidence(entry)}


def required_unbacked(comparison: dict[str, str], claims: dict[str, str],
                      required_roles: list[str], strict: bool,
                      wired: set[str] | None = None) -> list[str]:
    """Required roles the session wire never confirmed, under strict attribution.

    The defect this closes has TWO halves. A required role could be claimed in `models_used`, run on
    nothing the CLI ever recorded, and the run still exited 3 (DEGRADED). And — the bypass this
    function closed second — a required role could leave no trace AND leave no claim, because only
    CLAIMED required roles were checked: deleting the claim was a way to pass strict attribution
    outright. So the wire is the thing checked, not the claim: every required role needs wire
    evidence, whether `models_used` names it or not. A required role that IS on the wire needs no
    claim (the evidence is the artifact).

    Two documented exemptions keep the rule from producing false failures:
      * a CONDITIONAL role (`gui_expert`, `farukon_expert`, `roblox_expert`, `security_auditor`)
        that the run does not
        claim never fails on its own — its wire is demanded only when the run says it ran;
      * a role the pipeline claims as `unused` is not a claim the wire has to confirm for a
        non-required comparison, but a REQUIRED role marked unused is still a required role, so it
        is checked against the wire like any other (there is no "mark it unused" escape either).
    `wired` is the role set the wire actually traced (see `wired_roles`); None keeps the historical
    claim-only behaviour for a caller that supplies no wire evidence at all.
    """
    if not strict:
        return []
    unbacked: list[str] = []
    for role in required_roles:
        claimed = role in claims and not is_unused(claims.get(role, ""))
        if not claimed:
            if role in CONDITIONAL_ROLES or wired is None:
                continue
            if role not in wired:
                unbacked.append(role)
            continue
        if comparison.get(role) in ("degraded", "unverified"):
            unbacked.append(role)
    return sorted(unbacked)


def strict_failure_line(role: str, raw_claim: str, strict_reason: str) -> str:
    """The one-line report of a required role the wire never saw."""
    if raw_claim and not is_unused(raw_claim):
        return (f"{role}: unbacked (claimed={claim_model(raw_claim)}, no subagent.spawned trace) -- "
                f"a REQUIRED role whose claim the session wire cannot confirm FAILS the run, never "
                f"DEGRADED ({strict_reason})")
    return (f"{role}: unbacked (no models_used claim, no subagent.spawned trace) -- a REQUIRED role "
            f"must be visible on the session wire with or without a models_used claim, so omitting "
            f"the claim cannot bypass strict attribution; this FAILS the run, never DEGRADED "
            f"({strict_reason})")


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


def unknown_roles(claims: dict[str, str]) -> list[str]:
    """`models_used` keys that name no role of the factory, sorted (`main` aside).

    The registry is the single source (`model_matrix.ROLES`); `main` is the session model the
    factory logs next to the roles. A key nobody declared is not "a role without a wire" — it is a
    pipeline that invented a role, which the run must report as an error (exit 1).
    """
    return sorted(role for role in claims if role not in KNOWN_ROLES)


def unknown_role_line(role: str) -> str:
    """The one-line report of a `models_used` role the factory does not have."""
    return (f"{role}: run error -- not a role of the factory registry {REGISTRY_HINT}; a "
            f"models_used key must be one of {', '.join(KNOWN_ROLES)}")


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
      `match`      the wire served EXACTLY the claimed model — the served canonical set equals the
                   singleton claimed set, so a role served with the claim AND a fallback model is a
                   mismatch, not a match (an `unused` claim with no evidence also matches — the
                   claim and the wire agree the role did not run);
      `mismatch`   the wire served another model — INCLUDING an `unused` claim whose role left
                   evidence, which is flagged in `flags.unused_but_wired` and never accepted;
      `degraded`   the session exists but this role left no model evidence;
      `unverified` there is no session at all, so nothing can be confirmed (`degraded_reason`).
    A role the pipeline does not claim at all is listed in `flags.unclaimed_roles` (the claim
    side is the factory's own contract, so an unclaimed wire role is informational, not a failure).
    The FIFTH status of the artifact — `unknown_role`, for a `models_used` key outside the factory's
    registry — is not produced here: `build_report` adds it from `unknown_roles(claims)` and lists
    the key in `flags.unknown_roles`, because a key nobody declared is a run error (exit 1), not a
    comparison of a claim with the wire.
    """
    comparison: dict[str, str] = {}
    lines: list[str] = []
    flags: dict[str, list[str]] = {"unused_but_wired": [], "unclaimed_roles": [],
                                   "unknown_roles": [], "required_unbacked": []}
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
        # The served canonical set must EQUAL the singleton claimed set: a role the wire served
        # with the claimed model AND a substituted/fallback one is a mismatch, because "did this
        # role ever run the claimed model" is not the question — "did it run exactly that model" is.
        # Two spellings of one model (`k3` / `kimi-k3`) canonicalize to one element, so the
        # comparison is about models, not about alias strings.
        served_set = {canonical(alias) for alias, count in served.items() if count}
        if served_set == {canonical(claimed)}:
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
    """`FAIL` when a claim is disproven or a role is unknown, else `DEGRADED`, else `PASS`.

    A proven mismatch is NEVER hidden by a degradation: the wire disproving a claim is the one
    finding the owner must not lose, so it wins. A `models_used` role that is not in the factory's
    registry (`unknown_role`) is the same kind of finding — the pipeline invented a role — so it is
    a run error (FAIL), never a degradation. An `unbacked` status (a REQUIRED role the session wire
    never traced, under strict attribution, claimed in `models_used` or not) is a FAIL for the same
    reason: the run declared the role mandatory and produced no artifact proving it ran.

    An EMPTY comparison is not a success while a claim set was required (`claims_required`, the
    default): with nothing compared, "every claimed role matches the wire" is vacuously true and
    the exit code would claim an artifact-backed confirmation of a model that was never named — so
    a pipeline that names no role in `models_used` is DEGRADED. Only a caller that asks for a
    claim-free wire report (no `--pipeline` at all, `claims_required=False`) may pass on nothing.
    """
    if any(status in ("mismatch", "unknown_role", "unbacked") for status in comparison.values()):
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
                 pipeline, force_strict: bool = False) -> tuple[dict, list[str], str, str]:
    """Do the whole job: (artifact, printed lines, verdict, degraded reason).

    Raises AttributionError for an input error (exit 2). A missing session/wire is NOT an error:
    it yields an artifact with `attribution_degraded: true` and the reason, so the flow can record
    `models_warning` instead of staying silent. `force_strict` is the CLI's `--strict` (the only
    switch of the strict-attribution contract, and it only turns strictness ON).
    """
    wire_home = pathlib.Path(home) if home is not None else WIRE_HOME
    run_id = ""
    claims: dict[str, str] = {}
    pipeline_text = ""
    contract = {"task_type": "", "task_type_declared": False, "required_roles": []}
    if pipeline is not None:
        contract = read_pipeline_contract(pipeline)
        run_id, claims = contract["run_id"], contract["claims"]
        pipeline_text = str(pipeline)
    strict, strict_reason = strict_decision(contract["task_type"],
                                            contract["task_type_declared"], force_strict)

    degraded_reason = ""
    session_info: dict = {}
    analysis = {"agents": {}, "spawns": {}, "skipped_lines": 0, "malformed_lines": 0, "wires": []}
    try:
        session_info = resolve_session(repo, session, wire_home, contract)
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
    malformed_lines = analysis["malformed_lines"]
    if malformed_lines:
        # An unexplained skipped record is unparsed evidence: it could contain another served
        # model or a substitution, so the attribution can NEVER pass on it — DEGRADED, like a
        # missing wire. Only a genuinely TRUNCATED, not newline-terminated final record is
        # tolerated: a terminated final line was written completely, so it is malformed.
        degraded_reason = degraded_reason or (
            f"{malformed_lines} wire record(s) are malformed or foreign (only a truncated, not "
            f"newline-terminated final JSON record of a wire being written is tolerated): unparsed "
            f"evidence could hide a served model or a substitution, so the attribution must not "
            f"pass on it")
    comparison, lines, flags = compare_claims(claims, roles, degraded_reason)
    bogus = unknown_roles(claims)
    if bogus:
        # A role the factory does not have is a run error, not a degradation: report it FIRST (the
        # owner must see the contract breach before the per-role details) and force the verdict.
        for role in bogus:
            comparison[role] = "unknown_role"
            flags["unknown_roles"].append(role)
        lines = [unknown_role_line(role) for role in bogus] + lines
    unbacked = required_unbacked(comparison, claims, contract["required_roles"], strict,
                                 wired_roles(roles))
    if unbacked:
        # Strict attribution: a REQUIRED role the wire never confirmed is a run FAILURE, not a
        # degradation — the run declared the role mandatory, so "no wire for this role" is the
        # missing artifact, never a technical detail. The check reads the WIRE, so a required role
        # that `models_used` simply omits is caught exactly like a claimed one.
        for role in unbacked:
            comparison[role] = "unbacked"
            flags["required_unbacked"].append(role)
        lines = [strict_failure_line(role, claims.get(role, ""), strict_reason)
                 for role in unbacked] + lines
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
            "run_bound": bool(session_info.get("run_bound")),
            "bound_by": session_info.get("bound_by") or None,
            "wire_files": len(analysis["wires"]),
            "skipped_lines": skipped_lines,
            "malformed_lines": malformed_lines,
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
        "strict": bool(strict),
        "strict_reason": strict_reason,
        "task_type": contract["task_type"] or None,
        "required_roles": list(contract["required_roles"]),
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
        bogus = [role for role, status in comparison.items() if status == "unknown_role"]
        if bogus:
            return (f"{len(bogus)} models_used role(s) are not roles of the factory: "
                    + "; ".join(f"{role} is not in {REGISTRY_HINT}" for role in sorted(bogus))
                    + " -- a pipeline may only name the factory's own roles")
        unbacked = [role for role, status in comparison.items() if status == "unbacked"]
        if unbacked:
            return (f"{len(unbacked)} REQUIRED role(s) left no session-wire trace "
                    f"(no subagent.spawned trace): "
                    + ", ".join(f"{role} "
                                + (f"claimed={claim_model(report['claims']['models'][role])}"
                                   if report["claims"]["models"].get(role) else
                                   "has no models_used claim")
                                for role in sorted(unbacked))
                    + f" -- strict attribution ({report.get('strict_reason') or 'strict'}) requires "
                      f"wire evidence for every required role, claimed or not, and fails the run, "
                      f"never DEGRADED")
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
    ap.add_argument("--strict", action="store_true",
                    help="Force strict attribution for every task_type (a REQUIRED role with no "
                         "session-wire trace FAILS the run, claimed in models_used or not); there "
                         "is no weakening opt-out. It is the default already for implement/refactor")
    ap.add_argument("--quiet", action="store_true", help="Print only the final summary line")
    args = ap.parse_args()

    try:
        report, lines, verdict, degraded_reason = build_report(
            args.repo, args.session, args.home, args.pipeline, args.strict)
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
            print(f"NOTE - session_index.jsonl names {report['session']['session_index']} for the "
                  f"audited session's work directory, the pick is {report['session']['id']}")
    if degraded_reason:
        print(f"model_attribution.py: DEGRADED - {degraded_reason}", file=sys.stderr)

    print(f"{verdict} - {_summary(verdict, report, degraded_reason)} ({out})")
    return {"PASS": 0, "FAIL": 1, "DEGRADED": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())

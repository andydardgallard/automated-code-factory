#!/usr/bin/env python3
"""
The supervisor permit gate (proposal P-8's machine backstop, violation N-5) — zero LLM tokens.

WHY THIS EXISTS

task_15 registers `factory-supervisor`, a JUDGE-side role that reviews a proposed delegation's permit
against the rulebook and the approved plan. That verdict is MODEL-ENFORCED: a main agent that skips
the step is not physically stopped by a model reading prose. This script is the deterministic half:

  - a delegation is described by a PERMIT (`.code-factory/state/permits.yaml`), which must exist
    BEFORE the subagent is spawned;
  - the supervisor's `allow`|`deny` verdict and its evidence are recorded ON that permit;
  - the spawned agent id is bound to the permit it ran under;
  - the FINISH AUDIT joins the permits with the session wire (`subagent.spawned` events) and with the
    approved plan's task list: every spawn must match a unique, allowed, already-judged permit whose
    scope is a subset of the plan task's files, and every allowed permit must either have run or be
    explicitly closed.

FORMAT: `permits.yaml` is a JSON-compatible YAML document and is parsed with the STDLIB json module
(no YAML dependency, no hand-written parser). Shape:

  {"run_id": "<YYYYMMDD>-<8 hex>",
   "permits": [{"permit_id": "<id>", "task_id": "<plan task id>", "role": "<factory role>",
                "phase": "<lifecycle phase>", "scope": ["<repo-relative path>", ...],
                "constraints": ["<text>", ...], "created_at": "<ISO>",
                "verdict": null | "allow" | "deny", "evidence": "<text>",
                "verdict_at": "<ISO>", "verdict_at_ms": <int>,
                "agent_id": null | "<agent id>", "bound_at": null | "<ISO>",
                "closed": null | {"at": "<ISO>", "reason": "<text>"}}]}

SUBCOMMANDS

  init    --repo <root>                       create the skeleton {run_id, permits: []} (refuses to
                                              overwrite a file that already lists permits)
  add     --repo <root> --permit-id <id> --task-id <plan task id> --role <role> --phase <phase>
          [--scope <repo-relative path> ...] [--constraint <text> ...]
                                              register ONE permit; the task id must exist in the
                                              approved plan, the role must be registered, the phase
                                              must be a known lifecycle phase, every scope must be a
                                              confined repo-relative path, and an EMPTY scope is only
                                              allowed for a read-only / business-test role
  verdict --repo <root> --permit-id <id> --verdict allow|deny --evidence <text>
                                              record the supervisor's verdict (evidence is
                                              mandatory; a second verdict on the same permit fails)
  bind    --repo <root> --permit-id <id> --agent-id <id>
                                              record the agent id a permitted delegation spawned
                                              (only on an ALLOWED, judged permit; an agent id is
                                              unique across the whole file)
  close   --repo <root> --permit-id <id> --reason <text>
                                              mark an allowed permit as NOT executed (the only way an
                                              unused allow stops being an audit failure)
  audit   --repo <root> [--session <dir|auto>] [--home <path>]
                                              the FINISH gate (see below)

THE AUDIT (exit codes: 0 pass, 1 violation, 2 input error, 3 DEGRADED — no session wire to audit)

  Every `subagent.spawned` in the session wire must match a permit BY AGENT ID AND ROLE; the permit
  must be `allow` (a DENIED permit may never acquire an agent id, so a spawn under it is a breach);
  its verdict time must PRECEDE the spawn time; its scope must be a SUBSET of the files the approved
  plan declares for its task id; every allowed permit must be bound to a spawn or explicitly closed;
  and two permits may never share a permit id or an agent id. A wire line that is not a JSON object
  FAILS THE AUDIT CLOSED — an unreadable wire is exactly the state in which "every delegation was
  permitted" cannot be claimed. An absent session/wire is DEGRADED (exit 3), like the action audit.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import re
import sys
import tempfile

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The gate may be loaded BY PATH (gate_all.py, a test harness): the sibling modules it reuses
    # must be importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from manifest import ManifestError, confined_relpath  # noqa: E402
from model_matrix import ROLES  # noqa: E402

PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
PLAN_REL = pathlib.Path(".code-factory") / "state" / "plan.md"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"

VERDICTS = ("allow", "deny")
# The lifecycle phases a permit may be issued in: the factory's own phase names (analysis ->
# acceptance) plus the finish checkpoint. A closed vocabulary so `--phase nonsense` cannot pass.
PERMIT_PHASES = ("analysis", "plan", "implement", "review", "refactor", "security_audit",
                 "acceptance", "finish")
# The roles that produce NO file change — a read-only analysis or a business test — may carry an
# empty scope. Every other role must say which files it will touch: an empty scope for a coder or a
# documenter would permit an unbounded change behind a permit.
READ_ONLY_ROLES = frozenset({"analyzer", "planner", "reviewer", "diagnostician", "advisor",
                             "business_tester", "supervisor"})
PERMIT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
TASK_LINE = re.compile(r"^-\s+(?P<id>[A-Za-z][A-Za-z0-9_]*)\s*:\s*(?P<rest>.*)$")
FILES_FIELD = re.compile(r"\bfiles\s*:\s*(?P<files>.*?)(?:;\s*(?:deps|verify)\b|$)")


class PermitError(ValueError):
    """An input this script cannot honour: a message + exit 2, never a traceback."""


class PermitDegraded(RuntimeError):
    """There is no session wire to audit (exit 3): nothing was proven either way."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the verdicts survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def _now() -> tuple[str, int]:
    """`(ISO timestamp, epoch milliseconds)` of the moment a record is written."""
    moment = datetime.datetime.now(tz=datetime.timezone.utc)
    return moment.isoformat(timespec="seconds"), int(moment.timestamp() * 1000)


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise PermitError(f"repository root does not exist: {root}")
    return root


def plan_text(root: pathlib.Path) -> str:
    """The approved plan's text; a missing plan is an actionable error (there is nothing to check)."""
    path = root / PLAN_REL
    if not path.is_file():
        raise PermitError(f"no approved plan at {path}: a permit answers a PLAN task, so the plan "
                          f"must exist before any delegation is permitted")
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc


def plan_tasks(root: pathlib.Path) -> dict[str, list[str]]:
    """`{task_id: [declared file, ...]}` of the approved plan's DAG.

    A plan line `- task_09: ... files: a.py, b.py; deps: [...]` declares the files that task may
    touch; a task whose entry carries no `files:` field maps to an EMPTY list, which the audit treats
    as "the plan does not say", never as "anything is allowed".
    """
    tasks: dict[str, list[str]] = {}
    current: str | None = None
    for line in plan_text(root).splitlines():
        match = TASK_LINE.match(line)
        if match:
            current = match.group("id")
            tasks.setdefault(current, [])
            body = match.group("rest")
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            body = line.strip()                     # a wrapped continuation of the same entry
        else:
            current = None
            continue
        files = FILES_FIELD.search(body)
        if files and current is not None:
            declared = [item.strip() for item in files.group("files").split(",") if item.strip()]
            tasks[current] = declared
    return tasks


def pipeline_run_id(root: pathlib.Path) -> str:
    """The run id of the WIP checkpoint, format-checked (a permit belongs to exactly one run)."""
    path = root / PIPELINE_REL
    if not path.is_file():
        raise PermitError(f"no WIP checkpoint at {path}: the flow writes it (with the run_id) at the "
                          f"start of a run")
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = RUN_ID_LINE.match(line.rstrip())
            if match:
                run_id = match.group(1).strip().strip("'\"")
                if RUN_ID_RE.match(run_id):
                    return run_id
                raise PermitError(f"{path} carries run_id {run_id!r}, which is not "
                                  f"YYYYMMDD-<8 lowercase hex> (scripts/run_id.py gen computes it)")
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc
    raise PermitError(f"{path} declares no run_id: a permit must belong to exactly one run")


def _normalize_scope(root: pathlib.Path, raw: str) -> str:
    """One confined repo-relative scope path (a trailing `/` marks a directory and is dropped)."""
    text = (raw or "").strip().replace("\\", "/").rstrip("/")
    try:
        return confined_relpath(root, text)
    except ManifestError as exc:
        raise PermitError(str(exc)) from exc


def _within_plan(scope: str, declared: list[str]) -> bool:
    """Is `scope` EQUAL TO or BELOW one of the plan task's declared entries?

    The plan task grants a scope; a permit may narrow it, never widen it. So a permit on a FILE is
    inside a plan entry that declares that file or an ancestor DIRECTORY of it, and a permit on a
    DIRECTORY is inside a plan entry that declares the same directory or one of its ancestors — a
    permit on `src/` under a plan entry of `src/main.py` would authorise files the plan never
    mentions, which is exactly what the containment has to refuse.
    """
    for entry in declared:
        base = entry.rstrip("/")
        if scope == base or scope.startswith(base + "/"):
            return True
    return False


def _outside_plan(scopes: list[str], declared: list[str]) -> list[str]:
    """The permit scopes that are neither equal to nor beneath a declared plan entry."""
    return [scope for scope in scopes if not _within_plan(scope, declared)]


def _validate_role(role: str) -> str:
    if role == "main" or role not in ROLES:
        raise PermitError(f"role {role!r} is not a registered delegate role: the factory has "
                          f"{', '.join(ROLES)} (and `main` is the session itself, never a "
                          f"delegation)")
    return role


def _validate_permit_id(value: str, label: str = "permit id") -> str:
    if not PERMIT_ID_RE.match(value or ""):
        raise PermitError(f"the {label} must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                          f"{value!r}")
    return value


# ------------------------------------------------------------------------------------------ storage

def _empty(run_id: str) -> dict:
    return {"run_id": run_id, "permits": []}


def read_permits(root: pathlib.Path) -> dict:
    """The parsed permits file; an absent/malformed/ill-shaped one is an input error (exit 2)."""
    path = root / PERMITS_REL
    if not path.is_file():
        raise PermitError(f"no permits file at {path}: run `permit_gate.py init --repo {root}` "
                          f"first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermitError(f"{path} is not readable JSON (permits.yaml is JSON-compatible YAML): "
                          f"{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("permits"), list):
        raise PermitError(f"{path} must be an object with a 'permits' list")
    if not RUN_ID_RE.match(str(data.get("run_id", ""))):
        raise PermitError(f"{path}: run_id {data.get('run_id')!r} is not YYYYMMDD-<8 lowercase hex>")
    for index, permit in enumerate(data["permits"]):
        if not isinstance(permit, dict) or not isinstance(permit.get("permit_id"), str):
            raise PermitError(f"{path}: permits[{index}] must be an object with a 'permit_id'")
    return data


def _write_permits(root: pathlib.Path, data: dict) -> pathlib.Path:
    """Write the permits file deterministically and ATOMICALLY.

    A filesystem failure is DATA: it names the path and the OS reason and exits 2, and the permits
    file the run already had stays byte-identical (an audit must never read a half-written permit).
    """
    payload = {"run_id": data.get("run_id", ""), "permits": data.get("permits", [])}
    path = root / PERMITS_REL
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    except OSError as exc:
        raise PermitError(f"cannot write the permits file {path}: {exc}") from exc
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise PermitError(f"cannot write the permits file {path} (the previous one is untouched): "
                          f"{exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise
    return path


def _permit(data: dict, permit_id: str) -> dict:
    for permit in data["permits"]:
        if permit.get("permit_id") == permit_id:
            return permit
    known = ", ".join(sorted(str(permit.get("permit_id")) for permit in data["permits"])) or "none"
    raise PermitError(f"no permit {permit_id!r} in the file (known: {known})")


# -------------------------------------------------------------------------------------- subcommands

def init(root: str | pathlib.Path) -> dict:
    """Create the skeleton `{run_id, permits: []}`; a file that already lists permits is kept."""
    root = _checked_repo(root)
    run_id = pipeline_run_id(root)
    path = root / PERMITS_REL
    if path.is_file():
        existing = read_permits(root)
        if existing["permits"]:
            raise PermitError(f"{path} already lists {len(existing['permits'])} permit(s): it is "
                              f"created ONCE per run — a second init would forget them")
        if existing.get("run_id") == run_id:
            return {"status": "unchanged", "run_id": run_id, "permits": str(path)}
        _write_permits(root, _empty(run_id))
        return {"status": "reinitialized", "run_id": run_id, "permits": str(path)}
    _write_permits(root, _empty(run_id))
    return {"status": "created", "run_id": run_id, "permits": str(path)}


def add(root: str | pathlib.Path, permit_id: str, task_id: str, role: str, phase: str,
        scopes: list[str] | None = None, constraints: list[str] | None = None) -> dict:
    """Register ONE permit (validated against the plan, the registry, the phases and the scope)."""
    root = _checked_repo(root)
    _validate_permit_id(permit_id)
    _validate_role(role)
    if phase not in PERMIT_PHASES:
        raise PermitError(f"unknown phase {phase!r}: a permit names one of "
                          f"{', '.join(PERMIT_PHASES)}")
    tasks = plan_tasks(root)
    if task_id not in tasks:
        raise PermitError(f"task id {task_id!r} does not exist in the approved plan "
                          f"({PLAN_REL.as_posix()}): a permit may only answer a planned task "
                          f"({len(tasks)} task(s) known)")
    scopes_in = scopes or []
    normalized = [_normalize_scope(root, scope) for scope in scopes_in]
    duplicated = sorted({scope for scope in normalized if normalized.count(scope) > 1})
    if duplicated:
        raise PermitError(f"scope lists {', '.join(duplicated)} more than once")
    if not normalized and role not in READ_ONLY_ROLES:
        raise PermitError(f"role {role!r} changes files, so its permit needs at least one --scope "
                          f"(empty scope is allowed only for the read-only/business-test roles: "
                          f"{', '.join(sorted(READ_ONLY_ROLES))})")
    declared = tasks[task_id]
    if not declared:
        raise PermitError(f"plan task {task_id!r} declares no files, so the scope of this permit "
                          f"cannot be proven a subset of it: name the files in "
                          f"{PLAN_REL.as_posix()} first")
    outside = _outside_plan(normalized, declared)
    if outside:
        raise PermitError(f"scope {', '.join(outside)} is not declared by plan task {task_id!r} "
                          f"({', '.join(declared)}): a permit may narrow the plan task's scope, "
                          f"never widen it")
    data = read_permits(root)
    if any(permit.get("permit_id") == permit_id for permit in data["permits"]):
        raise PermitError(f"permit id {permit_id!r} is already used: a permit id is unique")
    created, _ms = _now()
    permit = {"permit_id": permit_id, "task_id": task_id, "role": role, "phase": phase,
              "scope": normalized, "constraints": [str(text).strip() for text in constraints or []
                                                   if str(text).strip()],
              "created_at": created, "verdict": None, "evidence": "", "verdict_at": None,
              "verdict_at_ms": None, "agent_id": None, "bound_at": None, "closed": None}
    data["permits"].append(permit)
    path = _write_permits(root, data)
    return {"status": "added", "permit": permit, "permits": str(path)}


def verdict(root: str | pathlib.Path, permit_id: str, decision: str, evidence: str) -> dict:
    """Record the supervisor's verdict (evidence mandatory; one verdict per permit)."""
    root = _checked_repo(root)
    if decision not in VERDICTS:
        raise PermitError(f"verdict must be one of {list(VERDICTS)}, got {decision!r}")
    text = (evidence or "").strip()
    if not text:
        raise PermitError("--evidence is required: a verdict without the artifact or rule it rests "
                          "on cannot be audited (an allow especially: it authorises a delegation)")
    data = read_permits(root)
    permit = _permit(data, permit_id)
    if permit.get("verdict") is not None:
        raise PermitError(f"permit {permit_id!r} already carries the verdict "
                          f"{permit['verdict']!r}: one permit, one verdict (open a new permit for a "
                          f"re-judged delegation)")
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} is already bound to agent "
                          f"{permit['agent_id']!r}: a verdict cannot follow the spawn")
    stamp, stamp_ms = _now()
    permit.update(verdict=decision, evidence=text, verdict_at=stamp, verdict_at_ms=stamp_ms)
    path = _write_permits(root, data)
    return {"status": "recorded", "permit_id": permit_id, "verdict": decision, "evidence": text,
            "verdict_at": stamp, "permits": str(path)}


def bind(root: str | pathlib.Path, permit_id: str, agent_id: str) -> dict:
    """Bind the spawned agent id to an ALLOWED permit (unique across the whole file)."""
    root = _checked_repo(root)
    if not AGENT_ID_RE.match(agent_id or ""):
        raise PermitError(f"--agent-id must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                          f"{agent_id!r}")
    data = read_permits(root)
    permit = _permit(data, permit_id)
    if permit.get("closed"):
        raise PermitError(f"permit {permit_id!r} is closed as NOT executed: a closed permit cannot "
                          f"acquire an agent id")
    if permit.get("verdict") != "allow":
        raise PermitError(f"permit {permit_id!r} is not allowed (verdict {permit.get('verdict')!r}):"
                          f" only an ALLOWED permit may be bound to a spawned agent — a denied "
                          f"permit NEVER acquires an agent id")
    for other in data["permits"]:
        if other is not permit and other.get("agent_id") == agent_id:
            raise PermitError(f"agent id {agent_id!r} is already bound to permit "
                              f"{other.get('permit_id')!r}: one agent, one permit")
    if permit.get("agent_id") == agent_id:
        return {"status": "unchanged", "permit_id": permit_id, "agent_id": agent_id,
                "permits": str(root / PERMITS_REL)}
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} is already bound to agent "
                          f"{permit['agent_id']!r}: a permit records the ONE agent it spawned")
    stamp, _ms = _now()
    permit.update(agent_id=agent_id, bound_at=stamp)
    path = _write_permits(root, data)
    return {"status": "bound", "permit_id": permit_id, "agent_id": agent_id,
            "permits": str(path)}


def close(root: str | pathlib.Path, permit_id: str, reason: str) -> dict:
    """Mark an ALLOWED, never-spawned permit as NOT executed (the reason is mandatory)."""
    root = _checked_repo(root)
    text = (reason or "").strip()
    if not text:
        raise PermitError("--reason is required: an unused permit is closed WITH the reason it was "
                          "not executed")
    data = read_permits(root)
    permit = _permit(data, permit_id)
    if permit.get("verdict") != "allow":
        raise PermitError(f"permit {permit_id!r} is not an allowed permit (verdict "
                          f"{permit.get('verdict')!r}): a denied permit needs no closure")
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} already ran under agent {permit['agent_id']!r}: a "
                          f"permit that spawned is not 'not executed'")
    if permit.get("closed"):
        return {"status": "unchanged", "permit_id": permit_id,
                "permits": str(root / PERMITS_REL)}
    stamp, _ms = _now()
    permit["closed"] = {"at": stamp, "reason": text}
    path = _write_permits(root, data)
    return {"status": "closed", "permit_id": permit_id, "reason": text, "permits": str(path)}


# -------------------------------------------------------------------------------------------- audit

def _attribution():
    """The sibling `model_attribution` module (session resolution), imported on demand."""
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import model_attribution  # noqa: PLC0415  (deliberately lazy)
    except ImportError as exc:
        raise PermitError(f"the permit audit reuses model_attribution.py's session resolution, "
                          f"which cannot be imported: {exc}") from exc
    return model_attribution


def wire_spawns(session_dir: pathlib.Path) -> tuple[list[dict], list[str], int]:
    """`(spawns, malformed, events)` of every `agents/*/wire.jsonl` of one session.

    A spawn is `{agent_id, role, time_ms, wire}`; a malformed line (not a JSON object) or a spawn
    with no readable time/role is REPORTED, never skipped.
    """
    attribution = _attribution()
    agents_dir = session_dir / attribution.AGENTS_DIR
    wires = sorted(wire for wire in agents_dir.glob(f"*/{attribution.WIRE_FILE}") if wire.is_file()) \
        if agents_dir.is_dir() else []
    if not wires:
        raise PermitDegraded(f"session {session_dir.name} has no {attribution.AGENTS_DIR}/*/"
                             f"{attribution.WIRE_FILE}: there is no spawn evidence to audit")
    spawns: list[dict] = []
    malformed: list[str] = []
    events = 0
    for wire in wires:
        try:
            text = wire.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise PermitError(f"cannot read the wire {wire}: {exc}") from exc
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(f"{wire}:{number}: not a JSON object (an unreadable wire cannot "
                                 f"prove that every delegation was permitted)")
                continue
            if not isinstance(event, dict):
                malformed.append(f"{wire}:{number}: the event is not a JSON object")
                continue
            events += 1
            if event.get("type") != "subagent.spawned":
                continue
            agent_id = event.get("subagentId")
            role = attribution.role_from_profile(str(event.get("subagentName") or ""))
            at = event.get("time")
            where = f"{wire}:{number}"
            if not isinstance(agent_id, str) or not agent_id:
                malformed.append(f"{where}: a spawn with no subagentId cannot be matched to a permit")
                continue
            if not role:
                malformed.append(f"{where}: spawn {agent_id!r} names no factory role "
                                 f"({event.get('subagentName')!r})")
                continue
            if not _usable_stamp(at):
                malformed.append(f"{where}: spawn {agent_id!r} carries no usable time "
                                 f"({at!r}): a millisecond stamp must be a finite number, never a "
                                 f"bool, a string, NaN or an infinity")
                continue
            spawns.append({"agent_id": agent_id, "role": role, "time_ms": int(at), "wire": where})
    return spawns, malformed, events


def _ownership_problems(permits: list[dict]) -> tuple[dict[str, list[dict]], list[str]]:
    """`(permits by agent id, problems)`: a permit id and an agent id each name ONE permit."""
    by_agent: dict[str, list[dict]] = {}
    for permit in permits:
        agent_id = permit.get("agent_id")
        if agent_id:
            by_agent.setdefault(agent_id, []).append(permit)
    permit_ids = [permit.get("permit_id") for permit in permits]
    problems: list[str] = []
    for duplicate in sorted({pid for pid in permit_ids if permit_ids.count(pid) > 1}):
        problems.append(f"duplicate permit id {duplicate!r}: one permit, one id")
    for agent_id, owners in sorted(by_agent.items()):
        if len(owners) > 1:
            problems.append(f"agent id {agent_id!r} is bound to {len(owners)} permits "
                            f"({', '.join(str(owner.get('permit_id')) for owner in owners)}): one "
                            f"agent, one permit")
    return by_agent, problems


def _usable_stamp(value: object) -> bool:
    """Can the gate COMPARE this value as a millisecond stamp?

    A stamp is a real number of milliseconds, never a bool, a string, NaN or an infinity. A Python
    int is unbounded and finite by nature, so `10**1000` is USABLE — it simply orders last, and
    converting it to float to "check" it would raise `OverflowError` instead of judging it. The
    predicate therefore never converts an int; only a float is tested with `math.isfinite`.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _verdict_order_problems(permit: dict, label: str, spawn: dict) -> list[str]:
    """The verdict stamp must be readable AND precede the spawn it permits.

    The stamp is a millisecond number this gate writes itself, so anything else — missing, a bool, a
    string, NaN, an infinity — makes the ORDER unprovable: that is an explicit violation, never a
    check silently skipped because an `isinstance(int)` test did not hold.
    """
    judged = permit.get("verdict_at_ms")
    if judged is None:
        return [f"unreadable verdict time: {label} carries no verdict_at_ms, so the order of the "
                f"verdict and the spawn {spawn['agent_id']!r} cannot be proven ({spawn['wire']})"]
    if not _usable_stamp(judged):
        return [f"unreadable verdict time: {label} carries verdict_at_ms {judged!r}, which is not "
                f"a finite number ({spawn['wire']})"]
    if judged > spawn["time_ms"]:
        return [f"out-of-order verdict: {label} was allowed at {permit.get('verdict_at')}, AFTER "
                f"agent {spawn['agent_id']!r} spawned ({spawn['wire']}): a verdict precedes the "
                f"spawn it permits"]
    return []


def _spawn_problems(spawn: dict, by_agent: dict[str, list[dict]],
                    tasks: dict[str, list[str]]) -> list[str]:
    """Why one wire spawn is not covered by a valid permit (empty = the delegation was permitted)."""
    owners = by_agent.get(spawn["agent_id"], [])
    if not owners:
        return [f"permit-less delegation: agent {spawn['agent_id']!r} (role {spawn['role']!r}) "
                f"spawned at {spawn['wire']} with NO permit"]
    if len(owners) > 1:
        return []                                        # already reported as a duplicate
    permit = owners[0]
    label = f"permit {permit.get('permit_id')!r}"
    problems: list[str] = []
    if permit.get("verdict") == "deny":
        return [f"denied permit executed: {label} was DENIED and agent {spawn['agent_id']!r} "
                f"spawned anyway ({spawn['wire']})"]
    if permit.get("verdict") != "allow":
        return [f"unjudged permit executed: {label} has no allow verdict, yet agent "
                f"{spawn['agent_id']!r} spawned ({spawn['wire']})"]
    if permit.get("role") != spawn["role"]:
        problems.append(f"role mismatch: {label} permits role {permit.get('role')!r}, but agent "
                        f"{spawn['agent_id']!r} is {spawn['role']!r} ({spawn['wire']})")
    problems += _verdict_order_problems(permit, label, spawn)
    problems += _plan_problems(permit, label, tasks)
    return problems


def _plan_problems(permit: dict, label: str, tasks: dict[str, list[str]]) -> list[str]:
    """The permit must answer a planned task, and its scope must sit inside that task's files."""
    task_id = str(permit.get("task_id") or "")
    declared = tasks.get(task_id)
    if declared is None:
        return [f"unplanned task: {label} answers {task_id!r}, which is not a task of the approved "
                f"plan"]
    if not declared:
        return [f"unprovable scope: {label} answers {task_id!r}, whose plan entry declares no "
                f"files — the scope cannot be proven a subset"]
    outside = _outside_plan(permit.get("scope") or [], declared)
    if outside:
        return [f"scope violation: {label} includes {', '.join(outside)}, which {task_id!r} does "
                f"not declare in the approved plan"]
    return []


def _lifecycle_problems(permits: list[dict], by_agent: dict[str, list[dict]],
                        spawned_agents: set[str]) -> list[str]:
    """Permits that were allowed but never resolved, and bindings the wire never confirms."""
    problems: list[str] = []
    for permit in permits:
        if permit.get("verdict") != "allow" or permit.get("agent_id") or permit.get("closed"):
            continue
        problems.append(f"unused permit: {permit.get('permit_id')!r} was allowed but never spawned "
                        f"and is not closed — close it with the reason it was not executed")
    for agent_id, owners in sorted(by_agent.items()):
        if agent_id not in spawned_agents and len(owners) == 1:
            problems.append(f"bound but never spawned: permit "
                            f"{owners[0].get('permit_id')!r} claims agent {agent_id!r}, which the "
                            f"session wire does not hold")
    return problems


def audit(root: str | pathlib.Path, session: str = "auto", home: str | None = None) -> dict:
    """The finish gate: permits vs the session wire vs the approved plan.

    The three checks are focused helpers — ownership (one permit id, one agent id), the spawn
    coverage and the permit lifecycle — so each failure class is testable on its own and the
    backstop stays readable.
    """
    attribution = _attribution()
    root = _checked_repo(root)
    wire_home = pathlib.Path(home) if home else attribution.WIRE_HOME
    try:
        info = attribution.resolve_session(str(root), session, wire_home)
    except attribution.Degraded as exc:
        raise PermitDegraded(str(exc)) from exc
    except attribution.AttributionError as exc:
        raise PermitError(str(exc)) from exc
    session_dir = pathlib.Path(info["session_dir"])
    spawns, malformed, events = wire_spawns(session_dir)
    path = root / PERMITS_REL
    if path.is_file():
        data = read_permits(root)
    else:
        data = _empty("")
    permits = data["permits"]
    tasks = plan_tasks(root)

    problems: list[str] = [f"malformed wire evidence: {entry}" for entry in malformed]
    by_agent, ownership = _ownership_problems(permits)
    problems += ownership
    for spawn in spawns:
        problems += _spawn_problems(spawn, by_agent, tasks)
    problems += _lifecycle_problems(permits, by_agent,
                                    {spawn["agent_id"] for spawn in spawns})
    return {"status": "failed" if problems else "ok", "repo": str(root),
            "session": str(session_dir), "permits": str(path), "run_id": data.get("run_id") or None,
            "events": events, "spawns": len(spawns), "permits_count": len(permits),
            "problems": problems}


# -------------------------------------------------------------------------------------------- CLI

def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="permit_gate.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the permits file skeleton")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("add", help="register one permit")
    p.add_argument("--repo", required=True)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--task-id", required=True, dest="task_id",
                   help="a task id of the approved plan (.code-factory/state/plan.md)")
    p.add_argument("--role", required=True, help="a registered delegate role")
    p.add_argument("--phase", required=True, help="one of " + ", ".join(PERMIT_PHASES))
    p.add_argument("--scope", action="append", default=[],
                   help="repo-relative path the delegation may touch (repeatable)")
    p.add_argument("--constraint", action="append", default=[],
                   help="a rule the delegation must honour (repeatable)")
    p.set_defaults(func=_cmd_add)

    p = sub.add_parser("verdict", help="record the supervisor verdict for a permit")
    p.add_argument("--repo", required=True)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--verdict", required=True, choices=VERDICTS)
    p.add_argument("--evidence", required=True,
                   help="the artifact or rule the verdict rests on (never empty)")
    p.set_defaults(func=_cmd_verdict)

    p = sub.add_parser("bind", help="record the agent id an allowed permit spawned")
    p.add_argument("--repo", required=True)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--agent-id", required=True, dest="agent_id")
    p.set_defaults(func=_cmd_bind)

    p = sub.add_parser("close", help="mark an allowed permit as NOT executed")
    p.add_argument("--repo", required=True)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=_cmd_close)

    p = sub.add_parser("audit", help="finish gate: permits vs the session wire vs the plan")
    p.add_argument("--repo", required=True)
    p.add_argument("--session", default="auto",
                   help="a session directory, or 'auto' for the current one (default)")
    p.add_argument("--home", default=None, help="the CLI's wire root (default: ~/.kimi-code)")
    p.set_defaults(func=_cmd_audit)
    return ap


def _cmd_init(args: argparse.Namespace) -> int:
    _emit(init(args.repo))
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    _emit(add(args.repo, args.permit_id, args.task_id, args.role, args.phase, args.scope,
              args.constraint))
    return 0


def _cmd_verdict(args: argparse.Namespace) -> int:
    _emit(verdict(args.repo, args.permit_id, args.verdict, args.evidence))
    return 0


def _cmd_bind(args: argparse.Namespace) -> int:
    _emit(bind(args.repo, args.permit_id, args.agent_id))
    return 0


def _cmd_close(args: argparse.Namespace) -> int:
    _emit(close(args.repo, args.permit_id, args.reason))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        result = audit(args.repo, args.session, args.home)
    except PermitDegraded as exc:
        print(f"DEGRADED - the permit audit cannot prove anything: {exc}")
        return 3
    print(f"session: {result['session']}")
    print(f"permits: {result['permits']} ({result['permits_count']} permit(s))")
    print(f"events: {result['events']}, spawns: {result['spawns']}")
    for problem in result["problems"]:
        print(f"violation: {problem}")
    if result["status"] == "ok":
        print(f"PASS - every delegation in the wire ({result['spawns']}) is covered by an allowed, "
              f"judged, in-scope permit and no permit is left unused")
        return 0
    print(f"FAIL - {len(result['problems'])} permit-audit violation(s)")
    return 1


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except PermitError as exc:
        print(f"permit_gate.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

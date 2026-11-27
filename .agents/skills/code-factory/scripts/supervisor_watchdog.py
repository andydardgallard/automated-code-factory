#!/usr/bin/env python3
"""
The supervisor watchdog's deterministic scanner (zero LLM tokens, stdlib only).

WHY THIS EXISTS

The factory supervisor is a run-long BACKGROUND WATCHDOG, not a synchronous per-delegation permit
clerk: it is launched ONCE at run start for the whole run, and it spends LLM tokens ONLY when a
deterministic scan flags an anomaly. This script is the deterministic layer that makes that cheap:
ONE scan pass over the `.code-factory` state costs no tokens, so the orchestrator (the flow, not a
polling-interval CLI input — there is deliberately none) runs it at every phase transition and
before every gate checkpoint, and the supervisor subagent is resumed only when a scan found
something. On a confirmed violation the supervisor records a BLOCKING DENY through this script:
`gate_all.py` runs `status` as the `watchdog-deny` gate row of phases K and Y, and a phase gate may
not pass while an unresolved deny is recorded. The deny names the violating role and the rulebook
citation, which is exactly what the correction routing consumes.

HONEST LIMIT: the CLI offers no call-time interception. The watchdog's enforcement is CONTINUOUS
deterministic scanning plus the BLOCKING phase gates — a violation that slips between scans is
still caught by the next gate and by the deterministic finish audits (`permit_gate.py`,
`delegation_gate.py`, `action_gate.py`).

THE STATE FILE `.code-factory/state/watchdog.json` — run-bound, schema-validated, fail-closed (a
malformed state is an input error, never a crash and never silently ignored):

  {"run_id": "<YYYYMMDD>-<8 hex>",
   "launch": null | {"at": "<ISO>", "authority": "run"},
   "scans": <int>,
   "events": [{"event": "<Phase 0 event>", "seq": <int>, "at": "<ISO>", "detail": "<text>"}],
   "anomalies": [{"rule": "<rulebook id>", "role": "<factory role|main>", "detail": "<text>",
                  "detected_at": "<ISO>", "scan": <int>}],
   "denies": [{"rule": "<rulebook id>", "role": "<factory role|main>", "detail": "<text>",
               "at": "<ISO>",
               "resolved": null | {"at": "<ISO>", "evidence": "<text>"}}]}

The `events` list is the ordered Phase 0 journal the bootstrap observed (an older state file
without it is read with an empty journal, never rejected).

SUBCOMMANDS

  begin   --launch-dir <dir>
        record ONE watchdog bootstrap BEFORE Phase 0 begins. It is launch-scoped and run-id
        INDEPENDENT (deliberately: the run_id does not exist yet at that point) and it is KEYED: a
        fresh launch nonce (`<YYYYMMDD>-<HHMMSS>-<6 hex>`, UTC time + os.urandom) names the file,
        so several factories launched from ONE directory into DIFFERENT repositories never share a
        mutable record. Writes `<launch-dir>/.code-factory/state/watchdog-bootstrap-<launch_id>
        .json`:
        {"launch_id": "<nonce>", "begun_at": "<ISO>", "run_id": null, "events": [...],
         "supervisor_model": null, "activated": null, "completed": null, "history": []}
        and returns the `launch_id` every later operation is addressed by. A COMPLETED or ABANDONED
        keyed bootstrap is an IMMUTABLE history entry of the launch directory: it is never rewritten
        and never carried into another bootstrap (no cross-run `history`; the field stays for the
        legacy shape). A second `begin` is therefore a NEW, independent supervision — the old
        single-occupancy refusal is inverted on purpose (owner-approved).
        The unkeyed `watchdog-bootstrap.json` is the LEGACY (pre-key) shape: still resolvable, never
        silently migrated, and `history` still validates on it.
  resolve-model --launch-dir <dir> --task <task file as handed over> [--config <path>]
                [--launch-id <id>]
        resolve and RECORD the supervisor's model BEFORE it is spawned. The handed-over task's
        `models.supervisor` pin is authoritative and recorded VERBATIM (never substituted); only an
        ABSENT pin falls back to the role's `model_preference: primary` side of the factory's
        DEFAULT MATRIX — the ONE precedence of `model_matrix.py`, never a per-run choice of the main
        agent. The command returns the `model` the Agent tool must be given and stores it in the
        bootstrap as `supervisor_model` (`model`, `source`, `resolved_at`), so the launch-scoped
        record the spawn is bound to and the model `models_used.supervisor` reports at the finish
        carry the SAME value. Exit 1 when NO model resolves at all (a STOP: the run never spawns a
        role nobody gave a model to), exit 2 on an empty/unreadable task file, a malformed `models:`
        matrix, an unusable `--config` value or a DIFFERENT second resolution — a supervisor's model
        is never swapped mid-launch.
  observe --launch-dir <dir> --event <event> --seq <int> [--detail <text>] [--launch-id <id>]
        record ONE Phase 0 observation under the bootstrap. The event vocabulary is CLOSED
        (`parse`, `resolve`, `memory-read`, `memory-write`, `run-id`) and the sequence is
        non-negative and STRICTLY increasing (two events may not share a place in the order, and
        the order may not regress). An observation with no recorded `begin` is refused: the OLD
        order — parse first, supervise later — never becomes a library record. `--detail` is an
        OPTIONAL routing note: empty is legitimate, `DETAIL_MAX` (4000) characters is the bound.
        After activation the same observation is also appended to the run-bound state.
  activate --launch-dir <dir> --repo <root> [--launch-id <id>]
        bind the addressed bootstrap ATOMICALLY to the run that now exists: exit 1 (fail closed)
        while a mandated Phase 0 operation was never observed or was observed OUT OF ORDER, exit 2
        on an input error (a second activation, another run's state — archive it). The transition
        covers TWO writes, so it is RECOVERABLE: when the run-bound state was written but the
        bootstrap was not, retrying the SAME bootstrap finishes the binding instead of refusing the
        run as already launched. On success the run-bound state is written with `launch.at` = the
        bootstrap's OWN `begun_at` (the moment supervision really started, never a later stand-in)
        and carries the ordered observations.
  complete --launch-dir <dir> [--launch-id <id>]
        close the bootstrap of the run `activate` bound: the record names that run, the finished
        run's own watchdog state is left untouched, and ONE completion per binding is allowed. An
        unbound bootstrap has no completed run to record (exit 2), and a second completion is
        refused (exit 2).
  abandon --launch-dir <dir> --reason <text> [--launch-id <id>]
        end a bootstrap that NEVER bound a run — the honest transition after a failed Phase 0 (an
        unparsable task, a refused activation). The reason is mandatory and bounded and stays on the
        record; an ACTIVATED bootstrap is a run IN PROGRESS and is refused (exit 2 — end it with
        `complete` at its Finish), as is an already closed one.
        RESOLUTION without `--launch-id`: `observe`/`activate`/`complete`/`abandon` address the ONE
        UNCOMPLETED bootstrap of the launch directory (the legacy unkeyed file included). MULTIPLE
        uncompleted bootstraps are an input error that names every candidate id and demands
        `--launch-id` — the state of several factories in one directory is never guessed. An
        explicit `--launch-id` is a FILENAME COMPONENT and must match `^\\d{8}-\\d{6}-[0-9a-f]{6}$`;
        a malformed or unknown one is an input error, never a silent fallback.
  launch  --repo <root>
        record the run's ONE watchdog launch for a run that already has a run_id (the legacy path:
        a run started under `begin`/`observe`/`activate` is launched by `activate`). Single owner:
        a second launch for the same run fails; a state file of ANOTHER run is stale and must be
        archived first
  scan    --repo <root>
        ONE scan pass (zero LLM cost): the pipeline counters against the budgets, the permits
        file's validity and run_id, the completeness of the gate records that exist, and the
        action-gate journal. NEW anomalies are appended atomically (a re-scan never duplicates a
        finding). Exit 0 clean, 1 new anomalies or unresolved denies.
  deny    --repo <root> --rule <id> --role <role> --detail <text>
        record a BLOCKING deny (the correction routing: rule = the rulebook citation, role = the
        violating role the correction is routed to)
  resolve --repo <root> --rule <id> --role <role> --evidence <text>
        mark every matching unresolved deny resolved, with the evidence of the correction
  status  --repo <root>
        report the watchdog state as JSON; exit 1 while an unresolved deny blocks the run AND when
        this run never recorded a launch/activation (fail closed: `gate_all.py` runs this as the
        `watchdog-deny` row of phases K and Y, and a run the watchdog never watched must not pass
        a phase gate)

EXIT CODES: 0 clean / recorded, 1 anomalies found, an unresolved deny, NO recorded launch for
this run, a `models.supervisor` resolution that yields NO model (a STOP, never a substitute), or an
activation whose mandated Phase 0 operations were unobserved or out of order (the phase gate fails
closed), 2 input error (a malformed state, a stale run binding, a bad argument —
a message naming the fix, never a traceback).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import tempfile

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The watchdog may be loaded BY PATH (gate_all.py, a test harness): the sibling scanners it
    # reuses must be importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from model_matrix import ROLES  # noqa: E402
import model_matrix  # noqa: E402  (the ONE model-precedence resolver, reused)

WATCHDOG_REL = pathlib.Path(".code-factory") / "state" / "watchdog.json"
# The LEGACY unkeyed bootstrap (pre-key shape): still resolvable, never silently migrated.
BOOTSTRAP_REL = pathlib.Path(".code-factory") / "state" / "watchdog-bootstrap.json"
# A KEYED bootstrap is `watchdog-bootstrap-<launch_id>.json` in the same directory.
BOOTSTRAP_PREFIX = "watchdog-bootstrap"
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
# The launch nonce `begin` mints: UTC time + random suffix. It is a FILENAME COMPONENT, so it is
# validated before it is ever used as one (separators, `..`, empty have zero legitimacy).
LAUNCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
RULE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# A deny detail is a routing note, not a document: bounded so the state file stays a state file.
DETAIL_MAX = 4000
DENY_ROLES = tuple(ROLES) + ("main",)
# The CLOSED Phase 0 vocabulary: an event outside it is not an observation of a Phase 0 operation.
PHASE0_EVENTS = ("parse", "resolve", "memory-read", "memory-write", "run-id")
# The operations the supervisor must have watched BEFORE it can bind to a run, IN THIS ORDER: the
# supervisor that begins first watches the parse, the repository resolution, the memory read and the
# run id that follows them. The old order parsed first and watched nothing (mistakes.txt item 1).
PHASE0_REQUIRED = ("parse", "resolve", "memory-read", "run-id")
# The counters of the WIP checkpoint that the flow MANDATES but that are NOT factory roles: they
# carry no retry budget, and no deny is ever routed to them.
NON_ROLE_COUNTERS = ("plan_rejections",)
# The role whose model is resolved BEFORE the supervisor is spawned. The task's `models.supervisor`
# pin wins verbatim; an ABSENT pin takes the role's `model_preference` side of the default matrix
# (supervisor.md declares `primary`), so the main agent never picks the model itself.
SUPERVISOR_ROLE = "supervisor"
SUPERVISOR_MODEL_KEY = "supervisor_model"
# Where a resolved model may come from: the task's matrix, or the factory's default matrix.
SUPERVISOR_SOURCES = ("task", "default")
# The scan's own rule citations (the rulebook rules each check stands on).
RULE_BUDGETS = "retry-budgets"
RULE_PERMITS = "permit-trail"
RULE_GATE_RECORD = "gate-record"
RULE_ACTIONS = "destructive-action-gate"


class WatchdogError(ValueError):
    """An input this script cannot honour: a message + exit 2, never a traceback."""


class ActivationRefused(WatchdogError):
    """Phase 0 was not supervised as the flow mandates: exit 1 (the gate-like verdict), not 2.

    This is not the caller's malformed input — the inputs are well-formed — it is the RUN's
    record of Phase 0 proving that the old order (parse first, supervise later) was used. A phase
    gate may not pass on such a run, so it exits 1 and names every operation that went unwatched.
    """


class ModelUnresolved(WatchdogError):
    """The supervisor's model resolves to NOTHING: exit 1 (a STOP), never a substitute.

    A task that names no `models.supervisor` and a default matrix that offers the role no model
    leave the spawn with no model at all — and there is no third path (rule
    `models-generator-ne-judge`), so the run stops here instead of letting the main agent pick one.
    """


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the verdicts survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def _now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")


def _now_precise() -> str:
    """A launch's `begun_at`: microsecond precision, so two begins never share a moment."""
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="microseconds")


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise WatchdogError(f"repository root does not exist: {root}")
    return root


def _checked_task_file(task: str | pathlib.Path) -> pathlib.Path:
    """The handed-over task file: an existing, non-EMPTY regular file.

    `--task` is the file the owner handed over, so its purpose is fixed: an absent path, a
    directory and a zero-byte file are all input errors naming the fix. An empty file would
    otherwise read as "no models matrix", silently resolving the default matrix for a task nobody
    wrote.
    """
    path = pathlib.Path(os.path.abspath(str(task)))
    if not path.is_file():
        raise WatchdogError(f"--task {path} is not an existing file: pass the task file AS HANDED "
                            f"OVER (the same file `task_parser.py parse` reads), never a directory "
                            f"or a guess")
    if path.stat().st_size < 1:
        raise WatchdogError(f"--task {path} is empty: the supervisor's model is resolved from the "
                            f"handed-over task's `models:` matrix, so an empty file resolves "
                            f"nothing — pass the task file the owner handed over")
    return path


def _checked_config_file(config: str | pathlib.Path | None) -> pathlib.Path | None:
    """The optional explicit CLI config: `None` (the module default) or an existing file."""
    if config is None:
        return None
    path = pathlib.Path(os.path.abspath(str(config)))
    if not path.is_file():
        raise WatchdogError(f"--config {path} is not an existing file: it must be the CLI config "
                            f"carrying `default_model` / `[secondary_model] default_model`, or be "
                            f"omitted to read the factory's default config")
    return path


def _run_id(root: pathlib.Path) -> str:
    """The current pipeline run id (the state file is bound to exactly one run)."""
    import permit_gate  # noqa: PLC0415  (sibling, shared run-id reading)
    try:
        return permit_gate.pipeline_run_id(root)
    except permit_gate.PermitError as exc:
        raise WatchdogError(str(exc)) from exc


def _validate_rule(rule: str) -> str:
    if not RULE_RE.fullmatch(rule or ""):
        raise WatchdogError(f"--rule must be a rulebook citation id ([A-Za-z0-9._-]+), got "
                            f"{rule!r}")
    return rule


def _validate_role(role: str) -> str:
    if role not in DENY_ROLES:
        raise WatchdogError(f"--role must be a factory role or 'main' (the correction is routed "
                            f"to it), got {role!r}")
    return role


def _validate_note(value: object, label: str) -> str:
    """An OPTIONAL routing note: empty is legitimate, `DETAIL_MAX` characters is the bound.

    (review R1) `observe --detail` wrote whatever it was given into the launch-scoped bootstrap,
    while every other note of this script (`deny`) is bounded. A routing note is a note, not a
    document: 4000 characters are accepted and 4001 are an input error, so the state file stays a
    state file.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WatchdogError(f"{label} must be text, got {type(value).__name__}")
    text = value.strip()
    if len(text) > DETAIL_MAX:
        raise WatchdogError(f"{label} is {len(text)} characters: a routing note is bounded to "
                            f"{DETAIL_MAX} characters so the watchdog state stays a state file")
    return text


def _validate_text(value: str, label: str) -> str:
    text = _validate_note(value, label)
    if not text:
        raise WatchdogError(f"{label} is required and may not be empty")
    return text


# ------------------------------------------------------------------------------------------ storage

def _fresh(run_id: str) -> dict:
    return {"run_id": run_id, "launch": None, "scans": 0, "events": [], "anomalies": [],
            "denies": [], SUPERVISOR_MODEL_KEY: None}


def _validate_model_record(path: pathlib.Path, value: object) -> None:
    """`supervisor_model` is null or `{model, source, resolved_at}` — fail closed on anything else.

    The record is what the supervisor is spawned with, so a hand-edited or half-written record is
    an input error naming the shape instead of a model the main agent would have to interpret.
    """
    if value is None:
        return
    if (not isinstance(value, dict)
            or not isinstance(value.get("model"), str) or not value["model"].strip()
            or value.get("source") not in SUPERVISOR_SOURCES
            or not isinstance(value.get("resolved_at"), str) or not value["resolved_at"]):
        raise WatchdogError(f"{path}: {SUPERVISOR_MODEL_KEY} must be null or an object with a "
                            f"non-empty 'model', a 'source' of "
                            f"{'|'.join(SUPERVISOR_SOURCES)} and a non-empty 'resolved_at'")


def _validate_state(path: pathlib.Path, data: object) -> dict:
    """Schema-validate the loaded state: a malformed file is an input error, never a crash."""
    if not isinstance(data, dict):
        raise WatchdogError(f"{path} must be a JSON object, got {type(data).__name__}")
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise WatchdogError(f"{path}: run_id must be YYYYMMDD-<8 lowercase hex>, got {run_id!r}")
    launch = data.get("launch")
    if launch is not None and (not isinstance(launch, dict)
                               or not isinstance(launch.get("at"), str)):
        raise WatchdogError(f"{path}: launch must be null or an object with a string 'at'")
    scans = data.get("scans")
    if not isinstance(scans, int) or isinstance(scans, bool) or scans < 0:
        raise WatchdogError(f"{path}: scans must be a non-negative integer, got {scans!r}")
    events = data.get("events", [])
    if not isinstance(events, list):
        raise WatchdogError(f"{path}: events must be a list, got {type(events).__name__}")
    for index, entry in enumerate(events):
        where = f"{path}: events[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("event"), str) \
                or not isinstance(entry.get("at"), str):
            raise WatchdogError(f"{where} must be an object with string event/at")
        if not isinstance(entry.get("seq"), int) or isinstance(entry.get("seq"), bool):
            raise WatchdogError(f"{where}: seq must be an integer")
    data["events"] = events
    for key in ("anomalies", "denies"):
        if not isinstance(data.get(key), list):
            raise WatchdogError(f"{path}: {key} must be a list, got {type(data.get(key)).__name__}")
    for index, anomaly in enumerate(data["anomalies"]):
        where = f"{path}: anomalies[{index}]"
        if not isinstance(anomaly, dict) or not all(
                isinstance(anomaly.get(field), str)
                for field in ("rule", "role", "detail", "detected_at")):
            raise WatchdogError(f"{where} must be an object with string rule/role/detail/"
                                f"detected_at")
        if not isinstance(anomaly.get("scan"), int) or isinstance(anomaly.get("scan"), bool):
            raise WatchdogError(f"{where}: scan must be an integer")
    for index, deny in enumerate(data["denies"]):
        where = f"{path}: denies[{index}]"
        if not isinstance(deny, dict) or not all(
                isinstance(deny.get(field), str) for field in ("rule", "role", "detail", "at")):
            raise WatchdogError(f"{where} must be an object with string rule/role/detail/at")
        resolved = deny.get("resolved")
        if resolved is not None and (not isinstance(resolved, dict)
                                     or not isinstance(resolved.get("at"), str)
                                     or not isinstance(resolved.get("evidence"), str)):
            raise WatchdogError(f"{where}: resolved must be null or an object with string 'at' "
                                f"and 'evidence'")
    _validate_model_record(path, data.get(SUPERVISOR_MODEL_KEY))
    return data


def read_state(root: pathlib.Path) -> dict | None:
    """The parsed watchdog state, or None when the run has none yet (fail-closed on malformed)."""
    path = root / WATCHDOG_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WatchdogError(f"{path} is not readable JSON: {exc} — the watchdog state is "
                            f"fail-closed: fix or archive the file, it is never ignored") from exc
    return _validate_state(path, data)


def _state_for_run(root: pathlib.Path, run_id: str) -> dict:
    """The run's state (a fresh skeleton when absent); a DIFFERENT run's state is stale."""
    data = read_state(root)
    if data is None:
        return _fresh(run_id)
    if data["run_id"] != run_id:
        raise WatchdogError(f"{root / WATCHDOG_REL} belongs to run {data['run_id']!r}, but the "
                            f"current pipeline run is {run_id!r}: the watchdog state is bound to "
                            f"one run — archive the stale file instead of reusing it")
    return data


def _write_state(root: pathlib.Path, data: dict) -> pathlib.Path:
    """Write the state deterministically and ATOMICALLY (temp file + os.replace)."""
    return _atomic_json(root / WATCHDOG_REL, data)


def _unresolved(data: dict) -> list[dict]:
    return [deny for deny in data["denies"] if deny.get("resolved") is None]


# ---------------------------------------------------------------------------------- bootstrap (P0)

def _checked_launch_dir(launch_dir: str | pathlib.Path) -> pathlib.Path:
    """The launch directory holds the launch-scoped bootstrap: it must already exist."""
    directory = pathlib.Path(os.path.abspath(str(launch_dir)))
    if not directory.is_dir():
        raise WatchdogError(f"launch directory does not exist: {directory} — "
                            f"`begin --launch-dir` takes the directory the factory was launched "
                            f"from (it is created by the launcher, never by the watchdog)")
    return directory


def _bootstrap_path(directory: pathlib.Path, launch_id: str | None = None) -> pathlib.Path:
    """The bootstrap file of ONE launch: keyed by its nonce; unkeyed only for a legacy record."""
    if launch_id is None:
        return directory / BOOTSTRAP_REL
    return directory / BOOTSTRAP_REL.parent / f"{BOOTSTRAP_PREFIX}-{launch_id}.json"


def _bootstrap_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Every bootstrap file of the launch directory: the keyed ones and the legacy unkeyed one."""
    return sorted((directory / BOOTSTRAP_REL.parent).glob(f"{BOOTSTRAP_PREFIX}*.json"))


def _launch_id_of(path: pathlib.Path) -> str | None:
    """The launch nonce a keyed bootstrap file is named by; None for the legacy unkeyed file."""
    if path.name == BOOTSTRAP_REL.name:
        return None
    return path.name[len(BOOTSTRAP_PREFIX) + 1:-len(".json")]


def _validate_launch_id(launch_id: str) -> str:
    """`--launch-id` becomes a filename component: only the documented nonce shape is legitimate."""
    if not LAUNCH_ID_RE.fullmatch(launch_id or ""):
        raise WatchdogError(f"--launch-id must be the launch nonce the factory's `begin` minted "
                            f"(^\\d{{8}}-\\d{{6}}-[0-9a-f]{{6}}$), got {launch_id!r}: it names the "
                            f"bootstrap file, so separators, `..` and an empty value have no "
                            f"legitimacy")
    return launch_id


def _mint_launch_id() -> str:
    """A fresh launch nonce: UTC time + `os.urandom`, validated before it names a file."""
    nonce = (datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
             + "-" + os.urandom(3).hex())
    if not LAUNCH_ID_RE.fullmatch(nonce):
        raise WatchdogError(f"the minted launch id {nonce!r} is not a usable filename component: "
                            f"one launch could not be told from another")
    return nonce


def _validate_bootstrap(path: pathlib.Path, data: object) -> dict:
    if not isinstance(data, dict):
        raise WatchdogError(f"{path} must be a JSON object, got {type(data).__name__}")
    if not isinstance(data.get("begun_at"), str) or not data["begun_at"]:
        raise WatchdogError(f"{path}: begun_at must be a non-empty ISO timestamp")
    if data.get("launch_id") is not None and (
            not isinstance(data.get("launch_id"), str)
            or not LAUNCH_ID_RE.fullmatch(data["launch_id"])):
        raise WatchdogError(f"{path}: launch_id must be null or the launch nonce that names the "
                            f"file (^\\d{{8}}-\\d{{6}}-[0-9a-f]{{6}}$), got {data['launch_id']!r}")
    if data.get("run_id") is not None and not isinstance(data.get("run_id"), str):
        raise WatchdogError(f"{path}: run_id must be null or a string")
    events = data.get("events")
    if not isinstance(events, list):
        raise WatchdogError(f"{path}: events must be a list, got {type(events).__name__}")
    for index, entry in enumerate(events):
        where = f"{path}: events[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("event"), str) \
                or not isinstance(entry.get("at"), str):
            raise WatchdogError(f"{where} must be an object with string event/at")
        if not isinstance(entry.get("seq"), int) or isinstance(entry.get("seq"), bool):
            raise WatchdogError(f"{where}: seq must be an integer")
    _validate_model_record(path, data.get(SUPERVISOR_MODEL_KEY))
    activated = data.get("activated")
    if activated is not None and (not isinstance(activated, dict)
                                  or not isinstance(activated.get("at"), str)
                                  or not isinstance(activated.get("run_id"), str)
                                  or not isinstance(activated.get("repo"), str)):
        raise WatchdogError(f"{path}: activated must be null or an object with string "
                            f"at/run_id/repo")
    completed = data.setdefault("completed", None)
    if completed is not None:
        if not isinstance(completed, dict) or not isinstance(completed.get("at"), str):
            raise WatchdogError(f"{path}: completed must be null or an object with a string at")
        # A closed bootstrap names EITHER the run it completed OR — for a bootstrap that never
        # bound a run — the abandonment with the reason it ended for. Nothing else is a record.
        if completed.get("abandoned") is True:
            if completed.get("run_id") is not None:
                raise WatchdogError(f"{path}: an ABANDONED bootstrap records no run, got run_id "
                                    f"{completed.get('run_id')!r}")
            if not isinstance(completed.get("reason"), str) or not completed["reason"].strip():
                raise WatchdogError(f"{path}: an abandoned bootstrap must carry the reason it was "
                                    f"abandoned for")
        elif not isinstance(completed.get("run_id"), str):
            raise WatchdogError(f"{path}: completed must be null or an object with string "
                                f"at/run_id")
    history = data.setdefault("history", [])
    if not isinstance(history, list):
        raise WatchdogError(f"{path}: history must be a list, got {type(history).__name__}")
    return data


def _read_bootstrap_file(path: pathlib.Path) -> dict:
    """Read + validate ONE bootstrap file (fail-closed: an input error, never a silent skip)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WatchdogError(f"{path} is not readable JSON: {exc} — the Phase 0 bootstrap is "
                            f"fail-closed: fix or archive the file, it is never ignored") from exc
    return _validate_bootstrap(path, data)


def _no_bootstrap_error(directory: pathlib.Path) -> WatchdogError:
    return WatchdogError(
        f"no {BOOTSTRAP_PREFIX}*.json in {directory}: the supervisor did not BEGIN before "
        f"Phase 0, so this operation went unwatched — the supervisor must be watching "
        f"Phase 0 from before the parse (mistakes.txt item 1): run "
        f"`supervisor_watchdog.py begin --launch-dir <launch dir>` FIRST, then observe every "
        f"Phase 0 event")


def resolve_bootstrap(directory: str | pathlib.Path,
                      launch_id: str | None = None) -> dict:
    """The ONE bootstrap an operation addresses: `{launch_id, path, bootstrap}` (the shared resolver).

    An explicit `launch_id` names its keyed file and NOTHING else: a malformed or unknown key is an
    input error, never a fallback to "some" bootstrap. Without it the launch directory resolves only
    when exactly ONE bootstrap is UNCOMPLETED — the legacy unkeyed file is such a bootstrap, so a
    paused run resumes on the file it already has and is never silently migrated. SEVERAL
    uncompleted bootstraps are an ambiguity that names every candidate and demands `--launch-id`:
    which run a supervision belongs to is never guessed.
    """
    directory = _checked_launch_dir(directory)
    if launch_id is not None:
        key = _validate_launch_id(launch_id)
        path = _bootstrap_path(directory, key)
        if not path.is_file():
            known = ", ".join(str(_launch_id_of(file) or file.name)
                              for file in _bootstrap_files(directory)) or "none"
            raise WatchdogError(
                f"no bootstrap keyed {key!r} in {directory}: `--launch-id` must be the nonce "
                f"`begin` returned for THIS supervision (known: {known}) — a key that names no "
                f"bootstrap is never resolved to another one")
        return {"launch_id": key, "path": path, "bootstrap": _read_bootstrap_file(path)}
    files = _bootstrap_files(directory)
    if not files:
        raise _no_bootstrap_error(directory)
    records = [(path, _read_bootstrap_file(path)) for path in files]
    uncompleted = [(path, record) for path, record in records
                   if record.get("completed") is None]
    if len(uncompleted) == 1:
        path, record = uncompleted[0]
        return {"launch_id": _launch_id_of(path), "path": path, "bootstrap": record}
    if len(uncompleted) > 1:
        candidates = ", ".join(_launch_id_of(path) or f"{path.name} (legacy, unkeyed)"
                               for path, _record in uncompleted)
        raise WatchdogError(
            f"{len(uncompleted)} UNCOMPLETED bootstraps are recorded in {directory} ({candidates}): "
            f"which supervision this operation belongs to is not guessable — pass `--launch-id "
            f"<id>` (the nonce its `begin` returned) to address exactly one of them")
    closed = ", ".join(f"{_launch_id_of(path) or path.name} {_closed_phrase(record['completed'])}"
                       for path, record in records)
    raise WatchdogError(
        f"every bootstrap in {directory} is already closed ({closed}): a closed record is history "
        f"and is never rewritten — run `supervisor_watchdog.py begin --launch-dir {directory}` for "
        f"the next run's Phase 0")


def _atomic_json(path: pathlib.Path, data: dict) -> pathlib.Path:
    """Write a state document deterministically and ATOMICALLY (temp file + os.replace)."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                                        suffix=".tmp")
    except OSError as exc:
        raise WatchdogError(f"cannot write {path}: {exc}") from exc
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise WatchdogError(f"cannot write {path} (the previous one is untouched): {exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise
    return path


# -------------------------------------------------------------------------------------- subcommands

def begin(launch_dir: str | pathlib.Path) -> dict:
    """Record ONE KEYED watchdog bootstrap — BEFORE Phase 0, run-id independently.

    The defect this closes (mistakes.txt item 1): the old flow parsed the task, resolved
    `repo_path`, read the memory and only THEN computed a run_id and launched a supervisor whose
    launch REQUIRED that run_id — so the mandated order was impossible and all of Phase 0 went
    unwatched. `begin` therefore needs nothing but the launch directory.

    The bootstrap is KEYED by a minted launch nonce (defect C, owner-approved inversion): several
    factories launched from ONE directory into DIFFERENT repositories must never share a mutable
    file, so a second `begin` starts an independent supervision instead of being refused. The nonce
    is returned as `launch_id` and every later operation is addressed by it; without it the launch
    directory resolves only while exactly ONE bootstrap is uncompleted. A completed/abandoned keyed
    record is IMMUTABLE history — never rewritten, never carried into another bootstrap.
    """
    directory = _checked_launch_dir(launch_dir)
    launch_id = _mint_launch_id()
    while _bootstrap_path(directory, launch_id).exists():     # never overwrite a record
        launch_id = _mint_launch_id()
    data = {"launch_id": launch_id, "begun_at": _now_precise(), "run_id": None, "events": [],
            "activated": None, "completed": None, "history": []}
    path = _atomic_json(_bootstrap_path(directory, launch_id), data)
    return {"status": "begun", "launch_id": launch_id, "run_id": None, "events": 0,
            "begun_at": data["begun_at"], "history": 0, "state": str(path)}


def resolve_model(launch_dir: str | pathlib.Path, task: str | pathlib.Path,
                  config: str | pathlib.Path | None = None,
                  launch_id: str | None = None) -> dict:
    """Resolve and RECORD the supervisor's model from the handed-over task BEFORE the spawn.

    (defect C11) The supervisor used to be spawned with whatever model the main agent had in hand,
    so a task pin `models.supervisor: k3.1-pro` silently ran on another model and the finish
    attribution failed against a claim nobody could have honoured. The model is therefore resolved
    DETERMINISTICALLY from the task the owner handed over, through the ONE precedence of
    `model_matrix.py`: a `models.supervisor` pin is recorded VERBATIM (never substituted), and only
    an ABSENT pin falls back to the role's `model_preference: primary` side of the default matrix.
    The resolution is stored in the launch-scoped bootstrap, so the value the main agent spawns
    with and the value `models_used.supervisor` reports at the finish come from the SAME record.

    Ordering: this reads only the task's `models:` block, never the parsed task, so it runs after
    `begin` and BEFORE the spawn without dragging any Phase 0 operation out of order.
    """
    # Boundary (rule `input-validation`): the empty forms are never legitimate — an empty path
    # would silently mean the CURRENT DIRECTORY through `os.path.abspath`, and an empty
    # `--launch-id` is a malformed key, not "the single uncompleted bootstrap".
    if len(str(launch_dir).strip()) < 1:
        raise WatchdogError("--launch-dir may not be empty: it must be the directory the factory "
                            "was launched from")
    if len(str(task).strip()) < 1:
        raise WatchdogError("--task may not be empty: it must be the task file AS HANDED OVER")
    if config is not None and len(str(config).strip()) < 1:
        raise WatchdogError("--config may not be empty when given: omit it to read the factory's "
                            "default CLI config")
    if launch_id is not None and len(str(launch_id).strip()) < 1:
        raise WatchdogError("--launch-id may not be empty when given: omit the flag to address the "
                            "launch directory's ONE uncompleted bootstrap")
    directory = _checked_launch_dir(launch_dir)
    resolved = resolve_bootstrap(directory, launch_id)
    data = resolved["bootstrap"]
    finished = data.get("completed")
    if finished is not None:
        raise WatchdogError(f"the bootstrap in {directory} was closed "
                            f"{_closed_phrase(finished)}: its supervisor model is history — `begin` "
                            f"a fresh bootstrap for the next independent run")
    task_path = _checked_task_file(task)
    config_path = _checked_config_file(config)
    try:
        task_matrix = model_matrix.task_models(task_path)
        default_matrix = model_matrix.load_default_matrix(config_path)
    except model_matrix.ModelMatrixError as exc:
        raise WatchdogError(f"{exc}") from exc
    except OSError as exc:
        raise WatchdogError(f"cannot read the handed-over task {task_path}: {exc}") from exc
    entry = model_matrix.resolve(task_matrix, default_matrix, SUPERVISOR_ROLE)
    model = entry["model"]
    if not model:
        raise ModelUnresolved(
            f"no model resolves for role {SUPERVISOR_ROLE!r}: the handed-over task {task_path} "
            f"names no `models.{SUPERVISOR_ROLE}` and the factory's default matrix offers none "
            f"(source 'none') — there is no third path, so pin `models.{SUPERVISOR_ROLE}` in the "
            f"task or let that role's side of the default matrix declare a model BEFORE the "
            f"supervisor is spawned")
    kept = data.get(SUPERVISOR_MODEL_KEY)
    if kept is not None:
        if kept["model"] == model:
            return {"status": "resolved", "launch_id": resolved["launch_id"],
                    "role": SUPERVISOR_ROLE, "model": model, "source": kept["source"],
                    "recorded": False, "warnings": entry["warnings"],
                    "state": str(resolved["path"])}
        raise WatchdogError(
            f"the supervisor's model of this launch is already resolved to {kept['model']!r} "
            f"(source {kept['source']!r}), but {task_path} now resolves {model!r}: a supervisor's "
            f"model is never swapped mid-launch — restore the handed-over task's "
            f"`models.{SUPERVISOR_ROLE}` pin, or `abandon --reason` this bootstrap and `begin` a "
            f"fresh launch")
    data[SUPERVISOR_MODEL_KEY] = {"model": model, "source": entry["source"],
                                  "resolved_at": _now()}
    path = _atomic_json(resolved["path"], data)
    return {"status": "resolved", "launch_id": resolved["launch_id"], "role": SUPERVISOR_ROLE,
            "model": model, "source": entry["source"], "recorded": True,
            "warnings": entry["warnings"], "state": str(path)}


def _closed_phrase(finished: dict) -> str:
    """How a CLOSED bootstrap names its ending: an abandoned attempt or a completed run."""
    if finished.get("abandoned") is True:
        return f"as ABANDONED at {finished['at']} ({finished['reason']!r})"
    return f"at {finished['at']} for run {finished['run_id']!r}"


def _finish_checkpoint(activated: dict, directory: pathlib.Path) -> str:
    """The bound run's checkpoint must have REACHED THE FINISH before the bootstrap is closed.

    (review R2, critical) `complete` used to read only the bootstrap, so the flow could free the
    launch directory while the run was still `in_progress` and let a second supervisor interleave
    with the first. `complete` therefore reads the checkpoint of the run `activate` bound and
    FAILS CLOSED (exit 2) unless it declares `status: ok` for that same run.
    """
    import delegation_gate as dg  # noqa: PLC0415  (sibling, shared checkpoint reader)
    root = pathlib.Path(activated["repo"])
    path = root / dg.PIPELINE_REL
    try:
        text = dg._read_pipeline(path)
    except dg.GateError as exc:
        raise WatchdogError(f"cannot complete the bootstrap of run {activated['run_id']!r}: its "
                            f"checkpoint {path} is unreadable ({exc}) — the Finish checkpoint is "
                            f"the completion's evidence, so `complete` fails closed") from exc
    status = None
    for line in text.splitlines():
        match = re.match(r"^status:\s*(.*)$", line.rstrip())
        if match:
            status = match.group(1).strip().strip("'\"")
            break
    if status != "ok":
        raise WatchdogError(
            f"cannot complete the bootstrap of run {activated['run_id']!r}: its Finish checkpoint "
            f"{path} declares status {status!r}, not 'ok' — `complete` closes the supervisor at "
            f"the END of the run, so the run must reach the Finish first (the flow writes "
            f"`status: ok` there); a completion while the run is in_progress would free the launch "
            f"directory for a second supervisor mid-run")
    try:
        run_id = _run_id(root)
    except WatchdogError as exc:
        raise WatchdogError(f"cannot complete the bootstrap in {directory}: {exc}") from exc
    if run_id != activated["run_id"]:
        raise WatchdogError(f"the checkpoint {path} now belongs to run {run_id!r}, but this "
                            f"bootstrap is bound to run {activated['run_id']!r}: a completion "
                            f"names the run it supervised — archive the bootstrap instead of "
                            f"completing over another run")
    return status


def complete(launch_dir: str | pathlib.Path, launch_id: str | None = None) -> dict:
    """Close the bootstrap of the run it BOUND, at the run's Finish.

    (review R1, critical) A completed record used to be indistinguishable from an unfinished one,
    so the second run launched from the same directory could never start its own supervisor. The
    completion is ONE per binding and names the run; the finished run's own watchdog state is
    history and is never rewritten here. (review R2) The completion belongs to the Finish: the
    bound run's checkpoint must already declare `status: ok`. Under the keyed lifecycle only the
    ADDRESSED file is written, so a completed record stays immutable.
    """
    directory = _checked_launch_dir(launch_dir)
    resolved = resolve_bootstrap(directory, launch_id)
    data = resolved["bootstrap"]
    if data.get("completed") is not None:
        raise WatchdogError(f"this bootstrap was already closed "
                            f"{_closed_phrase(data['completed'])}: ONE ending per bootstrap — the "
                            f"run is finished and its record is final")
    activated = data.get("activated")
    if activated is None:
        raise WatchdogError(f"the bootstrap in {directory} is not bound to a run: `complete` "
                            f"closes the bootstrap of the run `activate` bound — there is no "
                            f"completed run to record yet (a bootstrap that never bound a run, "
                            f"because Phase 0 failed, is ended with `abandon --reason <why>`)")
    _finish_checkpoint(activated, directory)
    data["completed"] = {"at": _now(), "run_id": activated["run_id"]}
    path = _atomic_json(resolved["path"], data)
    return {"status": "completed", "launch_id": resolved["launch_id"],
            "run_id": activated["run_id"], "completed": data["completed"], "state": str(path)}


def abandon(launch_dir: str | pathlib.Path, reason: str,
            launch_id: str | None = None) -> dict:
    """End a bootstrap that never bound a run, WITH the reason it failed.

    (review R1) A run whose Phase 0 failed — an unparsable task, a refused activation — leaves a
    begun bootstrap behind that bound nothing: `complete` has no bound run to close. This is the ONE
    honest way out, and it is deliberately narrow: the bootstrap must exist, must NOT be bound by
    `activate` (a bound bootstrap is the run IN PROGRESS and ends with `complete` once its
    checkpoint declares `status: ok`), must not already be closed, and the reason is mandatory and
    bounded. The reason stays on the addressed record, which is immutable keyed history.
    """
    directory = _checked_launch_dir(launch_dir)
    resolved = resolve_bootstrap(directory, launch_id)
    data = resolved["bootstrap"]
    if data.get("completed") is not None:
        raise WatchdogError(f"this bootstrap was already closed "
                            f"{_closed_phrase(data['completed'])}: ONE ending per bootstrap — "
                            f"`begin` a fresh one for the next independent run")
    activated = data.get("activated")
    if activated is not None:
        raise WatchdogError(f"the bootstrap in {directory} is bound to run "
                            f"{activated['run_id']!r} since {activated['at']}, so it is a run IN "
                            f"PROGRESS: an activated bootstrap is never abandoned — end it with "
                            f"`complete --launch-dir <launch dir>` once its checkpoint declares "
                            f"`status: ok`, because abandoning a bound run would erase the "
                            f"supervision of a run that may still be spawning")
    note = _validate_text(reason, "--reason")
    data["completed"] = {"at": _now(), "run_id": None, "abandoned": True, "reason": note}
    path = _atomic_json(resolved["path"], data)
    return {"status": "abandoned", "launch_id": resolved["launch_id"], "run_id": None,
            "completed": data["completed"], "events": len(data["events"]), "state": str(path)}


def observe(launch_dir: str | pathlib.Path, event: str, seq: int, detail: str = "",
            launch_id: str | None = None) -> dict:
    """Record ONE Phase 0 observation under the addressed bootstrap.

    (closed vocabulary, strictly increasing sequence) After `activate` the same observation is also
    appended to the run-bound state, so the run's own journal stays complete (the memory write
    happens long after Phase 0).
    """
    directory = _checked_launch_dir(launch_dir)
    resolved = resolve_bootstrap(directory, launch_id)
    data = resolved["bootstrap"]
    finished = data.get("completed")
    if finished is not None:
        raise WatchdogError(f"the bootstrap in {directory} was closed "
                            f"{_closed_phrase(finished)}: its Phase 0 journal is closed — `begin` "
                            f"a fresh bootstrap for the next independent run")
    if event not in PHASE0_EVENTS:
        raise WatchdogError(f"--event must be one of the Phase 0 operations "
                            f"({', '.join(PHASE0_EVENTS)}), got {event!r}: the vocabulary is "
                            f"closed — an event outside it is not an observation of Phase 0")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise WatchdogError(f"--seq must be a non-negative integer (the Phase 0 position of the "
                            f"event), got {seq!r}")
    last = max((entry["seq"] for entry in data["events"]), default=-1)
    if seq == last and any(entry["seq"] == seq for entry in data["events"]):
        raise WatchdogError(f"--seq {seq} is already taken: the Phase 0 sequence is STRICTLY "
                            f"increasing and two events may not share a place in the order (next "
                            f"free position: {last + 1})")
    if seq <= last:
        raise WatchdogError(f"--seq {seq} regresses the Phase 0 order (the last observed position "
                            f"is {last}): the sequence is STRICTLY increasing, so the journal may "
                            f"not be rewritten after the fact (next free position: {last + 1})")
    record = {"event": event, "seq": seq, "at": _now(), "detail": _validate_note(detail, "--detail")}
    data["events"].append(record)
    data["events"].sort(key=lambda entry: entry["seq"])
    activated = data["activated"]
    if activated is not None:
        # The run-bound journal is the authoritative one once the bootstrap has bound: write it
        # first, so a failure cannot leave the launch-scoped file ahead of the run's own record.
        root = pathlib.Path(activated["repo"])
        bound = _state_for_run(_checked_repo(root), activated["run_id"])
        bound["events"].append(record)
        bound["events"].sort(key=lambda entry: entry["seq"])
        _write_state(root, bound)
    path = _atomic_json(resolved["path"], data)
    return {"status": "observed", "launch_id": resolved["launch_id"], "run_id": data["run_id"],
            "event": event, "seq": seq, "events": len(data["events"]),
            "activated": activated is not None, "state": str(path)}


def _phase0_problem(observed: list[str]) -> str | None:
    """The reason the Phase 0 journal cannot bind a run, or None when it can (order matters)."""
    missing = [event for event in PHASE0_REQUIRED if event not in observed]
    if missing:
        return ("the supervisor did not observe " + ", ".join(missing) + " before this run: "
                "Phase 0 ran with the supervisor watching "
                + (", ".join(observed) or "nothing")
                + f" — the OLD order (parse first, supervise later) is refused, the mandated "
                f"order is {' -> '.join(PHASE0_REQUIRED)}")
    positions = [observed.index(event) for event in PHASE0_REQUIRED]
    if positions != sorted(positions):
        return ("the mandated Phase 0 operations were observed OUT OF ORDER: the journal records "
                f"{' -> '.join(observed)}, but the run must be watched in the order "
                f"{' -> '.join(PHASE0_REQUIRED)} — the parse cannot be `observed` after the fact")
    return None


def _pending_activation(existing: dict | None, data: dict, run_id: str) -> bool:
    """True when the run's launch is THIS bootstrap's own HALF-FINISHED activation.

    (defect C07) `activate` is one logical transition over two files: the run-bound state (which
    carries `launch.at` = the bootstrap's `begun_at`) and then the bootstrap (which carries the
    binding). If the second write fails, the run looks "already launched" although nothing bound
    it, and a retry of the SAME bootstrap used to be refused — the run could never be supervised.
    The launch time is the bootstrap's own microsecond `begun_at`, so a matching `launch.at` is
    that interruption and never a competing supervisor: retrying finishes the same transition.
    """
    if existing is None or existing["run_id"] != run_id or existing["launch"] is None:
        return False
    return (existing["launch"].get("authority") == "run"
            and existing["launch"].get("at") == data["begun_at"])


def activate(launch_dir: str | pathlib.Path, repo: str | pathlib.Path,
             launch_id: str | None = None) -> dict:
    """Bind the bootstrap ATOMICALLY to the run that now exists (exit 1 = Phase 0 was unwatched)."""
    directory = _checked_launch_dir(launch_dir)
    resolved = resolve_bootstrap(directory, launch_id)
    data = resolved["bootstrap"]
    if data.get("completed") is not None:
        raise WatchdogError(f"the bootstrap in {directory} was closed "
                            f"{_closed_phrase(data['completed'])}: a closed bootstrap cannot be "
                            f"re-activated — `begin` a fresh bootstrap for the next independent "
                            f"run")
    if data["activated"] is not None:
        raise WatchdogError(f"this bootstrap was already activated at {data['activated']['at']} "
                            f"for run {data['activated']['run_id']!r}: ONE activation per "
                            f"bootstrap — a second one would re-bind the supervision and could "
                            f"rewrite its history")
    root = _checked_repo(repo)
    run_id = _run_id(root)
    observed = [entry["event"] for entry in data["events"]]
    problem = _phase0_problem(observed)
    if problem is not None:
        raise ActivationRefused(f"{problem}")
    existing = read_state(root)
    if existing is not None and existing["run_id"] != run_id:
        raise WatchdogError(f"{root / WATCHDOG_REL} belongs to run {existing['run_id']!r}, but the "
                            f"current pipeline run is {run_id!r}: the watchdog state is bound to "
                            f"one run — archive the stale file instead of activating over it")
    if existing is not None and existing["launch"] is not None \
            and not _pending_activation(existing, data, run_id):
        raise WatchdogError(f"the watchdog of run {run_id!r} was already launched at "
                            f"{existing['launch']['at']}: ONE watchdog per run — archive the "
                            f"stale state or resume the supervisor instead of re-activating")
    state = existing if existing is not None else _fresh(run_id)
    state["launch"] = {"at": data["begun_at"], "authority": "run"}
    state["events"] = [dict(entry) for entry in data["events"]]
    # The resolved supervisor model travels WITH the binding: the run's own record then names the
    # model its supervisor was spawned with, so the finish attribution can be checked against it.
    state[SUPERVISOR_MODEL_KEY] = data.get(SUPERVISOR_MODEL_KEY)
    path = _write_state(root, state)
    data["run_id"] = run_id
    data["activated"] = {"at": _now(), "run_id": run_id, "repo": str(root)}
    _atomic_json(resolved["path"], data)
    return {"status": "activated", "launch_id": resolved["launch_id"], "run_id": run_id,
            "events": len(state["events"]), "launch": state["launch"],
            "supervisor_model": state[SUPERVISOR_MODEL_KEY], "state": str(path)}


def launch(root: str | pathlib.Path) -> dict:
    """Record the run's ONE watchdog launch (single owner per run, under the run's authority)."""
    root = _checked_repo(root)
    run_id = _run_id(root)
    data = _state_for_run(root, run_id)
    if data["launch"] is not None:
        raise WatchdogError(f"the watchdog of run {run_id} was already launched at "
                            f"{data['launch']['at']}: ONE watchdog per run — resume it on "
                            f"anomalies instead of launching a second one")
    data["launch"] = {"at": _now(), "authority": "run"}
    path = _write_state(root, data)
    return {"status": "launched", "run_id": run_id, "launch": data["launch"], "state": str(path)}


def deny(root: str | pathlib.Path, rule: str, role: str, detail: str) -> dict:
    """Record a BLOCKING deny: no phase gate passes while it is unresolved."""
    root = _checked_repo(root)
    rule = _validate_rule(rule)
    role = _validate_role(role)
    detail = _validate_text(detail, "--detail")
    run_id = _run_id(root)
    data = _state_for_run(root, run_id)
    record = {"rule": rule, "role": role, "detail": detail, "at": _now(), "resolved": None}
    data["denies"].append(record)
    path = _write_state(root, data)
    return {"status": "denied", "run_id": run_id, "deny": record, "state": str(path),
            "blocking": True}


def resolve(root: str | pathlib.Path, rule: str, role: str, evidence: str) -> dict:
    """Resolve every matching unresolved deny, with the evidence of the correction."""
    root = _checked_repo(root)
    rule = _validate_rule(rule)
    role = _validate_role(role)
    evidence = _validate_text(evidence, "--evidence")
    run_id = _run_id(root)
    data = _state_for_run(root, run_id)
    matched = [entry for entry in _unresolved(data)
               if entry["rule"] == rule and entry["role"] == role]
    if not matched:
        raise WatchdogError(f"no UNRESOLVED deny for rule {rule!r} and role {role!r}: a "
                            f"resolution answers a recorded blocking deny (known unresolved: "
                            f"{len(_unresolved(data))})")
    stamp = _now()
    for entry in matched:
        entry["resolved"] = {"at": stamp, "evidence": evidence}
    path = _write_state(root, data)
    return {"status": "resolved", "run_id": run_id, "resolved": len(matched), "state": str(path)}


def status(root: str | pathlib.Path) -> dict:
    """The watchdog state report. FAIL-CLOSED: a run with no recorded watchdog launch is blocked.

    `gate_all.py` runs this as the `watchdog-deny` gate row of phases K and Y, so a zero exit here
    means "the watchdog watched this run and recorded no unresolved deny". A run that never
    launched the watchdog has NO such record — a missing state file is not "nothing to report",
    it is the absence of the real-time supervision layer — so it exits non-zero with the reason
    instead of silently passing the gate.
    """
    root = _checked_repo(root)
    data = read_state(root)
    if data is None:
        return {"status": "unlaunched", "launched": False, "scans": 0, "anomalies": [],
                "unresolved_denies": [], SUPERVISOR_MODEL_KEY: None,
                "state": str(root / WATCHDOG_REL),
                "fail_closed": (f"no {WATCHDOG_REL.as_posix()} for this run: the watchdog was never "
                                f"launched, so no phase gate can claim the run was supervised — "
                                f"launch it at run start with `supervisor_watchdog.py launch`")}
    # A state file of ANOTHER run is stale even for a read: the watchdog-deny gate row must never
    # consume another run's verdicts.
    run_id = _run_id(root)
    if data["run_id"] != run_id:
        raise WatchdogError(f"{root / WATCHDOG_REL} belongs to run {data['run_id']!r}, but the "
                            f"current pipeline run is {run_id!r}: archive the stale file")
    unresolved = _unresolved(data)
    if data["launch"] is None:
        return {"status": "unlaunched", "launched": False, "run_id": data["run_id"],
                "scans": data["scans"], "anomalies": data["anomalies"],
                "unresolved_denies": unresolved, "state": str(root / WATCHDOG_REL),
                SUPERVISOR_MODEL_KEY: data.get(SUPERVISOR_MODEL_KEY),
                "fail_closed": (f"{root / WATCHDOG_REL} records no launch for run {run_id!r}: the "
                                f"watchdog of this run was never started, so the phase gate cannot "
                                f"pass — launch it with `supervisor_watchdog.py launch`")}
    return {"status": "blocked" if unresolved else "ok", "launched": True,
            "run_id": data["run_id"], "scans": data["scans"], "anomalies": data["anomalies"],
            "unresolved_denies": unresolved, SUPERVISOR_MODEL_KEY: data.get(SUPERVISOR_MODEL_KEY),
            "state": str(root / WATCHDOG_REL)}


# -------------------------------------------------------------------------------------------- scan

def _counter_anomalies(root: pathlib.Path, emit) -> None:
    """The pipeline counters must respect the budgets plus the recorded owner authorizations."""
    import delegation_gate as dg  # noqa: PLC0415  (sibling scanner, reused)
    path = root / dg.PIPELINE_REL
    try:
        text = dg._read_pipeline(path)
    except dg.GateError as exc:
        emit(RULE_BUDGETS, "main", f"the WIP checkpoint is unreadable: {exc}")
        return
    if dg._block(dg._lines(text), dg.COUNTERS_HEADER) is None:
        return                                   # nothing counted yet (the finish audit's domain)
    try:
        counters = dg.read_counters(text)
    except dg.GateError as exc:
        emit(RULE_BUDGETS, "main", f"the retry counters are malformed: {exc}")
        return
    for role, value in sorted(counters.items()):
        if role in NON_ROLE_COUNTERS:
            continue            # a mandated non-role counter (plan_rejections) carries no budget
        if role not in dg.BUDGETS:
            emit(RULE_BUDGETS, "main",
                 f"retry_counters.{role} exists, but role {role!r} has no retry budget: the "
                 f"checkpoint was hand-written (budgeted roles: {', '.join(sorted(dg.BUDGETS))})")
            continue
        # The SAME ceiling the pre-delegation gate enforces: only the coder's follows the approved
        # plan (one per distinct coder task + one retry reserve), so a legitimate multi-task run is
        # never false-flagged, and the raw base table is never compared against on its own.
        budget = dg.budget_for(role, root)
        ceiling = budget + dg._authorizations_for(text, role)
        if value > ceiling:
            emit(RULE_BUDGETS, "main",
                 f"retry_counters.{role} is {value}, above its budget {budget}"
                 + (f" + {ceiling - budget} owner authorization(s)" if ceiling >
                    budget else "")
                 + ": the counter was moved without the gate (rule `retry-budgets`)")


def _permit_anomalies(root: pathlib.Path, run_id: str, emit) -> None:
    """The permits file must parse, validate, and belong to THIS run."""
    import permit_gate as pg  # noqa: PLC0415  (sibling scanner, reused)
    path = root / pg.PERMITS_REL
    if not path.is_file():
        return
    try:
        data = pg.read_permits(root)
    except pg.PermitError as exc:
        emit(RULE_PERMITS, "main", f"the permits file is malformed: {exc}")
        return
    if data["run_id"] != run_id:
        emit(RULE_PERMITS, "main",
             f"the permits file belongs to run {data['run_id']!r}, but the current run is "
             f"{run_id!r}: stale permits never authorize this run's delegations")


def _gate_record_anomalies(root: pathlib.Path, emit) -> None:
    """Every gate record that EXISTS must be complete and clean (a missing phase record is the
    finish checkpoint's concern, not the scan's)."""
    import gate_all  # noqa: PLC0415  (sibling scanner, reused)
    contract = gate_all.pipeline_contract(root)
    for phase in gate_all.PHASES:
        path = root / gate_all.RECORD_REL / f"gate-{phase}.md"
        if not path.is_file():
            continue
        try:
            problems, _rows = gate_all.verify_record(path, phase, contract,
                                                     "the working tree against HEAD")
        except gate_all.GateAllError as exc:
            problems = [str(exc)]
        for problem in problems:
            emit(RULE_GATE_RECORD, "main", f"gate record {path.name}: {problem}")


def _action_journal_anomalies(root: pathlib.Path, emit) -> None:
    """The action-gate journal must stay well-formed (a malformed row is unauditable)."""
    import action_gate  # noqa: PLC0415  (sibling scanner, reused)
    path = root / action_gate.DEFAULT_JOURNAL
    if not path.is_file():
        return
    try:
        _rows, problems = action_gate.read_journal_rows(path)
    except action_gate.AuditError as exc:
        emit(RULE_ACTIONS, "main", f"the action-gate journal is unreadable: {exc}")
        return
    for problem in problems:
        emit(RULE_ACTIONS, "main", f"action-gate journal: {problem}")


def scan(root: str | pathlib.Path) -> dict:
    """ONE deterministic scan pass over the `.code-factory` state (zero LLM cost).

    New anomalies are appended atomically with the scan number; a finding a previous scan already
    recorded is not duplicated. Returns the scan report (also what the CLI prints).
    """
    root = _checked_repo(root)
    run_id = _run_id(root)
    data = _state_for_run(root, run_id)
    findings: list[dict] = []

    def emit(rule: str, role: str, detail: str) -> None:
        findings.append({"rule": rule, "role": role, "detail": detail})

    _counter_anomalies(root, emit)
    _permit_anomalies(root, run_id, emit)
    _gate_record_anomalies(root, emit)
    _action_journal_anomalies(root, emit)

    known = {(entry["rule"], entry["detail"]) for entry in data["anomalies"]}
    data["scans"] += 1
    new: list[dict] = []
    for finding in findings:
        if (finding["rule"], finding["detail"]) in known:
            continue
        record = {**finding, "detected_at": _now(), "scan": data["scans"]}
        data["anomalies"].append(record)
        new.append(record)
    path = _write_state(root, data)
    unresolved = _unresolved(data)
    verdict = "blocked" if unresolved else ("anomalies" if new else "clean")
    return {"status": verdict, "run_id": run_id, "scan": data["scans"],
            "new_anomalies": new, "anomalies_total": len(data["anomalies"]),
            "unresolved_denies": unresolved, "state": str(path)}


# -------------------------------------------------------------------------------------------- CLI

def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=False))


class _WideHelp(argparse.RawDescriptionHelpFormatter):
    """A help formatter that never wraps the usage line.

    `gate_all.py` decides whether the `watchdog-deny` row applies by reading the FIRST line of
    `--help` for `{begin,...,status}`; argparse's default 80-column wrap puts the choices on the
    second line once there are eight subcommands, which silently SKIPS the gate row that exists to
    block a run for an unresolved deny. The width is therefore explicit, not terminal-derived.
    """

    def __init__(self, prog: str, **kwargs):
        kwargs.setdefault("width", 200)
        super().__init__(prog, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    def add(sub: argparse._SubParsersAction, name: str, **kwargs) -> argparse.ArgumentParser:
        # The subcommand choices must stay on the FIRST usage line: `gate_all.py` reads them from
        # `--help` to decide whether the watchdog-deny row applies, so every parser is wide.
        return sub.add_parser(name, formatter_class=_WideHelp, **kwargs)

    ap = argparse.ArgumentParser(prog="supervisor_watchdog.py", description=__doc__,
                                 formatter_class=_WideHelp)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = add(sub, "begin", help="record ONE keyed watchdog bootstrap BEFORE Phase 0 (launch-scoped, "
                               "run-id independent; returns the launch id)")
    p.add_argument("--launch-dir", required=True,
                   help="the directory the factory was launched from (holds "
                        ".code-factory/state/watchdog-bootstrap-<launch id>.json)")
    p.set_defaults(func=_cmd_begin)

    p = add(sub, "resolve-model", help="resolve and RECORD the supervisor's model from the "
                                       "handed-over task BEFORE the spawn (a task pin wins "
                                       "verbatim; only an absent pin takes the primary default)")
    p.add_argument("--launch-dir", required=True,
                   help="the directory the factory was launched from (holds the bootstrap the "
                        "resolution is recorded in)")
    p.add_argument("--task", required=True,
                   help="the task file AS HANDED OVER (the same file the parse reads); only its "
                        "`models:` matrix is read here")
    p.add_argument("--config", default=None,
                   help="the CLI config carrying default_model / [secondary_model] default_model "
                        "(default: the factory's own config)")
    p.add_argument("--launch-id", default=None,
                   help="the launch nonce `begin` returned (omit it while the launch directory "
                        "holds exactly ONE uncompleted bootstrap)")
    p.set_defaults(func=_cmd_resolve_model)

    p = add(sub, "observe", help="record ONE Phase 0 observation (closed vocabulary, "
                                 "strictly increasing sequence)")
    p.add_argument("--launch-dir", required=True)
    p.add_argument("--event", required=True,
                   help=f"one of {', '.join(PHASE0_EVENTS)}")
    p.add_argument("--seq", required=True, type=int,
                   help="the Phase 0 position of the event (a non-negative integer, strictly "
                        "increasing across the journal)")
    p.add_argument("--detail", default="", help="an optional routing note (bounded)")
    p.add_argument("--launch-id", default=None,
                   help="the launch nonce `begin` returned (omit it while the launch directory "
                        "holds exactly ONE uncompleted bootstrap)")
    p.set_defaults(func=_cmd_observe)

    p = add(sub, "activate", help="bind the bootstrap to the run once its run_id exists "
                                  "(exit 1 while Phase 0 went unwatched or out of order)")
    p.add_argument("--launch-dir", required=True)
    p.add_argument("--repo", required=True,
                   help="the RESOLVED repository root holding .code-factory/")
    p.add_argument("--launch-id", default=None,
                   help="the launch nonce `begin` returned (omit it while the launch directory "
                        "holds exactly ONE uncompleted bootstrap)")
    p.set_defaults(func=_cmd_activate)

    p = add(sub, "complete", help="close the bootstrap of the run it bound (ONE completion per "
                                  "binding; the record is then immutable history)")
    p.add_argument("--launch-dir", required=True)
    p.add_argument("--launch-id", default=None,
                   help="the launch nonce `begin` returned (omit it while the launch directory "
                        "holds exactly ONE uncompleted bootstrap)")
    p.set_defaults(func=_cmd_complete)

    p = add(sub, "abandon", help="end a bootstrap that NEVER bound a run (a failed Phase 0), with "
                                 "the reason it failed; an ACTIVATED bootstrap is never abandoned")
    p.add_argument("--launch-dir", required=True)
    p.add_argument("--reason", required=True,
                   help=f"why this bootstrap never bound a run (at most {DETAIL_MAX} characters)")
    p.add_argument("--launch-id", default=None,
                   help="the launch nonce `begin` returned (omit it while the launch directory "
                        "holds exactly ONE uncompleted bootstrap)")
    p.set_defaults(func=_cmd_abandon)

    p = add(sub, "launch", help="record the run's ONE watchdog launch (single owner)")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_launch)

    p = add(sub, "scan", help="one deterministic scan pass over .code-factory state")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_scan)

    p = add(sub, "deny", help="record a BLOCKING deny (no phase gate passes until resolved)")
    p.add_argument("--repo", required=True)
    p.add_argument("--rule", required=True, help="the rulebook citation id ([A-Za-z0-9._-]+)")
    p.add_argument("--role", required=True,
                   help="the violating role the correction is routed to (a factory role or "
                        "'main')")
    p.add_argument("--detail", required=True,
                   help=f"what was violated and what corrects it (at most {DETAIL_MAX} "
                        f"characters)")
    p.set_defaults(func=_cmd_deny)

    p = add(sub, "resolve", help="resolve a blocking deny with the correction's evidence")
    p.add_argument("--repo", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--evidence", required=True,
                   help="the artifact or re-check that proves the correction")
    p.set_defaults(func=_cmd_resolve)

    p = add(sub, "status", help="report anomalies/denies (exit 1 while a deny blocks, and "
                                      "fail closed when this run never launched the watchdog)")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_status)
    return ap


def _cmd_begin(args: argparse.Namespace) -> int:
    _emit(begin(args.launch_dir))
    return 0


def _cmd_resolve_model(args: argparse.Namespace) -> int:
    _emit(resolve_model(args.launch_dir, args.task, args.config, args.launch_id))
    return 0


def _cmd_observe(args: argparse.Namespace) -> int:
    _emit(observe(args.launch_dir, args.event, args.seq, args.detail, args.launch_id))
    return 0


def _cmd_activate(args: argparse.Namespace) -> int:
    _emit(activate(args.launch_dir, args.repo, args.launch_id))
    return 0


def _cmd_complete(args: argparse.Namespace) -> int:
    _emit(complete(args.launch_dir, args.launch_id))
    return 0


def _cmd_abandon(args: argparse.Namespace) -> int:
    _emit(abandon(args.launch_dir, args.reason, args.launch_id))
    return 0


def _cmd_launch(args: argparse.Namespace) -> int:
    _emit(launch(args.repo))
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    result = scan(args.repo)
    _emit(result)
    return 1 if result["status"] in ("anomalies", "blocked") else 0


def _cmd_deny(args: argparse.Namespace) -> int:
    _emit(deny(args.repo, args.rule, args.role, args.detail))
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    _emit(resolve(args.repo, args.rule, args.role, args.evidence))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    result = status(args.repo)
    _emit(result)
    if result["status"] == "unlaunched":
        print(f"FAIL - {result['fail_closed']}", file=sys.stderr)
        return 1                       # fail closed: the phase gate must not pass
    return 1 if result["status"] == "blocked" else 0


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except ActivationRefused as exc:
        print(f"supervisor_watchdog.py: FAIL - {exc}", file=sys.stderr)
        return 1                       # fail closed: Phase 0 was not supervised as mandated
    except ModelUnresolved as exc:
        print(f"supervisor_watchdog.py: FAIL - {exc}", file=sys.stderr)
        return 1                       # a STOP: the supervisor has no model to be spawned with
    except WatchdogError as exc:
        print(f"supervisor_watchdog.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

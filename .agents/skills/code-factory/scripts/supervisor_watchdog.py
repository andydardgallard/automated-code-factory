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
   "anomalies": [{"rule": "<rulebook id>", "role": "<factory role|main>", "detail": "<text>",
                  "detected_at": "<ISO>", "scan": <int>}],
   "denies": [{"rule": "<rulebook id>", "role": "<factory role|main>", "detail": "<text>",
               "at": "<ISO>",
               "resolved": null | {"at": "<ISO>", "evidence": "<text>"}}]}

SUBCOMMANDS

  launch  --repo <root>
        record the run's ONE watchdog launch (single owner: a second launch for the same run
        fails; a state file of ANOTHER run is stale and must be archived first)
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
        this run never recorded a launch (fail closed: `gate_all.py` runs this as the
        `watchdog-deny` row of phases K and Y, and a run the watchdog never watched must not pass
        a phase gate)

EXIT CODES: 0 clean / recorded, 1 anomalies found, an unresolved deny, or NO recorded launch for
this run (the phase gate fails closed), 2 input error (a malformed state, a stale run binding, a bad
argument — a message naming the fix, never a traceback).
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

WATCHDOG_REL = pathlib.Path(".code-factory") / "state" / "watchdog.json"
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
RULE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# A deny detail is a routing note, not a document: bounded so the state file stays a state file.
DETAIL_MAX = 4000
DENY_ROLES = tuple(ROLES) + ("main",)
# The scan's own rule citations (the rulebook rules each check stands on).
RULE_BUDGETS = "retry-budgets"
RULE_PERMITS = "permit-trail"
RULE_GATE_RECORD = "gate-record"
RULE_ACTIONS = "destructive-action-gate"


class WatchdogError(ValueError):
    """An input this script cannot honour: a message + exit 2, never a traceback."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the verdicts survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def _now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise WatchdogError(f"repository root does not exist: {root}")
    return root


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


def _validate_text(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise WatchdogError(f"{label} is required and may not be empty")
    if len(text) > DETAIL_MAX:
        raise WatchdogError(f"{label} is {len(text)} characters: a routing note is bounded to "
                            f"{DETAIL_MAX} characters so the watchdog state stays a state file")
    return text


# ------------------------------------------------------------------------------------------ storage

def _fresh(run_id: str) -> dict:
    return {"run_id": run_id, "launch": None, "scans": 0, "anomalies": [], "denies": []}


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
    path = root / WATCHDOG_REL
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                                        suffix=".tmp")
    except OSError as exc:
        raise WatchdogError(f"cannot write the watchdog state {path}: {exc}") from exc
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise WatchdogError(f"cannot write the watchdog state {path} (the previous one is "
                            f"untouched): {exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise
    return path


def _unresolved(data: dict) -> list[dict]:
    return [deny for deny in data["denies"] if deny.get("resolved") is None]


# -------------------------------------------------------------------------------------- subcommands

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
                "unresolved_denies": [], "state": str(root / WATCHDOG_REL),
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
                "fail_closed": (f"{root / WATCHDOG_REL} records no launch for run {run_id!r}: the "
                                f"watchdog of this run was never started, so the phase gate cannot "
                                f"pass — launch it with `supervisor_watchdog.py launch`")}
    return {"status": "blocked" if unresolved else "ok", "launched": True,
            "run_id": data["run_id"], "scans": data["scans"], "anomalies": data["anomalies"],
            "unresolved_denies": unresolved, "state": str(root / WATCHDOG_REL)}


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
        if role not in dg.BUDGETS:
            emit(RULE_BUDGETS, "main",
                 f"retry_counters.{role} exists, but role {role!r} has no retry budget: the "
                 f"checkpoint was hand-written (budgeted roles: {', '.join(sorted(dg.BUDGETS))})")
            continue
        ceiling = dg.BUDGETS[role] + dg._authorizations_for(text, role)
        if value > ceiling:
            emit(RULE_BUDGETS, "main",
                 f"retry_counters.{role} is {value}, above its budget {dg.BUDGETS[role]}"
                 + (f" + {ceiling - dg.BUDGETS[role]} owner authorization(s)" if ceiling >
                    dg.BUDGETS[role] else "")
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="supervisor_watchdog.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch", help="record the run's ONE watchdog launch (single owner)")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_launch)

    p = sub.add_parser("scan", help="one deterministic scan pass over .code-factory state")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("deny", help="record a BLOCKING deny (no phase gate passes until resolved)")
    p.add_argument("--repo", required=True)
    p.add_argument("--rule", required=True, help="the rulebook citation id ([A-Za-z0-9._-]+)")
    p.add_argument("--role", required=True,
                   help="the violating role the correction is routed to (a factory role or "
                        "'main')")
    p.add_argument("--detail", required=True,
                   help=f"what was violated and what corrects it (at most {DETAIL_MAX} "
                        f"characters)")
    p.set_defaults(func=_cmd_deny)

    p = sub.add_parser("resolve", help="resolve a blocking deny with the correction's evidence")
    p.add_argument("--repo", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--evidence", required=True,
                   help="the artifact or re-check that proves the correction")
    p.set_defaults(func=_cmd_resolve)

    p = sub.add_parser("status", help="report anomalies/denies (exit 1 while a deny blocks, and "
                                      "fail closed when this run never launched the watchdog)")
    p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    p.set_defaults(func=_cmd_status)
    return ap


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
    except WatchdogError as exc:
        print(f"supervisor_watchdog.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Contract test for `supervisor_watchdog.py` — the supervisor watchdog's deterministic scanner.

WHY THIS EXISTS

The supervisor is a run-long BACKGROUND WATCHDOG: it is launched once per run, the deterministic
`scan` pass costs zero LLM tokens, LLM resumes happen only on flagged anomalies, and a confirmed
violation becomes a BLOCKING deny that fails `gate_all.py` phase K/Y until it is resolved with
evidence. This test pins exactly that, through the shipped CLI (a subprocess, like the flow calls
it):

  - a CLEAN scan finds nothing and costs nothing (exit 0, no anomalies, the state file written
    atomically and run-bound);
  - anomaly detection: a counter above its budget, a malformed permits file, stale permits of
    another run, a failing gate record row and a malformed action-gate journal row each become ONE
    recorded anomaly (rule + role + detail), and a re-scan never duplicates a finding;
  - a stale run binding (the state file of ANOTHER run) and a malformed state file are fail-closed
    input errors (exit 2, no traceback), never silently reused;
  - the single-owner launch: one launch per run, a second launch and a launch over another run's
    state are refused;
  - the BOOTSTRAP ORDER (mistakes.txt item 1): the supervisor begins BEFORE Phase 0 — `begin` is
    run-id INDEPENDENT and launch-scoped, `observe` records each Phase 0 event (closed vocabulary,
    strictly increasing sequence) and `activate` binds the bootstrap atomically to the run once the
    run_id exists; an event observed with no recorded begin, and an activation whose mandated
    operations were never observed or were observed OUT OF ORDER, are refused — the OLD order (parse
    first, supervise later) can never become a green run; a bound bootstrap is COMPLETED once with
    `complete`, and that terminal, run-bound record frees the launch directory for the next
    independent run instead of blocking it forever; a bootstrap that never bound a run (a failed
    Phase 0) is ended with `abandon --reason` — the reason stays on the record — while an
    ACTIVATED bootstrap is a run in progress and is never abandoned;
  - the KEYED bootstrap (defect C): `begin` mints a launch nonce (`\\d{8}-\\d{6}-[0-9a-f]{6}`) and
    writes `watchdog-bootstrap-<launch_id>.json`, so several factories launched from ONE directory
    into DIFFERENT repositories never share a mutable bootstrap file — a second `begin` is a NEW
    keyed bootstrap (the old single-occupancy refusal is inverted on purpose, owner-approved);
    `observe`/`activate`/`complete`/`abandon` take `--launch-id`, and without it the ONE
    uncompleted bootstrap (an unkeyed legacy file included) is resolved, while MULTIPLE uncompleted
    bootstraps are an exit-2 ambiguity that names every id and demands `--launch-id`, never a
    guess; a completed keyed record is an IMMUTABLE history entry (no cross-run `history`
    carry-over) and an unkeyed legacy bootstrap stays resumable, never silently migrated; a
    malformed or unknown `--launch-id` is an exit-2 input error;
  - an observation note (`observe --detail`) is OPTIONAL and bounded: empty is legitimate, 4000
    characters is the documented bound and 4001 is an exit-2 input error that records nothing;
  - `retry_counters.plan_rejections` — the counter the flow MANDATES — is a non-role counter, never
    an unknown role and never a budgeted one;
  - a recorded deny blocks: `status` exits 1 while the deny is unresolved, the deny names the
    violating role and the rulebook citation (the correction routing), `resolve` unblocks with
    evidence, and `gate_all.py` phase K fails while the deny stands (wired as the watchdog-deny
    gate row);
  - the CLI contract: `--help` exit 0 for every subcommand, usage errors exit 2, no traceback, and
    the help survives a legacy console code page.

Exit code 0 = every assertion passes, 1 = the watchdog did not behave as the contract says.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("supervisor_watchdog.py")
STATE_REL = pathlib.Path(".code-factory") / "state" / "watchdog.json"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
RUN_ID = "20261103-8e939171"
OTHER_RUN = "20261104-b5b601f6"
# The documented bound of a routing note (`deny --detail`, `observe --detail`).
DETAIL_MAX = 4000
# The launch nonce `begin` mints: UTC timestamp + random suffix, and a FILENAME component.
LAUNCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

CHECKPOINT = """\
run_id: {run_id}
phase: w2
status: in_progress
updated_at: "2026-11-03T20:00:00+03:00"
retry_counters:
  coder: 0
  ba: 0
  planner: 0
  diagnostician: 0
  advisor: 0
  infrastructure: 0
  reviewer: 0
"""


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stdout and "Traceback" not in res.stderr,
          f"{label}: no traceback allowed: {res.stderr!r}")


def payload(res: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}


def repo(tmp: pathlib.Path, name: str, checkpoint: str | None = None) -> pathlib.Path:
    """A repository with a WIP checkpoint (counters at zero unless the caller says otherwise)."""
    root = tmp / name
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (root / PIPELINE_REL).write_text(
        checkpoint if checkpoint is not None else CHECKPOINT.format(run_id=RUN_ID),
        encoding="utf-8")
    return root


def state_of(root: pathlib.Path) -> dict:
    return json.loads((root / STATE_REL).read_text(encoding="utf-8"))


def finish_checkpoint(root: pathlib.Path) -> None:
    """Reach the run's Finish: the WIP checkpoint leaves `in_progress` and records `status: ok`."""
    path = root / PIPELINE_REL
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("status: in_progress", "status: ok"), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# A clean scan finds nothing and costs nothing
# --------------------------------------------------------------------------------------------

def test_clean_scan(tmp: pathlib.Path) -> None:
    root = repo(tmp, "clean")
    res = run("scan", "--repo", str(root))
    expect_clean_cli(res, 0, "a clean scan")
    report = payload(res)
    check(report["status"] == "clean" and report["new_anomalies"] == []
          and report["anomalies_total"] == 0,
          f"a clean scan reports no anomaly (zero tokens, zero findings): {report!r}")
    data = state_of(root)
    check(data["run_id"] == RUN_ID and data["scans"] == 1 and data["anomalies"] == []
          and data["launch"] is None,
          f"the state file is run-bound and records the scan: {data!r}")
    # A second clean scan is just as quiet (and increments only the scan counter).
    res = run("scan", "--repo", str(root))
    expect_clean_cli(res, 0, "a second clean scan")
    check(payload(res)["scan"] == 2 and payload(res)["anomalies_total"] == 0,
          f"the scan counter increments, nothing else: {payload(res)!r}")


# --------------------------------------------------------------------------------------------
# Anomaly detection: each broken state becomes ONE recorded anomaly, never duplicated
# --------------------------------------------------------------------------------------------

def test_anomaly_detection(tmp: pathlib.Path) -> None:
    # A counter above its budget (hand-written checkpoint).
    root = repo(tmp, "over-budget",
                CHECKPOINT.format(run_id=RUN_ID).replace("  reviewer: 0", "  reviewer: 3"))
    res = run("scan", "--repo", str(root))
    expect_clean_cli(res, 1, "a counter above the budget")
    report = payload(res)
    check(report["status"] == "anomalies" and len(report["new_anomalies"]) == 1,
          f"exactly one anomaly is recorded: {report!r}")
    anomaly = report["new_anomalies"][0]
    check(anomaly["rule"] == "retry-budgets" and anomaly["role"] == "main"
          and "reviewer" in anomaly["detail"] and anomaly["scan"] == 1,
          f"the anomaly names the rule, the role and the counter: {anomaly!r}")

    # A re-scan of the same broken state records NO duplicate (and exits 0: nothing new, no deny).
    res = run("scan", "--repo", str(root))
    expect_clean_cli(res, 0, "a re-scan with no new finding")
    check(payload(res)["new_anomalies"] == [] and payload(res)["anomalies_total"] == 1,
          f"an anomaly is recorded once: {payload(res)!r}")

    # An unknown counter role and a malformed counter value are anomalies too.
    weird = repo(tmp, "weird-counter",
                 "run_id: " + RUN_ID + "\nretry_counters:\n  wizard: 1\n")
    res = run("scan", "--repo", str(weird))
    expect_clean_cli(res, 1, "a counter for a role with no budget")
    check("wizard" in payload(res)["new_anomalies"][0]["detail"],
          f"the unknown role must be named: {payload(res)!r}")
    broken = repo(tmp, "broken-counter",
                  "run_id: " + RUN_ID + "\nretry_counters:\n  reviewer: many\n")
    res = run("scan", "--repo", str(broken))
    expect_clean_cli(res, 1, "a malformed counter value")
    check("malformed" in payload(res)["new_anomalies"][0]["detail"],
          f"the malformed counter must be named: {payload(res)!r}")

    # A malformed permits file and stale permits of another run.
    permits = repo(tmp, "bad-permits")
    (permits / PERMITS_REL).write_text("{ not json", encoding="utf-8")
    res = run("scan", "--repo", str(permits))
    expect_clean_cli(res, 1, "a malformed permits file")
    check(payload(res)["new_anomalies"][0]["rule"] == "permit-trail",
          f"the permits violation cites the permit trail: {payload(res)!r}")
    stale = repo(tmp, "stale-permits")
    (stale / PERMITS_REL).write_text(json.dumps({"run_id": OTHER_RUN, "permits": []}) + "\n",
                                     encoding="utf-8")
    res = run("scan", "--repo", str(stale))
    expect_clean_cli(res, 1, "permits of another run")
    check("stale" in payload(res)["new_anomalies"][0]["detail"].lower()
          and OTHER_RUN in payload(res)["new_anomalies"][0]["detail"],
          f"the stale run must be named: {payload(res)!r}")

    # A failing row in an existing gate record (completeness is judged by the record's own phase).
    gated = repo(tmp, "gate-record")
    logs = gated / ".code-factory" / "logs"
    logs.mkdir(parents=True)
    (logs / "gate-K.md").write_text(
        f"run_id: {RUN_ID}\n\n# Gate record — phase K\n\n"
        "| gate | exit | applicability | ran_at | command |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| run-id | 1 | applicable | 2026-11-03T00:00:00Z | run_id.py check |\n",
        encoding="utf-8")
    res = run("scan", "--repo", str(gated))
    expect_clean_cli(res, 1, "a failing gate record row")
    details = " ".join(entry["detail"] for entry in payload(res)["new_anomalies"])
    check("gate-K.md" in details and "run-id" in details,
          f"the failing row must be named: {details!r}")

    # A malformed action-gate journal row.
    journaled = repo(tmp, "journal")
    jlogs = journaled / ".code-factory" / "logs"
    jlogs.mkdir(parents=True)
    (jlogs / "action-gate.md").write_text(
        "# Action Gate Journal\n\n"
        "| timestamp | mode | class | decision | scope | action | reason |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| not | enough | cells |\n", encoding="utf-8")
    res = run("scan", "--repo", str(journaled))
    expect_clean_cli(res, 1, "a malformed action-gate journal row")
    check(payload(res)["new_anomalies"][0]["rule"] == "destructive-action-gate",
          f"the journal violation cites the action gate: {payload(res)!r}")


# --------------------------------------------------------------------------------------------
# Fail-closed: a stale run binding and a malformed state are input errors, never reused
# --------------------------------------------------------------------------------------------

def test_stale_and_malformed_state(tmp: pathlib.Path) -> None:
    root = repo(tmp, "stale")
    expect_clean_cli(run("launch", "--repo", str(root)), 0, "launch")
    # The pipeline moves to ANOTHER run: the state file is stale and everything refuses closed.
    (root / PIPELINE_REL).write_text(CHECKPOINT.format(run_id=OTHER_RUN), encoding="utf-8")
    for command in (("scan",), ("status",), ("launch",),
                    ("deny", "--rule", "retry-budgets", "--role", "coder", "--detail", "x")):
        res = run(*command, "--repo", str(root))
        expect_clean_cli(res, 2, f"{command[0]} over another run's state")
        check("stale" in res.stderr or "belongs to run" in res.stderr,
              f"{command[0]} must name the stale run binding: {res.stderr!r}")

    # A malformed state file is fail-closed for every reader (never a crash, never ignored).
    malformed = repo(tmp, "malformed")
    (malformed / STATE_REL).write_text("{ not json", encoding="utf-8")
    for command in (("scan",), ("status",)):
        res = run(*command, "--repo", str(malformed))
        expect_clean_cli(res, 2, f"{command[0]} over a malformed state")
        check("fail-closed" in res.stderr, f"{command[0]} must say fail-closed: {res.stderr!r}")
    # A well-JSON'd but ill-shaped state is rejected field by field.
    for index, bad in enumerate(({"run_id": "nonsense", "launch": None, "scans": 0,
                                  "anomalies": [], "denies": []},
                                 {"run_id": RUN_ID, "launch": None, "scans": -1,
                                  "anomalies": [], "denies": []},
                                 {"run_id": RUN_ID, "launch": None, "scans": 0,
                                  "anomalies": [{"rule": 1}], "denies": []},
                                 {"run_id": RUN_ID, "launch": None, "scans": 0, "anomalies": [],
                                  "denies": [{"rule": "r", "role": "coder", "detail": "d",
                                              "at": "t", "resolved": "yes"}]})):
        target = repo(tmp, f"ill-shaped-{index}")
        (target / STATE_REL).write_text(json.dumps(bad), encoding="utf-8")
        res = run("status", "--repo", str(target))
        expect_clean_cli(res, 2, f"an ill-shaped state ({index})")


# --------------------------------------------------------------------------------------------
# The single-owner launch
# --------------------------------------------------------------------------------------------

def test_status_fails_closed_without_a_launch(tmp: pathlib.Path) -> None:
    """(review R1, major) `status` is the `watchdog-deny` gate row: no launch recorded = FAIL.

    gate_all.py runs `status` at phases K and Y and passes the phase only on exit 0, so a run whose
    watchdog was never launched used to pass the gate that exists to prove the run was supervised.
    Both the no-state and the unlaunched-state cases must exit non-zero, name the fix, and stay a
    message (never a traceback, never a crash).
    """
    no_state = repo(tmp, "no-state")
    res = run("status", "--repo", str(no_state))
    expect_clean_cli(res, 1, "status without any state file")
    report = payload(res)
    check(report["status"] == "unlaunched" and report["launched"] is False,
          f"the report must say unlaunched: {report!r}")
    check("never launched" in res.stderr and "launch" in res.stderr,
          f"the refusal must name the fix: {res.stderr!r}")
    check("FAIL" in res.stderr, f"the gate row must read as a failure: {res.stderr!r}")

    # A state file that exists but records NO launch is the same fail-closed case.
    unlaunched = repo(tmp, "unlaunched")
    (unlaunched / STATE_REL).write_text(json.dumps(
        {"run_id": RUN_ID, "launch": None, "scans": 0, "anomalies": [], "denies": []}),
        encoding="utf-8")
    res = run("status", "--repo", str(unlaunched))
    expect_clean_cli(res, 1, "status with an unlaunched state")
    report = payload(res)
    check(report["status"] == "unlaunched" and report["run_id"] == RUN_ID,
          f"the report must name the run: {report!r}")
    check("records no launch" in res.stderr,
          f"the refusal must say the run recorded no launch: {res.stderr!r}")

    # …and the launch clears it: the same row passes once the watchdog was started.
    expect_clean_cli(run("launch", "--repo", str(unlaunched)), 0, "launch")
    expect_clean_cli(run("status", "--repo", str(unlaunched)), 0, "status after the launch")


def test_single_launch(tmp: pathlib.Path) -> None:
    root = repo(tmp, "launch")
    res = run("launch", "--repo", str(root))
    expect_clean_cli(res, 0, "launch")
    report = payload(res)
    check(report["status"] == "launched" and report["launch"]["authority"] == "run",
          f"the watchdog is launched under the run's own authority: {report!r}")
    res = run("launch", "--repo", str(root))
    expect_clean_cli(res, 2, "a second launch")
    check("ONE watchdog per run" in res.stderr,
          f"the single-owner rule must be stated: {res.stderr!r}")
    check(state_of(root)["launch"] is not None, "a refused launch must not touch the state")
    res = run("status", "--repo", str(root))
    expect_clean_cli(res, 0, "status after a clean launch")
    check(payload(res)["launched"] is True and payload(res)["status"] == "ok",
          f"status reports the launch: {payload(res)!r}")


# --------------------------------------------------------------------------------------------
# A deny blocks the phase gates; resolve unblocks with evidence; the routing names role + rule
# --------------------------------------------------------------------------------------------

def test_deny_blocks_and_routes(tmp: pathlib.Path) -> None:
    root = repo(tmp, "deny")
    expect_clean_cli(run("launch", "--repo", str(root)), 0, "launch")
    res = run("deny", "--repo", str(root), "--rule", "retry-budgets", "--role", "coder",
              "--detail", "coder retried past its budget: route the correction to the coder")
    expect_clean_cli(res, 0, "deny")
    record = payload(res)["deny"]
    check(record["rule"] == "retry-budgets" and record["role"] == "coder"
          and record["resolved"] is None,
          f"the deny names the rulebook citation and the violating role: {record!r}")

    # While the deny is unresolved: status blocks (exit 1) and names role + rule.
    res = run("status", "--repo", str(root))
    expect_clean_cli(res, 1, "status while a deny is unresolved")
    report = payload(res)
    check(report["status"] == "blocked" and len(report["unresolved_denies"]) == 1,
          f"the run is blocked: {report!r}")
    deny = report["unresolved_denies"][0]
    check(deny["rule"] == "retry-budgets" and deny["role"] == "coder" and deny["detail"],
          f"the correction routing names the role and the rule: {deny!r}")
    # …and a scan reports the block as well.
    res = run("scan", "--repo", str(root))
    expect_clean_cli(res, 1, "a scan while a deny is unresolved")
    check(payload(res)["status"] == "blocked", f"the scan sees the block: {payload(res)!r}")

    # The blocking deny fails gate_all phase K (wired as the watchdog-deny gate row).
    gate = pathlib.Path(__file__).with_name("gate_all.py")
    res = subprocess.run([sys.executable, str(gate), "--repo", str(root), "--phase", "K"],
                         capture_output=True, text=True, errors="replace")
    check(res.returncode != 0 and "watchdog-deny" in res.stdout,
          f"phase K must fail on the watchdog-deny row while a deny is unresolved: "
          f"{res.returncode} {res.stdout!r} {res.stderr!r}")
    record_text = (root / ".code-factory" / "logs" / "gate-K.md").read_text(encoding="utf-8")
    row = next(line for line in record_text.splitlines() if line.startswith("| watchdog-deny "))
    check("| 1 |" in row, f"the watchdog-deny row records the failure: {row!r}")

    # Resolving needs the matching rule and role, and evidence; then the run unblocks.
    res = run("resolve", "--repo", str(root), "--rule", "retry-budgets", "--role", "tester",
              "--evidence", "fixed")
    expect_clean_cli(res, 2, "resolving a deny of another role")
    res = run("resolve", "--repo", str(root), "--rule", "retry-budgets", "--role", "coder",
              "--evidence", "  ")
    expect_clean_cli(res, 2, "resolving without evidence")
    res = run("resolve", "--repo", str(root), "--rule", "retry-budgets", "--role", "coder",
              "--evidence", "coder counter corrected and re-audited green")
    expect_clean_cli(res, 0, "resolve")
    check(payload(res)["resolved"] == 1, f"exactly one deny is resolved: {payload(res)!r}")
    res = run("status", "--repo", str(root))
    expect_clean_cli(res, 0, "status after the resolution")
    resolved = state_of(root)["denies"][0]["resolved"]
    check(resolved and "re-audited" in resolved["evidence"],
          f"the resolution keeps its evidence: {resolved!r}")

    # The deny/resolve inputs are validated at the boundary.
    res = run("deny", "--repo", str(root), "--rule", "not a rule!", "--role", "coder",
              "--detail", "x")
    expect_clean_cli(res, 2, "a malformed rule id")
    res = run("deny", "--repo", str(root), "--rule", "retry-budgets", "--role", "wizard",
              "--detail", "x")
    expect_clean_cli(res, 2, "an unknown role")
    res = run("deny", "--repo", str(root), "--rule", "retry-budgets", "--role", "coder",
              "--detail", " " * 5000)
    expect_clean_cli(res, 2, "an oversized/empty detail")


# --------------------------------------------------------------------------------------------
# The argparse contract
# --------------------------------------------------------------------------------------------

def test_cli_contract(tmp: pathlib.Path) -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("launch", "scan", "deny", "resolve", "status", "begin", "observe", "activate",
                 "complete", "abandon"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("scan"), 2, "scan without --repo")
    expect_clean_cli(run("deny", "--repo", "."), 2, "deny without --rule/--role/--detail")
    expect_clean_cli(run("begin"), 2, "begin without --launch-dir")
    expect_clean_cli(run("observe", "--launch-dir", ".", "--event", "parse"), 2,
                     "observe without --seq")
    expect_clean_cli(run("activate", "--launch-dir", "."), 2, "activate without --repo")
    expect_clean_cli(run("complete"), 2, "complete without --launch-dir")
    expect_clean_cli(run("abandon", "--launch-dir", "."), 2, "abandon without --reason")
    expect_clean_cli(run("scan", "--repo", str(tmp / "nope")), 2, "an unusable --repo")
    # A repository with no checkpoint at all is an actionable input error, never a traceback.
    bare = tmp / "bare"
    bare.mkdir()
    res = run("scan", "--repo", str(bare))
    expect_clean_cli(res, 2, "scan without a checkpoint")
    check("run_id" in res.stderr, f"the missing run binding must be named: {res.stderr!r}")
    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


# --------------------------------------------------------------------------------------------
# The BOOTSTRAP: the supervisor begins BEFORE Phase 0 and observes every Phase 0 operation
# --------------------------------------------------------------------------------------------
# The launch-scoped bootstrap directory; a KEYED bootstrap is `watchdog-bootstrap-<launch_id>.json`
# and the unkeyed `watchdog-bootstrap.json` is the LEGACY (pre-defect-C) shape, still resumable.
BOOT_DIR_REL = pathlib.Path(".code-factory") / "state"
BOOT_REL = BOOT_DIR_REL / "watchdog-bootstrap.json"
# The CLOSED Phase 0 vocabulary: an event outside it is not an observation of a Phase 0 operation.
PHASE0_VOCABULARY = ("parse", "resolve", "memory-read", "memory-write", "run-id")
# The operations that must be observed BEFORE the bootstrap can bind to a run, IN THIS ORDER:
# the supervisor that begins first watches the parse, the repo resolution, the memory read and the
# run id that follows them. The old order parsed first and watched nothing (mistakes.txt item 1).
PHASE0_REQUIRED = ("parse", "resolve", "memory-read", "run-id")


def phase0_dir(tmp: pathlib.Path, name: str) -> pathlib.Path:
    root = tmp / name
    root.mkdir()
    return root


def boot_path(launch: pathlib.Path, launch_id: str) -> pathlib.Path:
    return launch / BOOT_DIR_REL / f"watchdog-bootstrap-{launch_id}.json"


def bootstraps_of(launch: pathlib.Path) -> list[pathlib.Path]:
    """Every bootstrap file of the launch directory, keyed ones and the legacy unkeyed one."""
    return sorted((launch / BOOT_DIR_REL).glob("watchdog-bootstrap*.json"))


def begin(launch: pathlib.Path) -> str:
    """`begin` and the launch nonce it mints — the key every later operation is addressed by."""
    res = run("begin", "--launch-dir", str(launch))
    expect_clean_cli(res, 0, "begin")
    launch_id = payload(res).get("launch_id")
    check(isinstance(launch_id, str) and LAUNCH_ID_RE.fullmatch(launch_id),
          f"`begin` must mint a launch nonce (^\\d{{8}}-\\d{{6}}-[0-9a-f]{{6}}$), got "
          f"{launch_id!r}")
    check(boot_path(launch, launch_id).is_file(),
          f"the bootstrap is written under the launch id it reported: {bootstraps_of(launch)!r}")
    return launch_id


def observe(launch: pathlib.Path, seq: int, event: str, detail: str = "phase 0",
            launch_id: str | None = None) -> subprocess.CompletedProcess[str]:
    args = ["observe", "--launch-dir", str(launch), "--event", event, "--seq", str(seq),
            "--detail", detail]
    if launch_id is not None:
        args += ["--launch-id", launch_id]
    return run(*args)


def bootstrap_of(launch: pathlib.Path, launch_id: str | None = None) -> dict:
    """A bootstrap record: the keyed one asked for, else the launch's ONE uncompleted bootstrap."""
    if launch_id is not None:
        path = boot_path(launch, launch_id)
        check(path.is_file(),
              f"the bootstrap keyed {launch_id} must exist: {bootstraps_of(launch)!r}")
        return json.loads(path.read_text(encoding="utf-8"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in bootstraps_of(launch)]
    uncompleted = [record for record in records if record.get("completed") is None]
    if len(uncompleted) == 1:
        return uncompleted[0]
    check(len(records) == 1,
          f"expected ONE uncompleted bootstrap in the launch directory, got "
          f"{[path.name for path in bootstraps_of(launch)]!r}")
    return records[0]


def test_bootstrap_precedes_phase0(tmp: pathlib.Path) -> None:
    """(mistakes.txt 1) The supervisor watches Phase 0, so it must exist BEFORE Phase 0 runs.

    The defect this pins: the flow parsed the task, resolved `repo_path`, read the memory and only
    THEN computed the run_id and launched the supervisor — whose launch itself REQUIRED that
    run_id — so the required order was impossible and the whole of Phase 0 went unwatched. The
    contract: `begin --launch-dir` needs nothing but the launch directory, `observe` records each
    Phase 0 event under a strictly increasing sequence, and `activate --launch-dir --repo` binds the
    bootstrap to the run's state once the run_id exists.
    """
    target = repo(tmp, "bootstrap")                       # the resolved repository, WITH a run_id
    launch = phase0_dir(tmp, "bootstrap-launch")

    # An unusable launch directory is an actionable input error, never a traceback.
    expect_clean_cli(run("begin", "--launch-dir", str(tmp / "no-such-launch")), 2,
                     "begin on a missing launch directory")
    # The OLD order is refused at once: an event nobody began to watch is not an observation.
    res = observe(launch, 0, "parse")
    expect_clean_cli(res, 2, "observing before the supervisor began")
    check("begin" in res.stderr and "Phase 0" in res.stderr,
          f"the refusal must name the begin the flow skipped: {res.stderr!r}")

    # `begin` is run-id INDEPENDENT (launch-scoped) and mints the KEY of this supervision.
    launch_id = begin(launch)
    data = bootstrap_of(launch, launch_id)
    check(data["run_id"] is None and data["events"] == [] and data["activated"] is None
          and isinstance(data["begun_at"], str) and data["begun_at"],
          f"the launch-scoped bootstrap state is run_id-free: {data!r}")
    # (defect C, owner-approved inversion) A second `begin` from the SAME directory is not refused:
    # it starts a NEW keyed bootstrap, so two factories launched from one folder into DIFFERENT
    # repositories never share a mutable file. The old single-occupancy pin is deliberately gone.
    res = run("begin", "--launch-dir", str(launch))
    expect_clean_cli(res, 0, "a second begin in the same launch directory")
    other_id = payload(res).get("launch_id")
    check(isinstance(other_id, str) and LAUNCH_ID_RE.fullmatch(other_id) and other_id != launch_id,
          f"a second begin mints its OWN launch id: {payload(res)!r}")
    check(boot_path(launch, other_id).is_file(),
          f"each bootstrap has its own keyed file: {[p.name for p in bootstraps_of(launch)]!r}")

    # The vocabulary is CLOSED: only the Phase 0 operations are observable events.
    res = observe(launch, 0, "extract", launch_id=launch_id)
    expect_clean_cli(res, 2, "an event outside the Phase 0 vocabulary")
    for event in PHASE0_VOCABULARY:
        check(event in res.stderr, f"the refusal must list the closed vocabulary, missing "
                                   f"{event!r}: {res.stderr!r}")
    # The sequence is a non-negative integer, strictly increasing: zero is legitimate, a duplicate
    # and a regression are not (two events may not share a place in the order).
    expect_clean_cli(observe(launch, -1, "parse", launch_id=launch_id), 2, "a negative sequence")
    expect_clean_cli(observe(launch, 0, "parse", launch_id=launch_id), 0,
                     "the first observation of Phase 0")
    check(payload(observe(launch, 1, "resolve", launch_id=launch_id))["status"] == "observed",
          "the second observation is recorded")
    expect_clean_cli(observe(launch, 1, "memory-read", launch_id=launch_id), 2,
                     "a duplicate sequence")
    expect_clean_cli(observe(launch, 0, "memory-read", launch_id=launch_id), 2,
                     "a regressing sequence")
    journal = [entry["event"] for entry in bootstrap_of(launch, launch_id)["events"]]
    check(journal == ["parse", "resolve"],
          f"the accepted observations keep their order: {journal!r}")
    # Only the addressed bootstrap is written: the sibling run's journal stays empty.
    check(bootstrap_of(launch, other_id)["events"] == [],
          f"an observation lands in the bootstrap it was addressed to: "
          f"{bootstrap_of(launch, other_id)!r}")

    # Activation FAILS CLOSED while a mandated operation went unobserved (the old order).
    res = run("activate", "--launch-dir", str(launch), "--repo", str(target),
              "--launch-id", launch_id)
    expect_clean_cli(res, 1, "activating with Phase 0 operations unobserved")
    for missing in ("memory-read", "run-id"):
        check(missing in res.stderr, f"the refusal must name the unobserved {missing}: "
                                     f"{res.stderr!r}")
    check(not (target / STATE_REL).exists(),
          "a refused activation must not write the run-bound state")

    # Observing the rest, in order, then activating: the state BINDS to the run atomically.
    expect_clean_cli(observe(launch, 2, "memory-read", launch_id=launch_id), 0,
                     "observing the memory read")
    expect_clean_cli(observe(launch, 3, "run-id", launch_id=launch_id), 0,
                     "observing the run id")
    res = run("activate", "--launch-dir", str(launch), "--repo", str(target),
              "--launch-id", launch_id)
    expect_clean_cli(res, 0, "activate")
    report = payload(res)
    check(report["status"] == "activated" and report["run_id"] == RUN_ID
          and report["events"] == len(PHASE0_REQUIRED),
          f"activation binds the bootstrap to the run of the resolved repository: {report!r}")
    bound = state_of(target)
    check(bound["run_id"] == RUN_ID and bound["scans"] == 0 and bound["anomalies"] == []
          and bound["denies"] == [],
          f"the run-bound state starts clean and run-bound: {bound!r}")
    check(bound["launch"] is not None and bound["launch"]["authority"] == "run"
          and bound["launch"]["at"] == bootstrap_of(launch, launch_id)["begun_at"],
          f"the bound launch keeps the bootstrap's OWN launch time (never a later stand-in): "
          f"{bound!r}")
    check([entry["event"] for entry in bound["events"]] == list(PHASE0_REQUIRED),
          f"the run-bound state carries the ordered Phase 0 observations: {bound!r}")
    activated = bootstrap_of(launch, launch_id)
    check(activated["run_id"] == RUN_ID and activated["activated"] is not None,
          f"the launch-scoped bootstrap records the binding it performed: {activated!r}")
    check(sorted(p.name for p in (target / STATE_REL).parent.glob("*.tmp")) == [],
          "the binding is atomic: no temporary file survives it")
    # The phase gate sees a supervised run.
    res = run("status", "--repo", str(target))
    expect_clean_cli(res, 0, "status after activation")
    check(payload(res)["launched"] is True and payload(res)["status"] == "ok",
          f"status reports the launched, clean run: {payload(res)!r}")
    # Activation happens ONCE: a second one would re-bind and could rewrite history.
    res = run("activate", "--launch-dir", str(launch), "--repo", str(target),
              "--launch-id", launch_id)
    expect_clean_cli(res, 2, "a second activation")

    # The memory WRITE is observed by the same supervisor, now against the run's own state.
    res = observe(launch, 4, "memory-write", "the run's finish record", launch_id=launch_id)
    expect_clean_cli(res, 0, "observing the memory write after activation")
    check(state_of(target)["events"][-1]["event"] == "memory-write",
          f"the post-activation observation lands in the run-bound state: {state_of(target)!r}")


def test_old_order_cannot_activate(tmp: pathlib.Path) -> None:
    """The OLD order — parse/resolve/memory/run_id before the supervisor — can never pass.

    Two shapes of the same defect are refused fail-closed (exit 1, the gate's own verdict, never a
    silent success): an operation that was never observed at all, and the mandated operations
    observed in the WRONG order (the run_id "observed" before the parse is a record written after
    the fact, which is exactly what the fix exists to stop).
    """
    # (a) No observation at all: the parse happened and nothing watched it.
    target = repo(tmp, "old-order")
    launch = phase0_dir(tmp, "old-order-launch")
    expect_clean_cli(run("begin", "--launch-dir", str(launch)), 0, "begin")
    res = run("activate", "--launch-dir", str(launch), "--repo", str(target))
    expect_clean_cli(res, 1, "activating with nothing observed")
    for missing in PHASE0_REQUIRED:
        check(missing in res.stderr, f"the refusal must name the unobserved {missing}: "
                                     f"{res.stderr!r}")
    check(not (target / STATE_REL).exists(),
          "the old order never produces a run-bound watchdog state")

    # (b) The mandated operations observed OUT OF ORDER.
    wrong = phase0_dir(tmp, "wrong-order-launch")
    expect_clean_cli(run("begin", "--launch-dir", str(wrong)), 0, "begin")
    for seq, event in enumerate(("resolve", "parse", "memory-read", "run-id")):
        expect_clean_cli(observe(wrong, seq, event), 0, f"observing {event}")
    res = run("activate", "--launch-dir", str(wrong), "--repo", str(target))
    expect_clean_cli(res, 1, "activating on an out-of-order journal")
    check("order" in res.stderr.lower() and "parse" in res.stderr,
          f"the refusal must state the violated order: {res.stderr!r}")
    check(not (target / STATE_REL).exists(),
          "an out-of-order journal never produces a run-bound watchdog state")

    # (c) A run-bound state of ANOTHER run is never overwritten by an activation.
    other = repo(tmp, "old-order-other", CHECKPOINT.format(run_id=OTHER_RUN))
    stale_launch = phase0_dir(tmp, "stale-launch")
    expect_clean_cli(run("begin", "--launch-dir", str(stale_launch)), 0, "begin")
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(stale_launch, seq, event), 0, f"observing {event}")
    (other / STATE_REL).write_text(json.dumps(
        {"run_id": RUN_ID, "launch": None, "scans": 0, "anomalies": [], "denies": []}),
        encoding="utf-8")
    res = run("activate", "--launch-dir", str(stale_launch), "--repo", str(other))
    expect_clean_cli(res, 2, "activating over another run's watchdog state")
    check("archive" in res.stderr or "belongs to run" in res.stderr,
          f"the refusal must name the stale binding: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# `plan_rejections` is a MANDATED counter, not an unknown role and not a budgeted one
# --------------------------------------------------------------------------------------------

def test_plan_rejections_is_a_counter_not_a_role(tmp: pathlib.Path) -> None:
    """(review R1, major) The flow MANDATES `retry_counters.plan_rejections`.

    The flow and `references/planning-guide.md` tell the orchestrator to count every plan rejection
    in `retry_counters.plan_rejections`, so the scan must accept it — it used to be reported as
    "role 'plan_rejections' has no retry budget", i.e. a false positive on the run's own mandated
    record. It stays a NON-role counter: it carries no retry budget (any tally is legitimate, the
    committee rule is judged elsewhere) and it is never a valid `--role` for a deny.
    """
    for tally in (0, 1, 2, 7):
        counted = repo(tmp, f"plan-rejections-{tally}",
                       CHECKPOINT.format(run_id=RUN_ID).replace(
                           "  reviewer: 0", f"  reviewer: 0\n  plan_rejections: {tally}"))
        res = run("scan", "--repo", str(counted))
        expect_clean_cli(res, 0, f"a checkpoint counting {tally} plan rejection(s)")
        report = payload(res)
        check(report["new_anomalies"] == [],
              f"retry_counters.plan_rejections is a MANDATED counter, not an unknown role: "
              f"{report!r}")
    # It is a counter, never a role: no deny is routed to it.
    counted = repo(tmp, "plan-rejections-role",
                   CHECKPOINT.format(run_id=RUN_ID).replace(
                       "  reviewer: 0", "  reviewer: 0\n  plan_rejections: 1"))
    res = run("deny", "--repo", str(counted), "--rule", "plan-rejections", "--role",
              "plan_rejections", "--detail", "x")
    expect_clean_cli(res, 2, "a deny routed to the plan_rejections counter")
    # …while a role with neither a budget nor a mandate is still an anomaly.
    wizard = repo(tmp, "plan-rejections-wizard",
                  CHECKPOINT.format(run_id=RUN_ID).replace(
                      "  reviewer: 0", "  reviewer: 0\n  wizard: 1"))
    res = run("scan", "--repo", str(wizard))
    expect_clean_cli(res, 1, "an unknown counter role")
    check("wizard" in payload(res)["new_anomalies"][0]["detail"],
          f"the unknown role is still named: {payload(res)!r}")


# --------------------------------------------------------------------------------------------
# The coder counter is validated against the SAME plan-derived ceiling as the gate
# --------------------------------------------------------------------------------------------

PLAN = """\
# Plan

**Tasks (DAG)**

- T1: build the parser; role: coder; files: src/a.py; deps: []; verification: pytest
- T2: wire the parser; role: coder; files: src/b.py; deps: [T1]; verification: pytest
- T3: cover the parser; role: coder; files: tests/test_a.py; deps: [T1]; verification: pytest
- T4: review the wiring; role: reviewer; files: ; deps: [T2]; verification: pytest
"""


def test_plan_derived_coder_ceiling(tmp: pathlib.Path) -> None:
    """The coder's ceiling is ONE delegation per distinct coder plan task plus one retry reserve.

    The scan used to compare the raw base table (`coder: 1`) against the counter, so a legitimate
    approved multi-task plan — T16 lets the gate count one coder delegation per plan task — was
    false-flagged from the second coder task on. The scan now uses `delegation_gate.budget_for`,
    i.e. the SAME ceiling the gate enforces, so the watchdog and the gate can never disagree.
    """
    for counted in (1, 2, 3, 4):
        root = repo(tmp, f"plan-coder-{counted}",
                    CHECKPOINT.format(run_id=RUN_ID).replace(
                        "  coder: 0", f"  coder: {counted}"))
        (root / ".code-factory" / "state" / "plan.md").write_text(PLAN, encoding="utf-8")
        res = run("scan", "--repo", str(root))
        expect_clean_cli(res, 0, f"a coder counter of {counted} within a 3-task plan's 4")
        check(payload(res)["new_anomalies"] == [],
              f"3 coder plan tasks + 1 retry reserve allows 4 coder delegations, so a counter of "
              f"{counted} is legitimate: {payload(res)!r}")
    # One above the derived ceiling is STILL an anomaly, and the message names the real budget.
    over = repo(tmp, "plan-coder-over",
                CHECKPOINT.format(run_id=RUN_ID).replace("  coder: 0", "  coder: 5"))
    (over / ".code-factory" / "state" / "plan.md").write_text(PLAN, encoding="utf-8")
    res = run("scan", "--repo", str(over))
    expect_clean_cli(res, 1, "a coder counter above the plan-derived ceiling")
    detail = payload(res)["new_anomalies"][0]["detail"]
    check("coder" in detail and "4" in detail,
          f"the anomaly names the derived budget, not the raw table: {payload(res)!r}")
    # The ceiling belongs to the coder ONLY: the same plan never widens the reviewer's budget.
    reviewer = repo(tmp, "plan-reviewer-over",
                    CHECKPOINT.format(run_id=RUN_ID).replace("  reviewer: 0", "  reviewer: 3"))
    (reviewer / ".code-factory" / "state" / "plan.md").write_text(PLAN, encoding="utf-8")
    res = run("scan", "--repo", str(reviewer))
    expect_clean_cli(res, 1, "a reviewer counter above its fixed budget")
    check(payload(res)["new_anomalies"][0]["detail"].count("2"),
          f"the reviewer keeps its fixed budget of 2: {payload(res)!r}")
    # No approved plan, an unreadable one and a prose-only coder mention leave the base budget 1.
    prose = """\
# Plan

The coder will implement everything; a coder task is expected.

- T1: plan only; role: planner; files: ; deps: []; verification: none
"""
    for label, plan in (("no-plan", None), ("prose-plan", prose)):
        root = repo(tmp, f"plan-base-{label}",
                    CHECKPOINT.format(run_id=RUN_ID).replace("  coder: 0", "  coder: 2"))
        if plan is not None:
            (root / ".code-factory" / "state" / "plan.md").write_text(plan, encoding="utf-8")
        res = run("scan", "--repo", str(root))
        expect_clean_cli(res, 1, f"a coder counter of 2 with {label}")
        check("coder" in payload(res)["new_anomalies"][0]["detail"],
              f"{label}: the coder counter is still judged against the base budget: "
              f"{payload(res)!r}")


def test_sequential_runs(tmp: pathlib.Path) -> None:
    """(review R1/R2, defect C) A COMPLETED keyed bootstrap never blocks the next independent run.

    `begin` refused whenever a bootstrap file existed, so the second run launched from the same
    directory could never start its own supervisor: the first run's completed record looked like an
    unfinished one. Under the keyed lifecycle (owner-approved inversion) each run OWNS its bootstrap
    file, so a completed record is an IMMUTABLE history entry of the launch directory — it is never
    rewritten and no longer carried into the next bootstrap's `history` (that carry-over is obsolete
    for keyed files; the field stays for legacy validation). The lifecycle stays INTEGRATED with the
    Finish: the supervisor observes the finish memory write, the run's checkpoint reaches
    `status: ok`, and only then `complete --launch-id` closes that binding — a completion while the
    run is still `in_progress` is refused.
    """
    first = repo(tmp, "sequential-first")
    second = repo(tmp, "sequential-second", CHECKPOINT.format(run_id=OTHER_RUN))
    launch = phase0_dir(tmp, "sequential-launch")

    first_id = begin(launch)
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(launch, seq, event, launch_id=first_id), 0,
                         f"observe {event} of run 1")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(first),
                         "--launch-id", first_id), 0, "activate run 1")
    # The run's finish memory write is still observed by the SAME supervisor, against the run.
    expect_clean_cli(observe(launch, len(PHASE0_REQUIRED), "memory-write",
                             "the run's finish record", launch_id=first_id),
                     0, "observe the finish memory write of run 1")
    first_state = (first / STATE_REL).read_text(encoding="utf-8")
    first_begun = bootstrap_of(launch, first_id)["begun_at"]

    # A bootstrap that was never activated has no completed run to record.
    unbound = phase0_dir(tmp, "sequential-unbound")
    unbound_id = begin(unbound)
    expect_clean_cli(run("complete", "--launch-dir", str(unbound), "--launch-id", unbound_id), 2,
                     "completing an unactivated bootstrap")

    # The completion belongs to the FINISH (review R2): while the run's own checkpoint is still in
    # progress the flow has not reached the Finish, so completing would free the launch directory
    # mid-run and let a second supervisor interleave with the first. Fail closed.
    res = run("complete", "--launch-dir", str(launch), "--launch-id", first_id)
    expect_clean_cli(res, 2, "completing a run whose checkpoint is still in progress")
    lowered = res.stderr.lower()
    check(any(word in lowered for word in ("finish", "in_progress", "in progress", "status")),
          f"the refusal must name the unfinished checkpoint: {res.stderr!r}")
    check(bootstrap_of(launch, first_id).get("completed") is None,
          "a refused completion must not record one")

    # The Finish checkpoint lands, then ONE explicit completion, bound to the run it supervised.
    finish_checkpoint(first)
    res = run("complete", "--launch-dir", str(launch), "--launch-id", first_id)
    expect_clean_cli(res, 0, "complete run 1 at its Finish")
    completed = bootstrap_of(launch, first_id).get("completed")
    check(isinstance(completed, dict) and completed.get("run_id") == RUN_ID
          and isinstance(completed.get("at"), str) and completed["at"],
          f"the completion is bound to the run it supervised: {bootstrap_of(launch, first_id)!r}")
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", first_id), 2,
                     "a second completion")
    check((first / STATE_REL).read_text(encoding="utf-8") == first_state,
          "completing the bootstrap must not rewrite the finished run's watchdog state")
    first_record = boot_path(launch, first_id).read_text(encoding="utf-8")

    # Run 2 starts in the SAME launch directory: a fresh, independent, KEYED bootstrap.
    second_id = begin(launch)
    check(second_id != first_id and boot_path(launch, second_id).is_file(),
          f"the next run gets its own bootstrap file: {[p.name for p in bootstraps_of(launch)]!r}")
    fresh = bootstrap_of(launch, second_id)
    check(fresh.get("run_id") is None and fresh.get("activated") is None
          and fresh.get("events") == [] and fresh.get("completed") is None
          and fresh.get("begun_at") != first_begun,
          f"the next run starts from an empty bootstrap: {fresh!r}")
    check(not (fresh.get("history") or []),
          f"a keyed bootstrap carries no cross-run history (the completed record IS the history): "
          f"{fresh!r}")
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(launch, seq, event, launch_id=second_id), 0,
                         f"observe {event} of run 2")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(second),
                         "--launch-id", second_id), 0, "activate run 2")
    check(state_of(second)["run_id"] == OTHER_RUN and state_of(second)["launch"] is not None,
          f"run 2 binds its own watchdog state: {state_of(second)!r}")
    check((first / STATE_REL).read_text(encoding="utf-8") == first_state,
          "run 1's watchdog history survives run 2 untouched")
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", second_id), 2,
                     "completing run 2 before its Finish")
    finish_checkpoint(second)
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", second_id), 0,
                     "complete run 2 at its Finish")
    check(bootstrap_of(launch, second_id)["completed"]["run_id"] == OTHER_RUN,
          f"the second completion names the second run: {bootstrap_of(launch, second_id)!r}")
    # Run 1's completed record is history: untouched by every later operation.
    check(boot_path(launch, first_id).read_text(encoding="utf-8") == first_record,
          "the completed record of run 1 is immutable")
    check(bootstrap_of(launch, first_id)["completed"]["run_id"] == RUN_ID,
          f"run 1's completion still names run 1: {bootstrap_of(launch, first_id)!r}")


def test_unactivated_bootstrap_abandonment(tmp: pathlib.Path) -> None:
    """(R1, major) A bootstrap that FAILED before it bound a run is abandoned EXPLICITLY.

    A run whose Phase 0 failed (an unparsable task, a refused activation) leaves a begun bootstrap
    behind: `complete` has no bound run to close, so the launch directory would keep an uncompleted
    bootstrap forever. `abandon --reason` supplies the honest transition for an UNACTIVATED
    bootstrap only — the reason lands on the record, which under the keyed lifecycle is IMMUTABLE
    history (the reason is read from that very file, not from a carried-over `history` list) —
    while an ACTIVATED bootstrap is the run in progress and stays protected by `complete`.
    """
    launch = phase0_dir(tmp, "abandon-failed")
    expect_clean_cli(run("abandon", "--launch-dir", str(launch), "--reason", "x"), 2,
                     "abandoning a bootstrap nobody began")
    failed_id = begin(launch)
    expect_clean_cli(observe(launch, 0, "parse", "the parse failed", launch_id=failed_id), 0,
                     "observe the failed parse")
    expect_clean_cli(run("abandon", "--launch-dir", str(launch), "--launch-id", failed_id), 2,
                     "abandon without a reason")
    res = run("abandon", "--launch-dir", str(launch), "--launch-id", failed_id, "--reason", "   ")
    expect_clean_cli(res, 2, "abandon with an empty reason")
    res = run("abandon", "--launch-dir", str(launch), "--launch-id", failed_id,
              "--reason", "the task could not be parsed, so Phase 0 never bound a run")
    expect_clean_cli(res, 0, "abandoning an unactivated failed bootstrap")
    report = payload(res)
    check(report.get("status") == "abandoned" and report.get("run_id") is None,
          f"the abandonment records that no run was bound: {report!r}")
    record = bootstrap_of(launch, failed_id).get("completed") or {}
    check(record.get("abandoned") is True and record.get("run_id") is None
          and "could not be parsed" in str(record.get("reason")),
          f"the abandonment keeps its own reason on the record: {record!r}")
    expect_clean_cli(run("abandon", "--launch-dir", str(launch), "--launch-id", failed_id,
                         "--reason", "again"), 2, "a second abandonment")
    failed_record = boot_path(launch, failed_id).read_text(encoding="utf-8")
    # The failed bootstrap is closed history now: the next independent run may begin, and the
    # reason it was abandoned stays auditable in that immutable keyed record.
    fresh_id = begin(launch)
    check(fresh_id != failed_id, "the next run gets its own launch id")
    fresh = bootstrap_of(launch, fresh_id)
    check(fresh.get("completed") is None and fresh.get("events") == [],
          f"the next run starts fresh: {fresh!r}")
    check(not (fresh.get("history") or []),
          f"a keyed bootstrap carries no cross-run history: {fresh!r}")
    check(boot_path(launch, failed_id).read_text(encoding="utf-8") == failed_record,
          "the abandoned record is immutable")
    abandoned = bootstrap_of(launch, failed_id)["completed"]
    check(abandoned.get("abandoned") is True and "could not be parsed" in str(abandoned["reason"]),
          f"the abandonment stays auditable in its own keyed record: {abandoned!r}")

    # An ACTIVATED bootstrap is the run in progress: it is NEVER abandoned, and `complete` — the
    # end of a bound run — still refuses before its Finish.
    target = repo(tmp, "abandon-active")
    active = phase0_dir(tmp, "abandon-active-launch")
    active_id = begin(active)
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(active, seq, event, launch_id=active_id), 0,
                         f"observe {event} of the active run")
    expect_clean_cli(run("activate", "--launch-dir", str(active), "--repo", str(target),
                         "--launch-id", active_id), 0, "activate the active run")
    before = bootstrap_of(active, active_id)
    res = run("abandon", "--launch-dir", str(active), "--launch-id", active_id,
              "--reason", "the run looks stuck")
    expect_clean_cli(res, 2, "abandoning an ACTIVATED bootstrap")
    lowered = res.stderr.lower()
    check("complete" in lowered and "in progress" in lowered,
          f"the refusal must route the bound run to `complete`: {res.stderr!r}")
    check(bootstrap_of(active, active_id) == before,
          "a refused abandonment must not touch the activated bootstrap")
    expect_clean_cli(run("complete", "--launch-dir", str(active), "--launch-id", active_id), 2,
                     "completing the active run before its Finish")


def test_observe_detail_bound(tmp: pathlib.Path) -> None:
    """(R1, major) The observation note is bounded like every other routing note.

    `deny --detail` was bounded to 4000 characters while `observe --detail` was not, so a Phase 0
    observation could write an arbitrarily long text into the launch-scoped bootstrap. The bound is
    the documented one — an EMPTY note stays legitimate (most observations need none), 4000
    characters is accepted and 4001 is an input error that records nothing.
    """
    launch = phase0_dir(tmp, "detail-bound")
    expect_clean_cli(run("begin", "--launch-dir", str(launch)), 0, "begin (detail bound)")
    expect_clean_cli(run("observe", "--launch-dir", str(launch), "--event", "parse", "--seq", "0"),
                     0, "an observation with no --detail")
    expect_clean_cli(observe(launch, 1, "resolve", ""), 0, "an empty --detail")
    expect_clean_cli(observe(launch, 2, "memory-read", "d" * DETAIL_MAX), 0,
                     "a --detail exactly at the bound")
    res = run("observe", "--launch-dir", str(launch), "--event", "run-id", "--seq", "3",
              "--detail", "d" * (DETAIL_MAX + 1))
    expect_clean_cli(res, 2, "a --detail one character above the bound")
    check(str(DETAIL_MAX) in res.stderr,
          f"the refusal must name the {DETAIL_MAX}-character bound: {res.stderr!r}")
    events = bootstrap_of(launch)["events"]
    check([entry["event"] for entry in events] == ["parse", "resolve", "memory-read"],
          f"a refused observation records nothing: {events!r}")
    check(events[-1]["detail"] == "d" * DETAIL_MAX,
          f"the bounded note is stored as given: {events[-1]!r}")


def test_ambiguity_refuses(tmp: pathlib.Path) -> None:
    """(defect C) TWO uncompleted bootstraps in one directory are never a guess.

    Two factories launched from the SAME directory into DIFFERENT repositories each own a keyed
    bootstrap, so "the bootstrap of this run" is only knowable from the key. Without `--launch-id`
    every bootstrap operation is refused at once (exit 2, no traceback) naming every candidate id
    and the flag that disambiguates them; with the key the operation resolves to exactly that
    bootstrap. Once only ONE uncompleted bootstrap is left, the unkeyed call resolves to it again —
    ambiguity is the ONLY case where the launch directory refuses to resolve.
    """
    launch = phase0_dir(tmp, "ambiguous")
    target = repo(tmp, "ambiguous-repo")
    first_id = begin(launch)
    second_id = begin(launch)
    check(first_id != second_id, "two begins mint two different launch ids")

    for command in (("observe", "--launch-dir", str(launch), "--event", "parse", "--seq", "0"),
                    ("activate", "--launch-dir", str(launch), "--repo", str(target)),
                    ("complete", "--launch-dir", str(launch)),
                    ("abandon", "--launch-dir", str(launch), "--reason", "x")):
        res = run(*command)
        expect_clean_cli(res, 2, f"{command[0]} with two uncompleted bootstraps")
        check(first_id in res.stderr and second_id in res.stderr,
              f"{command[0]} must list EVERY candidate launch id: {res.stderr!r}")
        check("--launch-id" in res.stderr,
              f"{command[0]} must demand the flag that disambiguates the launch: {res.stderr!r}")
    check(bootstrap_of(launch, first_id)["events"] == []
          and bootstrap_of(launch, second_id)["events"] == [],
          "a refused ambiguous operation writes nothing")
    check(bootstraps_of(launch) and len(bootstraps_of(launch)) == 2,
          f"the refused operations created no third bootstrap: {bootstraps_of(launch)!r}")

    # The key resolves it, and only the addressed bootstrap records the observation.
    expect_clean_cli(observe(launch, 0, "parse", launch_id=second_id), 0,
                     "an observation keyed by --launch-id")
    check(bootstrap_of(launch, second_id)["events"][0]["event"] == "parse"
          and bootstrap_of(launch, first_id)["events"] == [],
          "the observation lands in the addressed bootstrap only")

    # Close the FIRST run completely; the second stays uncompleted, so an unkeyed call resolves to
    # it again (the ONE-uncompleted rule) and can be abandoned without a key.
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(launch, seq, event, launch_id=first_id), 0,
                         f"observe {event} of the first run")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(target),
                         "--launch-id", first_id), 0, "activate the first run")
    finish_checkpoint(target)
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", first_id), 0,
                     "complete the first run")
    expect_clean_cli(observe(launch, 1, "resolve"), 0,
                     "an unkeyed observation again resolves to the ONE uncompleted bootstrap")
    check(bootstrap_of(launch, second_id)["events"][-1]["event"] == "resolve",
          f"the unkeyed observation landed in the remaining bootstrap: "
          f"{bootstrap_of(launch, second_id)!r}")
    expect_clean_cli(run("abandon", "--launch-dir", str(launch),
                         "--reason", "the second run never bound a repository"), 0,
                     "abandon the remaining uncompleted bootstrap without a key")

    # Nothing is uncompleted now: an unkeyed call is the ORIGINAL "did not begin" error.
    res = observe(launch, 0, "parse")
    expect_clean_cli(res, 2, "observing with no uncompleted bootstrap left")
    check("begin" in res.stderr and "Phase 0" in res.stderr,
          f"the refusal must name the begin the flow skipped: {res.stderr!r}")


def test_legacy_bootstrap_resumes(tmp: pathlib.Path) -> None:
    """(defect C) An UNKEYED legacy bootstrap stays resumable and is never silently migrated.

    A run that was already in flight when the keyed lifecycle landed has no launch id: its
    `watchdog-bootstrap.json` is the legacy shape. It stays resolvable through the ONE-uncompleted
    rule — observed, activated and completed exactly as before — and the script neither renames it
    nor writes a keyed sibling, so a paused run resumes on the file it already has.
    """
    target = repo(tmp, "legacy")
    launch = phase0_dir(tmp, "legacy-launch")
    (launch / BOOT_DIR_REL).mkdir(parents=True)
    legacy = {"begun_at": "2026-11-03T20:00:00+00:00", "run_id": None, "events": [],
              "activated": None, "completed": None, "history": []}
    (launch / BOOT_REL).write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    # No key exists for it, so the unkeyed call must resolve it: one uncompleted bootstrap.
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(launch, seq, event), 0, f"observe {event} of the legacy run")
    check([entry["event"] for entry in bootstrap_of(launch)["events"]] == list(PHASE0_REQUIRED),
          f"the legacy journal records the ordered observations: {bootstrap_of(launch)!r}")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(target)), 0,
                     "activate the legacy bootstrap")
    bound = state_of(target)
    check(bound["run_id"] == RUN_ID and bound["launch"]["at"] == legacy["begun_at"],
          f"the legacy binding keeps its own launch time: {bound!r}")

    finish_checkpoint(target)
    expect_clean_cli(run("complete", "--launch-dir", str(launch)), 0,
                     "complete the legacy bootstrap at its Finish")
    check(bootstrap_of(launch)["completed"]["run_id"] == RUN_ID,
          f"the legacy completion names its run: {bootstrap_of(launch)!r}")
    check([path.name for path in bootstraps_of(launch)] == [BOOT_REL.name],
          f"a legacy bootstrap is resolved, never silently migrated: {bootstraps_of(launch)!r}")


def test_launch_id_validation(tmp: pathlib.Path) -> None:
    """(defect C, input boundary) `--launch-id` is a FILENAME COMPONENT, so it is validated.

    A key of the documented shape (`^\\d{8}-\\d{6}-[0-9a-f]{6}$`) resolves its bootstrap; anything
    else — empty, separators, traversal, the run_id shape, uppercase hex — has zero legitimacy as a
    filename component and is an exit-2 input error that writes nothing. A well-formed key that
    names no bootstrap is likewise an actionable error, never a silent fallback to "some" file.
    """
    target = repo(tmp, "launch-id")
    launch = phase0_dir(tmp, "launch-id-launch")
    known = begin(launch)
    # The positive control: the key of a real bootstrap resolves it.
    expect_clean_cli(observe(launch, 0, "parse", launch_id=known), 0,
                     "an observation keyed by its own launch id")
    for bad in ("", "x", "../escape", "20261103-8e939171", "20261103-123456-ABCDEF",
                "20261103-123456-abcdef/x", "20261103-123456-abcdef\\.."):
        for command in (("observe", "--launch-dir", str(launch), "--event", "resolve",
                         "--seq", "1"),
                        ("activate", "--launch-dir", str(launch), "--repo", str(target)),
                        ("complete", "--launch-dir", str(launch)),
                        ("abandon", "--launch-dir", str(launch), "--reason", "x")):
            res = run(*command, "--launch-id", bad)
            expect_clean_cli(res, 2, f"{command[0]} with --launch-id {bad!r}")

    # A well-formed key that names no bootstrap: named, exit 2, no fallback to the real one.
    missing = "20260101-000000-abcdef"
    for command in (("observe", "--launch-dir", str(launch), "--event", "resolve", "--seq", "1"),
                    ("complete", "--launch-dir", str(launch))):
        res = run(*command, "--launch-id", missing)
        expect_clean_cli(res, 2, f"{command[0]} with an unknown --launch-id")
        check(missing in res.stderr, f"the unknown key must be named: {res.stderr!r}")

    check([path.name for path in bootstraps_of(launch)] == [boot_path(launch, known).name],
          f"a rejected --launch-id creates no bootstrap file: {bootstraps_of(launch)!r}")
    journal = [entry["event"] for entry in bootstrap_of(launch, known)["events"]]
    check(journal == ["parse"], f"the accepted key keeps its one observation: {journal!r}")
    check(not (target / STATE_REL).exists(),
          "no rejected --launch-id wrote the run-bound state")


def test_concurrent_keyed_launches(tmp: pathlib.Path) -> None:
    """(defect C, business scenario) Two factories, ONE launch directory, two repositories.

    The point of the keyed lifecycle: interleaved lifecycles of two runs sharing a launch directory
    never touch a shared mutable file. Each `begin` mints its own key and file, each observation,
    activation and completion is addressed by that key, and each run binds and finishes its OWN
    repository. The old single-occupancy refusal made this scenario impossible from one folder.
    """
    first = repo(tmp, "concurrent-first")
    second = repo(tmp, "concurrent-second", CHECKPOINT.format(run_id=OTHER_RUN))
    launch = phase0_dir(tmp, "concurrent-launch")

    first_id = begin(launch)
    second_id = begin(launch)
    check(first_id != second_id, "the two runs have their own launch ids")
    # INTERLEAVED Phase 0: each observation is addressed by the key of the run it belongs to.
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_clean_cli(observe(launch, seq, event, launch_id=first_id), 0,
                         f"observe {event} of run 1")
        expect_clean_cli(observe(launch, seq, event, launch_id=second_id), 0,
                         f"observe {event} of run 2")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(first),
                         "--launch-id", first_id), 0, "activate run 1")
    expect_clean_cli(run("activate", "--launch-dir", str(launch), "--repo", str(second),
                         "--launch-id", second_id), 0, "activate run 2")

    first_boot = bootstrap_of(launch, first_id)
    second_boot = bootstrap_of(launch, second_id)
    check(first_boot["activated"]["repo"] == str(first)
          and second_boot["activated"]["repo"] == str(second),
          f"each bootstrap bound its OWN repository: {first_boot!r} / {second_boot!r}")
    for root, boot, run_id in ((first, first_boot, RUN_ID), (second, second_boot, OTHER_RUN)):
        data = state_of(root)
        check(data["run_id"] == run_id and data["launch"]["at"] == boot["begun_at"]
              and [entry["event"] for entry in data["events"]] == list(PHASE0_REQUIRED),
              f"run {run_id} has its own complete run-bound state: {data!r}")
    check(state_of(first)["run_id"] != state_of(second)["run_id"],
          "the two runs never share a run-bound state")

    # Both reach their Finish and are completed under their own key, without disturbing the other.
    finish_checkpoint(first)
    finish_checkpoint(second)
    second_record = boot_path(launch, second_id).read_text(encoding="utf-8")
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", first_id), 0,
                     "complete run 1")
    check(boot_path(launch, second_id).read_text(encoding="utf-8") == second_record,
          "completing run 1 leaves run 2's bootstrap byte-identical")
    first_record = boot_path(launch, first_id).read_text(encoding="utf-8")
    expect_clean_cli(run("complete", "--launch-dir", str(launch), "--launch-id", second_id), 0,
                     "complete run 2")
    check(boot_path(launch, first_id).read_text(encoding="utf-8") == first_record,
          "completing run 2 leaves run 1's completed record byte-identical")
    check(bootstrap_of(launch, first_id)["completed"]["run_id"] == RUN_ID
          and bootstrap_of(launch, second_id)["completed"]["run_id"] == OTHER_RUN,
          f"each completion names its own run: {bootstrap_of(launch, first_id)!r} / "
          f"{bootstrap_of(launch, second_id)!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        # The UNAFFECTED sections first: they must stay green while the keyed-bootstrap sections
        # below are still pinned to the pre-fix behaviour (this is the vaccination evidence).
        test_clean_scan(tmp)
        test_anomaly_detection(tmp)
        test_stale_and_malformed_state(tmp)
        test_status_fails_closed_without_a_launch(tmp)
        test_single_launch(tmp)
        test_deny_blocks_and_routes(tmp)
        test_old_order_cannot_activate(tmp)
        test_observe_detail_bound(tmp)
        test_plan_rejections_is_a_counter_not_a_role(tmp)
        test_plan_derived_coder_ceiling(tmp)
        test_cli_contract(tmp)
        # The CHANGED and NEW sections (defect C, keyed bootstraps): expected to FAIL before T11.
        test_bootstrap_precedes_phase0(tmp)
        test_sequential_runs(tmp)
        test_unactivated_bootstrap_abandonment(tmp)
        test_ambiguity_refuses(tmp)
        test_legacy_bootstrap_resumes(tmp)
        test_launch_id_validation(tmp)
        test_concurrent_keyed_launches(tmp)

    print("PASS - supervisor_watchdog.py is the supervisor watchdog's deterministic layer: a clean "
          "scan costs nothing and records nothing, a budget/permits/gate-record/journal violation "
          "becomes ONE deduplicated anomaly citing the rule and the role, a stale run binding and "
          "a malformed state are fail-closed exit-2 errors, the launch is single-owner per run, a "
          "recorded deny names the violating role and the rulebook citation and BLOCKS gate_all "
          "phase K/Y until it is resolved with evidence, the supervision BOOTSTRAP precedes Phase 0 "
          "(begin is run-id independent, observe records the closed Phase 0 vocabulary under a "
          "strictly increasing sequence, activate binds the launch to the run atomically, a "
          "COMPLETED bootstrap frees the launch directory for the next independent run, and an "
          "UNACTIVATED failed bootstrap is ended with an audited `abandon --reason` that an "
          "activated run in progress is protected from) and the "
          "OLD order — an unobserved operation, an out-of-order journal, a stale run binding — can "
          "never activate, the bootstrap is KEYED (begin mints a launch nonce and its own file, so "
          "several factories launched from ONE directory into DIFFERENT repositories share no "
          "mutable file — a second begin is a new keyed bootstrap, observe/activate/complete/"
          "abandon take --launch-id, MULTIPLE uncompleted bootstraps are a loud exit-2 ambiguity "
          "naming every id instead of a guess, a completed keyed record is immutable history, an "
          "unkeyed legacy bootstrap stays resumable and is never silently migrated, a malformed or "
          "unknown --launch-id is an exit-2 input error), the observation note is optional and "
          "bounded to 4000 characters, "
          "retry_counters.plan_rejections is the mandated non-role counter rather "
          "than an unknown role, the coder counter is judged against the SAME plan-derived ceiling "
          "the pre-delegation gate enforces (one delegation per distinct coder plan task plus one "
          "retry reserve — 3 plan tasks allow 4, never the raw base table of 1) while every other "
          "role keeps its fixed budget and a plan naming no coder task keeps the base budget, "
          "and the argparse contract holds (--help exit 0, usage errors "
          "exit 2, no traceback).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

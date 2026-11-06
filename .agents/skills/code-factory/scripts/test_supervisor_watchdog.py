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
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("supervisor_watchdog.py")
STATE_REL = pathlib.Path(".code-factory") / "state" / "watchdog.json"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
RUN_ID = "20261103-8e939171"
OTHER_RUN = "20261104-b5b601f6"
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
    for name in ("launch", "scan", "deny", "resolve", "status"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("scan"), 2, "scan without --repo")
    expect_clean_cli(run("deny", "--repo", "."), 2, "deny without --rule/--role/--detail")
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


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_clean_scan(tmp)
        test_anomaly_detection(tmp)
        test_stale_and_malformed_state(tmp)
        test_status_fails_closed_without_a_launch(tmp)
        test_single_launch(tmp)
        test_deny_blocks_and_routes(tmp)
        test_cli_contract(tmp)

    print("PASS - supervisor_watchdog.py is the supervisor watchdog's deterministic layer: a clean "
          "scan costs nothing and records nothing, a budget/permits/gate-record/journal violation "
          "becomes ONE deduplicated anomaly citing the rule and the role, a stale run binding and "
          "a malformed state are fail-closed exit-2 errors, the launch is single-owner per run, a "
          "recorded deny names the violating role and the rulebook citation and BLOCKS gate_all "
          "phase K/Y until it is resolved with evidence, and the argparse contract holds "
          "(--help exit 0, usage errors exit 2, no traceback).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

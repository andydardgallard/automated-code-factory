#!/usr/bin/env python3
"""
Contract test for `permit_gate.py` — the supervisor permit gate (proposal P-8, violation N-5).

WHY THIS EXISTS

`factory-supervisor` (task_15) returns an allow|deny verdict, but a model reading prose does not
physically stop a delegation. This gate is the deterministic half: a delegation needs a PERMIT that
existed before the spawn, carries the supervisor's verdict and its evidence, is bound to the spawned
agent id, and whose scope is a subset of the approved plan task it answers. The finish audit joins
the permits with the session wire (`subagent.spawned` events) and with the plan's task list, and
fails every delegation it cannot account for.

COVERED, through the shipped CLI (a subprocess, like the flow calls it):

  - `init` creates `{run_id, permits: []}` from the checkpoint and never overwrites permits;
  - `add` validates the plan task id, the registered role, the phase, the confined repo-relative
    scope and the empty-scope rule (read-only/business-test roles only), and keeps the permit id
    unique;
  - `verdict` records the supervisor decision with its mandatory evidence, once per permit;
  - `bind` records the spawned agent id on an ALLOWED permit only, unique across the file;
  - `close` marks an allowed permit as NOT executed (reason mandatory, idempotent);
  - `audit` passes a valid verdict→spawn chain and fails, naming the culprit: a permit-less
    delegation, a scope violation, a denied-but-spawned agent, duplicate agent ids, an out-of-order
    verdict, an unused open permit, a malformed wire line, an unplanned task and a plan task with no
    declared files; an absent session wire is DEGRADED (exit 3);
  - the CLI contract: `--help` exit 0 for every subcommand, usage errors exit 2, no traceback, and
    the help survives a legacy console code page.

Exit code 0 = every assertion passes, 1 = the gate did not behave as the contract says.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

TOOL = pathlib.Path(__file__).with_name("permit_gate.py")
PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
PLAN_REL = pathlib.Path(".code-factory") / "state" / "plan.md"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
RUN_ID = "20261103-8e939171"
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

PLAN = """\
## Tasks (DAG)

- task_09: manifest enforcement. files: manifest.py, test_manifest.py; deps: []; verify: x
- task_10: the whole scripts directory. files: scripts/; deps: []; verify: z
- task_18: the closing docs, with no file list. deps: all; verify: y
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


def repo(tmp: pathlib.Path, name: str = "repo") -> pathlib.Path:
    """A repository with a checkpoint, an approved plan and an initialised permits file."""
    root = tmp / name
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w3\n", encoding="utf-8")
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    return root


def permits(root: pathlib.Path) -> dict:
    return json.loads((root / PERMITS_REL).read_text(encoding="utf-8"))


def write_permits(root: pathlib.Path, data: dict) -> None:
    (root / PERMITS_REL).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def mutate(root: pathlib.Path, permit_id: str, **fields) -> None:
    """Hand-edit ONE permit (an abuse fixture the CLI itself would refuse)."""
    data = permits(root)
    for permit in data["permits"]:
        if permit["permit_id"] == permit_id:
            permit.update(fields)
    write_permits(root, data)


def session(root: pathlib.Path, spawns: list[tuple[str, str, int]], *,
            malformed: list[str] | None = None) -> pathlib.Path:
    """A fixture session: `subagent.spawned` events `(agent id, profile, time_ms)` plus raw lines."""
    directory = (root / "home" / "sessions" / "wd_fixture"
                 / "session_11111111-1111-4111-8111-111111111111")
    (directory / "agents" / "main").mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(json.dumps({
        "id": "session_11111111-1111-4111-8111-111111111111",
        "cwd": str(root).replace("\\", "/"), "archived": False,
        "agents": {"main": {"type": "main"}}}), encoding="utf-8")
    lines = [json.dumps({"type": "subagent.spawned", "subagentId": agent,
                         "subagentName": profile, "parentAgentId": "main", "time": stamp})
             for agent, profile, stamp in spawns]
    lines.extend(malformed or [])
    (directory / "agents" / "main" / "wire.jsonl").write_text("\n".join(lines) + "\n",
                                                              encoding="utf-8")
    return directory


def allow(root: pathlib.Path, permit_id: str = "P1", role: str = "coder",
          scope: tuple[str, ...] = ("manifest.py",), task_id: str = "task_09") -> None:
    """Register + allow + bind one permit in one go (the happy path the fixtures build on)."""
    args = ["add", "--repo", str(root), "--permit-id", permit_id, "--task-id", task_id,
            "--role", role, "--phase", "implement"]
    for entry in scope:
        args.extend(["--scope", entry])
    expect_clean_cli(run(*args), 0, f"add {permit_id}")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", permit_id,
                         "--verdict", "allow", "--evidence", f"{task_id} is in the approved plan"),
                     0, f"verdict {permit_id}")


def audit(root: pathlib.Path, directory: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return run("audit", "--repo", str(root), "--session", str(directory))


# --------------------------------------------------------------------------------------------
# init / add: the permit's inputs
# --------------------------------------------------------------------------------------------

def test_init(tmp: pathlib.Path) -> None:
    root = tmp / "init"
    (root / ".code-factory" / "state").mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init")
    check(payload(res)["status"] == "created" and permits(root) == {"run_id": RUN_ID,
                                                                     "permits": []},
          f"init must write the documented skeleton: {payload(res)!r}")
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init (second run)")
    check(payload(res)["status"] == "unchanged", f"a second init is idempotent: {res.stdout!r}")

    # A populated file is never overwritten.
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    allow(root)
    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 2, "init over a populated file")
    check("already lists" in res.stderr, f"the refusal must explain it: {res.stderr!r}")
    check(len(permits(root)["permits"]) == 1, "a refused init must not touch the file")

    # The run id comes from the checkpoint.
    no_run = tmp / "init-no-run"
    (no_run / ".code-factory" / "state").mkdir(parents=True)
    (no_run / PIPELINE_REL).write_text("phase: w3\n", encoding="utf-8")
    res = run("init", "--repo", str(no_run))
    expect_clean_cli(res, 2, "init without a run_id")
    check("run_id" in res.stderr and "belong to exactly one run" in res.stderr,
          f"the error must name the missing run id: {res.stderr!r}")
    res = run("init", "--repo", str(tmp / "no-checkpoint"))
    expect_clean_cli(res, 2, "init without a checkpoint")


def test_add(tmp: pathlib.Path) -> None:
    root = repo(tmp, "add")
    base = ["add", "--repo", str(root), "--phase", "implement"]

    res = run(*base, "--permit-id", "P1", "--task-id", "task_99", "--role", "coder",
              "--scope", "manifest.py")
    expect_clean_cli(res, 2, "an unplanned task id")
    check("does not exist in the approved plan" in res.stderr,
          f"the refusal must name the plan: {res.stderr!r}")
    for label, role in (("unregistered", "wizard"), ("main", "main")):
        res = run(*base, "--permit-id", "P2", "--task-id", "task_09", "--role", role,
                  "--scope", "manifest.py")
        expect_clean_cli(res, 2, f"a {label} role")
        check("role" in res.stderr, f"the refusal must name the role rule: {res.stderr!r}")
    res = run("add", "--repo", str(root), "--permit-id", "P3", "--task-id", "task_09",
              "--role", "coder", "--phase", "deploy", "--scope", "manifest.py")
    expect_clean_cli(res, 2, "an unknown phase")
    check("phase" in res.stderr, f"the refusal must name the phases: {res.stderr!r}")

    # Empty scope: refused for a role that changes files, allowed for a read-only one.
    res = run(*base, "--permit-id", "P4", "--task-id", "task_09", "--role", "coder")
    expect_clean_cli(res, 2, "an empty scope for a coder")
    check("at least one --scope" in res.stderr, f"the rule must be stated: {res.stderr!r}")
    for role in ("analyzer", "reviewer", "supervisor", "business_tester"):
        res = run(*base, "--permit-id", f"R-{role}", "--task-id", "task_09", "--role", role)
        expect_clean_cli(res, 0, f"an empty scope for {role}")

    # Scope confinement and uniqueness.
    for label, scope in (("absolute", "/etc/passwd"), ("escaping", "../outside.py"),
                         ("drive", "C:/Windows/hosts")):
        res = run(*base, "--permit-id", f"S-{label}", "--task-id", "task_09", "--role", "coder",
                  "--scope", scope)
        expect_clean_cli(res, 2, f"a {label} scope")
    res = run(*base, "--permit-id", "D1", "--task-id", "task_09", "--role", "coder",
              "--scope", "manifest.py", "--scope", "manifest.py")
    expect_clean_cli(res, 2, "a duplicated scope")
    check("more than once" in res.stderr, f"the duplication must be named: {res.stderr!r}")

    # A permit id is unique.
    allow(root, "P1")
    res = run(*base, "--permit-id", "P1", "--task-id", "task_09", "--role", "coder",
              "--scope", "manifest.py")
    expect_clean_cli(res, 2, "a duplicate permit id")
    check("already used" in res.stderr, f"the duplication must be named: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# verdict / bind / close: the permitted lifecycle
# --------------------------------------------------------------------------------------------

def test_lifecycle(tmp: pathlib.Path) -> None:
    root = repo(tmp, "lifecycle")
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "P1", "--task-id", "task_09",
                         "--role", "coder", "--phase", "implement", "--scope", "manifest.py"),
                     0, "add")
    # Evidence is mandatory — for an allow especially.
    res = run("verdict", "--repo", str(root), "--permit-id", "P1", "--verdict", "allow",
              "--evidence", "   ")
    expect_clean_cli(res, 2, "an allow without evidence")
    check("--evidence is required" in res.stderr, f"the rule must be stated: {res.stderr!r}")
    # A DENIED permit can never acquire an agent id.
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "P1", "--verdict", "deny",
                         "--evidence", "the scope exceeds task_09 / a rule forbids it"), 0,
                     "record a deny")
    res = run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id", "agent-1")
    expect_clean_cli(res, 2, "binding a denied permit")
    check("NEVER" in res.stderr, f"the refusal must state the rule: {res.stderr!r}")
    check(permits(root)["permits"][0]["agent_id"] is None,
          "a denied permit must stay without an agent id")
    # One verdict per permit.
    res = run("verdict", "--repo", str(root), "--permit-id", "P1", "--verdict", "allow",
              "--evidence", "later")
    expect_clean_cli(res, 2, "a second verdict")
    check("already carries the verdict" in res.stderr, f"the rule must be stated: {res.stderr!r}")

    # The happy path: allow -> bind, agent ids unique.
    allow(root, "P2")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P2", "--agent-id", "agent-2"),
                     0, "bind")
    res = run("bind", "--repo", str(root), "--permit-id", "P2", "--agent-id", "agent-2")
    expect_clean_cli(res, 0, "bind (same agent id)")
    check(payload(res)["status"] == "unchanged", f"a repeated bind is idempotent: {res.stdout!r}")
    allow(root, "P3")
    res = run("bind", "--repo", str(root), "--permit-id", "P3", "--agent-id", "agent-2")
    expect_clean_cli(res, 2, "a duplicate agent id")
    check("one agent, one permit" in res.stderr, f"the rule must be stated: {res.stderr!r}")

    # close: only an allowed, never-spawned permit; reason mandatory; idempotent.
    allow(root, "P4")
    res = run("close", "--repo", str(root), "--permit-id", "P4", "--reason", "  ")
    expect_clean_cli(res, 2, "a close without a reason")
    expect_clean_cli(run("close", "--repo", str(root), "--permit-id", "P4", "--reason",
                         "the dependency task was dropped"), 0, "close")
    res = run("close", "--repo", str(root), "--permit-id", "P4", "--reason", "again")
    expect_clean_cli(res, 0, "close (second run)")
    check(payload(res)["status"] == "unchanged", f"a repeated close is idempotent: {res.stdout!r}")
    res = run("close", "--repo", str(root), "--permit-id", "P2", "--reason", "x")
    expect_clean_cli(res, 2, "closing a permit that spawned")
    res = run("close", "--repo", str(root), "--permit-id", "P1", "--reason", "x")
    expect_clean_cli(res, 2, "closing a denied permit")


# --------------------------------------------------------------------------------------------
# audit: the finish gate
# --------------------------------------------------------------------------------------------

def test_audit(tmp: pathlib.Path) -> None:
    # 1. The valid chain: the permit existed, was allowed, was bound, and the spawn is younger.
    root = repo(tmp, "audit-ok")
    future = int(time.time() * 1000) + 60000
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-3"), 0, "bind")
    directory = session(root, [("agent-3", "factory-coder", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 0, "a valid permit chain")
    check("PASS" in res.stdout, f"the audit must report the pass: {res.stdout!r}")

    # 2. A permit-less delegation is named.
    loose = tmp / "audit-loose"
    (loose / ".code-factory" / "state").mkdir(parents=True)
    (loose / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    (loose / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(loose)), 0, "init (loose fixture)")
    directory = session(loose, [("agent-9", "factory-coder", future)])
    res = audit(loose, directory)
    expect_clean_cli(res, 1, "a permit-less delegation")
    check("permit-less delegation" in res.stdout and "agent-9" in res.stdout,
          f"the audit must name the agent: {res.stdout!r}")

    # 3. A scope violation: the permit's scope is not a subset of the plan task's files. `add`
    #    refuses it, so the fixture is a permit file edited outside the CLI — the audit still catches
    #    it, which is the point of validating the direction in both places.
    scoped = repo(tmp, "audit-scope")
    allow(scoped, "P1", scope=("manifest.py",))
    mutate(scoped, "P1", scope=["test_vaccination.py"])
    expect_clean_cli(run("bind", "--repo", str(scoped), "--permit-id", "P1", "--agent-id",
                         "agent-4"), 0, "bind")
    directory = session(scoped, [("agent-4", "factory-coder", future)])
    res = audit(scoped, directory)
    expect_clean_cli(res, 1, "a scope violation")
    check("scope violation" in res.stdout and "test_vaccination.py" in res.stdout,
          f"the audit must name the out-of-scope path: {res.stdout!r}")

    # 4. A plan task with NO declared files cannot back a permit.
    unprovable = repo(tmp, "audit-nofiles")
    allow(unprovable, "P1", scope=("manifest.py",))
    mutate(unprovable, "P1", task_id="task_18")
    expect_clean_cli(run("bind", "--repo", str(unprovable), "--permit-id", "P1", "--agent-id",
                         "agent-5"), 0, "bind")
    directory = session(unprovable, [("agent-5", "factory-coder", future)])
    res = audit(unprovable, directory)
    expect_clean_cli(res, 1, "an unprovable scope")
    check("unprovable scope" in res.stdout, f"the audit must say why: {res.stdout!r}")

    # 5. Denied-but-spawned (hand-edited: the CLI refuses this bind).
    denied = repo(tmp, "audit-denied")
    expect_clean_cli(run("add", "--repo", str(denied), "--permit-id", "P1", "--task-id",
                         "task_09", "--role", "coder", "--phase", "implement", "--scope",
                         "manifest.py"), 0, "add")
    expect_clean_cli(run("verdict", "--repo", str(denied), "--permit-id", "P1", "--verdict",
                         "deny", "--evidence", "not permitted"), 0, "deny")
    mutate(denied, "P1", agent_id="agent-6")
    directory = session(denied, [("agent-6", "factory-coder", future)])
    res = audit(denied, directory)
    expect_clean_cli(res, 1, "a denied permit that spawned")
    check("denied permit executed" in res.stdout, f"the audit must name the breach: {res.stdout!r}")

    # 6. Out-of-order: the verdict is recorded AFTER the spawn it permits.
    late = repo(tmp, "audit-order")
    allow(late, "P1")
    expect_clean_cli(run("bind", "--repo", str(late), "--permit-id", "P1", "--agent-id",
                         "agent-7"), 0, "bind")
    directory = session(late, [("agent-7", "factory-coder", 1000)])
    res = audit(late, directory)
    expect_clean_cli(res, 1, "a verdict recorded after the spawn")
    check("out-of-order verdict" in res.stdout, f"the audit must name the order: {res.stdout!r}")

    # 7. Duplicate agent ids across permits (hand-edited).
    doubled = repo(tmp, "audit-double")
    allow(doubled, "P1")
    allow(doubled, "P2", scope=("test_manifest.py",))
    mutate(doubled, "P1", agent_id="agent-8")
    mutate(doubled, "P2", agent_id="agent-8")
    directory = session(doubled, [("agent-8", "factory-coder", future)])
    res = audit(doubled, directory)
    expect_clean_cli(res, 1, "a duplicated agent id")
    check("is bound to 2 permits" in res.stdout, f"the audit must name it: {res.stdout!r}")

    # 8. An unused allowed permit fails until it is CLOSED.
    unused = repo(tmp, "audit-unused")
    allow(unused, "P1")
    directory = session(unused, [])
    res = audit(unused, directory)
    expect_clean_cli(res, 1, "an unused allowed permit")
    check("unused permit" in res.stdout and "P1" in res.stdout,
          f"the audit must name the permit: {res.stdout!r}")
    expect_clean_cli(run("close", "--repo", str(unused), "--permit-id", "P1", "--reason",
                         "the task was deferred"), 0, "close the unused permit")
    res = audit(unused, directory)
    expect_clean_cli(res, 0, "a closed unused permit")

    # 9. A malformed wire line fails the audit CLOSED.
    broken = repo(tmp, "audit-malformed")
    allow(broken, "P1")
    expect_clean_cli(run("bind", "--repo", str(broken), "--permit-id", "P1", "--agent-id",
                         "agent-10"), 0, "bind")
    directory = session(broken, [("agent-10", "factory-coder", future)],
                        malformed=["{ this is not json"])
    res = audit(broken, directory)
    expect_clean_cli(res, 1, "a malformed wire line")
    check("malformed" in res.stdout.lower(), f"the audit must name it: {res.stdout!r}")

    # 10. An unplanned task and a role mismatch are caught (hand-edited).
    unplanned = repo(tmp, "audit-task")
    allow(unplanned, "P1")
    mutate(unplanned, "P1", task_id="task_99", agent_id="agent-11")
    directory = session(unplanned, [("agent-11", "factory-coder", future)])
    res = audit(unplanned, directory)
    expect_clean_cli(res, 1, "a permit on an unplanned task")
    check("unplanned task" in res.stdout, f"the audit must name it: {res.stdout!r}")
    mismatch = repo(tmp, "audit-role")
    allow(mismatch, "P1")
    mutate(mismatch, "P1", agent_id="agent-12")
    directory = session(mismatch, [("agent-12", "factory-code-reviewer", future)])
    res = audit(mismatch, directory)
    expect_clean_cli(res, 1, "a role mismatch")
    check("role mismatch" in res.stdout, f"the audit must name it: {res.stdout!r}")

    # 11. An absent session wire is DEGRADED, never a silent pass.
    empty = tmp / "audit-empty"
    (empty / "agents").mkdir(parents=True)
    (empty / "state.json").write_text("{}", encoding="utf-8")
    res = audit(root, empty)
    expect_clean_cli(res, 3, "an absent session wire")
    check("DEGRADED" in res.stdout, f"the verdict must say DEGRADED: {res.stdout!r}")
    empty_home = tmp / "empty-home"
    empty_home.mkdir()
    res = run("audit", "--repo", str(root), "--session", "auto", "--home", str(empty_home))
    expect_clean_cli(res, 3, "a repository with no session")
    # A NONEXISTENT explicit session path is an input error (the caller named something wrong).
    res = run("audit", "--repo", str(root), "--session", str(tmp / "no-session"))
    expect_clean_cli(res, 2, "an explicit session path that does not exist")


# --------------------------------------------------------------------------------------------
# The argparse contract
# --------------------------------------------------------------------------------------------

def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("init", "add", "verdict", "bind", "close", "audit"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("add", "--repo", "."), 2, "add without the required flags")
    expect_clean_cli(run("verdict", "--repo", ".", "--permit-id", "P1"), 2,
                     "verdict without --verdict/--evidence")
    expect_clean_cli(run("audit"), 2, "audit without --repo")
    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


# --------------------------------------------------------------------------------------------
# R1-06: the scope containment has ONE direction — a permit may NARROW the plan task, never widen it.
# R1-07: a wire stamp or a verdict stamp that is not a finite number is an audit FAILURE, never a
#        silent pass of the verdict-order check.
# R1-05: a filesystem failure while writing the permits file exits 2 with the path and the reason,
#        never a traceback.
# R1-17: the audit's three failure classes are focused helpers, so each stays testable on its own.

def test_scope_direction(tmp: pathlib.Path) -> None:
    """(R1-06) A permit scope equal to or BELOW a declared entry passes; a broader one is refused."""
    narrow = repo(tmp, "scope-narrow")
    # task_10 declares the DIRECTORY `scripts/`: a file beneath it is inside the plan task.
    expect_clean_cli(run("add", "--repo", str(narrow), "--permit-id", "P1", "--task-id", "task_10",
                         "--role", "coder", "--phase", "implement", "--scope",
                         "scripts/deep/file.py"), 0, "add a scope BELOW a declared directory")
    # task_09 declares the FILE manifest.py: its parent directory is NOT inside the plan task.
    wider = repo(tmp, "scope-wider")
    res = run("add", "--repo", str(wider), "--permit-id", "P2", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "scripts")
    expect_clean_cli(res, 2, "add a scope WIDER than a declared file")
    check("never widen" in res.stderr, f"the refusal must state the direction: {res.stderr!r}")
    equal = repo(tmp, "scope-equal")
    expect_clean_cli(run("add", "--repo", str(equal), "--permit-id", "P3", "--task-id", "task_10",
                         "--role", "coder", "--phase", "implement", "--scope", "scripts"), 0,
                     "add a scope EQUAL to a declared directory")
    # …and the audit judges the same direction: a narrower permit under a declared directory is fine.
    directory = session(equal, [("agent-n", "factory-coder",
                                int(time.time() * 1000) + 60000)])
    expect_clean_cli(run("verdict", "--repo", str(equal), "--permit-id", "P3", "--verdict",
                         "allow", "--evidence", "task_10 is in the approved plan"), 0, "verdict")
    expect_clean_cli(run("bind", "--repo", str(equal), "--permit-id", "P3", "--agent-id",
                         "agent-n"), 0, "bind")
    expect_clean_cli(audit(equal, directory), 0, "a permit narrower than the plan task")


def test_wire_times(tmp: pathlib.Path) -> None:
    """(R1-07) A non-finite/bool/string stamp is malformed: the audit fails instead of skipping."""
    root = repo(tmp, "wire-times")
    allow(root, "P1", scope=("manifest.py",))
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-t"), 0, "bind")
    for bad in (None, "123", True, float("nan"), float("inf")):
        directory = session(root, [("agent-t", "factory-coder", bad)])
        res = audit(root, directory)
        expect_clean_cli(res, 1, f"a spawn time of {bad!r}")
        check("no usable time" in res.stdout, f"the audit must name the stamp: {res.stdout!r}")


def test_verdict_time(tmp: pathlib.Path) -> None:
    """(R1-07) A permit whose verdict_at_ms is missing or not finite cannot prove the order."""
    for index, bad in enumerate((None, "1", True, float("nan"), float("inf"))):
        root = repo(tmp, f"verdict-time-{index}")
        allow(root, "P1", scope=("manifest.py",))
        mutate(root, "P1", agent_id="agent-v", verdict_at_ms=bad,
               verdict_at="2026-01-01T00:00:00Z")
        directory = session(root, [("agent-v", "factory-coder", 5000)])
        res = audit(root, directory)
        expect_clean_cli(res, 1, f"a verdict_at_ms of {bad!r}")
        check("unreadable verdict time" in res.stdout,
              f"the audit must name the unreadable stamp: {res.stdout!r}")


def test_atomic_write_failure(tmp: pathlib.Path) -> None:
    """(R1-05) An unwritable permits file is an actionable exit 2, and no traceback escapes."""
    blocked = tmp / "permit-write-blocked"
    state = blocked / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text(f"run_id: {RUN_ID}" + chr(10), encoding="utf-8")
    (state / "plan.md").write_text(PLAN, encoding="utf-8")
    # A directory where the file belongs: the atomic replace fails AFTER the temp write, which is
    # exactly the path that used to escape as a traceback.
    (state / "permits.yaml").mkdir()
    res = run("init", "--repo", str(blocked))
    expect_clean_cli(res, 2, "init on an unwritable permits path")
    check("cannot write the permits file" in res.stderr,
          f"init must name the write failure: {res.stderr!r}")

    # A READ-ONLY permits file: the CLI fails, and the permits it already holds stay byte-identical
    # (a half-written permit trail would make the finish audit read a state nobody approved).
    frozen = repo(tmp, "permit-write-frozen")
    allow(frozen, "P1", scope=("manifest.py",))
    permits_file = frozen / PERMITS_REL
    before = permits_file.read_bytes()
    os.chmod(permits_file, 0o444)
    try:
        res = run("add", "--repo", str(frozen), "--permit-id", "P2", "--task-id", "task_09",
                  "--role", "coder", "--phase", "implement", "--scope", "test_manifest.py")
        expect_clean_cli(res, 2, "add onto a read-only permits file")
        check("cannot write the permits file" in res.stderr,
              f"add must name the write failure: {res.stderr!r}")
        check(permits_file.read_bytes() == before,
              "a failed write must leave the permits file byte-identical")
    finally:
        os.chmod(permits_file, 0o644)


def test_huge_stamps(tmp: pathlib.Path) -> None:
    """(I3-2) A 10**1000 JSON integer stamp is judged, never a traceback (exit 1, no crash)."""
    root = repo(tmp, "huge-stamps")
    directory = session(root, [("agent-h", "factory-coder", 10 ** 1000)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a spawn stamped 10**1000 with no permit")
    check("permit-less delegation" in res.stdout,
          f"the audit must report the real violation: {res.stdout!r}")

    allowed = repo(tmp, "huge-verdict")
    allow(allowed, "P1", scope=("manifest.py",))
    mutate(allowed, "P1", agent_id="agent-h2", verdict_at_ms=10 ** 1000,
           verdict_at="2026-01-01T00:00:00Z")
    directory = session(allowed, [("agent-h2", "factory-coder", 5000)])
    res = audit(allowed, directory)
    expect_clean_cli(res, 1, "a permit stamped 10**1000 judging an earlier spawn")
    check("out-of-order verdict" in res.stdout,
          f"the order rule must decide, not the conversion: {res.stdout!r}")


def test_audit_helpers() -> None:
    """(R1-17) The audit is composed of focused helpers, each owning ONE failure class."""
    scripts = str(TOOL.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import permit_gate as pg
    finally:
        sys.path.remove(scripts)
    for name in ("_ownership_problems", "_spawn_problems", "_plan_problems",
                 "_lifecycle_problems", "_within_plan", "_outside_plan",
                 "_verdict_order_problems", "_usable_stamp"):
        check(callable(getattr(pg, name, None)), f"the audit helper {name} must exist")
    check(pg._within_plan("scripts/a.py", ["scripts/"]) and not pg._within_plan("scripts",
                                                                              ["scripts/a.py"]),
          "the containment must be one-directional, in the helper too")
    # (I3-2) The stamp predicate is OVERFLOW-SAFE: a Python int is unbounded and finite, so a huge
    # JSON integer is a usable stamp (it merely orders last) — testing it with math.isfinite would
    # raise OverflowError instead of judging it.
    for value, usable in ((10 ** 1000, True), (0, True), (-1, True),
                          (float("nan"), False), (float("inf"), False), (True, False),
                          ("1", False), (None, False)):
        check(pg._usable_stamp(value) is usable,
              f"_usable_stamp({value!r}) must be {usable}")
    # …and the end-to-end rule never surprises: a huge verdict stamp simply orders last.
    huge = pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": 10 ** 1000},
                                      "permit 'P1'",
                                      {"agent_id": "a1", "time_ms": 5000, "wire": "wire:1"})
    check(len(huge) == 1 and "out-of-order verdict" in huge[0],
          f"a huge verdict stamp must be judged by the ORDER, never by a crash: {huge!r}")

    # (R2-5) The timestamp rule is its own helper: every unusable stamp is an explicit violation and
    # an in-order pair is silent (the four cases are also pinned end to end by test_verdict_time).
    spawn = {"agent_id": "a1", "time_ms": 5000, "wire": "wire:1"}
    for stamp in (None, True, False, "1", float("nan"), float("inf")):
        out = pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": stamp}, "permit 'P1'",
                                         spawn)
        check(len(out) == 1 and "unreadable verdict time" in out[0],
              f"a verdict stamp of {stamp!r} must be unreadable: {out!r}")
    late = pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": 9000}, "permit 'P1'",
                                      spawn)
    check(len(late) == 1 and "out-of-order verdict" in late[0],
          f"a verdict AFTER the spawn must be an order violation: {late!r}")
    check(pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": 5000}, "permit 'P1'",
                                     spawn) == [],
          "an in-order verdict must be silent")
    check(pg._lifecycle_problems([{"permit_id": "P9", "verdict": "allow"}], {}, set())
          == ["unused permit: 'P9' was allowed but never spawned and is not closed — close it with "
              "the reason it was not executed"],
          "the lifecycle helper must own the unused-permit class")
    by_agent, problems = pg._ownership_problems([{"permit_id": "P1", "agent_id": "a1"},
                                                 {"permit_id": "P2", "agent_id": "a1"}])
    check(len(by_agent["a1"]) == 2 and problems and "one agent, one permit" in problems[0],
          f"the ownership helper must own the duplicate class: {problems!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_init(tmp)
        test_add(tmp)
        test_lifecycle(tmp)
        test_audit(tmp)
        test_scope_direction(tmp)
        test_wire_times(tmp)
        test_verdict_time(tmp)
        test_atomic_write_failure(tmp)
        test_huge_stamps(tmp)
        test_audit_helpers()
        test_cli_contract()

    print("PASS - permit_gate.py enforces the supervisor permit trail: init writes the run's "
          "skeleton, add validates the plan task, the registered role, the phase, the confined "
          "repo-relative scope and the empty-scope rule, verdict records one evidenced allow|deny, "
          "bind records a unique agent id on an ALLOWED permit only, close retires an unused "
          "permit with a reason, and the finish audit joins the permits with the session wire and "
          "the plan — failing a permit-less delegation, a scope violation, a denied-but-spawned "
          "agent, a duplicate agent id, an out-of-order verdict, an unused permit, a malformed wire "
          "line and an unprovable task, and reporting DEGRADED (exit 3) when no wire exists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  - the run binding (C32): a permits file of ANOTHER run is rejected before any spawn is
    evaluated;
  - the supervisor bootstrap (C31): supervisor spawns are exempt from the permit-less check, and a
    bound supervisor spawn is still audited;
  - bootstrap permits (C2): `--kind bootstrap` is limited to analyzer/planner/supervisor, answers
    the parsed TASK (`--task-id bootstrap`), and is never plan-checked by the audit;
  - the load validation (C30): every field's type/vocabulary is validated when the file is read —
    a malformed permit (a list `agent_id`, a string `scope`, an unknown verdict/role/phase/kind)
    is an exit-2 input error, never a crash;
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
TASK_REL = pathlib.Path(".code-factory") / "state" / "task.yaml"
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
    check("--kind" in run("add", "--help").stdout,
          "the add help must document --kind (plan|bootstrap)")
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
    """(R1-07) A permit whose verdict_at_ms is missing or not finite cannot prove the order.

    The LOAD validation (C30) owns the ill-TYPED stamps (a string, a bool): they are exit-2 input
    errors the moment the file is read. The AUDIT owns the well-typed but unusable ones (missing,
    NaN, infinity): they are exit-1 violations naming the unreadable stamp.
    """
    for index, bad in enumerate((None, float("nan"), float("inf"))):
        root = repo(tmp, f"verdict-time-{index}")
        allow(root, "P1", scope=("manifest.py",))
        mutate(root, "P1", agent_id="agent-v", verdict_at_ms=bad,
               verdict_at="2026-01-01T00:00:00Z")
        directory = session(root, [("agent-v", "factory-coder", 5000)])
        res = audit(root, directory)
        expect_clean_cli(res, 1, f"a verdict_at_ms of {bad!r}")
        check("unreadable verdict time" in res.stdout,
              f"the audit must name the unreadable stamp: {res.stdout!r}")
    for index, bad in enumerate(("1", True)):
        root = repo(tmp, f"verdict-type-{index}")
        allow(root, "P1", scope=("manifest.py",))
        mutate(root, "P1", agent_id="agent-v", verdict_at_ms=bad,
               verdict_at="2026-01-01T00:00:00Z")
        res = run("verdict", "--repo", str(root), "--permit-id", "P1", "--verdict", "allow",
                  "--evidence", "irrelevant: the file must fail to load first")
        expect_clean_cli(res, 2, f"a verdict_at_ms of {bad!r} fails the load validation")
        check("verdict_at_ms" in res.stderr,
              f"the load error must name the field: {res.stderr!r}")


def test_load_validation(tmp: pathlib.Path) -> None:
    """(C30) read_permits validates EVERY field's type/vocabulary: malformed file = exit 2."""
    root = repo(tmp, "load-validation")
    allow(root, "P1", scope=("manifest.py",))
    cases = (
        ("agent_id-list", {"agent_id": ["agent-1"]}, "agent_id"),
        ("agent_id-dict", {"agent_id": {"id": 1}}, "agent_id"),
        ("scope-string", {"scope": "manifest.py"}, "scope"),
        ("scope-items", {"scope": ["a.py", 3]}, "scope"),
        ("constraints-string", {"constraints": "be good"}, "constraints"),
        ("verdict-vocabulary", {"verdict": "maybe"}, "verdict"),
        ("role-vocabulary", {"role": "wizard"}, "role"),
        ("phase-vocabulary", {"phase": "deploy"}, "phase"),
        ("task-id-type", {"task_id": 9}, "task_id"),
        ("closed-shape", {"closed": "done"}, "closed"),
        ("kind-vocabulary", {"kind": "informal"}, "kind"),
    )
    for name, fields, needle in cases:
        mutate(root, "P1", **fields)
        res = run("close", "--repo", str(root), "--permit-id", "P1", "--reason", "x")
        expect_clean_cli(res, 2, f"a permit with {name}")
        check(needle in res.stderr,
              f"{name}: the load error must name the field: {res.stderr!r}")
        data = permits(root)
        original = {"permit_id": "P1", "kind": "plan", "task_id": "task_09", "role": "coder",
                    "phase": "implement", "scope": ["manifest.py"], "constraints": [],
                    "created_at": data["permits"][0]["created_at"], "verdict": "allow",
                    "evidence": "task_09 is in the approved plan",
                    "verdict_at": data["permits"][0]["verdict_at"],
                    "verdict_at_ms": data["permits"][0]["verdict_at_ms"],
                    "agent_id": None, "bound_at": None, "closed": None}
        write_permits(root, {"run_id": RUN_ID, "permits": [original]})
    # The control: the restored file loads and audits cleanly.
    directory = session(root, [])
    expect_clean_cli(audit(root, directory), 1, "the restored permit is unused (not malformed)")
    res = run("close", "--repo", str(root), "--permit-id", "P1", "--reason", "deferred")
    expect_clean_cli(res, 0, "the restored file loads")


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

    # An UNWRITABLE permits location: the CLI fails, and the permits it already holds stay
    # byte-identical (a half-written permit trail would make the finish audit read a state nobody
    # approved). The write failure must be DETERMINISTIC on every platform: `chmod 0444` on the
    # FILE is a Windows-only assumption — on POSIX the atomic replace is governed by the
    # DIRECTORY's permissions, not the destination's mode, so a read-only directory (which refuses
    # the temp file itself) is the portable POSIX counterpart of a read-only destination on
    # Windows.
    frozen = repo(tmp, "permit-write-frozen")
    allow(frozen, "P1", scope=("manifest.py",))
    permits_file = frozen / PERMITS_REL
    before = permits_file.read_bytes()
    if os.name == "nt":
        os.chmod(permits_file, 0o444)
        restore = (permits_file, 0o644)
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            print("note: skipping the read-only-directory case — root ignores directory modes")
            return
        os.chmod(permits_file.parent, 0o555)
        restore = (permits_file.parent, 0o755)
    try:
        res = run("add", "--repo", str(frozen), "--permit-id", "P2", "--task-id", "task_09",
                  "--role", "coder", "--phase", "implement", "--scope", "test_manifest.py")
        expect_clean_cli(res, 2, "add onto an unwritable permits location")
        check("cannot write the permits file" in res.stderr,
              f"add must name the write failure: {res.stderr!r}")
        check(permits_file.read_bytes() == before,
              "a failed write must leave the permits file byte-identical")
        check(not list(permits_file.parent.glob("permits.yaml.*.tmp")),
              "a failed write must not leave a temp file behind")
    finally:
        os.chmod(*restore)


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


def test_supervisor_bootstrap(tmp: pathlib.Path) -> None:
    """(C31) The supervisor's own spawns are exempt from the permit-less check (wire-level).

    The watchdog is launched at run start under the run's OWN authority: it can never carry a
    verdict that precedes its own spawn. A supervisor spawn with no permit passes; a CODER spawn
    in the same wire is still flagged (the exemption is role-specific); and a supervisor spawn
    bound to a permit is still audited like any other.
    """
    future = int(time.time() * 1000) + 60000
    root = repo(tmp, "audit-supervisor")
    directory = session(root, [("agent-sup", "factory-supervisor", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 0, "a supervisor spawn without a permit (the bootstrap exemption)")
    check("PASS" in res.stdout, f"the audit must report the pass: {res.stdout!r}")

    # The exemption is role-specific: a coder spawn in the same wire is still permit-less.
    mixed = repo(tmp, "audit-supervisor-mixed")
    directory = session(mixed, [("agent-sup2", "factory-supervisor", future),
                                ("agent-c", "factory-coder", future)])
    res = audit(mixed, directory)
    expect_clean_cli(res, 1, "a coder spawn next to an exempt supervisor spawn")
    check("permit-less delegation" in res.stdout and "agent-c" in res.stdout
          and "agent-sup2" not in res.stdout,
          f"only the coder spawn may be flagged: {res.stdout!r}")

    # A supervisor spawn bound to a permit is audited like any other (role mismatch is caught).
    bound = repo(tmp, "audit-supervisor-bound")
    allow(bound, "P1", role="analyzer", scope=())
    mutate(bound, "P1", agent_id="agent-sup3")
    directory = session(bound, [("agent-sup3", "factory-supervisor", future)])
    res = audit(bound, directory)
    expect_clean_cli(res, 1, "a bound supervisor spawn with a role mismatch")
    check("role mismatch" in res.stdout, f"the bound spawn is fully audited: {res.stdout!r}")


def test_stale_permits(tmp: pathlib.Path) -> None:
    """(C32) Permits of ANOTHER run never authorize this run's delegations."""
    future = int(time.time() * 1000) + 60000
    root = repo(tmp, "audit-stale")
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-s"), 0, "bind")
    # Another run reuses the repository: the pipeline moves on, the permits file stays.
    (root / PIPELINE_REL).write_text("run_id: 20261104-b5b601f6\nphase: w3\n", encoding="utf-8")
    directory = session(root, [("agent-s", "factory-coder", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "permits of a stale run")
    check("stale permits" in res.stdout and "20261104-b5b601f6" in res.stdout,
          f"the audit must reject the stale run binding before any spawn is evaluated: "
          f"{res.stdout!r}")
    check("permit-less" not in res.stdout,
          f"the stale binding replaces the per-spawn evaluation: {res.stdout!r}")


TASK_YAML = "title: t\nrepo_path: .\ndescription: d\n"


def test_bootstrap_permits(tmp: pathlib.Path) -> None:
    """(C2) A `--kind bootstrap` permit answers the TASK, for the pre-plan read-only roles."""
    future = int(time.time() * 1000) + 60000
    # The pre-plan reality: a checkpoint and a task, but NO approved plan yet.
    root = tmp / "bootstrap"
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    (root / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init (no plan yet)")
    for role in ("analyzer", "planner", "supervisor"):
        res = run("add", "--repo", str(root), "--permit-id", f"B-{role}", "--kind", "bootstrap",
                  "--task-id", "bootstrap", "--role", role, "--phase", "analysis")
        expect_clean_cli(res, 0, f"a bootstrap permit for {role}")

    # The limits: an implementation role, a plan task id, and a missing task are refused.
    res = run("add", "--repo", str(root), "--permit-id", "B-coder", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "coder", "--phase", "analysis")
    expect_clean_cli(res, 2, "a bootstrap permit for a file-changing role")
    check("limited to the pre-plan read-only roles" in res.stderr,
          f"the limit must be stated: {res.stderr!r}")
    res = run("add", "--repo", str(root), "--permit-id", "B-task", "--kind", "bootstrap",
              "--task-id", "task_09", "--role", "analyzer", "--phase", "analysis")
    expect_clean_cli(res, 2, "a bootstrap permit naming a plan task")
    check("TASK itself" in res.stderr, f"the rule must be stated: {res.stderr!r}")
    no_task = tmp / "bootstrap-no-task"
    (no_task / ".code-factory" / "state").mkdir(parents=True)
    (no_task / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(no_task)), 0, "init (no task)")
    res = run("add", "--repo", str(no_task), "--permit-id", "B1", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis")
    expect_clean_cli(res, 2, "a bootstrap permit without a task")
    check("task" in res.stderr, f"the missing task must be named: {res.stderr!r}")
    # …and a plan permit still requires the approved plan (the pre-plan failure mode of C2).
    res = run("add", "--repo", str(root), "--permit-id", "B-plan", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "a.py")
    expect_clean_cli(res, 2, "a plan permit before the plan exists")
    check("no approved plan" in res.stderr, f"the plan rule must hold: {res.stderr!r}")

    # Once the plan IS approved, the bootstrap permit is judged by verdict order and role, never
    # by the plan's task list ("bootstrap" is not a plan task and must not be flagged as one).
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    for permit_id in ("B-analyzer", "B-planner", "B-supervisor"):
        expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", permit_id,
                             "--verdict", "allow",
                             "--evidence", "bootstrap permit against the parsed task"), 0,
                         f"verdict {permit_id}")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "B-analyzer",
                         "--agent-id", "agent-b"), 0, "bind")
    expect_clean_cli(run("close", "--repo", str(root), "--permit-id", "B-planner",
                         "--reason", "planning finished"), 0, "close planner")
    expect_clean_cli(run("close", "--repo", str(root), "--permit-id", "B-supervisor",
                         "--reason", "covered by the supervisor bootstrap exemption"), 0,
                     "close supervisor")
    directory = session(root, [("agent-b", "factory-analyzer", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 0, "a judged bootstrap permit chain")
    check("unplanned task" not in res.stdout,
          f"a bootstrap permit must not be plan-checked: {res.stdout!r}")


def test_owner_authorization_verified(tmp: pathlib.Path) -> None:
    """(R1, critical) A self-attested `owner_authorized` flag never bypasses the order check.

    The flag lives in the hand-editable `permits.yaml`, so a forged one used to discharge an
    out-of-order verdict. The exception now requires the RUN-BOUND record: an
    `owner_authorizations:` note in `.code-factory/state/pipeline.yaml` naming `permit=<id>`.
    A flag without that record FAILS the audit; the record — not the flag — is the decision.
    """
    future = int(time.time() * 1000) + 60000
    root = tmp / "owner-authz"
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    (root / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init (owner authorization)")
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "PB", "--kind", "bootstrap",
                         "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis"), 0,
                     "add PB")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "PB", "--verdict", "allow",
                         "--evidence", "bootstrap permit against the parsed task"), 0, "verdict PB")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "PB", "--agent-id", "agent-b"),
                     0, "bind PB")
    # The abuse fixture: the permit is hand-edited to claim the owner authorized it retroactively,
    # while its verdict is LATER than the spawn it permits. No checkpoint record exists.
    mutate(root, "PB", owner_authorized=True, evidence="the owner said so",
           verdict_at_ms=future + 60000)
    directory = session(root, [("agent-b", "factory-analyzer", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a forged owner_authorized flag")
    check("unverified owner authorization" in res.stdout,
          f"the audit must refuse the flag and name the missing record: {res.stdout!r}")
    check("permit=PB" in res.stdout,
          f"the refusal must name the record it looked for: {res.stdout!r}")

    # The independent record — written by the owner's decision path, not by the permit — turns the
    # same permit into a legitimate exception.
    pipeline = root / PIPELINE_REL
    pipeline.write_text(pipeline.read_text(encoding="utf-8")
                        + "owner_authorizations:\n"
                          "  - 2026-11-05T16:59:25Z permit=PB role=analyzer mode=hitl\n",
                        encoding="utf-8")
    res = audit(root, directory)
    expect_clean_cli(res, 0, "the checkpoint records the authorization")
    check("unverified owner authorization" not in res.stdout,
          f"a recorded authorization must discharge the order violation: {res.stdout!r}")

    # A record naming ANOTHER permit authorizes nothing.
    pipeline.write_text(pipeline.read_text(encoding="utf-8").replace("permit=PB", "permit=PZ"),
                        encoding="utf-8")
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a record naming another permit")
    check("unverified owner authorization" in res.stdout,
          f"only the permit's OWN recorded authorization counts: {res.stdout!r}")
    check(not (root / "permits-forged.json").exists(), "no fixture file may be left behind")


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
                                      {"agent_id": "a1", "time_ms": 5000, "wire": "wire:1"}, set())
    check(len(huge) == 1 and "out-of-order verdict" in huge[0],
          f"a huge verdict stamp must be judged by the ORDER, never by a crash: {huge!r}")

    # (R2-5) The timestamp rule is its own helper: every unusable stamp is an explicit violation and
    # an in-order pair is silent (the four cases are also pinned end to end by test_verdict_time).
    spawn = {"agent_id": "a1", "time_ms": 5000, "wire": "wire:1"}
    for stamp in (None, True, False, "1", float("nan"), float("inf")):
        out = pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": stamp}, "permit 'P1'",
                                         spawn, set())
        check(len(out) == 1 and "unreadable verdict time" in out[0],
              f"a verdict stamp of {stamp!r} must be unreadable: {out!r}")
    late = pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": 9000}, "permit 'P1'",
                                      spawn, set())
    check(len(late) == 1 and "out-of-order verdict" in late[0],
          f"a verdict AFTER the spawn must be an order violation: {late!r}")
    check(pg._verdict_order_problems({"permit_id": "P1", "verdict_at_ms": 5000}, "permit 'P1'",
                                     spawn, set()) == [],
          "an in-order verdict must be silent")
    # (R3-1) The owner-authorized retroactive BOOTSTRAP exception: a hitl owner may authorize a
    # bootstrap delegation that predates its permit (the pre-mechanism gap); the permit carries
    # owner_authorized: true plus evidence, and the order violation is discharged. A plan-kind
    # permit, a missing flag or missing evidence NEVER qualify.
    ok_override = pg._verdict_order_problems(
        {"permit_id": "PB", "kind": "bootstrap", "owner_authorized": True,
         "evidence": "owner authorized retroactively", "verdict_at_ms": 9000}, "permit 'PB'", spawn,
        {"PB"})
    check(ok_override == [], f"an owner-authorized bootstrap override must be silent: {ok_override!r}")
    # The flag is SELF-ATTESTED in the editable permits file (review R1, critical): without the
    # checkpoint recording the decision the override is a forged flag and the order stands.
    forged = pg._verdict_order_problems(
        {"permit_id": "PB", "kind": "bootstrap", "owner_authorized": True,
         "evidence": "owner authorized retroactively", "verdict_at_ms": 9000}, "permit 'PB'", spawn,
        set())
    check(len(forged) == 1 and "unverified owner authorization" in forged[0],
          f"a flag the checkpoint does not record must be refused: {forged!r}")
    other = pg._verdict_order_problems(
        {"permit_id": "PB", "kind": "bootstrap", "owner_authorized": True,
         "evidence": "owner authorized retroactively", "verdict_at_ms": 9000}, "permit 'PB'", spawn,
        {"PC"})
    check(len(other) == 1 and "unverified owner authorization" in other[0],
          f"an authorization of ANOTHER permit must not discharge this one: {other!r}")
    for broken in ({"permit_id": "PB", "kind": "plan", "owner_authorized": True,
                    "evidence": "owner authorized retroactively", "verdict_at_ms": 9000},
                   {"permit_id": "PB", "kind": "bootstrap", "evidence": "e", "verdict_at_ms": 9000},
                   {"permit_id": "PB", "kind": "bootstrap", "owner_authorized": True,
                    "evidence": "  ", "verdict_at_ms": 9000}):
        out = pg._verdict_order_problems(broken, "permit 'PB'", spawn, {"PB"})
        check(len(out) == 1 and "out-of-order verdict" in out[0],
              f"only a bootstrap permit with flag AND evidence qualifies: {out!r}")
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
        test_load_validation(tmp)
        test_supervisor_bootstrap(tmp)
        test_stale_permits(tmp)
        test_bootstrap_permits(tmp)
        test_owner_authorization_verified(tmp)
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

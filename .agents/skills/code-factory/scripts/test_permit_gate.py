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
  - the CURRENT-SESSION propagation (failing-first, factory-defect-session-resolution.md): with the
    factory launched from its own directory and `repo_path` pointing at another project, the
    explicit current session is audited while the stale target-cwd wire reproduces the false
    `bound but never spawned`; `auto`/omitted never audit that stale session, a blank `--session`
    is an exit-2 input error and a missing current wire is DEGRADED (exit 3);
  - the PRIOR-SESSION binding (failing-first, task_02a): a permit bound before the audited session's
    `createdAt` was an EARLIER CLI session's delegation and is not a `bound but never spawned` of
    this one, while a binding inside the session — or one whose session cannot be dated — keeps the
    violation and every other class (permit-less, denied, out-of-order) stays fatal; and agent ids
    restart in every session, so a previous session's agent id never blocks this session's `bind`
    (nor collides in the audit) while a duplicate within one session still fails both — and for two
    OVERLAPPING sessions, whose `createdAt` windows cannot separate them, the identity a binding
    RECORDS (`session_id`) is what decides (failing-first, task_06d);
  - the RESUMED-AGENT correlation (failing-first, ADV-1): an agent the flow resumes emits a second
    generic `subagent.spawned` line, and an agent id is ONE delegation — its FIRST spawn names the
    role the permit answers, the resume is neither a role mismatch nor a permit-less delegation,
    and the original (never the convenient) role still decides a genuine mismatch;
  - the supervisor bootstrap (C31): supervisor spawns are exempt from the permit-less check, and a
    bound supervisor spawn is still audited;
  - bootstrap permits (C2): `--kind bootstrap` is limited to analyzer/planner/supervisor, answers
    the parsed TASK (`--task-id bootstrap`), and is never plan-checked by the audit — EXCEPT the
    supervisor itself (failing-first, review R1), whose permit is bound to the RUN's authority
    (the WIP checkpoint's `run_id`) because the supervisor is launched BEFORE Phase 0 parses the
    task, so a clean checkout with no task and no plan can still permit it — and, before the
    checkpoint exists at all (review R2), to the launch-scoped `begin` bootstrap through
    `--launch-dir`, leaving the run binding to the later `activate`; that registry is LAUNCH-ONLY
    (no unresolved target `--repo`, review R4) and `bind-run --launch-dir/--repo` transfers it —
    permits and journal — to the resolved repository at activation;
  - the load validation (C30): every field's type/vocabulary is validated when the file is read —
    a malformed permit (a list `agent_id`, a string `scope`, an unknown verdict/role/phase/kind)
    is an exit-2 input error, never a crash;
  - the LEDGER INTEGRITY (failing-first): the run's transitions form an append-only hash-chained
    journal (`permits.ledger.jsonl`), so a registry that was reset and re-created, a truncated tail,
    a hand-edited persisted field, a post-deny repair, a rewritten journal line, a deleted registry,
    an unjournaled legacy file and an owner authorization stamped AFTER the spawn it excuses are all
    refusals — by the write commands and by the finish audit — never a green finish; the ONE
    amendment a hand-editable file may show is computed PER PERMIT (failing-first, review R1): the
    owner-authorized bootstrap may be annotated inside a registry whose ORDINARY permits stay
    byte-for-byte the recorded history, so authorizing one delegation neither freezes the registry
    nor lets any other permit be edited;
  - the LEGACY SNAPSHOT (failing-first): a pre-journal registry is attested by ONE marked `snapshot`
    event that leaves `permits.yaml` byte-identical, is stamped NOW, records no `init`/`add`/
    `verdict`/`bind` time it did not observe, refuses a second snapshot and still exposes every
    violation the attested permits carry;
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
WATCHDOG_TOOL = pathlib.Path(__file__).with_name("supervisor_watchdog.py")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import permit_gate as pg  # noqa: E402  (the importable API whose transaction is fault-injected)
BOOT_REL = pathlib.Path(".code-factory") / "state" / "watchdog-bootstrap.json"
PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
LEDGER_REL = pathlib.Path(".code-factory") / "state" / "permits.ledger.jsonl"
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
            malformed: list[str] | None = None,
            created_at: int | None = None) -> pathlib.Path:
    """A fixture session: `subagent.spawned` events `(agent id, profile, time_ms)` plus raw lines.

    `created_at` is the session's OWN start (`state.json` -> `createdAt`, an epoch-millisecond
    number): it is what tells a binding recorded in an earlier session from this session's own.
    """
    directory = (root / "home" / "sessions" / "wd_fixture"
                 / "session_11111111-1111-4111-8111-111111111111")
    (directory / "agents" / "main").mkdir(parents=True, exist_ok=True)
    state = {"id": "session_11111111-1111-4111-8111-111111111111",
             "cwd": str(root).replace("\\", "/"), "archived": False,
             "agents": {"main": {"type": "main"}}}
    if created_at is not None:
        state["createdAt"] = created_at
    (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
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
    #    it, which is the point of validating the direction in both places. The edit and the binding
    #    land in ONE state: the CLI refuses to append to a registry whose recorded history does not
    #    reach the file on disk, so a hand-written registry writes both fields together.
    scoped = repo(tmp, "audit-scope")
    allow(scoped, "P1", scope=("manifest.py",))
    mutate(scoped, "P1", scope=["test_vaccination.py"], agent_id="agent-4",
           bound_at="2026-01-01T00:00:00Z")
    directory = session(scoped, [("agent-4", "factory-coder", future)])
    res = audit(scoped, directory)
    expect_clean_cli(res, 1, "a scope violation")
    check("scope violation" in res.stdout and "test_vaccination.py" in res.stdout,
          f"the audit must name the out-of-scope path: {res.stdout!r}")

    # 4. A plan task with NO declared files cannot back a permit.
    unprovable = repo(tmp, "audit-nofiles")
    allow(unprovable, "P1", scope=("manifest.py",))
    mutate(unprovable, "P1", task_id="task_18", agent_id="agent-5",
           bound_at="2026-01-01T00:00:00Z")
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
    for name in ("init", "add", "verdict", "bind", "close", "snapshot-legacy", "audit"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("add", "--repo", "."), 2, "add without the required flags")
    check("--kind" in run("add", "--help").stdout,
          "the add help must document --kind (plan|bootstrap)")
    expect_clean_cli(run("snapshot-legacy"), 2, "snapshot-legacy without --repo")
    check("--note" in run("snapshot-legacy", "--help").stdout,
          "the snapshot help must document --note")
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

def test_resumed_agent_role_correlation(tmp: pathlib.Path) -> None:
    """(failing-first, ADV-1) A RESUMED agent is judged by the role it was spawned with.

    The CLI appends a SECOND `subagent.spawned` line for an agent the flow resumes, and that resume
    event carries a generic profile name instead of the factory profile. The audit judged every
    spawn line on its own, so the resumed reviewer's line read `role mismatch: permit 'P1' permits
    role 'reviewer', but agent 'agent-12' is 'coder'` — 47 such false violations on one real wire.
    An agent id is ONE delegation: the role comes from its FIRST spawn (the original delegation the
    permit answered), a later resume of the same id is that same delegation, and the original role —
    never whichever name happens to be convenient — is what the permit is judged against.
    """
    future = int(time.time() * 1000) + 60000

    # 1. A resumed reviewer: the permit role is the one the ORIGINAL spawn carries.
    resumed = repo(tmp, "resume-reviewer")
    allow(resumed, "P1", role="reviewer")
    expect_clean_cli(run("bind", "--repo", str(resumed), "--permit-id", "P1", "--agent-id",
                         "agent-12"), 0, "bind a reviewer permit")
    directory = session(resumed, [("agent-12", "factory-code-reviewer", future),
                                  ("agent-12", "coder", future + 1000)])
    res = audit(resumed, directory)
    expect_clean_cli(res, 0, "a resumed agent under its own permit")
    check("PASS" in res.stdout, f"the resumed delegation must pass the audit: {res.stdout!r}")
    check("role mismatch" not in res.stdout,
          f"a resume is not a second delegation and its generic name is no mismatch: {res.stdout!r}")
    check("permit-less delegation" not in res.stdout,
          f"the bound agent id must cover the resume event too: {res.stdout!r}")

    # 2. The correlation never picks the convenient name: a CODER permit over a reviewer spawn stays
    #    a mismatch, even though the resume event happens to say 'coder'.
    flipped = repo(tmp, "resume-coder")
    allow(flipped, "P1", role="coder")
    expect_clean_cli(run("bind", "--repo", str(flipped), "--permit-id", "P1", "--agent-id",
                         "agent-13"), 0, "bind a coder permit")
    directory = session(flipped, [("agent-13", "factory-code-reviewer", future),
                                  ("agent-13", "coder", future + 1000)])
    res = audit(flipped, directory)
    expect_clean_cli(res, 1, "a genuine role mismatch behind a resume")
    check("role mismatch" in res.stdout and "agent-13" in res.stdout,
          f"the ORIGINAL role decides, so the mismatch must stand: {res.stdout!r}")

    # 3. A resumed agent that carries NO permit is still a permit-less delegation.
    loose = tmp / "resume-loose"
    (loose / ".code-factory" / "state").mkdir(parents=True)
    (loose / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    (loose / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(loose)), 0, "init (resume fixture)")
    directory = session(loose, [("agent-14", "factory-code-reviewer", future),
                                ("agent-14", "coder", future + 1000)])
    res = audit(loose, directory)
    expect_clean_cli(res, 1, "a resumed agent with no permit")
    check("permit-less delegation" in res.stdout and "agent-14" in res.stdout,
          f"the resumed delegation must still be named: {res.stdout!r}")

    # 4. A single spawn with the wrong role — no resume involved — is unchanged: the finding the
    #    correlation explains must never be softened away.
    plain = repo(tmp, "resume-plain")
    allow(plain, "P1", role="reviewer")
    expect_clean_cli(run("bind", "--repo", str(plain), "--permit-id", "P1", "--agent-id",
                         "agent-15"), 0, "bind")
    directory = session(plain, [("agent-15", "factory-coder", future)])
    res = audit(plain, directory)
    expect_clean_cli(res, 1, "a single wrong-role spawn")
    check("role mismatch" in res.stdout and "agent-15" in res.stdout,
          f"a real role mismatch must still fail: {res.stdout!r}")


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


# --------------------------------------------------------------------------------------------
# The finish audit must read the CURRENT run's wire when launch and repository differ
# --------------------------------------------------------------------------------------------

def layout_session(home: pathlib.Path, cwd: pathlib.Path, session_id: str, lines: list[str], *,
                   age_s: float = 0.0, created_at: int | None = None) -> pathlib.Path:
    """One fixture session whose `state.json` cwd is `cwd` and whose wire holds `lines`."""
    directory = home / "sessions" / f"wd_{cwd.name}" / session_id
    (directory / "agents" / "main").mkdir(parents=True, exist_ok=True)
    state = {"id": session_id, "cwd": str(cwd).replace("\\", "/"), "archived": False,
             "agents": {"main": {"type": "main"}}}
    if created_at is not None:
        state["createdAt"] = created_at
    (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (directory / "agents" / "main" / "wire.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        for path in [*directory.rglob("*"), directory]:
            os.utime(path, (stamp, stamp))
    return directory


def launch_layout(tmp: pathlib.Path, name: str) -> dict:
    """A launch directory, a target repository and two sessions — the reported layout.

    The stale session's cwd is the TARGET repository (it ran there days earlier); the run's own
    session's cwd is the LAUNCH directory. The pipeline is the run's evidence of both.
    """
    home = tmp / f"home-{name}"
    launch = tmp / f"launch-{name}"
    root = tmp / f"repo-{name}"
    launch.mkdir(parents=True, exist_ok=True)
    (root / ".code-factory" / "state").mkdir(parents=True, exist_ok=True)
    future = int(time.time() * 1000) + 60000
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    stale = layout_session(home, root, "session_28000000-0000-4000-8000-000000000028", [
        json.dumps({"type": "llm.request", "agentId": "main", "model": "kimi-k3",
                    "time": int(time.time() * 1000) - 86400000})], age_s=86400)
    current = layout_session(home, launch, "session_28111111-1111-4111-8111-111111111111", [
        json.dumps({"type": "subagent.spawned", "subagentId": "agent-3",
                    "subagentName": "factory-coder", "parentAgentId": "main",
                    "time": future})])
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    # The binding is made BEFORE the checkpoint names its session — the pre-identity shape the
    # reported run had. Only such a binding is dated by the audited session's own start, which is
    # what makes the stale wire reproduce the accusation this test is about; a binding that RECORDS
    # its session is placed by that identity instead (see
    # `test_overlapping_sessions_bind_the_same_agent_ids`). The full checkpoint is written right
    # after, so `auto` has the run evidence it must resolve by.
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w3\n", encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init")
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-3"), 0, "bind")
    (root / PIPELINE_REL).write_text(
        f"run_id: {RUN_ID}\nphase: w3\nstatus: in_progress\n"
        f'started_at: "{started}"\n'
        f'launch_dir: "{launch.as_posix()}"\n'
        f'session_dir: "{current.as_posix()}"\n', encoding="utf-8")
    return {"home": home, "launch": launch, "root": root, "stale": stale, "current": current,
            "future": future}


def test_current_session_resolution(tmp: pathlib.Path) -> None:
    """(failing-first, factory-defect-session-resolution.md) The audit must not read the old wire.

    The reported run was launched from the factory directory for another project: its own session
    had `cwd` = the launch directory and an older session had `cwd` = the target repository, so
    `--session auto` matched the target repository and the audit printed `bound but never spawned`
    about a run that had finished weeks earlier. The explicit session is the contract; `auto` must
    resolve the one run-bound candidate or DEGRADE, a blank `--session` is an input error, and a
    stale wire is never audited as this run.
    """
    fixture = launch_layout(tmp, "session")
    home, root = fixture["home"], fixture["root"]
    stale, current = fixture["stale"], fixture["current"]
    stale_dir = str(stale.resolve())
    current_dir = str(current.resolve())

    # The run's own wire: the bound permit and its spawn really do match.
    res = run("audit", "--repo", str(root), "--session", str(current), "--home", str(home))
    expect_clean_cli(res, 0, "the explicit current session")
    check(current_dir in res.stdout and "PASS" in res.stdout,
          f"the audit must name and pass the run's own wire: {res.stdout!r}")

    # The stale wire accuses the current run's permit of a delegation it never made.
    res = run("audit", "--repo", str(root), "--session", str(stale), "--home", str(home))
    expect_clean_cli(res, 1, "the stale target-cwd session")
    check(stale_dir in res.stdout and "bound but never spawned" in res.stdout,
          f"the false accusation the report describes must be reproducible: {res.stdout!r}")

    # `auto` must never be that accusation: the old target-cwd session is not this run.
    for label, extra in (("auto", ("--session", "auto")), ("omitted", ())):
        res = run("audit", "--repo", str(root), *extra, "--home", str(home))
        check(res.returncode in (0, 3),
              f"{label}: a confident audit of the stale wire is the defect: exit "
              f"{res.returncode} {res.stdout!r} {res.stderr!r}")
        check(f"session: {stale_dir}" not in res.stdout,
              f"{label}: the stale target-cwd session must not be audited: {res.stdout!r}")
        if res.returncode == 0:
            check(f"session: {current_dir}" in res.stdout,
                  f"{label}: a resolved audit must read the run's own wire: {res.stdout!r}")

    # A blank --session is an input error: blank never means `auto`.
    res = run("audit", "--repo", str(root), "--session", "", "--home", str(home))
    expect_clean_cli(res, 2, "a blank --session")

    # The run's session is gone: a wire older than `started_at` DEGRADES instead of accusing.
    current.rename(tmp / "session-moved-away")
    res = run("audit", "--repo", str(root), "--session", "auto", "--home", str(home))
    expect_clean_cli(res, 3, "a run whose own session is missing")
    check("DEGRADED" in res.stdout,
          f"the degradation must be loud, never a confident stale audit: {res.stdout!r}")


TASK_YAML = "title: t\nrepo_path: .\ndescription: d\n"


def test_prior_session_binding_is_not_a_current_spawn(tmp: pathlib.Path) -> None:
    """(failing-first, task_02a) A binding an EARLIER CLI session recorded is not this session's.

    Phase K of run 20261123-9598a460 failed on `bound but never spawned` about
    `supervisor-bootstrap`: that permit was bound to `agent-3` in the PREVIOUS CLI session (its
    `bound_at` — 07:10:42 — precedes the audited session's `createdAt`, 07:24:11), and agent ids
    restart in every session, so this session's wire can never hold it. The session boundary is the
    evidence that decides: a binding older than the audited session belongs to another session, a
    binding INSIDE it — or a registry whose session cannot be dated at all — keeps the violation,
    and every other current-session class stays fatal.
    """
    root = repo(tmp, "audit-prior-session")
    now = int(time.time() * 1000)
    past = now - 7200000                                    # the PREVIOUS session's moment
    past_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(past / 1000))
    started = past + 3600000                                # the audited session began later
    # P1 ran in the PREVIOUS session: it was allowed and bound at that earlier moment (only the
    # clock is pinned there — the records and the ledger are the real ones the gate writes).
    real_now = pg._now
    pg._now = lambda: (past_iso, past)
    try:
        pg.add(root, "P1", "task_09", "coder", "implement", ["manifest.py"])
        pg.verdict(root, "P1", "allow", "task_09 is in the approved plan")
        pg.bind(root, "P1", "agent-3")
    finally:
        pg._now = real_now
    # P2 is THIS session's delegation: allowed before the spawn it permits.
    allow(root, "P2", scope=("test_manifest.py",))
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P2", "--agent-id",
                         "agent-1"), 0, "bind (the current session's delegation)")
    spawns = [("agent-1", "factory-coder", now + 1000)]

    # 1. The audited session began AFTER P1 was bound: P1 is the earlier session's delegation, so
    #    the run passes — this is the false accusation that failed phase K.
    directory = session(root, spawns, created_at=started)
    res = audit(root, directory)
    expect_clean_cli(res, 0, "a permit bound in a previous session")
    check("PASS" in res.stdout and "bound but never spawned" not in res.stdout,
          f"a prior-session binding must not be reported as this session's spawn: {res.stdout!r}")

    # 2. The SAME registry audited as the session the binding falls INSIDE: a genuine
    #    `bound but never spawned` — the boundary decides, never a blanket waiver.
    session(root, spawns, created_at=past - 3600000)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a binding that belongs to the audited session")
    check("bound but never spawned" in res.stdout and "agent-3" in res.stdout,
          f"a current-session binding the wire does not hold must still fail: {res.stdout!r}")

    # 3. No session start recorded: unprovable, so the fail-closed reading (this session's) stands.
    session(root, spawns)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "an undatable session")
    check("bound but never spawned" in res.stdout,
          f"without the session's own start the violation must stand: {res.stdout!r}")

    # 4. The exemption is NARROW: a permit-less delegation of the CURRENT session still fails.
    session(root, [*spawns, ("agent-9", "factory-coder", now + 2000)], created_at=started)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a permit-less delegation beside a prior-session binding")
    check("permit-less delegation" in res.stdout and "agent-9" in res.stdout
          and "bound but never spawned" not in res.stdout,
          f"only the prior-session class is exempt, never a genuine one: {res.stdout!r}")


def test_overlapping_sessions_bind_the_same_agent_ids(tmp: pathlib.Path) -> None:
    """(failing-first, task_06d) OVERLAPPING CLI sessions: `createdAt` cannot place a binding.

    Live failure: the audit of run 20261123-9598a460 reported `agent id 'agent-3' is bound to 2
    permits (supervisor-bootstrap, tester-farukon)`. Both bindings were made in a DIFFERENT,
    OVERLAPPING CLI session — the old session was still alive when the audited one was created, so
    `bound_at` falls INSIDE the audited session's `createdAt` window and the timestamp rule (task_02a)
    reads them as this session's: a duplicate that never happened, and `bind` of the current coder's
    reused id was refused for the same reason. The evidence that separates them is the session
    identity a binding RECORDS (`bind` -> `session_id`, from the run's own `session_dir`); a binding
    made before that field existed keeps the stamp reading (it is not this session's) but is never
    paired with another such binding, because one stamp cannot say WHICH earlier session made it.
    """
    now = int(time.time() * 1000)
    future = now + 60000
    audited_started = now - 1800000                  # the audited session's `createdAt` …
    during_overlap = now - 600000                    # … and the OLD session was still alive here

    # PART A — the PRE-IDENTITY registry an earlier factory left behind: two bindings, both carrying
    # only a stamp, both predating the audited session (the reported shape: `supervisor-bootstrap`
    # and `tester-farukon`, both on `agent-3`). One stamp proves a binding is not this session's but
    # never WHICH earlier session made it, so the two must not be paired into a duplicate.
    legacy_root = tmp / "overlapping-legacy"
    (legacy_root / ".code-factory" / "state").mkdir(parents=True)
    (legacy_root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: K\n", encoding="utf-8")
    (legacy_root / PLAN_REL).write_text(PLAN, encoding="utf-8")

    def legacy_permit(permit_id: str, role: str, bound_ms: int) -> dict:
        at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(bound_ms / 1000))
        return {"permit_id": permit_id, "kind": "bootstrap", "task_id": "bootstrap",
                "role": role, "phase": "analysis", "scope": [], "constraints": [],
                "created_at": at, "verdict": "allow", "evidence": "earlier factory",
                "verdict_at": at, "verdict_at_ms": bound_ms - 60000, "agent_id": "agent-3",
                "bound_at": at, "closed": None}

    write_permits(legacy_root, {"run_id": RUN_ID, "permits": [
        legacy_permit("supervisor-bootstrap", "supervisor", during_overlap - 7200000),
        legacy_permit("analyzer-farukon", "analyzer", during_overlap - 3600000)]})
    expect_clean_cli(run("snapshot-legacy", "--repo", str(legacy_root)), 0, "snapshot-legacy")
    legacy_home = tmp / "home-overlapping-legacy"
    audited = layout_session(legacy_home, legacy_root,
                             "session_31111111-1111-4111-8111-111111111111", [],
                             created_at=audited_started)
    res = run("audit", "--repo", str(legacy_root), "--session", str(audited),
              "--home", str(legacy_home))
    expect_clean_cli(res, 0, "two pre-identity bindings of two earlier sessions")
    check("is bound to 2 permits" not in res.stdout and "PASS" in res.stdout,
          f"bindings whose session is unidentified must not be paired: {res.stdout!r}")

    # PART B — the OVERLAP: the old session was still running AFTER the audited one was created, so
    # its binding's stamp falls INSIDE the audited window and the timestamp rule reads it as this
    # session's. The identity the binding RECORDS is what separates them.
    root = repo(tmp, "overlapping-sessions")
    home = tmp / "home-overlapping"
    old = layout_session(home, root, "session_30000000-0000-4000-8000-000000000030", [],
                         created_at=during_overlap - 3600000)
    current = layout_session(home, root, "session_31111111-1111-4111-8111-111111111111", [
        json.dumps({"type": "subagent.spawned", "subagentId": "agent-3",
                    "subagentName": "factory-tester", "parentAgentId": "main", "time": future}),
        json.dumps({"type": "subagent.spawned", "subagentId": "agent-4",
                    "subagentName": "factory-coder", "parentAgentId": "main", "time": future})],
        created_at=audited_started)

    # 1. The OLD session's coder, bound while the checkpoint named THAT session: the binding records
    #    its identity, so nothing later has to guess from a timestamp.
    (root / PIPELINE_REL).write_text(
        f"run_id: {RUN_ID}\nphase: w3\nsession_dir: \"{old.as_posix()}\"\n", encoding="utf-8")
    allow(root, "coder-first", scope=("manifest.py",))
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "coder-first", "--agent-id",
                         "agent-4"), 0, "bind (the old session's coder)")

    # 2. The audited session reuses BOTH agent ids: the recorded identity is the evidence, never the
    #    overlap — so `bind` accepts them (the pre-fix reading refused `agent-3`/`agent-4` here).
    (root / PIPELINE_REL).write_text(
        f"run_id: {RUN_ID}\nphase: w3\nsession_dir: \"{current.as_posix()}\"\n", encoding="utf-8")
    allow(root, "tester-farukon", role="tester")
    for permit_id, agent_id, scope in (("tester-farukon", "agent-3", ("manifest.py",)),
                                       ("coder-second", "agent-4", ("test_manifest.py",))):
        if permit_id == "coder-second":
            allow(root, permit_id, scope=scope)
        res = run("bind", "--repo", str(root), "--permit-id", permit_id, "--agent-id", agent_id)
        expect_clean_cli(res, 0, f"bind {agent_id} that an OVERLAPPING session used ({permit_id})")
        check("one agent, one permit" not in res.stderr,
              f"an overlapping session's binding must not block this one: {res.stderr!r}")

    # 3. The bindings carry the identity that decided them.
    recorded = {permit["permit_id"]: permit for permit in permits(root)["permits"]}
    check(recorded["tester-farukon"]["session_id"] == current.name
          and recorded["coder-second"]["session_id"] == current.name,
          f"a binding must record the session it was made in: {recorded['tester-farukon']!r}")
    check(recorded["coder-first"]["session_id"] == old.name,
          f"the old session's binding keeps ITS identity: {recorded['coder-first']!r}")

    # 4. The audit names no duplicate: this is the false violation the report produced.
    res = run("audit", "--repo", str(root), "--session", str(current), "--home", str(home))
    expect_clean_cli(res, 0, "two overlapping sessions that reused agent ids")
    check("PASS" in res.stdout and "is bound to 2 permits" not in res.stdout,
          f"an overlapping session's reuse is not a duplicate: {res.stdout!r}")

    # 5. …and the identity is evidence, not a waiver: a binding of the AUDITED session that its wire
    #    never confirms still fails closed.
    allow(root, "reviewer-extra", role="reviewer", scope=())
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "reviewer-extra",
                         "--agent-id", "agent-5"), 0, "bind (an agent the wire never spawns)")
    res = run("audit", "--repo", str(root), "--session", str(current), "--home", str(home))
    expect_clean_cli(res, 1, "a recorded binding the audited wire never confirms")
    check("bound but never spawned" in res.stdout and "agent-5" in res.stdout
          and "is bound to 2 permits" not in res.stdout,
          f"the identity places a binding, it never excuses it: {res.stdout!r}")


def test_current_session_violations_survive_the_session_boundary(tmp: pathlib.Path) -> None:
    """(task_02a) A DATED session still fails every violation the wire really shows."""
    now = int(time.time() * 1000)
    started = now - 3600000                     # this session began an hour before the audit

    # A denied permit that executed anyway.
    denied = repo(tmp, "session-boundary-denied")
    expect_clean_cli(run("add", "--repo", str(denied), "--permit-id", "P1", "--task-id",
                         "task_09", "--role", "coder", "--phase", "implement", "--scope",
                         "manifest.py"), 0, "add")
    expect_clean_cli(run("verdict", "--repo", str(denied), "--permit-id", "P1", "--verdict",
                         "deny", "--evidence", "not permitted"), 0, "deny")
    mutate(denied, "P1", agent_id="agent-6")
    res = audit(denied, session(denied, [("agent-6", "factory-coder", now)], created_at=started))
    expect_clean_cli(res, 1, "a denied permit that spawned in this session")
    check("denied permit executed" in res.stdout,
          f"the session boundary must not silence a denial: {res.stdout!r}")

    # A verdict recorded after the spawn it permits.
    late = repo(tmp, "session-boundary-order")
    allow(late, "P1")
    expect_clean_cli(run("bind", "--repo", str(late), "--permit-id", "P1", "--agent-id",
                         "agent-7"), 0, "bind")
    res = audit(late, session(late, [("agent-7", "factory-coder", now - 1800000)],
                              created_at=started))
    expect_clean_cli(res, 1, "an out-of-order verdict in this session")
    check("out-of-order verdict" in res.stdout,
          f"the session boundary must not excuse the order: {res.stdout!r}")

    # A binding inside the session that the wire never confirms.
    unspawned = repo(tmp, "session-boundary-binding")
    allow(unspawned, "P1")
    expect_clean_cli(run("bind", "--repo", str(unspawned), "--permit-id", "P1", "--agent-id",
                         "agent-5"), 0, "bind")
    res = audit(unspawned, session(unspawned, [], created_at=started))
    expect_clean_cli(res, 1, "a binding of this session with no spawn")
    check("bound but never spawned" in res.stdout and "agent-5" in res.stdout,
          f"a binding this session recorded must be proven by its wire: {res.stdout!r}")


def test_prior_session_agent_id_does_not_block_the_current_session(tmp: pathlib.Path) -> None:
    """(failing-first, task_02a) Agent ids restart in every CLI session, so a previous session's
    binding must not collide with this session's agent id.

    Live failure: binding the current run's tester (`agent-3`) to `tester-farukon` was refused —
    "agent id 'agent-3' is already bound to permit 'supervisor-bootstrap'" — because the PREVIOUS
    CLI session had used `agent-3` for the supervisor. `bind` and the audit must judge the collision
    on the SAME evidence (the run's own session start), while a duplicate WITHIN one session stays
    fatal and an undatable session keeps the refusal.
    """
    root = repo(tmp, "agent-id-reuse")
    past = int(time.time() * 1000) - 7200000                     # the PREVIOUS session's moment
    past_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(past / 1000))
    started = past + 3600000                                     # this session began an hour later
    directory = session(root, [], created_at=started)
    # The previous session's registry was bound BEFORE this run's activation wrote the checkpoint:
    # nothing named a session yet, so that binding could not record one (the pre-identity shape).
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w3\n", encoding="utf-8")

    # 1. What the previous session left behind: the supervisor's bootstrap permit, bound to agent-3
    #    before this session existed. Only the clock is pinned to that moment — the records, the
    #    verdict and the ledger are the real ones the gate writes.
    real_now = pg._now
    pg._now = lambda: (past_iso, past)
    try:
        pg.add(root, "supervisor-bootstrap", "bootstrap", "supervisor", "analysis", kind="bootstrap")
        pg.verdict(root, "supervisor-bootstrap", "allow", "run-own authority bootstrap")
        pg.bind(root, "supervisor-bootstrap", "agent-3")
    finally:
        pg._now = real_now
    recorded = {permit["permit_id"]: permit for permit in permits(root)["permits"]}
    check(recorded["supervisor-bootstrap"]["bound_at"] == past_iso,
          f"the fixture must record the previous session's binding moment: "
          f"{recorded['supervisor-bootstrap']!r}")
    # …and the activation that follows binds the registry to THIS run's session.
    (root / PIPELINE_REL).write_text(
        f"run_id: {RUN_ID}\nphase: w3\nsession_dir: \"{directory.as_posix()}\"\n", encoding="utf-8")

    # 2. THIS session's tester delegation: the same agent id, a different session.
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "tester-farukon", "--task-id",
                         "task_09", "--role", "tester", "--phase", "implement", "--scope",
                         "manifest.py"), 0, "add (tester)")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "tester-farukon",
                         "--verdict", "allow", "--evidence", "task_09 is in the approved plan"),
                     0, "verdict (tester)")
    res = run("bind", "--repo", str(root), "--permit-id", "tester-farukon", "--agent-id", "agent-3")
    expect_clean_cli(res, 0, "bind an agent id a previous session used")
    check("one agent, one permit" not in res.stderr,
          f"a previous session's binding must not block this one: {res.stderr!r}")

    # 3. The audit agrees with that bind: the current session's spawn is permitted, the previous
    #    session's binding is neither a duplicate nor a spawn of this session.
    directory = session(root, [("agent-3", "factory-tester", int(time.time() * 1000) + 1000)],
                        created_at=started)
    res = audit(root, directory)
    expect_clean_cli(res, 0, "the current session's reuse of a previous agent id")
    check("PASS" in res.stdout and "supervisor-bootstrap" not in res.stdout,
          f"the earlier session's delegation must not be judged by this session: {res.stdout!r}")

    # 4. A duplicate INSIDE this session is still refused.
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "tester-second", "--task-id",
                         "task_09", "--role", "tester", "--phase", "implement", "--scope",
                         "test_manifest.py"), 0, "add (second tester)")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "tester-second",
                         "--verdict", "allow", "--evidence", "task_09 is in the approved plan"),
                     0, "verdict (second tester)")
    res = run("bind", "--repo", str(root), "--permit-id", "tester-second", "--agent-id", "agent-3")
    expect_clean_cli(res, 2, "a second binding of one agent id in the SAME session")
    check("one agent, one permit" in res.stderr, f"the rule must be stated: {res.stderr!r}")

    # 5. Fail closed: with no `session_dir` the run cannot date its own session, so the collision is
    #    unprovable and the refusal stands.
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w3\n", encoding="utf-8")
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "tester-third", "--task-id",
                         "task_09", "--role", "tester", "--phase", "implement", "--scope",
                         "manifest.py"), 0, "add (third tester)")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "tester-third",
                         "--verdict", "allow", "--evidence", "task_09 is in the approved plan"),
                     0, "verdict (third tester)")
    res = run("bind", "--repo", str(root), "--permit-id", "tester-third", "--agent-id", "agent-3")
    expect_clean_cli(res, 2, "an undatable run reusing a bound agent id")
    check("one agent, one permit" in res.stderr,
          f"an unprovable session must keep the refusal: {res.stderr!r}")

    # 6. And the AUDIT still reports two permits of this session bound to one agent id (hand-edited,
    #    since the CLI refuses that bind — the last check, because the edit desynchronizes the ledger
    #    from the file and every later write is refused by design).
    mutate(root, "tester-third", agent_id="agent-3")
    res = audit(root, directory)
    expect_clean_cli(res, 1, "two permits of this session bound to one agent id")
    check("is bound to 2 permits" in res.stdout,
          f"the audit must keep refusing a same-session duplicate: {res.stdout!r}")


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


def test_supervisor_permit_before_task(tmp: pathlib.Path) -> None:
    """(review R1, critical) The supervisor's own permit is bound to the RUN, not to the task.

    The mandated order starts the supervisor BEFORE Phase 0 parses the task (`begin` needs only the
    launch directory), so a supervisor bootstrap permit anchored on the parsed task could not exist
    when the supervisor is launched: the run's own authority — the WIP checkpoint's `run_id` — is
    the only anchor available at that moment. `analyzer`/`planner` still answer the TASK itself and
    keep the parsed-task anchor.
    """
    root = tmp / "clean-checkout"
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: pre-flight\n", encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init on a clean checkout")
    check(not (root / TASK_REL).exists() and not (root / PLAN_REL).exists(),
          "the fixture must have NO parsed task and NO approved plan yet")

    res = run("add", "--repo", str(root), "--permit-id", "PB-supervisor", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "supervisor", "--phase", "analysis")
    expect_clean_cli(res, 0, "a supervisor bootstrap permit before the task is parsed")
    data = permits(root)
    check(len(data["permits"]) == 1 and data["permits"][0]["role"] == "supervisor"
          and data["permits"][0]["kind"] == "bootstrap"
          and data["permits"][0]["task_id"] == "bootstrap",
          f"the pre-task permit answers the run itself: {data!r}")

    # The task anchor is unchanged for the roles that really answer the task.
    for role in ("analyzer", "planner"):
        res = run("add", "--repo", str(root), "--permit-id", f"PB-{role}", "--kind", "bootstrap",
                  "--task-id", "bootstrap", "--role", role, "--phase", "analysis")
        expect_clean_cli(res, 2, f"a {role} bootstrap permit before the task is parsed")
        check("task" in res.stderr.lower(),
              f"the {role} refusal must name the missing task: {res.stderr!r}")

    # The run authority is the anchor: without the checkpoint there is no run to permit against.
    bare = tmp / "clean-checkout-no-run"
    (bare / ".code-factory" / "state").mkdir(parents=True)
    res = run("init", "--repo", str(bare))
    expect_clean_cli(res, 2, "init without a WIP checkpoint")
    check("checkpoint" in res.stderr or "run_id" in res.stderr,
          f"the missing run binding must be named: {res.stderr!r}")

    # An UNPARSEABLE task does not block the supervisor permit (it is not the anchor)…
    broken = tmp / "clean-checkout-broken-task"
    broken_state = broken / ".code-factory" / "state"
    broken_state.mkdir(parents=True)
    (broken / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: pre-flight\n", encoding="utf-8")
    (broken / TASK_REL).write_text("title: t\n", encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(broken)), 0, "init (broken task)")
    res = run("add", "--repo", str(broken), "--permit-id", "PB-supervisor", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "supervisor", "--phase", "analysis")
    expect_clean_cli(res, 0, "a supervisor bootstrap permit over an unparseable task")
    # …while the same tree refuses the task-anchored roles on the parse itself.
    res = run("add", "--repo", str(broken), "--permit-id", "PB-analyzer", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis")
    expect_clean_cli(res, 2, "an analyzer bootstrap permit over an unparseable task")
    check("parse" in res.stderr.lower(),
          f"the analyzer refusal must name the parse failure: {res.stderr!r}")


def test_supervisor_permit_without_run_id(tmp: pathlib.Path) -> None:
    """(review R2, critical) The pre-run supervisor permit needs NEITHER task NOR checkpoint.

    The supervisor begins before Phase 0: at that moment there is no parsed task AND no computed
    `run_id` — the WIP checkpoint does not exist yet. The launch-scoped bootstrap (`begin`'s own
    `begun_at`) is therefore the only authority available, so `init`/`add` must accept
    `--launch-dir`, anchor the supervisor permit to that bootstrap, and leave the run binding to
    the later `activate`. Analyzer/planner still answer the parsed TASK and stay anchored there.
    """
    clean = tmp / "clean-launch-repo"
    (clean / ".code-factory" / "state").mkdir(parents=True)
    launch = tmp / "clean-launch"
    launch.mkdir()

    # The supervisor begins first — run-id independently, as the flow mandates.
    began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin", "--launch-dir", str(launch)],
                           capture_output=True, text=True, errors="replace")
    expect_clean_cli(began, 0, "the supervisor begins on a clean launch directory")
    bootstrap = json.loads((launch / BOOT_REL).read_text(encoding="utf-8"))
    check(bootstrap["run_id"] is None and bootstrap["activated"] is None,
          f"the launch bootstrap exists BEFORE any run binding: {bootstrap!r}")
    check(not (clean / PIPELINE_REL).exists() and not (clean / TASK_REL).exists(),
          "the fixture must have NEITHER a checkpoint run_id NOR a parsed task")

    expect_clean_cli(run("init", "--repo", str(clean), "--launch-dir", str(launch)), 0,
                     "init before any run_id exists")
    data = permits(clean)
    check(data.get("run_id") in (None, ""),
          f"the pre-run registry carries no run_id yet: {data!r}")

    res = run("add", "--repo", str(clean), "--launch-dir", str(launch),
              "--permit-id", "PB-supervisor", "--kind", "bootstrap",
              "--task-id", "bootstrap", "--role", "supervisor", "--phase", "analysis")
    expect_clean_cli(res, 0, "a supervisor permit before the run id exists")
    permit = permits(clean)["permits"][0]
    check(permit["role"] == "supervisor" and permit["kind"] == "bootstrap"
          and permit["task_id"] == "bootstrap" and permit.get("run_id") is None,
          f"the pre-run supervisor permit answers the launch, not a run: {permit!r}")
    check(bootstrap["begun_at"] in json.dumps(permit),
          f"the permit must be anchored to the launch bootstrap it answers: {permit!r}")

    # The task anchor is unchanged for the roles that really answer the task.
    for role in ("analyzer", "planner"):
        res = run("add", "--repo", str(clean), "--launch-dir", str(launch),
                  "--permit-id", f"PB-{role}", "--kind", "bootstrap",
                  "--task-id", "bootstrap", "--role", role, "--phase", "analysis")
        expect_clean_cli(res, 2, f"a {role} bootstrap permit before the task is parsed")
        check("task" in res.stderr.lower(),
              f"the {role} refusal must name the missing task: {res.stderr!r}")

    # Without a begun bootstrap there is no authority to anchor the pre-run registry on.
    bare = tmp / "clean-launch-bare"
    (bare / ".code-factory" / "state").mkdir(parents=True)
    empty_launch = tmp / "clean-launch-empty"
    empty_launch.mkdir()
    res = run("init", "--repo", str(bare), "--launch-dir", str(empty_launch))
    expect_clean_cli(res, 2, "init with no begun launch bootstrap")
    check("bootstrap" in res.stderr.lower() or "begin" in res.stderr.lower(),
          f"the refusal must name the missing launch bootstrap: {res.stderr!r}")


def test_launch_only_registry_transfer(tmp: pathlib.Path) -> None:
    """(review R4, critical) The pre-run registry is LAUNCH-ONLY and is TRANSFERRED at binding.

    Phase 0a has no resolved `repo_path`, so passing the unresolved target as `--repo` to
    `init`/`add` was wrong twice over: it required a repository that does not exist yet, and it put
    the permit history somewhere else than the launch. The registry must be created and populated
    against the LAUNCH directory alone (no `--repo`), and the activation's `bind-run` must transfer
    that SAME registry — permits and their journal — to the resolved repository once its checkpoint
    names the run.
    """
    launch = tmp / "split-launch"
    launch.mkdir()
    target = tmp / "split-target"                       # NOT resolved yet: it does not exist

    began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                            "--launch-dir", str(launch)],
                           capture_output=True, text=True, errors="replace")
    expect_clean_cli(began, 0, "the supervisor begins on the launch directory")
    bootstrap = json.loads((launch / BOOT_REL).read_text(encoding="utf-8"))

    # 1. Launch-only registry: NO --repo at all, because no target exists yet.
    expect_clean_cli(run("init", "--launch-dir", str(launch)), 0,
                     "init against the launch directory only")
    check(not target.exists(), "the launch-only init must not need (or create) the target repository")
    launch_permits = launch / PERMITS_REL
    check(launch_permits.is_file(), f"the launch registry must live in the launch directory: "
                                    f"{launch_permits}")
    data = json.loads(launch_permits.read_text(encoding="utf-8"))
    check(data.get("run_id") in (None, ""), f"the launch registry is unbound: {data!r}")

    expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--kind", "bootstrap", "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0,
                     "a supervisor permit from the launch directory only")
    permit = json.loads(launch_permits.read_text(encoding="utf-8"))["permits"][0]
    check(permit["permit_id"] == "PB-supervisor" and permit["kind"] == "bootstrap"
          and bootstrap["begun_at"] in json.dumps(permit),
          f"the launch-only permit is anchored to the launch bootstrap: {permit!r}")

    # The unresolved target is still untouched: nothing was written under a not-yet-known repo.
    check(not target.exists(), "no target-side artifact may be created before repo resolution")
    # …and the task-anchored roles still refuse without the parsed task.
    res = run("add", "--launch-dir", str(launch), "--permit-id", "PB-analyzer", "--kind",
              "bootstrap", "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis")
    expect_clean_cli(res, 2, "an analyzer launch-only permit without the parsed task")
    check("task" in res.stderr.lower(), f"the analyzer refusal must name the task: {res.stderr!r}")

    # (review R5) The supervisor's verdict and its spawn binding happen in the LAUNCH registry —
    # before the target exists — and TRAVEL with it: the verdict precedes the spawn and the binding
    # names the agent it spawned, in the registry the transfer delivers.
    expect_clean_cli(run("verdict", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--verdict", "allow", "--evidence", "the launch bootstrap it answers"),
                     0, "the supervisor verdict in the launch registry")
    expect_clean_cli(run("bind", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--agent-id", "agent-sup"), 0,
                     "the spawn binding in the launch registry")
    judged = json.loads(launch_permits.read_text(encoding="utf-8"))["permits"][0]
    check(judged.get("verdict") == "allow" and judged.get("agent_id") == "agent-sup"
          and isinstance(judged.get("verdict_at_ms"), int),
          f"the launch registry carries the judged, bound permit before any transfer: {judged!r}")

    # 2. Now the repository is resolved and has a run: NEW tests must not weaken the old path.
    state = target / ".code-factory" / "state"
    state.mkdir(parents=True)
    (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w2\n", encoding="utf-8")
    (target / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
    check(not (target / PERMITS_REL).exists(),
          "the target must not have a second registry of its own before the binding")

    # 3. Activation TRANSFERS the same registry: same permits, now bound to the run.
    expect_clean_cli(run("bind-run", "--launch-dir", str(launch), "--repo", str(target)), 0,
                     "bind-run transfers the launch registry to the resolved repository")
    bound = permits(target)
    check(bound.get("run_id") == RUN_ID, f"the transferred registry is bound to the run: {bound!r}")
    check([item["permit_id"] for item in bound["permits"]] == ["PB-supervisor"]
          and bound["permits"][0]["role"] == "supervisor"
          and bound["permits"][0]["kind"] == "bootstrap",
          f"the SAME permit must survive the transfer, not a copy of a different registry: {bound!r}")
    ledger = target / LEDGER_REL
    check(ledger.is_file(), f"the registry's journal must travel with it: {ledger}")
    actions = [json.loads(line).get("action") for line in
               ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    check("bind-run" in actions, f"the transfer is a journaled bind-run transition: {actions!r}")
    # The launch registry keeps no permit the target did not receive (one registry, not a fork).
    moved = json.loads(launch_permits.read_text(encoding="utf-8")) if launch_permits.is_file() else {}
    check(not moved.get("permits") or moved.get("run_id") == RUN_ID,
          f"the launch registry is not left as a competing unbound fork: {moved!r}")

    # (review R5) The transferred verdict/binding satisfy the order audit: the verdict precedes the
    # spawn and the binding names it, judged from the wire that really ran.
    future = int(time.time() * 1000) + 60000
    directory = session(target, [("agent-sup", "factory-supervisor", future)])
    expect_clean_cli(audit(target, directory), 0,
                     "the transferred registry passes the order audit")


def test_transfer_failure_is_atomic(tmp: pathlib.Path) -> None:
    """(review R5, major) A failed transfer leaves BOTH registries intact and is retryable.

    The transfer copies the permits, copies the journal and binds the run as three writes. A fault
    after the first copy left a half-registry at the target: the source stayed but the retry was
    refused as "already exists", and the run had a registry nobody could finish writing. The
    transfer must be failure-atomic — a failed attempt leaves NO target artifact, the launch
    registry byte-identical and still unbound, and the same command can be retried successfully once
    the obstacle is gone. Both an injected journal-copy fault and an injected bind fault are
    exercised through the module API (a subprocess cannot fail mid-transaction).
    """
    def fixture(name: str) -> tuple[pathlib.Path, pathlib.Path, bytes, bytes | None]:
        launch = tmp / f"{name}-launch"
        launch.mkdir()
        target = tmp / f"{name}-target"
        state = target / ".code-factory" / "state"
        state.mkdir(parents=True)
        (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w2\n", encoding="utf-8")
        (target / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
        (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
        began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                                "--launch-dir", str(launch)],
                               capture_output=True, text=True, errors="replace")
        expect_clean_cli(began, 0, "the supervisor begins before the transfer")
        expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "the launch registry")
        expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                             "--kind", "bootstrap", "--task-id", "bootstrap",
                             "--role", "supervisor", "--phase", "analysis"), 0,
                         "the launch-only supervisor permit")
        permits_before = (launch / PERMITS_REL).read_bytes()
        ledger = launch / LEDGER_REL
        return launch, target, permits_before, ledger.read_bytes() if ledger.is_file() else None

    def assert_failure_atomic(label: str, launch: pathlib.Path, target: pathlib.Path,
                              permits_before: bytes, ledger_before: bytes | None) -> None:
        check(not (target / PERMITS_REL).exists(),
              f"{label}: a failed transfer must not leave a half-written target registry")
        check(not (target / LEDGER_REL).exists(),
              f"{label}: a failed transfer must not leave a half-written target journal")
        check((launch / PERMITS_REL).read_bytes() == permits_before,
              f"{label}: the launch registry must stay byte-identical")
        if ledger_before is not None:
            check((launch / LEDGER_REL).read_bytes() == ledger_before,
                  f"{label}: the launch journal must stay byte-identical")
        source = json.loads((launch / PERMITS_REL).read_text(encoding="utf-8"))
        check(source.get("run_id") in (None, ""),
              f"{label}: the source registry is still unbound after the failed attempt: {source!r}")
        check(not list((target / ".code-factory" / "state").glob("permits.transferred-*")),
              f"{label}: a failed transfer must not archive a fake destination")

    def retry_succeeds(label: str, launch: pathlib.Path, target: pathlib.Path) -> None:
        expect_clean_cli(run("bind-run", "--launch-dir", str(launch), "--repo", str(target)), 0,
                         f"{label}: the retried transfer")
        retried = permits(target)
        check(retried.get("run_id") == RUN_ID
              and [item["permit_id"] for item in retried["permits"]] == ["PB-supervisor"],
              f"{label}: the retried transfer delivers the same registry: {retried!r}")
        check(not (launch / PERMITS_REL).is_file(),
              f"{label}: the successful transfer retires the launch copy")

    # 1. The JOURNAL copy fails after the permits copy: the target must be rolled back.
    launch, target, permits_before, ledger_before = fixture("atomic-copy")
    original_copy = pg._copy_atomic
    calls = {"count": 0}

    def flaky_copy(source: pathlib.Path, destination: pathlib.Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise pg.PermitError("injected failure: the journal copy")
        original_copy(source, destination)

    pg._copy_atomic = flaky_copy
    try:
        pg.bind_run(str(target), launch_dir=str(launch))
    except pg.PermitError as exc:
        check("injected" in str(exc), f"the injected fault must be the failure: {exc}")
    else:
        raise AssertionError("the injected journal-copy fault must fail the transfer")
    finally:
        pg._copy_atomic = original_copy
    assert_failure_atomic("journal copy", launch, target, permits_before, ledger_before)
    retry_succeeds("journal copy", launch, target)

    # 2. The BIND fails after both copies: the target must be rolled back too.
    launch, target, permits_before, ledger_before = fixture("atomic-bind")
    original_bind = pg._bind_in_place

    def flaky_bind(root: pathlib.Path, run_id: str | None = None) -> dict:
        raise pg.PermitError("injected failure: the run binding")

    pg._bind_in_place = flaky_bind
    try:
        pg.bind_run(str(target), launch_dir=str(launch))
    except pg.PermitError as exc:
        check("injected" in str(exc), f"the injected bind fault must be the failure: {exc}")
    else:
        raise AssertionError("the injected bind fault must fail the transfer")
    finally:
        pg._bind_in_place = original_bind
    assert_failure_atomic("bind", launch, target, permits_before, ledger_before)
    retry_succeeds("bind", launch, target)


def test_retirement_failure_is_atomic(tmp: pathlib.Path) -> None:
    """(review R6, major) A SOURCE-RETIREMENT fault is inside the transaction too.

    The copy/bind writes were already failure-atomic, but the two retirement renames sat outside
    that transaction: a fault in the first left a BOUND target plus a LIVE launch registry (a
    competing registry), and a fault in the second left the permits archived while the journal was
    still live — a half-retired source that could not be retried. Both renames belong to the same
    transaction: every failure leaves the launch registry intact and unbound, no target artifact and
    no archive half-way, and the same command succeeds on retry.
    """
    def fixture(name: str) -> tuple[pathlib.Path, pathlib.Path, bytes, bytes]:
        launch = tmp / f"{name}-launch"
        launch.mkdir()
        target = tmp / f"{name}-target"
        (target / ".code-factory" / "state").mkdir(parents=True)
        (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w2\n", encoding="utf-8")
        (target / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
        (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
        began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                                "--launch-dir", str(launch)],
                               capture_output=True, text=True, errors="replace")
        expect_clean_cli(began, 0, "the supervisor begins before the transfer")
        expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "the launch registry")
        expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                             "--kind", "bootstrap", "--task-id", "bootstrap",
                             "--role", "supervisor", "--phase", "analysis"), 0,
                         "the launch-only supervisor permit")
        return (launch, target, (launch / PERMITS_REL).read_bytes(),
                (launch / LEDGER_REL).read_bytes())

    def inject(path: pathlib.Path, label: str, launch: pathlib.Path, target: pathlib.Path,
               permits_before: bytes, ledger_before: bytes) -> None:
        original = pg.os.replace

        def flaky_replace(source, destination):
            if pathlib.Path(source) == path:
                raise OSError(f"injected failure: the {label} retirement")
            return original(source, destination)

        pg.os.replace = flaky_replace
        try:
            pg.bind_run(str(target), launch_dir=str(launch))
        except pg.PermitError as exc:
            check("retire" in str(exc).lower() or "injected" in str(exc).lower(),
                  f"the {label} retirement fault must be reported: {exc}")
        else:
            raise AssertionError(f"the injected {label} retirement fault must fail the transfer")
        finally:
            pg.os.replace = original

        # Consistent state: no bound target, no half-retired source, no stray archive.
        check(not (target / PERMITS_REL).exists() and not (target / LEDGER_REL).exists(),
              f"{label} retirement: a failed transfer must leave NO target registry — a bound "
              f"target beside a live launch registry is a competing registry")
        check((launch / PERMITS_REL).is_file() and (launch / LEDGER_REL).is_file(),
              f"{label} retirement: the launch registry and journal must both still exist")
        check((launch / PERMITS_REL).read_bytes() == permits_before,
              f"{label} retirement: the launch registry must stay byte-identical")
        check((launch / LEDGER_REL).read_bytes() == ledger_before,
              f"{label} retirement: the launch journal must stay byte-identical")
        source = json.loads((launch / PERMITS_REL).read_text(encoding="utf-8"))
        check(source.get("run_id") in (None, ""),
              f"{label} retirement: the source registry must stay unbound: {source!r}")
        state = launch / ".code-factory" / "state"
        check(not list(state.glob("permits.transferred-*")),
              f"{label} retirement: a failed transfer must not leave a half-retired archive")

        # Retryable: the SAME command completes the transfer.
        expect_clean_cli(run("bind-run", "--launch-dir", str(launch), "--repo", str(target)), 0,
                         f"{label} retirement: the retried transfer")
        retried = permits(target)
        check(retried.get("run_id") == RUN_ID
              and [item["permit_id"] for item in retried["permits"]] == ["PB-supervisor"],
              f"{label} retirement: the retried transfer delivers the same registry: {retried!r}")
        check(not (launch / PERMITS_REL).is_file(),
              f"{label} retirement: the successful retry retires the launch copy")

    # 1. The first retirement rename — the permits file — fails.
    launch, target, permits_before, ledger_before = fixture("retire-permits")
    inject(launch / PERMITS_REL, "permits", launch, target, permits_before, ledger_before)
    # 2. The second retirement rename — the journal — fails after the permits rename succeeded.
    launch, target, permits_before, ledger_before = fixture("retire-ledger")
    inject(launch / LEDGER_REL, "journal", launch, target, permits_before, ledger_before)


def test_rollback_restoration_failure_is_reported(tmp: pathlib.Path) -> None:
    """(review R7, major) A FAILED rollback is reported truthfully, never as a clean restore.

    `_untransfer` swallowed every OSError, so when the restoration rename itself failed the launch
    registry stayed in its archive while `bind_run` promised "restored unchanged … retry" — a false
    claim that also deleted the only other copy at the target. A rollback that cannot complete must
    say so, name where the launch registry actually is, and PRESERVE the target registry as evidence
    instead of pretending the transfer never happened.
    """
    launch = tmp / "rollback-launch"
    launch.mkdir()
    target = tmp / "rollback-target"
    (target / ".code-factory" / "state").mkdir(parents=True)
    (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w2\n", encoding="utf-8")
    (target / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                                     "--launch-dir", str(launch)],
                                    capture_output=True, text=True, errors="replace"), 0,
                     "the supervisor begins")
    expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "the launch registry")
    expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--kind", "bootstrap", "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0, "the launch-only supervisor permit")
    archive_permits, _archive_ledger = pg._transferred_paths(launch, RUN_ID)

    original = pg.os.replace

    def flaky_replace(source, destination):
        path = pathlib.Path(source)
        if path == launch / LEDGER_REL:
            raise OSError("injected failure: the journal retirement")
        if path == archive_permits:
            raise OSError("injected failure: the launch-copy restoration")
        return original(source, destination)

    pg.os.replace = flaky_replace
    try:
        pg.bind_run(str(target), launch_dir=str(launch))
    except pg.PermitError as exc:
        message = str(exc)
    else:
        raise AssertionError("the injected retirement/restoration faults must fail the transfer")
    finally:
        pg.os.replace = original

    # The claim must be TRUE: no "restored unchanged" promise, and the archive is named.
    lowered = message.lower()
    check("restored unchanged" not in lowered and "retry `bind-run" not in lowered,
          f"an incomplete rollback must not claim a clean restore and a plain retry: {message!r}")
    check(str(archive_permits) in message or any(
        word in lowered for word in ("could not be restored", "incomplete", "recover", "archive")),
          f"the failure must say the launch registry was NOT restored and where it is: {message!r}")
    # The surviving evidence is preserved: the launch copy sits in its archive, and the target
    # registry is NOT deleted while the source is incomplete.
    check(archive_permits.is_file(),
          f"the launch registry must remain in its archive after the failed restoration: "
          f"{archive_permits}")
    check((target / PERMITS_REL).exists(),
          "the target registry is the remaining evidence of the run and must be preserved when the "
          "source could not be restored")


def test_target_cleanup_failure_is_reported(tmp: pathlib.Path) -> None:
    """(review R7, major) A target-cleanup OSError is aggregated, not silently swallowed.

    When the rollback's `unlink` of the target registry failed, `_untransfer` ignored it and
    `bind_run` reported "nothing was left at <target>" while the target registry was still there —
    the retry then refused on the leftover. The cleanup failure must be part of the reported result,
    naming the path that remains, so the operator sees the actual state.
    """
    launch = tmp / "cleanup-launch"
    launch.mkdir()
    target = tmp / "cleanup-target"
    (target / ".code-factory" / "state").mkdir(parents=True)
    (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: w2\n", encoding="utf-8")
    (target / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                                     "--launch-dir", str(launch)],
                                    capture_output=True, text=True, errors="replace"), 0,
                     "the supervisor begins")
    expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "the launch registry")
    expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--kind", "bootstrap", "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0, "the launch-only supervisor permit")
    permits_before = (launch / PERMITS_REL).read_bytes()

    original_copy = pg._copy_atomic
    original_unlink = pg.pathlib.Path.unlink
    leftover = target / PERMITS_REL
    state = {"copies": 0}

    def flaky_copy(source: pathlib.Path, destination: pathlib.Path) -> None:
        state["copies"] += 1
        if state["copies"] == 2:        # the permits copy landed, the journal copy fails
            raise pg.PermitError("injected failure: the transfer was interrupted")
        return original_copy(source, destination)

    def flaky_unlink(self, *args, **kwargs):
        if pathlib.Path(self) == leftover:
            raise OSError("injected failure: the target cleanup")
        return original_unlink(self, *args, **kwargs)

    pg._copy_atomic = flaky_copy
    pg.pathlib.Path.unlink = flaky_unlink
    try:
        pg.bind_run(str(target), launch_dir=str(launch))
    except pg.PermitError as exc:
        message = str(exc)
    else:
        raise AssertionError("the injected copy/cleanup faults must fail the transfer")
    finally:
        pg._copy_atomic = original_copy
        pg.pathlib.Path.unlink = original_unlink

    lowered = message.lower()
    check("nothing was left" not in lowered,
          f"the failure must not claim the target was cleaned when its unlink failed: {message!r}")
    check(str(leftover) in message or any(
        word in lowered for word in ("could not be removed", "could not be deleted", "left behind",
                                     "cleanup", "clean up")),
          f"the failure must name the target artifact that remains: {message!r}")
    check(leftover.exists(),
          "the leftover target registry must really still exist — the report must match the state")
    check((launch / PERMITS_REL).read_bytes() == permits_before,
          "the launch registry must stay byte-identical after the cleanup failure")


def test_ledger_legacy_snapshot(tmp: pathlib.Path) -> None:
    """(failing-first) A PRE-JOURNAL registry is attested as it stands — never re-invented.

    A run that started before this journal has real permits and no transition history. Refusing
    every write forever is not honesty either: the run needs ONE explicit transition that says
    "these records exist, their earlier history is unproven". `snapshot-legacy` is that transition —
    it leaves `permits.yaml` byte-identical, writes a single `snapshot` event stamped NOW (no
    `init`/`add`/`verdict`/`bind` ever claims a time it did not happen at), refuses a second
    snapshot, and does not launder a single existing violation.
    """
    future = int(time.time() * 1000) + 60000

    def legacy(name: str, permits_in: list[dict]) -> pathlib.Path:
        """A registry an earlier factory wrote: no journal, permits with their own history."""
        root = tmp / name
        state = root / ".code-factory" / "state"
        state.mkdir(parents=True)
        (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: implement\n",
                                         encoding="utf-8")
        (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
        write_permits(root, {"run_id": RUN_ID, "permits": permits_in})
        return root

    def permit(permit_id: str, agent_id: str | None, verdict: str = "allow",
               at: str = "2026-11-20T09:00:00Z") -> dict:
        return {"permit_id": permit_id, "kind": "plan", "task_id": "task_09", "role": "coder",
                "phase": "implement", "scope": ["manifest.py"], "constraints": [],
                "created_at": "2026-11-20T08:59:00Z", "verdict": verdict,
                "evidence": "recorded by the earlier factory", "verdict_at": at,
                "verdict_at_ms": 1763629200000, "agent_id": agent_id,
                "bound_at": "2026-11-20T09:01:00Z" if agent_id else None, "closed": None}

    # 1. Before the snapshot the run cannot write: an unjournaled registry is unproven history.
    root = legacy("legacy-snapshot", [permit("P1", "agent-3"), permit("P2", "agent-4")])
    directory = session(root, [("agent-3", "factory-coder", future),
                               ("agent-4", "factory-coder", future)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a pre-journal registry")
    ledger_violation(res, "a pre-journal registry")
    res = run("add", "--repo", str(root), "--permit-id", "P3", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "manifest.py")
    expect_clean_cli(res, 2, "an add on a pre-journal registry")
    ledger_violation(res, "an add on a pre-journal registry")
    check("snapshot-legacy" in res.stderr,
          f"the refusal must name the honest remedy: {res.stderr!r}")

    # 2. The snapshot attests the file AS IT STANDS.
    before = (root / PERMITS_REL).read_bytes()
    res = run("snapshot-legacy", "--repo", str(root), "--note", "pre-upgrade run")
    expect_clean_cli(res, 0, "snapshot-legacy")
    check((root / PERMITS_REL).read_bytes() == before,
          "a snapshot must never rewrite the registry it attests")
    lines = (root / LEDGER_REL).read_text(encoding="utf-8").splitlines()
    check(len(lines) == 1, f"a snapshot is ONE event, not one per permit: {lines!r}")
    event = json.loads(lines[0])
    check(event["action"] == "snapshot" and event["permit_id"] is None,
          f"the event must be marked as a snapshot, not as a transition: {event!r}")
    check("unproven" in (event["note"] or "").lower() and "pre-upgrade run" in event["note"],
          f"the marking must say the earlier history is unproven: {event.get('note')!r}")
    check(event["seq"] == 1 and event["prev"] == "0" * 64,
          f"the snapshot is the chain's genesis: {event!r}")
    recorded = event["doc"]
    check([item["created_at"] for item in recorded["permits"]]
          == ["2026-11-20T08:59:00Z"] * 2
          and [item["verdict_at"] for item in recorded["permits"]]
          == ["2026-11-20T09:00:00Z"] * 2,
          f"the recorded state must be the file's own, never re-stamped: {recorded!r}")
    check(event["at"] > "2026-11-20T09:01:00Z",
          f"the snapshot is stamped NOW, never back-dated: {event['at']!r}")

    # 3. …and the attested registry is a usable, honest run again: appends continue the chain.
    expect_clean_cli(audit(root, directory), 0, "the attested registry")
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "P3", "--task-id", "task_09",
                         "--role", "coder", "--phase", "implement", "--scope", "manifest.py"), 0,
                     "a write after the snapshot")
    grown = [json.loads(line)
             for line in (root / LEDGER_REL).read_text(encoding="utf-8").splitlines()]
    check(len(grown) == 2 and grown[1]["prev"] == grown[0]["hash"]
          and grown[1]["action"] == "add",
          f"the post-snapshot write must continue the chain: {grown!r}")

    # 4. A second snapshot is refused, and the journal is untouched.
    written = (root / LEDGER_REL).read_bytes()
    res = run("snapshot-legacy", "--repo", str(root))
    expect_clean_cli(res, 2, "a second snapshot")
    ledger_violation(res, "a second snapshot")
    check((root / LEDGER_REL).read_bytes() == written,
          "a refused snapshot must not touch the journal")

    # 5. The attestation is not a laundromat: an existing violation still fails the audit, and an
    #    edit after the snapshot is drift like any other.
    dirty = legacy("legacy-snapshot-dirty", [permit("PD", "agent-d", verdict="deny")])
    expect_clean_cli(run("snapshot-legacy", "--repo", str(dirty)), 0, "snapshot (dirty registry)")
    res = audit(dirty, session(dirty, [("agent-d", "factory-coder", future)]))
    expect_clean_cli(res, 1, "a denied-but-spawned permit of a pre-journal registry")
    check("denied permit executed" in res.stdout,
          f"the snapshot must not excuse the real violation: {res.stdout!r}")
    mutate(dirty, "PD", evidence="reworded after the snapshot")
    res = audit(dirty, session(dirty, [("agent-d", "factory-coder", future)]))
    expect_clean_cli(res, 1, "an edit after the snapshot")
    ledger_violation(res, "an edit after the snapshot")

    # 6. The command's own refusals: another run's registry, an empty one, and none at all.
    other = legacy("legacy-snapshot-other", [permit("P1", None)])
    (other / PIPELINE_REL).write_text("run_id: 20261104-b5b601f6\n", encoding="utf-8")
    res = run("snapshot-legacy", "--repo", str(other))
    expect_clean_cli(res, 2, "a snapshot of another run's registry")
    check("20261104-b5b601f6" in res.stderr, f"the refusal must name the run: {res.stderr!r}")
    empty = legacy("legacy-snapshot-empty", [])
    res = run("snapshot-legacy", "--repo", str(empty))
    expect_clean_cli(res, 2, "a snapshot of an empty registry")
    check("init" in res.stderr, f"the remedy must be named: {res.stderr!r}")
    bare = tmp / "legacy-snapshot-bare"
    (bare / ".code-factory" / "state").mkdir(parents=True)
    (bare / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    res = run("snapshot-legacy", "--repo", str(bare))
    expect_clean_cli(res, 2, "a snapshot without a registry")
    check(not (bare / LEDGER_REL).exists(), "a refused snapshot must not create a journal")


def test_launch_scoped_binding(tmp: pathlib.Path) -> None:
    """(review R2, critical) The launch-scoped registry is bound to its run ONCE, honestly.

    `init --launch-dir` creates the registry unbound, so the run's permits exist before any run
    does. The binding is the activation's job: `bind-run` must match the checkpoint that activation
    wrote, happen at most once, write atomically and journal its OWN transition — the pre-run
    permits keep every timestamp they were recorded with, and a hand-edited binding is drift.
    """
    root = tmp / "launch-bind"
    (root / ".code-factory" / "state").mkdir(parents=True)
    launch = tmp / "launch-bind-dir"
    launch.mkdir()
    began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin", "--launch-dir", str(launch)],
                           capture_output=True, text=True, errors="replace")
    expect_clean_cli(began, 0, "begin before the binding")
    expect_clean_cli(run("init", "--repo", str(root), "--launch-dir", str(launch)), 0,
                     "init before the run id exists")
    expect_clean_cli(run("add", "--repo", str(root), "--launch-dir", str(launch),
                         "--permit-id", "PB-supervisor", "--kind", "bootstrap",
                         "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0, "the pre-run supervisor permit")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "PB-supervisor",
                         "--verdict", "allow",
                         "--evidence", "the run's own supervisor authority (launch bootstrap)"), 0,
                     "the supervisor's verdict precedes its spawn")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "PB-supervisor",
                         "--agent-id", "agent-sup"), 0, "the supervisor's spawn is bound")

    # An unbound registry authorizes nothing: the audit says so and names the binding.
    directory = session(root, [("agent-sup", "factory-supervisor",
                                int(time.time() * 1000) + 60000)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "an unbound launch-scoped registry")
    check("unbound" in res.stdout and "bind-run" in res.stdout,
          f"the audit must name the missing binding and its command: {res.stdout!r}")
    check("permit-less" not in res.stdout,
          f"the unbound verdict replaces the per-spawn evaluation: {res.stdout!r}")

    # The binding needs the run the activation recorded.
    res = run("bind-run", "--repo", str(root))
    expect_clean_cli(res, 2, "a binding without a run")
    check("checkpoint" in res.stderr or "run_id" in res.stderr,
          f"the missing run binding must be named: {res.stderr!r}")

    pre_run = permits(root)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    res = run("bind-run", "--repo", str(root))
    expect_clean_cli(res, 0, "bind-run at activation")
    bound = permits(root)
    check(bound["run_id"] == RUN_ID, f"the registry must be bound to the run: {bound!r}")
    check(bound["permits"] == pre_run["permits"],
          f"binding must not re-stamp the pre-run permits: {bound['permits']!r}")
    events = [json.loads(line) for line in (root / LEDGER_REL).read_text(
        encoding="utf-8").splitlines()]
    check([event["action"] for event in events]
          == ["init", "add", "verdict", "bind", "bind-run"],
          f"the binding is its OWN journaled transition: {[e['action'] for e in events]!r}")
    check(events[-1]["prev"] == events[-2]["hash"] and events[-1]["state"]
          != events[-2]["state"],
          f"the binding must continue the chain: {events[-1]!r}")
    check(events[-1]["doc"]["permits"] == events[-2]["doc"]["permits"]
          and events[-1]["doc"]["run_id"] != events[-2]["doc"]["run_id"],
          f"the binding changes the RUN only, never an earlier transition: {events[-1]!r}")

    # …and the attestation holds: the run's own wire now passes (the plan exists by finish time).
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(audit(root, directory), 0, "the bound registry")
    res = run("bind-run", "--repo", str(root))
    expect_clean_cli(res, 0, "a repeated bind-run")
    check(payload(res)["status"] == "unchanged", f"one binding per registry: {res.stdout!r}")
    res = run("bind-run", "--repo", str(root), "--run-id", "20261104-b5b601f6")
    expect_clean_cli(res, 2, "a binding to another run")
    check("20261104-b5b601f6" in res.stderr, f"the wrong run must be named: {res.stderr!r}")

    # A hand-edited binding is drift: the history says which run the registry was bound to.
    data = permits(root)
    data["run_id"] = "20261104-b5b601f6"
    write_permits(root, data)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a hand-edited run binding")
    ledger_violation(res, "a hand-edited run binding")


def test_launch_transfer_guards(tmp: pathlib.Path) -> None:
    """(review R4) The transfer is a MOVE of one registry: no merge, no second transfer.

    `bind-run --launch-dir --repo` must carry the identical permits and the identical journal to the
    resolved repository, retire the launch copy to an archive (never leave a competing registry) and
    refuse to write over a registry the target already has.
    """
    launch = tmp / "guard-launch"
    launch.mkdir()
    began = subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin", "--launch-dir", str(launch)],
                           capture_output=True, text=True, errors="replace")
    expect_clean_cli(began, 0, "begin for the transfer guards")
    expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "launch-only init")
    expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--kind", "bootstrap", "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0, "launch-only add")
    source_permits = (launch / PERMITS_REL).read_bytes()
    source_ledger = (launch / LEDGER_REL).read_bytes()

    # A target that ALREADY has a registry is never overwritten or merged into.
    occupied = tmp / "guard-occupied"
    (occupied / ".code-factory" / "state").mkdir(parents=True)
    (occupied / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    (occupied / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(occupied)), 0, "init (occupied target)")
    own = (occupied / PERMITS_REL).read_bytes()
    res = run("bind-run", "--launch-dir", str(launch), "--repo", str(occupied))
    expect_clean_cli(res, 2, "a transfer onto an existing registry")
    check("already exists" in res.stderr, f"the refusal must name the conflict: {res.stderr!r}")
    check((occupied / PERMITS_REL).read_bytes() == own,
          "a refused transfer must not touch the target's registry")
    check((launch / PERMITS_REL).read_bytes() == source_permits,
          "a refused transfer must leave the launch registry in place")

    # The real transfer: the SAME records and journal arrive, the launch copy is retired.
    target = tmp / "guard-target"
    (target / ".code-factory" / "state").mkdir(parents=True)
    (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    (target / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("bind-run", "--launch-dir", str(launch), "--repo", str(target)), 0,
                     "the transfer")
    moved = permits(target)
    source = json.loads(source_permits.decode("utf-8"))
    check(moved["run_id"] == RUN_ID
          and [item["permit_id"] for item in moved["permits"]]
          == [item["permit_id"] for item in source["permits"]]
          and moved["permits"][0]["created_at"] == source["permits"][0]["created_at"],
          f"the identical permit must arrive, not a re-created one: {moved!r}")
    copied = (target / LEDGER_REL).read_bytes()
    check(copied.startswith(source_ledger),
          "the journal must travel verbatim, with the binding appended to it")
    check(len(copied.splitlines()) == len(source_ledger.splitlines()) + 1,
          "the transfer adds exactly the ONE bind-run transition")
    check(not (launch / PERMITS_REL).exists() and not (launch / LEDGER_REL).exists(),
          "the launch copy must be retired, never left as a second registry")
    archived = sorted(path.name for path in
                      (launch / PERMITS_REL.parent).glob("permits*transferred-*"))
    check(len(archived) == 2 and all(RUN_ID in name for name in archived),
          f"the launch history is archived under its run: {archived!r}")

    # …and a second transfer of the same launch registry is impossible.
    res = run("bind-run", "--launch-dir", str(launch), "--repo", str(target))
    expect_clean_cli(res, 2, "a repeated transfer")
    check((target / LEDGER_REL).read_bytes() == copied,
          "a refused transfer must leave the target untouched")


def test_launch_lifecycle_arguments(tmp: pathlib.Path) -> None:
    """(review R5) `verdict`/`bind` act on ONE named registry — the launch's, before the transfer.

    The supervisor's verdict and its spawn binding must be recordable in the launch-only registry
    (no target exists yet) and must NOT silently land in a different registry: the command takes
    `--repo` or `--launch-dir`, never both, never neither. A rollback after a fault leaves no
    temporary file behind either.
    """
    launch = tmp / "life-launch"
    launch.mkdir()
    expect_clean_cli(subprocess.run([sys.executable, str(WATCHDOG_TOOL), "begin",
                                     "--launch-dir", str(launch)], capture_output=True, text=True,
                                    errors="replace"), 0, "begin (lifecycle fixtures)")
    expect_clean_cli(run("init", "--launch-dir", str(launch)), 0, "launch-only init")
    expect_clean_cli(run("add", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--kind", "bootstrap", "--task-id", "bootstrap", "--role", "supervisor",
                         "--phase", "analysis"), 0, "launch-only add")

    # Binding an unjudged permit is refused, in the launch registry like anywhere else.
    res = run("bind", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
              "--agent-id", "agent-sup")
    expect_clean_cli(res, 2, "binding a permit the supervisor has not judged")
    check("not allowed" in res.stderr, f"the verdict rule must still hold: {res.stderr!r}")

    # The launch registry and a run's registry are DIFFERENT registries.
    other = tmp / "life-other"
    (other / ".code-factory" / "state").mkdir(parents=True)
    (other / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    (other / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(other)), 0, "the run's own registry")
    for label, extra in (("both roots", ("--repo", str(other), "--launch-dir", str(launch))),
                         ("no root", ())):
        res = run("verdict", *extra, "--permit-id", "PB-supervisor", "--verdict", "allow",
                  "--evidence", "x")
        expect_clean_cli(res, 2, f"verdict with {label}")
        check("ONE registry" in res.stderr or "--repo" in res.stderr,
              f"the refusal must name the registry rule: {res.stderr!r}")
        res = run("bind", *extra, "--permit-id", "PB-supervisor", "--agent-id", "agent-sup")
        expect_clean_cli(res, 2, f"bind with {label}")

    # The verdict lands in the launch registry only, and its evidence is there.
    expect_clean_cli(run("verdict", "--launch-dir", str(launch), "--permit-id", "PB-supervisor",
                         "--verdict", "allow", "--evidence", "the launch bootstrap it answers"), 0,
                     "the launch verdict")
    check(permits(launch)["permits"][0]["verdict"] == "allow"
          and permits(other)["permits"] == [],
          "the verdict must land in the registry it names, never in another one")

    # A fault during the transfer leaves no temporary file in the target.
    target = tmp / "life-target"
    (target / ".code-factory" / "state").mkdir(parents=True)
    (target / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\n", encoding="utf-8")
    original = pg._bind_in_place

    def failing(root: pathlib.Path, run_id: str | None = None) -> dict:
        raise pg.PermitError("injected failure: leave nothing behind")

    pg._bind_in_place = failing
    try:
        pg.bind_run(str(target), launch_dir=str(launch))
    except pg.PermitError:
        pass
    else:
        raise AssertionError("the injected fault must fail the transfer")
    finally:
        pg._bind_in_place = original
    check(not list((target / PERMITS_REL).parent.glob("*.tmp")),
          "a rolled-back transfer must not leave a temporary file behind")
    expect_clean_cli(run("bind-run", "--launch-dir", str(launch), "--repo", str(target)), 0,
                     "the retried transfer after the fault")
    check(permits(target)["permits"][0]["verdict"] == "allow",
          "the transferred registry keeps the verdict recorded at the launch")


LEDGER_WORDS = ("integrity", "chain", "truncat", "tamper", "append-only", "history")


def ledger_violation(res: subprocess.CompletedProcess[str], label: str) -> None:
    """A refused/reset ledger must be refused AS a ledger violation.

    The downstream symptoms of a reset (a permit-less delegation, an unused permit) are already
    reported today; what is missing is that the run can tell the owner its PERMIT HISTORY was
    rewritten. So the message has to name the ledger itself, not just the symptom.
    """
    text = (res.stdout + res.stderr).lower()
    check(any(word in text for word in LEDGER_WORDS),
          f"{label}: the failure must be attributed to the permit ledger "
          f"({', '.join(LEDGER_WORDS)}), got stdout={res.stdout!r} stderr={res.stderr!r}")


def test_ledger_reset_and_reinit(tmp: pathlib.Path) -> None:
    """(failing-first) A deny -> delete -> re-init -> recreate manoeuvre must stay visible.

    The supervisor's early deny leaves nothing to repair in a ledger that can be thrown away: the
    flow deletes `permits.yaml`, re-initialises it and re-registers the same permit as if it had
    been allowed from the start. Nothing in the file itself records the loss, so the run must
    verify the ledger BEFORE every write and at the finish audit, and refuse to append to, or pass,
    a registry whose history no longer continues the one the run already recorded.
    """
    future = int(time.time() * 1000) + 60000
    root = repo(tmp, "ledger-reset")
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-3"), 0, "bind")
    directory = session(root, [("agent-3", "factory-coder", future)])
    expect_clean_cli(audit(root, directory), 0, "the intact ledger")
    legitimate = (root / PERMITS_REL).read_bytes()

    # The reset: the whole registry replaced by the empty skeleton a fresh `init` writes.
    write_permits(root, {"run_id": RUN_ID, "permits": []})
    before = (root / PERMITS_REL).read_bytes()
    res = run("add", "--repo", str(root), "--permit-id", "P2", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "test_manifest.py")
    expect_clean_cli(res, 2, "an add on top of a reset ledger")
    ledger_violation(res, "an add on top of a reset ledger")
    check((root / PERMITS_REL).read_bytes() == before,
          "a refused write must leave the reset ledger byte-identical")

    # The recreate: the same records re-registered under fresh timestamps. The bytes differ from
    # the history the run recorded, so the audit must not accept the rebuilt file as the run's.
    recreated = json.loads(legitimate.decode("utf-8"))
    for permit in recreated["permits"]:
        permit["created_at"] = "2099-01-01T00:00:00Z"
        permit["verdict_at"] = "2099-01-01T00:00:01Z"
    write_permits(root, recreated)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a recreated ledger")
    ledger_violation(res, "a recreated ledger")


def test_ledger_truncation_and_drift(tmp: pathlib.Path) -> None:
    """(failing-first) Truncation, hand-edited fields and a post-deny repair are all visible.

    Today the audit judges only the CURRENT content of the file: a truncated tail (the latest
    transition dropped), one rewritten persisted field (the evidence reworded), or a DENIED permit
    repaired into an ALLOW plus a spawn all load as a perfectly valid ledger. A run that silently
    changed its own history therefore finishes green. The append-only ledger must fail each of them
    and must not let a later append paper over the gap.
    """
    future = int(time.time() * 1000) + 60000
    root = repo(tmp, "ledger-trunc")
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-3"), 0, "bind P1")
    allow(root, "P2", scope=("test_manifest.py",))
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P2", "--agent-id",
                         "agent-4"), 0, "bind P2")
    directory = session(root, [("agent-3", "factory-coder", future),
                               ("agent-4", "factory-coder", future)])
    expect_clean_cli(audit(root, directory), 0, "the intact two-transition ledger")
    intact = json.loads((root / PERMITS_REL).read_text(encoding="utf-8"))

    # (a) Truncation: only the latest transition is dropped.
    write_permits(root, {"run_id": intact["run_id"], "permits": [intact["permits"][0]]})
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a truncated ledger")
    ledger_violation(res, "a truncated ledger")

    # (b) A new append does not paper over the truncated tail.
    before = (root / PERMITS_REL).read_bytes()
    res = run("add", "--repo", str(root), "--permit-id", "P3", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "manifest.py")
    expect_clean_cli(res, 2, "an add on top of a truncated ledger")
    ledger_violation(res, "an add on top of a truncated ledger")
    check((root / PERMITS_REL).read_bytes() == before,
          "a refused write must leave the truncated ledger byte-identical")

    # (c) Projection drift: ONE persisted field rewritten, the rest untouched. `evidence` is not
    #     consulted by the current audit, so this file passes today.
    drifted = json.loads(json.dumps(intact))
    drifted["permits"][1]["evidence"] = "reworded after the delegation happened"
    write_permits(root, drifted)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a drifted ledger")
    ledger_violation(res, "a drifted ledger")

    # Restoring the recorded ledger heals the run: the check is content, never a timestamp.
    write_permits(root, intact)
    expect_clean_cli(audit(root, directory), 0, "the restored ledger")

    # (d) Post-deny replacement: the DENY is repaired into an ALLOW plus an agent id. The CLI
    #     cannot produce this state (`verdict` refuses to follow a spawn, `bind` refuses a denied
    #     permit), so the fixture writes it — and the audit must still see it.
    denied = repo(tmp, "ledger-post-deny")
    expect_clean_cli(run("add", "--repo", str(denied), "--permit-id", "PD", "--task-id",
                         "task_09", "--role", "coder", "--phase", "implement", "--scope",
                         "manifest.py"), 0, "add PD")
    expect_clean_cli(run("verdict", "--repo", str(denied), "--permit-id", "PD", "--verdict",
                         "deny", "--evidence", "the supervisor refused the delegation"), 0,
                     "deny PD")
    data = permits(denied)
    data["permits"][0].update(verdict="allow", evidence="repaired after the fact",
                              verdict_at="2099-01-01T00:00:00Z", verdict_at_ms=future - 1000,
                              agent_id="agent-d", bound_at="2099-01-01T00:00:01Z")
    write_permits(denied, data)
    directory = session(denied, [("agent-d", "factory-coder", future)])
    res = audit(denied, directory)
    expect_clean_cli(res, 1, "a post-deny repair")
    ledger_violation(res, "a post-deny repair")


def test_ledger_chain(tmp: pathlib.Path) -> None:
    """(failing-first) The journal ITSELF is the proof: an edited line or a deleted registry fails.

    The registry and the journal are two files, so the abuse can target either. A journal line
    rewritten by hand breaks its own hash and the link of every line after it; deleting the registry
    while the journal survives removes the state the run recorded. Both are refused by the audit and
    by the next write, and the honest journal of a run that did nothing wrong passes.
    """
    future = int(time.time() * 1000) + 60000
    root = repo(tmp, "ledger-chain")
    allow(root, "P1")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-3"), 0, "bind")
    directory = session(root, [("agent-3", "factory-coder", future)])
    expect_clean_cli(audit(root, directory), 0, "the intact chain")
    journal = root / LEDGER_REL
    lines = journal.read_text(encoding="utf-8").splitlines()
    check(len(lines) >= 4, f"init+add+verdict+bind must be four transitions: {lines!r}")
    entries = [json.loads(line) for line in lines]
    check(all(entries[index]["prev"] == entries[index - 1]["hash"]
              for index in range(1, len(entries))),
          f"each transition must link to the previous one: {lines!r}")

    # (e) A hand-rewritten line: the transition it records is no longer the one that happened.
    rewritten = [dict(json.loads(line)) for line in lines]
    rewritten[1]["action"] = "close"
    journal.write_text("\n".join(json.dumps(line, sort_keys=True) for line in rewritten) + "\n",
                       encoding="utf-8")
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a rewritten journal line")
    ledger_violation(res, "a rewritten journal line")
    before = journal.read_bytes()
    res = run("add", "--repo", str(root), "--permit-id", "P2", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "test_manifest.py")
    expect_clean_cli(res, 2, "a write on top of a rewritten journal")
    ledger_violation(res, "a write on top of a rewritten journal")
    check(journal.read_bytes() == before, "a refused write must not touch the journal")

    # (f) The registry deleted: the journal still holds the state the run recorded.
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    expect_clean_cli(audit(root, directory), 0, "the restored journal")
    (root / PERMITS_REL).unlink()
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a deleted registry")
    ledger_violation(res, "a deleted registry")
    res = run("add", "--repo", str(root), "--permit-id", "P2", "--task-id", "task_09",
              "--role", "coder", "--phase", "implement", "--scope", "test_manifest.py")
    expect_clean_cli(res, 2, "an add after the registry was deleted")
    ledger_violation(res, "an add after the registry was deleted")

    # A registry that predates the chain is reported, never silently adopted.
    legacy = repo(tmp, "ledger-legacy")
    allow(legacy, "P1")
    (legacy / LEDGER_REL).unlink()
    res = audit(legacy, session(legacy, []))
    expect_clean_cli(res, 1, "an unjournaled registry")
    ledger_violation(res, "an unjournaled registry")
    res = run("close", "--repo", str(legacy), "--permit-id", "P1", "--reason", "x")
    expect_clean_cli(res, 2, "a write on an unjournaled registry")
    ledger_violation(res, "a write on an unjournaled registry")


def test_ledger_retroactive_authorization(tmp: pathlib.Path) -> None:
    """(failing-first) An owner authorization recorded AFTER the spawn discharges nothing.

    The bootstrap exception exists for a delegation the supervisor could not judge in advance. It
    is not a waiver: an authorization appended at finish — after the delegation already ran — is
    the post-hoc acceptance this release forbids. The record's own stamp must precede the spawn it
    excuses; otherwise the out-of-order verdict stands and the run FAILS.
    """
    past = int(time.time() * 1000) - 600000
    root = tmp / "ledger-retroactive"
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    (root / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init (retroactive)")
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "PR", "--kind", "bootstrap",
                         "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis"), 0,
                     "add PR")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "PR", "--verdict",
                         "allow", "--evidence", "bootstrap permit against the parsed task"), 0,
                     "verdict PR")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "PR", "--agent-id",
                         "agent-r"), 0, "bind PR")
    # The verdict (recorded now) postdates the spawn (ten minutes ago): out of order by construction.
    data = permits(root)
    data["permits"][0].update(owner_authorized=True, evidence="the owner said so afterwards")
    write_permits(root, data)
    # The owner's note carries its own stamp — AFTER the spawn it is supposed to excuse.
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((past + 300000) / 1000))
    (root / PIPELINE_REL).write_text(
        (root / PIPELINE_REL).read_text(encoding="utf-8")
        + f"owner_authorizations:\n  - {stamp} permit=PR role=analyzer mode=hitl\n",
        encoding="utf-8")
    directory = session(root, [("agent-r", "factory-analyzer", past)])
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a retroactive owner authorization")
    text = (res.stdout + res.stderr).lower()
    check("pr" in text, f"the refusal must name the permit: {res.stdout!r} {res.stderr!r}")
    check(any(word in text for word in
              ("retroactive", "after the spawn", "out-of-order", "authorization")
              + LEDGER_WORDS),
          f"the refusal must name the retroactive authorization or the broken ledger: "
          f"{res.stdout!r} {res.stderr!r}")


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


def test_ledger_mixed_authorization(tmp: pathlib.Path) -> None:
    """(R1, critical) One owner-authorized permit does not demand that EVERY permit be authorized.

    The ledger records ONE projection per state, so a registry that holds ORDINARY permits — the
    everyday in-order transitions, which never carry an annotation — together with the ONE
    bootstrap the owner authorized was refused as a rewritten history ("a reset, a truncated tail
    or an edited record"), and the run could neither audit nor write again. The contract: an
    ordinary permit must be UNCHANGED history, the annotated permit is the ONE allowed difference,
    and any edit of an ordinary permit's recorded fields is still a rewritten record.
    """
    now = int(time.time() * 1000)
    root = tmp / "mixed-authorization"
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / PIPELINE_REL).write_text(f"run_id: {RUN_ID}\nphase: analysis\n", encoding="utf-8")
    (root / TASK_REL).write_text(TASK_YAML, encoding="utf-8")
    (root / PLAN_REL).write_text(PLAN, encoding="utf-8")
    expect_clean_cli(run("init", "--repo", str(root)), 0, "init (mixed authorization)")
    # An ORDINARY permit: judged before the spawn it permits, the everyday case.
    allow(root)
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "P1", "--agent-id",
                         "agent-p1"), 0, "bind P1")
    # The bootstrap permit the owner authorizes, plus one ordinary permit still to be judged: the
    # registry must stay WRITABLE after the annotation.
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "PB", "--kind", "bootstrap",
                         "--task-id", "bootstrap", "--role", "analyzer", "--phase", "analysis"), 0,
                     "add PB")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "PB", "--verdict", "allow",
                         "--evidence", "bootstrap permit against the parsed task"), 0,
                     "verdict PB")
    expect_clean_cli(run("bind", "--repo", str(root), "--permit-id", "PB", "--agent-id",
                         "agent-b"), 0, "bind PB")
    # An ordinary permit that stays PENDING across the annotation: the registry must remain
    # WRITABLE after it (the amendment is not a frozen file).
    expect_clean_cli(run("add", "--repo", str(root), "--permit-id", "P3", "--task-id", "task_09",
                         "--role", "planner", "--phase", "plan", "--scope", "manifest.py"), 0,
                     "add P3")
    expect_clean_cli(run("verdict", "--repo", str(root), "--permit-id", "P3", "--verdict", "allow",
                         "--evidence", "task_09 is in the approved plan"), 0, "verdict P3")
    # The owner's decision: PB ran before its permit could be judged, so its permit is annotated
    # and the checkpoint records the authorization with its OWN (earlier) stamp.
    mutate(root, "PB", owner_authorized=True, evidence="the owner authorized the bootstrap",
           verdict_at_ms=now + 60000)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((now - 400000) / 1000))
    (root / PIPELINE_REL).write_text(
        f"run_id: {RUN_ID}\nphase: analysis\n"
        f"owner_authorizations:\n  - {stamp} permit=PB role=analyzer mode=hitl\n",
        encoding="utf-8")
    directory = session(root, [("agent-b", "factory-analyzer", now - 300000),
                               ("agent-p1", "factory-coder", now + 60000)])
    # The amendment leaves the registry WRITABLE: the next ordinary transition still appends.
    expect_clean_cli(run("close", "--repo", str(root), "--permit-id", "P3", "--reason",
                         "not executed: this plan needed no separate planning round"), 0,
                     "a write after the mixed amendment")
    res = audit(root, directory)
    expect_clean_cli(res, 0, "a mixed registry holding ONE owner-authorized permit")
    check("integrity" not in res.stdout.lower(),
          f"an amended registry must not be reported as a rewritten one: {res.stdout!r}")

    # Strictness survives: an ANNOTATION on an ordinary permit (a retroactive repair the checkpoint
    # never decided) is a rewritten record, and so is an edit of its recorded fields.
    recorded = permits(root)
    mutate(root, "P1", owner_authorized=True, verdict_at_ms=now + 60000)
    res = audit(root, directory)
    expect_clean_cli(res, 1, "a self-annotated ordinary permit")
    ledger_violation(res, "a self-annotated ordinary permit")
    write_permits(root, recorded)
    expect_clean_cli(audit(root, directory), 0, "the restored mixed registry")
    mutate(root, "P1", evidence="edited by hand")
    res = audit(root, directory)
    expect_clean_cli(res, 1, "an edited ordinary permit")
    ledger_violation(res, "an edited ordinary permit")


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
        test_current_session_resolution(tmp)
        test_prior_session_binding_is_not_a_current_spawn(tmp)
        test_prior_session_agent_id_does_not_block_the_current_session(tmp)
        test_overlapping_sessions_bind_the_same_agent_ids(tmp)
        test_current_session_violations_survive_the_session_boundary(tmp)
        test_bootstrap_permits(tmp)
        test_supervisor_permit_before_task(tmp)
        test_supervisor_permit_without_run_id(tmp)
        test_launch_only_registry_transfer(tmp)
        test_transfer_failure_is_atomic(tmp)
        test_retirement_failure_is_atomic(tmp)
        test_rollback_restoration_failure_is_reported(tmp)
        test_target_cleanup_failure_is_reported(tmp)
        test_launch_transfer_guards(tmp)
        test_launch_lifecycle_arguments(tmp)
        test_owner_authorization_verified(tmp)
        test_ledger_reset_and_reinit(tmp)
        test_ledger_truncation_and_drift(tmp)
        test_ledger_retroactive_authorization(tmp)
        test_ledger_mixed_authorization(tmp)
        test_ledger_chain(tmp)
        test_ledger_legacy_snapshot(tmp)
        test_launch_scoped_binding(tmp)
        test_audit_helpers()
        test_cli_contract()
    with tempfile.TemporaryDirectory() as raw:
        test_resumed_agent_role_correlation(pathlib.Path(raw))

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

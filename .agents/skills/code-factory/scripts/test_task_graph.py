#!/usr/bin/env python3
"""
Deterministic self-test for `task_graph.py` (zero LLM tokens).

Verifies that readiness and status transitions are decided by the script, never by a model:
  - `create` writes <id>.json with the documented fields (atomic — no temp files left behind),
    refuses duplicate ids, invalid ids, self-dependencies and dependency CYCLES (exit 1 with the
    cycle in the message, without creating the offending file),
  - `claim` moves pending -> in_progress ONLY for a ready task (a blocked task and a repeat claim
    are refused, i.e. the status race is deterministic),
  - `complete` moves in_progress -> done, refuses a task that was never claimed, is idempotent for
    an already done task, and unblocks the dependants,
  - `ready` lists exactly the claimable pending tasks, `list` shows every task with its state,
  - `sha` / `verify-sha` produce and check the sha256 checkpoint values, and the default tasks
    directory is `.code-factory/state/tasks` relative to the working directory.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "task_graph.py"
FIELDS = ("id", "title", "status", "owner", "blockedBy")


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", cwd=cwd)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def load(tasks_dir: pathlib.Path, task_id: str) -> dict:
    return json.loads((tasks_dir / f"{task_id}.json").read_text(encoding="utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        tasks = tmp / "tasks"
        base = ("--dir", str(tasks))

        # 1. create: a dependency-free task, with exactly the documented fields.
        res = run("create", *base, "--id", "task_01", "--title", "Scaffold gate")
        expect(res.returncode == 0, f"create must exit 0: {res.stderr!r}")
        task = load(tasks, "task_01")
        expect(tuple(task) == FIELDS, f"task file must hold exactly {FIELDS}: {tuple(task)}")
        expect(task["id"] == "task_01" and task["title"] == "Scaffold gate",
               f"create must store id/title: {task!r}")
        expect(task["status"] == "pending" and task["owner"] is None and task["blockedBy"] == [],
               f"a fresh task must be pending, unowned and unblocked: {task!r}")
        expect(not list(tasks.glob("*.tmp")), "the atomic write must not leave temp files behind")

        # 2. create with a dependency, plus a forward reference (allowed, reported as a note).
        expect(run("create", *base, "--id", "task_02", "--title", "Second",
                   "--blocked-by", "task_01").returncode == 0, "create with a dependency must pass")
        res = run("create", *base, "--id", "task_03", "--title", "Third",
                  "--blocked-by", "task_09")
        expect(res.returncode == 0, f"a forward reference must be accepted: {res.stderr!r}")
        expect("does not exist yet" in res.stdout,
               f"an unknown dependency must be reported as a note: {res.stdout!r}")

        # 3. ready: only the unblocked pending task.
        res = run("ready", *base)
        expect(res.returncode == 0, f"ready must exit 0: {res.stderr!r}")
        expect(res.stdout.split() == ["task_01"], f"only task_01 is ready: {res.stdout!r}")

        # 4. Status race: a blocked task cannot be claimed, an unknown task cannot be claimed.
        res = run("claim", *base, "--id", "task_02", "--owner", "coder")
        expect(res.returncode == 1, "claiming a blocked task must be refused")
        expect("not ready" in res.stderr and "task_01" in res.stderr,
               f"the refusal must name the blocker: {res.stderr!r}")
        expect(load(tasks, "task_02")["status"] == "pending", "a refused claim must not change state")
        expect(run("claim", *base, "--id", "task_99", "--owner", "coder").returncode == 1,
               "claiming an unknown task must be refused")
        expect(run("claim", *base, "--id", "task_07", "--owner", "").returncode == 1,
               "claiming without an owner must be refused")

        # 5. claim -> in_progress; a second claim is refused (the owner is fixed once).
        res = run("claim", *base, "--id", "task_01", "--owner", "coder")
        expect(res.returncode == 0, f"claiming a ready task must exit 0: {res.stderr!r}")
        task = load(tasks, "task_01")
        expect(task["status"] == "in_progress" and task["owner"] == "coder",
               f"claim must set in_progress/owner: {task!r}")
        expect(run("claim", *base, "--id", "task_01", "--owner", "tester").returncode == 1,
               "claiming an in_progress task again must be refused")

        # 6. complete: pending -> refused; in_progress -> done; done -> idempotent; unblocks.
        res = run("complete", *base, "--id", "task_03")
        expect(res.returncode == 1 and "claim it" in res.stderr,
               f"completing an unclaimed task must be refused: {res.stderr!r}")
        expect(run("complete", *base, "--id", "task_01").returncode == 0, "complete must exit 0")
        expect(load(tasks, "task_01")["status"] == "done", "complete must set done")
        res = run("complete", *base, "--id", "task_01")
        expect(res.returncode == 0 and "already done" in res.stdout,
               f"completing twice must be idempotent: {res.stdout!r}")
        expect(run("ready", *base).stdout.split() == ["task_02"],
               "completing task_01 must unblock task_02")
        expect(run("claim", *base, "--id", "task_02", "--owner", "tester").returncode == 0,
               "an unblocked task must be claimable")
        expect(run("complete", *base, "--id", "task_02").returncode == 0, "complete must exit 0")
        expect(run("ready", *base).stdout.strip() == "",
               "task_03 stays blocked by its missing dependency")

        # 7. list: every task with state, owner and dependencies.
        res = run("list", *base)
        lines = {line.split("\t")[0]: line.split("\t") for line in res.stdout.splitlines()}
        expect(set(lines) == {"task_01", "task_02", "task_03"}, f"list must show all tasks: {res.stdout!r}")
        expect(lines["task_01"][1] == "done" and lines["task_01"][2] == "coder",
               f"list must show status and owner: {lines['task_01']!r}")
        expect(lines["task_02"][3] == "task_01", f"list must show blockedBy: {lines['task_02']!r}")

        # 8. Duplicate id and invalid id are refused.
        res = run("create", *base, "--id", "task_01", "--title", "Dup")
        expect(res.returncode == 1 and "already exists" in res.stderr,
               f"a duplicate id must be refused: {res.stderr!r}")
        expect(run("create", *base, "--id", "../evil", "--title", "Bad").returncode == 1,
               "a path-traversal id must be refused")
        expect(run("create", *base, "--id", "task_04", "--title", "   ").returncode == 1,
               "an empty title must be refused")

        # 9. Cycles: a self-dependency and a two-node cycle are refused, no file written.
        res = run("create", *base, "--id", "cyc_a", "--title", "A", "--blocked-by", "cyc_a")
        expect(res.returncode == 1 and "itself" in res.stderr,
               f"a self-dependency must be refused: {res.stderr!r}")
        expect(run("create", *base, "--id", "cyc_a", "--title", "A",
                   "--blocked-by", "cyc_b").returncode == 0, "cyc_a -> cyc_b must be accepted")
        res = run("create", *base, "--id", "cyc_b", "--title", "B", "--blocked-by", "cyc_a")
        expect(res.returncode == 1, "a dependency cycle must be refused")
        expect("cycle" in res.stderr and "cyc_a" in res.stderr and "cyc_b" in res.stderr,
               f"the refusal must show the cycle: {res.stderr!r}")
        expect(not (tasks / "cyc_b.json").exists(), "a refused create must not write a task file")

        # 10. sha256 checkpoint helpers.
        artifact = tmp / "pipeline.yaml"
        artifact.write_bytes(b"tasks:\n  - task_01\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        res = run("sha", str(artifact))
        expect(res.returncode == 0 and res.stdout.strip() == digest,
               f"sha must print the sha256 of the file: {res.stdout!r} != {digest}")
        expect(run("verify-sha", str(artifact), digest).returncode == 0, "a matching sha must exit 0")
        expect(run("verify-sha", str(artifact), "sha256:" + digest).returncode == 0,
               "a prefixed sha256 value must be accepted")
        res = run("verify-sha", str(artifact), "0" * 64)
        expect(res.returncode == 1 and "MISMATCH" in res.stderr,
               f"a changed artifact must be detected: {res.returncode} {res.stderr!r}")
        artifact.write_bytes(b"tampered\n")
        expect(run("verify-sha", str(artifact), digest).returncode == 1,
               "a tampered artifact must fail verification")
        expect(run("sha", str(tmp / "missing.yaml")).returncode == 1,
               "sha of a missing file must exit 1")

        # 11. Default tasks dir: .code-factory/state/tasks relative to the working directory.
        workdir = tmp / "cwd"
        workdir.mkdir()
        expect(run("create", "--id", "default_01", "--title", "Default dir",
                   cwd=str(workdir)).returncode == 0, "create must work with the default --dir")
        expect((workdir / ".code-factory" / "state" / "tasks" / "default_01.json").is_file(),
               "the default tasks dir must be .code-factory/state/tasks")
        expect(run("ready", cwd=str(workdir)).stdout.split() == ["default_01"],
               "ready must read the default tasks dir")

    print("PASS - task_graph.py creates/claims/completes tasks, refuses cycles, blocked claims and "
          "unclaimed completions, reports readiness deterministically, and checks sha256.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

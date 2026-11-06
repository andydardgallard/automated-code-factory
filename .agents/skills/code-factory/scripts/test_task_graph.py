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
    directory is `.code-factory/state/tasks` relative to the working directory,
  - the OPTIONAL `--repo`/`--root` anchor (before or after the subcommand) resolves the RELATIVE
    paths of the invocation — `--dir` and the `file` of `sha`/`verify-sha` — against the run's
    resolved repo_path, while an absolute path stays as it is and the flag-less invocation keeps
    resolving against the cwd,
  - a MALFORMED task file (scalar, array, wrong field types) is one clean `error: ` line naming the
    file, exit 1 — never a TypeError traceback — in every command that loads the graph, and a graph
    holding one broken file is refused as a whole instead of being half-read,
  - a SYNCHRONIZED concurrent probe: two independent claim processes against the SAME pending task,
    started together — exactly one wins (exit 0), the other is refused, the persisted file shows one
    owner and one pending -> in_progress transition, and no lock file is left behind,
  - a SYNCHRONIZED RECLAMATION race: two reclaimers of one STALE lock, interleaved deterministically
    (reclaimer A is suspended the instant it has judged the lock stale, B then reclaims it and holds
    a fresh LIVE lock, A resumes) — A must be refused and B's fresh lock must survive, because the
    loser of a reclaim race may never unlink the winner's new lock.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import task_graph  # noqa: E402  (the lock contract's constants are read, not re-declared)

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

        # 12. The optional `--repo`/`--root` anchor: run from a launch directory that is not the repo
        #     root, the graph lands under --repo — the DEFAULT --dir and a relative --dir alike, before
        #     or after the subcommand — and so does the relative `file` of sha/verify-sha. Without the
        #     flag the cwd stays the base (case 11) and an absolute path is never re-anchored.
        launch = tmp / "launch"
        launch.mkdir()
        repo = tmp / "target" / "repo"
        expect(run("create", "--repo", str(repo), "--id", "anchored_01", "--title", "Anchored",
                   cwd=str(launch)).returncode == 0, "create --repo must exit 0")
        anchored_tasks = repo / ".code-factory" / "state" / "tasks"
        expect((anchored_tasks / "anchored_01.json").is_file(),
               "--repo must anchor the DEFAULT tasks dir at the resolved repo_path")
        expect(not (launch / ".code-factory").exists(),
               "no task file may land in the launch directory when --repo is given")
        res = run("claim", "--repo", str(repo), "--id", "anchored_01", "--owner", "coder",
                  cwd=str(launch))
        expect(res.returncode == 0 and load(anchored_tasks, "anchored_01")["owner"] == "coder",
               f"claim --repo must write into the anchored graph: {res.stderr!r}")
        expect(run("--root", str(repo), "list", cwd=str(launch)).stdout.split() != [],
               "--root must be accepted as a synonym of --repo, before the subcommand too")
        expect(run("create", "--repo", str(repo), "--dir", ".code-factory/state/tasks",
                   "--id", "anchored_02", "--title", "Two", cwd=str(launch)).returncode == 0,
               "a relative --dir must be anchored at --repo")
        expect((anchored_tasks / "anchored_02.json").is_file(),
               "a relative --dir must write under the resolved repo_path")
        expect(run("ready", "--repo", str(repo), cwd=str(launch)).stdout.split() == ["anchored_02"],
               "ready --repo must read the anchored graph")
        artifact = repo / "artifact.bin"
        artifact.write_text("checkpoint\n", encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        res = run("sha", "--repo", str(repo), "artifact.bin", cwd=str(launch))
        expect(res.returncode == 0 and res.stdout.strip() == digest,
               f"sha --repo must anchor a relative file: {res.stdout!r} {res.stderr!r}")
        expect(run("verify-sha", "--repo", str(repo), "artifact.bin", digest,
                   cwd=str(launch)).returncode == 0,
               "verify-sha --repo must anchor a relative file")
        expect(run("ready", cwd=str(launch)).stdout.split() == [],
               "without --repo the cwd stays the base (no graph in the launch directory)")
        expect(run("sha", "artifact.bin", cwd=str(launch)).returncode == 1,
               "without --repo a relative file resolves against the cwd")
        expect(run("ready", "--repo", str(launch), "--dir", str(anchored_tasks)).stdout.split()
               == ["anchored_02"],
               "an absolute --dir must never be re-anchored")

        # 13. REGRESSION (self-review 20261031-d2f6fea6, critical 11): a malformed task FILE is a
        #     clean refusal, never a TypeError traceback. `read_task` used to run its membership
        #     tests on the decoded JSON before checking that it is an object, so a `bad.json`
        #     containing `1` printed `TypeError: argument of type 'int' is not a container or
        #     iterable` — a crash in EVERY command that loads the graph.
        broken = tmp / "broken"
        broken.mkdir()
        bad_json = broken / "bad.json"
        bad_json.write_text("1\n", encoding="utf-8")
        for args in (("list",), ("ready",),
                     ("claim", "--id", "task_01", "--owner", "coder"),
                     ("complete", "--id", "task_01"),
                     ("create", "--id", "task_new", "--title", "New")):
            res = run(*args, "--dir", str(broken))
            expect(res.returncode == 1,
                   f"{args[0]} must refuse a scalar task file with exit 1: "
                   f"{res.returncode} {res.stdout!r} {res.stderr!r}")
            expect("Traceback" not in res.stderr,
                   f"{args[0]} must not print a traceback: {res.stderr!r}")
            expect(res.stderr.startswith("error: ") and "bad.json" in res.stderr,
                   f"{args[0]} must name the broken file in one 'error: ' line: {res.stderr!r}")
            expect(res.stderr.strip().count("\n") == 0,
                   f"{args[0]} must print exactly one error line: {res.stderr!r}")

        # The same refusal for the other malformed shapes: a JSON array, a task whose `blockedBy`
        # is not a list (a string would have been iterated character by character), and a task
        # whose `title` is not text.
        bad_json.unlink()                   # one malformed file at a time: each must be named
        for name, body in (("array.json", "[1, 2]\n"),
                           ("string-null.json", "null\n"),
                           ("bad-blockedby.json", json.dumps(
                               {"id": "bad_blockedby", "title": "T", "status": "pending",
                                "owner": None, "blockedBy": "bad_blockedby"}) + "\n"),
                           ("bad-title.json", json.dumps(
                               {"id": "bad_title", "title": 7, "status": "pending",
                                "owner": None, "blockedBy": []}) + "\n"),
                           ("bad-status.json", json.dumps(
                               {"id": "bad_status", "title": "T", "status": ["pending"],
                                "owner": None, "blockedBy": []}) + "\n")):
            (broken / name).write_text(body, encoding="utf-8")
            # `ready` reads the whole directory, so it must refuse every malformed shape.
            res = run("ready", "--dir", str(broken))
            expect(res.returncode == 1 and "Traceback" not in res.stderr,
                   f"a malformed task file must be refused cleanly ({name}): "
                   f"{res.returncode} {res.stderr!r}")
            expect(res.stderr.startswith("error: ") and name in res.stderr,
                   f"the refusal must name {name}: {res.stderr!r}")
            (broken / name).unlink()

        # A valid task next to a broken file is still refused as a WHOLE: the graph is either read
        # completely or not at all (a half-read graph would decide readiness on partial state).
        bad_json.write_text("1\n", encoding="utf-8")
        (broken / "good.json").write_text(json.dumps(
            {"id": "good", "title": "Good", "status": "pending", "owner": None,
             "blockedBy": []}) + "\n", encoding="utf-8")
        res = run("list", "--dir", str(broken))
        expect(res.returncode == 1 and "Traceback" not in res.stderr,
               f"a broken graph must not be half-read: {res.returncode} {res.stderr!r}")
        expect("bad.json" in res.stderr, f"the refusal must name the broken file: {res.stderr!r}")

        # 14. CONCURRENT claim probe (review 20261104-b5b601f6, major 13): the sequential race test
        #     above can never catch a check-then-write race, so two INDEPENDENT claim processes are
        #     started together against the same pending task. Exactly one may win (exit 0), the
        #     other must be refused as already claimed, and the persisted file must show the single
        #     winning owner — one pending -> in_progress transition. The claim is a
        #     compare-and-claim under an exclusive lock, so the probe is deterministic: even a
        #     perfectly serialized pair leaves the loser facing an in_progress task.
        for round_no in range(3):
            race_id = f"race_{round_no:02d}"
            res = run("create", *base, "--id", race_id, "--title", "Race probe")
            expect(res.returncode == 0, f"create for the race probe must exit 0: {res.stderr!r}")
            procs = [subprocess.Popen([sys.executable, str(TOOL), "claim", *base,
                                       "--id", race_id, "--owner", owner],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, errors="replace")
                     for owner in ("racer-a", "racer-b")]
            outcomes = []
            for proc in procs:
                out, err = proc.communicate()
                outcomes.append((proc.returncode, out, err))
            wins = [o for o in outcomes if o[0] == 0]
            refused = [o for o in outcomes if o[0] == 1]
            expect(len(wins) == 1 and len(refused) == 1,
                   f"exactly one of two concurrent claims may win: {outcomes!r}")
            expect(f"claimed: {race_id}" in wins[0][1],
                   f"the winning claim must report the claim: {wins!r}")
            expect("in_progress" in refused[0][2],
                   f"the losing claim must be refused as already claimed: {refused!r}")
            task = load(tasks, race_id)
            expect(task["status"] == "in_progress" and task["owner"] in ("racer-a", "racer-b"),
                   f"the persisted task must show one owner and one transition: {task!r}")
        expect(not list(tasks.glob("*.claim.lock")),
               "no claim lock may be left behind by the concurrent probe")

        # 15. REGRESSION (review R1, major): a crashed claim must not lock its task out forever.
        #     The lock names its owner (owner + pid + timestamp), so recovery is OWNERSHIP-AWARE:
        #     a lock whose process is gone AND which is older than the retry window is reclaimed,
        #     while a LIVE claim's lock is never stolen — however long its holder takes.
        crash_id = "crash_01"
        expect(run("create", *base, "--id", crash_id, "--title", "Crash recovery").returncode == 0,
               "create for the crash probe must exit 0")
        crash_lock = tasks / f"{crash_id}.claim.lock"
        old = time.time() - (task_graph.CLAIM_LOCK_STALE_SECONDS * 4)
        # (a) A crashed claim: a dead pid and an old timestamp. The next claim must succeed.
        crash_lock.write_text(json.dumps({"owner": "crashed-coder", "pid": 2 ** 22 + 12345,
                                          "created_ms": int(old * 1000)}) + "\n",
                              encoding="utf-8")
        os.utime(crash_lock, (old, old))
        res = run("claim", *base, "--id", crash_id, "--owner", "coder")
        expect(res.returncode == 0,
               f"a stale lock of a dead claim must be reclaimed, not refused forever: "
               f"{res.returncode} {res.stderr!r}")
        expect(load(tasks, crash_id)["status"] == "in_progress",
               "the reclaimed task must be claimed")
        expect(not crash_lock.exists(), "a released claim must leave no lock behind")

        # (b) A LIVE claim's lock is never stolen, even when it is old: the owner is alive.
        expect(run("create", *base, "--id", "live_01", "--title", "Live lock").returncode == 0,
               "create for the live-lock probe must exit 0")
        live_lock = tasks / "live_01.claim.lock"
        live_lock.write_text(json.dumps({"owner": "live-coder", "pid": os.getpid(),
                                         "created_ms": int(old * 1000)}) + "\n", encoding="utf-8")
        os.utime(live_lock, (old, old))
        res = run("claim", *base, "--id", "live_01", "--owner", "other")
        expect(res.returncode == 1 and "being claimed elsewhere" in res.stderr,
               f"a LIVE claim's lock must never be stolen: {res.returncode} {res.stderr!r}")
        expect(load(tasks, "live_01")["status"] == "pending",
               "a refused claim must not change the task")
        live_lock.unlink()

        # (c) A lock INSIDE the retry window is not reclaimed even when its pid looks dead: it may
        #     be a claim that has just created the file and not yet written it.
        recent_lock = tasks / "live_01.claim.lock"
        recent_lock.write_text("", encoding="utf-8")          # blank: the write has not landed yet
        res = run("claim", *base, "--id", "live_01", "--owner", "other")
        expect(res.returncode == 1 and "being claimed elsewhere" in res.stderr,
               f"a fresh lock must never be reclaimed: {res.returncode} {res.stderr!r}")
        recent_lock.unlink()

        # (d) The lock carries its owner, so recovery is a decision about a NAMED process.
        res = run("claim", *base, "--id", "live_01", "--owner", "named-owner")
        expect(res.returncode == 0, f"the final claim must succeed: {res.stderr!r}")
        expect(not live_lock.exists(), "the named claim must release its lock")

        # 16. REGRESSION (review R2): a stale-lock reclaimer must never unlink a rival's FRESH lock.
        #     `lock_is_stale` -> `unlink` -> re-create is a check-then-act race: between the stale
        #     judgement and the unlink the stale lock can be gone and a fresh LIVE lock in its
        #     place, which an unconditional unlink destroys — and two claims then enter the critical
        #     section. The interleaving is FORCED, not hoped for: reclaimer A is suspended the
        #     instant it has judged the lock stale; reclaimer B then reclaims the lock completely
        #     and keeps the fresh lock it created; A resumes and runs its unlink. Exactly one
        #     claimant may win: A must be refused, B's fresh lock must still name B, and the task
        #     must be untouched.
        expect(run("create", *base, "--id", "reclaim_01",
                   "--title", "Reclaim race").returncode == 0,
               "create for the reclaimer race must exit 0")
        race_lock = tasks / "reclaim_01.claim.lock"
        race_lock.write_text(json.dumps({"owner": "crashed-coder", "pid": 2 ** 22 + 54321,
                                         "created_ms": int(old * 1000)}) + "\n", encoding="utf-8")
        os.utime(race_lock, (old, old))        # the crash's leftover: dead pid, past the grace

        real_stale = task_graph.lock_is_stale
        real_attempts = task_graph.CLAIM_LOCK_ATTEMPTS
        real_delay = task_graph.CLAIM_LOCK_DELAY_SECONDS
        judged, winner_holds = threading.Event(), threading.Event()
        loser_outcome: list[str] = []
        winner_lock: list[pathlib.Path] = []

        def paused_stale(lock: pathlib.Path, now: float | None = None) -> bool:
            """A's staleness judgement — and the suspension point of the interleaving."""
            stale = real_stale(lock, now)
            if threading.current_thread() is loser_thread and not judged.is_set():
                judged.set()               # A has judged the lock stale ...
                winner_holds.wait(10)      # ... and is paused while B reclaims it
            return stale

        def lose() -> None:
            try:
                task_graph.acquire_claim_lock(tasks, "reclaim_01", "loser")
                loser_outcome.append("claimed")
            except task_graph.GraphError as exc:
                loser_outcome.append(str(exc))

        def win() -> None:
            judged.wait(10)
            winner_lock.append(task_graph.acquire_claim_lock(tasks, "reclaim_01", "winner"))
            winner_holds.set()             # B HOLDS the fresh lock: A must not remove it

        loser_thread = threading.Thread(target=lose, daemon=True)
        winner_thread = threading.Thread(target=win, daemon=True)
        task_graph.lock_is_stale = paused_stale
        task_graph.CLAIM_LOCK_ATTEMPTS, task_graph.CLAIM_LOCK_DELAY_SECONDS = 5, 0.01
        try:
            loser_thread.start()
            winner_thread.start()
            loser_thread.join(20)
            winner_thread.join(20)
        finally:
            task_graph.lock_is_stale = real_stale
            task_graph.CLAIM_LOCK_ATTEMPTS, task_graph.CLAIM_LOCK_DELAY_SECONDS = (
                real_attempts, real_delay)
        expect(not loser_thread.is_alive() and not winner_thread.is_alive(),
               "the reclaimer race must finish")
        expect(winner_lock and winner_lock[0] == race_lock,
               f"the winner must hold the claim lock: {winner_lock!r}")
        expect(len(loser_outcome) == 1 and "being claimed elsewhere" in loser_outcome[0],
               f"the losing reclaimer must be refused, not win: {loser_outcome!r}")
        expect(race_lock.exists(),
               "the loser's unlink must not remove the winner's fresh lock")
        expect(json.loads(race_lock.read_text(encoding="utf-8"))["owner"] == "winner",
               f"the fresh lock must still name the winner: {race_lock.read_text()!r}")
        expect(load(tasks, "reclaim_01")["status"] == "pending",
               "a refused claim must not change the task")
        recover_files = list(tasks.glob("*.recover"))
        for leftover in recover_files:
            expect(leftover.stat().st_size == 0,
                   "a leftover .recover mutex is inert (permanent, never unlinked, OS-released on death)")
            # The mutex must not stay locked after the race: acquiring it directly must work.
            handle = task_graph._acquire_recovery_mutex(leftover)
            expect(handle is not None, "a leftover .recover mutex must be acquirable (no stale stealing)")
            task_graph._release_recovery_mutex(handle)
        task_graph.release_claim_lock(winner_lock[0])
        expect(not race_lock.exists(), "releasing the winning claim must leave no lock behind")

    print("PASS - task_graph.py creates/claims/completes tasks, refuses cycles, blocked claims and "
          "unclaimed completions, reports readiness deterministically, decides a CONCURRENT claim "
          "race and a stale-lock RECLAMATION race for exactly one winner without stealing a rival's "
          "fresh lock, checks sha256, anchors the relative graph/sha paths at "
          "--repo, and refuses a malformed task file (scalar, array, wrong field type) with one "
          "clean 'error: ' line instead of a TypeError traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

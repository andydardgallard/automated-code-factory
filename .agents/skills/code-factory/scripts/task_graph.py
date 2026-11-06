#!/usr/bin/env python3
"""
Deterministic on-disk task graph for the Code Factory — zero LLM tokens.

Tasks live as one JSON file per task in `.code-factory/state/tasks/<id>.json`:

  {"id": "task_01", "title": "...", "status": "pending|in_progress|done",
   "owner": "coder|null", "blockedBy": ["task_02"]}

The SCRIPT decides readiness (a pending task whose every `blockedBy` task is `done`), not a model:
`claim` refuses a task that is not ready or not pending, `create` refuses a dependency cycle, and
every write is atomic (temp file + replace), so a crashed or interrupted run never leaves a
half-written task file. A claim is a compare-and-claim under an exclusive per-task lock file
(`O_CREAT | O_EXCL`), so two CONCURRENT claims of the same pending task can never both win. The lock
records its OWNER (`{"owner","pid","created_ms"}`): a claim that crashes before releasing it leaves a
STALE lock that a later claim may reclaim, but only when the recorded process is provably gone AND
the lock is older than the staleness window (which exceeds the whole retry window) — a
live claim's lock is never stolen. Reclaiming is destructive, so it runs under its own recovery
mutex and re-validates the lock's identity first: a loser can never remove the fresh lock a rival
created after the stale one.

Commands:
  create --dir <tasks_dir> --id <id> --title "<title>" [--blocked-by id1,id2]
  claim  --id <id> --owner <role> [--dir <tasks_dir>]
  complete --id <id> [--dir <tasks_dir>]
  ready  [--dir <tasks_dir>]        # ids of the claimable tasks, one per line
  list   [--dir <tasks_dir>]        # id, status, owner, blockedBy, title
  sha <file>                        # sha256 of a file (checkpoint/resume)
  verify-sha <file> <expected>      # exit 0 when the file's sha256 matches <expected>

Default tasks dir: `.code-factory/state/tasks`. Exit code 0 = success, 1 = refused/failed — a
malformed task file (unparseable JSON, a scalar or array document, a field of the wrong type) is one
such failure: a single `error: ...` line naming the file and the problem, never a traceback, and a
graph holding one malformed file is refused as a whole instead of being half-read.

Every subcommand accepts an OPTIONAL `--repo <root>` (a synonym: `--root`; accepted before or
after the subcommand) — the resolved repo_path of the run. When it is given, the RELATIVE paths of
the invocation are resolved against it: `--dir` (the graph location) and the `file` of `sha` /
`verify-sha` — an absolute path is always taken as it is. So a run whose repo_path is not its
launch directory reads and writes the graph of that repository and of no other. Without the flag
nothing changes: relative paths stay relative to the caller's working directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import time

PENDING, IN_PROGRESS, DONE = "pending", "in_progress", "done"
STATUSES = (PENDING, IN_PROGRESS, DONE)
DEFAULT_TASKS_DIR = ".code-factory/state/tasks"
TASK_FIELDS = ("id", "title", "status", "owner", "blockedBy")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPO_HELP = ("Resolved repo_path of the run: a RELATIVE --dir (and the `file` of sha/verify-sha) "
             "is resolved against it (default: the caller's working directory — unchanged without "
             "the flag)")


class GraphError(Exception):
    """A refused command (bad id, unknown task, cycle, wrong status) — exits 1."""


def anchored(path: str | pathlib.Path, repo: str | None) -> pathlib.Path:
    """`path` resolved against the explicit `--repo` root; an absolute path is taken as it is.

    Without `--repo` the path is returned unchanged, so the caller's working directory stays the
    base and the graph is read where it was before the flag existed (fail-safe default: a missing
    anchor must never silently re-point the graph at the wrong repository).
    """
    resolved = pathlib.Path(path)
    if repo and not resolved.is_absolute():
        return pathlib.Path(repo) / resolved
    return resolved


def tasks_dir_of(args: argparse.Namespace) -> pathlib.Path:
    """Tasks directory of the invocation, anchored at `--repo` when it was given."""
    return anchored(args.dir, args.repo)


def add_repo(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the optional repo anchor to a subcommand parser.

    `default=SUPPRESS`, so a value given BEFORE the subcommand (`task_graph.py --repo <root> ready`)
    survives: the subparser only overwrites the attribute when the flag is repeated after it.
    """
    parser.add_argument("--repo", "--root", dest="repo", metavar="ROOT",
                        default=argparse.SUPPRESS, help=REPO_HELP)
    return parser


def task_path(tasks_dir: pathlib.Path, task_id: str) -> pathlib.Path:
    return tasks_dir / f"{task_id}.json"


def validate_id(task_id: str, what: str = "task id") -> str:
    if not ID_RE.match(task_id):
        raise GraphError(f"invalid {what} {task_id!r}: use letters, digits, '.', '_' or '-'")
    return task_id


def read_task(path: pathlib.Path) -> dict:
    """One task file, validated: (a dict with `TASK_FIELDS` of the documented TYPES).

    Every malformed shape — unparseable JSON, a scalar/array document, a missing field, a field of
    the wrong type — becomes a `GraphError` (exit 1, one line, no traceback). The type check comes
    BEFORE any membership test: `f in data` on a decoded scalar raised `TypeError` and crashed every
    command that loads the graph, so a single `bad.json` containing `1` took the whole graph down.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphError(f"cannot read task file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GraphError(f"task file {path} must hold one JSON object with the field(s) "
                         f"{', '.join(TASK_FIELDS)}, but it holds {type(data).__name__} "
                         f"{data!r}")
    missing = [f for f in TASK_FIELDS if f not in data]
    if missing:
        raise GraphError(f"task file {path} is missing field(s): {', '.join(missing)}")
    if not isinstance(data["id"], str) or not isinstance(data["title"], str):
        raise GraphError(f"task file {path} must carry 'id' and 'title' as strings, got "
                         f"id={data['id']!r} title={data['title']!r}")
    if not isinstance(data["status"], str) or data["status"] not in STATUSES:
        raise GraphError(f"task file {path} has unknown status {data['status']!r} "
                         f"(expected one of: {', '.join(STATUSES)})")
    if data["owner"] is not None and not isinstance(data["owner"], str):
        raise GraphError(f"task file {path} must carry 'owner' as a string or null, got "
                         f"{data['owner']!r}")
    if not isinstance(data["blockedBy"], list) \
            or not all(isinstance(dep, str) for dep in data["blockedBy"]):
        raise GraphError(f"task file {path} must carry 'blockedBy' as a list of task ids, got "
                         f"{data['blockedBy']!r}")
    return data


def load_tasks(tasks_dir: pathlib.Path) -> dict[str, dict]:
    """All tasks in the directory, keyed by id (a missing directory means an empty graph)."""
    if not tasks_dir.is_dir():
        return {}
    tasks: dict[str, dict] = {}
    for path in sorted(tasks_dir.glob("*.json")):
        data = read_task(path)
        if data["id"] != path.stem:
            raise GraphError(f"task file {path} declares id {data['id']!r} (expected {path.stem!r})")
        tasks[data["id"]] = data
    return tasks


def write_task(path: pathlib.Path, task: dict) -> None:
    """Atomic write: temp file in the same directory + replace (never a partial task file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {field: task[field] for field in TASK_FIELDS}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(ordered, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def find_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """One dependency cycle as `[a, b, a]` (DFS colouring), or None when the graph is a DAG."""
    state: dict[str, int] = {}  # 1 = on the current path, 2 = fully explored
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        if state.get(node) == 1:
            return path[path.index(node):] + [node]
        if state.get(node) == 2:
            return None
        state[node] = 1
        path.append(node)
        for dep in edges.get(node, []):
            cycle = visit(dep)
            if cycle:
                return cycle
        path.pop()
        state[node] = 2
        return None

    for node in sorted(edges):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def is_ready(task: dict, tasks: dict[str, dict]) -> bool:
    """Ready = still pending and every dependency is done (unknown deps are never done)."""
    return (task["status"] == PENDING
            and all(tasks.get(dep, {}).get("status") == DONE for dep in task["blockedBy"]))


def parse_blocked_by(raw: str | None) -> list[str]:
    out: list[str] = []
    for item in (raw or "").replace(" ", ",").split(","):
        item = item.strip()
        if item and item not in out:
            out.append(validate_id(item, "blockedBy id"))
    return out


def cmd_create(args: argparse.Namespace) -> int:
    tasks_dir = tasks_dir_of(args)
    task_id = validate_id(args.id)
    title = args.title.strip()
    if not title:
        raise GraphError("title must not be empty")
    blocked_by = parse_blocked_by(args.blocked_by)
    if task_id in blocked_by:
        raise GraphError(f"task {task_id!r} cannot be blocked by itself")
    path = task_path(tasks_dir, task_id)
    if path.is_file():
        raise GraphError(f"task {task_id!r} already exists ({path})")

    tasks = load_tasks(tasks_dir)
    edges = {tid: list(t["blockedBy"]) for tid, t in tasks.items()}
    edges[task_id] = blocked_by
    cycle = find_cycle(edges)
    if cycle:
        raise GraphError(f"dependency cycle rejected: {' -> '.join(cycle)}")

    write_task(path, {"id": task_id, "title": title, "status": PENDING,
                      "owner": None, "blockedBy": blocked_by})
    print(f"created: {task_id} ({path})")
    for dep in blocked_by:
        if dep not in tasks:
            print(f"note: blockedBy task {dep!r} does not exist yet (task stays blocked until it is done)")
    return 0


# A claim holds the exclusive lock for milliseconds, so a contender retries briefly before it is
# refused. The same retry window is the grace a lock must exceed before it can be RECLAIMED: a
# claim that crashes between creating the lock and releasing it used to lock its task out forever,
# so a lock whose recorded process is gone AND which is older than the retry window is stale.
CLAIM_LOCK_ATTEMPTS = 100
CLAIM_LOCK_DELAY_SECONDS = 0.05
# How old a lock must be before it can be reclaimed. This MUST exceed the whole retry window above
# (100 x 0.05s = 5s): a contender waits that long before it gives up, so the lock of a LIVE claim
# must still look fresh at the moment that wait ends — otherwise the wait itself would "age" the
# lock into staleness and the recovery would steal a running claim.
CLAIM_LOCK_STALE_SECONDS = 30.0
# Reclaiming a stale lock is a destructive act, so it runs under its OWN mutex — one more
# `O_CREAT | O_EXCL` file next to the lock, held for the microseconds of a revalidate + unlink.
CLAIM_LOCK_RECOVERY_SUFFIX = ".recover"


def _pid_alive(pid: int) -> bool:
    """Is a process with this pid still running? (best effort, and it never signals the process)

    POSIX answers with `os.kill(pid, 0)`, which sends no signal. Windows is NOT probed that way:
    there `os.kill` maps every signal other than CTRL_C/CTRL_BREAK to `TerminateProcess`, i.e. the
    probe would kill the owner — the process handle is opened read-only through ctypes instead.
    Anything the probe cannot decide counts as ALIVE: a lock is never stolen on a guess.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes                                    # noqa: PLC0415  (Windows only)
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFO
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # ERROR_INVALID_PARAMETER is the only answer that proves the pid is gone; a permission
            # or any other failure is UNKNOWN and therefore alive.
            return kernel32.GetLastError() != 87
        except (AttributeError, OSError, ValueError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:                     # EPERM: the process exists, it is just not ours
        return True
    return True


def lock_is_stale(lock: pathlib.Path, now: float | None = None) -> bool:
    """Can this claim lock be reclaimed? Only when its owner is GONE and it is past the grace.

    The lock content names its owner (`{"owner","pid","created_ms"}`), which is what makes the
    recovery ownership-AWARE instead of a timeout: a LIVE claim's lock is never stolen, however
    long its holder takes. A lock with no readable content — a legacy empty file or one being
    written right now — is judged by its modification time alone and is therefore only reclaimable
    after the same grace period, which a live claim (milliseconds) never approaches.
    """
    now = time.time() if now is None else now
    try:
        raw = lock.read_text(encoding="utf-8", errors="replace")
        info = json.loads(raw) if raw.strip() else None
        age = now - lock.stat().st_mtime
    except (OSError, ValueError):
        info, age = None, 0.0          # unreadable right now: not stale
    if age < CLAIM_LOCK_STALE_SECONDS:
        return False                   # inside the retry window: a live claim is still settling
    if not isinstance(info, dict):
        return True                    # legacy/blank lock, old enough to be a crash's leftover
    return not _pid_alive(info.get("pid"))


def lock_identity(lock: pathlib.Path) -> tuple[str, int] | None:
    """Which lock is this, right now? Its content plus its modification time, or None if unreadable.

    Reclaiming is a decision about ONE concrete lock file, so the recovery remembers the identity it
    judged stale and compares it again under the recovery mutex: the same identity means the same,
    unmoved lock; anything else means a rival has replaced it in the meantime, and then it is not
    ours to remove.
    """
    try:
        stamp = lock.stat().st_mtime_ns
        raw = lock.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None                    # gone or being written right now: no identity to own
    return raw, stamp


def _recovery_mutex_path(lock: pathlib.Path) -> pathlib.Path:
    return lock.with_name(lock.name + CLAIM_LOCK_RECOVERY_SUFFIX)


def _acquire_recovery_mutex(mutex: pathlib.Path):
    """Take the reclamation mutex if it is free — never block, never steal, never delete.

    The mutex is a PERMANENT file (`O_CREAT`, created once and never unlinked) guarded by an
    OS-level nonblocking exclusive lock (`msvcrt.locking`/`fcntl.flock`). Exactly one reclaimer
    enters the check + revalidate + unlink at a time; a busy mutex just means "somebody else is
    reclaiming", and the caller retries its normal loop. Because the OS releases the lock when the
    holder dies, a crashed reclaimer leaves no residue to steal — there is NO timeout-based
    stealing, so the steal-check/unlink race (two reclaimers both judging a leftover mutex stale and
    one unlinking the other's fresh mutex) cannot exist. Returns the handle, or None when busy.
    """
    try:
        handle = os.open(mutex, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt                                    # noqa: PLC0415  (Windows-only)
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl                                     # noqa: PLC0415  (POSIX-only)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        return None                        # held by a live reclaimer: they decide, we wait
    return handle


def _release_recovery_mutex(handle) -> None:
    if handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt                                    # noqa: PLC0415
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl                                     # noqa: PLC0415
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(handle)
    except OSError:
        pass


def reclaim_stale_lock(lock: pathlib.Path) -> bool:
    """Remove `lock` — but ONLY if it is still the very lock that was judged stale.

    `lock_is_stale(lock)` followed by `lock.unlink()` is a check-then-act race, and the act is
    destructive: between the two steps a rival reclaimer can remove the stale lock and create a
    FRESH, LIVE one, which the unlink would then destroy — and two claims would enter the critical
    section. So the reclaim runs under the recovery mutex AND re-makes its decision on the same
    object: the identity judged before taking the mutex (content + mtime) must still be the identity
    afterwards, and the lock must still be stale. A loser therefore never touches a winner's fresh
    lock — it simply walks away and waits the live claim out. Returns True only when it removed the
    stale lock it judged.
    """
    observed = lock_identity(lock)
    if observed is None:
        return False
    mutex = _acquire_recovery_mutex(_recovery_mutex_path(lock))
    if mutex is None:
        return False                   # another reclaimer owns the decision: retry the claim loop
    try:
        if lock_identity(lock) != observed or not lock_is_stale(lock):
            return False               # replaced (or revived) meanwhile: not ours to remove
        try:
            lock.unlink()
        except OSError:
            return False
        return True
    finally:
        _release_recovery_mutex(mutex)


def acquire_claim_lock(tasks_dir: pathlib.Path, task_id: str, owner: str) -> pathlib.Path:
    """The exclusive claim lock of one task, created with `O_CREAT | O_EXCL`: exactly ONE
    contender holds it, so a check-then-write race can never let two claims both succeed.

    A stale lock (owner gone, older than the staleness window) is reclaimed and the create retried.
    The removal goes through `reclaim_stale_lock`, which serializes it and revalidates the lock's
    identity: every racer still has to WIN the exclusive create, and no racer can remove a lock that
    a rival created after the stale one — so exactly one of them proceeds and the rest find a fresh,
    LIVE lock and wait it out.
    """
    lock = tasks_dir / f"{task_id}.claim.lock"
    payload = json.dumps({"owner": owner, "pid": os.getpid(), "created_ms": int(time.time() * 1000)})
    reclaimed = False
    for _ in range(CLAIM_LOCK_ATTEMPTS):
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not reclaimed and lock_is_stale(lock) and reclaim_stale_lock(lock):
                reclaimed = True
                continue
            time.sleep(CLAIM_LOCK_DELAY_SECONDS)
            continue
        except FileNotFoundError:  # no tasks directory at all: the clean unknown-task refusal
            raise GraphError(f"unknown task {task_id!r} in {tasks_dir}") from None
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
        return lock
    raise GraphError(f"task {task_id!r} is being claimed elsewhere — wait and try again")


def release_claim_lock(lock: pathlib.Path) -> None:
    """Release this claim's lock (best effort, never a traceback).

    On Windows a concurrent reader can hold the file open for an instant, so the unlink is retried
    briefly. A lock that still cannot be removed is not a correctness problem: it names OUR pid, so
    once this process exits the next claim's staleness check reclaims it.
    """
    for _ in range(CLAIM_LOCK_ATTEMPTS):
        try:
            lock.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(CLAIM_LOCK_DELAY_SECONDS)


def cmd_claim(args: argparse.Namespace) -> int:
    tasks_dir = tasks_dir_of(args)
    task_id = validate_id(args.id)
    owner = (args.owner or "").strip()
    if not owner:
        raise GraphError("owner must not be empty")
    lock = acquire_claim_lock(tasks_dir, task_id, owner)
    try:
        # The whole check-then-write runs under the lock: a second claim that slips between the
        # status check and the write of this one finds the lock taken and, once it is released,
        # re-reads the graph and sees the task already in_progress.
        tasks = load_tasks(tasks_dir)
        task = tasks.get(task_id)
        if task is None:
            raise GraphError(f"unknown task {task_id!r} in {tasks_dir}")
        if task["status"] != PENDING:
            raise GraphError(f"task {task_id!r} is {task['status']}: only pending tasks can be claimed")
        blocking = [dep for dep in task["blockedBy"] if tasks.get(dep, {}).get("status") != DONE]
        if blocking:
            raise GraphError(f"task {task_id!r} is not ready: blocked by {', '.join(blocking)}")

        task["status"], task["owner"] = IN_PROGRESS, owner
        write_task(task_path(tasks_dir, task_id), task)
    finally:
        release_claim_lock(lock)
    print(f"claimed: {task_id} -> {IN_PROGRESS} (owner: {owner})")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    tasks_dir = tasks_dir_of(args)
    task_id = validate_id(args.id)
    tasks = load_tasks(tasks_dir)
    task = tasks.get(task_id)
    if task is None:
        raise GraphError(f"unknown task {task_id!r} in {tasks_dir}")
    if task["status"] == DONE:
        print(f"already done: {task_id}")
        return 0
    if task["status"] != IN_PROGRESS:
        raise GraphError(f"task {task_id!r} is {PENDING}: claim it before completing it")
    task["status"] = DONE
    write_task(task_path(tasks_dir, task_id), task)
    print(f"completed: {task_id} -> {DONE}")
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    tasks_dir = tasks_dir_of(args)
    tasks = load_tasks(tasks_dir)
    ready = [tid for tid, task in sorted(tasks.items()) if is_ready(task, tasks)]
    for task_id in ready:
        print(task_id)
    print(f"ready: {len(ready)} of {len(tasks)} task(s)", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    tasks_dir = tasks_dir_of(args)
    tasks = load_tasks(tasks_dir)
    for task_id, task in sorted(tasks.items()):
        blocked = ",".join(task["blockedBy"]) or "-"
        print(f"{task_id}\t{task['status']}\t{task['owner'] or '-'}\t{blocked}\t{task['title']}")
    print(f"total: {len(tasks)} task(s)", file=sys.stderr)
    return 0


def sha256_of(path: pathlib.Path) -> str:
    if not path.is_file():
        raise GraphError(f"file not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_sha(args: argparse.Namespace) -> int:
    print(sha256_of(anchored(args.file, args.repo)))
    return 0


def cmd_verify_sha(args: argparse.Namespace) -> int:
    path = anchored(args.file, args.repo)
    actual = sha256_of(path)
    expected = args.expected.strip().lower()
    if expected.startswith("sha256:"):
        expected = expected[len("sha256:"):]
    if actual != expected:
        print(f"MISMATCH: {path} sha256={actual} expected={args.expected}", file=sys.stderr)
        return 1
    print(f"OK: {path} sha256={actual}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # The anchor is optional and defaults to the caller's cwd (fail-safe): nothing changes without
    # the flag.
    ap.add_argument("--repo", "--root", dest="repo", metavar="ROOT", default=None, help=REPO_HELP)
    sub = ap.add_subparsers(dest="command", required=True)

    def with_dir(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--dir", default=DEFAULT_TASKS_DIR,
                            help=f"tasks directory (default: {DEFAULT_TASKS_DIR})")
        add_repo(parser)
        return parser

    p_create = with_dir(sub.add_parser("create", help="create a pending task"))
    p_create.add_argument("--id", required=True)
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--blocked-by", default="", help="comma-separated dependency ids")
    p_create.set_defaults(func=cmd_create)

    p_claim = with_dir(sub.add_parser("claim", help="pending -> in_progress (only when ready)"))
    p_claim.add_argument("--id", required=True)
    p_claim.add_argument("--owner", required=True)
    p_claim.set_defaults(func=cmd_claim)

    p_complete = with_dir(sub.add_parser("complete", help="in_progress -> done"))
    p_complete.add_argument("--id", required=True)
    p_complete.set_defaults(func=cmd_complete)

    with_dir(sub.add_parser("ready", help="ids of the claimable tasks")).set_defaults(func=cmd_ready)
    with_dir(sub.add_parser("list", help="all tasks with status/owner/dependencies")).set_defaults(func=cmd_list)

    p_sha = sub.add_parser("sha", help="sha256 of a file")
    p_sha.add_argument("file")
    add_repo(p_sha)
    p_sha.set_defaults(func=cmd_sha)

    p_verify = sub.add_parser("verify-sha", help="compare a file's sha256 with the expected value")
    p_verify.add_argument("file")
    p_verify.add_argument("expected")
    add_repo(p_verify)
    p_verify.set_defaults(func=cmd_verify_sha)
    return ap


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except GraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

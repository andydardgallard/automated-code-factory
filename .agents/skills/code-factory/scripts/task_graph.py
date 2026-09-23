#!/usr/bin/env python3
"""
Deterministic on-disk task graph for the Code Factory — zero LLM tokens.

Tasks live as one JSON file per task in `.code-factory/state/tasks/<id>.json`:

  {"id": "task_01", "title": "...", "status": "pending|in_progress|done",
   "owner": "coder|null", "blockedBy": ["task_02"]}

The SCRIPT decides readiness (a pending task whose every `blockedBy` task is `done`), not a model:
`claim` refuses a task that is not ready or not pending, `create` refuses a dependency cycle, and
every write is atomic (temp file + replace), so a crashed or interrupted run never leaves a
half-written task file.

Commands:
  create --dir <tasks_dir> --id <id> --title "<title>" [--blocked-by id1,id2]
  claim  --id <id> --owner <role> [--dir <tasks_dir>]
  complete --id <id> [--dir <tasks_dir>]
  ready  [--dir <tasks_dir>]        # ids of the claimable tasks, one per line
  list   [--dir <tasks_dir>]        # id, status, owner, blockedBy, title
  sha <file>                        # sha256 of a file (checkpoint/resume)
  verify-sha <file> <expected>      # exit 0 when the file's sha256 matches <expected>

Default tasks dir: `.code-factory/state/tasks`. Exit code 0 = success, 1 = refused/failed.
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

PENDING, IN_PROGRESS, DONE = "pending", "in_progress", "done"
STATUSES = (PENDING, IN_PROGRESS, DONE)
DEFAULT_TASKS_DIR = ".code-factory/state/tasks"
TASK_FIELDS = ("id", "title", "status", "owner", "blockedBy")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class GraphError(Exception):
    """A refused command (bad id, unknown task, cycle, wrong status) — exits 1."""


def task_path(tasks_dir: pathlib.Path, task_id: str) -> pathlib.Path:
    return tasks_dir / f"{task_id}.json"


def validate_id(task_id: str, what: str = "task id") -> str:
    if not ID_RE.match(task_id):
        raise GraphError(f"invalid {what} {task_id!r}: use letters, digits, '.', '_' or '-'")
    return task_id


def read_task(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphError(f"cannot read task file {path}: {exc}") from exc
    missing = [f for f in TASK_FIELDS if f not in data]
    if missing:
        raise GraphError(f"task file {path} is missing field(s): {', '.join(missing)}")
    if data["status"] not in STATUSES:
        raise GraphError(f"task file {path} has unknown status {data['status']!r}")
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
    tasks_dir = pathlib.Path(args.dir)
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


def cmd_claim(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.dir)
    task_id = validate_id(args.id)
    owner = (args.owner or "").strip()
    if not owner:
        raise GraphError("owner must not be empty")
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
    print(f"claimed: {task_id} -> {IN_PROGRESS} (owner: {owner})")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.dir)
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
    tasks_dir = pathlib.Path(args.dir)
    tasks = load_tasks(tasks_dir)
    ready = [tid for tid, task in sorted(tasks.items()) if is_ready(task, tasks)]
    for task_id in ready:
        print(task_id)
    print(f"ready: {len(ready)} of {len(tasks)} task(s)", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.dir)
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
    print(sha256_of(pathlib.Path(args.file)))
    return 0


def cmd_verify_sha(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.file)
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
    sub = ap.add_subparsers(dest="command", required=True)

    def with_dir(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--dir", default=DEFAULT_TASKS_DIR,
                            help=f"tasks directory (default: {DEFAULT_TASKS_DIR})")
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
    p_sha.set_defaults(func=cmd_sha)

    p_verify = sub.add_parser("verify-sha", help="compare a file's sha256 with the expected value")
    p_verify.add_argument("file")
    p_verify.add_argument("expected")
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

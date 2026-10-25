#!/usr/bin/env python3
"""
Deterministic self-test for the repo-scoping contract (zero LLM tokens).

The canonical `repo-scoping` rule says a run resolves the task's `repo_path` ONCE and then places
EVERYTHING relative to that resolved target repository. This test proves it at SCRIPT level with a
scripted MINI-RUN whose repo_path is NOT the launch directory: a temp "launch" directory (standing
for the factory deployment folder, `git init`-ed so any stray artifact makes it visibly dirty) and a
separate temp "scratch" target repository (also `git init`-ed). From cwd = launch the deterministic
steps of a run are invoked exactly as the instruction layer prescribes — a RELATIVE artifact path
anchored by `--repo <scratch>`:

  run_id.py gen --repo <scratch> --task .code-factory/state/task.yaml
  run_id.py check --repo <scratch> --dir .code-factory
  factory_preflight.py --repo <scratch> --out .code-factory/state/preflight.json
  task_graph.py --repo <scratch> create --id task_01 --title ...
  error_router.py classify --repo <scratch> --log .code-factory/logs/errors.md
  verify_quotes.py --repo <scratch> --claims .code-factory/state/claims.json --report ...
  repo_inventory.py inventory --repo <scratch> --tracked

Asserted: every artifact lands under `<scratch>/.code-factory/` (and is read back from there), while
the launch directory stays untouched — the full path walk before/after the mini-run is identical and
`git -C <launch> status --porcelain` stays empty (a misplaced artifact would show up as untracked);
the git half of the contract holds too — the branch and the commit made via `git -C <scratch>` appear
in `git -C <scratch> log` while the launch repository's HEAD, branch, commit list and reflog are
byte-for-byte unchanged; the tracked inventory is anchored at `--repo` as well — `--tracked` reads
the TARGET repository's tracked set, so an untracked machine-local file inside the target stays out
of the review inventory while the flag-less walk still sees it; and the LEGACY default still works —
the same invocations WITHOUT `--repo`, run from cwd = the target repository, land in that repository
(backward compatibility).

The temp directories are removed at the end with a retry + read-only-attribute fallback (git keeps
its objects read-only and Windows can hold a just-closed file briefly). `git` must be on PATH: the
mini-run is a git-native run, and the test fails loudly rather than silently skipping that half.

Exit code 0 = all assertions pass, 1 = the contract was violated (the message names the case).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date

SCRIPTS = pathlib.Path(__file__).resolve().parent
RUN_ID = SCRIPTS / "run_id.py"
PREFLIGHT = SCRIPTS / "factory_preflight.py"
TASK_GRAPH = SCRIPTS / "task_graph.py"
ERROR_ROUTER = SCRIPTS / "error_router.py"
VERIFY_QUOTES = SCRIPTS / "verify_quotes.py"
REPO_INVENTORY = SCRIPTS / "repo_inventory.py"

# A tiny but real task file (the workspace of the mini-run) and an error log routing to the coder.
TASK_YAML = "title: repo scoping mini-run\nrepo_path: scratch\nmode: auto\n"
ERRORS_MD = "# Errors\nAssertionError: 1 != 2\n"
QUOTE = "AssertionError: 1 != 2"
CLAIMS = [{"quote": QUOTE, "source": ".code-factory/logs/errors.md"}]
BRANCH = "factory/repo-scoping"
COMMIT_MSG = "v0: mini-run artifacts"
# The commit identity is passed per command, so the test never depends on the machine's git config
# (a missing user.name would fail the commit) and a globally enabled commit signing cannot hang it.
IDENTITY = ("-c", "commit.gpgsign=false", "-c", "user.name=Factory Test",
            "-c", "user.email=factory@example.invalid")


def run(tool: pathlib.Path, *args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(tool), *args],
                          capture_output=True, text=True, errors="replace", cwd=str(cwd))


def git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`git -C <repo> <args>` — every repository this test touches lives in its own temp directory."""
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, errors="replace")


def git_ok(repo: pathlib.Path, *args: str) -> str:
    res = git(repo, *args)
    expect(res.returncode == 0, f"git -C {repo} {' '.join(args)} must succeed: {res.stderr!r}")
    return res.stdout


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def field(output: str, name: str) -> str:
    """Value of a `name: value` line of `error_router.py classify`; '' when the line is absent."""
    for line in output.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key == name:
            return value
    return ""


def expected_run_id(task: pathlib.Path) -> str:
    """Independent restatement of the documented id, so a wrong algorithm cannot agree with itself.

    The documented algorithm hashes the task bytes with CRLF normalized to LF (a platform-neutral
    id), so the restatement normalizes too.
    """
    text = task.read_bytes().replace(bytes([13, 10]), bytes([10]))
    return f"{date.today():%Y%m%d}-{hashlib.sha256(text).hexdigest()[:8]}"


def tree(root: pathlib.Path) -> set[str]:
    """Every path under `root`, relative and POSIX, WITHOUT the top-level `.git` metadata.

    A walking snapshot is what proves "nothing factory-related landed here": git only ever writes
    inside its own `.git`, so an artifact the mini-run misplaced shows up as a NEW path (and as an
    untracked entry in `git status`).
    """
    found: set[str] = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if rel.parts[0] != ".git":
            found.add(rel.as_posix())
    return found


def repo_state(repo: pathlib.Path) -> tuple[str, str, str, str]:
    """(HEAD, branch, reflog, every commit) — each field a git mutation in `repo` would change.

    A failing command contributes its stdout, which is empty (a repository without commits has no
    HEAD, no reflog, no log): the comparison is between two states of the SAME repository, so an
    absent value is as meaningful as a present one.
    """
    return (git(repo, "rev-parse", "HEAD").stdout.strip(),
            git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
            git(repo, "reflog", "--all").stdout,
            git(repo, "log", "--all", "--oneline").stdout)


def remove_tree(path: pathlib.Path, attempts: int = 3) -> None:
    """Best-effort removal of the temp mini-run.

    Git writes its objects read-only and Windows can keep a just-closed file locked for a moment
    (antivirus/indexer), so the read-only attribute is cleared and the removal retried. A lock that
    outlives the retries only warns: the directory is disposable and must never fail a passing test.
    """
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    try:
                        os.chmod(pathlib.Path(root) / name, stat.S_IWRITE)
                    except OSError:
                        pass
            if attempt < attempts:
                time.sleep(0.5)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        print(f"WARNING - could not remove the temporary mini-run {path}")


def main() -> int:
    expect(shutil.which("git") is not None,
           "git must be on PATH: this mini-run is a git-native run (see the git-native rule)")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="factory-repo-scoping-"))
    try:
        # 1. Setup: a "launch" directory (the deployment folder, git init-ed so a stray artifact
        #    makes it dirty and visible) and a SEPARATE "scratch" target repository. The run's
        #    repo_path is scratch — deliberately NOT the directory the steps are launched from.
        launch, scratch = tmp / "launch", tmp / "scratch"
        for repo in (launch, scratch):
            repo.mkdir()
            git_ok(repo, "init", "-q")
        cf = scratch / ".code-factory"
        task_file = cf / "state" / "task.yaml"
        task_file.parent.mkdir(parents=True)
        task_file.write_text(TASK_YAML, encoding="utf-8")
        errors = cf / "logs" / "errors.md"
        errors.parent.mkdir(parents=True)
        errors.write_text(ERRORS_MD, encoding="utf-8")
        claims = cf / "state" / "claims.json"
        claims.write_text(json.dumps(CLAIMS), encoding="utf-8")
        run_id = expected_run_id(task_file)
        launch_before, state_before = tree(launch), repo_state(launch)
        expect(git(launch, "status", "--porcelain").stdout == "",
               "the launch repository must start clean (nothing to hide a misplaced artifact)")

        # 2. run_id gen: the RELATIVE --task is resolved against --repo, so the id is computed from
        #    the TARGET's task file while the cwd is the launch directory. An absolute --task gives
        #    the same id, and without the flag the same relative path is not found — direct proof
        #    that the flag, not the cwd, is the base.
        res = run(RUN_ID, "gen", "--repo", str(scratch), "--task", ".code-factory/state/task.yaml",
                  cwd=launch)
        expect(res.returncode == 0, f"gen --repo must exit 0: {res.stderr!r}")
        expect(res.stdout.strip() == run_id,
               f"gen --repo must read the target task file: {res.stdout!r} != {run_id!r}")
        res = run(RUN_ID, "gen", "--repo", str(scratch), "--task", str(task_file), cwd=launch)
        expect(res.returncode == 0 and res.stdout.strip() == run_id,
               f"an absolute --task must yield the same id: {res.stdout!r} {res.stderr!r}")
        res = run(RUN_ID, "gen", "--task", ".code-factory/state/task.yaml", cwd=launch)
        expect(res.returncode == 1 and "Traceback" not in res.stderr,
               f"without --repo the task path stays relative to the cwd: {res.stderr!r}")

        # 3. run_id check: the relative `--dir .code-factory` scans the TARGET's artifacts (its
        #    unmarked logs/errors.md is named), while the launch directory has nothing to scan.
        res = run(RUN_ID, "check", "--repo", str(scratch), "--dir", ".code-factory", cwd=launch)
        expect(res.returncode == 1 and res.stdout.split() == ["logs/errors.md"],
               f"check --repo must scan the target's artifacts: {res.stdout!r} {res.stderr!r}")
        res = run(RUN_ID, "check", "--repo", str(launch), "--dir", ".code-factory", cwd=launch)
        expect(res.returncode == 0 and "0 checked" in res.stdout,
               f"the launch directory must hold no artifacts: {res.stdout!r}")

        # 4. preflight: the capability file lands at <scratch>/.code-factory/state/preflight.json,
        #    not in the launch directory.
        res = run(PREFLIGHT, "--repo", str(scratch), "--out", ".code-factory/state/preflight.json",
                  cwd=launch)
        expect(res.returncode == 0,
               f"preflight must exit 0 with python and git present: {res.stdout!r} {res.stderr!r}")
        preflight = cf / "state" / "preflight.json"
        expect(preflight.is_file(), "--repo must anchor a relative --out at the target repository")
        caps = json.loads(preflight.read_text(encoding="utf-8"))
        expect(bool(caps["python_cmd"]) and caps["git"] is True,
               f"the anchored capability file must be usable: {caps!r}")

        # 5. task graph: `create` is the subcommand that puts state on disk; its DEFAULT --dir
        #    (.code-factory/state/tasks) is anchored at --repo and `ready --repo` reads it back.
        res = run(TASK_GRAPH, "--repo", str(scratch), "create", "--id", "task_01",
                  "--title", "Scaffold the mini-run", cwd=launch)
        expect(res.returncode == 0, f"create --repo must exit 0: {res.stderr!r}")
        graph = cf / "state" / "tasks" / "task_01.json"
        expect(graph.is_file(), "the graph must land under <scratch>/.code-factory/state/tasks")
        expect(json.loads(graph.read_text(encoding="utf-8"))["status"] == "pending",
               f"the anchored graph must hold the created task: {graph}")
        expect(run(TASK_GRAPH, "--repo", str(scratch), "ready", cwd=launch).stdout.split()
               == ["task_01"], "ready --repo must read the anchored graph")
        expect(run(TASK_GRAPH, "ready", cwd=launch).stdout.split() == [],
               "the launch directory must hold no task graph")

        # 6. error routing: the relative --log is read from the target repository and the
        #    learned-pattern lookup stays <scratch>/.code-factory/state (no learned file here, so
        #    the defaults route the AssertionError to the coder).
        res = run(ERROR_ROUTER, "classify", "--repo", str(scratch), "--log",
                  ".code-factory/logs/errors.md", cwd=launch)
        expect(res.returncode == 0, f"classify --repo must exit 0: {res.stderr!r}")
        expect(field(res.stdout, "log") == str(errors),
               f"the anchored log must be the target's: {res.stdout!r}")
        expect((field(res.stdout, "category"), field(res.stdout, "route"),
                field(res.stdout, "pattern_id")) == ("ASSERTION", "coder", "19"),
               f"the anchored log must classify against the defaults: {res.stdout!r}")

        # 7. quotes: a relative --claims and its relative quote source resolve against --repo, and
        #    the relative --report lands in the target's logs.
        res = run(VERIFY_QUOTES, "--repo", str(scratch), "--claims",
                  ".code-factory/state/claims.json", "--report", ".code-factory/logs/quotes.json",
                  cwd=launch)
        expect(res.returncode == 0, f"an exact quote must verify: {res.stdout!r} {res.stderr!r}")
        report = cf / "logs" / "quotes.json"
        expect(report.is_file(), "--repo must anchor a relative --report at the target repository")
        expect(json.loads(report.read_text(encoding="utf-8"))["all_verified"] is True,
               "the anchored report must confirm the quote")
        res = run(VERIFY_QUOTES, "--claims", ".code-factory/state/claims.json", cwd=launch)
        expect(res.returncode == 1,
               "without --repo the claims path stays relative to the cwd (nothing to read there)")

        # 8. Every artifact of the mini-run exists under <scratch>/.code-factory/ ... and NOTHING of
        #    it is in the launch directory: the path walk is unchanged and git reports a clean work
        #    tree (a misplaced artifact would appear as `?? .code-factory/`).
        for rel in ("state/task.yaml", "state/preflight.json", "state/tasks/task_01.json",
                    "state/claims.json", "logs/errors.md", "logs/quotes.json"):
            expect((cf / rel).is_file(), f"{rel} must exist under <scratch>/.code-factory")
        expect(not (launch / ".code-factory").exists(),
               "no artifact tree may land in the launch directory")
        expect(tree(launch) == launch_before == set(),
               f"the launch directory must gain no file at all: {sorted(tree(launch))}")
        expect(git(launch, "status", "--porcelain").stdout == "",
               f"the launch repository must stay clean: {git(launch, 'status', '--porcelain').stdout!r}")

        # 9. The git half of the contract: the feature branch and the commit are made in the TARGET
        #    via `git -C <scratch>`, so they appear in the scratch log while the launch repository's
        #    HEAD, branch, commit list and reflog stay byte-for-byte unchanged.
        git_ok(scratch, "checkout", "-q", "-b", BRANCH)
        git_ok(scratch, "add", "-A")
        res = git(scratch, *IDENTITY, "commit", "-m", COMMIT_MSG)
        expect(res.returncode == 0, f"the commit in the target must succeed: {res.stderr!r}")
        expect(git_ok(scratch, "log", "--format=%s").splitlines() == [COMMIT_MSG],
               f"the commit must appear in `git -C <scratch> log`: {git_ok(scratch, 'log')!r}")
        expect(git_ok(scratch, "rev-parse", "--abbrev-ref", "HEAD").strip() == BRANCH,
               "the feature branch must be the scratch repository's branch")
        expect(".code-factory" in git_ok(scratch, "show", "--name-only", "--format="),
               "the scratch commit must carry the mini-run artifacts")
        expect(repo_state(launch) == state_before,
               f"the launch repository must be untouched: {repo_state(launch)!r} != {state_before!r}")
        expect(git(launch, "log", "--all", "--oneline").stdout == ""
               and git(launch, "reflog", "--all").stdout == "",
               "no commit and no reflog entry may appear in the launch repository")

        # 10. After the git work: still nothing in the launch directory, still a clean work tree.
        expect(tree(launch) == launch_before,
               f"the launch directory changed during the git half: {sorted(tree(launch))}")
        expect(git(launch, "status", "--porcelain").stdout == "",
               f"the launch repository must stay clean: {git(launch, 'status', '--porcelain').stdout!r}")

        # 11. Backward compatibility: the SAME invocations WITHOUT `--repo`, run from cwd = the
        #     target repository, still land in that repository — the flag-less default is the cwd,
        #     the behavior every earlier run relied on.
        res = run(RUN_ID, "gen", "--task", ".code-factory/state/task.yaml", cwd=scratch)
        expect(res.returncode == 0 and res.stdout.strip() == run_id,
               f"without --repo a relative --task resolves against the cwd: "
               f"{res.stdout!r} {res.stderr!r}")
        res = run(PREFLIGHT, "--out", ".code-factory/state/preflight-legacy.json", cwd=scratch)
        expect(res.returncode == 0, f"preflight without --repo must exit 0: {res.stderr!r}")
        expect((cf / "state" / "preflight-legacy.json").is_file(),
               "without --repo the relative --out stays in the cwd")
        res = run(TASK_GRAPH, "create", "--id", "legacy_01", "--title", "Legacy default", cwd=scratch)
        expect(res.returncode == 0 and (cf / "state" / "tasks" / "legacy_01.json").is_file(),
               f"without --repo the default graph dir stays in the cwd: {res.stderr!r}")
        res = run(ERROR_ROUTER, "classify", "--log", ".code-factory/logs/errors.md", cwd=scratch)
        expect(res.returncode == 0 and field(res.stdout, "category") == "ASSERTION",
               f"without --repo classify must read the cwd's log: {res.stdout!r} {res.stderr!r}")
        res = run(VERIFY_QUOTES, "--claims", ".code-factory/state/claims.json",
                  "--report", ".code-factory/logs/quotes-legacy.json", cwd=scratch)
        expect(res.returncode == 0 and (cf / "logs" / "quotes-legacy.json").is_file(),
               f"without --repo verify_quotes must write into the cwd: {res.stdout!r} {res.stderr!r}")
        expect(tree(launch) == set() and git(launch, "status", "--porcelain").stdout == "",
               "the launch directory must still hold nothing after the flag-less invocations")

        # 12. The tracked inventory is anchored at `--repo` like everything else: `inventory --tracked`
        #     reads the TARGET repository's tracked set (its committed `.code-factory/` artifacts are
        #     tracked, so they do appear), while an untracked machine-local file dropped into the target
        #     stays out of the review inventory — and the flag-less walk still sees it.
        (scratch / "machine.config.local").write_text("API_KEY=local-only\n", encoding="utf-8")
        res = run(REPO_INVENTORY, "inventory", "--repo", str(scratch), "--tracked", cwd=launch)
        expect(res.returncode == 0, f"inventory --tracked must exit 0: {res.stderr!r}")
        tracked_paths = [f["path"] for f in json.loads(res.stdout)["files"]]
        expect(".code-factory/state/task.yaml" in tracked_paths,
               f"the tracked set must come from the target repository: {tracked_paths}")
        expect("machine.config.local" not in tracked_paths,
               f"an untracked local file must stay out of the tracked inventory: {tracked_paths}")
        res = run(REPO_INVENTORY, "inventory", "--repo", str(scratch), cwd=launch)
        expect("machine.config.local" in [f["path"] for f in json.loads(res.stdout)["files"]],
               f"the flag-less walk must still see the local file: {res.stdout!r}")
        expect(tree(launch) == launch_before
               and git(launch, "status", "--porcelain").stdout == "",
               "the tracked-mode step must leave the launch directory untouched")
    finally:
        remove_tree(tmp)

    print("PASS - with repo_path != cwd every deterministic step of a run (run_id gen/check, "
          "preflight, task graph, error routing, quote verification, tracked inventory) places and "
          "reads its artifacts under <repo>/.code-factory/ via --repo, leaving the launch directory, "
          "its work tree, its HEAD and its reflog untouched; the git half lives in the target "
          "(`git -C <repo>`); and the flag-less invocation still resolves against the cwd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

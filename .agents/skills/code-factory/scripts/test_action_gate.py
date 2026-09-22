#!/usr/bin/env python3
"""
Deterministic self-test for `action_gate.py` (zero LLM tokens).

Covers the User Sovereignty contract:
  - HARD_DENY (exit 1 in BOTH modes): `git push` into main/master in every refspec form,
    `--force`/`--mirror` pushes, the same push hidden behind git GLOBAL options (`git -C repo
    push origin main`, `git -c a=b push ...`, joined `--git-dir=`/`--exec-path=` forms),
    `git reset --hard` on a remote ref, deletion of a filesystem root, and deletion outside the
    declared `--scope` (including "no scope declared" — the gate never guesses),
  - CONFIRM: destructive actions inside scope — `rm` of a scoped file, `git checkout --`,
    `git clean` — exit 2 in `--mode hitl`, exit 0 as `ALLOW_WITH_ASSUMPTION` in `--mode auto`;
    also any git invocation the gate cannot parse (unknown global option, missing option value,
    no subcommand) or does not know as read-only (`git frobnicate`, `git branch -D main`):
    fail-safe, never ALLOW,
  - ALLOW (exit 0): read-only commands (also with global options in front: `git -C repo status`),
    pushes/checkouts that provably stay off the default branch and inside scope, `git clean -n`,
  - the decision journal is created once, appended for EVERY check (timestamp/mode/class/decision),
    never rewritten, and its default path is honoured when `--journal` is omitted.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "action_gate.py"

ROW_RE = re.compile(r"^\| \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "check", *args],
                          capture_output=True, text=True, errors="replace", cwd=cwd)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        journal = tmp / "logs" / "action-gate.md"
        calls = 0

        def gate(*args: str) -> subprocess.CompletedProcess[str]:
            """Every gate call in this test is recorded in the shared journal."""
            nonlocal calls
            calls += 1
            return run(*args, "--journal", str(journal))

        # 1. ALLOW: read-only commands, including one that merely mentions a destructive verb;
        #    git global options in front of a read-only subcommand change nothing.
        for action in ("git status", "python -m pytest", "git log --oneline -5",
                       "git -C repo status", "git --no-pager log --oneline -5",
                       "git -c core.pager=cat diff", "git --git-dir=repo/.git rev-parse HEAD"):
            res = gate("--action", action)
            expect(res.returncode == 0, f"{action!r} must be allowed: {res.stdout!r}")
            expect("decision: ALLOW" in res.stdout, f"{action!r} must report ALLOW: {res.stdout!r}")

        # 2. HARD_DENY: push into the default branch, in every refspec form (both modes).
        for action in ("git push origin main", "git push origin master", "git push -f origin main",
                       "git push --force origin master", "git push --force-with-lease origin main",
                       "git push origin HEAD:main", "git push origin refs/heads/master",
                       "git push --mirror origin", "git push --all origin", "git push main"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                expect(res.returncode == 1,
                       f"{action!r} in {mode} must be HARD_DENY (exit 1): {res.returncode} "
                       f"{res.stdout!r}")
                expect("decision: HARD_DENY" in res.stdout,
                       f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 2b. HARD_DENY: git GLOBAL options in front of the subcommand must not hide the push —
        #     whether they carry a separate value, a joined value, or no value at all.
        for action in ("git -C repo push origin main", "git -C repo -c a=b push origin master",
                       "git -c a=b push --force origin main",
                       "git -c push.default=current push main",
                       "git --git-dir repo/.git push origin main",
                       "git --git-dir=repo/.git push origin main",
                       "git --work-tree repo push origin main", "git --work-tree=repo push main",
                       "git --exec-path=/usr/lib/git-core push origin main",
                       "git -P push --mirror origin", "git --paginate push --all origin",
                       "git --no-pager push -f origin master"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                expect(res.returncode == 1,
                       f"{action!r} in {mode} must be HARD_DENY (exit 1): {res.returncode} "
                       f"{res.stdout!r}")
                expect("decision: HARD_DENY" in res.stdout,
                       f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 2c. Fail-safe CONFIRM (never ALLOW): a git invocation the gate cannot parse — an unknown
        #     global option, a valued option without its value, no subcommand — or a subcommand it
        #     does not know to be read-only (it could be destructive: `git branch -D main`).
        for action in ("git --nowhere push origin main", "git --git-dir", "git -C repo",
                       "git", "git frobnicate", "git branch -D main",
                       "git update-ref -d refs/heads/main"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                if mode == "hitl":
                    expect(res.returncode == 2,
                           f"{action!r} in hitl must require confirmation: {res.returncode} "
                           f"{res.stdout!r}")
                    expect("decision: CONFIRM_REQUIRED" in res.stdout,
                           f"{action!r} must report CONFIRM_REQUIRED: {res.stdout!r}")
                else:
                    expect(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                           f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                expect("decision: ALLOW\n" not in res.stdout,
                       f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 3. ALLOW: pushes that provably stay off the default branch (also behind global options).
        for action in ("git push origin feature/hardening", "git push -f origin feature/main-fix",
                       "git push origin feature/x:feature/y", "git -C repo push origin feature/x",
                       "git --no-pager push -f origin feature/main-fix"):
            res = gate("--action", action)
            expect(res.returncode == 0, f"{action!r} must be allowed: {res.stdout!r}")

        # 3b. CONFIRM: the same bare push stays unprovable once global options are stripped.
        res = gate("--action", "git -C repo push")
        expect(res.returncode == 2, f"bare push behind globals must be confirmed: {res.stdout!r}")

        # 4. CONFIRM: a bare `git push` cannot be proven not to push the default branch.
        res = gate("--action", "git push")
        expect(res.returncode == 2, f"bare git push must require confirmation: {res.returncode}")

        # 5. reset: remote ref -> HARD_DENY, local ref -> ALLOW.
        for action in ("git reset --hard origin/main", "git reset --hard upstream/master",
                       "git reset --hard refs/remotes/origin/main"):
            res = gate("--action", action)
            expect(res.returncode == 1, f"{action!r} must be HARD_DENY: {res.stdout!r}")
        for action in ("git reset --hard HEAD~1", "git reset --soft HEAD~1"):
            res = gate("--action", action)
            expect(res.returncode == 0, f"{action!r} must be allowed: {res.stdout!r}")

        # 6. HARD_DENY: deletion of a filesystem root (independent of scope and mode).
        for action in ("rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf *", "rm -rf C:\\"):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 1, f"{action!r} must be HARD_DENY: {res.stdout!r}")

        # 7. HARD_DENY: deletion outside the declared scope.
        for action, scope in (("rm -rf other/data", "src"),
                              ("del /f /s /q C:\\temp\\x", "src"),
                              ("rmdir /s /q other", "src"),
                              ("rm -rf /var/lib/data", "src")):
            res = gate("--action", action, "--scope", scope)
            expect(res.returncode == 1,
                   f"{action!r} (scope {scope}) must be HARD_DENY: {res.stdout!r}")
            expect("HARD_DENY" in res.stdout, f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 8. HARD_DENY: destructive action with no scope at all — nothing can be proven in scope.
        res = gate("--action", "rm -rf build/out")
        expect(res.returncode == 1, "deletion without --scope must be HARD_DENY: " + res.stdout)
        expect("--scope" in res.stdout, f"the deny must hint at --scope: {res.stdout!r}")

        # 9. CONFIRM (hitl, exit 2) vs ALLOW_WITH_ASSUMPTION (auto, exit 0): inside scope.
        for action in ("rm src/old.py", "rm -rf src/generated", "git checkout -- src/a.py",
                       "git restore src/a.py", "git clean -fd", "git clean -fd src"):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 2,
                   f"{action!r} inside scope must require confirmation: {res.returncode} {res.stdout!r}")
            expect("decision: CONFIRM_REQUIRED" in res.stdout,
                   f"{action!r} must report CONFIRM_REQUIRED: {res.stdout!r}")
            res = gate("--action", action, "--scope", "src", "--mode", "auto")
            expect(res.returncode == 0,
                   f"{action!r} in auto mode must not be blocked: {res.returncode} {res.stdout!r}")
            expect("decision: ALLOW_WITH_ASSUMPTION" in res.stdout and "assumption:" in res.stdout,
                   f"{action!r} in auto mode must record an assumption: {res.stdout!r}")

        # 10. Out-of-scope checkout/clean stay HARD_DENY (scope also guards the working tree).
        for action in ("git checkout -- other/a.py", "git restore other/a.py", "git clean -fd other"):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 1, f"{action!r} outside scope must be HARD_DENY: {res.stdout!r}")

        # 11. `git clean -n` is a dry run -> ALLOW; `git checkout <branch>` does not discard work.
        for action in ("git clean -n", "git clean --dry-run -fd", "git checkout feature/x"):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 0, f"{action!r} must be allowed: {res.stdout!r}")

        # 12. A destructive command hidden behind `&&` is still found.
        res = gate("--action", "echo start && git push origin main", "--scope", "src")
        expect(res.returncode == 1, "a chained push into main must be HARD_DENY: " + res.stdout)

        # 13. Journal: created once with a header, one row per check, append-only.
        expect(journal.is_file(), f"the journal must be created at {journal}")
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        expect(len(rows) == calls, f"the journal must hold {calls} rows, found {len(rows)}")
        expect(text.count("# Action Gate Journal") == 1, "the journal header must be written once")
        expect("| hitl | HARD_DENY | HARD_DENY |" in text and "| auto | CONFIRM |" in text,
               f"rows must carry mode, class and decision: {text!r}")
        before = text
        res = gate("--action", "git status")
        expect(res.returncode == 0, "the extra check must be allowed")
        after = journal.read_text(encoding="utf-8")
        expect(after.startswith(before), "the journal must be append-only")

        # 14. Default journal path is relative to the working directory.
        workdir = tmp / "cwd"
        workdir.mkdir()
        res = run("--action", "git status", cwd=str(workdir))
        expect(res.returncode == 0, f"the default journal must not break the check: {res.stderr!r}")
        default_journal = workdir / ".code-factory" / "logs" / "action-gate.md"
        expect(default_journal.is_file(),
               f"the default journal must be {default_journal}, got {res.stdout!r}")

    print("PASS - action_gate.py hard-denies pushes to main/master (also behind git global options) "
          "and root/out-of-scope deletions; fail-safe CONFIRMs unparsable/unknown git calls; "
          "confirms in-scope destruction in hitl, records an assumption in auto; journal appended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

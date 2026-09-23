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
    never rewritten, and its default path is honoured when `--journal` is omitted; an unwritable
    journal (e.g. its parent is an existing regular file, on POSIX and on Windows) is an
    infrastructure error — exit 3 with an `error:` line on stderr and the classification still
    printed — never a traceback, never a blindly lost verdict,
  - the help text survives a legacy Windows console: the module docstring used as the parser
    description carries `→`, which cp1251 cannot encode, so `--help` and a usage error are both
    run under `PYTHONIOENCODING=cp1251` and must answer with help / exit 2 instead of a traceback.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "action_gate.py"
# A legacy Windows code page: it cannot represent `→` (U+2192), the character that used to blow up.
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

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

        # 15. An unwritable journal is an infrastructure error (exit 3), not a traceback: the
        #     journal's parent is an existing regular FILE (portable — chmod does not block writes
        #     on Windows), and the classification must survive on stdout.
        blocker = tmp / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        res = run("--action", "git status", "--journal", str(blocker / "journal.md"))
        output = res.stdout + res.stderr
        expect(res.returncode == 3,
               f"an unwritable journal must exit 3: {res.returncode} {output!r}")
        expect("cannot write" in res.stderr,
               f"the journal failure must be explained on stderr: {output!r}")
        expect("Traceback" not in output, f"the failure must not be a traceback: {output!r}")
        expect("decision: ALLOW" in res.stdout,
               f"the decision must still be printed when the journal fails: {output!r}")
        expect(not (blocker / "journal.md").exists(), "no journal file may be created")

        # 16. Encoding contract under a legacy Windows code page: the module docstring used as the
        #     ArgumentParser description carries `→`, which cp1251 cannot encode — argparse used to
        #     die with UnicodeEncodeError and a traceback instead of printing help. Both calls below
        #     run under PYTHONIOENCODING=cp1251 and are captured as BYTES, decoded as UTF-8, because
        #     the gate now forces UTF-8 on its own streams whatever the console is.
        legacy = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True,
                                env=LEGACY_ENV)
        text = (legacy.stdout + legacy.stderr).decode("utf-8", "replace")
        expect(legacy.returncode == 0,
               f"--help must exit 0 under PYTHONIOENCODING=cp1251: {text!r}")
        expect("Traceback" not in text, f"--help must not raise a traceback: {text!r}")
        expect("\u2192" in text,
               f"the help must keep its non-ASCII characters, not be stripped to ASCII: {text!r}")

        legacy = subprocess.run([sys.executable, str(TOOL), "--bogus"], capture_output=True,
                                env=LEGACY_ENV)
        text = (legacy.stdout + legacy.stderr).decode("utf-8", "replace")
        expect(legacy.returncode == 2,
               f"an unknown flag must still exit 2 under PYTHONIOENCODING=cp1251: "
               f"{legacy.returncode} {text!r}")
        expect("usage:" in text, f"an unknown flag must print a usage error: {text!r}")
        expect("Traceback" not in text, f"an unknown flag must not raise a traceback: {text!r}")

        # 17. `git stash` is classified explicitly instead of falling into the generic fail-safe:
        #     stashing rewrites the SHARED working tree of the run, where parallel agents keep
        #     uncommitted work, so every mutating form — bare (default `push`), push, pop, apply,
        #     drop, clear, whatever the flags — is CONFIRM with its own business reason citing the
        #     rulebook rule `no-shared-tree-git-mutations`, and never the generic fail-safe text.
        #     The reading forms (list/show, flags included) stay ALLOW, an unknown stash
        #     subcommand keeps the fail-safe CONFIRM, and the subcommand is read with git's own
        #     option parsing: the VALUES of -m/--message are consumed as values, so the mutating
        #     `git stash -m list` (a push with the message "list") can no longer buy an ALLOW — a
        #     negative control pins that hole shut, and `git stash -m "msg" list` still reads.
        fail_safe = "is not a subcommand the gate can prove harmless"
        for action in ("git stash", "git stash push", 'git stash push -m "wip"', "git stash pop",
                       "git stash apply stash@{0}", "git stash drop stash@{1}", "git stash clear"):
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
            expect("no-shared-tree-git-mutations" in res.stdout,
                   f"{action!r} must cite the rulebook rule it protects: {res.stdout!r}")
            expect(fail_safe not in res.stdout,
                   f"{action!r} must carry its own reason, not the generic fail-safe: {res.stdout!r}")
        for action in ("git stash list", "git stash list --oneline", "git stash show -p"):
            res = gate("--action", action)
            expect(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                   f"{action!r} only reads the stash and must be ALLOW: {res.stdout!r}")
        #     Negative control: a value flag must not smuggle a mutating push into a reading form.
        #     git parses `-m`/`--message` as taking a VALUE, so `git stash -m list` is a push whose
        #     message happens to be "list" — it must be CONFIRM, never the ALLOW of `git stash list`.
        for action in ("git stash -m list", "git stash --message show", "git stash -m show",
                       'git stash --message "wip"', "git stash -m"):
            res = gate("--action", action)
            expect(res.returncode == 2,
                   f"{action!r} mutates the working tree and must require confirmation: "
                   f"{res.returncode} {res.stdout!r}")
            expect("no-shared-tree-git-mutations" in res.stdout,
                   f"{action!r} must carry the mutating-stash reason: {res.stdout!r}")
            expect("decision: ALLOW\n" not in res.stdout,
                   f"{action!r} must never be a blind ALLOW: {res.stdout!r}")
        #     A real subcommand AFTER a consumed value is still read correctly both ways.
        for action in ('git stash -m "msg" list', "git stash --message=wip list"):
            res = gate("--action", action)
            expect(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                   f"{action!r} ends in the reading form `list` and must be ALLOW: {res.stdout!r}")
        res = gate("--action", "git stash push -m list")
        expect(res.returncode == 2 and "no-shared-tree-git-mutations" in res.stdout,
               f"'git stash push -m list' must stay CONFIRM (push wins, whatever -m says): "
               f"{res.returncode} {res.stdout!r}")
        res = gate("--action", "git stash bogus")
        expect(res.returncode == 2,
               f"an unknown stash subcommand must require confirmation: {res.returncode} {res.stdout!r}")
        expect(fail_safe in res.stdout,
               f"an unknown stash subcommand must keep the fail-safe reason: {res.stdout!r}")

    print("PASS - action_gate.py hard-denies pushes to main/master (also behind git global options) "
          "and root/out-of-scope deletions; fail-safe CONFIRMs unparsable/unknown git calls; "
          "confirms in-scope destruction in hitl, records an assumption in auto; classifies git "
          "stash explicitly (mutating forms CONFIRM with the no-shared-tree-git-mutations rule, "
          "list/show ALLOW, and values of -m/--message are consumed so they cannot hide a push); "
          "journal appended "
          "and an unwritable journal exits 3 instead of raising; --help and usage errors survive a "
          "legacy cp1251 console without a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  - shell wrappers (F1 regression): the payload of `sh`/`bash`/`dash`/`zsh` `-c`, cmd `/c`|`/k` and
    PowerShell/pwsh `-Command`/`-c` is classified recursively, so `sh -c "rm -rf /"` is the same
    root deletion as the bare `rm -rf /` and a wrapped push into main is as visible as a direct one
    (nesting and separators inside the quoted payload included); a wrapper whose payload cannot be
    read as command TEXT (`bash deploy.sh`, `pwsh -File x.ps1`, `-EncodedCommand`, a code flag
    without a payload, an ambiguous `-co`, an unknown flag) is CONFIRM — never a blind ALLOW,
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

        # 18. F1 (vaccination): a destructive PAYLOAD hidden inside a shell wrapper is classified
        #     exactly like the payload itself — the gate must never answer ALLOW because the only
        #     thing it saw was the wrapper's name. `sh -c "rm -rf /"` is the same root deletion as
        #     the bare `rm -rf /`, a wrapped push into main is as visible as a direct one, and the
        #     recursion also covers nesting and separators inside the quoted payload. Spellings
        #     covered: sh/bash/dash/zsh `-c` (combined flags like `-ec`/`-lc` included), cmd `/c`
        #     and `/k`, PowerShell/pwsh `-Command` and `-c`.
        wrapper_deny = (
            'sh -c "rm -rf /"', "sh -c 'rm -rf /'", "sh -ec 'rm -rf /'", "sh -c rm -rf /",
            'bash -c "rm -rf /"', 'bash -lc "rm -rf /"', 'dash -c "rm -rf /"',
            'zsh -c "rm -rf /"', 'sh -c "rm -rf / && echo done"',
            'bash -c "echo start; git push origin main"', 'sh -c \'bash -c "rm -rf /"\'',
            'cmd /c "rm -rf /"', 'cmd /C "del /f /s /q C:\\"', 'cmd.exe /c "rmdir /s /q C:\\"',
            'cmd /k "git push origin main"',
            'powershell -Command "rm -rf /"', 'powershell -c "rm -rf /"',
            'powershell -ConfigurationName main -Command "rm -rf /"',
            'pwsh -Command "rm -rf /"', 'pwsh -c "git push --force origin master"',
        )
        for action in wrapper_deny:
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                expect(res.returncode == 1,
                       f"{action!r} in {mode} hides a destructive payload and must be HARD_DENY "
                       f"(exit 1): {res.returncode} {res.stdout!r}")
                expect("decision: HARD_DENY" in res.stdout,
                       f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 18b. Fail-safe: a wrapper whose payload cannot be read as command TEXT is CONFIRM, never
        #      ALLOW — a script file, an encoded PowerShell block, a code flag with no payload at
        #      all, and the ambiguous `-co` (a prefix of -ConfigurationName/-ConfigurationFile
        #      too, so the gate refuses to guess that it means -Command).
        wrapper_unreadable = (
            "bash deploy.sh", "bash -x build.sh", "bash -n script.sh", "sh", "sh -c", "sh -c ''",
            "cmd", "cmd /d", "cmd /k", "pwsh", "powershell -NoProfile",
            "powershell -File deploy.ps1", "powershell -EncodedCommand ZQBjAGgAbwA=",
            "pwsh -File x.ps1", "powershell -ConfigurationName main",
            'powershell -co "rm -rf /"',
        )
        for action in wrapper_unreadable:
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

        # 18c. `--scope` still decides inside a wrapper: an in-scope deletion stays CONFIRM (hitl) /
        #      recorded assumption (auto), while a destructive payload out of scope stays HARD_DENY.
        for action in ('sh -c "rm src/old.py"', 'bash -c "rm -rf src/generated"',
                       'cmd /c "del src/old.py"', 'pwsh -Command "rm src/old.py"'):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 2,
                   f"{action!r} deletes inside scope and must require confirmation: "
                   f"{res.returncode} {res.stdout!r}")
            res = gate("--action", action, "--scope", "src", "--mode", "auto")
            expect(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                   f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
        for action in ('sh -c "rm -rf other/data"', 'cmd /c "del other/data"',
                       'powershell -Command "git push origin main"',
                       'sh -c "git reset --hard origin/main"'):
            res = gate("--action", action, "--scope", "src")
            expect(res.returncode == 1,
                   f"{action!r} is destructive out of scope and must be HARD_DENY: {res.stdout!r}")

        # 18d. The fix is not "every wrapper is suspect": a payload that IS readable and provably
        #      harmless stays ALLOW, and quoting is respected — a separator inside a quoted
        #      operand is data, not a command boundary.
        for action in ('sh -c "ls -la"', 'bash -c "git status"', 'cmd /c "git status"',
                       'pwsh -Command "git log --oneline"',
                       'powershell -NoProfile -c "python -m pytest"', 'sh -c "echo \'x; y\'"'):
            res = gate("--action", action)
            expect(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                   f"{action!r} runs a harmless payload and must be ALLOW: {res.stdout!r}")

        # 19. F1 rework (vaccination): the splitter's escape rules must be PER QUOTE TYPE, exactly
        #     like a real shell's. A single-quoted string has NO escapes — it ends at the next `'`
        #     whatever stands before it, so `echo 'a\' && rm -rf /` is `echo a\` followed by a real
        #     `rm -rf /`. In double quotes a backslash escapes only `$`, a backtick, `"`, `\` and a
        #     newline, so `echo "a\\" && rm -rf /` is `echo a\` followed by the same deletion. A
        #     quote-type-blind rule kept the quote open across the separator and ALLOWed both.
        quote_escape_deny = (
            r"echo 'a\' && rm -rf /",
            r'echo "a\\" && rm -rf /',
            r"echo 'a\' && git push origin main",
            r'''sh -c "echo 'a\' && rm -rf /"''',
            r"""sh -c 'echo "a\\" && rm -rf /'""",
            r'''bash -c "echo 'a\' && git push origin main"''',
        )
        for action in quote_escape_deny:
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                expect(res.returncode == 1,
                       f"{action!r} in {mode} runs a destructive command after the quoted operand "
                       f"and must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                expect("decision: HARD_DENY" in res.stdout,
                       f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 19b. Negative controls: the corrected escape rules must not over-deny. With no destructive
        #      command after the separator, the same quoted operands stay ALLOW — the double-quote
        #      rules keep `\"`, `\$`, a backtick and `\\` inside the string.
        for action in (r"echo 'a\'", r'echo "a\\"', r"echo 'a\' && echo ok",
                       r'echo "a\\" && echo ok', r'''sh -c "echo 'a\' && echo ok"''',
                       r'echo "a \"quoted\" \$HOME \`x\`"'):
            res = gate("--action", action)
            expect(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                   f"{action!r} is harmless echo text and must be ALLOW: {res.stdout!r}")

        # 20. F1 round 3 (vaccination): the `-c` / `/c` / `-Command` argument must be rebuilt the way
        #     the wrapper ITSELF reads it — adjacent quoted and unquoted runs concatenate into ONE
        #     argument, so `sh -c "echo "hi" && rm -rf X"` is exactly `sh -c 'echo hi && rm -rf X'`
        #     and the tail really runs. A first-quote-to-first-quote cut keeps only `echo ` and drops
        #     the rest, which is a destructive blind spot: such a line must never be ALLOW.
        concat_deny = (
            'sh -c "echo "hi" && rm -rf X"',
            'sh -c "echo "hi"; rm -rf /"',
            'bash -c "echo "hi" && rm -rf X"',
            'bash -c "echo "hi"; rm -rf /"',
            'sh -c "echo "hi" && git push origin main"',
            'bash -c \'sh -c "echo "hi" && rm -rf /"\'',
            'cmd /c "echo "hi" && rm -rf /"',
        )
        for action in concat_deny:
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                expect(res.returncode == 1,
                       f"{action!r} in {mode} runs the concatenated tail and must be HARD_DENY "
                       f"(exit 1): {res.returncode} {res.stdout!r}")
                expect("decision: HARD_DENY" in res.stdout,
                       f"{action!r} must report HARD_DENY: {res.stdout!r}")

        # 20b. Benign concatenation must not be over-denied: the same quoting shape with a harmless
        #      tail stays ALLOW, because the reconstructed payload is provably harmless.
        for action in ('sh -c "echo "hi""', 'sh -c "echo "hi" && echo ok"',
                       'sh -c "echo "hi"; echo ok"', 'bash -c "echo "hi" && git status"'):
            res = gate("--action", action)
            expect(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                   f"{action!r} runs a harmless concatenated payload and must be ALLOW: "
                   f"{res.stdout!r}")

        # 20c. What cannot be read as ONE finished argument is CONFIRM, never ALLOW: a `-c` line left
        #      inside an open quote has no complete command string yet (a real shell waits for the
        #      closing quote), so the gate refuses to guess a payload out of the truncated first quote.
        for action in ('sh -c "rm -rf /', "bash -c 'rm -rf /", 'sh -c "echo "hi" && rm -rf /'):
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

        # 21. F1 round 4 (vaccination, run 20261017-5cdfc7af): a PowerShell SINGLE-quoted
        #     `-Command`/`-c` payload must be classified exactly like its double-quoted and bare
        #     twins. PowerShell has a real single-quote literal (a doubled '' inside one is a single
        #     escaped quote), so the text after -Command is a command string carried in ONE argument;
        #     the gate cannot know whether the caller's shell already stripped those quotes, so the
        #     fail-safe contract makes it classify the inner text as a POTENTIAL command. The pre-fix
        #     Windows tokenizer reads `'` as a literal character, so the payload collapses into one
        #     harmless-looking token and every destructive vector below is ALLOW. Failures are
        #     COLLECTED here instead of raised one by one: the vaccination run has to enumerate EVERY
        #     failing vector, not stop at the first one.
        vaccination_failures: list[str] = []

        def check(cond: bool, msg: str) -> None:
            """Record a vaccination failure instead of aborting, so one red run lists them all."""
            if not cond:
                print(f"FAIL: {msg}")
                vaccination_failures.append(msg)

        def class_of(res: subprocess.CompletedProcess[str]) -> str:
            match = re.search(r"^class: (\S+)$", res.stdout, re.MULTILINE)
            return match.group(1) if match else ""

        def ps_spellings(binary: str, flag: str, payload: str) -> tuple[str, str, str]:
            """The three spellings of ONE payload: single-quoted, double-quoted, bare."""
            return (f"{binary} {flag} '{payload}'", f'{binary} {flag} "{payload}"',
                    f"{binary} {flag} {payload}")

        # 21a. Every destructive vector of the task in BOTH modes: pwsh and powershell, -Command and
        #      -c, the three payloads, single vs double vs bare. HARD_DENY (exit 1) in both modes and
        #      the SAME class in all three spellings - the single-quoted form must never be the one
        #      spelling that buys an ALLOW.
        ps_destructive = ("rm -rf /", "Remove-Item -Recurse -Force C:\\", "git push origin main")
        for binary in ("pwsh", "powershell"):
            for flag in ("-Command", "-c"):
                for payload in ps_destructive:
                    single, double, bare = ps_spellings(binary, flag, payload)
                    for mode in ("hitl", "auto"):
                        res = gate("--action", single, "--mode", mode)
                        check(res.returncode == 1,
                              f"{single!r} in {mode} hides a destructive payload and must be "
                              f"HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                        check("decision: HARD_DENY" in res.stdout,
                              f"{single!r} must report HARD_DENY: {res.stdout!r}")
                        twins = [gate("--action", twin, "--mode", mode) for twin in (double, bare)]
                        for spelling, twin in zip((double, bare), twins):
                            check(twin.returncode == 1 and "decision: HARD_DENY" in twin.stdout,
                                  f"the twin {spelling!r} in {mode} must stay HARD_DENY: "
                                  f"{twin.returncode} {twin.stdout!r}")
                        check(class_of(res) == class_of(twins[0]) == class_of(twins[1])
                              == "HARD_DENY",
                              f"{single!r} in {mode} must classify like its twins, got "
                              f"{class_of(res)!r} vs {class_of(twins[0])!r} / "
                              f"{class_of(twins[1])!r}")

        # 21b. Scoped destruction stays CONFIRM: the single-quoted spelling of an IN-SCOPE deletion is
        #      the same CONFIRM_REQUIRED (hitl, exit 2) and ALLOW_WITH_ASSUMPTION (auto, exit 0) as its
        #      twins - never the blind ALLOW the pre-fix tokenizer answers.
        for binary, flag, payload in (("pwsh", "-Command", "rm -rf src/generated"),
                                      ("pwsh", "-c", "rm -rf src/generated"),
                                      ("powershell", "-Command", "Remove-Item src/old.py"),
                                      ("powershell", "-c", "Remove-Item src/old.py")):
            single, double, bare = ps_spellings(binary, flag, payload)
            hitl = gate("--action", single, "--scope", "src")
            check(hitl.returncode == 2 and "decision: CONFIRM_REQUIRED" in hitl.stdout,
                  f"{single!r} inside scope must require confirmation in hitl: "
                  f"{hitl.returncode} {hitl.stdout!r}")
            auto = gate("--action", single, "--scope", "src", "--mode", "auto")
            check(auto.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in auto.stdout,
                  f"{single!r} inside scope must be a recorded assumption in auto: {auto.stdout!r}")
            for twin in (double, bare):
                twin_hitl = gate("--action", twin, "--scope", "src")
                check(twin_hitl.returncode == 2
                      and "decision: CONFIRM_REQUIRED" in twin_hitl.stdout,
                      f"the twin {twin!r} inside scope must stay CONFIRM_REQUIRED: "
                      f"{twin_hitl.returncode} {twin_hitl.stdout!r}")
                check(class_of(hitl) == class_of(twin_hitl) == "CONFIRM",
                      f"{single!r} must classify {class_of(hitl)!r} like its twin {twin!r} "
                      f"{class_of(twin_hitl)!r}")

        # 21c. Negative controls (no over-deny): a benign single-quoted payload is ALLOW in every
        #      spelling - "PowerShell invoked with single quotes" must not become a blanket deny.
        for binary, flag, payload in (("pwsh", "-Command", "Write-Host hi"),
                                      ("pwsh", "-c", "Write-Host hi"),
                                      ("powershell", "-Command", "Write-Host hi"),
                                      ("powershell", "-c", "Write-Host hi"),
                                      ("pwsh", "-Command", "hello"),
                                      ("powershell", "-c", "hello")):
            for spelling in ps_spellings(binary, flag, payload):
                res = gate("--action", spelling)
                check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                      f"the benign payload {spelling!r} must stay ALLOW: {res.stdout!r}")
        res = gate("--action", "pwsh -Command 'Write-Host hi'", "--mode", "auto")
        check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
              f"a benign single-quoted payload must stay ALLOW in auto too: {res.stdout!r}")

        # 21d. Fail-safe: what cannot be read as ONE finished command string is CONFIRM, never ALLOW -
        #      a single quote left open (the caller's shell has not finished reading the argument yet)
        #      and an empty or blank payload carry no command text that could be proven harmless.
        for action in ("pwsh -Command 'rm -rf /", "powershell -c 'git push origin main",
                       "pwsh -Command ''", "powershell -c ''", "powershell -c ' '"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 21e. A doubled single quote inside such a payload is ONE escaped quote (PowerShell's own
        #      rule), so it must not hide what follows it: a destructive tail after the escaped quote
        #      is still HARD_DENY, a benign one is still ALLOW.
        for action in ("pwsh -Command 'echo ''ok''; rm -rf /'",
                       "powershell -c 'Write-Host ''hi'' && git push origin main'",
                       "pwsh -c 'echo ''a''; Remove-Item -Recurse -Force C:\\'"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1 and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} runs a destructive command after an escaped quote and "
                      f"must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
        for action in ("pwsh -Command 'echo ''ok''; git status'",
                       "powershell -c 'Write-Host ''hi''; echo done'"):
            res = gate("--action", action)
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"{action!r} is benign text around an escaped quote and must be ALLOW: "
                  f"{res.stdout!r}")

        # 21f. Review rework (iteration 1, run 20261017-5cdfc7af): decoding a doubled quote can leave
        #      the INNER payload with an UNMATCHED quote — `pwsh -Command 'echo ''; rm -rf /'` decodes
        #      to the text `echo '; rm -rf /`, and `powershell -c 'echo ''; git push origin main'` to
        #      `echo '; git push origin main` — so what follows the stray quote is never read as a
        #      command boundary. A text whose quoting does not close cannot be proven harmless: the
        #      class must be CONFIRM and the mode mapping applied to it (CONFIRM_REQUIRED with exit 2
        #      in hitl, ALLOW_WITH_ASSUMPTION with exit 0 in auto), never a blind ALLOW.
        for action in ("pwsh -Command 'echo ''; rm -rf /'",
                       "powershell -c 'echo ''; git push origin main'"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} leaves an unterminated inner quote and must be CONFIRM, "
                      f"not {class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # One red run must list every failing vector, so the collected failures are raised only here,
        # after all of them have been exercised.
        if vaccination_failures:
            raise AssertionError(
                f"{len(vaccination_failures)} PowerShell single-quote vaccination assertion(s) "
                f"failed: every line above starting with FAIL is one bug-reproducing vector "
                f"(a single-quoted -Command/-c payload must classify like its twins)")

    print("PASS - action_gate.py hard-denies pushes to main/master (also behind git global options) "
          "and root/out-of-scope deletions; fail-safe CONFIRMs unparsable/unknown git calls; "
          "confirms in-scope destruction in hitl, records an assumption in auto; classifies git "
          "stash explicitly (mutating forms CONFIRM with the no-shared-tree-git-mutations rule, "
          "list/show ALLOW, and values of -m/--message are consumed so they cannot hide a push); "
          "classifies the payload of shell wrappers (sh/bash/dash/zsh -c, cmd /c|/k, "
          "powershell/pwsh -Command|-c) recursively, so a wrapped root deletion or push is as "
          "visible as the bare one and an unreadable payload CONFIRMs instead of ALLOWing; "
          "journal appended "
          "and an unwritable journal exits 3 instead of raising; --help and usage errors survive a "
          "legacy cp1251 console without a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

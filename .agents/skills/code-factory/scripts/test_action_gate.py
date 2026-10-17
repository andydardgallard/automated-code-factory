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
  - the decoded payload of a `powershell`/`pwsh` wrapper is split with POWERSHELL's quoting rules
    (a backslash is literal and never keeps a string open), so `pwsh -Command 'echo "\\"; rm -rf /'`
    and `powershell -c 'echo "\\"; git push origin main'` are HARD_DENY in both modes, a balanced
    benign backslash string stays ALLOW, and cmd.exe / POSIX payloads keep their own escape rules,
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

        # 22. Item 1 (vaccination, run 20261017-4beb46d5): the DECODED payload of a PowerShell wrapper
        #     is command TEXT in POWERSHELL's dialect, not POSIX. PowerShell has NO backslash escape —
        #     a backslash is a literal character — so `echo "\"` ENDS its string on the `"` after the
        #     backslash and the `;` that follows is a real command separator, exactly as a real pwsh
        #     reads it. Splitting that payload with the POSIX rules instead kept the string open across
        #     the `;` and swallowed the tail: both review-2 vectors below were ALLOW in hitl AND auto.
        #     Only the DOUBLED quote (`''` / `""`) is an escaped quote inside PowerShell's own quoting,
        #     and the POSIX/cmd.exe splitters are untouched (section 19 pins the POSIX `"a\\"` escape).
        ps_backslash_destructive = (r'echo "\"; rm -rf /', r'echo "\"; git push origin main')

        # 22a. Both review-2 vectors in every wrapper spelling of the task: pwsh and powershell,
        #      `-Command` and `-c`, hitl and auto. The readable destructive tail after the closed
        #      PowerShell string is HARD_DENY (exit 1) in both modes.
        for binary in ("pwsh", "powershell"):
            for flag in ("-Command", "-c"):
                for payload in ps_backslash_destructive:
                    action = f"{binary} {flag} '{payload}'"
                    for mode in ("hitl", "auto"):
                        res = gate("--action", action, "--mode", mode)
                        check(res.returncode == 1,
                              f"{action!r} in {mode} closes its PowerShell string before the `;` and "
                              f"runs a destructive tail; it must be HARD_DENY (exit 1): "
                              f"{res.returncode} {res.stdout!r}")
                        check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                              f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 22b. Same payload, the other TWO outer spellings (double-quoted and bare). Whichever shell
        #      the caller used, the gate cannot know how far it stripped and re-quoted those
        #      backslashes, so the ambiguous spelling must stay fail-safe: HARD_DENY or CONFIRM, but
        #      never the blind ALLOW that hid the tail.
        for binary in ("pwsh", "powershell"):
            for flag in ("-Command", "-c"):
                for payload in ps_backslash_destructive:
                    for spelling in (f'{binary} {flag} "{payload}"', f"{binary} {flag} {payload}"):
                        for mode in ("hitl", "auto"):
                            res = gate("--action", spelling, "--mode", mode)
                            check("decision: ALLOW\n" not in res.stdout,
                                  f"{spelling!r} in {mode} carries the same destructive tail and must "
                                  f"never be a blind ALLOW: {res.stdout!r}")
                            check(class_of(res) in ("HARD_DENY", "CONFIRM"),
                                  f"{spelling!r} in {mode} must classify as HARD_DENY or CONFIRM, got "
                                  f"{class_of(res)!r}: {res.stdout!r}")

        # 22c. Negative controls (no over-deny): a BALANCED backslash/quote string is benign text and
        #      keeps its previous ALLOW — the fix must not turn "PowerShell with a backslash" into a
        #      blanket deny. Nothing destructive follows the closed string, so every vector stays
        #      ALLOW even though the tail is now really split as a separate command.
        for action in (r'''pwsh -Command 'echo "C:\temp\x"; echo ok' ''',
                       r'''powershell -c 'Write-Host "a\"; echo ok' ''',
                       r'''pwsh -c 'echo ok; git status' ''',
                       r'''pwsh -Command 'echo "a\\"; echo ok' ''',
                       r'''powershell -Command 'Write-Host "C:\Program Files\x"' '''):
            res = gate("--action", action.strip())
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"the balanced backslash payload {action.strip()!r} must stay ALLOW: {res.stdout!r}")

        # 22d. A backslash payload whose readable tail is destructive but INSIDE scope keeps the
        #      ordinary mode mapping: CONFIRM_REQUIRED (hitl, exit 2) and ALLOW_WITH_ASSUMPTION
        #      (auto, exit 0) — the same verdicts its quote-free twins already get.
        for binary in ("pwsh", "powershell"):
            for flag in ("-Command", "-c"):
                for payload in (r'echo "\"; rm -rf src/generated',
                                r'echo "\"; Remove-Item src/old.py'):
                    action = f"{binary} {flag} '{payload}'"
                    hitl = gate("--action", action, "--scope", "src")
                    check(hitl.returncode == 2 and "decision: CONFIRM_REQUIRED" in hitl.stdout,
                          f"{action!r} deletes inside scope and must require confirmation in hitl: "
                          f"{hitl.returncode} {hitl.stdout!r}")
                    auto = gate("--action", action, "--scope", "src", "--mode", "auto")
                    check(auto.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in auto.stdout,
                          f"{action!r} inside scope must be a recorded assumption in auto: "
                          f"{auto.stdout!r}")
                    check("decision: ALLOW\n" not in hitl.stdout,
                          f"{action!r} must never be a blind ALLOW in hitl: {hitl.stdout!r}")

        # 22e. Malformed / unreadable controls: a payload whose PowerShell quoting never closes (an
        #      open `"`, a doubled quote that lost its partner) and a wrapper line left inside an open
        #      quote carry no finished command string, so they CONFIRM — never ALLOW.
        for action in ("pwsh -Command 'echo \"a\\'",
                       "pwsh -Command 'echo \"a\"\"; rm -rf /'",
                       "pwsh -Command 'echo \"\\\"; rm -rf /"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} cannot be read as one finished command string and must "
                      f"be CONFIRM, not {class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 22f. Every one of those decisions is journaled like any other: the shared journal holds one
        #      append-only row per gate call made so far, item-1 vectors included.
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        check(len(rows) == calls,
              f"every item-1 check must be journaled: {len(rows)} rows for {calls} gate calls")

        # 23. Item 2 (vaccination, run 20261017-4beb46d5): a harmless OUTER name must not hide what the
        #     line really runs. `env`, `sudo` and `builtin` are transparent launchers — their options
        #     and `env` assignments are parsed (never executed) and the command they run is classified
        #     like a bare one — and a readable `$(...)` is a potential command too, read with the
        #     enclosing shell's quoting rules. Pre-fix the gate classified the literal line, so every
        #     vector below was a blind ALLOW in both modes.

        # 23a. The documented destructive launcher forms, both modes: HARD_DENY (exit 1), because the
        #      inner command IS the root deletion / default-branch push of its bare twin.
        for action in ("env rm -rf /", "sudo rm -rf /", "builtin rm -rf /",
                       "env git push origin main", "sudo git push origin main",
                       "builtin git push origin main"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"the launcher {action!r} in {mode} hides a destructive command and must be "
                      f"HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 23b. The launchers' ORDINARY arguments must not hide the command either: env assignments,
        #      plain flags, separate/joined option values, the `--` terminator, and launchers and
        #      wrappers nesting in either order (the inner command is read recursively).
        for action in ("env FOO=1 rm -rf /", "env FOO=1 BAR=2 git push origin main",
                       "env -i rm -rf /", "env --ignore-environment rm -rf /",
                       "env -u FOO rm -rf /", "env -uFOO rm -rf /",
                       "env --unset=FOO git push origin main",
                       "env -C /tmp rm -rf /", "env --chdir=/tmp rm -rf /",
                       "env -- FOO=1 rm -rf /",
                       "sudo -n rm -rf /", "sudo -E rm -rf /", "sudo -u root rm -rf /",
                       "sudo -uroot rm -rf /", "sudo --user=root git push origin main",
                       "sudo -u root -- rm -rf /", "sudo -H -n -E git push origin master",
                       'sudo -u root sh -c "rm -rf /"',
                       'env bash -c "git push origin main"',
                       "sudo env git push --force origin master",
                       "env sudo builtin rm -rf /", 'sudo pwsh -c "git push origin main"'):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} keeps a destructive command behind ordinary launcher "
                      f"arguments and must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 23c. Readable `$(...)` substitutions: the shell runs their body, so they are classified at
        #      EVERY level — bare, inside a double-quoted operand, inside a wrapper payload, nested in
        #      another substitution, behind a launcher, and around one. The cmd.exe form is included
        #      because the gate cannot know whether the CALLER's shell expands it.
        for action in ('sh -c "$(rm -rf /)"', 'sh -c "$(git push origin main)"',
                       'bash -c "$(git push --force origin master)"',
                       'echo "$(rm -rf /)"', "echo $(rm -rf /)",
                       'echo "start $(rm -rf /) end"', 'echo "$(git push origin main)"',
                       'sh -c "echo $(rm -rf /)"',
                       'echo "$(echo "$(rm -rf /)")"',
                       'sudo sh -c "$(rm -rf /)"', 'echo "$(sudo rm -rf /)"',
                       'echo "$(env git push origin main)"',
                       'cmd /c "echo $(rm -rf /)"'):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} runs a destructive command substitution and must be "
                      f"HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 23d. The same at the deepest supported level: inside a decoded PowerShell payload, both a
        #      PowerShell subexpression and a launcher prefix are read recursively.
        for action in ("pwsh -Command 'Write-Host \"$(rm -rf /)\"'",
                       "powershell -c 'Write-Host \"$(git push origin main)\"'",
                       "pwsh -Command 'Write-Host \"$(Get-Date)\"; rm -rf /'",
                       "env pwsh -c 'git push origin main'",
                       "sudo powershell -Command 'Remove-Item -Recurse -Force C:\\'"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} hides a destructive command at a nested level and must be "
                      f"HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 23e. Negative controls (no over-deny): launchers around harmless commands keep their ALLOW.
        #      `env` without a command only prints the environment, so it stays harmless too.
        for action in ("env python -m pytest", "env FOO=1 git status", "env", "env -i",
                       "sudo -n git status", "sudo -u root ls -la", "builtin echo hi",
                       "builtin cd src", "env sudo git log --oneline -5",
                       'sudo bash -c "git status"'):
            res = gate("--action", action)
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"the benign launcher form {action!r} must stay ALLOW: {res.stdout!r}")

        # 23f. Negative controls for substitutions: text the enclosing shell does NOT execute is left
        #      alone — a substitution inside a literal single-quoted string, and one whose `$` is
        #      escaped in POSIX double quotes. A readable but harmless body stays ALLOW as well.
        for action in ("echo '$(rm -rf /)'", 'echo "\\$(rm -rf /)"',
                       "echo '$(git push origin main)'", 'echo "$(git status)"',
                       'sh -c "echo $(git log --oneline -5)"', 'echo "path $(pwd)"',
                       "pwsh -Command 'Write-Host \"$(Get-Date)\"'",
                       "echo \"$(echo 'a; b')\""):
            res = gate("--action", action)
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"the inert or harmless substitution {action!r} must stay ALLOW: {res.stdout!r}")

        # 23g. Fail-safe CONFIRM, never a blind ALLOW: launcher syntax the gate does not model (an
        #      unknown option, a missing option value, env's split-string -S, a launcher that names no
        #      command, sudo opening a shell) and a substitution whose `)` never closes carry no
        #      command that could be proven harmless.
        for action in ("sudo --nowhere rm -rf /", "sudo -u", "env -u", 'env -S "rm -rf /"',
                       "builtin", "sudo", "sudo -i", "sudo -s", 'echo "$(rm -rf /"',
                       'echo "$(echo $(rm -rf /)"'):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} cannot be read as a finished command and must be "
                      f"CONFIRM, not {class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 23h. `--scope` still decides inside a launcher or a substitution: an in-scope deletion keeps
        #      CONFIRM_REQUIRED (hitl, exit 2) and ALLOW_WITH_ASSUMPTION (auto, exit 0), exactly like
        #      the bare deletion it wraps.
        for action in ("sudo rm -rf src/generated", "env rm -rf src/generated",
                       'sh -c "echo $(rm -rf src/generated)"',
                       "env FOO=1 rm src/old.py"):
            hitl = gate("--action", action, "--scope", "src")
            check(hitl.returncode == 2 and "decision: CONFIRM_REQUIRED" in hitl.stdout,
                  f"{action!r} deletes inside scope and must require confirmation in hitl: "
                  f"{hitl.returncode} {hitl.stdout!r}")
            auto = gate("--action", action, "--scope", "src", "--mode", "auto")
            check(auto.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in auto.stdout,
                  f"{action!r} inside scope must be a recorded assumption in auto: {auto.stdout!r}")
            check("decision: ALLOW\n" not in hitl.stdout,
                  f"{action!r} must never be a blind ALLOW in hitl: {hitl.stdout!r}")
        #      ... while the same launcher forms out of scope stay HARD_DENY.
        for action in ("sudo rm -rf other/data", "env FOO=1 rm -rf /var/lib/data",
                       'sudo sh -c "echo $(del other/data)"'):
            res = gate("--action", action, "--scope", "src")
            check(res.returncode == 1,
                  f"{action!r} deletes outside scope and must be HARD_DENY: {res.stdout!r}")

        # 23i. These decisions are journaled like any other: still exactly one append-only row per
        #      gate call, item-2 vectors included.
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        check(len(rows) == calls,
              f"every item-2 check must be journaled: {len(rows)} rows for {calls} gate calls")

        # 24. Item 2 follow-up (vaccination, run 20261017-4beb46d5): `VAR=value` words before the
        #     command are ordinary launcher arguments for `sudo` too (the manual documents environment
        #     settings in that form), so the command AFTER them is classified like its bare twin. The
        #     pre-fix parser consumed assignments for `env` only and stopped at the first `VAR=value`
        #     after `sudo`, classified the assignment itself as a harmless command name and blind
        #     ALLOWed the destructive tail — `sudo FOO=1 rm -rf /`, `sudo -u root FOO=1 rm -rf /` and
        #     `env FOO=1 sudo FOO=2 rm -rf /` were all ALLOW (exit 0) in hitl and auto.

        # 24a. Readable `VAR=value` prefixes, alone and behind ordinary sudo options, nested with
        #      `env`/`sudo` and with a wrapper payload: HARD_DENY (exit 1) in both modes.
        for action in ("sudo FOO=1 rm -rf /", "sudo FOO=1 git push origin main",
                       "sudo -u root FOO=1 rm -rf /",
                       "sudo -E FOO=1 BAR=2 git push origin main",
                       "sudo -u root -- FOO=1 rm -rf /",
                       "env FOO=1 sudo FOO=2 rm -rf /",
                       "sudo FOO=1 env BAR=2 rm -rf /",
                       "sudo FOO=1 sudo BAR=2 git push origin master",
                       'sudo FOO=1 sh -c "rm -rf /"'):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} keeps a destructive command behind a sudo assignment "
                      f"and must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 24b. Negative controls: the same assignment forms around a harmless command stay ALLOW, so
        #      the fix does not turn a sudo assignment into a blanket deny.
        for action in ("sudo FOO=1 git status", "sudo -u root FOO=1 ls -la",
                       "env FOO=1 sudo FOO=2 git log --oneline -5", "sudo FOO=1 cat src/a.py"):
            res = gate("--action", action)
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"the benign sudo assignment {action!r} must stay ALLOW: {res.stdout!r}")

        # 24c. Only READABLE assignment syntax is stepped over: a first word that looks like one but is
        #      not `NAME=value`, and a `builtin` whose first word carries an assignment, are ambiguous —
        #      CONFIRM (hitl exit 2 / auto recorded assumption), never a blind ALLOW.
        for action in ("sudo 1FOO=1 rm -rf /", "sudo FOO-=1 rm -rf /", "sudo =1 rm -rf /",
                       "builtin FOO=1 rm -rf /"):
            for mode in ("hitl", "auto"):
                res = gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} carries an unreadable launcher word and must be CONFIRM, "
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

        # 24d. `--scope` still decides behind a sudo assignment: an in-scope deletion keeps
        #      CONFIRM_REQUIRED (hitl, exit 2) and ALLOW_WITH_ASSUMPTION (auto, exit 0).
        for action in ("sudo FOO=1 rm -rf src/generated", "env FOO=1 sudo BAR=2 rm src/old.py"):
            hitl = gate("--action", action, "--scope", "src")
            check(hitl.returncode == 2 and "decision: CONFIRM_REQUIRED" in hitl.stdout,
                  f"{action!r} deletes inside scope and must require confirmation in hitl: "
                  f"{hitl.returncode} {hitl.stdout!r}")
            auto = gate("--action", action, "--scope", "src", "--mode", "auto")
            check(auto.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in auto.stdout,
                  f"{action!r} inside scope must be a recorded assumption in auto: {auto.stdout!r}")
            check("decision: ALLOW\n" not in hitl.stdout,
                  f"{action!r} must never be a blind ALLOW in hitl: {hitl.stdout!r}")

        # 25. Item 2 review iteration 1 rework (vaccination, run 20261017-4beb46d5). Four edge defects
        #     of the launcher/substitution analysis, each reproduced below; every gate call goes through
        #     `check()` and every vector is guarded, so one crash (a RecursionError) cannot hide the
        #     failures of the others.
        def safe_gate(*args: str) -> subprocess.CompletedProcess[str]:
            """Run the gate and turn an unexpected harness error into a failing, not aborting, call."""
            try:
                return gate(*args)
            except Exception as exc:                     # pragma: no cover - red-run protection
                print(f"FAIL: the gate could not be run for {args!r}: {exc!r}")
                vaccination_failures.append(f"the gate could not be run for {args!r}: {exc!r}")
                return subprocess.CompletedProcess(args=[], returncode=-1, stdout="", stderr="")

        # 25a. Launcher recursion must keep QUOTE-AWARE argument boundaries. `FOO="a b"` is ONE
        #      argument whose value contains a space; a dequote/re-join round trip turned it into the
        #      words `a` and `b`, so the destructive command behind it became the argument of a bogus
        #      command name and the line was blind-ALLOWed. The same loss over-denied benign text.
        for action in ('env FOO="a b" rm -rf /', 'sudo -u root FOO="a b" git push origin main',
                       'env FOO="a b" BAR="c d" git push origin master',
                       'sudo -u root FOO="a b" sh -c "rm -rf /"'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} keeps a destructive command behind a QUOTED launcher "
                      f"argument and must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")
        #      ... and the same quoting shape around HARMLESS text must stay ALLOW: the `; rm -rf /`
        #      is inside the wrapper's single quotes, so no shell runs it.
        for action in ('sudo sh -c "echo \'; rm -rf /\'"',
                       'env FOO="a b" sh -c "echo \'; rm -rf /\'"',
                       'sudo FOO="a b" git status', 'env FOO="a b" echo hi'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                      f"{action!r} in {mode} runs only harmless text and must be ALLOW: {res.stdout!r}")

        # 25b. A BALANCED substitution body is extracted as a whole: the line used to be cut at the
        #      separators INSIDE `$(...)`, so the body reached the classifier in fragments and a
        #      readable destructive body was reported as an unclosed (malformed) substitution — a
        #      CONFIRM where HARD_DENY was due, and an auto assumption instead of a block.
        for action in ('echo $(git push origin main && echo ok)',
                       'echo $(rm -rf /; echo ok)',
                       'echo "$(git push origin main; echo ok)"',
                       'sh -c "echo $(rm -rf /; echo ok)"',
                       'echo $(echo $(rm -rf /; echo ok))',
                       'echo $(sudo rm -rf / && echo ok)'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} carries a destructive separator body and must be "
                      f"HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")
        #      Benign bodies with separators stay ALLOW, and the forms the shell does NOT execute are
        #      still inert (literal single quotes, an escaped `$`).
        for action in ('echo $(git status && echo ok)', 'echo $(echo a; echo b)',
                       "echo '$(rm -rf / && echo ok)'",
                       'echo "\\$(rm -rf /; echo ok)"'):
            res = safe_gate("--action", action)
            check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                  f"{action!r} is inert or harmless and must stay ALLOW: {res.stdout!r}")

        # 25c. Substitution recursion is BOUNDED: 1,200 nested benign `$()` bodies used to raise
        #      RecursionError (a traceback, no classification, no journal row). Deep nesting must
        #      answer the fail-safe CONFIRM with the ordinary mode mapping instead. The string is only
        #      ever DATA for the gate — it is never executed.
        deep_benign = "echo " + "$(" * 1200 + "git status" + ")" * 1200
        rows_before_deep = len([line for line in journal.read_text(encoding="utf-8").splitlines()
                                if ROW_RE.match(line)])
        for mode, code in (("hitl", 2), ("auto", 0)):
            res = safe_gate("--action", deep_benign, "--mode", mode)
            output = res.stdout + res.stderr
            check("Traceback" not in output and "RecursionError" not in output,
                  f"1,200-nested substitutions must not raise in {mode}: {output[:800]!r}")
            check(class_of(res) == "CONFIRM",
                  f"1,200-nested substitutions in {mode} must be a fail-safe CONFIRM, not "
                  f"{class_of(res)!r}: {res.stdout[:400]!r}")
            check(res.returncode == code,
                  f"1,200-nested substitutions in {mode} must exit {code}: {res.returncode} "
                  f"{res.stdout[:400]!r} {res.stderr[:400]!r}")
            if mode == "hitl":
                check("decision: CONFIRM_REQUIRED" in res.stdout,
                      f"deep nesting in hitl must require confirmation: {res.stdout[:400]!r}")
            else:
                check("decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                      f"deep nesting in auto must be a recorded assumption: {res.stdout[:400]!r}")
        rows_after_deep = len([line for line in journal.read_text(encoding="utf-8").splitlines()
                               if ROW_RE.match(line)])
        check(rows_after_deep - rows_before_deep == 2,
              f"both deep-nesting decisions must be journaled: {rows_after_deep - rows_before_deep} "
              f"row(s) added")

        # 25d. An EMPTY or blank substitution body is malformed input, not a harmless command: it
        #      carries no command string that could be proven safe, so it CONFIRMs (never a blind
        #      ALLOW) and is journaled like every other decision.
        for action in ("echo $()", 'echo "$( )"'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} has an empty substitution body and must be CONFIRM, not "
                      f"{class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 25e. Everything above is journaled like any other decision: one append-only row per call.
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        check(len(rows) == calls,
              f"every review-rework check must be journaled: {len(rows)} rows for {calls} gate calls")

        # 26. Item 2, review iteration 2 / Advisor rework (vaccination, run 20261017-4beb46d5): a
        #     launcher's OWN control words must be recognised by their DECODED value, because that is
        #     what the shell hands the launcher: `env "-i"` IS the option `-i`. The parser fed quoted
        #     raw spans into those predicates, so a quoted flag/terminator was read as the inner
        #     command name and the destructive tail behind it was blind-ALLOWed, while a quoted whole
        #     assignment (`env "FOO=a b" rm -rf /`) degraded into an unreadable CONFIRM. Every sibling
        #     of that class is pinned below, in both modes.

        # 26a. Quoted control words with a destructive tail: short flags, joined and long options,
        #      value options, the `--` terminator, whole assignments and terminator+assignment forms,
        #      for `env` and `sudo`, deletion and push analogues. HARD_DENY (exit 1) in both modes.
        for action in ('env "-i" rm -rf /', 'env "--ignore-environment" rm -rf /',
                       'env "-i" git push origin main',
                       'env "--" rm -rf /', 'env "--" git push origin main',
                       'env "-u" FOO rm -rf /', 'env "-uFOO" rm -rf /',
                       'sudo "-u" root rm -rf /', 'sudo "-uroot" rm -rf /',
                       'sudo "-u" root git push origin main',
                       'sudo "--user=root" git push origin main',
                       'sudo "--user=root" rm -rf /',
                       'env "FOO=a b" rm -rf /', 'env "FOO=a b" git push origin master',
                       'sudo "FOO=a b" git push origin main',
                       'env -- "FOO=a b" rm -rf /',
                       'env "-i" "FOO=a b" rm -rf /',
                       'sudo "sh" -c "rm -rf /"'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} hides a destructive command behind a QUOTED launcher "
                      f"control word and must be HARD_DENY (exit 1): {res.returncode} {res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 26b. Quoted but UNSUPPORTED or malformed control words stay fail-safe: an unsupported option
        #      (`env "-S"` is a split string the gate does not model), an unknown long option, a value
        #      option without its value, and an EMPTY command name carry no command that could be
        #      proven harmless, so they CONFIRM (hitl exit 2 / auto recorded assumption), never ALLOW.
        for action in ('env "-S" "a b" rm -rf /', 'sudo "--nowhere" rm -rf /',
                       'env "-u"', 'env "" rm -rf /', 'sudo "" git push origin main',
                       'builtin "" rm -rf /'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} carries an unreadable quoted control word and must be "
                      f"CONFIRM, not {class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 26c. Negative controls: quoting a launcher's own words around a HARMLESS command changes
        #      nothing — the same forms stay ALLOW in both modes, so the fix is not a blanket deny of
        #      quoted launcher syntax, and the quoted wrapper text of 25a stays benign.
        for action in ('env "-i" git status', 'env "--" git status',
                       'env "--ignore-environment" git log --oneline -5',
                       'sudo "-u" root ls -la', 'env "FOO=a b" echo hi',
                       'sudo "sh" -c "echo \'; rm -rf /\'"', 'env "-i"'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                      f"the benign quoted control word {action!r} in {mode} must stay ALLOW: "
                      f"{res.stdout!r}")

        # 26d. `--scope` still decides behind a quoted control word: an in-scope deletion keeps
        #      CONFIRM_REQUIRED (hitl, exit 2) and ALLOW_WITH_ASSUMPTION (auto, exit 0), while the
        #      out-of-scope form stays HARD_DENY.
        for action in ('sudo "-u" root rm -rf src/generated', 'env "FOO=a b" rm src/old.py'):
            hitl = safe_gate("--action", action, "--scope", "src")
            check(hitl.returncode == 2 and "decision: CONFIRM_REQUIRED" in hitl.stdout,
                  f"{action!r} deletes inside scope and must require confirmation in hitl: "
                  f"{hitl.returncode} {hitl.stdout!r}")
            auto = safe_gate("--action", action, "--scope", "src", "--mode", "auto")
            check(auto.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in auto.stdout,
                  f"{action!r} inside scope must be a recorded assumption in auto: {auto.stdout!r}")
            check("decision: ALLOW\n" not in hitl.stdout,
                  f"{action!r} must never be a blind ALLOW in hitl: {hitl.stdout!r}")
        for action in ('env "FOO=a b" rm -rf /var/lib/data', 'sudo "--" rm -rf other/data'):
            res = safe_gate("--action", action, "--scope", "src")
            check(res.returncode == 1,
                  f"{action!r} deletes outside scope and must be HARD_DENY: {res.stdout!r}")

        # 26e. Those decisions are journaled like every other one: one append-only row per call.
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        check(len(rows) == calls,
              f"every quoted-control check must be journaled: {len(rows)} rows for {calls} calls")

        # 27. Item 2 residual of the failed full-backlog attempt (vaccination): real bash runs
        #     `builtin -- rm -rf /` as `rm -rf /` — the terminator only ends option parsing and is
        #     never a command name. Taking it for one left the word after it unclassified, so the
        #     destructive tail was blind-ALLOWed. The whole class is pinned below, in both modes.

        # 27a. `builtin --` / `builtin "--"` in front of a destructive command IS that command:
        #      HARD_DENY (exit 1) in both modes, for the deletion and the push analogue, bare and
        #      quoted, and also when the whole line is the payload of a `sh -c` wrapper.
        for action in ("builtin -- rm -rf /", 'builtin "--" rm -rf /',
                       "builtin -- git push origin main", 'builtin "--" git push origin main',
                       "sh -c 'builtin -- rm -rf /'"):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 1,
                      f"{action!r} in {mode} hides a destructive command behind the `builtin --` "
                      f"option terminator and must be HARD_DENY (exit 1): {res.returncode} "
                      f"{res.stdout!r}")
                check(class_of(res) == "HARD_DENY" and "decision: HARD_DENY" in res.stdout,
                      f"{action!r} in {mode} must report HARD_DENY: {res.stdout!r}")

        # 27b. Negative controls: the same terminator in front of HARMLESS text changes nothing — it
        #      stays ALLOW in both modes, so the fix is not a blanket deny of `builtin --`.
        for action in ("builtin -- echo hi", 'builtin "--" echo hi'):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(res.returncode == 0 and "decision: ALLOW\n" in res.stdout,
                      f"the benign option terminator {action!r} in {mode} must stay ALLOW: "
                      f"{res.stdout!r}")
                check(class_of(res) != "HARD_DENY",
                      f"the benign option terminator {action!r} in {mode} must never be "
                      f"HARD_DENY: {res.stdout!r}")

        # 27c. bash's `builtin` accepts NO option other than the `--` terminator, so any other
        #      dash-option is ambiguous — it may be meant to step over the words behind it — and
        #      carries no command that could be proven harmless: CONFIRM (hitl exit 2 / auto
        #      recorded assumption), never a blind ALLOW.
        for action in ("builtin -v rm -rf /",):
            for mode in ("hitl", "auto"):
                res = safe_gate("--action", action, "--mode", mode)
                check(class_of(res) == "CONFIRM",
                      f"{action!r} in {mode} carries an unsupported builtin option and must be "
                      f"CONFIRM, not {class_of(res)!r}: {res.stdout!r}")
                if mode == "hitl":
                    check(res.returncode == 2 and "decision: CONFIRM_REQUIRED" in res.stdout,
                          f"{action!r} in hitl must require confirmation: "
                          f"{res.returncode} {res.stdout!r}")
                else:
                    check(res.returncode == 0 and "decision: ALLOW_WITH_ASSUMPTION" in res.stdout,
                          f"{action!r} in auto must be a recorded assumption: {res.stdout!r}")
                check("decision: ALLOW\n" not in res.stdout,
                      f"{action!r} must never be a blind ALLOW: {res.stdout!r}")

        # 27d. Those decisions are journaled like every other one: one append-only row per call.
        text = journal.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if ROW_RE.match(line)]
        check(len(rows) == calls,
              f"every builtin-terminator check must be journaled: {len(rows)} rows for {calls} calls")

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
          "and an unwritable journal exits 3 instead of raising; a `builtin --` option terminator "
          "cannot hide a destructive command while benign terminators stay ALLOW; --help and usage "
          "errors survive a legacy cp1251 console without a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

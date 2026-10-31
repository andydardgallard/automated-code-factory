#!/usr/bin/env python3
"""
Deterministic action gate (User Sovereignty) for the Code Factory — zero LLM tokens.

Every destructive shell action the factory wants to run is classified BEFORE it runs, by regex /
token parsing only (no model, no network, no repo state): the gate never guesses, so an action it
cannot prove safe is either confirmed by the user or blocked.

Classes and exit codes:
  ALLOW                 exit 0  — nothing destructive detected
  CONFIRM               exit 2 in `--mode hitl` (user confirmation required)
                        exit 0 in `--mode auto` (recorded as ALLOW_WITH_ASSUMPTION)
  HARD_DENY             exit 1  — blocked in BOTH modes
  journal failure       exit 3  — infrastructure error: the journal could not be written (the
                        classification is still printed, so the decision itself is not lost)

Git commands are classified by their SUBCOMMAND: the leading global options (`-C`, `-c`,
`--git-dir`, `--work-tree`, `--exec-path`, `-P`/`--paginate`, `--no-pager`, joined forms like
`--git-dir=...`) are stripped first, so `git -C repo push origin main` is a push like any other
and cannot buy an ALLOW with an option prefix.

Shell wrappers are transparent: the payload of `sh`/`bash`/`dash`/`zsh`/`ksh` with `-c` (combined
flags like `-ec`/`-lc` included), of `cmd` with `/c` or `/k`, and of `powershell`/`pwsh` with
`-Command` (the short `-c` too) is classified RECURSIVELY with the same rules — nesting included.
Quoting is resolved before the line is cut into simple commands, so a separator inside a quoted
operand can no longer tear a payload in half (`sh -c "rm -rf / && echo x"` is a root deletion, not
the harmless command `sh`). The command-string argument itself is rebuilt with the wrapper's OWN
tokenizer — adjacent quoted and unquoted runs CONCATENATE into one argument, as in a real shell — so
`sh -c "echo "hi" && rm -rf X"` is read as the `-c` argument `echo hi && rm -rf X` and denied,
instead of stopping at the `echo ` before the first inner quote.

PowerShell single quotes (fixed contract): a `powershell`/`pwsh` `-Command` (or `-c`) payload may be
a SINGLE-quoted literal — `pwsh -Command 'rm -rf /'`. From bash the outer shell strips those quotes
and pwsh really runs the text, while from cmd.exe they are literal and pwsh prints a string; the gate
cannot know the caller's shell, so it takes the fail-safe reading: the INNER text of a single-quoted
`-Command`/`-c` argument is classified as a POTENTIAL command, exactly like its double-quoted and
bare twins (`pwsh -Command 'rm -rf /'` is the same root deletion as `pwsh -Command "rm -rf /"` and
`pwsh -Command rm -rf /`). A doubled `''` inside such a literal is ONE escaped quote, PowerShell's
own rule, so `pwsh -Command 'echo ''ok''; rm -rf /'` is still the deletion behind the escaped quote.
Benign inner text (`pwsh -Command 'Write-Host hi'`) stays ALLOW — this is not a blanket deny of
single quotes — while an unreadable or ambiguous payload keeps the fail-safe CONFIRM, never an
ALLOW: a quote left open in the argument, an empty payload, and also an unmatched quote left in the
DECODED inner text (a doubled `''` that lost its partner turns `pwsh -Command 'echo ''; rm -rf /'`
into `echo '; rm -rf /`, which cannot be read as a finished command and must be confirmed, not
called harmless).

Launcher prefixes (fixed contract, run 20261017-4beb46d5): `env`, `sudo` and `builtin` are
TRANSPARENT. Their own options — a separate value (`sudo -u root`), a joined one (`--user=root`,
`-uroot`) — and the `NAME=VALUE` assignments `env` and `sudo` both document in front of the command
are parsed, never executed, and the command they run is classified recursively with the same rules:
`env rm -rf /`, `sudo rm -rf /` and `builtin rm -rf /` are the root deletion they really are,
`sudo FOO=1 rm -rf /` and `sudo -u root -- git push origin main` are that deletion and that push, the
`--` option terminator is honoured in front of the command (`builtin -- rm -rf /` is still that
deletion, while the benign `builtin -- echo hi` stays ALLOW), and
launchers nest with each other and with the shell wrappers in either order (`sudo sh -c "rm -rf /"`,
`env FOO=1 sudo FOO=2 rm -rf /`). The launcher's OWN words are read by their DECODED value — the shell
hands `sudo "-u" root rm -rf /` the option `-u` and `env "--" rm -rf /` the terminator, and
`env "FOO=a b" rm -rf /` the assignment — while the inner command keeps its original quoting, so those
forms hide nothing and a quoted assignment is not mistaken for an unreadable one. Only the forms the
gate models are read: an unknown or unsupported
option (`env -S`, whose value is a split string), a valued option without its value (`sudo -u`),
`sudo -i`/`-s` (they open a shell), `builtin` with no command, an unsupported `builtin` option
(`builtin -v ...`), an empty command name (`env "" ...`) and
a first word that only looks like an
assignment (`sudo 1FOO=1 ...`) CONFIRM — never an ALLOW. A benign launcher
(`env python -m pytest`, `sudo FOO=1 git status`, `builtin echo hi`) stays ALLOW, and `env` alone only
prints the environment.

Command substitutions (fixed contract, run 20261017-4beb46d5): a readable `$(...)` is a command the
SHELL runs, so its body is classified as a potential command at EVERY level and in every wrapper —
`sh -c "$(rm -rf /)"`, `echo $(rm -rf /)` and the PowerShell subexpression
`pwsh -Command 'Write-Host "$(rm -rf /)"'` are the deletion they would run, nested substitutions
included. A balanced body is read as ONE operand, separators inside it included, so
`echo $(git push origin main && echo ok)` and `echo $(rm -rf /; echo ok)` are those destructive
commands. Only what the enclosing shell really executes is read: a substitution inside a literal
single-quoted string (`echo '$(rm -rf /)'`) and one whose `$` is escaped in POSIX double quotes
(`echo "\\$(rm -rf /)"`) are text and stay ALLOW, while a `)` that never closes, an EMPTY body
(`echo $()`) and a nesting deeper than `MAX_WRAPPER_DEPTH` levels CONFIRM. Nothing is
evaluated or executed: no variable, arithmetic, glob or backtick expansion, and no substitution or
launcher is run to classify it. The gate still classifies what the line literally runs beyond these
constructs, which is why the two are read as commands rather than expanded.

PowerShell backslash semantics (fixed contract, run 20261017-4beb46d5): the DECODED payload of a
`powershell`/`pwsh` wrapper is command TEXT in PowerShell's OWN dialect, so it is split into simple
commands with PowerShell's quote/backslash rules, not the POSIX ones. A backslash there is a LITERAL
character and never escapes a quote, so `pwsh -Command 'echo "\\"; rm -rf /'` closes its string on
the quote after the backslash and really runs `rm -rf /`, and
`powershell -c 'echo "\\"; git push origin main'` is that push — both HARD_DENY, as is every
pwsh/powershell and -Command/-c spelling of them. Only a DOUBLED quote (`''` / `""`) is an escaped
quote inside its own quoting. The dialect belongs to that ONE payload: cmd.exe and POSIX payloads
keep their own splitter (a POSIX `"a\\\\"` still escapes, so `echo "a\\\\" && rm -rf /` stays a
deletion), and a balanced benign backslash string (`pwsh -c 'echo "C:\\temp\\x"; echo ok'`) stays
ALLOW instead of becoming a blanket deny. An outer spelling the gate cannot read on those terms —
or a payload whose PowerShell quoting never closes — keeps the fail-safe CONFIRM, never an ALLOW.

HARD_DENY rules:
  * `git push` (also `--force` / `-f` / `--mirror` / `--all`) that targets the default branch
    (`main` / `master`, in any refspec form: `main`, `refs/heads/main`, `origin/main`, `HEAD:main`),
  * `git push --all` / `--mirror` (they publish every local branch, default branch included),
  * `git reset --hard` against a remote-tracking ref (`origin/...`, `upstream/...`, `@{u}`,
    `refs/remotes/...`), and `git reset --hard` at a pathspec outside the declared scope,
  * deletion (`rm`, `rmdir`, `rd`, `del`, `erase`, `Remove-Item`, `git rm`) of a target that is NOT
    covered by the declared `--scope`: filesystem root / `/*` / `~` / a drive root, absolute paths
    outside scope, `..` escapes, and — deliberately — any delete when no `--scope` was given
    (without a declared scope nothing can be proven to be inside the task's scope),
  * a shell wrapper whose readable payload is one of the above — a wrapper is transparent, so
    `sh -c "rm -rf /"` is the same root deletion as `rm -rf /`.

CONFIRM rules (destructive but inside the declared scope, and anything the gate cannot read):
  * `git push` whose DESTINATION is `HEAD` (`git push origin HEAD`, `@`, `+HEAD`, `HEAD:HEAD`):
    HEAD is whatever branch is checked out, so on `main`/`master` that push IS the default-branch
    push — the destination is unproven, and only a proven non-default one (`HEAD:feature/x`) stays
    ALLOW,
  * deletion of a path covered by `--scope`,
  * `git checkout -- <path>` / `git restore` of paths inside scope. Without the `--` separator an
    operand that can only be a pathspec (`.`, `./...`, an absolute or home path, a wildcard)
    takes the SAME scope route — `.` IS a pathspec that discards the whole tree, never an ALLOW —
    and an operand with a path separator is ambiguous (a branch name or a path) and CONFIRMs;
    only a plain branch/ref switch (`git checkout main`, `git checkout -b feature`) does not
    discard file changes and stays ALLOW. A ref flag is no licence to ALLOW either: the
    `-b`/`-B`/`--orphan` branch forms take a branch and an optional start point; `--detach` stays
    ALLOW only when no pathspec follows it, because `git checkout --detach HEAD .` still restores
    `.` from HEAD over the uncommitted changes,
  * `git clean` (repo-wide by nature). `git clean -n` / `--dry-run` is a no-op → ALLOW,
  * `git stash` in its mutating forms: a bare `git stash` (which IS the default `push`), `push`,
    `pop`, `apply`, `drop`, `clear`. Stashing rewrites the SHARED working tree of the run, where
    parallel agents keep uncommitted work, so it can race them or lose their changes — therefore
    the confirmation reason cites the rulebook rule `no-shared-tree-git-mutations` (subagents never
    stash/reset/checkout/clean; only the main agent confirms such a mutation). The reading forms
    `git stash list` / `git stash show` (any flags: `show -p`, `list --oneline`) stay ALLOW, and an
    unknown stash subcommand keeps the fail-safe CONFIRM below like any other unclassified action.
    The subcommand is read with git's own option parsing (values of `-m`/`--message` are consumed
    as values), so a mutating push cannot masquerade as a reading form: `git stash -m list` is a
    push with the message "list" → CONFIRM, while `git stash -m "msg" list` is ALLOW: real git
    rejects it ("fatal: subcommand wasn't specified; 'push' can't be assumed due to unexpected
    token 'list'"), so no mutation can hide behind that form.
  * an unparsable git invocation — unknown global option, a valued global option without its value,
    no subcommand at all — and any git subcommand the gate does not know: fail-safe, because what
    the gate cannot read it never calls safe (`git frobnicate` / `git branch -D main` → CONFIRM),
  * a shell wrapper whose payload is not readable as command TEXT, and a wrapper nested deeper than
    `MAX_WRAPPER_DEPTH` levels: `bash deploy.sh` (a script file), `pwsh -File x.ps1` /
    `-EncodedCommand <blob>`, a `-c` / `/c` with no payload at all, an unknown flag, the ambiguous
    `-co` (also a prefix of PowerShell's `-ConfigurationName`/`-ConfigurationFile`), or a line left
    INSIDE an open quote (`sh -c "rm -rf /`), whose command string a real shell has not finished
    reading yet. Fail-safe: what the gate cannot read it never calls harmless — it CONFIRMs, never
    ALLOWs.

Usage:
  python action_gate.py check --action "git push origin main" [--mode hitl|auto] \\
      [--scope src] [--scope tests] [--journal .code-factory/logs/action-gate.md]

Every decision is appended to the journal (timestamp, action, class, mode, decision, scope,
reason); the journal is created on first use and never rewritten. If the journal cannot be
written (e.g. its parent is a regular file), the classification is printed first and the gate
exits 3 with an `error:` line on stderr instead of raising a traceback.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import posixpath
import re
import sys

ALLOW, CONFIRM, HARD_DENY = "ALLOW", "CONFIRM", "HARD_DENY"
DEFAULT_JOURNAL = ".code-factory/logs/action-gate.md"
DEFAULT_BRANCHES = ("main", "master")
JOURNAL_TITLE = "# Action Gate Journal"
JOURNAL_HEADER = ("| timestamp | mode | class | decision | scope | action | reason |",
                  "| --- | --- | --- | --- | --- | --- | --- |")

# class + mode -> recorded decision, and decision -> exit code.
DECISION = {
    (ALLOW, "hitl"): "ALLOW",
    (ALLOW, "auto"): "ALLOW",
    (CONFIRM, "hitl"): "CONFIRM_REQUIRED",
    (CONFIRM, "auto"): "ALLOW_WITH_ASSUMPTION",
    (HARD_DENY, "hitl"): "HARD_DENY",
    (HARD_DENY, "auto"): "HARD_DENY",
}
EXIT_CODE = {"ALLOW": 0, "CONFIRM_REQUIRED": 2, "ALLOW_WITH_ASSUMPTION": 0, "HARD_DENY": 1}

# Simple-command separators: the classification runs per command, so a destructive command hidden
# behind `&&` / `;` / `|` is still found when the whole line is passed as one `--action`. They only
# separate OUTSIDE quotes (`split_commands`), otherwise a wrapper's quoted payload would be cut in
# half before the gate could read it.
COMMAND_SPLIT_RE = re.compile(r"&&|\|\||[&;|\n]")
# Backslash escapes INSIDE a quoted run, per quote type, exactly as a real shell reads them: a
# single-quoted string has NONE (it ends at the next `'`, whatever stands before it), while in
# double quotes a backslash escapes only `$`, a backtick, `"`, `\` and a newline. A quote-type-blind
# rule kept `'a\'` open across the following separator and hid `rm -rf /` behind it.
QUOTE_ESCAPES = {'"': frozenset({"$", "`", '"', "\\", "\n"}), "'": frozenset()}
# Shell-ish tokenizer that keeps quotes and backslashes (Windows paths) intact.
TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')

# Shell wrappers: the gate reads the command string they will run and classifies THAT, so a
# destructive payload cannot hide behind the wrapper's name (`sh`, not `rm`, used to be the only
# thing the gate saw). `-c` is the command-string flag of every POSIX shell listed here, cmd uses
# `/c` and `/k`, PowerShell/pwsh use `-Command` (the short `-c` included).
SHELL_WRAPPERS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "cmd", "powershell", "pwsh"})
# The wrappers whose payload is PowerShell TEXT. It is split with PowerShell's quoting rules, where a
# backslash is a literal character (see `split_commands_powershell`); every other payload keeps the
# POSIX / cmd.exe rules it is really read with.
POWERSHELL_WRAPPERS = frozenset({"powershell", "pwsh"})
# The dialect of ONE command TEXT: POSIX (backslash escapes a quote inside a quoted run, see
# QUOTE_ESCAPES) or PowerShell (it never does). The dialect belongs to a single text, never to the
# whole run, so a PowerShell payload cannot change how a POSIX or cmd.exe payload is read.
POSIX_DIALECT, POWERSHELL_DIALECT = "posix", "powershell"
POSIX_COMMAND_FLAG_RE = re.compile(r"-[A-Za-z]*c[A-Za-z]*")     # -c, -ec, -lc
CMD_COMMAND_FLAGS = ("/c", "/k")
# PowerShell parameter spellings the gate trusts as `-Command`. `-co` is deliberately NOT among
# them: it is also a prefix of -ConfigurationName / -ConfigurationFile (valued options), so an
# ambiguous spelling stays unreadable → CONFIRM rather than a guessed payload.
POWERSHELL_COMMAND_FLAGS = ("c", "com", "comm", "comma", "comman", "command")
# ... and flags whose value is a script file / an encoded block: no command TEXT to classify.
POWERSHELL_UNREADABLE = ("file", "encodedcommand")
# A nested wrapper is analyzed recursively; the cap keeps a pathologically nested line from
# blowing the stack — beyond it the wrapper is CONFIRM (fail-safe), never ALLOW.
MAX_WRAPPER_DEPTH = 6

# Launcher prefixes: a harmless OUTER name that merely runs the command after it. They are TRANSPARENT
# like the shell wrappers — their own options (and `env`'s NAME=VALUE assignments) are parsed, never
# executed, and the command they run is classified recursively, so `env rm -rf /` is the deletion it
# really is. The values of a launcher's own options are consumed like a real `getopt` consumes them.
LAUNCHER_PREFIXES = frozenset({"env", "sudo", "builtin"})
# `NAME=VALUE` words a launcher accepts before the command it runs: `env` documents them, and `sudo`
# documents environment settings in the same form, so a readable assignment is an ordinary launcher
# argument on both. A word that only LOOKS like one stays unreadable (CONFIRM), never an ALLOW.
LAUNCHER_ASSIGNMENTS = frozenset({"env", "sudo"})
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Launcher options that take NO value (joined `--opt=value` still carries its own).
LAUNCHER_FLAGS = {
    "env": frozenset({"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}),
    "sudo": frozenset({"-A", "--askpass", "-b", "--background", "-E", "--preserve-env", "-e",
                       "--edit", "-H", "--set-home", "-i", "--login", "-K", "--remove-timestamp",
                       "-k", "--reset-timestamp", "-l", "--list", "-n", "--non-interactive",
                       "-P", "--preserve-groups", "-S", "--stdin", "-s", "--shell", "-v",
                       "--validate", "-V", "--version"}),
    "builtin": frozenset(),
}
# ... and the options whose value is the NEXT token (or follows `=` / is joined to a short flag).
LAUNCHER_VALUE_FLAGS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-p", "--prompt", "-h", "--host", "-C",
                       "--close-from", "-D", "--chdir", "-R", "--chroot", "-r", "--role", "-t",
                       "--type", "-T", "--command-timeout", "-U", "--other-user"}),
    "builtin": frozenset(),
}

DELETE_COMMANDS = {"rm", "rm.exe", "rmdir", "rd", "del", "erase", "remove-item", "ri"}
DELETE_FLAG_RE = re.compile(r"^/[a-z][a-z0-9]*$")          # cmd.exe switches: /f /s /q /ah
ROOT_TARGETS = {"", "/", "~", "/*", "$home", "${home}", "%userprofile%", "%homedrive%"}
DRIVE_ROOT_RE = re.compile(r"^[a-z]:/?$")
REMOTE_REF_PREFIXES = ("origin/", "upstream/", "refs/remotes/", "@{u", "@{upstream}")
# git global options that stand BEFORE the subcommand and take a separate value argument.
GIT_GLOBAL_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace",
                         "--config-env"}
# ... and those that take no value.
GIT_GLOBAL_FLAGS = {"-P", "--paginate", "--no-pager"}
# joined forms: `-C<path>`, `-c<name>=<value>` (the valued long options use `--opt=value`).
GIT_GLOBAL_JOINED_RE = re.compile(r"^-[Cc].+")
# Subcommands that only READ: they cannot touch the default branch or the working tree, so they
# stay ALLOW. Every other subcommand the gate does not classify is CONFIRM (fail-safe).
GIT_READ_ONLY = {"blame", "cat-file", "check-attr", "check-ignore", "count-objects", "describe",
                 "diff", "diff-index", "diff-tree", "for-each-ref", "grep", "help", "log",
                 "ls-files", "ls-remote", "ls-tree", "merge-base", "name-rev", "rev-parse",
                 "shortlog", "show", "status", "verify-commit", "verify-tag", "version",
                 "whatchanged"}
GIT_READ_ONLY_REASON = "reads only; it cannot touch the default branch or the working tree"
# `git stash` subcommands that only read the stash, and those that rewrite the working tree.
# A bare `git stash` IS the default `push`, so it mutates too.
STASH_READ_ONLY = {"list", "show"}
STASH_MUTATING = {"push", "pop", "apply", "drop", "clear"}
# `git stash` options that TAKE A VALUE: the token after them is that value, never a subcommand
# (`git stash -m list` is a push carrying the message "list", not the reading form `git stash
# list`). Joined forms (`--message=list`) hold their value in the same token, so they hide nothing.
STASH_VALUE_FLAGS = ("-m", "--message")
STASH_MUTATING_REASON = ("rewrites the SHARED working tree of the run, where parallel agents keep "
                         "uncommitted work: stashing can race them or lose their changes (rulebook "
                         "rule no-shared-tree-git-mutations — subagents never stash/reset/checkout/"
                         "clean, only the main agent confirms such a mutation)")


def tokens(command: str) -> list[str]:
    """Split a single simple command into argv-like tokens (quotes preserved as delimiters)."""
    return [m.group(1) if m.group(1) is not None else
            m.group(2) if m.group(2) is not None else m.group(3)
            for m in TOKEN_RE.finditer(command)]


def token_spans(command: str, dialect: str = POSIX_DIALECT) -> list[tuple[str, str]]:
    """`(raw span, decoded value)` for every argv-like token, in order and INDEX-ALIGNED.

    One launcher word needs both views: the DECODED value is what the shell hands the program, so a
    control word is recognised however it was quoted (`env "-i"` IS the option `-i`), while the RAW span
    keeps its quoting so the command text can be rebuilt without losing argument boundaries. Tying them
    to one scan keeps index `i` naming the same word in both views, which is what lets `strip_launcher`
    decide on `decoded[i]` and rebuild the remaining command from `raw[i:]`.

    `tokens` DEQUOTES (a value is compared the way the shell would hand it over) but cannot rebuild
    text; a raw-only view cannot recognise control words. This returns both. A quoted run stays quoted
    in the raw span, adjacent quoted / unquoted runs stay ONE token, and the decoded value resolves
    quotes and escapes per the enclosing dialect's rules (`QUOTE_ESCAPES` for POSIX, a doubled quote for
    PowerShell), so `env FOO="a b" rm -rf /` still carries the assignment `FOO=a b` as ONE word.
    """
    spans: list[tuple[str, str]] = []
    raw: list[str] = []
    value: list[str] = []
    quote = ""
    powershell = dialect == POWERSHELL_DIALECT
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            raw.append(ch)
            if powershell and ch == quote:
                if i + 1 < len(command) and command[i + 1] == quote:    # '' / "" = escaped quote
                    raw.append(command[i + 1])
                    value.append(ch)
                    i += 2
                    continue
                quote = ""
            elif not powershell and ch == "\\" and i + 1 < len(command) \
                    and command[i + 1] in QUOTE_ESCAPES[quote]:
                raw.append(command[i + 1])
                value.append(command[i + 1])                            # the escape resolves away
                i += 2
                continue
            elif not powershell and ch == quote:
                quote = ""
            else:
                value.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            raw.append(ch)
            i += 1
            continue
        if ch.isspace():
            if raw:
                spans.append(("".join(raw), "".join(value)))
                raw, value = [], []
            i += 1
            continue
        if ch == "\\" and not powershell and i + 1 < len(command):
            raw.append(ch)
            raw.append(command[i + 1])
            value.append(command[i + 1])                                # `\"` outside quotes is `"`
            i += 2
            continue
        raw.append(ch)
        value.append(ch)
        i += 1
    if raw:
        spans.append(("".join(raw), "".join(value)))
    return spans


def split_commands(action: str, dialect: str = POSIX_DIALECT) -> list[str]:
    """Simple-command TEXTS of `action`, split only at separators OUTSIDE quotes.

    Quoting matters because a wrapper keeps its payload in ONE argument: cutting
    `sh -c "rm -rf / && echo x"` at the quoted `&&` would leave the gate with the mangled `sh -c
    "rm -rf` and lose the deletion. Inside a quoted run a separator is data, and which backslash
    sequences are escapes is decided PER QUOTE TYPE (`QUOTE_ESCAPES`) exactly as a real shell
    reads them — a single-quoted string has none, so `echo 'a\\' && rm -rf /` really is `echo a\\`
    followed by the deletion, while in double quotes `\\\\` and `\\"` are escapes.

    `dialect` is the dialect of THIS text: a PowerShell payload is PowerShell's own quoting, where a
    backslash never escapes anything (`split_commands_powershell`); everything else is POSIX.

    The returned text is the LINE VERBATIM (quotes and backslashes included): the splitter only
    decides where one simple command ends, and `posix_argv` re-reads the text afterwards — the
    tokenizer here must not resolve quoting on its own or argument boundaries would be lost.
    """
    if dialect == POWERSHELL_DIALECT:
        return split_commands_powershell(action)
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(action):
        ch = action[i]
        if quote:
            escaped = (ch == "\\" and i + 1 < len(action)
                       and action[i + 1] in QUOTE_ESCAPES[quote])
            if escaped:                                  # copy the pair verbatim, quote stays open
                buf += [ch, action[i + 1]]
                i += 2
                continue
            if ch == quote:
                quote = ""
            buf.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "\\":
            buf.append(ch)
            buf.append(action[i + 1] if i + 1 < len(action) else "")
            i += 2
            continue
        elif ch == "$" and action.startswith("$(", i):
            i = copy_substitution(action, i, buf, POSIX_DIALECT)
            continue
        else:
            match = COMMAND_SPLIT_RE.match(action, i)
            if match:
                parts.append("".join(buf))
                buf = []
                i = match.end()
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [part for part in parts if part.strip()]


def split_commands_powershell(action: str) -> list[str]:
    """Simple-command TEXTS of a PowerShell payload, split with POWERSHELL's quoting rules.

    PowerShell has NO backslash escape: a backslash is a literal character, so a `"` always ends the
    string it opened, whatever stands before it. Read with the POSIX rules, `echo "\\"; rm -rf /` kept
    the string open across the `;` (the `\\"` looked like an escaped quote) and swallowed the
    deletion, although a real pwsh closes the string on that quote and runs `rm -rf /`. Only a DOUBLED
    quote (`''` / `""`) is an escaped quote inside its own quoting — the same rule
    `powershell_quote_complete` applies, and the two must agree: a payload that passes that check never
    ends inside a quote here.

    The POSIX and cmd.exe splitters are untouched: a POSIX `"a\\\\"` still escapes, so this dialect can
    never change how a non-PowerShell payload is read. Like `split_commands`, the returned text is the
    LINE VERBATIM (quotes and backslashes included) — only the boundaries are decided here.
    """
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(action):
        ch = action[i]
        if quote:
            if ch == quote:
                if i + 1 < len(action) and action[i + 1] == quote:   # '' / "" is one escaped quote
                    buf += [ch, action[i + 1]]
                    i += 2
                    continue
                quote = ""
            buf.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "$" and action.startswith("$(", i):
            i = copy_substitution(action, i, buf, POWERSHELL_DIALECT)
            continue
        match = COMMAND_SPLIT_RE.match(action, i)
        if match:
            parts.append("".join(buf))
            buf = []
            i = match.end()
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [part for part in parts if part.strip()]


def copy_substitution(text: str, start: int, buf: list[str], dialect: str) -> int:
    """Copy the whole `$(...)` starting at `start` into `buf`; return the index just past it.

    A substitution body is ONE operand of the enclosing command, whatever separators it contains, so
    the separator scan must keep it intact and let `substitution_bodies` cut it out as a whole:
    `echo $(git push origin main && echo ok)` is the push, not the fragment `echo $(git push origin
    main ` followed by ` echo ok)` — cutting it first made a readable destructive body look like an
    UNCLOSED substitution (a CONFIRM instead of the HARD_DENY it deserves). An unclosed `$(` is copied
    to the end of the line, so `substitution_bodies` still reports it as unreadable.
    """
    end = matching_paren(text, start + 2, dialect)
    stop = len(text) if end is None else end + 1
    buf.append(text[start:stop])
    return stop


def matching_paren(text: str, start: int, dialect: str) -> int | None:
    """Index of the `)` closing a substitution body that starts at `start`, or None if it never does.

    Nested parentheses are counted (`$(echo $(rm -rf /))`), and quoting inside the body is skipped with
    the dialect's own rules, so a `)` inside a quoted string of the body does not close it early.
    """
    depth = 0
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if dialect == POWERSHELL_DIALECT:
                if ch == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    quote = ""
                i += 1
                continue
            if ch == "\\" and i + 1 < len(text) and text[i + 1] in QUOTE_ESCAPES[quote]:
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "\\" and dialect == POSIX_DIALECT:
            i += 2
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == ")":
            return i
        i += 1
    return None


def substitution_bodies(text: str, dialect: str = POSIX_DIALECT) -> tuple[list[str], bool]:
    """`(inner command texts of the `$(...)` this shell runs, was the text completely read)`.

    A `$(...)` substitution is not a value the gate can expand: the shell RUNS it, so the only safe
    reading is to classify its body as a potential command. Which substitutions really run depends on
    the enclosing shell's quoting rules, and only those are returned:

      * POSIX: a substitution inside a literal single-quoted string (`echo '$(rm -rf /)'`) is text,
        and so is one whose `$` is escaped in double quotes (`echo "\\$(rm -rf /)"`) — both inert,
      * PowerShell: a single-quoted string is literal too, while inside a double-quoted string a
        subexpression DOES run (`Write-Host "$(Get-Date)"`),
      * no expansion is attempted at all: this scans quoting, it does not evaluate anything.

    `False` means a `$(` never closes, so no command string can be proven — the caller CONFIRMs it.
    """
    bodies: list[str] = []
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if dialect == POWERSHELL_DIALECT:
                if ch == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    quote = ""
                    i += 1
                    continue
                if ch == "$" and quote == '"' and text.startswith("$(", i):
                    end = matching_paren(text, i + 2, dialect)
                    if end is None:
                        return bodies, False
                    bodies.append(text[i + 2:end])
                    i = end + 1
                    continue
                i += 1
                continue
            if ch == "\\" and i + 1 < len(text) and text[i + 1] in QUOTE_ESCAPES[quote]:
                i += 2                                  # escaped (`\$`, `\"`): never a substitution
                continue
            if ch == quote:
                quote = ""
                i += 1
                continue
            if ch == "$" and quote == '"' and text.startswith("$(", i):
                end = matching_paren(text, i + 2, dialect)
                if end is None:
                    return bodies, False
                bodies.append(text[i + 2:end])
                i = end + 1
                continue
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "\\" and dialect == POSIX_DIALECT:
            i += 2                                      # `\$(x)` outside quotes is literal text
            continue
        if ch == "$" and text.startswith("$(", i):
            end = matching_paren(text, i + 2, dialect)
            if end is None:
                return bodies, False
            bodies.append(text[i + 2:end])
            i = end + 1
            continue
        i += 1
    return bodies, True


def posix_argv(line: str) -> tuple[list[str], bool]:
    """`(argv a POSIX shell builds from line, was the line completely read)`.

    Quotes are resolved the way the shell does — they are REMOVED from the value and adjacent
    quoted / unquoted runs CONCATENATE into one argument, so `"echo "hi"` is the single argument
    `echo hi` (this is why `sh -c "echo "hi" && rm -rf X"` really runs `rm`). Escapes follow the
    per-quote-type rules (`QUOTE_ESCAPES`) inside a quoted run and escape the next character
    outside them.

    The flag is False when the line ends INSIDE a quote: the shell has not finished reading the
    argument yet, so no payload can be proven — the caller must CONFIRM instead of guessing it from
    the text read so far.
    """
    argv: list[str] = []
    buf: list[str] = []
    open_token = False                       # the token has content (a '' run is a real, empty arg)
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            escaped = (ch == "\\" and i + 1 < len(line) and line[i + 1] in QUOTE_ESCAPES[quote])
            if escaped:
                buf.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            open_token = True
            i += 1
            continue
        if ch == "\\" and i + 1 < len(line):
            buf.append(line[i + 1])
            open_token = True
            i += 2
            continue
        if ch.isspace():
            if open_token:
                argv.append("".join(buf))
                buf, open_token = [], False
            i += 1
            continue
        buf.append(ch)
        open_token = True
        i += 1
    if open_token:
        argv.append("".join(buf))
    return argv, not quote


def windows_argv(line: str) -> tuple[list[str], bool]:
    """`(argv cmd.exe builds from line, was the line completely read)`.

    cmd.exe has no POSIX backslash escape and no single-quote quoting at all: a `"` merely TOGGLES
    quoting and a `'` is a literal character, so it follows the line character by character. Quotes
    are removed from the value and adjacent runs concatenate; an unbalanced `"` makes the line
    unreadable (`complete` is False), so the caller CONFIRMs instead of guessing. PowerShell uses
    `powershell_argv` instead — its single quotes are real quoting.
    """
    argv: list[str] = []
    buf: list[str] = []
    open_token = False
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            open_token = True
            continue
        if ch.isspace() and not in_quotes:
            if open_token:
                argv.append("".join(buf))
                buf, open_token = [], False
            continue
        buf.append(ch)
        open_token = True
    if open_token:
        argv.append("".join(buf))
    return argv, not in_quotes


def powershell_argv(line: str) -> tuple[list[str], bool]:
    """`(argv PowerShell builds from line, was the line completely read)`.

    PowerShell quoting is the Windows one — `"` and now also `'` merely TOGGLE quoting, there is no
    POSIX backslash escape, so `powershell -Command "Remove-Item -Recurse -Force C:\\"` really closes
    the argument on that quote and keeps the backslash, and `pwsh -Command 'rm -rf /'` carries the
    whole deletion as ONE argument. A doubled `''` inside a single-quoted literal is ONE escaped
    quote (PowerShell's own rule), so it neither ends the literal nor hides what follows it.

    Quotes are removed from the value and adjacent runs concatenate; a quote left OPEN makes the
    line unreadable (`complete` is False), because the caller's shell has not finished reading the
    argument and no payload can be proven — the caller CONFIRMs it instead of guessing.
    """
    argv: list[str] = []
    buf: list[str] = []
    open_token = False
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                if quote == "'" and i + 1 < len(line) and line[i + 1] == "'":
                    buf.append("'")                      # '' is one escaped quote, literal goes on
                    open_token = True
                    i += 2
                    continue
                quote = ""
            else:
                buf.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            open_token = True
            i += 1
            continue
        if ch.isspace():
            if open_token:
                argv.append("".join(buf))
                buf, open_token = [], False
            i += 1
            continue
        buf.append(ch)
        open_token = True
        i += 1
    if open_token:
        argv.append("".join(buf))
    return argv, not quote


def is_git(argv: list[str]) -> bool:
    return bool(argv) and pathlib.PurePath(argv[0]).name.lower() in ("git", "git.exe")


def strip_git_globals(argv: list[str]) -> tuple[list[str], str]:
    """Drop the leading global options: `(argv from the subcommand, problem)`.

    A non-empty `problem` means the invocation could not be parsed — the caller CONFIRMs it,
    because a gate that cannot see the real subcommand must never call the action harmless.
    """
    i = 1
    while i < len(argv):
        token = argv[i]
        if not token.startswith("-") or token == "-":
            return [*argv[:1], *argv[i:]], ""
        if token in GIT_GLOBAL_FLAGS:
            i += 1
        elif token in GIT_GLOBAL_VALUE_OPTS:
            if i + 1 >= len(argv):
                return [], f"the global option {token} is missing its value"
            i += 2
        elif "=" in token and token.split("=", 1)[0] in GIT_GLOBAL_VALUE_OPTS:
            i += 1
        elif GIT_GLOBAL_JOINED_RE.match(token):
            i += 1
        else:
            return [], f"the global option {token} is not recognised"
    return [], "no subcommand follows the global options"


def norm(path: str) -> str:
    """Normalise a shell path token for scope comparison (backslashes, quotes, `./`)."""
    p = path.strip().strip('"').strip("'").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def target_base(target: str) -> str:
    """Path part of a delete target: trailing wildcards removed, trailing slashes dropped."""
    p = norm(target)
    while p.endswith("*") or p.endswith("/"):
        p = p[:-1]
    return p


def is_root_target(target: str) -> bool:
    base = target_base(target)
    return base.lower() in ROOT_TARGETS or bool(DRIVE_ROOT_RE.match(base))


def in_scope(target: str, scopes: list[str]) -> bool:
    """True when `target` is the scope path itself or lives below one of the scopes."""
    if not scopes:
        return False
    t = posixpath.normpath(target_base(target))
    for scope in scopes:
        s = posixpath.normpath(norm(scope)).rstrip("/")
        if s and (t == s or t.startswith(s + "/")):
            return True
    return False


def is_default_branch_ref(token: str) -> bool:
    """True when the refspec/token names main or master as a full ref component."""
    parts = re.split(r"[:/@]", norm(token))
    return any(part in DEFAULT_BRANCHES for part in parts)


# A push whose DESTINATION is one of these publishes whatever branch is checked out right now.
HEAD_PUSH_DESTINATIONS = ("HEAD", "@")


def push_destination(refspec: str) -> str:
    """Destination side of a push refspec (`src:dst` -> `dst`), force marker `+` removed."""
    return norm(refspec).split(":", 1)[-1].lstrip("+").strip()


def is_head_push_destination(refspec: str) -> bool:
    """True when the refspec publishes to HEAD (`git push origin HEAD`, `@`, `+HEAD`).

    `HEAD` is not a branch name but a pointer to whatever is checked out, so `git push origin
    HEAD` pushes the default branch whenever `main`/`master` is checked out. The gate classifies
    a command line, not a repository, so it can never prove that destination non-default —
    an unproven destination CONFIRMs, it is never an ALLOW.
    """
    return push_destination(refspec) in HEAD_PUSH_DESTINATIONS


def flags_of(argv: list[str]) -> list[str]:
    return [t for t in argv if t.startswith("-") and t != "-"]


def operands_of(argv: list[str], skip: int) -> list[str]:
    """Non-flag operands after the subcommand (`skip` tokens: argv[0] and the subcommand)."""
    return [t for t in argv[skip:] if not (t.startswith("-") and t != "-")]


def classify_push(argv: list[str]) -> tuple[str, str]:
    flags = flags_of(argv)
    operands = operands_of(argv, 2)
    if any(f in ("--all", "--mirror") for f in flags):
        return HARD_DENY, "git push --all/--mirror publishes every local branch, default branch included"
    hits = [t for t in operands if is_default_branch_ref(t)]
    if hits:
        return HARD_DENY, f"git push targets the default branch ({', '.join(hits)})"
    head_destinations = [t for t in operands[1:] if is_head_push_destination(t)]
    if head_destinations:
        return CONFIRM, (f"git push publishes to HEAD ({', '.join(head_destinations)}): HEAD is "
                         f"whatever branch is checked out, so the destination cannot be proven "
                         f"not to be the default branch")
    if len(operands) <= 1:
        return CONFIRM, ("git push does not name a branch; it cannot be proven not to push the "
                         "default branch")
    return ALLOW, f"git push targets a non-default branch ({', '.join(operands[1:])})"


def classify_reset(argv: list[str], scopes: list[str]) -> tuple[str, str]:
    """`git reset --hard` by its TARGET: a remote ref denies, a pathspec discards the tree.

    A pathspec form (`git reset --hard -- .`, `git reset --hard src/`) throws away every
    uncommitted change it covers, exactly like `git checkout -- <path>` — the operand is a path,
    not a ref, so it is routed through the same scope logic instead of being called a local-ref
    reset. A plain ref reset (`HEAD~1`, `feature`) stays ALLOW: it is the rollback mechanism.
    """
    if "--hard" not in flags_of(argv):
        return ALLOW, "git reset without --hard does not discard the working tree"
    operands = operands_of(argv, 2)
    if not operands:
        return CONFIRM, ("git reset --hard with no target resets to HEAD and discards the whole "
                         "working tree")
    remote = [t for t in operands if norm(t).startswith(REMOTE_REF_PREFIXES)]
    if remote:
        return HARD_DENY, f"git reset --hard rewinds to a remote ref ({', '.join(remote)})"
    paths = [t for t in operands if is_pathspec_token(t)]
    if paths:
        outside = [t for t in paths if not in_scope(t, scopes)]
        if outside:
            return HARD_DENY, (f"git reset --hard discards changes outside the declared scope "
                               f"({', '.join(outside)})")
        return CONFIRM, (f"git reset --hard discards uncommitted changes at a pathspec "
                         f"({', '.join(paths)})")
    if any("/" in t or "\\" in t for t in operands):
        return CONFIRM, (f"git reset --hard {' '.join(operands)} is ambiguous: an operand with a "
                         f"path separator may be a pathspec that discards uncommitted changes — "
                         f"use `git reset --hard -- <path>` or a plain ref to say so explicitly")
    return ALLOW, "git reset --hard on a local ref"


# Ref flags that take a branch operand (and an optional start point), never a path.
CHECKOUT_BRANCH_FLAGS = ("-b", "-B", "--orphan")
# `--detach` alone takes only a ref, but git still reads the operands AFTER that ref as paths
# (`git checkout --detach HEAD .` restores `.` from HEAD), so it is not a licence to ALLOW.
DETACH_FLAGS = ("--detach",)
# A drive-letter path (`C:\x`, `C:/x`) can only be a pathspec, never a branch name.
DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_pathspec_token(token: str) -> bool:
    """True when a `git checkout` operand can ONLY be a pathspec, never a branch/ref name.

    Branch names never look like these: `.` / `..` (the current/parent directory), a `./` /
    `../` relative form, an absolute or home path, a drive-letter path, a trailing separator
    (a directory spelling), or a glob wildcard. git itself rejects most of them as ref names,
    so without a `--` separator such an operand is unambiguously a path the command discards.
    """
    raw = token.strip().strip('"').strip("'")
    t = norm(raw)
    return (t in (".", "..") or t.startswith("../")
            or raw.startswith(("./", ".\\", "/", "~")) or raw.endswith(("/", "\\"))
            or bool(DRIVE_PATH_RE.match(raw))
            or any(mark in raw for mark in "*?["))


def paths_follow_ref_flag(operands: list[str]) -> bool:
    """True when a `--detach` operand list may still end in paths, not a ref alone.

    With `--detach` git reads the FIRST operand as the ref and EVERY following operand as a
    pathspec, so `git checkout --detach HEAD .` restores `.` (and everything under it) from HEAD
    over the uncommitted changes; a single unmistakable pathspec operand (`.`, `../`, a wildcard)
    is a path too. Only when no such operand follows is the command a pure ref switch.
    """
    return len(operands) >= 2 or any(is_pathspec_token(t) for t in operands)


def classify_checkout(argv: list[str], scopes: list[str]) -> tuple[str, str]:
    sub = argv[1].lower()
    rest = argv[2:]
    paths: list[str] = []
    if sub == "checkout":
        if "--" in rest:
            paths = rest[rest.index("--") + 1:]
        else:
            operands = operands_of(rest, 0)
            flags = flags_of(rest)
            if any(f in CHECKOUT_BRANCH_FLAGS for f in flags):
                return ALLOW, ("git checkout -b/-B/--orphan creates or switches a branch; it "
                               "does not discard file changes")
            if any(f in DETACH_FLAGS for f in flags) and not paths_follow_ref_flag(operands):
                return ALLOW, ("git checkout --detach switches to a detached head without a "
                               "pathspec; it does not discard file changes")
            if not operands:
                return ALLOW, "bare git checkout without a pathspec does not discard file changes"
            if len(operands) >= 2:
                # `git checkout <tree-ish> <path>...`: with two operands git reads the FIRST as a
                # tree-ish and EVERYTHING after it as paths, so the command restores files from
                # that tree over the uncommitted ones.
                paths = operands[1:]
            elif any(is_pathspec_token(t) for t in operands):
                # One unambiguous pathspec makes git read EVERY operand as a path: the command
                # discards file changes, so the operands take the same scope route as after `--`.
                paths = operands
            elif any("/" in t or "\\" in t for t in operands):
                return CONFIRM, (f"git checkout {' '.join(operands)} without `--` is ambiguous: "
                                 f"an operand with a path separator may be a pathspec that "
                                 f"discards uncommitted changes — use `git checkout -- <path>` "
                                 f"to say so explicitly")
            else:
                return ALLOW, (f"git checkout {' '.join(operands)} switches the branch/ref; "
                               f"it does not discard file changes")
    else:  # git restore
        paths = operands_of(rest, 0)
    if not paths:
        return CONFIRM, "git checkout/restore of the whole working tree discards changes"
    outside = [p for p in paths if not in_scope(p, scopes)]
    if outside:
        return HARD_DENY, f"discards changes outside the declared scope ({', '.join(outside)})"
    return CONFIRM, f"discards uncommitted changes inside scope ({', '.join(paths)})"


def classify_clean(argv: list[str], scopes: list[str]) -> tuple[str, str]:
    if {"-n", "--dry-run"} & set(flags_of(argv)):
        return ALLOW, "git clean -n/--dry-run only lists what would be removed"
    paths = operands_of(argv, 2)
    outside = [p for p in paths if not in_scope(p, scopes)]
    if outside:
        return HARD_DENY, f"git clean removes untracked files outside scope ({', '.join(outside)})"
    return CONFIRM, "git clean removes untracked files"


def stash_subcommand(argv: list[str]) -> str:
    """The subcommand git itself would see: the first OPERAND after `git stash`, or "" for none.

    Option VALUES are consumed like git consumes them, so a value can never masquerade as a
    subcommand: after `-m` / `--message` the next token is skipped (`git stash -m list` is a push
    with the message "list", NOT the reading form), while a joined `--message=<v>` carries its
    value in the flag token itself. `--` ends the options, so nothing after it is a subcommand
    (a bare `git stash -- x` is the default `push` with a pathspec → CONFIRM, the fail-safe).
    """
    tokens = argv[2:]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            break
        if token in STASH_VALUE_FLAGS:
            i += 2                                  # this token's value is never a subcommand
            continue
        if token.startswith("-") and token != "-":
            i += 1
            continue
        return token
    return ""


def classify_stash(argv: list[str]) -> tuple[str, str] | None:
    """Classify `git stash` by its SUBCOMMAND (flags change nothing: `git stash show -p` reads,
    `git stash push -m x` writes). The subcommand is read with git's own option parsing
    (`stash_subcommand`), so a value flag cannot smuggle a mutating push into the reading forms
    and a leading flag without a subcommand stays the bare `push` → CONFIRM.
    `None` = unknown subcommand, so the caller keeps its fail-safe.
    """
    sub = stash_subcommand(argv)
    if sub in STASH_READ_ONLY:
        return ALLOW, f"git stash {sub} {GIT_READ_ONLY_REASON}"
    if sub in STASH_MUTATING or not sub:                     # bare `git stash` = default `push`
        return CONFIRM, f"git stash {sub or 'push'} {STASH_MUTATING_REASON}"
    return None


def classify_delete(argv: list[str], scopes: list[str]) -> tuple[str, str]:
    targets = [t for t in argv[1:]
               if not (t.startswith("-") and t != "-") and not DELETE_FLAG_RE.match(t)]
    if not targets:
        return CONFIRM, "deletion command without a parsable target"
    roots = [t for t in targets if is_root_target(t)]
    if roots:
        return HARD_DENY, f"deletion of a filesystem root ({', '.join(roots)})"
    outside = [t for t in targets if not in_scope(t, scopes)]
    if outside:
        reason = f"deletion outside the declared scope ({', '.join(outside)})"
        if not scopes:
            reason += "; no --scope was given, so nothing can be proven to be in scope"
        return HARD_DENY, reason
    return CONFIRM, f"deletion inside the declared scope ({', '.join(targets)})"


def powershell_flag(token: str) -> str:
    """The parameter a PowerShell flag token spells (`-NoProfile` -> `noprofile`, else "")."""
    return token.lstrip("-/").lower() if token[:1] in ("-", "/") else ""


def is_unreadable_powershell_flag(token: str) -> bool:
    """True for a PowerShell flag whose value is a script file / encoded block, not command text."""
    flag = powershell_flag(token)
    return bool(flag) and any(word.startswith(flag) for word in POWERSHELL_UNREADABLE)


def powershell_quote_complete(payload: str) -> bool:
    """True when the DECODED payload's own quoting closes, read with PowerShell's rules.

    The payload `powershell_payload` returns is command TEXT that the recursive classifier re-reads,
    and decoding a doubled quote (`''` -> `'`) can leave a quote in it without a partner:
    `pwsh -Command 'echo ''; rm -rf /'` decodes to `echo '; rm -rf /`. The splitter then treats the
    rest of the line as quoted text, so a destructive tail would be swallowed and the wrapper
    answered ALLOW. PowerShell quotes with `"` and `'` alike and escapes a quote by DOUBLING it, so a
    payload whose quoting never closes carries no command string that can be proven harmless — the
    caller must CONFIRM it (the fail-safe), never call it safe.
    """
    quote = ""
    i = 0
    while i < len(payload):
        ch = payload[i]
        if quote:
            if ch == quote:
                if i + 1 < len(payload) and payload[i + 1] == quote:
                    i += 2                              # a doubled quote is one escaped quote
                    continue
                quote = ""
        elif ch in "\"'":
            quote = ch
        i += 1
    return not quote


def powershell_payload(argv: list[str]) -> str | None:
    """The command string a PowerShell wrapper runs, or None when it cannot be read.

    Only `-Command` and its trusted abbreviations are read as the payload. `-File` and
    `-EncodedCommand` carry a script file / an encoded blob with no command TEXT to classify, and
    the ambiguous `-co` (also -ConfigurationName/-ConfigurationFile) is refused instead of guessed:
    both leave the wrapper unanalyzable, so the caller CONFIRMs it — never ALLOW. Any other flag,
    including the ones the gate does not know, is skipped; if no command string is found afterwards
    the wrapper is unanalyzable too (the fail-safe), so an unknown flag cannot expose a payload that
    is silently dropped.

    The decoded text must also be completely quoted on its OWN terms
    (`powershell_quote_complete`): a doubled quote that lost its partner leaves an unmatched quote,
    the recursive splitter would read the rest of the line as quoted text, and a destructive tail
    behind it would be invisible — so an unterminated payload is unreadable (None -> CONFIRM) too.
    """
    for i, token in enumerate(argv[1:], start=1):
        flag = powershell_flag(token)
        if not flag:
            continue
        if is_unreadable_powershell_flag(token):
            return None
        if flag in POWERSHELL_COMMAND_FLAGS:
            rest = argv[i + 1:]
            if any(is_unreadable_powershell_flag(t) for t in rest):
                return None
            payload = " ".join(rest)
            return payload if powershell_quote_complete(payload) else None
    return None


def wrapper_payload(name: str, raw: str) -> str | None:
    """The command string the shell wrapper `name` will run, or None when it cannot be read.

    `raw` is the simple-command TEXT (quotes and escape pairs verbatim, see `split_commands`), so the
    arguments are rebuilt with the wrapper's OWN tokenizer: adjacent quoted and unquoted runs
    concatenate into ONE argument, exactly as a real shell reads them. That is what keeps
    `sh -c "echo "hi" && rm -rf X"` visible — its `-c` argument is `echo hi && rm -rf X`, not the
    `echo ` that a first-quote-to-first-quote cut would stop at.

    `None` means unreadable, and the caller CONFIRMs it: a script file, an encoded block, an unknown
    flag, no command flag at all, an empty payload, or a line left INSIDE a quote (`sh -c "rm -rf /`,
    `pwsh -Command 'rm -rf /`) whose argument a shell has not finished reading — none of those may
    ever become ALLOW.

    cmd.exe is read with `windows_argv` (a `'` is literal there), PowerShell with `powershell_argv`
    (its single quotes are real quoting, so the inner text of `-Command '...'` is the payload — the
    outer shell may have stripped those quotes before pwsh saw them).
    """
    if name == "cmd":
        argv, complete = windows_argv(raw)
        if not complete:
            return None
        for i, token in enumerate(argv[1:], start=1):
            if token.lower() in CMD_COMMAND_FLAGS:
                return " ".join(argv[i + 1:])
        return None
    if name in ("powershell", "pwsh"):
        argv, complete = powershell_argv(raw)
        if not complete:
            return None
        return powershell_payload(argv)
    argv, complete = posix_argv(raw)
    if not complete:
        return None
    for i, token in enumerate(argv[1:], start=1):            # POSIX shells: -c, -ec, -lc, ...
        if POSIX_COMMAND_FLAG_RE.fullmatch(token):
            return " ".join(argv[i + 1:])
    return None


def classify_wrapper(name: str, raw: str, scopes: list[str], depth: int) -> tuple[str, str]:
    """Classify WHAT a shell wrapper runs: its payload, recursively, like a bare command line.

    The payload is read in the wrapper's OWN dialect: a `powershell`/`pwsh` payload is PowerShell text,
    where a backslash is literal and cannot keep a string open across a `;` — so
    `pwsh -Command 'echo "\\"; rm -rf /'` really runs `rm -rf /` (HARD_DENY) instead of reading as a
    harmless `echo`. Every other wrapper keeps the POSIX / cmd.exe rules its payload is read with.
    """
    payload = wrapper_payload(name, raw)
    if payload is None or not payload.strip():
        return CONFIRM, (f"the payload of `{name}` cannot be read as one finished command string "
                         f"(a script file, an encoded block, an unknown flag, no payload at all or "
                         f"a line left inside a quote): what it runs cannot be proven harmless")
    if depth >= MAX_WRAPPER_DEPTH:
        return CONFIRM, (f"`{name}` nests shell wrappers deeper than {MAX_WRAPPER_DEPTH} "
                         f"levels: the innermost payload cannot be proven harmless")
    dialect = POWERSHELL_DIALECT if name in POWERSHELL_WRAPPERS else POSIX_DIALECT
    cls, reason = classify(payload, scopes, depth + 1, dialect)
    if cls == ALLOW:
        return ALLOW, f"`{name}` runs a payload that is not destructive ({reason})"
    return cls, f"`{name}` runs a destructive payload: {reason}"


def strip_launcher(name: str, spans: list[tuple[str, str]]) -> tuple[list[str], str]:
    """The command a launcher runs: `(inner RAW spans, problem)`.

    `env` and `sudo` accept their own options first — with a separate value (`sudo -u root`), a joined
    value (`--user=root`, `-uroot`) — and the `NAME=VALUE` assignments both of them document in front of
    the command, in addition to a `--` terminator; `builtin` takes the command straight away, accepting
    only the same `--` terminator in front of it. Nothing
    here is executed or expanded: the launcher's own words are dropped so that the command it runs can
    be classified like a bare one.

    `spans` are the INDEX-ALIGNED `(raw span, decoded value)` pairs of `token_spans`: every control
    decision below reads the DECODED value, because that is what the shell hands the launcher
    (`env "-i"` is the option `-i`, `env "--"` is the terminator, `env "FOO=a b"` is an assignment),
    while the inner command is rebuilt from the RAW spans at the same indices, so its quoting and its
    argument boundaries survive the recursion. Reading raw spans here instead recognised none of the
    quoted control words and blind-ALLOWed the destructive tail behind them.

    A non-empty `problem` means the invocation could not be read (an unknown or unsupported option such
    as `env -S`, whose value is a split string; a valued option without its value; `sudo -i`/`-s`,
    which open a shell; `builtin` with no command or with a `--` terminator and no command behind it;
    an unsupported `builtin` option such as `-v`; an EMPTY command name; a first word that looks like
    an assignment but is not `NAME=VALUE`) — the caller CONFIRMs it, because a gate that cannot see the
    command it would run must never call the action harmless. An empty inner list with no problem means
    the launcher runs nothing at all (`env` alone prints the environment).
    """
    if name == "builtin":
        if len(spans) < 2:
            return [], "`builtin` names no command to run"
        start = 1
        if spans[start][1] == "--":
            start += 1                                      # the `--` option terminator, like env/sudo
            if start >= len(spans):
                return [], "`builtin --` names no command to run"
        command = spans[start][1]
        if not command.strip():
            return [], "`builtin` names an empty command"
        if command.startswith("-") and command != "-":
            return [], f"the option {command} of `builtin` is not one the gate can read"
        if "=" in command:
            return [], f"`builtin` names {command}, which cannot be read as a command"
        return [raw for raw, _ in spans[start:]], ""
    flags, value_flags = LAUNCHER_FLAGS[name], LAUNCHER_VALUE_FLAGS[name]
    assigns = name in LAUNCHER_ASSIGNMENTS
    opens_shell = False
    i = 1
    while i < len(spans):
        token = spans[i][1]                                 # DECIDED on the decoded value
        if token == "--":
            i += 1
            break
        if assigns and ENV_ASSIGNMENT_RE.match(token):
            i += 1
            continue
        if not token.startswith("-") or token == "-":
            if assigns and "=" in token:
                return [], f"the assignment {token} of `{name}` cannot be read"
            break
        flag, joined = token.partition("=")[0], "=" in token
        if not joined and len(token) > 2 and token[:2] in value_flags:
            flag, joined = token[:2], True                  # joined short value: `-uFOO`, `-C/tmp`
        if flag in value_flags:
            if joined:
                i += 1
            elif i + 1 >= len(spans):
                return [], f"the option {token} of `{name}` is missing its value"
            else:
                i += 2
            continue
        if flag in flags:
            if name == "sudo" and flag in ("-i", "--login", "-s", "--shell"):
                opens_shell = True                          # env's -i means: ignore the environment
            i += 1
            continue
        return [], f"the option {token} of `{name}` is not one the gate can read"
    while assigns and i < len(spans) and ENV_ASSIGNMENT_RE.match(spans[i][1]):
        i += 1                                              # assignments after `--`
    inner = [raw for raw, _ in spans[i:]]                   # REBUILT from the aligned raw spans
    if inner:
        if not spans[i][1].strip():
            return [], f"`{name}` runs a command whose name is empty"
        return inner, ""
    if opens_shell:
        return [], f"`{name}` would open a shell whose commands cannot be read"
    if name == "env":
        return [], ""                                       # `env` alone only prints the environment
    return [], f"`{name}` names no command to run"


def classify_launcher(name: str, raw: str, scopes: list[str], depth: int,
                      dialect: str) -> tuple[str, str]:
    """Classify WHAT a launcher prefix runs: its inner command, recursively, like a bare command line.

    The launcher is transparent, so `env rm -rf /`, `sudo -u root rm -rf /` and `builtin rm -rf /` are
    the deletion they really are, and launchers nest with each other and with the shell wrappers in
    either order (`sudo sh -c "rm -rf /"`, `env sudo git push origin main`). `dialect` is passed down
    unchanged: a launcher does not change how its payload is quoted.

    The launcher's own words are read as DECODED values, while the inner command is rebuilt from the RAW
    spans aligned with them (`token_spans`): `env "-i"` and `env "--"` ARE its option and terminator (read
    raw, they became the command name and blind-ALLOWed the tail), and `sudo sh -c "echo '; rm -rf /'"`
    keeps the single-quoted wrapper text that no shell runs.
    """
    inner, problem = strip_launcher(name, token_spans(raw, dialect))
    if problem:
        return CONFIRM, (f"the `{name}` launcher cannot be read ({problem}): the command it would run "
                         f"cannot be proven harmless")
    if not inner:
        return ALLOW, f"`{name}` runs no command"
    if depth >= MAX_WRAPPER_DEPTH:
        return CONFIRM, (f"`{name}` nests launchers and wrappers deeper than {MAX_WRAPPER_DEPTH} "
                         f"levels: the innermost command cannot be proven harmless")
    cls, reason = classify(" ".join(inner), scopes, depth + 1, dialect)
    if cls == ALLOW:
        return ALLOW, f"`{name}` runs a command that is not destructive ({reason})"
    return cls, f"`{name}` runs a destructive command: {reason}"


def classify_command(argv: list[str], scopes: list[str], depth: int = 0,
                     raw: str = "", dialect: str = POSIX_DIALECT) -> tuple[str, str]:
    """Classify one simple command; `raw` is its text, kept for the wrapper payload rebuild.

    `dialect` is the quoting dialect of that text, passed on to a launcher's inner command so a
    PowerShell payload keeps PowerShell rules all the way down.
    """
    if not argv:
        return ALLOW, "empty command"
    name = pathlib.PurePath(argv[0]).name.lower()
    if is_git(argv):
        argv, problem = strip_git_globals(argv)
        if problem:
            return CONFIRM, (f"git invocation cannot be parsed ({problem}): whether it touches the "
                             f"default branch or the working tree cannot be proven")
        sub = argv[1].lower()
        if sub == "push":
            return classify_push(argv)
        if sub == "reset":
            return classify_reset(argv, scopes)
        if sub in ("checkout", "restore"):
            return classify_checkout(argv, scopes)
        if sub == "clean":
            return classify_clean(argv, scopes)
        if sub == "stash":
            # An unknown stash subcommand (`git stash bogus`) stays None -> fail-safe CONFIRM below.
            classified = classify_stash(argv)
            if classified is not None:
                return classified
        if sub == "rm":
            return classify_delete(["rm", *argv[2:]], scopes)
        if sub in GIT_READ_ONLY:
            return ALLOW, f"git {sub} {GIT_READ_ONLY_REASON}"
        return CONFIRM, (f"git {sub} is not a subcommand the gate can prove harmless: confirm it "
                         f"before running")
    if name in DELETE_COMMANDS:
        return classify_delete(argv, scopes)
    wrapper = name[:-4] if name.endswith(".exe") else name
    if wrapper in SHELL_WRAPPERS:
        return classify_wrapper(wrapper, raw, scopes, depth)
    if wrapper in LAUNCHER_PREFIXES:
        return classify_launcher(wrapper, raw, scopes, depth, dialect)
    return ALLOW, f"{name} is not a destructive command"


def classify(action: str, scopes: list[str], depth: int = 0,
             dialect: str = POSIX_DIALECT) -> tuple[str, str]:
    """Worst class over all simple commands of `action` (HARD_DENY > CONFIRM > ALLOW).

    `depth` counts the shell wrappers already unwrapped on the way down; a payload is classified
    with the same rules, so `sh -c "git push origin main"` is a wrapped push and not a command
    named `sh`. Each simple command keeps its RAW text next to its argv, so a wrapper can rebuild
    its own argument list (concatenated quoted/unquoted runs) instead of guessing it from tokens.

    `dialect` is the quoting dialect of THIS text and only of this text: a decoded PowerShell payload
    is PowerShell's own (backslash literal, see `split_commands_powershell`), everything the gate reads
    elsewhere stays POSIX. A nested wrapper decides its own dialect again from its name, so the
    PowerShell rules never leak into a POSIX or cmd.exe payload.

    A segment is more than the command it names: a readable `$(...)` substitution inside it is a
    command the SHELL runs, so its body is classified here too, at every nesting level
    (`substitution_bodies` decides which substitutions this dialect really executes). Nesting is
    BOUNDED by `MAX_WRAPPER_DEPTH` and an empty body CONFIRMs, so neither a pathologically nested line
    nor a body with no command in it can be read as harmless (or crash the gate).
    """
    worst, reasons = ALLOW, []
    order = {ALLOW: 0, CONFIRM: 1, HARD_DENY: 2}

    def merge(cls: str, reason: str) -> None:
        """Fold one finding into the worst-so-far, keeping the reasons of the worst class only."""
        nonlocal worst, reasons
        if order[cls] > order[worst]:
            reasons = []
        if order[cls] >= order[worst]:
            worst = cls
            reasons.append(reason)

    for segment in split_commands(action, dialect):
        merge(*classify_command(tokens(segment), scopes, depth, segment, dialect))
        bodies, complete = substitution_bodies(segment, dialect)
        for body in bodies:                          # readable bodies are classified either way
            if not body.strip():
                merge(CONFIRM, ("a `$(...)` command substitution is empty: it carries no command that "
                                "could be proven harmless"))
                continue
            if depth >= MAX_WRAPPER_DEPTH:
                merge(CONFIRM, (f"a `$(...)` command substitution nests deeper than "
                                f"{MAX_WRAPPER_DEPTH} levels: the innermost command cannot be proven "
                                f"harmless"))
                continue
            body_cls, body_reason = classify(body, scopes, depth + 1, dialect)
            if body_cls != ALLOW:                    # a harmless body cannot change the verdict
                merge(body_cls, f"a `$(...)` command substitution: {body_reason}")
        if not complete:
            merge(CONFIRM, ("a `$(...)` command substitution never closes: the command it would run "
                            "cannot be proven harmless"))
    if not reasons:
        return ALLOW, "no destructive command found"
    return worst, "; ".join(reasons)


def append_journal(path: pathlib.Path, line: list[str]) -> None:
    """Append one decision row (header written once, file only ever grows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        if new:
            fh.write(JOURNAL_TITLE + "\n\n" + "\n".join(JOURNAL_HEADER) + "\n")
        fh.write("| " + " | ".join(line) + " |\n")


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`→`), which that codec cannot encode: `print_help()` would raise
    UnicodeEncodeError and the user would get a traceback instead of the help, and the
    classification of a real action could be lost the same way. `errors="replace"` keeps a stream
    that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="classify one shell action")
    p_check.add_argument("--action", required=True, help="the full shell command line to classify")
    p_check.add_argument("--mode", choices=("hitl", "auto"), default="hitl",
                         help="hitl requires user confirmation, auto records an assumption")
    p_check.add_argument("--scope", action="append", default=[],
                         help="path the task is allowed to modify (repeatable)")
    p_check.add_argument("--journal", default=DEFAULT_JOURNAL,
                         help=f"decision journal (default: {DEFAULT_JOURNAL})")
    args = ap.parse_args()

    action = args.action.strip()
    scopes = [s for s in args.scope if s and s.strip()]
    cls, reason = classify(action, scopes)
    decision = DECISION[(cls, args.mode)]
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    journal = pathlib.Path(args.journal)

    print(f"class: {cls}")
    print(f"decision: {decision}")
    print(f"mode: {args.mode}")
    print(f"scope: {', '.join(scopes) if scopes else '(none)'}")
    print(f"action: {action}")
    print(f"reason: {reason}")
    print(f"journal: {journal}")
    if decision == "CONFIRM_REQUIRED":
        print("confirm: user confirmation required before running this action")
    elif decision == "ALLOW_WITH_ASSUMPTION":
        print(f"assumption: mode=auto - destructive action inside scope was allowed without "
              f"confirmation ({reason})")
    elif decision == "HARD_DENY":
        print(f"blocked: {reason}")
        if not scopes and "scope" in reason:
            print("hint: pass --scope <path> once the task scope is known")

    # The decision is already on stdout, so an unwritable journal is an infrastructure error
    # (exit 3), never a lost verdict and never a traceback.
    try:
        append_journal(journal, [stamp, args.mode, cls, decision, ",".join(scopes) or "-",
                                 f"`{cell(action)}`", cell(reason)])
    except OSError as exc:
        print(f"error: cannot write the action-gate journal {journal}: {exc}", file=sys.stderr)
        return 3
    return EXIT_CODE[decision]


if __name__ == "__main__":
    sys.exit(main())

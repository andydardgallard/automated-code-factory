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

KNOWN LIMITATION (open, carried in the backlog): a `powershell`/`pwsh` `-Command` payload in
SINGLE quotes is still FAIL-OPEN — the Windows tokenizer reads `'` as a literal character, so
`pwsh -Command 'rm -rf /'` is classified ALLOW while the same payload in double quotes is
HARD_DENY. Never treat the wrapper rule as proof of safety for a single-quoted PowerShell payload.
The gate also does not expand launcher prefixes (`env rm -rf /`, `sudo rm -rf /`) or command
substitutions (`sh -c "$(rm -rf /)"`): it classifies what the line literally runs, so a
substitution or a launcher prefix hides the payload from it.

HARD_DENY rules:
  * `git push` (also `--force` / `-f` / `--mirror` / `--all`) that targets the default branch
    (`main` / `master`, in any refspec form: `main`, `refs/heads/main`, `origin/main`, `HEAD:main`),
  * `git push --all` / `--mirror` (they publish every local branch, default branch included),
  * `git reset --hard` against a remote-tracking ref (`origin/...`, `upstream/...`, `@{u}`,
    `refs/remotes/...`),
  * deletion (`rm`, `rmdir`, `rd`, `del`, `erase`, `Remove-Item`, `git rm`) of a target that is NOT
    covered by the declared `--scope`: filesystem root / `/*` / `~` / a drive root, absolute paths
    outside scope, `..` escapes, and — deliberately — any delete when no `--scope` was given
    (without a declared scope nothing can be proven to be inside the task's scope),
  * a shell wrapper whose readable payload is one of the above — a wrapper is transparent, so
    `sh -c "rm -rf /"` is the same root deletion as `rm -rf /`.

CONFIRM rules (destructive but inside the declared scope, and anything the gate cannot read):
  * deletion of a path covered by `--scope`,
  * `git checkout -- <path>` / `git restore` of paths inside scope,
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


def split_commands(action: str) -> list[str]:
    """Simple-command TEXTS of `action`, split only at separators OUTSIDE quotes.

    Quoting matters because a wrapper keeps its payload in ONE argument: cutting
    `sh -c "rm -rf / && echo x"` at the quoted `&&` would leave the gate with the mangled `sh -c
    "rm -rf` and lose the deletion. Inside a quoted run a separator is data, and which backslash
    sequences are escapes is decided PER QUOTE TYPE (`QUOTE_ESCAPES`) exactly as a real shell
    reads them — a single-quoted string has none, so `echo 'a\\' && rm -rf /` really is `echo a\\`
    followed by the deletion, while in double quotes `\\\\` and `\\"` are escapes.

    The returned text is the LINE VERBATIM (quotes and backslashes included): the splitter only
    decides where one simple command ends, and `posix_argv` re-reads the text afterwards — the
    tokenizer here must not resolve quoting on its own or argument boundaries would be lost.
    """
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
    """`(argv cmd.exe or PowerShell builds from line, was the line completely read)`.

    Neither has a POSIX backslash escape: a `"` merely TOGGLES quoting, so
    `powershell -Command "Remove-Item -Recurse -Force C:\\"` really closes the argument on that
    quote and keeps the backslash — a POSIX reading would swallow the closing quote and lose the
    whole payload. Quotes are removed from the value and adjacent runs concatenate; an unbalanced
    `"` makes the line unreadable (`complete` is False), so the caller CONFIRMs instead of guessing.
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


def simple_commands(action: str) -> list[list[str]]:
    """The argv-only view of `split_commands` (quote-naive `tokens`; classification uses the raw
    text instead, so it can rebuild wrapper arguments exactly)."""
    return [tokens(part) for part in split_commands(action)]


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
    if len(operands) <= 1:
        return CONFIRM, ("git push does not name a branch; it cannot be proven not to push the "
                         "default branch")
    return ALLOW, f"git push targets a non-default branch ({', '.join(operands[1:])})"


def classify_reset(argv: list[str]) -> tuple[str, str]:
    if "--hard" not in flags_of(argv):
        return ALLOW, "git reset without --hard does not discard the working tree"
    remote = [t for t in operands_of(argv, 2) if norm(t).startswith(REMOTE_REF_PREFIXES)]
    if remote:
        return HARD_DENY, f"git reset --hard rewinds to a remote ref ({', '.join(remote)})"
    return ALLOW, "git reset --hard on a local ref"


def classify_checkout(argv: list[str], scopes: list[str]) -> tuple[str, str]:
    sub = argv[1].lower()
    rest = argv[2:]
    paths: list[str] = []
    if sub == "checkout":
        if "--" not in rest:
            return ALLOW, "git checkout without a pathspec does not discard file changes"
        paths = rest[rest.index("--") + 1:]
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


def powershell_payload(argv: list[str]) -> str | None:
    """The command string a PowerShell wrapper runs, or None when it cannot be read.

    Only `-Command` and its trusted abbreviations are read as the payload. `-File` and
    `-EncodedCommand` carry a script file / an encoded blob with no command TEXT to classify, and
    the ambiguous `-co` (also -ConfigurationName/-ConfigurationFile) is refused instead of guessed:
    both leave the wrapper unanalyzable, so the caller CONFIRMs it — never ALLOW. Any other flag,
    including the ones the gate does not know, is skipped; if no command string is found afterwards
    the wrapper is unanalyzable too (the fail-safe), so an unknown flag cannot expose a payload that
    is silently dropped.
    """
    for i, token in enumerate(argv[1:], start=1):
        flag = powershell_flag(token)
        if not flag:
            continue
        if is_unreadable_powershell_flag(token):
            return None
        if flag in POWERSHELL_COMMAND_FLAGS:
            rest = argv[i + 1:]
            return None if any(is_unreadable_powershell_flag(t) for t in rest) else " ".join(rest)
    return None


def wrapper_payload(name: str, raw: str) -> str | None:
    """The command string the shell wrapper `name` will run, or None when it cannot be read.

    `raw` is the simple-command TEXT (quotes and escape pairs verbatim, see `split_commands`), so the
    arguments are rebuilt with the wrapper's OWN tokenizer: adjacent quoted and unquoted runs
    concatenate into ONE argument, exactly as a real shell reads them. That is what keeps
    `sh -c "echo "hi" && rm -rf X"` visible — its `-c` argument is `echo hi && rm -rf X`, not the
    `echo ` that a first-quote-to-first-quote cut would stop at.

    `None` means unreadable, and the caller CONFIRMs it: a script file, an encoded block, an unknown
    flag, no command flag at all, an empty payload, or a line left INSIDE a quote (`sh -c "rm -rf /`)
    whose argument a shell has not finished reading — none of those may ever become ALLOW.
    """
    if name in ("cmd", "powershell", "pwsh"):
        argv, complete = windows_argv(raw)
        if not complete:
            return None
        if name == "cmd":
            for i, token in enumerate(argv[1:], start=1):
                if token.lower() in CMD_COMMAND_FLAGS:
                    return " ".join(argv[i + 1:])
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
    """Classify WHAT a shell wrapper runs: its payload, recursively, like a bare command line."""
    payload = wrapper_payload(name, raw)
    if payload is None or not payload.strip():
        return CONFIRM, (f"the payload of `{name}` cannot be read as one finished command string "
                         f"(a script file, an encoded block, an unknown flag, no payload at all or "
                         f"a line left inside a quote): what it runs cannot be proven harmless")
    if depth >= MAX_WRAPPER_DEPTH:
        return CONFIRM, (f"`{name}` nests shell wrappers deeper than {MAX_WRAPPER_DEPTH} "
                         f"levels: the innermost payload cannot be proven harmless")
    cls, reason = classify(payload, scopes, depth + 1)
    if cls == ALLOW:
        return ALLOW, f"`{name}` runs a payload that is not destructive ({reason})"
    return cls, f"`{name}` runs a destructive payload: {reason}"


def classify_command(argv: list[str], scopes: list[str], depth: int = 0,
                     raw: str = "") -> tuple[str, str]:
    """Classify one simple command; `raw` is its text, kept for the wrapper payload rebuild."""
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
            return classify_reset(argv)
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
    return ALLOW, f"{name} is not a destructive command"


def classify(action: str, scopes: list[str], depth: int = 0) -> tuple[str, str]:
    """Worst class over all simple commands of `action` (HARD_DENY > CONFIRM > ALLOW).

    `depth` counts the shell wrappers already unwrapped on the way down; a payload is classified
    with the same rules, so `sh -c "git push origin main"` is a wrapped push and not a command
    named `sh`. Each simple command keeps its RAW text next to its argv, so a wrapper can rebuild
    its own argument list (concatenated quoted/unquoted runs) instead of guessing it from tokens.
    """
    worst, reasons = ALLOW, []
    order = {ALLOW: 0, CONFIRM: 1, HARD_DENY: 2}
    for segment in split_commands(action):
        cls, reason = classify_command(tokens(segment), scopes, depth, segment)
        if order[cls] >= order[worst]:
            if order[cls] > order[worst]:
                reasons = []
            worst = cls
            reasons.append(reason)
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

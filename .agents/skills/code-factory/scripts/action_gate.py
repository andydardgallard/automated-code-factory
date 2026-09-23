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

HARD_DENY rules:
  * `git push` (also `--force` / `-f` / `--mirror` / `--all`) that targets the default branch
    (`main` / `master`, in any refspec form: `main`, `refs/heads/main`, `origin/main`, `HEAD:main`),
  * `git push --all` / `--mirror` (they publish every local branch, default branch included),
  * `git reset --hard` against a remote-tracking ref (`origin/...`, `upstream/...`, `@{u}`,
    `refs/remotes/...`),
  * deletion (`rm`, `rmdir`, `rd`, `del`, `erase`, `Remove-Item`, `git rm`) of a target that is NOT
    covered by the declared `--scope`: filesystem root / `/*` / `~` / a drive root, absolute paths
    outside scope, `..` escapes, and — deliberately — any delete when no `--scope` was given
    (without a declared scope nothing can be proven to be inside the task's scope).

CONFIRM rules (destructive but inside the declared scope, and anything the gate cannot read):
  * deletion of a path covered by `--scope`,
  * `git checkout -- <path>` / `git restore` of paths inside scope,
  * `git clean` (repo-wide by nature). `git clean -n` / `--dry-run` is a no-op → ALLOW,
  * an unparsable git invocation — unknown global option, a valued global option without its value,
    no subcommand at all — and any git subcommand the gate does not know: fail-safe, because what
    the gate cannot read it never calls safe (`git frobnicate` / `git branch -D main` → CONFIRM).

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
# behind `&&` / `;` / `|` is still found when the whole line is passed as one `--action`.
COMMAND_SPLIT_RE = re.compile(r"&&|\|\||[&;|\n]")
# Shell-ish tokenizer that keeps quotes and backslashes (Windows paths) intact.
TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')

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


def tokens(command: str) -> list[str]:
    """Split a single simple command into argv-like tokens (quotes preserved as delimiters)."""
    return [m.group(1) if m.group(1) is not None else
            m.group(2) if m.group(2) is not None else m.group(3)
            for m in TOKEN_RE.finditer(command)]


def simple_commands(action: str) -> list[list[str]]:
    return [tokens(part) for part in COMMAND_SPLIT_RE.split(action) if part.strip()]


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


def classify_command(argv: list[str], scopes: list[str]) -> tuple[str, str]:
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
        if sub == "rm":
            return classify_delete(["rm", *argv[2:]], scopes)
        if sub in GIT_READ_ONLY:
            return ALLOW, f"git {sub} {GIT_READ_ONLY_REASON}"
        return CONFIRM, (f"git {sub} is not a subcommand the gate can prove harmless: confirm it "
                         f"before running")
    if name in DELETE_COMMANDS:
        return classify_delete(argv, scopes)
    return ALLOW, f"{name} is not a destructive command"


def classify(action: str, scopes: list[str]) -> tuple[str, str]:
    """Worst class over all simple commands of `action` (HARD_DENY > CONFIRM > ALLOW)."""
    worst, reasons = ALLOW, []
    order = {ALLOW: 0, CONFIRM: 1, HARD_DENY: 2}
    for argv in simple_commands(action):
        cls, reason = classify_command(argv, scopes)
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

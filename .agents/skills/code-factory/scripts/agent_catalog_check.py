#!/usr/bin/env python3
"""
Deterministic on-disk probe of the factory's sub-agent catalog (zero LLM tokens, stdlib only).

WHY THIS EXISTS

The CLI has intermittently reported "Unknown agent type" for a factory role although its profile
was on disk: the CLI's own profile registry reloaded and lost the entry. That failure is
indistinguishable, from the caller's side, from a profile that is really MISSING or broken — and
the two need opposite reactions (a retry of the SAME role and model versus a factory defect that
must stop the run). No deterministic probe existed, so every occurrence was guesswork, and a
"helpful" role/model substitution was the tempting, unsafe answer.

This probe answers exactly one question, from the repository alone: is the catalog COMPLETE and
VALID on disk? It reads what the CLI reads — `.agents/agents/sub-agents/<file>.md` — and checks,
for every factory role, that the profile exists, has a parseable YAML frontmatter, declares a
`name:` that resolves back to THAT role, that no two profiles claim the same name, and that a
declared `model_preference` is one the CLI knows (`primary`|`secondary`).

The role roster is NOT reimplemented here: `model_matrix.ROLES` + `model_matrix.ROLE_FILES` name
the 15 roles and their profile files, and `model_attribution.role_from_profile` is the one
`factory-<role>` -> role resolver the attribution check already uses. A third copy of the roster
would be a catalog of its own — the very thing this script exists to make trustworthy.

READING THE RESULT (Defect A degradation route)

  every profile present and valid  -> the catalog on disk is FINE, so an "Unknown agent type"
                                      error is CLI-side catalog loss: retry the SAME role with the
                                      SAME model inside the retry budget (rule
                                      `model-unavailable-stop`); never a substitution.
  a profile MISSING or INVALID     -> factory defect: stop and report the actionable line below.

PUBLIC API

  use_utf8_output()                       force UTF-8 on stdout/stderr (house convention)
  profiles_dir(root=None)                 the directory the profiles are read from
  read_frontmatter(path)                  top-level `key: value` of a profile's frontmatter, or None
  parse_frontmatter(path)                 (fields, problem): fields only when the block PARSES
  check_catalog(root=None, roles=None)    {"profiles_dir", "roles": [...], "errors": [...]}

`check_catalog` is the API a test drives; the CLI below is a thin printer over it.

FRONTMATTER SYNTAX (why the parser is a strict subset, not a lenient reader)

The probe must not answer "the profile is fine" about a profile the CLI cannot parse, and must not
answer "broken" about one it parses perfectly. A line-splitting reader gets both wrong: it accepts
`name: "factory-coder` (strip the stray quote, call it valid) and rejects `model_preference: secondary
  # owner-selected side` (the comment becomes part of the value). So the frontmatter is validated as
the SUBSET the profiles actually use — top-level `key: value` scalars, `- item` sequences under an
empty value, single- or double-quoted scalars, flow collections balanced on one line, and a trailing
`#` comment — and anything outside that subset is reported with its line number instead of being
guessed at. Quoted values and comments are read the way YAML reads them, so a healthy profile is never
refused.

CLI

  python agent_catalog_check.py check [--root <dir>] [--role <role>]

  --root  directory to probe. Default: the factory's own `.agents/agents/sub-agents`. A root that
          carries `agents/sub-agents/` is probed there (a factory or target-project root); a root
          that IS the profiles directory (a hermetic test fixture) is probed directly. A path that
          is not an existing directory is a contract error (exit 2): it has zero legitimacy and
          must not silently check nothing.
  --role  check ONE role only (the degradation route asks about the role that failed). A value
          outside `model_matrix.ROLES` is a contract error (exit 2) listing the valid roles, so a
          typo can never look like a clean result.

Exit codes: 0 = the catalog is complete and valid; 1 = at least one profile MISSING or INVALID
(actionable line printed); 2 = a contract error with a message and no traceback (bad `--root` or
`--role`), or an unreadable profiles directory.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The registry and the role resolver are SIBLINGS; the script may be loaded by path (a test,
    # gate_all.py), so they must be importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from model_attribution import role_from_profile  # noqa: E402
from model_matrix import ROLES, ROLE_FILES, SUBAGENTS_DIR, use_utf8_output  # noqa: E402

# The `model_preference` values the CLI accepts; anything else cannot select a model side.
PREFERENCES = ("primary", "secondary")
# Where a profile root carries its profiles (mirrors the repository layout).
PROFILES_REL = pathlib.Path("agents") / "sub-agents"
# A top-level frontmatter key; an indented line belongs to a nested value and is not read.
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9_\-]+)[ \t]*:(?:[ \t]+(.*))?$")
# An indented `- item` of a sequence value (the only indented form the profiles use).
SEQUENCE_ITEM = re.compile(r"^[ \t]+-[ \t]+(.*)$")
# Opening and closing characters of a flow collection, in matching order.
FLOW_OPENERS, FLOW_CLOSERS = "([{", ")]}"


def profiles_dir(root=None) -> pathlib.Path:
    """The directory the profiles are read from.

    Default: the factory's own sub-agent directory (`model_matrix.SUBAGENTS_DIR`, the one home of
    that path). For an explicit `root`, `<root>/agents/sub-agents` wins when it is a directory —
    that is the layout of a repository — otherwise `root` itself is taken as the profiles
    directory, so a hermetic fixture can copy just the profiles it needs.
    """
    if root is None:
        return SUBAGENTS_DIR
    base = pathlib.Path(root)
    nested = base / PROFILES_REL
    return nested if nested.is_dir() else base


def _closing_quote(value: str, quote: str) -> int:
    """The index of the quote that CLOSES the scalar opened at index 0, or -1.

    A double-quoted scalar escapes with a backslash; a single-quoted one escapes the quote by
    doubling it (`''`) — the way YAML does, so a value carrying an apostrophe is read correctly.
    """
    index = 1
    while index < len(value):
        char = value[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            return index
        index += 1
    return -1


def _strip_comment(value: str) -> str:
    """The value without a trailing `#` comment (`#` starts one when it is not inside a token)."""
    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1] in " \t"):
            return value[:index].strip()
    return value.strip()


def _flow_problem(value: str) -> str | None:
    """Why a flow collection (`[...]`/`{...}`) does not close on its own line, or None."""
    stack: list[str] = []
    quote = ""
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or value[index - 1] in " \t"):
            break
        elif char in FLOW_OPENERS:
            stack.append(char)
        elif char in FLOW_CLOSERS:
            if not stack:
                return f"the value closes a collection with {char!r} that is never opened"
            opener = stack.pop()
            if FLOW_OPENERS.index(opener) != FLOW_CLOSERS.index(char):
                return f"the value closes {opener!r} with {char!r}"
        index += 1
    if quote:
        return f"the value opens with {quote} but never closes it"
    if stack:
        return f"the value opens {stack[-1]!r} and never closes it on the same line"
    return None


def _scalar_problem(value: str) -> str | None:
    """Why `value` is not a scalar/collection this probe reads, or None when it is READABLE.

    The accepted subset is the one the factory's profiles use: a plain scalar, a single- or
    double-quoted scalar, or a flow collection balanced on one line — each optionally followed by a
    `#` comment. Anything else is a syntax question this probe refuses to guess, because a lenient
    reader would report a profile the CLI cannot parse as healthy.
    """
    value = value.strip()
    if not value or value.startswith("#"):
        return None                                   # empty (a block follows) or a comment
    first = value[0]
    if first in "\"'":
        end = _closing_quote(value, first)
        if end < 0:
            return f"the value opens with {first} but never closes it"
        rest = value[end + 1:].strip()
        if rest and not rest.startswith("#"):
            return (f"there is text after the closing {first} that is neither a comment nor part of "
                    f"the value")
        return None
    if first in FLOW_OPENERS:
        return _flow_problem(value)
    plain = _strip_comment(value)
    if not plain:
        return None
    if ": " in plain or plain.endswith(":"):
        return "an unquoted `: ` inside a value starts a nested mapping"
    if plain[0] in FLOW_CLOSERS:
        return f"the value starts with {plain[0]!r}, which closes a collection that is never opened"
    return None


def _scalar_value(value: str) -> str:
    """The value as the CLI reads it: unquoted, with a trailing comment removed (validated first)."""
    value = value.strip()
    if not value or value.startswith("#"):
        return ""
    if value[0] in "\"'":
        end = _closing_quote(value, value[0])
        return value[1:end] if end > 0 else ""
    return _strip_comment(value)


def parse_frontmatter(path: pathlib.Path) -> tuple[dict[str, str] | None, str | None]:
    """(fields, problem) for a profile: fields only when the WHOLE frontmatter block parses.

    `(None, None)` means "no readable frontmatter at all" — the file is missing/unreadable, does not
    open with `---`, or never closes the block (the caller reports that as its own INVALID line).
    `(None, problem)` means the block is there but malformed; `problem` names the line and the
    reason, so the caller can hand the author an actionable line instead of a generic failure.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):                 # absent, a directory, no permission
        return None, None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    fields: dict[str, str] = {}
    previous = ""                                 # the last top-level key, for sequence items
    open_value = False                            # that key's value was empty, so items may follow
    for number, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "---":
            return fields, None
        body = raw.rstrip()
        if not body.strip():
            continue
        if raw.startswith("\t"):
            return None, (f"line {number}: the line is indented with a TAB — YAML forbids tab "
                          f"indentation")
        if raw[:1] in (" ", "\t"):
            if body.lstrip().startswith("#"):
                continue
            item = SEQUENCE_ITEM.match(body)
            if item is None:
                return None, (f"line {number}: an indented line that is not a `- item` sequence "
                              f"item — this probe reads scalars and `- item` lists only")
            if not open_value:
                return None, (f"line {number}: a sequence item follows `{previous}`, whose value is "
                              f"not empty — a list must be the value of its own key")
            problem = _scalar_problem(item.group(1))
            if problem is not None:
                return None, f"line {number}: {problem}"
            continue
        if body.startswith("#"):
            continue
        match = FRONTMATTER_KEY.match(body)
        if match is None:
            return None, (f"line {number}: `{body.strip()[:60]}` is neither a `key: value` line nor "
                          f"a comment")
        key = match.group(1)
        value = match.group(2) or ""
        if key in fields:
            return None, f"line {number}: the key `{key}` is declared twice"
        problem = _scalar_problem(value)
        if problem is not None:
            return None, f"line {number}: `{key}`: {problem}"
        fields[key] = _scalar_value(value)
        previous = key
        open_value = fields[key] == ""            # an empty value: a `- item` list may follow
    return None, None                             # the block was never closed


def read_frontmatter(path: pathlib.Path) -> dict[str, str] | None:
    """Top-level `key: value` scalars of a profile's frontmatter; None when it does not parse.

    None means "no frontmatter this script can read" — missing, unreadable, not opening with `---`,
    never closing the block, or syntactically malformed. Values are read the way YAML reads them:
    surrounding quotes removed, a trailing `#` comment dropped.
    """
    fields, _problem = parse_frontmatter(path)
    return fields


def _profile_entry(role: str, profiles: pathlib.Path, names: dict[str, str]) -> dict:
    """One role's catalog entry: its profile identity plus every problem found with it."""
    file_name = ROLE_FILES.get(role, f"{role}.md")
    path = profiles / file_name
    entry = {"role": role, "file": str(path), "name": "", "model_preference": "", "problems": []}
    if not path.is_file():
        entry["problems"].append(
            f"no sub-agent profile at {path} — the CLI cannot launch this role; restore "
            f"`{file_name}` with the frontmatter of the {role} profile")
        return entry
    fields, syntax = parse_frontmatter(path)
    if syntax is not None:
        entry["problems"].append(
            f"{path} has a malformed YAML frontmatter — {syntax}; the CLI cannot parse this profile, "
            f"so the role answers 'Unknown agent type' at launch; repair the frontmatter (the catalog "
            f"probe reads `key: value` scalars, `- item` lists, quoted values and trailing `#` "
            f"comments)")
        return entry
    if fields is None:
        entry["problems"].append(
            f"{path} has no readable YAML frontmatter (line 1 must be `---` and the block must be "
            f"closed by a second `---`) — the CLI cannot read the profile's identity; restore the "
            f"frontmatter")
        return entry

    name = fields.get("name", "")
    preference = fields.get("model_preference", "").strip().lower()
    entry["name"] = name
    entry["model_preference"] = preference or "primary"
    if not name:
        entry["problems"].append(
            f"{path} declares no `name:` — the CLI addresses a profile by its name, so this role "
            f"is unlaunchable; add `name:` with the profile name the factory delegates to")
    else:
        resolved = role_from_profile(name)
        if resolved != role:
            entry["problems"].append(
                f"{path} declares name `{name}`, which resolves to role "
                f"`{resolved or '<none>'}`, not `{role}` — the factory would delegate {role} to a "
                f"profile that answers as another role; fix the `name:`")
        else:
            names[name] = role
    if preference and preference not in PREFERENCES:
        entry["problems"].append(
            f"{path} declares model_preference `{preference}`, which is not one of "
            f"{'|'.join(PREFERENCES)} — the role then has no side of the default matrix and no "
            f"model to run on; correct the value (an ABSENT field means primary, as the CLI does)")
    return entry


def _stray_identities(profiles: pathlib.Path, names: dict[str, str],
                      checked: set[pathlib.Path]) -> list[str]:
    """Profile files OUTSIDE the checked roster that re-declare a claimed `name:`.

    Inside the roster a name that resolves to its OWN role is unique by construction (resolution
    is a function of the name), so a real ambiguity needs a second file — a stale or copied
    profile left in the directory. The CLI would then see two profiles with one identity, which is
    exactly the kind of catalog confusion that surfaces as "Unknown agent type", so it is reported
    instead of ignored because the file is not on the roster.
    """
    problems: list[str] = []
    try:
        candidates = sorted(profiles.glob("*.md"))
    except OSError:                               # an unreadable profiles directory
        return problems
    for path in candidates:
        if path.resolve() in checked:
            continue
        fields = read_frontmatter(path)
        name = (fields or {}).get("name", "")
        if name in names:
            problems.append(f"{names[name]}: {path} re-declares the identity `{name}` of the "
                            f"{names[name]} profile — two profiles with one name make the CLI's "
                            f"catalog ambiguous; remove or rename the stray profile")
    return problems


def check_catalog(root=None, roles=None) -> dict:
    """The whole catalog verdict: {"profiles_dir", "roles": [entry...], "errors": [line...]}.

    Every role of `roles` (default: all of `model_matrix.ROLES`, the one roster) is checked.
    `errors` is the flat list of actionable lines — empty means the catalog on disk is complete
    and valid, so an "Unknown agent type" error is CLI-side and the SAME role may be retried.
    """
    profiles = profiles_dir(root)
    wanted = list(ROLES) if roles is None else list(roles)
    names: dict[str, str] = {}
    entries = [_profile_entry(role, profiles, names) for role in wanted]
    checked = {(profiles / ROLE_FILES.get(role, f"{role}.md")).resolve() for role in wanted}
    errors = [f"{entry['role']}: {problem}"
              for entry in entries for problem in entry["problems"]]
    errors += _stray_identities(profiles, names, checked)
    return {"profiles_dir": str(profiles), "roles": entries, "errors": errors}


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def cmd_check(args) -> int:
    if args.root is not None and not pathlib.Path(args.root).is_dir():
        print(f"agent_catalog_check.py: --root {args.root!r} is not an existing directory — "
              f"point it at the directory holding `agents/sub-agents/` (or at the profiles "
              f"directory itself)", file=sys.stderr)
        return 2
    if args.role is not None and args.role not in ROLES:
        print(f"agent_catalog_check.py: unknown role {args.role!r} — valid roles: "
              f"{', '.join(ROLES)}", file=sys.stderr)
        return 2

    report = check_catalog(args.root, [args.role] if args.role else None)
    print(f"profiles: {report['profiles_dir']}")
    printed: set[str] = set()
    for entry in report["roles"]:
        status = "INVALID" if entry["problems"] else "OK"
        print(f"{status:<8} {entry['role']}: name={entry['name'] or '-'} "
              f"model_preference={entry['model_preference'] or '-'}")
        for problem in entry["problems"]:
            print(f"         {problem}")
            printed.add(f"{entry['role']}: {problem}")
    for error in report["errors"]:
        if error not in printed:                  # a catalog-level problem, not one role's line
            print(f"INVALID  {error}")
    if report["errors"]:
        print(f"catalog INVALID: {len(report['errors'])} problem(s) in "
              f"{len(report['roles'])} checked profile(s) — a delegation to a broken role would "
              f"fail as 'Unknown agent type'; repair the profile(s) above before the run")
        return 1
    print(f"catalog OK: {len(report['roles'])} profile(s) present and valid — an 'Unknown agent "
          f"type' error is CLI-side catalog loss, so retry the SAME role with the SAME model "
          f"inside the retry budget (never a substitution)")
    return 0


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Probe the on-disk sub-agent catalog")
    check.add_argument("--root", default=None,
                       help="Directory to probe (default: the factory's agents/sub-agents)")
    check.add_argument("--role", default=None,
                       help="Check one role only (must be a role of model_matrix.ROLES)")
    check.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

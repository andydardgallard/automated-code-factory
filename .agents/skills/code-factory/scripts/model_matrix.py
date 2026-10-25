#!/usr/bin/env python3
"""
Deterministic model precedence of a Code Factory run (zero LLM tokens, stdlib only).

The owner's ruling — implemented here literally, so no prose can reshape it:

  (a) the task's `models:` matrix NAMES a role -> that exact model is used. A generator/judge
      family collision is reported as a WARNING and NEVER turned into a substitution: the task
      is authoritative, even when it breaks the factory's own diversity rule.
  (b) the task does NOT name the role -> the model comes from the factory's DEFAULT MATRIX
      (top-level `default_model` / `[secondary_model] default_model` of the CLI config, selected
      by the role's `model_preference` in `.agents/agents/sub-agents/<role>.md`). There the
      generator != judge family rule IS enforced: a same-family pair with either side coming from
      the default matrix is an ERROR naming the fix.
  (c) there is no third path — the main agent never picks a model on its own.

The ONE exception is the plan committee's second planner (`committee_second_planner`): it always
comes from the family CONTRASTING the first planner, whatever the matrix says. That is the only
place `override` is ever involved; `resolve()` never sets it.

Public API (`precedence()` returns the same rulebook as one English paragraph):

  family(alias) -> "kimi"|"deepseek"|"qwen"   vendor family of a model alias; ValueError if unknown
  load_default_matrix(config_path=None)       role -> model from config.toml + sub-agent frontmatter
  resolve(task_matrix, default_matrix, role)  one role: model, source (task|default|none), warnings
  resolve_all(task_matrix, default_matrix)    every role, in ROLES order
  check_families(resolved)                    {"errors": [...], "warnings": [...]} generator vs judge
  committee_second_planner(first_model, ...)  the contrasting planner of the plan committee
  precedence()                                the precedence, one paragraph

CLI:
  python model_matrix.py family --model deepseek-flash
  python model_matrix.py default [--config ~/.kimi-code/config.toml]
  python model_matrix.py resolve --task .code-factory/state/task.yaml [--config <path>] [--json]

`family` prints the vendor family of one alias. `default` prints the default matrix, `resolve`
prints the resolved matrix of a task plus the family check. Exit codes: 0 = success; 1 = `resolve`
found a family ERROR, i.e. the default matrix breaks its own generator != judge rule; 2 = a contract
error with a message and no traceback — an alias `family` cannot place into a known family, or a
task file `resolve` cannot read. A missing config file or missing sub-agent file degrades gracefully
(that role is simply absent from the default matrix) — the factory then has no model to offer and
says so instead of inventing one.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# Every role that can be named by a task's `models:` matrix, in the order the factory reports them.
ROLES = ("analyzer", "planner", "coder", "tester", "gui_expert", "refactorer",
         "reviewer", "diagnostician", "advisor", "documenter", "security_auditor", "skill_manager")
# The two sides of the generator != judge rule (gui_expert implements, so it is generator-side).
GENERATOR_SIDE = ("coder", "tester", "gui_expert")
JUDGE_SIDE = ("reviewer", "diagnostician", "advisor")

# Role -> sub-agent file name, where the file name is not `<role>.md`.
ROLE_FILES = {"reviewer": "code-reviewer.md", "gui_expert": "gui-expert.md",
              "security_auditor": "security-auditor.md", "skill_manager": "skill-manager.md"}
# The factory's own sub-agent definitions carry `model_preference:` in their YAML frontmatter.
# A module-level constant, not an environment variable: nothing may silently re-point it.
SUBAGENTS_DIR = pathlib.Path(__file__).resolve().parents[3] / "agents" / "sub-agents"
DEFAULT_CONFIG = pathlib.Path.home() / ".kimi-code" / "config.toml"
# The pool the committee picks the second planner from, when the caller does not narrow it.
COMMITTEE_POOL = ("kimi-k3", "deepseek-flash", "qwen-max")

# Vendor family -> substrings that identify it in a model alias (case-insensitive).
FAMILY_KEYWORDS = (("kimi", ("kimi", "moonshot")),
                   ("deepseek", ("deepseek",)),
                   ("qwen", ("qwen", "qwq", "dashscope")))
# `k3`, `k3.1`, `k1`, ... — a version token of the Kimi line, as the provider tables spell it.
KIMI_VERSION_TOKEN = re.compile(r"^k\d")


class ModelMatrixError(ValueError):
    """An alias or a matrix the factory cannot place into a model family."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the messages survive a console code page.

    A Windows console defaults to a legacy code page (cp866/cp1251) and messages may carry
    non-ASCII characters: `print_help()` would raise UnicodeEncodeError and the user would get a
    traceback instead of a usage line. `errors="replace"` keeps a stream that cannot be
    reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def family(alias: str) -> str:
    """Vendor family of a model alias: "kimi", "deepseek" or "qwen".

    Classification is deterministic and fails loud: there is no "other" bucket, because a bucket
    nobody can name would silently accept a same-family pair. Raises ValueError for an alias no
    known family claims (an empty alias, or a vendor the factory has no rule for).
    """
    if not isinstance(alias, str) or not alias.strip():
        raise ModelMatrixError(f"cannot place model alias {alias!r} into a family: empty alias")
    norm = alias.strip().lower()
    for name, keywords in FAMILY_KEYWORDS:
        if any(keyword in norm for keyword in keywords):
            return name
    tokens = [token for token in re.split(r"[^a-z0-9]+", norm) if token]
    if any(KIMI_VERSION_TOKEN.match(token) for token in tokens):
        return "kimi"
    known = ", ".join(name for name, _ in FAMILY_KEYWORDS)
    raise ModelMatrixError(f"cannot place model alias {alias!r} into a family "
                           f"(known families: {known})")


def _comment_free(line: str) -> str:
    """Drop a trailing TOML comment (` #...`); a `#` glued to a value is kept."""
    return re.sub(r"\s+#.*$", "", line).strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _config_defaults(config_path: pathlib.Path) -> tuple[str, str]:
    """(default_model, [secondary_model] default_model) of the CLI config; ("", "") if unreadable.

    Parsed with regexes, not `tomllib` (which exists only from Python 3.11), and only the two keys
    the precedence needs are read — the config also carries secrets, which stay untouched.
    """
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):                 # absent, a directory, no permission
        return "", ""
    primary = ""
    secondary = ""
    section = ""
    for raw in text.splitlines():
        line = _comment_free(raw)
        if not line:
            continue
        header = re.match(r"^\[\[?(.+?)\]\]?$", line)
        if header:
            section = header.group(1).strip()
            continue
        pair = re.match(r'^([A-Za-z0-9_."\-]+)\s*=\s*(.*)$', line)
        if not pair or pair.group(1).strip("\"'") != "default_model":
            continue
        value = _unquote(pair.group(2))
        if section == "":
            primary = primary or value
        elif section == "secondary_model":
            secondary = secondary or value
    return primary, secondary


def _model_preference(path: pathlib.Path) -> str:
    """`model_preference` of a sub-agent file, or "" when there is no such file.

    The YAML frontmatter is the only place it is declared (between the first two `---` lines).
    An existing file without the field runs on the CLI's default model, i.e. primary — the CLI
    behaviour, not a guess of this script. A MISSING file returns "" (no preference at all), so
    the role stays out of the default matrix instead of being handed a model nobody chose.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "primary"
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^model_preference\s*:\s*([A-Za-z0-9_\-]+)", line.strip())
        if match:
            return match.group(1).lower()
    return "primary"


def load_default_matrix(config_path: str | pathlib.Path | None = None) -> dict[str, str]:
    """The factory's DEFAULT MATRIX: role -> model, as configured (case b of the precedence).

    Two inputs, both read, neither required:
      - the CLI config (default `~/.kimi-code/config.toml`): top-level `default_model` (primary)
        and `[secondary_model] default_model` (secondary);
      - the sub-agent frontmatter: `.agents/agents/sub-agents/<role>.md` declares
        `model_preference: primary|secondary`, which selects one of those two values.

    A role with no sub-agent file, or whose side of the config declares no `default_model`, is
    simply ABSENT from the returned dict — the factory has no model to offer for it and must not
    invent one. A missing config file returns `{}` instead of raising: the factory degrades to
    "no default matrix", never to a crash.
    """
    path = pathlib.Path(config_path) if config_path is not None else DEFAULT_CONFIG
    primary, secondary = _config_defaults(path)
    matrix: dict[str, str] = {}
    for role in ROLES:
        preference = _model_preference(SUBAGENTS_DIR / ROLE_FILES.get(role, f"{role}.md"))
        if not preference:
            continue                       # no sub-agent file: no role in the default matrix
        model = secondary if preference == "secondary" else primary
        if model:
            matrix[role] = model
    return matrix


def _matrix(value) -> dict:
    """A task/default matrix as a dict; anything that is not a mapping counts as empty."""
    return value if isinstance(value, dict) else {}


def _model(value) -> str:
    """A matrix value as a model alias; anything that is not a non-empty scalar is empty."""
    if value is None or isinstance(value, bool):
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def resolve(task_matrix, default_matrix, role: str) -> dict:
    """The model of ONE role and where it came from.

    Returns {"role", "model", "source": "task"|"default"|"none", "warnings", "override"}.
    A role named by the task keeps its task value verbatim (`override` stays False, no family
    substitution whatever the families say); otherwise the default matrix decides; otherwise the
    model is empty, the source is "none" and a warning says the model must be supplied. `override`
    exists for the ONE exception (the committee's second planner) and `resolve` never raises it.
    """
    task = _matrix(task_matrix)
    default = _matrix(default_matrix)
    warnings: list[str] = []
    model = _model(task.get(role))
    if role in task and not model:
        warnings.append(f"{role}: models.{role} is present in the task but empty — treated as "
                        f"absent, so the default matrix applies")
    if model:
        return {"role": role, "model": model, "source": "task", "warnings": warnings,
                "override": False}
    model = _model(default.get(role))
    if model:
        return {"role": role, "model": model, "source": "default", "warnings": warnings,
                "override": False}
    warnings.append(f"{role}: no model in the task's models matrix and none in the factory "
                    f"default matrix — the caller must supply one explicitly")
    return {"role": role, "model": "", "source": "none", "warnings": warnings, "override": False}


def resolve_all(task_matrix, default_matrix) -> dict[str, dict]:
    """`resolve` for every role: ROLES order first, then any extra role either matrix carries."""
    task = _matrix(task_matrix)
    default = _matrix(default_matrix)
    order = list(ROLES) + sorted((set(task) | set(default)) - set(ROLES))
    return {role: resolve(task, default, role) for role in order}


def check_families(resolved) -> dict[str, list[str]]:
    """Generator != judge over the resolved roles: {"errors": [...], "warnings": [...]}.

    A same-family pair is a WARNING when BOTH models came from the task (the task is
    authoritative — the collision is reported, never "fixed" by substitution) and an ERROR when
    either side came from the default matrix (the default matrix breaks its own rule; the message
    names the fix). A role whose alias no family claims yields a warning, not a crash: the pair
    cannot be checked, and saying so is the only honest answer.
    """
    entries = list(resolved.values()) if isinstance(resolved, dict) else list(resolved)
    by_role: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        role = _model(entry.get("role"))
        model = _model(entry.get("model"))
        if role and model:
            by_role[role] = (model, _model(entry.get("source")))

    errors: list[str] = []
    warnings: list[str] = []
    families: dict[str, str] = {}
    for role, (model, _source) in by_role.items():
        try:
            families[role] = family(model)
        except ModelMatrixError as exc:
            warnings.append(f"{role}: {exc} — the generator != judge family rule cannot be "
                            f"checked for this role")

    for generator in GENERATOR_SIDE:
        for judge in JUDGE_SIDE:
            if generator not in families or judge not in families:
                continue
            if families[generator] != families[judge]:
                continue
            gen_model, gen_source = by_role[generator]
            judge_model, judge_source = by_role[judge]
            pair = f"{generator} ({gen_model}) and {judge} ({judge_model}) resolve to the same " \
                   f"model family '{families[generator]}'"
            if gen_source == "task" and judge_source == "task":
                warnings.append(
                    f"{pair}; both models come from the task's models matrix, which is "
                    f"authoritative — the model is NOT substituted, the collision is reported "
                    f"only")
            else:
                origins = ", ".join(f"{role} from the {by_role[role][1]} matrix"
                                    for role in (generator, judge))
                errors.append(
                    f"{pair} while {origins}, so the default matrix breaks its own "
                    f"generator != judge rule; fix the default matrix by widening "
                    f"[secondary_model] so the two families differ, or pin models.{generator} / "
                    f"models.{judge} in the task")
    return {"errors": errors, "warnings": warnings}


def committee_second_planner(first_planner_model: str,
                             available=COMMITTEE_POOL) -> str:
    """The second planner of the plan committee: the ONE exception to the matrix.

    Returns the FIRST alias in `available` whose family differs from the first planner's family —
    the committee exists to be independent, so its second planner never shares the first one's
    family, whatever the task's matrix says. Raises ValueError when the first planner's alias is
    unclassifiable or when the pool offers no contrasting family: the factory then has no
    independent planner and must stop instead of pretending it launched one.
    """
    first_family = family(first_planner_model)
    for alias in available:
        try:
            if family(alias) != first_family:
                return alias
        except ModelMatrixError:
            continue                       # an unclassifiable candidate can never contrast
    raise ModelMatrixError(
        f"no model in {list(available)!r} contrasts the family '{first_family}' of "
        f"{first_planner_model!r} — the plan committee needs an independent second planner")


def precedence() -> str:
    """The model precedence as one English paragraph — the single wording every carrier repeats."""
    return (
        "Model precedence. (a) When the task's `models:` matrix names a role, that exact model is "
        "used and the model is never substituted: a generator/judge family collision is only a "
        "WARNING that names both roles and both models and states that the task is authoritative. "
        "(b) When the task does not name the role, its model comes from the factory's DEFAULT "
        "MATRIX — the CLI config's `default_model` / `[secondary_model] default_model` selected by "
        "the role's `model_preference` — where the generator != judge family rule IS enforced: a "
        "same-family coder|tester|gui_expert vs reviewer|diagnostician|advisor pair with either "
        "side taken from the default matrix is an ERROR naming the fix (widen [secondary_model] so "
        "the two families differ, or pin models.<role> in the task). (c) There is no third path: "
        "the main agent never picks a model on its own, so an unnamed role goes to the default "
        "matrix, never to a per-run decision. The ONE exception is the plan committee's second "
        "planner, which always comes from a family CONTRASTING the first planner (deterministically "
        "the first alias in the available pool whose family differs) — the only place an override "
        "is allowed; every other role follows (a) and (b)."
    )


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

MODELS_HEADER = re.compile(r"^models:\s*(#.*)?$")
MODELS_ENTRY = re.compile(r"^(\s+)([A-Za-z0-9_]+)\s*:\s*(\S.*?)\s*$")


def task_models(path: pathlib.Path) -> dict[str, str]:
    """The `models:` block of a task file as role -> alias (an absent block is an empty dict).

    A deliberately small regex reader: the factory owns the task format, and the only block it
    needs here is a flat `role: alias` mapping. Every other key of the task is left to the main
    agent — this script must not grow a YAML parser.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: dict[str, str] = {}
    inside = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not inside:
            if MODELS_HEADER.match(line):
                inside = True
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = MODELS_ENTRY.match(line)
        if not match:
            break                                   # the block ended: a new top-level key
        value = re.sub(r"\s+#.*$", "", match.group(3)).strip().strip("\"'")
        if value:
            entries[match.group(2)] = value
    return entries


def cmd_family(args) -> int:
    try:
        print(family(args.model))
    except ModelMatrixError as exc:
        print(f"model_matrix.py: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_default(args) -> int:
    matrix = load_default_matrix(args.config)
    if not matrix:
        print(f"model_matrix.py: no default matrix resolved from {args.config or DEFAULT_CONFIG} "
              f"— no default_model there, or no sub-agent frontmatter", file=sys.stderr)
        return 0
    for role, model in matrix.items():
        print(f"{role}: {model}")
    return 0


def cmd_resolve(args) -> int:
    try:
        task_matrix = task_models(pathlib.Path(args.task))
    except (OSError, ValueError) as exc:
        print(f"model_matrix.py: cannot read the task file {args.task}: {exc}", file=sys.stderr)
        return 2
    default_matrix = load_default_matrix(args.config)
    resolved = resolve_all(task_matrix, default_matrix)
    report = check_families(resolved)
    if args.json:
        print(json.dumps({"resolved": resolved, "check": report}, indent=2, ensure_ascii=False))
    else:
        for role, entry in resolved.items():
            model = entry["model"] or "(none)"
            print(f"{role}: {model} [{entry['source']}]")
            for warning in entry["warnings"]:
                print(f"  warning: {warning}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
    return 1 if report["errors"] else 0


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    fam = sub.add_parser("family", help="Print the vendor family of a model alias")
    fam.add_argument("--model", required=True, help="Model alias (e.g. kimi-k3, deepseek-flash)")
    fam.set_defaults(func=cmd_family)

    default = sub.add_parser("default", help="Print the factory's default matrix (role: model)")
    default.add_argument("--config", default=None,
                         help=f"CLI config to read (default: {DEFAULT_CONFIG})")
    default.set_defaults(func=cmd_default)

    res = sub.add_parser("resolve", help="Resolve a task's models matrix and check the families")
    res.add_argument("--task", required=True, help="Task file carrying the models matrix")
    res.add_argument("--config", default=None,
                     help=f"CLI config to read (default: {DEFAULT_CONFIG})")
    res.add_argument("--json", action="store_true", help="Print the resolution as JSON")
    res.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

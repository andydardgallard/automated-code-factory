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
  validate_matrix(value, origin)              one models matrix as role -> alias, validated
  load_default_matrix(config_path=None)       role -> model from config.toml + sub-agent frontmatter
  resolve(task_matrix, default_matrix, role)  one role: model, source (task|default|none), warnings
  resolve_all(task_matrix, default_matrix)    every role, in ROLES order
  check_families(resolved)                    {"errors": [...], "warnings": [...]} generator vs judge
  check_resolution(resolved)                  the full pre-flight: unresolved roles + families
  committee_second_planner(first_model, ...)  the contrasting planner of the plan committee
  precedence()                                the precedence, one paragraph

A models matrix is a MAPPING: a supported role key (`ROLES`) -> ONE non-empty model alias string
(and nothing else — a list, a mapping inside a role or an empty value is a contract error, never a
silently empty matrix). `load_default_matrix` reads only the model-selection entries of the CLI
config, and it validates them: a malformed value or an unclosed table header is an actionable
config error, never a literal model alias.

CLI:
  python model_matrix.py family --model deepseek-flash
  python model_matrix.py default [--config ~/.kimi-code/config.toml]
  python model_matrix.py resolve --task .code-factory/state/task.yaml [--config <path>] [--json]

`family` prints the vendor family of one alias. `default` prints the default matrix, `resolve`
prints the resolved matrix of a task plus the family check. Exit codes: 0 = success; 1 = `resolve`
found a resolution ERROR — either a REQUIRED role with no model at all (source `none`: no task
entry and no default-matrix entry, and there is no third path), or the default matrix breaks its
own generator != judge rule; 2 = a contract error with a message and no traceback — an alias
`family` cannot place into a known family, a task file `resolve` cannot read, a models matrix that
is not a mapping of supported roles to non-empty alias strings, or a CLI config whose
model-selection entries are malformed. A missing config file or missing sub-agent file degrades
gracefully (that role is simply absent from the default matrix) — the factory then has no model to
offer and says so instead of inventing one.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# Every role that can be named by a task's `models:` matrix, in the order the factory reports them.
ROLES = ("analyzer", "planner", "coder", "tester", "gui_expert", "farukon_expert",
         "roblox_expert", "business_tester", "refactorer", "reviewer", "supervisor",
         "diagnostician", "advisor", "documenter", "security_auditor", "skill_manager")
# The two sides of the generator != judge rule (gui_expert, farukon_expert and roblox_expert
# implement, so they are generator-side; the business_tester DOES the product as a user and
# reports, so it is generator-side too, while the supervisor only JUDGES a permit and is
# judge-side).
GENERATOR_SIDE = ("coder", "tester", "gui_expert", "farukon_expert", "roblox_expert",
                  "business_tester")
JUDGE_SIDE = ("reviewer", "supervisor", "diagnostician", "advisor")

# Role -> sub-agent file name, where the file name is not `<role>.md`.
ROLE_FILES = {"reviewer": "code-reviewer.md", "gui_expert": "gui-expert.md",
              "farukon_expert": "farukon-expert.md", "roblox_expert": "roblox-expert.md",
              "business_tester": "business-tester.md",
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


CONFIG_TABLE = re.compile(r"^\[(?P<name>[^\[\]]+)\]$")
CONFIG_ARRAY_TABLE = re.compile(r"^\[\[(?P<name>[^\[\]]+)\]\]$")
CONFIG_ENTRY = re.compile(r'^(?P<key>[A-Za-z0-9_."\-]+)\s*=\s*(?P<value>.*)$')


def _config_section(line: str) -> str | None:
    """The table name a config header line declares, or None when the header is malformed.

    TOML closes a table header with the SAME number of brackets it opens: `[secondary_model]`, or
    the array-of-tables form `[[secondary_model]]`. One loose regex accepted a mismatched count
    (`[[secondary_model]`, `[secondary_model]]`), so the section a `default_model` belongs to was
    silently misread instead of failing. Leading whitespace is stripped by the caller: TOML allows
    it before a header, so an indented header is judged exactly like a flush-left one.
    """
    for pattern in (CONFIG_TABLE, CONFIG_ARRAY_TABLE):
        match = pattern.match(line)
        if match:
            return match.group("name").strip()
    return None


def _config_alias(config_path: pathlib.Path, number: int, value: str) -> str:
    """One `default_model` value as a model alias; a malformed value is a config ERROR.

    A `default_model` is a TOML string: ONE quoted alias (`default_model = "kimi-code/k3"`) or one
    bare token. An unclosed quote, an unclosed array, an empty value or text after the closing
    quote is refused with the file, the line and the fix — the reader used to pass such a value
    through `_unquote` untouched, so `default_model = [unterminated` became the model alias
    `[unterminated` for every primary-preference role.
    """
    text = value.strip()
    fix = ('write ONE model alias — a quoted string or a bare token, e.g. '
           'default_model = "kimi-code/k3" (no array, inline table, spaces or commas)')
    if not text:
        problem = "the default_model entry has no value"
    elif text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end < 0:
            problem = f"the quoted default_model value {text!r} never closes"
            fix = f"close the quote ('default_model = {quote}kimi-code/k3{quote}')"
        elif text[end + 1:].strip():
            problem = f"the default_model value {text!r} has text after its closing quote"
        elif not text[1:end].strip():
            problem = "the default_model value is empty"
        else:
            return text[1:end].strip()
    elif re.fullmatch(r"[^\s\[\]{},]+", text):
        return text
    else:
        problem = f"the default_model value {text!r} is not a model alias"
    raise ModelMatrixError(f"{config_path}: line {number}: {problem} — {fix}")


def _config_defaults(config_path: pathlib.Path) -> tuple[str, str]:
    """(default_model, [secondary_model] default_model) of the CLI config; ("", "") if unreadable.

    Parsed with regexes, not `tomllib` (which exists only from Python 3.11), and only the two keys
    the precedence needs are read — the config also carries secrets, which stay untouched. What it
    DOES read is validated, because a misread here hands a role a model nobody configured: a table
    header must be closed with the same number of brackets it opens (otherwise the section a
    `default_model` belongs to is silently misread)
    and a `default_model` value must be one model alias (`_config_alias`). Leading whitespace is
    legal TOML before a header and is stripped first, so an indented header is READ as its section
    (or refused when malformed) exactly like a flush-left one; skipping indented lines hid a real
    `[secondary_model]` section and every malformed indented header alike. Malformed content raises
    ModelMatrixError naming the file, the line and the fix.
    """
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):                 # absent, a directory, no permission
        return "", ""
    primary = ""
    secondary = ""
    section = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = _comment_free(raw)
        if not line:
            continue
        if line.startswith("["):
            name = _config_section(line)
            if name is None:
                raise ModelMatrixError(
                    f"{config_path}: line {number}: the table header {line!r} is not closed — a "
                    f"table header is written '[name]' on one line with the SAME number of "
                    f"closing brackets (e.g. '[secondary_model]'); without it a default_model "
                    f"below is read in the wrong section")
            section = name
            continue
        pair = CONFIG_ENTRY.match(line)
        key = pair.group("key").strip("\"'") if pair else ""
        value = pair.group("value") if pair else ""
        if key == "default_model":
            alias = _config_alias(config_path, number, value)
            if section == "":
                primary = primary or alias
            elif section == "secondary_model":
                secondary = secondary or alias
            continue
        if not pair and line.startswith("default_model"):
            raise ModelMatrixError(
                f"{config_path}: line {number}: {line!r} is not a model-selection entry — write "
                f"default_model = \"kimi-code/k3\" on one line")
        if pair and not value.strip():
            raise ModelMatrixError(
                f"{config_path}: line {number}: the entry {key!r} has no value — write "
                f"'{key} = <value>' or delete the line")
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
    "no default matrix", never to a crash. MALFORMED config content is different: a
    `default_model` that is not a model alias, or a table header that is not closed, raises
    ModelMatrixError naming the file, the line and the fix (`_config_defaults`).
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


def _checked_role(role, where: str) -> str:
    """`role` when it is a supported model role; a contract error naming the roster otherwise."""
    if not isinstance(role, str) or role not in ROLES:
        raise ModelMatrixError(
            f"{where}{role!r} is not a supported model role — the supported roles are: "
            f"{', '.join(ROLES)}; fix the key name or drop the entry")
    return role


def _checked_alias(role: str, alias, where: str) -> str:
    """One role's model alias: a non-empty string; a contract error naming the role otherwise."""
    if not isinstance(alias, str) or not alias.strip():
        raise ModelMatrixError(
            f"{where}models.{role} is not a model alias ({alias!r}) — one role takes ONE "
            f"non-empty model alias string (e.g. '{role}: kimi-code/k3'), not an empty value, a "
            f"list or a mapping")
    return alias.strip()


def validate_matrix(value, origin: str) -> dict[str, str]:
    """A models matrix as role -> alias; anything else is a contract error, never an empty matrix.

    `None` is a legitimate absence (no `models:` block at all) and yields `{}`, exactly like an
    explicitly empty mapping. Everything else must be a MAPPING of a supported role
    (`ROLES`) to one non-empty model alias string — a list of entries, a bare string, a list or a
    mapping inside a role and an empty alias are all refused with a message naming the matrix, the
    offending key and the roster. The pre-fix resolver coerced every one of them to an empty matrix
    (or to the alias `str(value)`), so a wrong-shaped block silently resolved the defaults.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelMatrixError(
            f"{origin}: {value!r} is not a models matrix — it must be a MAPPING of a supported "
            f"role to one model alias (one '<role>: <alias>' entry per role), not a "
            f"{type(value).__name__}; the supported roles are: {', '.join(ROLES)}")
    matrix: dict[str, str] = {}
    for role, alias in value.items():
        _checked_role(role, f"{origin}: ")
        matrix[role] = _checked_alias(role, alias, f"{origin}: ")
    return matrix


def _model(value) -> str:
    """A matrix value as a model alias; anything that is not a non-empty scalar is empty."""
    if value is None or isinstance(value, bool):
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def resolve(task_matrix, default_matrix, role: str) -> dict:
    """The model of ONE role and where it came from.

    Returns {"role", "model", "source": "task"|"default"|"none", "warnings", "override"}.
    Both matrices are validated first (see `validate_matrix`): a wrong-shaped or unsupported
    models matrix raises instead of resolving the defaults. A role named by the task keeps its task
    value verbatim (`override` stays False, no family substitution whatever the families say);
    otherwise the default matrix decides; otherwise the model is empty, the source is "none" and a
    warning says the model must be supplied. `override` exists for the ONE exception (the
    committee's second planner) and `resolve` never raises it.
    """
    return _resolve(validate_matrix(task_matrix, "the task's models matrix"),
                    validate_matrix(default_matrix, "the default matrix"), role)


def _resolve(task: dict[str, str], default: dict[str, str], role: str) -> dict:
    """`resolve` over two ALREADY validated matrices (no re-validation per role)."""
    warnings: list[str] = []
    model = _model(task.get(role))
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
    """`resolve` for every role, in ROLES order.

    An unsupported role key makes either matrix a contract error: `ROLES` is the whole roster the
    factory launches, so a key outside it can never be a resolved entry (the pre-fix code appended
    every extra key and printed it as if the assignment had taken effect).
    """
    task = validate_matrix(task_matrix, "the task's models matrix")
    default = validate_matrix(default_matrix, "the default matrix")
    return {role: _resolve(task, default, role) for role in ROLES}


def _default_side(role: str, source: str) -> str:
    """The side of the CLI config a role resolves from ("primary"|"secondary"), or "" when the
    role does not come from the default matrix (or its sub-agent file declares no preference).
    """
    if source != "default":
        return ""
    return _model_preference(SUBAGENTS_DIR / ROLE_FILES.get(role, f"{role}.md"))


def check_families(resolved) -> dict[str, list[str]]:
    """Generator != judge over the resolved roles: {"errors": [...], "warnings": [...]}.

    A same-family pair is a WARNING when BOTH models came from the task (the task is
    authoritative — the collision is reported, never "fixed" by substitution) and an ERROR when
    either side came from the default matrix (the default matrix breaks its own rule; the message
    names only an ACHIEVABLE fix: when both roles read the SAME side of the config, no widening
    of that one key can separate them, so only pinning models.<role> in the task is named). A
    role whose alias no family claims yields a warning, not a crash: the pair cannot be checked,
    and saying so is the only honest answer. Likewise, when one whole SIDE (every generator or
    every judge) resolved no model at all, the rule cannot be fully checked — a warning says so
    instead of silently passing.
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

    generator_present = any(role in by_role for role in GENERATOR_SIDE)
    judge_present = any(role in by_role for role in JUDGE_SIDE)
    if generator_present != judge_present:
        missing = "judge" if generator_present else "generator"
        side = JUDGE_SIDE if generator_present else GENERATOR_SIDE
        warnings.append(f"no {missing}-side role ({', '.join(side)}) resolved a model — the "
                        f"generator != judge family rule cannot be fully checked")

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
                gen_side = _default_side(generator, gen_source)
                judge_side = _default_side(judge, judge_source)
                if gen_side and gen_side == judge_side:
                    # Both roles read the SAME config key: widening that key moves both models
                    # together, so it can never separate them — only a task-side pin can.
                    remedy = (f"both roles take the {gen_side} side of the default matrix, so "
                              f"no widening of that one key can separate them — pin "
                              f"models.{generator} or models.{judge} in the task")
                else:
                    remedy = (f"fix the default matrix by widening [secondary_model] so the two "
                              f"families differ, or pin models.{generator} / models.{judge} in "
                              f"the task")
                errors.append(
                    f"{pair} while {origins}, so the default matrix breaks its own "
                    f"generator != judge rule; {remedy}")
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
        "same-family coder|tester|gui_expert|farukon_expert|roblox_expert vs "
        "reviewer|diagnostician|advisor pair with either "
        "side taken from the default matrix is an ERROR naming the fix (widen [secondary_model] so "
        "the two families differ, or pin models.<role> in the task). (c) There is no third path: "
        "the main agent never picks a model on its own, so an unnamed role goes to the default "
        "matrix, never to a per-run decision. The ONE exception is the plan committee's second "
        "planner, which always comes from a family CONTRASTING the first planner (deterministically "
        "the first alias in the available pool whose family differs) — the only place an override "
        "is allowed; every other role follows (a) and (b)."
    )


def check_resolution(resolved) -> dict[str, list[str]]:
    """The full pre-flight of a run: unresolved REQUIRED roles + the generator != judge check.

    Every role `resolve_all()` returns is a role the factory must launch, so every one of them is
    REQUIRED: a role whose source is "none" has no model at all, and the contract offers no third
    path to fall back on (rule `models-generator-ne-judge`). Such a role is an ERROR, not the
    per-entry warning `resolve()` carries — otherwise a completely empty configuration (no task
    `models:` block, no default matrix) would read as a clean resolve and the run would start
    with roles nobody can hand a model to. Returns {"errors", "warnings"}, the family check's own
    lists included, so a caller has ONE verdict to act on.
    """
    report = check_families(resolved)
    entries = list(resolved.values()) if isinstance(resolved, dict) else list(resolved)
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if _model(entry.get("model")):
            continue
        role = _model(entry.get("role")) or "<unknown>"
        errors.append(
            f"{role}: no model resolved — the task's models matrix does not name this role and "
            f"the default matrix offers none (source 'none'); there is no third path, so pin "
            f"models.{role} in the task or have the role's side of the default matrix declare a "
            f"model before the run starts")
    return {"errors": errors + report["errors"], "warnings": report["warnings"]}


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

MODELS_HEADER = re.compile(r"^models:\s*(?P<rest>.*)$")
MODELS_ENTRY = re.compile(r"^\s+(?P<role>[A-Za-z0-9_]+)\s*:\s*(?P<value>.*)$")


def task_models(path: pathlib.Path) -> dict[str, str]:
    """The `models:` block of a task file as role -> alias (an absent block is an empty dict).

    A deliberately small regex reader: the factory owns the task format, and the only block it
    needs here is a flat `role: alias` mapping. Every other key of the task is left to the main
    agent — this script must not grow a YAML parser. What it DOES read is validated like a matrix
    (`validate_matrix`): a value on the `models:` line (a list or an inline shape), a line that is
    not `<role>: <alias>`, an unsupported role key, a duplicate role and a missing or unquoted
    alias are contract errors naming the file, the line and the fix. The pre-fix reader stopped at
    the first such line and returned an empty matrix, so a malformed block silently resolved the
    default models — and an unsupported role was printed as a valid entry.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: dict[str, str] = {}
    inside = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        where = f"{path}: line {number}: "
        if not inside:
            header = MODELS_HEADER.match(line)
            if header:
                rest = header.group("rest").strip()
                if rest and not rest.startswith("#"):
                    raise ModelMatrixError(
                        f"{where}'models:' carries the value {rest!r} — a models matrix is a "
                        f"MAPPING, so leave the line as 'models:' and indent one "
                        f"'<role>: <model alias>' entry per line")
                inside = True
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            break                                   # the block ended: a new top-level key
        match = MODELS_ENTRY.match(line)
        if not match:
            raise ModelMatrixError(
                f"{where}{line.strip()!r} is not a matrix entry — every entry of the models matrix "
                f"is one line '<role>: <model alias>' indented under 'models:' (a list or a nested "
                f"mapping is not a matrix)")
        role = _checked_role(match.group("role"), where)
        if role in entries:
            raise ModelMatrixError(f"{where}duplicate models entry '{role}' — each role appears "
                                   f"once in the matrix")
        alias = re.sub(r"\s+#.*$", "", match.group("value")).strip()
        if alias[:1] in ("'", '"'):
            if len(alias) < 2 or alias[-1] != alias[0]:
                raise ModelMatrixError(
                    f"{where}models.{role} has the unterminated quoted alias {alias!r} — close the "
                    f"quote on this line or write the alias without quotes")
            alias = alias[1:-1]
        entries[role] = _checked_alias(role, alias, where)
    return entries


def cmd_family(args) -> int:
    try:
        print(family(args.model))
    except ModelMatrixError as exc:
        print(f"model_matrix.py: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_default(args) -> int:
    try:
        matrix = load_default_matrix(args.config)
    except ModelMatrixError as exc:
        print(f"model_matrix.py: {exc}", file=sys.stderr)
        return 2
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
        default_matrix = load_default_matrix(args.config)
    except OSError as exc:
        print(f"model_matrix.py: cannot read the task file {args.task}: {exc}", file=sys.stderr)
        return 2
    except ModelMatrixError as exc:
        print(f"model_matrix.py: {exc}", file=sys.stderr)
        return 2
    resolved = resolve_all(task_matrix, default_matrix)
    report = check_resolution(resolved)
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

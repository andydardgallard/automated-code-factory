#!/usr/bin/env python3
"""
Deterministic self-test for the ERROR contract of `task_parser.py` (stdlib only).

A parser that rejects a task without saying what to fix is worse than no parser: the owner is
non-technical and the run stops anyway. The contract under test:

  (a) every malformed task file exits 2 with an ACTIONABLE message — it names the file, the LINE,
      what is wrong and the concrete fix (a shape to write instead);
  (b) a message is never a traceback and never a generic "cannot read file" — an authoring error
      and an unreadable file are different messages;
  (c) the CLI keeps the house contract: `--help` exits 0 with usage, a wrong invocation exits 2 with
      a message and no traceback.

Cases (fixtures live in a tempdir; nothing is written into the repository):

  1. a list item with no value (`- criterion:`) exits 2 naming the line, the missing value and both
     shapes to write instead (an inline one and a block scalar);
  2. a misaligned sibling key inside a criterion exits 2 naming the line, the column it needs and
     the indentation rule;
  3. an unknown `task_type` value exits 2 naming the line, the value and the allowed values;
  4. a missing required `title` exits 2 naming the field and the line to add;
  5. an invalid boolean is never coerced: `derived: perhaps` exits 2 naming the line, the value and
     both allowed values (the pre-fix code silently turned it into `false`), while `true`/`false` in
     any case are accepted;
  6. the CLI contract: `--help` exits 0 with usage, a missing `--task` exits 2, an unreadable task
     file exits 2 with a read message — none of them prints a traceback, and the successful path
     stays silent on stderr;
  7. REGRESSION (self-review 20261031-d2f6fea6, critical 12): an unterminated double or single quote
     and an invalid double-quoted escape sequence exit 2 naming the line and the fix — the pre-fix
     `_scalar` only recognised a quoted scalar when BOTH delimiters existed and otherwise returned
     the text unchanged, so `title: "unterminated` parsed successfully — while well-formed quotes
     and escapes still parse verbatim;
  8. REGRESSION (review 20261126, N02/M03): the `models:` block is validated against the ONE role
     registry of `model_matrix.ROLES`, so a misspelled role key (`made_up_role`) exits 2 naming the
     line, the role and the supported roles — the pre-fix parser accepted any key and the resolver
     then printed it as a valid entry — and a list-shaped `models:` block stays a refusal; a
     supported role->alias mapping still parses.
  9. REGRESSION (review 20261126, N04): an UNQUOTED YAML anchor (`&name`) or alias (`*name`) at the
     start of a value exits 2 naming the line, the construct and the fix — the pre-fix parser read
     `title: &title Anchored` as the literal text `'&title Anchored'` (BA-008) — while a QUOTED
     anchor/alias, the same characters inside a block scalar and a plain scalar keeps them verbatim.
  10. REGRESSION (business-adversarial BA-033): a plain scalar whose YAML flow collection (`[...]` /
     `{...}`) is never closed exits 2 naming the line, the opener and the fix — the pre-fix parser
     accepted `title: [unterminated`, `description: [see the notes` and `repo_path: [unterminated`
     as literal task data — while a BALANCED pair and a quoted value keep such characters as text.
     An apostrophe inside a plain scalar (`[Bob's]`) is literal text, so it neither raises a false
     unclosed-flow error nor hides a really unclosed opener.
  11. REGRESSION (review-3): WHITESPACE alone is not a scalar boundary. `title: Ask [Bob 's] notes`
     used to open a quoted region at the apostrophe that merely follows a space, swallow the
     closing `]` and exit 2 on a perfectly valid value; a quoted scalar may begin only at a value
     start or after a flow opener/comma/separator (whitespace in between allowed), so legitimate
     quoted flow elements still parse (a quote there IS a delimiter again) and a real unclosed
     opener with a quoted element in front of it is still refused.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task_parser as tp  # noqa: E402  (after the sys.path guard, so the test runs from anywhere)

TOOL = SCRIPTS / "task_parser.py"
# The messages carry non-ASCII characters (em dashes): pin UTF-8 on the child's streams.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

# line numbers below are 1-based and refer to the fixture text that carries them.
MISSING_VALUE = """\
title: "A criterion without a value"
repo_path: .
acceptance_criteria:
  - criterion:
"""

BAD_INDENT = """\
title: "A misaligned sibling key"
repo_path: .
acceptance_criteria:
  - criterion: "The report lists the CNY instrument."
    verify: "true"
   derived: true
"""

BAD_TASK_TYPE = """\
title: "An unknown task type"
repo_path: .
task_type: audit
"""

MISSING_TITLE = """\
repo_path: .
description: |
  The business goal, written for a person.
"""

BAD_DERIVED = """\
title: "An invalid boolean"
repo_path: .
acceptance_criteria:
  - criterion: "The report lists the CNY instrument."
    derived: perhaps
"""

DERIVED_CASE_VARIANTS = """\
title: "Boolean case variants"
repo_path: .
acceptance_criteria:
  - criterion: "The report lists the CNY instrument."
    derived: TRUE
  - criterion: "The report lists the Si instrument."
    derived: False
"""

VALID = """\
title: "A valid task"
repo_path: .
acceptance_criteria:
  - criterion: "The report lists the CNY instrument."
"""

# REGRESSION (self-review 20261031-d2f6fea6, critical 12): the quoted-scalar shapes that used to be
# accepted silently. Each line number below is 1-based in its own fixture.
UNTERMINATED_DOUBLE = """\
title: "A title whose quote never closes
repo_path: .
"""

UNTERMINATED_SINGLE = """\
title: 'A title whose quote never closes
repo_path: .
"""

BAD_DOUBLE_ESCAPE = """\
title: "A \\q bad escape"
repo_path: .
"""

QUOTED_ESCAPES_OK = """\
title: "A \\"quoted\\" \\\\ title with \\t escapes"
repo_path: .
acceptance_criteria:
  - "A plain quoted item with a \\"quote\\" inside."
"""

# REGRESSION (review 20261126, N02/M03): the models block must name a SUPPORTED role and must be a
# mapping. Each line number below is 1-based in its own fixture.
UNKNOWN_MODELS_ROLE = """\
title: "An unknown model role"
repo_path: .
models:
  coder: deepseek-flash
  made_up_role: deepseek-flash
"""

MODELS_AS_LIST = """\
title: "A models block written as a list"
repo_path: .
models:
  - coder: deepseek-flash
"""

MODELS_OK = """\
title: "A supported models matrix"
repo_path: .
models:
  coder: deepseek-flash
  reviewer: kimi-code/k3
"""

# REGRESSION (review 20261126, N04): YAML anchors/aliases are unsupported and were read as literal
# text. Each line number below is 1-based in its own fixture.
ANCHOR_VALUE = """\
title: &title Anchored title
repo_path: .
"""

ALIAS_VALUE = """\
title: "An alias in a criterion"
repo_path: .
acceptance_criteria:
  - criterion: *shared
"""

ANCHOR_BLOCK_VALUE = """\
title: "An anchor in an indented text block"
repo_path: .
user_story:
  &story As the owner, I want the report.
"""

ANCHORS_AS_TEXT_OK = """\
title: "&title Anchored title"
repo_path: .
description: |
  Keep &anchor and *alias as literal characters.
acceptance_criteria:
  - "An item quoting *shared verbatim."
  - criterion: '&title in single quotes'
commit_exclude:
  - "&build and *release stay text"
"""

# REGRESSION (business-adversarial BA-033): a plain scalar whose YAML flow collection is never
# CLOSED was read as literal text, so `[unterminated` became valid title/description/repo_path data.
# Each line number below is 1-based in its own fixture.
UNCLOSED_FLOW_TITLE = """\
title: [unterminated
repo_path: .
"""

UNCLOSED_FLOW_DESCRIPTION = """\
title: "An unclosed flow collection"
repo_path: .
description: [see the owner's notes
"""

UNCLOSED_FLOW_REPO_PATH = """\
title: "An unclosed flow collection"
repo_path: [unterminated
"""

FLOW_COLLECTIONS_AS_TEXT_OK = """\
title: See [the notes] and {the glossary} for the wording
repo_path: .
description: "[unterminated is intended text inside a quoted scalar"
acceptance_criteria:
  - criterion: "The report lists the CNY instrument."
    verify: "test -f report[1].txt"
"""

# REGRESSION (review-2 finding 2): an apostrophe inside a PLAIN scalar is literal text, never the
# opening quote of a quoted scalar — `[Bob's]` used to hide its own closing bracket behind a quote
# state nobody opened, so a perfectly valid task file failed with "unclosed flow collection".
APOSTROPHE_PLAIN_SCALARS_OK = """\
title: Ask Bob's team whether [Bob's] notes and {the owner's} rules apply
repo_path: .
description: |
  Don't rewrite someone else's plain text; the owner's [notes] stay readable.
acceptance_criteria:
  - criterion: The player's own [inventory] list is unchanged
    verify: test -f "report[1].txt"
"""

# REGRESSION (review-3): WHITESPACE alone must not count as a scalar boundary. A quote after a
# space in plain text is the apostrophe of `[Bob 's]`, not the opening of a quoted scalar, so the
# closing `]` stays visible and the value is valid.
QUOTE_AFTER_SPACE_OK = """\
title: Ask [Bob 's] team and {the owner 's} rules
repo_path: .
description: Roll call for [Bob 's] shift is done
acceptance_criteria:
  - criterion: The [Bob 's] list is complete
    verify: test -f "report[1].txt"
"""

# The same rule must still DELIMIT a real quoted element inside a flow collection…
QUOTED_FLOW_ELEMENTS_OK = """\
title: Roll call [Bob, 'Carol'] and {'owner': 'the lead'}
repo_path: .
description: Notes for Bob, 'the lead' and [Bob 's] stay text
"""

# …and it must still catch a really unclosed opener, quoted element in front of it or not.
UNCLOSED_FLOW_AFTER_QUOTED_ELEMENT = """\
title: Roll call [Bob 's] and [unterminated
repo_path: .
"""


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=ENV)


def out(res: subprocess.CompletedProcess[bytes]) -> str:
    """stdout as text, CRLF-normalized (Windows text-mode stdout may translate newlines)."""
    return res.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def err(res: subprocess.CompletedProcess[bytes]) -> str:
    return res.stderr.decode("utf-8", "replace")


def expect_failure(res: subprocess.CompletedProcess[bytes], task_file: pathlib.Path,
                   needles: tuple[str, ...]) -> str:
    """The one shape every malformed task must produce: exit 2, one actionable line, no traceback."""
    message = err(res)
    expect(res.returncode == 2, f"{task_file.name} must exit 2, got {res.returncode}: {message!r}")
    expect("Traceback" not in message, f"{task_file.name}: no traceback allowed: {message!r}")
    expect(out(res).strip() == "", f"{task_file.name}: nothing may be printed on stdout: "
                                   f"{out(res)!r}")
    expect(message.startswith("error: "), f"{task_file.name}: one 'error: ' line expected: "
                                          f"{message!r}")
    expect(len(message.strip().splitlines()) == 1,
           f"{task_file.name}: the message must be ONE line (no dump): {message!r}")
    expect(task_file.name in message, f"{task_file.name}: the message must name the file: "
                                      f"{message!r}")
    for needle in needles:
        expect(needle in message, f"{task_file.name}: the message must carry {needle!r}: "
                                  f"{message!r}")
    return message


def case_1_item_without_a_value(root: pathlib.Path) -> None:
    """(a) `- criterion:` with no value: the line, the problem and both shapes to write."""
    task_file = write(root, "missing-value.yaml", MISSING_VALUE)
    expect_failure(run("parse", "--task", str(task_file)), task_file,
                   ("line 4", "'criterion' item is missing a value",
                    "- criterion: <text>", "- criterion: |", "indented lines"))
    # the library raises the same actionable text (the CLI is not the only entry point).
    try:
        tp.parse_file(task_file)
    except tp.TaskError as exc:
        expect(exc.line == 4 and "- criterion: |" in str(exc),
               f"TaskError must name line 4 and the fix: {exc!r}")
    else:
        raise AssertionError("a criterion without a value must raise TaskError")


def case_2_bad_indentation(root: pathlib.Path) -> None:
    """(a) A misaligned sibling key: the line, the needed column and the rule to follow."""
    task_file = write(root, "bad-indent.yaml", BAD_INDENT)
    expect_failure(run("parse", "--task", str(task_file)), task_file,
                   ("line 6", "inconsistent indentation", "column 4", "2 per nesting level"))
    try:
        tp.parse_file(task_file)
    except tp.TaskError as exc:
        expect(exc.line == 6, f"TaskError must name the offending line: {exc!r}")
    else:
        raise AssertionError("a misaligned sibling key must raise TaskError")


def case_3_unknown_task_type(root: pathlib.Path) -> None:
    """(a) An unknown enum value names the value AND the allowed ones."""
    task_file = write(root, "bad-task-type.yaml", BAD_TASK_TYPE)
    expect_failure(run("parse", "--task", str(task_file)), task_file,
                   ("line 3", "unknown task_type value", "'audit'",
                    "implement, review, refactor, security_audit"))


def case_4_missing_required_title(root: pathlib.Path) -> None:
    """(a) A missing required field names the field and the line to add."""
    task_file = write(root, "missing-title.yaml", MISSING_TITLE)
    expect_failure(run("parse", "--task", str(task_file)), task_file,
                   ("missing required field 'title'", "title: <short business goal>"))


def case_5_invalid_boolean_is_a_hard_error(root: pathlib.Path) -> None:
    """(a) `derived: perhaps` is refused — never silently coerced to `false` (the pre-fix bug)."""
    task_file = write(root, "bad-derived.yaml", BAD_DERIVED)
    expect_failure(run("parse", "--task", str(task_file)), task_file,
                   ("line 5", "'derived' takes 'true' or 'false'", "'perhaps'",
                    "derived: true", "derived: false"))
    try:
        tp.parse_file(task_file)
    except tp.TaskError as exc:
        expect(exc.line == 5 and "true" in str(exc) and "false" in str(exc),
               f"TaskError must name line 5 and both allowed values: {exc!r}")
    else:
        raise AssertionError("an invalid 'derived' value must raise TaskError, not become false")

    # The documented values pass, in any case — the check is strict about the SPELLING only.
    variants = write(root, "derived-variants.yaml", DERIVED_CASE_VARIANTS)
    res = run("parse", "--task", str(variants))
    expect(res.returncode == 0,
           f"'true'/'false' in any case must be accepted: {res.returncode} {err(res)!r}")
    task, _warnings = tp.parse_file(variants)
    expect(tp.normalize(task)["acceptance_criteria"] ==
           [{"criterion": "The report lists the CNY instrument.", "verify": None,
             "derived": True},
            {"criterion": "The report lists the Si instrument.", "verify": None,
             "derived": False}],
           f"the boolean values must be read as booleans: {tp.normalize(task)!r}")


def case_6_cli_contract(root: pathlib.Path) -> None:
    """(c) `--help` 0, a wrong or unreadable invocation 2 — a traceback never appears."""
    helped = run("--help")
    expect(helped.returncode == 0, f"--help must exit 0: {err(helped)!r}")
    expect("usage:" in out(helped), f"--help must print usage: {out(helped)!r}")
    expect("Traceback" not in err(helped), f"--help must not traceback: {err(helped)!r}")
    parse_help = run("parse", "--help")
    expect(parse_help.returncode == 0 and "--out" in out(parse_help),
           f"parse --help must document --out: {out(parse_help)!r}")

    missing_arg = run("parse")
    expect(missing_arg.returncode == 2, "a missing --task must exit 2")
    expect("Traceback" not in err(missing_arg), f"usage errors must not traceback: "
                                               f"{err(missing_arg)!r}")
    expect("--task" in err(missing_arg), f"the usage error must name --task: {err(missing_arg)!r}")

    unknown = root / "no-such-task.yaml"
    unreadable = run("parse", "--task", str(unknown))
    expect_failure(unreadable, unknown, ("cannot read task file", "check the path"))
    expect("line " not in err(unreadable),
           f"an unreadable file is a READ error, not an authoring error: {err(unreadable)!r}")

    # the happy path stays quiet on stderr and is the only one that prints a summary.
    task_file = write(root, "valid.yaml", VALID)
    ok = run("parse", "--task", str(task_file))
    expect(ok.returncode == 0, f"a valid task must exit 0: {err(ok)!r}")
    expect(ok.stderr == b"", f"a valid task must not warn: {err(ok)!r}")
    expect(out(ok).strip().startswith("ok: ") and "acceptance_criteria=1" in out(ok),
           f"the summary must carry the counts: {out(ok)!r}")


def case_7_malformed_quoted_scalars_are_rejected(root: pathlib.Path) -> None:
    """Regression (self-review 20261031-d2f6fea6, critical 12): a broken quote is an error.

    `_scalar` used to treat text as double-quoted only when BOTH delimiters were present and
    otherwise returned it unchanged, so `title: "unterminated` parsed successfully (exit 0, title
    `'"unterminated'`) and malformed owner input entered every later stage. An unterminated quote
    and an invalid double-quoted escape are now refused with the same actionable exit 2.
    """
    # (a) unterminated double quote, (b) unterminated single quote, (c) invalid escape sequence.
    # Every message must also show the offending text, so the owner can see what broke.
    for name, text, needles in (
            ("unterminated-double.yaml", UNTERMINATED_DOUBLE,
             ("line 1", "unterminated", "double-quoted", "closing quote",
              "A title whose quote never closes")),
            ("unterminated-single.yaml", UNTERMINATED_SINGLE,
             ("line 1", "unterminated", "single-quoted", "closing quote",
              "A title whose quote never closes")),
            ("bad-escape.yaml", BAD_DOUBLE_ESCAPE,
             ("line 1", "invalid", "double-quoted", "escape", "\\q"))):
        task_file = write(root, name, text)
        expect_failure(run("parse", "--task", str(task_file)), task_file, needles)
        try:
            tp.parse_file(task_file)
        except tp.TaskError as exc:
            expect("line 1" in str(exc),
                   f"{name}: the library error must name line 1: {exc!r}")
        else:
            raise AssertionError(f"{name}: a malformed quoted scalar must raise TaskError")

    # The VALUE is never invented: a broken quote is refused instead of being half-read.
    expect(not (root / "bad-escape.json").exists(),
           "a refused task must not write its normalized JSON")

    # Contrast: WELL-FORMED escapes and quotes still parse (the check is about breaking the quote
    # contract, not about banning quotes).
    good = write(root, "quoted-escapes.yaml", QUOTED_ESCAPES_OK)
    res = run("parse", "--task", str(good))
    expect(res.returncode == 0, f"a well-formed quoted scalar must parse: {err(res)!r}")
    task, _warnings = tp.parse_file(good)
    expect(task["title"] == 'A "quoted" \\ title with \t escapes',
           f"the escapes must be decoded: {task['title']!r}")
    expect(task["acceptance_criteria"] == [{"criterion": 'A plain quoted item with a "quote" '
                                                          'inside.'}],
           f"a quoted list item must survive: {task['acceptance_criteria']!r}")


def case_8_models_block_is_validated(root: pathlib.Path) -> None:
    """Regression (review 20261126, N02/M03): the models block names SUPPORTED roles only.

    The parser used to accept any `models:` key, so a misspelled role entered every later stage and
    the resolver printed it as a valid resolved entry. The block is now checked against the ONE
    role registry (`model_matrix.ROLES`, imported rather than re-declared), and a wrong-shaped
    block stays a refusal instead of becoming an empty matrix.
    """
    for name, text, line, needles in (
            ("unknown-models-role.yaml", UNKNOWN_MODELS_ROLE, "line 5",
             ("unknown models role", "made_up_role", "analyzer", "role")),
            ("models-as-list.yaml", MODELS_AS_LIST, "line 4",
             ("models", "role", "- coder: deepseek-flash"))):
        task_file = write(root, name, text)
        expect_failure(run("parse", "--task", str(task_file)), task_file,
                       (line, *needles))
        try:
            tp.parse_file(task_file)
        except tp.TaskError as exc:
            expect(line in str(exc), f"{name}: TaskError must name {line}: {exc!r}")
        else:
            raise AssertionError(f"{name}: a wrong models block must raise TaskError")

    # Contrast: a supported role->alias mapping still parses, and its count is reported.
    good = write(root, "models-ok.yaml", MODELS_OK)
    res = run("parse", "--task", str(good))
    expect(res.returncode == 0, f"a supported models matrix must parse: {err(res)!r}")
    expect("models=2" in out(res), f"the summary must count the models: {out(res)!r}")
    task, _warnings = tp.parse_file(good)
    expect(task["models"] == {"coder": "deepseek-flash", "reviewer": "kimi-code/k3"},
           f"the matrix must be read verbatim: {task['models']!r}")


def case_9_anchors_and_aliases_are_rejected(root: pathlib.Path) -> None:
    """Regression (review 20261126, N04): an unsupported anchor/alias is refused, not literal text.

    The parser read `title: &title Anchored` as the literal string `'&title Anchored'` and
    `- criterion: *shared` as `'*shared'`, so a construct it cannot resolve entered every later
    stage as if the owner had written it. An unquoted anchor or alias at the start of a value is
    now exit 2 naming the line, the construct and the fix; quoted text (and a `&`/`*` inside a
    plain scalar or a block scalar) is intended literal characters and is kept verbatim.
    """
    for name, text, line, kind in (
            ("anchor-value.yaml", ANCHOR_VALUE, "line 1", "anchor"),
            ("alias-value.yaml", ALIAS_VALUE, "line 4", "alias"),
            ("anchor-block-value.yaml", ANCHOR_BLOCK_VALUE, "line 4", "anchor")):
        task_file = write(root, name, text)
        expect_failure(run("parse", "--task", str(task_file)), task_file,
                       (line, "unsupported", kind, "aliases", "quote it"))
        try:
            tp.parse_file(task_file)
        except tp.TaskError as exc:
            expect(exc.line == int(line.split()[1]) and kind in str(exc),
                   f"{name}: TaskError must name {line} and the {kind}: {exc!r}")
        else:
            raise AssertionError(f"{name}: an unquoted {kind} must raise TaskError")

    # Contrast: quoted anchors/aliases — and the same characters inside a block scalar or a longer
    # plain scalar — are intended LITERAL text and must survive verbatim.
    good = write(root, "anchors-as-text.yaml", ANCHORS_AS_TEXT_OK)
    res = run("parse", "--task", str(good))
    expect(res.returncode == 0, f"quoted anchor/alias text must parse: {res.returncode} "
                                f"{err(res)!r}")
    expect(res.stderr == b"", f"quoted anchor/alias text must not warn: {err(res)!r}")
    task, _warnings = tp.parse_file(good)
    expect(task["title"] == "&title Anchored title",
           f"a quoted anchor must stay literal text: {task['title']!r}")
    expect(task["description"] == "Keep &anchor and *alias as literal characters.\n",
           f"a block scalar keeps its &/* characters: {task['description']!r}")
    expect([item["criterion"] for item in task["acceptance_criteria"]] ==
           ["An item quoting *shared verbatim.", "&title in single quotes"],
           f"quoted list items must stay literal: {task['acceptance_criteria']!r}")
    expect(task["commit_exclude"] == ["&build and *release stay text"],
           f"a quoted string list item must stay literal: {task['commit_exclude']!r}")


def case_10_unclosed_flow_collections_are_rejected(root: pathlib.Path) -> None:
    """Regression (business-adversarial BA-033): an unclosed `[`/`{` is an error, not task data.

    The parser has no flow-collection reader, so a plain scalar with an unclosed opener used to
    travel on as literal text: `title: [unterminated` parsed successfully and the malformed
    value — including `repo_path: [unterminated` — entered every later stage as valid task data.
    An unclosed opener is now exit 2 naming the line, the opener and the fix, while a BALANCED
    pair and a quoted or block-scalar value keep such characters as intended literal text.
    """
    for name, text, line, opener in (
            ("unclosed-flow-title.yaml", UNCLOSED_FLOW_TITLE, "line 1", "'['"),
            ("unclosed-flow-description.yaml", UNCLOSED_FLOW_DESCRIPTION, "line 3", "'['"),
            ("unclosed-flow-repo-path.yaml", UNCLOSED_FLOW_REPO_PATH, "line 2", "'['")):
        task_file = write(root, name, text)
        expect_failure(run("parse", "--task", str(task_file)), task_file,
                       (line, "unclosed YAML flow collection", opener,
                        "quote it"))
        try:
            tp.parse_file(task_file)
        except tp.TaskError as exc:
            expect(exc.line == int(line.split()[1]) and "flow collection" in str(exc),
                   f"{name}: TaskError must name {line} and the flow collection: {exc!r}")
        else:
            raise AssertionError(f"{name}: an unclosed flow collection must raise TaskError")

    # The nested `{` opener is refused the same way (the check is not specific to `[`).
    braced = write(root, "unclosed-flow-braces.yaml",
                   'title: "Braced"\nrepo_path: .\ndescription: {see the owner\n')
    expect_failure(run("parse", "--task", str(braced)), braced,
                   ("line 3", "unclosed YAML flow collection", "'{'", "quote it"))

    # Contrast: BALANCED flow pairs stay plain text, and a quoted scalar keeps an unclosed opener
    # verbatim (its characters are intended literally).
    good = write(root, "flow-as-text.yaml", FLOW_COLLECTIONS_AS_TEXT_OK)
    res = run("parse", "--task", str(good))
    expect(res.returncode == 0, f"balanced flow brackets as text must parse: {res.returncode} "
                                f"{err(res)!r}")
    expect(res.stderr == b"", f"balanced flow brackets as text must not warn: {err(res)!r}")
    task, _warnings = tp.parse_file(good)
    expect(task["title"] == "See [the notes] and {the glossary} for the wording",
           f"a balanced flow pair must stay plain text: {task['title']!r}")
    expect(task["description"] == "[unterminated is intended text inside a quoted scalar",
           f"a quoted scalar must keep its brackets verbatim: {task['description']!r}")
    expect(task["acceptance_criteria"] == [{"criterion": "The report lists the CNY instrument.",
                                            "verify": "test -f report[1].txt"}],
           f"a balanced verify command must survive: {task['acceptance_criteria']!r}")

    # Contrast (review-2 finding 2): an APOSTROPHE inside a plain scalar is literal text, so a
    # balanced pair after it stays plain text instead of raising a false unclosed-flow error.
    apostrophes = write(root, "apostrophe-plain-scalars.yaml", APOSTROPHE_PLAIN_SCALARS_OK)
    res = run("parse", "--task", str(apostrophes))
    expect(res.returncode == 0, f"apostrophes in plain scalars must parse: {res.returncode} "
                                f"{err(res)!r}")
    expect(res.stderr == b"", f"apostrophes in plain scalars must not warn: {err(res)!r}")
    task, _warnings = tp.parse_file(apostrophes)
    expect(task["title"] == "Ask Bob's team whether [Bob's] notes and {the owner's} rules apply",
           f"an apostrophe inside a plain scalar is literal text: {task['title']!r}")

    # …and the apostrophe never HIDES a really unclosed opener: before the fix the quote state it
    # opened swallowed the `[`, so this malformed value would have entered the run as task data.
    hidden = write(root, "unclosed-flow-after-apostrophe.yaml",
                   "title: Ask the owner's team about [unterminated\nrepo_path: .\n")
    expect_failure(run("parse", "--task", str(hidden)), hidden,
                   ("line 1", "unclosed YAML flow collection", "'['", "quote it"))


def case_11_whitespace_is_not_a_quote_boundary(root: pathlib.Path) -> None:
    """Regression (review-3): a quote after WHITESPACE alone does not open a quoted scalar.

    `_at_scalar_boundary` accepted any preceding space/tab, so the apostrophe of `[Bob 's]` opened a
    quoted region, the closing `]` fell inside it and a valid task file exited 2 with "unclosed YAML
    flow collection". The boundary is now the nearest non-whitespace character — a value start or a
    flow opener/comma/separator — so `[Bob 's]` parses, a genuinely quoted flow element is still
    read as quoted, and a real unclosed opener is still refused.
    """
    spaced = write(root, "quote-after-space.yaml", QUOTE_AFTER_SPACE_OK)
    res = run("parse", "--task", str(spaced))
    expect(res.returncode == 0, f"a quote after a space in plain text must parse: "
                                f"{res.returncode} {err(res)!r}")
    expect(res.stderr == b"", f"a quote after a space must not warn: {err(res)!r}")
    task, _warnings = tp.parse_file(spaced)
    expect(task["title"] == "Ask [Bob 's] team and {the owner 's} rules",
           f"whitespace is not a quote boundary: {task['title']!r}")
    expect(task["description"] == "Roll call for [Bob 's] shift is done",
           f"whitespace is not a quote boundary in a description either: "
           f"{task['description']!r}")

    # Contrast: a quoted element after a flow opener/comma/separator IS a quoted scalar again.
    quoted = write(root, "quoted-flow-elements.yaml", QUOTED_FLOW_ELEMENTS_OK)
    res = run("parse", "--task", str(quoted))
    expect(res.returncode == 0, f"quoted flow elements must parse: {res.returncode} "
                                f"{err(res)!r}")
    task, _warnings = tp.parse_file(quoted)
    expect(task["title"] == "Roll call [Bob, 'Carol'] and {'owner': 'the lead'}",
           f"a quoted flow element must stay plain text of the value: {task['title']!r}")

    # Control: a real unclosed opener is still an error, whatever quoted text precedes it.
    unclosed = write(root, "unclosed-flow-after-quoted-element.yaml",
                     UNCLOSED_FLOW_AFTER_QUOTED_ELEMENT)
    expect_failure(run("parse", "--task", str(unclosed)), unclosed,
                   ("line 1", "unclosed YAML flow collection", "'['", "quote it"))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        case_1_item_without_a_value(root)
        print("PASS 1 - '- criterion:' exits 2 naming line 4, the missing value and both shapes "
              "to write instead")
        case_2_bad_indentation(root)
        print("PASS 2 - a misaligned sibling key exits 2 naming the line, the needed column and "
              "the indentation rule")
        case_3_unknown_task_type(root)
        print("PASS 3 - an unknown task_type exits 2 naming the value and the allowed values")
        case_4_missing_required_title(root)
        print("PASS 4 - a missing required title exits 2 naming the field and the line to add")
        case_5_invalid_boolean_is_a_hard_error(root)
        print("PASS 5 - 'derived: perhaps' exits 2 naming the line and both allowed values "
              "(never a silent false), while true/false in any case are read as booleans")
        case_6_cli_contract(root)
        print("PASS 6 - --help exits 0, wrong/unreadable invocations exit 2, no traceback ever, "
              "and the valid path is silent on stderr")
        case_7_malformed_quoted_scalars_are_rejected(root)
        print("PASS 7 - an unterminated double/single quote and an invalid double-quoted escape "
              "exit 2 naming the line and the fix (never a silent fallback), while well-formed "
              "quotes and escapes still parse")
        case_8_models_block_is_validated(root)
        print("PASS 8 - the models block is validated against the one role registry: an unknown "
              "role key and a list-shaped block exit 2 naming the line, the problem and the fix, "
              "while a supported role->alias mapping still parses")
        case_9_anchors_and_aliases_are_rejected(root)
        print("PASS 9 - an unquoted YAML anchor/alias exits 2 naming the line, the construct and "
              "the fix (never literal text), while quoted anchors/aliases and their characters "
              "inside a block scalar stay verbatim")
        case_10_unclosed_flow_collections_are_rejected(root)
        print("PASS 10 - an unclosed YAML flow collection in title/description/repo_path exits 2 "
              "naming the line, the opener and the fix (never literal task data), while balanced "
              "pairs, quoted values and apostrophes in plain scalars keep their brackets as text "
              "and an apostrophe never hides a really unclosed opener")
        case_11_whitespace_is_not_a_quote_boundary(root)
        print("PASS 11 - a quote after whitespace alone in plain text ([Bob 's]) parses instead of "
              "opening a quoted region, quoted flow elements after an opener/comma/separator are "
              "still delimited, and a real unclosed opener is still refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())

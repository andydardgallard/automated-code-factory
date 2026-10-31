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
     and escapes still parse verbatim.

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
    return 0


if __name__ == "__main__":
    sys.exit(main())

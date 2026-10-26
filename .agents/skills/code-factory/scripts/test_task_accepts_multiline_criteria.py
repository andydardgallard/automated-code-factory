#!/usr/bin/env python3
"""
Deterministic self-test for multi-line `acceptance_criteria` items of `task_parser.py` (stdlib only).

Acceptance criteria are authored in business language, so a criterion is very often more than one
line. The contract under test:

  (a) a criterion written as a block scalar (`- criterion: |` followed by indented lines) parses and
      its text survives VERBATIM — line breaks and the single trailing newline included;
  (b) `verify:` and `derived:` stay SIBLING keys of such a criterion: the block ends where the
      sibling key starts, so a `verify` command never becomes part of the criterion text and never
      swallows the next item;
  (c) a plain multi-word criterion (unquoted, a colon-free sentence) and a bare string item
      (`- "text"`) are the same thing to the consumer: each item carries `criterion`, and the
      optional keys keep their typed values (`verify` a string, `derived` a boolean);
  (d) the mixed shapes of one list keep their ORDER, so a multi-line criterion is followed by its
      own siblings and then by the next item.

Cases (fixtures live in a tempdir; nothing is written into the repository):

  1. a mixed list of criteria parses (exit 0) and every criterion text survives verbatim — the
     block scalar keeps both of its lines, the plain multi-word one is one line, the bare string
     item and the final block scalar are unchanged;
  2. the sibling keys of a block criterion are read as siblings: `verify` is the command (not part
     of the criterion) and the following item is a separate criterion;
  3. the typed values hold: every item carries `criterion`; `derived` is a boolean (false when
     absent) and `verify` is null when absent, so a consumer never sees a missing key;
  4. a `|` criterion as the LAST item of the list and the list as the last field of the file parse
     without swallowing the end of the file, and `parse_file` returns the same document;
  5. a `|-` (stripped) and a `>` (folded) criterion are read as their documented texts;
  6. chomping is honoured for BOTH styles: `|+` and `>+` (keep) preserve every trailing blank line
     of the block verbatim — the old code dropped them, so a keep-form criterion was silently
     shortened — while `|-` strips and plain `|` clips to exactly one trailing newline;
  7. END OF FILE: a keep-chomp block scalar as the LAST thing in the file yields exactly the
     source's real trailing newlines for both `|+` and `>+` — the artificial element `split("\\n")`
     leaves after a terminal newline is not a line of the file, and counting it added a phantom
     blank line (`first\\n` wrongly became `first\\n\\n`);
  8. LEADING blank lines inside a block scalar are content and survive verbatim — in the literal
     and the folded style, under clip and under keep chomping — while the indentation of the block
     is still taken from its first NON-blank line.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
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

BLOCK_ONE = ("The strategy generates at least 5 LONG/SHORT signals for CNY.\n"
             "The same input produces exactly the same signals on a second run.\n")
BLOCK_LAST = ("The manager sees the warehouse balance on the page.\n"
              "The page loads in under 3 seconds on the office network.\n")

FIXTURE = """\
title: "Multi-line acceptance criteria"
repo_path: ./repo
description: |
  The criteria below are the checks the manager performs personally.

acceptance_criteria:
  - criterion: |
      The strategy generates at least 5 LONG/SHORT signals for CNY.
      The same input produces exactly the same signals on a second run.
    verify: "python -m pytest -q tests/test_cny_signals.py"
  - criterion: The report lists the CNY instrument and the Si instrument
    derived: true
  - "Behavior for the Si instrument did not change."
  - criterion: |
      The manager sees the warehouse balance on the page.
      The page loads in under 3 seconds on the office network.
"""

FOLDED = """\
title: "Stripped and folded criteria"
repo_path: .
acceptance_criteria:
  - criterion: |-
      The report is produced without a trailing newline.
    verify: "true"
  - criterion: >
      The report names the CNY instrument
      and the Si instrument.
"""


# Chomping fixtures: the `|+` and the plain `|` bodies end with TWO blank lines, so the keep form
# has to return them and the clip form has to reduce them to exactly one trailing newline.
CHOMP = """\
title: "Chomping of block scalar criteria"
repo_path: .
acceptance_criteria:
  - criterion: |+
      The report is produced.
      The numbers match.


  - criterion: >+
      The report names the CNY instrument.


  - criterion: |-
      The report is produced without a trailing newline.
    verify: "true"
  - criterion: |
      The report is produced.
      The numbers match.


  - criterion: "A plain criterion."
"""


# End-of-file fixtures: the keep-chomp block scalar IS the last thing in the file, so the only
# trailing line break is the one that ends the source line — nothing may be added to it. (The old
# code counted the element `split("\n")` leaves after a terminal newline as a blank line.)
EOF_KEEP = """\
title: "Keep-chomp at the end of the file"
repo_path: .
acceptance_criteria:
  - criterion: |+
      The report is produced.
      The numbers match.
  - criterion: >+
      The report names the CNY instrument.
"""

# Leading blank lines: each body starts with TWO empty lines, which are content in both styles and
# under both the clip (`|`, `>`) and the keep (`|+`, `>+`) chomp indicator.
LEADING_BLANKS = """\
title: "Leading blank lines are content"
repo_path: .
acceptance_criteria:
  - criterion: |


      The report is produced.
      The numbers match.
  - criterion: >


      The report names the CNY instrument.
  - criterion: |+


      The report is produced.
  - criterion: >+


      The report names the CNY instrument.
  - criterion: "A plain criterion."
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


def parse(root: pathlib.Path, name: str, text: str) -> dict:
    """Parse `text` through the CLI and return the normalized document."""
    task_file = write(root, name, text)
    out_file = root / (pathlib.Path(name).stem + ".json")
    res = run("parse", "--task", str(task_file), "--out", str(out_file))
    expect(res.returncode == 0,
           f"{name} must parse (exit 0): {res.returncode} {err(res)!r}")
    expect(res.stderr == b"", f"{name} must not warn: {err(res)!r}")
    expect(out(res).strip().startswith("ok: "),
           f"{name} must print the one-line summary: {out(res)!r}")
    return json.loads(out_file.read_text(encoding="utf-8"))


def case_1_mixed_criteria_parse(root: pathlib.Path) -> None:
    """(a),(c),(d) A mixed list parses and every criterion text survives verbatim, in order."""
    criteria = parse(root, "mixed.yaml", FIXTURE)["acceptance_criteria"]
    expect(len(criteria) == 4, f"all four items must be kept: {criteria!r}")
    expect(criteria[0]["criterion"] == BLOCK_ONE,
           f"the multi-line criterion must survive verbatim: {criteria[0]['criterion']!r}")
    expect(criteria[1]["criterion"] == "The report lists the CNY instrument and the Si instrument",
           f"a plain multi-word criterion is one value: {criteria[1]['criterion']!r}")
    expect(criteria[2]["criterion"] == "Behavior for the Si instrument did not change.",
           f"a bare string item is a criterion: {criteria[2]['criterion']!r}")
    expect(criteria[3]["criterion"] == BLOCK_LAST,
           f"the last block criterion must survive verbatim: {criteria[3]['criterion']!r}")


def case_2_siblings_are_not_swallowed(root: pathlib.Path) -> None:
    """(b) `verify` ends the block and stays a sibling key; the next item stays separate."""
    criteria = json.loads((root / "mixed.json").read_text(encoding="utf-8"))["acceptance_criteria"]
    verify = criteria[0]["verify"]
    expect(verify == "python -m pytest -q tests/test_cny_signals.py",
           f"verify must be the command alone: {verify!r}")
    expect("pytest" not in criteria[0]["criterion"],
           f"the verify command must not leak into the criterion text: {criteria[0]!r}")
    expect("Criterion" not in criteria[1]["criterion"] and criteria[1]["verify"] is None,
           f"the item after the block must not inherit a verify: {criteria[1]!r}")
    expect(criteria[1]["criterion"].startswith("The report lists"),
           f"the second item must be read on its own: {criteria[1]!r}")


def case_3_typed_values(root: pathlib.Path) -> None:
    """(c) Every item carries `criterion`; the optional keys keep their types."""
    criteria = json.loads((root / "mixed.json").read_text(encoding="utf-8"))["acceptance_criteria"]
    for index, item in enumerate(criteria):
        expect(list(item) == ["criterion", "verify", "derived"],
               f"item {index} must carry exactly the documented keys: {item!r}")
        expect(isinstance(item["criterion"], str) and item["criterion"].strip(),
               f"item {index} must carry a non-empty criterion: {item!r}")
        expect(isinstance(item["derived"], bool),
               f"item {index} must carry a boolean derived: {item!r}")
    expect(criteria[1]["derived"] is True, f"derived: true must be kept: {criteria[1]!r}")
    expect(criteria[0]["derived"] is False and criteria[2]["derived"] is False,
           f"an absent derived must be false: {criteria!r}")


def case_4_last_item_and_api(root: pathlib.Path) -> None:
    """(a),(d) A block criterion as the last item is not truncated; the API agrees."""
    task, warnings = tp.parse_file(root / "mixed.yaml")
    expect(warnings == [], f"a valid task yields no warning: {warnings!r}")
    document = json.loads((root / "mixed.json").read_text(encoding="utf-8"))
    expect(tp.normalize(task) == document,
           "the library API and the CLI must produce the same document")
    expect(document["acceptance_criteria"][-1]["criterion"] == BLOCK_LAST,
           f"the last criterion must end at the end of the file intact: "
           f"{document['acceptance_criteria'][-1]!r}")
    expect(not document["acceptance_criteria"][-1]["criterion"].endswith("\n\n"),
           "the last criterion must not gain an extra newline")


def case_5_strip_and_fold(root: pathlib.Path) -> None:
    """(a) `|-` strips the trailing newline; `>` folds the lines into one."""
    criteria = parse(root, "folded.yaml", FOLDED)["acceptance_criteria"]
    expect(criteria[0]["criterion"] == "The report is produced without a trailing newline.",
           f"a '|-' criterion must be stripped of its trailing newline: "
           f"{criteria[0]['criterion']!r}")
    expect(criteria[0]["verify"] == "true", f"the sibling must survive: {criteria[0]!r}")
    expect(criteria[1]["criterion"] == "The report names the CNY instrument and the Si "
                                       "instrument.\n",
           f"a '>' criterion must be folded into one line: {criteria[1]['criterion']!r}")


def case_6_chomping(root: pathlib.Path) -> None:
    """(b) `|+`/`>+` keep every trailing blank line; `|-` strips; `|` clips to exactly one.

    The block bodies below end with TWO blank lines. The keep forms must return them (the line
    break of the last content line plus the two blank lines = three `\\n`), which is exactly what
    the pre-fix code lost when it stripped trailing blank lines before looking at the chomp
    indicator.
    """
    criteria = parse(root, "chomp.yaml", CHOMP)["acceptance_criteria"]
    expect(len(criteria) == 5, f"all five chomping criteria must be kept: {criteria!r}")
    expect(criteria[0]["criterion"] == "The report is produced.\nThe numbers match.\n\n\n",
           f"a '|+' criterion must keep its two trailing blank lines verbatim: "
           f"{criteria[0]['criterion']!r}")
    expect(criteria[1]["criterion"] == "The report names the CNY instrument.\n\n\n",
           f"a '>+' criterion must keep its two trailing blank lines verbatim too: "
           f"{criteria[1]['criterion']!r}")
    expect(criteria[2]["criterion"] == "The report is produced without a trailing newline.",
           f"a '|-' criterion must be stripped: {criteria[2]['criterion']!r}")
    expect(criteria[2]["verify"] == "true",
           f"the sibling key after a stripped block must survive: {criteria[2]!r}")
    expect(criteria[3]["criterion"] == "The report is produced.\nThe numbers match.\n",
           f"a plain '|' criterion must clip to exactly one trailing newline: "
           f"{criteria[3]['criterion']!r}")
    expect(criteria[4]["criterion"] == "A plain criterion.",
           f"the item after the blocks must stay untouched: {criteria[4]['criterion']!r}")


def case_7_eof_keep_chomp(root: pathlib.Path) -> None:
    """(e) A keep-chomp block scalar at EOF adds no phantom blank line.

    The fixture ends immediately after the last content line and its line break. `split("\\n")`
    leaves one empty element there that is NOT a line of the file; counting it as a blank line made
    `first\\n` normalize to `first\\n\\n` for both `|+` and `>+`.
    """
    criteria = parse(root, "eof.yaml", EOF_KEEP)["acceptance_criteria"]
    expect(len(criteria) == 2, f"both EOF criteria must be kept: {criteria!r}")
    expect(criteria[0]["criterion"] == "The report is produced.\nThe numbers match.\n",
           f"a '|+' block ending the file must end with exactly one newline: "
           f"{criteria[0]['criterion']!r}")
    expect(criteria[1]["criterion"] == "The report names the CNY instrument.\n",
           f"a '>+' block ending the file must end with exactly one newline: "
           f"{criteria[1]['criterion']!r}")
    expect(not criteria[0]["criterion"].endswith("\n\n")
           and not criteria[1]["criterion"].endswith("\n\n"),
           f"no EOF criterion may gain a phantom trailing blank line: {criteria!r}")
    # The source really has no blank line at the end — the fixture's last line is content.
    source = (root / "eof.yaml").read_text(encoding="utf-8")
    expect(source.endswith("The report names the CNY instrument.\n"),
           f"the fixture must end on its last content line: {source[-45:]!r}")


def case_8_leading_blank_lines(root: pathlib.Path) -> None:
    """(f) Leading blank lines inside a block scalar are content and survive verbatim.

    Two empty lines start each body. Before the fix they were dropped, so a criterion that opens
    with a blank line silently lost it — in the literal and in the folded style, under clip and
    under keep chomping alike. The block's indentation still comes from its first NON-blank line.
    """
    criteria = parse(root, "leading.yaml", LEADING_BLANKS)["acceptance_criteria"]
    expect(len(criteria) == 5, f"all five criteria must be kept: {criteria!r}")
    expect(criteria[0]["criterion"] == "\n\nThe report is produced.\nThe numbers match.\n",
           f"a '|' criterion must keep its two leading blank lines: "
           f"{criteria[0]['criterion']!r}")
    expect(criteria[1]["criterion"] == "\n\nThe report names the CNY instrument.\n",
           f"a '>' criterion must keep its two leading blank lines: "
           f"{criteria[1]['criterion']!r}")
    expect(criteria[2]["criterion"] == "\n\nThe report is produced.\n",
           f"a '|+' criterion must keep its leading blank lines AND its clip-tail: "
           f"{criteria[2]['criterion']!r}")
    expect(criteria[3]["criterion"] == "\n\nThe report names the CNY instrument.\n",
           f"a '>+' criterion must keep its leading blank lines too: "
           f"{criteria[3]['criterion']!r}")
    expect(criteria[4]["criterion"] == "A plain criterion.",
           f"the item after the blocks must stay untouched: {criteria[4]['criterion']!r}")
    for index, item in enumerate(criteria[:4]):
        expect(item["criterion"][:2] == "\n\n" and item["criterion"][2] != "\n",
               f"item {index} must start with exactly TWO blank lines: "
               f"{item['criterion']!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        case_1_mixed_criteria_parse(root)
        print("PASS 1 - a mixed criteria list parses and every criterion survives verbatim "
              "(block scalar, plain multi-word, bare string, block scalar last)")
        case_2_siblings_are_not_swallowed(root)
        print("PASS 2 - verify/derived are SIBLING keys of a block criterion and never become "
              "part of its text or of the next item")
        case_3_typed_values(root)
        print("PASS 3 - every item carries criterion/verify/derived with the documented types")
        case_4_last_item_and_api(root)
        print("PASS 4 - a block criterion as the last item is intact and parse_file equals the "
              "CLI document")
        case_5_strip_and_fold(root)
        print("PASS 5 - '|-' strips and '>' folds a criterion as documented")
        case_6_chomping(root)
        print("PASS 6 - '|+' and '>+' keep every trailing blank line verbatim, '|-' strips and "
              "plain '|' clips to exactly one trailing newline")
        case_7_eof_keep_chomp(root)
        print("PASS 7 - a keep-chomp block scalar at the END of the file yields exactly the "
              "source's real trailing newlines ('|+' and '>+'), no split-sentinel blank line")
        case_8_leading_blank_lines(root)
        print("PASS 8 - LEADING blank lines inside a block scalar survive verbatim in the literal "
              "and folded style, under clip and keep chomping")
    return 0


if __name__ == "__main__":
    sys.exit(main())

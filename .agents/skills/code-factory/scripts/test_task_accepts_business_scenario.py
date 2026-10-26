#!/usr/bin/env python3
"""
Deterministic self-test for the `business_tests:` block of `task_parser.py` (stdlib only).

A valid task carrying a full `business_tests:` block (scenario / config / expected_results, with
multi-line `|` texts) is exactly the shape the factory rejected as "unreadable" when parsing was
LLM-only. The contract under test:

  (a) such a task parses with exit 0 and a one-line summary on stdout;
  (b) every text of the block survives VERBATIM into the normalized JSON — no re-wrapping, no
      re-quoting, no trimmed line breaks, no comment stripped out of a block body;
  (c) the normalized document always carries every documented field, so a consumer can read
      `business_tests` without checking whether the key exists;
  (d) the library API (`parse_file`) and the CLI agree, and the shipped task template advertises a
      `business_tests:` block that this parser accepts.

Cases (fixtures live in a tempdir; nothing is written into the repository):

  1. a task with a full `business_tests:` block exits 0 with a summary naming the file and both
     scenario counts, and writes the normalized JSON;
  2. every `business_tests:` text survives VERBATIM — the multi-line `|` scenario and
     `expected_results` keep their line breaks and their single trailing newline, the plain
     `expected_results` is unchanged — and the same file with CRLF line endings parses to the SAME
     texts (CRLF is normalized on read, never inside the texts);
  3. the shapes coexist: a plain string item next to a block one, blank lines and full-line
     comments between the items are ignored, and a `#` INSIDE a block body stays part of the text;
  4. the normalized JSON carries every documented field (absent ones empty, never missing), is
     UTF-8, LF-terminated and agrees with `parse_file`;
  5. the shipped `assets/task-template.yaml` advertises a `business_tests:` block and the parser
     accepts it (the template may not drift away from what the parser reads).

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
TEMPLATE = SCRIPTS.parent / "assets" / "task-template.yaml"
# The messages carry non-ASCII characters (em dashes): pin UTF-8 on the child's streams.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

# The scenario texts the assertions compare against — copied from the fixture below on purpose,
# so a parser that "helpfully" re-wraps, folds or strips anything fails here.
SCENARIO_FULL = ("Run the monthly report for January with two warehouses.\n"
                 "Both warehouses carry a positive balance.\n")
EXPECTED_FULL = ("The report lists both warehouses.\n"
                 "The total equals the sum of the two balances.\n")
EXPECTED_HASH = ("The report lists both warehouses.   # this hash is text, not a comment\n"
                 "The total equals the sum of the two balances.\n")

FIXTURE = """\
# A valid business task: the delivery of the monthly report.
title: "Monthly report for the CNY instrument"

repo_path: ./repo

description: |
  The manager needs the monthly report for the CNY instrument.
  Today it is prepared by hand and the numbers differ from the terminal.

business_tests:
  - scenario: |
      Run the monthly report for January with two warehouses.
      Both warehouses carry a positive balance.
    config: "configs/january.toml"
    expected_results: |
      The report lists both warehouses.
      The total equals the sum of the two balances.

  # A second, deliberately simpler scenario — the plain shapes must coexist with the blocks.
  - scenario: "Run the report for a month without trades"
    config: "configs/empty.toml"
    expected_results: "The report is produced with a zero total and no error."

  - scenario: "Prepare the report again from the same input"
    config: "configs/january.toml"
    expected_results: |
      The report lists both warehouses.   # this hash is text, not a comment
      The total equals the sum of the two balances.

acceptance_criteria:
  - "The report lists the CNY instrument."
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


def parse_task(root: pathlib.Path, text: str, stem: str = "task"):
    """Run the CLI on `text` and return (task file, json file, result)."""
    task_file = write(root, f"{stem}.yaml", text)
    out_file = root / f"{stem}.json"
    res = run("parse", "--task", str(task_file), "--out", str(out_file))
    return task_file, out_file, res


def case_1_full_business_tests_block_parses(root: pathlib.Path) -> None:
    """(a) A task with a full `business_tests:` block is parsed, summarized and written."""
    task_file, out_file, res = parse_task(root, FIXTURE, "full")
    expect(res.returncode == 0,
           f"a task with a business_tests block must exit 0: {res.returncode} {err(res)!r}")
    expect(res.stderr == b"", f"a valid task must not warn: {err(res)!r}")
    body = out(res).strip()
    expect(len(body.splitlines()) == 1, f"the summary must be ONE line: {body!r}")
    expect(body.startswith("ok: ") and "full.yaml" in body,
           f"the summary must name the parsed file: {body!r}")
    expect("business_tests=3" in body,
           f"the summary must count the three scenarios: {body!r}")
    expect(out_file.is_file(), "the normalized JSON must be written to --out")
    document = json.loads(out_file.read_text(encoding="utf-8"))
    expect(len(document["business_tests"]) == 3,
           f"all three scenarios must be kept: {document['business_tests']!r}")
    expect(task_file.is_file(), "the fixture must be a real temporary file")


def case_2_texts_survive_verbatim(root: pathlib.Path) -> None:
    """(b) Every business_tests text reaches the JSON byte-for-byte, LF and CRLF alike."""
    _task, out_file, res = parse_task(root, FIXTURE, "verbatim")
    expect(res.returncode == 0, f"the fixture must parse: {err(res)!r}")
    tests = json.loads(out_file.read_text(encoding="utf-8"))["business_tests"]
    expect(tests[0]["scenario"] == SCENARIO_FULL,
           f"the multi-line scenario must survive verbatim: {tests[0]['scenario']!r}")
    expect(tests[0]["config"] == "configs/january.toml",
           f"the plain config must survive verbatim: {tests[0]['config']!r}")
    expect(tests[0]["expected_results"] == EXPECTED_FULL,
           f"the multi-line expected_results must survive verbatim: "
           f"{tests[0]['expected_results']!r}")
    expect(tests[1]["expected_results"] == "The report is produced with a zero total and no "
                                           "error.",
           f"a plain expected_results must stay one line: {tests[1]['expected_results']!r}")
    expect(tests[2]["expected_results"] == EXPECTED_HASH,
           f"a '#' inside a block body is text, not a comment: {tests[2]['expected_results']!r}")
    for test in tests:
        for key, value in test.items():
            if value is not None:
                expect(isinstance(value, str) and "\r" not in value,
                       f"no text may carry a CR: {key}={value!r}")

    # CRLF: normalized on read, so the very same texts come out (nothing inside a text changes).
    crlf = root / "crlf.yaml"
    crlf.write_bytes(FIXTURE.replace("\n", "\r\n").encode("utf-8"))
    crlf_json = root / "crlf.json"
    res = run("parse", "--task", str(crlf), "--out", str(crlf_json))
    expect(res.returncode == 0, f"a CRLF task file must parse: {res.returncode} {err(res)!r}")
    expect(json.loads(crlf_json.read_text(encoding="utf-8"))["business_tests"] == tests,
           "a CRLF task file must yield exactly the same texts")


def case_3_shapes_coexist(root: pathlib.Path) -> None:
    """(c) Comments and blank lines between items are ignored; block and plain items coexist."""
    document = json.loads((root / "verbatim.json").read_text(encoding="utf-8"))
    tests = document["business_tests"]
    expect(tests[1]["scenario"] == "Run the report for a month without trades",
           f"the plain scenario must be read as one value: {tests[1]['scenario']!r}")
    expect(not any("# A second" in (value or "") for test in tests for value in test.values()),
           f"a full-line comment must never enter a value: {tests!r}")
    expect(not any("\n\n" in (value or "") for test in tests for value in test.values()),
           f"a blank line between items must not survive as an empty text line: {tests!r}")
    expect(document["acceptance_criteria"][0]["criterion"] ==
           "The report lists the CNY instrument.",
           f"the criteria after the block must still be read: {document['acceptance_criteria']!r}")


def case_4_normalized_document_shape(root: pathlib.Path) -> None:
    """(c) The JSON is complete, deterministic, UTF-8/LF, and equal to what the API returns."""
    out_file = root / "verbatim.json"
    raw = out_file.read_bytes()
    expect(b"\r" not in raw, "the normalized JSON must use LF newlines")
    expect(raw.endswith(b"\n"), "the normalized JSON must end with a newline")
    document = json.loads(raw.decode("utf-8"))
    expect(list(document) == list(tp.TOP_FIELDS),
           f"the JSON must carry every documented field in order: {list(document)!r}")
    expect(document["title"] == "Monthly report for the CNY instrument",
           f"the title must survive verbatim: {document['title']!r}")
    expect(document["mode"] == "hitl" and document["task_type"] == "implement",
           f"the documented defaults must be filled in: {document!r}")
    expect(document["commit_exclude"] == [] and document["models"] == {}
           and document["reference_docs"] == [] and document["reference_skills"] == [],
           f"absent collections must be empty, never missing: {document!r}")

    task, warnings = tp.parse_file(root / "verbatim.yaml")
    expect(warnings == [], f"a valid task yields no warning: {warnings!r}")
    expect(tp.normalize(task) == document,
           "the library API and the CLI must produce the same document")


def case_5_template_advertises_the_shape() -> None:
    """(d) The shipped template shows a `business_tests:` block the parser accepts."""
    text = TEMPLATE.read_text(encoding="utf-8")
    expect("\nbusiness_tests:\n" in text,
           f"the task template must advertise an ACTIVE business_tests block: {TEMPLATE}")
    expect("expected_results: |" in text,
           f"the template must show a multi-line expected_results: {TEMPLATE}")
    with tempfile.TemporaryDirectory() as tmp:
        res = run("parse", "--task", str(TEMPLATE), "--out", str(pathlib.Path(tmp) / "t.json"))
    expect(res.returncode == 0,
           f"the shipped template must parse cleanly: {res.returncode} {err(res)!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        case_1_full_business_tests_block_parses(root)
        print("PASS 1 - a task with a full business_tests block parses (exit 0), prints one "
              "summary line and writes the normalized JSON")
        case_2_texts_survive_verbatim(root)
        print("PASS 2 - every scenario/config/expected_results text survives VERBATIM (line "
              "breaks and trailing newline kept, CRLF input yielding identical texts)")
        case_3_shapes_coexist(root)
        print("PASS 3 - block and plain items coexist; blank lines and comments are ignored while "
              "a '#' inside a block body stays text")
        case_4_normalized_document_shape(root)
        print("PASS 4 - the normalized document carries every documented field, is LF/UTF-8 and "
              "equals the library API result")
        case_5_template_advertises_the_shape()
        print("PASS 5 - the shipped task template advertises a business_tests block the parser "
              "accepts")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Self-test for the input-validation gate and the prose requirement behind it (zero LLM tokens).

Two halves of one contract are pinned here, and neither is read by any other self-test:

  - `scripts/check_input_validation.py` BITES. The gate is a reviewer/tester advisory over a
    unified diff, so its verdicts are proven on real diffs written to temp files and run through
    the shipped script: a new numeric Rust struct field with no validation is reported as
    `missing-validation` (the farukon `stall_patience` defect), the same field with a fitted check
    passes, a zero default under an only-rejects-zero check is reported as `purpose-blind-check`,
    a new `add_argument("--max-retries", ...)` is caught and its validated form passes, noise
    (comments / ordinary code) stays silent, and a malformed or non-UTF-8 diff can never crash the
    scan. The negative half is asserted, not assumed: every catching case REQUIRES exit 1 and the
    finding kind + input name in the output, so a gate that stopped biting fails this test.

    Four precision rules are pinned by fixtures of their own, because each one used to make the
    scan lie in one direction:
      - a WRAPPED argparse call (`add_argument(` / `"--format",` / `...)`) is read from its
        continuation lines, so the name, its `type=` and a declarative `choices=` are not lost;
      - a `->` return arrow is not a comparison, so a getter does not validate its own field,
        while a purpose-fitted `== 0` rejection IS evidence (the golden purpose-fitted case) AND
        counts as an only-rejects-zero check, so `#[serde(default)]` + `if x == 0 { Err }` is a
        purpose-blind finding while an upper bound that accepts zero is not;
      - an argparse `choices=` on the declaration is declarative validation, so the argument passes
        and the same argument without it does not;
      - a `#[serde(default = "fn")]` names a function the scan cannot evaluate, so it is UNKNOWN
        and never a zero default (the golden missing-validation case defaults to 5 this way), while
        a bare `#[serde(default)]` and a literal `default = "0"` are provable zeros;
      - a validation keyword counts only as a CALL or a statement shape, so a bare assignment
        (`max_retries = args.max_retries`), a name merely containing max/check/range, and a keyword
        that only APPEARS in the line (`print("max", args.max_retries)`) are not evidence, while a
        real `clamp(...)` call over the input is.

    The two shipped golden diffs are replayed as well, and the purpose-fitted one is proven
    NON-VACUOUSLY: `check_golden_purpose_fitted` imports the gate module and asserts that it really
    DETECTS `stall_patience` there with the `== 0` line as its evidence, then mutates that line to
    `== 99` on a throwaway copy and requires the finding to appear — an exit-0-only assertion would
    also be satisfied by a detector that finds nothing at all, which is exactly the defect this
    half exists to rule out.

  - the requirement has CARRIERS in the shipped documents, so a careless edit cannot delete the
    prose while every other self-test stays green: the rulebook's `## input-validation` section and
    its marked canonical block, the reviewer's §3 severity example (a new input path left without
    purpose-fitted validation is severity >= major, a blanket check rejecting a legitimate value is
    the same defect), the plan's `### Input-validation analysis` section, the tester's
    `zero-legitimacy` obligation, and `check_factory_rules.py` accepting the whole registry.

Every prose probe (a)-(d) is one function over the document TEXT, so its NEGATIVE form can run the
SAME probe against a throwaway copy with the needle removed: the probe must then FAIL. Asserting
only that the needle string is gone would prove nothing about the probe; requiring its refusal
proves the probe really reads that text. Positive probes always read the REAL shipped file.

Exit code 0 = every check passed, 1 = the gate or a carrier did not behave as the contract says.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Callable

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPTS = pathlib.Path(__file__).resolve().parent
GATE = SCRIPTS / "check_input_validation.py"
RULES_CHECKER = SCRIPTS / "check_factory_rules.py"

SKILL_DIR = ".agents/skills/code-factory"
RULEBOOK = f"{SKILL_DIR}/references/factory-rules.md"
CODE_REVIEW = f"{SKILL_DIR}/references/code-review.md"
PLANNING_GUIDE = f"{SKILL_DIR}/references/planning-guide.md"
VERIFICATION = f"{SKILL_DIR}/references/verification-strategy.md"
GOLDEN_DIR = "skill-base/golden-set/cases"
GOLDEN_MISSING = f"{GOLDEN_DIR}/missing-input-validation/diff.patch"
GOLDEN_OK = f"{GOLDEN_DIR}/purpose-fitted-validation-ok/diff.patch"

RULE_ID = "input-validation"
BEGIN_MARKER = f"<!-- factory-rule: {RULE_ID} begin -->"
END_MARKER = f"<!-- factory-rule: {RULE_ID} end -->"
SEVERITY_EXAMPLE = "- a NEW input path left without purpose-fitted validation"
INPUT_ANALYSIS_HEADING = "Input-validation analysis"
ZERO_LEGITIMACY = "zero-legitimacy"
SECTION_HEADING_RE = re.compile(r"^#{2,4}\s")


# --------------------------------------------------------------------------------------------
# Fixtures: unified diffs written to temp files and fed to the shipped gate
# --------------------------------------------------------------------------------------------
def rust_diff(added: list[str]) -> str:
    """A diff that adds `added` lines to a serde-configured Rust settings struct.

    The surrounding context carries `struct` and `Deserialize`, so the file qualifies as a
    config-ish Rust file exactly the way `farukon_core/src/settings.rs` does.
    """
    lines = [
        "diff --git a/farukon_core/src/settings.rs b/farukon_core/src/settings.rs",
        "--- a/farukon_core/src/settings.rs",
        "+++ b/farukon_core/src/settings.rs",
        "@@ -12,7 +12,12 @@ use serde::Deserialize;",
        " #[derive(Debug, Clone, Deserialize)]",
        " pub struct Settings {",
        "     pub model: String,",
    ]
    lines += ["+" + line for line in added]
    lines += ["     pub retries: usize,", " }", ""]
    return "\n".join(lines)


def python_diff(added: list[str]) -> str:
    """A diff that adds `added` lines to an argparse builder (`tools/run.py`)."""
    lines = [
        "diff --git a/tools/run.py b/tools/run.py",
        "--- a/tools/run.py",
        "+++ b/tools/run.py",
        "@@ -20,6 +20,10 @@ def build_parser() -> argparse.ArgumentParser:",
        "     parser = argparse.ArgumentParser()",
        '     parser.add_argument("--verbose", action="store_true")',
    ]
    lines += ["+" + line for line in added]
    lines += ["     return parser", ""]
    return "\n".join(lines)


RUST_FIELD = "    pub stall_patience: usize,"
RUST_VALIDATION = [
    "impl Settings {",
    "    fn check_stall_patience(&self) -> Result<(), String> {",
    "        if self.stall_patience > 0 {",
    "            return Ok(());",
    "        }",
    '        Err("stall_patience must be positive".into())',
    "    }",
    "}",
]
# The purpose-fitted shape of the golden `purpose-fitted-validation-ok` case: the rejection is
# `== 0`, and the error line deliberately does NOT name the field, so the `== 0` line is the only
# candidate evidence in the whole diff — the scan can pass only by recognising that comparison.
RUST_ZERO_EQUALITY = [
    "impl Settings {",
    "    fn validate(&self) -> Result<(), String> {",
    "        if self.stall_patience == 0 {",
    '            return Err("must be greater than 0".into());',
    "        }",
    "        Ok(())",
    "    }",
    "}",
]
# A getter that names the field and carries a `->` return arrow: an arrow is not a comparison, so
# this line is NOT validation evidence (the old raw-substring test counted its `>`).
RUST_ARROW_GETTER = [
    "impl Settings {",
    "    pub fn stall_patience(&self) -> usize {",
    "        self.stall_patience",
    "    }",
    "}",
]
# A check that bounds the value from ABOVE only: zero stays legal, so the zero default under it is
# not a contradiction and no purpose-blind finding may be raised.
RUST_UPPER_BOUND = [
    "impl Settings {",
    "    fn check_stall_patience(&self) -> Result<(), String> {",
    "        if self.stall_patience > 100 {",
    '            return Err("stall_patience must stay at or below 100".into());',
    "        }",
    "        Ok(())",
    "    }",
    "}",
]
# The `== 0` line of the shipped purpose-fitted golden diff. It is rewritten to `== 99` to prove
# that the gate's exit 0 there comes FROM that recognition and not from a detector that saw nothing.
GOLDEN_EQUALITY_LINE = "        if self.stall_patience == 0 {"
PY_ARGUMENT = [
    '    parser.add_argument("--max-retries", type=int, default=3,',
    '                        help="how many times to retry")',
]
PY_VALIDATION = [
    "    if args.max_retries < 1 or args.max_retries > 100:",
    '        parser.error("--max-retries must be between 1 and 100")',
]
# A WRAPPED declaration: the paren and the quoted name sit on different added lines.
PY_ARGUMENT_MULTILINE = [
    "    parser.add_argument(",
    '        "--max-retries",',
    "        type=int,",
    "        default=3,",
    "    )",
]
# A wrapped declaration whose only "check" is the parser's own `choices=`: declarative validation.
PY_CHOICES = [
    "    parser.add_argument(",
    '        "--format",',
    '        choices=("text", "json"),',
    '        default="text",',
    "    )",
]
# The same wrapped argument with no constraint at all: the name is still read from line 2, so the
# scan reports it instead of skipping the call.
PY_NO_CHOICES = [
    "    parser.add_argument(",
    '        "--format",',
    '        default="text",',
    "    )",
]
# A plain ASSIGNMENT: it copies the input and names it, but checks nothing. The old prefix match
# read the `max` substring of `max_retries` as a validation keyword and blessed this line.
PY_ASSIGNMENT = [
    "    max_retries = args.max_retries",
]
# A helper NAME merely containing a keyword (`range`, `check`, `max`) is not a check either.
PY_KEYWORD_NAME = [
    "    range_checker = args.max_retries",
    "    print(range_checker)",
]
# A real validation CALL over the input: a validation keyword used as a call, so it stays evidence.
PY_CLAMP = [
    "    max_retries = clamp(args.max_retries, 1, 100)",
]
# A keyword that merely OCCURS in the line — printed, logged, quoted — checks nothing. The token
# alone used to count (review R1, critical 19), which turned any mention of `max` into a green.
PY_PRINTED_KEYWORD = [
    '    print("max", args.max_retries)',
]
PY_LOGGED_STRING = [
    '    log.info("clamped between 1 and 100, checked", args.max_retries)',
]
# A comment that names the input and a keyword is a plan, not a check.
PY_COMMENTED_CHECK = [
    "    # TODO check args.max_retries before use",
]
NOISE_DIFF = "\n".join([
    "diff --git a/farukon_core/src/settings.rs b/farukon_core/src/settings.rs",
    "--- a/farukon_core/src/settings.rs",
    "+++ b/farukon_core/src/settings.rs",
    "@@ -12,6 +12,7 @@ use serde::Deserialize;",
    " pub struct Settings {",
    "     pub model: String,",
    "+    /// How long to wait before retrying; configured elsewhere.",
    "     pub retries: usize,",
    " }",
    "diff --git a/tools/run.py b/tools/run.py",
    "--- a/tools/run.py",
    "+++ b/tools/run.py",
    "@@ -1,3 +1,6 @@",
    " # helpers",
    "+def banner(text: str) -> str:",
    "+    return f'== {text} =='",
    "+",
    "",
])
GARBAGE_DIFF = "\n".join([
    "not a diff at all",
    "+ this is a plus line outside any hunk",
    "- minus",
    "@@ a broken hunk header @@",
    "+++ ",
    "--- ",
    "\\ No newline at end of file",
    "",
])
GARBAGE_BYTES = b"\xff\xfe\x00 not utf-8 \x80\x81\x82 +++ b/x.rs\n+pub a: usize\n"


# --------------------------------------------------------------------------------------------
# Runners
# --------------------------------------------------------------------------------------------
def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the report survives a legacy Windows console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def locate_root(start: pathlib.Path) -> pathlib.Path:
    """The repository root: the directory holding `AGENTS.md` and the code-factory rulebook.

    Derived, not assumed: a layout change must not silently point the probes at `.agents/`.
    """
    for parent in (start, *start.parents):
        if (parent / "AGENTS.md").is_file() and (parent / RULEBOOK).is_file():
            return parent
    return start.parents[3]


ROOT = locate_root(SCRIPTS)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True, errors="replace")


def gate_on(diff: str | bytes) -> subprocess.CompletedProcess[str]:
    """Run the shipped gate on `diff`, written to a throwaway file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "changes.diff"
        if isinstance(diff, bytes):
            path.write_bytes(diff)
        else:
            path.write_text(diff, encoding="utf-8")
        return run("--diff", str(path))


def report(result: subprocess.CompletedProcess[str]) -> str:
    """The gate's stdout+stderr, single-spaced, for an assertion message."""
    return " ".join((result.stdout + result.stderr).split())


def got(result: subprocess.CompletedProcess[str]) -> str:
    """The gate's verdict in one assertion message: its exit code plus its output."""
    return f"exit {result.returncode}: {report(result)}"


def doc(rel: str) -> str:
    path = ROOT / rel
    expect(path.is_file(), f"{rel} is missing — the requirement has no carrier")
    return path.read_text(encoding="utf-8")


def golden(rel: str) -> str:
    """A shipped golden case's diff text (its absence is a failure, never a skip)."""
    path = ROOT / rel
    expect(path.is_file(), f"{rel} is missing — the golden case is part of the shipped set")
    return path.read_text(encoding="utf-8")


def gate_module():
    """The shipped gate imported BY PATH, so a test can assert on its DETECTION, not just its exit.

    Exit 0 alone is satisfiable by a detector that finds nothing (which is exactly how the
    purpose-fitted golden case could pass vacuously), so the check reaches into the module the
    reviewer's advisory is built on.
    """
    expect(GATE.is_file(), f"{GATE.name} is missing — the gate module is the subject of this test")
    spec = importlib.util.spec_from_file_location("check_input_validation_under_test", GATE)
    expect(spec is not None and spec.loader is not None,
           f"{GATE} cannot be imported as a module — its detection cannot be asserted")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module        # dataclasses resolve their class module through it
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise AssertionError(f"{GATE} cannot be imported: {exc}") from exc
    return module


def section_of(text: str, heading_re: str) -> str:
    """The body of the first heading matching `heading_re`, up to the next heading of its level."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(heading_re, line.strip())), None)
    expect(start is not None, f"no heading matching {heading_re!r}")
    body = [lines[start]]
    for line in lines[start + 1:]:
        if SECTION_HEADING_RE.match(line.strip()):
            break
        body.append(line)
    return "\n".join(body)


# --------------------------------------------------------------------------------------------
# 1-6. The gate bites on real diffs
# --------------------------------------------------------------------------------------------
def check_rust_missing_validation() -> str:
    """The farukon defect: a new numeric settings field arrives with no validation at all."""
    result = gate_on(rust_diff([RUST_FIELD]))
    expect(result.returncode == 1,
           f"an unvalidated new field must exit 1: {got(result)}")
    expect("stall_patience" in result.stdout,
           f"the output must name the new input: {report(result)}")
    expect("missing-validation" in result.stdout,
           f"the output must name the finding kind: {report(result)}")
    expect("findings: 1" in result.stdout,
           f"exactly one new input was added and it has no check: {report(result)}")
    return "missing-validation: stall_patience (exit 1)"


def check_rust_validation_ok() -> str:
    """The same field with a fitted range check in the same file's added lines is accepted."""
    result = gate_on(rust_diff([RUST_FIELD] + RUST_VALIDATION))
    expect(result.returncode == 0,
           f"a validated new field must exit 0: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "validated field passes (exit 0, ok)"


def check_rust_purpose_blind() -> str:
    """A bare `#[serde(default)]` (numeric Default is 0) under an only-rejects-zero check."""
    result = gate_on(rust_diff(["    #[serde(default)]", RUST_FIELD] + RUST_VALIDATION))
    expect(result.returncode == 1,
           f"a zero default with an only-rejects-zero check must exit 1: {got(result)}")
    expect("purpose-blind-check" in result.stdout,
           f"the output must name purpose-blind-check: {report(result)}")
    expect("stall_patience" in result.stdout,
           f"the output must name the input: {report(result)}")
    expect("missing-validation" not in result.stdout,
           f"the purpose-blind case has a check, so it is not a missing one: {report(result)}")
    return "purpose-blind-check: stall_patience (exit 1)"


def check_rust_literal_zero_default() -> str:
    """A provable literal zero default (`default = "0"`) is still a zero default."""
    result = gate_on(rust_diff(['    #[serde(default = "0")]', RUST_FIELD] + RUST_VALIDATION))
    expect(result.returncode == 1,
           f"a literal zero default must be read as zero: {got(result)}")
    expect("purpose-blind-check" in result.stdout,
           f"a literal `0` default is a zero default: {report(result)}")
    return "purpose-blind-check: literal 0 default (exit 1)"


def check_rust_custom_default_unknown() -> str:
    """`default = "fn"` names a function: UNKNOWN, never a zero default (the golden 5 case).

    The golden `missing-input-validation` case defaults the new field to 5 through such a function,
    so treating the attribute as a zero default would raise a purpose-blind finding on a diff whose
    real defect is the missing check — a false accusation next to a true one.
    """
    result = gate_on(rust_diff(['    #[serde(default = "default_stall_patience")]', RUST_FIELD]
                               + RUST_VALIDATION))
    expect(result.returncode == 0,
           f"a validated field with a custom default function must exit 0: {got(result)}")
    expect("purpose-blind-check" not in result.stdout,
           f"a named default function is unknown, not zero: {report(result)}")
    return "custom default function is unknown, not zero (exit 0, no findings)"


def check_rust_arrow_is_not_validation() -> str:
    """A `->` return arrow is an operator of the language, not a comparison against a bound."""
    result = gate_on(rust_diff([RUST_FIELD] + RUST_ARROW_GETTER))
    expect(result.returncode == 1,
           f"an arrow is not a validation and the field has no check: {got(result)}")
    expect("missing-validation" in result.stdout,
           f"the getter's `->` must not count as a range check: {report(result)}")
    return "a `->` return arrow is not validation evidence (exit 1)"


def check_rust_zero_equality() -> str:
    """The golden purpose-fitted shape: `== 0` is the only evidence and it must be recognised."""
    result = gate_on(rust_diff([RUST_FIELD] + RUST_ZERO_EQUALITY))
    expect(result.returncode == 0,
           f"an `if field == 0` rejection is purpose-fitted validation: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "`if field == 0` is recognised as the check (exit 0, ok)"


def check_python_missing_validation() -> str:
    """A new CLI argument accepted with no check is a missing validation."""
    result = gate_on(python_diff(PY_ARGUMENT))
    expect(result.returncode == 1,
           f"an unvalidated new argument must exit 1: {got(result)}")
    expect("--max-retries" in result.stdout,
           f"the output must name the argument: {report(result)}")
    expect("missing-validation" in result.stdout,
           f"the output must name the finding kind: {report(result)}")
    return "missing-validation: --max-retries (exit 1)"


def check_python_validation_ok() -> str:
    """The bounded range check on the same argument clears the finding."""
    result = gate_on(python_diff(PY_ARGUMENT + PY_VALIDATION))
    expect(result.returncode == 0,
           f"a bounded new argument must exit 0: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "bounded --max-retries passes (exit 0, ok)"


def check_python_multiline_caught() -> str:
    """A wrapped `add_argument(` call is still an input: its name is on the next added line."""
    result = gate_on(python_diff(PY_ARGUMENT_MULTILINE))
    expect(result.returncode == 1,
           f"a wrapped unvalidated argument must exit 1: {got(result)}")
    expect("--max-retries" in result.stdout,
           f"the name on the continuation line must be read: {report(result)}")
    expect("missing-validation" in result.stdout,
           f"the wrapped call has no check: {report(result)}")
    return "missing-validation: wrapped --max-retries (exit 1)"


def check_python_multiline_ok() -> str:
    """The same wrapped call with a bounded range check passes."""
    result = gate_on(python_diff(PY_ARGUMENT_MULTILINE + PY_VALIDATION))
    expect(result.returncode == 0,
           f"a wrapped, validated argument must exit 0: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "wrapped --max-retries with a range check passes (exit 0, ok)"


def check_python_choices_ok() -> str:
    """`choices=` on the declaration is declarative validation of that argument."""
    result = gate_on(python_diff(PY_CHOICES))
    expect(result.returncode == 0,
           f"an argparse `choices=` is the check for its own argument: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "`choices=` counts as validation (exit 0, ok)"


def check_python_no_choices_caught() -> str:
    """The same wrapped argument without `choices=` has no check and must be reported."""
    result = gate_on(python_diff(PY_NO_CHOICES))
    expect(result.returncode == 1,
           f"an unconstrained --format must exit 1: {got(result)}")
    expect("--format" in result.stdout,
           f"the output must name the argument: {report(result)}")
    expect("missing-validation" in result.stdout,
           f"nothing constrains --format: {report(result)}")
    return "missing-validation: --format without choices (exit 1)"


def check_python_assignment_is_not_validation() -> str:
    """A bare assignment names the input and carries the substring `max` — but checks nothing.

    Regression for the prefix-match defect: `max_retries = args.max_retries` used to count as
    validation evidence, so an unvalidated numeric CLI input got a false green.
    """
    result = gate_on(python_diff(PY_ARGUMENT + PY_ASSIGNMENT))
    expect(result.returncode == 1,
           f"a plain assignment must not validate the argument: {got(result)}")
    expect("missing-validation" in result.stdout and "--max-retries" in result.stdout,
           f"the unvalidated argument must be reported: {report(result)}")
    return "missing-validation: a bare assignment is not a check (exit 1)"


def check_python_keyword_name_is_not_validation() -> str:
    """A name merely CONTAINING a keyword (`range_checker`) is not a validation construct."""
    result = gate_on(python_diff(PY_ARGUMENT + PY_KEYWORD_NAME))
    expect(result.returncode == 1,
           f"a keyword-containing helper name must not validate the argument: {got(result)}")
    expect("missing-validation" in result.stdout,
           f"the unvalidated argument must be reported: {report(result)}")
    return "missing-validation: a name containing `range` is not a check (exit 1)"


def check_python_full_token_call_ok() -> str:
    """A full-token validation call over the input still counts as evidence."""
    result = gate_on(python_diff(PY_ARGUMENT + PY_CLAMP))
    expect(result.returncode == 0,
           f"a real clamp(...) call over the input must exit 0: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "clamp(args.max_retries, 1, 100) passes (exit 0, ok)"


def check_python_mentioned_keyword_is_not_validation() -> str:
    """A keyword that merely APPEARS (printed, logged, commented) is not a check (R1, C19).

    `print("max", args.max_retries)` names the input and contains the token `max` without checking
    anything, so the argument must still be reported. The three shapes cover a quoted keyword, a
    keyword inside a longer message, and a keyword in a comment.
    """
    for label, extra in (("printed keyword", PY_PRINTED_KEYWORD),
                         ("logged message", PY_LOGGED_STRING),
                         ("commented check", PY_COMMENTED_CHECK)):
        result = gate_on(python_diff(PY_ARGUMENT + extra))
        expect(result.returncode == 1,
               f"a keyword that only appears ({label}) must not validate the argument: "
               f"{got(result)}")
        expect("missing-validation" in result.stdout and "--max-retries" in result.stdout,
               f"the unvalidated argument must still be reported ({label}): {report(result)}")
    return "a keyword that only appears (print/log/comment) is not evidence (exit 1)"


def check_noise_ok() -> str:
    """Comments and ordinary code add no input, so the gate stays silent."""
    result = gate_on(NOISE_DIFF)
    expect(result.returncode == 0, f"a diff without a new input must exit 0: {got(result)}")
    expect("ok" in result.stdout, f"the clean run must say ok: {report(result)}")
    return "comments / ordinary code stay silent (exit 0)"


def check_garbage_no_crash() -> str:
    """A hand-edited, truncated or non-UTF-8 diff is never a traceback."""
    for label, payload in (("text", GARBAGE_DIFF), ("non-utf-8 bytes", GARBAGE_BYTES)):
        result = gate_on(payload)
        expect(result.returncode in (0, 1, 2),
               f"garbage diff ({label}) must exit 0/1/2, not {result.returncode}: "
               f"{report(result)}")
        expect("Traceback" not in result.stderr,
               f"garbage diff ({label}) must not crash the scan: {report(result)}")
    return "malformed and non-UTF-8 diffs scan without a traceback"


# --------------------------------------------------------------------------------------------
# 6b. Zero-equality classification and the shipped golden cases
# --------------------------------------------------------------------------------------------
def check_rust_zero_equality_purpose_blind() -> str:
    """`== 0` IS an only-rejects-zero check, so a zero default under it is a contradiction."""
    result = gate_on(rust_diff(["    #[serde(default)]", RUST_FIELD] + RUST_ZERO_EQUALITY))
    expect(result.returncode == 1,
           f"a zero default under an `== 0` rejection must exit 1: {got(result)}")
    expect("purpose-blind-check" in result.stdout,
           f"`if x == 0 {{ Err }}` rejects zero exactly like `> 0` does: {report(result)}")
    expect("stall_patience" in result.stdout,
           f"the output must name the input: {report(result)}")
    expect("missing-validation" not in result.stdout,
           f"the field is checked, so it is not a missing validation: {report(result)}")
    return "purpose-blind-check: zero default + `== 0` rejection (exit 1)"


def check_rust_upper_bound_ok() -> str:
    """An upper bound leaves zero legal, so the zero default is not contradicted."""
    result = gate_on(rust_diff(["    #[serde(default)]", RUST_FIELD] + RUST_UPPER_BOUND))
    expect(result.returncode == 0,
           f"a `> 100` upper bound accepts the zero default: {got(result)}")
    expect("purpose-blind-check" not in result.stdout,
           f"only a check that REJECTS zero contradicts a zero default: {report(result)}")
    return "upper bound accepting zero raises no purpose-blind finding (exit 0)"


def check_golden_missing_case() -> str:
    """The shipped missing case: exactly one finding, and it is the missing check."""
    result = gate_on(golden(GOLDEN_MISSING))
    expect(result.returncode == 1,
           f"the golden missing-validation case must be caught: {got(result)}")
    expect("missing-validation" in result.stdout,
           f"the case's defect is the missing check: {report(result)}")
    expect("stall_patience" in result.stdout,
           f"the finding must name the new input: {report(result)}")
    expect("findings: 1" in result.stdout,
           f"the case carries exactly one new unvalidated input: {report(result)}")
    expect("purpose-blind-check" not in result.stdout,
           f"a named default function is unknown, so no purpose-blind finding: {report(result)}")
    return f"{GOLDEN_MISSING}: one missing-validation finding (exit 1)"


def check_golden_purpose_fitted_case() -> str:
    """The shipped purpose-fitted case passes BECAUSE `== 0` is recognised — proven both ways.

    Exit 0 alone is vacuous: a detector that finds no input at all also exits 0. So the gate module
    is imported and its detection asserted (one `stall_patience`, evidence = the `== 0` line), and
    the line is then rewritten to `== 99` on a throwaway copy — the same diff must then be reported
    as a missing validation, which only happens if the input was seen.
    """
    text = golden(GOLDEN_OK)
    expect(GOLDEN_EQUALITY_LINE in text,
           f"{GOLDEN_OK} no longer carries the `== 0` rejection the case is built on")
    module = gate_module()
    inputs = [(new_input.name, module.validation_evidence(fd, new_input))
              for fd in module.parse_diff(text) for new_input in module.rust_inputs(fd)]
    expect([name for name, _evidence in inputs] == ["stall_patience"],
           f"{GOLDEN_OK} must DETECT exactly the new field (a clean exit proves nothing if the "
           f"scan sees no input at all): detected {inputs!r}")
    evidence = inputs[0][1]
    expect(any(module.ZERO_EQUALITY.search(line) for line in evidence),
           f"the `== 0` line must be the evidence that clears the field: {evidence!r}")

    result = gate_on(text)
    expect(result.returncode == 0,
           f"the golden purpose-fitted case must exit 0: {got(result)}")
    mutated = text.replace(GOLDEN_EQUALITY_LINE, GOLDEN_EQUALITY_LINE.replace("== 0", "== 99"))
    expect(mutated != text, f"{GOLDEN_OK}: the `== 0` line could not be mutated")
    after = gate_on(mutated)
    expect(after.returncode == 1 and "missing-validation" in after.stdout,
           f"without its `== 0` line the same field must be reported — the golden exit 0 is the "
           f"recognition, not a blind detector: {got(after)}")
    return (f"{GOLDEN_OK}: detected, `== 0` is the evidence (exit 0); `== 99` -> "
            "missing-validation (exit 1)")


# --------------------------------------------------------------------------------------------
# 7. The CLI contract
# --------------------------------------------------------------------------------------------
def check_help() -> str:
    result = run("--help")
    expect(result.returncode == 0, f"--help must exit 0: {got(result)}")
    expect("usage" in result.stdout.lower(), f"--help must print the usage: {report(result)}")
    expect("input" in result.stdout.lower(),
           f"--help must describe the scan it performs: {report(result)}")
    return "--help exits 0 with usage"


def check_usage_error() -> str:
    result = run("--no-such-flag")
    expect(result.returncode == 2,
           f"an unknown flag must exit 2 (argparse), not {result.returncode}: {report(result)}")
    expect("Traceback" not in result.stderr,
           f"a usage error must not be a traceback: {report(result)}")
    return "unknown flag exits 2 without a traceback"


# --------------------------------------------------------------------------------------------
# 8. The prose carriers of the requirement: one probe function per document, so the negative half
#    can run the SAME probe against a mutated copy and require its refusal.
# --------------------------------------------------------------------------------------------
def probe_rulebook(text: str) -> str:
    """(a) the rulebook is the single home of the rule and its canonical marked block."""
    expect(f"## {RULE_ID}" in text,
           f"{RULEBOOK} must declare the rule heading `## {RULE_ID}`")
    expect(BEGIN_MARKER in text, f"{RULEBOOK} must carry `{BEGIN_MARKER}`")
    expect(END_MARKER in text, f"{RULEBOOK} must carry `{END_MARKER}`")
    expect("purpose-fitted" in text,
           f"{RULEBOOK} must state the purpose-fitted decision, not the word 'validation' alone")
    return f"{RULEBOOK}: `## {RULE_ID}` + marked canonical block"


def probe_code_review(text: str) -> str:
    """(b) the reviewer's §3 classes a new unvalidated input path as severity >= major."""
    section = section_of(text, r"^#{2,3}\s*3\.\s*Severity")
    expect(SEVERITY_EXAMPLE in section,
           f"{CODE_REVIEW} §3 must carry the example `{SEVERITY_EXAMPLE}`")
    example = next(line for line in section.splitlines() if SEVERITY_EXAMPLE in line)
    expect("severity" in example.lower() and "major" in example.lower(),
           f"the §3 example must fix the severity at >= major: {example!r}")
    expect(ZERO_LEGITIMACY in example,
           f"the §3 example must send the value's zero-legitimacy with the finding: {example!r}")
    expect("check_input_validation.py" in text,
           f"{CODE_REVIEW} must name the deterministic helper the reviewer relies on")
    return f"{CODE_REVIEW} §3: severity >= major for a new unvalidated input path"


def probe_planning_guide(text: str) -> str:
    """(c) the plan states the validation decision for every new or changed input."""
    expect(INPUT_ANALYSIS_HEADING in text,
           f"{PLANNING_GUIDE} must carry the `{INPUT_ANALYSIS_HEADING}` section")
    section = section_of(text, rf"^#{{2,4}}\s*{re.escape(INPUT_ANALYSIS_HEADING)}\s*$")
    for needle in (ZERO_LEGITIMACY, "overflow"):
        expect(needle in section,
               f"the `{INPUT_ANALYSIS_HEADING}` section must decide the input's {needle!r}")
    expect("unjustified" in section or "why no validation is needed" in section,
           f"the `{INPUT_ANALYSIS_HEADING}` section must demand a reason, not a bare field: "
           f"{section[:300]!r}")
    return f"{PLANNING_GUIDE}: `{INPUT_ANALYSIS_HEADING}` (range / zero-legitimacy / overflow)"


def probe_verification(text: str) -> str:
    """(d) the tester must prove zero-legitimacy and overflow at the edges."""
    expect(ZERO_LEGITIMACY in text,
           f"{VERIFICATION} must require the input's {ZERO_LEGITIMACY!r} to be proven")
    expect("overflow" in text.lower(),
           f"{VERIFICATION} must require the overflow behaviour to be proven")
    return f"{VERIFICATION}: {ZERO_LEGITIMACY} + overflow proven at the edges"


def rejected_by(rel: str, needle: str, probe: Callable[[str], str]) -> str:
    """The negative half of a prose probe: the SAME probe must REFUSE a copy without the needle.

    Deleting the needle and asserting it is gone proves nothing about the probe — a probe that
    matches some other text would still pass. So the probe function itself is run against the
    mutated document and its AssertionError is required. The mutated copy is a throwaway file; the
    real document is never written.
    """
    text = doc(rel)
    expect(needle in text, f"{rel} does not contain {needle!r} — the probe would be vacuous")
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp) / pathlib.Path(rel).name
        copy.write_text(text.replace(needle, ""), encoding="utf-8")
        mutated = copy.read_text(encoding="utf-8")
    expect(mutated != text, f"{rel}: removing {needle!r} changed nothing")
    try:
        probe(mutated)
    except AssertionError as exc:
        return (f"the probe refuses a copy without {needle!r}: "
                f"{' '.join(str(exc).split())[:80]}")
    raise AssertionError(f"{rel}: the probe still passes on a copy with {needle!r} removed — it "
                         "does not read that text, so its positive half is vacuous")


def check_rulebook_rule() -> str:
    return probe_rulebook(doc(RULEBOOK))


def check_rulebook_rule_unproven() -> str:
    """(a) negative half: the marker probe really reads the marker."""
    return rejected_by(RULEBOOK, BEGIN_MARKER, probe_rulebook)


def check_code_review_severity() -> str:
    return probe_code_review(doc(CODE_REVIEW))


def check_code_review_severity_unproven() -> str:
    """(b) negative half: the §3 example probe really reads that example line."""
    return rejected_by(CODE_REVIEW, SEVERITY_EXAMPLE, probe_code_review)


def check_planning_guide() -> str:
    return probe_planning_guide(doc(PLANNING_GUIDE))


def check_planning_guide_unproven() -> str:
    """(c) negative half: the heading probe really reads the heading it names."""
    return rejected_by(PLANNING_GUIDE, INPUT_ANALYSIS_HEADING, probe_planning_guide)


def check_verification_zero_legitimacy() -> str:
    return probe_verification(doc(VERIFICATION))


def check_verification_zero_legitimacy_unproven() -> str:
    """(d) negative half: the zero-legitimacy probe really reads that word."""
    return rejected_by(VERIFICATION, ZERO_LEGITIMACY, probe_verification)


def check_factory_rules() -> str:
    """(e) the rulebook's registry (which carries this rule) still validates as a whole."""
    result = subprocess.run([sys.executable, str(RULES_CHECKER)],
                            capture_output=True, text=True, errors="replace")
    expect(result.returncode == 0,
           f"check_factory_rules.py must exit 0: {report(result)}")
    expect("PASS" in result.stdout,
           f"check_factory_rules.py must report PASS: {report(result)}")
    return "check_factory_rules.py PASS (exit 0)"


# --------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------
CHECKS = (
    ("1. a new Rust config field with no validation is caught", check_rust_missing_validation),
    ("2. the same field with a fitted check passes", check_rust_validation_ok),
    ("3. a bare serde zero default under an only-rejects-zero check is purpose-blind",
     check_rust_purpose_blind),
    ("4. a literal `0` default is a zero default too", check_rust_literal_zero_default),
    ("5. a named serde default function is unknown, not zero", check_rust_custom_default_unknown),
    ("6. a `->` return arrow is not a range check", check_rust_arrow_is_not_validation),
    ("7. `if field == 0` is a purpose-fitted check", check_rust_zero_equality),
    ("8. a zero default under an `== 0` rejection is purpose-blind",
     check_rust_zero_equality_purpose_blind),
    ("9. an upper bound that accepts zero is not purpose-blind", check_rust_upper_bound_ok),
    ("10a. a new CLI argument with no validation is caught", check_python_missing_validation),
    ("10b. the same argument with a bounded range check passes", check_python_validation_ok),
    ("11a. a wrapped add_argument call is still an input", check_python_multiline_caught),
    ("11b. the wrapped call with a range check passes", check_python_multiline_ok),
    ("12a. argparse `choices=` is declarative validation", check_python_choices_ok),
    ("12b. the same argument without `choices=` is caught", check_python_no_choices_caught),
    ("12c. a bare assignment is not validation", check_python_assignment_is_not_validation),
    ("12d. a keyword-containing name is not validation",
     check_python_keyword_name_is_not_validation),
    ("12e. a full-token validation call still counts", check_python_full_token_call_ok),
    ("12f. a keyword that only appears (print/log/comment) is not evidence",
     check_python_mentioned_keyword_is_not_validation),
    ("13. comments and ordinary code stay silent", check_noise_ok),
    ("14. a malformed or non-UTF-8 diff never crashes", check_garbage_no_crash),
    ("15. --help exits 0", check_help),
    ("16. a usage error exits 2 without a traceback", check_usage_error),
    ("17. the golden missing case yields one missing-validation finding and no purpose-blind one",
     check_golden_missing_case),
    ("18. the golden purpose-fitted case is DETECTED and clears on `== 0`",
     check_golden_purpose_fitted_case),
    ("19a. the rulebook declares the rule and its marked block", check_rulebook_rule),
    ("19a'. the marker probe refuses a copy without the marker",
     check_rulebook_rule_unproven),
    ("19b. the reviewer's §3 fixes severity >= major", check_code_review_severity),
    ("19b'. the §3 example probe refuses a copy without it",
     check_code_review_severity_unproven),
    ("19c. the plan carries the Input-validation analysis section", check_planning_guide),
    ("19c'. the plan heading probe refuses a copy without it", check_planning_guide_unproven),
    ("19d. the tester must prove zero-legitimacy", check_verification_zero_legitimacy),
    ("19d'. the zero-legitimacy probe refuses a copy without it",
     check_verification_zero_legitimacy_unproven),
    ("19e. the rulebook registry validates as a whole", check_factory_rules),
)


def main() -> int:
    use_utf8_output()
    print(f"input-validation gate under {ROOT}")
    failures: list[str] = []
    for title, check in CHECKS:
        try:
            detail = check()
        except AssertionError as exc:
            failures.append(f"{title}: {exc}")
            print(f"FAIL - {title}: {exc}", file=sys.stderr)
            continue
        print(f"ok   - {title}" + (f" -> {detail}" if detail else ""))

    if failures:
        print(f"FAIL - {len(failures)} of {len(CHECKS)} check(s) failed", file=sys.stderr)
        return 1

    print(f"PASS - {len(CHECKS)} checks: check_input_validation.py catches a new unvalidated Rust "
          "field and CLI argument (wrapped calls included), accepts their fitted checks — a "
          "comparison, a `== 0` rejection, an argparse `choices=`, a full-token validation call "
          "(never a bare assignment or a keyword-containing name) — flags the purpose-blind zero "
          "default while treating a named serde default function as unknown and an upper bound "
          "that accepts zero as no contradiction, stays silent on noise and survives garbage "
          "input — and both shipped golden cases are replayed NON-VACUOUSLY: the missing one "
          "yields exactly one missing-validation finding, the purpose-fitted one is DETECTED with "
          "its `== 0` line as evidence and turns into a finding once that line says `== 99`. The "
          "requirement itself still has its carriers: the rulebook rule and marked block, the "
          "reviewer's §3 severity example, the plan's validation analysis and the tester's "
          "zero-legitimacy obligation, with every prose probe proven by REFUSING a copy with its "
          "needle removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

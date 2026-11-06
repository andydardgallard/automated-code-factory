#!/usr/bin/env python3
"""
Advisory scan of a unified diff for NEWLY ADDED external inputs that arrive with no validation
(stdlib only, line-oriented, deterministic, zero LLM tokens).

The defect class this tool looks for: a new optional numeric config field added with a bare type
and no range / zero / overflow check, or a new CLI argument accepted without any check — the
"the caller can now pass 0 and nobody notices" case a reviewer tends to skip when the diff reads
cleanly. It is a reviewer/tester advisory: it never gates a target project's CI and it reports a
heuristic, not a proof.

Detection (v1 scope):
  1. Rust config-ish struct fields — a file whose path ends in `.rs` AND whose added or context
     lines mention `struct` AND (`serde` / `Deserialize` / `config` / `settings`, or the path
     carries `config` / `settings`). Inside such a file every ADDED line that declares a public
     field (`pub <name>: <type>`, optional `(crate)` qualifier) with a NUMERIC-ish type is a new
     input: `usize`, `u8`..`u128`, `i8`..`i128`, `isize`, `f32`, `f64`, `NonZero*` and
     `Option<...>` of any of those.
  2. Python CLI inputs — every ADDED line that opens `add_argument(` or `click.option(`
     (`@click.option(` included); the input name is the first quoted argument of the call, read on
     the opening line or, when the call is wrapped, on the first of its contiguous continuation
     lines. A call whose name still cannot be read is skipped. The scan is line-oriented, so the
     TEXT of such a call inside a string literal — a self-test's own fixture — is indistinguishable
     from a real declaration and is reported like one; that is a false positive, and the advisory
     deliberately errs in that direction.

A detected input is VALIDATED when the same file's added lines — the declaring lines themselves are
excluded, so a `max_*` field or a `--max-retries` flag cannot validate itself — carry its name AND
one validation SHAPE: a comparison OPERATOR (`<`, `<=`, `>`, `>=`; a `->` return arrow or a
`=>` match arm is not a comparison), a zero comparison (`== 0`, `!= 0`), a validation CALL
(`clamp(`, `validate(`, `check(`, `.max(`, `NonZeroU32::new(`, `checked_add(`, `try_from(`, ...) or
an `assert` statement. String and char literals are ignored, so a keyword that only OCCURS in the
line — `print("max", args.max_retries)`, a log message, a dict key — is NOT evidence, and neither
is a bare assignment such as `max_retries = args.max_retries` or a helper name merely containing
max/check/range. An argparse `choices=` is the one exception to the exclusion: it is declarative
validation written on the argument it constrains. A `NonZero*` FIELD TYPE is itself the check and
validates the field without any extra line. Anything else is a `missing-validation` finding
(severity major).

Purpose-blind check: when a NUMERIC input's ONLY validation is a rejection of zero (`> 0`,
`>= 1`, `== 0`, `NonZero`, `min=1`) while the same diff PROVABLY defaults that input to zero
(`default=0`, `default = 0`, a bare `#[serde(default)]` — the numeric `Default` impl is 0 — or a
`#[serde(default = "0")]` literal), a second `purpose-blind-check` finding (severity major) says
the blanket check contradicts the input's own default. A named default function
(`#[serde(default = "default_stall_patience")]`) is UNKNOWN, never zero: the scan cannot see what it
returns, so it is no evidence of a zero default. A bare `!= 0` is evidence of a check but is NOT
classified as zero-rejecting — the comparison alone does not say which side the rejection is on.

Output: one line per finding `path: kind: name — message`, then `findings: N`; with
`--format json` a JSON array of {file, line_name, kind, severity, message}. No findings prints
`ok: no unvalidated new inputs` (text) or `[]` (json) and exits 0.

Usage:
  python check_input_validation.py --diff changes.diff
  python check_input_validation.py --base origin/main [--repo /path/to/repo]
  git diff main...HEAD | python check_input_validation.py

`--diff` reads a unified diff file; `--base COMMIT` asks git for `<repo> diff <base>...HEAD`
(`--repo` defaults to "."); with neither, the diff is read from stdin. The diff is decoded as
UTF-8 with replacement and CRLF-normalized, and any line outside a recognized diff construct is
treated as context, so a malformed or hand-edited diff can never crash the scan.

Exit codes: 0 — no findings, 1 — at least one finding, 2 — argument error (argparse) or the
diff could not be produced (unreadable `--diff` file, failing `git diff`).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field

# Numeric-ish Rust types: the family that carries range / zero / overflow semantics.
NUMERIC_TYPES = frozenset({
    "usize", "u8", "u16", "u32", "u64", "u128",
    "isize", "i8", "i16", "i32", "i64", "i128",
    "f32", "f64",
})

# A comparison OPERATOR, matched as an operator and never as a raw substring: `-> usize` is a return
# arrow, `=>` a match arm and `<<` / `>>` a shift or a generic close, so none of them may count as
# validation evidence (`x>=1` without spaces still counts).
COMPARISON = re.compile(r"(?<![-=<>])(?:>=|<=|>(?![>=])|<(?![<=]))")
# A comparison against zero is the purpose-fitted rejection `if x == 0 { return Err(...) }` — the
# shape the golden purpose-fitted case uses, which a bare operator test cannot see.
ZERO_EQUALITY = re.compile(r"[=!]=\s*0(?:\.0)?(?![\w.])")
# A validation CALL: the keyword must be USED as a call (`clamp(`, `max(`, `.validate(`, ...), or
# be one of the two prefix families that are calls by construction — Rust's checked arithmetic
# (`checked_add(`) and the `NonZero<Ux/Ix>` constructors (`NonZeroU32::new(`). A keyword that merely
# OCCURS in the line — a string literal (`print("max", args.max_retries)`), a log message, a dict
# key — is not a check: the token alone never validates anything.
VALIDATION_CALL = re.compile(
    r"(?:^|[^\w])(?:clamp|validate|validator|check|ensure|nonzero\w*|checked_\w+|try_from|range|min"
    r"|max)\s*\(", re.IGNORECASE)
# The `NonZero<Ux/Ix>` type constructors are associated calls: `NonZeroU32::new(`, `NonZero::new(`.
NONZERO_CONSTRUCTOR = re.compile(r"(?:^|[^\w])nonzero\w*\s*::\s*\w+\s*\(", re.IGNORECASE)
# `assert` is a STATEMENT, not a call: `assert args.n > 0` (the comparison is seen separately) and
# `assert_positive(...)` / `assert args.n, "reason"` are still validation statements.
VALIDATION_ASSERT = re.compile(r"(?:^|[^\w])assert(?:_\w+)?\b", re.IGNORECASE)
# A string literal or a char literal, stripped before any keyword matching: text INSIDE a literal
# is data, never a check (`print("clamp the value", args.x)` checks nothing).
LITERAL = re.compile(r"""[rbfu]{0,2}(?:'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'(?:\\.|[^'\\\n])*'"""
                     r"""|\"(?:\\.|[^\"\\\n])*\")""")
# Declarative validation written on the declaration itself: argparse's `choices=(...)`.
DECLARATIVE_VALIDATION = re.compile(r"\bchoices\s*=")
# The narrower subset that only rejects zero — the shape the purpose-blind check looks for. `== 0`
# rejects zero exactly like `> 0` does, so it belongs here as well; a bare `!= 0` does not, because
# the comparison alone does not say which side of it the rejection sits on (it is still evidence).
ZERO_REJECT = re.compile(r"(?<![-=])>\s*0(?![\d.])|>=\s*1(?![\d.])|==\s*0(?![\d.])|nonzero|"
                         r"min(?:_value)?\s*=\s*1(?![\d.])|range\s*\(\s*1\s*,", re.IGNORECASE)
ZERO_DEFAULT = re.compile(r"default\s*=\s*(?:Some\(\s*)?(?:[\"']0[\"']|0(?:\.0)?)(?![\d.])")
# A `#[...]` attribute that mentions a default, and the same attribute with a PROVABLY zero value:
# `default = "fn_name"` names a function the scan cannot evaluate, so it is unknown, not zero.
SERDE_DEFAULT = re.compile(r"\bdefault\b", re.IGNORECASE)
SERDE_DEFAULT_VALUE = re.compile(r"\bdefault\s*=\s*[\"']?0(?:\.0)?[\"']?(?![\w.])", re.IGNORECASE)
SERDE_DEFAULT_ASSIGN = re.compile(r"\bdefault\s*=", re.IGNORECASE)

CONFIG_PATH = re.compile(r"config|settings", re.IGNORECASE)
CONFIG_HINTS = ("serde", "deserialize", "config", "settings")
RUST_FIELD = re.compile(r"^\s*pub(?:\s*\([^)]*\))?\s+([A-Za-z_]\w*)\s*:\s*(.+?),?\s*$")
PY_MARKER = re.compile(r"add_argument\s*\(|click\.option\s*\(")
PY_ARG_NAME = re.compile(r"^\s*[\"']([^\"']+)[\"']")
# The only numeric signal a Python argument line carries: an explicit `type=int|float`.
NUMERIC_PY_TYPE = re.compile(r"type\s*=\s*(?:int|float)\b")
HUNK_NEW_START = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class AddedLine:
    """One ADDED line of a diff, with its line number in the NEW file and its position in the
    file's added list (`index`, used to exclude a declaration from its own validation evidence)."""
    lineno: int
    text: str
    index: int


@dataclass
class FileDiff:
    """The added lines and the context lines of one file of a unified diff."""
    path: str
    added: list[AddedLine] = field(default_factory=list)
    context: list[str] = field(default_factory=list)


@dataclass
class NewInput:
    """A newly added external input and the evidence collected for it.

    `index`..`last_index` are the added lines the declaration occupies (an argparse call may be
    wrapped over several lines) and `text` is that whole declaration, so a name, a `type=` hint or a
    `choices=` on a continuation line is seen by the scan. `attrs_before` is the contiguous
    `#[...]` block added right above a Rust field.
    """
    file: str
    name: str
    forms: tuple[str, ...]
    kind: str                       # "field" (Rust) or "argument" (Python)
    lineno: int
    index: int                      # first added line of the declaration
    last_index: int                 # last added line of the declaration
    text: str                       # the declaration, its continuation lines included
    numeric: bool = False
    attrs_before: tuple[str, ...] = ()
    type_validated: bool = False    # a `NonZero*` type is itself the check


def path_of(header: str) -> str:
    """File path of a `+++ b/path` / `--- a/path` header; "" for /dev/null or an unreadable one."""
    token = header.split("\t")[0].strip()
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        token = token[1:-1]
    if token in ("", "/dev/null"):
        return ""
    for prefix in ("b/", "a/"):
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


def parse_diff(text: str) -> list[FileDiff]:
    """Parse a unified diff into per-file added/context lines.

    Line-oriented by design: `diff --git`, `--- `, `+++ ` and `@@` are recognized as structure,
    `+` / `-` / ` ` inside a hunk as added / removed / context, and every other line (a
    hand-edited or truncated diff) is kept as context instead of raising.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    in_hunk = False
    new_lineno = 0
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith("diff --git "):
            current, in_hunk = None, False
            continue
        if raw.startswith("+++ "):
            path = path_of(raw[4:])
            current = FileDiff(path=path)
            files.append(current)
            in_hunk = False
            continue
        if raw.startswith("--- "):
            in_hunk = False
            continue
        if raw.startswith("@@"):
            match = HUNK_NEW_START.match(raw)
            new_lineno = int(match.group(1)) if match else 0
            in_hunk = current is not None and current.path != ""
            continue
        if not in_hunk or current is None:
            continue
        if raw.startswith("+"):
            current.added.append(AddedLine(new_lineno, raw[1:], len(current.added)))
            new_lineno += 1
        elif raw.startswith(" "):
            current.context.append(raw[1:])
            new_lineno += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue                      # removed line or "\ No newline at end of file"
        else:
            current.context.append(raw)   # unparseable inside a hunk: treat as context
            new_lineno += 1
    return files


def is_numeric_type(rust_type: str) -> bool:
    """True for a numeric primitive, a `NonZero*`, or an `Option<...>` of either."""
    declared = rust_type.split("//")[0].strip()
    if declared.startswith("Option<") and declared.endswith(">"):
        return is_numeric_type(declared[len("Option<"):-1])
    base = declared.split("::")[-1].strip()
    return base in NUMERIC_TYPES or base.startswith("NonZero")


def is_nonzero_type(rust_type: str) -> bool:
    """True when the type itself rejects zero (`NonZeroU32`, `Option<NonZeroU8>`, ...)."""
    declared = rust_type.split("//")[0].strip()
    if declared.startswith("Option<") and declared.endswith(">"):
        return is_nonzero_type(declared[len("Option<"):-1])
    return declared.split("::")[-1].strip().startswith("NonZero")


def is_config_file(fd: FileDiff) -> bool:
    """A `.rs` file that declares a struct and looks config-ish (serde / Deserialize / path)."""
    if not fd.path.endswith(".rs"):
        return False
    texts = [line.text for line in fd.added] + fd.context
    if not any("struct" in text for text in texts):
        return False
    hinted = any(hint in text.lower() for text in texts for hint in CONFIG_HINTS)
    return hinted or bool(CONFIG_PATH.search(fd.path))


def argument_forms(name: str) -> tuple[str, ...]:
    """Search forms of an input name: `--max-retries` is written `max_retries` in the code."""
    bare = name.lstrip("-")
    forms = {name, bare, bare.replace("-", "_"), bare.replace("_", "-")}
    return tuple(sorted(form for form in forms if form))


def mentions(text: str, forms: tuple[str, ...]) -> bool:
    """True when `text` mentions one of the forms as a whole token (not inside a longer word)."""
    return any(re.search(rf"(?<![\w-]){re.escape(form)}(?![\w-])", text) for form in forms)


def is_validation(text: str) -> bool:
    """True when `text` carries a validation SHAPE, never merely a keyword.

    Three shapes count: a comparison operator (`>`, `<=`, ...), a zero comparison (`== 0`), and a
    validation CALL (`clamp(` / `max(` / `.validate(` / `NonZeroU32::new(` / an `assert`
    statement). String and char literals are stripped first, so `print("max", args.max_retries)` —
    a keyword that only APPEARS in the line — is not evidence, and neither is a bare assignment
    (`max_retries = args.max_retries`) or a name merely containing max/check/range.
    """
    code = LITERAL.sub('""', text)
    return bool(COMPARISON.search(code) or ZERO_EQUALITY.search(code)
                or VALIDATION_CALL.search(code) or NONZERO_CONSTRUCTOR.search(code)
                or VALIDATION_ASSERT.search(code))


def attrs_above(fd: FileDiff, index: int) -> tuple[str, ...]:
    """The contiguous `#[...]` attribute lines added immediately above added line `index`."""
    attrs: list[str] = []
    above = index - 1
    while above >= 0 and fd.added[above].text.strip().startswith("#["):
        attrs.append(fd.added[above].text.strip())
        above -= 1
    return tuple(reversed(attrs))


def attr_defaults_zero(attr: str) -> bool:
    """True when ONE `#[...]` attribute line provably defaults a numeric field to zero.

    A bare `#[serde(default)]` falls back to the type's `Default` impl, which is 0 for a numeric
    field. `default = "<name>"` names a FUNCTION whose return value the scan cannot see, so it is
    unknown — the golden `missing-input-validation` case defaults its field to 5 through such a
    function. Only a literal `0` / `0.0` value is provably zero.
    """
    if not SERDE_DEFAULT.search(attr):
        return False
    if SERDE_DEFAULT_VALUE.search(attr):
        return True
    return SERDE_DEFAULT_ASSIGN.search(attr) is None


def rust_inputs(fd: FileDiff) -> list[NewInput]:
    """New numeric public fields of a config-ish Rust file."""
    if not is_config_file(fd):
        return []
    inputs: list[NewInput] = []
    for line in fd.added:
        match = RUST_FIELD.match(line.text)
        if not match:
            continue
        name, declared = match.group(1), match.group(2)
        if not is_numeric_type(declared):
            continue
        inputs.append(NewInput(file=fd.path, name=name, forms=argument_forms(name),
                               kind="field", lineno=line.lineno, index=line.index,
                               last_index=line.index, text=line.text, numeric=True,
                               attrs_before=attrs_above(fd, line.index),
                               type_validated=is_nonzero_type(declared)))
    return inputs


def python_call(fd: FileDiff, at: int, rest: str) -> tuple[str, int]:
    """The whole text of the call opened by added line `at`, and its last added line index.

    A declaration may be wrapped (`add_argument(` / `    "--format",` / `    choices=(...)`), so the
    name and the `type=` / `default=` / `choices=` hints are read from every line of the call. The
    call ends at its balanced closing paren; a call that never closes stops at the last line of the
    same added block — contiguous NEW-file line numbers, so a following hunk is never swallowed.
    """
    parts = [rest.strip()]
    depth = 1 + rest.count("(") - rest.count(")")
    last = at
    while depth > 0 and last + 1 < len(fd.added) \
            and fd.added[last + 1].lineno == fd.added[last].lineno + 1:
        last += 1
        text = fd.added[last].text
        parts.append(text.strip())
        depth += text.count("(") - text.count(")")
    return " ".join(part for part in parts if part), last


def python_inputs(fd: FileDiff) -> list[NewInput]:
    """New `add_argument(` / `click.option(` inputs; a call whose name cannot be read is skipped."""
    inputs: list[NewInput] = []
    for line in fd.added:
        marker = PY_MARKER.search(line.text)
        if not marker:
            continue
        text, last = python_call(fd, line.index, line.text[marker.end():])
        name_match = PY_ARG_NAME.match(text)
        if not name_match:
            continue
        name = name_match.group(1)
        inputs.append(NewInput(file=fd.path, name=name, forms=argument_forms(name),
                               kind="argument", lineno=line.lineno, index=line.index,
                               last_index=last, text=text))
    return inputs


def declaration_of(fd: FileDiff, new_input: NewInput) -> list[str]:
    """The texts that ARE the declaration: its own lines, or the same plus related added lines.

    A wrapped argparse call carries its `type=` / `default=` / `choices=` on lines that may not name
    the argument, so those lines belong to the declaration as well.
    """
    return [new_input.text] + [line.text for line in fd.added
                               if new_input.index <= line.index <= new_input.last_index
                               or mentions(line.text, new_input.forms)]


def python_numeric(fd: FileDiff, new_input: NewInput) -> bool:
    """A Python input counts as numeric when its own declaration or a related added line declares a
    numeric `type=` or a numeric `default=` — the only numeric signal a line-oriented scan sees."""
    return any(NUMERIC_PY_TYPE.search(text) or ZERO_DEFAULT.search(text)
               for text in declaration_of(fd, new_input))


def validation_evidence(fd: FileDiff, new_input: NewInput) -> list[str]:
    """Validation evidence for one input: added lines naming it, plus its own declarative check.

    The declaring lines themselves are excluded: `pub max_retries: usize` and
    `add_argument("--max-retries", type=int)` both contain their own name plus keyword-ish
    fragments, so counting them would mark every input validated. An argparse `choices=` is the
    exception — it is the check, written where the argument is declared.
    """
    evidence: list[str] = []
    if new_input.kind == "argument" and DECLARATIVE_VALIDATION.search(new_input.text):
        evidence.append(new_input.text)
    for line in fd.added:
        if new_input.index <= line.index <= new_input.last_index:
            continue
        if not mentions(line.text, new_input.forms) or not is_validation(line.text):
            continue
        evidence.append(line.text)
    return evidence


def has_zero_default(fd: FileDiff, new_input: NewInput) -> bool:
    """True when the diff PROVABLY defaults this input to zero: `default=0`, a bare
    `#[serde(default)]` above a numeric field (its `Default` is 0), or a `default = "0"` literal."""
    if any(attr_defaults_zero(attr) for attr in new_input.attrs_before):
        return True
    return any(ZERO_DEFAULT.search(text) for text in declaration_of(fd, new_input))


def scan(text: str) -> list[dict[str, object]]:
    """All findings of a diff: one per unvalidated new input, plus the purpose-blind findings."""
    findings: list[dict[str, object]] = []
    for fd in parse_diff(text):
        inputs = rust_inputs(fd) + python_inputs(fd)
        inputs.sort(key=lambda item: (item.lineno, item.index))
        for new_input in inputs:
            if new_input.kind == "argument":
                new_input.numeric = python_numeric(fd, new_input)
            evidence = validation_evidence(fd, new_input)
            if not evidence and new_input.type_validated:
                evidence = ["NonZero"]      # the type is the check; no separate line exists
            base = {"file": new_input.file, "line_name": new_input.name, "severity": "major"}
            if not evidence:
                findings.append({**base, "kind": "missing-validation",
                                 "message": (f"new {new_input.kind} '{new_input.name}' has no "
                                             "accompanying validation (range/zero/overflow "
                                             "check) in the same file's added lines")})
                continue
            zero_only = all(ZERO_REJECT.search(line) for line in evidence)
            if zero_only and new_input.numeric and has_zero_default(fd, new_input):
                findings.append({**base, "kind": "purpose-blind-check",
                                 "message": (f"the only check on '{new_input.name}' rejects zero "
                                             "while the same diff defaults it to 0 — the check "
                                             "contradicts the input's own default")})
    return findings


def read_diff(args: argparse.Namespace) -> str:
    """The diff text from --diff, from `git diff <base>...HEAD`, or from stdin.

    Raises ValueError with a human-readable cause when the requested source cannot be produced:
    scanning an empty diff would report a false "ok".
    """
    if args.diff:
        try:
            data = pathlib.Path(args.diff).read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read --diff file {args.diff}: {exc}") from exc
        return data.decode("utf-8", errors="replace")
    if args.base:
        command = ["git", "-C", args.repo, "diff", f"{args.base}...HEAD"]
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except OSError as exc:
            raise ValueError(f"cannot run git: {exc}") from exc
        if result.returncode != 0:
            detail = " ".join(result.stderr.decode("utf-8", errors="replace").split())
            raise ValueError(f"git diff {args.base}...HEAD failed: "
                             f"{detail[:200] or 'no detail'}")
        return result.stdout.decode("utf-8", errors="replace")
    return sys.stdin.read()


def render(findings: list[dict[str, object]], fmt: str) -> None:
    """Print the findings in the requested shape plus the summary line."""
    if fmt == "json":
        print(json.dumps(findings, indent=2, ensure_ascii=False))
        return
    if not findings:
        print("ok: no unvalidated new inputs")
        return
    for finding in findings:
        print(f"{finding['file']}: {finding['kind']}: {finding['line_name']} — "
              f"{finding['message']}")
    print(f"findings: {len(findings)}")


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the em dash survive a legacy console.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text and every
    finding line carry a non-ASCII character (`—`), which that codec cannot encode:
    `print_help()` would raise UnicodeEncodeError instead of showing the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def build_parser() -> argparse.ArgumentParser:
    """The CLI: diff source, repo anchor, output format, and the documented scope in the epilog."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="detection v1: added numeric Rust config struct fields (pub <name>: <type> in a "
               "struct+serde/config file) and added Python CLI arguments (add_argument( / "
               "click.option( ), wrapped calls included) with no accompanying validation in the "
               "same file — an argparse `choices=` counts as validation; plus purpose-blind-check "
               "when a provable zero default meets an only-rejects-zero check.")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--diff", metavar="PATH", help="unified diff file to scan")
    source.add_argument("--base", metavar="COMMIT",
                        help="scan `git -C <repo> diff <base>...HEAD` instead of a file")
    ap.add_argument("--repo", metavar="PATH", default=".",
                    help="repository of --base (default: the current directory)")
    ap.add_argument("--format", choices=("text", "json"), default="text",
                    help="text: one line per finding + `findings: N`; json: array (default: text)")
    return ap


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        text = read_diff(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = scan(text)
    render(findings, args.format)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

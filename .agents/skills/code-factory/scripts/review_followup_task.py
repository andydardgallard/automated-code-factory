#!/usr/bin/env python3
"""
Deterministic generator of the follow-up task of a report-only review run (zero LLM tokens).

A `task_type: review` / `security_audit` run never edits the project: it delivers its merged
findings as a report plus ONE task file the owner runs when they choose (the rulebook rule
`review-report-only`). This script writes that task file. It is deterministic — the same merged
findings and the same argv produce a byte-identical file — so the hand-over cannot be softened,
reordered or silently extended in prose.

Input — the merged findings JSON of `merge_findings.py --report`
(`.code-factory/logs/code-review-merged.json`):

  {"verdict": "approve | request_changes",
   "counts": {"critical": 2, "major": 11, "minor": 7, "nit": 0},
   "findings": [{"severity": "critical | major | minor | nit", "file": "<path>",
                 "line": <int|null>, "title": "...", "detail": "...",
                 "occurrences": ["<shard id>", ...]}],
   "shards": [...]}

A BARE JSON LIST of findings is accepted too (then the generated file carries no review verdict).
`counts`/`shards`/`total_*` of the input are ignored and recomputed from `findings`, so a stale
summary in the report can never reach the generated task.

Output — ONE flat task in the factory task format (`assets/task-template.yaml`), ready to run:

  title                 derived from the review verdict and the recomputed finding counts
  repo_path             the `--repo` value, verbatim
  description           the findings grouped by severity with `file:line` and the detail, plus the
                        statement that the file comes from a report-only run the owner runs later
  mode: hitl            the owner decides when it runs
  task_type: implement   a review hands the fix over as a separate implement run
  acceptance_criteria   one criterion per finding (`derived: true` unless the finding carries a
                        `verify` command, or its location is checkable: a module whose sibling
                        self-test exists derives `python <sibling test>`), then a final
                        MACHINE-VERIFIABLE criterion that re-runs every such command (or, when no
                        finding is checkable, the tree-soundness gate), and the "the change is
                        reviewed" criterion (derived: a code review is not machine-checkable)
  commit_exclude        the factory's standard exclusion list
  leading comments      the source run_id and the reproducing command line

Verified acceptance: the gate `verify_acceptance.py` accepts a run only when at least ONE criterion
carries a `verify` command — a task whose criteria are all `derived` is doomed to DEGRADED, i.e.
handed over but never acceptably finishable. The generator therefore never emits such a criterion
list: every checkable finding contributes its command and the final criterion re-runs them, so the
generated task can be finished to SUCCESS. The fallback (`DEFAULT_FINAL_VERIFY`) is a real check of
the tree (`python -m compileall -q .`), not a placeholder: it always executes and never lies about
proving the findings closed.

Quoting: NO scalar is ever interpolated into `key: value` — every scalar is emitted as a YAML
double-quoted string (backslash and `"` escaped, newlines as `\\n`) or, for the description, as a
`|-` block scalar. A finding containing `: `, `"`, `#` or a newline therefore cannot corrupt the
file, which is exactly what a naive `f"{key}: {value}"` emitter does. `parse_task()` is the
matching reader for the emitted YAML subset and is what `--check` validates with.

CLI:
  review_followup_task.py --findings <json> --repo <path> --out <yaml>
                          [--run-id <id>] [--title "..."] [--verdict-ok approve]
  review_followup_task.py --check --out <yaml>

  `--verdict-ok` lists (comma-separated) the verdicts that mean "the review accepted the tree"
  (default `approve`). A report whose verdict is accepted AND that carries no findings has
  nothing to hand over: no file is written and the script reports it (exit 0). Every other report
  — any findings, or a non-accepted verdict — produces the task.

Exit codes:
  0 — the task was written (`wrote <out> (<n> findings)`), or the accepted report had nothing to
      hand over, or `--check` found a valid file;
  1 — an input file cannot be READ (`--findings` when generating, `--out` with `--check`) or the
      `--check` target does not have the shape of a generated task file;
  2 — invalid input: broken JSON, a finding outside the contract, an unwritable `--out`, or a
      missing `--findings` (usage error).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import textwrap

SEVERITIES = ("critical", "major", "minor", "nit")
TASK_TYPES = ("implement", "review", "refactor", "security_audit")
MODES = ("hitl", "auto")
GENERATED_TASK_TYPE = "implement"
GENERATED_MODE = "hitl"
# The task file is read by a human: wrap long finding details instead of one endless line.
WRAP_WIDTH = 84
DETAIL_INDENT = "      "
# The full detail belongs to the description; a criterion stays readable and is capped.
CRITERION_DETAIL_MAX = 400
DEFAULT_VERDICT_OK = "approve"
GENERATOR_PATH = ".agents/skills/code-factory/scripts/review_followup_task.py"
GENERATOR_COMMAND = "python " + GENERATOR_PATH
# Every key the generated file always carries; `--check` fails when one of them is missing.
REQUIRED_TASK_KEYS = ("title", "repo_path", "description", "mode", "task_type",
                      "acceptance_criteria", "commit_exclude")
# The factory's standard commit_exclude list: files a run may create or modify but must never
# commit (task files, credentials, machine-local configuration, browser profiles, artifacts).
STANDARD_COMMIT_EXCLUDE = (
    "task.yaml",
    "task_*.yaml",
    "task-*.yaml",
    ".kimi-code/local.toml",
    "**/.env*",
    "**/*credentials*",
    "**/*.secret.json",
    "**/*.pem",
    "**/*.key",
    "**/*.whl",
    "**/chrome-profile*/**",
    "**/*.heapsnapshot",
)
FINAL_CRITERION = ("The change is reviewed: the factory code reviewer inspects the fix and every "
                   "finding above is either fixed or dispositioned with a reason before the task "
                   "is accepted.")
# The verified-acceptance gate needs at least one criterion with a `verify` command, so the task
# always ends with a REAL one: the per-finding checks re-run on the fixed tree.
FINAL_VERIFY_CRITERION = ("The findings are closed and stay closed: the {count} verification "
                          "command(s) this task carries are re-run on the fixed tree and each of "
                          "them exits 0.")
# Last resort when no finding names a checkable location: prove the tree is still sound. It is a
# modest gate, but a real one — it executes everywhere and never makes the task unfinishable.
FINAL_VERIFY_CRITERION_DEFAULT = ("The fix leaves the tree sound: every Python file of the "
                                  "repository still compiles (no fix leaves a broken file "
                                  "behind).")
DEFAULT_FINAL_VERIFY = "python -m compileall -q ."
# Separator of the chained per-finding commands; `&&` works in cmd.exe and /bin/sh alike.
CHAIN_SEPARATOR = " && "

# YAML subset emitted by this script and read back by parse_task(): a flat top-level mapping of
# `key: value` scalars, `key:` + `- item` lists, mapping items inside a list, and `|`/`|-` blocks.
KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>.*)$")
ITEM_LINE = re.compile(r"^(?P<indent>[ ]*)-[ ]+(?P<rest>.*)$")
BLOCK_MARKERS = ("|", "|-", "|+", ">", ">-", ">+")
ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}


class CliError(Exception):
    """A terminated run: the message is printed as `error: ...` and `code` becomes the exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------------------------
# Emitting: every scalar goes through yaml_quote (or the block scalar), never through f-strings.
# --------------------------------------------------------------------------------------------

def yaml_quote(text: str) -> str:
    """Double-quoted YAML scalar: safe for `:`, `"`, `#`, backslashes and newlines."""
    out = []
    for char in text:
        if char in ('\\', '"'):
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def block_scalar(text: str) -> list[str]:
    """The lines of a literal `|-` block scalar body (indented, no trailing whitespace)."""
    lines = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        lines.append(("  " + stripped) if stripped else "")
    return lines


def format_counts(counts: dict) -> str:
    """One deterministic counts string in severity order."""
    return ", ".join(f"{severity}: {counts[severity]}" for severity in SEVERITIES)


def location(finding: dict) -> str:
    """`file:line`, or the bare file when the finding carries no line."""
    return finding["file"] if finding["line"] is None else f"{finding['file']}:{finding['line']}"


def flatten(text: str, limit: int = 0) -> str:
    """One line out of arbitrary text, optionally capped with an explicit marker."""
    flat = " ".join(text.split())
    if limit and len(flat) > limit:
        flat = flat[:limit].rstrip() + " [...]"
    return flat


def wrapped(text: str, indent: str = DETAIL_INDENT, width: int = WRAP_WIDTH) -> list[str]:
    """Wrap a finding detail into literal block-scalar lines (never empty, never blank-only)."""
    flat = " ".join(text.split())
    if not flat:
        return []
    return [indent + line for line in textwrap.wrap(flat, width=max(20, width - len(indent)),
                                                   break_long_words=False,
                                                   break_on_hyphens=False)]


def criterion_text(finding: dict) -> str:
    """The criterion of one finding: severity, `file:line`, title and the (capped) detail."""
    head = f"[{finding['severity']}] {location(finding)} — {flatten(finding['title'])}"
    detail = flatten(finding["detail"], CRITERION_DETAIL_MAX)
    return head if not detail else f"{head}: {detail}"


def counts_of(findings: list[dict]) -> dict:
    """Recompute the per-severity counts from the findings themselves."""
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding["severity"]] += 1
    return counts


def grouped(findings: list[dict]) -> list[tuple[str, list[dict]]]:
    """(severity, findings) in severity order; the input order is preserved inside a group."""
    return [(severity, [f for f in findings if f["severity"] == severity])
            for severity in SEVERITIES]


def derive_title(verdict: str, findings: list[dict], counts: dict, run_id: str) -> str:
    """Title: the review's verdict plus the recomputed finding counts, nothing else."""
    source = f"review run {run_id}" if run_id else "the report-only review"
    verdict_part = f"[{verdict}] " if verdict else ""
    return (f"Review follow-up {verdict_part}— close {len(findings)} finding(s) "
            f"({format_counts(counts)}) handed over by {source}")


def render_description(verdict: str, findings: list[dict], counts: dict, run_id: str,
                       command: str) -> str:
    """The owner-facing description: what was found, where, and that nothing was applied."""
    lines = [
        "Follow-up to a report-only review run: the findings below are handed over as a task.",
        "",
        "This file was generated from a REPORT-ONLY review run — the review changed nothing in the",
        "tree, and none of the findings below has been applied. Run this task when you choose to;",
        "the review run itself never edits the project.",
        "",
        f"- review verdict: {verdict or 'not reported (bare findings list)'}",
        f"- findings: {len(findings)} ({format_counts(counts)})",
    ]
    if run_id:
        lines.append(f"- source run_id: {run_id}")
    lines.append(f"- generated by: {command}")
    for severity, group in grouped(findings):
        if not group:
            continue
        lines += ["", f"## {severity} ({len(group)})", ""]
        for index, finding in enumerate(group, start=1):
            lines.append(f"{index}. {location(finding)} — {flatten(finding['title'])}")
            detail = finding["detail"].strip()
            if detail:
                lines.append("   detail:")
                lines += wrapped(detail)
    return "\n".join(lines)


def shell_token(token: str) -> str:
    """Quote one argv token for the reproducing command in the leading comment."""
    if token and not re.search(r"[\s\"']", token):
        return token
    return '"' + token.replace("\\", "\\\\").replace('"', '\\"') + '"'


def command_line(args: argparse.Namespace) -> str:
    """The generating command, rebuilt from the argv in a fixed order (deterministic)."""
    parts = GENERATOR_COMMAND.split(" ") + ["--findings", args.findings or "", "--repo",
                                             args.repo, "--out", args.out]
    if args.run_id:
        parts += ["--run-id", args.run_id]
    if args.title:
        parts += ["--title", args.title]
    if args.verdict_ok != DEFAULT_VERDICT_OK:
        parts += ["--verdict-ok", args.verdict_ok]
    return " ".join(shell_token(" ".join(part.split())) for part in parts)


def render_task(title: str, repo_path: str, description: str, criteria: list[dict],
                run_id: str, command: str) -> str:
    """The whole task file: leading comments, the flat task mapping, quoted scalars only."""
    lines = [
        "# Generated by review_followup_task.py — do NOT edit by hand: regenerate it from the",
        "# merged findings instead. The owner runs this task when they choose; the review run",
        "# that produced the findings edited nothing.",
        f"# source run_id: {run_id or '(not given)'}",
        f"# command: {command}",
        "",
        f"title: {yaml_quote(title)}",
        f"repo_path: {yaml_quote(repo_path)}",
        "",
        "description: |-",
        *block_scalar(description),
        "",
        f"mode: {yaml_quote(GENERATED_MODE)}",
        f"task_type: {yaml_quote(GENERATED_TASK_TYPE)}",
        "",
        "acceptance_criteria:",
    ]
    for item in criteria:
        lines.append(f"  - criterion: {yaml_quote(item['criterion'])}")
        if item.get("verify"):
            lines.append(f"    verify: {yaml_quote(item['verify'])}")
        else:
            lines.append("    derived: true")
    lines += ["", "commit_exclude:"]
    lines += [f"  - {yaml_quote(pattern)}" for pattern in STANDARD_COMMIT_EXCLUDE]
    return "\n".join(lines) + "\n"


def sibling_test(file: str) -> str:
    """`x/check.py` -> `x/test_check.py`; "" when the path is not a checkable Python module."""
    parts = [part for part in file.replace("\\", "/").split("/") if part]
    name = parts[-1] if parts else ""
    if not name.endswith(".py") or name.startswith("test_") or ".." in parts:
        return ""
    parts[-1] = "test_" + name
    return "/".join(parts)


def derived_verify(finding: dict, repo: pathlib.Path) -> str:
    """A verify command derived from the finding's location: run the module's sibling self-test.

    A finding usually points at a module (`.../action_gate.py`) and the factory keeps its
    deterministic self-tests beside it (`test_action_gate.py`), so re-running that test is a real
    proof that the finding is closed. No sibling test, no command: a fabricated check would be a
    claim, not evidence.
    """
    candidate = sibling_test(finding["file"])
    if not candidate:
        return ""
    try:
        if (repo / candidate).is_file():
            return f"python {candidate}"
    except OSError:      # an unreadable path is simply not checkable
        pass
    return ""


def build_criteria(findings: list[dict], repo: pathlib.Path = pathlib.Path(".")) -> list[dict]:
    """One criterion per finding + a final VERIFIED one + the (derived) review criterion.

    A finding carries its own `verify` command, or derives one from its location (see
    `derived_verify`). The final criterion re-runs every such command, so the generated task always
    has at least one criterion the verified-acceptance gate can actually execute.
    """
    criteria: list[dict] = []
    verifies: list[str] = []
    for finding in findings:
        verify = finding["verify"] or derived_verify(finding, repo)
        if verify and verify not in verifies:
            verifies.append(verify)
        criteria.append({"criterion": criterion_text(finding), "verify": verify,
                         "derived": not verify})
    if verifies:
        criteria.append({"criterion": FINAL_VERIFY_CRITERION.format(count=len(verifies)),
                         "verify": CHAIN_SEPARATOR.join(verifies)})
    else:
        criteria.append({"criterion": FINAL_VERIFY_CRITERION_DEFAULT,
                         "verify": DEFAULT_FINAL_VERIFY})
    criteria.append({"criterion": FINAL_CRITERION, "verify": "", "derived": True})
    return criteria


# --------------------------------------------------------------------------------------------
# Reading: the matching parser for the emitted YAML subset (used by `--check`).
# --------------------------------------------------------------------------------------------

def parse_scalar(token: str, lineno: int):
    """Decode one scalar token: a quoted string (with escapes), a bool, or plain text."""
    if token.startswith('"'):
        out = []
        index = 1
        while index < len(token):
            char = token[index]
            if char == "\\":
                escape = token[index + 1:index + 2]
                if escape not in ESCAPES:
                    raise ValueError(f"line {lineno}: unknown escape \\{escape} in a quoted "
                                     f"scalar")
                out.append(ESCAPES[escape])
                index += 2
                continue
            if char == '"':
                if token[index + 1:].strip():
                    raise ValueError(f"line {lineno}: text after the closing quote of a scalar")
                return "".join(out)
            out.append(char)
            index += 1
        raise ValueError(f"line {lineno}: unterminated quoted scalar")
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1].replace("''", "'")
    if token in ("true", "false"):  # a PLAIN bool only; a quoted "true" stays a string
        return token == "true"
    return token


def _skip_blank(lines: list[str], index: int) -> int:
    while index < len(lines) and (not lines[index].strip()
                                 or lines[index].lstrip().startswith("#")):
        index += 1
    return index


def read_block(lines: list[str], index: int, marker: str) -> tuple[str, int]:
    """Read a `|`/`>` block scalar body starting at `index`; return (value, next index)."""
    start = _skip_blank(lines, index)
    indent = None
    body: list[str] = []
    cursor = start
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip():
            body.append("")
            cursor += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current == 0:
            break
        if indent is None:
            indent = current
        if current < indent:
            break
        body.append(line[indent:])
        cursor += 1
    while body and not body[-1]:
        body.pop()
        cursor -= 1  # trailing blank lines belong to the next construct
    value = "\n".join(body)
    if marker.startswith("|+") or marker.startswith(">+"):
        value += "\n"
    elif marker in ("|", ">"):
        value += "\n"
    return value, cursor


def read_list(lines: list[str], index: int, key: str) -> tuple[list, int]:
    """Read a `- item` list (scalars or flat mappings) starting at `index`."""
    start = _skip_blank(lines, index)
    if start >= len(lines) or not ITEM_LINE.match(lines[start]):
        return [], index  # `key:` with no items: an empty list, nothing consumed
    indent = len(ITEM_LINE.match(lines[start]).group("indent"))
    items: list = []
    cursor = start
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() or line.lstrip().startswith("#"):
            cursor += 1
            continue
        match = ITEM_LINE.match(line)
        if not match or len(match.group("indent")) != indent:
            break
        rest = match.group("rest").strip()
        lineno = cursor + 1
        cursor += 1
        field = KEY_LINE.match(rest)
        if not field:  # a plain scalar item
            items.append(parse_scalar(rest, lineno))
            continue
        item: dict = {}
        value = field.group("rest").strip()
        item[field.group("key")] = parse_scalar(value, lineno) if value else ""
        while cursor < len(lines):
            nested = lines[cursor]
            if not nested.strip() or nested.lstrip().startswith("#"):
                cursor += 1
                continue
            if ITEM_LINE.match(nested):
                break
            nested_indent = len(nested) - len(nested.lstrip(" "))
            if nested_indent <= indent:
                break
            nested_field = KEY_LINE.match(nested.strip())
            if not nested_field:
                raise ValueError(f"line {cursor + 1}: expected 'key: value' inside a list item, "
                                 f"got {nested.strip()!r}")
            nested_value = nested_field.group("rest").strip()
            item[nested_field.group("key")] = (parse_scalar(nested_value, cursor + 1)
                                               if nested_value else "")
            cursor += 1
        items.append(item)
    return items, cursor


def parse_task(text: str) -> dict:
    """Parse the flat task mapping this script emits; raise ValueError on anything else."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    task: dict = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        lineno = index + 1
        index += 1
        if not stripped or stripped.startswith("#"):
            continue
        if raw[0] == " ":
            raise ValueError(f"line {lineno}: unexpected indentation at the top level")
        match = KEY_LINE.match(raw)
        if not match:
            raise ValueError(f"line {lineno}: not a 'key: value' line: {stripped!r}")
        if match.group("key") in task:
            raise ValueError(f"line {lineno}: duplicate key {match.group('key')!r}")
        rest = match.group("rest").strip()
        if rest in BLOCK_MARKERS:
            task[match.group("key")], index = read_block(lines, index, rest)
        elif rest:
            task[match.group("key")] = parse_scalar(rest, lineno)
        else:
            task[match.group("key")], index = read_list(lines, index, match.group("key"))
    return task


def check_task(text: str) -> list[str]:
    """Shape problems of a generated task file (empty list = valid)."""
    try:
        task = parse_task(text)
    except ValueError as exc:
        return [f"not a parsable generated task file: {exc}"]
    problems = [f"missing required key '{key}'" for key in REQUIRED_TASK_KEYS if not task.get(key)]
    if task.get("task_type") and task["task_type"] not in TASK_TYPES:
        problems.append(f"task_type {task['task_type']!r} is not one of {list(TASK_TYPES)}")
    if task.get("mode") and task["mode"] not in MODES:
        problems.append(f"mode {task['mode']!r} is not one of {list(MODES)}")
    criteria = task.get("acceptance_criteria")
    if criteria and not isinstance(criteria, list):
        problems.append("acceptance_criteria must be a list of criteria")
    for position, item in enumerate(criteria or [], start=1):
        if not isinstance(item, dict) or not str(item.get("criterion", "")).strip():
            problems.append(f"acceptance_criteria[{position - 1}] needs a non-empty 'criterion'")
    if criteria and not any(isinstance(item, dict) and str(item.get("verify", "")).strip()
                            for item in criteria):
        problems.append("acceptance_criteria carries no verify command: the verified-acceptance "
                        "gate (verify_acceptance.py) can only report DEGRADED for this task")
    exclude = task.get("commit_exclude")
    if exclude and (not isinstance(exclude, list)
                    or not all(isinstance(pattern, str) and pattern for pattern in exclude)):
        problems.append("commit_exclude must be a list of non-empty patterns")
    return problems


# --------------------------------------------------------------------------------------------
# Input contract of the merged findings report.
# --------------------------------------------------------------------------------------------

def normalize_finding(raw: object, index: int, label: str) -> dict:
    """One validated finding; raise CliError naming the file and the offending record."""
    where = f"{label}: findings[{index}]"
    if not isinstance(raw, dict):
        raise CliError(f"{where} must be a JSON object, got {type(raw).__name__}", 2)
    severity = raw.get("severity")
    if severity not in SEVERITIES:
        raise CliError(f"{where}.severity must be one of {list(SEVERITIES)}, got {severity!r}", 2)
    file = raw.get("file")
    if not isinstance(file, str) or not file.strip():
        raise CliError(f"{where}.file must be a non-empty string, got {file!r}", 2)
    line = raw.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
        raise CliError(f"{where}.line must be an integer or null, got {line!r}", 2)
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CliError(f"{where}.title must be a non-empty string, got {title!r}", 2)
    detail = raw.get("detail", "")
    if not isinstance(detail, str):
        raise CliError(f"{where}.detail must be a string, got {type(detail).__name__}", 2)
    verify = raw.get("verify", "")
    if not isinstance(verify, str):
        raise CliError(f"{where}.verify must be a string, got {type(verify).__name__}", 2)
    return {"severity": severity, "file": file.strip(), "line": line, "title": title.strip(),
            "detail": detail, "verify": verify.strip()}


def load_findings(path: pathlib.Path) -> tuple[str, list[dict]]:
    """Read the merged report; return (verdict, findings). Exit codes: 1 unreadable, 2 invalid."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError(f"cannot read --findings {path}: {exc}", 1) from None
    label = str(path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"{label}: invalid JSON at line {exc.lineno} column {exc.colno}: "
                       f"{exc.msg}", 2) from None
    if isinstance(payload, list):
        verdict, raw_findings = "", payload
    elif isinstance(payload, dict):
        verdict = payload.get("verdict", "")
        if not isinstance(verdict, str):
            raise CliError(f"{label}: verdict must be a string, got {type(verdict).__name__}", 2)
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            raise CliError(f"{label}: findings must be a list, "
                           f"got {type(raw_findings).__name__}", 2)
    else:
        raise CliError(f"{label}: top level must be a merged report object or a findings list, "
                       f"got {type(payload).__name__}", 2)
    return verdict, [normalize_finding(raw, index, label)
                     for index, raw in enumerate(raw_findings)]


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def write_text(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 with LF newlines on every platform (byte-identical output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", metavar="JSON",
                    help="Merged findings JSON (merge_findings.py --report output) or a bare "
                         "findings list; required unless --check is given")
    ap.add_argument("--repo", default=".",
                    help="Target repository recorded as the task's repo_path (default: .)")
    ap.add_argument("--out", required=True, metavar="YAML",
                    help="Path of the task file to write, or the file to validate with --check")
    ap.add_argument("--run-id", default="",
                    help="run_id of the review run (comment + description)")
    ap.add_argument("--title", default="", help="Override the derived task title")
    ap.add_argument("--verdict-ok", default=DEFAULT_VERDICT_OK, metavar="VERDICTS",
                    help="Comma-separated verdicts that mean the review accepted the tree; an "
                         "accepted report with no findings generates no task "
                         f"(default: {DEFAULT_VERDICT_OK})")
    ap.add_argument("--check", action="store_true",
                    help="Validate the shape of an existing generated task file instead of "
                         "generating one")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    if args.check:
        try:
            text = out.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"error: cannot read {out}: {exc}", file=sys.stderr)
            return 1
        problems = check_task(text)
        if problems:
            print(f"error: {out} is not a valid generated task file:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"ok - {out} is a valid generated follow-up task")
        return 0

    if not args.findings:
        ap.error("--findings is required unless --check is given")   # usage error: exit 2
    if not args.repo.strip():
        ap.error("--repo must not be empty: it becomes the task's repo_path")

    try:
        verdict, findings = load_findings(pathlib.Path(args.findings))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code

    accepted = {value.strip() for value in args.verdict_ok.split(",") if value.strip()}
    if verdict in accepted and not findings:
        print(f"nothing to do: verdict {verdict} is accepted by --verdict-ok {args.verdict_ok} "
              f"and the report carries no findings; no task written")
        return 0

    counts = counts_of(findings)
    command = command_line(args)
    title = args.title.strip() or derive_title(verdict, findings, counts, args.run_id)
    description = render_description(verdict, findings, counts, args.run_id, command)
    text = render_task(title, args.repo, description,
                       build_criteria(findings, pathlib.Path(args.repo)), args.run_id, command)
    try:
        write_text(out, text)
    except OSError as exc:
        print(f"error: cannot write {out}: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {out} ({len(findings)} findings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

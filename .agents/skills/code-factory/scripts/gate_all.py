#!/usr/bin/env python3
"""
One aggregator for the factory's deterministic gates (zero LLM tokens, stdlib only).

WHY THIS EXISTS

The factory ships a set of deterministic gates (the input-validation diff gate, the English-only
scan, the run-id provenance check, the action-gate finish audit, the rulebook reconciler, the
manifest audit). Each one was invoked — or not — by prose in the flow, and nothing made a SKIPPED
gate visible: the run report said what the agent chose to say. This aggregator runs every gate that
APPLIES to a phase, records each one (`gate` / `exit` / `applicability` / `ran_at` / `command`) in
one file per phase, and fails when a gate that should have run left no record.

PHASES

  K  the pre-implementation checkpoint: the input-validation diff gate (implement/refactor only),
     the English-only scan, the run-id provenance check, the rulebook reconciler and the
     watchdog-deny gate (a recorded unresolved supervisor deny blocks the phase).
  Y  the finish checkpoint: every K gate plus the action-gate finish audit and the manifest audit.

The manifest audit is CHANGE-PRODUCING only: a `review`/`security_audit` run is report-only and
never initializes a manifest, so the gate is recorded `skipped` with that reason instead of failing
on the missing file.

Optional gates (the delegation and permit audits, the watchdog-deny gate) are picked up
automatically once the script
EXISTS and advertises the subcommand: a gate script that is not present is recorded as
`not present: skipped` with the reason and never fails the phase, while a gate that IS present and
fails propagates a failure (exit 1).

THE SESSION OF THE WIRE-AUDITING GATES

The action, delegation and permit audits read the CLI session wire, and `auto` is a guess: when the
factory is launched from its deployment directory and the task's `repo_path` points elsewhere, the
run's wire is the LAUNCH directory's session while an older session carries the TARGET repository as
its `cwd` (factory-defect-session-resolution.md). This aggregator therefore forwards exactly ONE
explicit session — the `--session` it was given — to those gates. Without `--session` their own
`auto` applies only for a run launched FROM its repository; a run whose checkpoint names another
`launch_dir` is recorded FAIL CLOSED for those gates instead of auditing somebody else's wire. A
blank `--session` is an input error: blank is never a synonym for `auto`.

USAGE

  python gate_all.py --repo <root> --phase K|Y [--diff BASE HEAD] [--out <record>]
  python gate_all.py --repo <root> --phase K|Y --verify-only <record>

  --diff BASE HEAD   the change range of the run. Without it the input-validation gate scans the
                     working tree against HEAD (`--base HEAD`), which is what both checkpoints mean.
  --out              the record file (default: `<repo>/.code-factory/logs/gate-<phase>.md`); the
                     path is resolved through its nearest existing ancestor and must stay INSIDE
                     --repo (an absolute or traversing path that escapes is an input error)
  --verify-only      do not run anything: check that `<record>` names every gate that APPLIES to the
                     phase and that none of them failed — the "a missing gate record is a failure"
                     rule, usable by a later audit.

EXIT CODES

  0  every applicable gate ran and passed, and the record names all of them
  1  a gate failed, or the record is missing/incomplete (a phase that ran has its record)
  2  usage/input error: an unknown phase, a malformed diff range, a `--repo` that is not a
     directory, an unwritable record path, an unreadable existing record (never a traceback)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
PHASES = ("K", "Y")
RECORD_REL = pathlib.Path(".code-factory") / "logs"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
TASK_TYPE_LINE = re.compile(r"^task_type:\s*(.*)$")
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
LAUNCH_DIR_LINE = re.compile(r"^launch_dir:\s*(.*)$")
SESSION_DIR_LINE = re.compile(r"^session_dir:\s*(.*)$")
STARTED_AT_LINE = re.compile(r"^started_at:\s*(.*)$")
STRICT_TASK_TYPES = ("implement", "refactor")
ROW_RE = re.compile(r"^\|\s*(?P<gate>[a-z0-9-]+)\s*\|(?P<rest>.*)\|\s*$")


class GateAllError(ValueError):
    """An input this aggregator cannot honour: a message + exit 2, never a traceback."""


class Gate:
    """One deterministic gate: its script, the phases it applies to and how it is invoked.

    `optional` gates are the ones another task ships later: when the script is absent (or does not
    advertise the subcommand yet) the aggregator records `not present: skipped` and moves on.
    `{repo}` / `{diff}` / `{session}` are the only placeholders the argument list may use; a gate
    whose list names `{session}` is a WIRE-AUDITING gate and only ever sees an explicit session.
    """

    def __init__(self, name: str, script: str, phases: tuple[str, ...], args: tuple[str, ...],
                 optional: bool = False, diff_scoped: bool = False,
                 change_producing: bool = False):
        self.name = name
        self.script = script
        self.phases = phases
        self.args = args
        self.optional = optional
        self.diff_scoped = diff_scoped
        # A change-producing gate audits the run's CHANGE SET; a report-only task type
        # (review/security_audit) never produces one, so the gate is skipped with the reason.
        self.change_producing = change_producing


GATES: tuple[Gate, ...] = (
    Gate("input-validation", "check_input_validation.py", PHASES, ("--diff", "{diff}"),
         diff_scoped=True),
    Gate("english-only", "check_english_only.py", PHASES, ("--root", "{repo}")),
    Gate("run-id", "run_id.py", PHASES, ("check", "--dir", ".code-factory", "--repo", "{repo}")),
    Gate("factory-rules", "check_factory_rules.py", PHASES, ("--root", "{repo}")),
    Gate("action-audit", "action_gate.py", ("Y",), ("audit", "--repo", "{repo}",
         "--session", "{session}")),
    Gate("manifest-audit", "manifest.py", ("Y",), ("audit", "--repo", "{repo}"),
         change_producing=True),
    Gate("delegation-audit", "delegation_gate.py", ("Y",), ("audit", "--repo", "{repo}",
         "--session", "{session}"), optional=True),
    Gate("permit-audit", "permit_gate.py", PHASES, ("audit", "--repo", "{repo}",
         "--session", "{session}"), optional=True),
    Gate("watchdog-deny", "supervisor_watchdog.py", PHASES, ("status", "--repo", "{repo}"),
         optional=True),
)
RECORD_COLUMNS = ("gate", "exit", "applicability", "ran_at", "command")


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the record survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise GateAllError(f"repository root does not exist: {root}")
    return root


def pipeline_contract(root: pathlib.Path) -> dict:
    """`{task_type, run_id, launch_dir, session_dir, started_at}` of the run's checkpoint.

    Missing values stay empty strings: they are DATA, not an error — but an empty `launch_dir`
    means the run has no evidence of being launched outside its repository, so the wire-auditing
    gates may resolve their session themselves.
    """
    keys = ("task_type", "run_id", "launch_dir", "session_dir", "started_at")
    contract = dict.fromkeys(keys, "")
    patterns = {"task_type": TASK_TYPE_LINE, "run_id": RUN_ID_LINE,
                "launch_dir": LAUNCH_DIR_LINE, "session_dir": SESSION_DIR_LINE,
                "started_at": STARTED_AT_LINE}
    path = root / PIPELINE_REL
    if not path.is_file():
        return contract
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateAllError(f"cannot read {path}: {exc}") from exc
    for line in text.splitlines():
        if line[:1].isspace():
            continue
        for key in keys:
            match = patterns[key].match(line.rstrip())
            if match and not contract[key]:
                contract[key] = match.group(1).strip().strip("'\"")
    return contract


def norm_path(value: str | pathlib.Path) -> str:
    """A path normalised for comparison: absolute, forward slashes, case-folded on Windows."""
    raw = str(value or "")
    if not raw:
        return ""
    try:
        raw = str(pathlib.Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):      # an unparsable or vanishing path
        pass
    text = raw.replace("\\", "/").rstrip("/")
    return text.casefold() if os.name == "nt" else text


def checked_session(value: str | None) -> str:
    """The ONE session forwarded to the wire-auditing gates: a directory, or `auto`.

    A blank value is refused — "blank" is never a synonym for `auto`, and it is exactly how a
    caller loses the run's identity by accident. A named directory must exist: a gate pointed at a
    missing session would DEGRADE or, worse, resolve another one.
    """
    text = (value or "").strip()
    if not text:
        raise GateAllError("--session is empty: name the run's own session directory (or pass "
                          "'auto' explicitly) — a blank value is never a synonym for auto")
    if text.lower() == "auto":
        return "auto"
    directory = pathlib.Path(text).expanduser()
    if not directory.is_dir():
        raise GateAllError(f"--session {text!r} is not a session directory: the wire-auditing gates "
                          f"must be given the run's own session, never a guess")
    return str(directory.resolve())


def session_blocked(root: pathlib.Path, contract: dict) -> str:
    """Why the wire-auditing gates must NOT fall back to `auto` here, or "" when they may.

    A run launched from ANOTHER directory owns a session whose `cwd` is that launch directory, so
    matching on the target repository finds an OLDER run instead (the defect this file closes).
    Without an explicit session such a phase FAILS CLOSED rather than auditing the wrong wire.
    """
    launch = contract.get("launch_dir") or ""
    if not launch or norm_path(launch) == norm_path(root):
        return ""
    return (f"fail closed: this run was launched from {launch}, not from {root}, so its wire is "
            f"the launch directory's session and `auto` could audit another run's — pass the run's "
            f"own --session")


def resolve_range(root: pathlib.Path, diff: tuple[str, str] | None) -> tuple[str, str] | None:
    """`(base, head)` of a range git can actually resolve — a malformed one is an INPUT ERROR.

    This is the ONE range check of the command: the running path materializes the diff from the
    validated refs, and `--verify-only` calls it too, because a record attested against a range the
    gate itself would refuse to run is not attested at all. The refs are probed with
    `git diff --quiet` (no diff text is produced), so the read-only path stays read-only.
    """
    if diff is None:
        return None
    base, head = diff
    for ref in (base, head):
        if not ref or ref.startswith("-"):
            raise GateAllError(f"malformed diff range {base!r}..{head!r}: a commit-ish may not be "
                               f"empty or start with '-'")
    try:
        res = subprocess.run(["git", "-C", str(root), "diff", "--quiet", base, head],
                             capture_output=True)
    except OSError as exc:
        raise GateAllError(f"cannot compute the diff range {base}..{head}: {exc}") from exc
    # 0 = the refs resolve (no difference), 1 = they resolve and differ; anything else is git
    # refusing the range, which is exactly the malformed case.
    if res.returncode not in (0, 1):
        detail = res.stderr.decode("utf-8", "replace").strip()
        raise GateAllError(f"malformed diff range {base}..{head}: git answered "
                           f"{detail or 'exit ' + str(res.returncode)}")
    return base, head


def range_reason(diff: tuple[str, str] | None) -> str:
    """How the run's change range is described in a record (the default range has no refs)."""
    return "the working tree against HEAD" if diff is None else f"{diff[0]}..{diff[1]}"


def change_range(root: pathlib.Path, diff: tuple[str, str] | None) -> tuple[pathlib.Path | None, str]:
    """`(diff file or None, reason)`: the run's change range, materialized as one unified diff.

    Without `--diff` the range is the working tree against `HEAD` (what both checkpoints mean).
    A range git cannot resolve is an INPUT ERROR: a gate that scans the wrong range would report a
    green verdict about changes nobody made.
    """
    wanted = resolve_range(root, diff)
    if wanted is None:
        return None, range_reason(None)
    base, head = wanted
    try:
        res = subprocess.run(["git", "-C", str(root), "diff", base, head], capture_output=True)
    except OSError as exc:
        raise GateAllError(f"cannot compute the diff range {base}..{head}: {exc}") from exc
    if res.returncode != 0:
        detail = res.stderr.decode("utf-8", "replace").strip()
        raise GateAllError(f"malformed diff range {base}..{head}: git answered "
                           f"{detail or 'exit ' + str(res.returncode)}")
    handle, temp = tempfile.mkstemp(prefix="gate-all-", suffix=".diff")
    with os.fdopen(handle, "wb") as stream:
        stream.write(res.stdout)
    return pathlib.Path(temp), range_reason(wanted)


def gate_available(gate: Gate) -> tuple[bool, str]:
    """`(available, reason)` — an optional gate is available only when its subcommand exists."""
    script = SCRIPT_DIR / gate.script
    if not script.is_file():
        return False, f"not present: {gate.script} is not shipped"
    if not gate.optional:
        return True, ""
    subcommand = next((arg for arg in gate.args if not arg.startswith("-")), "")
    if subcommand:
        try:
            res = subprocess.run([sys.executable, str(script), "--help"], capture_output=True,
                                 text=True, errors="replace")
        except OSError as exc:
            return False, f"not present: {gate.script} cannot be run ({exc})"
        # argparse lists its subcommands in the usage line (`usage: x [-h] {check,init} ...`) — the
        # ONLY reliable place: the help BODY of these scripts is their long docstring, where the
        # word "audit" occurs for prose reasons. The usage block may WRAP onto continuation lines
        # (permit_gate.py's subcommand list does), so the whole block — everything after `usage:`
        # up to the first blank line — is searched, not only its first line.
        lines = (res.stdout + res.stderr).splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith("usage:")), None)
        block: list[str] = []
        for line in lines[start:] if start is not None else []:
            if not line.strip():
                break
            block.append(line)
        choices: set[str] = set()
        match = re.search(r"\{([a-z0-9,\-_ ]+)\}", "\n".join(block))
        if match:
            choices = {part.strip() for part in match.group(1).split(",")}
        if subcommand not in choices:
            return False, (f"not present: {gate.script} advertises no `{subcommand}` subcommand "
                           f"yet")
    return True, ""


def applicability(gate: Gate, phase: str, contract: dict, range_reason: str) -> tuple[bool, str]:
    """`(applies, reason)` of one gate in one phase."""
    if phase not in gate.phases:
        return False, f"not applicable in phase {phase}"
    available, why = gate_available(gate)
    if not available:
        return False, why
    if gate.diff_scoped:
        task_type = contract["task_type"]
        if task_type and task_type not in STRICT_TASK_TYPES:
            return False, (f"not applicable: task_type {task_type} produces no change range for the "
                           f"input-validation scan")
        return True, f"applicable: the change range is {range_reason}"
    if gate.change_producing:
        task_type = contract["task_type"]
        if task_type and task_type not in STRICT_TASK_TYPES:
            return False, (f"not applicable: task_type {task_type} is report-only and never "
                           f"initializes a manifest")
    return True, "applicable"


# ----------------------------------------------------------------------------------------- record

def record_path(root: pathlib.Path, phase: str, out: str | None) -> pathlib.Path:
    """The record file's path, CONFINED to the repository.

    `--out` is user input: an absolute path or a `..` traversal must never make the aggregator
    write its record outside the resolved repository. The file itself may not exist yet, so the
    path is resolved through its NEAREST EXISTING ANCESTOR (symlinks included) and the remaining
    components are re-appended; the result must stay inside --repo.
    """
    if not out:
        return root / RECORD_REL / f"gate-{phase}.md"
    raw = pathlib.Path(out)
    candidate = raw if raw.is_absolute() else root / raw
    node, tail = candidate, []
    while not node.exists() and node.parent != node:
        tail.append(node.name)
        node = node.parent
    if not node.exists():
        raise GateAllError(f"--out {out!r} has no existing ancestor: the record path cannot be "
                           f"confined to the repository root {root}")
    resolved = node.resolve()
    for part in reversed(tail):
        if part in ("", ".", ".."):
            raise GateAllError(f"--out {out!r} may not contain {part!r} components: the record "
                               f"path must be a plain path inside the repository root {root}")
        resolved = resolved / part
    base = root.resolve()
    if not resolved.is_relative_to(base):
        raise GateAllError(f"--out {out!r} resolves to {resolved}, which is outside the "
                           f"repository root {base}: the gate record must stay inside --repo")
    return resolved


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def write_record(path: pathlib.Path, phase: str, run_id: str, rows: list[dict]) -> pathlib.Path:
    """Write the phase record deterministically (a markdown table, one row per gate)."""
    lines = [f"run_id: {run_id}", "",
             f"# Gate record — phase {phase}", "",
             "| " + " | ".join(RECORD_COLUMNS) + " |",
             "| " + " | ".join("---" for _ in RECORD_COLUMNS) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(str(row[column])) for column in RECORD_COLUMNS) + " |")
    text = "\n".join(lines) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise GateAllError(f"cannot write the gate record {path}: {exc}") from exc
    return path


def read_record(path: pathlib.Path) -> tuple[str, list[dict]]:
    """`(run_id, rows)` of an existing record; an UNREADABLE one is an input error (exit 2)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateAllError(f"cannot read the gate record {path}: {exc}") from exc
    run_id = ""
    rows: list[dict] = []
    for line in text.splitlines():
        match = RUN_ID_LINE.match(line.rstrip())
        if match and not run_id:
            run_id = match.group(1).strip()
        row = ROW_RE.match(line.strip())
        if not row or row.group("gate") in RECORD_COLUMNS:
            continue
        rest = row.group("rest").replace("\\|", "|")
        values = [part.strip() for part in re.split(r"(?<!\\)\|", rest)]
        if len(values) != len(RECORD_COLUMNS) - 1:
            continue
        if all(set(value) <= set("-: ") for value in values):
            continue                                  # the table separator
        rows.append({"gate": row.group("gate"), **dict(zip(RECORD_COLUMNS[1:], values))})
    return run_id, rows


def verify_record(path: pathlib.Path, phase: str, contract: dict,
                  range_reason: str) -> tuple[list[str], list[dict]]:
    """`(problems, rows)` — the record must name every applicable gate and accept none of them."""
    expected = {gate.name: applicability(gate, phase, contract, range_reason) for gate in GATES}
    if not path.is_file():
        # A phase that ran leaves its record: its absence is a FAILURE of the run, not of this
        # command (rule: a missing gate record in the run's artifacts is itself a failure).
        missing = [name for name, (applies, _reason) in expected.items() if applies]
        return ([f"no gate record at {path}: {len(missing)} gate(s) that apply to phase {phase} "
                 f"left no record ({', '.join(missing)}) — a phase that ran has its record"], [])
    run_id, rows = read_record(path)
    listed = {row["gate"]: row for row in rows}
    problems: list[str] = []
    # A record is evidence of a CHECKPOINT of THIS run: a green record another run wrote must not
    # satisfy this phase, and a record that names no run at all proves nothing.
    if not run_id:
        problems.append(f"{path}: the gate record names no run_id — a record that cannot be "
                        f"attributed to a run is not evidence for this phase")
    elif contract.get("run_id") and run_id != contract["run_id"]:
        problems.append(f"{path}: the gate record belongs to run {run_id!r}, not to this run's "
                        f"{contract['run_id']!r} — another run's green record does not satisfy "
                        f"phase {phase}")
    for name, (applies, reason) in expected.items():
        if applies and name not in listed:
            problems.append(f"{path}: no record for the {name!r} gate, which applies in phase "
                            f"{phase} ({reason}) — a gate that should have run and left no record is "
                            f"a failure")
        if applies and name in listed and listed[name]["exit"] != "0":
            problems.append(f"{path}: the {name!r} gate is recorded as exit {listed[name]['exit']} — "
                            f"the phase failed")
    for name in listed:
        if name not in expected:
            problems.append(f"{path}: the record names the unknown gate {name!r}")
        elif not expected[name][0]:
            # A gate that does not apply may still be LISTED — that is how the record states WHY it
            # did not run — but it must be recorded as skipped, never as a run.
            if listed[name]["exit"] != "skipped":
                problems.append(f"{path}: the record names the {name!r} gate with exit "
                                f"{listed[name]['exit']}, but it does not apply in phase {phase} "
                                f"({expected[name][1]})")
    return problems, rows


# -------------------------------------------------------------------------------------------- run

def gate_argv(gate: Gate, root: pathlib.Path, diff_file: pathlib.Path | None,
              session: str) -> list[str]:
    """The argument list of one gate, placeholders filled — `session` is the ONLY one forwarded.

    A gate that takes no `{session}` placeholder never sees it. A wire-auditing gate invoked
    WITHOUT a session drops the flag AND its value (the template's empty placeholder must never
    become a stray argument), so the audited script's own default applies — which only happens for
    a run launched inside its repository (`run_phase` refuses the case that would guess).
    """
    values = {"repo": str(root), "diff": str(diff_file) if diff_file else "", "session": session}
    argv: list[str] = []
    skip = False
    for arg in gate.args:
        if skip:                                  # the value of a dropped `--session` flag
            skip = False
            continue
        if arg == "--session" and not session:
            skip = True
            continue
        filled = arg.format(**values)
        if filled:
            argv.append(filled)
    return argv


def run_gate(gate: Gate, root: pathlib.Path, diff_file: pathlib.Path | None,
             session: str = "") -> dict:
    """Run one gate as a subprocess and report its outcome (the command is data, never a shell)."""
    if gate.diff_scoped and diff_file is None:
        # No explicit range: scan the working tree against HEAD (both checkpoints mean this).
        argv = ["--base", "HEAD"]
    else:
        argv = gate_argv(gate, root, diff_file, session)
    command = [sys.executable, gate.script, *argv]
    stamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        res = subprocess.run(command, cwd=str(SCRIPT_DIR), capture_output=True, text=True,
                             errors="replace")
        code = res.returncode
        output = (res.stdout + res.stderr).strip()
    except OSError as exc:                        # the interpreter itself could not start it
        code, output = 2, f"cannot run {gate.script}: {exc}"
    return {"gate": gate.name, "exit": str(code), "applicability": "applicable",
            "ran_at": stamp,
            "command": " ".join([gate.script, *argv]).strip(),
            "output": output}


def run_phase(root: pathlib.Path, phase: str, diff: tuple[str, str] | None,
              out: str | None, session: str | None = None) -> dict:
    """Run every applicable gate of `phase`, write the record and self-verify it.

    `session` is the run's own session, forwarded verbatim to the wire-auditing gates. When it is
    absent and the run was LAUNCHED OUTSIDE its repository, those gates are recorded FAIL CLOSED:
    their `auto` resolution would match an older target-cwd session and answer about another run.
    """
    root = _checked_repo(root)
    if phase not in PHASES:
        raise GateAllError(f"unknown phase {phase!r}: the factory has exactly two gate checkpoints, "
                           f"{' and '.join(PHASES)}")
    contract = pipeline_contract(root)
    session = checked_session(session) if session is not None else ""
    blocked = "" if session else session_blocked(root, contract)
    diff_file, range_reason = change_range(root, diff)
    rows: list[dict] = []
    try:
        for gate in GATES:
            applies, reason = applicability(gate, phase, contract, range_reason)
            if not applies:
                rows.append({"gate": gate.name, "exit": "skipped", "applicability": reason,
                             "ran_at": datetime.datetime.now(tz=datetime.timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "command": "-"})
                continue
            if blocked and "{session}" in gate.args:
                rows.append({"gate": gate.name, "exit": "2", "applicability": blocked,
                             "ran_at": datetime.datetime.now(tz=datetime.timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "command": f"{gate.script} (not run: no --session)",
                             "output": blocked})
                continue
            rows.append(run_gate(gate, root, diff_file, session))
    finally:
        if diff_file is not None:
            diff_file.unlink(missing_ok=True)
    path = record_path(root, phase, out)
    write_record(path, phase, contract["run_id"] or "unknown", rows)
    problems, _rows = verify_record(path, phase, contract, range_reason)
    failed = [row for row in rows if row["exit"] not in ("0", "skipped")]
    result = {"phase": phase, "repo": str(root), "record": str(path), "run_id":
              contract["run_id"] or None, "gates": rows, "failed": [row["gate"] for row in failed],
              "problems": problems,
              "status": "failed" if (failed or problems) else "ok"}
    return result


def format_summary(result: dict) -> str:
    lines = [f"gate_all phase {result['phase']} under {result['repo']}",
             f"record: {result['record']}"]
    for row in result["gates"]:
        state = row["exit"] if row["exit"] != "skipped" else "skipped"
        lines.append(f"  {row['gate'] + ':':<20}{state:<8}{row['applicability']}")
    for problem in result["problems"]:
        lines.append(f"  PROBLEM: {problem}")
    if result["status"] == "ok":
        lines.append(f"PASS - every gate that applies to phase {result['phase']} ran and passed "
                     f"({len(result['gates'])} gate(s) recorded)")
    else:
        lines.append(f"FAIL - phase {result['phase']} has failing gate(s) "
                     f"{', '.join(result['failed']) or 'none'} and/or an incomplete record")
    return "\n".join(lines)


# -------------------------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gate_all.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="repository root of the run")
    ap.add_argument("--phase", required=True, choices=PHASES,
                    help="K (pre-implementation) or Y (finish)")
    ap.add_argument("--diff", nargs=2, metavar=("BASE", "HEAD"), default=None,
                    help="the run's change range (default: the working tree against HEAD)")
    ap.add_argument("--out", default=None,
                    help=f"record file (default: <repo>/{RECORD_REL.as_posix()}/gate-<phase>.md)")
    ap.add_argument("--session", default=None,
                    help="the run's own session directory (or an explicit 'auto'), forwarded to the "
                         "wire-auditing gates (action-audit, delegation-audit, permit-audit); a "
                         "blank value is a usage error and an omitted one fails closed for a run "
                         "launched outside its repository")
    ap.add_argument("--verify-only", default=None, metavar="RECORD",
                    help="only check an existing record against the phase's gate table")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    return ap


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        root = _checked_repo(args.repo)
        # The range is validated BEFORE anything reads or writes: `--verify-only` must refuse a
        # malformed range exactly like a phase run (ADV-2) and leave the record untouched.
        checked = resolve_range(root, tuple(args.diff) if args.diff else None)
        contract = pipeline_contract(root)
        range_reason = "the working tree against HEAD" if checked is None else \
            f"{checked[0]}..{checked[1]}"
        session = checked_session(args.session) if args.session is not None else None
        if args.verify_only:
            problems, rows = verify_record(pathlib.Path(args.verify_only), args.phase, contract,
                                           range_reason)
            payload = {"phase": args.phase, "record": args.verify_only,
                       "gates": [row["gate"] for row in rows], "problems": problems,
                       "status": "failed" if problems else "ok"}
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                for problem in problems:
                    print(f"PROBLEM: {problem}")
                print(f"{'PASS' if not problems else 'FAIL'} - "
                      f"{len(rows)} recorded gate(s) for phase {args.phase}")
            return 0 if not problems else 1
        result = run_phase(root, args.phase, tuple(args.diff) if args.diff else None, args.out,
                           session)
    except GateAllError as exc:
        print(f"gate_all.py: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        payload = {key: value for key, value in result.items() if key != "gates"}
        payload["gates"] = [{key: value for key, value in row.items() if key != "output"}
                            for row in result["gates"]]
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(format_summary(result))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

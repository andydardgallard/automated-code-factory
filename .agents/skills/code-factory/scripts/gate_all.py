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
     the English-only scan, the run-id provenance check and the rulebook reconciler.
  Y  the finish checkpoint: every K gate plus the action-gate finish audit and the manifest audit.

Optional gates (the delegation and permit audits) are picked up automatically once the script
EXISTS and advertises the subcommand: a gate script that is not present is recorded as
`not present: skipped` with the reason and never fails the phase, while a gate that IS present and
fails propagates a failure (exit 1). This is how `permit_gate.py` (task_16) joins without touching
this file.

USAGE

  python gate_all.py --repo <root> --phase K|Y [--diff BASE HEAD] [--out <record>]
  python gate_all.py --repo <root> --phase K|Y --verify-only <record>

  --diff BASE HEAD   the change range of the run. Without it the input-validation gate scans the
                     working tree against HEAD (`--base HEAD`), which is what both checkpoints mean.
  --out              the record file (default: `<repo>/.code-factory/logs/gate-<phase>.md`)
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
STRICT_TASK_TYPES = ("implement", "refactor")
ROW_RE = re.compile(r"^\|\s*(?P<gate>[a-z0-9-]+)\s*\|(?P<rest>.*)\|\s*$")


class GateAllError(ValueError):
    """An input this aggregator cannot honour: a message + exit 2, never a traceback."""


class Gate:
    """One deterministic gate: its script, the phases it applies to and how it is invoked.

    `optional` gates are the ones another task ships later: when the script is absent (or does not
    advertise the subcommand yet) the aggregator records `not present: skipped` and moves on.
    `{repo}` / `{diff}` are the only placeholders the argument list may use.
    """

    def __init__(self, name: str, script: str, phases: tuple[str, ...], args: tuple[str, ...],
                 optional: bool = False, diff_scoped: bool = False):
        self.name = name
        self.script = script
        self.phases = phases
        self.args = args
        self.optional = optional
        self.diff_scoped = diff_scoped


GATES: tuple[Gate, ...] = (
    Gate("input-validation", "check_input_validation.py", PHASES, ("--diff", "{diff}"),
         diff_scoped=True),
    Gate("english-only", "check_english_only.py", PHASES, ("--root", "{repo}")),
    Gate("run-id", "run_id.py", PHASES, ("check", "--dir", ".code-factory", "--repo", "{repo}")),
    Gate("factory-rules", "check_factory_rules.py", PHASES, ("--root", "{repo}")),
    Gate("action-audit", "action_gate.py", ("Y",), ("audit", "--repo", "{repo}")),
    Gate("manifest-audit", "manifest.py", ("Y",), ("audit", "--repo", "{repo}")),
    Gate("delegation-audit", "delegation_gate.py", ("Y",), ("audit", "--repo", "{repo}"),
         optional=True),
    Gate("permit-audit", "permit_gate.py", PHASES, ("audit", "--repo", "{repo}"), optional=True),
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
    """`{task_type, run_id}` of the run's checkpoint — missing values stay empty (data, not an error)."""
    contract = {"task_type": "", "run_id": ""}
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
        for key, pattern in (("task_type", TASK_TYPE_LINE), ("run_id", RUN_ID_LINE)):
            match = pattern.match(line.rstrip())
            if match and not contract[key]:
                contract[key] = match.group(1).strip().strip("'\"")
    return contract


def change_range(root: pathlib.Path, diff: tuple[str, str] | None) -> tuple[pathlib.Path | None, str]:
    """`(diff file or None, reason)`: the run's change range, materialized as one unified diff.

    Without `--diff` the range is the working tree against `HEAD` (what both checkpoints mean).
    A range git cannot resolve is an INPUT ERROR: a gate that scans the wrong range would report a
    green verdict about changes nobody made.
    """
    if diff is None:
        return None, "the working tree against HEAD"
    base, head = diff
    for ref in (base, head):
        if not ref or ref.startswith("-"):
            raise GateAllError(f"malformed diff range {base!r}..{head!r}: a commit-ish may not be "
                               f"empty or start with '-'")
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
    return pathlib.Path(temp), f"{base}..{head}"


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
        # word "audit" occurs for prose reasons.
        usage_lines = (res.stdout + res.stderr).splitlines()
        choices: set[str] = set()
        match = re.search(r"\{([a-z0-9,\-_ ]+)\}", usage_lines[0]) if usage_lines else None
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
    return True, "applicable"


# ----------------------------------------------------------------------------------------- record

def record_path(root: pathlib.Path, phase: str, out: str | None) -> pathlib.Path:
    if out:
        path = pathlib.Path(out)
        return path if path.is_absolute() else root / path
    return root / RECORD_REL / f"gate-{phase}.md"


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

def run_gate(gate: Gate, root: pathlib.Path, diff_file: pathlib.Path | None) -> dict:
    """Run one gate as a subprocess and report its outcome (the command is data, never a shell)."""
    if gate.diff_scoped and diff_file is None:
        # No explicit range: scan the working tree against HEAD (both checkpoints mean this).
        argv = ["--base", "HEAD"]
    else:
        argv = [arg.format(repo=str(root), diff=str(diff_file) if diff_file else "")
                for arg in gate.args]
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
              out: str | None) -> dict:
    """Run every applicable gate of `phase`, write the record and self-verify it."""
    root = _checked_repo(root)
    if phase not in PHASES:
        raise GateAllError(f"unknown phase {phase!r}: the factory has exactly two gate checkpoints, "
                           f"{' and '.join(PHASES)}")
    contract = pipeline_contract(root)
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
            rows.append(run_gate(gate, root, diff_file))
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
    ap.add_argument("--verify-only", default=None, metavar="RECORD",
                    help="only check an existing record against the phase's gate table")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    return ap


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        root = _checked_repo(args.repo)
        contract = pipeline_contract(root)
        range_reason = "the working tree against HEAD" if args.diff is None else \
            f"{args.diff[0]}..{args.diff[1]}"
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
        result = run_phase(root, args.phase, tuple(args.diff) if args.diff else None, args.out)
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

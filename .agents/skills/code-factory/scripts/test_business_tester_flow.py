#!/usr/bin/env python3
"""
Deterministic self-test of the adversarial business-tester flow (stdlib only).

The finding this pins: the W3 card `factory-business-tester` described a role whose evidence shape,
scope and routing existed only as prose. This script exercises the flow for real — a throwaway CLI
product with SEEDED defects is attacked through its own user interface, exactly as the card demands
(a user types the product's commands; no import, no debugger, no product edit) — and then checks the
report the role has to hand over:

  (a) every scenario is driven by REAL user-level commands in a throwaway copy of the product, and
      a pass is proven (the happy path holds) rather than assumed;
  (b) the adversarial matrix reproduces every seeded defect: empty, malformed, huge, negative,
      repeated (double submit) and out-of-order input — a scenario that stops breaking the product
      fails this test, so the fixture can never quietly lose its teeth;
  (c) the evidence report carries the documented shape (card `business-tester.md`), and every
      invariant of that shape is enforced: the enum values, the `broke`/`no_defect` consistency, one
      breakage per broken scenario, `product_files_edited: 0`, `debugger_used: false`,
      `actions_were_user_level: true`, and NO acceptance claim (the tester owns acceptance);
  (d) a recorded breakage routes through the EXISTING deterministic error path to the coder: the
      observed output classifies to `route: coder`, and there is no separate business-tester retry
      budget in `delegation_gate.py` (a broken product is a code defect, not a new role);
  (e) `--evidence <path>` judges a report file by its documented SHAPE: any report a real run wrote
      passes, and a mutated one exits 1 (the check is not a tautology). Only the script's OWN
      fixture report (marked `fixture: seeded-defect/1`) is additionally compared with the built-in
      seeded-defect matrix — a real run's scenario ids are the run's, never this fixture's. `--write`
      refuses to overwrite an existing file, because that file may hold a real run's evidence: the
      fixture report is regenerated only with `--write --force`.

Usage:
  python test_business_tester_flow.py [--evidence <report.json>] [--write [--force]] [--no-drive]

  --evidence <path>  validate this report. Missing → written from the fixture (a fresh clone works).
                     A report WITHOUT the fixture marker is validated on shape alone; a marked one
                     is also checked against the seeded-defect matrix.
  --write            regenerate the fixture self-check report (default target: the seeded-defect
                     path under `.code-factory/logs/business-adversarial/`). REFUSES to overwrite an
                     existing file unless `--force` is given.
  --no-drive         validate `--evidence` only, without driving the fixture product.

Without `--evidence` the report is built and validated in memory only; nothing is written.

Exit code 0 = every assertion passed, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import date

SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
ROUTER = SCRIPTS / "error_router.py"
CARD = ROOT / ".agents" / "agents" / "sub-agents" / "business-tester.md"
DEFAULT_EVIDENCE = ROOT / ".code-factory" / "logs" / "business-adversarial" / "seeded-defect.json"
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
OUTCOMES = ("held", "broke", "unverified")
CLASSIFICATIONS = ("code_defect", "contract_gap", "environment", "no_defect")
SEVERITIES = ("critical", "major", "minor")
TASK_TYPES = ("implement", "review", "refactor")
INTERFACES = ("cli", "http", "ui")
# Keys of a report that claims an acceptance verdict — the business tester may never issue one.
FORBIDDEN_REPORT_KEYS = ("verdict", "acceptance", "pass", "accepted")
SCENARIO_KEYS = ("id", "goal", "interface", "actions", "expected", "observed", "outcome",
                 "classification")
BREAKAGE_KEYS = ("scenario", "severity", "summary")
# The marker of the script's OWN report. A report a real run wrote carries no marker and is judged
# on its documented SHAPE alone — its scenarios are the run's product, not this fixture's shop.py —
# while a marked report must also match the built-in seeded-defect matrix.
FIXTURE_MARKER = "seeded-defect/1"

# The product under attack: a tiny order desk with three seeded defects. It is copied into a fresh
# directory per scenario, so every scenario starts from the same state and the recorded commands stay
# the ones a user types (no absolute temporary path leaks into the report).
PRODUCT = '''\
"""Order desk - the product the adversarial business tester attacks."""
import argparse
import pathlib
import sys

PRICES = {"widget": 250, "gadget": 400}
CAPACITY = 1000
STATE = pathlib.Path("orders.log")


def order(args) -> int:
    qty = int(args.qty)                                    # DEFECT 1: raw user value, unvalidated
    assert qty < CAPACITY, "warehouse capacity exceeded"    # DEFECT 2: an assert on valid input
    total = PRICES[args.sku] * qty                          # DEFECT 3: a negative qty is billed
    if args.commit:
        with STATE.open("a", encoding="utf-8") as handle:   # DEFECT 4: no idempotency
            handle.write(f"{args.sku} {qty}\\n")
    print(f"ok: {qty} {args.sku} = {total}")
    return 0


def report() -> int:
    lines = STATE.read_text(encoding="utf-8").splitlines() if STATE.exists() else []
    print(f"orders: {len(lines)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="shop.py")
    sub = ap.add_subparsers(dest="command", required=True)
    place = sub.add_parser("order")
    place.add_argument("--sku", required=True, choices=sorted(PRICES))
    place.add_argument("--qty", required=True)
    place.add_argument("--commit", action="store_true")
    sub.add_parser("report")
    parsed = ap.parse_args(argv)
    return order(parsed) if parsed.command == "order" else report()


if __name__ == "__main__":
    sys.exit(main())
'''

# One entry per user-level scenario. `defect` returns True when the product BROKE (the predicate is
# what makes the outcome honest: a scenario "holds" only while the product does the promised thing).
SCENARIOS = (
    {"id": "happy-path", "interface": "cli",
     "goal": "The ordinary order: one widget, quantity three",
     "commands": (("order", "--sku", "widget", "--qty", "3"),),
     "expected": "exit 0 and the line `ok: 3 widget = 750`",
     "classification": "code_defect",
     "defect": lambda out, rc: rc != 0 or "ok: 3 widget = 750" not in out},
    {"id": "empty-qty", "interface": "cli",
     "goal": "Clear the quantity field and submit",
     "commands": (("order", "--sku", "widget", "--qty", ""),),
     "expected": "a readable refusal naming the quantity, exit 2",
     "classification": "code_defect",
     "defect": lambda out, rc: "Traceback" in out or rc == 0},
    {"id": "malformed-qty", "interface": "cli",
     "goal": "Type letters into a quantity field",
     "commands": (("order", "--sku", "widget", "--qty", "abc"),),
     "expected": "a readable refusal naming the quantity, exit 2",
     "classification": "code_defect",
     "defect": lambda out, rc: "Traceback" in out or rc == 0},
    {"id": "huge-qty", "interface": "cli",
     "goal": "A large but legitimate order (a full truck)",
     "commands": (("order", "--sku", "widget", "--qty", "5000"),),
     "expected": "the order is accepted or refused with a business message, never a crash",
     "classification": "code_defect",
     "defect": lambda out, rc: "AssertionError" in out or "Traceback" in out},
    {"id": "negative-qty", "interface": "cli",
     "goal": "A negative quantity, as a careless typo",
     "commands": (("order", "--sku", "widget", "--qty", "-2"),),
     "expected": "the order is refused; a negative amount is never billed",
     "classification": "code_defect",
     "defect": lambda out, rc: rc == 0 and "-500" in out},
    {"id": "repeated-commit", "interface": "cli",
     "goal": "Double submit: the same order committed twice",
     "commands": (("order", "--sku", "gadget", "--qty", "1", "--commit"),
                  ("order", "--sku", "gadget", "--qty", "1", "--commit"),
                  ("report",)),
     "expected": "one order is recorded (the double submit is idempotent)",
     "classification": "code_defect",
     "defect": lambda out, rc: "orders: 2" in out},
    {"id": "report-before-order", "interface": "cli",
     "goal": "Open the report before anything was ordered",
     "commands": (("report",),),
     "expected": "exit 0 and `orders: 0` - an empty report is not an error",
     "classification": "code_defect",
     "defect": lambda out, rc: rc != 0 or "orders: 0" not in out},
    {"id": "web-gui-checkout", "interface": "ui",
     "goal": "Buy the same widget through the shop's Web checkout",
     "commands": (),
     "expected": "the checkout completes through the browser",
     # The fixture ships no Web GUI: an unverifiable scenario is reported UNVERIFIED, never a pass.
     "classification": "environment",
     "defect": lambda out, rc: False},
)
# The seeded outcome of every scenario — a fixture that stops breaking fails the test loudly.
EXPECTED_OUTCOMES = {"happy-path": "held", "empty-qty": "broke", "malformed-qty": "broke",
                     "huge-qty": "broke", "negative-qty": "broke", "repeated-commit": "broke",
                     "report-before-order": "held", "web-gui-checkout": "unverified"}
# The severity each recovered breakage is reported with (a crash that loses an order is critical),
# and the one-line summary the main agent acts on.
SEVERITY = {"happy-path": "minor", "empty-qty": "major", "malformed-qty": "major",
            "huge-qty": "critical", "negative-qty": "critical", "repeated-commit": "major",
            "report-before-order": "minor", "web-gui-checkout": "minor"}
SUMMARY = {"empty-qty": "an empty quantity crashes the order with an unhandled ValueError",
           "malformed-qty": "letters in the quantity crash the order with an unhandled ValueError",
           "huge-qty": "a legitimate 5000-unit order trips an internal assertion and crashes",
           "negative-qty": "a negative quantity is accepted and billed (total -500)",
           "repeated-commit": "a double submit records the same order twice (not idempotent)"}


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_id_of(content: bytes) -> str:
    """`<YYYYMMDD>-<8 hex>`, the factory's run id: the date plus a content-derived suffix."""
    normalized = content.replace(b"\r\n", b"\n")
    return f"{date.today():%Y%m%d}-{hashlib.sha256(normalized).hexdigest()[:8]}"


def drive(product_source: pathlib.Path, scenario: dict, workdir: pathlib.Path) -> tuple[str, int]:
    """Run one scenario's commands in a fresh copy of the product; return (combined output, rc)."""
    for name in ("orders.log",):
        (workdir / name).unlink(missing_ok=True)
    chunks: list[str] = []
    rc = 0
    for command in scenario["commands"]:
        res = subprocess.run([sys.executable, product_source.name, *command], cwd=workdir,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120)
        typed = shlex.join([product_source.name, *command])
        # The recorded transcript carries the command a user typed, never a temporary path.
        seen = (res.stdout + res.stderr).replace(str(workdir), "<run>").rstrip()
        chunks.append(f"$ python {typed}\n{seen}")
        rc = res.returncode
    return "\n".join(chunks), rc


def build_report(product_source: pathlib.Path, sandbox: pathlib.Path) -> dict:
    """Attack the product with the whole matrix and return the classified evidence report."""
    scenarios: list[dict] = []
    breakages: list[dict] = []
    for scenario in SCENARIOS:
        workdir = sandbox / scenario["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        copy = workdir / product_source.name
        copy.write_bytes(product_source.read_bytes())
        observed, rc = drive(copy, scenario, workdir)
        broke = bool(scenario["commands"]) and scenario["defect"](observed, rc)
        outcome = "broke" if broke else ("unverified" if not scenario["commands"] else "held")
        expect(outcome == EXPECTED_OUTCOMES[scenario["id"]],
               f"scenario {scenario['id']!r} must come out {EXPECTED_OUTCOMES[scenario['id']]!r}, "
               f"got {outcome!r}: {observed[-400:]!r}")
        scenarios.append({
            "id": scenario["id"], "goal": scenario["goal"],
            "interface": scenario["interface"],
            "actions": [{"action": "user_action",
                         "command": "python " + shlex.join([product_source.name, *command])}
                        for command in scenario["commands"]],
            "expected": scenario["expected"],
            "observed": observed or "the interface could not be reached from the fixture",
            "outcome": outcome,
            "classification": "no_defect" if outcome == "held" else scenario["classification"],
        })
        if broke:
            breakages.append({"scenario": scenario["id"],
                              "severity": SEVERITY[scenario["id"]],
                              "summary": SUMMARY[scenario["id"]]})
    return {
        "run_id": run_id_of(product_source.read_bytes()),
        "role": "factory-business-tester",
        "task_type": "implement",
        "fixture": FIXTURE_MARKER,
        "scenarios": scenarios,
        "breakages": breakages,
        "actions_were_user_level": True,
        "product_files_edited": 0,
        "debugger_used": False,
    }


def fixture_triples(report: dict) -> list[tuple[str, str, str]]:
    """The `(id, outcome, classification)` rows of a report: the fixture matrix comparison."""
    return [(s["id"], s["outcome"], s["classification"]) for s in report["scenarios"]]


def validate_report(report: object, fixture_matrix: list[tuple[str, str, str]] | None = None
                    ) -> list[str]:
    """Every invariant of the documented evidence shape; an empty list means a valid report.

    The SHAPE is the contract for any report a run wrote, so it is checked for all of them. Two
    extra rules apply on top:

    - a report carrying the `fixture` marker is this script's own self-check report, so its
      `(id, outcome, classification)` triples must equal `fixture_matrix` — the callers pass the
      built-in matrix, and an unknown marker value is a problem in itself. A report with NO marker
      is a real run's (its scenarios are the run's product, not this fixture's shop.py) and is
      judged on shape alone: demanding the fixture's triples of it would reject every real report;
    - the OPTIONAL structured keys a run may add (`actions`, `findings`, `edit_or_debugger_used`, a
      per-breakage `classification`) are validated WHEN PRESENT, so an extra key can never lie
      (a `findings` entry with an unknown severity or an `edit_or_debugger_used: true` is refused).
    """
    problems: list[str] = []
    if not isinstance(report, dict):
        return [f"the report must be a JSON object, got {type(report).__name__}"]
    if isinstance(report, (list, str, int, float, bool)) or report is None:
        return [f"the report must be a JSON object, got {type(report).__name__}: a list, a string or "
                f"a number is not an evidence report"]
    for key in FORBIDDEN_REPORT_KEYS:
        if key in report:
            problems.append(f"the report may never carry {key!r} — acceptance belongs to the "
                            "factory-tester, this report is diagnostic input")
    for key in ("run_id", "role", "task_type", "scenarios", "breakages",
                "actions_were_user_level", "product_files_edited", "debugger_used"):
        if key not in report:
            problems.append(f"the report is missing {key!r}")
    if problems:
        return problems
    marker = report.get("fixture")
    if marker is not None and marker != FIXTURE_MARKER:
        problems.append(f"an unknown `fixture` marker {marker!r}: only {FIXTURE_MARKER!r} marks the "
                        "built-in self-check report")
    if not isinstance(report["run_id"], str) or not RUN_ID_RE.match(report["run_id"]):
        problems.append(f"run_id must be '<YYYYMMDD>-<8 hex>', got {report['run_id']!r}")
    if report["role"] != "factory-business-tester":
        problems.append(f"role must be 'factory-business-tester', got {report['role']!r}")
    if report["task_type"] not in TASK_TYPES:
        problems.append(f"task_type must be one of {TASK_TYPES}, got {report['task_type']!r} — a "
                        "security_audit belongs to the factory-security-auditor")
    if report["actions_were_user_level"] is not True:
        problems.append(f"actions_were_user_level must be true, got "
                        f"{report['actions_were_user_level']!r}")
    if report["product_files_edited"] != 0 or isinstance(report["product_files_edited"], bool):
        problems.append(f"product_files_edited must be the number 0, got "
                        f"{report['product_files_edited']!r}")
    if report["debugger_used"] is not False:
        problems.append(f"debugger_used must be false, got {report['debugger_used']!r}")
    if "edit_or_debugger_used" in report and report["edit_or_debugger_used"] is not False:
        problems.append(f"edit_or_debugger_used must be false, got "
                        f"{report['edit_or_debugger_used']!r}")
    if "actions" in report:
        listed = report["actions"]
        if not isinstance(listed, list) or not all(isinstance(item, str) and item.strip()
                                                   for item in listed):
            problems.append("the optional `actions` recap must be a list of non-empty command "
                            "strings")

    scenarios = report["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        return problems + ["scenarios must be a non-empty list"]
    ids: list[str] = []
    for index, scenario in enumerate(scenarios):
        where = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            problems.append(f"{where} must be an object")
            continue
        for key in SCENARIO_KEYS:
            if key not in scenario:
                problems.append(f"{where} is missing {key!r}")
        if problems and any(key not in scenario for key in SCENARIO_KEYS):
            continue
        where = f"scenarios[{index}] ({scenario.get('id')!r})"
        valid_id = isinstance(scenario["id"], str) and bool(scenario["id"].strip())
        if not valid_id:
            problems.append(f"{where}: id must be a non-empty STRING — it is the key the whole "
                            f"report is cross-checked by, so a list or an object cannot be one")
        else:
            ids.append(scenario["id"])
        for key in ("id", "goal", "expected", "observed"):
            if not isinstance(scenario[key], str) or not scenario[key].strip():
                problems.append(f"{where}: {key!r} must be a non-empty string")
        if scenario["interface"] not in INTERFACES:
            problems.append(f"{where}: interface must be one of {INTERFACES}, got "
                            f"{scenario['interface']!r}")
        if scenario["outcome"] not in OUTCOMES:
            problems.append(f"{where}: outcome must be one of {OUTCOMES}, got "
                            f"{scenario['outcome']!r}")
        if scenario["classification"] not in CLASSIFICATIONS:
            problems.append(f"{where}: classification must be one of {CLASSIFICATIONS}, got "
                            f"{scenario['classification']!r}")
        actions = scenario["actions"]
        if not isinstance(actions, list):
            problems.append(f"{where}: actions must be a list")
        else:
            if scenario["outcome"] != "unverified" and not actions:
                problems.append(f"{where}: a scenario that was RUN must list its user actions")
            for act_index, action in enumerate(actions):
                if not isinstance(action, dict) or action.get("action") != "user_action":
                    problems.append(f"{where}: actions[{act_index}] must be "
                                    f"{{'action': 'user_action', ...}}")
                elif not isinstance(action.get("command"), str) or not action["command"].strip():
                    problems.append(f"{where}: actions[{act_index}] must name the command a user "
                                    "types")
        # The outcome and the classification may not contradict each other.
        if scenario["outcome"] == "held" and scenario["classification"] != "no_defect":
            problems.append(f"{where}: a HELD scenario is a proven pass and must be classified "
                            f"'no_defect', got {scenario['classification']!r}")
        if scenario["outcome"] == "broke" and scenario["classification"] == "no_defect":
            problems.append(f"{where}: a BROKEN scenario cannot be classified 'no_defect'")
        if scenario["outcome"] == "unverified" and scenario["classification"] == "no_defect":
            problems.append(f"{where}: an UNVERIFIED scenario is never a pass — it may not be "
                            "classified 'no_defect'")

    for scenario_id in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"scenario id {scenario_id!r} is reported more than once — every scenario "
                        "id is unique (a duplicate double-counts or hides a scenario)")

    breakages = report["breakages"]
    if not isinstance(breakages, list):
        return problems + ["breakages must be a list"]
    usable = [s for s in scenarios
              if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"].strip()]
    broken = {s["id"] for s in usable if s.get("outcome") == "broke"}
    covered: list[str] = []
    for index, breakage in enumerate(breakages):
        where = f"breakages[{index}]"
        if not isinstance(breakage, dict):
            problems.append(f"{where} must be an object")
            continue
        for key in BREAKAGE_KEYS:
            if key not in breakage:
                problems.append(f"{where} is missing {key!r}")
        if any(key not in breakage for key in BREAKAGE_KEYS):
            continue
        if not isinstance(breakage["scenario"], str) or not breakage["scenario"].strip():
            problems.append(f"{where}: scenario must be a non-empty STRING naming a reported "
                            f"scenario, got {breakage['scenario']!r}")
            covered.append(breakage["scenario"])
            continue
        if breakage["scenario"] not in ids:
            problems.append(f"{where}: scenario {breakage['scenario']!r} is not one of the "
                            "reported scenarios")
        if breakage["severity"] not in SEVERITIES:
            problems.append(f"{where}: severity must be one of {SEVERITIES}, got "
                            f"{breakage['severity']!r}")
        if not isinstance(breakage["summary"], str) or not breakage["summary"].strip():
            problems.append(f"{where}: summary must be one non-empty line")
        if "classification" in breakage:
            reported = {s["id"]: s.get("classification") for s in usable}
            if breakage["classification"] not in CLASSIFICATIONS:
                problems.append(f"{where}: classification must be one of {CLASSIFICATIONS}, got "
                                f"{breakage['classification']!r}")
            elif breakage["classification"] != reported.get(breakage["scenario"]):
                problems.append(f"{where}: the breakage classification "
                                f"{breakage['classification']!r} contradicts the scenario's "
                                f"{reported.get(breakage['scenario'])!r}")
        covered.append(breakage["scenario"])
    covered_strings = [c for c in covered if isinstance(c, str)]
    for scenario_id in sorted({c for c in covered_strings if covered_strings.count(c) > 1}):
        problems.append(f"scenario {scenario_id!r} carries "
                        f"{covered_strings.count(scenario_id)} breakage entries — exactly one "
                        "breakage is recorded per broken scenario")
    covered_ids = set(covered_strings)
    for scenario_id in sorted(broken - covered_ids):
        problems.append(f"scenario {scenario_id!r} broke but carries no breakage entry — every "
                        "broken scenario is reported")
    for scenario_id in sorted(covered_ids - broken):
        problems.append(f"scenario {scenario_id!r} carries a breakage entry but did not break")

    if "findings" in report:
        findings = report["findings"]
        if not isinstance(findings, list):
            problems.append("the optional `findings` list must be a JSON array")
        else:
            for index, finding in enumerate(findings):
                where = f"findings[{index}]"
                if not isinstance(finding, dict):
                    problems.append(f"{where} must be an object")
                    continue
                if finding.get("severity") not in SEVERITIES:
                    problems.append(f"{where}: severity must be one of {SEVERITIES}, got "
                                    f"{finding.get('severity')!r}")
                if finding.get("scenario") not in ids:
                    problems.append(f"{where}: scenario {finding.get('scenario')!r} is not one of "
                                    "the reported scenarios")
                text = finding.get("summary") or finding.get("observed")
                if not isinstance(text, str) or not text.strip():
                    problems.append(f"{where}: a finding needs a non-empty `summary` or `observed`")

    # The matrix comparison is the LAST check, and only for a report whose scenario rows are all
    # usable records: a malformed report must be reported as malformed, never crash the comparison.
    if fixture_matrix is not None and marker == FIXTURE_MARKER:
        rows = report["scenarios"]
        if isinstance(rows, list) and all(
                isinstance(row, dict) and all(key in row for key in ("id", "outcome",
                                                                     "classification"))
                for row in rows):
            shipped = fixture_triples(report)
            if shipped != fixture_matrix:
                problems.append(f"the marked fixture report no longer matches the built-in "
                                f"seeded-defect matrix (regenerate with --write --force): "
                                f"{shipped!r} != {fixture_matrix!r}")
    return problems


def classify(log_file: pathlib.Path) -> dict[str, str]:
    """Run the EXISTING router on a recorded output and return its key: value lines."""
    res = subprocess.run([sys.executable, str(ROUTER), "classify", "--log", str(log_file)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    expect(res.returncode == 0, f"error_router.py classify must work: {res.stderr!r}")
    fields: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key.strip()] = value.strip()
    return fields


def case_1_user_level_drive(product: pathlib.Path, sandbox: pathlib.Path) -> None:
    """(a) The product is attacked through its own CLI, and the pass is proven, not assumed."""
    scenario = next(s for s in SCENARIOS if s["id"] == "happy-path")
    workdir = sandbox / "case1"
    workdir.mkdir(parents=True, exist_ok=True)
    copy = workdir / product.name
    copy.write_bytes(product.read_bytes())
    observed, rc = drive(copy, scenario, workdir)
    expect(rc == 0 and "ok: 3 widget = 750" in observed,
           f"the ordinary order must hold: {observed!r}")
    for scenario in SCENARIOS:
        for command in scenario["commands"]:
            expect(command[0] in ("order", "report"),
                   f"a user command must name a product subcommand, not internals: {command!r}")
            expect(not any(part in ("-c", "import") for part in command),
                   f"the attack must never import the product: {command!r}")


def case_2_breakages_recovered() -> None:
    """(b) The seeded defects are all recovered — empty, malformed, huge, negative, repeated, order."""
    expect({s["id"] for s in SCENARIOS} == set(EXPECTED_OUTCOMES),
           "every seeded scenario must carry an expected outcome")
    kinds = {s["id"] for s in SCENARIOS}
    for needed in ("empty-qty", "malformed-qty", "huge-qty", "negative-qty", "repeated-commit",
                   "report-before-order"):
        expect(needed in kinds, f"the adversarial matrix must include {needed!r}")


def case_3_report_shape(report: dict) -> None:
    """(c) The report validates, and every invariant is enforced (no tautology, no free pass)."""
    card = CARD.read_text(encoding="utf-8")
    for key in (*SCENARIO_KEYS, *BREAKAGE_KEYS, "run_id", "role", "task_type", "breakages",
                "actions_were_user_level", "product_files_edited", "debugger_used"):
        expect(key in card, f"the card must document the report key {key!r} — this validator is "
                            "the card's shape, not a shape of its own")
    expect("factory-business-tester" in card and ".code-factory/logs/business-adversarial/" in card,
           f"the card must name the role and its evidence tree: {CARD}")
    problems = validate_report(report)
    expect(not problems, f"the built report must be valid: {problems!r}")
    expect(report["product_files_edited"] == 0 and report["debugger_used"] is False,
           "the report must state the boundaries the role is held to")
    expect(len(report["breakages"]) == sum(1 for s in report["scenarios"]
                                           if s["outcome"] == "broke"),
           f"every broken scenario needs exactly one breakage: {report['breakages']!r}")

    def mutate(**changes) -> dict:
        copy = json.loads(json.dumps(report))
        copy.update(changes)
        return copy

    def mutate_scenario(index: int, **changes) -> dict:
        copy = json.loads(json.dumps(report))
        copy["scenarios"][index].update(changes)
        return copy

    broken_index = next(i for i, s in enumerate(report["scenarios"]) if s["outcome"] == "broke")
    held_index = next(i for i, s in enumerate(report["scenarios"]) if s["outcome"] == "held")
    mutations = {
        "a missing key": {k: v for k, v in report.items() if k != "role"},
        "the wrong role": mutate(role="factory-tester"),
        "an out-of-scope task type": mutate(task_type="security_audit"),
        "a claimed acceptance verdict": mutate(verdict="PASS"),
        "an edited product file": mutate(product_files_edited=1),
        "a debugger": mutate(debugger_used=True),
        "non-user-level actions": mutate(actions_were_user_level=False),
        "a held scenario classified code_defect": mutate_scenario(
            held_index, classification="code_defect"),
        "a broken scenario classified no_defect": mutate_scenario(
            broken_index, classification="no_defect"),
        "an unverified pass": mutate_scenario(
            next(i for i, s in enumerate(report["scenarios"])
                 if s["outcome"] == "unverified"), classification="no_defect"),
        "an unknown outcome": mutate_scenario(held_index, outcome="passed"),
        "an empty action list on a run scenario": mutate_scenario(held_index, actions=[]),
        "an action that is not user-level": mutate_scenario(
            held_index, actions=[{"action": "import_module", "command": "import shop"}]),
        "a breakage for a scenario that held": mutate(
            breakages=report["breakages"] + [{"scenario": report["scenarios"][held_index]["id"],
                                              "severity": "minor", "summary": "phantom"}]),
        "a broken scenario with no breakage": mutate(breakages=[
            b for b in report["breakages"]
            if b["scenario"] != report["scenarios"][broken_index]["id"]]),
        "a duplicated breakage entry": mutate(
            breakages=report["breakages"] + [dict(report["breakages"][0])]),
        "a duplicated scenario id": mutate_scenario(
            held_index, id=report["scenarios"][broken_index]["id"]),
        "an unknown severity": mutate(breakages=[
            {**report["breakages"][0], "severity": "blocker"}] + report["breakages"][1:]),
        "a malformed run id": mutate(run_id="not-a-run-id"),
    }
    for what, mutated in mutations.items():
        expect(bool(validate_report(mutated)),
               f"the validator must reject {what} — otherwise the shape is not enforced: "
               f"{mutated!r:.200}")


def case_4_routing(report: dict, sandbox: pathlib.Path) -> None:
    """(d) A breakage routes through the EXISTING path to the coder; no separate budget exists."""
    scenario = next(s for s in report["scenarios"] if s["id"] == "huge-qty")
    expect(scenario["outcome"] == "broke" and scenario["classification"] == "code_defect",
           f"the seeded crash must be reported as a code defect: {scenario!r}")
    observed = next(b for b in report["scenarios"] if b["id"] == "huge-qty")["observed"]
    log = write(sandbox / "huge-qty.log", observed + "\n")
    fields = classify(log)
    expect(fields.get("route") == "coder",
           f"a business breakage must route to the coder through error_router.py, got "
           f"{fields.get('route')!r} ({fields!r})")
    expect(fields.get("category") == "ASSERTION",
           f"the observed crash must classify as ASSERTION, got {fields.get('category')!r}")
    expect(fields.get("pattern_id") not in (None, "-"),
           f"the route must come from a named pattern: {fields!r}")

    sys.path.insert(0, str(SCRIPTS))
    try:
        import delegation_gate  # noqa: PLC0415  (the gate's own budget table is the contract)
    finally:
        sys.path.remove(str(SCRIPTS))
    for role in ("business_tester", "factory-business-tester"):
        expect(role not in delegation_gate.BUDGETS,
               f"there is no separate business-tester retry budget — a broken product spends the "
               f"coder's budget: {delegation_gate.BUDGETS!r}")
    expect("coder" in delegation_gate.BUDGETS,
           f"the coder budget is the one a breakage spends: {delegation_gate.BUDGETS!r}")


def run_script(script: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run this self-test as a user would, with the arguments the flow tells the role to type."""
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


def real_run_report() -> dict:
    """A report shaped like a REAL run's: another product, different scenario ids, the optional keys.

    It carries NO `fixture` marker, so the only thing that may judge it is the documented shape — the
    regression this pins: the validator demanded its own shop.py triples and refused every real
    report a run could write.
    """
    return {
        "run_id": "20261103-1f4e9a2b",
        "role": "factory-business-tester",
        "task_type": "implement",
        "scenarios": [
            {"id": "cli-surface-help", "goal": "Every delivered tool answers --help",
             "interface": "cli",
             "actions": [{"action": "user_action", "command": "python agent_cli.py --help"}],
             "expected": "exit 0 and a readable synopsis", "observed": "exit 0, synopsis printed",
             "outcome": "held", "classification": "no_defect"},
            {"id": "evidence-validate-real-report", "goal": "Validate the run's own report",
             "interface": "cli",
             "actions": [{"action": "user_action", "command": "python verify_evidence.py report.json"}],
             "expected": "the shape-valid report passes", "observed": "exit 1, refused",
             "outcome": "broke", "classification": "contract_gap"},
            {"id": "gate-order-and-repeats", "goal": "Repeat a gate call out of order",
             "interface": "cli", "actions": [],
             "expected": "the second call is refused", "observed": "not executed: owner stopped",
             "outcome": "unverified", "classification": "environment"},
        ],
        "breakages": [{"scenario": "evidence-validate-real-report", "severity": "major",
                       "summary": "the validator refused a shape-valid report"}],
        "actions": ["python agent_cli.py --help"],
        "findings": [{"tool": "verify_evidence.py", "severity": "major",
                      "scenario": "evidence-validate-real-report", "observed": "exit 1"}],
        "actions_were_user_level": True,
        "product_files_edited": 0,
        "debugger_used": False,
        "edit_or_debugger_used": False,
        "summary": "two scenarios were run: the CLI surface held, the validator broke",
    }


def case_5_evidence_file(report: dict, script: pathlib.Path, sandbox: pathlib.Path) -> None:
    """(e) `--evidence` judges by SHAPE; only the marked fixture is matrix-checked; --write refuses."""
    fixture = write(sandbox / "fixture.json", json.dumps(report, indent=1) + "\n")
    res = run_script(script, "--evidence", str(fixture), "--no-drive")
    expect(res.returncode == 0, f"the marked fixture evidence must pass: {res.stdout[-400:]!r} "
                                f"{res.stderr[-400:]!r}")

    real = real_run_report()
    real_path = write(sandbox / "real-run.json", json.dumps(real, indent=1) + "\n")
    res = run_script(script, "--evidence", str(real_path), "--no-drive")
    expect(res.returncode == 0,
           f"a real run's shape-valid report must pass — its scenario ids are the run's, not the "
           f"fixture's: {res.stdout[-400:]!r} {res.stderr[-400:]!r}")

    def rejected(what: str, payload: dict) -> None:
        path = write(sandbox / f"mutated-{len(list(sandbox.iterdir()))}.json",
                     json.dumps(payload, indent=1) + "\n")
        res = run_script(script, "--evidence", str(path), "--no-drive")
        expect(res.returncode == 1, f"{what} must be rejected: {res.stdout[-300:]!r}")
        expect("FAIL - " in res.stdout + res.stderr,
               f"the rejection of {what} must say what is wrong: {res.stdout!r} {res.stderr!r}")

    def mutated(**changes) -> dict:
        copy = json.loads(json.dumps(real))
        copy.update(changes)
        return copy

    rejected("a report claiming an edited product", mutated(product_files_edited=3))
    rejected("a report with a used debugger", mutated(edit_or_debugger_used=True))
    rejected("a findings entry with an unknown severity", mutated(
        findings=[{"tool": "verify_evidence.py", "severity": "blocker",
                   "scenario": "cli-surface-help", "observed": "x"}]))
    rejected("an `actions` recap that is not a list of commands", mutated(actions=[{"cmd": "x"}]))
    rejected("a breakage classification contradicting its scenario", mutated(
        breakages=[{"scenario": "evidence-validate-real-report", "severity": "major",
                    "summary": "x", "classification": "no_defect"}]))
    # The fixture report IS matrix-checked: moving one outcome away from the seeded defect must fail.
    drifted = json.loads(json.dumps(report))
    drifted["scenarios"][1]["outcome"] = "held"
    drifted["scenarios"][1]["classification"] = "no_defect"
    drifted["breakages"] = [b for b in drifted["breakages"]
                            if b["scenario"] != report["scenarios"][1]["id"]]
    rejected("marked fixture evidence that drifts from the seeded matrix", drifted)

    # (R1-11) A report that is not even an OBJECT, or whose marked scenarios are malformed, must be
    # REFUSED with a shape error — never crash the validator before it says what is wrong.
    for label, payload in (("a JSON list", [1, 2, 3]), ("a JSON string", "not a report"),
                           ("a JSON number", 42), ("JSON null", None)):
        path = write(sandbox / f"container-{label.split()[-1]}.json",
                     json.dumps(payload) + "\n")
        res = run_script(script, "--evidence", str(path), "--no-drive")
        expect(res.returncode == 1, f"{label} must be refused: {res.stdout[-300:]!r}")
        expect("Traceback" not in res.stdout + res.stderr,
               f"{label} must not crash the validator: {res.stderr[-400:]!r}")
        expect("must be a JSON object" in res.stdout + res.stderr,
               f"{label} must be named as a non-object report: {res.stderr!r}")
    malformed_rows = [
        ("a marked report whose scenarios are not objects", [1, 2]),
        ("a marked report whose scenario lacks the keys triples need", [{"id": "x"}]),
        ("a marked report with no scenarios list", "nope"),
    ]
    # (R2-3) A scenario id (or a breakage's scenario) that is not a STRING is a shape violation:
    # putting a list/object into the id sets and maps would crash the validator instead of naming
    # what is wrong.
    id_cases = [
        ("a scenario id that is a list", "scenarios", [{"id": ["a"], "goal": "g", "interface": "cli",
                                                        "actions": [], "expected": "e",
                                                        "observed": "o", "outcome": "unverified",
                                                        "classification": "environment"}]),
        ("a scenario id that is an object", "scenarios",
         [{"id": {"a": 1}, "goal": "g", "interface": "cli", "actions": [], "expected": "e",
           "observed": "o", "outcome": "unverified", "classification": "environment"}]),
        ("a breakage naming its scenario with a list", "breakages",
         [{"scenario": ["cli-surface-help"], "severity": "major", "summary": "s"}]),
    ]
    for label, key, value in id_cases:
        payload = json.loads(json.dumps(real))
        payload[key] = value
        path = write(sandbox / "bad-id.json", json.dumps(payload, indent=1) + chr(10))
        res = run_script(script, "--evidence", str(path), "--no-drive")
        expect(res.returncode == 1, f"{label} must be refused: {res.stdout[-300:]!r}")
        expect("Traceback" not in res.stdout + res.stderr,
               f"{label} must not crash the validator: {res.stderr[-400:]!r}")
        expect("STRING" in res.stdout + res.stderr,
               f"{label} must be named as a non-string id: {res.stderr!r}")

    for label, rows in malformed_rows:
        payload = json.loads(json.dumps(real))
        payload["fixture"] = FIXTURE_MARKER
        payload["scenarios"] = rows
        path = write(sandbox / "malformed-marked.json", json.dumps(payload, indent=1) + "\n")
        res = run_script(script, "--evidence", str(path), "--no-drive")
        expect(res.returncode == 1, f"{label} must be refused: {res.stdout[-300:]!r}")
        expect("Traceback" not in res.stdout + res.stderr,
               f"{label} must not crash the validator: {res.stderr[-400:]!r}")

    # `--write` may never silently clobber a file that holds a real run's evidence.
    before = real_path.read_bytes()
    res = run_script(script, "--write", "--evidence", str(real_path))
    expect(res.returncode == 1,
           f"--write must REFUSE to overwrite an existing report: {res.stdout[-300:]!r}")
    expect("--force" in res.stdout + res.stderr,
           f"the refusal must name the escape hatch: {res.stdout!r} {res.stderr!r}")
    expect(real_path.read_bytes() == before, "a refused --write must leave the file untouched")
    res = run_script(script, "--write", "--force", "--evidence", str(real_path), "--no-drive")
    expect(res.returncode == 0, f"--write --force must regenerate: {res.stdout[-400:]!r} "
                                f"{res.stderr[-400:]!r}")
    regenerated = json.loads(real_path.read_text(encoding="utf-8"))
    expect(regenerated.get("fixture") == FIXTURE_MARKER,
           "only an explicit --write --force replaces a report, and it writes the marked fixture")
    expect(not validate_report(regenerated, fixture_triples(report)),
           f"the regenerated fixture report must validate: {regenerated!r:.200}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", metavar="JSON", default=None,
                        help="the evidence report to validate; a report without the `fixture` "
                             "marker is judged on its documented shape alone (a missing file is "
                             "written from the fixture, so a fresh clone works)")
    parser.add_argument("--write", action="store_true",
                        help="regenerate the fixture self-check report; REFUSES to overwrite an "
                             "existing file unless --force is given")
    parser.add_argument("--force", action="store_true",
                        help="allow --write to replace an existing report")
    parser.add_argument("--no-drive", action="store_true",
                        help="validate --evidence only (used by the self-test on its own output)")
    args = parser.parse_args(argv)

    try:
        if args.write:
            evidence: pathlib.Path | None = (pathlib.Path(args.evidence) if args.evidence
                                             else DEFAULT_EVIDENCE)
        else:
            evidence = pathlib.Path(args.evidence) if args.evidence else None
        if args.write and evidence.exists() and not args.force:
            raise AssertionError(f"refusing to overwrite {evidence}: it may hold a REAL run's "
                                 "evidence and this script only writes its own fixture report. "
                                 "Re-run with --write --force to replace it.")
        if args.no_drive and evidence is None:
            raise AssertionError("--no-drive validates a report: pass --evidence <path>")

        with tempfile.TemporaryDirectory() as tmp:
            sandbox = pathlib.Path(tmp)
            product = write(sandbox / "product" / "shop.py", PRODUCT)
            before = digest(product)
            report = build_report(product, sandbox / "runs")
            expect(digest(product) == before,
                   "the attack must never edit a product file (the copy changed)")
            expect(not validate_report(report, fixture_triples(report)),
                   "the fixture report this script builds must satisfy its own shape")

            if evidence is not None:
                if args.write or not evidence.exists():
                    write(evidence, json.dumps(report, indent=1) + "\n")
                try:
                    stored = json.loads(evidence.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise AssertionError(f"{evidence} is not readable JSON: {exc}") from exc
                # The matrix comparison applies to THIS script's own marked report only: a real
                # run's report has the run's scenarios and is judged on the documented shape.
                problems = validate_report(
                    stored, fixture_triples(report)
                    if isinstance(stored, dict)
                    and stored.get("fixture") == FIXTURE_MARKER else None)
                expect(not problems, f"{evidence} is not a valid evidence report: {problems!r}")
            if args.no_drive:
                print(f"PASS - {evidence} carries the documented business-tester evidence shape "
                      f"(and, when marked, the exact seeded-defect matrix)")
                return 0

            case_1_user_level_drive(product, sandbox)
            print("PASS 1 - the product is attacked through its own CLI in a throwaway copy: the "
                  "ordinary order HOLDS (a proven pass) and no product file is touched")
            case_2_breakages_recovered()
            print("PASS 2 - the adversarial matrix reproduces every seeded defect: empty, "
                  "malformed, huge, negative, repeated (double submit) and out-of-order input")
            case_3_report_shape(report)
            print("PASS 3 - the evidence report carries the documented shape, the card and the "
                  "validator agree on every key, and all 19 mutated reports are rejected")
            case_4_routing(report, sandbox)
            print("PASS 4 - the breakage routes through error_router.py to the coder (ASSERTION, "
                  "a named pattern) and there is no separate business-tester retry budget")
            case_5_evidence_file(report, pathlib.Path(__file__).resolve(), sandbox)
            print("PASS 5 - `--evidence` accepts any shape-valid report (a real run's included) "
                  "while only the marked fixture is matrix-checked, every mutated shape is "
                  "rejected, and --write refuses to clobber a report without --force")
    except AssertionError as exc:
        print(f"FAIL - {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Contract test for `gate_all.py` — one aggregator for the factory's deterministic gates (zero tokens).

WHY THIS EXISTS

Every deterministic gate of the factory used to be invoked by prose in the flow, so a SKIPPED gate
was invisible: the run report said what the agent chose to say. This aggregator runs every gate that
APPLIES to a phase, records each one and fails when a gate that should have run left no record. The
test pins exactly that:

  - the APPLICABILITY MATRIX: phase K runs the diff gate, the English-only scan, the run-id check and
    the rulebook reconciler; phase Y adds the action audit and the manifest audit; the optional
    permit/delegation audits are recorded `not present: skipped` with the reason (never a failure),
    and the diff gate is skipped for a `review` task;
  - a gate that IS present and FAILS propagates (exit 1) and is named in the record;
  - a MISSING record (or a record missing the row of an applicable gate) is a failure, and a record
    naming a gate that does not apply is a failure too;
  - the record format: a `run_id:` line, the fixed five-column table, one row per gate in the gate
    table's order, deterministic across runs;
  - the CLI contract: `--phase` only K|Y (usage error otherwise), a malformed diff range is exit 2,
    `--help` survives a legacy console code page, no traceback anywhere.

The fixture is a repository that carries a DEPLOYED factory (the rulebook and its carriers copied
from this tree, as `prepare_factory` would) plus a git history, a WIP checkpoint, a manifest and a
session wire — so every gate of the phase has real input instead of a mock.

Exit code 0 = every assertion passes, 1 = the aggregator did not behave as the contract says.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gate_all  # noqa: E402  (the gate table is read directly by the availability pins)

TOOL = pathlib.Path(__file__).with_name("manifest.py")
GATE = pathlib.Path(__file__).with_name("gate_all.py")
ACTIONS = pathlib.Path(__file__).with_name("action_gate.py")
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}
RUN_ID = "20261103-8e939171"
# The deployed factory documents the rulebook's reconciler reads (copied verbatim: a fixture may not
# weaken the rulebook it is checked against).
FACTORY_DOCS = ("AGENTS.md", ".agents/README.md", ".agents/agents/code-factory.md",
                ".agents/skills/code-factory/SKILL.md")
FACTORY_DIRS = (".agents/agents/sub-agents", ".agents/skills/code-factory/references")
GATE_NAMES = ("input-validation", "english-only", "run-id", "factory-rules", "action-audit",
              "manifest-audit", "delegation-audit", "permit-audit")


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GATE), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stdout and "Traceback" not in res.stderr,
          f"{label}: no traceback allowed: {res.stderr!r}")


def git(root: pathlib.Path, *args: str) -> None:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    check(res.returncode == 0, f"git {' '.join(args)} failed: {res.stderr!r}")


def copy_factory(root: pathlib.Path) -> None:
    for rel in FACTORY_DOCS:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    for rel in FACTORY_DIRS:
        shutil.copytree(REPO_ROOT / rel, root / rel)


def session(home: pathlib.Path, repo: pathlib.Path, commands: list[str]) -> pathlib.Path:
    """A fixture session for `repo` whose wire records `commands` as executed shell calls."""
    directory = (home / ".kimi-code" / "sessions" / "wd_fixture"
                 / "session_11111111-1111-4111-8111-111111111111")
    (directory / "agents" / "main").mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(json.dumps({
        "id": "session_11111111-1111-4111-8111-111111111111",
        "cwd": str(repo).replace("\\", "/"), "archived": False,
        "agents": {"main": {"type": "main"}}}), encoding="utf-8")
    events = [{"type": "tool.call", "tool": "shell", "arguments": {"command": command}}
              for command in commands]
    (directory / "agents" / "main" / "wire.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    return directory


def deployed_repo(tmp: pathlib.Path, name: str = "repo", task_type: str = "implement",
                  home: pathlib.Path | None = None) -> pathlib.Path:
    """A repository with a deployed factory, a checkpoint, a manifest and a session wire."""
    root = tmp / name
    root.mkdir(parents=True)
    copy_factory(root)
    (root / ".code-factory" / "state").mkdir(parents=True, exist_ok=True)
    (root / ".code-factory" / "state" / "pipeline.yaml").write_text(
        f"run_id: {RUN_ID}\ntask_type: {task_type}\nphase: w2\nstatus: in_progress\n",
        encoding="utf-8")
    # A real run always has its APPROVED PLAN, and the permit audit answers plan tasks: the fixture
    # carries one (a factory without a plan cannot be permit-audited at all).
    (root / ".code-factory" / "state" / "plan.md").write_text(
        "## Tasks (DAG)\n\n- task_01: the fixture task. files: src/a.py; deps: []; verify: true\n",
        encoding="utf-8")
    env = {**os.environ}
    subprocess.run([sys.executable, str(TOOL), "init", "--repo", str(root)], capture_output=True,
                   env=env)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "-q", "-m", "base")
    if home is not None:
        session(home, root, ["git status"])
    return root


def env_for(home: pathlib.Path) -> dict:
    """The CLI's wire root follows the user profile, so the fixture home is injected that way."""
    return {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}


def record_of(root: pathlib.Path, phase: str) -> str:
    return (root / ".code-factory" / "logs" / f"gate-{phase}.md").read_text(encoding="utf-8")


def rows_of(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in ("gate", "---"):
            continue
        rows[cells[0]] = cells
    return rows


# --------------------------------------------------------------------------------------------
# The applicability matrix
# --------------------------------------------------------------------------------------------

def test_applicability(tmp: pathlib.Path) -> None:
    home = tmp / "home-k"
    home.mkdir()
    root = deployed_repo(tmp, "k", home=home)

    res = run("--repo", str(root), "--phase", "K", env=env_for(home))
    expect_clean_cli(res, 0, "phase K")
    text = record_of(root, "K")
    check(text.splitlines()[0] == f"run_id: {RUN_ID}",
          f"the record must attribute itself to the run: {text.splitlines()[:2]!r}")
    check("| gate | exit | applicability | ran_at | command |" in text,
          f"the record must carry the documented table: {text!r}")
    rows = rows_of(text)
    check(list(rows) == list(GATE_NAMES),
          f"every gate of the table must have exactly one row, in order: {list(rows)!r}")
    for name in ("input-validation", "english-only", "run-id", "factory-rules", "permit-audit"):
        check(rows[name][1] == "0", f"{name} must have run and passed in phase K: {rows[name]}")
    check(rows["input-validation"][2].startswith("applicable"),
          f"the diff gate applies to an implement run: {rows['input-validation']}")
    for name in ("action-audit", "manifest-audit"):
        check(rows[name][1] == "skipped" and "phase K" in rows[name][2],
              f"{name} belongs to phase Y: {rows[name]}")
    check(rows["delegation-audit"][1] == "skipped" and
          "not applicable in phase K" in rows["delegation-audit"][2],
          f"the Y-only delegation audit does not run in phase K: {rows['delegation-audit']}")
    # An optional gate is picked up the moment its script advertises the subcommand — that is how
    # `permit_gate.py` joined the table — so no gate is "not present" any more. The three
    # availability branches are pinned on the table itself below.
    check(rows["permit-audit"][2] == "applicable",
          f"the permit audit applies to both phases: {rows['permit-audit']}")
    check("PASS" in res.stdout, f"the run must report its verdict: {res.stdout!r}")

    # The record is deterministic across runs (only `ran_at` may differ).
    first = {name: cells[:2] + cells[2:] for name, cells in rows.items()}
    res = run("--repo", str(root), "--phase", "K", env=env_for(home))
    expect_clean_cli(res, 0, "phase K (second run)")
    second = rows_of(record_of(root, "K"))
    check(set(second) == set(first), "a second run records the same gates")
    for name in first:
        check(second[name][1] == first[name][1] and second[name][2] == first[name][2],
              f"the {name} row must be stable across runs: {first[name]} vs {second[name]}")

    # Phase Y adds the audit gates, on a repo whose session wire holds only a harmless command.
    home_y = tmp / "home-y"
    home_y.mkdir()
    repo_y = deployed_repo(tmp, "y", home=home_y)
    res = run("--repo", str(repo_y), "--phase", "Y", env=env_for(home_y))
    expect_clean_cli(res, 0, "phase Y")
    rows = rows_of(record_of(repo_y, "Y"))
    for name in ("input-validation", "english-only", "run-id", "factory-rules", "action-audit",
                 "manifest-audit", "delegation-audit", "permit-audit"):
        check(rows[name][1] == "0", f"{name} must have run and passed in phase Y: {rows[name]}")
    # The two W3 audits are REAL now: their scripts advertise `audit`, so the Y phase runs them.
    check(rows["delegation-audit"][2] == "applicable" and rows["permit-audit"][2] == "applicable",
          f"the delegation and permit audits belong to phase Y: {rows['delegation-audit']} / "
          f"{rows['permit-audit']}")

    # …and the Y record is itself a run-id-bearing artifact, so a LATER phase still passes run-id.
    res = run("--repo", str(repo_y), "--phase", "K", env=env_for(home_y))
    expect_clean_cli(res, 0, "phase K after a Y record exists")
    check(rows_of(record_of(repo_y, "K"))["run-id"][1] == "0",
          "the gate record must carry a run_id line, so it is attributed and does not break the "
          "run-id gate")

    # A review task produces no change range: the diff gate is SKIPPED with that reason.
    home_r = tmp / "home-r"
    home_r.mkdir()
    review = deployed_repo(tmp, "review", task_type="review", home=home_r)
    res = run("--repo", str(review), "--phase", "K", env=env_for(home_r))
    expect_clean_cli(res, 0, "phase K of a review run")
    row = rows_of(record_of(review, "K"))["input-validation"]
    check(row[1] == "skipped" and "task_type review" in row[2],
          f"the diff gate does not apply to a review run: {row}")


# --------------------------------------------------------------------------------------------
# A failing gate propagates
# --------------------------------------------------------------------------------------------

def test_failure_propagates(tmp: pathlib.Path) -> None:
    home = tmp / "home-f"
    home.mkdir()
    root = deployed_repo(tmp, "failing", home=home)

    # Break the manifest audit: a registered changed file drifts after its registration.
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (root / ".code-factory" / "backups" / "src").mkdir(parents=True)
    (root / ".code-factory" / "backups" / "src" / "a.py").write_text("a = 0\n", encoding="utf-8")
    added = subprocess.run([sys.executable, str(TOOL), "add", "--repo", str(root),
                            "--changed", "src/a.py"], capture_output=True, text=True)
    check(added.returncode == 0, f"the manifest fixture must register the file: {added.stderr!r}")
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    res = run("--repo", str(root), "--phase", "Y", env=env_for(home))
    expect_clean_cli(res, 1, "phase Y with a drifted manifest")
    check("FAIL" in res.stdout, f"the verdict must be reported: {res.stdout!r}")
    rows = rows_of(record_of(root, "Y"))
    check(rows["manifest-audit"][1] == "1",
          f"the failing gate must be recorded with its exit code: {rows['manifest-audit']}")
    check("manifest-audit" in res.stdout, f"the failure must name the gate: {res.stdout!r}")

    # A second, independent gate: a Cyrillic line in a shipped file fails the English-only scan.
    other_home = tmp / "home-e"
    other_home.mkdir()
    english = deployed_repo(tmp, "english", home=other_home)
    (english / "notes.md").write_text("\u041f\u0440\u0438\u0432\u0435\u0442\n", encoding="utf-8")
    git(english, "add", "-A")
    git(english, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "-q", "-m", "cy")
    res = run("--repo", str(english), "--phase", "K", env=env_for(other_home))
    expect_clean_cli(res, 1, "phase K with a Cyrillic shipped file")
    check(rows_of(record_of(english, "K"))["english-only"][1] == "1",
          "the English-only gate must be recorded as failed")


# --------------------------------------------------------------------------------------------
# The record is the artifact: a missing record (or row) is a failure
# --------------------------------------------------------------------------------------------

def test_record_verification(tmp: pathlib.Path) -> None:
    home = tmp / "home-v"
    home.mkdir()
    root = deployed_repo(tmp, "verify", home=home)
    expect_clean_cli(run("--repo", str(root), "--phase", "K", env=env_for(home)), 0, "phase K")

    record = root / ".code-factory" / "logs" / "gate-K.md"
    res = run("--repo", str(root), "--phase", "K", "--verify-only", str(record))
    expect_clean_cli(res, 0, "verify an intact record")

    # A record that lost a row of an applicable gate.
    text = record.read_text(encoding="utf-8")
    missing = "\n".join(line for line in text.splitlines()
                        if not line.startswith("| english-only ")) + "\n"
    record.write_text(missing, encoding="utf-8")
    res = run("--repo", str(root), "--phase", "K", "--verify-only", str(record))
    expect_clean_cli(res, 1, "verify a record missing an applicable gate")
    check("english-only" in res.stdout and "no record" in res.stdout,
          f"the missing gate must be named: {res.stdout!r}")

    # A record naming a gate that does not apply to the phase.
    extra = ("\n| manifest-audit | 0 | applicable | 2026-11-03T00:00:00Z | manifest.py audit |")
    record.write_text(text.replace("\n| permit-audit ", extra + "\n| permit-audit "), encoding="utf-8")
    res = run("--repo", str(root), "--phase", "K", "--verify-only", str(record))
    expect_clean_cli(res, 1, "verify a record naming a gate of another phase")
    check("does not apply in phase K" in res.stdout, f"the reason must be stated: {res.stdout!r}")

    # A record with a failing gate is a failed phase.
    record.write_text(text.replace("| run-id | 0 |", "| run-id | 1 |"), encoding="utf-8")
    res = run("--repo", str(root), "--phase", "K", "--verify-only", str(record))
    expect_clean_cli(res, 1, "verify a record with a failed gate")
    check("exit 1" in res.stdout, f"the recorded failure must be named: {res.stdout!r}")

    # NO record at all for a phase that should have one.
    absent = root / ".code-factory" / "logs" / "gate-Y.md"
    res = run("--repo", str(root), "--phase", "Y", "--verify-only", str(absent))
    expect_clean_cli(res, 1, "verify a missing record")
    check("no gate record" in res.stdout, f"the absence must be named: {res.stdout!r}")
    check("action-audit" in res.stdout,
          f"the gates that should have run must be listed: {res.stdout!r}")


# --------------------------------------------------------------------------------------------
# The CLI contract
# --------------------------------------------------------------------------------------------

def test_gate_availability() -> None:
    """A missing optional gate is `not present: skipped`; one that ships without the subcommand too.

    No file has to be removed for this: the branches are asked of `gate_available` directly, and
    BOTH reasons are exact — a gate nobody wrote, and a script that exists but does not advertise
    the subcommand the table would call.
    """
    missing = gate_all.Gate("ghost-audit", "no_such_gate.py", ("Y",), ("audit", "--repo", "{repo}"),
                            optional=True)
    available, reason = gate_all.gate_available(missing)
    check(available is False and reason.startswith("not present") and "not shipped" in reason,
          f"a gate whose script does not exist must be skipped with its reason: {reason!r}")
    no_subcommand = gate_all.Gate("ghost-sub", "delegation_gate.py", ("Y",),
                                  ("no-such-subcommand", "--repo", "{repo}"), optional=True)
    available, reason = gate_all.gate_available(no_subcommand)
    check(available is False and "advertises no" in reason,
          f"a script without the subcommand must be skipped with its reason: {reason!r}")
    required = gate_all.Gate("required", "run_id.py", ("K",), ("check", "--dir", ".x"))
    check(gate_all.gate_available(required) == (True, ""),
          "a non-optional gate is available whenever its script ships")


def test_cli_contract(tmp: pathlib.Path) -> None:
    root = tmp / "cli"
    root.mkdir()
    expect_clean_cli(run("--help"), 0, "--help")
    check("--phase" in run("--help").stdout, "the help must document --phase")
    expect_clean_cli(run("--repo", str(root), "--phase", "Z"), 2, "an unknown phase")
    expect_clean_cli(run("--repo", str(root)), 2, "a missing --phase")
    expect_clean_cli(run("--phase", "K"), 2, "a missing --repo")
    expect_clean_cli(run("--repo", str(tmp / "nope"), "--phase", "K"), 2,
                     "an unusable --repo")
    expect_clean_cli(run("--repo", str(root), "--phase", "K", "--diff", "HEAD"), 2,
                     "a one-sided --diff")
    expect_clean_cli(run("--repo", str(root), "--phase", "K", "--diff", "x", "y"), 2,
                     "a diff range of refs that do not resolve")
    check("Traceback" not in run("--repo", str(root), "--phase", "K").stderr,
          "a repository without a checkpoint must not raise a traceback")
    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_applicability(tmp)
        test_failure_propagates(tmp)
        test_record_verification(tmp)
        test_gate_availability()
        test_cli_contract(tmp)

    print("PASS - gate_all.py runs every deterministic gate that applies to a phase: phase K runs "
          "the input-validation diff gate (implement/refactor only), the English-only scan, the "
          "run-id check and the rulebook reconciler; phase Y adds the action audit and the manifest "
          "audit; an optional gate that is not shipped is recorded `not present: skipped` with its "
          "reason while a present gate that fails propagates exit 1; every gate gets one row in the "
          "deterministic, run-id-bearing record, and a missing record (or a missing/failing/"
          "inapplicable row) is a failure; an unknown phase and a malformed diff range are exit-2 "
          "usage errors without a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

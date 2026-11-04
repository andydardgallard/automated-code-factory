#!/usr/bin/env python3
"""
Contract test for `delegation_gate.py` — the pre-delegation retry-budget gate (zero LLM tokens).

WHY THIS EXISTS

The rulebook gives every role a retry budget and keeps the counters in
`.code-factory/state/pipeline.yaml`. Before this gate the counter was self-reported: whoever
delegated a role also wrote the number, so nothing refused a third reviewer pass. The gate must be
the one that COUNTS — it increments `retry_counters.<role>` itself and refuses once the budget is
exhausted — and this test proves exactly that, with the fixtures of the review that asked for it.

COVERED, all through the shipped CLI (a subprocess, like the flow calls it):

  - `init` materializes the `retry_counters` block for every budgeted role at 0, keeps existing
    values, is idempotent and never creates a second block;
  - `check` increments the counter once per allowed delegation and REFUSES the delegation that
    would exceed the budget WITHOUT incrementing it (the failing-first pin: the third reviewer
    delegation of a budget of 2);
  - the refusal is the mode's: hitl instructs the `AskUserQuestion` owner stop, auto names the
    FAILED-run reason and has NO override (`--owner-authorized` is an input error there);
  - `--owner-authorized` (hitl) grants EXACTLY ONE extra delegation PER owner decision: every
    authorized call at the ceiling records its own timestamped note, so N recorded decisions allow
    budget + N delegations, while an UNauthorized call at that ceiling is refused;
  - the per-role budgets are enforced (coder=1, reviewer=2, infrastructure=3);
  - the inputs are validated: an unbudgeted/unknown role, a missing checkpoint, a missing
    `retry_counters` block, and a counter that is not a non-negative integer (bool / negative /
    numeric string / junk) are exit-2 errors with an actionable message and never a traceback;
  - the write is surgical (unrelated keys and comments survive, CRLF is kept) and atomic (no
    `*.tmp` file is left behind);
  - the argparse contract: `--help` exit 0 for every command, a usage error exit 2, no traceback,
    and the help survives a legacy console code page.

Exit code 0 = every assertion passes, 1 = the gate did not behave as the contract says.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("delegation_gate.py")
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
BUDGETS = {"coder": 1, "ba": 2, "planner": 2, "diagnostician": 1, "advisor": 1,
           "infrastructure": 3, "reviewer": 2}
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

CHECKPOINT = """\
run_id: 20261103-8e939171
phase: "5-implement-W2"
status: in_progress
updated_at: "2026-11-03T20:00:00+03:00"
files_touched: []
pending_decision: null
resume_hint: "keep this line byte-identical: the gate edits ONE counter"
retry_counters:
  coder: 0
  ba: 0
  planner: 0
  diagnostician: 0
  advisor: 0
  infrastructure: 0
  reviewer: 0
models_used:
  main: kimi-code/k3
"""


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def repo(tmp: pathlib.Path, name: str, text: str = CHECKPOINT) -> pathlib.Path:
    """A throwaway repository holding a WIP checkpoint with `text`."""
    root = tmp / name
    path = root / PIPELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return root


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def gate(root: pathlib.Path, role: str, mode: str = "hitl", *extra: str,
         env: dict | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
    """One `check` call plus the parsed JSON verdict (an empty dict when it printed none)."""
    res = run("check", "--repo", str(root), "--role", role, "--mode", mode, *extra, env=env)
    try:
        verdict = json.loads(res.stdout)
    except json.JSONDecodeError:
        verdict = {}
    return res, verdict


def counters(root: pathlib.Path) -> dict[str, int]:
    """The counters the checkpoint really carries (read by the shipped gate, not by this test)."""
    res = run("init", "--repo", str(root))
    check(res.returncode == 0, f"init must read the counters: {res.stdout!r} {res.stderr!r}")
    return json.loads(res.stdout)["counters"]


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: no traceback allowed: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# init: the block is materialized only on request
# --------------------------------------------------------------------------------------------

def test_init(tmp: pathlib.Path) -> None:
    headerless = CHECKPOINT.split("retry_counters:")[0] + "models_used:\n  main: kimi-code/k3\n"
    root = repo(tmp, "init", headerless)

    # A checkpoint without the block FAILS the gate with the one command that fixes it.
    res, verdict = gate(root, "coder")
    expect_clean_cli(res, 2, "check without a retry_counters block")
    check("init" in res.stderr and "retry_counters" in res.stderr,
          f"the error must name the block and the fix: {res.stderr!r}")
    check(verdict == {}, f"an input error prints no verdict: {res.stdout!r}")

    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init")
    payload = json.loads(res.stdout)
    check(payload["status"] == "initialized", f"the first init initializes: {payload}")
    check(payload["counters"] == {role: 0 for role in BUDGETS},
          f"every budgeted role starts at 0: {payload['counters']}")
    text = (root / PIPELINE_REL).read_text(encoding="utf-8")
    check(text.count("retry_counters:") == 1,
          f"init must never create a second block: {text!r}")
    check("resume_hint: \"keep this line byte-identical" in text,
          f"init must not touch the other keys: {text!r}")

    res = run("init", "--repo", str(root))
    expect_clean_cli(res, 0, "init (second run)")
    check(json.loads(res.stdout)["status"] == "unchanged",
          f"a second init is idempotent: {res.stdout!r}")
    check((root / PIPELINE_REL).read_text(encoding="utf-8") == text,
          "an idempotent init must not change a byte")

    # An existing value is kept, and a role that has no line yet is added.
    partial = repo(tmp, "init-partial", "run_id: 20261103-8e939171\nphase: w2\nstatus: in_progress\n"
                                        "updated_at: \"2026-11-03\"\nretry_counters:\n  coder: 1\n")
    res = run("init", "--repo", str(partial))
    expect_clean_cli(res, 0, "init with one existing counter")
    check(json.loads(res.stdout)["counters"]["coder"] == 1,
          f"an existing counter must be kept: {res.stdout!r}")
    check(json.loads(res.stdout)["counters"]["reviewer"] == 0,
          f"a missing counter must be added at 0: {res.stdout!r}")

    # A flow mapping on the header is normalized before members are written under it.
    flow = repo(tmp, "init-flow", "run_id: 20261103-8e939171\nretry_counters: {}\n")
    res = run("init", "--repo", str(flow))
    expect_clean_cli(res, 0, "init over a flow mapping")
    text = (flow / PIPELINE_REL).read_text(encoding="utf-8")
    check("retry_counters: {}\n  coder" not in text,
          f"a flow mapping must be normalized, not left holding children: {text!r}")
    check("retry_counters:\n  coder: 0" in text, f"the block form must be written: {text!r}")


# --------------------------------------------------------------------------------------------
# check: the counter is counted by the gate, and the exhausted budget REFUSES
# --------------------------------------------------------------------------------------------

def test_third_reviewer_is_refused(tmp: pathlib.Path) -> None:
    """THE failing-first pin: budget reviewer=2, so the third delegation is refused."""
    root = repo(tmp, "reviewer")
    first, v1 = gate(root, "reviewer")
    expect_clean_cli(first, 0, "reviewer delegation 1")
    check(v1["allow"] is True and v1["counter"] == 1 and v1["budget"] == 2,
          f"the first delegation is counted: {v1}")
    second, v2 = gate(root, "reviewer")
    expect_clean_cli(second, 0, "reviewer delegation 2")
    check(v2["allow"] is True and v2["counter"] == 2, f"the second delegation is counted: {v2}")

    before = (root / PIPELINE_REL).read_text(encoding="utf-8")
    third, v3 = gate(root, "reviewer")
    expect_clean_cli(third, 1, "reviewer delegation 3 (budget exhausted)")
    check(v3["allow"] is False, f"the third delegation must be REFUSED: {v3}")
    check(v3["counter"] == 2 and v3["budget"] == 2,
          f"a refused delegation must NOT increment the counter: {v3}")
    check("exhausted" in v3["reason"] and "reviewer" in v3["reason"],
          f"the reason must name the exhausted budget: {v3['reason']!r}")
    check((root / PIPELINE_REL).read_text(encoding="utf-8") == before,
          "a refusal must write nothing")
    check(counters(root)["reviewer"] == 2,
          "the checkpoint must still carry the two consumed delegations")

    # `--owner-authorized` in AUTO is an input error: auto has no override at all.
    res = run("check", "--repo", str(root), "--role", "reviewer", "--mode", "auto",
              "--owner-authorized")
    expect_clean_cli(res, 2, "--owner-authorized in auto")
    check("hitl" in res.stderr, f"the error must say where the flag belongs: {res.stderr!r}")


def test_mode_semantics(tmp: pathlib.Path) -> None:
    hitl_root = repo(tmp, "modes-hitl")
    for _ in range(2):
        gate(hitl_root, "reviewer")
    res, verdict = gate(hitl_root, "reviewer", "hitl")
    expect_clean_cli(res, 1, "hitl refusal")
    check("AskUserQuestion" in verdict["reason"],
          f"hitl must send the main agent to the owner stop: {verdict['reason']!r}")
    check(verdict["allow"] is False, f"hitl refusal is a refusal: {verdict}")

    auto_root = repo(tmp, "modes-auto")
    for _ in range(2):
        gate(auto_root, "reviewer", "auto")
    res, verdict = gate(auto_root, "reviewer", "auto")
    expect_clean_cli(res, 1, "auto refusal")
    check("FAILED" in verdict["reason"] and "no override" in verdict["reason"],
          f"auto must name the FAILED run and that there is no override: {verdict['reason']!r}")
    check("owner-authorized" not in verdict["reason"].replace("--owner-authorized", ""),
          f"auto must not offer the hitl override: {verdict['reason']!r}")


def test_owner_authorization(tmp: pathlib.Path) -> None:
    """Every owner decision grants ONE extra delegation, and every one is recorded.

    The bug this pins (found in live use): the gate treated `--owner-authorized` as a
    once-per-run flag, so a SECOND owner decision could not be honored although the refusal prose
    told the main agent to ask the owner again. The allowance is per DECISION: N recorded
    authorizations permit budget + N delegations, an unauthorized call at budget + N is refused,
    and each authorized call beyond the budget records a new timestamped note.
    """
    root = repo(tmp, "authorized")
    for _ in range(2):
        gate(root, "reviewer")

    # The FIRST owner decision: one extra delegation, recorded.
    res, verdict = gate(root, "reviewer", "hitl", "--owner-authorized")
    expect_clean_cli(res, 0, "the owner-authorized extra delegation")
    check(verdict["allow"] is True and verdict["counter"] == 3 and verdict["owner_authorized"],
          f"the owner grants ONE extra delegation: {verdict}")
    check(verdict.get("authorizations") == 1,
          f"the verdict must count the recorded authorization: {verdict}")
    text = (root / PIPELINE_REL).read_text(encoding="utf-8")
    check("owner_authorizations:" in text, f"the permission must be recorded: {text!r}")
    notes = [line for line in text.splitlines() if "role=reviewer" in line]
    check(len(notes) == 1 and "counter=3" in notes[0],
          f"the note must be timestamped and name the role and the counter: {notes!r}")
    check(any(part[:4].isdigit() and "T" in part for part in notes[0].split()),
          f"the note must carry a timestamp: {notes[0]!r}")

    # A SECOND owner decision (a new answer to a new AskUserQuestion): ONE more delegation.
    res, verdict = gate(root, "reviewer", "hitl", "--owner-authorized")
    expect_clean_cli(res, 0, "a SECOND owner-authorized delegation")
    check(verdict["allow"] is True and verdict["counter"] == 4,
          f"a new owner decision grants a new single extra delegation: {verdict}")
    check(verdict.get("authorizations") == 2,
          f"the second permission must be counted: {verdict}")
    text = (root / PIPELINE_REL).read_text(encoding="utf-8")
    notes = [line for line in text.splitlines() if "role=reviewer" in line]
    check(len(notes) == 2 and any("counter=4" in note for note in notes),
          f"every authorization is recorded as its own note: {notes!r}")

    # An UNauthorized call is still refused once budget + authorizations are used.
    before = (root / PIPELINE_REL).read_text(encoding="utf-8")
    res, verdict = gate(root, "reviewer", "hitl")
    expect_clean_cli(res, 1, "an unauthorized delegation beyond budget + authorizations")
    check(verdict["allow"] is False and verdict["counter"] == 4,
          f"an unauthorized call must be refused with the counter kept: {verdict}")
    check("exhausted" in verdict["reason"],
          f"the refusal must say the budget is exhausted: {verdict['reason']!r}")
    check((root / PIPELINE_REL).read_text(encoding="utf-8") == before,
          "a refused delegation must write nothing")

    # …and a THIRD owner decision is honored again (the ceiling follows the recorded decisions).
    res, verdict = gate(root, "reviewer", "hitl", "--owner-authorized")
    expect_clean_cli(res, 0, "a THIRD owner-authorized delegation")
    check(verdict["allow"] is True and verdict["counter"] == 5
          and verdict.get("authorizations") == 3,
          f"the allowance is budget + the recorded decisions: {verdict}")


def test_per_role_budgets(tmp: pathlib.Path) -> None:
    root = repo(tmp, "budgets")
    first, verdict = gate(root, "coder")
    expect_clean_cli(first, 0, "coder delegation 1")
    check(verdict["budget"] == 1, f"coder has a budget of 1: {verdict}")
    second, verdict = gate(root, "coder")
    expect_clean_cli(second, 1, "coder delegation 2 (budget exhausted)")
    check(verdict["allow"] is False and verdict["counter"] == 1,
          f"the coder budget is one delegation: {verdict}")

    infra = repo(tmp, "budgets-infra")
    for index in range(3):
        res, verdict = gate(infra, "infrastructure")
        expect_clean_cli(res, 0, f"infrastructure delegation {index + 1}")
        check(verdict["counter"] == index + 1, f"infrastructure counter: {verdict}")
    fourth, verdict = gate(infra, "infrastructure")
    expect_clean_cli(fourth, 1, "infrastructure delegation 4")
    check(verdict["allow"] is False and verdict["budget"] == 3,
          f"infrastructure has a budget of 3: {verdict}")


# --------------------------------------------------------------------------------------------
# Input validation: every bad input is a message + exit 2, never a traceback
# --------------------------------------------------------------------------------------------

def test_input_validation(tmp: pathlib.Path) -> None:
    root = repo(tmp, "inputs")

    res, verdict = gate(root, "business_tester")
    expect_clean_cli(res, 2, "an unbudgeted role")
    check("no retry budget" in res.stderr and "reviewer" in res.stderr,
          f"the error must name the budgeted roles: {res.stderr!r}")
    check(verdict == {}, "an unbudgeted role prints no verdict")

    expect_clean_cli(run("check", "--repo", str(root), "--role", "reviewer"), 2,
                     "check without --mode")
    expect_clean_cli(run("check", "--repo", str(root), "--role", "reviewer", "--mode", "chat"),
                     2, "an unknown --mode")
    expect_clean_cli(run("check", "--repo", str(root / "nope"), "--role", "reviewer",
                         "--mode", "hitl"), 2, "a missing repository root")

    missing_root = tmp / "inputs-missing"
    missing_root.mkdir()
    res = run("check", "--repo", str(missing_root), "--role", "reviewer", "--mode", "hitl")
    expect_clean_cli(res, 2, "a missing checkpoint")
    check("pipeline.yaml" in res.stderr, f"the error must name the checkpoint: {res.stderr!r}")

    cases = {
        "negative": "  reviewer: -1\n",
        "bool": "  reviewer: true\n",
        "numeric string": "  reviewer: \"2\"\n",
        "word": "  reviewer: many\n",
        "float": "  reviewer: 1.5\n",
    }
    for label, line in cases.items():
        broken = repo(tmp, f"counter-{label.replace(' ', '-')}",
                      "run_id: 20261103-8e939171\nretry_counters:\n" + line)
        res, verdict = gate(broken, "reviewer")
        expect_clean_cli(res, 2, f"a {label} counter")
        check("non-negative integer" in res.stderr and "reviewer" in res.stderr,
              f"a {label} counter must be named as invalid: {res.stderr!r}")
        check(verdict == {}, f"a {label} counter prints no verdict")

    # A LIST where the mapping belongs is refused (not silently read as an empty counter set).
    listed = repo(tmp, "counter-list", "run_id: 20261103-8e939171\nretry_counters: []\n")
    res, _verdict = gate(listed, "reviewer")
    expect_clean_cli(res, 2, "retry_counters as a list")
    check("mapping" in res.stderr, f"the error must name the expected shape: {res.stderr!r}")


# --------------------------------------------------------------------------------------------
# The write is surgical and atomic
# --------------------------------------------------------------------------------------------

def test_write_is_surgical(tmp: pathlib.Path) -> None:
    original = CHECKPOINT.replace("models_used:\n",
                                  "# a comment the gate must keep\nmodels_used:\n")
    root = repo(tmp, "surgical", original)
    res, verdict = gate(root, "reviewer")
    expect_clean_cli(res, 0, "one counted delegation")
    text = (root / PIPELINE_REL).read_text(encoding="utf-8")
    expected = original.replace("  reviewer: 0", "  reviewer: 1")
    check(text == expected,
          f"only ONE counter byte may change:\n{text!r}\n!=\n{expected!r}")
    check(not list((root / PIPELINE_REL).parent.glob("*.tmp")),
          f"an atomic write leaves no temp file: {list((root / PIPELINE_REL).parent.iterdir())}")

    crlf = repo(tmp, "crlf", CHECKPOINT.replace("\n", "\r\n"))
    res, verdict = gate(crlf, "coder")
    expect_clean_cli(res, 0, "a CRLF checkpoint")
    raw = (crlf / PIPELINE_REL).read_bytes()
    check(b"\r\n" in raw and b"  coder: 1\r\n" in raw,
          f"a CRLF checkpoint keeps its line endings: {raw[:120]!r}")


# --------------------------------------------------------------------------------------------
# The argparse contract
# --------------------------------------------------------------------------------------------

def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("check", "init"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")
    check("--owner-authorized" in run("check", "--help").stdout,
          "the check help must document --owner-authorized")
    expect_clean_cli(run(), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand"), 2, "an unknown subcommand")
    expect_clean_cli(run("check", "--repo", "."), 2, "check without --role/--mode")

    legacy = run("--help", env=LEGACY_ENV)
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")



# --------------------------------------------------------------------------------------------
# settle: the review-round refund (proposal P-8)
# --------------------------------------------------------------------------------------------
def settle(root: pathlib.Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    """One `settle` call plus the parsed JSON verdict (an empty dict when it printed none)."""
    res = run("settle", "--repo", str(root), *args)
    try:
        verdict = json.loads(res.stdout)
    except json.JSONDecodeError:
        verdict = {}
    return res, verdict


def refuted_round(root: pathlib.Path, round_id: str = "iter-1", *,
                  dispositions: tuple[str, ...] = ("refuted",),
                  named_round: str | None = "same",
                  proof: str = ".code-factory/logs/code-review.md") -> str:
    """Write the merged-findings artifact of one review round and return its repo-relative path."""
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "code-review.md").write_text("# review\n", encoding="utf-8")
    payload: dict = {"findings": [
        {"severity": "major", "file": "src/a.py", "line": 1, "title": f"finding {index}",
         "detail": "detail", "finding_disposition": disposition, "finding_evidence": proof}
        for index, disposition in enumerate(dispositions)]}
    if named_round is not None:
        payload["round"] = round_id if named_round == "same" else named_round
    path = logs / f"round-{round_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return f".code-factory/logs/round-{round_id}.json"


def round_artifact(root: pathlib.Path, round_id: str, *,
                   dispositions: tuple[str, ...] = ("refuted",),
                   proof: str = ".code-factory/logs/code-review.md") -> str:
    """Write the merged-findings report of ONE round (with its identity) and return its rel. path."""
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "code-review.md").write_text("# review\n", encoding="utf-8")
    payload = {"round": round_id, "findings": [
        {"severity": "major", "file": "src/a.py", "line": index + 1, "title": f"t{index}",
         "detail": "d", "finding_disposition": disposition, "finding_evidence": proof}
        for index, disposition in enumerate(dispositions)]}
    path = logs / f"merged-{round_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return f".code-factory/logs/merged-{round_id}.json"


def test_settle(tmp: pathlib.Path) -> None:
    """A WHOLLY REFUTED review round refunds exactly one consumed reviewer iteration, once."""
    root = repo(tmp, "settle")
    first = round_artifact(root, "iter-1")
    second = round_artifact(root, "iter-2")
    third = round_artifact(root, "iter-3")
    mixed_artifact = round_artifact(root, "iter-4", dispositions=("refuted", "accepted"))
    # Two reviewer iterations were consumed (the budget is 2).
    for _ in range(2):
        gate(root, "reviewer")
    check(counters(root)["reviewer"] == 2, "the fixture must have consumed two iterations")

    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-1",
                          "--evidence", first, "--refuted-all")
    expect_clean_cli(res, 0, "settle a wholly refuted round")
    check(verdict["status"] == "settled" and verdict["refunded"] == 1 and verdict["counter"] == 1,
          f"exactly one iteration is refunded: {verdict}")
    text = (root / PIPELINE_REL).read_text(encoding="utf-8")
    check("settled_rounds:" in text and "round=iter-1" in text,
          f"the settlement must be recorded: {text!r}")
    check(counters(root)["reviewer"] == 1, "the counter on disk must be the refunded one")

    # Idempotent per round: the same round never refunds twice, however often it is retried.
    before = (root / PIPELINE_REL).read_text(encoding="utf-8")
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-1",
                          "--evidence", first, "--refuted-all")
    expect_clean_cli(res, 0, "settle the same round twice")
    check(verdict["status"] == "already-settled" and verdict["refunded"] == 0,
          f"a repeated settlement is idempotent: {verdict}")
    check((root / PIPELINE_REL).read_text(encoding="utf-8") == before,
          "an idempotent settlement must not change a byte")

    # A DIFFERENT round refunds again; the counter can never go below 0.
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-2",
                          "--evidence", second, "--refuted-all")
    expect_clean_cli(res, 0, "settle a second round")
    check(verdict["counter"] == 0 and verdict["refunded"] == 1, f"the second refund: {verdict}")
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-3",
                          "--evidence", third, "--refuted-all")
    expect_clean_cli(res, 1, "settle with nothing left to refund")
    check(verdict["status"] == "refused" and verdict["refunded"] == 0 and verdict["counter"] == 0,
          f"the counter must never go below 0: {verdict}")
    check("below 0" in verdict["reason"], f"the reason must say it: {verdict['reason']!r}")

    # (R2-1) The artifact must NAME the round it settles: a report without its identity, or the
    # report of ANOTHER round, is refused — one artifact can never refund two ids.
    anonymous = root / ".code-factory" / "logs" / "anonymous.json"
    anonymous.write_text(json.dumps({"findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/code-review.md"}]}), encoding="utf-8")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-9",
              "--evidence", ".code-factory/logs/anonymous.json", "--refuted-all")
    expect_clean_cli(res, 2, "settle with a report that names no round")
    check("names no review round" in res.stderr, f"the refusal must say it: {res.stderr!r}")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-9",
              "--evidence", second, "--refuted-all")
    expect_clean_cli(res, 2, "settle with ANOTHER round's report")
    check("belongs to review round" in res.stderr, f"the refusal must say it: {res.stderr!r}")
    check(counters(root)["reviewer"] == 0, "a refused settlement must not move the counter")

    # Abuse cases: a mixed round, missing/outside evidence, and another role are refused.
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-4",
                          "--evidence", mixed_artifact)
    expect_clean_cli(res, 2, "settle a MIXED round")
    check("WHOLLY REFUTED" in res.stderr, f"the rule must be stated: {res.stderr!r}")
    check(verdict == {}, "a refused settlement prints no verdict")

    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-5",
              "--evidence", "no-such-artifact.md", "--refuted-all")
    expect_clean_cli(res, 2, "settle without an existing evidence artifact")
    check("existing artifact" in res.stderr, f"the missing artifact must be named: {res.stderr!r}")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-6",
              "--evidence", "../outside.md", "--refuted-all")
    expect_clean_cli(res, 2, "settle with an escaping evidence path")
    res = run("settle", "--repo", str(root), "--role", "coder", "--round", "iter-7",
              "--evidence", first, "--refuted-all")
    expect_clean_cli(res, 2, "settle a non-reviewer role")
    check("reviewer" in res.stderr, f"the error must name the only settleable role: {res.stderr!r}")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "bad round!",
              "--evidence", first, "--refuted-all")
    expect_clean_cli(res, 2, "settle with an unusable round id")

    # The settle CLI contract.
    helped = run("settle", "--help")
    expect_clean_cli(helped, 0, "settle --help")
    check("--refuted-all" in helped.stdout and "--evidence" in helped.stdout,
          f"the help must document the settlement flags: {helped.stdout!r}")
    expect_clean_cli(run("settle", "--repo", str(root), "--role", "reviewer"), 2,
                     "settle without --round/--evidence")


def test_settle_reads_the_round(tmp: pathlib.Path) -> None:
    """(R1-02) `--refuted-all` is checked against the round artifact, never taken on trust."""
    root = repo(tmp, "settle-artifact")
    for _ in range(2):
        gate(root, "reviewer")
    before = (root / PIPELINE_REL).read_text(encoding="utf-8")

    def refuse(label: str, evidence: str, reason: str, *extra: str) -> None:
        res, verdict = settle(root, "--role", "reviewer", "--round", "iter-1",
                              "--evidence", evidence, "--refuted-all", *extra)
        expect_clean_cli(res, 2, label)
        check(verdict == {}, f"{label}: a refused settlement prints no verdict")
        check(reason in res.stderr, f"{label}: the refusal must state {reason!r}: {res.stderr!r}")
        check((root / PIPELINE_REL).read_text(encoding="utf-8") == before,
              f"{label}: a refused settlement must not touch the checkpoint")
        check(counters(root)["reviewer"] == 2, f"{label}: the counter must not move")

    # A round with an ACCEPTED finding is mixed: the reviewer really found something.
    path = refuted_round(root, "iter-1", dispositions=("refuted", "accepted"))
    refuse("an accepted finding in the round", path, "MIXED")
    # Every finding refuted but one carries no disposition at all (legacy default = accepted).
    path = refuted_round(root, "iter-1b", dispositions=("refuted", ""))
    (root / path).write_text(json.dumps({"round": "iter-1", "findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/code-review.md"},
        {"severity": "major", "file": "b.py", "finding_evidence": ""}]}), encoding="utf-8")
    refuse("a finding with no disposition", path, "MIXED")
    # A refutation with no evidence is a suppression, not a refund.
    (root / path).write_text(json.dumps({"round": "iter-1", "findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ""}]}), encoding="utf-8")
    refuse("a refutation with no evidence", path, "finding_evidence")
    # The evidence must exist inside the repository.
    (root / path).write_text(json.dumps({"round": "iter-1", "findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/absent.md"}]}), encoding="utf-8")
    refuse("a refutation pointing at a missing artifact", path, "not an existing")
    # An empty round proves nothing.
    (root / path).write_text(json.dumps({"round": "iter-1", "findings": []}), encoding="utf-8")
    refuse("a round with no findings", path, "states no findings")
    # The artifact of ANOTHER round cannot settle this one.
    path = refuted_round(root, "iter-2", named_round="iter-9")
    refuse("the artifact of another round", path, "belongs to review round")
    # Not even a merged-findings report at all.
    refuse("a non-JSON artifact", ".code-factory/logs/code-review.md", "merged-findings JSON")

    path = refuted_round(root, "iter-1", named_round=None)
    refuse("an artifact naming no round", path, "names no review round")

    # …and the genuine article DOES refund.
    path = refuted_round(root, "iter-1", named_round="iter-1")
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-1", "--evidence", path,
                          "--refuted-all")
    expect_clean_cli(res, 0, "a wholly refuted round with its artifact")
    check(verdict["status"] == "settled" and verdict["refunded"] == 1,
          f"the refund must go through: {verdict}")


def test_settle_round_trip(tmp: pathlib.Path) -> None:
    """(I3-1) A report `merge_findings.py --round` produced settles; a hand-forged id does not.

    The two commands share ONE identifier grammar, so the artifact the producer stamps can always
    be consumed by the settlement — and a report whose round was typed by hand outside that grammar
    is refused instead of silently matching nothing.
    """
    root = repo(tmp, "settle-round-trip")
    for _ in range(2):
        gate(root, "reviewer")
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "code-review.md").write_text("# review\n", encoding="utf-8")
    shard = logs / "shard-1.json"
    shard.write_text(json.dumps({
        "shard": "shard-1", "verdict": "request_changes", "findings": [
            {"severity": "major", "file": "src/a.py", "line": 1, "title": "t", "detail": "d",
             "finding_disposition": "refuted",
             "finding_evidence": ".code-factory/logs/code-review.md"}]}), encoding="utf-8")
    merged = logs / "merged.json"
    res = run_merge("--inputs", str(shard), "--repo", str(root), "--round", "iter-1",
                    "--report", str(merged))
    expect_clean_cli(res, 0, "merge a wholly refuted round (it approves)")
    check(json.loads(merged.read_text(encoding="utf-8"))["round"] == "iter-1",
           "the merged report must carry the round identity")

    # The produced artifact settles its round.
    res, verdict = settle(root, "--role", "reviewer", "--round", "iter-1",
                          "--evidence", ".code-factory/logs/merged.json", "--refuted-all")
    expect_clean_cli(res, 0, "settle with the report merge_findings.py produced")
    check(verdict["status"] == "settled" and verdict["refunded"] == 1,
           f"the round-trip must refund: {verdict}")

    # A hand-forged identifier is refused for being outside the grammar.
    forged = logs / "forged.json"
    forged.write_text(json.dumps({"round": "bad round!", "findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/code-review.md"}]}), encoding="utf-8")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "bad round!",
              "--evidence", ".code-factory/logs/forged.json", "--refuted-all")
    expect_clean_cli(res, 2, "settle with a forged round identifier")
    check("[A-Za-z0-9._-]+" in res.stderr, f"the refusal must name the grammar: {res.stderr!r}")
    # …and a TERMINAL NEWLINE is not an identifier: `$` matches before it, `fullmatch` does not —
    # on the CLI argument and on the artifact's own `round` alike.
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-8\n",
              "--evidence", ".code-factory/logs/merged.json", "--refuted-all")
    expect_clean_cli(res, 2, "settle with a terminal newline in --round")
    newline_artifact = logs / "newline.json"
    newline_artifact.write_text(json.dumps({"round": "iter-1\n", "findings": [
        {"severity": "major", "file": "a.py", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/code-review.md"}]}), encoding="utf-8")
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-1",
              "--evidence", ".code-factory/logs/newline.json", "--refuted-all")
    expect_clean_cli(res, 2, "settle an artifact whose round ends with a newline")
    check("FULL" in res.stderr, f"the refusal must name the grammar: {res.stderr!r}")

    # …and an artifact whose round was typed outside the grammar is refused by the CONSUMER too.
    res = run("settle", "--repo", str(root), "--role", "reviewer", "--round", "iter-9",
              "--evidence", ".code-factory/logs/forged.json", "--refuted-all")
    expect_clean_cli(res, 2, "settle an artifact stamped with a forged identifier")
    check("settlement identifier" in res.stderr,
          f"the consumer must name the grammar: {res.stderr!r}")


def run_merge(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the sibling producer `merge_findings.py` (the artifact the settlement consumes)."""
    merge = pathlib.Path(__file__).with_name("merge_findings.py")
    return subprocess.run([sys.executable, str(merge), *args], capture_output=True, text=True,
                          errors="replace")


def test_atomic_write_failure(tmp: pathlib.Path) -> None:
    """(R1-05) An unwritable checkpoint is an actionable exit 2 and keeps the old bytes."""
    frozen = repo(tmp, "gate-write-frozen")
    path = frozen / PIPELINE_REL
    before = path.read_bytes()
    os.chmod(path, 0o444)
    try:
        res = run("check", "--repo", str(frozen), "--role", "coder", "--mode", "hitl")
        expect_clean_cli(res, 2, "check onto a read-only checkpoint")
        check("cannot write the checkpoint" in res.stderr,
              f"the CLI must name the write failure: {res.stderr!r}")
        check(path.read_bytes() == before,
              "a failed write must leave the checkpoint byte-identical")
    finally:
        os.chmod(path, 0o644)



# --------------------------------------------------------------------------------------------
# audit: every budgeted-role spawn must have a counter trail (the gate_all phase-Y hook)
# --------------------------------------------------------------------------------------------
def write_wire(root: pathlib.Path, events: list, *extra: str) -> pathlib.Path:
    """A fixture session: `state.json` + `agents/main/wire.jsonl` (JSON events plus raw lines)."""
    session = root / "session"
    (session / "agents" / "main").mkdir(parents=True, exist_ok=True)
    (session / "state.json").write_text("{}", encoding="utf-8")
    lines = [json.dumps(event) for event in events] + list(extra)
    (session / "agents" / "main" / "wire.jsonl").write_text("\n".join(lines) + "\n",
                                                            encoding="utf-8")
    return session


def spawn(agent: str, profile: str, at: int = 1) -> dict:
    return {"type": "subagent.spawned", "subagentId": agent, "subagentName": profile,
            "parentAgentId": "main", "time": at}


def test_audit(tmp: pathlib.Path) -> None:
    """A budgeted-role spawn with no counted delegation FAILS the finish audit.

    The hook `gate_all.py` calls at phase Y: the wire is the evidence of what really ran, the
    counters are the evidence of what was counted, and this audit joins them. Fail-closed on a
    malformed wire line; DEGRADED (exit 3) when there is no wire at all.
    """
    root = repo(tmp, "audit")
    session = write_wire(root, [spawn("agent-1", "factory-code-reviewer"),
                                {"type": "llm.request", "agentId": "agent-1", "model": "k3",
                                 "time": 2}])
    res = run("audit", "--repo", str(root), "--session", str(session))
    expect_clean_cli(res, 1, "an uncounted reviewer spawn")
    check("uncounted delegation" in res.stdout and "reviewer" in res.stdout,
          f"the audit must name the role: {res.stdout!r}")

    # A counted delegation passes — the counter is the trail.
    gate(root, "reviewer")
    res = run("audit", "--repo", str(root), "--session", str(session))
    expect_clean_cli(res, 0, "a counted reviewer spawn")
    check("PASS" in res.stdout, f"the audit must report the pass: {res.stdout!r}")

    # …and a REFUNDED iteration still counts as a trail — CAUSALLY. The fixture's wire holds TWO
    # reviewer spawns, so the accounting has to add up: after the settlement refunds one iteration
    # the counter is 1 and the recorded refund is 1, and only `counter + refunded >= spawns` passes.
    # The control below removes the refund and keeps the same wire, and it FAILS.
    refunded = repo(tmp, "audit-refunded")
    refunded_session = write_wire(refunded, [spawn("agent-r1", "factory-code-reviewer"),
                                             spawn("agent-r2", "factory-code-reviewer")])
    for _ in range(2):
        gate(refunded, "reviewer")
    check(counters(refunded)["reviewer"] == 2,
          "the refunded fixture must have counted two reviewer delegations")
    res = run("audit", "--repo", str(refunded), "--session", str(refunded_session))
    expect_clean_cli(res, 0, "two counted reviewer delegations for two spawns")
    check("reviewer=2" in res.stdout, f"the audit must count both spawns: {res.stdout!r}")

    artifact = round_artifact(refunded, "iter-1")
    res, verdict = settle(refunded, "--role", "reviewer", "--round", "iter-1",
                          "--evidence", artifact, "--refuted-all")
    expect_clean_cli(res, 0, "settle a wholly refuted round before the audit")
    check(verdict["status"] == "settled" and verdict["refunded"] == 1,
          f"the settlement must really refund one iteration: {verdict}")
    check(counters(refunded)["reviewer"] == 1,
          "the counter on disk must be decremented to 1 by the settlement")
    text = (refunded / PIPELINE_REL).read_text(encoding="utf-8")
    check("settled_rounds:" in text and "refunded=1" in text,
          f"the refunded round must be recorded: {text!r}")

    res = run("audit", "--repo", str(refunded), "--session", str(refunded_session))
    expect_clean_cli(res, 0, "a refunded iteration still counts")
    check("PASS" in res.stdout, f"a refund must not look uncounted: {res.stdout!r}")
    check("reviewer=2" in res.stdout,
          f"the passing audit must still see BOTH spawns: {res.stdout!r}")

    # CONTROL: the SAME two-spawn wire with only ONE counted delegation and NO settlement is red —
    # that is what makes the refund above causal rather than incidental.
    control = repo(tmp, "audit-refund-control")
    control_session = write_wire(control, [spawn("agent-c1", "factory-code-reviewer"),
                                           spawn("agent-c2", "factory-code-reviewer")])
    gate(control, "reviewer")
    check(counters(control)["reviewer"] == 1, "the control must count exactly one delegation")
    res = run("audit", "--repo", str(control), "--session", str(control_session))
    expect_clean_cli(res, 1, "one counted delegation for two spawns")
    check("uncounted delegation" in res.stdout and "reviewer" in res.stdout,
          f"the control must report the missing count: {res.stdout!r}")
    check("2 time(s)" in res.stdout and "is 1" in res.stdout,
          f"the control must state the arithmetic: {res.stdout!r}")

    # A role WITHOUT a budget is out of scope (analyzer spawns need no counter).
    clean = repo(tmp, "audit-nobudget")
    directory = write_wire(clean, [spawn("agent-2", "factory-analyzer")])
    res = run("audit", "--repo", str(clean), "--session", str(directory))
    expect_clean_cli(res, 0, "an unbudgeted role spawn")

    # A malformed wire line fails closed.
    broken = repo(tmp, "audit-malformed")
    directory = write_wire(broken, [spawn("agent-3", "factory-code-reviewer")], "{ not json")
    res = run("audit", "--repo", str(broken), "--session", str(directory))
    expect_clean_cli(res, 1, "a malformed wire line")
    check("malformed" in res.stdout.lower(), f"the audit must name it: {res.stdout!r}")

    # No wire at all: DEGRADED, never a silent pass.
    empty = tmp / "audit-empty"
    (empty / "agents").mkdir(parents=True)
    (empty / "state.json").write_text("{}", encoding="utf-8")
    res = run("audit", "--repo", str(root), "--session", str(empty))
    expect_clean_cli(res, 3, "an absent session wire")
    check("DEGRADED" in res.stdout, f"the verdict must say DEGRADED: {res.stdout!r}")

    # The CLI contract of the new subcommand.
    helped = run("audit", "--help")
    expect_clean_cli(helped, 0, "audit --help")
    check("--session" in helped.stdout, f"the help must document --session: {helped.stdout!r}")
    expect_clean_cli(run("audit"), 2, "audit without --repo")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        test_init(tmp)
        test_third_reviewer_is_refused(tmp)
        test_mode_semantics(tmp)
        test_owner_authorization(tmp)
        test_per_role_budgets(tmp)
        test_input_validation(tmp)
        test_write_is_surgical(tmp)
        test_settle(tmp)
        test_settle_reads_the_round(tmp)
        test_settle_round_trip(tmp)
        test_atomic_write_failure(tmp)
        test_audit(tmp)
        test_cli_contract()

    print("PASS - delegation_gate.py counts every delegation itself: the counter is incremented "
          "and persisted atomically (one counter, every other byte preserved, CRLF kept), the "
          "delegation that would exceed the role's budget is REFUSED without an increment (hitl "
          "sends the main agent to the AskUserQuestion owner stop, auto names the FAILED run and "
          "has no override), --owner-authorized grants exactly one recorded extra delegation per "
          "owner decision (N recorded decisions allow budget + N delegations, a second decision was "
          "refused forever before this fix), "
          "init materializes the retry_counters block idempotently, and every bad input (an "
          "unbudgeted role, a missing checkpoint or block, a counter that is not a non-negative "
          "integer) is an actionable exit-2 error without a traceback; and `settle` refunds exactly "
          "ONE consumed reviewer iteration for a WHOLLY REFUTED round (never below 0, idempotent per "
          "round through the settled_rounds record, evidence mandatory, a mixed round and another "
          "role refused); and `audit` fails a budgeted-role spawn the session wire shows with no "
          "counted delegation, fail-closed on malformed wire evidence and DEGRADED without one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

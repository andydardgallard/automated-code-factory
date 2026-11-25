#!/usr/bin/env python3
"""
Contract test for `run_guard.py` — the repo-side single-active-run guard (zero LLM tokens).

WHY THIS EXISTS

Defect C: the factory works with the repository named by the task's `repo_path`, not the launch
folder. Two factories launched from the SAME folder into DIFFERENT repositories must both run,
while one active run per TARGET REPO stays the rule — and that rule must fail closed LOUDLY,
repo-side, instead of being discovered halfway through a phase. This test is the vaccination: it
pins the claim semantics of `run_guard.py` BEFORE the guard exists, so the script is written
against a failing test rather than the test against the script.

COVERED, all through the shipped CLI (a subprocess, like the flow calls it):

  - NO checkpoint at all → CLAIMED (exit 0): a fresh target repo is free;
  - a TERMINAL checkpoint (`status: ok` or `status: failed`) of ANOTHER run → CLAIMED (exit 0):
    a finished run never blocks the next one;
  - the SAME run_id as the checkpoint, `status: in_progress` → CLAIMED (exit 0): a resume is not
    a second active run;
  - a DIFFERENT run_id while the checkpoint says `status: in_progress` → REFUSED (exit 1), the
    message naming the BLOCKING run, its phase and its `updated_at`, and the resolution (finish or
    roll back that run first) — a loud refusal, never a silent overwrite of someone's checkpoint;
  - an active (`in_progress`) checkpoint that carries NO run_id is UNIDENTIFIABLE, so it can never
    be "the same run": fail closed with the same loud refusal (exit 1), never a claim;
  - the guard is a CHECK, not a lock: `claim` and `status` write NOTHING — the repository's bytes
    and file list are identical before and after (no lock file, no migrated checkpoint, no
    `.code-factory/` conjured into a bare repo), which is what lets two runs into two repos share
    one launch folder;
  - `status --repo` is the read-only probe: exit 0 with a report for both a free and an occupied
    repo, and the checkpoint byte-identical afterwards;
  - the inputs are validated at the boundary (exit 2, actionable message, never a traceback): a
    `--run-id` that is not `YYYYMMDD-<8 lowercase hex>` (short/long/uppercase/separators/blank), a
    `--repo` that is missing or not a directory — a malformed id must never silently claim a repo;
  - the argparse contract: `--help` exits 0 for the script and for both subcommands (also on a
    legacy console code page), a usage error exits 2;
  - ONE checkpoint contract: the guard reads the repo checkpoint through
    `delegation_gate`'s shared reader instead of parsing `.code-factory/state/pipeline.yaml`
    a second way, and a CRLF checkpoint is read as well as an LF one;
  - END TO END (the business scenario this defect was reported for): TWO factories launched from
    ONE folder into TWO repositories run interleaved through the factory's OWN scripts — two keyed
    supervisor bootstraps, two keyed launch-scoped permit registries, two transactional `bind-run`
    transfers — and no launch-scoped file is shared or rewritten by the sibling; both runs finish,
    while a second run claiming a repository another run already holds is REFUSED loudly (exit 1)
    naming the blocking run.

Exit code 0 = every assertion passes, 1 = the guard did not behave as the contract says.
A missing `run_guard.py` is reported as a plain FAIL (this file ships BEFORE the implementation:
that failure is the vaccination evidence, not a broken test).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("run_guard.py")
WATCHDOG_TOOL = pathlib.Path(__file__).with_name("supervisor_watchdog.py")
PERMIT_TOOL = pathlib.Path(__file__).with_name("permit_gate.py")
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
LAUNCH_STATE_REL = pathlib.Path(".code-factory") / "state"
PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
# The launch nonce `supervisor_watchdog.py begin` mints (a filename component of the launch's own
# registry), and the Phase 0 operations a bootstrap must have watched before it may bind a run.
LAUNCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
PHASE0_REQUIRED = ("parse", "resolve", "memory-read", "run-id")
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

# The run this test claims; the fixtures put a DIFFERENT run in the checkpoint unless a section
# says otherwise (the point of the guard is exactly that difference).
RUN_ID = "20261125-5beb8e51"
OTHER_ID = "20261103-8e939171"
# The end-to-end scenario runs two factories side by side: the second run's id, and one more for
# the "a finished run frees its repository" claim.
SECOND_ID = "20261126-7c0d1e2f"
THIRD_ID = "20261127-1a2b3c4d"


def checkpoint_text(run_id: str | None = OTHER_ID, status: str = "in_progress",
                    phase: str = "5-implement-W2",
                    updated_at: str = "2026-11-03T20:00:00+03:00") -> str:
    """A WIP checkpoint in the shipped shape (`run_id`, `phase`, `status`, `updated_at`)."""
    lines = []
    if run_id is not None:
        lines.append(f"run_id: {run_id}")
    lines += [f"phase: \"{phase}\"", f"status: {status}", f"updated_at: \"{updated_at}\"",
              "files_touched: []"]
    return "\n".join(lines) + "\n"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def repo(tmp: pathlib.Path, name: str, text: str | None = None) -> pathlib.Path:
    """A throwaway target repository; `text` becomes its WIP checkpoint when given."""
    root = tmp / name
    if text is not None:
        path = root / PIPELINE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    else:
        root.mkdir(parents=True, exist_ok=True)
    return root


def snapshot(root: pathlib.Path) -> dict[str, str]:
    """Every file below `root` as `relative posix path -> sha256`, so a WRITE is visible."""
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
        elif path.is_dir():
            files[path.relative_to(root).as_posix() + "/"] = "dir"
    return files


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def output(res: subprocess.CompletedProcess[str]) -> str:
    """What the guard said, stdout and stderr together, lower-cased for the wording pins."""
    return f"{res.stdout}\n{res.stderr}".lower()


def expect(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: no traceback allowed: {res.stderr!r}")


def claim(root: pathlib.Path, run_id: str = RUN_ID) -> subprocess.CompletedProcess[str]:
    return run("claim", "--repo", str(root), "--run-id", run_id)


def expect_claimed(root: pathlib.Path, label: str, run_id: str = RUN_ID) -> None:
    """A claim that must succeed — and must leave the repository byte-identical."""
    before = snapshot(root)
    res = claim(root, run_id)
    expect(res, 0, label)
    check(run_id in res.stdout, f"{label}: the claim must name the run it claimed: {res.stdout!r}")
    check(snapshot(root) == before,
          f"{label}: the guard is a CHECK, not a lock — it must write nothing, "
          f"but the repository changed")


# --------------------------------------------------------------------------------------------
# the four claim cases
# --------------------------------------------------------------------------------------------

def test_claimable_without_checkpoint(tmp: pathlib.Path) -> None:
    """A fresh target repo is free — and no `.code-factory/` is created by asking."""
    root = repo(tmp, "fresh")
    expect_claimed(root, "claim on a repo with no checkpoint")
    check(not (root / ".code-factory").exists(),
          "a claim must never conjure a .code-factory/ into a bare repository")


def test_claimable_on_terminal_status(tmp: pathlib.Path) -> None:
    """A finished (ok/failed) run never blocks the next one."""
    for status in ("ok", "failed"):
        root = repo(tmp, f"terminal-{status}", checkpoint_text(status=status))
        expect_claimed(root, f"claim over a {status} checkpoint of another run")
        check((root / PIPELINE_REL).read_text(encoding="utf-8") == checkpoint_text(status=status),
              f"a claim over a {status} checkpoint must not touch it")


def test_resume_keeps_the_same_run(tmp: pathlib.Path) -> None:
    """The same run_id is the SAME run: resuming it is never a second active run."""
    text = checkpoint_text(run_id=RUN_ID, status="in_progress")
    root = repo(tmp, "resume", text)
    expect_claimed(root, "claim of the run the in_progress checkpoint already names")
    check((root / PIPELINE_REL).read_text(encoding="utf-8") == text,
          "a resume must not rewrite the checkpoint it resumes")
    finished = repo(tmp, "resume-ok", checkpoint_text(run_id=RUN_ID, status="ok"))
    expect_claimed(finished, "claim of the same run over its own finished checkpoint")


def test_refused_different_active_run(tmp: pathlib.Path) -> None:
    """The failing-first pin: a DIFFERENT active run owns the repo, so the claim is REFUSED."""
    root = repo(tmp, "occupied", checkpoint_text())
    before = snapshot(root)
    res = claim(root, RUN_ID)
    expect(res, 1, "claim while another run is in_progress")
    said = output(res)
    check(OTHER_ID in said, f"the refusal must NAME the blocking run {OTHER_ID}: {said!r}")
    check(RUN_ID not in said.replace(OTHER_ID, ""),
          f"the blocking run is the OTHER run, not the claimant: {said!r}")
    check("5-implement-w2" in said, f"the refusal must name the blocking phase: {said!r}")
    check("2026-11-03" in said, f"the refusal must name updated_at: {said!r}")
    check("in_progress" in said, f"the refusal must name the blocking status: {said!r}")
    check("finish" in said or "roll back" in said or "rollback" in said,
          f"the refusal must name the resolution (finish or roll back that run): {said!r}")
    check(snapshot(root) == before,
          "a REFUSED claim must not touch the blocking run's checkpoint")

    # Two runs of the same day differ only by their hash: a near-miss must not be mistaken for
    # the same run (the shape is validated, the identity is compared EXACTLY).
    near_miss = RUN_ID[:-1] + ("0" if RUN_ID[-1] != "0" else "1")
    near = repo(tmp, "occupied-near", checkpoint_text(run_id=RUN_ID))
    expect(claim(near, near_miss), 1, "claim with a near-miss of the active run's id")


def test_fail_closed_on_unidentifiable_run(tmp: pathlib.Path) -> None:
    """An active checkpoint with no run_id can never be "the same run" — fail closed."""
    for name, text in (("no-run-id", checkpoint_text(run_id=None)),
                       ("blank-run-id", checkpoint_text(run_id="\"\""))):
        root = repo(tmp, name, text)
        before = snapshot(root)
        res = claim(root, RUN_ID)
        expect(res, 1, f"claim over an in_progress checkpoint with {name}")
        check(snapshot(root) == before, f"{name}: a refusal must not rewrite the checkpoint")


# --------------------------------------------------------------------------------------------
# the read-only status probe
# --------------------------------------------------------------------------------------------

def test_status_is_read_only(tmp: pathlib.Path) -> None:
    """`status` reports both free and occupied repos and changes nothing."""
    free = repo(tmp, "status-free")
    before = snapshot(free)
    res = run("status", "--repo", str(free))
    expect(res, 0, "status on a repo with no checkpoint")
    check(res.stdout.strip(), f"the probe must report something: {res.stdout!r}")
    check(snapshot(free) == before, "status must write nothing")

    occupied = repo(tmp, "status-occupied", checkpoint_text())
    before = snapshot(occupied)
    res = run("status", "--repo", str(occupied))
    expect(res, 0, "status on an occupied repo")
    check(OTHER_ID in res.stdout,
          f"the probe must report the active run of the repository: {res.stdout!r}")
    check(snapshot(occupied) == before, "status must leave the checkpoint byte-identical")


# --------------------------------------------------------------------------------------------
# boundary: every bad input is exit 2
# --------------------------------------------------------------------------------------------

def test_input_validation(tmp: pathlib.Path) -> None:
    """A malformed run_id or an unusable --repo must never silently claim a repo."""
    root = repo(tmp, "validation-free")
    malformed = {
        "empty": "",
        "blank": "   ",
        "short-hash": "20261125-5beb8e5",
        "long-hash": "20261125-5beb8e511",
        "uppercase-hash": "20261125-5BEB8E51",
        "short-date": "2026112-5beb8e51",
        "prose-date": "2026-11-25-5beb8e51",
        "traversal": "../../20261125-5beb8e51",
        "no-hash": "20261125",
        "junk": "not-a-run-id",
    }
    for label, value in malformed.items():
        res = claim(root, value)
        expect(res, 2, f"claim with a {label} run id ({value!r})")
        check(any(token in res.stderr.lower()
                  for token in ("run_id", "run id", "run-id")),
              f"the error must name the offending input: {res.stderr!r}")

    res = run("claim", "--repo", str(root))
    expect(res, 2, "claim without --run-id")
    res = run("claim", "--run-id", RUN_ID)
    expect(res, 2, "claim without --repo")

    missing = tmp / "does-not-exist"
    for label, path in (("missing", missing), ("a file", root / PIPELINE_REL)):
        if label == "a file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(checkpoint_text(), encoding="utf-8")
        res = claim(path)
        expect(res, 2, f"claim with a --repo that is {label}")
    expect(run("status", "--repo", str(missing)), 2, "status with a missing --repo")


def test_cli_contract() -> None:
    """House argparse conventions: help exits 0 (also on a legacy code page), misuse exits 2."""
    for args in (("--help",), ("claim", "--help"), ("status", "--help")):
        res = run(*args)
        expect(res, 0, f"run_guard.py {' '.join(args)}")
        check(res.stdout.strip(), f"run_guard.py {' '.join(args)} must print help")
        legacy = run(*args, env=LEGACY_ENV)
        expect(legacy, 0, f"run_guard.py {' '.join(args)} under cp1251")
        check(legacy.stdout.strip(), "the help must survive a legacy console code page")
    res = run("frobnicate")
    expect(res, 2, "an unknown subcommand")
    res = run("claim", "--bogus-flag", RUN_ID)
    expect(res, 2, "an unknown flag")


# --------------------------------------------------------------------------------------------
# one checkpoint contract with delegation_gate
# --------------------------------------------------------------------------------------------

def test_shares_the_checkpoint_reader(tmp: pathlib.Path) -> None:
    """The guard must not parse `.code-factory/state/pipeline.yaml` a second way."""
    source = TOOL.read_text(encoding="utf-8")
    check("delegation_gate" in source,
          "run_guard.py must read the checkpoint through delegation_gate's shared reader "
          "(one contract), not re-implement it")
    # The shared reader is text-preserving: a CRLF checkpoint reads like an LF one.
    crlf = checkpoint_text(run_id=RUN_ID, status="in_progress").replace("\n", "\r\n")
    root = repo(tmp, "crlf", crlf)
    expect_claimed(root, "claim of a CRLF checkpoint")
    check((root / PIPELINE_REL).read_bytes().count(b"\r\n") > 0,
          "a claim must not normalize the checkpoint's line endings")


# --------------------------------------------------------------------------------------------
# end to end: two factories, ONE launch folder, two target repositories
# --------------------------------------------------------------------------------------------

def tool(path: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One shipped factory script, called the way the flow calls it (a subprocess)."""
    return subprocess.run([sys.executable, str(path), *args], capture_output=True, text=True,
                          errors="replace")


def expect_tool(res: subprocess.CompletedProcess[str], code: int, label: str) -> dict:
    """One factory-script call: the expected exit code, no traceback, and its JSON payload."""
    expect(res, code, label)
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}


def begin(launch: pathlib.Path, label: str) -> str:
    """Begin one supervision in `launch` and return the launch id it minted for it."""
    payload = expect_tool(tool(WATCHDOG_TOOL, "begin", "--launch-dir", str(launch)), 0, label)
    launch_id = payload.get("launch_id")
    check(isinstance(launch_id, str) and bool(LAUNCH_ID_RE.match(launch_id)),
          f"{label}: `begin` must return the launch id that keys its own record: {payload!r}")
    check((launch / LAUNCH_STATE_REL / f"watchdog-bootstrap-{launch_id}.json").is_file(),
          f"{label}: the bootstrap must be keyed per launch, never one shared record")
    return launch_id


def keyed_registry(launch: pathlib.Path, launch_id: str) -> tuple[pathlib.Path, pathlib.Path]:
    """The permit registry ONE launch id owns: its permits file and its journal."""
    state = launch / LAUNCH_STATE_REL
    return (state / f"permits.launch-{launch_id}.yaml",
            state / f"permits.ledger.launch-{launch_id}.jsonl")


def observe_phase0(launch: pathlib.Path, launch_id: str, label: str) -> None:
    """Record the Phase 0 operations `activate` demands, in the order the flow mandates."""
    for seq, event in enumerate(PHASE0_REQUIRED):
        expect_tool(tool(WATCHDOG_TOOL, "observe", "--launch-dir", str(launch), "--launch-id",
                         launch_id, "--event", event, "--seq", str(seq)), 0,
                    f"{label}: observe {event}")


def test_concurrent_launches_in_one_folder(tmp: pathlib.Path) -> None:
    """(business scenario) Two factories in ONE folder, into TWO repos: both run, nothing shared.

    The reported defect: the launch-scoped state (supervisor bootstrap and pre-run permit registry)
    had ONE fixed path per folder, so a second factory launched from the same folder rewrote the
    first one's records. The owner's rule is repo-scoped: one ACTIVE run per TARGET repository, and
    several runs per launch folder. This section drives both runs through the factory's own scripts,
    INTERLEAVED, and pins: two keyed bootstraps and two keyed registries with no shared mutable
    file, each launch's records byte-identical while the sibling works, each registry transferred
    to ITS repo, both runs finishing, and the repository-level refusal still loud.
    """
    launch = tmp / "concurrent-launch"
    launch.mkdir()
    repo_a = repo(tmp, "concurrent-a")
    repo_b = repo(tmp, "concurrent-b")

    # 1. The guard is REPO-scoped: both runs claim their OWN target repository, from one folder.
    expect_claimed(repo_a, "run A claims its own repository")
    expect_claimed(repo_b, "run B claims its own repository in the SAME launch folder", SECOND_ID)

    # 2. Both supervisors begin in that one folder — each mints its OWN launch id.
    launch_a = begin(launch, "the first supervisor begins")
    launch_b = begin(launch, "the second supervisor begins in the SAME folder")
    check(launch_a != launch_b,
          "two runs launched from one folder need two launch ids: they are different runs")

    # 3. Interleaved pre-run lifecycles, one registry per launch.
    runs = ((launch_a, "PB-supervisor-a", "the first run"), (launch_b, "PB-supervisor-b",
                                                             "the second run"))
    for launch_id, _permit_id, label in runs:
        expect_tool(tool(PERMIT_TOOL, "init", "--launch-dir", str(launch), "--launch-id",
                         launch_id), 0, f"{label}: the launch-only init")
    permits_a, ledger_a = keyed_registry(launch, launch_a)
    permits_b, ledger_b = keyed_registry(launch, launch_b)
    for launch_id, permit_id, label in runs:
        expect_tool(tool(PERMIT_TOOL, "add", "--launch-dir", str(launch), "--launch-id", launch_id,
                         "--permit-id", permit_id, "--kind", "bootstrap", "--task-id", "bootstrap",
                         "--role", "supervisor", "--phase", "analysis"), 0, f"{label}: add")
    kept_a = (permits_a.read_bytes(), ledger_a.read_bytes())

    # Run B's whole lifecycle runs FIRST and leaves run A's records byte-identical.
    expect_tool(tool(PERMIT_TOOL, "verdict", "--launch-dir", str(launch), "--launch-id", launch_b,
                     "--permit-id", "PB-supervisor-b", "--verdict", "allow", "--evidence",
                     "the launch bootstrap this permit answers"), 0, "the second run's verdict")
    expect_tool(tool(PERMIT_TOOL, "bind", "--launch-dir", str(launch), "--launch-id", launch_b,
                     "--permit-id", "PB-supervisor-b", "--agent-id", "agent-sup-b"), 0,
                "the second run's binding")
    check((permits_a.read_bytes(), ledger_a.read_bytes()) == kept_a,
          "one launch's lifecycle must never rewrite the sibling launch's registry")
    expect_tool(tool(PERMIT_TOOL, "verdict", "--launch-dir", str(launch), "--launch-id", launch_a,
                     "--permit-id", "PB-supervisor-a", "--verdict", "allow", "--evidence",
                     "the launch bootstrap this permit answers"), 0, "the first run's verdict")
    expect_tool(tool(PERMIT_TOOL, "bind", "--launch-dir", str(launch), "--launch-id", launch_a,
                     "--permit-id", "PB-supervisor-a", "--agent-id", "agent-sup-a"), 0,
                "the first run's binding")

    # No shared mutable launch-scoped file exists anywhere in the folder.
    state_files = sorted(path.name for path in (launch / LAUNCH_STATE_REL).iterdir())
    check(not (launch / PERMITS_REL).exists()
          and not (launch / LAUNCH_STATE_REL / "permits.ledger.jsonl").exists(),
          f"a keyed launch registry must never share the unkeyed file: {state_files!r}")
    check(sorted((f"permits.launch-{launch_a}.yaml", f"permits.ledger.launch-{launch_a}.jsonl",
                  f"permits.launch-{launch_b}.yaml", f"permits.ledger.launch-{launch_b}.jsonl",
                  f"watchdog-bootstrap-{launch_a}.json", f"watchdog-bootstrap-{launch_b}.json"))
          == state_files, f"the folder must hold ONE keyed set per launch: {state_files!r}")
    data_a = json.loads(permits_a.read_text(encoding="utf-8"))
    data_b = json.loads(permits_b.read_text(encoding="utf-8"))
    check([permit["permit_id"] for permit in data_a["permits"]] == ["PB-supervisor-a"]
          and [permit["permit_id"] for permit in data_b["permits"]] == ["PB-supervisor-b"],
          "each launch's registry must carry ITS OWN permits, never the sibling's")

    # 4. A transfer that cannot say WHICH launch it means is refused, and writes nothing.
    activation = ((repo_a, RUN_ID), (repo_b, SECOND_ID))
    for root, run_id in activation:
        (root / PIPELINE_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / PIPELINE_REL).write_text(
            checkpoint_text(run_id=run_id, status="in_progress", phase="0-phase0"),
            encoding="utf-8", newline="")
    res = tool(PERMIT_TOOL, "bind-run", "--launch-dir", str(launch), "--repo", str(repo_a))
    expect_tool(res, 2, "an id-less transfer over TWO open launches")
    check(launch_a in res.stderr and launch_b in res.stderr,
          f"the ambiguity must name both launch ids: {res.stderr!r}")
    check(not (repo_a / PERMITS_REL).exists(), "a refused transfer must write nothing")

    # 5. Each launch's registry travels to ITS repository, once, as its own judged record.
    for launch_id, root in ((launch_a, repo_a), (launch_b, repo_b)):
        expect_tool(tool(PERMIT_TOOL, "bind-run", "--launch-dir", str(launch), "--repo", str(root),
                         "--launch-id", launch_id), 0, f"the transfer of launch {launch_id}")
    bound_a = json.loads((repo_a / PERMITS_REL).read_text(encoding="utf-8"))
    bound_b = json.loads((repo_b / PERMITS_REL).read_text(encoding="utf-8"))
    check(bound_a["run_id"] == RUN_ID and bound_b["run_id"] == SECOND_ID
          and [permit["permit_id"] for permit in bound_a["permits"]] == ["PB-supervisor-a"]
          and [permit["permit_id"] for permit in bound_b["permits"]] == ["PB-supervisor-b"]
          and bound_a["permits"][0]["agent_id"] == "agent-sup-a"
          and bound_b["permits"][0]["agent_id"] == "agent-sup-b",
          f"each repository must receive ITS OWN judged registry: {bound_a!r} / {bound_b!r}")
    check(not permits_a.exists() and not permits_b.exists(),
          "a transferred launch copy is retired, never left as a live fork")

    # 6. One ACTIVE run per repository still bites — loudly, naming the blocking run.
    res = claim(repo_a, SECOND_ID)
    expect(res, 1, "run B claiming the repository run A is working in")
    said = output(res)
    check(RUN_ID in said, f"the refusal must name the blocking run {RUN_ID}: {said!r}")
    check("0-phase0" in said, f"the refusal must name the blocking phase: {said!r}")
    expect_claimed(repo_a, "run A resumes the repository it holds")
    expect_claimed(repo_b, "run B resumes its own repository", SECOND_ID)

    # 7. Both runs FINISH: the keyed bootstraps close independently and the repos free up again.
    for root, run_id in activation:
        (root / PIPELINE_REL).write_text(
            checkpoint_text(run_id=run_id, status="ok", phase="10-finish"),
            encoding="utf-8", newline="")
    for launch_id, root in ((launch_a, repo_a), (launch_b, repo_b)):
        observe_phase0(launch, launch_id, f"launch {launch_id}")
        expect_tool(tool(WATCHDOG_TOOL, "activate", "--launch-dir", str(launch), "--repo",
                         str(root), "--launch-id", launch_id), 0,
                    f"the activation of launch {launch_id}")
        payload = expect_tool(tool(WATCHDOG_TOOL, "complete", "--launch-dir", str(launch),
                                   "--launch-id", launch_id), 0,
                              f"the completion of launch {launch_id}")
        check(payload.get("launch_id") == launch_id,
              f"the completion must name the launch it closes: {payload!r}")
    expect_claimed(repo_a, "a finished run frees its repository for the next one", THIRD_ID)
    final = sorted(path.name for path in (launch / LAUNCH_STATE_REL).iterdir())
    check(not (launch / PERMITS_REL).exists()
          and not any(name.startswith("permits.launch-") and "transferred" not in name
                      for name in final),
          f"no live launch-scoped registry may be left behind: {final!r}")
    check(len([name for name in final if name.startswith("watchdog-bootstrap-")]) == 2
          and len([name for name in final if "transferred" in name]) == 4,
          f"the folder keeps two immutable bootstraps and two retired registries: {final!r}")


SECTIONS = (
    test_claimable_without_checkpoint,
    test_claimable_on_terminal_status,
    test_resume_keeps_the_same_run,
    test_refused_different_active_run,
    test_fail_closed_on_unidentifiable_run,
    test_status_is_read_only,
    test_input_validation,
    test_shares_the_checkpoint_reader,
    test_concurrent_launches_in_one_folder,
)


def main() -> int:
    if not TOOL.is_file():
        print(f"FAIL - {TOOL.name} does not exist: the repo-side single-active-run guard is "
              f"missing, so a second run can silently claim a repository another run is working "
              f"in. Expected a deterministic `claim`/`status` guard (see "
              f".code-factory/state/plan.md T12).")
        return 1
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        failures = []
        for section in SECTIONS:
            try:
                section(tmp)
            except AssertionError as exc:
                failures.append(f"{section.__name__}: {exc}")
        try:
            test_cli_contract()
        except AssertionError as exc:
            failures.append(f"test_cli_contract: {exc}")

    for failure in failures:
        print(f"FAIL - {failure}")
    if failures:
        print(f"FAIL - {len(failures)} section(s) failed: the run guard does not keep one "
              f"active run per target repo, loudly and read-only")
        return 1
    print("PASS - run_guard.py keeps one active run per TARGET REPO: a repo with no checkpoint, "
          "a terminal (ok/failed) checkpoint of another run and the same run's own resume are all "
          "CLAIMED (exit 0), a DIFFERENT in_progress run is REFUSED (exit 1) with the blocking "
          "run, its phase, its updated_at and the resolution named, an active checkpoint with no "
          "run_id fails closed, claim/status write NOTHING (no lock file, no migrated "
          "checkpoint, no .code-factory/ in a bare repo), every malformed run_id or unusable "
          "--repo is an exit-2 error without a traceback, the checkpoint is read through "
          "delegation_gate's shared reader, and two factories launched from ONE folder into TWO "
          "repositories run interleaved through the factory's own scripts with a keyed bootstrap "
          "and a keyed permit registry each - nothing shared, both finishing, the second claim on "
          "a held repository refused loudly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

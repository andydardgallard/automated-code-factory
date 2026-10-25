#!/usr/bin/env python3
"""
Vaccination harness: prove that every registered vaccine BITES (zero LLM tokens, stdlib only).

The factory rule `vaccination` demands that a bug found after acceptance first gets a check that
FAILS on the pre-fix state, and only then the fix. A check that also passes BEFORE the fix proves
nothing — it is a tautology, and nothing in the suite would notice. This harness closes that hole
mechanically for the release's whole change set: `.code-factory/logs/findings-disposition.md` names
one `vaccine: <ID>` per fixed finding, the registry below maps every such ID to the self-test module
that carries the check, and each module is executed TWICE with the same interpreter:

  1. against the WORKING TREE — it must exit 0 (the fix is in place), and
  2. against a PRISTINE PRE-FIX TREE — it must exit NON-ZERO (the check really detects the bug).

The pre-fix tree is `git -C <repo> archive <base_sha>` extracted into a temp dir: byte-for-byte the
tree before the change, built with a READ-ONLY git command (no branch, no index, no working-tree
mutation — the run's shared tree is never touched). The CURRENT test modules are then copied into
that tree, because they did not exist at the base commit; nothing else is copied. A production
module that did not exist at the base is therefore MISSING in the pre-fix tree, and its test fails
on an import error — that is itself an honest pre-fix failure, never a reason to copy the fix in
and hide it; it is PRINTED as an explicit exemption instead of being left silent.

`V-review-verdict-distinction` has no test module: its check is the local probe below, which reads
the canonical `factory-rule` blocks from the root it is pointed at — the same function serves both
runs, so the block that is absent at the base commit fails there and passes here.

Cross-checks run before anything slow, and `--registry-only` stops after them:
  - every `vaccine: <ID>` of the disposition file is registered, and every registered ID is named
    by at least one `fixed:` line (reported both ways — an orphaned vaccine is as bad as a
    registered ID nobody claims);
  - every item carries `fixed:` or `deferred:`, and a `deferred:` item carries `reason:`;
  - the ids RV-1..RV-20, BL-1..BL-8 and PR-1..PR-18 are all present;
  - every registered test module (and the `test_prompt_structure.py` helper) exists in the
    working tree.
The disposition file lives under the gitignored `.code-factory/`, so a FRESH CLONE keeps no run
artifact. Its absence is NOT a failure: the harness's durable ground truth is its own REGISTRY. A
missing file prints `note - <path> absent (a fresh clone keeps no run artifact):
registry/disposition cross-checks skipped`, the registry-only checks still run, and the proof
continues — exit 0. When the file IS present the cross-checks run and still fail the harness for
any disagreement.

Invariant: a vaccine is proven ONLY by a pair of runs — PASS on the working tree and NON-ZERO on
the pre-fix tree. Every `current PASS, pre-fix FAIL` line prints WHY the pre-fix run failed (the
first `AssertionError`/`Error` line, truncated), because "some non-zero exit" alone is not a proof.
A production module that did not exist at the base commit makes the pre-fix import fail by
construction; that is still an honest bite, but it is named as an explicit exemption
(`[exempt: module '<name>' did not exist at the base commit]`) instead of being passed off as a
behavioural difference. A green pre-fix run or a red working-tree run is reported as a failure of
THIS harness; none of them can end in a false pass.

The base commit is resolved against git itself, never against the hand-maintained constant alone:
without an explicit `--base` the release commit the flow recorded in
`.code-factory/state/git-head.txt` leads and its PARENT is replayed as "before the change", so a
`BASE_SHA` that drifted costs a printed note, not the proof; a fresh clone without the recorded
file falls back to the constant and is still held to it. A base git cannot resolve, a recorded
commit this repository does not know, and a base that is not an ancestor of HEAD are FAIL (exit 1)
naming the reason — a wrong base proves the wrong release, which is a red, never a skip. The honest
SKIP (exit 3) is kept for the single case where nothing can be answered at all: git is unavailable,
or the history holds no previous release to replay.

Exit code 0 = every vaccine bites and every cross-check holds, 1 = a vaccine did not bite, a
cross-check failed, or the base commit contradicts the repository, 3 = the base commit cannot be
answered for at all (no git, or no previous release) so nothing could be proven.
"""
from __future__ import annotations

import argparse
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import NamedTuple

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]

DISPOSITION = ".code-factory/logs/findings-disposition.md"
RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
STATE_HEAD = ".code-factory/state/git-head.txt"
SCRIPTS_REL = pathlib.PurePosixPath(".agents/skills/code-factory/scripts")

# The release's base commit: the FALLBACK replayed as "before the change" when the flow's own
# record is absent (`.code-factory/state/git-head.txt` is gitignored, so a fresh clone keeps no run
# artifact). When the record IS there, the recorded release commit's parent leads and a drifted
# constant only costs a note; `--base` overrides both for a later release.
BASE_SHA = "fb43f2a400bfac6f1edcffafc5a09370425b4357"

# A vaccine whose check is the local probe rather than a test module.
LOCAL = "LOCAL"
# The sibling parser the new text-contract self-tests import; copied so those imports resolve in
# the pre-fix tree as well (`test_prompt_structure.py` itself predates the base commit).
HELPER_TEST = "test_prompt_structure.py"

# The disposition contract: every group of the task's three sources, exhaustively.
EXPECTED_GROUPS = (("RV", 20), ("BL", 8), ("PR", 18))

# id -> the self-test module that carries its check (`LOCAL` = the probe in this file). `ids come
# from the disposition file`: a finding's `vaccine:` names one of these, and the cross-check refuses
# a registry id that no `fixed:` line claims.
REGISTRY: tuple[tuple[str, str], ...] = (
    ("V-memory-identity", "test_memory_project.py"),
    ("V-memory-fresh", "test_memory_project.py"),
    ("V-memory-onerecord", "test_memory_project.py"),
    ("V-memory-compact", "test_memory_project.py"),
    ("V-memory-carried", "test_memory_project.py"),
    ("V-memory-actuality", "test_memory_project.py"),
    ("V-memory-prev2", "test_factory_model.py"),
    ("V-memory-single-contract", "test_factory_model.py"),
    ("V-memory-backlog-kind", "test_factory_model.py"),
    ("V-model-precedence", "test_model_precedence.py"),
    ("V-model-attribution", "test_model_attribution.py"),
    ("V-review-routing", "test_review_report_only.py"),
    ("V-sa-guarantee", "test_security_audit_guarantee.py"),
    ("V-flow-contracts", "test_flow_contracts.py"),
    ("V-review-delivery", "test_review_followup_task.py"),
    ("V-review-acceptance-stop", "test_verify_acceptance.py"),
    ("V-docs-english", "test_check_english_only.py"),
    ("V-doc-validator", "test_validate_documentation.py"),
    ("V-version-cargo", "test_version_manager.py"),
    ("V-merge-shardsort", "test_merge_findings.py"),
    ("V-genreport-error", "test_gen_code_changes_report.py"),
    ("V-rules-message", "test_factory_rules.py"),
    ("V-precedent-index", "test_precedent_index.py"),
    ("V-review-verdict-distinction", LOCAL),
)

# `- RV-12: fixed: ... | vaccine: V-memory-identity` — one item per finding, never wrapped.
ITEM_RE = re.compile(r"^-\s+([A-Z][A-Z0-9]*-\d+)\s*:\s*(.*)$")
VACCINE_RE = re.compile(r"vaccine\s*:\s*([A-Za-z0-9_.-]+(?:\s*,\s*[A-Za-z0-9_.-]+)*)")
# Tolerates the `<!-- factory-rule: <id> begin -->` / `end` markers with any inner spacing.
BLOCK_RE = r"<!--\s*factory-rule:\s*{id}\s*begin\s*-->(.*?)<!--\s*factory-rule:\s*{id}\s*end\s*-->"
# (canonical rule id, fragment its block must carry) — the pre-fix tree predates both facts.
LOCAL_PROBES = (
    ("review-gate-policy", "judges the delivered review"),
    ("review-report-only", "results.review="),
)
# The output of a self-test is long; a failure line is what names the defect for the reader.
HINT_WIDTH = 200
# A pre-fix run may legitimately fail on an import: a production module the fix introduced simply
# does not exist at the base commit (see pre_fix_hint).
MODULE_MISSING_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
# The exception line of a traceback (`AssertionError: …`, `ModuleNotFoundError: …`) — the line that
# states WHY the pre-fix run failed, unlike the `raise …` source line above it.
ERROR_LINE_RE = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?[A-Za-z_]*(?:Error|Exception):")


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so vaccine ids and paths survive a legacy Windows console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


# --------------------------------------------------------------------------------------------
# The disposition file: one item per finding, its `fixed:`/`deferred:` state and its vaccine
# --------------------------------------------------------------------------------------------
class Item(NamedTuple):
    """One finding line of the disposition file."""

    line: int
    ident: str
    text: str

    @property
    def is_fixed(self) -> bool:
        return "fixed:" in self.text

    @property
    def is_deferred(self) -> bool:
        return "deferred:" in self.text

    @property
    def vaccines(self) -> tuple[str, ...]:
        """Every vaccine id the item names, in order (`vaccine: A, B` names two)."""
        match = VACCINE_RE.search(self.text)
        if not match:
            return ()
        return tuple(part.strip() for part in match.group(1).split(",") if part.strip())

    @property
    def vaccine(self) -> str:
        """The first vaccine id the item names, or "" when it names none."""
        found = self.vaccines
        return found[0] if found else ""


def parse_disposition(root: pathlib.Path, problems: list[str]) -> tuple[list[Item], bool]:
    """Every `- <ID>: ...` item of the disposition file, plus whether the file exists at all.

    A MISSING file is deliberately NOT a problem: `.code-factory/` is gitignored, so a fresh clone
    keeps no run artifact. The harness's durable ground truth is its own REGISTRY; the caller prints
    a note and skips the cross-checks that need the artifact. A file that IS there is held to the
    whole contract below.
    """
    path = root / DISPOSITION
    if not path.is_file():
        return [], False
    items: list[Item] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = ITEM_RE.match(line.strip())
        if match is None:
            continue
        item = Item(number, match.group(1), match.group(2))
        items.append(item)
        if not (item.is_fixed or item.is_deferred):
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` carries neither `fixed:` "
                            "nor `deferred:` — every finding is disposed of explicitly")
        if item.is_deferred and "reason:" not in item.text:
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is deferred without "
                            "`reason:` — a deferred finding says why it waits")
        if item.is_fixed and not item.vaccine:
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is fixed without "
                            "`vaccine: <ID>` — an unfrozen fix cannot be proven")
    if not items:
        problems.append(f"{DISPOSITION}:1: no `- <ID>: ...` item found — the format changed")
    return items, True


def check_registry(items: list[Item], disposed: bool = True) -> tuple[list[str], list[str]]:
    """The cross-checks: (hard problems, registry/disposition drift reported both ways).

    A hard problem breaks the upstream contract the harness reads (an undisposed item, an
    incomplete id inventory, a missing test module) — nothing can be proven then. Drift is the two
    lists disagreeing about WHICH vaccines exist: it does not stop the proof, because proving an
    orphaned vaccine is still worth doing, but it keeps the run red — a vaccine no finding claims
    proves nothing about this release, and a finding whose vaccine is unregistered is never run.

    `disposed=False` means the disposition file is absent (a fresh clone): the registry is then the
    only ground truth, so the registry-INTRINSIC checks (unique ids, every module present) still
    run, while the two lists cannot be compared at all and the comparison is skipped, not faked.
    """
    problems: list[str] = []
    registered = [vaccine for vaccine, _tool in REGISTRY]
    registered_set = set(registered)
    if len(registered_set) != len(registered):
        duplicates = sorted({vid for vid in registered if registered.count(vid) > 1})
        problems.append(f"REGISTRY: duplicate id(s) {', '.join(duplicates)} — one vaccine, one entry")

    drift: list[str] = []
    if disposed:
        named = {vid for item in items if item.is_fixed for vid in item.vaccines}
        claimed = {vid for item in items for vid in item.vaccines}
        drift = [f"{DISPOSITION}: `{vaccine}` is named by a finding but is NOT registered in REGISTRY — "
                 "its check would never be executed"
                 for vaccine in sorted(claimed - registered_set)]
        drift += [f"REGISTRY: `{vaccine}` is registered but no `fixed:` line of {DISPOSITION} names it "
                  "— an orphaned vaccine proves nothing"
                  for vaccine in sorted(registered_set - named)]

        present = {item.ident for item in items}
        for prefix, count in EXPECTED_GROUPS:
            missing = [f"{prefix}-{index}" for index in range(1, count + 1)
                       if f"{prefix}-{index}" not in present]
            if missing:
                problems.append(f"{DISPOSITION}: missing id(s) {', '.join(missing)} — the "
                                f"{prefix} inventory must be complete ({prefix}-1..{prefix}-{count})")

    for tool in sorted({tool for _vaccine, tool in REGISTRY if tool != LOCAL} | {HELPER_TEST}):
        if not (SCRIPT_DIR / tool).is_file():
            problems.append(f"{SCRIPT_DIR.name}/{tool}: file is missing — the vaccine of "
                            "REGISTRY cannot be executed")
    return problems, drift


# --------------------------------------------------------------------------------------------
# The local probe (`V-review-verdict-distinction`): the rulebook block, read from a given root
# --------------------------------------------------------------------------------------------
def probe_review_verdict_distinction(root: pathlib.Path) -> list[str]:
    """Every (rule id, fragment) of LOCAL_PROBES must live inside that rule's canonical block.

    `root` is the tree the probe is pointed at — the working tree in the current run and the
    pre-fix tree in the second one, so the ONE function serves both and the base commit, which
    predates both facts, fails here.
    """
    path = root / RULEBOOK
    if not path.is_file():
        return [f"{RULEBOOK}: file is missing — the review distinction cannot be read"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for rule_id, fragment in LOCAL_PROBES:
        block = re.search(BLOCK_RE.format(id=re.escape(rule_id)), text, re.S)
        if block is None:
            problems.append(f"{RULEBOOK}: no `{rule_id}` canonical block — the distinction between "
                            "the review's acceptance and the verdict on the reviewed code is not "
                            "stated where the rulebook keeps it")
        elif fragment not in block.group(1):
            line = text.count("\n", 0, block.start()) + 1
            problems.append(f"{RULEBOOK}:{line}: the `{rule_id}` block must contain {fragment!r} — "
                            "a review run's acceptance judges the delivered review while the "
                            "verdict stays recorded as `results.review=`")
    return problems


# --------------------------------------------------------------------------------------------
# The pre-fix tree: a read-only `git archive` of the base commit, extracted under tempfile
# --------------------------------------------------------------------------------------------
def commit_exists(repo: pathlib.Path, sha: str) -> tuple[bool, str]:
    """(does `git cat-file -e <sha>` succeed, git's message)."""
    try:
        res = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha], capture_output=True)
    except OSError as exc:                        # no git on PATH at all
        return False, str(exc)
    return res.returncode == 0, res.stderr.decode("utf-8", "replace").strip()


def extract_base_tree(repo: pathlib.Path, sha: str, dest: pathlib.Path) -> str:
    """Extract `git archive <sha>` into `dest`; "" on success, a reason otherwise.

    READ-ONLY: `git archive` reads the object database and writes nothing into the repository.
    """
    try:
        res = subprocess.run(["git", "-C", str(repo), "archive", sha], capture_output=True)
    except OSError as exc:
        return str(exc)
    if res.returncode != 0:
        message = res.stderr.decode("utf-8", "replace").strip()
        return message or f"git archive exited {res.returncode}"
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(res.stdout), mode="r:") as archive:
            try:
                archive.extractall(dest, filter="data")   # PEP 706: the tarball cannot escape dest
            except TypeError:                            # an interpreter without the filter argument
                archive.extractall(dest)
    except tarfile.TarError as exc:
        return f"the archive of {sha} is unreadable: {exc}"
    return ""


def copy_tests(dest_scripts: pathlib.Path) -> list[str]:
    """Copy the CURRENT test modules REGISTRY needs into the pre-fix tree; report what is missing."""
    problems: list[str] = []
    dest_scripts.mkdir(parents=True, exist_ok=True)
    tools = sorted({tool for _vaccine, tool in REGISTRY if tool != LOCAL} | {HELPER_TEST})
    for tool in tools:
        source = SCRIPT_DIR / tool
        if not source.is_file():
            problems.append(f"{tool}: not in the working tree — its vaccines cannot be copied")
            continue
        shutil.copyfile(source, dest_scripts / tool)
    return problems


# --------------------------------------------------------------------------------------------
# Running one test module
# --------------------------------------------------------------------------------------------
class Run(NamedTuple):
    """The outcome of one test module: `code` is None only when it hit the timeout."""

    code: int | None
    stdout: str
    stderr: str
    seconds: float

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    @property
    def verdict(self) -> str:
        return f"exit {self.code}" if self.code is not None else "timeout"


def run_module(scripts: pathlib.Path, tool: str, timeout: int) -> Run:
    """Execute one test module with the running interpreter, its own directory on sys.path."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"     # the child's bytes are decoded as UTF-8 below
    started = _now()
    try:
        res = subprocess.run([sys.executable, str(scripts / tool)], cwd=str(scripts),
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             env=env, timeout=timeout)
        return Run(res.returncode, res.stdout, res.stderr, _now() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return Run(None, stdout, stderr, _now() - started)


def _now() -> float:
    return time.monotonic()


def _shortened(text: str) -> str:
    return text if len(text) <= HINT_WIDTH else text[:HINT_WIDTH - 1] + "\u2026"


def failure_hint(run: Run) -> str:
    """The line that names the defect, or the last meaningful one; trimmed for a one-line report."""
    lines = [line.strip() for line in run.output.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("FAIL", "Traceback", "AssertionError")) or "Error:" in line:
            return _shortened(line)
    return _shortened(lines[-1]) if lines else "(no output)"


def missing_module(output: str) -> str:
    """The top-level module a `ModuleNotFoundError` in `output` names ("" when there is none)."""
    match = MODULE_MISSING_RE.search(output)
    return match.group(1).split(".")[0] if match else ""


def module_existed_at_base(pre_scripts: pathlib.Path, name: str) -> bool:
    """True when `name` is importable in the pre-fix tree: a module file or a package directory."""
    return ((pre_scripts / f"{name}.py").is_file()
            or (pre_scripts / name / "__init__.py").is_file())


def pre_fix_hint(run: Run, pre_scripts: pathlib.Path) -> str:
    """What made the pre-fix run fail, plus an explicit exemption for a module absent at base.

    A non-zero exit alone is not a proof: the reason is printed next to every `current PASS,
    pre-fix FAIL` line (the first `AssertionError`/`Error` line, truncated). The pre-fix tree is the
    base commit with the CURRENT tests copied into it, so a production module the fix introduced is
    MISSING there and its import fails by construction — an honest bite, but it is named as an
    exemption (`[exempt: module '<name>' did not exist at the base commit]`) instead of being
    presented as a behavioural difference.
    """
    lines = [line.strip() for line in run.output.splitlines() if line.strip()]
    hint = next((line for line in lines if ERROR_LINE_RE.match(line)), "")
    hint = _shortened(hint) if hint else failure_hint(run)
    name = missing_module(run.output)
    if name and not module_existed_at_base(pre_scripts, name):
        return (f"{hint} [exempt: module '{name}' did not exist at the base commit, so the "
                f"pre-fix import fails by construction]")
    return hint


# --------------------------------------------------------------------------------------------
# The two-run proof, one vaccine at a time
# --------------------------------------------------------------------------------------------
def prove(root: pathlib.Path, base_sha: str, timeout: int, drift: list[str]) -> int:
    """Build the pre-fix tree, run every vaccine twice and print one honest line per vaccine."""
    short = base_sha[:7]
    known, message = commit_exists(root, base_sha)
    if not known:
        detail = f" ({message})" if message else ""
        if shutil.which("git") is None:
            print(f"SKIP - vaccination cannot run without git{detail}: the proof needs the "
                  "release base commit, and nothing was proven")
            return 3
        # resolve_base already accepted this commit: a disappearance under the harness is a red.
        print(f"FAIL - the base commit {base_sha} cannot be replayed{detail}: nothing was proven")
        return 1

    tools = sorted({tool for _vaccine, tool in REGISTRY if tool != LOCAL})
    with tempfile.TemporaryDirectory(prefix="vaccination-") as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        pre_root = tmp / "pre"
        reason = extract_base_tree(root, base_sha, pre_root)
        if reason:
            print(f"FAIL - the pre-fix tree of {base_sha} could not be built: {reason}")
            return 1
        pre_scripts = pre_root / SCRIPTS_REL
        copy_problems = copy_tests(pre_scripts)
        if copy_problems:
            print("FAIL - the pre-fix tree is incomplete, so no vaccine can be proven:")
            for problem in copy_problems:
                print(f"  - {problem}")
            return 1

        # Every distinct module runs ONCE per tree; its vaccines share that single run.
        current: dict[str, Run] = {}
        prefix: dict[str, Run] = {}
        for step, tool in enumerate(tools, 1):
            print(f"  [{step}/{len(tools)}] working tree: {tool}", file=sys.stderr, flush=True)
            current[tool] = run_module(SCRIPT_DIR, tool, timeout)
            print(f"  [{step}/{len(tools)}] pre-fix {short}: {tool}", file=sys.stderr, flush=True)
            prefix[tool] = run_module(pre_scripts, tool, timeout)

        bitten = 0
        failures: list[str] = []
        for vaccine, tool in REGISTRY:
            if tool == LOCAL:
                here = probe_review_verdict_distinction(root)
                there = probe_review_verdict_distinction(pre_root)
                if here:
                    message = (f"{vaccine}: current FAIL — the local probe is red on the working "
                               f"tree: {here[0]}")
                elif not there:
                    message = (f"{vaccine}: current PASS, pre-fix PASS — TAUTOLOGY: {RULEBOOK} at "
                               f"{short} already carries every fragment the local probe looks for, "
                               "so its check does not test what the fix changed")
                else:
                    print(f"{vaccine}: current PASS, pre-fix FAIL (the probe finds "
                          f"{len(there)} missing fact(s) in {RULEBOOK})")
                    bitten += 1
                    continue
                print(message)
                failures.append(message)
                continue

            green_here = current[tool].code == 0
            green_there = prefix[tool].code == 0
            if not green_here:
                message = (f"{vaccine}: current FAIL ({current[tool].verdict}) — {tool} is red on "
                           f"the working tree: {failure_hint(current[tool])}")
            elif green_there:
                message = (f"{vaccine}: current PASS, pre-fix PASS — TAUTOLOGY: {tool} exits 0 on "
                           f"the pre-fix tree {short} as well, so its check does not test what "
                           "the fix changed")
            else:
                print(f"{vaccine}: current PASS, pre-fix FAIL ({prefix[tool].verdict}) — "
                      f"{pre_fix_hint(prefix[tool], pre_scripts)}")
                bitten += 1
                continue
            print(message)
            failures.append(message)

    total = len(REGISTRY)
    if failures:
        line = (f"FAIL - {total - bitten} of {total} vaccine(s) did not bite (fail on {short}, "
                "pass on the working tree)")
        if drift:
            line += f"; {len(drift)} cross-check drift(s) are red as well (see above)"
        print(line)
        return 1
    if drift:
        print(f"FAIL - {bitten} of {total} vaccine(s) bite (fail on {short}, pass on the working "
              f"tree), but {len(drift)} registry/disposition drift(s) are red (see above) — a "
              "vaccine no `fixed:` line claims proves nothing until the two lists agree")
        return 1
    print(f"PASS - {bitten} vaccine(s) bite (fail on {short}, pass on the working tree)")
    return 0


# --------------------------------------------------------------------------------------------
# Resolving the base commit: the recorded release is one input, git is the arbiter
# --------------------------------------------------------------------------------------------
def git_stdout(repo: pathlib.Path, *args: str) -> tuple[bool, str]:
    """(success, stdout-or-error) of one READ-ONLY git call."""
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    except OSError as exc:
        return False, str(exc)
    if res.returncode != 0:
        return False, res.stderr.decode("utf-8", "replace").strip()
    return True, res.stdout.decode("utf-8", "replace").strip()


def is_ancestor(repo: pathlib.Path, sha: str) -> bool:
    """True when `sha` is an ancestor of HEAD — a base that is not replays the wrong release."""
    try:
        res = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, "HEAD"],
                             capture_output=True)
    except OSError:
        return False
    return res.returncode == 0


def resolve_base(repo: pathlib.Path, base: str, explicit: bool) -> tuple[str, str, str]:
    """The base commit to replay as the pre-fix tree: (sha, kind, message).

    kind "ok"   — sha is the commit to replay;
    kind "fail" — git answered and the answer contradicts the inputs (a base that is no commit,
                  a recorded release this repository does not know, a base that is not an ancestor
                  of HEAD): a wrong base proves the WRONG release, so this is red, never a skip;
    kind "skip" — nothing can be answered at all: git is unavailable, or the history holds no
                  previous release (the recorded commit is the root commit).

    Without an explicit `--base` the commit recorded in `.code-factory/state/git-head.txt` leads:
    the flow records the release commit there, so its PARENT is the base — a `BASE_SHA` constant
    that drifted costs a printed note, not the proof. Without the recorded file (a fresh clone
    keeps no run artifact) the constant is the only input and is held to the same git checks, so
    the staleness guard is not inert there.
    """
    if shutil.which("git") is None:
        return "", "skip", "git is not on PATH, so no base commit can be verified"
    recorded_path = repo / STATE_HEAD
    recorded = recorded_path.read_text(encoding="utf-8").strip() if recorded_path.is_file() else ""
    if recorded and not explicit:
        known, _message = git_stdout(repo, "rev-parse", "--verify", f"{recorded}^{{commit}}")
        if not known:
            return "", "fail", (f"{STATE_HEAD} records {recorded}, which this repository does not "
                                "know — the recorded release cannot be replayed")
        ok, parent = git_stdout(repo, "rev-parse", "--verify", f"{recorded}^")
        if not ok:
            return "", "skip", (f"{STATE_HEAD} records the root commit {recorded}: the history "
                                "holds no previous release to replay as the pre-fix tree")
        if parent != base:
            print(f"note - BASE_SHA ({base[:7]}) disagrees with the recorded release: {STATE_HEAD} "
                  f"names {recorded[:7]}, so the base is resolved from git as its parent "
                  f"{parent[:7]} — a stale constant no longer vetoes the proof")
        base = parent
    known, message = commit_exists(repo, base)
    if not known:
        detail = f" ({message})" if message else ""
        return "", "fail", f"the base commit {base} cannot be resolved{detail}"
    if not is_ancestor(repo, base):
        return "", "fail", (f"the base commit {base[:7]} is not an ancestor of HEAD — it would "
                            "replay a tree that is not 'before the fix'")
    return base, "ok", ""


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    use_utf8_output()
    parser = argparse.ArgumentParser(
        description="Prove that every registered vaccine fails on the pre-fix tree and passes on "
                    "the working tree.")
    parser.add_argument("--registry-only", action="store_true",
                        help="run the fast disposition/registry cross-checks and skip the slow runs")
    parser.add_argument("--base", default=None, metavar="SHA",
                        help="base commit replayed as the pre-fix tree (default: the parent of the "
                             "release commit recorded in .code-factory/state/git-head.txt, or the "
                             "pinned release base when no run artifact survives)")
    parser.add_argument("--timeout", type=int, default=900, metavar="SECONDS",
                        help="per-module budget; an overrun is a failure, never a green run")
    args = parser.parse_args(argv)

    problems: list[str] = []
    items, disposed = parse_disposition(REPO_ROOT, problems)
    registry_problems, drift = check_registry(items, disposed)
    problems.extend(registry_problems)
    if problems:
        print(f"FAIL - {len(problems)} vaccination cross-check problem(s) under {REPO_ROOT}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    vaccines = len(REGISTRY)
    groups = ", ".join(f"{prefix}-1..{prefix}-{count}" for prefix, count in EXPECTED_GROUPS)
    if not disposed:
        # Durable ground truth is REGISTRY: no run artifact, nothing to compare it with.
        print(f"note - {DISPOSITION} absent (a fresh clone keeps no run artifact): "
              f"registry/disposition cross-checks skipped")
        print(f"PASS - cross-checks: {vaccines} registered vaccine(s), every one unique and backed "
              f"by an existing test module ({DISPOSITION} absent, so its id inventory and the two "
              f"lists are not compared)")
    elif drift:
        print(f"FAIL - cross-checks: {len(items)} item(s) disposed of, {vaccines} registered "
              f"vaccine(s), every id present ({groups}), but the registry and {DISPOSITION} "
              f"disagree ({len(drift)} place(s), reported both ways):")
        for problem in drift:
            print(f"  - {problem}")
    else:
        print(f"PASS - cross-checks: {len(items)} item(s) disposed of, {vaccines} registered "
              f"vaccine(s), every id present ({groups}), REGISTRY and {DISPOSITION} name each other")

    if args.registry_only:
        return 1 if drift else 0

    base, kind, message = resolve_base(REPO_ROOT, args.base or BASE_SHA, args.base is not None)
    if kind == "skip":
        print(f"SKIP - {message}: nothing could be proven")
        return 3
    if kind == "fail":
        print(f"FAIL - the base commit cannot be established: {message}")
        return 1
    return prove(REPO_ROOT, base, args.timeout, drift)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

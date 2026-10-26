#!/usr/bin/env python3
"""
Vaccination harness: prove that every registered vaccine BITES (zero LLM tokens, stdlib only).

The factory rule `vaccination` demands that a bug found after acceptance first gets a check that
FAILS on the pre-fix state, and only then the fix. A check that also passes BEFORE the fix proves
nothing — it is a tautology, and nothing in the suite would notice. This harness closes that hole
mechanically for the release's whole change set: `.code-factory/logs/findings-disposition.md` names
one `vaccine: <ID>` per fixed finding, the registry below maps every such ID to its FOCUSED check,
and every check is executed TWICE with the same interpreter:

  1. against the WORKING TREE — it must exit 0 (the fix is in place), and
  2. against a PRISTINE PRE-FIX TREE — it must fail with THE VACCINE'S OWN, DECLARED failure.

"Non-zero exit" alone is never proof (a pre-fix run can die of an import error, an unrelated
assertion, an infrastructure error or a timeout). Every registry entry therefore declares, besides
its check, the failure it EXPECTS (`Vaccine.expected`, a regex that the pre-fix run's failure line
must match), and the classification is strict:

  - exit 0 on the working tree — required, otherwise the check is red today and nothing is proven;
  - a timeout, an exit code other than 1, a crash (a non-`AssertionError` exception) or a failure
    line the vaccine does not claim — a HARNESS FAILURE, printed as such and never counted as a
    bite;
  - exit 1 with the declared failure line — the only way a vaccine is proven to bite.

The KINDS (`Vaccine.kind`) are:
  - `module`   — a self-test module; the pre-fix run must fail with the declared assertion line.
  - `structural` — the fix INTRODUCES a production module or a public symbol, so the pre-fix run
    cannot even reach the check: the declared failure must name exactly that missing module/attr
    (the `AttributeError`/`ModuleNotFoundError` is printed as `[structural: ...]`, and the artefact
    must exist on the working tree — a missing import the vaccine does NOT declare stays a harness
    failure).
  - `probe`    — a FOCUSED check written in this file: a few lines that exercise only this
    vaccine's defect. It is used wherever a self-test module bundles several vaccines, because one
    whole-module run aborts at its FIRST failing check and would otherwise validate all the other
    vaccines of that module by accident. Probes reuse the self-tests' own fixtures (imported from
    the module copied into the pre-fix tree) instead of re-inventing them.
  - `local`    — the rulebook probe at the bottom of this file.

The pre-fix tree is `git -C <repo> archive <base_sha>` extracted into a temp dir: byte-for-byte the
tree before the change, built with a READ-ONLY git command (no branch, no index, no working-tree
mutation — the run's shared tree is never touched). The CURRENT test modules are then copied into
that tree, because they did not exist at the base commit; nothing else is copied, so a production
module the fix introduced is genuinely absent there.

TWO RELEASES, TWO BASES. The historical groups (RV/BL/PR) prove the fixes of the previous release
and are replayed against its base (`BASE_SHA`, or `--base`). The `RF` group (review follow-up)
proves THIS run's own fixes, so it declares its own base (`RUN_BASE_SHA` = the release commit whose
tree the run started from) and a pre-fix failure of its own: every `Vaccine` may therefore name a
`base`, and one pre-fix tree is built per distinct base. A release whose vaccines were only ever
proven against an older tree proves nothing about the current change set, which is exactly why the
group exists and why `EXPECTED_GROUPS` lists its finding ids.

`V-review-verdict-distinction` has no test module: its check is the local probe below, which reads
the canonical `factory-rule` blocks from the root it is pointed at — the same function serves both
runs, so the block that is absent at the base commit fails there and passes here.

Cross-checks run before anything slow, and `--registry-only` stops after them:
  - every `vaccine: <ID>` of the disposition file is registered, and every registered ID is named
    by at least one `fixed:` line (reported both ways — an orphaned vaccine is as bad as a
    registered ID nobody claims);
  - every item carries `fixed:` or `deferred:`, and a `deferred:` item carries `reason:`;
  - the ids RV-1..RV-20, BL-1..BL-8, PR-1..PR-18, RF-1..RF-15 and NM-1..NM-2 are all present;
  - every registered test module (and the `test_prompt_structure.py` helper) exists in the
    working tree.
The disposition file lives under the gitignored `.code-factory/`, so a FRESH CLONE keeps no run
artifact. Its absence is NOT a failure: the harness's durable ground truth is its own REGISTRY. A
missing file prints `note - <path> absent (a fresh clone keeps no run artifact):
registry/disposition cross-checks skipped`, the registry-only checks still run, and the proof
continues — exit 0. When the file IS present the cross-checks run and still fail the harness for
any disagreement.

Invariant: a vaccine is proven ONLY by a pair of runs — PASS on the working tree and, on the
pre-fix tree, a failure whose line matches the vaccine's own declared `expected` regex, with the
failure printed next to every `current PASS, pre-fix FAIL` line. A green pre-fix run, a red
working-tree run, a timeout, a crash, an import error the vaccine does not declare, or any failure
line it does not claim is reported as a failure of THIS harness (a separate HARNESS FAILURE
category); none of them can end in a false pass, and none of them is ever counted as a bite.

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
# The base of THIS run's own fixes (run 20261026-2ea2eb55 started from the v12.16.0 release
# commit): every `RF` vaccine is replayed against it, so the new change set is proven by its own
# pre-fix tree instead of riding on an older release's proof.
RUN_BASE_SHA = "9acc1b7e742ea0ebbe9f65b30f3eee80c8b9be5e"

# The four kinds of focused check a vaccine can name (see the module docstring).
MODULE = "module"
STRUCTURAL = "structural"
PROBE = "probe"
LOCAL = "local"
KINDS = (MODULE, STRUCTURAL, PROBE, LOCAL)
# The sibling parser the new text-contract self-tests import; copied so those imports resolve in
# the pre-fix tree as well (`test_prompt_structure.py` itself predates the base commit).
HELPER_TEST = "test_prompt_structure.py"

# The disposition contract: every group of the task's sources, exhaustively. `RF` is this run's
# own review follow-up group: a release whose vaccines were only ever replayed against an older
# base proves nothing about the change set being shipped now.
EXPECTED_GROUPS = (("RV", 20), ("BL", 8), ("PR", 18), ("RF", 15), ("NM", 2))


class Vaccine(NamedTuple):
    """One registered vaccine: its FOCUSED check and the pre-fix failure that proves it bit.

    `target` is a self-test module for `module`/`structural` and the probe's python source for
    `probe` (empty for `local`). `expected` is a regex that the pre-fix run's failure LINE must
    match — "it exited non-zero" is never enough, and a failure the vaccine does not claim is a
    harness failure, not a bite. `base` is the commit replayed as this vaccine's pre-fix tree
    ("" = the release base, i.e. `BASE_SHA`/`--base`).
    """

    ident: str
    kind: str
    target: str
    expected: str
    base: str = ""

    def target_name(self) -> str:
        """How the check is named in the report."""
        if self.kind == PROBE:
            return f"the focused probe of {self.ident}"
        return self.target or RULEBOOK


# --------------------------------------------------------------------------------------------
# The focused probes: one defect each, for the findings whose self-test module bundles several
# vaccines (a whole-module run aborts at its FIRST failing check, so it cannot prove the rest).
# They import the self-tests' own fixtures (the current module is copied into the pre-fix tree),
# so a fixture change is picked up here instead of being duplicated.
# --------------------------------------------------------------------------------------------
PROBE_IDENTITY = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    repo = pathlib.Path(td) / "work"
    t.git_root_commit_repo(repo, "vaccine-identity")
    res = t.run("init", "--repo", str(repo))
    t.expect(res.returncode == 0, f"init must exit 0: {res.stderr!r}")
    lines = (repo / "memory" / "summary.md").read_text(encoding="utf-8").splitlines()
    repo_line = next((i for i, line in enumerate(lines) if line.startswith("repo_path:")), -1)
    t.expect(repo_line >= 0, "summary.md must declare repo_path")
    t.expect(repo_line + 1 < len(lines) and lines[repo_line + 1].startswith("project_id: "),
             "the memory identity must be declared as `project_id:` right after `repo_path:`")
'''

PROBE_ONERECORD = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    run_id = "20261001-aaaabbbb"
    t.write_journal(root,
                    t.journal_entry("2026-10-01T00:00:00Z", "proj", run_id=run_id,
                                    factory_version="12.16.0", marks=True),
                    t.journal_entry("2026-10-02T00:00:00Z", "proj", run_id=run_id,
                                    factory_version="12.16.0", marks=True))
    res = t.run("check", "--repo", str(root), "--no-owner-check")
    t.expect(res.returncode == 1,
             "one run is ONE record: a run_id carried by two records must fail `check`: "
             f"{res.stdout!r} {res.stderr!r}")
    said = res.stdout + res.stderr
    t.expect(run_id in said, "the duplicated run_id must be named")
    t.expect("2026-10-01" in said and "2026-10-02" in said,
             "both records carrying the one run id must be named")
'''

PROBE_COMPACT = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    t.write_journal(root, *[t.journal_entry(f"2026-09-{day:02d}T00:00:00Z", "proj")
                            for day in range(1, 6)])
    before = ((root / "memory" / "change-log.md").read_text(encoding="utf-8"),
              (root / "memory" / "summary.md").read_text(encoding="utf-8"))
    res = t.run("compact", "--repo", str(root), "--threshold", "3", "--keep", "1", "--dry-run")
    t.expect(res.returncode == 0,
             "`compact` must plan the 50/20 fold: the journal is over the threshold, so the plan "
             f"must exit 0: {res.stdout!r} {res.stderr!r}")
    after = ((root / "memory" / "change-log.md").read_text(encoding="utf-8"),
             (root / "memory" / "summary.md").read_text(encoding="utf-8"))
    t.expect(after == before, "a `--dry-run` plan must not write a byte")
'''

PROBE_CARRIED = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    debt = t.unfinished_block(("a debt", "critical", "true"))
    t.write_journal(root,
                    t.journal_entry("2026-09-28T00:00:00Z", "proj", unfinished=debt),
                    t.journal_entry("2026-09-29T00:00:00Z", "proj", run_id="20260929-aaaabbbb",
                                    factory_version="12.16.0", marks=True, unfinished=debt))
    res = t.run("backlog", "--repo", str(root), "--check")
    t.expect(res.returncode == 0,
             "an item carried in the CURRENT record with a reason must pass `backlog --check` "
             f"(a carried debt is legal, only a silent disappearance fails): "
             f"{res.stdout!r} {res.stderr!r}")
    t.expect("carried" in res.stdout.lower(),
             f"the carried item must be reported as carried: {res.stdout!r}")
'''

PROBE_ACTUALITY = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    t.write_journal(root, t.journal_entry("2026-09-28T00:00:00Z", "proj"))
    summary = root / "memory" / "summary.md"
    text = summary.read_text(encoding="utf-8")
    t.expect("\\n## Current state\\n" in text,
             "the template must carry a `## Current state` section")
    summary.write_text(text.replace("\\n## Current state\\n",
                                    "\\n## Current state\\n- 999 test files\\n", 1),
                       encoding="utf-8")
    res = t.run("check", "--repo", str(root), "--strict", "--no-owner-check")
    t.expect(res.returncode == 1,
             "`--strict` must turn a stale `## Current state` into an error "
             f"(the claimed test-file count diverges from the tree): {res.stdout!r} {res.stderr!r}")
'''

PROBE_SINGLE_CONTRACT = '''\
import sys
sys.path.insert(0, ".")
import check_factory_model
import memory_project
if not hasattr(memory_project, "validate_memory"):
    raise AssertionError("the memory contract must have ONE public implementation, "
                         "memory_project.validate_memory, which check_factory_model delegates to")
if not hasattr(check_factory_model, "validate_memory"):
    raise AssertionError("check_factory_model must delegate to memory_project.validate_memory "
                         "instead of carrying its own copy of the contract")
'''

PROBE_BACKLOG_KIND = '''\
import pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    entry = t.journal_entry("2026-09-28T00:00:00Z", "proj", run_id="20260928-aaaabbbb",
                            factory_version="12.16.0", marks=True)
    lines = [line for line in entry.replace("task_type: implement",
                                            "task_type: backlog").splitlines()
             if not line.startswith("results:")]
    at = next(i for i, line in enumerate(lines) if line.startswith("decisions:"))
    lines.insert(at, "results: finding=the record kind is rejected; impact=the discovery record "
                     "cannot be written [verified: probe]")
    t.write_journal(root, "\\n".join(lines) + "\\n")
    res = subprocess.run([sys.executable, "check_factory_model.py", "--memory-only",
                          "--repo", str(root)], capture_output=True, text=True, errors="replace")
    said = res.stdout + res.stderr
    t.expect("invalid task_type" not in said,
             f"`backlog` is a legitimate record kind, not an invalid task_type: {said!r}")
    t.expect(res.returncode == 0,
             f"a record of the `backlog` kind must pass the memory gate: {said!r}")
'''

# --------------------------------------------------------------------------------------------
# This run's own (RF) focused probes: the fixes of the review follow-up, replayed against
# RUN_BASE_SHA. The text/constant fixes have no self-test module of their own, so the probe reads
# the tree it is pointed at (cwd = that tree's scripts dir; the root is three levels up).
# --------------------------------------------------------------------------------------------
PROBE_RCR_EDGE = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
skill = (root / ".agents/skills/code-factory/SKILL.md").read_text(encoding="utf-8")
unconditional = [line for line in skill.splitlines() if re.match(r"^\\s*RCR\\s*-->\\s*M\\s*$", line)]
conditional = [line for line in skill.splitlines() if re.match(r"^\\s*RCR\\s*-->\\|", line)]
if unconditional or len(conditional) < 3:
    raise AssertionError("the RCR node must not fall back to M unconditionally: the reviewer budget "
                         "is split into three conditional edges (rework / hitl stop / auto "
                         f"conditional pass), found {len(conditional)} conditional edge(s) and "
                         f"{len(unconditional)} unconditional one(s)")
'''

PROBE_MEM_WARN_FLOOD = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
text = (root / "prepare_factory.ps1").read_text(encoding="utf-8")
if "$MemReport" not in text or re.search(r"\\(\\$MemCheckOut\\)", text):
    raise AssertionError("the memory CHECK line must print the verdict plus a WARN count: the whole "
                         "multi-line `check` output (one WARN per legacy entry) is for PARSING only "
                         "and must never reach the console ($MemReport, not $MemCheckOut)")
'''

PROBE_AGENTS_SIZE_GATE = '''\
import pathlib, sys
root = pathlib.Path(".").resolve().parents[3]
sys.path.insert(0, ".")
import project_fingerprint as pf
warn = getattr(pf, "AGENTS_SIZE_WARN_BYTES", None)
fail = getattr(pf, "AGENTS_SIZE_FAIL_BYTES", None)
if warn is None or fail is None:
    raise AssertionError("AGENTS.md needs a size gate: project_fingerprint must carry "
                         "AGENTS_SIZE_WARN_BYTES (28 KB) and AGENTS_SIZE_FAIL_BYTES (32 KB), so a "
                         "drifting instructions file is warned about and a too-large one is refused")
size = (root / "AGENTS.md").stat().st_size
if size > fail:
    raise AssertionError(f"AGENTS.md is {size} bytes — over the {fail}-byte hard limit of the size "
                         "gate; the instructions file must be a pointer map, not a copy")
'''

# id -> the FOCUSED check that proves it, and the pre-fix failure it must produce. `ids come from
# the disposition file`: a finding's `vaccine:` names one of these, and the cross-check refuses a
# registry id that no `fixed:` line claims.
REGISTRY: tuple[Vaccine, ...] = (
    Vaccine("V-memory-identity", PROBE, PROBE_IDENTITY,
            r"the memory identity must be declared as `project_id:` right after `repo_path:`"),
    Vaccine("V-memory-fresh", MODULE, "test_memory_project.py",
            r"missing journal must note it"),
    Vaccine("V-memory-onerecord", PROBE, PROBE_ONERECORD,
            r"one run is ONE record: a run_id carried by two records must fail"),
    Vaccine("V-memory-compact", PROBE, PROBE_COMPACT,
            r"`compact` must plan the 50/20 fold"),
    Vaccine("V-memory-carried", PROBE, PROBE_CARRIED,
            r"an item carried in the CURRENT record with a reason must pass"),
    Vaccine("V-memory-actuality", PROBE, PROBE_ACTUALITY,
            r"`--strict` must turn a stale `## Current state` into an error"),
    Vaccine("V-memory-prev2", MODULE, "test_factory_model.py",
            r"canonical memory must warn only about the pre-v2 record"),
    Vaccine("V-memory-single-contract", PROBE, PROBE_SINGLE_CONTRACT,
            r"the memory contract must have ONE public implementation"),
    Vaccine("V-memory-backlog-kind", PROBE, PROBE_BACKLOG_KIND,
            r"`backlog` is a legitimate record kind, not an invalid task_type"),
    Vaccine("V-model-precedence", STRUCTURAL, "test_model_precedence.py",
            r"ModuleNotFoundError: No module named 'model_matrix'"),
    Vaccine("V-model-attribution", STRUCTURAL, "test_model_attribution.py",
            r"ModuleNotFoundError: No module named 'model_attribution'"),
    Vaccine("V-review-routing", MODULE, "test_review_report_only.py",
            r"FAIL flow-guard"),
    Vaccine("V-sa-guarantee", MODULE, "test_security_audit_guarantee.py",
            r"the security_audit guarantee is NOT preserved"),
    Vaccine("V-flow-contracts", MODULE, "test_flow_contracts.py",
            r"the Finish node wires the memory mechanisms"),
    Vaccine("V-review-delivery", STRUCTURAL, "test_review_followup_task.py",
            r"ModuleNotFoundError: No module named 'review_followup_task'"),
    Vaccine("V-review-acceptance-stop", MODULE, "test_verify_acceptance.py",
            r"must name the unverified count"),
    Vaccine("V-docs-english", MODULE, "test_check_english_only.py",
            r"memory_v2_hit: a v2 record with Cyrillic must exit 1"),
    Vaccine("V-doc-validator", MODULE, "test_validate_documentation.py",
            r"bare '\*'/'\|' lines outside a block must be code"),
    Vaccine("V-version-cargo", MODULE, "test_version_manager.py",
            r"validate must exit 1 on a diverging \[workspace\.package\] version"),
    Vaccine("V-merge-shardsort", STRUCTURAL, "test_merge_findings.py",
            r"AttributeError: module 'merge_findings' has no attribute 'shard_key'"),
    Vaccine("V-genreport-error", MODULE, "test_gen_code_changes_report.py",
            r"stderr must be exactly one `error: \.\.\.` line"),
    Vaccine("V-rules-message", MODULE, "test_factory_rules.py",
            r"must point at its four canonical documents"),
    Vaccine("V-precedent-index", MODULE, "test_precedent_index.py",
            r"status must be FRESH here"),
    Vaccine("V-review-verdict-distinction", LOCAL, "",
            r"the `review-gate-policy` block must contain"),
    # ---- RF: this run's own review follow-up, replayed against RUN_BASE_SHA -------------------
    Vaccine("V-rf-a1", PROBE, PROBE_RCR_EDGE,
            r"the RCR node must not fall back to M unconditionally", RUN_BASE_SHA),
    Vaccine("V-rf-a2", MODULE, "test_action_gate.py",
            r"'git push origin HEAD' in hitl must require confirmation", RUN_BASE_SHA),
    Vaccine("V-rf-a3", MODULE, "test_evidence_ledger.py",
            r"an empty signed scope must never be FRESH", RUN_BASE_SHA),
    Vaccine("V-rf-a5", MODULE, "test_validate_documentation.py",
            r"code after a single-line block comment must be a code line", RUN_BASE_SHA),
    Vaccine("V-rf-a6", MODULE, "test_verify_acceptance.py",
            r"SUCCESS without a ledger must be impossible", RUN_BASE_SHA),
    Vaccine("V-rf-a7", MODULE, "test_windows_scripts.py",
            r"a start\.sh\.bak that cannot be created aborts the overwrite", RUN_BASE_SHA),
    Vaccine("V-rf-b1", MODULE, "test_chrome_devtools_mcp.py",
            r"an unreadable \(missing\) package\.json must trigger a reinstall", RUN_BASE_SHA),
    Vaccine("V-rf-b2", MODULE, "test_model_attribution.py",
            r"an empty models_used set must be DEGRADED", RUN_BASE_SHA),
    Vaccine("V-rf-b3", MODULE, "test_model_precedence.py",
            r"a task with no matrix on a config with no default_model leaves every role unresolved",
            RUN_BASE_SHA),
    Vaccine("V-rf-b4", MODULE, "test_review_followup_task.py",
            r"expected 5 criteria, got 4", RUN_BASE_SHA),
    Vaccine("V-rf-b5", MODULE, "test_version_manager.py",
            r"a symlink escaping the repository must be excluded", RUN_BASE_SHA),
    Vaccine("V-rf-c1", PROBE, PROBE_MEM_WARN_FLOOD,
            r"the memory CHECK line must print the verdict plus a WARN count", RUN_BASE_SHA),
    Vaccine("V-rf-c2", MODULE, "test_memory_project.py",
            r"a synthetic backfilled run_id/factory_version must be valid", RUN_BASE_SHA),
    Vaccine("V-rf-c4", STRUCTURAL, "test_calibrate_reviewer.py",
            r"AttributeError: module 'calibrate_reviewer' has no attribute 'REVIEWER_PROMPT_FILES'",
            RUN_BASE_SHA),
    Vaccine("V-rf-c6", PROBE, PROBE_AGENTS_SIZE_GATE,
            r"AGENTS\.md (?:needs a size gate|is \d+ bytes — over the)", RUN_BASE_SHA),
    # ---- NM: this run's own fixes (run 20261026-838dc245) — the named-model stop rule and the
    # unknown-role run error. Replayed against the same base the run started from: at 9acc1b7 no
    # stop rule exists and an invented `models_used` role fell through to DEGRADED.
    Vaccine("V-nm-1", MODULE, "test_no_role_substitution.py",
            r"rule 'model-unavailable-stop' is missing", RUN_BASE_SHA),
    Vaccine("V-nm-2", MODULE, "test_provider_stop.py",
            r"no provider-failure node", RUN_BASE_SHA),
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
# A line that states WHY a run failed: the self-tests print `FAIL …` on a broken case, and a
# traceback ends in `<SomeError>: …`. A bare exit code never names a defect.
FAILURE_LINE_RE = re.compile(r"^(?:FAIL\b|AssertionError:|[A-Za-z_][\w.]*(?:Error|Exception):)")
# An UNCONTROLLED death: a crash the vaccine did not declare. `AssertionError` is deliberately not
# here — it is the self-tests' own way of reporting a broken check. A crash is never proof, except
# for a `structural` vaccine whose declared failure is exactly that missing module/symbol.
CRASH_RE = re.compile(
    r"^(?:[A-Za-z_][\w.]*\.)?(?:ModuleNotFoundError|ImportError|AttributeError|NameError|"
    r"TypeError|KeyError|IndexError|ValueError|OSError|RuntimeError|RecursionError|"
    r"UnboundLocalError|SystemExit)(?::|\s*$)")
# The two shapes a `structural` vaccine may declare: the fix introduces a production module, or a
# public symbol of an existing one.
MISSING_MODULE_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
MISSING_ATTR_RE = re.compile(r"AttributeError: module '([^']+)' has no attribute '([^']+)'")
# The only exit code a controlled check failure uses (`sys.exit(main())` after a failed assertion).
CHECK_FAILED_EXIT = 1


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
    registered = [vaccine.ident for vaccine in REGISTRY]
    registered_set = set(registered)
    if len(registered_set) != len(registered):
        duplicates = sorted({vid for vid in registered if registered.count(vid) > 1})
        problems.append(f"REGISTRY: duplicate id(s) {', '.join(duplicates)} — one vaccine, one entry")
    problems += check_focus()

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

    for tool in sorted(module_targets() | {HELPER_TEST}):
        if not (SCRIPT_DIR / tool).is_file():
            problems.append(f"{SCRIPT_DIR.name}/{tool}: file is missing — the vaccine of "
                            "REGISTRY cannot be executed")
    return problems, drift


def module_targets() -> set[str]:
    """Every self-test module a `module`/`structural` vaccine runs (probes need no file)."""
    return {vaccine.target for vaccine in REGISTRY if vaccine.kind in (MODULE, STRUCTURAL)}


def check_focus() -> list[str]:
    """The focus contract of the registry itself: none of these may silently degrade a proof.

    - a `probe` must COMPILE (a broken probe would fail for the wrong reason);
    - `kind` must be one of the four, and `expected` must be a usable regex;
    - a vaccine proves a SPECIFIC defect, so two vaccines of the same module may not share one
      `expected` string — that is exactly the "one unrelated failure validates them all" defect
      this harness exists to refuse; a shared module is legal only with a distinct signature each
      (and the pre-fix run aborts at its first failing check, so every other signature of that
      module becomes a HARNESS FAILURE, not a bite);
    - a `structural` vaccine must declare the missing module/symbol, and that artefact must EXIST
      on the working tree — otherwise the import error is unrelated to the fix and proves nothing.
    """
    problems: list[str] = []
    signatures: dict[tuple[str, str, str], list[str]] = {}
    for vaccine in REGISTRY:
        if vaccine.kind not in KINDS:
            problems.append(f"REGISTRY: `{vaccine.ident}` has kind `{vaccine.kind}` — one of "
                            f"{', '.join(KINDS)}")
            continue
        try:
            re.compile(vaccine.expected)
        except re.error as exc:
            problems.append(f"REGISTRY: `{vaccine.ident}` has an unusable `expected` regex: {exc}")
            continue
        if vaccine.kind == PROBE:
            try:
                compile(vaccine.target, f"<probe {vaccine.ident}>", "exec")
            except SyntaxError as exc:
                problems.append(f"REGISTRY: the probe of `{vaccine.ident}` does not compile: {exc}")
            continue
        if vaccine.kind == LOCAL:
            continue
        signatures.setdefault((vaccine.base, vaccine.kind, vaccine.target),
                              []).append(vaccine.expected)
        if vaccine.kind == STRUCTURAL:
            problems += check_structural(vaccine)
    for (_base, _kind, target), expected in sorted(signatures.items()):
        if len(set(expected)) != len(expected):
            problems.append(f"REGISTRY: two vaccines of {target} declare the same pre-fix failure "
                            "— one signature cannot prove two different defects")
    return problems


def check_structural(vaccine: Vaccine) -> list[str]:
    """A `structural` vaccine must name a missing module/symbol that the FIX introduces."""
    module = MISSING_MODULE_RE.search(vaccine.expected)
    attribute = MISSING_ATTR_RE.search(vaccine.expected)
    if module is None and attribute is None:
        return [f"REGISTRY: `{vaccine.ident}` is `structural` but does not declare a missing "
                "module (`ModuleNotFoundError: No module named '<name>'`) or a missing symbol "
                "(`AttributeError: module '<module>' has no attribute '<name>'`)"]
    name = (module.group(1) if module else attribute.group(1)).split(".")[0]
    source = SCRIPT_DIR / f"{name}.py"
    if not source.is_file():
        return [f"REGISTRY: `{vaccine.ident}` is `structural` on the module `{name}`, which does "
                "not exist on the working tree — an import error of an absent fix proves nothing"]
    if attribute is not None:
        symbol = re.escape(attribute.group(2))
        if not re.search(rf"^(?:def|class)\s+{symbol}\b|^\s*{symbol}\s*=",
                         source.read_text(encoding="utf-8"), re.M):
            return [f"REGISTRY: `{vaccine.ident}` is `structural` on the symbol "
                    f"`{name}.{attribute.group(2)}`, which the working tree does not define"]
    return []


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


def local_probe(vaccine: Vaccine, root: pathlib.Path) -> tuple[str, str]:
    """(GREEN|BIT|HARNESS, hint) of the rulebook probe pointed at `root`.

    The probe is not a process, so it is classified by hand: a clean read is GREEN, a missing fact
    the vaccine declares is BIT, and a missing fact it does NOT declare is a HARNESS failure (the
    rulebook drifted for another reason, which proves nothing about this fix).
    """
    problems = probe_review_verdict_distinction(root)
    if not problems:
        return GREEN, f"every fact is present in {RULEBOOK}"
    if not re.search(vaccine.expected, problems[0]):
        return HARNESS, (f"the probe reports a failure the vaccine does not claim ({problems[0]}) — "
                         "an unrelated drift is never proof")
    return BIT, f"{len(problems)} missing fact(s) in {RULEBOOK}: {problems[0]}"


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
    for tool in sorted(module_targets() | {HELPER_TEST}):
        source = SCRIPT_DIR / tool
        if not source.is_file():
            problems.append(f"{tool}: not in the working tree — its vaccines cannot be copied")
            continue
        shutil.copyfile(source, dest_scripts / tool)
    return problems


# --------------------------------------------------------------------------------------------
# Running one check (a self-test module or a focused probe)
# --------------------------------------------------------------------------------------------
class Run(NamedTuple):
    """The outcome of one check: `code` is None only when it hit the timeout."""

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
    return _spawn([sys.executable, str(scripts / tool)], scripts, timeout)


def run_probe(scripts: pathlib.Path, source: str, timeout: int) -> Run:
    """Execute one focused probe (`python -c`) with the same interpreter and directory."""
    return _spawn([sys.executable, "-c", source], scripts, timeout)


def run_check(scripts: pathlib.Path, vaccine: Vaccine, timeout: int) -> Run:
    """The vaccine's OWN check: its focused probe, or its self-test module."""
    if vaccine.kind == PROBE:
        return run_probe(scripts, vaccine.target, timeout)
    return run_module(scripts, vaccine.target, timeout)


def _spawn(argv: list[str], cwd: pathlib.Path, timeout: int) -> Run:
    """One child process, its bytes decoded as UTF-8, a timeout reported as `code=None`."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"     # the child's bytes are decoded as UTF-8 below
    started = _now()
    try:
        res = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", env=env, timeout=timeout)
        return Run(res.returncode, res.stdout, res.stderr, _now() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return Run(None, stdout, stderr, _now() - started)


def _now() -> float:
    return time.monotonic()


def _shortened(text: str) -> str:
    return text if len(text) <= HINT_WIDTH else text[:HINT_WIDTH - 1] + "\u2026"


def failure_line(run: Run) -> str:
    """The line that names WHY the run failed ("" when it names none); trimmed for one-line output.

    Only a line that states a defect counts — the self-tests print `FAIL …`, a crashed run ends in
    `<SomeError>: …`. A last line of prose is NOT a failure line: the caller then reports the run
    as a harness failure instead of inventing a reason.
    """
    for line in run.output.splitlines():
        line = line.strip()
        if line and FAILURE_LINE_RE.match(line):
            return _shortened(line)
    return ""


def failure_hint(run: Run) -> str:
    """The failure line, or the last meaningful output line when the run named no defect."""
    line = failure_line(run)
    if line:
        return line
    lines = [line.strip() for line in run.output.splitlines() if line.strip()]
    return _shortened(lines[-1]) if lines else "(no output)"


# "green" = the check passes, "bit" = it failed with the vaccine's own declared defect,
# "harness" = anything else: a timeout, a crash, an unrelated failure, an unclaimed import error.
GREEN, BIT, HARNESS = "green", "bit", "harness"


def classify(run: Run, vaccine: Vaccine, timeout: int) -> tuple[str, str]:
    """(GREEN|BIT|HARNESS, one-line explanation) for ONE run of ONE vaccine's focused check.

    This is the whole strictness of the harness: only a controlled failure whose line matches the
    vaccine's own `expected` regex counts as a bite. A timeout (`code is None`), an exit code other
    than 1 (an argparse/infrastructure death), a crash and a failure line the vaccine does not
    claim are all HARNESS failures, never proof.
    """
    if run.code is None:
        return HARNESS, f"timed out after {timeout}s — a timeout proves nothing"
    if run.code == 0:
        return GREEN, run.verdict
    line = failure_line(run)
    if run.code != CHECK_FAILED_EXIT:
        return HARNESS, (f"exited {run.code}, not {CHECK_FAILED_EXIT} — a controlled check reports "
                         f"its failure with exit {CHECK_FAILED_EXIT}: {failure_hint(run)}")
    if not line:
        return HARNESS, "exited 1 without naming a failure — nothing was proven"
    if not re.search(vaccine.expected, line):
        what = "crashed" if CRASH_RE.match(line) else "failed"
        return HARNESS, (f"{what} for a reason the vaccine does not claim ({line}) — an unrelated "
                         "failure is never proof")
    if CRASH_RE.match(line):
        # Only a `structural` vaccine may declare a crash, and check_focus() has already proven the
        # declared module/symbol exists on the working tree.
        if vaccine.kind != STRUCTURAL:
            return HARNESS, f"crashed ({line}) — a crash is never proof of a behavioural fix"
        return BIT, f"{line} [structural: the fix introduces it, and the working tree has it]"
    return BIT, line


# --------------------------------------------------------------------------------------------
# The two-run proof, one vaccine at a time
# --------------------------------------------------------------------------------------------
def prove(root: pathlib.Path, base_sha: str, timeout: int, drift: list[str]) -> int:
    """Build one pre-fix tree per distinct base, run every vaccine twice, print one line per vaccine.

    `base_sha` is the release base of the historical groups; a vaccine that names its own `base`
    (this run's `RF` group) is replayed against that commit instead. Every base is held to the same
    git checks — a base that is not a commit, or not an ancestor of HEAD, is a red, never a skip.
    """
    short = base_sha[:7]
    if shutil.which("git") is None:
        print("SKIP - vaccination cannot run without git: the proof needs a pre-fix tree, and "
              "nothing was proven")
        return 3
    bases = {vaccine.base or base_sha for vaccine in REGISTRY}
    for base in sorted(bases):
        known, message = commit_exists(root, base)
        if not known:
            detail = f" ({message})" if message else ""
            print(f"FAIL - the base commit {base} cannot be replayed{detail}: nothing was proven")
            return 1
        if not is_ancestor(root, base):
            print(f"FAIL - the base commit {base[:7]} is not an ancestor of HEAD — it would replay "
                  "a tree that is not 'before the fix'")
            return 1

    with tempfile.TemporaryDirectory(prefix="vaccination-") as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        pre_scripts: dict[str, pathlib.Path] = {}
        pre_roots: dict[str, pathlib.Path] = {}
        for base in sorted(bases):
            tree = tmp / f"pre-{base[:7]}"
            print(f"  building the pre-fix tree of {base[:7]}", file=sys.stderr, flush=True)
            reason = extract_base_tree(root, base, tree)
            if reason:
                print(f"FAIL - the pre-fix tree of {base} could not be built: {reason}")
                return 1
            copy_problems = copy_tests(tree / SCRIPTS_REL)
            if copy_problems:
                print("FAIL - the pre-fix tree is incomplete, so no vaccine can be proven:")
                for problem in copy_problems:
                    print(f"  - {problem}")
                return 1
            pre_roots[base] = tree
            pre_scripts[base] = tree / SCRIPTS_REL

        runs: dict[tuple[str, str, str], Run] = {}

        def run_once(scripts: pathlib.Path, vaccine: Vaccine) -> Run:
            """One run per (tree, check): the two groups may share a module on different bases."""
            key = (str(scripts), vaccine.kind, vaccine.target)
            if key not in runs:
                runs[key] = run_check(scripts, vaccine, timeout)
            return runs[key]

        bitten = 0
        failures: list[str] = []        # a vaccine that did not prove its defect
        harness: list[str] = []         # a check whose failure cannot be trusted as proof
        total_steps = len(REGISTRY) * 2
        for step, vaccine in enumerate(REGISTRY, 1):
            base = vaccine.base or base_sha
            where = f"{base[:7]}" if base != base_sha else short
            how = ("the local rulebook probe" if vaccine.kind == LOCAL
                   else f"{vaccine.target_name()} @ {where}")
            if vaccine.kind == LOCAL:
                here = local_probe(vaccine, root)
                there = local_probe(vaccine, pre_roots[base])
            else:
                print(f"  [{2 * step - 1}/{total_steps}] working tree: {vaccine.ident}",
                      file=sys.stderr, flush=True)
                here = classify(run_once(SCRIPT_DIR, vaccine), vaccine, timeout)
                print(f"  [{2 * step}/{total_steps}] pre-fix {where}: {vaccine.ident}",
                      file=sys.stderr, flush=True)
                there = classify(run_once(pre_scripts[base], vaccine), vaccine, timeout)
            if here[0] != GREEN:
                message = (f"{vaccine.ident}: current FAIL — {how} is red on the working tree: "
                           f"{here[1]}")
                failures.append(message)
            elif there[0] == GREEN:
                message = (f"{vaccine.ident}: current PASS, pre-fix PASS — TAUTOLOGY: {how} passes "
                           f"on the pre-fix tree {short} as well, so its check does not test what "
                           "the fix changed")
                failures.append(message)
            elif there[0] == BIT:
                print(f"{vaccine.ident}: current PASS, pre-fix FAIL — {there[1]}")
                bitten += 1
                continue
            else:
                message = f"{vaccine.ident}: HARNESS FAILURE — {there[1]}"
                harness.append(message)
            print(message)

    total = len(REGISTRY)
    spans = " / ".join(sorted({v.base[:7] if v.base else short for v in REGISTRY}))
    if failures or harness:
        line = (f"FAIL - {total - bitten} of {total} vaccine(s) did not bite (fail on {spans}, "
                "pass on the working tree)")
        if harness:
            line += (f"; {len(harness)} of them are HARNESS FAILURES (a timeout, a crash, an "
                     "unrelated failure or an unclaimed import error is never proof)")
        if drift:
            line += f"; {len(drift)} cross-check drift(s) are red as well (see above)"
        print(line)
        return 1
    if drift:
        print(f"FAIL - {bitten} of {total} vaccine(s) bite (fail on {spans}, pass on the working "
              f"tree), but {len(drift)} registry/disposition drift(s) are red (see above) — a "
              "vaccine no `fixed:` line claims proves nothing until the two lists agree")
        return 1
    print(f"PASS - {bitten} vaccine(s) bite (fail on {spans}, pass on the working tree), each with "
          "the failure it declares")
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
                        help="base commit of the HISTORICAL (RV/BL/PR) groups, replayed as their "
                             "pre-fix tree (default: the parent of the release commit recorded in "
                             ".code-factory/state/git-head.txt, or the pinned release base when no "
                             "run artifact survives). The RF group always uses RUN_BASE_SHA, the "
                             "commit this run started from")
    parser.add_argument("--timeout", type=int, default=900, metavar="SECONDS",
                        help="per-check budget; an overrun is a HARNESS FAILURE, never a green run")
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
    kinds = ", ".join(f"{sum(1 for v in REGISTRY if v.kind == kind)} {kind}" for kind in KINDS)
    if not disposed:
        # Durable ground truth is REGISTRY: no run artifact, nothing to compare it with.
        print(f"note - {DISPOSITION} absent (a fresh clone keeps no run artifact): "
              f"registry/disposition cross-checks skipped")
        print(f"PASS - cross-checks: {vaccines} registered vaccine(s) ({kinds}), every one unique, "
              f"its check existing and its expected pre-fix failure declared ({DISPOSITION} absent, "
              f"so its id inventory and the two lists are not compared)")
    elif drift:
        print(f"FAIL - cross-checks: {len(items)} item(s) disposed of, {vaccines} registered "
              f"vaccine(s), every id present ({groups}), but the registry and {DISPOSITION} "
              f"disagree ({len(drift)} place(s), reported both ways):")
        for problem in drift:
            print(f"  - {problem}")
    else:
        print(f"PASS - cross-checks: {len(items)} item(s) disposed of, {vaccines} registered "
              f"vaccine(s) ({kinds}), every id present ({groups}), REGISTRY and {DISPOSITION} name "
              f"each other")

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

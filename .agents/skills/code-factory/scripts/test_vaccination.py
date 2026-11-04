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
    NO vaccine of this kind is registered any more, and `check_focus` refuses a new one: a
    whole-module signature is the FIRST assertion of that module on the pre-fix tree, so any later
    assertion added to the same module can overtake it — the bite would then belong to another
    defect, or become a harness failure. The kind is kept in the vocabulary only so the refusal can
    be stated by name; every former `module` vaccine is now an isolated `probe`.
  - `structural` — the fix INTRODUCES a production module or a public symbol, so the pre-fix run
    cannot even reach the check: the declared failure must name exactly that missing module/attr
    (the `AttributeError`/`ModuleNotFoundError` is printed as `[structural: ...]`, and the artefact
    must exist on the working tree — a missing import the vaccine does NOT declare stays a harness
    failure).
  - `probe`    — a FOCUSED check written in this file: a few lines that exercise only this
    vaccine's defect. Every vaccine is one of these unless a structural absence is the defect: a
    whole-module run aborts at its FIRST failing check and would otherwise validate all the other
    vaccines of that module by accident. Probes reuse the self-tests' own fixtures and published
    checks (imported from the module copied into the pre-fix tree) instead of re-inventing them.
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

CLAIMS, AND THE ONE GAP THAT CANNOT BE CLOSED. Every vaccine must be claimed: the `CC`/`FK`/`FB`
runs ship their own claim lists (`RELEASE_CLAIMS`), the run-local `FX`/`DP`/`IV` groups are claimed
by the disposition file, and the older `RV`/`BL`/`PR`/`RF`/`NM` groups are claimed by
`RECONSTRUCTED_CLAIMS` — one claim per VACCINE, each carrying an evidence pointer (`CHANGELOG.md`,
`memory/change-log.md` or a release commit) whose anchor text `check_reconstructed_claims` RE-READS,
so a claim whose evidence rotted is a red. Those five groups' per-FINDING ids (`RV-1`..`RV-20`,
`BL-1`..`BL-8`, `PR-1`..`PR-18`, `RF-1`..`RF-15`, `NM-1`..`NM-2`) are NOT recoverable: the
disposition files that carried them were gitignored and never committed, and the v12.17.0 journal
itself records that the RV/PR item texts in that file were reconstructions of an overwritten review
log. `RECONSTRUCTED_CLAIM_GAPS` states those gaps and every run PRINTS them — a claim is never
numbered again to look complete.

The `CC` group closes the same hole for the 12.19 CLEAN-CODE release: its six checks are replayed
against the v12.18.0 release commit the run started from (`CLEAN_CODE_BASE_SHA`), so the release
the harness claims to cover is covered by its own pre-fix tree. That release left no per-run
disposition file behind (a clone keeps none), so its finding list lives in `CLEAN_CODE_FINDINGS`
next to the vaccines it claims, and the SAME two-way cross-check runs over it: an orphaned CC
vaccine and a claim no vaccine answers are both red.

The `FX` group is THIS run's own change set (run 20261031-dd7ffa0e): one focused check per TESTABLE
code fix, replayed against `FX_BASE_SHA`, so the fixes being shipped now are proven against the tree
the run started from. Its claim is the disposition the run itself wrote — `FX-1..FX-15`, one item per
fix, each naming its vaccine — so a fix without a bite cannot be dispositioned as done.

The `DP` group is THIS run's own change set (run 20261101-7cbfae60): the ten findings of the
report-only review that preceded it — the dead `EnterPlanMode` gate in three carriers, the Advisor
agreement gate in the agent document and the flowchart, two dead routing rows, the workflow-prose
pass of the rule reconciler, the extended prompt-structure pins and the operator manual's approval
wording — plus the portable-verify guidance and the `--baseline-files` scope exclusion. Every one
of them is a FOCUSED probe replayed against `DP_BASE_SHA`, because the modules the fixes touched
(`test_flow_contracts.py`, `test_prompt_structure.py`, `test_factory_rules.py`,
`test_validate_documentation.py`) each bundle SEVERAL of these vaccines: a whole-module run would
abort at its first failing check on the pre-fix tree and validate its neighbours by accident. The
probes reuse those modules' own published check functions (`check_advisor_agreement`,
`check_routing_prose`, `check_readme_approval`, `check_plan_approval`, `normalize_path_list`), so a
renamed or removed check becomes a red here instead of a silently narrower proof.

The `FK` group is THIS run's own change set (run 20261103-4489eb00): the conditional Farukon
platform path — the specialist's carriers in `SKILL.md` and `code-factory.md`, the `--farukon`
pre-flight probe, `models.farukon_expert` and its `models_used` logging, the tester-owned replay
acceptance and the new `references/farukon-mcp.md`. Each contract is one focused probe replayed
against `FARUKON_BASE_SHA` (the HEAD the run started from, where no Farukon carrier exists yet); the
fifth probe re-executes the `check_farukon_wiring` section of `test_flow_contracts.py` against that
tree, so the new module check itself is proven red before the feature, and the sixth pins the
`farukon_expert` GENERATOR side of `model_matrix.py` — a pin that must NOT live in a module another
group replays against an older base (V-rf-b3 replays `test_model_precedence.py`, where an exact role
tuple would fail for a reason unrelated to that regression). Its claim lives in
`FARUKON_FINDINGS` next to the vaccines, exactly as `CLEAN_CODE_FINDINGS` does for the 12.19 release.

The `FB` group closes the Farukon/vaccination debt of THIS run (run 20261103-8e939171): applicability
bound to an explicit platform SUBJECT (the generic identity words `integration`/`runtime` alone no
longer activate the role), the handshake timeouts validated as finite non-negative reals BEFORE a
process is started, the complexity reduction of `decide_applicability`/`validate_config`, and the
shared `mcp_json_merge.py` module both MCP helpers now import — plus the W2 hardening of this same
run (violations N-1..N-6): the pre-delegation retry-budget gate (`delegation_gate.py`, which counts
the delegation itself and refuses it once the budget is exhausted), strict model attribution
(`model_attribution.py`, which FAILS a required role whose claim the session wire never confirmed),
the computed change set (`manifest.py`: a backup before a change, sha256 registration, a finish
audit), the classified process signalling plus the session-wire action audit (`action_gate.py`), and
the one deterministic-gate aggregator per phase (`gate_all.py`), the derived fingerprint state
(`project_fingerprint.py --write-state` / `--check-state`, so AGENTS.md carries no hash of itself)
and the accepted|refuted finding disposition end to end (`merge_findings.py` ->
`review_followup_task.py` -> `delegation_gate.py settle`, which refunds a wholly refuted round).
Each one is a FOCUSED probe replayed against `FB_BASE_SHA` (the release commit the run started from),
because `test_farukon_mcp.py` bundles the first four and a whole-module run would abort at its first
failing check. Its claim lives in
`FB_FINDINGS` next to the vaccines.

`V-review-verdict-distinction` has no test module: its check is the local probe below, which reads
the canonical `factory-rule` blocks from the root it is pointed at — the same function serves both
runs, so the block that is absent at the base commit fails there and passes here.

Cross-checks run before anything slow, and `--registry-only` stops after them:
  - every `vaccine: <ID>` of the disposition file is registered, and every registered vaccine is
    claimed by name (the disposition, a release claim list or a reconstructed claim) — reported both
    ways, because an orphaned vaccine is as bad as a registered claim nobody can execute;
  - no `module` vaccine is registered: every vaccine isolates ONE defect (see the KINDS above);
  - a claim item carries `fixed:` (with a `vaccine:`), `fixed-prose:` (with `files:` and `because:`,
    documentation/prompt/meta-test material only) or `deferred:` (with `reason:`);
  - every group the disposition ENUMERATES has its complete id inventory, and every vaccine of that
    group is named by one of its items — a group the disposition does not enumerate has to be one of
    the five older groups whose run artifact is not kept (`LOST_GROUPS`);
  - the reconstructed claims are complete one-per-vaccine, keyed by the vaccine id, and each one's
    EVIDENCE is re-read (`check_reconstructed_claims`): a pointer that no longer resolves, or an
    anchor the cited document/revision no longer contains, is a red;
  - every registered vaccine is covered by SOME claim (release list, reconstructed claim, or — for
    the run-local FX/DP/IV groups — the disposition file while it is present); the vaccines a fresh
    clone cannot cover are reported as a note, never as a pass;
  - every registered test module (and the `test_prompt_structure.py` helper) exists in the
    working tree;
  - `check_disposition_fixtures()` re-proves the cross-checks themselves: seven dispositions the
    harness MUST refuse (no claim, fixed without a vaccine, a claim on an unregistered vaccine, a
    prose claim on production code, a prose claim without `because:`, an incomplete inventory, an
    enumerated group whose vaccines are unnamed) plus the shipped file, which must pass;
  - `check_claim_fixtures()` does the same for the reconstructed claims: four claim lists the
    harness MUST refuse (a document that does not exist, an evidence anchor that rotted, an
    unregistered vaccine, a claim re-numbered instead of keyed by its vaccine) plus the shipped
    list, which must pass.

The disposition file lives under the gitignored `.code-factory/`, so a FRESH CLONE keeps no run
artifact. Its ABSENCE is not a failure: the harness's durable ground truth is its own REGISTRY, and a
missing file prints a note. Its PRESENCE without a single `vaccine:` claim and without a group id is
NOT that case any more: it fails, because every fix it disposes of would sit outside the pre-fix
proof. A run whose fixes are mostly prose/meta declares them `fixed-prose:` with `files:` and
`because:` instead of weakening the claim.

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
# The base of the 12.19 CLEAN-CODE release (run 20261031-6dfd0921 started from the v12.18.0 release
# commit): every `CC` vaccine is replayed against it, so the release this harness claims to cover is
# covered by its own pre-fix tree.
CLEAN_CODE_BASE_SHA = "34b7a468fe6036ba58e2848a3cfc85921797bc09"
# The base of THIS run's own fixes (run 20261031-dd7ffa0e started from the v12.19.0 release commit):
# every `FX` vaccine is replayed against it, so the change set being shipped now is proven against
# the tree it started from instead of riding on an older release's proof.
FX_BASE_SHA = "33b8ed84bb0bf5517475e57d5a153a6e835bfdd7"
# The pre-fix HEAD of THIS run's own input-validation gate: `check_input_validation.py` and its
# self-test are new files of the run, so the `IV` vaccine is replayed against the commit whose tree
# holds neither of them — the self-test must be red there for its own first reason.
IV_BASE_SHA = "b72b5e0177690d1c5e5ea0d5f6c9e14311cf3c17"
# The pre-fix HEAD of THIS run's own change set (run 20261101-7cbfae60 started from it): every `DP`
# vaccine is replayed against that commit, so the fixes being shipped now are proven against the
# tree the run started from — never against an older release's base.
DP_BASE_SHA = "f4b48920705a53e1329addaa7847d0cfc35b8369"
# The pre-feature HEAD of THIS run's own change set (run 20261103-4489eb00 started from it): every
# `FK` vaccine is replayed against that commit, so the conditional Farukon path's carriers are
# proven against the tree that predates them (no specialist, no reference file, no wiring).
FARUKON_BASE_SHA = "d5e535104a8e2bc697d809fe51c126f10f8bc6ff"
# The pre-fix HEAD of THIS run's Farukon/vaccination-debt change set (run 20261103-8e939171 started
# from it): every `FB` vaccine is replayed against that commit, so the platform-subject binding, the
# timeout validation, the complexity extraction and the shared merge module are proven against the
# tree that predates them.
FB_BASE_SHA = "4ad54efe8e5aa638cf2d78cddf38f7ca35b425f0"

# The four kinds of focused check a vaccine can name (see the module docstring).
MODULE = "module"
STRUCTURAL = "structural"
PROBE = "probe"
LOCAL = "local"
KINDS = (MODULE, STRUCTURAL, PROBE, LOCAL)
# The sibling parser the new text-contract self-tests import; copied so those imports resolve in
# the pre-fix tree as well (`test_prompt_structure.py` itself predates the base commit).
HELPER_TEST = "test_prompt_structure.py"
# The self-test modules the FOCUSED probes import for their fixtures (a probe reuses the module's
# own helpers instead of re-inventing them, and its published check where the module has one). They
# are copied into every pre-fix tree: no `module` vaccine remains (see check_focus), so these files
# are the ONLY test code the harness ships into a pre-fix tree.
PROBE_FIXTURES = ("test_action_gate.py", "test_check_english_only.py", "test_chrome_devtools_mcp.py",
                  "test_evidence_ledger.py", "test_factory_model.py", "test_factory_rules.py",
                  "test_farukon_mcp.py", "test_flow_contracts.py",
                  "test_gen_code_changes_report.py", "test_input_validation_gate.py",
                  "test_memory_project.py", "test_model_attribution.py",
                  "test_model_precedence.py", "test_no_role_substitution.py",
                  "test_precedent_index.py", "test_review_followup_task.py",
                  "test_review_report_only.py", "test_security_audit_guarantee.py",
                  "test_validate_documentation.py", "test_version_manager.py",
                  "test_verify_acceptance.py", "test_windows_scripts.py")

# The disposition contract: every group of the task's sources, exhaustively. `RF` is an earlier
# review follow-up group, `CC` the 12.19 clean-code release and `FX` THIS run's own fixes: a release
# whose vaccines were only ever replayed against an older base proves nothing about the change set
# being shipped now.
EXPECTED_GROUPS = (("RV", 20), ("BL", 8), ("PR", 18), ("RF", 15), ("NM", 2), ("CC", 6), ("FX", 15),
                   ("DP", 12), ("FK", 6), ("FB", 37))
# The id prefix that tags a registered vaccine with its group. The five historical groups below
# carry no tag (their vaccines are the release-wide `V-memory-*`, `V-model-*`, ... entries).
GROUP_TAGS = {"RF": "V-rf-", "NM": "V-nm-", "CC": "V-cc-", "FX": "V-fx-", "DP": "V-dp-",
              "FK": "V-fk-", "FB": "V-fb-"}
# Groups whose per-run disposition artifact is NOT kept anywhere a clone can read: `.code-factory/`
# is gitignored, so their item texts are gone. Their vaccines are still attributable by tag (RF/NM)
# or by the shared historical release base (RV/BL/PR), and that attribution is what keeps the
# orphan check alive for them. A group that is NOT in this tuple has to be enumerated by the
# disposition in force — this run's own `FX` group cannot claim anything by attribution.
LOST_GROUPS = ("RV", "BL", "PR", "RF", "NM")
# The three historical groups share one release base and carry no id tag, so their vaccines are
# attributable to the set, never to one group.
HISTORICAL_GROUP = "RV/BL/PR"


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

# Two RF vaccines are PROBES, not whole-module runs, for the reason this harness documents: their
# self-test modules now carry later checks that fail EARLIER on the pre-fix tree, so a module run
# would abort on a neighbouring defect and never reach the vaccine's own signature. Each probe
# exercises only its own defect and reuses the module's own fixtures (the current module is copied
# into the pre-fix tree, so `import test_memory_project` resolves there).
PROBE_DOC_COMMENT_CODE = '''\
import sys
sys.path.insert(0, ".")
import validate_documentation as vd
mask = vd._doc_mask(["/* doc */ return safe_value;"])
if mask != [False]:
    raise AssertionError("code after a single-line block comment must be a code line: _doc_mask "
                         f"returned {mask} for `/* doc */ return safe_value;` — a line is "
                         "documentation only when everything outside its comment spans is blank")
'''

PROBE_MEMORY_SYNTHETIC_BACKFILL = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    t.write_journal(root, t.journal_entry(
        "2026-09-25T00:00:00Z", "proj",
        run_id="20260901-e9c0219e (synthetic, backfilled 2026-10-26)",
        factory_version="12.8.0 (synthetic, backfilled 2026-10-26)", marks=True))
    res = t.run("check", "--repo", str(root))
    t.expect(res.returncode == 0,
             f"a synthetic backfilled run_id/factory_version must be valid: {res.stderr!r}")
'''

# NM-2's two halves are the flow hub and the unknown-role run error. A whole-module run of
# `test_provider_stop.py` now aborts on a later, neighbouring row-D assertion, so the vaccine is a
# probe: the hub is read from SKILL.md and the unknown-role half is the self-test's own case 12,
# which is re-executed against the pre-fix `model_attribution.py` as well.
PROBE_PROVIDER_FAILURE_NODE = '''\
import pathlib, re, sys, tempfile
sys.path.insert(0, ".")
root = pathlib.Path(".").resolve().parents[3]
skill = (root / ".agents/skills/code-factory/SKILL.md").read_text(encoding="utf-8")
node = re.search(r"\\bMS\\[[^\\n]*", skill)
feeds = re.findall(r"-->\\|[^|\\n]*provider error at delegation[^|\\n]*\\|\\s*MS\\b", skill)
if node is None or len(feeds) < 10:
    raise AssertionError("no provider-failure node: the flow must carry an `MS[...]` node fed by "
                         "every task-named delegation (found "
                         f"{0 if node is None else len(feeds)} such edge(s), 14 today) — a provider "
                         "refusal of a task-named model would have no branch to classify the error, "
                         "spend the infrastructure budget on the SAME model and stop")
import test_model_attribution as t
with tempfile.TemporaryDirectory() as td:
    t.case_12_unknown_role_is_a_run_error(pathlib.Path(td))
'''

# --------------------------------------------------------------------------------------------
# THIS RUN's (FX) focused probes: one per TESTABLE code fix of run 20261031-dd7ffa0e, replayed
# against FX_BASE_SHA (the v12.19.0 release commit the run started from). Each probe re-executes
# that fix's regression assertion and nothing else, so a fix whose self-test module is shared with
# a later change still proves its own defect on the pre-fix tree.
# --------------------------------------------------------------------------------------------
PROBE_FX_RUST_REGEX = '''\
import pathlib, subprocess, sys, tempfile
log = pathlib.Path(tempfile.mkdtemp()) / "rust.log"
log.write_text("error[E0308]: mismatched types\\n  --> src/main.rs:3:5\\n", encoding="utf-8")
res = subprocess.run([sys.executable, "error_router.py", "classify", "--log", str(log)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
fields = dict(line.split(": ", 1) for line in res.stdout.splitlines() if ": " in line)
if fields.get("route") != "coder" or fields.get("category") != "COMPILE_ERROR":
    raise AssertionError("a Rust compile error `error[E0308]` must route to COMPILE_ERROR/coder "
                         f"(row 8), got route={fields.get('route')!r} "
                         f"category={fields.get('category')!r} "
                         f"pattern_id={fields.get('pattern_id')!r} — a character class instead of a "
                         "bracket-escaped error code matches no real Rust error, so compile "
                         "failures stop reaching the coder")
'''

PROBE_FX_TIMEOUT_SPLIT = '''\
import pathlib, subprocess, sys, tempfile

def classify(text):
    log = pathlib.Path(tempfile.mkdtemp()) / "timeout.log"
    log.write_text(text, encoding="utf-8")
    res = subprocess.run([sys.executable, "error_router.py", "classify", "--log", str(log)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    return dict(line.split(": ", 1) for line in res.stdout.splitlines() if ": " in line)

non_test = classify("the command timed out after 60s\\n")
test = classify("pytest: a test timed out\\n")
if non_test.get("route") != "coder":
    raise AssertionError("a NON-test timeout must reach the coder route (row 17), got "
                         f"{non_test.get('route')!r} via pattern {non_test.get('pattern_id')!r} — a "
                         "row-16 pattern with no test-context predicate shadows every timeout and "
                         "makes the documented coder branch unreachable")
if test.get("route") != "planner":
    raise AssertionError("a TEST timeout must stay with the planner (row 16), got "
                         f"{test.get('route')!r} via pattern {test.get('pattern_id')!r}")
'''

PROBE_FX_PROVIDER_ROUTE = '''\
import json, pathlib, subprocess, sys, tempfile
doc = json.loads(pathlib.Path("..", "references", "error-patterns.default.json")
                 .read_text(encoding="utf-8"))
routes = {row["id"]: row.get("route") for row in doc.get("provider_patterns", [])}
wrong = [ident for ident in ("D", "F") if routes.get(ident) != "infrastructure"]
if wrong:
    raise AssertionError("a PROVIDER_MODEL / PROVIDER_FORMAT failure must route to infrastructure "
                         f"(budget 3), rows {', '.join(wrong)} say otherwise: {routes} — the "
                         "canonical stop rule sends every task-named PROVIDER_* failure to the "
                         "infrastructure path, not to the planner")
log = pathlib.Path(tempfile.mkdtemp()) / "provider.log"
log.write_text("model not found: kimi-code/k9\\n", encoding="utf-8")
res = subprocess.run([sys.executable, "error_router.py", "classify", "--log", str(log)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
fields = dict(line.split(": ", 1) for line in res.stdout.splitlines() if ": " in line)
if fields.get("route") != "infrastructure":
    raise AssertionError("a PROVIDER_MODEL failure must route to infrastructure, got "
                         f"{fields.get('route')!r} via pattern {fields.get('pattern_id')!r}")
'''

PROBE_FX_DETACH_PATHSPEC = '''\
import pathlib, subprocess, sys, tempfile
scope = pathlib.Path(tempfile.mkdtemp()) / "repo"
scope.mkdir()
subprocess.run(["git", "init", "-q", str(scope)], capture_output=True, text=True)
res = subprocess.run([sys.executable, "action_gate.py", "check", "--action",
                      "git checkout --detach HEAD .", "--scope", str(scope), "--mode", "hitl"],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
if "decision: ALLOW" in res.stdout:
    raise AssertionError("`git checkout --detach HEAD .` must never be ALLOW: a ref flag does not "
                         "prove there is no pathspec, and this form restores `.` over the tree — a "
                         f"ref-flag shortcut that returns before examining the pathspec destroys "
                         f"uncommitted work (got {res.stdout.strip()!r})")
'''

PROBE_FX_VENDOR_PIN = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_chrome_devtools_mcp as t
with tempfile.TemporaryDirectory() as td:
    project = pathlib.Path(td) / "unreviewed"
    t.seed_vendored_entry(project, version="0.0.1-unreviewed")
    res = t.run("probe", "--target", str(t.project_assets(project)[0]), "--json")
    payload = json.loads(res.stdout or "{}")
    cap = (payload.get("capabilities") or {}).get("vendor_entry") or {}
    if cap.get("present") or payload.get("mcp_usable") is not False:
        raise AssertionError("an unreviewed vendored version must make the browser path unusable: a "
                             "present entry file is not proof of the reviewed pin — only a version "
                             f"PROVEN equal to PINNED_VERSION may count as installed (got {cap!r}, "
                             f"mcp_usable={payload.get('mcp_usable')!r})")
'''

PROBE_FX_FIX_TASK_REPO_PATH = '''\
import sys
sys.path.insert(0, ".")
import memory_project as mp
required = tuple(getattr(mp, "FIX_TASK_REQUIRED", ()))
if "repo_path" not in required:
    raise AssertionError("FIX_TASK_REQUIRED must carry repo_path: the security-audit and task-format "
                         "contracts require a resolved repo_path, so a fix task without it is "
                         f"unusable for whoever runs it next (got {required!r})")
'''

PROBE_FX_IDENTITY_UNVERIFIED = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import memory_project as mp
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "not-a-repository"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "summary.md").write_text(
        "# Summary\\n\\n<!-- code-factory-memory: summary -->\\n\\nproject: declared\\n"
        "repo_path: .\\nproject_id: deadbeefcafe\\n\\n## Current state\\n", encoding="utf-8")
    try:
        owner, basis, warnings = mp.expected_owner(root)
    except Exception as exc:
        raise AssertionError(f"expected_owner must fall back, not fail: {exc!r}")
    if basis != "identity-unverified":
        raise AssertionError("an unverifiable project_id must fall back to the name basis with the "
                             f"`identity-unverified` basis, got basis={basis!r} owner={owner!r} — "
                             "trusting a declared id exactly when no root commit can be computed "
                             "lets a foreign or arbitrary id pass")
'''

PROBE_FX_V2_KEYS = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_memory_project as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.expect(t.run("init", "--repo", str(root), "--project", "proj").returncode == 0,
             "init must exit 0")
    t.write_journal(root, t.journal_entry("2026-09-28T00:00:00Z", "proj",
                                          run_id="20260928-aaaabbbb", marks=True))
    res = t.run("check", "--repo", str(root), "--no-owner-check")
    said = res.stdout + res.stderr
    if res.returncode != 1 or "factory_version" not in said:
        raise AssertionError("a v2 record missing the mandatory keys must fail, not warn: the "
                             "record proves itself v2 by its run_id, so a missing "
                             f"`unfinished`/`factory_version` is an error (exit {res.returncode}, "
                             f"said {said.strip()[:200]!r})")
'''

PROBE_FX_MIXED_MODEL = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_model_attribution as t
with tempfile.TemporaryDirectory() as td:
    try:
        t.case_13_mixed_model_service_is_a_mismatch(pathlib.Path(td))
    except AssertionError as exc:
        raise AssertionError("a mixed-model service must be a mismatch: a role served by the "
                             "claimed model AND by a substituted fallback model passes a membership "
                             f"test, so the anti-substitution gate stays green ({exc})")
'''

PROBE_FX_MISSING_MARKER = '''\
import pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
import project_fingerprint as pf
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True)
    (root / "a.txt").write_text("hello\\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.email=factory@example.test", "-c", "user.name=factory"]
    subprocess.run([*git, "add", "a.txt"], capture_output=True, text=True)
    subprocess.run([*git, "commit", "-qm", "fixture"], capture_output=True, text=True)
    (root / "a.txt").unlink()
    records = pf._content_records(root) or []
    marker = getattr(pf, "MISSING_CONTENT", "MISSING")
    if not any(f" {marker} " in record for record in records):
        raise AssertionError("a deleted tracked file must be recorded with the MISSING marker: "
                             "falling back to the index record keeps the content fingerprint "
                             "unchanged (the baseline already embeds it), so a deep deletion can "
                             f"take the SKIP path (records {records!r}, marker {marker!r})")
'''

PROBE_FX_GRAPH_SCALAR = '''\
import pathlib, subprocess, sys, tempfile
tasks = pathlib.Path(tempfile.mkdtemp()) / "tasks"
tasks.mkdir()
(tasks / "bad.json").write_text("1\\n", encoding="utf-8")
res = subprocess.run([sys.executable, "task_graph.py", "list", "--dir", str(tasks)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
if res.returncode != 1 or "Traceback" in res.stderr or "bad.json" not in res.stderr:
    raise AssertionError("a scalar JSON task file must be refused, not crash: the decoded state has "
                         "to be validated before any membership test, so a `1` names the file and "
                         f"fails cleanly (exit {res.returncode}, stderr {res.stderr.strip()[:200]!r})")
'''

PROBE_FX_UNTERMINATED_QUOTE = '''\
import pathlib, subprocess, sys, tempfile
task = pathlib.Path(tempfile.mkdtemp()) / "task.yaml"
task.write_text('title: "unterminated\\nrepo_path: .\\ndescription: probe\\ntask_type: implement\\n'
                'mode: hitl\\nacceptance_criteria:\\n  - criterion: probe\\n', encoding="utf-8")
res = subprocess.run([sys.executable, "task_parser.py", "parse", "--task", str(task)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
if res.returncode != 2 or "error:" not in res.stderr:
    raise AssertionError("an unterminated double-quoted scalar must exit 2 with an actionable "
                         "message: `_scalar` treats a quote as a delimiter only when both ends "
                         "exist, so malformed owner input enters every later stage "
                         f"(exit {res.returncode}, stderr {res.stderr.strip()[:200]!r})")
'''

PROBE_FX_DOCSTRING_RESIDUAL = '''\
import sys
sys.path.insert(0, ".")
import validate_documentation as vd
line = '"""doc"""; safe = 1'
mask = vd._doc_mask([line])
if mask != [False]:
    raise AssertionError("code after a docstring must be a code line: a line is documentation only "
                         "when the residual outside its triple-quoted span is blank, so a change "
                         "after the closing delimiter is a code change (got "
                         f"{mask!r} for {line!r})")
'''

PROBE_FX_DERIVE_UNTRACKED = '''\
import pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
import validate_documentation as vd
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True)
    (root / "docs").mkdir()
    (root / "docs" / "d.md").write_text("# doc\\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.email=factory@example.test", "-c", "user.name=factory"]
    subprocess.run([*git, "add", "docs/d.md"], capture_output=True, text=True)
    subprocess.run([*git, "commit", "-qm", "fixture"], capture_output=True, text=True)
    (root / "src").mkdir()
    (root / "src" / "sneaky.py").write_text("dangerous = 1\\n", encoding="utf-8")
    files, _note = vd.derive_changed_files(root)
    if not any("sneaky.py" in str(name) for name in files):
        raise AssertionError("--derive must include an undeclared untracked file: skipping git's "
                             "`??` entries lets a documenter create a new source file with real "
                             "code, leave it out of --files, and never submit it to check() "
                             f"(derived {files!r})")
'''

PROBE_FX_TITLE_ESCAPE = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_version_manager as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "repo"
    t.build_clean_repo(root)
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    if "v12.1.0" not in text:
        raise AssertionError(f"the fixture README must carry the version title, got {text!r}")
    readme.write_text(text.replace("v12.1.0", "v12x1x0"), encoding="utf-8")
    code, out, err = t.run_validate(root)
    said = out + err
    if code == 0 or "title does not match" not in said:
        raise AssertionError("a near-miss README title must be refused: VERSION is interpolated "
                             "into a regular expression, so its dots match any character and "
                             f"`v12x1x0` passes as consistent (exit {code}, said {said.strip()[:200]!r})")
'''

# --------------------------------------------------------------------------------------------
# The 12.19 release's (CC) focused probes: one defect each, replayed against CLEAN_CODE_BASE_SHA.
# They read the tree they are pointed at (cwd = that tree's scripts dir; the root is three levels
# up), so the shipped artifact of the release is what is proven — never a copy of it.
# --------------------------------------------------------------------------------------------
PROBE_CC_SKILLS = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
sections = {"clean-code-discipline": ("Overview", "Key concepts", "How to use", "Constraints"),
            "clean-code-metrics": ("Overview", "Key concepts", "How to use", "Business criteria",
                                   "Constraints")}
for name in sections:
    rel = f"skill-base/skills/{name}/SKILL.md"
    path = root / rel
    if not path.is_file():
        raise AssertionError(f"{rel} must be shipped: the {name} skill of the 12.19 release is "
                             "missing from the skill base")
    text = path.read_text(encoding="utf-8")
    head = text.split("---")[1] if text.startswith("---") else ""
    if f"name: {name}" not in head:
        raise AssertionError(f"{rel}: the frontmatter must name the skill {name!r}")
    for section in sections[name]:
        if f"\\n## {section}\\n" not in text:
            raise AssertionError(f"{rel}: the contract section `## {section}` is missing")
'''

PROBE_CC_METRICS = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
rel = "skill-base/skills/clean-code-metrics/SKILL.md"
path = root / rel
text = path.read_text(encoding="utf-8") if path.is_file() else ""
gates = (("CRAP < 10", r"CRAP\\s*<\\s*10"),
         ("0.8 or above", r"0\\.8\\s+or\\s+above"),
         ("rank >= 0.8", r"rank\\s*>=\\s*0\\.8"),
         ("kill the surviving mutants", r"kill\\w*\\s+(?:the|each)\\s+surviving\\s+mutant"),
         ("delete the dead code", r"(?:delete|remove)s?\\s+(?:the\\s+)?dead\\s+code"))
for label, pattern in gates:
    if not re.search(pattern, text, re.I):
        raise AssertionError(f"{rel}: the gate threshold {label!r} is not stated (an absent file "
                             "states nothing)")
'''

PROBE_CC_SAFETY = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
rel = "skill-base/skills/clean-code-metrics/SKILL.md"
path = root / rel
text = path.read_text(encoding="utf-8") if path.is_file() else ""
if not re.search(r"on their own initiative|without asking", text, re.I):
    raise AssertionError(f"{rel}: no warning that the measuring tools install packages on their own "
                         "initiative (an absent file warns about nothing)")
if not re.search(r"must not happen unattended", text, re.I):
    raise AssertionError(f"{rel}: the install warning does not forbid the unattended form")
if not (re.search(r"shell", text, re.I) and re.search(r"argument\\s+vector", text, re.I)):
    raise AssertionError(f"{rel}: no warning contrasting a shell-string coverage command with the "
                         "argument-vector form")
prohibition = r"(?:installer|viewer|get-uml-viewer)\\b[^.]{0,160}?\\b(?:must\\s+not|must\\s+never|never|do\\s+not)\\s+(?:be\\s+)?(?:executed|run)\\b"
if not re.search(prohibition, text, re.I):
    raise AssertionError(f"{rel}: no prohibition on EXECUTING scripts/get-uml-viewer")
'''

PROBE_CC_MANIFEST = '''\
import json, pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = "skill-base/manifest.json"
path = root / rel
skills = {}
if path.is_file():
    skills = json.loads(path.read_text(encoding="utf-8")).get("skills") or {}
pinned = (("clean-code-discipline", "57a8bdd28e45ed41900ace0bafa2ff76dd9ed70f", 0),
          ("clean-code-metrics", "6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d", 4))
for name, revision, sources in pinned:
    entry = skills.get(name)
    if not isinstance(entry, dict):
        raise AssertionError(f"{rel}: the 12.19 skill {name} is not registered — it has no source, "
                             "no content hash and no pinned revision")
    if entry.get("resolved_revision") != revision:
        raise AssertionError(f"{rel}: {name} is not pinned to {revision} "
                             f"(got {entry.get('resolved_revision')!r})")
    sha = entry.get("sha256")
    digest_ok = isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
    if not digest_ok:
        raise AssertionError(f"{rel}: {name} has no 64-hex content hash (got {sha!r})")
    if sources:
        listed = entry.get("sources") or []
        if len(listed) != sources:
            raise AssertionError(f"{rel}: {name} must carry all {sources} sources in its `sources` "
                                 f"list (got {len(listed)})")
'''

PROBE_CC_WIRING = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/skills/code-factory/references/code-review.md"
path = root / rel
if not path.is_file():
    raise AssertionError(f"{rel} must be shipped")
text = path.read_text(encoding="utf-8")
if not re.search(r"(?m)^##\\s+2\\.2\\s+Metric gates\\s*$", text):
    raise AssertionError(f"{rel}: the standing `## 2.2 Metric gates` section is missing — the "
                         "reviewer is not held to the gates")
gates = (("gate 1", r"(?m)^1\\.\\s+\\*\\*Complexity vs test coverage \\(gate 1\\)\\*\\*"),
         ("gate 2", r"(?m)^2\\.\\s+\\*\\*Duplication \\(gate 2\\)\\*\\*"),
         ("gate 3", r"(?m)^3\\.\\s+\\*\\*Test strength \\(gate 3\\)\\*\\*"))
for label, pattern in gates:
    if not re.search(pattern, text):
        raise AssertionError(f"{rel}: the numbered {label} is missing from `## 2.2 Metric gates`")
reference = "skill-base/skills/clean-code-discipline/SKILL.md"
for role in ("coder.md", "gui-expert.md"):
    body_path = root / ".agents/agents/sub-agents" / role
    if not body_path.is_file():
        raise AssertionError(f".agents/agents/sub-agents/{role} must be shipped")
    if reference not in body_path.read_text(encoding="utf-8"):
        raise AssertionError(f".agents/agents/sub-agents/{role}: does not reference {reference} — the "
                             "role that writes code is not held to the discipline")
reviewer = root / ".agents/agents/sub-agents/code-reviewer.md"
if not reviewer.is_file() or "2.2" not in reviewer.read_text(encoding="utf-8"):
    raise AssertionError(".agents/agents/sub-agents/code-reviewer.md: does not reference the metric "
                         "gates of `references/code-review.md` 2.2")
'''

PROBE_CC_CLI = '''\
import subprocess, sys

def help_of(*args):
    res = subprocess.run([sys.executable, "skill_base.py", *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise AssertionError(f"`skill_base.py {' '.join(args)}` must exit 0, got {res.returncode}: "
                             f"{res.stderr.strip()[:200]}")
    return res.stdout + res.stderr

resolve = help_of("resolve", "--help")
if "--revision" not in resolve:
    raise AssertionError("skill_base.py resolve must advertise --revision: pinning a Git source to "
                         "an exact commit is the provenance feature of the 12.19 release")
record = help_of("record", "--help")
for flag in ("--revision", "--extra-source"):
    if flag not in record:
        raise AssertionError(f"skill_base.py record must advertise {flag}: the multi-source "
                             "registration of the 12.19 release is missing")
'''

# --------------------------------------------------------------------------------------------
# THIS RUN's (DP) focused probes: one defect each, replayed against DP_BASE_SHA. The fixes of the
# review follow-up are spread over four self-test modules that each bundle several of them, so a
# whole-module run would abort at its FIRST failing check and validate its neighbours by accident.
# Every probe re-executes exactly one defect — a carrier's prose, or one published check of the
# module the fix extended — and reads the tree it is pointed at (cwd = that tree's scripts dir).
# --------------------------------------------------------------------------------------------
PROBE_DP_PLAN_AGENT = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/agents/code-factory.md"
text = (root / rel).read_text(encoding="utf-8")
dead = [number for number, line in enumerate(text.splitlines(), 1) if "EnterPlanMode" in line]
if dead:
    raise AssertionError(f"{rel}: Phase 3 must not call EnterPlanMode — Kimi Code 2.4.1 ships no "
                         f"plan-mode entry tool, so an agent following the phase instruction hits a "
                         f"dead call before the approval gate (lines {dead})")
phase = text.split("### Phase 3", 1)[1].split("\\n### ", 1)[0]
for needle in (".code-factory/state/plan.md", "AskUserQuestion", "WAIT for the answer"):
    if needle not in phase:
        raise AssertionError(f"{rel}: Phase 3 must keep the executable approval gate "
                             f"({needle!r} is missing)")
'''

PROBE_DP_PLAN_SKILL = '''\
import pathlib, re
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/skills/code-factory/SKILL.md"
text = (root / rel).read_text(encoding="utf-8")
dead = [number for number, line in enumerate(text.splitlines(), 1) if "EnterPlanMode" in line]
if dead:
    raise AssertionError(f"{rel}: flow node I must not call EnterPlanMode — Kimi Code 2.4.1 has no "
                         f"plan-mode entry tool, so the flowchart an agent follows hits a dead call "
                         f"before the HITL approval gate (lines {dead})")
node = re.search(r"^\\s*H\\s*-->\\s*I\\[(.*)\\]\\s*$", text, re.M)
body = node.group(1) if node else ""
for needle in (".code-factory/state/plan.md", "AskUserQuestion"):
    if needle not in body:
        raise AssertionError(f"{rel}: flow node I must keep the plan in .code-factory/state/plan.md "
                             f"and ask via AskUserQuestion ({needle!r} is missing)")
'''

PROBE_DP_PLAN_GUIDE = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/skills/code-factory/references/planning-guide.md"
text = (root / rel).read_text(encoding="utf-8")
dead = [number for number, line in enumerate(text.splitlines(), 1)
        if "EnterPlanMode" in line or "ExitPlanMode" in line]
if dead:
    raise AssertionError(f"{rel}: section 6 must not call the plan-mode tools — plan mode is "
                         f"USER-only (Shift-Tab or /plan), so the approval step is the plan file "
                         f"plus an explicit question (lines {dead})")
section = text.split("\\n## 6.", 1)[1].split("\\n## ", 1)[0]
for needle in (".code-factory/state/plan.md", "AskUserQuestion"):
    if needle not in section:
        raise AssertionError(f"{rel}: section 6 must present the plan file and ask via "
                             f"AskUserQuestion ({needle!r} is missing)")
'''

PROBE_DP_ADVISOR_AGENT = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/agents/code-factory.md"
text = (root / rel).read_text(encoding="utf-8")
start = text.find("4. **Advisor**")
step = text[start:text.find("\\n5. **Human**", start)] if start >= 0 else ""
if not step:
    raise AssertionError(f"{rel}: the escalation ladder must keep the Advisor step")
for needle in ("on `agreement: agree`", "on `agreement: disagree`, do not retry"):
    if needle not in step:
        raise AssertionError(f"{rel}: the Advisor step must branch on the AGREEMENT before it "
                             f"routes ({needle!r} is missing), otherwise a disagreeing Advisor is "
                             "turned into a blind retry of its recommended role")
if "reroute by `recommended_role`" in step:
    raise AssertionError(f"{rel}: the Advisor step still reroutes solely by `recommended_role` — "
                         "the documented human/auto disagreement path stays unreachable")
'''

PROBE_DP_ADVISOR_FLOW = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = t.check_advisor_agreement(t.ROOT)
if problems:
    raise AssertionError("the flowchart must branch on the Advisor's AGREEMENT before it names a "
                         f"role (ADR -->|agree| ARO, ADR -->|disagree, hitl/auto|): {problems[0]}")
'''

PROBE_DP_ROUTE_WRONG_RESULTS = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = [p for p in t.check_routing_prose(t.ROOT) if p.startswith(t.ERROR_ROUTING)]
if problems:
    raise AssertionError("error-routing §2 must not keep a WRONG_RESULTS -> CODER row the "
                         f"JSON-first router never takes: {problems[0]}")
'''

PROBE_DP_ROUTE_PROVIDER = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = [p for p in t.check_routing_prose(t.ROOT) if p.startswith(t.PROVIDERS)]
if problems:
    raise AssertionError("the provider guide must not send model/format to PLANNER — provider rows "
                         f"D/F route it to INFRASTRUCTURE: {problems[0]}")
'''

PROBE_DP_WORKFLOW_PROSE = '''\
import pathlib, shutil, sys, tempfile
root = pathlib.Path(".").resolve().parents[3]
sys.path.insert(0, ".")
import check_factory_rules as c
gate = getattr(c, "check_workflow_prose", None)
if gate is None:
    raise AssertionError("check_workflow_prose is missing: a marked factory-rule block covers only "
                         "the rule's canonical sentence, so a dead tool name, a stale flowchart node "
                         "or a reordered approval step in the workflow PROSE around it escapes every "
                         "existing check")
clean = gate(root)
if clean:
    raise AssertionError("the shipped approval carriers must pass the workflow-prose pass: "
                         f"{clean[0]}")
found = []
with tempfile.TemporaryDirectory() as td:
    tree = pathlib.Path(td) / "repo"
    for section in c.APPROVAL_SECTIONS:
        target = tree / section.carrier
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / section.carrier, target)
    skill = tree / c.APPROVAL_SECTIONS[0].carrier
    text = skill.read_text(encoding="utf-8")
    skill.write_text(text.replace("Wait for the answer.",
                                  f"Then call {c.FORBIDDEN_TOOL}. Wait for the answer.", 1),
                     encoding="utf-8")
    found = gate(tree)
if not any(c.FORBIDDEN_TOOL in problem for problem in found):
    raise AssertionError("a dead tool injected into flow node I must be reported by the "
                         f"workflow-prose pass, got {found!r} — a pass that cannot fail is no gate")
'''

PROBE_DP_PROMPT_PINS = '''\
import pathlib, sys
root = pathlib.Path(".").resolve().parents[3]
sys.path.insert(0, ".")
import test_prompt_structure as t
tools = set(getattr(t, "KIMI_2_4_1_TOOLS", ()))
problems = []
if "AskUserQuestion" not in tools or "EnterPlanMode" in tools:
    problems.append("the pinned Kimi Code 2.4.1 tool set must carry AskUserQuestion and must not "
                    "carry EnterPlanMode")
problems.extend(t.check_plan_approval(root))
problems.extend(t.check_tool_vocabulary(root))
problems.extend(t.check_cli_vocabulary(root))
if problems:
    raise AssertionError("the tool/CLI/approval pins must hold on the shipped carriers — without "
                         "them a dead tool name, an invented flag or a plan-mode approval step "
                         f"returns unnoticed: {problems[0]}")
'''

PROBE_DP_README_GATE = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = t.check_readme_approval(t.ROOT)
if problems:
    raise AssertionError("the operator manual's hitl bullet must describe the executable gate it "
                         f"documents (plan file + AskUserQuestion): {problems[0]}")
'''

PROBE_DP_PORTABLE_VERIFY = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
template = ".agents/skills/code-factory/assets/task-template.yaml"
guide = ".agents/skills/code-factory/references/planning-guide.md"
required = ((template, "factory_preflight.py"), (template, "preflight.json"),
            (template, "pathspec"), (template, "single quotes"),
            (guide, "### Portable verify commands"), (guide, "preflight.json"),
            (guide, "cmd.exe"), (guide, "single quotes"))
texts = {}
for rel, needle in required:
    if rel not in texts:
        texts[rel] = (root / rel).read_text(encoding="utf-8")
    if needle not in texts[rel]:
        raise AssertionError(f"{rel}: the portable-verify guidance must name {needle!r} — a verify "
                             "command runs through the shell the pre-flight probe found (cmd.exe on "
                             "Windows), so a POSIX single-quoted git pathspec exits 128 although "
                             "the condition holds")
'''

PROBE_DP_BASELINE_FILES = '''\
import subprocess, sys, tempfile, pathlib
sys.path.insert(0, ".")
import validate_documentation as vd
parse = getattr(vd, "parse_baseline_entries", None)
if parse is None:
    raise AssertionError("--baseline-files has no content state: a name-only exemption exempts an "
                         "already-changed file forever, so an undeclared edit to (even a protected) "
                         "baseline file is invisible — the exemption must be by path AND sha256")
digest = "a" * 64
if parse([f"a/b.md={digest}"]) != ({"a/b.md": digest}, []):
    raise AssertionError("a baseline entry must be <path>=<sha256hex>")
backslash = chr(92)
if parse([f"a{backslash}b.md={digest.upper()}"]) != ({"a/b.md": digest}, []):
    raise AssertionError("the baseline must unify separators and lowercase the recorded state")
if parse(["a/b.md"])[1] == []:
    raise AssertionError("a name-only baseline entry must be a usage error — name-only exemption is "
                         "exactly the hole the content state closes")
if parse([]) != ({}, []):
    raise AssertionError("an EMPTY baseline list is legitimate input — it excludes nothing")
escaped = [entry for entry in ("/abs/x.md", "C:/repo/x.md", "../outside.md", "docs/../../x.md", "")
           if not parse([entry + "=" + digest])[1]]
if escaped:
    raise AssertionError(f"a blank, absolute or `..`-escaping baseline entry must be rejected: "
                         f"{escaped!r}")
malformed = [entry for entry in (f"x.md={'a' * 63}", f"x.md={'a' * 65}", "x.md=nothex")
             if not parse([entry])[1]]
if malformed:
    raise AssertionError(f"a malformed state must be rejected: {malformed!r}")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / "kept.md").write_text("old\\n", encoding="utf-8")
    kept = vd.baseline_state(root, "kept.md")
    entries, problems = parse([f"kept.md={kept}"])
    if problems or entries.get("kept.md") != kept:
        raise AssertionError(f"a captured state must round-trip: {entries!r} {problems!r}")
    (root / "kept.md").write_text("new\\n", encoding="utf-8")
    if vd.baseline_state(root, "kept.md") == kept:
        raise AssertionError("a file changed after capture must stop matching its recorded state — "
                             "otherwise an undeclared edit to it hides behind the baseline name")
help_text = subprocess.run([sys.executable, "validate_documentation.py", "check", "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace").stdout
if "--baseline-files" not in help_text:
    raise AssertionError("--baseline-files must be discoverable in `check --help` — an option the "
                         "orchestrator cannot find is one it cannot pass")
'''

PROBE_FK_SKILL = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/skills/code-factory/SKILL.md"
text = (root / rel).read_text(encoding="utf-8")
missing = [needle for needle in ("references/farukon-mcp.md",
                                 ".agents/agents/sub-agents/farukon-expert.md",
                                 "--farukon", "farukon_mcp.py decide",
                                 "models.farukon_expert", "models_used.farukon_expert",
                                 "mcp__farukon__*")
           if needle not in text]
if missing:
    raise AssertionError(f"{rel}: the conditional Farukon path is unwired ({', '.join(missing)} is "
                         "missing) — the specialist, its probe, its model key and the tester-owned "
                         "acceptance must be named where the mechanism lives")
'''

PROBE_FK_AGENT = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/agents/code-factory.md"
text = (root / rel).read_text(encoding="utf-8")
missing = [needle for needle in ("  - factory-farukon-expert", "references/farukon-mcp.md",
                                 "farukon_mcp.py decide", "--farukon", "models.farukon_expert",
                                 "models_used.farukon_expert", "mcp__farukon__*", "F1\\u2013F2")
           if needle not in text]
if missing:
    raise AssertionError(f"{rel}: the Farukon platform path is not orchestrated "
                         f"({', '.join(missing)} is missing) — a conditional specialist nobody "
                         "registers, decides, probes for or routes is a capability no run reaches")
'''

PROBE_FK_TESTER = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/agents/sub-agents/tester.md"
text = (root / rel).read_text(encoding="utf-8")
owned = [block for block in text.split("\\n\\n")
         if "mcp__farukon__*" in block and "ACCEPTANCE" in block]
if "mcp__farukon__*" not in text or not owned:
    raise AssertionError(f"{rel}: the tester-owned replay acceptance is missing — the "
                         "`mcp__farukon__*` tools plus an ACCEPTANCE-labelled artifact set are what "
                         "make the final Farukon scenario independent of the specialist")
'''

PROBE_FK_REFERENCE = '''\
import pathlib
root = pathlib.Path(".").resolve().parents[3]
rel = ".agents/skills/code-factory/references/farukon-mcp.md"
path = root / rel
if not path.is_file():
    raise AssertionError(f"{rel} must be shipped — the conditional Farukon path carries its own "
                         "activation, evidence split, safety defaults and degradation contract")
text = path.read_text(encoding="utf-8")
missing = [needle for needle in ("farukon_mcp.py decide", "merge-config", "validate-config",
                                 "farukon_build", "order_capable", "UNVERIFIED", "F1\\u2013F2")
           if needle not in text]
if missing:
    raise AssertionError(f"{rel}: the platform contract is incomplete ({', '.join(missing)} is "
                         "missing) — a reference that omits the safety default or the degradation "
                         "rule cannot govern a platform session")
'''

PROBE_FK_CONTRACTS = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = t.check_farukon_wiring(t.ROOT)
if problems:
    raise AssertionError("the Farukon wiring contracts must hold on this tree: " + problems[0])
'''

# The generator side the Farukon role belongs to. It is pinned HERE and not in
# `test_model_precedence.py`, because that module is also replayed against older bases (V-rf-b3):
# an exact role tuple asserted there would fail on a pre-Farukon tree for a reason unrelated to the
# regression being proven, which is what made that vaccine a false positive.
PROBE_FK_GENERATOR_SIDE = '''\
import sys
sys.path.insert(0, ".")
import model_matrix as mm
expected = ("coder", "tester", "gui_expert", "farukon_expert", "business_tester")
if mm.GENERATOR_SIDE != expected:
    raise AssertionError("the farukon_expert generator side must be pinned in GENERATOR_SIDE: "
                         + repr(mm.GENERATOR_SIDE))
if "farukon_expert" not in mm.ROLES:
    raise AssertionError("farukon_expert must be a known role of the factory: " + repr(mm.ROLES))
'''

# THIS run's (FB) Farukon/vaccination-debt probes: one defect each, replayed against FB_BASE_SHA.
# They reuse `test_farukon_mcp.py`'s own fixtures (that module is copied into the pre-fix tree), so a
# fixture change is picked up here instead of being duplicated.
PROBE_FB_SUBJECT = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import farukon_mcp as fm
import test_farukon_mcp as t
with tempfile.TemporaryDirectory() as td:
    repo = t.platform_repo(pathlib.Path(td) / "platform-crate")
    for text in t.GENERIC_IDENTITY_TEXTS:
        decision = fm.decide_applicability(text, repo=repo)
        t.check(decision["decision"] == fm.NOT_APPLICABLE,
                f"a generic identity word is no platform subject: {text!r}")
'''

PROBE_FB_TIMEOUTS = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import farukon_mcp as fm
import test_farukon_mcp as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    workdir = root / "handshake"
    workdir.mkdir()
    marker = root / "spawned.txt"
    argv = t.fake_server(root, "fb-timeout",
                         f"import pathlib\\n"
                         f"pathlib.Path({str(marker)!r}).write_text('x', encoding='utf-8')\\n"
                         + t.GOOD_SERVER)
    for bad in (float("inf"), float("nan"), -1, True, "30"):
        result = fm.mcp_start_handshake(workdir, argv=argv, first_response_timeout=bad,
                                        response_timeout=1)
        t.check(result["ok"] is False and fm.TIMEOUT_REFUSAL in result["message"],
                f"an unusable timeout ({bad!r}) must be refused, not launched")
    t.check(not marker.exists(), "a refused timeout must never start a child process")
'''

PROBE_FB_COMPLEXITY = '''\
import ast, pathlib
BRANCHES = (ast.If, ast.For, ast.While, ast.AsyncFor, ast.And, ast.Or, ast.IfExp, ast.comprehension,
            ast.ExceptHandler)
tree = ast.parse(pathlib.Path("farukon_mcp.py").read_text(encoding="utf-8"))


def complexity(name):
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return 1 + sum(1 for child in ast.walk(node) if isinstance(child, BRANCHES))


for function in ("decide_applicability", "validate_config"):
    measured = complexity(function)
    if measured > 10:
        raise AssertionError(f"{function} must stay small (cyclomatic complexity {measured} > 10)")
'''

PROBE_FB_JSON_MERGE = '''\
import importlib.util, json, sys
sys.path.insert(0, ".")
if importlib.util.find_spec("mcp_json_merge") is None:
    raise AssertionError("the shared module mcp_json_merge must exist")
import chrome_devtools_mcp
import farukon_mcp
import mcp_json_merge
for module in (farukon_mcp, chrome_devtools_mcp):
    if module.mcp_json_merge is not mcp_json_merge:
        raise AssertionError(f"{module.__name__} must import the shared mcp_json_merge module")
text = '{\\n  "mcpServers": {},\\n  "userSetting": {\\n    "keep": true\\n  }\\n}\\n'
merged = mcp_json_merge.insert_managed_server(text, "farukon", {"command": "cargo"})
if json.loads(merged) != {"mcpServers": {"farukon": {"command": "cargo"}},
                          "userSetting": {"keep": True}}:
    raise AssertionError("the shared merge module must insert only the managed server")
if '"keep": true' not in merged:
    raise AssertionError("the shared merge must preserve every unrelated byte")
if mcp_json_merge.insert_managed_server(text, "farukon", {"command": "cargo"}) != merged:
    raise AssertionError("the shared merge must be deterministic")
'''

# W2 (violations N-1/N-2, proposal P-2): the retry budget must be counted by a PRE-DELEGATION gate
# that increments the counter itself and refuses when it is exhausted. On the pre-fix tree no such
# script exists, so the budget is counted by whoever reports it.
PROBE_FB_BUDGET = '''\
import importlib.util, json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if importlib.util.find_spec("delegation_gate") is None:
    raise AssertionError("delegation_gate.py must exist: a budget counted by the reporter is not "
                         "enforced")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text(
        chr(10).join(["run_id: 20261103-8e939171", "retry_counters:", "  reviewer: 0", ""]),
        encoding="utf-8")
    verdicts = []
    for _ in range(3):
        run = subprocess.run([sys.executable, "delegation_gate.py", "check", "--repo", str(root),
                              "--role", "reviewer", "--mode", "hitl"],
                             capture_output=True, text=True, errors="replace")
        try:
            verdict = json.loads(run.stdout)
        except ValueError:
            verdict = {}
        verdicts.append((run.returncode, verdict))
    if [code for code, _verdict in verdicts] != [0, 0, 1]:
        raise AssertionError(f"the third reviewer delegation must be refused: {verdicts}")
    refused = verdicts[2][1]
    if refused.get("allow") is not False or refused.get("counter") != 2:
        raise AssertionError(f"a refused delegation must not increment the counter: {refused}")
'''

# W2 (violation N-3, proposals P-1+P-3): strict attribution. On the pre-fix tree a REQUIRED role
# with a claim and no session-wire trace exits 3 (DEGRADED) instead of failing the run.
PROBE_FB_ATTRIBUTION = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    repo = root / "repo"
    repo.mkdir()
    session = root / "home" / "sessions" / "wd_x" / "session_11111111-1111-4111-8111-111111111111"
    (session / "agents" / "main").mkdir(parents=True)
    (session / "state.json").write_text(json.dumps({
        "id": "session_11111111-1111-4111-8111-111111111111",
        "cwd": str(repo).replace("\\\\", "/"), "archived": False,
        "agents": {"main": {"type": "main"}}}), encoding="utf-8")
    (session / "agents" / "main" / "wire.jsonl").write_text(json.dumps({
        "type": "llm.request", "agentId": "main", "model": "k3", "modelAlias": "kimi-k3"})
        + chr(10), encoding="utf-8")
    pipeline = root / "pipeline.yaml"
    pipeline.write_text(chr(10).join([
        "task_type: implement", "required_roles:", "  - reviewer", "run_id: 20261103-8e939171",
        "models_used:", "  reviewer: kimi-k3", ""]), encoding="utf-8")
    out = root / "attribution.json"
    run = subprocess.run([sys.executable, "model_attribution.py", "--session", str(session),
                          "--repo", str(repo), "--out", str(out), "--pipeline", str(pipeline)],
                         capture_output=True, text=True, errors="replace")
    artifact = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    if run.returncode != 1:
        raise AssertionError(f"a required role with no wire trace must FAIL under strict "
                             f"attribution, not degrade (exit {run.returncode}): {run.stdout!r}")
    if artifact.get("comparison", {}).get("reviewer") != "unbacked":
        raise AssertionError(f"the required role must be reported as unbacked: "
                             f"{artifact.get('comparison')!r}")
    if "reviewer" not in run.stdout:
        raise AssertionError("the failure must name the unbacked required role")
'''

# W2 (violation N-4, proposal P-4): the run's change set must be COMPUTED, not claimed — a manifest
# that refuses an edit without a backup and audits its own hashes. On the pre-fix tree no such script
# exists, so the manifest is written by hand and nothing proves the change set.
PROBE_FB_MANIFEST = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
tool = pathlib.Path("manifest.py")
if not tool.is_file():
    raise AssertionError("manifest.py must exist: a manifest written by hand proves nothing")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / ".code-factory" / "state").mkdir(parents=True)
    (root / ".code-factory" / "state" / "pipeline.yaml").write_text(
        "run_id: 20261103-8e939171" + chr(10), encoding="utf-8")
    (root / "src").mkdir()
    target = root / "src" / "a.py"
    target.write_text("a = 1" + chr(10), encoding="utf-8")

    def manifest(*args):
        return subprocess.run([sys.executable, "manifest.py", *args, "--repo", str(root)],
                              capture_output=True, text=True, errors="replace")

    if manifest("require").returncode != 1:
        raise AssertionError("a run without a manifest must be blocked before the first edit")
    if manifest("init").returncode != 0:
        raise AssertionError("manifest.py init must create the manifest")
    if manifest("add", "--changed", "src/a.py").returncode != 1:
        raise AssertionError("editing a file without a backup must be a BLOCKING error")
    backup = root / ".code-factory" / "backups" / "src" / "a.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("a = 0" + chr(10), encoding="utf-8")
    added = manifest("add", "--changed", "src/a.py")
    if added.returncode != 0:
        raise AssertionError(f"a backed-up change must register: {added.stderr!r}")
    entry = json.loads((root / ".code-factory" / "manifest.json").read_text(encoding="utf-8"))
    if len(entry["changed_files"][0]["sha256"]) != 64:
        raise AssertionError("the manifest must carry the sha256 the script computed")
    target.write_text("a = 2" + chr(10), encoding="utf-8")
    if manifest("audit").returncode != 1:
        raise AssertionError("the finish audit must report drift against the registered hash")
'''

# W2 (violation N-6, proposal P-6): `pkill`/`kill` fell through ALLOW, and nothing audited the shell
# commands the run really executed against the journal.
PROBE_FB_ACTIONGATE = '''\
import pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("action_gate.py").is_file():
    raise AssertionError("action_gate.py must be shipped")
with tempfile.TemporaryDirectory() as td:
    journal = pathlib.Path(td) / "action-gate.md"
    run = subprocess.run([sys.executable, "action_gate.py", "check", "--action", "pkill -f pytest",
                          "--mode", "hitl", "--journal", str(journal)],
                         capture_output=True, text=True, errors="replace")
    if "class: CONFIRM" not in run.stdout:
        raise AssertionError("pkill must be classified, not waved through as ALLOW: "
                             + run.stdout.replace(chr(10), " ")[:160])
    audit = subprocess.run([sys.executable, "action_gate.py", "audit", "--help"],
                           capture_output=True, text=True, errors="replace")
    if audit.returncode != 0:
        raise AssertionError("action_gate.py must offer the session-wire audit subcommand")
'''

# W2 (violation N-5, proposal P-5): one aggregator must run every deterministic gate of a phase and
# record it; a skipped gate without a record is a failure. On the pre-fix tree no aggregator exists.
PROBE_FB_GATEALL = '''\
import pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")

if not pathlib.Path("gate_all.py").is_file():
    raise AssertionError("gate_all.py must exist: without one aggregator a skipped gate is invisible")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    run = subprocess.run([sys.executable, "gate_all.py", "--repo", str(root), "--phase", "K",
                          "--verify-only", str(root / "gate-K.md")],
                         capture_output=True, text=True, errors="replace")
    if run.returncode != 1:
        raise AssertionError(f"a missing gate record must FAIL the phase (exit 1), got "
                             f"{run.returncode}: {run.stdout!r}")
    unknown = subprocess.run([sys.executable, "gate_all.py", "--repo", str(root), "--phase", "Z"],
                             capture_output=True, text=True, errors="replace")
    if unknown.returncode != 2:
        raise AssertionError("an unknown phase must be a usage error (exit 2)")
'''

# W2 (violation N-7, proposal P-7): the two-level fingerprint moved OUT of AGENTS.md into derived
# state, so AGENTS.md's content no longer depends on its own commit. On the pre-fix tree the marker
# is embedded in line 1 and there is no state file at all.
PROBE_FB_FINGERPRINT = '''import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text("[project]" + chr(10), encoding="utf-8")
    (root / "README.md").write_text("# demo" + chr(10), encoding="utf-8")
    (root / "src" / "a.py").write_text("x = 1" + chr(10), encoding="utf-8")
    run = subprocess.run([sys.executable, "project_fingerprint.py", "--repo", str(root),
                          "--write-state"], capture_output=True, text=True, errors="replace")
    if run.returncode != 0:
        raise AssertionError("--write-state must exist: the fingerprint must live in derived state, "
                             "not in the AGENTS.md whose commit it describes")
    state = json.loads((root / ".code-factory" / "state" / "fingerprint.json").read_text(encoding="utf-8"))
    if set(state) != {"structural", "content"} or len(state["structural"]) != 64:
        raise AssertionError(f"the state must carry exactly the two 64-hex hashes: {state!r}")
    check = subprocess.run([sys.executable, "project_fingerprint.py", "--repo", str(root),
                            "--check-state"], capture_output=True, text=True, errors="replace")
    if check.returncode != 0:
        raise AssertionError(f"--check-state must report a match: {check.stdout!r}")
    (root / "src" / "a.py").write_text("x = 2" + chr(10), encoding="utf-8")
    drifted = subprocess.run([sys.executable, "project_fingerprint.py", "--repo", str(root),
                              "--check-state"], capture_output=True, text=True, errors="replace")
    if drifted.returncode != 1:
        raise AssertionError("--check-state must report the divergence (exit 1)")
'''

# W2 (proposal P-8): a finding may be REFUTED with evidence, and a refutation must stop counting
# toward the critical rule without disappearing. On the pre-fix tree the field is discarded.
PROBE_FB_DISPOSITION = '''import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
import merge_findings as mf
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / ".code-factory" / "logs").mkdir(parents=True)
    (root / ".code-factory" / "logs" / "review.md").write_text("# review" + chr(10), encoding="utf-8")
    payload = {"shard": "shard-1", "verdict": "request_changes", "findings": [
        {"severity": "critical", "file": "a.py", "line": 1, "title": "refuted one",
         "finding_disposition": "refuted", "finding_evidence": ".code-factory/logs/review.md"}]}
    path = root / "shard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        loaded = mf.load_shard_file(path, root)      # the repo-aware (evidence-checking) reader
    except TypeError:                                 # the pre-fix reader takes the path only
        loaded = mf.load_shard_file(path)
    finding = loaded["findings"][0]
    if finding.get("finding_disposition") != "refuted":
        raise AssertionError("a finding_disposition must be accepted and kept, not discarded")
    report = mf.merge([loaded])
    if report["counts"]["critical"] != 0 or report.get("refuted") != 1:
        raise AssertionError(f"a refuted finding must not count as critical and must be counted as "
                             f"refuted: {report['counts']} / {report.get('refuted')!r}")
'''

# W2 (proposal P-8): a WHOLLY REFUTED review round refunds the one reviewer iteration it consumed.
# On the pre-fix tree delegation_gate.py has no settlement at all.
PROBE_FB_SETTLE = '''import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (root / ".code-factory" / "logs").mkdir(parents=True)
    evidence = root / ".code-factory" / "logs" / "review.md"
    evidence.write_text("# review" + chr(10), encoding="utf-8")
    (root / ".code-factory" / "logs" / "merged.json").write_text(json.dumps(
        {"round": "iter-1", "findings": [
            {"severity": "major", "file": "a.py", "line": 1, "title": "t", "detail": "d",
             "finding_disposition": "refuted",
             "finding_evidence": ".code-factory/logs/review.md"}]}), encoding="utf-8")
    (state / "pipeline.yaml").write_text(
        chr(10).join(["run_id: 20261103-8e939171", "retry_counters:", "  reviewer: 1", ""]),
        encoding="utf-8")

    def settle(*extra):
        return subprocess.run([sys.executable, "delegation_gate.py", "settle", "--repo", str(root),
                               "--role", "reviewer", "--round", "iter-1",
                               "--evidence", ".code-factory/logs/merged.json", *extra],
                              capture_output=True, text=True, errors="replace")

    run = settle("--refuted-all")
    if run.returncode != 0:
        raise AssertionError(f"a wholly refuted round must be settleable: {run.returncode} "
                             f"{run.stderr.strip()[:140]}")
    text = (state / "pipeline.yaml").read_text(encoding="utf-8")
    if "reviewer: 0" not in text or "settled_rounds:" not in text:
        raise AssertionError(f"the settlement must refund one iteration and record the round: {text!r}")
    again = settle("--refuted-all")
    if again.returncode != 0 or json.loads(again.stdout)["refunded"] != 0:
        raise AssertionError("a repeated settlement must be idempotent, never a second refund")
    mixed = settle()
    if mixed.returncode == 0:
        raise AssertionError("a MIXED round must never refund")
'''

# W3 (task_14): the ADVERSARIAL BUSINESS TESTER role — a generator-side, user-level role with its
# own card. On the pre-fix tree the role is not in the registry and the card does not exist.
PROBE_FB_BIZTESTER = '''import pathlib, sys
sys.path.insert(0, ".")
import model_matrix as mm
if "business_tester" not in mm.ROLES:
    raise AssertionError("business_tester must be a registered role of the factory: "
                         + repr(mm.ROLES))
if "business_tester" not in mm.GENERATOR_SIDE:
    raise AssertionError("business_tester produces the product's evidence and must be "
                         "generator-side: " + repr(mm.GENERATOR_SIDE))
if mm.ROLE_FILES.get("business_tester") != "business-tester.md":
    raise AssertionError("business_tester must map to its own card business-tester.md")
cards = pathlib.Path(".").resolve().parents[2] / "agents" / "sub-agents"
card = cards / "business-tester.md"
if not card.is_file():
    raise AssertionError("the adversarial business tester card must be shipped")
body = " ".join(card.read_text(encoding="utf-8").split())
if "model_preference: secondary" not in body:
    raise AssertionError("business_tester runs on the secondary model slot")
for needle in ("NEVER edit", "product_files_edited: 0", "security_audit",
               "factory-tester", "business-adversarial"):
    if needle not in body:
        raise AssertionError(f"the card must state {needle!r}: a user-level, no-edit, "
                             f"non-acceptance role is what the pin is about")
'''

# W3 (task_15): the read-only SUPERVISOR — a judge-side gatekeeper with its own card. On the pre-fix
# tree the role is not in the registry and the card does not exist.
PROBE_FB_SUPERVISOR = '''import pathlib, sys
sys.path.insert(0, ".")
import model_matrix as mm
if "supervisor" not in mm.ROLES:
    raise AssertionError("supervisor must be a registered role of the factory: " + repr(mm.ROLES))
if "supervisor" not in mm.JUDGE_SIDE:
    raise AssertionError("the supervisor only judges a permit and must be judge-side: "
                         + repr(mm.JUDGE_SIDE))
if "business_tester" in mm.JUDGE_SIDE:
    raise AssertionError("a generator role cannot sit on the judge side")
cards = pathlib.Path(".").resolve().parents[2] / "agents" / "sub-agents"
card = cards / "supervisor.md"
if not card.is_file():
    raise AssertionError("the supervisor card must be shipped")
body = " ".join(card.read_text(encoding="utf-8").split())
if "model_preference: primary" not in body:
    raise AssertionError("the supervisor runs on the primary (judge) model slot")
for needle in ("READ-ONLY", "permit_gate.py", "never write", "AskUserQuestion",
               "MODEL-ENFORCED", "denied_because"):
    if needle not in body:
        raise AssertionError(f"the card must state {needle!r}: the honest, read-only, machine-"
                             f"backstopped verdict contract is what the pin is about")
'''


# W3 (task_16): the deterministic permit gate behind the supervisor's MODEL-ENFORCED verdict. On the
# pre-fix tree no such gate exists, so a delegation nobody permitted cannot be detected at all.
PROBE_FB_PERMIT = '''\
import json, pathlib, subprocess, sys, tempfile, time
sys.path.insert(0, ".")
tool = pathlib.Path("permit_gate.py")
if not tool.is_file():
    raise AssertionError("permit_gate.py must exist: a model verdict with no deterministic gate "
                         "stops nothing")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10), encoding="utf-8")
    (state / "plan.md").write_text(chr(10).join([
        "## Tasks (DAG)", "",
        "- task_01: a fixture. files: a.py; deps: []; verify: true", ""]), encoding="utf-8")

    def gate(*args):
        return subprocess.run([sys.executable, "permit_gate.py", *args], capture_output=True,
                              text=True, errors="replace")

    if gate("init", "--repo", str(root)).returncode != 0:
        raise AssertionError("permit_gate init must write the run's permits skeleton")
    added = gate("add", "--repo", str(root), "--permit-id", "P1", "--task-id", "task_01",
                 "--role", "coder", "--phase", "implement", "--scope", "a.py")
    if added.returncode != 0:
        raise AssertionError(f"a planned, registered, in-scope permit must be accepted: "
                             f"{added.stderr.strip()[:140]}")
    if gate("verdict", "--repo", str(root), "--permit-id", "P1", "--verdict", "allow",
            "--evidence", "task_01 is in the approved plan").returncode != 0:
        raise AssertionError("an evidenced allow verdict must be recordable")
    session = root / "session"
    (session / "agents" / "main").mkdir(parents=True)
    (session / "state.json").write_text("{}", encoding="utf-8")
    spawn = {"type": "subagent.spawned", "subagentId": "agent-1",
             "subagentName": "factory-coder", "time": int(time.time() * 1000) + 60000}
    (session / "agents" / "main" / "wire.jsonl").write_text(json.dumps(spawn) + chr(10),
                                                           encoding="utf-8")
    audit = gate("audit", "--repo", str(root), "--session", str(session))
    if audit.returncode != 1 or "permit-less delegation" not in audit.stdout:
        raise AssertionError(f"a spawn nobody permitted must FAIL the audit: {audit.returncode} "
                             f"{audit.stdout.strip()[:140]}")
'''

# W3 (task_16): the same wire evidence, seen from the retry-budget side — the delegation audit that
# gate_all's phase-Y hook calls. On the pre-fix tree delegation_gate.py does not exist at all.
PROBE_FB_DELEGATION_AUDIT = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("delegation_gate.py").is_file():
    raise AssertionError("delegation_gate.py must exist: the retry budget is counted by the reporter")
helped = subprocess.run([sys.executable, "delegation_gate.py", "--help"], capture_output=True,
                        text=True, errors="replace")
usage = (helped.stdout + helped.stderr).splitlines()
first = usage[0] if usage else ""
if "audit" not in first:
    raise AssertionError("delegation_gate.py must offer the finish audit over the session wire: "
                         + first[:120])
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text(
        chr(10).join(["run_id: 20261103-8e939171", "retry_counters:", "  reviewer: 0", ""]),
        encoding="utf-8")
    session = root / "session"
    (session / "agents" / "main").mkdir(parents=True)
    (session / "state.json").write_text("{}", encoding="utf-8")
    spawn = {"type": "subagent.spawned", "subagentId": "agent-1",
             "subagentName": "factory-code-reviewer", "time": 1}
    (session / "agents" / "main" / "wire.jsonl").write_text(json.dumps(spawn) + chr(10),
                                                           encoding="utf-8")
    audit = subprocess.run([sys.executable, "delegation_gate.py", "audit", "--repo", str(root),
                            "--session", str(session)], capture_output=True, text=True,
                           errors="replace")
    if audit.returncode != 1 or "uncounted delegation" not in audit.stdout:
        raise AssertionError("a budgeted-role spawn with no counted delegation must FAIL the "
                             "delegation audit: " + str(audit.returncode))
'''

# --------------------------------------------------------------------------------------------
# The FB (task_17) FLOW probes: the W2/W3 mechanisms exist, but a gate nobody reaches protects
# nothing — each probe pins ONE wiring contract of the shipped flow and fails on the base tree,
# where the flow names none of them.
# --------------------------------------------------------------------------------------------
PROBE_FB_FLOW_GATE = '''\
import pathlib, sys
sys.path.insert(0, ".")
import test_flow_contracts as flow
root = pathlib.Path(".").resolve().parents[3]
doc = flow.Doc.load(root, flow.SKILL, [])
_first, nodes = flow.flow_nodes(doc)
by_id = {ident: body for _line, ident, body in nodes}
node = by_id.get("DG1", "")
for needle in ("delegation_gate.py check", "permit_gate.py add", "permit_gate.py verdict",
               "permit_gate.py bind", "permit_gate.py audit", "MODEL-ENFORCED"):
    if needle not in node:
        raise AssertionError("the pre-delegation node must reach " + needle
                             + ": a budget gate the flow never runs counts nothing")
'''

PROBE_FB_FLOW_PARALLEL = '''\
import pathlib, re, sys
sys.path.insert(0, ".")
import test_flow_contracts as flow
root = pathlib.Path(".").resolve().parents[3]
doc = flow.Doc.load(root, flow.SKILL, [])
_first, nodes = flow.flow_nodes(doc)
by_id = {ident: body for _line, ident, body in nodes}
node = by_id.get("BT", "")
for needle in ("factory-business-tester", "IN PARALLEL", "business-adversarial"):
    if needle not in node:
        raise AssertionError("node S must run the adversarial business tester IN PARALLEL with "
                             "the tester's business tests (" + needle + " is missing)")
if not re.search(r"\\bS\\s*-->\\s*BT\\b", doc.text):
    raise AssertionError("node S must OPEN the parallel branch: the `S --> BT` edge is missing")
'''

PROBE_FB_FLOW_CHECKPOINTS = '''\
import pathlib, sys
sys.path.insert(0, ".")
import test_flow_contracts as flow
root = pathlib.Path(".").resolve().parents[3]
order = (root / flow.CODE_FACTORY).read_text(encoding="utf-8")
body = " ".join(order.split())
for needle in ("gate_all.py --repo", "--phase K", "--phase Y", "manifest.py require",
               "manifest.py audit", "delegation_gate.py check"):
    if needle not in body:
        raise AssertionError("the executable order must reach " + needle
                             + ": a checkpoint nobody executes is prose, not a control")
'''

PROBE_FB_EVIDENCE = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
tool = pathlib.Path("test_business_tester_flow.py")
if not tool.is_file():
    raise AssertionError("test_business_tester_flow.py must exist: the evidence contract (a real "
                         "run's report judged on SHAPE, the matrix only for the self-check, and a "
                         "--write that never clobbers) is not shipped")
real = {"run_id": "20261103-1f4e9a2b", "role": "factory-business-tester",
        "task_type": "implement",
        "scenarios": [
            {"id": "cli-surface-help", "goal": "the --help of every delivered tool",
             "interface": "cli",
             "actions": [{"action": "user_action", "command": "python agent_cli.py --help"}],
             "expected": "exit 0 and a readable synopsis", "observed": "exit 0, synopsis printed",
             "outcome": "held", "classification": "no_defect"},
            {"id": "gate-order", "goal": "a gate call repeated out of order", "interface": "cli",
             "actions": [], "expected": "the repeat is refused",
             "observed": "not executed: the owner stopped the run", "outcome": "unverified",
             "classification": "environment"}],
        "breakages": [], "actions_were_user_level": True, "product_files_edited": 0,
        "debugger_used": False}
with tempfile.TemporaryDirectory() as td:
    path = pathlib.Path(td) / "real-run.json"
    path.write_text(json.dumps(real), encoding="utf-8")
    ok = subprocess.run([sys.executable, str(tool), "--evidence", str(path), "--no-drive"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ok.returncode != 0:
        raise AssertionError("a real run's shape-valid report must validate: the fixture matrix "
                             "belongs to the self-check, never to a run's report ("
                             + (ok.stdout + ok.stderr).strip()[-200:] + ")")
    before = path.read_bytes()
    clobber = subprocess.run([sys.executable, str(tool), "--write", "--evidence", str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
    if clobber.returncode != 1:
        raise AssertionError("--write must REFUSE to overwrite an existing report without "
                             "--force: " + (clobber.stdout + clobber.stderr).strip()[-200:])
    if path.read_bytes() != before:
        raise AssertionError("a refused --write must leave the run's evidence byte-identical, not "
                             "replace it with the built-in fixture")
'''


# --------------------------------------------------------------------------------------------
# The FB (review rework round 1) probes: one per REVIEWED defect of this run's change set. Each one
# exercises the shipped behaviour, so it fails on the base tree (where the behaviour is absent) and
# passes here.
# --------------------------------------------------------------------------------------------
PROBE_FB_TIMEOUTS_HUGE = '''\
import pathlib, sys
sys.path.insert(0, ".")
if not pathlib.Path("farukon_mcp.py").is_file():
    raise AssertionError("a timeout must be refused BEFORE the process starts")
import farukon_mcp as fm
check = getattr(fm, "_timeout_problem", None)
if check is None:
    raise AssertionError("a timeout must be refused BEFORE the process starts")
for field in ("first_response_timeout", "response_timeout"):
    problem = check(field, 10 ** 400)
    if not problem:
        raise AssertionError(f"a {field} must be refused BEFORE the process starts: an integer "
                             f"larger than the float range overflows the deadline")
    try:
        float(10 ** 400)
    except OverflowError:
        pass
    else:
        raise AssertionError("the fixture is wrong: 10 ** 400 must overflow float()")
'''

PROBE_FB_SETTLE_ARTIFACT = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("delegation_gate.py").is_file():
    raise AssertionError("a mixed round must be refused for being mixed")
import delegation_gate as dg
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10)
                                         + "retry_counters:" + chr(10) + "  reviewer: 2"
                                         + chr(10), encoding="utf-8")
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True)
    (logs / "review.md").write_text("# r" + chr(10), encoding="utf-8")
    path = logs / "merged.json"
    path.write_text(json.dumps({"round": "iter-1", "findings": [
        {"severity": "major", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/review.md"},
        {"severity": "major", "finding_disposition": "accepted", "finding_evidence": ""}]}),
        encoding="utf-8")
    try:
        dg.settle(root, "reviewer", "iter-1", ".code-factory/logs/merged.json", refuted_all=True)
    except dg.GateError as exc:
        if "MIXED" not in str(exc).upper():
            raise AssertionError("a mixed round must be refused for being mixed: " + str(exc))
    else:
        raise AssertionError("--refuted-all must be CHECKED against the round artifact: a mixed "
                             "round must never refund")
'''

PROBE_FB_REQUIRED_ROLES = '''\
import sys
sys.path.insert(0, ".")
import check_factory_model as cfm
check = getattr(cfm, "required_roles_errors", None)
if check is None:
    raise AssertionError("an implement/refactor checkpoint without the mandatory roles must fail")
for data in ({"task_type": "implement"}, {"task_type": "refactor", "required_roles": []},
             {"task_type": "implement", "required_roles": ["analyzer", "planner"]}):
    errors = check(data)
    if not errors:
        raise AssertionError(f"an implement/refactor checkpoint without the mandatory roles must "
                             f"fail: {data!r}")
'''

PROBE_FB_AUDIT_PATHS = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("manifest.py").is_file():
    raise AssertionError("a manifest entry outside the repository "
                         "must be an audit violation")
import manifest as mf
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / ".code-factory").mkdir(parents=True)
    (root / "a.py").write_text("a = 1" + chr(10), encoding="utf-8")
    (root / ".code-factory" / "manifest.json").write_text(json.dumps({
        "run_id": "20261103-8e939171",
        "changed_files": [{"path": "../../etc/passwd", "sha256": "0" * 64}],
        "created_files": []}), encoding="utf-8")
    result = mf.audit(root)
    if result["status"] != "failed" or not any("unconfined" in p for p in result["problems"]):
        raise AssertionError("a manifest entry outside the repository must be an audit violation: "
                             + repr(result["problems"]))
'''

PROBE_FB_WRITE_ERRORS = '''\
import os, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    path = state / "pipeline.yaml"
    path.write_text("run_id: 20261103-8e939171" + chr(10) + "status: in_progress" + chr(10)
                    + "retry_counters:" + chr(10) + "  coder: 0" + chr(10), encoding="utf-8")
    os.chmod(path, 0o444)
    try:
        res = subprocess.run([sys.executable, "delegation_gate.py", "check", "--repo", str(root),
                              "--role", "coder", "--mode", "hitl"], capture_output=True, text=True,
                             errors="replace")
    finally:
        os.chmod(path, 0o644)
    if res.returncode != 2 or "Traceback" in res.stderr or "cannot write" not in res.stderr:
        raise AssertionError("an unwritable checkpoint must be an actionable exit 2, never a "
                             "traceback: " + repr((res.returncode, res.stderr[-200:])))
'''

PROBE_FB_SCOPE_DIRECTION = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("permit_gate.py").is_file():
    raise AssertionError("the containment has one direction")
import permit_gate as pg
if not pg._within_plan("scripts/a.py", ["scripts/"]):
    raise AssertionError("a permit BELOW a declared directory must be inside the plan task")
if pg._within_plan("scripts", ["scripts/a.py"]):
    raise AssertionError("a permit ABOVE a declared file must be refused: the containment has one "
                         "direction")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10), encoding="utf-8")
    (state / "plan.md").write_text("- task_09: x. files: scripts/a.py; deps: []; verify: v"
                                   + chr(10), encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "a.py").write_text("a = 1" + chr(10), encoding="utf-8")
    pg.init(root)
    try:
        pg.add(root, "P1", "task_09", "coder", "implement", ["scripts"])
    except pg.PermitError:
        pass
    else:
        raise AssertionError("add must refuse a scope WIDER than the plan task's file")
'''

PROBE_FB_WIRE_TIMES = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("permit_gate.py").is_file():
    raise AssertionError("a spawn time must be malformed evidence, never a usable stamp")
import permit_gate as pg
with tempfile.TemporaryDirectory() as td:
    session = pathlib.Path(td)
    (session / "agents" / "main").mkdir(parents=True)
    (session / "state.json").write_text("{}", encoding="utf-8")
    for bad in ("NaN", "Infinity", "null", "true", chr(34) + "1" + chr(34)):
        (session / "agents" / "main" / "wire.jsonl").write_text(
            "{" + chr(34) + "type" + chr(34) + ": " + chr(34) + "subagent.spawned" + chr(34)
            + ", " + chr(34) + "subagentId" + chr(34) + ": " + chr(34) + "a1" + chr(34)
            + ", " + chr(34) + "subagentName" + chr(34) + ": " + chr(34) + "factory-coder"
            + chr(34) + ", " + chr(34) + "time" + chr(34) + ": " + bad + "}" + chr(10),
            encoding="utf-8")
        spawns, malformed, _events = pg.wire_spawns(session)
        if spawns or not malformed:
            raise AssertionError(f"a spawn time of {bad} must be malformed evidence, never a "
                                 f"usable stamp: {spawns!r}")
'''

PROBE_FB_JOURNAL_SHAPE = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import action_gate as ag
reader = getattr(ag, "read_journal_rows", None)
if reader is None:
    raise AssertionError("no corrupt journal row may be accepted as coverage")
with tempfile.TemporaryDirectory() as td:
    path = pathlib.Path(td) / "journal.md"
    path.write_text(chr(10).join([
        "| timestamp | mode | class | decision | scope | action | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| 2026-01-01T00:00:00Z | hitl | CONFIRM | maybe | src | rm -f x | looks fine |",
        "| 2026-01-01T00:00:00Z | hitl | CONFIRM | CONFIRM_REQUIRED | src |",
        "| 2026-01-01T00:00:00Z | yolo | CONFIRM | CONFIRM_REQUIRED | src | rm -f x | r |",
    ]) + chr(10), encoding="utf-8")
    result = reader(path)
    rows, problems = result if isinstance(result, tuple) else (result, [])
    if rows:
        raise AssertionError("no corrupt journal row may be accepted as coverage: " + repr(rows))
    if len(problems) != 3:
        raise AssertionError("every corrupt journal row must be reported: " + repr(problems))
'''

PROBE_FB_RECORD_RUN_ID = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("gate_all.py").is_file():
    raise AssertionError("another run's record must not satisfy this phase")
import gate_all as ga
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text(
        "run_id: 20261103-8e939171" + chr(10) + "task_type: implement" + chr(10)
        + "required_roles:" + chr(10) + "  - coder" + chr(10), encoding="utf-8")
    contract = ga.pipeline_contract(root)
    path = root / "gate-K.md"
    path.write_text("run_id: 20260101-deadbeef" + chr(10) + chr(10)
                    + "| gate | exit | applicability | ran_at | command |" + chr(10)
                    + "| --- | --- | --- | --- | --- |" + chr(10), encoding="utf-8")
    problems, _rows = ga.verify_record(path, "K", contract, "the working tree against HEAD")
    if not any("belongs to run" in p or "no run_id" in p for p in problems):
        raise AssertionError("another run's green record must not satisfy this phase: "
                             + repr(problems))
'''

PROBE_FB_REFUTED_VERDICT = '''\
import sys
sys.path.insert(0, ".")
import merge_findings as mm
shard = {"shard": "shard-1", "verdict": "request_changes", "findings": [
    {"severity": "critical", "file": "a.py", "line": 1, "title": "t", "detail": "d",
     "finding_disposition": "refuted", "finding_evidence": "logs/review.md"}]}
report = mm.merge([shard])
if report["verdict"] != "approve":
    raise AssertionError("a wholly refuted round must APPROVE, not stay blocked by the shard's "
                         "original request: " + report["verdict"])
silent = mm.merge([{"shard": "shard-2", "verdict": "request_changes", "findings": []}])
if silent["verdict"] != "request_changes":
    raise AssertionError("an empty request_changes must keep blocking")
'''

PROBE_FB_GATE_BINDING = '''\
import pathlib, sys
sys.path.insert(0, ".")
import test_flow_contracts as flow
root = pathlib.Path(".").resolve().parents[3]
problems = flow.check_delegation_gates(root)
if problems:
    raise AssertionError("every delegation must run the pre-delegation gate in the flow: "
                         + problems[0])
'''


PROBE_FB_ROUND_IDENTITY = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("delegation_gate.py").is_file():
    raise AssertionError("one artifact must settle exactly one round")
import delegation_gate as dg
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10)
                                         + "retry_counters:" + chr(10) + "  reviewer: 2"
                                         + chr(10), encoding="utf-8")
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True)
    (logs / "review.md").write_text("# r" + chr(10), encoding="utf-8")
    (logs / "anonymous.json").write_text(json.dumps({"findings": [
        {"severity": "major", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/review.md"}]}), encoding="utf-8")
    for round_id in ("iter-1", "iter-2"):
        try:
            dg.settle(root, "reviewer", round_id, ".code-factory/logs/anonymous.json",
                      refuted_all=True)
        except dg.GateError as exc:
            if "names no review round" not in str(exc):
                raise AssertionError("a report without its round identity must be refused for that "
                                     "reason: " + str(exc))
        else:
            raise AssertionError("one artifact must settle exactly one round: a report naming no "
                                 "round refunded " + round_id)
'''

PROBE_FB_JOURNAL_CONSISTENCY = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import action_gate as ag
reader = getattr(ag, "read_journal_rows", None)
if reader is None:
    raise AssertionError("a forged journal row is not coverage")
with tempfile.TemporaryDirectory() as td:
    path = pathlib.Path(td) / "journal.md"
    path.write_text(chr(10).join([
        "| timestamp | mode | class | decision | scope | action | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| 2026-01-01T00:00:00Z | auto | HARD_DENY | ALLOW_WITH_ASSUMPTION | - | rm -rf / | x |",
    ]) + chr(10), encoding="utf-8")
    result = reader(path)
    rows, problems = result if isinstance(result, tuple) else (result, [])
    if rows or not problems or "inconsistent decision" not in problems[0]:
        raise AssertionError("a row whose decision does not follow from its class+mode must be a "
                             "violation, not coverage: " + repr((rows, problems)))
'''


PROBE_FB_AUTH_RENEWAL = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("delegation_gate.py").is_file():
    raise AssertionError("a second owner decision must grant its own extra delegation")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10)
                                         + "status: in_progress" + chr(10)
                                         + "retry_counters:" + chr(10) + "  reviewer: 2"
                                         + chr(10), encoding="utf-8")

    def check(*extra):
        res = subprocess.run([sys.executable, "delegation_gate.py", "check", "--repo", str(root),
                              "--role", "reviewer", "--mode", "hitl", *extra],
                             capture_output=True, text=True, errors="replace")
        try:
            return res.returncode, json.loads(res.stdout or "{}")
        except ValueError:
            return res.returncode, {}

    code, verdict = check("--owner-authorized")
    if code != 0 or verdict.get("counter") != 3:
        raise AssertionError("the first owner decision must grant one extra delegation: "
                             + repr(verdict))
    code, verdict = check("--owner-authorized")
    if code != 0 or verdict.get("counter") != 4:
        raise AssertionError("a SECOND owner decision must grant its own extra delegation: "
                             + repr(verdict))
    code, verdict = check()
    if code != 1 or verdict.get("allow") is not False or verdict.get("counter") != 4:
        raise AssertionError("an unauthorized call at budget + authorizations must be refused: "
                             + repr(verdict))
'''


PROBE_FB_ROUND_GRAMMAR = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("merge_findings.py").is_file():
    raise AssertionError("the merged report must be stamped with a settlement identifier")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    shard = root / "s.json"
    shard.write_text(json.dumps({"shard": "shard-1", "verdict": "approve", "findings": []}),
                     encoding="utf-8")

    def run(*args):
        return subprocess.run([sys.executable, "merge_findings.py", "--inputs", str(shard),
                               *args], capture_output=True, text=True, errors="replace")

    good = run("--round", "iter-1")
    if good.returncode != 0 or json.loads(good.stdout).get("round") != "iter-1":
        raise AssertionError("the round identity must be stamped with a settlement identifier: "
                             + good.stderr[-160:])
    bad = run("--round", "bad round!")
    if bad.returncode != 2 or "[A-Za-z0-9._-]+" not in bad.stderr:
        raise AssertionError("an identifier the settlement rejects must be refused at the merge "
                             "boundary by its grammar: " + repr((bad.returncode, bad.stderr[-160:])))
'''

PROBE_FB_HUGE_STAMPS = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("permit_gate.py").is_file():
    raise AssertionError("a huge JSON integer stamp must be judged, not crash")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10), encoding="utf-8")
    (state / "plan.md").write_text("- task_09: x. files: manifest.py; deps: []; verify: v"
                                   + chr(10), encoding="utf-8")
    session = root / "session"
    (session / "agents" / "main").mkdir(parents=True)
    (session / "state.json").write_text("{}", encoding="utf-8")
    (session / "agents" / "main" / "wire.jsonl").write_text(json.dumps({
        "type": "subagent.spawned", "subagentId": "a1", "subagentName": "factory-coder",
        "time": 10 ** 1000}) + chr(10), encoding="utf-8")
    res = subprocess.run([sys.executable, "permit_gate.py", "audit", "--repo", str(root),
                          "--session", str(session)], capture_output=True, text=True,
                         errors="replace")
    if "Traceback" in res.stdout + res.stderr:
        raise AssertionError("a 10**1000 timestamp must be judged, not overflow the audit: "
                             + (res.stdout + res.stderr)[-200:])
    if res.returncode != 1 or "permit-less delegation" not in res.stdout:
        raise AssertionError("the audit must report the REAL violation at a huge stamp: "
                             + repr((res.returncode, res.stdout[-160:])))
'''


PROBE_FB_ROUND_FULLMATCH = '''\
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, ".")
if not pathlib.Path("merge_findings.py").is_file():
    raise AssertionError("a terminal newline must not be a valid round identifier")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    shard = root / "s.json"
    shard.write_text(json.dumps({"shard": "shard-1", "verdict": "approve", "findings": []}),
                     encoding="utf-8")
    res = subprocess.run([sys.executable, "merge_findings.py", "--inputs", str(shard),
                          "--round", "iter-1" + chr(10)], capture_output=True, text=True,
                         errors="replace")
    if res.returncode != 2 or "FULL" not in res.stderr:
        raise AssertionError("a terminal newline must not be a valid round identifier: the "
                             "producer accepted or refused it for the wrong reason: "
                             + repr((res.returncode, res.stderr[-160:])))
if not pathlib.Path("delegation_gate.py").is_file():
    raise AssertionError("a terminal newline must not be a valid round identifier")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    state = root / ".code-factory" / "state"
    state.mkdir(parents=True)
    (state / "pipeline.yaml").write_text("run_id: 20261103-8e939171" + chr(10)
                                         + "retry_counters:" + chr(10) + "  reviewer: 1"
                                         + chr(10), encoding="utf-8")
    logs = root / ".code-factory" / "logs"
    logs.mkdir(parents=True)
    (logs / "review.md").write_text("# r" + chr(10), encoding="utf-8")
    (logs / "newline.json").write_text(json.dumps({"round": "iter-1" + chr(10), "findings": [
        {"severity": "major", "finding_disposition": "refuted",
         "finding_evidence": ".code-factory/logs/review.md"}]}), encoding="utf-8")
    res = subprocess.run([sys.executable, "delegation_gate.py", "settle", "--repo", str(root),
                          "--role", "reviewer", "--round", "iter-1", "--evidence",
                          ".code-factory/logs/newline.json", "--refuted-all"],
                         capture_output=True, text=True, errors="replace")
    if res.returncode != 2 or "FULL" not in res.stderr:
        raise AssertionError("a terminal newline must not be a valid round identifier: the "
                             "settlement accepted or refused it for the wrong reason: "
                             + repr((res.returncode, res.stderr[-160:])))
'''

# --------------------------------------------------------------------------------------------
# The RV/BL/PR probes: the historical release's fixes, replayed against BASE_SHA (resolved by
# `resolve_base`, i.e. the release commit the run started from). They used to be `module` vaccines:
# a whole-module run whose FIRST failing assertion on the pre-fix tree was the declared signature —
# fragile, because a later assertion added to the same module can fail first and turn the vaccine
# into a harness failure. Each one now exercises EXACTLY ONE defect, so its signature cannot be
# overtaken: a focused CLI run, one published check of the self-test that owns the contract, or a
# library call with its own fixture. The declared `expected` strings stay the historical ones.
# --------------------------------------------------------------------------------------------
PROBE_PR_MEMORY_FRESH = '''\
import subprocess, sys, tempfile
with tempfile.TemporaryDirectory() as td:
    res = subprocess.run([sys.executable, "memory_project.py", "check", "--repo", td],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise AssertionError(f"a repository without memory/ must still exit 0: {res.returncode}")
    if "fresh project, memory/ absent" not in res.stdout:
        raise AssertionError("missing journal must note it: the fresh-project line must name the "
                             f"absent memory/ directory, got {res.stdout!r}")
'''

PROBE_PR_MEMORY_PREV2 = '''\
import sys, tempfile
sys.path.insert(0, ".")
import test_factory_model as t
with tempfile.TemporaryDirectory() as td:
    root = t.fixture(td)
    t.memory_fixture(root, t.PRE_V2_ENTRY)
    warnings = t.mem_warnings(root)
    if not (warnings and all("pre-v2 format" in w for w in warnings)):
        raise AssertionError("canonical memory must warn only about the pre-v2 record: the model "
                             f"check reports {warnings} instead of the shared contract's warning")
'''

PROBE_PR_REVIEW_ROUTING = '''\
import sys
sys.path.insert(0, ".")
import test_review_report_only as t
_notes, errors = t.check_flow_guard()
if errors:
    raise AssertionError("FAIL flow-guard - a review context must not reach a write node: "
                         + errors[0])
'''

PROBE_PR_SA_GUARANTEE = '''\
import sys
sys.path.insert(0, ".")
import test_security_audit_guarantee as t
errors = t.collect(t.ROOT)
if errors:
    raise AssertionError("the security_audit guarantee is NOT preserved: " + errors[0])
'''

PROBE_PR_FLOW_CONTRACTS = '''\
import sys
sys.path.insert(0, ".")
import test_flow_contracts as t
problems = t.check_finish_node(t.ROOT)
if problems:
    raise AssertionError("the Finish node wires the memory mechanisms: " + problems[0])
'''

PROBE_PR_ACCEPTANCE_STOP = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_verify_acceptance as t
with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    (tmp / "gate.py").write_text("gate = 1" + chr(10), encoding="utf-8")
    ledger = tmp / "state" / "gate-evidence.json"
    stamp = t.run_ledger("stamp", "--repo", str(tmp), "--ledger", str(ledger),
                         "--name", "regression", "--result", "pass", "--files", "gate.py")
    if stamp.returncode != 0:
        raise AssertionError(f"the evidence ledger stamp must work: {stamp.stderr!r}")
    criteria = t.write_criteria(tmp, [
        {"criterion": "verified", "verify": f'{t.PY} -c "pass"'},
        {"criterion": "inferred from artifacts", "derived": True},
        {"criterion": "never checked"}], name="mixed.json")
    md = tmp / "acceptance_mixed.md"
    res = t.run("--input", str(criteria), "--output", str(md), "--repo", str(tmp),
                "--regression", "pass", "--ledger", str(ledger), "--evidence-files", "gate.py")
    if res.returncode != 0:
        raise AssertionError(f"unverified criteria must not block SUCCESS: {res.stderr!r}")
    text = md.read_text(encoding="utf-8")
    if "all 1 verify criterion MET (2 criteria derived/unverified)" not in text:
        raise AssertionError("the SUCCESS reason must name the unverified count: " + text[:300])
'''

PROBE_PR_DOCS_ENGLISH = '''\
import sys
sys.path.insert(0, ".")
import test_check_english_only as t
try:
    t.check_memory_v2_hit()
except AssertionError as exc:
    raise AssertionError(f"memory_v2_hit: {exc}") from None
'''

PROBE_PR_DOC_VALIDATOR = '''\
import sys
sys.path.insert(0, ".")
import test_validate_documentation as t
mask = getattr(t.vd, "_doc_mask", None)
if mask is None:
    raise AssertionError("bare '*'/'|' lines outside a block must be code: validate_documentation "
                         "has no _doc_mask classifier")
result = mask(["def f():", "*ptr = 1;", "| mask = 2;", "    return 3"])
if result != [False, False, False, False]:
    raise AssertionError(f"bare '*'/'|' lines outside a block must be code: got {result}")
'''

PROBE_PR_VERSION_CARGO = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_version_manager as t
diverged = chr(10).join(['[workspace]', 'members = ["crates/a", "crates/b"]', '',
                         '[workspace.package]', 'version = "9.9.9"', 'edition = "2021"', ''])
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    t.build_clean_repo(root)
    t.write_manifest(root, "Cargo.toml", diverged)
    code, _out, _err = t.run_validate(root)
    if code != 1:
        raise AssertionError("validate must exit 1 on a diverging [workspace.package] version")
'''

PROBE_PR_GENREPORT_ERROR = '''\
import sys
sys.path.insert(0, ".")
import test_gen_code_changes_report as t
t.check_bad_commit()
'''

PROBE_PR_RULES_MESSAGE = '''\
import sys
sys.path.insert(0, ".")
import test_factory_rules as t
registry = t.parse_registry((t.ROOT / t.RULEBOOK).read_text(encoding="utf-8"))
carriers = registry.get(t.RULE) or []
if set(carriers) != set(t.GATE_CARRIERS):
    raise AssertionError(f"{t.RULE!r} must point at its four canonical documents: {carriers}")
'''

PROBE_PR_PRECEDENT_INDEX = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_precedent_index as t
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td) / "proj"
    root.mkdir()
    t.write_fixture(root)
    res = t.run("build", "--repo", str(root))
    if res.returncode != 0:
        raise AssertionError(f"an index build must exit 0: {res.stdout!r} {res.stderr!r}")
    t.fresh_status(root)
'''

# --------------------------------------------------------------------------------------------
# The RF probes: the review follow-up run's fixes, replayed against RUN_BASE_SHA. Same reason as
# above — the four self-test modules they used to run bundle several checks, so each defect now has
# its own isolated reproduction and the historical signature is stated by the probe itself.
# --------------------------------------------------------------------------------------------
PROBE_RF_ACTION_GATE = '''\
import subprocess, sys, tempfile
with tempfile.TemporaryDirectory() as td:
    journal = td + "/action-gate.md"

    def gate(*args):
        return subprocess.run([sys.executable, "action_gate.py", "check", *args,
                               "--journal", journal], capture_output=True, text=True,
                              errors="replace")

    for action in ("git push origin HEAD", "git push -u origin HEAD", "git push origin @"):
        hitl = gate("--action", action, "--mode", "hitl")
        if hitl.returncode != 2 or "CONFIRM_REQUIRED" not in hitl.stdout:
            raise AssertionError(f"'{action}' in hitl must require confirmation: {hitl.stdout!r}")
        auto = gate("--action", action, "--mode", "auto")
        if auto.returncode != 0 or "ALLOW_WITH_ASSUMPTION" not in auto.stdout:
            raise AssertionError(f"'{action}' in auto must be a recorded assumption: {auto.stdout!r}")
        if "decision: ALLOW" + chr(10) in auto.stdout:
            raise AssertionError(f"'{action}' must never be a blind ALLOW: {auto.stdout!r}")
'''

PROBE_RF_EVIDENCE_LEDGER = '''\
import json, pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_evidence_ledger as t
with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    (tmp / "a.py").write_text("a = 1" + chr(10), encoding="utf-8")
    nothing = t.sign(tmp)[0]
    ledger = tmp / "empty-scope" / "evidence.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"version": 1, "entries": [
        {"name": "regression", "result": "pass", "fingerprint": nothing, "files": [],
         "timestamp": "2026-09-24T10:00:00+00:00", "log": None, "run_id": ""}]}), encoding="utf-8")
    res = t.check(tmp, ledger)
    if res.returncode != 1 or "empty scope" not in res.stdout:
        raise AssertionError(f"an empty signed scope must never be FRESH: {res.stdout!r}"
                             f"{res.stderr!r}")
'''

PROBE_RF_NO_LEDGER = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_verify_acceptance as t
with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    criteria = t.write_criteria(tmp, [{"criterion": "ok", "verify": f'{t.PY} -c "pass"'}])
    md = tmp / "acceptance_no_ledger.md"
    res = t.run("--input", str(criteria), "--output", str(md), "--repo", str(tmp),
                "--regression", "pass")
    if res.returncode != 1:
        raise AssertionError(f"SUCCESS without a ledger must be impossible: {res.stdout!r}")
'''

PROBE_RF_BAK_FATAL = '''\
import sys
sys.path.insert(0, ".")
import test_windows_scripts as t
try:
    t.ps1_start_sh_backup_failure_is_fatal()
except AssertionError as exc:
    raise AssertionError("a start.sh.bak that cannot be created aborts the overwrite: "
                         + str(exc)) from None
'''

PROBE_RF_VENDOR_REINSTALL = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import chrome_devtools_mcp as cd
import test_chrome_devtools_mcp as t
with tempfile.TemporaryDirectory() as raw:
    case = pathlib.Path(raw) / "vendor-unproven-missing"
    case_entry = t.seed_vendored_entry(case)
    manifest_of = getattr(cd, "vendored_package_json", None)
    if manifest_of is None:
        raise AssertionError("an unreadable (missing) package.json must trigger a reinstall, never a "
                             "skip: chrome_devtools_mcp.vendored_package_json is missing")
    manifest_of(case_entry).unlink()
    seen = []

    def runner(argv, timeout):
        seen.append(argv)
        t.seed_vendored_entry(case)
        return 0, "added 1 package"

    result = cd.vendor_install(t.vendor_prefix(case), offline=False, runner=runner)
    if len(seen) != 1:
        raise AssertionError("an unreadable (missing) package.json must trigger a reinstall, never "
                             f"a skip: {result}")
'''

PROBE_RF_NO_CLAIMS = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_model_attribution as t
with tempfile.TemporaryDirectory() as raw:
    t.case_11_no_claims_is_degraded(pathlib.Path(raw))
'''

PROBE_RF_UNRESOLVED = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_model_precedence as t
with tempfile.TemporaryDirectory() as raw:
    root = pathlib.Path(raw)
    task = t.write(root, "task-empty.yaml", t.FIXTURE_TASK_NO_MODELS)
    config = t.write(root, "config-no-defaults.toml", "# no models configured here" + chr(10))
    broken = t.run("resolve", "--task", str(task), "--config", str(config))
    if broken.returncode != 1:
        raise AssertionError("a task with no matrix on a config with no default_model leaves every "
                             f"role unresolved, so the run must not start: {t.out(broken)!r}")
'''

PROBE_RF_CRITERIA = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_review_followup_task as t
with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    repo = tmp / "target repo"
    repo.mkdir()
    merged = t.write_json(tmp / "code-review-merged.json", t.MERGED)
    out = tmp / "state" / "review-followup.yaml"
    res = t.run("--findings", str(merged), "--repo", str(repo), "--out", str(out),
                "--run-id", "20261025-d412a454")
    if res.returncode != 0:
        raise AssertionError(f"generation must exit 0: {res.stderr!r}")
    task = t.generator.parse_task(out.read_text(encoding="utf-8"))
    criteria = task["acceptance_criteria"]
    if len(criteria) != len(t.FINDINGS) + 2:
        raise AssertionError(f"expected {len(t.FINDINGS) + 2} criteria, got {len(criteria)}")
'''

PROBE_RF_MANIFEST_SYMLINK = '''\
import pathlib, sys, tempfile
sys.path.insert(0, ".")
import test_version_manager as t
scan = getattr(t.vm, "cargo_manifests", None)
if scan is None:
    raise AssertionError("a symlink escaping the repository must be excluded: version_manager has "
                         "no cargo_manifests scan to apply the containment rule")
consistent = chr(10).join(['[workspace]', 'members = ["crates/a"]', '', '[workspace.package]',
                           'version = "12.1.0"', ''])
with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out_td:
    root = pathlib.Path(td).resolve()
    t.build_clean_repo(root)
    t.write_manifest(root, "Cargo.toml", consistent)
    outside = pathlib.Path(out_td).resolve()
    (outside / "Cargo.toml").write_text(
        chr(10).join(['[package]', 'name = "outside"', 'version = "9.9.9"', '']), encoding="utf-8")
    escape = t.fake_link_dir(root / "escape", target=outside,
                             children=[outside / "Cargo.toml"])
    fake_root = t.fake_link_dir(root, target=root,
                                children=[root / "Cargo.toml", escape])
    manifests = scan(fake_root)
    if any(p.parent == outside for p in manifests):
        raise AssertionError(f"a symlink escaping the repository must be excluded, got {manifests}")
'''

# The NM probe: the `model-unavailable-stop` rule is missing from the rulebook on the pre-fix tree,
# and the module's own rulebook check states exactly that (its carrier/flow checks are other
# findings of the same run and must not be able to overtake this signature).
PROBE_NM_RULEBOOK = '''\
import sys
sys.path.insert(0, ".")
import test_no_role_substitution as t
problems = t.check_rulebook(t.ROOT)
if problems:
    raise AssertionError("the model-unavailable-stop contract must hold: " + problems[0])
'''

# The IV probe: the input-validation gate itself is the fix, so on its pre-fix tree the script does
# not exist at all — the probe states that in the vaccine's own words instead of crashing with an
# ImportError, and on every tree that has the gate it must really bite on the farukon field.
PROBE_IV_GATE = '''\
import pathlib, sys
sys.path.insert(0, ".")
import test_input_validation_gate as t
failure = ("FAIL - 1. a new Rust config field with no validation is caught: an unvalidated new "
           "field must exit 1")
if not pathlib.Path("check_input_validation.py").is_file():
    raise AssertionError(failure)
result = t.gate_on(t.rust_diff([t.RUST_FIELD]))
if result.returncode != 1 or "missing-validation" not in result.stdout:
    raise AssertionError(f"{failure}: exit {result.returncode}: {t.report(result)}")
'''

# THIS run's (FB) finding list: (id, what the run delivered, the vaccine proven on FB_BASE_SHA).
FB_FINDINGS: tuple[tuple[str, str, str], ...] = (
    ("FB-1", "applicability is bound to an explicit platform SUBJECT: the generic identity words "
             "`integration`/`runtime` plus an operation no longer activate the farukon-expert role "
             "(a parser-integration or runtime-config task stays not_applicable, every existing "
             "positive stays applicable)", "V-fb-subject"),
    ("FB-2", "the handshake timeouts are validated at the public boundary BEFORE any process starts: "
             "NaN/±inf/negative/bool/numeric strings are refused with the structured not-ok result "
             "(no traceback, no Popen) while zero stays a legitimate immediate attempt",
     "V-fb-timeouts"),
    ("FB-3", "`decide_applicability` and `validate_config` are composed of focused helpers, so both "
             "stay small and readable with the behaviour frozen (the full `test_farukon_mcp.py` "
             "oracle stays green)", "V-fb-complexity"),
    ("FB-4", "the text-preserving JSON merge surgery lives ONCE, in the stdlib sibling "
             "`mcp_json_merge.py`, imported by both `farukon_mcp.py` and `chrome_devtools_mcp.py` "
             "with identical merge semantics", "V-fb-json-merge"),
    ("FB-5", "the retry budget is machine-enforced: `delegation_gate.py` increments "
             "`retry_counters.<role>` itself before a delegation and REFUSES it once the budget is "
             "exhausted (hitl: the owner stop, auto: FAILED, never an override; --owner-authorized "
             "grants exactly one recorded extra delegation)", "V-fb-budget"),
    ("FB-6", "strict model attribution: a role listed in `required_roles` that claims a model but "
             "left no session-wire trace FAILS the run (exit 1, the role named) for "
             "task_type implement/refactor by default and under `--strict`, never DEGRADED, with "
             "no weakening opt-out", "V-fb-attribution"),
    ("FB-7", "the run's change set is COMPUTED, not claimed: `manifest.py` blocks an edit of a "
             "changed file that has no backup, registers every path with the sha256 it computed "
             "inside the repository, and audits drift/missing backups/missing files at the finish "
             "gate", "V-fb-manifest"),
    ("FB-8", "process signalling is classified at all (`pkill`/`kill`/`killall`/`taskkill` CONFIRM, "
             "the every-process forms HARD_DENY, `kill -l` ALLOW) and the finished run's EXECUTED "
             "shell commands are audited against the action journal, fail-closed on a malformed "
             "wire", "V-fb-actiongate"),
    ("FB-9", "one aggregator (`gate_all.py`) runs every deterministic gate that applies to phase K "
             "or Y, records each one in an attributed record and fails when a gate that should have "
             "run left no record; a present gate that fails propagates, an absent optional gate is "
             "skipped with its reason", "V-fb-gateall"),
    ("FB-10", "the two-level project fingerprint lives in `.code-factory/state/fingerprint.json`, not "
              "in the AGENTS.md whose own commit it describes: `--write-state` writes exactly the "
              "two 64-hex hashes atomically, `--check-state` answers match/divergence/missing, and "
              "the model check reads the state (a stale embedded marker is ignored with a warning, "
              "a missing state is the actionable pre-clone error)", "V-fb-fingerprint"),
    ("FB-11", "a review finding may be REFUTED with evidence (`finding_disposition` "
              "accepted|refuted): a refutation requires an existing artifact, is never deleted from "
              "the merged report, stops counting toward the critical rule, and is omitted from the "
              "generated follow-up task while the omission is reported", "V-fb-disposition"),
    ("FB-12", "a WHOLLY REFUTED review round refunds exactly the one reviewer iteration it "
              "consumed (`delegation_gate.py settle`, evidence mandatory, never below 0, idempotent "
              "per round), while a mixed round never refunds", "V-fb-settle"),
    ("FB-13", "the adversarial BUSINESS TESTER is a registered generator-side role with its own "
              "card: a user-level attacker (wrong input, wrong order, edge configs, repeated "
              "actions, empty/huge/malformed data, interrupted flows) that never edits a product "
              "file, never uses a debugger, writes a classified evidence JSON under "
              "`.code-factory/logs/business-adversarial/`, skips `security_audit` and leaves "
              "acceptance to the tester", "V-fb-biztester"),
    ("FB-14", "the read-only SUPERVISOR is a registered judge-side role with its own card: it holds "
              "the rulebook and the approved plan as its constitution, returns an allow|deny permit "
              "verdict with evidence before a delegation, never writes a product file, never "
              "replaces a human gate, and states honestly that its verdict is model-enforced while "
              "`permit_gate.py` is the deterministic backstop", "V-fb-supervisor"),
    ("FB-15", "the deterministic PERMIT gate behind that verdict: `permit_gate.py` registers plan-"
              "bound, role-checked, in-scope permits, records one evidenced allow|deny, binds the "
              "spawned agent id to an allowed permit, retires an unused permit with a reason, and "
              "its finish audit fails a permit-less delegation, a scope violation, a "
              "denied-but-spawned agent, a duplicate agent id, an out-of-order verdict, an unused "
              "permit and a malformed wire line (DEGRADED when there is no wire)", "V-fb-permit"),
    ("FB-16", "the retry-budget finish audit: `delegation_gate.py audit` fails a budgeted-role spawn "
              "the session wire shows with no counted delegation, fail-closed on malformed wire "
              "evidence and DEGRADED without one — the hook `gate_all.py` calls at phase Y",
     "V-fb-delegation-audit"),
    ("FB-17", "the W2/W3 machinery is REACHABLE from the flow: node DG1 runs the pre-delegation "
              "budget gate and the whole permit lifecycle (add → verdict → spawn → bind, plus the "
              "audit backstop) BEFORE every budgeted or plan-scope-touching delegation, and states "
              "the honest limit (`MODEL-ENFORCED`)", "V-fb-flow-gate"),
    ("FB-18", "the adversarial business tester runs AT NODE S, in parallel with the tester's "
              "business tests (`S --> BT`), through the role's own card and its own "
              "`.code-factory/logs/business-adversarial/` evidence tree — a mechanism the flow "
              "never reaches is not a control", "V-fb-flow-parallel"),
    ("FB-19", "the executable order in `.agents/agents/code-factory.md` reaches the same controls "
              "the flow draws: `manifest.py require` before the first edit, `gate_all.py --repo … "
              "--phase K|Y` at both checkpoints, the manifest audit at the finish and the "
              "pre-delegation gate before a delegation", "V-fb-flow-checkpoints"),
    ("FB-20", "the business-tester EVIDENCE contract is executable, not prose: a report a REAL run "
              "wrote is validated on the documented shape alone (its scenario ids are the run's), "
              "the seeded-defect matrix comparison applies only to this self-test's own marked "
              "fixture report, and `--write` REFUSES to overwrite an existing report without "
              "`--force` — it never replaces a run's evidence with the built-in fixture",
     "V-fb-evidence-contract"),
    ("FB-21", "a handshake timeout larger than the float range is refused BEFORE a child process "
              "starts (the conversion that builds the deadline cannot overflow afterwards)",
     "V-fb-timeouts-huge"),
    ("FB-22", "`delegation_gate.py settle` CHECKS `--refuted-all` against the round's merged-findings "
              "artifact: every finding refuted with its own existing evidence, no accepted or "
              "undispositioned finding, the artifact of the round asked for — a mixed round never "
              "refunds", "V-fb-settle-artifact"),
    ("FB-23", "an implement/refactor checkpoint must declare the mandatory role set: an omitted or "
              "empty `required_roles` is a validation error, so strict attribution cannot be "
              "switched off by leaving the key out", "V-fb-required-roles"),
    ("FB-24", "the manifest AUDIT re-confines every entry: an absolute, traversal or drive-letter "
              "path in a hand-edited manifest is an audit violation", "V-fb-audit-paths"),
    ("FB-25", "a filesystem failure while writing a checkpoint is an actionable exit 2 with the "
              "previous bytes intact — in `delegation_gate.py`, `manifest.py` and `permit_gate.py` "
              "alike, never a traceback", "V-fb-write-errors"),
    ("FB-26", "the permit scope containment has ONE direction: a permit equal to or BELOW a declared "
              "plan entry is accepted (at add time and at audit), a permit above it is refused",
     "V-fb-scope-direction"),
    ("FB-27", "a spawn stamp that is not a finite non-bool number is malformed wire evidence, and a "
              "missing or unusable `verdict_at_ms` is an explicit audit failure instead of a "
              "silently skipped verdict-order check", "V-fb-wire-times"),
    ("FB-28", "every action-journal row is validated (shape, mode, class, decision): a corrupt row or "
              "an unknown decision is an audit violation, never coverage", "V-fb-journal-shape"),
    ("FB-29", "`gate_all.py --verify-only` accepts a record only when its run_id is present and equal "
              "to this run's checkpoint, so another run's green record cannot satisfy a phase",
     "V-fb-record-run-id"),
    ("FB-30", "a wholly refuted review round APPROVES (blocking is computed from the ACTIVE findings) "
              "while an empty `request_changes` keeps blocking", "V-fb-refuted-verdict"),
    ("FB-31", "the flow BINDS the pre-delegation gate to every delegation (per-node clauses for the "
              "analyzer, planner, coder, tester, business tester, reviewer, diagnostician, advisor, "
              "documenter and auditor), models the business leg as a real fork/join, and gives review "
              "and refactor a diagnostic adversarial path that never writes; the orchestrator "
              "registers every resolvable role", "V-fb-gate-binding"),
    ("FB-32", "the settlement artifact must NAME its review round (`round` is mandatory and must "
              "match), so one wholly-refuted report can never refund two round ids; "
              "`merge_findings.py --round` stamps that identity into the merged report",
     "V-fb-round-identity"),
    ("FB-33", "an action-journal row's decision must be the one the gate derives from its class and "
              "mode (`DECISION[(class, mode)]`): a forged combination is an audit violation, never "
              "coverage", "V-fb-journal-consistency"),
    ("FB-34", "the owner-authorized budget extension is PER OWNER DECISION: every "
              "`--owner-authorized` call at the ceiling records a new timestamped note and grants "
              "exactly one more delegation, so N recorded authorizations allow budget + N "
              "delegations (the live bug refused the second decision forever while its own prose "
              "told the main agent to ask the owner again)", "V-fb-auth-renewal"),
    ("FB-35", "the round identity has ONE grammar on both sides: `merge_findings.py --round` "
              "refuses an identifier outside [A-Za-z0-9._-]+ (exit 2, naming the grammar) and the "
              "settlement refuses an artifact stamped outside it, so a produced report can always "
              "settle the round it names", "V-fb-round-grammar"),
    ("FB-36", "a millisecond stamp is judged by an OVERFLOW-SAFE predicate: a Python int is finite "
              "by nature, so a huge JSON integer is ordered (and reported against) instead of "
              "raising OverflowError out of the audit", "V-fb-huge-stamps"),
    ("FB-37", "the round identifier is matched in FULL on both sides (`ROUND_RE.fullmatch`): a "
              "terminal newline or stray whitespace is refused by `merge_findings.py --round` (the "
              "RAW argument, never a stripped copy) and by the settlement's artifact validation, "
              "because `$` alone matches before a trailing newline", "V-fb-round-fullmatch"),
)

# THIS run's (FK) finding list: (id, what the run delivered, the vaccine proven on
# FARUKON_BASE_SHA). The per-run disposition artifact lives under the gitignored `.code-factory/`,
# so the claim of the conditional-platform change set is shipped here, next to the vaccines it
# names — cross-checked two-way exactly like the disposition items.
FARUKON_FINDINGS: tuple[tuple[str, str, str], ...] = (
    ("FK-1", "the flow wires the conditional Farukon path: applicability routing in the implement "
             "node, the `--farukon` pre-flight probe, `models.farukon_expert` with its "
             "`models_used` logging and the tester-owned acceptance", "V-fk-skill"),
    ("FK-2", "the agent instruction registers the specialist, decides applicability, probes the "
             "platform, delegates, logs the model and routes a cargo/MCP failure through F1-F2",
     "V-fk-agent"),
    ("FK-3", "the tester owns the final replay acceptance through `mcp__farukon__*` with "
             "ACCEPTANCE artifacts distinct from the specialist's diagnostics", "V-fk-tester"),
    ("FK-4", "`references/farukon-mcp.md` states activation, managed config, evidence split, "
             "safety defaults and the degradation contract", "V-fk-reference"),
    ("FK-5", "the new `check_farukon_wiring` section of `test_flow_contracts.py` is proven on the "
             "pre-feature tree", "V-fk-contracts"),
    ("FK-6", "`model_matrix.py` pins `farukon_expert` as a KNOWN role on the generator side, so the "
             "default matrix separates it from every judge (the pin moved out of the replayed legacy "
             "module `test_model_precedence.py` into its own focused probe)", "V-fk-generator-side"),
)

# The 12.19 release's own finding list: (id, what the release delivered, the vaccine that proves it
# bites on CLEAN_CODE_BASE_SHA). The release left no per-run disposition file that survives in a
# clone, so the claim lives here and is cross-checked two-way against REGISTRY exactly like the
# disposition items (no orphaned vaccine, no unregistered claim).
CLEAN_CODE_FINDINGS: tuple[tuple[str, str, str], ...] = (
    ("CC-1", "the clean-code discipline skill was not part of the factory: no permanent skill "
             "carried the writing discipline and its contract sections", "V-cc-skills"),
    ("CC-2", "the three metric gates existed in no artifact: CRAP < 10, duplication 0.8 or above "
             "and the surviving-mutant/dead-code gate had no wording a reviewer could apply",
     "V-cc-metrics"),
    ("CC-3", "the measuring tools' safety warnings were unwritten: the install-on-their-own-"
             "initiative risk, the shell-string form and the get-uml-viewer installer",
     "V-cc-safety"),
    ("CC-4", "the two new skills were unregistered: no manifest entry with a content hash, a pinned "
             "revision and the four metrics sources", "V-cc-manifest"),
    ("CC-5", "the gates were not WIRED: code-review.md had no standing §2.2 and the code-writing "
             "and reviewer roles referenced nothing", "V-cc-wiring"),
    ("CC-6", "skill_base.py had no pinned revisions and no multi-source registration "
             "(--revision / --extra-source / `-`)", "V-cc-cli"),
)

# The shipped claim lists, each with the vaccine-id prefix it owns: (source name, prefix, findings).
# One place, so the two-way cross-check runs over every list instead of growing a branch per release.
RELEASE_CLAIMS: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    ("CLEAN_CODE_FINDINGS", "V-cc-", CLEAN_CODE_FINDINGS),
    ("FARUKON_FINDINGS", "V-fk-", FARUKON_FINDINGS),
    ("FB_FINDINGS", "V-fb-", FB_FINDINGS),
)


class Claim(NamedTuple):
    """One reconstructed claim of a group whose per-run disposition artifact no clone keeps.

    `ident` is the CLAIM id and deliberately equals the vaccine id: the original finding numbers
    (`RV-n`, `BL-n`, `PR-n`, `RF-n`, `NM-n`) lived only in the gitignored disposition file, so
    numbering the claims again would fabricate evidence (see `RECONSTRUCTED_CLAIM_GAPS`). `what`
    states the defect the vaccine proves, and `source`/`anchor` name WHERE that claim comes from
    and the literal text it must still contain — a claim whose evidence rotted is a red, never a
    silent assertion. `source` is either a repo-relative document or `commit <sha>[:<path>]`.
    """

    ident: str
    vaccine: str
    what: str
    source: str
    anchor: str


# --------------------------------------------------------------------------------------------
# The reconstructed claims for RV/BL/PR, RF and NM. Those groups prove fixes of three older runs,
# and `.code-factory/logs/findings-disposition.md` — the artifact that carried their ids — was never
# committed (`.code-factory/` is gitignored, and `git rev-list --objects --all` holds no copy). The
# v12.17.0 journal even records that the RV/PR item TEXTS in that file were already reconstructions
# of an overwritten review log, which is why this list claims per VACCINE and cites the evidence
# that survived: the release entries of the tracked `CHANGELOG.md`, the release commits themselves,
# and the `memory/change-log.md` journals. Nothing here is inferred from the registry alone.
# --------------------------------------------------------------------------------------------
RECONSTRUCTED_CLAIMS: tuple[Claim, ...] = (
    # ---- RV/BL/PR: closed by release commit af7cfae (v12.15.0), except where a later release
    # closed the same defect class (the source column says which). BASE_SHA predates all of them.
    Claim("V-memory-identity", "V-memory-identity",
          "the memory owner is the repository identity, not the folder name: the summary declares "
          "`project_id` so a rename or a versioned copy keeps the memory valid",
          "CHANGELOG.md", "Memory ownership no longer depends on the folder name"),
    Claim("V-memory-fresh", "V-memory-fresh",
          "a project without `memory/` is a documented fresh start, distinct from a partial memory "
          "(`memory/` without its journal), which stays a failure",
          "CHANGELOG.md", "check --run-id/--strict/--allow-fresh"),
    Claim("V-memory-onerecord", "V-memory-onerecord",
          "one run is ONE record: a duplicate `run_id` in two valid records is detected instead of "
          "accepted",
          "CHANGELOG.md", "duplicate-`run_id` detection"),
    Claim("V-memory-compact", "V-memory-compact",
          "the 50/20 compaction the rulebook promised exists: a real fold with semantic pre-write "
          "verification that survives a second fold",
          "CHANGELOG.md", "the real 50/20 compaction"),
    Claim("V-memory-carried", "V-memory-carried",
          "an open backlog item carried in the current record with a reason is legal: "
          "`backlog --check` exits 0 when nothing disappeared",
          "CHANGELOG.md", "carried-with-a-reason backlog semantics"),
    Claim("V-memory-actuality", "V-memory-actuality",
          "`## Current state` is actualized every run and compared (version, open/closed counts, "
          "test-file count): a warning under `check`, an error under `--strict`",
          "CHANGELOG.md", "is actualized every run and compared"),
    Claim("V-memory-prev2", "V-memory-prev2",
          "the memory contract has ONE implementation, so the pre-v2 warning one validator reported "
          "is no longer swallowed by the other (the six divergent axes)",
          "CHANGELOG.md", "six previously divergent axes"),
    Claim("V-memory-single-contract", "V-memory-single-contract",
          "`memory_project.validate_memory` is the only implementation of the memory contract and "
          "`check_factory_model.py` delegates to it",
          "CHANGELOG.md", "Memory has one contract"),
    Claim("V-memory-backlog-kind", "V-memory-backlog-kind",
          "`task_type: backlog` is a documented record kind with its own `results` contract, so the "
          "record the factory itself writes is legal without rewriting history",
          "CHANGELOG.md", "becomes a documented record kind"),
    Claim("V-model-precedence", "V-model-precedence",
          "model precedence is stated once and implemented once: the task matrix wins verbatim, an "
          "unnamed role takes the default matrix, generator != judge is an error",
          "CHANGELOG.md", "Model precedence is stated once and implemented once"),
    Claim("V-model-attribution", "V-model-attribution",
          "the served model per role is derived from the CLI session wire and cross-checked against "
          "`models_used` instead of being self-reported",
          "CHANGELOG.md", "derives the model actually served per role"),
    Claim("V-review-routing", "V-review-routing",
          "a `task_type: review` run is report-only: no review verdict reaches a node that writes, "
          "and the findings leave as a report plus a follow-up task file",
          "CHANGELOG.md", "run is report-only"),
    Claim("V-sa-guarantee", "V-sa-guarantee",
          "security_audit's guarantee is untouched and not restated: an unmet review/security_audit "
          "criterion stops at the stop-and-ask node instead of entering error routing",
          "CHANGELOG.md", "guarantee is untouched and not restated"),
    Claim("V-flow-contracts", "V-flow-contracts",
          "the new memory mechanisms are wired into the flow: the Finish node invokes the "
          "compaction and the index is a build product of the flow",
          "CHANGELOG.md", "invoked by the Finish node"),
    Claim("V-review-acceptance-stop", "V-review-acceptance-stop",
          "a SUCCESS verdict names what it does not cover (the derived/unverified rest was not "
          "checked) instead of reading as 'every criterion was verified'",
          "commit 9acc1b7", "the verified-acceptance sentence now promises what the implementation "
                            "does"),
    Claim("V-review-delivery", "V-review-delivery",
          "a review delivers the report plus a generated follow-up task file: the merged findings "
          "become a deterministic `task_type: implement` file",
          "CHANGELOG.md", "The deliverable is the report plus a generated"),
    Claim("V-docs-english", "V-docs-english",
          "the English-only rule acts on NEW memory records (v2, not frozen in "
          "`memory/.english-freeze`), and a memory pass that cannot run is exit 3",
          "CHANGELOG.md", "The English-only rule acts on new memory records"),
    Claim("V-doc-validator", "V-doc-validator",
          "the documentation validator no longer accepts a code line starting `*` or `|` as "
          "documentation",
          "CHANGELOG.md", "no longer classifies a code line starting"),
    Claim("V-version-cargo", "V-version-cargo",
          "`version_manager.py` validates and syncs the version of a Rust workspace/member "
          "`Cargo.toml`, so a diverging `[workspace.package]` version fails",
          "CHANGELOG.md", "validates and syncs the version in a Rust workspace"),
    Claim("V-merge-shardsort", "V-merge-shardsort",
          "`merge_findings.py` sorts shard ids numerically, so a two-digit shard is no longer "
          "ordered by its spelling",
          "CHANGELOG.md", "sorts shard ids numerically"),
    Claim("V-genreport-error", "V-genreport-error",
          "`gen_code_changes_report.py` reports a bad `--commit` as one `error:` line instead of a "
          "multi-line git dump / traceback",
          "CHANGELOG.md", "reports a bad `--commit` as one"),
    Claim("V-rules-message", "V-rules-message",
          "the review-gate rule declares exactly its four canonical carrier documents (a rule that "
          "points elsewhere is caught by the contract test)",
          "commit 43463b3:.agents/skills/code-factory/scripts/test_factory_rules.py",
          "four canonical documents"),
    Claim("V-precedent-index", "V-precedent-index",
          "the precedent index is living state: `status` reports FRESH/STALE and `query --fresh` "
          "refuses a stale index instead of answering from it",
          "CHANGELOG.md", "The precedent index is a build product of the flow"),
    Claim("V-review-verdict-distinction", "V-review-verdict-distinction",
          "for a `task_type: review` run the review gate judges the delivered review, not the "
          "reviewed code: the verdict stays in `results.review=`",
          "commit af7cfae:.agents/skills/code-factory/references/code-review.md",
          "judges the delivered review"),
    # ---- RF: closed by release commit 43463b3 (v12.17.0), replayed against RUN_BASE_SHA (9acc1b7,
    # the v12.16.0 tree the run started from).
    Claim("V-rf-a1", "V-rf-a1",
          "the review gate is bounded: the unconditional `RCR --> M` edge is split into "
          "retry / hitl-stop / auto-conditional-pass, so an exhausted budget cannot restart coding",
          "CHANGELOG.md", "the flow's unconditional `RCR --> M` edge is split into retry"),
    Claim("V-rf-a2", "V-rf-a2",
          "`git push origin HEAD` cannot bypass the default-branch deny: an unprovable destination "
          "resolves conservatively to CONFIRM",
          "CHANGELOG.md", "refspecs resolve conservatively to CONFIRM"),
    Claim("V-rf-a3", "V-rf-a3",
          "an entry with an EMPTY recorded scope signed no file, so it is UNSCOPED and never FRESH",
          "CHANGELOG.md", "an empty recorded scope is UNSCOPED, never FRESH"),
    Claim("V-rf-a5", "V-rf-a5",
          "comment spans are parsed, so executable code sharing a line with a `/* */` comment is "
          "not accepted as documentation",
          "CHANGELOG.md", "comment spans are parsed"),
    Claim("V-rf-a6", "V-rf-a6",
          "SUCCESS requires a usable FRESH `regression=pass` ledger entry: no ledger is DEGRADED, "
          "never silently green",
          "CHANGELOG.md", "SUCCESS requires a usable FRESH `regression=pass` ledger entry"),
    Claim("V-rf-a7", "V-rf-a7",
          "a `start.sh.bak` backup that cannot be created aborts the overwrite with a hard "
          "deployment error instead of being swallowed",
          "CHANGELOG.md", "a failed `start.sh.bak` backup aborts the overwrite"),
    Claim("V-rf-b1", "V-rf-b1",
          "the vendored pinned install fails closed when the installed version cannot be proven "
          "(missing or corrupt package metadata)",
          "CHANGELOG.md", "the vendored pinned install fails closed"),
    Claim("V-rf-b2", "V-rf-b2",
          "an empty `models_used` claim set is DEGRADED (exit 3), never PASS: 'no claim to check' "
          "is not a confirmation",
          "CHANGELOG.md", "an empty `models_used` claim set is DEGRADED"),
    Claim("V-rf-b3", "V-rf-b3",
          "a required role with no model resolved is a resolution error (exit 1), so a task with "
          "no matrix on a config with no default model cannot start",
          "CHANGELOG.md", "a required role with no model resolved is a resolution error"),
    Claim("V-rf-b4", "V-rf-b4",
          "generated follow-up tasks carry a real `verify:` command per finding plus the review "
          "and VERIFIED criteria",
          "CHANGELOG.md", "generated follow-up tasks carry real `verify:` commands"),
    Claim("V-rf-b5", "V-rf-b5",
          "the Cargo manifest traversal skips symlink cycles and enforces containment beneath the "
          "repository, so an escaping link never enters the scan",
          "CHANGELOG.md", "the Cargo manifest traversal skips symlink cycles"),
    Claim("V-rf-c1", "V-rf-c1",
          "the memory CHECK line prints the verdict plus a warnings count instead of the full "
          "multi-line WARN output",
          "CHANGELOG.md", "the memory CHECK lines print the verdict plus a warnings count"),
    Claim("V-rf-c2", "V-rf-c2",
          "`memory_project.py` accepts the one-time migration annotation on a backfilled `run_id`/"
          "`factory_version`, so a synthetic legacy entry is valid",
          "CHANGELOG.md", "accepts the one-time migration annotation"),
    Claim("V-rf-c4", "V-rf-c4",
          "the §7 calibration obligation is a deterministic gate (`calibrate_reviewer.py status`) "
          "wired into the review flow, not prose",
          "CHANGELOG.md", "the §7 periodic-calibration obligation is a deterministic gate"),
    Claim("V-rf-c6", "V-rf-c6",
          "AGENTS.md has a size gate (warn > 28 KB, fail > 32 KB), so the guidance map cannot grow "
          "back without a red",
          "CHANGELOG.md", "AGENTS.md size gate: warn > 28 KB, fail > 32 KB"),
    # ---- NM: closed by release commit d412b2b (v12.18.0), replayed against RUN_BASE_SHA.
    Claim("V-nm-1", "V-nm-1",
          "the canonical rule `model-unavailable-stop` exists: an unavailable task-named model "
          "STOPS the run, and the main agent never performs or substitutes the role",
          "CHANGELOG.md", "Canonical rule `model-unavailable-stop`"),
    Claim("V-nm-2", "V-nm-2",
          "the stop is wired into the flow: the new node `MS` is fed by the reviewer/coder gates "
          "and the retry always re-uses the SAME model",
          "CHANGELOG.md", "new flow node MS fed by M/CR/CR0"),
)

# The parts of the RV/BL/PR/RF/NM claim that could NOT be recovered from evidence. They are
# REPORTED by `--registry-only`, never papered over: the claims above are per vaccine because the
# per-finding identities are gone, and inventing them would prove a mapping nobody can check.
RECONSTRUCTED_CLAIM_GAPS: tuple[str, ...] = (
    "the per-id inventories RV-1..RV-20, BL-1..BL-8, PR-1..PR-18, RF-1..RF-15 and NM-1..NM-2 are "
    "NOT recoverable: the disposition files that carried them were gitignored and were never "
    "committed (`git rev-list --objects --all` holds no copy), and the v12.17.0 journal records that "
    "the RV/PR item texts in that file were themselves reconstructions of an overwritten review log. "
    "The durable claims are therefore keyed by VACCINE, not by finding number",
    "the RV/BL/PR partition per item is not recoverable: the three sources were closed in ONE "
    "release commit (af7cfae, v12.15.0) whose message names the sources and the counts (46 items) "
    "but not which item came from which source, and no per-item record survived. Each claim names "
    "the release evidence that DOES exist (the CHANGELOG.md entry, the commit, or the journal)",
    "the 46 RV/BL/PR items answered 24 vaccines many-to-one, so which item a given vaccine answered "
    "is not recoverable either. Each claim states the surviving evidence sentence for the defect "
    "the vaccine proves; none is inferred from the registry alone",
)


# id -> the FOCUSED check that proves it, and the pre-fix failure it must produce. `ids come from
# the disposition file`: a finding's `vaccine:` names one of these, and the cross-check refuses a
# registry id that no `fixed:` line claims.
REGISTRY: tuple[Vaccine, ...] = (
    Vaccine("V-memory-identity", PROBE, PROBE_IDENTITY,
            r"the memory identity must be declared as `project_id:` right after `repo_path:`"),
    Vaccine("V-memory-fresh", PROBE, PROBE_PR_MEMORY_FRESH,
            r"missing journal must note it"),
    Vaccine("V-memory-onerecord", PROBE, PROBE_ONERECORD,
            r"one run is ONE record: a run_id carried by two records must fail"),
    Vaccine("V-memory-compact", PROBE, PROBE_COMPACT,
            r"`compact` must plan the 50/20 fold"),
    Vaccine("V-memory-carried", PROBE, PROBE_CARRIED,
            r"an item carried in the CURRENT record with a reason must pass"),
    Vaccine("V-memory-actuality", PROBE, PROBE_ACTUALITY,
            r"`--strict` must turn a stale `## Current state` into an error"),
    Vaccine("V-memory-prev2", PROBE, PROBE_PR_MEMORY_PREV2,
            r"canonical memory must warn only about the pre-v2 record"),
    Vaccine("V-memory-single-contract", PROBE, PROBE_SINGLE_CONTRACT,
            r"the memory contract must have ONE public implementation"),
    Vaccine("V-memory-backlog-kind", PROBE, PROBE_BACKLOG_KIND,
            r"`backlog` is a legitimate record kind, not an invalid task_type"),
    Vaccine("V-model-precedence", STRUCTURAL, "test_model_precedence.py",
            r"ModuleNotFoundError: No module named 'model_matrix'"),
    Vaccine("V-model-attribution", STRUCTURAL, "test_model_attribution.py",
            r"ModuleNotFoundError: No module named 'model_attribution'"),
    Vaccine("V-review-routing", PROBE, PROBE_PR_REVIEW_ROUTING,
            r"FAIL flow-guard"),
    Vaccine("V-sa-guarantee", PROBE, PROBE_PR_SA_GUARANTEE,
            r"the security_audit guarantee is NOT preserved"),
    Vaccine("V-flow-contracts", PROBE, PROBE_PR_FLOW_CONTRACTS,
            r"the Finish node wires the memory mechanisms"),
    Vaccine("V-review-delivery", STRUCTURAL, "test_review_followup_task.py",
            r"ModuleNotFoundError: No module named 'review_followup_task'"),
    Vaccine("V-review-acceptance-stop", PROBE, PROBE_PR_ACCEPTANCE_STOP,
            r"must name the unverified count"),
    Vaccine("V-docs-english", PROBE, PROBE_PR_DOCS_ENGLISH,
            r"memory_v2_hit: a v2 record with Cyrillic must exit 1"),
    Vaccine("V-doc-validator", PROBE, PROBE_PR_DOC_VALIDATOR,
            r"bare '\*'/'\|' lines outside a block must be code"),
    Vaccine("V-version-cargo", PROBE, PROBE_PR_VERSION_CARGO,
            r"validate must exit 1 on a diverging \[workspace\.package\] version"),
    Vaccine("V-merge-shardsort", STRUCTURAL, "test_merge_findings.py",
            r"AttributeError: module 'merge_findings' has no attribute 'shard_key'"),
    Vaccine("V-genreport-error", PROBE, PROBE_PR_GENREPORT_ERROR,
            r"stderr must be exactly one `error: \.\.\.` line"),
    Vaccine("V-rules-message", PROBE, PROBE_PR_RULES_MESSAGE,
            r"must point at its four canonical documents"),
    Vaccine("V-precedent-index", PROBE, PROBE_PR_PRECEDENT_INDEX,
            r"status must be FRESH here"),
    Vaccine("V-review-verdict-distinction", LOCAL, "",
            r"the `review-gate-policy` block must contain"),
    # ---- RF: this run's own review follow-up, replayed against RUN_BASE_SHA -------------------
    Vaccine("V-rf-a1", PROBE, PROBE_RCR_EDGE,
            r"the RCR node must not fall back to M unconditionally", RUN_BASE_SHA),
    Vaccine("V-rf-a2", PROBE, PROBE_RF_ACTION_GATE,
            r"'git push origin HEAD' in hitl must require confirmation", RUN_BASE_SHA),
    Vaccine("V-rf-a3", PROBE, PROBE_RF_EVIDENCE_LEDGER,
            r"an empty signed scope must never be FRESH", RUN_BASE_SHA),
    Vaccine("V-rf-a5", PROBE, PROBE_DOC_COMMENT_CODE,
            r"code after a single-line block comment must be a code line", RUN_BASE_SHA),
    Vaccine("V-rf-a6", PROBE, PROBE_RF_NO_LEDGER,
            r"SUCCESS without a ledger must be impossible", RUN_BASE_SHA),
    Vaccine("V-rf-a7", PROBE, PROBE_RF_BAK_FATAL,
            r"a start\.sh\.bak that cannot be created aborts the overwrite", RUN_BASE_SHA),
    Vaccine("V-rf-b1", PROBE, PROBE_RF_VENDOR_REINSTALL,
            r"an unreadable \(missing\) package\.json must trigger a reinstall", RUN_BASE_SHA),
    Vaccine("V-rf-b2", PROBE, PROBE_RF_NO_CLAIMS,
            r"an empty models_used set must be DEGRADED", RUN_BASE_SHA),
    # The original expectation, kept: on the pre-fix tree a task with no matrix and a config with no
    # default_model leaves every role unresolved, so the run must not start. The Farukon
    # generator-side pin lives in its own FK vaccine (V-fk-generator-side), never in this replay.
    Vaccine("V-rf-b3", PROBE, PROBE_RF_UNRESOLVED,
            r"a task with no matrix on a config with no default_model leaves every role "
            r"unresolved",
            RUN_BASE_SHA),
    Vaccine("V-rf-b4", PROBE, PROBE_RF_CRITERIA,
            r"expected 5 criteria, got 4", RUN_BASE_SHA),
    Vaccine("V-rf-b5", PROBE, PROBE_RF_MANIFEST_SYMLINK,
            r"a symlink escaping the repository must be excluded", RUN_BASE_SHA),
    Vaccine("V-rf-c1", PROBE, PROBE_MEM_WARN_FLOOD,
            r"the memory CHECK line must print the verdict plus a WARN count", RUN_BASE_SHA),
    Vaccine("V-rf-c2", PROBE, PROBE_MEMORY_SYNTHETIC_BACKFILL,
            r"a synthetic backfilled run_id/factory_version must be valid", RUN_BASE_SHA),
    # The second claim is suite evolution, not the fix: on the pre-fix tree the shipped golden
    # set is smaller than the current module's GOLDEN_EXPECTED, so the module fails there first.
    Vaccine("V-rf-c4", STRUCTURAL, "test_calibrate_reviewer.py",
            r"(?:AttributeError: module 'calibrate_reviewer' has no attribute "
            r"'REVIEWER_PROMPT_FILES'|golden cases are \[)",
            RUN_BASE_SHA),
    Vaccine("V-rf-c6", PROBE, PROBE_AGENTS_SIZE_GATE,
            r"AGENTS\.md (?:needs a size gate|is \d+ bytes — over the)", RUN_BASE_SHA),
    # ---- NM: this run's own fixes (run 20261026-838dc245) — the named-model stop rule and the
    # unknown-role run error. Replayed against the same base the run started from: at 9acc1b7 no
    # stop rule exists and an invented `models_used` role fell through to DEGRADED.
    Vaccine("V-nm-1", PROBE, PROBE_NM_RULEBOOK,
            r"rule 'model-unavailable-stop' is missing", RUN_BASE_SHA),
    Vaccine("V-nm-2", PROBE, PROBE_PROVIDER_FAILURE_NODE,
            r"no provider-failure node", RUN_BASE_SHA),
    # ---- CC: the 12.19 clean-code release (run 20261031-6dfd0921), replayed against
    # CLEAN_CODE_BASE_SHA. One focused probe per delivered item: the release bundled several fixes,
    # so a whole-module run would validate only the first failing check of each module.
    Vaccine("V-cc-skills", PROBE, PROBE_CC_SKILLS,
            r"clean-code-discipline/SKILL\.md must be shipped", CLEAN_CODE_BASE_SHA),
    Vaccine("V-cc-metrics", PROBE, PROBE_CC_METRICS,
            r"the gate threshold 'CRAP < 10' is not stated", CLEAN_CODE_BASE_SHA),
    Vaccine("V-cc-safety", PROBE, PROBE_CC_SAFETY,
            r"no warning that the measuring tools install packages on their own", CLEAN_CODE_BASE_SHA),
    Vaccine("V-cc-manifest", PROBE, PROBE_CC_MANIFEST,
            r"the 12\.19 skill clean-code-discipline is not registered", CLEAN_CODE_BASE_SHA),
    Vaccine("V-cc-wiring", PROBE, PROBE_CC_WIRING,
            r"the standing `## 2\.2 Metric gates` section is missing", CLEAN_CODE_BASE_SHA),
    Vaccine("V-cc-cli", PROBE, PROBE_CC_CLI,
            r"skill_base\.py resolve must advertise --revision", CLEAN_CODE_BASE_SHA),
    # ---- FX: THIS run's own fixes (run 20261031-dd7ffa0e), replayed against FX_BASE_SHA ---------
    # One focused probe per TESTABLE code fix. The prose/meta fixes of the same run cannot bite by
    # definition and are dispositioned `fixed-prose:` instead (see findings-disposition.md).
    Vaccine("V-fx-rust-regex", PROBE, PROBE_FX_RUST_REGEX,
            r"a Rust compile error `error\[E0308\]` must route to COMPILE_ERROR/coder", FX_BASE_SHA),
    Vaccine("V-fx-timeout-split", PROBE, PROBE_FX_TIMEOUT_SPLIT,
            r"a NON-test timeout must reach the coder route", FX_BASE_SHA),
    Vaccine("V-fx-provider-route", PROBE, PROBE_FX_PROVIDER_ROUTE,
            r"a PROVIDER_MODEL / PROVIDER_FORMAT failure must route to infrastructure", FX_BASE_SHA),
    Vaccine("V-fx-detach-pathspec", PROBE, PROBE_FX_DETACH_PATHSPEC,
            r"`git checkout --detach HEAD \.` must never be ALLOW", FX_BASE_SHA),
    Vaccine("V-fx-vendor-pin", PROBE, PROBE_FX_VENDOR_PIN,
            r"an unreviewed vendored version must make the browser path unusable", FX_BASE_SHA),
    Vaccine("V-fx-fix-task-repo-path", PROBE, PROBE_FX_FIX_TASK_REPO_PATH,
            r"FIX_TASK_REQUIRED must carry repo_path", FX_BASE_SHA),
    Vaccine("V-fx-identity-unverified", PROBE, PROBE_FX_IDENTITY_UNVERIFIED,
            r"an unverifiable project_id must fall back to the name basis", FX_BASE_SHA),
    Vaccine("V-fx-v2-keys", PROBE, PROBE_FX_V2_KEYS,
            r"a v2 record missing the mandatory keys must fail, not warn", FX_BASE_SHA),
    Vaccine("V-fx-mixed-model", PROBE, PROBE_FX_MIXED_MODEL,
            r"a mixed-model service must be a mismatch", FX_BASE_SHA),
    Vaccine("V-fx-missing-marker", PROBE, PROBE_FX_MISSING_MARKER,
            r"a deleted tracked file must be recorded with the MISSING marker", FX_BASE_SHA),
    Vaccine("V-fx-graph-scalar", PROBE, PROBE_FX_GRAPH_SCALAR,
            r"a scalar JSON task file must be refused, not crash", FX_BASE_SHA),
    Vaccine("V-fx-unterminated-quote", PROBE, PROBE_FX_UNTERMINATED_QUOTE,
            r"an unterminated double-quoted scalar must exit 2", FX_BASE_SHA),
    Vaccine("V-fx-docstring-residual", PROBE, PROBE_FX_DOCSTRING_RESIDUAL,
            r"code after a docstring must be a code line", FX_BASE_SHA),
    Vaccine("V-fx-derive-untracked", PROBE, PROBE_FX_DERIVE_UNTRACKED,
            r"--derive must include an undeclared untracked file", FX_BASE_SHA),
    Vaccine("V-fx-title-escape", PROBE, PROBE_FX_TITLE_ESCAPE,
            r"a near-miss README title must be refused", FX_BASE_SHA),
    # ---- IV: THIS run's own fix (the input-validation gate + its self-test), replayed against
    # IV_BASE_SHA. Both files are introduced by the run, so the pre-fix tree has no gate module at
    # all — the isolated probe states that in the vaccine's own words and never crashes.
    Vaccine("V-iv-gate", PROBE, PROBE_IV_GATE,
            r"FAIL - 1\. a new Rust config field with no validation is caught: an unvalidated new "
            r"field must exit 1", IV_BASE_SHA),
    # ---- DP: THIS run's own change set (run 20261101-7cbfae60), replayed against DP_BASE_SHA -----
    # One focused probe per disposed finding. The prose carriers and the four extended self-test
    # modules bundle several of these, so each probe re-executes exactly one defect.
    Vaccine("V-dp-plan-agent", PROBE, PROBE_DP_PLAN_AGENT,
            r"Phase 3 must not call EnterPlanMode", DP_BASE_SHA),
    Vaccine("V-dp-plan-flow-node", PROBE, PROBE_DP_PLAN_SKILL,
            r"flow node I must not call EnterPlanMode", DP_BASE_SHA),
    Vaccine("V-dp-plan-guide", PROBE, PROBE_DP_PLAN_GUIDE,
            r"section 6 must not call the plan-mode tools", DP_BASE_SHA),
    Vaccine("V-dp-advisor-agent", PROBE, PROBE_DP_ADVISOR_AGENT,
            r"the Advisor step must branch on the AGREEMENT", DP_BASE_SHA),
    Vaccine("V-dp-advisor-flow", PROBE, PROBE_DP_ADVISOR_FLOW,
            r"the flowchart must branch on the Advisor's AGREEMENT", DP_BASE_SHA),
    Vaccine("V-dp-route-wrong-results", PROBE, PROBE_DP_ROUTE_WRONG_RESULTS,
            r"error-routing §2 must not keep a WRONG_RESULTS -> CODER row", DP_BASE_SHA),
    Vaccine("V-dp-route-provider", PROBE, PROBE_DP_ROUTE_PROVIDER,
            r"the provider guide must not send model/format to PLANNER", DP_BASE_SHA),
    Vaccine("V-dp-workflow-prose", PROBE, PROBE_DP_WORKFLOW_PROSE,
            r"check_workflow_prose is missing", DP_BASE_SHA),
    Vaccine("V-dp-prompt-pins", PROBE, PROBE_DP_PROMPT_PINS,
            r"the tool/CLI/approval pins must hold on the shipped carriers", DP_BASE_SHA),
    Vaccine("V-dp-readme-gate", PROBE, PROBE_DP_README_GATE,
            r"the operator manual's hitl bullet must describe the executable gate", DP_BASE_SHA),
    Vaccine("V-dp-portable-verify", PROBE, PROBE_DP_PORTABLE_VERIFY,
            r"the portable-verify guidance must name", DP_BASE_SHA),
    Vaccine("V-dp-baseline-files", PROBE, PROBE_DP_BASELINE_FILES,
            r"--baseline-files has no content state", DP_BASE_SHA),
    # ---- FK: THIS run's own change set (run 20261103-4489eb00), replayed against FARUKON_BASE_SHA -
    # The conditional Farukon platform path: one focused probe per carrier class, plus the new
    # `check_farukon_wiring` section of test_flow_contracts.py re-executed against the same tree.
    Vaccine("V-fk-skill", PROBE, PROBE_FK_SKILL,
            r"the conditional Farukon path is unwired", FARUKON_BASE_SHA),
    Vaccine("V-fk-agent", PROBE, PROBE_FK_AGENT,
            r"the Farukon platform path is not orchestrated", FARUKON_BASE_SHA),
    Vaccine("V-fk-tester", PROBE, PROBE_FK_TESTER,
            r"the tester-owned replay acceptance is missing", FARUKON_BASE_SHA),
    Vaccine("V-fk-reference", PROBE, PROBE_FK_REFERENCE,
            r"farukon-mcp\.md must be shipped", FARUKON_BASE_SHA),
    Vaccine("V-fk-contracts", PROBE, PROBE_FK_CONTRACTS,
            r"the Farukon wiring contracts must hold", FARUKON_BASE_SHA),
    Vaccine("V-fk-generator-side", PROBE, PROBE_FK_GENERATOR_SIDE,
            r"the farukon_expert generator side must be pinned in GENERATOR_SIDE", FARUKON_BASE_SHA),
    # ---- FB: THIS run's Farukon/vaccination debt (run 20261103-8e939171), replayed against
    # FB_BASE_SHA. test_farukon_mcp.py bundles all four defects, so each one is its own probe.
    Vaccine("V-fb-subject", PROBE, PROBE_FB_SUBJECT,
            r"a generic identity word is no platform subject", FB_BASE_SHA),
    Vaccine("V-fb-timeouts", PROBE, PROBE_FB_TIMEOUTS,
            r"an unusable timeout \(.+\) must be refused, not launched", FB_BASE_SHA),
    Vaccine("V-fb-complexity", PROBE, PROBE_FB_COMPLEXITY,
            r"must stay small \(cyclomatic complexity", FB_BASE_SHA),
    Vaccine("V-fb-json-merge", PROBE, PROBE_FB_JSON_MERGE,
            r"the shared module mcp_json_merge must exist", FB_BASE_SHA),
    # ---- FB (W2): the machine-enforced retry budget and strict model attribution (violations
    # N-1/N-2/N-3, proposals P-1/P-2/P-3), replayed against the same pre-change HEAD.
    Vaccine("V-fb-budget", PROBE, PROBE_FB_BUDGET,
            r"delegation_gate\.py must exist: a budget counted by the reporter is not enforced",
            FB_BASE_SHA),
    Vaccine("V-fb-attribution", PROBE, PROBE_FB_ATTRIBUTION,
            r"a required role with no wire trace must FAIL under strict attribution",
            FB_BASE_SHA),
    Vaccine("V-fb-manifest", PROBE, PROBE_FB_MANIFEST,
            r"manifest\.py must exist: a manifest written by hand proves nothing", FB_BASE_SHA),
    Vaccine("V-fb-actiongate", PROBE, PROBE_FB_ACTIONGATE,
            r"pkill must be classified, not waved through as ALLOW", FB_BASE_SHA),
    Vaccine("V-fb-gateall", PROBE, PROBE_FB_GATEALL,
            r"gate_all\.py must exist: without one aggregator a skipped gate is invisible",
            FB_BASE_SHA),
    # ---- FB (W2): the derived fingerprint state and the finding disposition (violations N-7,
    # proposal P-8), replayed against the same pre-change HEAD.
    Vaccine("V-fb-fingerprint", PROBE, PROBE_FB_FINGERPRINT,
            r"--write-state must exist: the fingerprint must live in derived state",
            FB_BASE_SHA),
    Vaccine("V-fb-disposition", PROBE, PROBE_FB_DISPOSITION,
            r"a finding_disposition must be accepted and kept, not discarded", FB_BASE_SHA),
    Vaccine("V-fb-settle", PROBE, PROBE_FB_SETTLE,
            r"a wholly refuted round must be settleable", FB_BASE_SHA),
    # ---- FB (W3): the two new roles (tasks 14-15), replayed against the same pre-change HEAD.
    Vaccine("V-fb-biztester", PROBE, PROBE_FB_BIZTESTER,
            r"business_tester must be a registered role of the factory", FB_BASE_SHA),
    Vaccine("V-fb-supervisor", PROBE, PROBE_FB_SUPERVISOR,
            r"supervisor must be a registered role of the factory", FB_BASE_SHA),
    Vaccine("V-fb-permit", PROBE, PROBE_FB_PERMIT,
            r"permit_gate\.py must exist: a model verdict with no deterministic gate", FB_BASE_SHA),
    Vaccine("V-fb-delegation-audit", PROBE, PROBE_FB_DELEGATION_AUDIT,
            r"delegation_gate\.py must exist: the retry budget is counted by the reporter",
            FB_BASE_SHA),
    # ---- FB (task_17): the FLOW wiring of the W2/W3 machinery — a mechanism the shipped flow
    # never reaches is not a control, so each contract is replayed against the base tree, where the
    # flow names none of them.
    Vaccine("V-fb-flow-gate", PROBE, PROBE_FB_FLOW_GATE,
            r"the pre-delegation node must reach", FB_BASE_SHA),
    Vaccine("V-fb-flow-parallel", PROBE, PROBE_FB_FLOW_PARALLEL,
            r"node S must run the adversarial business tester IN PARALLEL", FB_BASE_SHA),
    Vaccine("V-fb-flow-checkpoints", PROBE, PROBE_FB_FLOW_CHECKPOINTS,
            r"the executable order must reach", FB_BASE_SHA),
    Vaccine("V-fb-evidence-contract", PROBE, PROBE_FB_EVIDENCE,
            r"test_business_tester_flow\.py must exist", FB_BASE_SHA),
    # ---- FB (review rework round 1): one vaccine per reviewed defect of this change set.
    Vaccine("V-fb-timeouts-huge", PROBE, PROBE_FB_TIMEOUTS_HUGE,
            r"must be refused BEFORE the", FB_BASE_SHA),
    Vaccine("V-fb-settle-artifact", PROBE, PROBE_FB_SETTLE_ARTIFACT,
            r"refused for being mixed", FB_BASE_SHA),
    Vaccine("V-fb-required-roles", PROBE, PROBE_FB_REQUIRED_ROLES,
            r"without the mandatory roles must fail", FB_BASE_SHA),
    Vaccine("V-fb-audit-paths", PROBE, PROBE_FB_AUDIT_PATHS,
            r"outside the repository must be an audit violation", FB_BASE_SHA),
    Vaccine("V-fb-write-errors", PROBE, PROBE_FB_WRITE_ERRORS,
            r"actionable exit 2, never a traceback", FB_BASE_SHA),
    Vaccine("V-fb-scope-direction", PROBE, PROBE_FB_SCOPE_DIRECTION,
            r"the containment has one direction", FB_BASE_SHA),
    Vaccine("V-fb-wire-times", PROBE, PROBE_FB_WIRE_TIMES,
            r"malformed evidence, never a usable stamp", FB_BASE_SHA),
    Vaccine("V-fb-journal-shape", PROBE, PROBE_FB_JOURNAL_SHAPE,
            r"no corrupt journal row may be accepted", FB_BASE_SHA),
    Vaccine("V-fb-record-run-id", PROBE, PROBE_FB_RECORD_RUN_ID,
            r"must not satisfy this phase", FB_BASE_SHA),
    Vaccine("V-fb-refuted-verdict", PROBE, PROBE_FB_REFUTED_VERDICT,
            r"must APPROVE, not stay blocked", FB_BASE_SHA),
    Vaccine("V-fb-gate-binding", PROBE, PROBE_FB_GATE_BINDING,
            r"must run the pre-delegation gate in the flow", FB_BASE_SHA),
    Vaccine("V-fb-round-identity", PROBE, PROBE_FB_ROUND_IDENTITY,
            r"must settle exactly one round", FB_BASE_SHA),
    Vaccine("V-fb-journal-consistency", PROBE, PROBE_FB_JOURNAL_CONSISTENCY,
            r"is not coverage", FB_BASE_SHA),
    Vaccine("V-fb-auth-renewal", PROBE, PROBE_FB_AUTH_RENEWAL,
            r"a second owner decision must grant", FB_BASE_SHA),
    Vaccine("V-fb-round-grammar", PROBE, PROBE_FB_ROUND_GRAMMAR,
            r"must be stamped with a settlement identifier", FB_BASE_SHA),
    Vaccine("V-fb-huge-stamps", PROBE, PROBE_FB_HUGE_STAMPS,
            r"must be judged, not crash", FB_BASE_SHA),
    Vaccine("V-fb-round-fullmatch", PROBE, PROBE_FB_ROUND_FULLMATCH,
            r"a terminal newline must not be a valid round identifier", FB_BASE_SHA),
)

# `- RV-12: fixed: ... | vaccine: V-memory-identity` — one item per finding, never wrapped. The id
# is either a group id (`RV-12`) or a finding id of the run's own review (`C13`, `Maj2`, `Min3`).
ITEM_RE = re.compile(r"^-\s+([A-Z][A-Za-z]*(?:-\d+|\d+))\s*:\s*(.*)$")
# The concrete grammar a follow-up run writes: `- C13 test_review_report_only.py — ...`, i.e. a
# finding id that is not a `<PREFIX>-<n>` group id, then a subject.
ITEM_PROSE_RE = re.compile(r"^-\s+([A-Z][A-Za-z]*\d+)\s+\S")
# The `files:` and `because:` fields a prose-only fix must carry (see PROSE_FILES_RE).
FILES_RE = re.compile(r"\bfiles\s*:\s*([^|]+)")
BECAUSE_RE = re.compile(r"\bbecause\s*:")
# What a prose-only fix may touch: documentation, prompts, the journal and the factory's own
# meta-tests. Production code, patterns JSON and runtime assets need a vaccine that bites.
PROSE_FILES_RE = re.compile(
    r"^(?:.*\.md|memory/.*|CHANGELOG.*|.*test_[^/]*\.py|.*\.task\.yaml)$")
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
    def is_prose_fixed(self) -> bool:
        """A fixed finding with no pre-fix bite possible (documentation, prompts, meta-tests)."""
        return "fixed-prose:" in self.text

    @property
    def files(self) -> tuple[str, ...]:
        """Every path the item names in its `files:` field."""
        match = FILES_RE.search(self.text)
        if not match:
            return ()
        return tuple(part.strip() for part in match.group(1).split(",") if part.strip())

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
    """Every claim or concrete item of the disposition file, plus whether the file exists at all.

    A MISSING file is deliberately NOT a problem: `.code-factory/` is gitignored, so a fresh clone
    keeps no run artifact. The harness's durable ground truth is its own REGISTRY; the caller prints
    a note and skips the cross-checks that need the artifact. A file that IS there is held to the
    grammar it uses — `- <ID>: fixed: … | vaccine: <ID>` (claims) or `- <ID> <subject> — …`
    (concrete, no vaccine claims) — and an unparsable file is a problem, not a silent skip.
    """
    path = root / DISPOSITION
    if not path.is_file():
        return [], False
    items: list[Item] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        match = ITEM_RE.match(stripped)
        if match is None:
            concrete = ITEM_PROSE_RE.match(stripped)
            if concrete is not None:
                # A dash-form item (`- C1 <subject> — ...`): the id is recognised so the refusal
                # below names it, instead of reporting an unreadable file. It carries no marker, so
                # it fails the `fixed:`/`fixed-prose:`/`deferred:` contract like any other item.
                items.append(Item(number, concrete.group(1), stripped))
            continue
        item = Item(number, match.group(1), match.group(2))
        items.append(item)
        if not (item.is_fixed or item.is_deferred or item.is_prose_fixed):
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` carries neither `fixed:`, "
                            "`fixed-prose:` nor `deferred:` — every finding is disposed of explicitly")
        if item.is_deferred and "reason:" not in item.text:
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is deferred without "
                            "`reason:` — a deferred finding says why it waits")
        if item.is_fixed and not item.vaccine:
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is fixed without "
                            "`vaccine: <ID>` — an unfrozen fix cannot be proven")
        if item.is_prose_fixed:
            problems += prose_fix_problems(item)
    if not items:
        problems.append(f"{DISPOSITION}:1: no `- <ID>: …` or `- <ID> <subject> — …` item found — the "
                        "format changed")
    return items, True


def prose_fix_problems(item: Item) -> list[str]:
    """A prose-only fix says why no bite is possible and touches no production code.

    `fixed-prose:` is the one way to dispose of a fix that cannot fail on a pre-fix tree —
    documentation, a prompt, a meta-test. It is not a free pass: the claim must name the artifacts
    it touched, and every one of them must be documentation/prompt/meta-test material. A production
    module, the patterns JSON or a runtime asset needs a `vaccine:` that bites.
    """
    problems: list[str] = []
    if not BECAUSE_RE.search(item.text):
        problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is a prose fix without "
                        "`because:` — a fix with no pre-fix bite says why none is possible")
    if not item.files:
        problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` is a prose fix without "
                        "`files:` — the claim must name the artifacts it touched")
    for rel in item.files:
        if not PROSE_FILES_RE.match(rel):
            problems.append(f"{DISPOSITION}:{item.line}: `{item.ident}` claims a PROSE fix on "
                            f"{rel!r} — production code needs a `vaccine:` replayed on its pre-fix "
                            "base, a documentation/prompt/meta-test edit does not")
    return problems


def speaks_claims(items: list[Item]) -> bool:
    """True when the disposition names a vaccine or a group id, i.e. can be cross-checked.

    The two lists are only comparable when the file names vaccines (`vaccine: <ID>`) or group ids
    (`<PREFIX>-<n>`). A disposition that names neither cannot be checked at all, and the harness
    refuses it (see `check_registry`) instead of passing it: a fix that is not tied to a vaccine
    replayed on its own pre-fix base is not proven by anything.
    """
    if any(item.vaccines for item in items):
        return True
    prefixes = {prefix for prefix, _count in EXPECTED_GROUPS}
    return any(item.ident.rsplit("-", 1)[0] in prefixes for item in items)


def vaccine_group(vaccine: Vaccine) -> str:
    """The group a registered vaccine belongs to ("" when it belongs to none).

    A group whose per-run artifact is gone (see `LOST_GROUPS`) is claimed by ATTRIBUTION: the
    vaccines of RF/NM/CC carry the group's tag in their id, and the historical RV/BL/PR vaccines
    share the release base and carry no tag at all. Any other vaccine — this run's `FX` group, a
    future group — must be NAMED by a claim, because attribution would make its claim vacuous.
    """
    for group, tag in GROUP_TAGS.items():
        if vaccine.ident.startswith(tag):
            return group
    return HISTORICAL_GROUP if not vaccine.base else ""


def check_registry(items: list[Item], disposed: bool = True) -> tuple[list[str], list[str]]:
    """The cross-checks: (hard problems, registry/disposition drift reported both ways).

    A hard problem breaks the upstream contract the harness reads (an undisposed item, an
    incomplete id inventory, a missing test module) — nothing can be proven then. Drift is the two
    lists disagreeing about WHICH vaccines exist: it does not stop the proof, because proving an
    orphaned vaccine is still worth doing, but it keeps the run red — a vaccine no finding claims
    proves nothing about this release, and a finding whose vaccine is unregistered is never run.

    `disposed=False` means the disposition file is absent (a fresh clone): the registry is then the
    only ground truth, so the registry-INTRINSIC checks (unique ids, every module present, the
    release claim list agreeing with the registry) still run, while the two lists cannot be compared
    at all and the comparison is skipped, not faked. A file that IS present but names no vaccine and
    no group id is NOT that case: it is refused, because a fix no vaccine answers is not proven.
    """
    problems: list[str] = []
    registered = [vaccine.ident for vaccine in REGISTRY]
    registered_set = set(registered)
    if len(registered_set) != len(registered):
        duplicates = sorted({vid for vid in registered if registered.count(vid) > 1})
        problems.append(f"REGISTRY: duplicate id(s) {', '.join(duplicates)} — one vaccine, one entry")
    problems += check_focus()
    problems += check_release_claims()
    problems += check_reconstructed_claims()

    drift: list[str] = []
    # A claim comes from the run's disposition file, a release claim list or a reconstructed claim
    # (the groups whose per-run artifact no clone keeps). Every source names a claim id AND the
    # vaccine that answers it, so both are read here — from EVERY shipped list, so a new group needs
    # its claim list added to RELEASE_CLAIMS (or RECONSTRUCTED_CLAIMS) and nothing else.
    claimed_vaccines = {vaccine for _source, _prefix, findings in RELEASE_CLAIMS
                        for _ident, _what, vaccine in findings}
    claimed_vaccines |= {claim.vaccine for claim in RECONSTRUCTED_CLAIMS}
    declared_ids = {ident for _source, _prefix, findings in RELEASE_CLAIMS
                    for ident, _what, _vaccine in findings}
    declared_ids |= {claim.ident for claim in RECONSTRUCTED_CLAIMS}
    uncovered = unclaimed_vaccines({vid for item in items for vid in item.vaccines}, disposed)
    if disposed and uncovered:
        problems.append("REGISTRY: " + ", ".join(uncovered) + " prove nothing durable — every "
                        "vaccine must be claimed by a release claim list, a reconstructed claim or a "
                        "disposition item")
    if disposed and not speaks_claims(items):
        # The escape this used to be is closed: a present disposition that names no vaccine and no
        # group id cannot be cross-checked by anything, so every fix it disposes of would sit
        # outside the pre-fix proof.
        problems.append(f"{DISPOSITION}:1: the disposition names no `vaccine:` claim and no group id, "
                        "so nothing in it can be cross-checked against REGISTRY — a fix that is not "
                        "tied to a vaccine replayed on its own pre-fix base is not proven")
    if disposed and speaks_claims(items):
        named = {vid for item in items if item.is_fixed for vid in item.vaccines}
        claimed = {vid for item in items for vid in item.vaccines}
        drift = [f"{DISPOSITION}: `{vaccine}` is named by a finding but is NOT registered in REGISTRY — "
                 "its check would never be executed"
                 for vaccine in sorted((claimed | claimed_vaccines) - registered_set)]

        # The orphan half: a registered vaccine is claimed either by NAME (this disposition, a
        # release claim list or a reconstructed claim) or by ATTRIBUTION to a group whose artifact
        # is lost. Attribution is never available to a group that is not in LOST_GROUPS, so this
        # run's own group cannot escape the registry/disposition comparison.
        drift += [f"REGISTRY: `{vaccine}` is registered but neither a `fixed:` line of {DISPOSITION} "
                  "nor a release claim names it — an orphaned vaccine proves nothing"
                  for vaccine in sorted(registered_set - named - claimed_vaccines)
                  if vaccine_group(_by_id(vaccine)) not in LOST_GROUPS
                  and vaccine_group(_by_id(vaccine)) != HISTORICAL_GROUP]

        enumerated = groups_enumerated(items)
        present = {item.ident for item in items} | declared_ids
        for prefix, count in EXPECTED_GROUPS:
            if prefix in LOST_GROUPS and prefix not in enumerated:
                continue                       # that run's item texts are not kept: see LOST_GROUPS
            missing = [f"{prefix}-{index}" for index in range(1, count + 1)
                       if f"{prefix}-{index}" not in present]
            if missing:
                problems.append(f"{DISPOSITION}: missing id(s) {', '.join(missing)} — the "
                                f"{prefix} inventory must be complete ({prefix}-1..{prefix}-{count})")

        # A group the disposition enumerates has to be answered ONE-FOR-ONE by the vaccines that
        # carry it: an enumerated group is a group whose fixes are being shipped now.
        for group in sorted(enumerated - set(LOST_GROUPS)):
            unnamed = sorted(v.ident for v in REGISTRY
                             if vaccine_group(v) == group and v.ident not in named)
            if unnamed:
                problems.append(f"{DISPOSITION}: the {group} group is enumerated but "
                                f"{', '.join(unnamed)} answer no `fixed:` item — every vaccine of a "
                                "group this disposition lists must be named by one of its items")

    for tool in sorted(module_targets() | set(PROBE_FIXTURES) | {HELPER_TEST}):
        if not (SCRIPT_DIR / tool).is_file():
            problems.append(f"{SCRIPT_DIR.name}/{tool}: file is missing — the vaccine of "
                            "REGISTRY cannot be executed")
    return problems, drift


def _by_id(ident: str) -> Vaccine:
    """The registered vaccine with that id (the caller iterates the registry, so it exists)."""
    return next(vaccine for vaccine in REGISTRY if vaccine.ident == ident)


def check_release_claims() -> list[str]:
    """The shipped claim lists and REGISTRY must name each other, one vaccine per claim.

    A release or run whose per-run disposition artifact a clone does not keep needs its claim
    written down somewhere durable: `CLEAN_CODE_FINDINGS`, `FARUKON_FINDINGS` and `FB_FINDINGS` are
    that place, and `RELEASE_CLAIMS` is the one list they are read through. The check is the same
    two-way contract the disposition gets: a claim with no registered vaccine is never executed, and
    a registered vaccine of that claim list's own prefix that no claim answers could be removed
    without anyone noticing.
    """
    problems: list[str] = []
    registered = {vaccine.ident for vaccine in REGISTRY}
    for source, prefix, findings in RELEASE_CLAIMS:
        claims = [ident for ident, _what, _vaccine in findings]
        for ident in sorted({claim for claim in claims if claims.count(claim) > 1}):
            problems.append(f"{source}: `{ident}` is claimed twice — one claim, one vaccine")
        for ident, _what, vaccine in findings:
            if vaccine not in registered:
                problems.append(f"{source}: {ident} names the vaccine `{vaccine}`, which is "
                                "NOT registered — its check would never be executed")
        claimed_vaccines = {vaccine for _ident, _what, vaccine in findings}
        for vaccine in sorted(registered - claimed_vaccines):
            if vaccine.startswith(prefix):
                problems.append(f"REGISTRY: `{vaccine}` is a release vaccine no {source} item "
                                "claims — an orphaned vaccine proves nothing")
    return problems


def claim_evidence(source: str) -> tuple[str | None, str]:
    """`(text, reason)` of a claim's evidence: what the pointer resolves to, or why it does not.

    `source` is a repo-relative document (`CHANGELOG.md`, `memory/change-log.md`, ...) or
    `commit <sha>[:<path>]`. The commit form is read with a READ-ONLY `git show`, so a claim cites a
    revision of the repository rather than the state of one working copy; a missing git is a
    reported reason, never a silent pass.
    """
    if source.startswith("commit "):
        sha, _, path = source[len("commit "):].partition(":")
        revision = f"{sha}:{path}" if path else sha
        try:
            res = subprocess.run(["git", "-C", str(REPO_ROOT), "show", revision],
                                 capture_output=True)
        except OSError as exc:                     # no git on PATH at all
            return None, f"git is unavailable ({exc})"
        if res.returncode != 0:
            return None, f"the revision {revision} cannot be read"
        return res.stdout.decode("utf-8", "replace"), ""
    path = REPO_ROOT / source
    if not path.is_file():
        return None, f"{source} does not exist in the repository"
    return path.read_text(encoding="utf-8"), ""


def check_reconstructed_claims(claims: tuple[Claim, ...] = RECONSTRUCTED_CLAIMS) -> list[str]:
    """The reconstructed RV/BL/PR/RF/NM claims must be complete, unique and EVIDENCE-BACKED.

    - one claim per vaccine, keyed by the vaccine id (the historical finding numbers are lost — see
      `RECONSTRUCTED_CLAIM_GAPS`);
    - every claim names a REGISTERED vaccine, states what it proves and carries an evidence pointer;
    - the evidence is RE-READ here: its anchor must still be present in the cited document or
      revision. A claim whose evidence rotted fails its own check instead of asserting a mapping
      nobody can verify.
    """
    problems: list[str] = []
    registered = {vaccine.ident for vaccine in REGISTRY}
    idents = [claim.ident for claim in claims]
    for ident in sorted({claim for claim in idents if idents.count(claim) > 1}):
        problems.append(f"RECONSTRUCTED_CLAIMS: `{ident}` is claimed twice — one claim, one vaccine")
    claimed: set[str] = set()
    for claim in claims:
        if claim.vaccine not in registered:
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.ident}` names the vaccine "
                            f"`{claim.vaccine}`, which is NOT registered — its check would never be "
                            "executed")
            continue
        if claim.ident != claim.vaccine:
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.ident}` must be keyed by its vaccine "
                            f"(`{claim.vaccine}`): the historical finding numbers do not exist, so "
                            "the only honest claim id is the vaccine it answers")
        if claim.vaccine in claimed:
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.vaccine}` is claimed twice — one claim, "
                            "one vaccine")
        claimed.add(claim.vaccine)
        if not claim.what.strip():
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.ident}` states nothing it proves")
        text, reason = claim_evidence(claim.source)
        if text is None:
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.ident}` cannot be verified: {reason}")
        elif claim.anchor not in text:
            problems.append(f"RECONSTRUCTED_CLAIMS: `{claim.ident}` cites {claim.source}, but its "
                            f"evidence no longer contains {claim.anchor!r} — a claim whose evidence "
                            "rotted is not a claim")
    return problems


def unclaimed_vaccines(named: set[str], disposed: bool) -> list[str]:
    """Registered vaccines that NO claim answers — the coverage half of the claim contract.

    A claim comes from a release claim list, a reconstructed claim, or (for the run-local FX/DP/IV
    groups) the run's own disposition file. The last source is a gitignored artifact, so its
    coverage is only checkable while that artifact is present; `disposed=False` therefore means
    "the run-local claims cannot be compared", not "they do not exist".
    """
    covered = {vaccine for _source, _prefix, findings in RELEASE_CLAIMS
               for _ident, _what, vaccine in findings}
    covered |= {claim.vaccine for claim in RECONSTRUCTED_CLAIMS}
    if disposed:
        covered |= named
    return sorted({vaccine.ident for vaccine in REGISTRY} - covered)


def groups_enumerated(items: list[Item]) -> set[str]:
    """The group prefixes the disposition enumerates (`FX-7` present ⇒ `FX`)."""
    return {prefix for prefix, _count in EXPECTED_GROUPS
            if any(item.ident.startswith(f"{prefix}-") for item in items)}


def inventory_state(items: list[Item], declared_ids: set[str] | None = None
                    ) -> tuple[list[str], list[str]]:
    """(group labels whose 1..N inventory is verified, group labels without an id inventory).

    A group whose per-run artifact is lost and which the disposition does not enumerate has no item
    texts left to check, so it is reported as "no per-id inventory" instead of a verified inventory.
    Its VACCINES are not left unclaimed: `RECONSTRUCTED_CLAIMS` covers every one of them, with the
    evidence pointer re-read by `check_reconstructed_claims`. The missing part is the numbering, and
    `RECONSTRUCTED_CLAIM_GAPS` states it rather than inventing it.
    """
    enumerated = groups_enumerated(items)
    declared = declared_ids or set()
    verified, attested = [], []
    for prefix, count in EXPECTED_GROUPS:
        label = f"{prefix}-1..{prefix}-{count}"
        if prefix in LOST_GROUPS and prefix not in enumerated and not any(
                ident.startswith(f"{prefix}-") for ident in declared):
            attested.append(prefix)
        else:
            verified.append(label)
    return verified, attested


def module_targets() -> set[str]:
    """Every self-test module a `module`/`structural` vaccine runs (probes need no file)."""
    return {vaccine.target for vaccine in REGISTRY if vaccine.kind in (MODULE, STRUCTURAL)}


# --------------------------------------------------------------------------------------------
# The cross-checks must REFUSE a disposition that cannot be proven, and ACCEPT the shipped one.
# Each fixture is a whole disposition body; `expected` is the fragment the refusal must carry
# ("" = the fixture must be accepted).
# --------------------------------------------------------------------------------------------
DISPOSITION_FIXTURES: tuple[tuple[str, str, str], ...] = (
    ("a present disposition that names no vaccine claim",
     "# Disposition\n\n## Fixed\n\n- C1 error-patterns.default.json — fixed by hand\n",
     "the disposition names no `vaccine:` claim and no group id"),
    ("a fixed item that names no vaccine",
     "- FX-15: fixed: the near-miss title is refused | files: README.md\n",
     "is fixed without `vaccine: <ID>`"),
    ("a claim naming a vaccine that is not registered",
     "- FX-15: fixed: the near-miss title is refused | vaccine: V-not-a-vaccine\n",
     "is named by a finding but is NOT registered in REGISTRY"),
    ("a prose claim on production code",
     "- C13: fixed-prose: the guard | files: .agents/skills/code-factory/scripts/error_router.py "
     "| because: meta\n- FX-15: fixed: title | vaccine: V-fx-title-escape\n",
     "claims a PROSE fix on"),
    ("a prose claim that says why no bite is possible",
     "- C13: fixed-prose: the guard | files: .agents/skills/code-factory/scripts/test_x.py\n"
     "- FX-15: fixed: title | vaccine: V-fx-title-escape\n",
     "is a prose fix without `because:`"),
    ("an enumerated group with an incomplete inventory",
     "- FX-1: fixed: the Rust regex | vaccine: V-fx-rust-regex\n",
     "the FX inventory must be complete"),
    ("an enumerated group whose vaccines are not named one-for-one",
     "".join(f"- FX-{n}: fixed: the same vaccine again | vaccine: V-fx-rust-regex\n"
             for n in range(1, 16)),
     "answer no `fixed:` item"),
)


def check_disposition_fixtures() -> list[str]:
    """Run the fixtures above: every refusal has to happen, and the shipped file has to pass.

    This is the self-check of the cross-checks themselves. Without it the "cannot be cross-checked"
    refusal could rot into a silent pass again — which is exactly the defect it was written for.
    """
    problems: list[str] = []
    for name, body, expected in DISPOSITION_FIXTURES:
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            path = root / DISPOSITION
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            found: list[str] = []
            items, disposed = parse_disposition(root, found)
            more, drift = check_registry(items, disposed)
        said = "\n".join(found + more + drift)
        if expected and expected not in said:
            problems.append(f"FIXTURE {name!r}: the cross-checks must refuse it with {expected!r}, "
                            f"said {said.strip()[:200]!r}")
        elif not expected and said.strip():
            problems.append(f"FIXTURE {name!r}: must be accepted, refused with "
                            f"{said.strip()[:200]!r}")

    found = []
    items, disposed = parse_disposition(REPO_ROOT, found)
    if disposed:
        more, drift = check_registry(items, disposed)
        if found or more or drift:
            problems.append(f"{DISPOSITION}: the shipped disposition must pass its own cross-checks: "
                            f"{(found + more + drift)[0]}")
    return problems


# The reconstructed-claim checks must REFUSE a claim nobody can verify, and ACCEPT the shipped list.
# Each fixture is a whole claim list; `expected` is the fragment the refusal must carry.
CLAIM_FIXTURES: tuple[tuple[str, tuple[Claim, ...], str], ...] = (
    ("a claim citing a document that does not exist",
     (Claim("V-memory-fresh", "V-memory-fresh", "the fresh-project note", "NO-SUCH-DOC.md", "x"),),
     "cannot be verified"),
    ("a claim whose evidence rotted",
     (Claim("V-memory-fresh", "V-memory-fresh", "the fresh-project note", "CHANGELOG.md",
            "this sentence was never written into the changelog"),),
     "evidence no longer contains"),
    ("a claim naming an unregistered vaccine",
     (Claim("V-nope", "V-nope", "nothing", "CHANGELOG.md", "12.15.0"),),
     "which is NOT registered"),
    ("a claim re-numbered instead of keyed by its vaccine",
     (Claim("RV-7", "V-memory-fresh", "the fresh-project note", "CHANGELOG.md", "12.15.0"),),
     "must be keyed by its vaccine"),
)


def check_claim_fixtures() -> list[str]:
    """Prove the reconstructed-claim checks bite, and that the shipped claim list passes them.

    Without this, "the evidence is re-read" could rot into a sentence: a check that accepts any
    pointer proves nothing about the claims it is supposed to guard.
    """
    problems: list[str] = []
    for name, claims, expected in CLAIM_FIXTURES:
        said = "\n".join(check_reconstructed_claims(claims))
        if expected not in said:
            problems.append(f"FIXTURE {name!r}: the claim checks must refuse it with {expected!r}, "
                            f"said {said.strip()[:200]!r}")
    shipped = "\n".join(check_reconstructed_claims())
    if shipped:
        problems.append("RECONSTRUCTED_CLAIMS: the shipped claim list must pass its own evidence "
                        f"check: {shipped.strip()[:200]}")
    return problems


def check_focus() -> list[str]:
    """The focus contract of the registry itself: none of these may silently degrade a proof.

    - a `probe` must COMPILE (a broken probe would fail for the wrong reason);
    - `kind` must be one of the four, and `expected` must be a usable regex;
    - NO `module` vaccine may be registered any more. A whole-module check declares the FIRST
      assertion its module fails on the pre-fix tree, so any later assertion added to that module
      can fail first instead: the bite then belongs to another defect (or becomes a harness
      failure), which is exactly the fragility this registry replaced with one isolated probe per
      finding. The check is here, not in a comment, so a regression cannot come back silently.
    - a vaccine proves a SPECIFIC defect, so two vaccines must not share one `expected` string for
      the same target — that is the "one unrelated failure validates them all" defect this harness
      exists to refuse;
    - a `structural` vaccine must declare the missing module/symbol, and that artefact must EXIST
      on the working tree — otherwise the import error is unrelated to the fix and proves nothing.
    """
    problems: list[str] = []
    signatures: dict[tuple[str, str, str], list[str]] = {}
    for vaccine in REGISTRY:
        if vaccine.kind == MODULE:
            problems.append(f"REGISTRY: `{vaccine.ident}` is a `module` vaccine on "
                            f"{vaccine.target} — a whole-module run cannot prove one defect: replace "
                            "it with an isolated `probe` that reproduces exactly that defect")
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
    """Copy the CURRENT test modules the vaccines and probes need into the pre-fix tree."""
    problems: list[str] = []
    dest_scripts.mkdir(parents=True, exist_ok=True)
    for tool in sorted(module_targets() | set(PROBE_FIXTURES) | {HELPER_TEST}):
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
    problems.extend(check_disposition_fixtures())
    problems.extend(check_claim_fixtures())
    if problems:
        print(f"FAIL - {len(problems)} vaccination cross-check problem(s) under {REPO_ROOT}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    vaccines = len(REGISTRY)
    verified, attested = inventory_state(
        items, {ident for _source, _prefix, findings in RELEASE_CLAIMS
                for ident, _what, _vaccine in findings})
    groups = ", ".join(verified)
    gone = (f"; {', '.join(attested)} have no per-id inventory artifact — their per-vaccine claims "
            f"are reconstructed from the journals and the release commits ({len(RECONSTRUCTED_CLAIMS)} "
            "claim(s), evidence re-read)"
            if attested else "")
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
              f"vaccine(s), every enumerated id present ({groups}){gone}, but the registry and "
              f"{DISPOSITION} disagree ({len(drift)} place(s), reported both ways):")
        for problem in drift:
            print(f"  - {problem}")
    else:
        print(f"PASS - cross-checks: {len(items)} item(s) disposed of, {vaccines} registered "
              f"vaccine(s) ({kinds}), every enumerated id present ({groups}){gone}, REGISTRY and "
              f"{DISPOSITION} name each other")

    for gap in RECONSTRUCTED_CLAIM_GAPS:
        print(f"gap - {gap}")

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

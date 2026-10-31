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

`V-review-verdict-distinction` has no test module: its check is the local probe below, which reads
the canonical `factory-rule` blocks from the root it is pointed at — the same function serves both
runs, so the block that is absent at the base commit fails there and passes here.

Cross-checks run before anything slow, and `--registry-only` stops after them:
  - every `vaccine: <ID>` of the disposition file is registered, and every registered ID is claimed
    by name (the disposition or a shipped claim list) or is attributable to a group whose own run
    kept no artifact — reported both ways, because an orphaned vaccine is as bad as a registered ID
    nobody claims;
  - a claim item carries `fixed:` (with a `vaccine:`), `fixed-prose:` (with `files:` and `because:`,
    documentation/prompt/meta-test material only) or `deferred:` (with `reason:`);
  - every group the disposition ENUMERATES has its complete id inventory, and every vaccine of that
    group is named by one of its items — a group the disposition does not enumerate has to be one of
    the five historical groups whose run artifact is not kept;
  - every registered test module (and the `test_prompt_structure.py` helper) exists in the
    working tree;
  - `check_disposition_fixtures()` re-proves the cross-checks themselves: seven dispositions the
    harness MUST refuse (no claim, fixed without a vaccine, a claim on an unregistered vaccine, a
    prose claim on production code, a prose claim without `because:`, an incomplete inventory, an
    enumerated group whose vaccines are unnamed) plus the shipped file, which must pass.

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
# own helpers instead of re-inventing them). They are copied into every pre-fix tree even when no
# `module`/`structural` vaccine of that run happens to name them.
PROBE_FIXTURES = ("test_chrome_devtools_mcp.py", "test_memory_project.py",
                  "test_model_attribution.py", "test_version_manager.py")

# The disposition contract: every group of the task's sources, exhaustively. `RF` is an earlier
# review follow-up group, `CC` the 12.19 clean-code release and `FX` THIS run's own fixes: a release
# whose vaccines were only ever replayed against an older base proves nothing about the change set
# being shipped now.
EXPECTED_GROUPS = (("RV", 20), ("BL", 8), ("PR", 18), ("RF", 15), ("NM", 2), ("CC", 6), ("FX", 15))
# The id prefix that tags a registered vaccine with its group. The five historical groups below
# carry no tag (their vaccines are the release-wide `V-memory-*`, `V-model-*`, ... entries).
GROUP_TAGS = {"RF": "V-rf-", "NM": "V-nm-", "CC": "V-cc-", "FX": "V-fx-"}
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
    Vaccine("V-rf-a5", PROBE, PROBE_DOC_COMMENT_CODE,
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
    Vaccine("V-rf-c2", PROBE, PROBE_MEMORY_SYNTHETIC_BACKFILL,
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

    drift: list[str] = []
    # A claim comes from the run's disposition file OR from the release claim list shipped next to
    # the vaccines (a release whose per-run artifact a clone does not keep). The claim list names a
    # finding id AND the vaccine that answers it, so both are read here.
    claimed_vaccines = {vaccine for _ident, _what, vaccine in CLEAN_CODE_FINDINGS}
    declared_ids = {ident for ident, _what, _vaccine in CLEAN_CODE_FINDINGS}
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

        # The orphan half: a registered vaccine is claimed either by NAME (this disposition or the
        # shipped claim list) or by ATTRIBUTION to a group whose artifact is lost. Attribution is
        # never available to a group that is not in LOST_GROUPS, so this run's own group cannot
        # escape the registry/disposition comparison.
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
    """The shipped claim list and REGISTRY must name each other, one vaccine per claim.

    A release whose per-run disposition artifact a clone does not keep needs its claim written down
    somewhere durable; `CLEAN_CODE_FINDINGS` is that place. The check is the same two-way contract
    the disposition gets: a claim with no registered vaccine is never executed, and a registered
    `CC` vaccine no claim answers could be removed without anyone noticing.
    """
    problems: list[str] = []
    registered = {vaccine.ident for vaccine in REGISTRY}
    claims = [ident for ident, _what, _vaccine in CLEAN_CODE_FINDINGS]
    for ident in sorted({claim for claim in claims if claims.count(claim) > 1}):
        problems.append(f"CLEAN_CODE_FINDINGS: `{ident}` is claimed twice — one claim, one vaccine")
    for ident, _what, vaccine in CLEAN_CODE_FINDINGS:
        if vaccine not in registered:
            problems.append(f"CLEAN_CODE_FINDINGS: {ident} names the vaccine `{vaccine}`, which is "
                            "NOT registered — its check would never be executed")
    claimed_vaccines = {vaccine for _ident, _what, vaccine in CLEAN_CODE_FINDINGS}
    for vaccine in sorted(registered - claimed_vaccines):
        if vaccine.startswith("V-cc-"):
            problems.append(f"REGISTRY: `{vaccine}` is a release vaccine no CLEAN_CODE_FINDINGS item "
                            "claims — an orphaned vaccine proves nothing")
    return problems


def groups_enumerated(items: list[Item]) -> set[str]:
    """The group prefixes the disposition enumerates (`FX-7` present ⇒ `FX`)."""
    return {prefix for prefix, _count in EXPECTED_GROUPS
            if any(item.ident.startswith(f"{prefix}-") for item in items)}


def inventory_state(items: list[Item], declared_ids: set[str] | None = None
                    ) -> tuple[list[str], list[str]]:
    """(group labels whose 1..N inventory is verified, group labels claimed by attribution).

    A group whose per-run artifact is lost and which the disposition does not enumerate has no
    item texts left to check, so its vaccines are claimed by ATTRIBUTION instead — reported, never
    presented as a verified inventory.
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
    if problems:
        print(f"FAIL - {len(problems)} vaccination cross-check problem(s) under {REPO_ROOT}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    vaccines = len(REGISTRY)
    verified, attested = inventory_state(items, {i for i, _w, _v in CLEAN_CODE_FINDINGS})
    groups = ", ".join(verified)
    gone = (f"; {', '.join(attested)} are claimed by attribution (their own run kept no artifact)"
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

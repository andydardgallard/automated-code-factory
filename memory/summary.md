# Project Summary — Code Factory

<!-- code-factory-memory: summary -->
project: repo
repo_path: .
project_id: dd18352c83a5

Condensed summary of the project. It is folded out of older `memory/change-log.md` records at
compaction (threshold 50 records) and is read at the start of every task, so the project's history
does not have to be derived again.

## Current state
Factory v12.15.0 — the "honest factory" patch is delivered on `feature/v12.15.0-honest-factory`
(base `fb43f2a`).
Latest run: implement (run_id 20261025-4e17a349, task-fix-v12.15.0.yaml, hitl). One patch closed
all 46 items of its three sources — the 20 findings of review 20261025-634bc01b, the 8 open backlog
items, and the 18 findings F1-F18 of the earlier report-only-review task — each dispositioned in
`.code-factory/logs/findings-disposition.md` with the check that proves it
(`.code-factory/logs/findings-disposition.md`, 46 fixed, 0 deferred). What is now true:
a `task_type: review` run is REPORT-ONLY (canonical rule `review-report-only`, 5 carriers): both
former write edges end at the delivery node `RD`, an unmet review/security_audit criterion goes to
the stop-and-ask node `XR`, and the findings leave as a report plus a generated follow-up task file
(`.code-factory/review/fix-tasks.yaml`); model precedence is stated once and implemented once
(`scripts/model_matrix.py`: the task's matrix wins verbatim and a family collision is only a
warning, an unnamed role takes the factory's default matrix where generator≠judge is enforced, the
committee's second planner is the only override), and the models actually served are confirmed from
the CLI session wire (`scripts/model_attribution.py`, match/mismatch/degraded); the memory has ONE
contract (`memory_project.validate_memory`, `check_factory_model` delegates), an ownership identity
from the repository root commit (`project_id`, so a rename or a copy keeps it valid), exactly one
record per run (`check --run-id`), a real 50/20 `compact` that survives a second fold, carry-over
with a reason that the finish gate accepts while a disappeared item still fails, and an actual
`## Current state` (version, open/closed counts, test count — strict under `--run-id`); the
precedent index is a build product of the flow (`build`/`status`/`query --fresh`); the English-only
gate acts on new memory records (history frozen in `memory/.english-freeze`) and on this summary.
Previous runs: review 20261025-634bc01b (report-only, 20 findings), review 20261025-d412a454
(18 findings — a review run was NOT report-only then), review 20261025-a32464ec (not accepted; its
unrequested 18-file rework was rolled back).
Version type: the deterministic matrix proposed `patch`; the code reviewer overrode it to `minor`
because a new canonical rule, two flow nodes, three scripts, a summary field and a record kind are
additive, not breaking.
Open backlog: 1 item (47 closed with evidence) — the `test_run_id.py` fixture digest depends on the
checkout's line endings (a pre-existing brittleness exposed by this release; normalizing CRLF in
`run_id` would change every historical run id, so it needs its own vaccination-first task).
Rulebook: 26 rules, 105 carriers, byte-identical (`check_factory_rules.py` exit 0). Memory owner:
repo, declared with `project_id` (the repository identity, not the folder name). Self-tests: 38
files, all passing — including 24 registered vaccines that each fail on the pre-fix tree and pass
here (`scripts/test_vaccination.py`).

## Key decisions
- The long-term memory `memory/` belongs to ONE target project (`repo_path`); the field
  `project:` is mandatory for new records, different values of it in one journal are an error,
  legacy records without `project:` are a warning. The factory's own development history never
  goes into the target project's memory.
- The memory is created at the DEPLOYMENT ROOT (the directory passed to `prepare_factory.sh`), the
  project name = the basename of the resolved `repo_path`; when `repo_path` points to a
  subdirectory, the agent passes `--project` explicitly and the name is pinned in the summary
  declaration.
- An existing AGENTS.md is overwritten as a whole (exactly 8 sections); hand-written notes live in
  `memory/summary.md`.
- The fingerprint does NOT include the git tree SHA (otherwise the embedded fingerprint goes stale
  immediately after the commit that commits it).
- The journal's compaction threshold is 50 records (the last 20 are kept); at compaction the
  `unfinished` items with severity=critical or follow_up=true are preserved without fail.
- The factory's own root AGENTS.md stays a hand-authored instruction (not the 8-section model).
- `VERSION` is the single source of truth of the version; the version type is decided by a
  deterministic matrix and validated by the reviewer (which may override it with an explanation);
  review/security_audit do not change the version.
- The documenter updates only doc comments and `.md` files (secondary model, validator, budget 1).

## Recent history
- 2026-10-25 — "Review of the long-term memory (20261025-634bc01b)" (main, d87592a, report-only):
  P1-P5 and M1-M8 plus owner-raised M9, each with a command, an exit code and an artifact; 20
  findings (2 critical, 11 major, 7 minor); 30/30 quotations verified; no product change, no
  version bump, 8 backlog items carried, 2 added. Established: the memory data is real and the
  gate is red (owner `repo` vs the pinned basename); the two validators disagree on six axes; the
  Finish node's `backlog --check` exit 0 cannot coexist with the carry-over branch; compaction is
  prose plus a manual post-hoc check; the precedent index is built by no flow node and is stale;
  and the model-precedence conflict let a live run override the task's reviewer model — the task
  is authoritative from now on.
- 2026-10-25 — "Review of the review flow (20261025-d412a454)" (main, d87592a, report-only): traced
  every edge out of a review verdict in the SKILL.md flowchart by graph walk — the review verdict
  leads into the implement entry (CRV0 -> G, SKILL.md:102) and the acceptance-failure edge
  (X|No -> RR -> coder, SKILL.md:164) reaches a coder for every task type, security_audit included;
  the read-only guarantee exists once and belongs to security_audit; the acceptance contract permits
  a review criterion only a code change can satisfy, and no self-test or rulebook rule pins the
  routing (0 tests name CRV0; 25 rules, none covers a report-only review). 18 findings
  (3 critical, 8 major, 4 minor, 3 nit), 35/35 quotations verified. No product change, no version
  bump, 6 backlog items carried with reasons.
- 2026-10-25 — "Review of the long-term memory mechanism (20261025-a32464ec)" (main, d87592a,
  report-only): 21 findings; the flow's review-to-implement edge produced an unrequested 18-file
  rework that the owner stopped and rolled back. Established the memory findings still open today
  (owner mismatch, `task_type: backlog` half-acceptance, Finish-vs-actuality, unwired compaction).
- 2026-09-24 — "Factory v9 (v12.12.1)" (factory/v9-review-rework, 2f53d2f): v8 review rework —
  deleted no-skeleton files now fail the translation-structure gate (vaccination test first),
  security-auditor severity mapping aligned to §5.1, ps1 old-git fallback + last-line failure
  reason, skill_base utf8-guard + usage fix, README tree fix, nit annotation; backlog 2 → 0.
  v12.12.0 → v12.12.1 (patch).
- 2026-09-24 — "Factory v7 (v12.12.0)" (factory/v7-english-only, c891a67): full RU→EN translation
  of the factory (freeze-functionality refactor; 46 files); 24th rule english-only (8 carriers);
  quality gates — glossary, check_english_only.py, check_translation_structure.py, 6-shard
  semantic audit (approve); test_run_id digest re-pinned; wave P outer-tree mistake reverted and
  redone. v12.11.0 → v12.12.0 (minor).
- 2026-09-24 — "Factory v6 (v12.11.0)" (feature/factory-v6-backlog-20260923, 4b6652c):
  full cleanup of the backlog across the whole history (32 follow_up → 0 open, all with evidence);
  explicit classification of git stash (mutating → CONFIRM, list/show → ALLOW, parsing of
  -m/--message); content fingerprint over the working tree (unstaged edits visible); the memory
  actuality mechanism (backlog --check + closed:+evidence: + the 23rd rule memory-actuality, a
  5-link RCA); project-learned overlay §1.2; ps1 try/catch, sh short reason, .gitattributes *.sh LF;
  providers.md §5.2. Plan committee (3 rejections → merged + the user's choice). v12.10.2 → v12.11.0 (minor).
- 2026-09-23 — "Factory v5 (v12.10.2)" (feature/factory-v5-backlog-20260923, ed62e88):
  utf8-guard in every argparse script (action_gate --help on cp1251, case 16), the 22nd rule
  no-shared-tree-git-mutations (6 carriers). v12.10.1 → v12.10.2 (patch).
- 2026-09-23 — "Factory v3 (v12.10.0)" (feature/factory-v3-backlog-20260923, 3e1a1bb):
  reviewer severity calibration (precision 0.619→0.857, recall→1.000, accuracy 7/7), committee
  on a double plan rejection (plan-committee + plan_arbiter.py + factory-planner),
  check_factory_model SKIP at the factory root (three-signal detector), FTS5 precedent_index.py,
  test_run_id re-pinned to the fixture. v12.9.1 → v12.10.0 (minor).
- 2026-09-21 — "Deploying and launching the factory on Windows" (feature/windows-launch, 37a683e):
  the Windows versions of both operations (`prepare_factory.ps1` + `prepare_factory.cmd`, `start.cmd`),
  parity with the bash path, a hard deployment failure → exit 1 without the "Done" banner (expected
  degradations stayed non-fatal), UTF-8/BOM/CRLF contracts, the self-test
  `scripts/test_windows_scripts.py`. v12.6.0 → v12.7.0 (minor).
- 2026-09-21 — "The factory's memory belongs to the target project" (feature/project-scoped-memory):
  the `project:` field in records and the project declaration in the summary, detection of mixed
  projects, the `memory_project.py` script, initialization of the project's memory at deployment,
  cleanup of the get_course_downloader project's memory from the factory's development history.
  v12.5.1 → v12.6.0 (minor).
- 2026-09-08 — "Factory v12.5.0" (feature/factory-v12.5.0, 123acf3): factory-documenter,
  the unfinished memory section, reference_docs/reference_skills + skill-base, end-to-end
  versioning.
- 2026-09-01 — "AGENTS.md as the single source of truth + portable memory" (main, a53ef72):
  Scout without `/init`, fingerprint, `memory/`, the model-check scripts, subagents read
  AGENTS.md/memory as the source of truth.

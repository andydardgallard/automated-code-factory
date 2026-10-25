<!-- code-factory-version: 12.15.0 -->
# Project: Autonomous Code Factory

This project contains an autonomous code-writing factory for the Kimi Code CLI.
The factory takes a business task from a non-technical user, analyzes the project, plans
changes, clarifies only business logic, gets the plan approved, implements the code, and runs
integration / regression / business tests with automatic rollback on failure, performing a
mandatory code review before acceptance.

## Structure

- `.example.task.yaml` — the committed example business task (format reference); a working
  `task.yaml` is per-run, gitignored and never shipped
- `.agents/skills/code-factory/` — the factory's flow skill (`SKILL.md`), references
  (`references/`: planning-guide, verification-strategy, error-routing, tech-stack-detection,
  code-review, providers, refactoring, security-audit, handoff-briefing — the mandatory
  subagent briefing template; `factory-rules.md` — the single rulebook of mandatory rules whose
  carriers are reconciled by `check_factory_rules.py`; `error-patterns.default.json` — the machine snapshot of the
  error-routing tables for `error_router.py`), and the task template (`assets/`)
- `.agents/skills/code-factory/scripts/` — deterministic stdlib scripts (0 tokens):
  `repo_inventory.py` (inventory + shards ≤20k lines), `merge_findings.py` (merging shard
  findings + merged verdict), `verify_acceptance.py` (criteria with `verify` → acceptance.md),
  `verify_quotes.py` (verbatim quote check), `evidence_ledger.py` (FRESH/STALE signatures),
  `factory_preflight.py` (environment probe), `action_gate.py` (destructive actions),
  `task_graph.py` (on-disk task graph), `log_tail.py` (tail of a long log), `repo_stats.py`
  (code-based analyses), `project_fingerprint.py`, `memory_project.py`, `version_manager.py`,
  `check_factory_rules.py` (reconciling the rulebook with its carriers: `factory-rule` blocks byte-for-byte),
  `check_english_only.py` (English-only gate over what the repository ships (`git ls-files`, like
  `project_fingerprint.py`): fails on any Cyrillic left outside the exceptions `CHANGELOG.md`,
  `memory/`, `task*.yaml`, `.code-factory/`, `.git/` — with `memory/` exempt as HISTORY only: the
  memory pass runs by default over the v2 records that are not listed in `memory/.english-freeze`
  and over `memory/summary.md` whole, and `--no-memory` is its one documented escape),
  `check_translation_structure.py` (translation skeleton comparator: a translated file may change its
  text, never its structure — headings, list items, code fences, `factory-rule` markers, definitions,
  CLI arguments; `--allow-added-rule <id>` admits a deliberately added rulebook rule),
  `run_id.py` (the run's run_id: `gen` from task.yaml / `check` — artifacts without run_id),
  `error_router.py` (JSON-first error classification: `classify`/`merge`),
  `calibrate_reviewer.py` (reviewer golden-set calibration: precision/recall/accuracy),
  `model_matrix.py` (the single model-precedence resolver: the task matrix used verbatim, the
  default matrix where the generator≠judge rule is enforced, the family check and the committee's
  contrasting second planner), `model_attribution.py` (artifact-backed model attribution: reads the
  CLI session wire and cross-checks `models_used` — a mismatch FAILS the run, a missing wire is
  DEGRADED), `review_followup_task.py` (deterministic review follow-up task generator: the merged
  findings → `.code-factory/review/fix-tasks.yaml`),
  `plan_arbiter.py` (deterministic merge of two competing plans + list of discrepancies —
  committee on double plan rejection), `precedent_index.py` (FTS5 precedent index over memory +
  codebase: `build`/`status`/`query`, with `status` reporting FRESH/STALE and `query --fresh`
  refusing a stale index instead of answering from it),
  `chrome_devtools_mcp.py` (conditional Web GUI browser path: applicability `decide`, existing
  E2E-stack discovery, browser matrix, vendored pinned install (`vendor-install`) + idempotent merge
  of the node-direct `chrome-devtools` server into `.kimi-code/mcp.json`, fail-soft capability probe).
  Self-tests pin these contracts: `test_model_precedence.py`, `test_model_attribution.py` and
  `test_review_followup_task.py` cover the three scripts above; `test_review_report_only.py` pins
  the report-only review routing, `test_security_audit_guarantee.py` pins the audit's guarantee,
  `test_flow_contracts.py` pins the wiring that lives in prose, and `test_vaccination.py` proves
  every fix of this release bites (its check fails on the pre-fix tree).
  Every argparse script reconfigures stdout/stderr to UTF-8 itself (`stream.reconfigure(encoding="utf-8",
  errors="replace")` under try/except), so `--help` and error messages with non-ASCII characters
  do not crash with `UnicodeEncodeError` on a console with a legacy code page (cp1251/cp866); the argparse
  contract is unchanged: `--help` → exit 0, usage error → exit 2, no traceback.
- `.agents/agents/` — the factory's main agent (Markdown `code-factory.md`) and subagents
  (`sub-agents/analyzer|planner|coder|gui-expert|tester|diagnostician|advisor|code-reviewer|refactorer|security-auditor|documenter|skill-manager.md`)
- `VERSION` — single source of truth for the factory version (one line X.Y.Z)
- `skill-base/` — persistent skill base from `reference_docs`/`reference_skills` (optional)
- `.agents/README.md` — the full factory usage manual
- `prepare_factory.sh` — one-action project preparation (creates the `start.sh` launcher)
- `prepare_factory.cmd` / `prepare_factory.ps1` — the same on Windows without Git Bash (entry point
  and implementation; they create the `start.cmd` launcher), `start.cmd` — launching the factory on Windows
- `memory/` — portable long-term memory of the TARGET project (committed); created AT THE
  DEPLOYMENT ROOT (the directory passed to `prepare_factory.sh`; on Windows —
  `prepare_factory.cmd`); base project name = basename of that directory: `change-log.md`
  (append-only run journal) and `summary.md` (condensed summary); the project marker — `project: <name>`
  in an entry and `project:`/`repo_path:` in the summary

## How to use

- Kimi Code 0.34+: `kimi`, then `/skill:code-factory`; or
  `kimi --agent-file .agents/agents/code-factory.md "task"`
- Full automation: `kimi --auto` → `/skill:code-factory`
- **One action**: `./prepare_factory.sh <project>` then `./<project>/start.sh` (the launcher
  sets `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` itself)
- **One action on Windows**: `prepare_factory.cmd <project>` then `cd <project>` and `start.cmd`
  (interactive; `/skill:code-factory` in the chat) or `start.cmd --auto` — no Git Bash needed; deployment
  does not require Python (the factory itself uses Python for the memory and version scripts)
- `mode: auto` in `task.yaml` controls only the factory's business questions; CLI permission
  prompts are disabled separately — via the `kimi --auto`/`--yolo` flag or `default_permission_mode`
  in `config.toml`.

## Conventions

- The factory's runtime state — `.code-factory/` (do not commit) — lives at the ROOT of the
  RESOLVED `repo_path`: the task's `repo_path` is resolved ONCE to an absolute path (relative to the
  launch directory) at the start of the run, and it is that resolved root (not the launch directory)
  which holds `.code-factory/`; every relative artifact path in these conventions is relative to it:
  `state/` (task, plan, pipeline.yaml, acceptance.md, evidence ledger, task graph),
  `logs/` (baseline, errors, results, code-review, shard findings),
  `backups/`, `manifest.json`.
  `state/precedents.db` is the FTS5 precedent index — a BUILD PRODUCT, not standing runtime state:
  the flow builds it at analysis time (`precedent_index.py build`), it is gitignored with the rest of
  `.code-factory/`, `precedent_index.py status` reports FRESH/STALE against the journal and the tree,
  and `query --fresh` refuses a stale index instead of answering from it.
- **AGENTS.md — single source of truth**: the factory generates it with exactly 8 `##` sections and a
  deterministic TWO-LEVEL fingerprint in the first line — structural (stack manifests,
  CI configs, README, directory list) + content (SHA-256 of the contents of tracked working-tree
  files, CRLF→LF) —
  `scripts/project_fingerprint.py --all`, marker
  `<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->`. It regenerates when EITHER
  of the two hashes diverges (start of a task) or when the structure/stack/entry points change (end of a task),
  and commits (with no separate Kimi init step); the "SKIP regeneration" branch is allowed ONLY when
  BOTH hashes match — a match of the structural level alone is not enough (changes deeper
  than the first level are seen by the content hash). The content hash is computed over the `git ls-files` working tree,
  so unstaged edits are visible to it; untracked files stay outside the hash — the factory
  warns about this rather than staying silent: `--content`/`--all` print a stderr note,
  `check_factory_model.py` prints a warning (hashes and exit codes do not change; `git add` brings an
  untracked file into the hash). Subagents read AGENTS.md instead of re-deriving the structure.
- **Long-term memory `memory/`** (committed, not ignored) — the memory of THE project named
  in the task's `repo_path` (for this repository the target project is the factory itself), not the factory's
  memory: one memory belongs to exactly one project. The `memory/` directory lives AT THE
  DEPLOYMENT ROOT — the one passed to `prepare_factory.sh`; the base project name at deployment =
  basename of that directory. When the task's `repo_path` points to a SUBDIRECTORY of the deployment root,
  the main agent creates the memory explicitly, naming the project: `memory_project.py init --repo <deployment
  root> --project <basename of the resolved repo_path>`, and the name is fixed in the summary's
  `project:` declaration. Every journal entry carries the `project: <project name>` marker, mandatory for NEW entries
  (the same name declared in the summary); the `summary.md` summary declares the project
  with `project:`/`repo_path:` lines right after the canonical marker. Entries without `project:` are legacy
  (warning); entries from different projects in one journal are an error (`check_factory_model.py`,
  `memory_project.py check`). The only writer is the main agent (one `change-log.md` entry
  per run, compaction into `summary.md` at the 50-entry threshold — the last 20 entries stay, and the
  flow invokes `memory_project.py compact` for it); it is read at the start of a task and by roles as
  needed. If `memory/` is missing (first access to the project), the factory creates it with the same
  `init` command with `--project <name>`. The factory's own development history NEVER enters the target
  project's memory. Model check — `scripts/check_factory_model.py`, whose memory validation is a thin
  delegation to `memory_project.validate_memory`, so there is ONE memory contract rather than two.
<!-- factory-rule: memory-ownership begin -->
**Memory ownership (canonical wording):** one memory belongs to exactly one project — the one named in the task's `repo_path`. The `memory/` directory lives at the DEPLOYMENT ROOT; the summary declares `project: <name>` (the project's name) and `project_id: <identity>`, where the identity is the first 12 hex characters of the sha256 of the repository's root commit, so renaming the folder or taking a versioned copy never invalidates the memory and a memory of a different repository is refused. A memory that declares no `project_id` falls back to the deployment-root basename, which is only a fallback and says so. The only writer is the main agent: exactly one entry in `memory/change-log.md` per run (`run_id`-addressed; a run with no record or with two records is an error), compaction into `memory/summary.md` at the 50-entry threshold (the last 20 remain, severity=critical and follow_up=true items always survive, and the flow invokes `memory_project.py compact`). Entries from different projects in one journal are an error (`check_factory_model.py`, `memory_project.py check`), entries without `project:` are legacy (a warning, not an error). The development history of the factory itself never enters the target project's memory.
<!-- factory-rule: memory-ownership end -->
<!-- factory-rule: memory-provenance begin -->
**Memory entry provenance (canonical wording):** an entry counts as a v2-format entry if its `factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a provenance marker) — so a half-migrated entry is checked too; such an entry must carry a `run_id` in the format `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) and provenance markers in the `decisions` and `results` fields: `[verified: <evidence>]` — the claim is confirmed by run evidence (log, acceptance, quote), `[inferred]` — an inference without direct evidence. A v2-format entry without a `run_id` or without markers in these fields is a format error (`memory_project.py check`, `check_factory_model.py`), whereas entries written by a factory no newer than 12.8.0 and carrying no v2 fields, and legacy entries without `project:`, yield only a warning. The `[verified: ...]` marker must reference concrete evidence (command/test/log); the validators check the marker's presence and form.
<!-- factory-rule: memory-provenance end -->
<!-- factory-rule: memory-actuality begin -->
**Memory actuality (canonical wording):** at the start of a run the open backlog is reconciled with the tree (`memory_project.py backlog --repo <root>`, a fold of every follow_up=true/severity=critical item over the journal history); at the end of a run each item is either closed with a `closed:` block carrying a mandatory `evidence:` in the run entry, or carried in `unfinished` with a `reason:` — a carried item is legal and the finish gate accepts it, while an item mentioned in no current record is a fatal silent disappearance, so `backlog --check` exits 1 for a disappeared item, a carried item without a reason, a closing without `evidence:` and a closing that names no existing item, and exits 0 when nothing disappeared. `memory_project.py check --run-id <run_id>` is the finish command: it requires exactly one record for the run. The summary's `## Current state` is actualized by EVERY run, not only at compaction — its version, open-backlog and closed counts and test-file count are compared with reality (`--strict`, implied by `--run-id`, turns a divergence into an error; a plain check reports it as a warning).
<!-- factory-rule: memory-actuality end -->
- **run_id and WIP checkpoint**: `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>` is computed at the start
  of a run (`run_id.py gen --task .code-factory/state/task.yaml`) and stamped into `pipeline.yaml`,
  `acceptance.md`, `logs/*.md`, `report.md`, and the memory entry; `run_id.py check --dir .code-factory`
  lists the run's artifacts without a `run_id`. The `pipeline.yaml` checkpoint carries the required keys
  `run_id`, `phase`, `status` (`ok|failed|in_progress`), `updated_at`, and the optional
  `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`, `models_used`; checked by
  `scripts/check_factory_model.py` (missing file — SKIP). A v2 memory entry carries a `run_id` and
  provenance markers `[verified: <evidence>]`/`[inferred]` in `decisions` and `results`.

- Communication with the user — business language only.
<!-- factory-rule: english-only begin -->
**English-only (canonical wording):** every artifact the factory produces is written in English only: code and comments of target projects, documentation, docstrings, commit messages, reports (`.code-factory/report*.md`, logs), memory entries, plans and subagent briefings. The factory accepts a task file in any language, but everything it produces from it is English. EXCEPTION: live communication with the user stays in the user's business language, and HISTORY is never rewritten — `CHANGELOG.md` and memory records written before this rule are frozen by `memory/.english-freeze` (one record heading per line) and are never edited; every NEW memory record is gated by `scripts/check_english_only.py`, whose memory pass runs by default over v2 records that are not frozen (`--no-memory` is the one documented escape).
<!-- factory-rule: english-only end -->
- **Artifacts before changes**: before editing any source file, `.code-factory/` must already
  contain `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
<!-- factory-rule: artifacts-first begin -->
**Artifacts before changes (canonical wording):** the factory edits no source file until `.code-factory/` already holds `state/task.yaml` (the parsed task), `state/plan.md` (the plan), `logs/baseline.md` (the baseline test run), `backups/` (a backup of every file that will be changed, relative paths preserved) and `manifest.json` (the changed and created files). The run state lives on disk, not in the conversation: non-persistent knowledge is lost on restart and makes rollback impossible.
<!-- factory-rule: artifacts-first end -->
<!-- factory-rule: run-id begin -->
**Run identifier (canonical wording):** at the start of a run `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` is computed deterministically (`scripts/run_id.py`) and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` and the run's memory entry. One run — one identifier; it links the artifacts to each other. `scripts/run_id.py check` finds the run's artifacts without a `run_id` and lists them.
<!-- factory-rule: run-id end -->

- **Repo gate**: if the task references files/symbols/configs missing from the repository —
  in hitl mode stop and ask the user; in auto mode record an assumption.
- **Error routing**: deterministic regex → Diagnostician (LLM) → Advisor (secondary,
  a family contrasting with the diagnostician, budget 1) → Human → FAILED; retries per role budgets
  (coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2).
<!-- factory-rule: retry-budgets begin -->
**Retry budgets (canonical wording):** every role has its own retry budget — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; the counters are kept in `.code-factory/state/pipeline.yaml` (`retry_counters`). An exhausted budget is not extended: the run escalates along the ladder deterministic regex → Diagnostician (LLM) → Advisor (LLM, secondary model, contrasting model family, budget 1) → Human (hitl) → FAILED with the full log. The factory does not loop, does not soften tests for a green run and does not fail silently.
<!-- factory-rule: retry-budgets end -->

- **Code review**: every task passes through the `factory-code-reviewer` subagent before
  acceptance. A regular task — a review of the changes diff; `task_type: review` and `security_audit` —
  a review/audit of all the code in SHARDS (`repo_inventory.py shards --tracked --max-lines 20000`
  over the TRACKED tree; `inventory --tracked` prints the same file set → parallel
  subagents per shard → `merge_findings.py` produces a deterministic merged verdict). A
  `task_type: review` run is report-only (`review-report-only`): its deliverable is the report
  (`.code-factory/logs/code-review.md` + `.code-factory/report.md`) plus the generated follow-up task
  file `.code-factory/review/fix-tasks.yaml` (`review_followup_task.py`) that the owner runs later as
  a separate `implement` task — the findings never become this run's plan, a review criterion that is
  not MET stops the run and asks the owner, and because nothing is edited every `verify:` criterion of
  a review task must be satisfiable on the unmodified tree; `security_audit` keeps its own guarantee
  (reports + a fix-task file, no auto-fixing). The critical/major boundary is set by `references/code-review.md` §3
  (critical — EXISTING behavior is damaged; major — a NEW path left unprotected or lost
  coverage), and §7 makes reviewer calibration on the golden set periodic: after every edit
  of the reviewer prompt and at least once per 5 review runs (`scripts/calibrate_reviewer.py`;
  soft thresholds — verdict accuracy 100%, macro precision ≥ 0.8).
<!-- factory-rule: vaccination begin -->
**Vaccination (canonical wording):** a bug found AFTER the task's acceptance first gets a regression test that reproduces it (the test fails on the current code), and only then the fix. A fix without a reproducing test is not accepted, and the test itself stays in the suite as a vaccine against recurrence. The code reviewer checks that every post-acceptance fix has such a test and counts its absence as a finding of severity ≥ major.
<!-- factory-rule: vaccination end -->

<!-- factory-rule: review-gate-policy begin -->
**Review gate (canonical wording):** a task is NOT accepted while the reviewer has open severity=critical findings (verdict `request_changes` with open critical findings). The reviewer budget = 2 iterations. If the budget is exhausted and critical findings remain: in hitl mode the factory STOPS and asks the user; in auto mode only a conditional pass is allowed — the corresponding criterion is marked `unverified_review` in `.code-factory/state/acceptance.md`, and the unresolved findings go into `.code-factory/report.md` (unresolved findings section), never silently. A full SUCCESS with open critical findings is impossible. For a `task_type: review` run the gate judges the delivered review, not the reviewed code: the verdict stays `request_changes` in `results.review=` while the run's own acceptance records whether the report and the follow-up task file were produced.
<!-- factory-rule: review-gate-policy end -->
<!-- factory-rule: review-report-only begin -->
**Report-only review (canonical wording):** a `task_type: review` run never edits the project: no review verdict, in either mode, reaches a node that starts a coder, writes a backup or changes a tracked source, test, config, documentation or data file — the run's own `.code-factory/` artifacts and its single `memory/` record are the only writes. The deliverable is the report (`.code-factory/logs/code-review.md` + `.code-factory/report.md`) plus a generated follow-up task file (`.code-factory/review/fix-tasks.yaml`, produced by `scripts/review_followup_task.py`) that the owner runs later as a separate `implement` task; the findings never become this run's plan. A review criterion that is not MET stops the run and asks the owner — it is never routed into error routing's coder branch — and because the run changes nothing, every `verify:` criterion of a review task must be satisfiable on the unmodified tree: a criterion that needs a change is an authoring error the run reports. A review run's acceptance judges the delivered report, while the verdict on the reviewed code stays recorded as `results.review=`; the two facts are never conflated. `security_audit` keeps its own guarantee (reports plus a fix-task file, no auto-fixing) unchanged, and this rule does not restate it.
<!-- factory-rule: review-report-only end -->
<!-- factory-rule: shard-protocol begin -->
**Shard protocol (canonical wording):** whole-repo review and security_audit never fit into one context: `scripts/repo_inventory.py shards --tracked --max-lines 20000` cuts the TRACKED tree (`git ls-files -z` at `--repo`, so an untracked or ignored machine-local file stays out of the review) into shards of ≤20000 lines, each shard is processed by its own parallel subagent (reviewer or auditor) and writes one findings file. The result is produced by the deterministic `scripts/merge_findings.py` (deduplication, sorting by severity, merged verdict), and the canonical review gate is applied to the MERGED findings, not to individual shards. A regular `implement` task is reviewed by diff and needs no sharding.
<!-- factory-rule: shard-protocol end -->

- **Verified acceptance**: criteria with `verify` are executed for real (`scripts/verify_acceptance.py`
  → `.code-factory/state/acceptance.md`; exit 0 only on SUCCESS — at least one criterion with
  `verify`, all MET, baseline proven), and evidence carries FRESH/STALE signatures
  (`scripts/evidence_ledger.py`): a green log from a stale revision does not count as acceptance.
<!-- factory-rule: verified-acceptance begin -->
**Verified acceptance (canonical wording):** acceptance is machine-verifiable — `scripts/verify_acceptance.py` actually executes the criteria with `verify` and writes exit codes and output excerpts into `.code-factory/state/acceptance.md`. Exit 0 is possible only on SUCCESS: at least one criterion with `verify`, all criteria MET, baseline proven; criteria without `verify` are marked `derived`/`unverified` and are not evidence. STALE evidence or a degraded baseline lowers the verdict to DEGRADED; SUCCESS without regression evidence is impossible.
<!-- factory-rule: verified-acceptance end -->
<!-- factory-rule: evidence-ledger begin -->
**Evidence ledger and quotes (canonical wording):** every piece of evidence (baseline, tests, review) is signed with the working-tree fingerprint via `scripts/evidence_ledger.py` and is accepted only with FRESH status; STALE evidence (files changed after signing) does not count as acceptance. Every quote from the reviewer, diagnostician or advisor is re-checked verbatim by `scripts/verify_quotes.py` (exact substring, only CRLF→LF is normalized). An unconfirmed quote is marked UNTRUSTED and does not affect the verdict.
<!-- factory-rule: evidence-ledger end -->

- **Briefing for every delegation**: the subagent receives a self-contained briefing per
  `.agents/skills/code-factory/references/handoff-briefing.md` — Task / Context / relevant
  files BY PATH (without inlining their contents) / what has already been tried and why it failed; only the main agent writes
  files; read-only roles carry the "no edits" suffix.
<!-- factory-rule: handoff-briefing begin -->
**Briefing of every delegation (canonical wording):** every delegation to a subagent is a self-contained briefing per `references/handoff-briefing.md` (Task / Context / relevant files BY PATH, without inlining their contents / what has already been tried and why it failed / the MEMORY FACTS: the open backlog items that touch this work and the relevant past decisions read from `memory/summary.md` and the journal, so a subagent never re-derives the project's history). Only the main agent writes files; read-only roles (analyzer, reviewer, security-auditor, diagnostician, advisor) carry the "no edits" suffix. The subagent returns a compact structured result with paths to artifacts, not a retelling of the context.
<!-- factory-rule: handoff-briefing end -->
<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

- **Task format**: `title`, `repo_path`, `description`, optional `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`
  (a criterion may optionally carry `verify: <command>` and `derived: true`), `business_tests`
  (scenario/configs/expected business results), `commit_exclude`, `models`.
  There is no `priority` field — all tasks are high by default.
<!-- factory-rule: task-format begin -->
**Task format (canonical wording):** a task carries `title`, `repo_path`, `description`, optionally `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (a criterion may carry `verify: <command>` and `derived: true`), `business_tests` (scenario, configs, expected business results), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. `repo_path` is REQUIRED for every task except a green-field one (a brand-new project created in place) and is always resolved ONCE to an absolute path at the start of the run. There is NO `priority` field — all tasks are high by default, the factory does not prioritize them. A missing required field is a task parsing error, not a reason to guess it mid-run.
<!-- factory-rule: task-format end -->

- **User story**: when `user_story` is present, the factory analyzes and uses it at the
  analysis, planning, and implementation stages (by all agents).
- **Plan approval (hitl)**: the first plan rejection sends it back for revision; the second
  is a double rejection: a second independent planner subagent is launched (from a contrasting model
  family), and `scripts/plan_arbiter.py` deterministically merges both plans and prints a list of
  discrepancies; the user is shown the merged plan, and further edits are made against it.
<!-- factory-rule: plan-committee begin -->
**Committee on double plan rejection (canonical wording):** if the user rejected the plan twice (hitl, Revise branch), the main agent launches a second independent planner subagent from a contrasting model family, which builds an alternative plan from the same task and the user's accumulated remarks; the deterministic `scripts/plan_arbiter.py` (stdlib) compares both plans by machine-readable sections (DAG tasks, verify commands, risks, business tests) and forms a merged variant with a list of discrepancies; the user is presented with the merged plan and the discrepancies, and further edits are made against it.
<!-- factory-rule: plan-committee end -->
- **`task_type: refactor`** — the freeze-functionality invariant: 100% of the existing tests pass
  unchanged; any behavior change is a critical error and an automatic rollback.
- **`task_type: security_audit`** — adaptive full audit (no live network scanning or
  pentesting); the result is reports + a fix-task file; the factory does NOT fix vulnerabilities itself.
- **Git-native**: if there is no git repository — `git init`; changes go through git
  (a feature branch per task), rollback to the base commit on failure.
<!-- factory-rule: git-native begin -->
**Git-native (canonical wording):** if the target repository has no git repository, the factory runs `git -C <resolved repo_path> init` — there is no separate init step in the CLI. EVERY git operation of the run targets the resolved repo_path — executed as `git -C <resolved repo_path>` (or with the cwd set to it): the init check, the feature branch created per task, the recording of the base commit and its HEAD in `<repo>/.code-factory/state/`, the commits, and the rollback to the base commit on failure. The working tree of the TARGET repository is kept clean: build artifacts are auto-untracked, factory artifacts are committed; a run never touches the factory's own deployment `.git`.
<!-- factory-rule: git-native end -->
<!-- factory-rule: repo-scoping begin -->
**Repo-path scoping (canonical wording):** at the start of a run the factory resolves the task's `repo_path` ONCE to an absolute path (relative to the launch directory) and then performs EVERYTHING relative to that resolved target repository: the `.code-factory/` artifact tree (`state/`, `logs/`, `backups/`, `manifest.json`, reports), backups, git operations (`git -C <repo>` or an explicit cwd), source edits and rollback. The documented exceptions that stay DEPLOYMENT-ROOT-scoped are `memory/` (the long-term memory lives at the deployment root) and `scripts/version_manager.py` (`VERSION` lives at the deployment root) — they receive their root explicitly, never a silent default to the launch directory.
<!-- factory-rule: repo-scoping end -->

- **Models**: models are set in `config.toml` (`default_model` + `[secondary_model]`);
  for subagents — `model_preference: primary|secondary`. Actual models are logged in
  `pipeline.yaml`/`report.md` (`models_used`). Model splitting requires
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — the `start.sh`/`start.cmd` launcher sets it itself; the factory
  checks it in pre-flight and, if missing, writes `models_warning` to pipeline.yaml/report.md.
  Kimi (K3) and Qwen models are routed via the task's `models` field (see
  `references/providers.md`).
<!-- factory-rule: models-generator-ne-judge begin -->
**Models: task first, then the default matrix (canonical wording):** exactly two cases and no third. (a) When the task's `models:` matrix names a role, that exact model is used and is NEVER substituted: a generator/judge family collision is a WARNING naming both roles and both models, never a reason to swap. (b) When the task does not name the role, its model comes from the factory's DEFAULT MATRIX — the CLI config's `default_model` / `[secondary_model] default_model` selected by the role's `model_preference` — where the generator≠judge rule IS enforced: a same-family coder/tester/gui_expert versus reviewer/diagnostician/advisor pair with either side taken from the default matrix is an ERROR naming the fix (widen `[secondary_model]` or pin `models.<role>` in the task). (c) There is no third path: the main agent never picks a model on its own. The ONE exception is the plan committee's second planner, which always comes from a family contrasting the first planner. `scripts/model_matrix.py` is the single implementation of this precedence, `scripts/test_model_precedence.py` pins it, and the model actually served is confirmed by an ARTIFACT: `scripts/model_attribution.py` reads the CLI session wire and cross-checks `models_used`, a mismatch fails the run, and a missing wire is DEGRADED — never silently green. The secondary model works only with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`; otherwise the factory writes `models_warning` and continues on the primary. The actual role models are logged in `.code-factory/state/pipeline.yaml` (`models_used`) and in `report.md`.
<!-- factory-rule: models-generator-ne-judge end -->

- **Reports**: `report.md` (run history) + `report_code_changes.md` (before→after diff)
  are generated automatically in `.code-factory/` on completion.
- **Commits**: the task's `commit_exclude` field excludes files from the git commit
  (for example, a personal strategy); the core and documentation are committed.
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (canonical wording):** files matching the task's `commit_exclude` patterns are NEVER committed — in no commit of the run, including the version and memory commit. Everything except the excluded patterns is staged; the code reviewer checks commit hygiene and counts an excluded file landing in the index as a finding of severity ≥ major.
<!-- factory-rule: commit-exclude end -->

- When factory files change, update `.agents/README.md` and these instructions.
- **Documentation**: after every successful implement/refactor, the
  `factory-documenter` subagent (secondary) is invoked — it updates only doc comments and `.md` files; validator
  `validate_documentation.py` with a budget of 1 retry; not invoked for review/security_audit.
<!-- factory-rule: documentation begin -->
**Documentation (canonical wording):** after every successful `implement`/`refactor` the main agent invokes the `factory-documenter` subagent (secondary) with the run's manifest; it updates ONLY doc comments and `.md` files and never code, tests or configs. It validates its work with `scripts/validate_documentation.py` with a budget of 1 retry; when the budget is exhausted, the documentation debt is recorded in the run report and the factory continues. Documentation is not invoked for `review`/`security_audit`.
<!-- factory-rule: documentation end -->

- **Version**: `VERSION` is the single source of truth; the version type is determined by a deterministic
  matrix, validated by the code reviewer (may override with an explanation), applied by
  `version_manager.py`; review/security_audit do not change the version.
<!-- factory-rule: versioning begin -->
**Versioning (canonical wording):** `VERSION` (one line `X.Y.Z`) is the single source of truth, all other files are synced FROM it via `scripts/version_manager.py`. The version type is suggested by a deterministic matrix (`suggest`), validated by the code reviewer (may override with an explanation, but does not choose from scratch), applied by `bump`/`set` + `sync` + `validate` exit 0. The version commit goes in ONE commit with the changes and carries the prefix `v<version>: `. `review`/`security_audit` tasks do NOT change the version.
<!-- factory-rule: versioning end -->


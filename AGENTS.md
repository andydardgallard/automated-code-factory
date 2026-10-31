<!-- code-factory-version: 12.19.0 -->
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
  `calibrate_reviewer.py` (reviewer golden-set calibration: precision/recall/accuracy; `status`
  is the deterministic form of the periodic-calibration obligation — it fails loudly when the
  reviewer prompt changed since the last recorded calibration or 5 runs passed, judged against the
  append-only `skill-base/golden-set/calibration-log.md`),
  `model_matrix.py` (the single model-precedence resolver: the task matrix used verbatim, the
  default matrix where the generator≠judge rule is enforced, the family check and the committee's
  contrasting second planner), `model_attribution.py` (artifact-backed model attribution: reads the
  CLI session wire and cross-checks `models_used` — a mismatch FAILS the run, a missing wire is
  DEGRADED, and a `models_used` key that is not a role of the factory is a run error, exit 1),
`review_followup_task.py` (deterministic review follow-up task generator: the merged
  findings → `.code-factory/review/fix-tasks.yaml`),
  `plan_arbiter.py` (deterministic merge of two competing plans + list of discrepancies —
  committee on double plan rejection), `precedent_index.py` (FTS5 precedent index over memory +
  codebase: `build`/`status`/`query`, with `status` reporting FRESH/STALE and `query --fresh`
  refusing a stale index instead of answering from it),
  `chrome_devtools_mcp.py` (conditional Web GUI browser path: applicability `decide`, existing
  E2E-stack discovery, browser matrix, vendored pinned install (`vendor-install`) + idempotent merge
  of the node-direct `chrome-devtools` server into `.kimi-code/mcp.json`, fail-soft capability probe),
  `task_parser.py` (deterministic stdlib task.yaml parser/validator for Phase 0: the full documented
  task schema incl. `business_tests` and multi-line `|` block scalars inside list items, verbatim
  texts, actionable line-numbered errors — exit 2 names the line and the fix, never a generic
  "unreadable" and never a traceback).
  Self-tests pin these contracts: `test_model_precedence.py` and `test_model_attribution.py` cover
  the two model scripts, `test_review_followup_task.py` the follow-up generator and
  `test_task_accepts_business_scenario.py` / `test_task_accepts_multiline_criteria.py` /
  `test_task_error_is_actionable.py` the task parser; `test_no_role_substitution.py` and
  `test_provider_stop.py` pin the `model-unavailable-stop` rule, its four carriers and the
  provider-failure branch of the flow; `test_review_report_only.py` pins
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
- `skill-base/` — persistent skill base from `reference_docs`/`reference_skills` (optional); it
  always holds the two clean-code skills — `clean-code-discipline` (the writing discipline: make it
  work, then make it right, then follow practice, with named checkable rules) and `clean-code-metrics`
  (the reviewer's three metric gates: CRAP below 10, duplication rank 0.8 removed, surviving mutants
  killed) — cited as standing practice by `coder`/`gui-expert` and applied by the reviewer through
  `references/code-review.md` §2.2; both are pinned in `skill-base/manifest.json` and install, vendor
  or execute nothing.
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

- **Mandatory rules live in ONE place**: every bullet below that names a rule id (`Rule \`<id>\``)
  points at that rule's canonical wording in
  `.agents/skills/code-factory/references/factory-rules.md`; this file deliberately does NOT quote
  the wording again — a second verbatim copy only drifts, and `check_factory_rules.py` reconciles
  the rulebook with every document that really does quote it. This file stays a MAP: it is
  hand-authored (not generated), and it must stay under 28 KB (warn) / 32 KB (hard fail) —
  `project_fingerprint.py` and `check_factory_model.py` enforce that.
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
- Rule `memory-ownership`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-ownership`).
- Rule `memory-provenance`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-provenance`).
- Rule `memory-actuality`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-actuality`).
- **run_id and WIP checkpoint**: `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>` is computed at the start
  of a run (`run_id.py gen --task .code-factory/state/task.yaml`) and stamped into `pipeline.yaml`,
  `acceptance.md`, `logs/*.md`, `report.md`, and the memory entry; `run_id.py check --dir .code-factory`
  lists the run's artifacts without a `run_id`. The `pipeline.yaml` checkpoint carries the required keys
  `run_id`, `phase`, `status` (`ok|failed|in_progress`), `updated_at`, and the optional
  `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`, `models_used`; checked by
  `scripts/check_factory_model.py` (missing file — SKIP). A v2 memory entry carries a `run_id` and
  provenance markers `[verified: <evidence>]`/`[inferred]` in `decisions` and `results`.

- Communication with the user — business language only.
- Rule `english-only`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## english-only`).
- **Artifacts before changes**: before editing any source file, `.code-factory/` must already
  contain `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
- Rule `artifacts-first`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## artifacts-first`).
- Rule `run-id`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## run-id`).

- **Repo gate**: if the task references files/symbols/configs missing from the repository —
  in hitl mode stop and ask the user; in auto mode record an assumption.
- **Error routing**: deterministic regex → Diagnostician (LLM) → Advisor (secondary,
  a family contrasting with the diagnostician, budget 1) → Human → FAILED; retries per role budgets
  (coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2).
- Rule `retry-budgets`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## retry-budgets`).

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
  soft thresholds — verdict accuracy 100%, macro precision ≥ 0.8). That obligation is
  DETERMINISTIC, not prose: `calibrate_reviewer.py status` compares the reviewer-prompt digest and
  the run count with `skill-base/golden-set/calibration-log.md` and exits 1 (loud FAIL) when a
  calibration is due; `score --log` appends the record that clears it.
- Rule `vaccination`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## vaccination`).

- Rule `review-gate-policy`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## review-gate-policy`).
- Rule `review-report-only`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## review-report-only`).
- Rule `shard-protocol`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## shard-protocol`).

- **Verified acceptance**: criteria with `verify` are executed for real (`scripts/verify_acceptance.py`
  → `.code-factory/state/acceptance.md`; exit 0 only on SUCCESS — at least one criterion with
  `verify`, all criteria that carry `verify` are MET, baseline proven), and evidence carries FRESH/STALE signatures
  (`scripts/evidence_ledger.py`): a green log from a stale revision does not count as acceptance.
- Rule `verified-acceptance`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## verified-acceptance`).
- Rule `evidence-ledger`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## evidence-ledger`).

- **Briefing for every delegation**: the subagent receives a self-contained briefing per
  `.agents/skills/code-factory/references/handoff-briefing.md` — Task / Context / relevant
  files BY PATH (without inlining their contents) / what has already been tried and why it failed; only the main agent writes
  files; read-only roles carry the "no edits" suffix.
- Rule `handoff-briefing`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## handoff-briefing`).
- Rule `no-shared-tree-git-mutations`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## no-shared-tree-git-mutations`).

- **Task format**: `title`, `repo_path`, `description`, optional `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`
  (a criterion may optionally carry `verify: <command>` and `derived: true`), `business_tests`
  (scenario/configs/expected business results), `commit_exclude`, `models`.
  There is no `priority` field — all tasks are high by default.
- Rule `task-format`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## task-format`).

- **User story**: when `user_story` is present, the factory analyzes and uses it at the
  analysis, planning, and implementation stages (by all agents).
- **Plan approval (hitl)**: the first plan rejection sends it back for revision; the second
  is a double rejection: a second independent planner subagent is launched (from a contrasting model
  family), and `scripts/plan_arbiter.py` deterministically merges both plans and prints a list of
  discrepancies; the user is shown the merged plan, and further edits are made against it.
- Rule `plan-committee`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## plan-committee`).
- **`task_type: refactor`** — the freeze-functionality invariant: 100% of the existing tests pass
  unchanged; any behavior change is a critical error and an automatic rollback.
- **`task_type: security_audit`** — adaptive full audit (no live network scanning or
  pentesting); the result is reports + a fix-task file; the factory does NOT fix vulnerabilities itself.
- **Git-native**: if there is no git repository — `git init`; changes go through git
  (a feature branch per task), rollback to the base commit on failure.
- Rule `git-native`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## git-native`).
- **Destructive-action gate**: before a destructive shell action the main agent classifies it with
  `scripts/action_gate.py check` — the flow never runs `git push`, `git reset --hard`, `git clean`, a
  path `git checkout`/`git restore`, `rm -rf` or a branch deletion unclassified. The rollback
  procedure classifies its restoring commands the same way.
- Rule `destructive-action-gate`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## destructive-action-gate`).
- Rule `repo-scoping`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## repo-scoping`).

- **Models**: models are set in `config.toml` (`default_model` + `[secondary_model]`);
  for subagents — `model_preference: primary|secondary`. Actual models are logged in
  `pipeline.yaml`/`report.md` (`models_used`). Model splitting requires
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — the `start.sh`/`start.cmd` launcher sets it itself; the factory
  checks it in pre-flight and, if missing, writes `models_warning` to pipeline.yaml/report.md.
  Kimi (K3) and Qwen models are routed via the task's `models` field (see
  `references/providers.md`).
- Rule `models-generator-ne-judge`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## models-generator-ne-judge`).
- Rule `model-unavailable-stop`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## model-unavailable-stop`).

- **Reports**: `report.md` (run history) + `report_code_changes.md` (before→after diff)
  are generated automatically in `.code-factory/` on completion.
- **Commits**: the task's `commit_exclude` field excludes files from the git commit
  (for example, a personal strategy); the core and documentation are committed.
- Rule `commit-exclude`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## commit-exclude`).

- When factory files change, update `.agents/README.md` and these instructions.
- **Documentation**: after every successful implement/refactor, the
  `factory-documenter` subagent (secondary) is invoked — it updates only doc comments and `.md` files; validator
  `validate_documentation.py` with a budget of 1 retry; not invoked for review/security_audit.
- Rule `documentation`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## documentation`).

- **Version**: `VERSION` is the single source of truth; the version type is determined by a deterministic
  matrix, validated by the code reviewer (may override with an explanation), applied by
  `version_manager.py`; review/security_audit do not change the version.
- Rule `versioning`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## versioning`).


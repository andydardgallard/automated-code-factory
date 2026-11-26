<!-- code-factory-version: 12.26.0 -->
# Project: Autonomous Code Factory

An autonomous code-writing factory for the Kimi Code CLI: it takes a business task from a
non-technical user, analyzes the project, plans the change, clarifies only business logic, gets the
plan approved, implements it, runs integration / regression / business tests with automatic rollback
on failure, and reviews the code before acceptance.

## Structure

- `.example.task.yaml` — the committed example business task (format reference); a working
  `task.yaml` is per-run, gitignored and never shipped
- `.agents/skills/code-factory/` — the flow skill (`SKILL.md`), references (`references/`:
  planning-guide, verification-strategy, error-routing, tech-stack-detection, code-review, providers,
  refactoring, security-audit, handoff-briefing — the mandatory briefing template; the conditional
  paths `chrome-devtools-mcp`, `farukon-mcp`, `roblox-mcp`; `factory-rules.md`
  — the single rulebook whose carriers `check_factory_rules.py` reconciles;
  `error-patterns.default.json` — the error-routing snapshot for `error_router.py`), and `assets/`
- `.agents/skills/code-factory/scripts/` — deterministic stdlib scripts (0 tokens):
  `repo_inventory.py` (inventory + shards ≤20k lines), `merge_findings.py` (merged verdict),
  `verify_acceptance.py` (criteria with `verify` → acceptance.md; a verify command's output goes to
  temp files and is read back as a bounded tail, so bulk output or an inheriting grandchild cannot
  hang the gate), `verify_quotes.py`, `evidence_ledger.py` (FRESH/STALE signatures),
  `factory_preflight.py`, `action_gate.py`, `task_graph.py`,
  `log_tail.py`, `repo_stats.py`, `project_fingerprint.py`, `memory_project.py`, `version_manager.py`,
  `check_factory_rules.py` (rulebook vs carriers: `factory-rule` blocks byte-for-byte + the
  approval-gate workflow prose), `check_english_only.py` (English-only gate over `git ls-files`: any
  Cyrillic outside the documented exceptions — `CHANGELOG.md`, `memory/`, `task*.yaml`,
  `.code-factory/`, `.git/` — fails, `memory/` only as HISTORY, `--no-memory` the escape),
  `check_translation_structure.py` (a translation may change its text, never its structure —
  headings, list items, fences, `factory-rule` markers, CLI arguments;
  `--allow-added-rule <id>` admits a deliberately added rule), `check_input_validation.py` (a newly
  added input with no purpose-fitted validation fails), `run_id.py` (`gen`/`check`), `run_guard.py`
  (single-active-run guard: `claim` after `run_id.py gen` and BEFORE the first checkpoint write — a
  free, TERMINAL or this-run resume is CLAIMED, another active run REFUSED loudly; writes nothing = a
  check, not a lock), `error_router.py` (JSON-first `classify`/`merge`), `agent_catalog_check.py`
  (FAIL-CLOSED on catalog COMPLETENESS: every `model_matrix.ROLES`/`ROLE_FILES` role needs a profile
  whose frontmatter parses in the strict YAML subset, a `name:` resolving back to that role (no third
  roster) and a `primary|secondary` `model_preference` — exit 0 =
  valid, so `Unknown agent type` is CLI-side LOSS and the SAME role is retried with the SAME model;
  exit 1/2 = a profile MISSING/INVALID or a bad root/role, a FACTORY DEFECT that STOPS the run, route
  `AGENT_CATALOG`), `calibrate_reviewer.py` (golden-set calibration: precision/recall/accuracy + the
  deterministic `status` gate), `model_matrix.py` (the single model-precedence resolver: task matrix
  verbatim, the default matrix under the generator≠judge rule, the family check, the committee's
  contrasting second planner), `model_attribution.py` (artifact-backed attribution from the CLI
  session wire: a mismatch FAILS, strictness is the DEFAULT for implement/refactor — a required role
  claiming a model with no wire trace FAILS — a missing wire is otherwise DEGRADED, an unknown
  `models_used` key is a run error), `review_followup_task.py` (findings → `review/fix-tasks.yaml`),
  `plan_arbiter.py` (two competing plans + discrepancies), `precedent_index.py` (FTS5 index:
  `build`/`status`/`query`, `query --fresh` refusing a stale index), `chrome_devtools_mcp.py`
  (conditional Web GUI path: `decide`, E2E-stack discovery, browser matrix, vendored pinned
  `vendor-install` + idempotent merge of the `chrome-devtools` server into `.kimi-code/mcp.json`,
  probe fail-soft but fail-closed on the vendored pin), `farukon_mcp.py` (conditional Farukon
  platform path: `decide` — the repo HOSTS the `farukon_mcp` crate AND the task text binds a platform
  OPERATION to an EXPLICIT SUBJECT (`SCOPE_APPLICABLE_SCORE`; identity vocabulary, task metadata and
  a `models.farukon_expert` pin never decide) — idempotent atomic merge-config of the `farukon` stdio
  server (`cargo run --quiet -p farukon_mcp --`, `cwd` = absolute platform root) into
  `.kimi-code/mcp.json`, conflict preserved, symlink-resolved `--target`, fail-soft probe with the
  opt-in bounded `--check-mcp-start`, `validate-config` echoing no entry value), `roblox_mcp.py`
  (conditional Roblox game path: `decide` — the repo IS a Roblox project (Rojo descriptor, place
  file, Roblox-API Luau source, managed project entry) AND the metadata-stripped task text binds a
  Roblox SUBJECT to an ACTION, so identity, text and a `models.roblox_expert` pin each alone keep the
  role off; idempotent atomic `merge-config` of the `Roblox_Studio` stdio server into the USER-SCOPE
  GLOBAL config (`$KIMI_CODE_HOME/mcp.json`, else `~/.kimi-code/mcp.json`) or a symlink-resolved
  `--target`, a different entry = conflict exit 3, target untouched; `validate-config`; a fail-soft
  probe whose Studio start is strictly opt-in (`--check-mcp-start`); and `scenario run`/`verdict`/
  `verify` — a bounded MCP session, the CAPTURED console output and a structured verdict where an
  error-logged run is never PASS and a screenshot is never the verdict), `modern_web_guidance.py`
  (pinned Modern Web Guidance adapter: a corpus read as DATA from ONE reviewed commit — never `npx`;
  freshness fails closed on the full sha, unstable guidance needs an explicit `.mwgrc` opt-in plus a
  declared fallback, `check-session` demands this run's own search→retrieval journal),
  `task_parser.py` (Phase 0 task.yaml parser/validator: the documented schema incl. `business_tests`
  and `|` block scalars; exit 2 names the line and the fix), and the delegation and
  change-set gates: `manifest.py` (change set with COMPUTED sha256 — `init`, the pre-edit `require`
  gate, `add --changed|--created` (a CHANGED file needs its backup first), the finish `audit`),
  `delegation_gate.py` (per-role budgets counted where the role EXECUTES: `check` increments and
  REFUSES an exhausted budget, `--owner-authorized` = one extra delegation per owner decision,
  `settle` refunds a wholly refuted reviewer round, `audit` reconciles the counters with the session
  wire; the CODER ceiling follows the approved plan — one delegation per DISTINCT coder task plus one
  retry reserve, falling closed to 1), `permit_gate.py` (`permits.yaml`
  `add`/`verdict`/`bind`/`close` + the finish audit: every spawn needs a unique allowed permit judged
  BEFORE it, scoped inside the plan task's files; every transition appends to the hash-chained
  `permits.ledger.jsonl`, verified against the state on disk BEFORE every write, so a reset, a
  truncated tail or a post-deny repair is refused, and the owner's `repair` is the only recovery
  (`--mode restore`/`--mode attest --note <why>`/report-only); the supervisor's permit precedes
  Phase 0 (`--launch-dir`, run-keyed by `--launch-id`) and `bind-run` TRANSFERS a keyed launch
  registry to the run),
  `gate_all.py` (phase `K`|`Y` aggregator: a missing gate record is a failure, the run's ONE explicit
  `--session` reaches the wire-auditing gates, a phase launched elsewhere FAILS CLOSED) and
  `mcp_json_merge.py` (the JSON merge the MCP helpers share). Sibling `test_*.py`
  modules pin them all — the gate, MCP-helper (`test_farukon_mcp.py`/`test_roblox_mcp.py`: opt-in
  handshakes, exit-3 conflict, scenario verdict), model, task-parser, flow-prose, catalog and
  input-validation tests named in `.agents/README.md` — and `test_vaccination.py` proves every fix of
  this release bites on the pre-fix tree. Every argparse script reconfigures its streams to UTF-8, so
  a legacy code page never breaks a message: `--help` → exit 0, usage error → exit 2, no traceback.
- `.agents/agents/` — the factory's main agent (Markdown `code-factory.md`) and subagents
  (`sub-agents/analyzer|planner|coder|gui-expert|farukon-expert|roblox-expert|tester|business-tester|diagnostician|advisor|code-reviewer|supervisor|refactorer|security-auditor|documenter|skill-manager.md`)
  — `business-tester` is generator-side and attacks the delivered change as an ADVERSARIAL USER
  through the product's own interfaces, in parallel with the tester; `roblox-expert` is the
  conditional 16th role: coder-class Roblox game implementation/operation through the built-in Roblox
  Studio MCP server, producing DIAGNOSTIC evidence only (the tester owns acceptance); `supervisor` is
  read-only and judge-side, launched FIRST as a run-long watchdog whose permit precedes Phase 0
  (observing the task parse, `repo_path` resolution, memory read/write and `run_id`) and returns an
  allow|deny verdict against the rulebook and the approved plan — MODEL-ENFORCED, with
  `permit_gate.py audit` as the deterministic backstop, so a main agent that skips the permit step is
  DETECTED at the finish, never intercepted at call time
- `VERSION` — single source of truth for the factory version (one line X.Y.Z)
- `skill-base/` — persistent skill base from `reference_docs`/`reference_skills` (optional): the two
  clean-code skills — `clean-code-discipline` (make it work, then make it right, then follow practice,
  with named checkable rules) and `clean-code-metrics` (the reviewer's three metric gates: CRAP below
  10, duplication rank 0.8 removed, surviving mutants killed), cited as standing practice by
  `coder`/`gui-expert`/`farukon-expert`/`roblox-expert` and applied by the reviewer through
  `references/code-review.md` §2.2 — plus the three pinned Roblox skills `game-development`,
  `roblox-studio-mcp` (the Studio MCP tool catalogue) and `roblox-engine-api` (a scoped INDEX whose
  single-page source limitation is documented). All are pinned in `skill-base/manifest.json`, read as
  DATA, and execute nothing.
- `.agents/README.md` — the full factory usage manual
- `prepare_factory.sh` — one-action project preparation (creates the `start.sh` launcher)
- `prepare_factory.cmd` / `prepare_factory.ps1` — the same on Windows without Git Bash (entry point
  and implementation; they create the `start.cmd` launcher), `start.cmd` — launching the factory on Windows
- **Portable user-scope agent catalog** — the CLI's PROJECT-scoped profile registry has repeatedly lost
  a role ("Unknown agent type"). Both deployers therefore copy all 16 profiles of
  `.agents/agents/sub-agents/` BYTE-FOR-BYTE into the CLI's USER-scope catalog — `$KIMI_CODE_HOME/agents`
  when set (it relocates the whole data root), else `~/.kimi-code/agents` (`$HOME` on Linux/Git Bash,
  `%USERPROFILE%` on Windows) — and both launchers refresh those copies BEFORE the CLI starts, with
  native shell/cmd commands only (no interpreter, no Python). The refresh is FAIL-CLOSED and
  PROVEN: every copy is compared with its source byte-for-byte (`cmp`, `fc /b`); an INCOMPLETE project
  catalog aborts (one missing profile would leave that role stale), and an ABSENT one is legal only
  over a COMPLETE user-scope catalog — otherwise the launch is refused with a `Code Factory:` message
  and a nonzero exit and no CLI starts. Profiles the factory does not manage are never touched.
  Pinned by `scripts/test_stable_agent_catalog.py`.
- `memory/` — portable long-term memory of the TARGET project (committed), created AT THE
  DEPLOYMENT ROOT (the directory passed to `prepare_factory.sh`, or `prepare_factory.cmd` on
  Windows): `change-log.md` (append-only run journal) and `summary.md` (condensed summary), named
  after that directory's basename, with the `project: <name>` marker in an entry and
  `project:`/`repo_path:` in the summary.
## How to use

- Kimi Code 0.34+: `kimi`, then `/skill:code-factory`; or
  `kimi --agent-file .agents/agents/code-factory.md "task"`
- Full automation: `kimi --auto` → `/skill:code-factory`
- **One action**: `./prepare_factory.sh <project>` then `./<project>/start.sh`; on Windows
  `prepare_factory.cmd <project>`, `cd <project>`, `start.cmd` (`--auto` for full autonomy) — no Git
  Bash and no Python prerequisite (only the memory and version scripts use it)
- `mode: auto` in `task.yaml` controls only the factory's business questions; CLI permission prompts
  are disabled separately — the `kimi --auto`/`--yolo` flag or `default_permission_mode` in
  `config.toml`.

## Conventions

- **Mandatory rules live in ONE place**: every bullet below that names a rule id (`Rule \`<id>\``)
  points at that rule's canonical wording in
  `.agents/skills/code-factory/references/factory-rules.md`; this file deliberately does NOT quote
  the wording again — a second copy only drifts, and `check_factory_rules.py` reconciles the rulebook
  with every document that does quote it. This file stays a MAP: hand-authored (not generated) and
  under 28 KB (warn) / 32 KB (hard fail) — `project_fingerprint.py` and `check_factory_model.py`
  enforce that.
- The factory's runtime state — `.code-factory/` (do not commit) — lives at the ROOT of the
  RESOLVED `repo_path`: the task's `repo_path` is resolved ONCE to an absolute path (relative to the
  launch directory) at the start of the run, and that resolved root — not the launch directory —
  holds `.code-factory/`; every relative artifact path here is relative to it: `state/` (task, plan,
  pipeline.yaml, acceptance.md, evidence ledger, task graph), `logs/` (baseline, errors, results,
  code-review, shard findings), `backups/`, `manifest.json`.
  `state/precedents.db` is the FTS5 precedent index — a BUILD PRODUCT, not standing runtime state:
  the flow builds it at analysis time (`precedent_index.py build`), it is gitignored with the rest of
  `.code-factory/`, `precedent_index.py status` reports FRESH/STALE against the journal and the tree,
  and `query --fresh` refuses a stale index instead of answering from it.
- **AGENTS.md — single source of truth**: the factory generates it with exactly 8 `##` sections; its
  deterministic TWO-LEVEL fingerprint — structural (stack manifests, CI configs, README, directory
  list) + content (SHA-256 of the tracked working tree, CRLF→LF) — lives in DERIVED STATE,
  `.code-factory/state/fingerprint.json`, never inside the file: `project_fingerprint.py
  --write-state` writes it, `--check-state` compares it (exit 0 match, 1 divergence, 2 no usable
  state). AGENTS.md therefore carries NO marker and no longer depends on the commit that carries it —
  one version commit again; a stale embedded marker is IGNORED with a warning, a fresh clone with no
  state file is an actionable error naming `--write-state`. It regenerates when EITHER hash diverges
  (start of a task) or the structure/stack/entry points change (end of a task), and commits — "SKIP
  regeneration" only when BOTH match. The content hash reads the `git ls-files` working tree, so
  unstaged edits are visible; an absent or unreadable tracked file is recorded `MISSING`, and
  untracked files stay outside it with an explicit note (`git add` brings one in). Subagents read
  AGENTS.md instead of re-deriving the structure.
- **Long-term memory `memory/`** (committed, not ignored) — the memory of THE project named in the
  task's `repo_path` (for this repository the target project is the factory itself), not the
  factory's memory: one memory belongs to exactly one project, and it lives AT THE DEPLOYMENT ROOT
  (the directory passed to `prepare_factory.sh`; base project name = its basename). When `repo_path`
  points to a SUBDIRECTORY, the main agent creates it explicitly: `memory_project.py init --repo
  <deployment root> --project <basename of the resolved repo_path>`, the name fixed in the summary's
  `project:` declaration (journal entry and summary both declare it — rule `memory-ownership`).
  Entries without `project:` are legacy (warning); entries from different projects in one journal are
  an error. The main agent is the only writer (one `change-log.md` entry per run, compaction into
  `summary.md` at the 50-entry threshold — the last 20 stay — via `memory_project.py compact`); a
  missing `memory/` is created by the same `init`, and the factory's own development history NEVER
  enters the target project's memory. Model check — `scripts/check_factory_model.py`, a thin
  delegation to `memory_project.validate_memory`, so there is ONE memory contract rather than two.
- Rule `memory-ownership`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-ownership`).
- Rule `memory-provenance`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-provenance`).
- Rule `memory-actuality`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## memory-actuality`).
- **run_id and WIP checkpoint**: `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>`, computed at the start
  of a run (`run_id.py gen --task .code-factory/state/task.yaml`) and stamped into `pipeline.yaml`,
  `acceptance.md`, `logs/*.md`, `report.md` and the memory entry; `run_id.py check` lists artifacts
  without a `run_id`, and the claimed repository is guarded by `run_guard.py claim` BEFORE the first
  checkpoint write. The `pipeline.yaml` checkpoint carries `run_id`, `phase`, `status`
  (`ok|failed|in_progress`), `updated_at` and optionally `files_touched`, `pending_decision`,
  `resume_hint`, `retry_counters`, `models_used`, `launch_id` (the `supervisor_watchdog.py begin`
  nonce keying this run's bootstrap); checked by `scripts/check_factory_model.py` (missing — SKIP). A
  v2 memory entry carries a `run_id`, provenance markers `[verified: <evidence>]`/`[inferred]` in
  `decisions` and `results`, plus `unfinished` and `factory_version` (omitting either is a format
  error; a pre-v2 entry only warns).

- Communication with the user — business language only.
- Rule `english-only`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## english-only`).
- **Artifacts before changes**: before any source edit, `.code-factory/` already holds
  `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.- Rule `artifacts-first`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## artifacts-first`).
- Rule `run-id`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## run-id`).

- **Repo gate**: if the task references files/symbols/configs missing from the repository, hitl stops
  and asks the user, auto records an assumption.
- **Error routing**: deterministic regex → Diagnostician (LLM) → Advisor (a judge-side model from a
  contrasting family, budget 1) → Human → FAILED; retries per role budget (`delegation_gate.py`:
  ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2, and the plan-derived
  coder ceiling).
- Rule `retry-budgets`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## retry-budgets`).

- **Code review**: every task passes through the `factory-code-reviewer` subagent before
  acceptance. A regular task — a review of the changes diff; `task_type: review` and `security_audit` —
  a review/audit of all the code in SHARDS (`repo_inventory.py shards --tracked --max-lines 20000`
  over the TRACKED tree → parallel subagents per shard → `merge_findings.py` merged verdict). A
  `task_type: review` run is report-only (`review-report-only`): the deliverable is the report
  (`.code-factory/logs/code-review.md` + `.code-factory/report.md`) plus the generated follow-up task
  file `.code-factory/review/fix-tasks.yaml` (`review_followup_task.py`) the owner runs later as a
  separate `implement` task — the findings never become this run's plan, a review criterion that is
  not MET stops the run and asks the owner, and because nothing is edited every `verify:` criterion of
  a review task must be satisfiable on the unmodified tree; `security_audit` keeps its own guarantee
  (reports + a fix-task file, no auto-fixing). The critical/major boundary is
  `references/code-review.md` §3 (critical — EXISTING behavior damaged; major — a NEW path left
  unprotected), and §7's calibration (after every reviewer-prompt edit, at least once per 5 review
  runs) is DETERMINISTIC: `calibrate_reviewer.py status` compares the reviewer-prompt digest and the
  run count with `skill-base/golden-set/calibration-log.md` and exits 1 when a calibration is due,
  while `score --log` appends the record that clears it.
- Rule `vaccination`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## vaccination`).

- Rule `review-gate-policy`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## review-gate-policy`).
- Rule `review-report-only`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## review-report-only`).
- Rule `input-validation`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## input-validation`).
- Rule `shard-protocol`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## shard-protocol`).

- **Verified acceptance**: criteria with `verify` are executed for real (`verify_acceptance.py` →
  `state/acceptance.md`; exit 0 only on SUCCESS — at least one criterion with `verify`, all MET,
  baseline proven), and evidence carries FRESH/STALE signatures (`evidence_ledger.py`): a green log
  from a stale revision is not acceptance.
- Rule `verified-acceptance`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## verified-acceptance`).
- Rule `evidence-ledger`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## evidence-ledger`).

- **Briefing for every delegation**: the subagent gets a self-contained briefing per
  `.agents/skills/code-factory/references/handoff-briefing.md` — Task / Context / relevant files BY
  PATH (never inlined) / what was already tried and why it failed; only the main agent writes files,
  and read-only roles carry the "no edits" suffix.
- Rule `handoff-briefing`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## handoff-briefing`).
- Rule `no-shared-tree-git-mutations`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## no-shared-tree-git-mutations`).

- **Task format**: `title`, `repo_path`, `description`, optional `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`
  (a criterion may carry `verify: <command>` and `derived: true`), `business_tests`
  (scenario/configs/expected business results), `commit_exclude`, `models`; there is no `priority`
  field — all tasks are high by default.
- Rule `task-format`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## task-format`).

- **User story**: when `user_story` is present it is used by all agents at the analysis, planning and
  implementation stages.
- **Plan approval (hitl)**: the first rejection sends the plan back for revision; the second is a
  double rejection — a second independent planner from a contrasting model family, and
  `scripts/plan_arbiter.py` merges both plans and prints the discrepancies; the user is shown the
  merged plan and further edits are made against it.
- Rule `plan-committee`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## plan-committee`).
- **`task_type: refactor`** — the freeze-functionality invariant: 100% of the existing tests pass
  unchanged; any behavior change is a critical error and an automatic rollback.
- **`task_type: security_audit`** — adaptive full audit (no live network scanning or pentesting); the
  result is reports + a fix-task file; the factory does NOT fix vulnerabilities itself.
- **Git-native**: if there is no git repository — `git init`; changes go through git (a feature branch
  per task), with rollback to the base commit on failure.
- Rule `git-native`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## git-native`).
- **Destructive-action gate**: before a destructive shell action the main agent classifies it with
  `scripts/action_gate.py check` — the flow never runs `git push`, `git reset --hard`, `git clean`, a
  path `git checkout`/`git restore`, `rm -rf` or a branch deletion unclassified, and the rollback
  procedure classifies its restoring commands the same way.
- Rule `destructive-action-gate`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## destructive-action-gate`).
- Rule `repo-scoping`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## repo-scoping`).

- **Models**: set in `config.toml` (`default_model` + `[secondary_model]`); for subagents —
  `model_preference: primary|secondary`; the models used are logged as `models_used` in
  `pipeline.yaml`/`report.md`. Splitting requires `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` (set by
  the launcher; pre-flight otherwise writes `models_warning`). Kimi (K3) and Qwen
  models are routed via the task's `models` field (`references/providers.md`). Optional keys name a
  role's model and are logged as `models_used.<role>`: `models.gui_expert`, `models.farukon_expert`,
  `models.roblox_expert`, `models.business_tester` (all generator-side, like `models.coder`) and
  `models.supervisor` (judge-side, so its family differs). The run writes `task_type` and
  `required_roles` (implement/refactor: analyzer, planner, coder, tester, business_tester, reviewer,
  documenter) into `pipeline.yaml` — the contract strict model attribution defaults to, with
  gui_expert, farukon_expert, roblox_expert and security_auditor conditional.
- Rule `models-generator-ne-judge`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## models-generator-ne-judge`).
- Rule `model-unavailable-stop`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## model-unavailable-stop`).

- **Reports**: `report.md` (run history) + `report_code_changes.md` (before→after diff) are generated
  automatically in `.code-factory/` on completion.
- **Commits**: the task's `commit_exclude` field excludes files from the git commit (for example, a
  personal strategy); the core and documentation are committed.
- Rule `commit-exclude`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## commit-exclude`).

- When factory files change, update `.agents/README.md` and these instructions.
- **Documentation**: after every successful implement/refactor the `factory-documenter` subagent
  (secondary) is invoked — it updates only doc comments and `.md` files; the validator
  `validate_documentation.py` (budget 1 retry) recounts the changed files from git with `--derive`
  (untracked new ones included), so an undeclared file fails, and exempts the orchestrator's
  `--baseline-files` set only while each file keeps its captured content; not invoked for
  review/security_audit.
- Rule `documentation`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## documentation`).

- **Version**: `VERSION` is the single source of truth; the version type comes from a deterministic
  matrix, is validated by the code reviewer (which may override with an explanation) and applied by
  `version_manager.py`; review/security_audit do not change the version.
- Rule `versioning`: canonical wording — `.agents/skills/code-factory/references/factory-rules.md` (`## versioning`).


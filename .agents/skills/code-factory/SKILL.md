---
name: code-factory
description: Autonomous code factory that accepts business tasks in plain language from non-technical users, analyzes the project, plans changes, asks only business-logic questions, obtains plan approval, then implements code and runs integration / regression / business tests with deterministic error routing and LLM diagnosis on failure, checkpoint/resume, and rollback, plus a mandatory code-review gate before acceptance, finally validating acceptance criteria. Works with any programming language or combination of languages. Use when the user says "run the code factory", "solve this business task", "implement this feature", "fix this bug", "build this project", "review this code", or provides a business task file (task.yaml) / description.
type: flow
---
<!-- code-factory-version: 12.12.0 -->

# Code Factory

Turns business tasks (described by non-technical users) into working, tested code.

## Reference files — read the relevant one when you reach its phase

- `references/tech-stack-detection.md` — deterministic stack detection + Scout pipeline (Phase 1)
- `references/planning-guide.md` — analysis checklist, DAG plan template, business-test questions (Phases 2–3)
- `references/verification-strategy.md` — integration / regression / business tests and rollback (Phases 4–9)
- `references/error-routing.md` — deterministic error classification, retry budgets, Diagnostician fallback (on any failure)
- `references/code-review.md` — static quality gate: checklist, severity, verdict, rework task (before acceptance)
- `references/providers.md` — model routing for Kimi (K3) and Qwen providers (Phase 4)
- `references/refactoring.md` — refactor task type: freeze functionality, 100% tests unchanged
- `references/security-audit.md` — security_audit task type: adaptive full audit + fix-task file
- `references/documentation.md` — factory-documenter: documentation methodology + validator (Finish phase)
- `references/reference-docs.md` — reference_docs/reference_skills: persistent skill base + relevance matrix (Phase 0/5)
- `references/factory-rules.md` — the ONE home of the mandatory rules + the documents that must quote each one verbatim (`scripts/check_factory_rules.py` verifies the byte-identical blocks; any phase)
- `assets/task-template.yaml` — business task template (Phase 0)

## Runtime state (inside the project)

All runtime artifacts live in `.code-factory/`:

- `state/` — parsed task, plan, pipeline.yaml (checkpoint/resume), acceptance
- `backups/` — backups of files before modification
- `manifest.json` — list of changed / created files (used for rollback)
- `logs/` — baseline, errors.md, diagnostic.md, test-results.md

Every run is identified by a deterministic `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>`, computed
at the start of the run with
`python .agents/skills/code-factory/scripts/run_id.py gen --task .code-factory/state/task.yaml`,
and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`,
`report.md` and the run's `memory/change-log.md` entry; `python
.agents/skills/code-factory/scripts/run_id.py check --dir .code-factory` lists the artifacts of the
run that carry no `run_id`.

The WIP checkpoint `.code-factory/state/pipeline.yaml` carries the REQUIRED keys `run_id`, `phase`,
`status` (`ok` | `failed` | `in_progress`) and `updated_at`, plus the optional `files_touched`,
`pending_decision`, `resume_hint`, `retry_counters` and `models_used`;
`scripts/check_factory_model.py` validates the file when it exists (a project without a checkpoint
is a SKIP, never a failure).

The portable long-term memory lives in the committable `memory/` directory (NOT ignored, travels
with the project). It is the memory of THE TARGET PROJECT named by the task's `repo_path` — one
memory belongs to exactly one project (when the task targets the factory repository, that target
project is the factory). The `memory/` directory itself is created IN THE DEPLOYMENT ROOT — the
directory handed to `prepare_factory.sh` (on Windows to `prepare_factory.cmd`, which runs
`prepare_factory.ps1` without Git Bash) — and the base project name is the basename of that root.
When the task's `repo_path` points to a SUBDIRECTORY of the deployment root, the project name is the
basename of the resolved `repo_path`, and the main agent creates the memory explicitly:
`python3 .agents/skills/code-factory/scripts/memory_project.py init --repo <deployment root>
--project <basename of the resolved repo_path>`, then reads it; the name is pinned in the summary's
`project:` declaration.

- `memory/change-log.md` — append-only journal, one entry per completed run; single writer: the
  main agent at the end of each task. Every NEW entry MUST carry `project: <project name>` (the name
  pinned in `memory/summary.md`'s `project:` declaration = basename of the resolved `repo_path`)
  next to the other fields, the run's `run_id: <YYYYMMDD-8hex>` and a provenance mark
  (`[verified: <evidence>]` or `[inferred]`) inside `decisions` and `results`; entries without
  `project:` are
  legacy and only warned about, while entries of DIFFERENT projects in one journal are an error
  (caught by `scripts/check_factory_model.py` and `memory_project.py check`). A record counts as
  format v2 when its `factory_version` is NEWER than 12.8.0 OR it already carries a v2 field
  (`run_id` or a mark): for a v2 record a missing `run_id`/mark is a format ERROR, while a record
  written by factory 12.8.0 or older that carries no v2 field only warns.
- `memory/summary.md` — compressed summary (current state + key decisions + recent history),
  compacted from the journal when it exceeds the threshold; it MUST declare the project with
  `project: <name>` and `repo_path: <path>` lines right after the canonical marker

The factory's own development history is NEVER written into the target project's memory.

The factory may create any files, skills, scripts or plugins inside the project that are needed to solve the task. The factory must keep the total token spend minimal: use subagents for heavy context (analysis, coding, testing, diagnosis), return only concise structured results, and avoid loading large files into the main context.

```mermaid
flowchart TD
    A([BEGIN]) --> B[Accept the task: read the user's message or task.yaml. Extract: title, repo_path, description, user_story (optional), mode (hitl/auto), task_type (implement default | review | refactor | security_audit), acceptance_criteria (each criterion may carry verify and derived), business_tests (scenario, config, expected_results), commit_exclude, models, reference_docs, reference_skills. There is NO priority field — every task is HIGH by default. Save the parsed task to .code-factory/state/task.yaml. Read the long-term memory of the TARGET project from repo_path (memory/summary.md + recent memory/change-log.md entries) — the memory of the project, NOT of the factory; if memory/ is absent (first contact with the project), create it first via memory_project.py init --repo <deployment root> --project <basename of repo_path> (memory/ always lives in the deployment root; the name is pinned in the summary's project: declaration) — so that project's history is not re-derived. Reconcile that memory with the tree in the SAME step: python .agents/skills/code-factory/scripts/memory_project.py backlog --repo <deployment root> folds the OPEN items (follow_up=true or severity=critical) over the WHOLE journal, and every open item is re-checked against the actual code before it is planned again — an item fixed in an earlier run is not re-declared open, and no item disappears without evidence. If no task file exists, treat the user's message as the task. Checkpoint: if .code-factory/state/pipeline.yaml exists and the task is unchanged, resume from the recorded phase.]
    B --> C{Is the business task clear enough?}
    C -->|No| D[Ask the user business-level clarifying questions via AskUserQuestion. Ask ONLY business logic and expectations, never coding questions. Then update the parsed task.]
    D --> B
    C -->|Yes| E[Analyze the project: launch factory-analyzer subagents in parallel to determine tech stack, structure, entry points, test setup. Detect the stack deterministically using references/tech-stack-detection.md. Run the existing test suite to establish a regression baseline and save it to .code-factory/logs/baseline.md.]
    E --> SC[Scout pipeline: compute the deterministic structural fingerprint via scripts/project_fingerprint.py; if AGENTS.md exists and its embedded fingerprint matches, SKIP regeneration; otherwise generate AGENTS.md with exactly the 8 standard sections (no init step).]
    SC --> C2{Does the task match the analyzed repo? Check that files, symbols, configs and data referenced by the task actually exist.}
    C2 -->|No| R1[Ask the user for the missing files or context via AskUserQuestion in hitl mode, or in auto mode record an assumption that the repo is the source of truth and continue. Then re-analyze.]
    R1 --> E
    C2 -->|Yes| F[Create the development plan following references/planning-guide.md: DAG of tasks with dependencies and per-task verification commands; business tests are first-class tasks in the plan. If the task needs new in-project skills, scripts or plugins, include them in the plan. Save the plan to .code-factory/state/plan.md. For task_type=review, the plan is the review rework list produced by the code reviewer.]
    F --> TT{task_type?}
    TT -->|review| CR0[Run factory-code-reviewer over the WHOLE codebase — in shards, never as one whole-repo context: repo_inventory.py shards with --max-lines 20000 → one reviewer subagent per shard in parallel → merge_findings.py prints the deterministic merged verdict (request_changes if any shard returned it or any critical finding exists). Write the verdict to .code-factory/logs/code-review.md and log models_used.reviewer. On request_changes the rework list becomes the plan.]
    CR0 --> CRV0{Review verdict?}
    CRV0 -->|approve| W
    CRV0 -->|request_changes| G
    TT -->|implement| G
    TT -->|refactor| RF[Refactor flow: baseline the existing test suite, plan structural-only tasks, implement with factory-refactorer, verify 100% of existing tests pass unchanged — any behavior change is a critical error and rolls back automatically. See references/refactoring.md.]
    RF --> L
    TT -->|security_audit| SA[Security audit flow: detect artifact types, run only the relevant checks with factory-security-auditor (read-only) over the same shards — repo_inventory.py shards ≤20000 lines → parallel auditors → merge_findings.py — write reports + a generated fix-task file. No code change and no auto-fixing. See references/security-audit.md.]
    SA --> W
    G -->|hitl| H[Business test definition: ask the user via AskUserQuestion for 1 a concrete business scenario (user story), 2 which configs and input data to run, 3 expected business results. Only business-logic questions. Store answers in the plan.]
    H --> I[Present the full plan for approval: write it to the plan file and call EnterPlanMode then ExitPlanMode. Wait for approval or revision comments. Count every rejection in retry_counters.plan_rejections of .code-factory/state/pipeline.yaml.]
    I --> J{Plan approved?}
    J -->|Revise - first rejection| F
    J -->|Revise - second rejection| PC[Plan committee: launch a SECOND independent factory-planner subagent (sub-agents/planner.md) from a CONTRASTING model family (planner = kimi-k3, second planner = deepseek-flash) to build an alternative plan for the same task and the user's accumulated comments; it never sees the rejected plan.]
    PC --> PC2[Run the deterministic arbiter: python .agents/skills/code-factory/scripts/plan_arbiter.py --plan-a .code-factory/state/plan.md --plan-b .code-factory/state/plan-2.md --out .code-factory/state/plan_merged.md. It merges the machine-readable sections (DAG tasks by id, risks, business tests) and lists every divergence.]
    PC2 --> PC3[Present the merged plan and the divergence list to the user in business language; the merged plan becomes the plan of record and every further revision applies to it (the committee runs at most once per task).]
    PC3 --> F
    J -->|Approve| K
    G -->|auto| L[Make reasonable business assumptions from the task description. Record every assumption explicitly in the plan.]
    L --> PF[Pre-flight: probe the real environment first with scripts/factory_preflight.py --out .code-factory/state/preflight.json — it reports the python command that actually works (python / python3 / py), git, bash/sh, the OS and KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL, and every command below is emitted for the capabilities found. Then the git check: if the project has no git repository, run git init. Working tree must be clean: auto-untrack build artifacts (target/, node_modules/, __pycache__/ etc.) and commit factory artifacts (AGENTS.md). Record git HEAD and git status in .code-factory/state/. Also verify model setup: for the new CLI check that KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 is exported (otherwise secondary-model split is INACTIVE); record a models_warning in pipeline.yaml if missing.]
    PF --> K[Backup the current state: copy every file that will be modified to .code-factory/backups/ preserving relative paths. Track created files in .code-factory/manifest.json. Write the checkpoint .code-factory/state/pipeline.yaml after every phase for resume.]
    K --> M[Implement: launch factory-coder subagents for the plan tasks, respecting dependencies; independent tasks can run in parallel. Every delegation uses the mandatory briefing template references/handoff-briefing.md. Models are passed by the main agent: pass model: explicitly to the Agent tool (supported by the CLI) following the task's models matrix — model_preference in the sub-agent .md files is only the FALLBACK for roles the task does not name. After each subagent returns, log the used model for each role to pipeline.yaml models_used. Each coder follows the plan and the project coding style in an isolated context. After every change, update manifest.json. Also create any new skills/scripts/plugins defined in the plan.]
    M --> N[Integration tests: write and run per-task tests for the changed modules following references/verification-strategy.md.]
    N --> O{Tests passed?}
    O -->|No| RR[Route the failure per references/error-routing.md: classify deterministically by regex, record the error context in .code-factory/logs/errors.md, and update retry counters in pipeline.yaml.]
    O -->|Yes| Q[Regression tests: run the full existing test suite of the project.]
    RR --> RR2{Classification result}
    RR2 -->|coder| P[Rollback: restore backups, remove files created by the factory, restore git state per references/verification-strategy.md. Return the error context to the coder.]
    P --> M
    RR2 -->|ba| P2[Rollback + update the plan with the error context.]
    P2 --> F
    RR2 -->|planner| P2
    RR2 -->|infrastructure| AI[Run the deterministic auto-fix command from error-routing.md, then re-run the failed verification.]
    AI --> M
    RR2 -->|diagnostician| DG[Run the factory-diagnostician subagent: deep LLM analysis of the error output and attempt history. Every finding must quote the archived evidence verbatim and the quotes are re-checked with scripts/verify_quotes.py; long logs are read through scripts/log_tail.py. Write the report to .code-factory/logs/diagnostic.md.]
    DG --> DR{Diagnostician recommendation}
    DR -->|coder| P
    DR -->|ba| P2
    DR -->|planner| P2
    DR -->|infrastructure| AI
    DR -->|human| ADV[Escalation step three: run the factory-advisor subagent (secondary model, budget advisor=1) with a self-contained briefing — the task, files by path, what was tried and why it failed, acceptance criteria. It returns the machine-read agreement (agree|disagree with the Diagnostician's route), root_cause, recommended_role, recommended_action and confidence, logged to .code-factory/logs/diagnostic.md.]
    ADV --> ADR{Advisor recommendation}
    ADR -->|coder| P
    ADR -->|ba| P2
    ADR -->|planner| P2
    ADR -->|infrastructure| AI
    ADR -->|human| U2[Show the user the diagnosis and ask how to proceed.]
    U2 --> V2{User decision}
    V2 -->|fix code| M
    V2 -->|revise plan| F
    V2 -->|stop| Y
    Q --> R{Tests passed?}
    R -->|No| RR
    R -->|Yes| S[Business tests: run the program with the user-provided configs and input data. Collect actual business results and compare them with the expected business results.]
    S --> T{Business results match?}
    T -->|No| U[Show the user actual vs expected results. Ask via AskUserQuestion: fix the code, or revise the expectations?]
    U --> V{User decision}
    V -->|Fix the code| M
    V -->|Revise the expectations| S
    T -->|Yes| CR[Code review: run the factory-code-reviewer over the change (normal task: the diff; review task: the whole repo) following references/code-review.md. Write the verdict to .code-factory/logs/code-review.md and log models_used.reviewer.]
    CR --> CRV{Review verdict?}
    CRV -->|request_changes| RCR[Record the reviewer retry counter in pipeline.yaml. If the reviewer budget is not exhausted, pass the rework list to the coder and re-run integration + regression tests (business tests only if business logic changed), then re-review. If the budget is exhausted the canonical review-gate policy applies: in hitl mode STOP and ask the user, in auto mode ONLY a conditional pass is allowed — mark the affected criterion unverified_review in state/acceptance.md and record the unresolved findings in report.md, never silently. A full SUCCESS with open critical findings is impossible.]
    RCR --> M
    CRV -->|approve| W[Acceptance check with scripts/verify_acceptance.py: --input criteria.json --output .code-factory/state/acceptance.md --repo the project --regression pass, fail or not-run --ledger --evidence-files the signed files --run-id <run_id>. Criteria carrying a verify command are executed for real and their exit codes plus output excerpts land in acceptance.md; criteria without verify are labeled derived/unverified and are not proof of anything; a degraded baseline or STALE ledger evidence downgrades the verdict to DEGRADED; the exit code is 0 only for SUCCESS.]
    W --> X{All criteria met?}
    X -->|No| RR
    X -->|Yes| DOC{task_type: implement or refactor?}
    DOC -->|Yes| DOC2[Documentation: invoke factory-documenter (secondary) with .code-factory/manifest.json; update only doc-comments and .md files; validator validate_documentation.py with retry budget 1; on exhaustion — the documentation debt goes into the run report, the factory continues.]
    DOC2 --> VER1[Version — step 1: deterministic matrix version_manager.py suggest → propose the type major|minor|patch|none with an explanation]
    VER1 --> VER2[Version — step 2: the code reviewer validates the proposed type, may override it with an explanation (never from scratch)]
    VER2 --> VER3[Version — step 3: apply bump|set + sync, validate exit 0; commit with the prefix v<version>: in the same commit as the changes]
    VER3 --> Y
    DOC -->|No (review/security_audit)| Y
    Y[Finish: remove backups, produce the final report (what changed, test results, business results, acceptance evidence, models_used per role). Regenerate AGENTS.md if structure/stack/entry points changed, then commit AGENTS.md + memory/ to the feature branch respecting commit_exclude. Append one entry to memory/change-log.md (single writer: the main agent) carrying the mandatory project field (project: name of the target project, pinned in summary.md's project: declaration = basename of repo_path) and compact the journal into memory/summary.md when over the threshold; summary.md declares project and repo_path right after the canonical marker. Every open backlog item of the journal is handled in that same entry: closed by a closed: block that names the item and carries the mandatory evidence: (closing without evidence is invalid, and so is a closed: block naming an item that exists in no record) or carried over in unfinished with its reason — nothing disappears without proof of closure. Actualize the Current state section of memory/summary.md on EVERY run, not only on compaction (version, test counts, open backlog), and require memory_project.py backlog --repo <deployment root> --check to exit 0 — open: 0 with every closed: element valid. Update project documentation if the task requires it. Write the self-contained .code-factory/report.md with the full history (task, plan, errors, diagnosis, results, manifest, models_used). Generate .code-factory/report_code_changes.md next to it with the scripts/gen_code_changes_report.py script and --run-id <run_id> (was-became per changed line; the run id stamps the report as belonging to this run). Present the report to the user.]
    Y --> Z([END])
```

Rules that always apply:

- **Task format**: the task has `title`, `repo_path`, `description`, optional `user_story`,
  `mode`, `task_type` (`implement` | `review` | `refactor` | `security_audit`),
  `acceptance_criteria` (each criterion may carry `verify: <command>` and `derived: true`),
  `business_tests` (optional `scenario`/`config`/`expected_results` — the source of the Phase 8
  business tests), `commit_exclude`, `models`, and the two optional knowledge fields
  `reference_docs` (list of `{path, skill}` documents to convert into skills) and
  `reference_skills` (names of existing skills to reuse). There is NO `priority` field — every
  task is HIGH by default and the factory never prioritizes.
<!-- factory-rule: task-format begin -->
**Task format (canonical wording):** a task carries `title`, `repo_path`, `description`, optionally `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (a criterion may carry `verify: <command>` and `derived: true`), `business_tests` (scenario, configs, expected business results), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. There is NO `priority` field — all tasks are high by default, the factory does not prioritize them. A missing required field is a task parsing error, not a reason to guess it mid-run.
<!-- factory-rule: task-format end -->

- **User story**: when present, `user_story` is analyzed and used by the analyzer, planner and
  coder — it disambiguates the business intent and drives decisions.
- **Plan committee (double rejection)**: in hitl mode the first revision of a rejected plan goes
  back to planning; a SECOND rejection is a double rejection — a second, independent
  `factory-planner` subagent from a contrasting model family builds an alternative plan (it never
  sees the rejected one) and the deterministic `scripts/plan_arbiter.py` merges both plans and
  lists the divergences, which the user decides.
<!-- factory-rule: plan-committee begin -->
**Committee on double plan rejection (canonical wording):** if the user rejected the plan twice (hitl, Revise branch), the main agent launches a second independent planner subagent from a contrasting model family, which builds an alternative plan from the same task and the user's accumulated remarks; the deterministic `scripts/plan_arbiter.py` (stdlib) compares both plans by machine-readable sections (DAG tasks, verify commands, risks, business tests) and forms a merged variant with a list of discrepancies; the user is presented with the merged plan and the discrepancies, and further edits are made against it.
<!-- factory-rule: plan-committee end -->
- **Language-agnostic**: detect the stack; never assume a language. The factory serves any
  project type (frontend, backend, CLI, library, green-field) — verification is framework-agnostic.
- **Token efficiency**: parallel subagents, isolated contexts, concise results, progressive
  reference loading, and deterministic error routing (zero-LLM) before LLM diagnosis.
- **Rollback safety**: every test failure triggers error routing → rollback before retrying.
<!-- factory-rule: rollback-on-retry begin -->
**Rollback before retry (canonical wording):** every test or build failure is first routed deterministically (`references/error-routing.md`), then the state is rolled back: files are restored from `.code-factory/backups/`, factory-created files are deleted, the git state is brought back to the recorded one. Only after the rollback is the error handed to the executing role — otherwise the retry runs on an already corrupted state. Infrastructure auto-fixes (environment, dependencies) do not roll back code.
<!-- factory-rule: rollback-on-retry end -->
<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

- **Business-first**: communicate with the user only in business terms.
- **Artifacts first**: before touching any source file, materialize into `.code-factory/` the
  parsed task, the plan, the baseline, the backup of changed files and the manifest. Do not keep
  factory state only in the conversation.
<!-- factory-rule: artifacts-first begin -->
**Artifacts before changes (canonical wording):** the factory edits no source file until `.code-factory/` already holds `state/task.yaml` (the parsed task), `state/plan.md` (the plan), `logs/baseline.md` (the baseline test run), `backups/` (a backup of every file that will be changed, relative paths preserved) and `manifest.json` (the changed and created files). The run state lives on disk, not in the conversation: non-persistent knowledge is lost on restart and makes rollback impossible.
<!-- factory-rule: artifacts-first end -->

- **Repo-mismatch gate**: if the task references files, symbols, configs or data that are absent
  in the repo, stop in hitl mode and ask the user for them (or record an assumption in auto
  mode). Never silently skip missing inputs.
- **Escalation ladder**: deterministic regex → Diagnostician (LLM) → Advisor (LLM, secondary
  model family, budget 1) → Human (HITL) → FAILED with a full log. The Advisor is the second
  opinion taken when the Diagnostician's fix did not work; it receives a self-contained briefing
  per `references/handoff-briefing.md` and never edits files. The factory never crashes silently.
- **Retry budgets**: coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3,
  reviewer=2. When a role's budget is exhausted, escalate to the Diagnostician (for test/code
  failures), then to the Advisor (budget 1), and finally to the human (hitl) — never loop forever.
  The reviewer is governed by the canonical gate policy:

<!-- factory-rule: review-gate-policy begin -->
**Review gate (canonical wording):** a task is NOT accepted while the reviewer has open severity=critical findings (verdict `request_changes` with open critical findings). The reviewer budget = 2 iterations. If the budget is exhausted and critical findings remain: in hitl mode the factory STOPS and asks the user; in auto mode only a conditional pass is allowed — the corresponding criterion is marked `unverified_review` in `.code-factory/state/acceptance.md`, and the unresolved findings go into `.code-factory/report.md` (unresolved findings section), never silently. A full SUCCESS with open critical findings is impossible.
<!-- factory-rule: review-gate-policy end -->
<!-- factory-rule: retry-budgets begin -->
**Retry budgets (canonical wording):** every role has its own retry budget — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; the counters are kept in `.code-factory/state/pipeline.yaml` (`retry_counters`). An exhausted budget is not extended: the run escalates along the ladder deterministic regex → Diagnostician (LLM) → Advisor (LLM, secondary model, contrasting model family, budget 1) → Human (hitl) → FAILED with the full log. The factory does not loop, does not soften tests for a green run and does not fail silently.
<!-- factory-rule: retry-budgets end -->
<!-- factory-rule: checkpoint-resume begin -->
**Checkpoint/resume (canonical wording):** after every phase the main agent writes `.code-factory/state/pipeline.yaml` (phase, status, files touched, pending decision, resume hint, run_id, time) — the run state lives on disk, not in the context. On restart the factory reconciles the plan checkpoint and, if the task has not changed, continues from the RECORDED phase, not from the beginning. `resume` restores the retry counters, so exhausted budgets are not reset by a restart.
<!-- factory-rule: checkpoint-resume end -->

- **Checkpoint/resume**: after every phase write `.code-factory/state/pipeline.yaml` (current
  phase, retry counters, plan fingerprint). On restart, resume from the recorded phase.
- **Report**: on finish (success OR FAILED) write `.code-factory/report.md` — one
  self-contained file with the full history (task, plan, errors, diagnosis, results) so it can
  be handed to the factory developer for analysis without reading the whole `.code-factory/`.
  Also write `.code-factory/report_code_changes.md` (next to it) via
  `scripts/gen_code_changes_report.py` — a deterministic was-became diff report of the commit
  (zero LLM tokens).
<!-- factory-rule: run-id begin -->
**Run identifier (canonical wording):** at the start of a run `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` is computed deterministically (`scripts/run_id.py`) and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` and the run's memory entry. One run — one identifier; it links the artifacts to each other. `scripts/run_id.py check` finds the run's artifacts without a `run_id` and lists them.
<!-- factory-rule: run-id end -->

- **AGENTS.md (single source of truth) + fingerprint**: the factory generates `AGENTS.md` with
  exactly 8 `##` sections and embeds a deterministic structural fingerprint on its first line
  (`scripts/project_fingerprint.py`). At the start of a task, if the embedded fingerprint matches
  the recomputed one, skip regeneration; otherwise regenerate. At the end of a task, regenerate
  if structure/stack/entry points changed, then commit it. There is no init step.
- **Long-term memory (`memory/`)**: committable, never ignored. It is the memory of the TARGET
  PROJECT named by the task's `repo_path` (one memory — one project; the factory repository is
  itself such a target project when the task points at it), never the memory of the factory's own
  development. The `memory/` directory is created IN THE DEPLOYMENT ROOT — the directory handed to
  `prepare_factory.sh` (on Windows to `prepare_factory.cmd`, which runs `prepare_factory.ps1`
  without Git Bash) — where the base project name is the basename of that root; if the task's
  `repo_path` points to a SUBDIRECTORY of it, the project name is the basename of the resolved
  `repo_path` and the main agent creates the memory explicitly. If `memory/` is missing on first
  contact with a project, create it with
  `python3 .agents/skills/code-factory/scripts/memory_project.py init --repo <deployment root>
  --project <basename of the resolved repo_path>`; the chosen name is pinned in the summary's
  `project:` declaration. Single writer = the main agent,
  which appends one entry to `memory/change-log.md` at the end of every task (success OR FAILED)
  and compacts old entries into `memory/summary.md` when the journal exceeds 50 entries (keeping
  the last 20). Every NEW entry MUST carry `project: <project name>` (the name pinned in
  `memory/summary.md`'s `project:` declaration = basename of the resolved
  `repo_path`) next to the other fields, plus an `unfinished` section (even if it is the explicit
  "no unfinished items" marker) and a `factory_version` field; each
  unfinished item has
  `item`, `reason`, `severity` (critical|warning|info) and `follow_up` (true|false).
  `memory/summary.md` MUST declare the project with `project:`/`repo_path:` lines right after the
  canonical marker. Compaction MUST preserve items with severity=critical or follow_up=true.
  Legacy entries without
  `project:` or the `unfinished`/`factory_version` keys validate with a warning, never an error;
  entries of DIFFERENT projects in one journal are an error (caught by
  `scripts/check_factory_model.py` and `memory_project.py check`). Verify with
  `scripts/check_factory_model.py` (8 sections + fingerprint + memory format).
<!-- factory-rule: memory-ownership begin -->
**Memory ownership (canonical wording):** one memory belongs to exactly one project — the one named in the task's `repo_path`; the `memory/` directory lives at the DEPLOYMENT ROOT, the base project name = basename of the resolved `repo_path` and is fixed in the summary's `project:` declaration. The only writer is the main agent: one entry in `memory/change-log.md` per run, compaction into `memory/summary.md` at the 50-entry threshold (the last 20 remain, severity=critical and follow_up=true items are always preserved). Entries from different projects in one journal are an error (`check_factory_model.py`, `memory_project.py check`), entries without `project:` are legacy (a warning, not an error). The development history of the factory itself never enters the target project's memory.
<!-- factory-rule: memory-ownership end -->
<!-- factory-rule: memory-provenance begin -->
**Memory entry provenance (canonical wording):** an entry counts as a v2-format entry if its `factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a provenance marker) — so a half-migrated entry is checked too; such an entry must carry a `run_id` in the format `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) and provenance markers in the `decisions` and `results` fields: `[verified: <evidence>]` — the claim is confirmed by run evidence (log, acceptance, quote), `[inferred]` — an inference without direct evidence. A v2-format entry without a `run_id` or without markers in these fields is a format error (`memory_project.py check`, `check_factory_model.py`), whereas entries written by a factory no newer than 12.8.0 and carrying no v2 fields, and legacy entries without `project:`, yield only a warning. The `[verified: ...]` marker must reference concrete evidence (command/test/log); the validators check the marker's presence and form.
<!-- factory-rule: memory-provenance end -->
<!-- factory-rule: memory-actuality begin -->
**Memory actuality (canonical wording):** at the start of a run the open backlog is reconciled with the tree (`memory_project.py backlog --repo <root>` — a fold of all follow_up=true/severity=critical over the journal history); at the end of a run every item is either closed with a `closed:` block with a mandatory `evidence:` in the run entry, or stays in `unfinished` with a reason — an item cannot disappear without evidence of closing: `backlog --check` gives exit 1 for open items, closing without `evidence:` and closing a nonexistent item. The `summary.md` summary (`## Current state`) is actualized by EVERY run, not only at compaction; a divergence between the version it declares and VERSION is a mechanism warning.
<!-- factory-rule: memory-actuality end -->

- **Documentation (factory-documenter)**: after every successful `implement` or `refactor` run,
  the main agent invokes the `factory-documenter` subagent (secondary model) with the run
  manifest; it updates ONLY doc-comments and `.md` files, never code/tests/configs, and validates
  its work with `scripts/validate_documentation.py` (retry budget 1). If validation is exhausted,
  the documentation debt is recorded in the run report and the factory continues. It is skipped
  for `review` and `security_audit`.
<!-- factory-rule: documentation begin -->
**Documentation (canonical wording):** after every successful `implement`/`refactor` the main agent invokes the `factory-documenter` subagent (secondary) with the run's manifest; it updates ONLY doc comments and `.md` files and never code, tests or configs. It validates its work with `scripts/validate_documentation.py` with a budget of 1 retry; when the budget is exhausted, the documentation debt is recorded in the run report and the factory continues. Documentation is not invoked for `review`/`security_audit`.
<!-- factory-rule: documentation end -->

- **Versioning (single source of truth)**: `VERSION` (one line `X.Y.Z`) is the only source of
  truth; all other files sync FROM it via `scripts/version_manager.py` (get/bump/sync/validate/
  set/suggest, stdlib only). After a successful `implement`/`refactor` run the version type is
  chosen by the deterministic matrix (`suggest`), validated by the code reviewer (which may
  override it with an explanation, never from scratch), then applied with `bump`/`set` + `sync`
  and committed in the SAME commit with a message prefixed `v<version>: `. `review`/`security_audit`
  tasks do NOT change the version.
<!-- factory-rule: versioning begin -->
**Versioning (canonical wording):** `VERSION` (one line `X.Y.Z`) is the single source of truth, all other files are synced FROM it via `scripts/version_manager.py`. The version type is suggested by a deterministic matrix (`suggest`), validated by the code reviewer (may override with an explanation, but does not choose from scratch), applied by `bump`/`set` + `sync` + `validate` exit 0. The version commit goes in ONE commit with the changes and carries the prefix `v<version>: `. `review`/`security_audit` tasks do NOT change the version.
<!-- factory-rule: versioning end -->
<!-- factory-rule: english-only begin -->
**English-only (canonical wording):** every artifact the factory produces is written in English only: code and comments of target projects, documentation, docstrings, commit messages, reports (`.code-factory/report*.md`, logs), memory entries, plans and subagent briefings. The factory accepts a task file in any language, but everything it produces from it is English. EXCEPTION: live communication with the user stays in the user's business language, and history (CHANGELOG and old memory entries) is never rewritten.
<!-- factory-rule: english-only end -->

- **Models**: the main agent PASSES the model explicitly to the Agent tool (`model:` is supported
  by the CLI) following the task's `models` matrix and the generator≠judge rule of
  `references/providers.md` (coder/tester and reviewer/diagnostician/advisor come from different
  model families). The ONE exception where the matrix does NOT apply is the second planner of the
  plan committee (double rejection): it always comes from the family contrasting the first planner
  — the committee rule outranks the matrix (`references/providers.md` §5.2). The per-role
  `model_preference: primary|secondary` in each sub-agent `.md` is the FALLBACK, resolved against
  `config.toml` `default_model`/`[secondary_model]` for roles the task does not name. Log the actual
  model used for each role to `.code-factory/state/pipeline.yaml`
  (`models_used`) and include it in `report.md` so the run is auditable. The main agent's own
  model is the session model (set via `kimi -m` / `/model`); record it too. The secondary model
  is only used when the env var `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` is exported — during
  pre-flight check it (Bash: `echo "${KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL:-unset}"`) and if
  missing write `models_warning: "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL is not set —
  coder/tester subagents will use the primary model"` to pipeline.yaml and include the warning
  in report.md. When a role's model is a Kimi (K3) or Qwen model, route it per
  `references/providers.md` (alias → provider config) and handle its errors per
  `references/error-routing.md` §1.1.
<!-- factory-rule: models-generator-ne-judge begin -->
**Models: generator ≠ judge (canonical wording):** the main agent passes the model explicitly in the Agent tool (`model:`) per the task's `models` matrix and the generator≠judge rule: coder/tester and reviewer/diagnostician/advisor are taken from different model families. `model_preference: primary|secondary` in a subagent's `.md` is only a FALLBACK for roles not named by the task. The actual role models are logged in `.code-factory/state/pipeline.yaml` (`models_used`) and in `report.md`; the secondary model works only with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, otherwise the factory writes `models_warning` and continues on primary.
<!-- factory-rule: models-generator-ne-judge end -->

- **Commit policy**: respect `commit_exclude` from the task — never commit matching files
  (e.g. personal strategy code); stage everything EXCEPT the excluded patterns.
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (canonical wording):** files matching the task's `commit_exclude` patterns are NEVER committed — in no commit of the run, including the version and memory commit. Everything except the excluded patterns is staged; the code reviewer checks commit hygiene and counts an excluded file landing in the index as a finding of severity ≥ major.
<!-- factory-rule: commit-exclude end -->

- **Git-native**: if the project has no git repository, run `git init`. All changes flow through
  git (feature branch per task), with rollback to the base commit on failure.
<!-- factory-rule: git-native begin -->
**Git-native (canonical wording):** if the project has no git repository, the factory runs `git init` — there is no separate init step in the CLI. All changes go through git: a feature branch is created per task, the base commit and its HEAD are recorded in `.code-factory/state/`, and on failure the run rolls back to the base commit. The working tree is kept clean: build artifacts are auto-untracked, factory artifacts are committed.
<!-- factory-rule: git-native end -->

- **Think in Code (analyzer / tester / diagnostician)**: never read files or logs just to count,
  search or summarize — write a small stdlib script and read only its result (ready-made
  analyzers: `scripts/repo_stats.py` — sizes, entry points, imports). Long test/build output goes
  to `.code-factory/logs/`; the context gets counters + tail only, via `scripts/log_tail.py`.
- **Sharded whole-repo operations (review / security_audit)**: `scripts/repo_inventory.py shards
  --max-lines 20000` → one reviewer/auditor subagent per shard in parallel → `scripts/
  merge_findings.py` returns the deterministic merged verdict; an entire repository never enters
  one context.
<!-- factory-rule: shard-protocol begin -->
**Shard protocol (canonical wording):** whole-repo review and security_audit never fit into one context: `scripts/repo_inventory.py shards --max-lines 20000` cuts the repository into shards of ≤20000 lines, each shard is processed by its own parallel subagent (reviewer or auditor) and writes one findings file. The result is produced by the deterministic `scripts/merge_findings.py` (deduplication, sorting by severity, merged verdict), and the canonical review gate is applied to the MERGED findings, not to individual shards. A regular `implement` task is reviewed by diff and needs no sharding.
<!-- factory-rule: shard-protocol end -->

- **Verified acceptance**: acceptance is machine-checked with `scripts/verify_acceptance.py` —
  criteria carrying `verify` are executed for real and their exit codes land in
  `state/acceptance.md`, criteria without `verify` are only `derived`/`unverified`; the exit code
  is 0 only for SUCCESS, a degraded baseline or STALE ledger evidence gives DEGRADED, and SUCCESS
  without regression proof is impossible.
<!-- factory-rule: verified-acceptance begin -->
**Verified acceptance (canonical wording):** acceptance is machine-verifiable — `scripts/verify_acceptance.py` actually executes the criteria with `verify` and writes exit codes and output excerpts into `.code-factory/state/acceptance.md`. Exit 0 is possible only on SUCCESS: at least one criterion with `verify`, all criteria MET, baseline proven; criteria without `verify` are marked `derived`/`unverified` and are not evidence. STALE evidence or a degraded baseline lowers the verdict to DEGRADED; SUCCESS without regression evidence is impossible.
<!-- factory-rule: verified-acceptance end -->
<!-- factory-rule: vaccination begin -->
**Vaccination (canonical wording):** a bug found AFTER the task's acceptance first gets a regression test that reproduces it (the test fails on the current code), and only then the fix. A fix without a reproducing test is not accepted, and the test itself stays in the suite as a vaccine against recurrence. The code reviewer checks that every post-acceptance fix has such a test and counts its absence as a finding of severity ≥ major.
<!-- factory-rule: vaccination end -->

- **Evidence ledger + quotes**: test and review evidence is signed with the working-tree
  fingerprint (`scripts/evidence_ledger.py`) and accepted only while FRESH; every quote a
  diagnostician or a reviewer asserts is re-checked verbatim with `scripts/verify_quotes.py`.
<!-- factory-rule: evidence-ledger begin -->
**Evidence ledger and quotes (canonical wording):** every piece of evidence (baseline, tests, review) is signed with the working-tree fingerprint via `scripts/evidence_ledger.py` and is accepted only with FRESH status; STALE evidence (files changed after signing) does not count as acceptance. Every quote from the reviewer, diagnostician or advisor is re-checked verbatim by `scripts/verify_quotes.py` (exact substring, only CRLF→LF is normalized). An unconfirmed quote is marked UNTRUSTED and does not affect the verdict.
<!-- factory-rule: evidence-ledger end -->

- **Environment pre-flight**: probe the real machine first with `scripts/factory_preflight.py
  --out .code-factory/state/preflight.json` (the python command that actually works, git, bash/sh,
  the OS, the secondary-model env) and emit every command for the capabilities actually found —
  this closes the python3-vs-py mismatch on Windows.
<!-- factory-rule: preflight begin -->
**Environment pre-flight (canonical wording):** before the first commands the factory probes the real environment via `scripts/factory_preflight.py --out .code-factory/state/preflight.json` — a working python command (`python`/`python3`/`py`), git, bash/sh, OS and `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`. Further commands are emitted for the FOUND capabilities, so a guess about `python3` on Windows does not break the run. A missing secondary model does not stop the run, it yields `models_warning` in pipeline.yaml and report.md.
<!-- factory-rule: preflight end -->

- **Handoff briefing**: every subagent delegation uses `references/handoff-briefing.md` (files by
  path, never pasted content; read-only roles get the no-edits suffix), and every subagent returns
  a concise structured result with artifact paths.
<!-- factory-rule: handoff-briefing begin -->
**Briefing of every delegation (canonical wording):** every delegation to a subagent is a self-contained briefing per `references/handoff-briefing.md` (Task / Context / relevant files BY PATH, without inlining their contents / what has already been tried and why it failed). Only the main agent writes files; read-only roles (analyzer, reviewer, security-auditor, diagnostician, advisor) carry the "no edits" suffix. The subagent returns a compact structured result with paths to artifacts, not a retelling of the context.
<!-- factory-rule: handoff-briefing end -->


---
name: code-factory
description: Autonomous code factory that accepts business tasks in plain language from non-technical users, analyzes the project, plans changes, asks only business-logic questions, obtains plan approval, then implements code and runs integration / regression / business tests with deterministic error routing and LLM diagnosis on failure, checkpoint/resume, and rollback, plus a mandatory code-review gate before acceptance, finally validating acceptance criteria. Works with any programming language or combination of languages. Use when the user says "run the code factory", "solve this business task", "implement this feature", "fix this bug", "build this project", "review this code", or provides a business task file (task.yaml) / description.
type: flow
---
<!-- code-factory-version: 12.5.1 -->

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
- `assets/task-template.yaml` — business task template (Phase 0)

## Runtime state (inside the project)

All runtime artifacts live in `.code-factory/`:

- `state/` — parsed task, plan, pipeline.yaml (checkpoint/resume), acceptance
- `backups/` — backups of files before modification
- `manifest.json` — list of changed / created files (used for rollback)
- `logs/` — baseline, errors.md, diagnostic.md, test-results.md

The portable long-term memory lives in the committable `memory/` directory (NOT ignored, travels
with the project):

- `memory/change-log.md` — append-only journal, one entry per completed run; single writer: the
  main agent at the end of each task
- `memory/summary.md` — compressed summary (current state + key decisions + recent history),
  compacted from the journal when it exceeds the threshold

The factory may create any files, skills, scripts or plugins inside the project that are needed to solve the task. The factory must keep the total token spend minimal: use subagents for heavy context (analysis, coding, testing, diagnosis), return only concise structured results, and avoid loading large files into the main context.

```mermaid
flowchart TD
    A([BEGIN]) --> B[Accept the task: read the user's message or task.yaml. Extract: title, repo_path, description, user_story (optional), mode (hitl/auto), task_type (implement default | review | refactor | security_audit), acceptance_criteria, commit_exclude, models, reference_docs, reference_skills. There is NO priority field — every task is HIGH by default. Save the parsed task to .code-factory/state/task.yaml. Read the long-term memory (memory/summary.md + recent memory/change-log.md entries) so project history is not re-derived. If no task file exists, treat the user's message as the task. Checkpoint: if .code-factory/state/pipeline.yaml exists and the task is unchanged, resume from the recorded phase.]
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
    TT -->|review| CR0[Run factory-code-reviewer over the WHOLE codebase (or the task's listed files) following references/code-review.md. Write the verdict to .code-factory/logs/code-review.md. On request_changes the rework list becomes the plan.]
    CR0 --> CRV0{Review verdict?}
    CRV0 -->|approve| W
    CRV0 -->|request_changes| G
    TT -->|implement| G
    TT -->|refactor| RF[Refactor flow: baseline the existing test suite, plan structural-only tasks, implement with factory-refactorer, verify 100% of existing tests pass unchanged — any behavior change is a critical error and rolls back automatically. See references/refactoring.md.]
    RF --> L
    TT -->|security_audit| SA[Security audit flow: detect artifact types, run only the relevant checks with factory-security-auditor (read-only), write reports + a generated fix-task file. No code change and no auto-fixing. See references/security-audit.md.]
    SA --> W
    G -->|hitl| H[Business test definition: ask the user via AskUserQuestion for 1 a concrete business scenario (user story), 2 which configs and input data to run, 3 expected business results. Only business-logic questions. Store answers in the plan.]
    H --> I[Present the full plan for approval: write it to the plan file and call EnterPlanMode then ExitPlanMode. Wait for approval or revision comments.]
    I --> J{Plan approved?}
    J -->|Revise| F
    J -->|Approve| K
    G -->|auto| L[Make reasonable business assumptions from the task description. Record every assumption explicitly in the plan.]
    L --> PF[Pre-flight: git check — if the project has no git repository, run git init. Working tree must be clean: auto-untrack build artifacts (target/, node_modules/, __pycache__/ etc.) and commit factory artifacts (AGENTS.md). Record git HEAD and git status in .code-factory/state/. Also verify model setup: for the new CLI check that KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 is exported (otherwise secondary-model split is INACTIVE); record a models_warning in pipeline.yaml if missing.]
    PF --> K[Backup the current state: copy every file that will be modified to .code-factory/backups/ preserving relative paths. Track created files in .code-factory/manifest.json. Write the checkpoint .code-factory/state/pipeline.yaml after every phase for resume.]
    K --> M[Implement: launch factory-coder subagents for the plan tasks, respecting dependencies; independent tasks can run in parallel. Models are configured per subagent via model_preference in their agent .md files. Do NOT pass a concrete model name to the Agent tool — it is not supported. After each subagent returns, log the used model for each role to pipeline.yaml models_used. Each coder follows the plan and the project coding style in an isolated context. After every change, update manifest.json. Also create any new skills/scripts/plugins defined in the plan.]
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
    RR2 -->|diagnostician| DG[Run the factory-diagnostician subagent: deep LLM analysis of the error output and attempt history. Write the report to .code-factory/logs/diagnostic.md.]
    DG --> DR{Diagnostician recommendation}
    DR -->|coder| P
    DR -->|ba| P2
    DR -->|planner| P2
    DR -->|infrastructure| AI
    DR -->|human| U2[Show the user the diagnosis and ask how to proceed.]
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
    CRV -->|request_changes| RCR[Record the reviewer retry counter in pipeline.yaml. If the reviewer budget is not exhausted, pass the rework list to the coder and re-run integration + regression tests (business tests only if business logic changed), then re-review. If budget is exhausted: in hitl mode ask the user, in auto mode record the unresolved findings in report.md and continue.]
    RCR --> M
    CRV -->|approve| W[Acceptance check: verify every acceptance_criteria item against the actual results and document evidence for each. Save the verification to .code-factory/state/acceptance.md.]
    W --> X{All criteria met?}
    X -->|No| RR
    X -->|Yes| DOC{task_type: implement или refactor?}
    DOC -->|Да| DOC2[Документирование: вызвать factory-documenter (secondary) по .code-factory/manifest.json; обновить только doc-комментарии и .md файлы; валидатор validate_documentation.py с бюджетом 1 retry; при исчерпании — документационный долг в отчёт прогона, фабрика продолжает.]
    DOC2 --> VER1[Версия — шаг 1: детерминированная матрица version_manager.py suggest → предложить тип major|minor|patch|none с объяснением]
    VER1 --> VER2[Версия — шаг 2: код-ревьюер валидирует предложенный тип, может переопределить с объяснением (не с нуля)]
    VER2 --> VER3[Версия — шаг 3: применить bump|set + sync, validate exit 0; коммит с префиксом v<версия>: в одном коммите с изменениями]
    VER3 --> Y
    DOC -->|Нет (review/security_audit)| Y
    Y[Finish: remove backups, produce the final report (what changed, test results, business results, acceptance evidence, models_used per role). Regenerate AGENTS.md if structure/stack/entry points changed, then commit AGENTS.md + memory/ to the feature branch respecting commit_exclude. Append one entry to memory/change-log.md (single writer: the main agent) and compact the journal into memory/summary.md when over the threshold. Update project documentation if the task requires it. Write the self-contained .code-factory/report.md with the full history (task, plan, errors, diagnosis, results, manifest, models_used). Generate .code-factory/report_code_changes.md next to it with the scripts/gen_code_changes_report.py script (was-became per changed line). Present the report to the user.]
    Y --> Z([END])
```

Rules that always apply:

- **Task format**: the task has `title`, `repo_path`, `description`, optional `user_story`,
  `mode`, `task_type` (`implement` | `review` | `refactor` | `security_audit`),
  `acceptance_criteria`, `commit_exclude`, `models`, and the two optional knowledge fields
  `reference_docs` (list of `{path, skill}` documents to convert into skills) and
  `reference_skills` (names of existing skills to reuse). There is NO `priority` field — every
  task is HIGH by default and the factory never prioritizes.
- **User story**: when present, `user_story` is analyzed and used by the analyzer, planner and
  coder — it disambiguates the business intent and drives decisions.
- **Language-agnostic**: detect the stack; never assume a language. The factory serves any
  project type (frontend, backend, CLI, library, green-field) — verification is framework-agnostic.
- **Token efficiency**: parallel subagents, isolated contexts, concise results, progressive
  reference loading, and deterministic error routing (zero-LLM) before LLM diagnosis.
- **Rollback safety**: every test failure triggers error routing → rollback before retrying.
- **Business-first**: communicate with the user only in business terms.
- **Artifacts first**: before touching any source file, materialize into `.code-factory/` the
  parsed task, the plan, the baseline, the backup of changed files and the manifest. Do not keep
  factory state only in the conversation.
- **Repo-mismatch gate**: if the task references files, symbols, configs or data that are absent
  in the repo, stop in hitl mode and ask the user for them (or record an assumption in auto
  mode). Never silently skip missing inputs.
- **Escalation ladder**: deterministic regex → Diagnostician (LLM) → Human (HITL) → FAILED with
  a full log. The factory never crashes silently.
- **Retry budgets**: coder=1, ba=2, planner=2, diagnostician=1, infrastructure=3,
  reviewer=2. When a role's budget is exhausted, escalate to the Diagnostician (for test/code
  failures) or, for the reviewer, to the human in hitl mode / a recorded unresolved-findings note
  in auto mode — never loop forever.
- **Checkpoint/resume**: after every phase write `.code-factory/state/pipeline.yaml` (current
  phase, retry counters, plan fingerprint). On restart, resume from the recorded phase.
- **Report**: on finish (success OR FAILED) write `.code-factory/report.md` — one
  self-contained file with the full history (task, plan, errors, diagnosis, results) so it can
  be handed to the factory developer for analysis without reading the whole `.code-factory/`.
  Also write `.code-factory/report_code_changes.md` (next to it) via
  `scripts/gen_code_changes_report.py` — a deterministic was-became diff report of the commit
  (zero LLM tokens).
- **AGENTS.md (single source of truth) + fingerprint**: the factory generates `AGENTS.md` with
  exactly 8 `##` sections and embeds a deterministic structural fingerprint on its first line
  (`scripts/project_fingerprint.py`). At the start of a task, if the embedded fingerprint matches
  the recomputed one, skip regeneration; otherwise regenerate. At the end of a task, regenerate
  if structure/stack/entry points changed, then commit it. There is no init step.
- **Long-term memory (`memory/`)**: committable, never ignored. Single writer = the main agent,
  which appends one entry to `memory/change-log.md` at the end of every task (success OR FAILED)
  and compacts old entries into `memory/summary.md` when the journal exceeds 50 entries (keeping
  the last 20). Every entry MUST include an `unfinished` section (even if it is the explicit
  "нет незавершённых элементов" marker) and a `factory_version` field; each unfinished item has
  `item`, `reason`, `severity` (critical|warning|info) and `follow_up` (true|false). Compaction
  MUST preserve items with severity=critical or follow_up=true. Legacy entries without the
  `unfinished`/`factory_version` keys validate with a warning, never an error. Verify with
  `scripts/check_factory_model.py` (8 sections + fingerprint + memory format).
- **Documentation (factory-documenter)**: after every successful `implement` or `refactor` run,
  the main agent invokes the `factory-documenter` subagent (secondary model) with the run
  manifest; it updates ONLY doc-comments and `.md` files, never code/tests/configs, and validates
  its work with `scripts/validate_documentation.py` (retry budget 1). If validation is exhausted,
  the documentation debt is recorded in the run report and the factory continues. It is skipped
  for `review` and `security_audit`.
- **Versioning (single source of truth)**: `VERSION` (one line `X.Y.Z`) is the only source of
  truth; all other files sync FROM it via `scripts/version_manager.py` (get/bump/sync/validate/
  set/suggest, stdlib only). After a successful `implement`/`refactor` run the version type is
  chosen by the deterministic matrix (`suggest`), validated by the code reviewer (which may
  override it with an explanation, never from scratch), then applied with `bump`/`set` + `sync`
  and committed in the SAME commit with a message prefixed `v<версия>: `. `review`/`security_audit`
  tasks do NOT change the version.
- **Models**: models are configured per role in the agent files themselves —
  `model_preference: primary|secondary` in each sub-agent `.md`, resolved against `config.toml`
  `default_model`/`[secondary_model]`. Do NOT pass a concrete model name to the Agent tool (not
  supported). Log the actual model used for each role to `.code-factory/state/pipeline.yaml`
  (`models_used`) and include it in `report.md` so the run is auditable. The main agent's own
  model is the session model (set via `kimi -m` / `/model`); record it too. The secondary model
  is only used when the env var `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` is exported — during
  pre-flight check it (Bash: `echo "${KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL:-unset}"`) and if
  missing write `models_warning: "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL is not set —
  coder/tester subagents will use the primary model"` to pipeline.yaml and include the warning
  in report.md. When a role's model is a Kimi (K3) or Qwen model, route it per
  `references/providers.md` (alias → provider config) and handle its errors per
  `references/error-routing.md` §1.1.
- **Commit policy**: respect `commit_exclude` from the task — never commit matching files
  (e.g. personal strategy code); stage everything EXCEPT the excluded patterns.
- **Git-native**: if the project has no git repository, run `git init`. All changes flow through
  git (feature branch per task), with rollback to the base commit on failure.

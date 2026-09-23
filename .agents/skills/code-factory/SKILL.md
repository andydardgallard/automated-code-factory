---
name: code-factory
description: Autonomous code factory that accepts business tasks in plain language from non-technical users, analyzes the project, plans changes, asks only business-logic questions, obtains plan approval, then implements code and runs integration / regression / business tests with deterministic error routing and LLM diagnosis on failure, checkpoint/resume, and rollback, plus a mandatory code-review gate before acceptance, finally validating acceptance criteria. Works with any programming language or combination of languages. Use when the user says "run the code factory", "solve this business task", "implement this feature", "fix this bug", "build this project", "review this code", or provides a business task file (task.yaml) / description.
type: flow
---
<!-- code-factory-version: 12.10.1 -->

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
    A([BEGIN]) --> B[Accept the task: read the user's message or task.yaml. Extract: title, repo_path, description, user_story (optional), mode (hitl/auto), task_type (implement default | review | refactor | security_audit), acceptance_criteria (each criterion may carry verify and derived), business_tests (scenario, config, expected_results), commit_exclude, models, reference_docs, reference_skills. There is NO priority field — every task is HIGH by default. Save the parsed task to .code-factory/state/task.yaml. Read the long-term memory of the TARGET project from repo_path (memory/summary.md + recent memory/change-log.md entries) — the memory of the project, NOT of the factory; if memory/ is absent (first contact with the project), create it first via memory_project.py init --repo <deployment root> --project <basename of repo_path> (memory/ always lives in the deployment root; the name is pinned in the summary's project: declaration) — so that project's history is not re-derived. If no task file exists, treat the user's message as the task. Checkpoint: if .code-factory/state/pipeline.yaml exists and the task is unchanged, resume from the recorded phase.]
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
    X -->|Yes| DOC{task_type: implement или refactor?}
    DOC -->|Да| DOC2[Документирование: вызвать factory-documenter (secondary) по .code-factory/manifest.json; обновить только doc-комментарии и .md файлы; валидатор validate_documentation.py с бюджетом 1 retry; при исчерпании — документационный долг в отчёт прогона, фабрика продолжает.]
    DOC2 --> VER1[Версия — шаг 1: детерминированная матрица version_manager.py suggest → предложить тип major|minor|patch|none с объяснением]
    VER1 --> VER2[Версия — шаг 2: код-ревьюер валидирует предложенный тип, может переопределить с объяснением (не с нуля)]
    VER2 --> VER3[Версия — шаг 3: применить bump|set + sync, validate exit 0; коммит с префиксом v<версия>: в одном коммите с изменениями]
    VER3 --> Y
    DOC -->|Нет (review/security_audit)| Y
    Y[Finish: remove backups, produce the final report (what changed, test results, business results, acceptance evidence, models_used per role). Regenerate AGENTS.md if structure/stack/entry points changed, then commit AGENTS.md + memory/ to the feature branch respecting commit_exclude. Append one entry to memory/change-log.md (single writer: the main agent) carrying the mandatory project field (project: name of the target project, pinned in summary.md's project: declaration = basename of repo_path) and compact the journal into memory/summary.md when over the threshold; summary.md declares project and repo_path right after the canonical marker. Update project documentation if the task requires it. Write the self-contained .code-factory/report.md with the full history (task, plan, errors, diagnosis, results, manifest, models_used). Generate .code-factory/report_code_changes.md next to it with the scripts/gen_code_changes_report.py script and --run-id <run_id> (was-became per changed line; the run id stamps the report as belonging to this run). Present the report to the user.]
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
**Формат задачи (каноническая формулировка):** задача несёт `title`, `repo_path`, `description`, опционально `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (критерий может нести `verify: <команда>` и `derived: true`), `business_tests` (сценарий, конфиги, ожидаемые бизнес-результаты), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. Поля `priority` НЕТ — все задачи по умолчанию high, фабрика их не приоритизирует. Отсутствие обязательного поля — ошибка разбора задачи, а не повод домыслить его по ходу прогона.
<!-- factory-rule: task-format end -->

- **User story**: when present, `user_story` is analyzed and used by the analyzer, planner and
  coder — it disambiguates the business intent and drives decisions.
- **Plan committee (double rejection)**: in hitl mode the first revision of a rejected plan goes
  back to planning; a SECOND rejection is a double rejection — a second, independent
  `factory-planner` subagent from a contrasting model family builds an alternative plan (it never
  sees the rejected one) and the deterministic `scripts/plan_arbiter.py` merges both plans and
  lists the divergences, which the user decides.
<!-- factory-rule: plan-committee begin -->
**Committee при двойном rejection плана (каноническая формулировка):** если пользователь дважды отклонил план (hitl, ветка Revise), главный агент запускает второго независимого planner-сабагента из контрастного семейства моделей, который строит альтернативный план по той же задаче и накопленным замечаниям пользователя; детерминированный `scripts/plan_arbiter.py` (stdlib) сравнивает оба плана по машиночитаемым секциям (DAG-задачи, verify-команды, риски, бизнес-тесты) и формирует merged-вариант со списком расхождений; пользователю представляется merged-план и расхождения, дальнейшие правки идут уже по нему.
<!-- factory-rule: plan-committee end -->
- **Language-agnostic**: detect the stack; never assume a language. The factory serves any
  project type (frontend, backend, CLI, library, green-field) — verification is framework-agnostic.
- **Token efficiency**: parallel subagents, isolated contexts, concise results, progressive
  reference loading, and deterministic error routing (zero-LLM) before LLM diagnosis.
- **Rollback safety**: every test failure triggers error routing → rollback before retrying.
<!-- factory-rule: rollback-on-retry begin -->
**Откат перед ретраем (каноническая формулировка):** каждый провал тестов или сборки сначала маршрутизируется детерминированно (`references/error-routing.md`), затем состояние откатывается: файлы восстанавливаются из `.code-factory/backups/`, созданные фабрикой файлы удаляются, состояние git приводится к зафиксированному. Только после отката ошибка отдаётся роли-исполнителю — иначе повторный прогон идёт по уже испорченному состоянию. Инфраструктурные авто-фиксы (окружение, зависимости) код не откатывают.
<!-- factory-rule: rollback-on-retry end -->

- **Business-first**: communicate with the user only in business terms.
- **Artifacts first**: before touching any source file, materialize into `.code-factory/` the
  parsed task, the plan, the baseline, the backup of changed files and the manifest. Do not keep
  factory state only in the conversation.
<!-- factory-rule: artifacts-first begin -->
**Артефакты до изменений (каноническая формулировка):** фабрика не правит ни одного исходника, пока в `.code-factory/` не материализованы `state/task.yaml` (разобранная задача), `state/plan.md` (план), `logs/baseline.md` (базовый прогон тестов), `backups/` (бэкап каждого файла, который будет изменён, с сохранением относительных путей) и `manifest.json` (изменённые и созданные файлы). Состояние прогона живёт на диске, а не в переписке: неперсистентное знание теряется при рестарте и делает откат невозможным.
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
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- factory-rule: review-gate-policy end -->
<!-- factory-rule: retry-budgets begin -->
**Бюджеты ретраев (каноническая формулировка):** у каждой роли свой бюджет повторов — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; счётчики ведутся в `.code-factory/state/pipeline.yaml` (`retry_counters`). Исчерпанный бюджет не продлевается: прогон эскалируется по лестнице детерминированный regex → Diagnostician (LLM) → Advisor (LLM, secondary модель, контрастное семейство, бюджет 1) → Human (hitl) → FAILED с полным логом. Фабрика не зацикливается, не смягчает тесты ради зелёного прогона и не падает молча.
<!-- factory-rule: retry-budgets end -->
<!-- factory-rule: checkpoint-resume begin -->
**Checkpoint/resume (каноническая формулировка):** после каждой фазы главный агент пишет `.code-factory/state/pipeline.yaml` (фаза, статус, затронутые файлы, ожидаемое решение, resume-hint, run_id, время) — состояние прогона живёт на диске, а не в контексте. При рестарте фабрика сверяет фиксатор плана и, если задача не изменилась, продолжает с ЗАПИСАННОЙ фазы, а не с начала. `resume` восстанавливает счётчики ретраев, поэтому исчерпанные бюджеты не обнуляются рестартом.
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
**Идентификатор прогона (каноническая формулировка):** в начале прогона детерминированно вычисляется `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` (`scripts/run_id.py`) и проставляется в `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` и в memory-запись прогона. Один прогон — один идентификатор, по нему артефакты связываются между собой. `scripts/run_id.py check` находит артефакты прогона без `run_id` и перечисляет их.
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
  "нет незавершённых элементов" marker) and a `factory_version` field; each unfinished item has
  `item`, `reason`, `severity` (critical|warning|info) and `follow_up` (true|false).
  `memory/summary.md` MUST declare the project with `project:`/`repo_path:` lines right after the
  canonical marker. Compaction MUST preserve items with severity=critical or follow_up=true.
  Legacy entries without
  `project:` or the `unfinished`/`factory_version` keys validate with a warning, never an error;
  entries of DIFFERENT projects in one journal are an error (caught by
  `scripts/check_factory_model.py` and `memory_project.py check`). Verify with
  `scripts/check_factory_model.py` (8 sections + fingerprint + memory format).
<!-- factory-rule: memory-ownership begin -->
**Владение памятью (каноническая формулировка):** одна память принадлежит ровно одному проекту — тому, что назван в `repo_path` задачи; каталог `memory/` живёт в КОРНЕ РАЗВЁРТЫВАНИЯ, базовое имя проекта = basename разрешённого `repo_path` и фиксируется в объявлении `project:` сводки. Единственный писатель — главный агент: одна запись в `memory/change-log.md` на прогон, компакция в `memory/summary.md` при пороге 50 записей (остаются последние 20, элементы severity=critical и follow_up=true сохраняются всегда). Записи разных проектов в одном журнале — ошибка (`check_factory_model.py`, `memory_project.py check`), записи без `project:` — legacy (предупреждение, не ошибка). История разработки самой фабрики в память целевого проекта не попадает.
<!-- factory-rule: memory-ownership end -->
<!-- factory-rule: memory-provenance begin -->
**Происхождение записей памяти (каноническая формулировка):** запись считается записью формата v2, если её `factory_version` новее 12.8.0 ИЛИ она уже несёт v2-поле (`run_id` или метку происхождения) — так полумигрированная запись тоже проверяется; у такой записи обязательны `run_id` формата `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) и метки происхождения в полях `decisions` и `results`: `[verified: <evidence>]` — утверждение подтверждено доказательством прогона (лог, acceptance, цитата), `[inferred]` — вывод без прямого доказательства. Запись формата v2 без `run_id` или без меток в этих полях — ошибка формата (`memory_project.py check`, `check_factory_model.py`), тогда как записи, написанные фабрикой не новее 12.8.0 и не несущие v2-полей, и legacy-записи без `project:` дают только предупреждение. Метка `[verified: ...]` обязана ссылаться на конкретное доказательство (команда/тест/лог); валидаторы проверяют наличие и форму метки.
<!-- factory-rule: memory-provenance end -->

- **Documentation (factory-documenter)**: after every successful `implement` or `refactor` run,
  the main agent invokes the `factory-documenter` subagent (secondary model) with the run
  manifest; it updates ONLY doc-comments and `.md` files, never code/tests/configs, and validates
  its work with `scripts/validate_documentation.py` (retry budget 1). If validation is exhausted,
  the documentation debt is recorded in the run report and the factory continues. It is skipped
  for `review` and `security_audit`.
<!-- factory-rule: documentation begin -->
**Документирование (каноническая формулировка):** после каждого успешного `implement`/`refactor` главный агент вызывает сабагента `factory-documenter` (secondary) с манифестом прогона; он обновляет ТОЛЬКО doc-комментарии и `.md` файлы и никогда код, тесты или конфиги. Свою работу он валидирует `scripts/validate_documentation.py` с бюджетом 1 retry; при исчерпании бюджета документационный долг фиксируется в отчёте прогона, и фабрика продолжает. Для `review`/`security_audit` документирование не вызывается.
<!-- factory-rule: documentation end -->

- **Versioning (single source of truth)**: `VERSION` (one line `X.Y.Z`) is the only source of
  truth; all other files sync FROM it via `scripts/version_manager.py` (get/bump/sync/validate/
  set/suggest, stdlib only). After a successful `implement`/`refactor` run the version type is
  chosen by the deterministic matrix (`suggest`), validated by the code reviewer (which may
  override it with an explanation, never from scratch), then applied with `bump`/`set` + `sync`
  and committed in the SAME commit with a message prefixed `v<версия>: `. `review`/`security_audit`
  tasks do NOT change the version.
<!-- factory-rule: versioning begin -->
**Версионирование (каноническая формулировка):** `VERSION` (одна строка `X.Y.Z`) — единый источник истины, все остальные файлы синхронизируются ИЗ него через `scripts/version_manager.py`. Тип версии предлагает детерминированная матрица (`suggest`), валидирует код-ревьюер (может переопределить с объяснением, но не выбирает с нуля), применяет `bump`/`set` + `sync` + `validate` exit 0. Коммит версии идёт в ОДНОМ коммите с изменениями и несёт префикс `v<версия>: `. Задачи `review`/`security_audit` версию НЕ меняют.
<!-- factory-rule: versioning end -->

- **Models**: the main agent PASSES the model explicitly to the Agent tool (`model:` is supported
  by the CLI) following the task's `models` matrix and the generator≠judge rule of
  `references/providers.md` (coder/tester and reviewer/diagnostician/advisor come from different
  model families). The per-role `model_preference: primary|secondary` in each sub-agent `.md` is
  the FALLBACK, resolved against `config.toml` `default_model`/`[secondary_model]` for roles the
  task does not name. Log the actual model used for each role to `.code-factory/state/pipeline.yaml`
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
**Модели: генератор ≠ судья (каноническая формулировка):** главный агент передаёт модель явно в Agent tool (`model:`) по матрице `models` задачи и правилу generator≠judge: coder/tester и reviewer/diagnostician/advisor берутся из разных семейств моделей. `model_preference: primary|secondary` в `.md` сабагента — только FALLBACK для ролей, не названных задачей. Фактические модели ролей логируются в `.code-factory/state/pipeline.yaml` (`models_used`) и в `report.md`; secondary-модель работает только при `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, иначе фабрика пишет `models_warning` и продолжает на primary.
<!-- factory-rule: models-generator-ne-judge end -->

- **Commit policy**: respect `commit_exclude` from the task — never commit matching files
  (e.g. personal strategy code); stage everything EXCEPT the excluded patterns.
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (каноническая формулировка):** файлы, попадающие под шаблоны `commit_exclude` задачи, НИКОГДА не коммитятся — ни в одном коммите прогона, включая коммит версии и памяти. Стейджится всё, кроме исключённых шаблонов; код-ревьюер проверяет гигиену коммита и попадание исключённого файла в индекс считает замечанием severity ≥ major.
<!-- factory-rule: commit-exclude end -->

- **Git-native**: if the project has no git repository, run `git init`. All changes flow through
  git (feature branch per task), with rollback to the base commit on failure.
<!-- factory-rule: git-native begin -->
**Git-native (каноническая формулировка):** если в проекте нет git-репозитория, фабрика делает `git init` — отдельного init-шага в CLI нет. Все изменения идут через git: на задачу создаётся feature-ветка, базовый коммит и его HEAD фиксируются в `.code-factory/state/`, при неудаче прогон откатывается к базовому коммиту. Рабочее дерево держится чистым: build-артефакты авто-унтрекаются, артефакты фабрики коммитятся.
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
**Шард-протокол (каноническая формулировка):** whole-repo ревью и security_audit никогда не помещаются в один контекст: `scripts/repo_inventory.py shards --max-lines 20000` режет репозиторий на шарды ≤20000 строк, каждый шард обрабатывает свой параллельный сабагент (ревьюер или аудитор) и пишет один findings-файл. Итог даёт детерминированный `scripts/merge_findings.py` (дедупликация, сортировка по severity, merged verdict), и канонический review-гейт применяется к MERGED findings, а не к отдельным шардам. Обычная задача `implement` ревьюится по diff и шардирования не требует.
<!-- factory-rule: shard-protocol end -->

- **Verified acceptance**: acceptance is machine-checked with `scripts/verify_acceptance.py` —
  criteria carrying `verify` are executed for real and their exit codes land in
  `state/acceptance.md`, criteria without `verify` are only `derived`/`unverified`; the exit code
  is 0 only for SUCCESS, a degraded baseline or STALE ledger evidence gives DEGRADED, and SUCCESS
  without regression proof is impossible.
<!-- factory-rule: verified-acceptance begin -->
**Проверяемая приёмка (каноническая формулировка):** приёмка машинно-проверяемая — `scripts/verify_acceptance.py` реально исполняет критерии с `verify` и пишет exit-коды и выдержки вывода в `.code-factory/state/acceptance.md`. Exit 0 возможен только при SUCCESS: хотя бы один критерий с `verify`, все критерии MET, baseline доказан; критерии без `verify` помечаются `derived`/`unverified` и доказательством не являются. STALE-доказательства или деградированный baseline понижают вердикт до DEGRADED; SUCCESS без регрессионного доказательства невозможен.
<!-- factory-rule: verified-acceptance end -->
<!-- factory-rule: vaccination begin -->
**Вакцинация (каноническая формулировка):** баг, найденный ПОСЛЕ приёмки задачи, сначала получает регрессионный тест, который его воспроизводит (тест падает на текущем коде), и только потом исправление. Фикс без воспроизводящего теста не принимается, а сам тест остаётся в наборе как вакцина против повторения. Код-ревьюер проверяет наличие такого теста у каждого пост-приёмочного фикса и считает его отсутствие замечанием severity ≥ major.
<!-- factory-rule: vaccination end -->

- **Evidence ledger + quotes**: test and review evidence is signed with the working-tree
  fingerprint (`scripts/evidence_ledger.py`) and accepted only while FRESH; every quote a
  diagnostician or a reviewer asserts is re-checked verbatim with `scripts/verify_quotes.py`.
<!-- factory-rule: evidence-ledger begin -->
**Реестр доказательств и цитаты (каноническая формулировка):** каждое доказательство (baseline, тесты, ревью) подписывается отпечатком рабочего дерева через `scripts/evidence_ledger.py` и принимается только со статусом FRESH; доказательство STALE (после подписи файлы изменились) приёмкой не считается. Каждая цитата ревьюера, диагноста или советника перепроверяется дословно `scripts/verify_quotes.py` (точная подстрока, нормализуется только CRLF→LF). Неподтверждённая цитата помечается UNTRUSTED и на вердикт не влияет.
<!-- factory-rule: evidence-ledger end -->

- **Environment pre-flight**: probe the real machine first with `scripts/factory_preflight.py
  --out .code-factory/state/preflight.json` (the python command that actually works, git, bash/sh,
  the OS, the secondary-model env) and emit every command for the capabilities actually found —
  this closes the python3-vs-py mismatch on Windows.
<!-- factory-rule: preflight begin -->
**Pre-flight окружения (каноническая формулировка):** перед первыми командами фабрика пробует реальное окружение через `scripts/factory_preflight.py --out .code-factory/state/preflight.json` — рабочая python-команда (`python`/`python3`/`py`), git, bash/sh, ОС и `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`. Дальнейшие команды эмитятся под НАЙДЕННЫЕ capabilities, поэтому догадка о `python3` на Windows не ломает прогон. Отсутствие secondary-модели прогон не останавливает, а даёт `models_warning` в pipeline.yaml и report.md.
<!-- factory-rule: preflight end -->

- **Handoff briefing**: every subagent delegation uses `references/handoff-briefing.md` (files by
  path, never pasted content; read-only roles get the no-edits suffix), and every subagent returns
  a concise structured result with artifact paths.
<!-- factory-rule: handoff-briefing begin -->
**Брифинг каждой делегации (каноническая формулировка):** каждая делегация сабагенту — самодостаточный брифинг по `references/handoff-briefing.md` (Task / Context / релевантные файлы ПУТЯМИ, без вставки содержимого / что уже пробовали и почему не сработало). Файлы пишет только главный агент; read-only роли (analyzer, reviewer, security-auditor, diagnostician, advisor) идут с суффиксом «без правок». Сабагент возвращает сжатый структурированный результат с путями к артефактам, а не пересказ контекста.
<!-- factory-rule: handoff-briefing end -->


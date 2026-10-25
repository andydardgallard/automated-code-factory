# Project Summary — Code Factory

<!-- code-factory-memory: summary -->
project: repo
repo_path: .

Сжатая сводка проекта. Сворачивается из старых записей `memory/change-log.md` при компакции
(порог 50 записей) и читается в начале каждой задачи, чтобы не выводить историю проекта заново.

## Current state
Factory v12.14.3 — the three most recent runs were REPORT-ONLY REVIEWS and none touched the
product tree.
Latest run: review (run_id 20261025-634bc01b, task-review-memory.yaml, hitl), report-only,
acceptance SUCCESS (7 verify criteria MET, 2 derived, regression pass, ledger FRESH): merged
verdict request_changes, 20 findings (2 critical, 11 major, 7 minor), report in
`.code-factory/report.md`, findings in `.code-factory/logs/code-review.md`. Its decision
question — is the long-term memory real end to end — is answered: the journal format v2, the
`closed:`/`evidence:` fold and the ownership validator work, while the per-run write guarantee,
the 50/20 compaction, the `## Current state` actuality beyond one WARN, and the precedent index
are prose or unwired; the two named validators diverge on six axes; `memory_project.py check`
and `check_factory_model.py` are red on this repository as found. The run also exposed and
recorded a model-precedence defect: the canonical generator≠judge rule was applied against the
task's explicit `models.reviewer` (a kimi-k3 pass that produced no verdict), and the task is
authoritative — the precedence must be written once and pinned.
Previous run: review (run_id 20261025-d412a454, task-review-workflow.yaml): a `task_type:
review` run is NOT report-only in the flow — the review verdict `CRV0 -->|request_changes| G`
(SKILL.md:102) reaches the implement entry and the acceptance-failure edge `X -->|No| RR`
(SKILL.md:164) reaches a coder for every task type; 18 findings.
Run before that: review (run_id 20261025-a32464ec, an earlier task-review-memory.yaml), NOT
ACCEPTED — its unrequested 18-file rework was stopped by the owner and rolled back (tree back at
d87592a; the diff is kept only as `.code-factory/rework-review-memory.patch`).
Latest delivered product: v12.14.3 at commit 692e518 (unchanged by all three reviews).
Open backlog: 8 items (39 closed with evidence) — the flow's review-to-implement routing
(critical), the model-precedence defect (critical, new), the self-reported model attribution
(new), the memory owner mismatch, the half-accepted backlog record kind, the Finish-vs-actuality
contradiction, the unwired compaction and precedent index, and the open version_manager.py
Rust-workspace item (now with mechanism evidence: `validate` prints PASS on a divergent
Cargo.toml).
Rulebook: 25 rules, 100 carriers, byte-identical (`check_factory_rules.py` exit 0). Memory owner:
repo (the rule pins the basename; the migration is a pending item). Self-tests: 31 files, all
passing.

## Key decisions
- Долгосрочная память `memory/` принадлежит ОДНОМУ целевому проекту (`repo_path`); поле
  `project:` обязательно для новых записей, разные его значения в одном журнале — ошибка,
  legacy-записи без `project:` — предупреждение. История разработки самой фабрики в память
  целевого проекта не попадает.
- Память создаётся в КОРНЕ РАЗВЁРТЫВАНИЯ (каталог, переданный `prepare_factory.sh`), имя проекта
  = basename разрешённого `repo_path`; когда `repo_path` указывает на подкаталог, агент передаёт
  `--project` явно и имя фиксируется в объявлении сводки.
- Существующий AGENTS.md перезаписывается целиком (ровно 8 секций); hand-written заметки — в
  `memory/summary.md`.
- Fingerprint НЕ включает git tree SHA (иначе встроенный fingerprint устаревает сразу после
  коммита, который его коммитит).
- Порог компакции журнала — 50 записей (остаются последние 20); при компакции элементы
  unfinished с severity=critical или follow_up=true сохраняются обязательно.
- Корневой AGENTS.md самой фабрики остаётся hand-authored инструкцией (не 8-секционной моделью).
- `VERSION` — единый источник истины версии; тип версии определяет детерминированная матрица,
  валидирует ревьюер (может переопределить с объяснением); review/security_audit версию не меняют.
- Документер обновляет только doc-комментарии и `.md` (secondary-модель, валидатор, бюджет 1).

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
- 2026-09-24 — «Фабрика v6 (v12.11.0)» (feature/factory-v6-backlog-20260923, 4b6652c):
  полная очистка backlog по всей истории (32 follow_up → 0 открытых, все с evidence);
  явная классификация git stash (мутирующие → CONFIRM, list/show → ALLOW, разбор -m/--message);
  контентный fingerprint по рабочему дереву (unstaged виден); механизм актуальности памяти
  (backlog --check + closed:+evidence: + 23-е правило memory-actuality, RCA 5 звеньев);
  project-learned overlay §1.2; ps1 try/catch, sh короткая причина, .gitattributes *.sh LF;
  providers.md §5.2. Комитет планов (3 rejection → merged + выбор пользователя). v12.10.2 → v12.11.0 (minor).
- 2026-09-23 — «Фабрика v5 (v12.10.2)» (feature/factory-v5-backlog-20260923, ed62e88):
  utf8-guard во всех argparse-скриптах (action_gate --help на cp1251, кейс 16), 22-е правило
  no-shared-tree-git-mutations (6 носителей). v12.10.1 → v12.10.2 (patch).
- 2026-09-23 — «Фабрика v3 (v12.10.0)» (feature/factory-v3-backlog-20260923, 3e1a1bb):
  severity-калибровка ревьюера (precision 0.619→0.857, recall→1.000, accuracy 7/7), committee
  при двойном rejection плана (plan-committee + plan_arbiter.py + factory-planner),
  check_factory_model SKIP на корне фабрики (трёхсигнальный детектор), FTS5 precedent_index.py,
  test_run_id перепинован на fixture. v12.9.1 → v12.10.0 (minor).
- 2026-09-21 — «Развёртывание и запуск фабрики в Windows» (feature/windows-launch, 37a683e):
  Windows-версии обеих операций (`prepare_factory.ps1` + `prepare_factory.cmd`, `start.cmd`),
  паритет с bash-путём, жёсткий сбой развёртывания → exit 1 без баннера «Готово» (ожидаемые
  деградации остались нефатальными), контракты UTF-8/BOM/CRLF, самотест
  `scripts/test_windows_scripts.py`. v12.6.0 → v12.7.0 (minor).
- 2026-09-21 — «Память фабрики принадлежит целевому проекту» (feature/project-scoped-memory):
  поле `project:` в записях и объявление проекта в сводке, детекция смешения проектов,
  скрипт `memory_project.py`, инициализация памяти проекта при развёртывании, очистка памяти
  проекта get_course_downloader от истории разработки фабрики. v12.5.1 → v12.6.0 (minor).
- 2026-09-08 — «Фабрика v12.5.0» (feature/factory-v12.5.0, 123acf3): factory-documenter,
  память unfinished, reference_docs/reference_skills + skill-base, сквозное версионирование.
- 2026-09-01 — «AGENTS.md как единый источник правды + переносимая память» (main, a53ef72):
  Scout без `/init`, fingerprint, `memory/`, скрипты проверки модели, сабагенты читают
  AGENTS.md/память как источник правды.

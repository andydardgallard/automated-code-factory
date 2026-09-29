# Project Summary — Code Factory

<!-- code-factory-memory: summary -->
project: repo
repo_path: .

Сжатая сводка проекта. Сворачивается из старых записей `memory/change-log.md` при компакции
(порог 50 записей) и читается в начале каждой задачи, чтобы не выводить историю проекта заново.

## Current state
Factory v12.13.0 — REPO-SCOPED: a run resolves the task's `repo_path` ONCE and does everything
relative to the resolved repository (`.code-factory/`, backups, `git -C <repo>`, rollback);
deployment-root exceptions: `memory/`, `version_manager.py`. 25th rule `repo-scoping` +
amended `git-native`/`task-format`; mandatory Repository-root in briefings; optional
`--repo`/`--root`/`--base` flags in run_id/factory_preflight/task_graph/error_router/
verify_quotes (cwd default unchanged); contract test `test_repo_scoping.py`; deployer
`.gitignore` hazards (task.yaml/start.cmd/start.sh) + `KIMI_FACTORY_LAUNCH_DIR` anchor;
verification-strategy §4.3 rollback order fixed (reset --hard <base> BEFORE switch);
test_error_router non-ASCII/8.3 path comparison fixed with vaccination. Previous: v12.12.1
(ENGLISH-ONLY translation + translation-quality gates `check_english_only.py` /
`check_translation_structure.py`, deleted-file gate hole closed, auditor severity mapping, ps1
parity, skill_base guard). History:
v12.8.0 (shard protocol, two-level fingerprint, Think in Code, review gate, verified acceptance,
verify_quotes, evidence ledger, advisor, preflight) + v12.9.0 (rulebook, run_id, memory v2
provenance, golden set, vaccination, WIP, error-patterns JSON) + v12.10.0 (severity boundary §3,
committee + plan_arbiter, root auto-detect → SKIP, precedent_index FTS5) + v12.10.1/12.10.2
(utf8-guard in all argparse scripts, 22nd rule no-shared-tree-git-mutations) + v12.11.0 (explicit
git stash classification in action_gate; content fingerprint over the working tree; memory
actuality mechanism: backlog [--check] + closed:+evidence: + 23rd rule memory-actuality;
project-learned overlay error_router §1.2; providers.md §5.2) + v12.12.0/12.12.1 (English-only
package + 24th rule; v8 review rework) + v12.13.0 (v10: repo-scoping contract, 25th rule).
Rulebook: 25 rules, 98 carriers. Memory owner: repo. 30/30 self-tests PASS (29 test_*.py +
test_env_propagation.sh).
Latest runs: v8 whole-project review (run_id 20260924-96879f22, task_type=review, no version
change): 8 findings, rework became `task-v9.yaml`, implemented by run v9 (run_id
20260924-8b9caeeb, v12.12.1, commit 2f53d2f). Run v10 (run_id 20260929-a4f03186, v12.13.0,
commit bbd4d4c, task_type=implement): the F1-F18 fix task of review run 20260929-62232c10 —
repo-scoping contract implemented, review approve (0 critical/0 major), acceptance SUCCESS
(7/7 MET, ledger FRESH), business mini-runs BT-1/BT-2 PASS.
Open backlog: 0 (34 items closed with evidence; 2 v10 reviewer nits recorded as info,
follow_up=false).

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

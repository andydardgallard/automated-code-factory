# Project Summary — Code Factory

<!-- code-factory-memory: summary -->
project: repo
repo_path: .

Сжатая сводка проекта. Сворачивается из старых записей `memory/change-log.md` при компакции
(порог 50 записей) и читается в начале каждой задачи, чтобы не выводить историю проекта заново.

## Current state
Фабрика v12.10.0: v12.8.0 (шард-протокол, двухуровневый fingerprint, Think in Code, review-гейт,
верифицируемая приёмка, verify_quotes, evidence ledger, advisor, preflight) + v12.9.0 (rulebook
factory-rules.md 21 правило с byte-identical носителями, сквозной run_id, provenance-память v2,
golden-set калибровка ревьюера, вакцинация, WIP-checkpoints, error-patterns JSON) + v12.10.0
(severity-граница critical=существующий путь / major=новый путь в code-review.md §3 + Reporting
discipline, норма калибровки §7: accuracy 100% / precision ≥ 0.8; committee при двойном rejection
плана — planner-2 контрастного семейства + детерминированный plan_arbiter.py; check_factory_model
авто-детектирует hand-authored корень фабрики → SKIP (3 сигнала); precedent_index.py — FTS5-поиск
прецедентов по memory/ и коду). Владелец памяти: repo. 25/25 self-тестов PASS.

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

# Project Summary — Code Factory

<!-- code-factory-memory: summary -->

Сжатая сводка проекта. Сворачивается из старых записей `memory/change-log.md` при компакции
(порог 50 записей) и читается в начале каждой задачи, чтобы не выводить историю проекта заново.

## Current state
Фабрика v12.1.0: `AGENTS.md` — единый источник правды (ровно 8 секций + детерминированный
fingerprint, без init-шага); переносимая память `memory/` (журнал + сводка); скрипты
`project_fingerprint.py` / `check_factory_model.py` / `test_factory_model.py`. Все self-тесты
PASS.

## Key decisions
- Существующий AGENTS.md перезаписывается целиком (ровно 8 секций); hand-written заметки — в
  `memory/summary.md`.
- Fingerprint НЕ включает git tree SHA (иначе встроенный fingerprint устаревает сразу после
  коммита, который его коммитит).
- Порог компакции журнала — 50 записей (остаются последние 20).
- Корневой AGENTS.md самой фабрики остаётся hand-authored инструкцией (не 8-секционной моделью).

## Recent history
- 2026-09-01 — «AGENTS.md как единый источник правды + переносимая память» (main, a53ef72):
  Scout без `/init`, fingerprint, `memory/`, скрипты проверки модели, сабагенты читают
  AGENTS.md/память как источник правды.

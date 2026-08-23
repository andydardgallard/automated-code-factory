# Changelog

Все заметные изменения в проекте Autonomous Code Factory документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — на [Semantic Versioning](https://semver.org/lang/ru/).

## [11.0.0] — 2026-08-12

### Added
- Сабагент `factory-code-reviewer` (read-only, `model_preference: primary`) и справочник
  `references/code-review.md`: статический quality gate перед приёмкой.
- Поле `task_type: implement | review` в шаблоне задачи.
- Правило code-review gate: обычная задача ревьюит diff, `task_type: review` — весь код в начале;
  задача не принимается при открытом вердикте `request_changes`; бюджет ревью = 2 итерации.

### Removed
- **BREAKING**: поддержка Kimi CLI 1.12 и Kimi Agents SDK — удалены `code-factory.yaml`,
  `system.md`, `models.yaml`, `sub-agents/*.yaml`, `examples/`. Модели теперь задаются только
  через `model_preference` в `.md`-сабагентах + `config.toml`.

## [10.2.0] — 2026-08-12

### Added
- Pre-flight проверка `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`: при отсутствии флага
  фабрика пишет `models_warning` в `pipeline.yaml`/`report.md`.

### Fixed
- `factory-analyzer` переведён на `model_preference: primary` (deepseek-v4-pro).
- Инструкции моделей: сабагентам больше не передаётся `model=` в Agent tool (не поддерживается
  в новой CLI) — модели задаются `model_preference` + `config.toml`.

## [10.1.0] — 2026-08-12

### Added
- Markdown-агенты для Kimi Code 0.34+: `code-factory.md` и сабагенты
  `analyzer|coder|tester|diagnostician.md` (frontmatter: name, description, tools,
  `model_preference`).
- Документация secondary-модели (`[secondary_model]` в `config.toml`).

### Changed
- `task.yaml` с личными данными заменён на `.example.task.yaml` (шаблон без секретов).
- Уточнена команда `/init` в `SKILL.md`/`system.md`: это slash-команда
  (`kimi -p /init --print --yolo -w <project>`), а не CLI subcommand.

## [10.0.0] — 2026-08-11

### Added
- Первая версия Autonomous Code Factory (flow skill `code-factory` + agents + SDK):
  оркестратор `SKILL.md`, справочники (planning-guide, verification-strategy, error-routing,
  tech-stack-detection), сабагенты analyzer/coder/tester/diagnostician, `models.yaml`,
  `prepare_factory.sh`, генератор `report_code_changes.md`.

[11.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.2.0...v11.0.0
[10.2.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.1.0...v10.2.0
[10.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.0.0...v10.1.0
[10.0.0]: https://github.com/andydardgallard/automated-code-factory/releases/tag/v10.0.0

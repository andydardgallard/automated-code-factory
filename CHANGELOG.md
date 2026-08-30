# Changelog

Все заметные изменения в проекте Autonomous Code Factory документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — на [Semantic Versioning](https://semver.org/lang/ru/).

## [12.0.0] — 2026-08-29

### Added
- **User story**: поле `user_story` в шаблоне задачи; обязательный анализ и использование
  контекста пользователя агентами фабрики на этапах анализа, планирования и реализации.
- **Тип задачи `refactor`**: выделенный поток со специализированным сабагентом
  `factory-refactorer` и справочником `references/refactoring.md`. Ключевое требование —
  «заморозка» функциональности: успех = структурное улучшение при 100% прохождении
  существующих тестов без изменений; любое изменение поведения — критическая ошибка и автооткат.
- **Тип задачи `security_audit`**: универсальный адаптивный полный аудит кибербезопасности
  (`references/security-audit.md` + сабагент `factory-security-auditor`, read-only).
  Автоматическое определение типов артефактов (код, IaC, контейнеры, сеть, секреты,
  зависимости), автономный выбор инструментов, отчёты + сгенерированный файл задач на
  исправление. Фабрика НЕ чинит уязвимости сама.
- **Провайдеры Kimi (K3) и Qwen**: `references/providers.md` — маршрутизация моделей через поле
  `models` задачи, корректная аутентификация/формат запросов, аддитивная интеграция без поломки
  существующих провайдеров. Ошибки провайдеров интегрированы в детерминированную маршрутизацию
  (`references/error-routing.md` §1.1).
- **Запуск одним действием**: `prepare_factory.sh` генерирует launcher `start.sh` в целевом
  проекте (автоматически выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`) и обновляет
  `.agents/` целиком (фабрика — source of truth).

### Removed
- **BREAKING**: поле `priority` полностью удалено из шаблонов, документации, инструкций агентов
  и логики. Все задачи по умолчанию обрабатываются с наивысшим приоритетом (`high`),
  приоритизацией фабрика не занимается.

## [11.1.0] — 2026-08-23

### Added
- `prepare_factory.sh`: при развёртывании фабрики добавляет `.agents/` в `.gitignore` целевого
  проекта (не ломая чтение/запись данных фабрики — `.gitignore` влияет только на git-трекинг).
- Блок «Лестница Ленивого Сеньора» (Ponytail) в `code-factory.md` и `coder.md`: обязательная
  лестница решений перед генерацией кода + фиксация выбора в `<thinking>`.
- Скрипты `scripts/test_prompt_structure.py` и `scripts/test_env_propagation.sh` — детерминированные
  проверки append-only структуры промптов и проброски env-переменной.

### Changed
- Документировано правило append-only сборки промптов (для автоматического кэша DeepSeek).
- Документирована причина потери `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL` и требование
  экспортировать его в том же терминале до запуска `kimi`.

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

[12.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.1.0...v12.0.0
[11.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.0.0...v11.1.0
[11.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.2.0...v11.0.0
[10.2.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.1.0...v10.2.0
[10.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.0.0...v10.1.0
[10.0.0]: https://github.com/andydardgallard/automated-code-factory/releases/tag/v10.0.0

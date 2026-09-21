# Changelog

Все заметные изменения в проекте Autonomous Code Factory документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — на [Semantic Versioning](https://semver.org/lang/ru/).

## [12.7.0] — 2026-09-21

### Added
- **Развёртывание и запуск фабрики в Windows без Git Bash**: `prepare_factory.cmd` (двойной клик
  в Проводнике / `cmd` / PowerShell) вызывает `prepare_factory.ps1` и возвращает его код выхода.
  PowerShell-деплойер повторяет шаги bash-версии 1:1: поиск рабочего Python с пробным запуском
  (`py -3` → `py` → `python` → `python3`, заглушка Microsoft Store не побеждает), `git init -b main`,
  копирование `.agents/`, создание/проверка памяти проекта (никогда не перезаписывается),
  `start.sh` (LF) + `start.cmd` (CRLF), те же 9 правил `.gitignore`, тот же отчёт готовности.
  Без Python развёртывание всё равно завершается успешно (шаг памяти деградирует с понятным текстом).
- **`start.cmd`** — Windows-launcher: выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`,
  проверяет наличие `kimi`, передаёт аргументы и код возврата; Git Bash не нужен.
- **Самотест `scripts/test_windows_scripts.py`**: контракты Windows-скриптов (BOM/CRLF, `chcp 65001`,
  передача аргументов и кода возврата, совпадение inline-шаблона `start.cmd` с файлом, реальное
  развёртывание с пробелом и с кириллицей в пути, идемпотентность памяти). В проекте, развёрнутом
  фабрикой, тест аккуратно пропускается (SKIP, exit 0) вместо ложного падения.

### Fixed
- `prepare_factory.ps1` больше не выдаёт жёсткий сбой за успех: сбой копирования `.agents/` или
  записи `start.sh`/`start.cmd`/`.gitignore` → `exit 1` и «Развёртывание не завершено» без баннера
  «Готово». Ожидаемые деградации остались нефатальными (нет Python → `не проверено (нет python)`, exit 0).
- `prepare_factory.ps1` выставляет `PYTHONUTF8=1` для своих вызовов python: кириллица в пути больше
  не превращается в мусор и не даёт ложное «память не создана».
- `prepare_factory.ps1` предупреждает с именем файла, прежде чем заменить существующий
  пользовательский `start.cmd`.

## [12.6.0] — 2026-09-21

### Added
- **Признак принадлежности памяти проекту**: запись журнала несёт обязательное для новых
  записей поле `project: <имя проекта>` (= basename разрешённого `repo_path`), а
  `memory/summary.md` объявляет `project:` и `repo_path:`. Память `memory/` описывает
  ЦЕЛЕВОЙ проект фабрики, а не саму фабрику.
- **Обнаружение смешения проектов**: `check_factory_model.py` считает записи с разными
  значениями `project:` в одной памяти ошибкой (пустое значение `project:` — тоже ошибка),
  а отсутствие объявления проекта в сводке — предупреждением.
- **Скрипт `memory_project.py`** (только stdlib): `name` (имя проекта), `init` (создать
  память проекта из шаблонов, только если её нет), `check` (проверить принадлежность и
  смешение), с self-тестом `test_memory_project.py`.
- **Память заводится при развёртывании**: `prepare_factory.sh` создаёт `memory/` с именем
  проекта, если её нет, НИКОГДА не перезаписывает существующую и предупреждает, если память
  объявлена за другой проект (`ПРОВЕРИТЬ ✗`) или смешивает проекты (`НЕСОГЛАСОВАНА ✗`).

### Changed
- Документация и инструкции (`AGENTS.md`, `README.md`, `.agents/README.md`, `SKILL.md`,
  справочники, главный агент и сабагенты) описывают `memory/` как память целевого проекта,
  создаваемую в корне развёртывания, и правило «одна память — один проект».
- Legacy-записи без `project:` остаются совместимыми: предупреждение, не ошибка.

## [12.5.1] — 2026-09-08

### Fixed
- **Защита от утечки API-ключей**: `.gitignore` теперь игнорирует `.env`, `.env.*`, `*.env`,
  `*.pem`, `*.key`; `prepare_factory.sh` добавляет те же паттерны в автодобавляемый блок
  `.gitignore` новых проектов.

## [12.5.0] — 2026-09-08

### Added
- **Сабагент документирования `factory-documenter`**: после каждого успешного
  implement/refactor-прогона обновляет документацию изменённых файлов (только doc-комментарии
  и `.md`, никогда код/тесты/конфиги). Встроенный валидатор `validate_documentation.py`
  (бюджет 1 retry); при исчерпании документационный долг фиксируется в отчёте, фабрика
  продолжает. Использует secondary-модель; не вызывается для review/security_audit.
- **Память «что НЕ реализовано»**: секция `unfinished` в записях журнала (item/reason/
  severity/follow_up) + поле `factory_version`. Главный агент заполняет секцию обязательно,
  даже если она пуста; компакция сохраняет critical/follow_up элементы; legacy-записи
  проходят валидацию с предупреждением.
- **Справочники-навыки `reference_docs`/`reference_skills`**: персистентная база `skill-base/`
  (SHA256-актуальность, переиспользование, инкрементальное обновление), сабагент
  `factory-skill-manager`, скрипт `skill_base.py`, детерминированная матрица релевантности для
  8 сабагентов, динамический (append-only) контекст.
- **Сквозное версионирование**: `VERSION` — единый источник истины; скрипт `version_manager.py`
  (get/bump/sync/validate/set/suggest, stdlib only); детерминированная матрица типов
  (major/minor/patch/none), валидация ревьюером (с правом переопределения с объяснением);
  синхронизация версии в README/CHANGELOG/AGENTS.md/SKILL.md/инструкцию; коммит с префиксом
  `v<версия>: `.

### Changed
- `check_factory_model.py` валидирует секцию `unfinished` и поле `factory_version` (legacy —
  предупреждение, не ошибка); self-тест расширен (12+ кейсов).
- Сабагенты `code-reviewer` валидируют предложенный матрицей тип версии.

## [12.1.0] — 2026-09-01

### Added
- **AGENTS.md как единый источник правды**: фабрика сама генерирует `AGENTS.md` проекта с ровно
  8 секциями `##` и встраивает детерминированный fingerprint структурных сигналов
  (`scripts/project_fingerprint.py`). При совпадении fingerprint анализ/Scout пропускается, при
  расхождении AGENTS.md перегенерируется; обновление в двух точках (начало/конец задачи).
- **Переносимая долгосрочная память `memory/`** (коммитимая, не игнорируется): `change-log.md`
  (append-only журнал, одна запись на прогон; единственный писатель — главный агент) и
  `summary.md` (сводка). Компакция журнала в сводку по порогу 50 записей.
- **Скрипты проверки модели**: `scripts/check_factory_model.py` (детерминированная проверка
  «8 секций + fingerprint + формат журнала») и `scripts/test_factory_model.py` (self-тест).

### Changed
- Сабагенты `analyzer`, `coder`, `tester`, `code-reviewer`, `diagnostician` читают `AGENTS.md` и
  `memory/` как источник правды, а не выводят структуру проекта заново.

### Removed
- Вызов `/init` из Scout-потока полностью удалён — фабрика генерирует `AGENTS.md` сама, без
  отдельного init-шага.

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

[12.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v12.0.0...v12.1.0
[12.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.1.0...v12.0.0
[11.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.0.0...v11.1.0
[11.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.2.0...v11.0.0
[10.2.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.1.0...v10.2.0
[10.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.0.0...v10.1.0
[10.0.0]: https://github.com/andydardgallard/automated-code-factory/releases/tag/v10.0.0

# Project: Autonomous Code Factory

Этот проект содержит автономную фабрику по написанию кода для Kimi Code CLI.
Фабрика принимает бизнес-задачу от нетехнического пользователя, анализирует проект, планирует
изменения, уточняет только бизнес-логику, согласует план, реализует код и гоняет
интеграционные / регрессионные / бизнес-тесты с автоматическим откатом при неудаче, проводит
обязательное code review перед приёмкой.

## Структура

- `task.yaml` — пример бизнес-задачи (эталон формата)
- `.agents/skills/code-factory/` — flow skill фабрики (`SKILL.md`), справочники
  (`references/`: planning-guide, verification-strategy, error-routing, tech-stack-detection,
  code-review, providers, refactoring, security-audit) и шаблон задачи (`assets/`)
- `.agents/agents/` — главный агент фабрики (Markdown `code-factory.md`) и сабагенты
  (`sub-agents/analyzer|coder|tester|diagnostician|code-reviewer|refactorer|security-auditor.md`)
- `.agents/README.md` — полная инструкция по использованию фабрики
- `prepare_factory.sh` — подготовка проекта одним действием (создаёт launcher `start.sh`)

## Как использовать

- Kimi Code 0.34+: `kimi`, затем `/skill:code-factory`; либо
  `kimi --agent-file .agents/agents/code-factory.md "задача"`
- Полный автомат: `kimi --auto` → `/skill:code-factory`
- **Одно действие**: `./prepare_factory.sh <проект>` затем `./<проект>/start.sh` (launcher сам
  выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`)
- `mode: auto` в `task.yaml` управляет только бизнес-вопросами фабрики; запросы разрешения
  CLI отключаются отдельно — флагом `kimi --auto`/`--yolo` или `default_permission_mode`
  в `config.toml`.

## Соглашения

- Рантайм-состояние фабрики — `.code-factory/` внутри проекта (не коммитить):
  `state/` (задача, план, pipeline.yaml), `logs/` (baseline, ошибки, результаты, code-review),
  `backups/`, `manifest.json`.
- Общение с пользователем — только на бизнес-языке.
- **Артефакты до изменений**: перед правкой любого исходника в `.code-factory/` должны уже
  существовать `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
- **Репо-гейт**: если задача ссылается на отсутствующие в репозитории файлы/символы/конфиги —
  в режиме hitl остановиться и спросить пользователя, в режиме auto зафиксировать допущение.
- **Маршрутизация ошибок**: детерминированный regex → Diagnostician (LLM) → Human → FAILED;
  ретраи по бюджетам ролей (coder=1, ba=2, planner=2, diagnostician=1, infrastructure=3,
  reviewer=2).
- **Code review**: каждая задача проходит через сабагента `factory-code-reviewer` перед
  приёмкой. Обычная задача — ревью diff изменений; `task_type: review` — ревью всего кода в
  начале, замечания становятся планом. Задача не принимается при открытом `request_changes`.
- **Формат задачи**: `title`, `repo_path`, `description`, опционально `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`,
  `commit_exclude`, `models`. Поля `priority` нет — все задачи по умолчанию high.
- **User story**: при наличии `user_story` фабрика анализирует и использует его на этапах
  анализа, планирования и реализации (всеми агентами).
- **`task_type: refactor`** — заморозка функциональности: 100% существующих тестов проходят без
  изменений, любое изменение поведения — критическая ошибка и автооткат.
- **`task_type: security_audit`** — адаптивный полный аудит (без живого сканирования сетей и
  пентеста); результат — отчёты + файл задач на исправление; фабрика НЕ чинит уязвимости сама.
- **Git-native**: если нет git-репозитория — `git init`; изменения идут через git
  (feature-ветка на задачу), откат к базовому коммиту при неудаче.
- **Модели**: модели задаются в `config.toml` (`default_model` + `[secondary_model]`),
  сабагентам — `model_preference: primary|secondary`. Фактические модели логируются в
  `pipeline.yaml`/`report.md` (`models_used`). Для разделения моделей нужен
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — launcher `start.sh` выставляет его сам; фабрика
  проверяет его в pre-flight и при отсутствии пишет `models_warning` в pipeline.yaml/report.md.
  Модели Kimi (K3) и Qwen маршрутизируются через поле `models` задачи (см.
  `references/providers.md`).
- **Отчёты**: `report.md` (история прогона) + `report_code_changes.md` (diff «было→стало»)
  генерируются автоматически в `.code-factory/` при завершении.
- **Коммиты**: поле `commit_exclude` в задаче исключает файлы из git-коммита
  (например, личную стратегию); ядро и документация коммитятся.
- При изменении файлов фабрики обновлять `.agents/README.md` и эти инструкции.

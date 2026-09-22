<!-- code-factory-version: 12.8.0 -->
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
  code-review, providers, refactoring, security-audit, handoff-briefing — обязательный шаблон
  брифинга сабагентов) и шаблон задачи (`assets/`)
- `.agents/skills/code-factory/scripts/` — детерминированные stdlib-скрипты (0 токенов):
  `repo_inventory.py` (инвентарь + шарды ≤20k строк), `merge_findings.py` (слияние findings
  шардов + merged verdict), `verify_acceptance.py` (критерии с `verify` → acceptance.md),
  `verify_quotes.py` (дословность цитат), `evidence_ledger.py` (подписи FRESH/STALE),
  `factory_preflight.py` (проба окружения), `action_gate.py` (деструктивные действия),
  `task_graph.py` (граф задач на диске), `log_tail.py` (хвост длинного лога), `repo_stats.py`
  (анализы кодом), `project_fingerprint.py`, `memory_project.py`, `version_manager.py`
- `.agents/agents/` — главный агент фабрики (Markdown `code-factory.md`) и сабагенты
  (`sub-agents/analyzer|coder|tester|diagnostician|advisor|code-reviewer|refactorer|security-auditor|documenter|skill-manager.md`)
- `VERSION` — единый источник истины для версии фабрики (одна строка X.Y.Z)
- `skill-base/` — персистентная база навыков из `reference_docs`/`reference_skills` (опционально)
- `.agents/README.md` — полная инструкция по использованию фабрики
- `prepare_factory.sh` — подготовка проекта одним действием (создаёт launcher `start.sh`)
- `prepare_factory.cmd` / `prepare_factory.ps1` — то же самое в Windows без Git Bash (точка входа
  и реализация; создают launcher `start.cmd`), `start.cmd` — запуск фабрики в Windows
- `memory/` — переносимая долгосрочная память ЦЕЛЕВОГО проекта (коммитится); создаётся В КОРНЕ
  РАЗВЁРТЫВАНИЯ (том каталоге, который передан `prepare_factory.sh`; в Windows —
  `prepare_factory.cmd`), базовое имя проекта = basename этого каталога: `change-log.md`
  (append-only журнал прогонов) и `summary.md` (сжатая сводка); признак проекта — `project: <имя>`
  в записи и `project:`/`repo_path:` в сводке

## Как использовать

- Kimi Code 0.34+: `kimi`, затем `/skill:code-factory`; либо
  `kimi --agent-file .agents/agents/code-factory.md "задача"`
- Полный автомат: `kimi --auto` → `/skill:code-factory`
- **Одно действие**: `./prepare_factory.sh <проект>` затем `./<проект>/start.sh` (launcher сам
  выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`)
- **Одно действие в Windows**: `prepare_factory.cmd <проект>` затем `cd <проект>` и `start.cmd`
  (интерактивно; в чате `/skill:code-factory`) либо `start.cmd --auto` — Git Bash не нужен; для
  развёртывания Python не требуется (сама фабрика использует Python для скриптов памяти и версии)
- `mode: auto` в `task.yaml` управляет только бизнес-вопросами фабрики; запросы разрешения
  CLI отключаются отдельно — флагом `kimi --auto`/`--yolo` или `default_permission_mode`
  в `config.toml`.

## Соглашения

- Рантайм-состояние фабрики — `.code-factory/` внутри проекта (не коммитить):
  `state/` (задача, план, pipeline.yaml, acceptance.md, ledger доказательств, граф задач),
  `logs/` (baseline, ошибки, результаты, code-review, findings шардов),
  `backups/`, `manifest.json`.
- **AGENTS.md — единый источник правды**: фабрика генерирует его с ровно 8 секциями `##` и
  детерминированным ДВУХУРОВНЕВЫМ fingerprint в первой строке — структурный (манифесты стека,
  CI-конфиги, README, список каталогов) + контентный (SHA индексированных git-файлов) —
  `scripts/project_fingerprint.py --all`, маркер
  `<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->`. Перегенерирует при расхождении
  ЛЮБОГО из двух хэшей (начало задачи) или изменении структуры/стека/точек входа (конец задачи)
  и коммитит (без отдельного init-шага Kimi); ветка «SKIP regeneration» разрешена ТОЛЬКО при
  совпадении ОБОИХ хэшей — совпадение одного структурного уровня недостаточно (изменения глубже
  первого уровня видит контентный хэш). Сабагенты читают AGENTS.md вместо повторного вывода
  структуры.
- **Долгосрочная память `memory/`** (коммитится, не игнорируется) — память ТОГО проекта, который
  указан в `repo_path` задачи (для этого репозитория целевой проект — сама фабрика), а не память
  фабрики: одна память принадлежит ровно одному проекту. Каталог `memory/` живёт В КОРНЕ
  РАЗВЁРТЫВАНИЯ — том, который передан `prepare_factory.sh`; базовое имя проекта при развёртывании =
  basename этого каталога. Когда `repo_path` задачи указывает на ПОДКАТАЛОГ корня развёртывания,
  главный агент создаёт память явно, назвав проект: `memory_project.py init --repo <корень
  развёртывания> --project <basename разрешённого repo_path>`, и имя фиксируется в объявлении
  `project:` сводки. Каждая запись журнала несёт обязательный для НОВЫХ записей признак
  `project: <имя проекта>` (то же имя, что объявлено в сводке); сводка `summary.md` объявляет проект
  строками `project:`/`repo_path:` сразу после канонического маркера. Записи без `project:` — legacy
  (предупреждение); записи разных проектов в одном журнале — ошибка (`check_factory_model.py`,
  `memory_project.py check`). Единственный писатель — главный агент (одна запись в `change-log.md`
  на прогон, компакция в `summary.md` по порогу 50 записей); читается в начале задачи и ролями по
  необходимости. Если `memory/` отсутствует (первое обращение к проекту), фабрика создаёт её той же
  командой `init` с `--project <имя>`. История разработки самой фабрики НИКОГДА не попадает в память
  целевого проекта. Проверка модели — `scripts/check_factory_model.py`.
- Общение с пользователем — только на бизнес-языке.
- **Артефакты до изменений**: перед правкой любого исходника в `.code-factory/` должны уже
  существовать `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
- **Репо-гейт**: если задача ссылается на отсутствующие в репозитории файлы/символы/конфиги —
  в режиме hitl остановиться и спросить пользователя, в режиме auto зафиксировать допущение.
- **Маршрутизация ошибок**: детерминированный regex → Diagnostician (LLM) → Advisor (secondary,
  контрастное семейство диагностика, бюджет 1) → Human → FAILED; ретраи по бюджетам ролей
  (coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2).
- **Code review**: каждая задача проходит через сабагента `factory-code-reviewer` перед
  приёмкой. Обычная задача — ревью diff изменений; `task_type: review` и `security_audit` —
  ревью/аудит всего кода ШАРДАМИ (`repo_inventory.py shards --max-lines 20000` → параллельные
  сабагенты по шардам → `merge_findings.py` даёт детерминированный merged verdict), замечания
  review-задачи становятся планом.

<!-- review-gate-policy: begin -->
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- review-gate-policy: end -->
- **Проверяемая приёмка**: критерии с `verify` исполняются реально (`scripts/verify_acceptance.py`
  → `.code-factory/state/acceptance.md`; exit 0 только при SUCCESS — хотя бы один критерий с
  `verify`, все MET, baseline доказан), а доказательства несут подписи FRESH/STALE
  (`scripts/evidence_ledger.py`): зелёный лог устаревшей ревизии приёмкой не считается.
- **Брифинг каждой делегации**: сабагент получает самодостаточный брифинг по
  `.agents/skills/code-factory/references/handoff-briefing.md` — Task / Context / релевантные
  файлы ПУТЯМИ (без вставки содержимого) / что уже пробовали и почему не сработало; файлы пишет
  только главный агент, read-only роли идут с суффиксом «без правок».
- **Формат задачи**: `title`, `repo_path`, `description`, опционально `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`
  (у критерия опционально `verify: <команда>` и `derived: true`), `business_tests`
  (сценарий/конфиги/ожидаемые бизнес-результаты), `commit_exclude`, `models`.
  Поля `priority` нет — все задачи по умолчанию high.
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
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — launcher `start.sh`/`start.cmd` выставляет его сам; фабрика
  проверяет его в pre-flight и при отсутствии пишет `models_warning` в pipeline.yaml/report.md.
  Модели Kimi (K3) и Qwen маршрутизируются через поле `models` задачи (см.
  `references/providers.md`).
- **Отчёты**: `report.md` (история прогона) + `report_code_changes.md` (diff «было→стало»)
  генерируются автоматически в `.code-factory/` при завершении.
- **Коммиты**: поле `commit_exclude` в задаче исключает файлы из git-коммита
  (например, личную стратегию); ядро и документация коммитятся.
- При изменении файлов фабрики обновлять `.agents/README.md` и эти инструкции.
- **Документирование**: после каждого успешного implement/refactor вызывается сабагент
  `factory-documenter` (secondary) — обновляет только doc-комментарии и `.md`, валидатор
  `validate_documentation.py` с бюджетом 1 retry; для review/security_audit не вызывается.
- **Версия**: `VERSION` — единый источник истины; тип версии определяет детерминированная
  матрица, валидирует код-ревьюер (может переопределить с объяснением), применяет
  `version_manager.py`; review/security_audit версию не меняют.

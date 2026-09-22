# Code Factory (for Kimi Code CLI)
<!-- code-factory-version: 12.8.0 -->

Автономная фабрика по написанию кода. Принимает бизнес-задачу от пользователя, который не
разбирается в программировании, анализирует проект, планирует изменения, уточняет только
бизнес-логику, получает согласование плана, а затем сама пишет код, гоняет
интеграционные / регрессионные / бизнес-тесты с автоматическим откатом при любой неудаче,
проводит обязательное code review перед приёмкой и проверяет критерии приёмки.

Поддерживает **любые языки** (стек определяется автоматически) и работает с существующими
проектами или создаёт проекты с нуля.

## Структура

```
.agents/
├── README.md                        # этот файл
├── skills/
│   └── code-factory/
│       ├── SKILL.md                 # Flow skill — главный оркестратор (тип: flow)
│       ├── references/
│       │   ├── planning-guide.md    # анализ проекта, DAG-план, вопросы по бизнес-тестам
│       │   ├── verification-strategy.md  # интеграционные/регресс/бизнес-тесты + откат
│       │   ├── error-routing.md     # детерминированная маршрутизация ошибок + Diagnostician
│       │   ├── tech-stack-detection.md  # определение стека + Scout pipeline
│       │   ├── code-review.md       # статический quality gate: чек-лист, severity, вердикт
│       │   ├── providers.md         # маршрутизация моделей Kimi (K3) и Qwen
│       │   ├── refactoring.md       # тип задачи refactor: заморозка функциональности
│       │   ├── security-audit.md    # тип задачи security_audit: адаптивный полный аудит
│       │   ├── documentation.md     # сабагент документирования: методология + валидатор
│       │   ├── handoff-briefing.md  # обязательный шаблон брифинга сабагентов (файлы путями)
│       │   └── reference-docs.md    # reference_docs/reference_skills: база навыков + матрица
│       ├── scripts/
│       │   ├── gen_code_changes_report.py  # генератор report_code_changes.md (diff было→стало)
│       │   ├── project_fingerprint.py      # двухуровневый fingerprint: структурный + контентный
│       │   ├── check_factory_model.py      # проверка: 8 секций + оба fingerprint + формат памяти
│       │   ├── test_factory_model.py       # self-тест скриптов модели
│       │   ├── memory_project.py           # память проекта: init/name/check/rename/compact-check/validate-fix-tasks
│       │   ├── test_memory_project.py      # self-тест скрипта памяти проекта
│       │   ├── test_prompt_structure.py    # self-тест: append-only структура промптов
│       │   ├── test_env_propagation.sh     # self-тест: перенос env-флага моделей
│       │   ├── validate_documentation.py   # валидатор документации (сабагент документирования)
│       │   ├── test_validate_documentation.py  # self-тест валидатора документации
│       │   ├── skill_base.py               # персистентная база навыков (reference_docs)
│       │   ├── test_skill_base.py          # self-тест базы навыков
│       │   ├── version_manager.py          # единый источник версии: get/bump/sync/validate/set/suggest
│       │   ├── test_version_manager.py     # self-тест скрипта версий (≥12 кейсов)
│       │   ├── validate_mermaid.py         # структурный валидатор Mermaid-диаграмм
│       │   ├── test_validate_mermaid.py    # self-тест валидатора Mermaid
│       │   ├── repo_inventory.py           # инвентарь репозитория + шарды (shard-протокол)
│       │   ├── test_repo_inventory.py      # self-тест инвентаря
│       │   ├── merge_findings.py           # детерминированное слияние findings шардов + вердикт
│       │   ├── test_merge_findings.py      # self-тест слияния findings
│       │   ├── repo_stats.py               # анализы репозитория кодом: sizes/entry-points/imports
│       │   ├── test_repo_stats.py          # self-тест анализов
│       │   ├── log_tail.py                 # счётчики + хвост длинного лога (без вытягивания в контекст)
│       │   ├── test_log_tail.py            # self-тест хвоста лога
│       │   ├── factory_preflight.py        # pre-flight окружения (python/python3/py и др.)
│       │   ├── test_factory_preflight.py   # self-тест pre-flight
│       │   ├── action_gate.py              # классификация деструктивных действий (ALLOW/CONFIRM/HARD_DENY)
│       │   ├── test_action_gate.py         # self-тест action gate
│       │   ├── task_graph.py               # граф задач на диске: create/claim/complete/ready/list
│       │   ├── test_task_graph.py          # self-тест графа задач
│       │   ├── evidence_ledger.py          # ledger доказательств с подписями FRESH/STALE
│       │   ├── test_evidence_ledger.py     # self-тест ledger'а доказательств
│       │   ├── verify_acceptance.py        # машинная проверка критериев приёмки (анти-тавтология)
│       │   ├── test_verify_acceptance.py   # self-тест проверки приёмки
│       │   ├── verify_quotes.py            # дословность цитат-доказательств (Evidence-Preserving Reducer)
│       │   ├── test_verify_quotes.py       # self-тест проверки цитат
│       │   ├── test_review_gate.py         # self-тест канонического review-гейта (5 документов)
│       │   └── test_windows_scripts.py     # self-тест Windows-скриптов развёртывания/запуска
│       └── assets/
│           └── task-template.yaml   # шаблон бизнес-задачи
└── agents/
    ├── code-factory.md              # главный агент (Kimi Code 0.34+, --agent-file Markdown)
    └── sub-agents/
        ├── analyzer.md              # сабагент: анализ проекта (read-only)
        ├── coder.md                 # сабагент: реализация кода
        ├── tester.md                # сабагент: тесты и проверка результатов
        ├── diagnostician.md         # сабагент: глубокий анализ ошибок (read-only)
        ├── advisor.md               # сабагент: второе мнение по ошибке после Diagnostician
        ├── code-reviewer.md         # сабагент: статическое ревью кода (read-only)
        ├── refactorer.md            # сабагент: рефакторинг без изменения поведения
        ├── security-auditor.md      # сабагент: аудит безопасности (read-only)
        ├── documenter.md            # сабагент: документация изменённых файлов (secondary)
        └── skill-manager.md         # сабагент: управление базой навыков (reference_docs)
```

Рантайм-состояние фабрики живёт в `.code-factory/` внутри проекта (не коммитится):
`state/` (задача, план, pipeline.yaml, acceptance.md, ledger доказательств, граф задач),
`backups/` (бэкапы изменяемых файлов), `manifest.json` (список изменённых/созданных файлов),
`logs/` (ошибки, результаты тестов, code review, findings шардов).

Переносимая долгосрочная память живёт в коммитимом каталоге `memory/` ТОГО проекта, который указан в
`repo_path` задачи (НЕ в `.gitignore`): `memory/change-log.md` (append-only журнал прогонов, одна
запись на задачу) и `memory/summary.md` (сжатая сводка). Каталог `memory/` создаётся В КОРНЕ
РАЗВЁРТЫВАНИЯ — том, который передан `prepare_factory.sh` (в Windows — `prepare_factory.cmd`, он
запускает `prepare_factory.ps1`); базовое имя проекта при развёртывании = basename этого каталога,
а запускается фабрика из него через `./start.sh` (Git Bash/Linux) или `start.cmd` (Windows). Одна
память принадлежит ровно одному проекту: каждая новая запись журнала
несёт признак `project: <имя проекта>`, сводка объявляет `project:`/`repo_path:` сразу после
канонического маркера; записи без `project:` — legacy, записи разных проектов в одном журнале —
ошибка (`check_factory_model.py`, `memory_project.py check`). Если `repo_path` задачи указывает на
ПОДКАТАЛОГ корня развёртывания, имя проекта = basename разрешённого `repo_path`, и главный агент
заводит память явно: `memory_project.py init --repo <корень развёртывания> --project <basename
разрешённого repo_path>`. Единственный писатель — главный агент в конце каждой задачи; читается
главным агентом/planner/analyzer в начале и остальными ролями по необходимости.

## Запуск (Kimi Code 0.34+, Node)

Подготовка и запуск — одно действие. Сначала подготовьте проект:

```bash
./prepare_factory.sh /path/to/your-project
```

Скрипт копирует фабрику, настраивает `.gitignore`/git и создаёт в проекте launcher `start.sh`
(в нём уже выставлена `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`). Дальше — просто запустите:

```bash
cd /path/to/your-project
./start.sh                 # открывает Kimi Code; в чате: /skill:code-factory
./start.sh --auto          # полностью автономный режим
```

Никаких дополнительных `export`-команд запоминать не нужно.

### Windows (без Git Bash)

Та же подготовка одним действием через `prepare_factory.cmd`: он вызывает `prepare_factory.ps1`
(Windows-версия деплойера, PowerShell входит в состав Windows) и передаёт её код возврата. Скрипт
копирует фабрику, настраивает git/`.gitignore`, создаёт в проекте launcher-ы `start.cmd` (Windows) и
`start.sh` (Git Bash/Linux) и печатает отчёт о готовности:

```bat
rem подготовка проекта (копирует фабрику, настраивает git/.gitignore и создаёт launcher-ы)
prepare_factory.cmd C:\work\my-project

rem запуск одним действием
cd C:\work\my-project
start.cmd
rem в чате: /skill:code-factory

rem полностью автономно:
start.cmd --auto
```

Для развёртывания Python не требуется: шаг долгосрочной памяти (`memory/`) без него деградирует с
понятным предупреждением, развёртывание всё равно завершится успешно, а память фабрика создаст при
первом обращении к проекту. Сама фабрика использует Python для скриптов памяти и версии
(`memory_project.py`, `version_manager.py` и др.).

Или вручную, без launcher-а:

```sh
kimi --agent-file .agents/agents/code-factory.md "Прочитай task.yaml и реши задачу"
```

Модели: `default_model` и `[secondary_model]` в `~/.kimi-code/config.toml`; сабагентам —
`model_preference: primary|secondary` в `.md`-файлах. Для разделения моделей сабагентов
нужен `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — launcher `start.sh`/`start.cmd` выставляет его сам.

## AGENTS.md и долгосрочная память

Фабрика сама держит `AGENTS.md` проекта актуальным единым источником правды:

- генерирует ровно 8 секций `##` (Project Overview, Technology Stack, Architecture Overview,
  Directory Structure, Key Configuration Files, Build & Run Instructions,
  Dependencies & Integrations, Known Constraints & Limitations) и встраивает в первую строку
  детерминированный ДВУХУРОВНЕВЫЙ fingerprint — структурный + контентный:
  `<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->`;
- fingerprint считается скриптом `scripts/project_fingerprint.py --all`: структурный уровень —
  манифесты стека, CI-конфиги, README, список каталогов; контентный — SHA-256 проиндексированных
  git-файлов (собственные артефакты фабрики исключены в обоих уровнях). Совпали ОБА — анализ/Scout
  и перегенерация пропускаются; не совпал любой — AGENTS.md перегенерируется (правки глубже
  первого уровня видит контентный уровень);
- обновляется в двух точках: начало задачи (внешние изменения) и конец задачи (собственные
  изменения фабрики), после чего коммитится; фабрика делает хороший AGENTS.md сама, без
  отдельного init-шага.

Переносимая память в `memory/` (коммитится, не игнорируется) — память ЦЕЛЕВОГО проекта из
`repo_path` задачи, а не история разработки фабрики. Каталог `memory/` создаётся В КОРНЕ
РАЗВЁРТЫВАНИЯ (том, который передан `prepare_factory.sh`, а в Windows — `prepare_factory.cmd`),
базовое имя проекта при развёртывании = basename этого каталога; при `repo_path` в ПОДКАТАЛОГЕ
корня развёртывания имя проекта = basename
разрешённого `repo_path`. Файлы: `change-log.md` (журнал прогонов, одна запись на задачу,
обязательный для новых записей признак `project: <имя проекта>`) и `summary.md` (сводка с
объявлением `project:`/`repo_path:` сразу после канонического маркера; компакция журнала по порогу
50 записей). При первом обращении к проекту, если `memory/` отсутствует, она создаётся командой
`python .agents/skills/code-factory/scripts/memory_project.py init --repo <корень развёртывания>
--project <basename разрешённого repo_path>` (имя фиксируется в объявлении `project:` сводки).
Проверка модели — скрипт `scripts/check_factory_model.py` (8 секций + fingerprint + формат журнала),
self-тест — `scripts/test_factory_model.py`; принадлежность памяти проекту — `memory_project.py
check`.

## Формат бизнес-задачи

Минимальный формат — свободный текст. Рекомендуемый — `task.yaml` (см. шаблон в
`.agents/skills/code-factory/assets/task-template.yaml`):

```yaml
title: "Стратегия не генерирует сигналы для CNY"
repo_path: ./repo            # только для существующих проектов
description: |
  Опишите проблему бизнес-языком, без технических деталей.
user_story: |                # опционально, но рекомендуется
  Как трейдер, я хочу сигналы по CNY, чтобы торговать дробным инструментом как Si.
mode: hitl                   # hitl (по умолчанию) | auto
task_type: implement         # implement | review | refactor | security_audit
acceptance_criteria:         # у критерия опционально есть verify: <команда> и derived: true
  - "Стратегия генерирует не менее 5 сигналов LONG/SHORT для CNY"
  - criterion: "Поведение для инструмента Si не изменилось"
    verify: "python -m pytest -q tests/test_si_regression.py"
business_tests:              # опционально: сценарий, конфиги и ожидаемые бизнес-результаты
  - scenario: "Запустить стратегию на данных CNY"
    config: "path/to/config.toml"
    expected_results: "Не менее 5 сигналов LONG/SHORT и положительная кривая капитала"
```
Поля `priority` нет — все задачи по умолчанию обрабатываются с наивысшим приоритетом.
`business_tests` читается в Phase 0 вместе с задачей; если поля нет, фабрика уточняет сценарий,
конфиги и ожидаемые бизнес-результаты у пользователя на этапе планирования (hitl).

`task_type: review` — задача «сделать code review существующего кода»: фабрика запускает
ревьюера по **всему** коду в начале, его замечания становятся планом работ.

`task_type: refactor` — снижение техдолга/дублирования/упрощение архитектуры **без изменения
поведения**: 100% существующих тестов должны пройти без изменений, любое изменение поведения —
критическая ошибка и автооткат (см. `references/refactoring.md`).

`task_type: security_audit` — полный адаптивный аудит кибербезопасности проекта: фабрика сама
определяет типы артефактов (код, инфраструктура, контейнеры, сеть) и запускает только
релевантные проверки. Результат — отчёты + сгенерированный файл задач на исправление. Фабрика
НЕ чинит уязвимости сама (см. `references/security-audit.md`).

## Режимы

- **hitl (по умолчанию)** — фабрика уточняет у пользователя бизнес-сценарий, конфиги для
  запуска и ожидаемые бизнес-результаты, затем показывает план на согласование.
- **auto** — фабрика принимает разумные допущения (записывает их в план как assumptions) и
  работает без вопросов.

> **Важно:** `mode: auto` управляет ТОЛЬКО бизнес-вопросами фабрики и согласованием плана.
> Он НЕ отключает запросы разрешения Kimi Code CLI на выполнение инструментов (Bash, Write,
> Edit и т.д.). Для полностью автономного прогона (без запросов разрешения) запускайте
> `kimi --auto` (или `--yolo`), либо задайте `default_permission_mode = "auto"` в
> `~/.kimi-code/config.toml`.

## Code review (обязательный gate)

Перед приёмкой каждая задача проходит через сабагента `factory-code-reviewer`:

- **обычная задача** — ревьюер смотрит **diff** изменений (не весь проект);
- **`task_type: review` / `security_audit`** — ревью/аудит **всего кода** ШАРДАМИ в начале:
  `scripts/repo_inventory.py shards --max-lines 20000` → по одному сабагенту на шард →
  детерминированный merged verdict скриптом `scripts/merge_findings.py` (каждый сабагент
  видит только файлы своего шарда); замечания review-задачи становятся планом.

Вердикт `approve` → задача идёт на приёмку; `request_changes` → формируется список переделки
для coder-а, после правок повторно гоняются тесты и ревью. При исчерпании бюджета действует
auto-escape политика: в режиме auto допускается только conditional pass с пометкой критерия
`unverified_review` (см. канонический блок ниже), в режиме hitl фабрика останавливается.

<!-- review-gate-policy: begin -->
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- review-gate-policy: end -->

Приёмка дополнительно проверяется машинно: критерии с `verify` исполняются по-настоящему
(`scripts/verify_acceptance.py` → `.code-factory/state/acceptance.md`), и SUCCESS (exit 0)
требует, чтобы хотя бы один критерий нёс `verify`, все критерии с `verify` были MET и
регрессионный baseline был доказан. Прогон без единого `verify` или с устаревшими
доказательствами получает DEGRADED, а не SUCCESS: подписи FRESH/STALE доказательств считает
`scripts/evidence_ledger.py`, поэтому зелёный лог старой ревизии приёмкой не считается.

## Откат изменений и маршрутизация ошибок

При неудаче любого теста фабрика НЕ откатывается вслепую:
1. **Классифицирует ошибку** детерминированно (regex, ~90% случаев, 0 токенов) —
   compile→coder, missing file→BA, bad command→Planner, инфраструктура→автофикс,
   wrong results/unknown→Diagnostician (см. `references/error-routing.md`).
2. **Роллбэк**: восстанавливает файлы из `.code-factory/backups/`, удаляет созданные файлы
   (по `manifest.json`), возвращает проект в до-изменённое состояние.
3. **Retry-бюджеты**: coder=1, BA=2, Planner=2, Diagnostician=1, advisor=1, infrastructure=3,
   reviewer=2. При исчерпании — эскалация на Diagnostician (LLM-анализ, пишет
   `.code-factory/logs/diagnostic.md`), затем на Advisor (`factory-advisor`, secondary-модель
   контрастного семейства, read-only, бюджет 1; маршрут решает машинное поле `agreement`
   доклада — см. `references/error-routing.md` §4.1).
4. **Human**: если Advisor или Diagnostician рекомендует — показать пользователю и спросить.
5. **FAILED**: только при исчерпании всех бюджетов, с полным логом в
   `.code-factory/logs/errors.md`. Фабрика никогда не падает молча.

Checkpoint/resume: после каждой фазы пишется `.code-factory/state/pipeline.yaml` — при
перезапуске фабрика продолжает с того же места.

Итоговый отчёт: при завершении (успех или FAILED) фабрика пишет `.code-factory/report.md` —
один самодостаточный файл со всей историей прогона (задача, план, изменения, тесты,
ошибки, диагностика, code review, acceptance). Рядом генерируется
`.code-factory/report_code_changes.md` — наглядный отчёт «было → стало» по изменённым строкам
коммита (скриптом `scripts/gen_code_changes_report.py`, без затрат LLM). Оба файла достаточно
переслать разработчику фабрики для анализа — читать весь `.code-factory/` не нужно.

## Бизнес-тесты

Бизнес-тест = запуск реальной (исправленной/созданной) программы с конфигами пользователя и
проверка, что **бизнес-результаты** совпадают с ожидаемыми. Сценарий, конфиги и ожидаемые
результаты фабрика уточняет у пользователя на этапе планирования (в режиме hitl).

Практические приёмы (обкатаны на реальном прогоне):
- читать `exit_results_path` из конфига и проверять сгенерированные отчёты (строки, колонки);
- если пользователь говорит «неправильный результат — только N вариантов», проверять, что после
  фикса уникальных вариантов результатов стало БОЛЬШЕ N (проверка отличий результатов);
- отличать «фильтр работает» от «сломано»: 0 сделок при неподходящем пороге — норма; доказать
  работу фильтра повторным прогоном с порогом, соразмерным цене инструмента;
- бизнес-тесты выполнять именно теми командами, что дал пользователь (build + run);
- побочные артефакты прогона (папки результатов) удалять после проверки или игнорировать в git.

## Автодокументирование, долг и версия

**Автодокументирование**: после каждого успешного `implement`/`refactor`-прогона фабрика
вызывает сабагента `factory-documenter` (secondary-модель). Он берёт список изменённых файлов
из `.code-factory/manifest.json` и приводит документацию в соответствие с кодом — только
doc-комментарии и `.md`, никогда код/тесты/конфиги. Результат проверяется встроенным
валидатором `scripts/validate_documentation.py` (бюджет 1 retry); при исчерпании долг
фиксируется в отчёте прогона, фабрика продолжает. Для `review`/`security_audit` не вызывается.

**Память «что НЕ реализовано»**: каждая запись журнала `memory/change-log.md` содержит поле
`project: <имя проекта>`, секцию `unfinished` (явный маркер «нет незавершённых элементов» либо
список элементов `item`/`reason`/`severity`/`follow_up`) и поле `factory_version`. Главный агент
заполняет их обязательно, даже если долга нет. При компакции сохраняются элементы critical или
follow_up.

**Справочники-навыки**: поля задачи `reference_docs` (`{path, skill}`) и `reference_skills`
(имена) подключают книги/документы как переиспользуемые навыки. База `skill-base/` персистентна,
актуальность определяется SHA256-хешем источника; управление — сабагент `factory-skill-manager`
и скрипт `scripts/skill_base.py`. Навыки попадают в динамический контекст сабагентов по
детерминированной матрице (см. `references/reference-docs.md`).

**Версия (единый источник истины)**: файл `VERSION` (одна строка X.Y.Z). После успешного
прогона тип версии определяет детерминированная матрица (`scripts/version_manager.py suggest`),
ревьюер валидирует (может переопределить с объяснением), затем `bump`/`sync` синхронизирует
версию в README/CHANGELOG/AGENTS.md/SKILL.md/инструкцию и проверяет `validate` (exit 0).
`review`/`security_audit` версию не меняют. Пользователю обновлять версию вручную не нужно.

## Модели

Роли фабрики используют разные модели. Модели задаются по ролям через `model_preference`
(`primary|secondary`) в `.md`-сабагентах + `config.toml` (`default_model` + `[secondary_model]`).
Можно менять провайдеров и семейства (deepseek, qwen, kimi/moonshot и др.):
- CLI: `kimi -m <model>` или `/model` в сессии;
- в задаче: поле `models:` в `task.yaml` (см. шаблон).

Поддержка Kimi (K3) и Qwen — аддитивная: при указании модели Kimi или Qwen фабрика сама
определяет вендора и маршрутизирует запросы на соответствующий API-эндпоинт с корректной
аутентификацией, не ломая уже подключённые модели. Подробности, конфиги и обработка ошибок —
в `references/providers.md` и `references/error-routing.md` §1.1.

Главный агент передаёт модель каждому сабагенту явно: аргумент `model:` в Agent tool
поддерживается CLI — модель берётся из матрицы `models` задачи по правилу generator≠judge
(кодер/тестер и ревьюер/диагностик/advisor — разные семейства моделей), а `model_preference`
(`primary|secondary`) в `.md`-сабагентах служит fallback для ролей, которые задача не назвала.
Фактическая модель записывается в `.code-factory/state/pipeline.yaml` (`models_used`) и в
`report.md` (раздел «Models used»). Если после прогона в `pipeline.yaml` все роли показывают одну
модель — значит, модели не разделялись. Для разделения обязателен флаг
`export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — без него coder/tester уйдут на primary.
Фабрика проверяет это в pre-flight и пишет `models_warning` в pipeline.yaml/report.md.

Переменную экспортируйте в **том же терминале**, где запускается `kimi`, и **до** его запуска.
Если `kimi` запущен из нового терминала, лаунчера или через `sudo`, переменная теряется и
фабрика увидит `unset` — это особенность окружения запуска, а не ошибка фабрики.

Рекомендуемое соответствие ролей:
- primary (рассуждающие): main/planner, analyzer, diagnostician, reviewer;
- secondary (быстрые): coder, tester.

## Кэширование промптов (DeepSeek)

Промпты собираются по принципу append-only для автоматического context-cache DeepSeek:
статичный префикс (системный промпт сабагента, контекст файлов) всегда в начале, динамические
данные (история ходов, логи ошибок) — строго в конце. Изменение начала/середины сбрасывает кэш.

## Коммиты

Фабрика коммитит изменения в feature-ветку. Поле `commit_exclude` в задаче позволяет
исключить файлы из коммита (например, личную стратегию) — фабрика всё равно может их
менять (бэкапы/тесты/откат), но в git-коммит они не попадут.

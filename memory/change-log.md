# Change Log — Code Factory

<!-- code-factory-memory: change-log -->

Append-only журнал прогонов фабрики. Одна запись на завершённую задачу (успех ИЛИ FAILED),
пишется единственным писателем — главным агентом (оркестратором) в конце Phase 9. Записи не
переупорядочиваются и не удаляются; при превышении порога (50 записей) старые записи
сворачиваются в `memory/summary.md`, здесь остаётся свежий хвост (последние 20).

Формат записи (плоский, проверяется `scripts/check_factory_model.py`):

```
## <ISO timestamp> — <title>
title: <строка>
project: <имя проекта>
timestamp: <ISO8601 дата>
run_id: <YYYYMMDD-8hex — идентификатор прогона, scripts/run_id.py>
branch: <ветка или "(none)">
commit: <sha или "(none)">
task_type: implement | review | refactor | security_audit
goal: <краткая цель>
changed_files: <список через "; ">
created_files: <список через "; ">
results: integration=<PASS|FAIL|SKIP>; regression=<...>; business=<...>; review=<approve|request_changes|SKIP> — ключевые значения с меткой [verified: <команда/тест/лог>] или [inferred]
decisions: <принятые решения и допущения; каждое ключевое утверждение с меткой [verified: <команда/тест/лог>] или [inferred]>
assumptions: <допущения>
models_used: analyzer=<модель>; planner=<модель>; coder=<модель>; tester=<модель>; reviewer=<модель>; diagnostician=<модель>; documenter=<модель>
factory_version: <X.Y.Z — версия фабрики на момент прогона>
unfinished: нет незавершённых элементов
```

Однострочный пример записи (одна запись — один блок, поля построчно):
`title: Короткий заголовок | project: repo | timestamp: 2026-01-01T00:00:00+0300 | run_id: 20260101-1a2b3c4d | task_type: implement`

Память `memory/` принадлежит ТОЛЬКО одному проекту — тому, что указан в поле `repo_path`
задачи; `project:` = basename разрешённого `repo_path`. Для этого репозитория целевой проект —
сама фабрика (каталог `repo`), поэтому во всех записях `project: repo`. Разные
значения `project:` в одном журнале — ошибка (память смешивает проекты; ловят
`scripts/check_factory_model.py` и `scripts/memory_project.py check`); записи без `project:` —
legacy (предупреждение, не ошибка).

**Формат v2 (введённый после v12.8.0): `run_id` + provenance-метки.** Поле `run_id` —
идентификатор прогона (`YYYYMMDD-<8 hex>`, см. `scripts/run_id.py`), который связывает запись с
артефактами прогона (pipeline.yaml, acceptance.md, logs/*.md, report.md). Каждое ключевое
утверждение записи в полях `decisions` и `results` несёт инлайн-метку:
`[verified: <команда/тест/лог, подтверждающий утверждение>]` — утверждение подтверждено
доказательством прогона, или `[inferred]` — выведено, но не проверено. Пример:
`results: integration=PASS [verified: .code-factory/logs/code-results.md]; review=approve [inferred]`.

Записью формата v2 считается запись, у которой `factory_version` НОВЕЕ 12.8.0 ИЛИ которая уже
несёт v2-поле (`run_id` или метку происхождения) — так полумигрированная запись тоже
проверяется. Для v2-записи отсутствие `run_id` (или `run_id` не по формату `YYYYMMDD-<8 hex>`)
либо отсутствие метки в `decisions`/`results` — ОШИБКА формата; записи, написанные фабрикой не
новее 12.8.0 и не несущие v2-полей, и legacy-записи без `project:` проходят валидацию с
предупреждением (не ошибкой). Проверяют `scripts/memory_project.py check` и
`scripts/check_factory_model.py`.

Если долг есть — вместо одной строки `unfinished:` пишется многострочный список; для каждого
элемента обязательны 4 поля (`item`, `reason`, `severity` critical|warning|info, `follow_up`
true|false):

```
unfinished:
  - item: замечания код-ревьюера приняты как есть
    reason: бюджет ревьюера исчерпан
    severity: warning
    follow_up: false
```

Секция `unfinished` заполняется ОБЯЗАТЕЛЬНО при каждой записи, даже если она пуста (явный
маркер `нет незавершённых элементов`). При компакции журнала в сводку элементы с
severity=critical или follow_up=true сохраняются обязательно. Существующие записи без секции
`unfinished`/`factory_version` или без поля `project` проходят валидацию с предупреждением
(не ошибкой); так же (предупреждением, не ошибкой) проходят записи, написанные фабрикой не
новее 12.8.0 и не несущие v2-полей (`run_id` или provenance-метки).

## 2026-09-01T01:01:45+0300 — AGENTS.md как единый источник правды + переносимая память
title: AGENTS.md как единый источник правды + переносимая долгосрочная память
project: repo
timestamp: 2026-09-01T01:01:45+0300
branch: main
commit: a53ef72ac36825fb3a6a1a34fc63781d1c2de7f6
task_type: implement
goal: AGENTS.md — единый источник правды (8 секций + fingerprint, без /init) + коммитимая память memory/
changed_files: .agents/skills/code-factory/references/tech-stack-detection.md; .agents/skills/code-factory/references/planning-guide.md; .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/agents/sub-agents/analyzer.md; .agents/agents/sub-agents/coder.md; .agents/agents/sub-agents/tester.md; .agents/agents/sub-agents/code-reviewer.md; .agents/agents/sub-agents/diagnostician.md; .agents/README.md; AGENTS.md; CHANGELOG.md
created_files: .agents/skills/code-factory/scripts/project_fingerprint.py; .agents/skills/code-factory/scripts/check_factory_model.py; .agents/skills/code-factory/scripts/test_factory_model.py; memory/change-log.md; memory/summary.md
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: существующий AGENTS.md перезаписывается целиком (ровно 8 секций); fingerprint без git tree SHA (иначе stale после коммита); порог компакции 50 записей (хвост 20); корневой AGENTS.md фабрики остаётся hand-authored
assumptions: repo/ и task_files/ — посторонние untracked, в коммит не входят; роли выполнены главным агентом (первичная модель), reviewer — сабагент factory-code-reviewer
models_used: analyzer=primary; planner=primary; coder=primary; tester=primary; reviewer=primary; diagnostician=unused

## 2026-09-08T14:07:38+0300 — Фабрика v12.5.0: documenter + память долга + база навыков + версионирование
title: Фабрика v12.5.0: documenter + память долга + база навыков + версионирование
project: repo
timestamp: 2026-09-08T14:07:38+0300
branch: feature/factory-v12.5.0
commit: 123acf33561298379a2c374fcb2fed27967a9df6
task_type: implement
goal: 4 задачи — автодокументирование (factory-documenter), память незавершённого (unfinished), справочники-навыки (reference_docs/reference_skills), сквозное версионирование (VERSION + version_manager)
changed_files: .agents/README.md; .agents/agents/code-factory.md; .agents/agents/sub-agents/code-reviewer.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/assets/task-template.yaml; .agents/skills/code-factory/references/code-review.md; .agents/skills/code-factory/scripts/check_factory_model.py; .agents/skills/code-factory/scripts/test_factory_model.py; .example.task.yaml; AGENTS.md; CHANGELOG.md; README.md; memory/change-log.md
created_files: .agents/agents/sub-agents/documenter.md; .agents/agents/sub-agents/skill-manager.md; .agents/skills/code-factory/references/documentation.md; .agents/skills/code-factory/references/reference-docs.md; .agents/skills/code-factory/scripts/skill_base.py; .agents/skills/code-factory/scripts/test_skill_base.py; .agents/skills/code-factory/scripts/test_validate_documentation.py; .agents/skills/code-factory/scripts/test_validate_mermaid.py; .agents/skills/code-factory/scripts/test_version_manager.py; .agents/skills/code-factory/scripts/validate_documentation.py; .agents/skills/code-factory/scripts/validate_mermaid.py; .agents/skills/code-factory/scripts/version_manager.py; VERSION
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: версия 12.1.0 → 12.5.0 (4 minor); documenter на secondary; skill-manager на primary; skill-base/ коммитится; mermaid-валидатор детерминированный (stdlib)
assumptions: mode hitl без вопросов (критерии машинно-проверяемы); все 4 задачи в одном прогоне/коммите
models_used: analyzer=primary; planner=primary; coder=primary; tester=primary; reviewer=primary; diagnostician=unused; documenter=secondary
factory_version: 12.5.0
unfinished: нет незавершённых элементов

## 2026-09-08T21:09:33+03:00 — Аудит системы безопасности
title: Аудит системы безопасности
project: repo
timestamp: 2026-09-08T21:09:33+03:00
branch: main
commit: (none)
task_type: security_audit
goal: полный адаптивный аудит репозитория код-фабрики v12.5.0; особое внимание — утечке API-ключей
changed_files: (none — аудит read-only, изменения кода не вносились)
created_files: .code-factory/audit/report.md; .code-factory/audit/fix-tasks.yaml
results: integration=SKIP; regression=SKIP; business=SKIP; review=SKIP
decisions: реальных секретов и опасных вызовов не найдено; единственный пробел — .gitignore не защищает .env/.pem/.key; сгенерирована fix-задача на implement
assumptions: целевой репозиторий — сама фабрика (AGENTS.md hand-authored, проверка модели в режиме --memory-only); SAST-сканеры отсутствуют — детерминированные grep-эвристики; совпадения паттернов в git-истории — только плейсхолдеры sk-xxxxx
models_used: analyzer=primary; planner=primary; coder=unused; tester=unused; reviewer=unused; diagnostician=unused; documenter=unused; security_auditor=primary
factory_version: 12.5.0
unfinished: нет незавершённых элементов

## 2026-09-08T21:28:42+03:00 — Закрыть возможность утечки API-ключей через git
title: Закрыть возможность утечки API-ключей через git
project: repo
timestamp: 2026-09-08T21:28:42+03:00
branch: main
commit: 5a966be
task_type: implement
goal: добавить защиту .env/приватных ключей в .gitignore и в автодобавляемый блок prepare_factory.sh
changed_files: .gitignore; prepare_factory.sh; VERSION; README.md; CHANGELOG.md; AGENTS.md; .agents/README.md; .agents/skills/code-factory/SKILL.md
created_files: (none)
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: версия 12.5.0 → 12.5.1 (patch, безопасность); код+версия одним коммитом v12.5.1, память — отдельным docs(memory)
assumptions: target = repo/ (подтверждено пользователем); documenter без изменений (правка не затрагивает doc-комментарии/.md); secondary-модель не выбиралась через Agent-инструмент
models_used: analyzer=primary; planner=primary; coder=primary; tester=primary; reviewer=primary; diagnostician=unused; documenter=primary; security_auditor=unused
factory_version: 12.5.1
unfinished: нет незавершённых элементов

## 2026-09-21T19:40:00+03:00 — Память фабрики принадлежит целевому проекту
title: Память фабрики принадлежит целевому проекту, а не самой фабрике
project: repo
timestamp: 2026-09-21T19:40:00+03:00
branch: feature/project-scoped-memory
commit: (none)
task_type: implement
goal: устранить смешение в memory/ истории разработки фабрики и целевого проекта; ввести признак проекта, детекцию смешения, инициализацию памяти при развёртывании и очистить память проекта get_course_downloader
changed_files: .agents/README.md; .agents/agents/code-factory.md; .agents/agents/sub-agents/analyzer.md; .agents/agents/sub-agents/code-reviewer.md; .agents/agents/sub-agents/coder.md; .agents/agents/sub-agents/diagnostician.md; .agents/agents/sub-agents/tester.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/planning-guide.md; .agents/skills/code-factory/references/tech-stack-detection.md; .agents/skills/code-factory/scripts/check_factory_model.py; .agents/skills/code-factory/scripts/test_factory_model.py; AGENTS.md; README.md; CHANGELOG.md; VERSION; memory/change-log.md; memory/summary.md; prepare_factory.sh
created_files: .agents/skills/code-factory/scripts/memory_project.py; .agents/skills/code-factory/scripts/test_memory_project.py
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: memory/ принадлежит целевому проекту (repo_path); поле project: обязательно для новых записей (basename разрешённого repo_path), разные значения в одном журнале — ошибка, отсутствие — legacy-предупреждение; объявление project:/repo_path: в сводке читается только из области после маркера до первой секции ##; prepare_factory.sh заводит память проекта и никогда не перезаписывает существующую, различая состояния ok/mixed/other; память создаётся в корне развёртывания, при repo_path-подкаталоге агент передаёт --project явно; правки в ../get_course_downloader ограничены memory/*.md и не коммитились (там идёт собственный прогон)
assumptions: целевой репозиторий этого прогона — сама фабрика (repo_path: .), поэтому project: = automated_vode_factory_v_12.15.1; запись памяти коммитится вместе с изменением, поэтому её собственный SHA не может быть записан — commit: (none); код-ревью прошло за 2 попытки (первая — request_changes с 8 замечаниями, все устранены); subagents запускались с явным model: primary из-за дефекта глобального конфига [secondary_model]
models_used: main=primary; analyzer=primary; planner=primary; coder=primary; tester=primary; reviewer=primary; diagnostician=unused; documenter=primary
factory_version: 12.6.0
unfinished:
  - item: references/planning-guide.md всё ещё говорит «init --repo <project root>» вместо «корень развёртывания»
    reason: замечание код-ревьюера severity=nit, вердикт approve; бюджет ревьюера исчерпан (2/2)
    severity: info
    follow_up: true
  - item: при сбое init скрипт prepare_factory.sh вставляет в предупреждение первую строку traceback («Traceback (most recent call last):»)
    reason: замечание severity=nit; полезнее последняя непустая строка ошибки или короткая причина
    severity: info
    follow_up: true
  - item: глобальный конфиг ~/.kimi-code/config.toml — [secondary_model] содержит таблицу models без обязательного default_model, запуск сабагента падает без явного model
    reason: файл вне рабочего каталога, правка не согласована с пользователем (по решению пользователя не правим)
    severity: warning
    follow_up: true
  - item: KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL не выставлена — разделение моделей неактивно
    reason: переменную выставляет launcher start.sh; прогон выполнялся без него
    severity: info
    follow_up: false
  - item: объявление project: ниже первой секции ## в сводке понижается до legacy-предупреждения
    reason: сознательное сужение области поиска объявления (защита от примеров внутри блоков кода), зафиксировано в docstring
    severity: info
    follow_up: false

## 2026-09-21T20:55:17+03:00 — Развёртывание и запуск фабрики в Windows

title: Развёртывание и запуск фабрики в Windows (скрипты prepare_factory и start)
project: repo
timestamp: 2026-09-21T20:55:17+03:00
branch: feature/windows-launch
commit: 37a683e
task_type: implement
goal: добавить Windows-варианты развёртывания проекта и запуска фабрики (prepare_factory, start), чтобы на Windows не требовался Git Bash — двойной клик / cmd / PowerShell; bash-путь не меняется; развёртывание работает и без установленного Python
changed_files: README.md; AGENTS.md; CHANGELOG.md; VERSION; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/tech-stack-detection.md; .agents/skills/code-factory/scripts/project_fingerprint.py; memory/change-log.md; memory/summary.md
created_files: prepare_factory.ps1; prepare_factory.cmd; start.cmd; .agents/skills/code-factory/scripts/test_windows_scripts.py
results: integration=PASS; regression=PASS; business=PASS; review=approve
decisions: PowerShell-деплойер повторяет шаги bash-версии 1:1 (поиск рабочего Python с пробным запуском, git init -b main, копирование .agents/, память проекта без перезаписи, start.sh LF + start.cmd CRLF, те же 9 правил .gitignore, тот же отчёт готовности); жёсткий сбой копирования или записи → exit 1 и «Развёртывание не завершено» без баннера «Готово», а ожидаемые деградации (нет Python → «не проверено (нет python)») остались нефатальными (exit 0); PYTHONUTF8=1 для вызовов python, иначе кириллица в пути давала мусор и ложное «память не создана»; предупреждение перед заменой существующего пользовательского start.cmd; новые launcher-файлы исключены из fingerprint-сигналов; версия 12.6.0 → 12.7.0 (minor, подтверждён ревьюером)
assumptions: целевой проект прогона — копия фабрики в ./repo (та же фабрика, repo_path указывает на подкаталог), поэтому память пишется под уже закреплённым именем проекта automated_vode_factory_v_12.15.1, а не под новым именем repo — иначе один журнал смешал бы два проекта; запись сделана в память целевого репозитория (feature-ветка), журнал корня развёртывания не менялся, так как правки в исходный репозиторий фабрики в задачу не входят; .ps1 хранится как UTF-8 с BOM, .cmd — UTF-8 без BOM, обе — CRLF (проверено побайтово); строка task.yaml про «устранение ошибок ручного запуска» устарела (подтверждено пользователем); прогон был прерван на старте бизнес-тестов и продолжен с чекпоинта pipeline.yaml
models_used: main=primary; analyzer=primary; planner=main (session model); coder=primary; tester=primary; reviewer=primary; diagnostician=unused; documenter=primary; security_auditor=unused
factory_version: 12.7.0
unfinished:
  - item: prepare_factory.ps1 — при жёстком сбое копирования .agents/ в вывод попадают сырые записи PowerShell (CategoryInfo, FullyQualifiedErrorId CopyContainerItemToLeafError): fallback Get-ChildItem | Copy-Item не обёрнут в try/catch
    reason: замечание ревьюера severity=minor при вердикте approve; контракт (exit 1, деловое сообщение, отсутствие «Готово») соблюдён
    severity: info
    follow_up: true
  - item: test_windows_scripts.py — на SKIP-пути (проект, развёрнутый фабрикой) печатается итоговый баннер «PASS - ... behave as expected», хотя проверок 0
    reason: замечание severity=nit; код возврата 0 верный, достаточно печатать баннер при passed > 0
    severity: info
    follow_up: false
  - item: start.cmd — pause без защиты от headless-запуска (в prepare_factory.cmd такая защита есть)
    reason: severity=nit, измерено безвредным (при перенаправленном stdin процесс вернулся за 0.1 с); осознанно оставлено техдолгом
    severity: info
    follow_up: false
  - item: prepare_factory.cmd — формулировка «пауза только при двойном клике» и echo %cmdcmdline% без кавычек сильнее кода
    reason: severity=nit; автотесты защищает второй признак (timeout.exe + перенаправленный stdin), он работает; оставлено техдолгом
    severity: info
    follow_up: false
  - item: check_factory_model.py без флага падает на корне фабрики (AGENTS.md hand-authored — без fingerprint и с русскими секциями)
    reason: предсуществующее — список ошибок побайтово тот же на базовом коммите 62dac43; docstring скрипта предписывает для корня фабрики режим --memory-only (с ним PASS)
    severity: warning
    follow_up: true
  - item: git-блобы .cmd/.ps1 хранятся с LF (i/lf) — CRLF восстанавливается только при core.autocrlf=true; .gitattributes в репозитории нет (касается и prepare_factory.sh)
    reason: предсуществующее свойство репозитория; launcher-ы в целевом проекте генерирует деплойер с явными CRLF/LF, поэтому дефект не проявляется на Windows-машине с autocrlf=true; введение .gitattributes вне плана задачи
    severity: warning
    follow_up: true
  - item: references/planning-guide.md говорит «init --repo <project root>» вместо «корень развёртывания»
    reason: замечание severity=nit из прогона v12.6.0, в эту задачу не входило
    severity: info
    follow_up: true
  - item: глобальный конфиг ~/.kimi-code/config.toml — [secondary_model] без обязательного default_model: запуск сабагента без явного model падает
    reason: файл вне рабочего каталога, по решению пользователя не правим; в этом прогоне все сабагенты запускались с явным model primary
    severity: warning
    follow_up: true
  - item: KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL в этом прогоне не выставлена — разделение моделей неактивно
    reason: переменную выставляет launcher start.sh/start.cmd; прогон шёл без него (models_warning в pipeline.yaml); сам launcher её выставляет — проверено в сценарии B2b
    severity: info
    follow_up: false
  - item: предсуществующий дрейф документации — в дереве скриптов .agents/README.md нет memory_project.py и test_memory_project.py; AGENTS.md называет task.yaml, тогда как в репозитории .example.task.yaml
    reason: предсуществующее (то же на базовом коммите), вне задачи про Windows-скрипты
    severity: info
    follow_up: false

## 2026-09-22T20:27:04+03:00 — Ревью фабрики по философии + план усиления (task-improvements.yaml)
title: Проверка фабрики на соблюдение философии и план её усиления по материалам
project: repo
timestamp: 2026-09-22T20:27:04+03:00
branch: feature/philosophy-review
commit: (none)
task_type: review
goal: независимое code review устройства фабрики по 4 принципам философии + сравнение с SoL-Pi/context-mode/gstack/opencode/learn-claude-code/paseo/Kaggle-курсом; результат — готовая implement-задача task-improvements.yaml
changed_files: memory/change-log.md
created_files: task-improvements.yaml (не закоммичен по решению пользователя); .code-factory/{state/task.yaml,state/pipeline.yaml,state/acceptance.md,logs/baseline.md,logs/analysis-factory.md,logs/research-solpi-contextmode-gstack.md,logs/research-opencode-lcc-paseo.md,logs/research-kaggle.md,logs/code-review.md,report.md,report_code_changes.md}
results: integration=SKIP; regression=PASS (8/8 self-тестов baseline); business=PASS (план и состав приоритетов утверждены пользователем); review=request_changes (verdict ревьюера по всему репо; rework-лист перенесён в task-improvements.yaml P1.15 — специфика review-задачи)
decisions: цель ревью — ./repo (уточнено у пользователя, две слипшиеся формулировки task.yaml слиты); skill-base в этом прогоне не создавалась — проекты изучены онлайн по README/докам, ./materials как тексты; критические находки аудита верифицированы независимым ревьюером (2a противоречие review-гейта в 5 документах; 2b слепота fingerprint глубже 1 уровня — доказано эмпирически); LSP/MCP/демоны/своя компакция/worktree сознательно отклонены (даже opencode отключил LSP); матрица моделей K3+deepseek-flash подтверждена с поправкой generator≠judge (advisor=deepseek-flash); версия не меняется (review → none); task-improvements.yaml и materials/ не коммитятся по решению пользователя
assumptions: opencode-ai/opencode заархивирован (переехал в charmbracelet/crush) — изучены README архива и доки нового anomalyco/opencode; PDF в materials не читались (есть транскрипты); имя проекта в памяти оставлено automated_vode_factory_v_12.15.1 несмотря на выявленную ложность (исправление — P1.14 будущего прогона, чтобы не смешивать конвенции вне задачи)
models_used: main=primary; analyzer=primary; planner=main; coder=unused; tester=unused; reviewer=primary; diagnostician=unused; documenter=unused; research explore×3=primary
factory_version: 12.7.0
unfinished:
  - item: реализовать план усиления task-improvements.yaml (P0×7 — шарды, двухуровневый fingerprint, Think in Code, унификация review-гейта, верифицируемая приёмка, verify_quotes, handoff-шаблоны; P1×8; P2 backlog)
    reason: главный результат прогона; файл лежит некоммиченным в ./repo (по решению пользователя)
    severity: critical
    follow_up: true
  - item: вердикт код-ревьюера request_changes (1 critical + 1 major + 16 minor/nit) не исправлен в коде, а перенесён в план
    reason: специфика task_type=review — замечания становятся планом (task-improvements.yaml P0.4, P1.14, P1.15)
    severity: warning
    follow_up: true
  - item: декларация project: automated_vode_factory_v_12.15.1 в памяти ложна (опечатка, ≠ basename), но проходит оба валидатора
    reason: конвенция project=basename(repo_path) машинно не enforced; исправление включено в P1.14
    severity: warning
    follow_up: true
  - item: ~/.kimi-code/config.toml исправлен вне репозитория (удалён secondary_model.force, конфликтовавший с models-пулом)
    reason: блокировал запуск любых сабагентов; исправлено по согласию пользователя; бэкап config.toml.bak-factory-20260923
    severity: info
    follow_up: false

## 2026-09-24T00:00:00+03:00 — Усиление фабрики v12.8.0: шарды, fingerprint, Think in Code, верифицируемая приёмка, антигаллюцинационные гейты
title: Усиление фабрики: шардирование whole-repo операций, двухуровневый fingerprint, Think in Code, верифицируемая приёмка и антигаллюцинационные гейты
project: repo
timestamp: 2026-09-24T00:00:00+03:00
branch: feature/factory-hardening-2026-09-24
commit: cf0f4e1
task_type: implement
goal: реализовать план усиления из task-improvements.yaml: P0×7 (шарды, двухуровневый fingerprint, Think in Code, единый review-гейт, верифицируемая приёмка, verify_quotes, handoff-шаблон), P1×8, P2 — backlog
changed_files: 29 файлов (scripts: project_fingerprint, check_factory_model, memory_project, gen_code_changes_report, version_manager, validate_documentation + тесты; references: code-review, security-audit, providers, verification-strategy, error-routing, tech-stack-detection, reference-docs; sub-agents: analyzer, tester, diagnostician, code-reviewer, security-auditor; code-factory.md, SKILL.md, AGENTS.md, .agents/README.md, task-template.yaml, prepare_factory.sh/.ps1, CHANGELOG, VERSION, memory/*)
created_files: scripts/{repo_inventory,merge_findings,log_tail,repo_stats,verify_acceptance,verify_quotes,evidence_ledger,factory_preflight,action_gate,task_graph}.py + 11 test_*.py; sub-agents/advisor.md; references/handoff-briefing.md; skill-base/skills/kaggle-agents-course/ (из ../materials, 68 файлов)
results: integration=PASS (19/19 test_*.py); regression=PASS (8/8 существующих без ослабления + 11 новых; check_factory_model --memory-only PASS); business=PASS (шарды: 45k строк → 3 шарда, merge с дедупликацией; fingerprint: повтор эксперимента 2026-09-23 — structural неизменен, content сдвинут; приёмка SUCCESS 11 MET + 1 derived); review=approve (итерация 2/2: 2 major закрыты и проверены эмпирически, цитаты ревьюера verify_quotes 4/4 VERIFIED)
decisions: владелец памяти мигрирован automated_vode_factory_v_12.15.1 → repo (rename, подтверждено пользователем); строгий вариант верифицируемой приёмки; skill kaggle-agents-course создан на k3 и оставлен (валиден, rerun на flash без выгоды — решение пользователя); устаревшее правило «не передавать model в Agent tool» исправлено — CLI поддерживает явный model:, secondary-роли запускались на deepseek-flash по матрице; nit fingerprint (index-based) оставлен задокументированным решением; start.cmd pause-finding отклонён как неточный; версия 12.7.0 → 12.8.0 (minor, новый сабагент advisor, валидировано ревьюером)
assumptions: канонический блок review-гейта вставлен русским текстом во все 5 документов включая англоязычные (тест требует байт-идентичности); advisor из P0.7 покрывается его созданием в P1.8
models_used: main=primary; analyzer=primary; planner=main; coder=deepseek-flash ×12; tester=unused (тесты писали кодеры); reviewer=primary; diagnostician=unused; advisor=unused; documenter=deepseek-flash; skill_manager=primary (расход с матрицей, зафиксирован)
factory_version: 12.8.0
unfinished:
  - item: P2 backlog — единый rulebook references/factory-rules.md + consistency-checker (B5)
    reason: осознанно не реализовано (P2 задачи); кандидат на следующий прогон
    severity: info
    follow_up: true
  - item: P2 backlog — вынос доменных regex из error-routing в project-learned patterns (B3)
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: P2 backlog — evaluate-your-evaluator: golden-set diff'ов для калибровки ревьюера
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: P2 backlog — вакцинация: баг после приёмки → регрессионный тест до фикса (норма)
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: P2 backlog — provenance/confidence метки (verified/inferred) в памяти
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: P2 backlog — сквозной run_id во всех артефактах .code-factory/
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: P2 backlog — WIP-checkpoints со структурированным телом; committee при двойном rejection плана; FTS5-индекс memory/ и кодовой базы (stdlib sqlite3)
    reason: осознанно не реализовано (P2 задачи)
    severity: info
    follow_up: true
  - item: контентный fingerprint читает git-индекс — unstaged-правки невидимы (nit ревьюера)
    reason: осознанное задокументированное решение; fallback покрывает non-git проекты
    severity: info
    follow_up: false
  - item: action_gate.py — uncaught OSError при незаписываемом журнале (nit ревьюера)
    reason: fails closed, не опасно; некритично
    severity: info
    follow_up: false
  - item: память корня развёртывания (../memory) всё ещё декларирует automated_vode_factory_v_12.15.1
    reason: память repo (целевого проекта) мигрирована; корневая память — отдельный deployment, вне scope задачи
    severity: info
    follow_up: false

## 2026-09-23T00:19:00+03:00 — Фабрика v2 (v12.9.0): rulebook + consistency-checker, run_id, provenance-память, калибровка ревьюера, WIP-checkpoints, error-patterns
title: Фабрика v2: единый rulebook с consistency-checker, сквозной run_id, provenance-метки памяти, golden-set калибровка ревьюера, вакцинация, WIP-checkpoints, project-learned error-patterns
project: repo
timestamp: 2026-09-23T00:19:00+03:00
run_id: 20260922-442cd2f8
branch: feature/factory-v2-rulebook-runid
commit: 23236b1
task_type: implement
goal: реализовать P2-backlog прогона v12.8.0: P0 (rulebook + check_factory_rules, сквозной run_id, provenance-метки verified/inferred в памяти), P1 (golden-set калибровка ревьюера, вакцинация, WIP-checkpoints, error-patterns JSON), P2 — backlog
changed_files: AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/agents/sub-agents/code-reviewer.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/code-review.md; .agents/skills/code-factory/references/error-routing.md; .agents/skills/code-factory/scripts/test_review_gate.py (тонкая обёртка); verify_acceptance.py; gen_code_changes_report.py; evidence_ledger.py (--run-id); memory_project.py; check_factory_model.py (v2 + check_pipeline_checkpoints); test_memory_project.py; test_factory_model.py; test_verify_acceptance.py; test_evidence_ledger.py (только расширения); memory/change-log.md (заголовок v2); README.md; CHANGELOG.md; VERSION
created_files: references/factory-rules.md (20 правил); references/error-patterns.default.json (20+6 паттернов); scripts/check_factory_rules.py; scripts/run_id.py; scripts/calibrate_reviewer.py; scripts/error_router.py + 4 test_*.py; skill-base/golden-set/ (7 кейсов, commit_exclude — не коммитится)
results: integration=PASS (23/23 test_*.py) [verified: .code-factory/logs/test-results.md]; regression=PASS (19 существующих без ослабления + 4 новых; check_factory_rules 20 правил/71 блок exit 0) [verified: .code-factory/logs/test-results.md]; business=PASS (калибровка ревьюера на golden-set: verdict accuracy 7/7 (100%), macro precision 0.619 / recall 0.857 — ревьюер склонен завышать severity) [verified: .code-factory/logs/reviewer-calibration.md]; review=approve (итерация 2/2: 1 critical — мёртвый version-триггер _v2_record, 1 major — запечатлённая дата в test_run_id, 5 minor/nit; все закрыты и проверены эмпирически, цитаты 19/19 VERIFIED) [verified: .code-factory/logs/code-review.md]
decisions: «новая» memory-запись определена гейтом factory_version>12.8.0 ИЛИ наличием v2-полей — иначе все 8 существующих записей с project: стали бы ошибками [verified: scripts/test_factory_model.py]; маркер review-gate-policy заменён на factory-rule: review-gate-policy в 5 носителях с дословным текстом, test_review_gate.py слит в обёртку без ослабления [verified: test_review_gate.py PASS, REQUIRED_MARKERS сохранены]; evidence ledger требует единого scope --files на stamp и check, иначе STALE [verified: evidence_ledger.py evaluate()]; классификация ошибок — JSON-first (project error-patterns.json > default), таблицы error-routing.md оставлены справочными, quirks слепка задокументированы [verified: references/error-routing.md §1]; версия 12.8.0 → 12.9.0 (minor по матрице --new-field/--new-subagent, валидировано ревьюером без override) [verified: version_manager.py validate exit 0]
assumptions: golden-set не коммитится (commit_exclude задачи) [verified: task.yaml]; пункт «версия в README не обновлена» снят пользователем — симптом не воспроизвёлся (локально и origin/main везде 12.8.0) [verified: git show origin/main:README.md]
models_used: main=primary; analyzer=kimi-code/k3 ×2; coder=deepseek-flash ×6 (rulebook, run_id, golden-set, error-patterns, память+checkpoints, rework); documenter=deepseek-flash; reviewer=kimi-code/k3 ×9 (7 калибровочных кейсов + 2 итерации ревью); diagnostician=unused; advisor=unused
factory_version: 12.9.0
unfinished:
  - item: P2 backlog — committee при двойном rejection плана (второй независимый planner + детерминированный arbiter)
    reason: P2 задачи — осознанно не реализованы, зафиксированы как backlog
    severity: info
    follow_up: true
  - item: P2 backlog — FTS5-индекс memory/ и кодовой базы (stdlib sqlite3) для поиска прецедентов
    reason: P2 задачи — осознанно не реализованы
    severity: info
    follow_up: true
  - item: калибровка выявила систематическое завышение severity ревьюером (deleted-test: ожидался major, дан critical; missing-error-handling: лишние critical/minor)
    reason: вердикты точны (7/7), но severity-калибровка промпта ревьюера — кандидат на следующий прогон
    severity: info
    follow_up: true
  - item: quirks слепка error-patterns: строка 8 (error[E\d+] — character class), строка 18 (незаэкранированные скобки), 16 затеняет 17, нюанс §2 WRONG_RESULTS/regression мёртв при JSON-first
    reason: перенесены дословно как слепок таблиц; задокументированы в Known quirks error-routing.md §1
    severity: info
    follow_up: false
  - item: check_factory_model.py без --memory-only падает на hand-authored корневом AGENTS.md фабрики
    reason: предсуществующее (см. запись v12.7.0); для корня фабрики предписан режим --memory-only
    severity: warning
    follow_up: true

## 2026-09-23T02:00:00+03:00 — Фабрика v3 (v12.10.0): severity-калибровка ревьюера, committee при двойном rejection плана, FTS5-индекс, check_factory_model на корне фабрики
title: Фабрика v3: committee при двойном rejection плана, FTS5-индекс memory и кодовой базы, severity-калибровка ревьюера по golden-set, корректный режим check_factory_model для корня фабрики
project: repo
timestamp: 2026-09-23T02:00:00+03:00
run_id: 20260923-bcbe68b3
branch: feature/factory-v3-backlog-20260923
commit: 3e1a1bb
task_type: implement
goal: реализовать backlog прогона v12.9.0: P0 (severity-калибровка ревьюера, committee при двойном rejection плана, check_factory_model на корне фабрики), P1 (FTS5-индекс, норма калибровки §7), P2 — backlog; дополнительно одобрено: починка test_run_id.py и финальный backlog-task.yaml
changed_files: references/code-review.md (§3 граница critical/major + Reporting discipline, §7 норма калибровки); sub-agents/code-reviewer.md; scripts/check_factory_model.py (трёхсигнальный авто-детект корня фабрики → SKIP); scripts/test_factory_model.py (кейсы 28a-d); scripts/test_run_id.py (пин на fixture 4b918a06); references/factory-rules.md (21-е правило plan-committee); SKILL.md (mermaid-ветка committee); .agents/agents/code-factory.md (Phase 3 + frontmatter factory-planner); references/planning-guide.md (§4 контракт арбитра, §6 committee); AGENTS.md; .agents/README.md; CHANGELOG.md; VERSION; README.md; sub-agents/{analyzer,diagnostician}.md (precedent_index)
created_files: scripts/plan_arbiter.py + test_plan_arbiter.py; scripts/precedent_index.py + test_precedent_index.py; sub-agents/planner.md; .code-factory/{state/*,logs/*,backups/*,manifest.json,report.md,report_code_changes.md}
results: integration=PASS (25/25 self-тестов: 23 существующих без ослабления + test_plan_arbiter + test_precedent_index) [verified: .code-factory/logs/test-results.md]; regression=PASS (check_factory_rules 21 правило/75 блоков, validate_mermaid 85 edges, check_factory_model --repo . SKIP+exit 0, run_id check 4/4) [verified: .code-factory/logs/test-results.md]; business=PASS 3/3 (калибровка: accuracy 7/7, macro precision 0.619→0.857, recall 0.857→1.000; check_factory_model на корне — SKIP без traceback; plan_arbiter на двух планах — merged + расхождения) [verified: .code-factory/logs/business-tests.md, .code-factory/logs/reviewer-calibration.md]; review=approve (итерация 3 по решению пользователя: critical детектора закрыт трёхсигнальной проверкой, major pi.SYMLINK_REL закрыт, открытых findings нет; цитаты 3/3 VERIFIED) [verified: .code-factory/logs/code-review.md, .code-factory/logs/quotes-review-1.md]; acceptance=SUCCESS (5 verified MET, 2 unverified, ledger FRESH×2, exit 0) [verified: .code-factory/state/acceptance.md]
decisions: golden-set восстановлен копированием из ../automated_code_factory_v12.8.0 (решение пользователя; commit_exclude, не коммитится) [verified: skill-base/golden-set/cases — 7 кейсов]; эталоны expected.yaml НЕ сдвигались — точность поднята промптом §3 (Reporting discipline: одна первопричина = одно finding; субъективное не сообщается) [verified: .code-factory/logs/reviewer-calibration.md раунды 0.786→0.857]; детектор корня фабрики = 3 сигнала (нет fingerprint + code-factory-version в line 1 + развёрнут SKILL.md) — SKILL.md alone слишком широкий (развёрнут в каждом целевом проекте), critical ревьюера итерации 1 [verified: test_factory_model.py кейсы 28a-d]; test_run_id перепинован на закоммиченный fixture assets/task-template.yaml вместо эфемерного .code-factory/state/task.yaml [verified: test_run_id.py PASS без .code-factory]; committee: planner-2 из контрастного семейства (kimi-k3→deepseek-flash), арбитр детерминированный stdlib, committee не более одного раза на задачу [verified: SKILL.md mermaid, plan_arbiter.py]; версия 12.9.1 → 12.10.0 (minor по матрице --new-subagent, валидировано ревьюером без override) [verified: version_manager.py validate exit 0]
assumptions: норма калибровки §7 — мягкий гейт (пороги accuracy 100%, precision ≥ 0.8 — повод перекалибровать промпт, не сдвигать эталоны) [verified: references/code-review.md §7]; symlink-под-проверка test_precedent_index self-skip'ается на хостах без прав (на этом хосте skip; гард доказан пробой со stub is_symlink) [verified: .code-factory/logs/code-review.md итерация 3]; корневая memory развёртывания и repo/memory — зеркала, запись внесена в обе [inferred]
models_used: main=primary; analyzer=kimi-code/k3 ×2; coder=deepseek-flash ×5; reviewer=kimi-code/k3 (14 калибровка + 3 ревью); documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.10.0
unfinished:
  - item: P2 backlog — gen_code_changes_report.py падает traceback'ом на --help
    reason: P2 задачи — осознанно не реализованы, зафиксированы как backlog (вынесено в task.yaml следующего прогона)
    severity: info
    follow_up: true
  - item: P2 backlog — контентный fingerprint читает git-индекс, unstaged-правки невидимы
    reason: P2; задокументированный nit с v12.8.0
    severity: info
    follow_up: true
  - item: P2 backlog — action_gate.py uncaught OSError при незаписываемом журнале (fails closed)
    reason: P2; nit с v12.8.0
    severity: info
    follow_up: true
  - item: P2 backlog — git-блобы .cmd/.ps1 с LF; .gitattributes покрывает только error-patterns.default.json
    reason: P2; прогон v12.9.1
    severity: info
    follow_up: true
  - item: устаревшие советы --memory-only для корня фабрики в tech-stack-detection.md:176 и memory_project.py:150
    reason: после авто-детекта v12.10.0 совет избыточен; кодер task_01 зафиксировал как out-of-scope
    severity: info
    follow_up: true
  - item: nit-naming — последний false positive калибровки (ревьюер сообщает nit при expected=[])
    reason: precision 0.857 при цели ≥0.8 достигнута; дальнейшее подавление nit'ов рискует over-suppression
    severity: info
    follow_up: false

## 2026-09-23T11:20:00+03:00 — Фабрика v4 (v12.10.1): P0-хвосты backlog v12.10.0 (argparse-контракт, fingerprint dirty-warning, action_gate exit 3, CRLF-пины, гигиена --memory-only) + nit-naming precision 1.000 + golden-set в git
title: Фабрика v4: argparse-контракт gen_code_changes_report, контентный fingerprint и unstaged-правки, action_gate OSError, CRLF для .cmd/.ps1, гигиена --memory-only + P1 nit-naming
project: repo
timestamp: 2026-09-23T11:20:00+03:00
run_id: 20260923-3540d5dc
branch: feature/factory-v4-backlog-20260923
commit: d07bded
task_type: implement
goal: реализовать backlog прогона v12.10.0: P0 (gen_code_changes_report --help без traceback, fingerprint dirty-warning, action_gate OSError → exit 3, CRLF-пины *.cmd/*.ps1, гигиена --memory-only), P1 (nit-naming false positive), плюс по решению пользователя — golden-set в git
changed_files: .agents/skills/code-factory/scripts/{gen_code_changes_report.py,project_fingerprint.py,check_factory_model.py,action_gate.py,memory_project.py,test_action_gate.py,test_factory_model.py,test_windows_scripts.py}; .gitattributes; references/{code-review.md,tech-stack-detection.md}; sub-agents/code-reviewer.md; AGENTS.md; .agents/README.md; CHANGELOG.md; README.md; VERSION
created_files: scripts/test_gen_code_changes_report.py; skill-base/golden-set/ (7 кейсов + README — восстановлен из ../automated_code_factory_v12.9.1 и ВПЕРВЫЕ закоммичен); .code-factory/{state/*,logs/*,backups/*,manifest.json,report.md,report_code_changes.md}
results: integration=PASS (26/26 test_*.py: 25 существующих без ослабления + test_gen_code_changes_report) [verified: .code-factory/logs/test-results.md]; regression=PASS (check_factory_rules 21/75 exit 0, validate_mermaid 85 edges, check_factory_model SKIP+exit 0) [verified: .code-factory/logs/test-results.md]; business=PASS 3/3 (BT-1 живой прогон report_code_changes.md 34 файла exit 0; BT-2 калибровка accuracy 7/7, macro precision 0.857→1.000, recall 1.000, nit-naming чист; BT-3 ls-files --eol i/lf w/crlf + attr/text eol=crlf) [verified: .code-factory/logs/business-tests.md, .code-factory/logs/reviewer-calibration.md]; review=approve (итерация 1/2, findings=[], вакцинация подтверждена, commit hygiene чист) [verified: .code-factory/logs/code-review.md]; acceptance=SUCCESS (7 verified MET + 1 derived, ledger FRESH×2, exit 0) [verified: .code-factory/state/acceptance.md]
decisions: P0.2 — индексное хэширование fingerprint СОХРАНЕНО + dirty-tree warning (решение делегировано агенту: платформенная/CRLF-стабильность, commit-стабильность, дешёвая проверка при каждом старте; хэш рабочего дерева дал бы вечные ложные перегенерации AGENTS.md) [verified: test_factory_model.py кейс 29]; action_gate — новый exit 3 (journal write failure), решение печатается ДО записи журнала [verified: test_action_gate.py кейс 15]; golden-set коммитится в git — решение пользователя при rejection #1 плана (фикстура нужна постоянно: test_calibrate_reviewer падает без неё, §7 требует периодической калибровки); commit_exclude прогона = task*.yaml + reference_docs/** [verified: git show --stat d07bded — 34 файла, golden-set включён]; версия 12.10.0 → 12.10.1 (patch по матрице --fix; ревьюер валидировал без override: exit 3 — документированное сужение crash-контракта, patch-класс) [verified: version_manager.py validate exit 0]
assumptions: nit-naming FP устранён правкой промпта §3 (нейтральный rename — тишина, не nit), эталоны не сдвигались [verified: reviewer-calibration.md round 2]; round 1 калибровки 5/7 — ошибка брифинга главного агента (verdict-правило «только critical» вместо «critical OR major», code-review.md:200), не промпта [verified: .code-factory/logs/reviewer-calibration.md rounds]; предупреждения git «LF will be replaced by CRLF» при коммите — следствие новых CRLF-пинов, блобы корректны (i/lf) [inferred]
models_used: main=primary; analyzer=kimi-code/k3 ×1; coder=deepseek-flash ×6; reviewer=kimi-code/k3 ×11 (1 ревью + 9 калибровка + 1 версия); documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.10.1
unfinished:
  - item: action_gate.py --help падает UnicodeEncodeError на cp1251-консоли (docstring содержит «→») — пре-существующий баг, найден кодером task_03; фикс = тот же паттерн use_utf8_output(), что и P0.1
    reason: вне scope задачи v4; зафиксирован эмпирически (HEAD-версия тоже падает)
    severity: info
    follow_up: true
  - item: гигиена процесса — coder task_03 использовал git stash/pop на ОБЩЕМ дереве параллельного прогона (риск гонки); кандидат в правило брифинга coder'ов
    reason: инцидент прогона без последствий (дерево проверено, stash пуст), но паттерн опасен
    severity: info
    follow_up: true

## 2026-09-23T12:56:13+03:00 — Фабрика v5 (v12.10.2): utf8-guard во всех argparse-скриптах (action_gate --help на cp1251) + 22-е правило no-shared-tree-git-mutations
title: Фабрика v5: action_gate --help без traceback на cp1251, utf8-guard во всех argparse-скриптах, запрет git stash на общем дереве как 22-е правило rulebook
project: repo
timestamp: 2026-09-23T12:56:13+03:00
run_id: 20260923-598c99c1
branch: feature/factory-v5-backlog-20260923
commit: ed62e88
task_type: implement
goal: реализовать backlog прогона v12.10.1: P0.1 action_gate --help на cp1251 (фикс + вакцина), P0.1b анализ и фикс остальных скриптов, P0.2 запрет git stash на общем дереве; task_05 — follow-up task-файл
changed_files: 32 файла — 22 scripts/*.py (inline use_utf8_output + вызов первой строкой main); test_action_gate.py (кейс 16 cp1251); references/factory-rules.md (22-е правило); AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; references/handoff-briefing.md; sub-agents/coder.md; VERSION; CHANGELOG.md; README.md
created_files: task-v6.yaml (не закоммичен, commit_exclude); .code-factory/{state/*,logs/*,manifest.json,report.md,report_code_changes.md}
results: integration=PASS (26/26 test_*.py без ослабления) [verified: .code-factory/logs/test-results.md]; regression=PASS (check_factory_rules 22 правила/81 блок exit 0, validate_mermaid 85 edges, check_factory_model SKIP+exit 0, run_id check 3/3) [verified: .code-factory/logs/test-results.md]; business=PASS 3/3 (BT-1 cp1251 sweep 24/24 exit 0; BT-2 rulebook consistent; BT-3 запрет stash в coder.md и handoff-briefing.md) [verified: .code-factory/logs/business-tests.md]; review=approve (итерация 1/2, findings=[], вакцинация кейса 16 подтверждена на pre-fix коде, commit hygiene чист) [verified: .code-factory/logs/code-review.md]; acceptance=SUCCESS (5 verified MET + 1 derived, ledger FRESH×3, exit 0) [verified: .code-factory/state/acceptance.md]
decisions: эмпирический sweep под PYTHONIOENCODING=cp1251 показал, что реально падает только action_gate.py, но по решению пользователя guard добавлен во все 22 argparse-скрипта с не-ASCII docstring [verified: .code-factory/logs/business-tests.md BT-1]; в error_router/plan_arbiter слабый пре-существующий guard (только stdout) заменён эталонным, в log_tail/precedent_index guard стоял после parse_args и не защищал --help — перемещён; ревьюер проверил все 4 отклонения [verified: .code-factory/logs/code-review.md]; запрет git stash оформлен 22-м правилом rulebook no-shared-tree-git-mutations (решение пользователя), 6 носителей byte-identical [verified: check_factory_rules.py exit 0]; версия 12.10.1 → 12.10.2 (patch по матрице --fix, ревьюер валидировал без override: новое правило — процессная норма, прецедент v12.10.1) [verified: version_manager.py validate exit 0]; follow-up backlog записан в task-v6.yaml по замечанию пользователя при rejection #1 плана [verified: task-v6.yaml]
assumptions: skill_base.py не трогали (не-ASCII нет) [verified: sweep]; классификация git stash в action_gate.py (сейчас fail-safe CONFIRM) вынесена в backlog task-v6.yaml [inferred]; память repo/memory и корня развёртывания — зеркала, запись внесена в обе [inferred]
models_used: main=primary; analyzer=explore primary; coder=deepseek-flash ×3; reviewer=kimi-code/k3 ×2 (ревью + валидация версии); documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.10.2
unfinished:
  - item: action_gate.py не классифицирует git stash явно (fail-safe CONFIRM) — после 22-го правила стоит явная классификация; вынесено в task-v6.yaml P0.1
    reason: вне scope задачи v5 (там — только брифинги/правило); зафиксировано при анализе
    severity: info
    follow_up: true
  - item: устаревшие советы --memory-only для корня фабрики в tech-stack-detection.md (~176) и memory_project.py (~150) — после авто-детекта v12.10.0 совет избыточен; вынесено в task-v6.yaml P0.2
    reason: follow_up из прогона v12.10.0, в задачу v5 не входило
    severity: info
    follow_up: true
  - item: P2 backlog — контентный fingerprint читает git-индекс, unstaged-правки невидимы (dirty-warning смягчает)
    reason: задокументированный nit с v12.8.0; в task-v6.yaml как P2
    severity: info
    follow_up: true

## 2026-09-24T00:47:29+03:00 — Фабрика v6 (v12.11.0): полная очистка backlog — stash в action_gate, механизм актуальности памяти (backlog/closed: + 23-е правило), fingerprint по рабочему дереву, project-learned overlay, гигиена деплойеров
title: Фабрика v6: явная классификация git stash в action_gate, гигиена советов --memory-only, старые nit'ы (ps1 try/catch, planning-guide wording) + закрытие ВСЕГО backlog разработкой + механизм актуальности памяти
project: repo
timestamp: 2026-09-24T00:47:29+03:00
run_id: 20260923-271a9782
branch: feature/factory-v6-backlog-20260923
commit: 4b6652c
task_type: implement
goal: backlog прогона v12.10.2 + все открытые follow_up истории (32 пункта) закрыты разработкой/доказательствами; по требованию пользователя — расследование устаревания памяти и механизм «память всегда актуальна»
changed_files: 25 файлов (коммит 4b6652c) — action_gate.py (+classify_stash, разбор -m/--message), project_fingerprint.py + check_factory_model.py (хэш по рабочему дереву, untracked_files), error_router.py (overlay fallback), memory_project.py (backlog/closed:), factory-rules.md + 5 носителей (23-е правило), SKILL.md + code-factory.md (шаги flow), providers.md §5.2, planning-guide.md, tech-stack-detection.md §7, prepare_factory.ps1/.sh, .gitattributes, тесты ×5, VERSION/CHANGELOG/README/AGENTS.md
created_files: .code-factory/{state/*,logs/*,manifest.json,report.md,report_code_changes.md}; новых файлов кода нет
results: integration=PASS (26/26 test_*.py без ослабления) [verified: .code-factory/logs/test-results.md]; regression=PASS (check_factory_rules 23 правила/86 блоков exit 0, check_factory_model SKIP+exit 0, version_manager validate 12.11.0 exit 0, run_id check exit 0) [verified: .code-factory/logs/test-results.md]; business=PASS 6/6 (BT-1 stash CONFIRM/ALLOW живьём; BT-2 fingerprint видит unstaged; BT-3 деплойеры деловые сообщения; BT-4 канон 23 правила + grep-контроль; BT-5 backlog --check ловит молчаливое исчезновение; BT-6 open:32 как промежуточный) [verified: .code-factory/logs/business-tests.md]; review=approve (итерация 2/2: critical classify_stash -m/--message закрыт rework + negative-control, minor docstring закрыт, nit закрыт) [verified: .code-factory/logs/code-review.md]; acceptance=SUCCESS [verified: .code-factory/state/acceptance.md]; backlog=0 открытых по всей истории [verified: memory_project.py backlog --repo . --check exit 0]
decisions: P0.1 stash -> CONFIRM с объяснением (решение пользователя, не HARD_DENY) [verified: task.yaml + диалог]; P0.2 --memory-only — широкий sweep, 0 носителей (советы удалены в v12.10.1) [verified: BT-4]; пользователь потребовал backlog пуст РАЗРАБОТКОЙ по всей истории (32 пункта) — 7 закрыты кодом v6, 25 закрыты ранее с доказательствами [verified: logs/memory-actuality-rca.md таблица]; первопричина устаревания памяти — 5 звеньев (нет переноса/идентификатора/проверки закрытия/актуализации сводки/шага сверки) [verified: logs/memory-actuality-rca.md]; механизм — вариант B комитета: closed:+evidence: + backlog --check + 23-е правило (выбор пользователя при approval) [verified: state/plan.md, factory-rules.md]; доменные regex — реализованы (решение пользователя): overlay уже был в v12.9.0, v6 добавил fallback+§1.2+тесты [verified: test_error_router.py 9a/9b]; версия minor 12.10.2 -> 12.11.0 (матрица --new-field, ревьюер валидировал без override) [verified: version_manager.py validate exit 0, logs/code-review.md]
assumptions: staged-new файл двигает хэш (git add вводит в tracked set) — задокументировано [verified: кейс 29d]; planner-2 комитета запущен на deepseek-flash по правилу plan-committee (контрастное семейство сильнее матрицы) — теперь задокументировано в providers.md §5.2 [verified: providers.md:152]
models_used: main=primary (kimi-code/k3); analyzer=kimi-code/k3; planner-2=deepseek-flash (комитет); coder=deepseek-flash ×5 (task_01/07/15/03+05+06/02+04+16) + rework ×1 + task_11 + task_12; tester=deepseek-flash; reviewer=kimi-code/k3 (2 итерации + валидация версии); documenter=deepseek-flash; RCA-разведка=explore kimi-code/k3; diagnostician=unused; advisor=unused
factory_version: 12.11.0
unfinished: нет незавершённых элементов
closed:
  - item: references/planning-guide.md всё ещё говорит «init --repo <project root>» вместо «корень развёртывания»
    evidence: v6 task_04: planning-guide.md:37 -> init --repo <deployment root> [verified: git grep "deployment root" -- references/planning-guide.md]
  - item: при сбое init скрипт prepare_factory.sh вставляет в предупреждение первую строку traceback («Traceback (most recent call last):»)
    evidence: v6 task_05: короткая причина через awk last non-empty [verified: test_windows_scripts.py PASS + business-tests.md BT-3]
  - item: глобальный конфиг ~/.kimi-code/config.toml — [secondary_model] содержит таблицу models без обязательного default_model, запуск сабагента падает без явного model
    evidence: исправлено вне репо ранее: config.toml:5 default_model = "kimi-code/k3" под [secondary_model] [verified: чтение ~/.kimi-code/config.toml, RCA #3]
  - item: prepare_factory.ps1 — при жёстком сбое копирования .agents/ в вывод попадают сырые записи PowerShell (CategoryInfo, FullyQualifiedErrorId CopyContainerItemToLeafError): fallback Get-ChildItem | Copy-Item не обёрнут в try/catch
    evidence: v6 task_03: try/catch + -ErrorAction Stop + $script:HardError [verified: BT-3 живое ACL-deny: exit 1, без баннера, 0 сырых записей]
  - item: check_factory_model.py без флага падает на корне фабрики (AGENTS.md hand-authored — без fingerprint и с русскими секциями)
    evidence: v12.10.0 (3e1a1bb): трёхсигнальный авто-детект корня фабрики -> SKIP [verified: check_factory_model.py:150-154, BT-4 exit 0]
  - item: git-блобы .cmd/.ps1 хранятся с LF (i/lf) — CRLF восстанавливается только при core.autocrlf=true; .gitattributes в репозитории нет (касается и prepare_factory.sh)
    evidence: v12.10.1 (d07bded): .gitattributes:5-6 cmd/ps1 eol=crlf; остаток *.sh закрыт v6 task_06 (.gitattributes:9) [verified: git check-attr eol -> lf]
  - item: references/planning-guide.md говорит «init --repo <project root>» вместо «корень развёртывания»
    evidence: как пункт #1 — v6 task_04 [verified: git grep "deployment root"]
  - item: глобальный конфиг ~/.kimi-code/config.toml — [secondary_model] без обязательного default_model: запуск сабагента без явного model падает
    evidence: как пункт #3 — config.toml:5 [verified: чтение файла]
  - item: реализовать план усиления task-improvements.yaml (P0×7 — шарды, двухуровневый fingerprint, Think in Code, унификация review-гейта, верифицируемая приёмка, verify_quotes, handoff-шаблоны; P1×8; P2 backlog)
    evidence: v12.8.0 (cf0f4e1): план реализован [verified: repo_inventory.py, verify_acceptance.py, handoff-briefing.md существуют]
  - item: вердикт код-ревьюера request_changes (1 critical + 1 major + 16 minor/nit) не исправлен в коде, а перенесён в план
    evidence: v12.8.0: замечания стали планом P0.4/P1.14/P1.15 и реализованы [verified: запись v12.8.0 в change-log.md]
  - item: декларация project: automated_vode_factory_v_12.15.1 в памяти ложна (опечатка, ≠ basename), но проходит оба валидатора
    evidence: v12.8.0: владелец мигрирован -> repo [verified: все записи журнала project: repo; check_factory_model exit 0]
  - item: P2 backlog — единый rulebook references/factory-rules.md + consistency-checker (B5)
    evidence: v12.9.0 (23236b1): references/factory-rules.md + scripts/check_factory_rules.py [verified: 23 правила, 86 блоков, exit 0]
  - item: P2 backlog — вынос доменных regex из error-routing в project-learned patterns (B3)
    evidence: v12.9.0: error_router.py + error-patterns.default.json; v6 task_15: overlay §1.2 + fallback + кейсы 9a/9b [verified: test_error_router.py PASS]
  - item: P2 backlog — evaluate-your-evaluator: golden-set diff'ов для калибровки ревьюера
    evidence: v12.9.0: calibrate_reviewer.py + skill-base/golden-set (7 кейсов) [verified: test_calibrate_reviewer.py PASS]
  - item: P2 backlog — вакцинация: баг после приёмки → регрессионный тест до фикса (норма)
    evidence: v12.9.0: правило vaccination в factory-rules.md [verified: check_factory_rules.py exit 0]
  - item: P2 backlog — provenance/confidence метки (verified/inferred) в памяти
    evidence: v12.9.0: формат v2 с метками [verified: memory_project.py:177-187, записи v12.9.0+]
  - item: P2 backlog — сквозной run_id во всех артефактах .code-factory/
    evidence: v12.9.0: scripts/run_id.py; записи несут run_id [verified: run_id.py check --dir .code-factory exit 0]
  - item: P2 backlog — WIP-checkpoints со структурированным телом; committee при двойном rejection плана; FTS5-индекс memory/ и кодовой базы (stdlib sqlite3)
    evidence: WIP — v12.9.0 (pipeline.yaml ключи); committee + FTS5 — v12.10.0 (3e1a1bb) [verified: plan_arbiter.py, precedent_index.py существуют]
  - item: P2 backlog — committee при двойном rejection плана (второй независимый planner + детерминированный arbiter)
    evidence: v12.10.0: plan_arbiter.py + sub-agents/planner.md + правило plan-committee [verified: check_factory_rules.py exit 0]
  - item: P2 backlog — FTS5-индекс memory/ и кодовой базы (stdlib sqlite3) для поиска прецедентов
    evidence: v12.10.0: precedent_index.py [verified: test_precedent_index.py PASS]
  - item: калибровка выявила систематическое завышение severity ревьюером (deleted-test: ожидался major, дан critical; missing-error-handling: лишние critical/minor)
    evidence: v12.10.0: граница §3 code-review.md -> precision 0.857; v12.10.1 -> 1.000 [verified: CHANGELOG.md:51-54]
  - item: check_factory_model.py без --memory-only падает на hand-authored корневом AGENTS.md фабрики
    evidence: как пункт #5 — авто-детект v12.10.0 [verified: check_factory_model.py:150-154]
  - item: P2 backlog — gen_code_changes_report.py падает traceback'ом на --help
    evidence: v12.10.1 (d07bded): test_gen_code_changes_report.py [verified: PASS в регрессии 26/26]
  - item: P2 backlog — контентный fingerprint читает git-индекс, unstaged-правки невидимы
    evidence: v12.10.1 dirty-warning; полное закрытие — v6 task_07: хэш по рабочему дереву [verified: кейс 29a-e test_factory_model.py, BT-2]
  - item: P2 backlog — action_gate.py uncaught OSError при незаписываемом журнале (fails closed)
    evidence: v12.10.1: action_gate.py except OSError -> exit 3 без traceback [verified: кейс 15 test_action_gate.py]
  - item: P2 backlog — git-блобы .cmd/.ps1 с LF; .gitattributes покрывает только error-patterns.default.json
    evidence: как пункт #6 — .gitattributes:5-6 (v12.10.1) + :9 *.sh (v6) [verified: git ls-files --eol]
  - item: устаревшие советы --memory-only для корня фабрики в tech-stack-detection.md:176 и memory_project.py:150
    evidence: v12.10.1 (d07bded): советы удалены; v6 task_02 sweep подтвердил 0 носителей [verified: BT-4 grep-контроль]
  - item: action_gate.py --help падает UnicodeEncodeError на cp1251-консоли (docstring содержит «→») — пре-существующий баг, найден кодером task_03; фикс = тот же паттерн use_utf8_output(), что и P0.1
    evidence: v12.10.2 (ed62e88): use_utf8_output во всех argparse-скриптах [verified: кейс 16 test_action_gate.py]
  - item: гигиена процесса — coder task_03 использовал git stash/pop на ОБЩЕМ дереве параллельного прогона (риск гонки); кандидат в правило брифинга coder'ов
    evidence: v12.10.2: 22-е правило no-shared-tree-git-mutations [verified: factory-rules.md, 6 носителей byte-identical]
  - item: action_gate.py не классифицирует git stash явно (fail-safe CONFIRM) — после 22-го правила стоит явная классификация; вынесено в task-v6.yaml P0.1
    evidence: v6 task_01: classify_stash + разбор -m/--message + кейс 17 [verified: BT-1 живые прогоны, ревью итерация 2 approve]
  - item: устаревшие советы --memory-only для корня фабрики в tech-stack-detection.md (~176) и memory_project.py (~150) — после авто-детекта v12.10.0 совет избыточен; вынесено в task-v6.yaml P0.2
    evidence: ложноживой дубль пункта #27 — закрыт в v12.10.1; перенесён без сверки (звено 5 RCA) [verified: BT-4 grep-контроль 0 носителей]
  - item: P2 backlog — контентный fingerprint читает git-индекс, unstaged-правки невидимы (dirty-warning смягчает)
    evidence: как пункт #24 — v6 task_07 [verified: кейс 29a-e, BT-2]

## 2026-09-24T02:30:00+03:00 — Factory v7 (v12.12.0): full English translation + english-only norm + translation-quality gates
title: Factory v7: translate the whole factory to English (code, comments, docs, skill, agents, rulebook) + 24th rule english-only; history unchanged
project: repo
timestamp: 2026-09-24T02:30:00+03:00
run_id: 20260924-2ec5185e
branch: factory/v7-english-only
commit: c891a67
task_type: refactor
goal: the entire factory is English-only — every produced artifact in English, behavior frozen; the english-only norm becomes a rulebook rule for all future artifacts
changed_files: 46 files (commit c891a67) — all deployers (prepare_factory.sh/.ps1/.cmd, start.cmd), scripts with Russian text (memory_project, plan_arbiter, gen_code_changes_report, version_manager, skill_base) + their test fixtures, SKILL.md (incl. mermaid labels), references/*, agents (code-factory.md + sub-agents), AGENTS.md, README.md, .agents/README.md, .example.task.yaml, .gitattributes (comments), skill-base/*, factory-rules.md + ALL rule carriers (23 blocks translated + 24th added), VERSION/CHANGELOG/README/AGENTS.md version sync
created_files: .agents/skills/code-factory/scripts/check_english_only.py + test, check_translation_structure.py + test; .code-factory/{state/*,logs/*,manifest.json,report.md,report_code_changes.md}
results: integration=PASS (28/28 test_*.py + test_env_propagation.sh, tokens translated synchronously, no assertion weakened) [verified: .code-factory/logs/test-results.md]; regression=PASS (check_factory_rules 24 rules/94 carriers exit 0, check_factory_model exit 0, test_validate_mermaid PASS, version_manager validate 12.12.0 exit 0) [verified: .code-factory/state/acceptance.md]; scan=PASS (0 Cyrillic outside exceptions, 105 files) [verified: check_english_only.py exit 0]; structure=PASS (39 changed files, skeleton preserved) [verified: check_translation_structure.py --allow-added-rule english-only exit 0]; semantic-audit=approve (6 shards, merged verdict approve, 0 critical/0 major, quotes re-verified) [verified: .code-factory/logs/semantic-audit/merged.json]; business=PASS (prepare_factory.sh temp deploy: exit 0, all messages English, banner contract intact) [verified: /tmp/cf_eng_bt.log]; review=approve (0 critical/0 major; version type minor validated without override) [verified: .code-factory/logs/code-review.md]; acceptance=SUCCESS (8 MET, 0 FAILED, evidence FRESH) [verified: .code-factory/state/acceptance.md]; backlog=0 open [verified: memory_project.py backlog --repo . --check exit 0]
decisions: waves translated by factory-refactorer subagents (kimi-k3) with rule blocks untouched until the dedicated rulebook wave, so check_factory_rules stayed exit 0 at every intermediate state [verified: wave reports + checker runs]; quality guaranteed by 3 loops — mandatory glossary, deterministic skeleton comparator, sharded LLM semantic audit with verbatim quotes [verified: .code-factory/state/glossary.md, merged.json]; user revision #1 demanded quality (not only quantity) — plan v2 added the semantic/structure gates and was approved [verified: .code-factory/state/plan.md]; wave P first edited the OUTER deployment tree by mistake — reverted by the main agent and redone inside repo/ [verified: git status of the outer tree]; test_run_id pinned digest re-pinned after the task-template translation (text-only, strength unchanged) [verified: test_run_id.py PASS]; check_translation_structure learned --allow-added-rule (deliberate rule addition) and --exclude (history files are supposed to grow) — declared allowances, not weakening [verified: test_check_translation_structure.py 10 cases PASS]; version minor 12.11.0 -> 12.12.0 (matrix --new-field, reviewer validated, no override) [verified: version_manager.py validate exit 0, logs/code-review.md]
assumptions: scope = repo/ only (task repo_path); the outer deployment copy is untouched [verified: outer git status]; the models matrix of the task was followed exactly even where generator!=judge would prefer a split (explicit matrix outranks the default) [verified: task.yaml models]; the evidence-ledger canonical wording "does not count as acceptance" kept as-is (defensible English; byte-identical carriers outrank a minor wording preference) [inferred]
models_used: main=kimi-code/k3; coder=deepseek-flash (task_01 guarantee scripts); refactorer=kimi-code/k3 x7 (waves D, M, S, K, A, P + rulebook R); semantic-audit=deepseek-flash x6 shards; code-reviewer=kimi-code/k3; documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.12.0
unfinished: no unfinished items

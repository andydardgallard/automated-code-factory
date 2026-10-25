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

## 2026-09-24T11:05:00+03:00 — Factory v8 (v12.12.0): whole-project code review after the English-only package
title: Factory v8: whole-project code review after the v12.12.0 change package (English translation, english-only rule, new guarantee scripts)
project: repo
timestamp: 2026-09-24T11:05:00+03:00
run_id: 20260924-96879f22
branch: factory/v8-whole-review
commit: none (review task; memory-only commit)
task_type: review
goal: post-package audit of the entire factory after v12.12.0 (RU-to-EN translation + english-only rule + check_english_only/check_translation_structure); deliverable = findings report + deterministic merged verdict; no code changes, no version change
changed_files: none (review task) — memory/ only
created_files: .code-factory/{state/*,logs/*,manifest.json,report.md,report_code_changes.md} incl. shard-findings/shard-{1,2}.json, code-review-merged.json, reviewer-calibration.md, golden-results/; task-v9.yaml (follow-up task, uncommitted per commit_exclude task*.yaml)
results: integration=PASS (28/28 test_*.py + test_env_propagation.sh, tree unchanged by the review) [verified: .code-factory/logs/test-results.md]; business=PASS (shard protocol produced 2 findings files + deterministic merged verdict with every asserted quote re-verified, 0 untrusted; cross-reference spot check 0 mismatches) [verified: .code-factory/logs/code-review-merged.json, verify_quotes.py exit 0]; calibration=PASS (7/7 verdict accuracy, macro precision/recall 1.000 — reviewer re-calibrated after the v12.12.0 prompt translation per code-review.md section 7) [verified: .code-factory/logs/reviewer-calibration.md]; shard-review=DONE (2 shards: shard-1 .agents/** 19920 lines, shard-2 deployers/docs/memory 3209 lines; 8 findings: 0 critical/1 major/6 minor/1 nit) [verified: .code-factory/logs/code-review-merged.json]; merged-verdict=request_changes — the anticipated outcome: the rework list became the plan of follow-up task-v9.yaml [verified: .code-factory/logs/code-review.md]; quotes=VERIFIED (9/9 verbatim, 0 untrusted) [verified: verify_quotes.py exit 0 over .code-factory/logs/claims.json]; major-finding=reproduced independently (deleted data.json exits 0 'ok - structure preserved (checked 0 changed files)') [verified: /tmp/cf_repro run, exit 0]; regression=PASS (28/28 test_*.py + test_env_propagation.sh, tree unchanged) [verified: .code-factory/logs/test-results.md]; review-gate=PASSED (0 open critical findings) [verified: .code-factory/state/acceptance.md]; acceptance=SUCCESS (4 MET, 1 derived, regression pass, ledger FRESH) [verified: verify_acceptance.py exit 0]
decisions: reviewer re-calibrated BEFORE the shard review because the v12.12.0 translation edited the reviewer prompt and code-review.md section 7 makes re-calibration mandatory after every prompt edit [verified: .code-factory/logs/reviewer-calibration.md]; criterion 1's authored verify used a shell glob that cmd.exe does not expand (exit 2, 'cannot be read') — infrastructure auto-fix 1/3: explicit shard file list + .code-factory/state/check_merged_gate.py asserting the criterion's actual content (merged verdict exists, 0 open critical); merge exit 1 (request_changes) is the review RESULT the task itself anticipates ('the rework list becomes the plan of a follow-up task'), not a criterion failure, while exit 2 stays a failure [verified: .code-factory/logs/errors.md, acceptance.md]; AGENTS.md carrying no fingerprint marker is NOT a violation — check_factory_model.py SKIPs the factory's own hand-authored manual via the three-signal detector (version marker, no fingerprint marker, SKILL.md deployed) [verified: acceptance.md criterion 3 SKIP line]; actionable findings carried as open backlog (follow_up=true) AND as the generated task-v9.yaml, so the debt is visible to the next run's reconciliation instead of being hidden [verified: memory_project.py backlog --repo . output]
assumptions: the shard reviewers' empirical claims were trusted only after independent reproduction (the major finding) and verbatim quote verification (9/9) [verified: /tmp/cf_repro, verify_quotes.py exit 0]; the outer deployment tree's memory/ is kept byte-identical with repo/memory/ (standing mirror convention) [inferred]
models_used: main=kimi-code/k3; code-reviewer=kimi-code/k3 x9 (7 calibration cases + 2 shard reviews); tester=unused (deterministic suite run by main); diagnostician=unused; advisor=unused
factory_version: 12.12.0
unfinished:
  - item: check_translation_structure.py silently passes deleted no-skeleton files (.json/.toml/binary) — the gate contract 'deleted files fail the check' is broken for unsupported types (v8 review, major)
    reason: rework item 1 (P0) of follow-up task-v9.yaml; fix = detect the deleted case before the family check + vaccination regression test deleting a .json
    severity: warning
    follow_up: true
  - item: v8 review minors for task-v9.yaml — security-auditor.md severity mapping contradicts security-audit.md section 5.1; prepare_factory.ps1 parity gaps (old-git fallback, short-reason first-vs-last line); skill_base.py missing utf8-guard and wrong usage lines; README.md structure tree misplaces task-template.yaml
    reason: rework items 2-7 (P1) of follow-up task-v9.yaml
    severity: info
    follow_up: true
  - item: test_version_manager.py helper suggest() annotated '-> str' but returns a (stdout, exit_code) tuple (v8 review, nit)
    reason: cosmetic; ride-along in task-v9.yaml P2
    severity: info
    follow_up: false

## 2026-09-24T12:30:00+03:00 — Factory v9 (v12.12.1): v8 review rework — deleted-file gate hole closed with vaccination, severity-mapping alignment, ps1 deployer parity, skill_base guard
title: Factory v9: fix the v8 review findings — translation-structure deleted-file hole, cross-carrier mismatches, deployer parity
project: repo
timestamp: 2026-09-24T12:30:00+03:00
run_id: 20260924-8b9caeeb
branch: factory/v9-review-rework
commit: 2f53d2f
task_type: implement
goal: rework list of the v8 whole-project review (merged verdict request_changes, 0 critical/1 major/6 minor/1 nit): P0 deleted no-skeleton files silently passing the translation-structure gate; P1 minors (severity mapping, ps1 parity x2, skill_base guard + usage, README tree); P2 nit (suggest() annotation)
changed_files: .agents/skills/code-factory/scripts/check_translation_structure.py; .agents/skills/code-factory/scripts/test_check_translation_structure.py; .agents/agents/sub-agents/security-auditor.md; prepare_factory.ps1; .agents/skills/code-factory/scripts/test_windows_scripts.py; .agents/skills/code-factory/scripts/skill_base.py; README.md; .agents/skills/code-factory/scripts/test_version_manager.py; VERSION; CHANGELOG.md; AGENTS.md; .agents/README.md; .agents/skills/code-factory/SKILL.md
created_files: .code-factory/{state/*,logs/*,backups/*,manifest.json,report.md,report_code_changes.md}; no new code files
results: integration=PASS (4/4 changed-module tests) [verified: .code-factory/logs/test-results.md]; regression=PASS (28/28 test_*.py + test_env_propagation.sh, no assertion weakened; gates check_factory_rules 24 rules/94 blocks, check_english_only 109 files, check_factory_model, validate_mermaid all exit 0) [verified: .code-factory/logs/test-results.md]; business=PASS (BT-1 v8 repro: deleted data.json -> exit 1 "data.json: deleted (a translation never removes a file)"; pre-fix it exited 0) [verified: .code-factory/logs/business-tests.md, .code-factory/logs/vaccination-task_01.md]; review=approve (iteration 1/2, 0 critical/0 major, 2 minor hygiene notes both addressed; quotes 2/2 VERIFIED) [verified: .code-factory/logs/code-review.md, .code-factory/logs/quotes-review.md]; acceptance=SUCCESS [verified: .code-factory/state/acceptance.md]; backlog=0 open [verified: memory_project.py backlog --repo . --check exit 0]
decisions: vaccination order enforced — regression test check_deleted_no_skeleton_file_fails written FIRST and archived failing on pre-fix code (exit 0 "ok - structure preserved"), only then the fix (deleted-at-worktree probe moved before the family(path) is None skip in cmd_check) [verified: .code-factory/logs/vaccination-task_01.md]; severity-mapping contradiction resolved in favor of references/security-audit.md section 5.1 (the factory contract), security-auditor.md:51 aligned [verified: git diff of security-auditor.md, reviewer check]; ps1 parity fixes mirror prepare_factory.sh:87-92 and :136-140 one-to-one, covered by two new static hooks in test_windows_scripts.py that fail on the pre-fix ps1 [verified: test_windows_scripts.py 27 PASS, coder runtime probes]; skill_base.py gained the same use_utf8_output() guard as the other 26 argparse scripts plus corrected top-level --base usage lines [verified: PYTHONIOENCODING=cp1251 --help exit 0]; version 12.12.0 -> 12.12.1 (patch by the matrix --fix, reviewer validated without override) [verified: version_manager.py validate exit 0, .code-factory/logs/code-review.md]
assumptions: the run label "v9" is a sequence label only — VERSION (12.12.0) was correct and is bumped per the matrix, per the task note [verified: task.yaml line 64]; the outer deployment tree memory/ is kept byte-identical with repo/memory/ (standing mirror convention) [inferred]; the translation-structure checker flagging the new defs against base ea30860 is expected (deliberate additions, not drift) and is not a gate for this run [inferred]
models_used: main=kimi-code/k3; analyzer=kimi-code/k3; coder=deepseek-flash x5 (task_01, task_02, task_03+04, task_05, task_06+07); reviewer=kimi-code/k3; documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.12.1
unfinished: no unfinished items
closed:
  - item: check_translation_structure.py silently passes deleted no-skeleton files (.json/.toml/binary) — the gate contract 'deleted files fail the check' is broken for unsupported types (v8 review, major)
    evidence: fixed in cmd_check (deleted probe before the family skip) + vaccination test check_deleted_no_skeleton_file_fails [verified: test_check_translation_structure.py 11/11 PASS, .code-factory/logs/vaccination-task_01.md, BT-1 exit 1 in .code-factory/logs/business-tests.md]
  - item: v8 review minors for task-v9.yaml — security-auditor.md severity mapping contradicts security-audit.md section 5.1; prepare_factory.ps1 parity gaps (old-git fallback, short-reason first-vs-last line); skill_base.py missing utf8-guard and wrong usage lines; README.md structure tree misplaces task-template.yaml
    evidence: all six minors implemented (auditor mapping aligned to the contract; ps1 old-git fallback + last-non-empty-line reason; skill_base use_utf8_output + usage lines; README tree entry moved) [verified: regression 28/28 + gates exit 0 in .code-factory/logs/test-results.md, review approve in .code-factory/logs/code-review.md]

## 2026-09-29T17:15:00+03:00 — Factory v10 (v12.13.0): scope the whole run to the resolved repo_path (25th rule repo-scoping)
title: Scope the whole factory run to the resolved repo_path: artifacts, git operations, rollback, subagent briefings (fix task of review run 20260929-62232c10, findings F1-F18)
project: repo
timestamp: 2026-09-29T17:15:00+03:00
run_id: 20260929-a4f03186
branch: factory/repo-scoping
commit: bbd4d4c
task_type: implement
goal: a factory run resolves the task's repo_path ONCE to an absolute path and then does EVERYTHING relative to that resolved repository — .code-factory/ artifacts, backups, git operations (git -C <repo>), rollback — with the documented deployment-root exceptions memory/ and version_manager.py; the production incident 20260929-b81785fd (artifacts written into the launch folder) becomes impossible by contract
changed_files: 33 files (commit bbd4d4c) — references/factory-rules.md (new rule repo-scoping + amended git-native/task-format) and all rule carriers (SKILL.md, code-factory.md, AGENTS.md, .agents/README.md), flow text (SKILL.md mermaid node B resolve step + stale-task warning, code-factory.md Phase 0 + Phase 9 --repo fixes), references (verification-strategy §2.2/§4 incl. the §4.3 rollback-order fix, handoff-briefing Repository root + checklist, documentation/error-routing/tech-stack-detection §7.2, code-review/security-audit scoping sentences), sub-agents analyzer/diagnostician/documenter, scripts (run_id, factory_preflight, task_graph, error_router, verify_quotes + 5 test files), deployers (prepare_factory.ps1/.sh, start.cmd, test_windows_scripts.py), assets/task-template.yaml, VERSION/CHANGELOG/README sync
created_files: .agents/skills/code-factory/scripts/test_repo_scoping.py (contract mini-run); .code-factory/{state/*,logs/*,backups/*,manifest.json,report.md,report_code_changes.md}
results: integration=PASS (30/30: 29 test_*.py incl. the new test_repo_scoping.py + test_env_propagation.sh) [verified: .code-factory/logs/final-regression.log]; regression=PASS (the 30/30 integration run above was executed on the final tree over the unchanged pre-existing suite, so it doubles as the regression evidence) [inferred] (supplemented 2026-10-16 in run 20261016-2ddb58eb under the plan-approved user authorization: inferred from this entry's own integration=PASS citing .code-factory/logs/final-regression.log; the cited log itself no longer exists on disk); gates=PASS (check_factory_rules 25 rules/98 carriers, check_factory_model --repo ., check_english_only, mermaid) [verified: .code-factory/logs/final-regression.log]; translation-structure=PASS under declared allowances (--allow-added-rule repo-scoping, --exclude CHANGELOG.md, 0 deleted files, 0 UNEXPECTED deltas — all 23 deltas map 1:1 to the task items) [verified: .code-factory/state/check_gates.py, state/acceptance.md]; business=PASS (BT-1 review mini-run 17/17 + BT-2 implement+rollback 23/23: artifacts, branch and commits only in the scratch repo, the launch folder byte-identical, induced-failure rollback restored the scratch tree) [verified: .code-factory/logs/business-tests.md]; review=approve (0 critical/0 major, 3 minor all reworked, 2 nit unresolved; quotes 4/5 verbatim, the 5th untrusted because its quoted §4.3 line was reworked in response to the finding itself) [verified: .code-factory/logs/code-review.md, logs/quotes-report.json]; vaccination=PASS (test_error_router case 9d failed pre-fix with the real OS 8.3 alias of a non-ASCII temp path, then the realpath/normcase comparison fix; no assertion weakened) [verified: .code-factory/logs/vaccination-task_06.md]; acceptance=SUCCESS (7/7 MET, evidence ledger 3/3 FRESH) [verified: .code-factory/state/acceptance.md, verify_acceptance.py exit 0]; backlog=0 open [verified: memory_project.py backlog --repo . --check exit 0]
decisions: the contract was established as the 25th canonical rule repo-scoping with byte-identical carriers instead of prose scattered across the instruction layer [verified: check_factory_rules.py exit 0 at every gate]; business tests are deterministic simulations of a run's steps — a nested factory run is not machine-runnable — approved with the plan [verified: approved plan, .code-factory/logs/business-tests.md]; criterion 5's check_translation_structure exit-0 requirement was judged by the user (hitl) as "accept with the documented list of deltas", enforced by a machine gate that whitelists (path, marker) deltas and fails on any unexpected one [verified: user answer, .code-factory/state/check_gates.py]; §4.3 rollback order fixed after BT-2 exposed the HEAD-moved breakage (reset --hard <base> BEFORE switch; the pre-run branch is recorded in state/git-branch.txt) [verified: .code-factory/logs/business-tests.md, reviewer minor #1]; version minor 12.12.1 -> 12.13.0 (matrix --new-field: new rule + new CLI flags; reviewer validated without override) [verified: version_manager.py validate exit 0]
assumptions: the previous review run's NUL-corrupted .code-factory artifacts (acceptance/criteria/evidence, shard findings, reports) carried zero evidentiary value and were removed; this run's criteria, ledger and reports were generated fresh [verified: od byte dumps, .code-factory/report.md]; the outer deployment tree memory/ is kept byte-identical with repo/memory/ (standing mirror convention) [inferred]; the run label "v10" is a sequence label only — VERSION was correct and is bumped per the matrix [verified: task.yaml note, version_manager.py]
models_used: main=kimi-code/k3; coder=deepseek-flash x8 delegations (task_01-08); tester=deepseek-flash (business tests); code-reviewer=kimi-k3; documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.13.0
unfinished:
  - item: residual bare .code-factory mentions without in-file scoping in sub-agents/advisor.md, references/providers.md, references/refactoring.md, references/reference-docs.md (v10 reviewer nit)
    reason: cosmetic consistency; covered by the global repo-scoping rule + the mandatory Repository-root briefing line; whitelisted in .code-factory/state/check_hygiene.py
    severity: info
    follow_up: false
  - item: prepare_factory.ps1 re-appends the whole 12-pattern .gitignore block when any single pattern is missing on an old deployment (duplicates on re-prepare; pre-existing behavior)
    reason: v10 reviewer nit; deployer hygiene candidate for a follow-up task, out of this task's scope
    severity: info
    follow_up: false

## 2026-10-17T01:45:00+03:00 — Factory v11 (v12.14.0): Web GUI specialist with independent Chrome DevTools MCP acceptance + remote URL reference_docs
title: Add factory-gui-expert with Chrome DevTools MCP (conditional Web GUI path, tester-owned acceptance) and remote URL sources for reference_docs
project: repo
timestamp: 2026-10-17T01:45:00+03:00
run_id: 20261016-2ddb58eb
branch: factory/gui-expert-remote-docs-20261016
commit: 8d4ff82
task_type: implement
goal: give Web GUI tasks a dedicated specialist that implements/debugs in the real browser while the tester independently proves the final scenario (never self-acceptance), keep non-Web runs untouched (no Chrome/Node dependency), and let reference_docs take public HTTP(S) document/Git URLs with deterministic create/reuse/update semantics
changed_files: 39 files (commit 8d4ff82) — sub-agents/gui-expert.md (new role, coder-class, MCP tools shared only with tester), tester.md (MCP tools + acceptance ownership), scripts/chrome_devtools_mcp.py + test (decide/discover-e2e/browser-matrix/merge-config/vendor-install/probe/validate-config), scripts/skill_base.py + test_remote_reference_docs.py (http_doc/http_git resolution, stdlib urllib + git executable, deterministic hashing, offline/stale), assets/chrome-devtools.mcp.json + chrome-devtools-smoke.html, references/chrome-devtools-mcp.md, both orchestration flows (SKILL.md mermaid + code-factory.md), providers/handoff-briefing/verification-strategy/reference-docs, factory_preflight --web-gui, error-patterns I1-I4 + test, prepare_factory.sh/.ps1 vendored MCP deployment + test_windows_scripts.py e2e cases, deployer .gitignore blocks, AGENTS.md/README/.agents/README.md/CHANGELOG/VERSION 12.14.0
created_files: .agents/agents/sub-agents/gui-expert.md; scripts/chrome_devtools_mcp.py + test_chrome_devtools_mcp.py + test_remote_reference_docs.py; references/chrome-devtools-mcp.md; assets/chrome-devtools.mcp.json + chrome-devtools-smoke.html; skill-base/skills/{playwright-mcp,chrome-devtools-mcp}/SKILL.md (generated through the new URL path)
results: integration=PASS (32 test files + shell contract, all per-task verifications exit 0) [verified: .code-factory/logs/final-acceptance.log]; regression=PASS (final-regression + gates green on the acceptance tree, 136 PASS lines) [verified: .code-factory/logs/final-regression.log]; business=PASS 7/7 scenarios (live real-Chrome full cycle: specialist reproduced+fixed the fixture defect via mcp__chrome-devtools__* only, independent tester verdict PASS; POSIX+Windows deploy preservation/idempotency/conflict; loopback remote lifecycle; direct public-URL created→reuse) [verified: .code-factory/logs/business-tests.md, .code-factory/logs/browser/20261016-2ddb58eb/tester-acceptance.md]; review=approve (0 critical/0 major/3 minor all reworked; quotes 5/5 verbatim; version minor validated) [verified: .code-factory/logs/code-review.md]; acceptance=SUCCESS (11 MET, 0 FAILED, 1 derived-by-design executed live, ledger regression=pass FRESH) [verified: .code-factory/state/acceptance.md, verify_acceptance.py exit 0]; backlog=0 open [verified: memory_project.py backlog --repo . --check exit 0]
decisions: criterion-1 verify text amended to the .as_posix() variant with the user's plan approval — the original cannot pass on Windows (MSYS2 bash mangles the backslash path; proven through verify_acceptance.py shell=True) [verified: .code-factory/logs/baseline.md, .code-factory/state/plan.md]; the managed MCP entry is node-direct against a vendored pinned install because the CLI spawns stdio servers without a shell (npx→ENOENT, npx.cmd→EINVAL on Windows) and headless sessions need KIMI_CODE_TRUST_WORKSPACE=1 for project MCP trust [verified: ~/.kimi-code/logs/kimi-code.log lines, live sessions 2/3 in .code-factory/logs/browser/20261016-2ddb58eb/]; .kimi-code/mcp.json + .kimi-code/vendor/ are gitignored machine-local artifacts — the committed pinned configuration is assets/chrome-devtools.mcp.json [verified: .gitignore, git check-ignore]; version minor via --new-subagent (new factory-gui-expert subagent), reviewer validated without override [verified: version_manager.py suggest + code-review.md]
assumptions: the interrupted run 20261016-02207624's artifacts were superseded by this run after the task file materially changed (new subagent requirement); its plan approval did not carry over [verified: run_id mismatch 02207624 vs 2ddb58eb, task diff]; the two v10 reviewer nits remain info-level non-follow-ups [verified: memory/change-log.md v10 entry]; Playwright MCP stayed out of scope (comparative reference only) [verified: task non-goals, skill-base/skills/playwright-mcp/SKILL.md marker]
models_used: main=kimi-code/k3; analyzer=kimi-code/k3 x2; coder=deepseek-flash (task_02-08 + E3 rework); gui_expert=deepseek-flash (live); tester=deepseek-flash (live); reviewer=kimi-k3; documenter=deepseek-flash; skill-manager=default fallback; diagnostician=unused; advisor=unused
factory_version: 12.14.0
unfinished:
  - item: none — no unfinished items this run
    reason: all acceptance criteria MET or executed live; review approved; backlog open: 0
    severity: info
    follow_up: false

## 2026-10-17T03:40:32+03:00 — Factory v12 (v12.14.0): whole-project code review after the GUI-specialist + remote-reference_docs change
title: Factory v12: whole-project review after v12.14.0 — sharded findings, verbatim evidence and rework plan; no fixes and no version change
project: repo
timestamp: 2026-10-17T03:40:32+03:00
run_id: 20261017-8afa3aae
branch: factory/whole-review-20261017
commit: none (review task; memory-only commit)
task_type: review
goal: review every tracked factory file after v12.14.0 in shards, verify all finding quotes, explicitly dispose of the two v10 nits, and produce a complete rework plan without modifying the product
changed_files: none to product/source files (review task) — memory/change-log.md and memory/summary.md only
created_files: .code-factory/{state/*,logs/*,report.md,report_code_changes.md} including tracked-review-shards.json, code-review-shards/{shard-1,shard-2}.json, code-review-merged.json, reviewer-calibration.md, golden-results/, quotes-report.json, reproductions.md and acceptance.md
results: integration=PASS (all shard, quote, coverage, merge, disposition and targeted-reproduction checks completed) [verified: .code-factory/logs/test-results.md and reproductions.md]; baseline=PASS (31 test_*.py + test_env_propagation.sh) [verified: .code-factory/logs/baseline.md and baseline.log]; calibration=PASS (7/7 verdict accuracy, macro precision/recall 1.000) [verified: .code-factory/logs/reviewer-calibration.md]; shard-review=DONE (2 shards, exactly 123 tracked files with no duplicates; deterministic reverse-order merge byte-identical) [verified: .code-factory/state/tracked-review-shards.json, .code-factory/state/code-review-merged-reversed.json]; merged-verdict=request_changes (2 critical + 12 major; rework plan covers all 14) [verified: .code-factory/logs/code-review-merged.json, .code-factory/state/plan.md]; quotes=VERIFIED (14/14 findings + 8/8 dispositions, 0 untrusted) [verified: .code-factory/logs/quotes-report.json and disposition-quotes-report.json]; targeted-reproductions=CONFIRMED (shell-wrapper ALLOW vs direct HARD_DENY, clean-clone MCP false-usable, missing-Node misroute, malformed-env crash, secret-name acceptance, hash cwd anchoring, duplicate-line doc-validation hole, clean-clone Windows 80 PASS/1 FAIL) [verified: .code-factory/logs/reproductions.md and clean-clone-windows.log]; regression=PASS (31 test_*.py + shell contract + rules/english/model/mermaid/version gates; Windows 81 PASS/0 FAIL) [verified: .code-factory/logs/final-regression.log]; business=PASS 2/2 review-execution scenarios [verified: .code-factory/logs/business-tests.md]; acceptance=DEGRADED (5 MET, 0 FAILED, 1 derived; regression+baseline FRESH but review_gate=fail because 2 critical findings remain open — full SUCCESS forbidden) [verified: .code-factory/state/acceptance.md, verify_acceptance.py exit 1]; backlog=1 critical rework item covering all 14 findings [verified: memory_project.py backlog --repo . --check expected exit 1 for the unresolved review rework]
decisions: the actual reviewer assignment was generated with the same inventory/shards CLI in a clean temporary clone because the generic root inventory included 14 untracked/ignored paths; this preserved the task's explicit tracked-only scope and independently confirmed the repo_inventory critical finding [verified: .code-factory/logs/analysis.md and reproductions.md]; no source fix, version change or documenter step was performed because task_type=review [verified: git diff -- VERSION and version_manager.py validate exit 0]; both v10 nits were disposed as non-issues with evidence, while the separate missing deployed .kimi-code/mcp.json ignore pattern remains a major finding [verified: .code-factory/logs/code-review.md v10 nit dispositions]; review_gate was signed fail rather than hiding open critical findings behind the otherwise green review-process criteria [verified: .code-factory/state/evidence.json and acceptance.md]
assumptions: the review deliverable is complete even though product acceptance remains request_changes; the open rework is intentional review debt, not a partially executed review [verified: task.yaml out-of-scope and .code-factory/state/acceptance.md]
models_used: main=kimi-code/k3; analyzer=kimi-code/k3; code-reviewer=kimi-code/k3 x9 (7 calibration cases + 2 shard reviews); coder/tester/documenter/diagnostician/advisor=unused
factory_version: 12.14.0
unfinished:
  - item: v12 whole-project review rework — 2 critical + 12 major findings (action_gate shell-wrapper bypass, tracked-only inventory/privacy, Web GUI pre-flight and MCP validation/routing, remote-source hashing/clone/record consistency, deployer ignore/test gaps, documentation-validator hole)
    reason: implement the 14-item rework list in .code-factory/state/plan.md as a separate follow-up task; this review task explicitly forbids fixes, so every finding remains open
    severity: critical
    follow_up: true

## 2026-10-17T05:48:51+03:00 — Factory v12-review rework (v12.14.1): the 14 review findings fixed; conditional pass with one open major
title: Factory: fix the v12 whole-project review findings (destructive-action gate bypass, tracked-only review scope, Web GUI pre-flight and MCP validation, remote reference_docs integrity, deployer/test hygiene, documentation validator)
project: repo
timestamp: 2026-10-17T05:48:51+03:00
run_id: 20261017-7a5130ac
branch: factory/v12-review-rework-20261017
commit: 756de71
task_type: implement
goal: make every safety gate, scope rule and validation check the v12 review found broken actually work — each fix proven by a regression test observed failing on the pre-fix code (vaccination) — without weakening any existing assertion or changing behavior outside the 14 findings
changed_files: 34 files (commit 756de71) — scripts (action_gate.py recursive shell-wrapper classification with per-quote-type escapes and real shell tokenization; repo_inventory.py --tracked NUL-safe git ls-files mode; factory_preflight.py resolved-repo MCP probe threading; chrome_devtools_mcp.py non-object-env validation + credential-name scanning; skill_base.py repo-anchored hash / supervised mid-transfer clone abort / record --resolved-hash without re-fetch; validate_documentation.py diff-opcode position mapping) + their 13 test files, error-patterns.default.json I1 + error-routing.md, SKILL.md (Approve->PF edge + --tracked shard nodes), the shard-protocol rule block in all 5 carriers, code-review/security-audit/reference-docs/chrome-devtools-mcp references, both deployers (.kimi-code/mcp.json gitignored), .agents/README.md + README.md + CHANGELOG.md, VERSION 12.14.1
created_files: none to the product (only .code-factory/ runtime artifacts)
results: integration=PASS (31 test_*.py + test_env_propagation.sh, run three times on the evolving tree, final block all exit 0) [verified: .code-factory/logs/test-results.md]; regression=PASS (same suite green on the acceptance tree; deterministic gates rules/english/model/mermaid/version all exit 0) [verified: .code-factory/logs/test-results.md, gates block]; business=PASS 8/8 scenarios with real CLI runs incl. tracked-tree review equality, clean-clone deployment hygiene (84 PASS in a fresh offline clone), hostile MCP configs, real-line I1 routing, remote reference_docs accuracy and reviewer calibration 7/7 accuracy / precision 1.000 [verified: .code-factory/logs/business-tests.md]; review=request_changes at budget exhaustion (iteration 1: 1 critical in the new F1 code, reworked and verified fixed; iteration 2: 0 critical / 1 major / 1 minor open) [verified: .code-factory/logs/code-review.md]; vaccination=PASS (22 pre/post logs; every fix observed failing pre-fix, incl. rework rounds A2/A3) [verified: .code-factory/logs/vaccination/]; acceptance=DEGRADED conditional pass (10 MET, 0 FAILED, 1 derived; regression+baseline+business FRESH; honest review_gate=fail entry downgrades; criterion 2 marked unverified_review) [verified: .code-factory/state/acceptance.md, verify_acceptance.py exit 1]; version patch 12.14.0 -> 12.14.1 (matrix --fix, reviewer validated without override) [verified: version_manager.py validate exit 0]; backlog=1 critical + 2 warning items open [verified: memory_project.py backlog --repo . --check expected exit 1 for the conditional-pass residuals]
decisions: the conditional pass was taken per the canonical review-gate policy (auto mode, reviewer budget 2/2 exhausted, no open critical findings): criterion 2 marked unverified_review in acceptance.md and the open findings recorded here and in report.md rather than extending an exhausted budget or silently accepting [verified: .code-factory/state/acceptance.md criterion-2 annotation, .code-factory/report.md unresolved-findings section]; the F1 fix took three implementation rounds because the reviewer and the business tester each caught a real fail-open the round before introduced or missed (quote-type-blind escapes; nested double quotes truncating the -c payload) — both caught by vaccination-first rework, never by weakening assertions [verified: logs/vaccination/A2-*.log and A3-*.log, logs/business-tests.md scenario-1 re-runs]; the shard-protocol canonical rule now mandates the tracked tree in all 5 carriers, byte-identical [verified: check_factory_rules.py PASS, 25 rules / 100 carriers]; the windows_argv tokenizer deliberately treats a double quote as a pure toggle with no backslash escape, matching cmd/PowerShell semantics [verified: test_action_gate.py sections 19-20c]
assumptions: the review rework list of run 20261017-8afa3aae was taken as the contract (no re-discovery) [verified: task description, logs/review-20261017-8afa3aae-rework-plan.md]; this run is not a Web GUI run, so no browser probe was performed and no browser capability was required [verified: .code-factory/state/preflight.json collected without --web-gui]; pre-existing untracked files in the launch directory (task_*.yaml, wheels, idea.md) were left untracked and uncommitted per commit_exclude [verified: git status]
models_used: main=kimi-code/k3; coder=deepseek-flash (8 parallel wave-1 groups + group C + 2 F1 rework rounds); tester=deepseek-flash (8 scenarios + 2 scenario-1 re-runs); reviewer=kimi-k3 (2 iterations + version validation); documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.14.1
closed:
  - item: v12 whole-project review rework — 2 critical + 12 major findings (action_gate shell-wrapper bypass, tracked-only inventory/privacy, Web GUI pre-flight and MCP validation/routing, remote-source hashing/clone/record consistency, deployer ignore/test gaps, documentation-validator hole)
    evidence: commit 756de71 (34 files); .code-factory/state/acceptance.md run_id 20261017-7a5130ac (10 MET / 0 FAILED / 1 derived, DEGRADED conditional pass); .code-factory/logs/vaccination/ 22 pre/post logs; .code-factory/logs/business-tests.md 8/8 MATCH
unfinished:
  - item: pwsh/powershell with a SINGLE-quoted -Command payload still ALLOWs destructive commands (`pwsh -Command 'rm -rf /'` -> ALLOW, exit 0) — reviewer iteration-2 major, pre-existing at base HEAD
    reason: reviewer budget (2/2) and coder budget (1/1) exhausted; canonical conditional pass recorded; fix direction: strip PowerShell single-quote literals in the wrapper tokenizer, with vaccination tests first
    severity: critical
    follow_up: true
  - item: action_gate wrapper analysis does not cover launcher prefixes (env/sudo/builtin) and does not expand $(...) substitutions — both pre-existing at HEAD and outside F1's supported-wrapper set
    reason: noted by the group-A coder; same fail-open family as F1; candidates for the next gate-hardening task
    severity: warning
    follow_up: true
  - item: installer-side missing-Node line (chrome_devtools_mcp.py:632, `... cannot be installed` tail) still routes to the diagnostician instead of infrastructure
    reason: outside F7's quoted scope (the probe line was fixed); extend I1 or add a sibling pattern in a follow-up
    severity: warning
    follow_up: true
  - item: simple_commands (action_gate.py:317) is dead code after the round-3 tokenizer rewrite
    reason: reviewer iteration-2 minor; cosmetic cleanup, left to keep the exhausted review budget honest
    severity: info
    follow_up: false

## 2026-10-17T08:54:25+03:00 — Factory v12.14.2: PowerShell single-quote hardening; conditional pass with one open major
title: Factory: close the pwsh/powershell single-quoted -Command fail-open in the destructive-action gate (plus remove the dead simple_commands helper)
project: repo
timestamp: 2026-10-17T08:54:25+03:00
run_id: 20261017-5cdfc7af
branch: factory/fix-pwsh-single-quote-20261017
commit: 15ea6a6
task_type: implement
goal: make single-quoted pwsh/powershell -Command/-c payloads classify like their double-quoted and bare twins, with vaccination-first tests and dead-helper cleanup, without changing the exit-code/journal contract or unrelated wrapper behavior
changed_files: 8 files (commit 15ea6a6) — action_gate.py PowerShell single-quote tokenization + decoded-quote completeness + fixed-contract/open-limitation docstring; test_action_gate.py additive section 21a-f; CHANGELOG.md 12.14.2 entry; VERSION 12.14.2; synchronized README.md, AGENTS.md, SKILL.md and .agents/README.md version markers
created_files: none to the product (only .code-factory/ runtime artifacts)
results: integration=PASS (test_action_gate.py exit 0, all section 21a-f and pre-existing assertions) [verified: .code-factory/logs/integration.log]; regression=PASS (31 test_*.py + test_env_propagation.sh, 84 Windows PASS/0 FAIL, all rules/english/model/mermaid/version gates green on 12.14.2) [verified: .code-factory/logs/regression.log and acceptance.md criterion 1]; business=MATCH for the covered matrix (192/192 real CLI checks, 48/48 twin groups, 192/192 journal rows; scenario 2 33/33) with the separate review-2 hole explicitly not covered [verified: .code-factory/logs/business-tests.md and business-test.log]; vaccination=PASS (original 114 red assertions then green; review-1 12 red assertions then green; no existing assertion changed) [verified: .code-factory/logs/vaccination.md and vaccination/*.log]; review=request_changes at budget exhaustion (iteration 1 major unmatched decoded quote closed; iteration 2 major POSIX-backslash recursive splitting open, 0 critical) [verified: .code-factory/logs/code-review.md, 2/2 quotes verified]; acceptance=DEGRADED conditional pass (3 MET / 0 FAILED / 1 derived; all 5 ledger entries FRESH; honest review_gate=fail; criterion 2 unverified_review) [verified: .code-factory/state/acceptance.md and logs/acceptance.log, verify_acceptance.py exit 1]; version patch 12.14.1 -> 12.14.2 (matrix --fix, reviewer validated without override) [verified: version_manager.py validate exit 0 and logs/code-review.md]; backlog=1 critical + 2 warning items open [verified: memory_project.py backlog --repo . --check expected exit 1 for the conditional-pass residual]
decisions: the plain single-quoted -Command/-c path now uses PowerShell tokenization, doubled single quotes are decoded, and unmatched decoded quotes become CONFIRM through the existing fail-safe [verified: action_gate.py powershell_argv/powershell_quote_complete and section-21 tests]; review iteration 2 found a DIFFERENT POSIX-backslash recursive-splitting hole after iteration 1 closed, and budgets were not extended: the canonical auto conditional pass was taken with criterion 2 unverified_review and the hole recorded in code-review, acceptance, CHANGELOG, the module docstring and this backlog [verified: logs/code-review.md iteration 2, state/acceptance.md criterion-2 annotation, CHANGELOG.md 12.14.2]; the original plain single-quote backlog item is closed with evidence, the dead helper is removed without a closure block because it was info/follow_up=false, and the new backslash finding remains a separate open item, so no residual is hidden [verified: business-tests.md covered matrix, report.md unresolved-findings section, this entry's closed/unfinished blocks]
assumptions: benign negative controls were not required to fail pre-fix; they are over-deny controls, while every bug-reproducing assertion was observed red first [verified: logs/vaccination.md]; the 192-check business matrix proves only its covered scenarios and is not safety clearance for the separately reproduced review-2 vectors [verified: logs/business-tests.md overall-status and open-finding sections]; pre-existing untracked user files were left untouched and uncommitted [verified: git status after commit 15ea6a6]
models_used: main=kimi-code/k3; analyzer=kimi-code/k3 x2; coder=deepseek-flash (initial vaccination/fix + review-1 vaccination/rework); tester=deepseek-flash (3 business runs); reviewer=kimi-k3 (2 iterations + patch validation); documenter=deepseek-flash; diagnostician=unused; advisor=unused
factory_version: 12.14.2
closed:
  - item: pwsh/powershell with a SINGLE-quoted -Command payload still ALLOWs destructive commands (`pwsh -Command 'rm -rf /'` -> ALLOW, exit 0) — reviewer iteration-2 major, pre-existing at base HEAD
    evidence: the three original destructive payloads across pwsh/powershell, -Command/-c, single/double/bare and hitl/auto now classify like their twins (HARD_DENY/CONFIRM, never blind ALLOW), and review-1 unmatched decoded quotes CONFIRM; section 21a-f plus 192/192 real CLI checks in .code-factory/logs/business-tests.md [verified: test_action_gate.py exit 0, vaccination pre/post logs, integration.log and acceptance.md criterion 2]
unfinished:
  - item: PowerShell DECODED payloads are recursively split with POSIX backslash rules, so `pwsh -Command 'echo "\"; rm -rf /'` and `powershell -c 'echo "\"; git push origin main'` still ALLOW in hitl and auto (review iteration-2 major)
    reason: reviewer budget 2/2 and coder budget 1/1 exhausted; canonical conditional pass recorded; next gate-hardening task must add red-before vectors and balanced benign controls, then use PowerShell quote/backslash semantics for recursive splitting without changing cmd/POSIX behavior
    severity: critical
    follow_up: true
  - item: action_gate wrapper analysis does not cover launcher prefixes (env/sudo/builtin) and does not expand $(...) substitutions — both pre-existing at HEAD and outside F1's supported-wrapper set
    reason: explicit non-goal of this run; unchanged candidate for a separate gate-hardening task
    severity: warning
    follow_up: true
  - item: installer-side missing-Node line (chrome_devtools_mcp.py:632, `... cannot be installed` tail) still routes to the diagnostician instead of infrastructure
    reason: explicit non-goal of this run; extend I1 or add a sibling pattern in a follow-up
    severity: warning
    follow_up: true

## 2026-10-17T11:24:39+03:00 — Factory full-backlog attempt FAILED: residual builtin -- bypass; product rolled back
title: Factory full remaining backlog attempt — three fixes attempted, terminal launcher business failure, rollback to base
project: repo
timestamp: 2026-10-17T11:24:39+03:00
run_id: 20261017-1955b445
branch: factory/fix-full-backlog-20261017 (rolled back and deleted; memory recorded on factory/fix-pwsh-single-quote-20261017)
commit: none delivered; base restored to 4607793; unreferenced failure snapshot c77c772386d30e30cacb517515bfa4b8e5076eea
task_type: implement
goal: close all three remaining backlog items with vaccination-first PowerShell, launcher/substitution, and installer-routing fixes, without weakening existing behavior or exceeding retry budgets
changed_files: none delivered; seven attempted files are preserved only in the failure snapshot and .code-factory/logs/failed-diff.patch
created_files: none to the product (only .code-factory/ runtime artifacts)
results: baseline=PASS (31 test_*.py + shell contract + deterministic gates, 84 Windows PASS/0 FAIL) [verified: .code-factory/logs/baseline.md and baseline.log]; vaccination=PASS as evidence collection (item1 88 red, item2 255 red, sudo 66 red, review1 58 red, Advisor 111 red, item3 real-line wrong route, each followed by green on the attempted snapshot) [verified: .code-factory/logs/vaccination/]; integration=PASS and regression=PASS on the attempted snapshot [verified: .code-factory/logs/integration.log and regression.log]; business=FAIL overall (PowerShell PASS: 112 calls/786 assertions/0 mismatches; installer PASS: 56 assertions/0 mismatches; launchers FAIL: 346 calls/2439 assertions/10 mismatches, all builtin -- forms) [verified: .code-factory/logs/business-tests.md, business-test.log and builtin-business-failure.log]; review=request_changes across two iterations; four iteration-1 findings closed, iteration-2 quoted-control finding addressed by Advisor-authorized rework but no third review permitted [verified: .code-factory/logs/code-review.md and diagnostic.md]; acceptance=NOT RUN because the business gate failed [verified: .code-factory/logs/test-results.md]; rollback=COMPLETE (tracked diff and index empty, base 4607793, pre-existing untracked files unchanged) [verified: .code-factory/state/git-status-after.txt and git diff --exit-code]; backlog=3 open [verified: memory_project.py backlog --repo . --check expected exit 1 after this entry]
decisions: the final business mismatch was not softened or reclassified as out of scope; error_router returned WRONG_RESULTS/diagnostician, but Diagnostician=1/1 and Advisor=1/1 were exhausted and auto mode has no human branch, so the run stopped [verified: .code-factory/logs/builtin-business-failure.log, pipeline.yaml retry_counters and errors.md]; no product commit, version bump, documenter step, or acceptance claim was made after failure [verified: VERSION 12.14.2, empty tracked diff, .code-factory/report.md]; the failure snapshot was retained only for audit and report_code_changes generation, not as a delivered commit [verified: .code-factory/state/failure-snapshot-commit.txt and report_code_changes.md]
assumptions: auto mode cannot supply the Human escalation decision after the Advisor route fails, so FAILED with rollback is the honest terminal state [verified: task.yaml mode=auto and references/error-routing.md escalation ladder]; the new builtin -- vectors remain in the runtime business harness as red evidence for a future task [verified: .code-factory/state/business_acceptance.py and logs/business-test.log]
models_used: main=kimi-code/k3; analyzer=kimi-k3 x2; coder=deepseek-flash; tester=deepseek-flash; reviewer=kimi-k3 x2; diagnostician=kimi-k3; advisor=deepseek-flash; documenter=unused
factory_version: 12.14.2
unfinished:
  - item: PowerShell DECODED payloads are recursively split with POSIX backslash rules, so `pwsh -Command 'echo "\"; rm -rf /'` and `powershell -c 'echo "\"; git push origin main'` still ALLOW in hitl and auto (review iteration-2 major)
    reason: the attempted fix passed its business scenario on the failure snapshot, but all product changes were rolled back after the launcher business failure; it remains open at base with reusable vaccination evidence
    severity: critical
    follow_up: true
  - item: action_gate wrapper analysis does not cover launcher prefixes (env/sudo/builtin) and does not expand $(...) substitutions — both pre-existing at HEAD and outside F1's supported-wrapper set
    reason: terminal residual on the attempted snapshot: builtin -- and quoted/wrapped/push analogues still ALLOW (10 business mismatches); all escalation budgets are exhausted and the attempted changes were rolled back
    severity: warning
    follow_up: true
  - item: installer-side missing-Node line (chrome_devtools_mcp.py:632, `... cannot be installed` tail) still routes to the diagnostician instead of infrastructure
    reason: the attempted I1 fix passed with the real vendor_install() line on the failure snapshot, but rollback restored the base tree; it remains open with reusable red/green evidence
    severity: warning
    follow_up: true

## 2026-10-17T13:28:00+03:00 — Factory v12.14.3: full remaining backlog closed (3 -> 0)
title: Factory full remaining backlog — PowerShell backslash splitting, launcher prefixes and command substitutions, installer missing-Node routing (retry of FAILED run 20261017-1955b445, hitl)
project: repo
timestamp: 2026-10-17T13:28:00+03:00
run_id: 20261017-4beb46d5
branch: factory/fix-full-backlog-v2-20261017
commit: 692e518
task_type: implement
goal: close all three open backlog items with vaccination-first fixes, reusing the proven machinery of the failed attempt and correcting its builtin -- residual
changed_files: .agents/skills/code-factory/scripts/action_gate.py, .agents/skills/code-factory/scripts/test_action_gate.py, .agents/skills/code-factory/scripts/test_error_router.py, .agents/skills/code-factory/references/error-patterns.default.json, .agents/skills/code-factory/references/error-routing.md, .agents/skills/code-factory/references/chrome-devtools-mcp.md, CHANGELOG.md, VERSION, AGENTS.md, README.md, .agents/README.md, .agents/skills/code-factory/SKILL.md (last two: version sync only)
created_files: none to the product (only .code-factory/ runtime artifacts)
results: baseline=PASS (31 test_*.py + shell contract, 84 Windows PASS/0 FAIL) [verified: .code-factory/logs/baseline.md and baseline.log]; vaccination=PASS (item1+item2 583 red assertions incl. the reused sections 22-26, item2 builtin -- 25 new red assertions in section 27, item3 REAL vendor_install() line routed to diagnostician; all green after the fixes) [verified: .code-factory/logs/vaccination/ item1-item2-red.log, item2-builtin-terminator-red.log, item3-red.log and the *-green.log pairs]; integration=PASS (the per-task suites of the changed modules, test_action_gate.py and test_error_router.py, green after each fix) [verified: .code-factory/logs/vaccination/item1-item2-green.log and item3-green.log]; regression=PASS exit 0, 84 PASS/0 FAIL [verified: .code-factory/logs/regression.log]; business=PASS (powershell 112 calls/786 assertions/0 mismatches, launchers 346 calls/2439 assertions/0 mismatches incl. the builtin -- vectors that failed the previous run, installer 56 assertions/0 mismatches) [verified: .code-factory/logs/business-tests-powershell.md, business-tests-launchers.md, business-tests-installer.md]; review=APPROVE at iteration 1 (0 critical, 0 major, 1 deferrable minor: unterminated-quote launcher lines keep the pre-existing ALLOW, recorded below; 6/6 quotes VERIFIED) [verified: .code-factory/logs/code-review.md and scripts/verify_quotes.py exit 0]; acceptance=SUCCESS exit 0 (5 verify criteria MET + 1 derived, FRESH evidence ledger 4/4) [verified: .code-factory/state/acceptance.md and acceptance.log]; version=patch 12.14.2 -> 12.14.3, matrix-suggested and reviewer-validated [verified: version_manager.py suggest --fix -> patch, code-review.md version_type, validate exit 0]
decisions: reused the failed run's proven PowerShell-dialect and launcher/substitution machinery from .code-factory/logs/failed-diff.patch and corrected its diagnosed root cause — the builtin branch of strip_launcher() now skips one leading decoded `--` before reading the command name, mirrors env/sudo, and CONFIRMs an unsupported builtin option [verified: .code-factory/logs/builtin-business-failure.log root cause, action_gate.py strip_launcher, business-tests-launchers.md 0 mismatches]; the reviewer's minor finding (unterminated-quote launcher lines ALLOW, pre-existing and unreachable by any shell) is deferred as info, not folded into this scope [verified: .code-factory/logs/code-review.md finding 1, severity minor]; test-file changes are purely additive, no assertion weakened [verified: code-review.md iteration 1 and the test diff]
assumptions: the failed run's artifact business harness .code-factory/state/business_acceptance.py remains the business oracle and was re-run green on the delivered tree [verified: business-tests-*.md RESULT PASS]
models_used: main=kimi-code/k3; analyzer=kimi-k3; coder=deepseek-flash; reviewer=kimi-k3; documenter=deepseek-flash; diagnostician=unused; advisor=unused; tester=deepseek-flash (harness re-run by main)
factory_version: 12.14.3
closed:
  - item: PowerShell DECODED payloads are recursively split with POSIX backslash rules, so `pwsh -Command 'echo "\"; rm -rf /'` and `powershell -c 'echo "\"; git push origin main'` still ALLOW in hitl and auto (review iteration-2 major)
    evidence: decoded PowerShell payloads are now split in PowerShell's own dialect (backslash literal, doubled quotes escape only); both review vectors and all pwsh/powershell, -Command/-c, hitl/auto equivalents are HARD_DENY, benign balanced controls unchanged, ambiguous input CONFIRMs — section 22 of test_action_gate.py red-then-green, business powershell scenario 786 assertions/0 mismatches, acceptance criterion 2 MET [verified: .code-factory/logs/vaccination/item1-item2-red.log + item1-item2-green.log, .code-factory/logs/business-tests-powershell.md, .code-factory/state/acceptance.md]
  - item: action_gate wrapper analysis does not cover launcher prefixes (env/sudo/builtin) and does not expand $(...) substitutions — both pre-existing at HEAD and outside F1's supported-wrapper set
    evidence: env/sudo/builtin options, VAR=val assignments and the `--` terminator (including after `builtin`, the residual that failed run 20261017-1955b445) are parsed recursively without execution, readable $(...) substitutions are analyzed per the enclosing shell's quoting, unknown/ambiguous forms CONFIRM, benign forms stay ALLOW — sections 23-27 red-then-green, business launchers scenario 346 calls/2439 assertions/0 mismatches, acceptance criterion 3 MET [verified: .code-factory/logs/vaccination/item2-builtin-terminator-red.log + item1-item2-green.log, .code-factory/logs/business-tests-launchers.md, .code-factory/state/acceptance.md]
  - item: installer-side missing-Node line (chrome_devtools_mcp.py:632, `... cannot be installed` tail) still routes to the diagnostician instead of infrastructure
    evidence: row I1 of error-patterns.default.json (and the byte-consistent error-routing.md cell) gained the installer alternative; the REAL vendor_install() line is BROWSER_TOOLCHAIN/infrastructure, the probe route and unrelated routes unchanged — test_error_router.py red-then-green, business installer scenario 56 assertions/0 mismatches, acceptance criterion 4 MET [verified: .code-factory/logs/vaccination/item3-red.log + item3-green.log, .code-factory/logs/business-tests-installer.md, .code-factory/state/acceptance.md]
unfinished:
  - item: unterminated-quote launcher lines (`env "rm -rf /`, `builtin "rm -rf /`) keep the pre-existing ALLOW instead of the fail-safe CONFIRM the wrapper path gives the same unreadable shape
    reason: reviewer iteration-1 minor finding; no shell parses such a line so nothing destructive can hide behind it, and the pre-change behavior was the same ALLOW — deferred as an optional hardening candidate
    severity: info
    follow_up: false

## 2026-10-23T16:20:00+03:00 — Backlog: version_manager.py ignores a Rust workspace version

title: Factory backlog — version_manager.py sync/validate does not see [workspace.package] version, so a Cargo workspace keeps the old version while the factory reports PASS
project: repo
timestamp: 2026-10-23T16:20:00+03:00
run_id: 20261023-8170f3d9
branch: none (backlog entry, no code change)
commit: none
task_type: backlog
goal: record a defect observed while run 20261023-6c8f973e (target project farukon_v3.0.0) bumped a Rust workspace to 3.11.0, so the next factory run can close it with vaccination.
changed_files: none — this record only declares the debt (evidence note: .code-factory/state/backlog-note-version-manager.md)
created_files: none
results: finding=CONFIRMED (version_manager.py sync updated VERSION, README.md and AGENTS.md to 3.11.0 and validate exited 0 while farukon_v3.0.0/Cargo.toml:14 still read version = "3.10.0"; the workspace crates reported 3.10.0 until the file was corrected by hand and Cargo.lock refreshed) [verified: farukon_v3.0.0/Cargo.toml:14 fixed by hand in run 20261023-6c8f973e commit e63fe2d6, cargo check exit 0, version_manager.py validate PASS afterwards]; impact=NONE for shipped artifacts of that run (the version commit was corrected before delivery), but the validator is unsound for any Rust workspace [verified: the run's final Cargo.toml and VERSION both 3.11.0]
decisions: the item is recorded as follow_up=true rather than fixed now, because this session was scoped to the farukon_v3.0.0 target project and the factory's own rulebook requires a vaccination-first fix with its own test [verified: AGENTS.md factory rules, vaccination rule]
assumptions: the correct behaviour is to mirror VERSION into a workspace's [workspace.package] version (and a plain crate's [package] version), and for validate to fail on any divergence; the exact locations to sync are for the fixing run to confirm [inferred]
models_used: main=deepseek-flash (the session that observed it); no factory agents ran for this backlog entry
factory_version: 12.14.3
unfinished:
  - item: version_manager.py does not sync a Rust workspace's [workspace.package] version and validate still exits 0 on the divergence
    reason: observed in run 20261023-6c8f973e against farukon_v3.0.0 (validate PASS while Cargo.toml stayed 3.10.0); needs a vaccination-first fix (a test that fails on the current script) plus a validate rule covering Cargo.toml
    severity: warning
    follow_up: true

## 2026-10-25T14:04:33+03:00 — Review run 20261025-a32464ec: long-term memory mechanism — report only, the rework was NOT executed
title: Code review — is the long-term memory (memory/) real end to end? Report-only run; a flow violation (a review verdict entering the implement branch) was found, stopped by the owner and rolled back
project: repo
timestamp: 2026-10-25T14:04:33+03:00
run_id: 20261025-a32464ec
branch: none (report-only run; the tree stayed at the base commit)
commit: d87592a (base commit; `git status` shows 0 modified tracked files outside memory/)
task_type: review
goal: decide whether the documented long-term-memory mechanism is real in the code, in the flow, in the validators and in the actual contents of memory/, and deliver findings — not fixes
changed_files: none to the product (an unrequested rework was produced by the flow's review-to-implement edge and then rolled back; its diff is kept as .code-factory/rework-review-memory.patch)
created_files: .code-factory/logs/code-review.md, .code-factory/logs/code-review-merged.json, .code-factory/logs/findings-shard-0.json, .code-factory/logs/findings-shard-1.json, .code-factory/logs/review-shards.json, .code-factory/logs/review-evidence.md, .code-factory/logs/business-tests-memory.md, .code-factory/report.md, .code-factory/rework-review-memory.patch, task-review-workflow.yaml
results: review=request_changes (merged verdict, 21 findings: 1 critical, 9 major, 11 minor) [verified: merge_findings.py exit 1 over .code-factory/logs/findings-shard-0.json + findings-shard-1.json, summary in code-review.md]; integration=SKIP (no code change was delivered); regression=PASS (baseline 31 self-test files exit 0 each; the tree after the rollback equals the baseline tree) [verified: .code-factory/logs/baseline.log and .code-factory/logs/regression.log]; business=SKIP by construction (the six business scenarios need the rework; the harness .code-factory/state/business_memory.py is kept as the oracle for the next run) [verified: .code-factory/logs/business-tests-memory.md]; acceptance=FAILURE (2 of 8 criteria unmet: criterion 2 demands that memory_project.py check and check_factory_model.py both exit 0 on the delivered tree, criterion 8 demands that no memory rule be enforced by prose alone — both are only satisfiable by code changes, which a review run must not make) [verified: .code-factory/state/acceptance.md]
decisions: the flow routes a review verdict `request_changes` into the implement/coder branch (SKILL.md:102 `CRV0 -->|request_changes| G`, SKILL.md:97 "the plan is the review rework list", code-factory.md:408-409 "its rework list becomes the plan"); the run followed that branch, rewrote 18 tracked files (+1768/-152), the owner stopped it and ordered a rollback, and the tree is back at d87592a [verified: git status --porcelain reports 0 modified files after `git restore`, HEAD d87592a, and .code-factory/rework-review-memory.patch holds the 2868-line diff of the discarded rework]; the memory-ownership question (P1) is answered by the rulebook — the owner is the basename of the resolved repo_path, so the committed `project: repo` is the wrong side — but the migration is work for a separate implement task, not for this review [verified: memory_project.py check --repo . exit 1 with the rename hint, back in its pre-run state]; the half-acceptance question (P2) is a real validator divergence, not a stale record: check_factory_model.py rejects the factory-written `task_type: backlog` record while memory_project.py accepts it [verified: check_factory_model.py --repo . exit 1 with the five errors, memory_project.py check --repo . --expect repo exit 0]; the task file's own acceptance criterion 2 is unsatisfiable in report-only mode and is recorded as the counter-example for task-review-workflow.yaml [verified: .code-factory/state/acceptance.md criterion 2 FAILED with exit 1]
assumptions: the review's findings are the debt of the follow-up implement run; .code-factory/rework-review-memory.patch is a draft proposal, not an approved change, and must be re-validated against the then-current tree
models_used: main=deepseek-flash; reviewer=kimi-k3 (2 parallel shards); analyzer=deepseek-flash; coder=deepseek-flash (discarded rework); tester=deepseek-flash; documenter=unused (review task); diagnostician=unused; advisor=unused
factory_version: 12.14.3
unfinished:
  - item: the factory flow routes a review's request_changes verdict into the implement/coder branch, so a report-only task type implements its own findings (SKILL.md:102, SKILL.md:97, code-factory.md:408-409); the security_audit branch alone says "No code change and no auto-fixing"
    reason: found by this run after the owner stopped an unrequested 18-file rework; needs a flow change (route the review verdict to the report + a fix-task artifact) plus a self-test that pins it; recorded as task-review-workflow.yaml for a separate review run
    severity: critical
    follow_up: true
  - item: memory/summary.md and all 24 journal records declare `project: repo` while the ownership rule pins the owner to the basename of the resolved repo_path (automated-code-factory_v12.13.0); memory_project.py check exits 1 on the committed memory
    reason: the rulebook makes the memory data the wrong side, but the migration (rename) and the escape-hatch documentation (subdirectory case) are work for an implement task
    severity: warning
    follow_up: true
  - item: a memory record kind the factory itself writes (task_type backlog) is rejected by check_factory_model.py and accepted by memory_project.py — half-accepted, so the factory's own gate is red on this repository
    reason: needs the record kind sanctioned in the journal format and enforced identically by both validators, with tests; history must not be rewritten
    severity: warning
    follow_up: true
  - item: the SKILL.md Finish node demands backlog --check exit 0 while the canonical memory-actuality rule allows carrying an item over in unfinished with a reason, so the factory's own memory cannot pass its own Finish gate
    reason: needs the Finish wording aligned with the canonical rule (critical/follow_up debt blocks Finish; warning/info with follow_up=false is a conditional pass), never a weakened validator
    severity: warning
    follow_up: true
  - item: the compaction promise (threshold 50, keep last 20, critical/follow_up survive) has no implementation and compact-check is named in no SKILL.md node; the precedent index (precedent_index.py) is built by no flow node while AGENTS.md presents it as living state
    reason: both mechanisms are tested but unwired; wiring or correcting the documentation is an implement task
    severity: warning
    follow_up: true
  - item: completed review run 20260929-62232c10 (findings F1-F18) has neither a journal record nor a memory commit
    reason: history is append-only and the run's artifacts were deleted, so a backfill record would fabricate provenance; kept as history evidence, not to be rewritten
    severity: info
    follow_up: false
  - item: the 11 minor findings of the merged verdict (absent-memory verdict split, unreadable-journal traceback, pre-v2 warning gap, 'one entry per run' unenforced, english-only gate excluding memory/, and the rest) stay unaddressed
    reason: recorded in .code-factory/logs/code-review.md with file:line; folded into the follow-up implement task
    severity: info
    follow_up: false

## 2026-10-25T15:02:28+03:00 — Review run 20261025-d412a454: is a `task_type: review` run report-only in the factory's flow? No — the review verdict is routed into the implement branch
title: Code review — the review branch of the factory flow versus the report-only contract; report-only run, no tracked file edited, no coder started after the verdict
project: repo
timestamp: 2026-10-25T15:02:28+03:00
run_id: 20261025-d412a454
branch: main (no feature branch: a report-only run produces no product change to isolate)
commit: d87592a (base commit; `git status` shows 0 modified tracked files outside memory/)
task_type: review
goal: decide whether a `task_type: review` run is report-only in the factory's own flow, trace every edge that starts at a review verdict, and establish P0-P7 / W1-W6 each with a command, an exit code and an artifact — without drafting a patch
changed_files: none to the product (this run's writes are .code-factory/ artifacts and its own memory records)
created_files: .code-factory/logs/code-review.md, .code-factory/logs/findings/{shard-1,shard-2}.json, .code-factory/logs/findings/merged.{json,md}, .code-factory/logs/w1-flow-trace.log, .code-factory/logs/w5-gates.log, .code-factory/logs/p0-origin-criterion.log, .code-factory/logs/p3-read-only-statements.log, .code-factory/logs/quote-{claims,check,crosscheck}.json, .code-factory/logs/review-shards.json, .code-factory/report.md, .code-factory/state/{plan.md,criteria.json,trace_flow.py,build_claims.py,crosscheck_findings.py}
results: review=request_changes (merged verdict of 2 shards, 18 findings: 3 critical, 8 major, 4 minor, 3 nit) [verified: merge_findings.py exit 1 over .code-factory/logs/findings/shard-1.json + shard-2.json, merged report in .code-factory/logs/code-review.md]; integration=SKIP (no code change was delivered); regression=PASS (all 31 self-test files exit 0 before and after the run; check_factory_rules.py 25 rules / 100 carriers exit 0; check_english_only.py exit 0; version_manager.py validate exit 0 at 12.14.3) [verified: .code-factory/logs/baseline.md and .code-factory/state/acceptance.md]; business=SKIP by construction (the five business scenarios describe a report-only outcome, which is verified by criterion 2 of the acceptance check instead of by a program run) [verified: .code-factory/state/acceptance.md]; acceptance=SUCCESS (4 verify criteria MET, 0 FAILED, 2 derived; regression=pass; evidence ledger FRESH) with the two red repository gates check_factory_model.py and memory_project.py check left exactly as found, exit 1 for pre-existing reasons this run must not fix [verified: verify_acceptance.py exit 0, .code-factory/state/acceptance.md, .code-factory/state/evidence-20261025-d412a454.json]
decisions: a review verdict has TWO writing edges, not one — `CRV0 -->|request_changes| G` (SKILL.md:102), where G is literally the implement entry (`TT -->|implement| G`, SKILL.md:103) that leads to pre-flight, backups and `M` "launch factory-coder subagents" (SKILL.md:120), and the acceptance-failure edge `X -->|No| RR --> RR2 -->|coder| P --> M` (SKILL.md:164, :126) which every task type shares, including security_audit [verified: .code-factory/state/trace_flow.py exit 1, shortest-path trace in .code-factory/logs/w1-flow-trace.log]; the read-only guarantee exists exactly once in the whole rulebook-and-flow surface and belongs to security_audit (`No code change and no auto-fixing`, SKILL.md:106; `The factory must NOT start fixing after the audit.`, references/security-audit.md:58) — a census of every carrier finds 0 statements of the kind about review [verified: .code-factory/logs/p3-read-only-statements.log]; the review "plan" is defined as the implement DAG (`SKILL.md:97`, `:99`, code-factory.md:232, planning-guide.md:82), which is how a report becomes a work order [verified: 4 quotations pinned by line and re-checked by verify_quotes.py, 35/35 VERIFIED]; the acceptance contract permits a review criterion that only a code change can satisfy, and the reproduction case proves it — the origin task's criterion 2 verify command exits 1 for pre-existing reasons [verified: .code-factory/logs/p0-origin-criterion.log, both validators exit 1]; no self-test pins the routing: 0 tests name CRV0, the only flow-graph invariant pins J|Approve->K and G|auto->K, verify_acceptance.py never reads task_type, and none of the 25 rules covers a report-only review [verified: .code-factory/logs/w5-gates.log]; the finish side is correct — SKILL.md:171 skips the documenter and the version steps for review, `suggest --no-change` returns none and VERSION stayed 12.14.3, though a review run that took the G edge would therefore mutate the product with no version trace at all [verified: version_manager.py validate exit 0, suggest --no-change exit 0]
assumptions: the six open backlog items are carried unchanged — this run produced the diagnosis of the routing item, not its fix, and a review run may not close an item without evidence of closure; the owner decides whether the findings become an implement task
models_used: main=deepseek-flash; reviewer=kimi-k3 (2 parallel shards); analyzer=deepseek-flash (plan written by the main agent); coder=unused (no code change); tester=unused (no code change); documenter=unused (review task); diagnostician=unused; advisor=unused
factory_version: 12.14.3
unfinished:
  - item: the factory flow routes a review's request_changes verdict into the implement/coder branch, so a report-only task type implements its own findings (SKILL.md:102, SKILL.md:97, code-factory.md:408-409); the security_audit branch alone says "No code change and no auto-fixing"
    reason: diagnosed, not fixed — this run established the routing with a graph trace (trace_flow.py exit 1) and added the second, previously unrecorded edge X|No->RR->P->M that reaches a coder for every task type; changing the flow is an implement task and the decision belongs to the owner
    severity: critical
    follow_up: true
  - item: version_manager.py does not sync a Rust workspace's [workspace.package] version and validate still exits 0 on the divergence
    reason: no evidence of closure; untouched by this review run
    severity: warning
    follow_up: true
  - item: memory/summary.md and all 24 journal records declare `project: repo` while the ownership rule pins the owner to the basename of the resolved repo_path (automated-code-factory_v12.13.0); memory_project.py check exits 1 on the committed memory
    reason: re-verified red by this run (memory_project.py check exit 1); the migration is a memory/code change a review run must not make
    severity: warning
    follow_up: true
  - item: a memory record kind the factory itself writes (task_type backlog) is rejected by check_factory_model.py and accepted by memory_project.py — half-accepted, so the factory's own gate is red on this repository
    reason: re-verified red by this run (check_factory_model.py exit 1 on the 2026-10-23 backlog record); fixing it means editing history or a validator
    severity: warning
    follow_up: true
  - item: the SKILL.md Finish node demands backlog --check exit 0 while the canonical memory-actuality rule allows carrying an item over in unfinished with a reason, so the factory's own memory cannot pass its own Finish gate
    reason: this run is itself the demonstration — it carried six items over in unfinished with reasons, so `backlog --check` exits 1 while the canonical rule is satisfied
    severity: warning
    follow_up: true
  - item: the compaction promise (threshold 50, keep last 20, critical/follow_up survive) has no implementation and compact-check is named in no SKILL.md node; the precedent index (precedent_index.py) is built by no flow node while AGENTS.md presents it as living state
    reason: no evidence of closure; untouched by this review run
    severity: warning
    follow_up: true

## 2026-10-25T19:20:00+03:00 — Review run 20261025-634bc01b: does the long-term memory (`memory/`) really work as the rulebook requires?
title: Code review (report only) — read path, write path, ownership, compaction, actuality, validator cross-consistency and rulebook agreement of the factory's long-term memory
project: repo
timestamp: 2026-10-25T19:20:00+03:00
run_id: 20261025-634bc01b
branch: main (no feature branch: a report-only run produces no product change to isolate)
commit: d87592a (base commit; `git status` shows 0 modified tracked files outside memory/)
task_type: review
goal: decide whether the long-term memory mechanism is real end to end — in the code, in the flow, in the validators and in the contents of memory/ today — establishing P1-P5 and M1-M8 each with a command, an exit code and an artifact, without drafting a patch
changed_files: none to the product (this run's writes are .code-factory/ artifacts and this record plus the summary actualization)
created_files: .code-factory/logs/code-review.md; .code-factory/logs/code-review-merged.json; .code-factory/logs/code-review-shards/shard-1.json; .code-factory/logs/code-review-shards/shard-2.json; .code-factory/logs/review-shards.json; .code-factory/logs/baseline-selftests.log; .code-factory/logs/probes-evidence.log; .code-factory/logs/m5-version-warning.log; .code-factory/logs/p2-validator-full.log; .code-factory/logs/quote-claims.json; .code-factory/logs/quote-report.json; .code-factory/report.md; .code-factory/state/plan.md; .code-factory/state/pipeline.yaml; .code-factory/state/criteria.json; .code-factory/state/acceptance.md
results: review=request_changes (merged verdict of 2 shards, 20 findings: 2 critical, 11 major, 7 minor) [verified: merge_findings.py exit 1 over .code-factory/logs/code-review-shards/shard-1.json + shard-2.json, merged report .code-factory/logs/code-review.md]; integration=SKIP (no code change was delivered) [inferred]; regression=PASS (all 31 factory self-test files exit 0 before and after the run; check_factory_rules.py 25 rules / 100 carriers exit 0; check_english_only.py exit 0 over 119 files; VERSION stayed 12.14.3) [verified: .code-factory/logs/baseline-selftests.log, .code-factory/state/acceptance.md]; business=SKIP by construction (the six business scenarios describe a report-only outcome and are verified by the acceptance criteria, not by a program run) [verified: .code-factory/state/acceptance.md]; acceptance=SUCCESS (7 verify criteria MET, 0 FAILED, 2 derived; regression=pass; evidence ledger FRESH) with the two red repository gates memory_project.py check and check_factory_model.py left exactly as found at exit 1 [verified: verify_acceptance.py exit 0, .code-factory/state/acceptance.md]
decisions: the read path is real for the main agent (SKILL.md:88 BEGIN names the summary, the recent journal entries and the exact backlog fold) but not for the delegated roles — the mandatory briefing template has 8 sections and no memory-facts slot, every consumer reads memory only "if the main agent provided them", and the folded backlog has no route into any briefing [verified: references/handoff-briefing.md, analyzer.md:21, finding 14 of .code-factory/logs/code-review.md]; the write path enforces the format (required keys, run_id shape, provenance marks in both validators) but not the lifecycle: run_id.py check excludes memory/ from ARTIFACT_GLOBS, a duplicate run_id in two valid records is accepted, and a deployment root without memory/ passes both memory_project.py check and backlog --check while check_factory_model.py fails — the two named validators disagree in opposite directions [verified: .code-factory/logs/probes-evidence.log, findings 6 and 7]; the ownership validator is right and the data is wrong (`project: repo` vs the pinned basename), but the identity model itself is defective — rename/re-version of the deployment root silently invalidates memory nobody edited, and the documented subdirectory configuration has no flag-free pass (plain check exit 1, --expect exit 0) [verified: .code-factory/logs/probes-evidence.log]; compaction is prose plus a manual post-hoc check: no compact subcommand (exit 2), the 50/20 numbers exist only in template text, only the critical/follow_up survival third is implemented and no SKILL.md node names compact-check [verified: .code-factory/logs/probes-evidence.log, finding 5]; actuality is half-real — the closed:/evidence: protocol and the whole-journal fold work (open 6, closed 39, legacy_drift 6, errors 0) and the version divergence IS computed but only as a WARN that never changes an exit code and is never called by check, while test counts and open backlog are compared with nothing [verified: .code-factory/logs/m5-version-warning.log, finding 16]; the two validators diverge on six axes in both directions (owner, task_type backlog, required keys, results sub-keys, empty project:, closed: without evidence:) and no test ties them together [verified: .code-factory/logs/probes-evidence.log, findings 2 and 11]; rulebook agreement: only memory-provenance is enforced as written; memory-ownership's single-writer/one-entry and compaction clauses are unenforced and memory-actuality's Finish node (backlog --check exit 0) contradicts the carry-over branch the same node and the rule allow [verified: finding 1 critical, memory_project.py backlog --repo . --check exit 1 with open: 6]; model precedence is stated three times and pinned nowhere (canonical generator-ne-judge unconditional in AGENTS.md:236, providers.md:159 "a warning, not a blocker", SKILL.md:334 matrix-first except the second planner), no code computes a model family and models_used is self-reported — this run is the live test: the first review pass overrode models.reviewer deepseek-flash with kimi-k3, produced no verdict, and both shards were re-run on deepseek-flash after the owner's ruling that the task is authoritative [verified: .code-factory/tmp/discarded-kimi-review/, session wire agents/agent-0 and agent-1 (80 llm.request events, model k3, 0 errors), findings 4 and 10]
assumptions: the six pre-existing open backlog items are carried unchanged, because a review run may produce the diagnosis of an item but not its closure; this record declares project: repo (not the rule-pinned basename) because 26 existing records declare repo and one record with another value would make the journal mix projects — the mismatch is carried as open debt instead of being edited, and history is not rewritten; the model-matrix conflict is resolved in favor of the task per the owner's ruling and recorded as debt rather than silently applied
models_used: main=deepseek-flash; reviewer=deepseek-flash (2 parallel shards, per the task models matrix); analyzer=deepseek-flash (plan written by the main agent); coder=unused (no code change); tester=unused (no code change); documenter=unused (review task); diagnostician=unused; advisor=unused
factory_version: 12.14.3
unfinished:
  - item: the generator≠judge rule is written unconditionally and was applied against an explicit task models matrix (this run: models.reviewer deepseek-flash overridden with kimi-k3 for two shard passes, discarded and re-run); it must be a DEFAULT for roles the task does not name, with the task matrix winning whenever both are specified, and the precedence must be stated once and pinned by a test
    reason: owner-raised in this run and not fixed here — a review run drafts no patch; the fix is a rulebook wording change plus a precedence test
    severity: critical
    follow_up: true
  - item: models_used is self-reported by the main agent and nothing derives it from the session wire, so an override or a silent substitution is invisible in pipeline.yaml, report.md and this journal; this run could answer "did kimi-k3 really run" only from ~/.kimi-code/sessions/.../agents/agent-*/wire.jsonl
    reason: diagnosed, not fixed — the artifact that proves model attribution is outside the repository and no script reads it
    severity: warning
    follow_up: true
  - item: version_manager.py does not sync a Rust workspace's [workspace.package] version and validate still exits 0 on the divergence
    reason: still open, and this run added the mechanism evidence (finding 9: validate on a tree with Cargo.toml on another version prints PASS and exits 0); a review run may not fix it
    severity: warning
    follow_up: true
  - item: the factory flow routes a review's request_changes verdict into the implement/coder branch, so a report-only task type implements its own findings (SKILL.md:102, SKILL.md:97, code-factory.md:408-409); the security_audit branch alone says "No code change and no auto-fixing"
    reason: still open; this run deliberately did not take the edge (no coder started after the verdict) per the owner's explicit instruction, which is the workaround the item exists to remove
    severity: critical
    follow_up: true
  - item: memory/summary.md and all 24 journal records declare `project: repo` while the ownership rule pins the owner to the basename of the resolved repo_path (automated-code-factory_v12.13.0); memory_project.py check exits 1 on the committed memory
    reason: re-verified red by this run (check exit 1; --expect repo exit 0) and grown to 26 records before this one; the migration is a memory change a report-only run must not make
    severity: warning
    follow_up: true
  - item: a memory record kind the factory itself writes (task_type backlog) is rejected by check_factory_model.py and accepted by memory_project.py — half-accepted, so the factory's own gate is red on this repository
    reason: re-verified red by this run (check_factory_model.py exit 1, five errors on the 2026-10-23 record); fixing it means editing history or completing a validator
    severity: warning
    follow_up: true
  - item: the SKILL.md Finish node demands backlog --check exit 0 while the canonical memory-actuality rule allows carrying an item over in unfinished with a reason, so the factory's own memory cannot pass its own Finish gate
    reason: this run is again the demonstration — it carries eight items with reasons, so backlog --check exits 1 while the canonical rule is satisfied; finding 1 rates the contradiction critical
    severity: warning
    follow_up: true
  - item: the compaction promise (threshold 50, keep last 20, critical/follow_up survive) has no implementation and compact-check is named in no SKILL.md node; the precedent index (precedent_index.py) is built by no flow node while AGENTS.md presents it as living state
    reason: re-verified by this run (no compact subcommand; compact-check exit 0 with --help only; 0 hits of precedent_index in SKILL.md; precedents.db stale — query a32464ec matches: 0)
    severity: warning
    follow_up: true

## 2026-10-25T23:40:00+03:00 — v12.15.0: one honest-factory patch — report-only review, model precedence from the task, verifiable memory, real compaction and a working precedent index

title: The 46 items of three sources closed (review 20261025-634bc01b, the open backlog, the earlier report-only-review task) — a review run is report-only, models come from the task and otherwise from the factory matrix, the memory is verifiable, compaction and the precedent index really work, and the small defects are gone
project: repo
timestamp: 2026-10-25T23:40:00+03:00
run_id: 20261025-4e17a349
branch: feature/v12.15.0-honest-factory
commit: the v12.15.0 release commit on feature/v12.15.0-honest-factory (branch point and base: fb43f2a)
task_type: implement
goal: make the factory keep what its rulebook promises in the three areas the owner distrusts - a review must bring knowledge and not edits, a model must be the one the task names (or the factory's default matrix) and that must be provable, and the project memory must be checkable - plus the promised compaction, the "how was this solved before" index and the small defects
changed_files: 41 tracked files (rulebook and its carriers, the SKILL.md flow, the agent spec, references, both task templates, AGENTS.md, .agents/README.md, CHANGELOG.md, VERSION, 17 scripts and 10 self-tests, memory/summary.md)
created_files: model_matrix.py, model_attribution.py, review_followup_task.py, test_model_precedence.py, test_model_attribution.py, test_review_followup_task.py, test_review_report_only.py, test_security_audit_guarantee.py, test_flow_contracts.py, test_vaccination.py, memory/.english-freeze, plus the run artifacts under .code-factory/ (plan, baseline, acceptance, findings-disposition.md, review diff, logs)
results: integration=PASS (38 self-test files exit 0, including the new guards and the 24-vaccine harness) [verified: .code-factory/logs/regression-after-waveC.log "TOTAL 38 FAILED 0" and test_vaccination.py "24 vaccine(s) bite"]; regression=PASS (the 31 files green at the base commit fb43f2a are still green; the count only grew 31 -> 38 and no test was deleted) [verified: .code-factory/logs/baseline.md vs the same runner after the change]; business=PASS (all seven business scenarios of the task are covered by executable checks: report-only review, the acceptance stop, the three model-matrix cases, memory passing its own gates, the folder rename, compaction, and "nothing weakened") [verified: test_review_report_only.py, test_verify_acceptance.py, test_model_precedence.py, test_memory_project.py, test_check_english_only.py]; review=request_changes in iteration 1 (3 major, 3 minor, 0 critical), five of six reworked and confirmed in iteration 2, which then found a second-fold closure bug that was fixed after the 2-iteration budget and is proven by test_memory_project.py cases 32 and 33 instead of a third review; no critical finding was open at any point [verified: the two reviewer verdict reports, neither with a critical finding]; acceptance=SUCCESS (17 criteria: 16 with a verify command MET, 1 derived; regression baseline pass) [verified: .code-factory/state/acceptance.md, produced by verify_acceptance.py against .code-factory/state/criteria.json; the second run signs the evidence ledger]
decisions: the owner chose to make the precedent index work rather than drop the promise, and to translate the Russian summary into English while freezing journal history [verified: the owner's two answers before the plan was approved]; a review verdict now ends at the report-only delivery node RD, and an unmet review/security_audit criterion goes to the stop-and-ask node XR instead of error routing [verified: test_review_report_only.py flow-guard, whose pre-fix probe catches 33 violations on the restored old graph]; the model precedence is implemented once in model_matrix.py (task matrix verbatim, a collision is a warning, the default matrix enforces generator != judge, the committee's second planner is the only override) [verified: test_model_precedence.py, and every role of this run really stayed deepseek-flash]; the memory contract is implemented once in memory_project.validate_memory and check_factory_model delegates to it [verified: test_factory_model.py parity block over the six former divergence axes]; the ownership identity is the repository root commit, not the folder name [verified: memory_project.py check --repo . exit 0 with basis "identity" while the folder name and project: repo disagree]; task_type backlog became a documented record kind with its own results contract instead of downgrading the v2 gate [verified: check_factory_model.py --repo . exit 0 with the 2026-10-23 record unchanged]; the version type is minor 12.15.0 - the deterministic matrix proposed patch and the reviewer overrode it with the explanation that a new rule, flow nodes, scripts, a summary field and a record kind are additive, not breaking [verified: version_manager.py set 12.15.0 + sync + validate exit 0, and the reviewer's version-type verdict]
assumptions: the vaccine registry's durable ground truth is the self-test's own table, so a clean checkout without the gitignored .code-factory/logs/findings-disposition.md still proves all 24 vaccines bite (the disposition cross-check is a run-time artifact check); the vaccination proof needs the release base commit and reports SKIP (exit 3) when the history is shallow; version_manager's Cargo sync only rewrites an existing literal and never inserts a field
models_used: main=deepseek-flash; analyzer=deepseek-flash (4 read-only analysis packages); coder=deepseek-flash (8 implementation packages + 3 rework packages); reviewer=deepseek-flash (2 review iterations); documenter=deepseek-flash (1 pass); tester=unused (the test runs were executed by the main agent); planner=unused (the plan was written by the main agent); diagnostician, advisor, gui_expert, security_auditor, skill_manager, refactorer=unused
factory_version: 12.15.0
closed:
  - item: version_manager.py does not sync a Rust workspace's [workspace.package] version and validate still exits 0 on the divergence
    evidence: v12.15.0 — validate compares [workspace.package], a member literal [package] version and a single-crate version; sync rewrites only an existing literal and is byte-idempotent; .code-factory/ and target/ are pruned [verified: test_version_manager.py cases 18-24 including a diverging workspace -> exit 1, and version_manager.py --repo . validate exit 0 on this repo]
  - item: the factory flow routes a review's request_changes verdict into the implement/coder branch, so a report-only task type implements its own findings (SKILL.md:102, SKILL.md:97, code-factory.md:408-409); the security_audit branch alone says "No code change and no auto-fixing"
    evidence: v12.15.0 — both former write edges end at the report-only delivery node RD; the end-of-task gate and the acceptance-failure edge are split by task type (implement/refactor -> RR, review/security_audit -> the stop-and-ask node XR); the new canonical rule review-report-only is byte-identical in 5 carriers [verified: test_review_report_only.py flow-guard and its pre-fix probe, test_security_audit_guarantee.py, check_factory_rules.py --rule review-report-only]
  - item: memory/summary.md and all 24 journal records declare `project: repo` while the ownership rule pins the owner to the basename of the resolved repo_path (automated-code-factory_v12.13.0); memory_project.py check exits 1 on the committed memory
    evidence: v12.15.0 — the summary declares project_id (the first 12 hex of the sha256 of the root commit) and the ownership chain prefers it over the folder name; no journal record was rewritten; the rule states the identity model [verified: memory_project.py check --repo . exit 0 with basis "identity", and the rename/copy cases of test_memory_project.py]
  - item: a memory record kind the factory itself writes (task_type backlog) is rejected by check_factory_model.py and accepted by memory_project.py — half-accepted, so the factory's own gate is red on this repository
    evidence: v12.15.0 — backlog is a documented record kind requiring results finding=/impact=, applied by the single shared contract; the 2026-10-23 record is legal unchanged [verified: check_factory_model.py --repo . exit 0 and the six-axis parity block of test_factory_model.py]
  - item: the SKILL.md Finish node demands backlog --check exit 0 while the canonical memory-actuality rule allows carrying an item over in unfinished with a reason, so the factory's own memory cannot pass its own Finish gate
    evidence: v12.15.0 — backlog --check exits 0 when nothing disappeared (a carried item with a reason is legal) and 1 for a disappeared item, a reasonless carry or an invalid closure; the Finish node and the canonical rule now say the same thing [verified: memory_project.py backlog --repo . --check exit 0 with carried: 8, and the unmentioned/reasonless cases of test_memory_project.py]
  - item: the compaction promise (threshold 50, keep last 20, critical/follow_up survive) has no implementation and compact-check is named in no SKILL.md node; the precedent index (precedent_index.py) is built by no flow node while AGENTS.md presents it as living state
    evidence: v12.15.0 — memory_project.py compact implements the fold with a semantic pre-write verification (a second fold cannot orphan a closure); the Finish node invokes it; the analysis node builds the index and queries it with --fresh, and status reports FRESH/STALE [verified: test_memory_project.py cases 28-33, test_precedent_index.py, test_flow_contracts.py, and a live build whose FRESH status and query now find run 20261025-634bc01b]
  - item: the generator≠judge rule is written unconditionally and was applied against an explicit task models matrix (this run: models.reviewer deepseek-flash overridden with kimi-k3 for two shard passes, discarded and re-run); it must be a DEFAULT for roles the task does not name, with the task matrix winning whenever both are specified, and the precedence must be stated once and pinned by a test
    evidence: v12.15.0 — the family rule is the DEFAULT for unnamed roles only; a task-named model is used verbatim and a collision is a warning; model_matrix.py is the single implementation and test_model_precedence.py pins every case [verified: test_model_precedence.py, and this run's nine family collisions produced warnings with no substitution - every role stayed deepseek-flash]
  - item: models_used is self-reported by the main agent and nothing derives it from the session wire, so an override or a silent substitution is invisible in pipeline.yaml, report.md and this journal; this run could answer "did kimi-k3 really run" only from ~/.kimi-code/sessions/.../agents/agent-*/wire.jsonl
    evidence: v12.15.0 — model_attribution.py reads agents/*/wire.jsonl of the current session, derives the model served per role, cross-checks models_used and returns match/mismatch (exit 1)/degraded (exit 3); the Finish node runs it [verified: test_model_attribution.py (10 cases including the k3-vs-claim mismatch) and a live run against this session's wire]
unfinished:
  - item: the fixture digest pinned in test_run_id.py (KNOWN_TASK_RUN_ID) depends on the checkout's line endings, because run_id hashes the raw task bytes
    reason: pre-existing brittleness, exposed when assets/task-template.yaml legitimately changed and the pin had to be moved to 20260929-f6a6e8c8; normalizing CRLF in run_id would change every historical run id, so it needs its own vaccination-first task
    severity: warning
    follow_up: true
  - item: the vaccination harness needs the release base commit and reports SKIP (exit 3) in a shallow clone
    reason: by design - a proof without the pre-fix tree would be a tautology - but a shallow clone therefore cannot run that self-test green
    severity: info
    follow_up: false

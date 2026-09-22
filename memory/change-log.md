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
branch: <ветка или "(none)">
commit: <sha или "(none)">
task_type: implement | review | refactor | security_audit
goal: <краткая цель>
changed_files: <список через "; ">
created_files: <список через "; ">
results: integration=<PASS|FAIL|SKIP>; regression=<...>; business=<...>; review=<approve|request_changes|SKIP>
decisions: <принятые решения и допущения>
assumptions: <допущения>
models_used: analyzer=<модель>; planner=<модель>; coder=<модель>; tester=<модель>; reviewer=<модель>; diagnostician=<модель>; documenter=<модель>
factory_version: <X.Y.Z — версия фабрики на момент прогона>
unfinished: нет незавершённых элементов
```

Однострочный пример записи (одна запись — один блок, поля построчно):
`title: Короткий заголовок | project: automated_vode_factory_v_12.15.1 | timestamp: 2026-01-01T00:00:00+0300 | task_type: implement`

Память `memory/` принадлежит ТОЛЬКО одному проекту — тому, что указан в поле `repo_path`
задачи; `project:` = basename разрешённого `repo_path`. Для этого репозитория целевой проект —
сама фабрика, поэтому во всех записях `project: automated_vode_factory_v_12.15.1`. Разные
значения `project:` в одном журнале — ошибка (память смешивает проекты; ловят
`scripts/check_factory_model.py` и `scripts/memory_project.py check`); записи без `project:` —
legacy (предупреждение, не ошибка).

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
(не ошибкой).

## 2026-09-01T01:01:45+0300 — AGENTS.md как единый источник правды + переносимая память
title: AGENTS.md как единый источник правды + переносимая долгосрочная память
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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
project: automated_vode_factory_v_12.15.1
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

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

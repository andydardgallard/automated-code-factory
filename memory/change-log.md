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
`unfinished`/`factory_version` проходят валидацию с предупреждением (не ошибкой).

## 2026-09-01T01:01:45+0300 — AGENTS.md как единый источник правды + переносимая память
title: AGENTS.md как единый источник правды + переносимая долгосрочная память
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

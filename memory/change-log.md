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
models_used: analyzer=<модель>; planner=<модель>; coder=<модель>; tester=<модель>; reviewer=<модель>; diagnostician=<модель>
```

(пока нет записей)

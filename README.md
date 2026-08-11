# Autonomous Code Factory v10

Автономная фабрика по написанию кода для **Kimi Code CLI + Kimi Agents SDK**.

Принимает бизнес-задачу от нетехнического пользователя, анализирует проект, планирует
изменения, уточняет только бизнес-логику, согласует план, реализует код и гоняет
интеграционные / регрессионные / бизнес-тесты с автоматическим откатом при неудаче.

Поддерживает **любые языки** и **любые типы проектов** (фронтенд, бэкенд, CLI, библиотека,
green-field) — стек определяется автоматически.

## Возможности

- **Работа из терминала** Kimi Code CLI: `/flow:code-factory`
- **Два режима**: `hitl` (уточняет бизнес-вопросы, план на согласование) и `auto` (полный автомат)
- **Детерминированная маршрутизация ошибок** (~90% без LLM) + **Diagnostician** (LLM-fallback) + Human → FAILED (никогда не падает молча)
- **Откат при неудаче** любого теста (бэкапы + манифест + git)
- **Checkpoint / resume** — продолжает с места сбоя
- **Git-native**: `git init` при отсутствии репозитория, feature-ветка на задачу, `commit_exclude`
- **Настраиваемые модели** для ролей (deepseek / qwen / kimi и др.) — `.agents/agents/models.yaml`
- **Автоотчёты**: `report.md` (история прогона) + `report_code_changes.md` (diff «было→стало»)

## Структура

```
├── .agents/
│   ├── README.md                    # полная инструкция по фабрике
│   ├── skills/code-factory/         # flow skill (SKILL.md) + references + scripts
│   ├── agents/                      # главный агент + сабагенты + models.yaml
│   └── examples/run_factory_sdk.py  # запуск через Kimi Agent SDK
├── AGENTS.md                        # контекст для агентов Kimi
├── prepare_factory.sh               # развернуть фабрику в проект (1 команда)
├── .example.task.yaml               # пример/шаблон бизнес-задачи
└── .gitignore
```

## Быстрый старт

```bash
# 1. Развернуть фабрику в проект
./prepare_factory.sh /path/to/your-project

# 2. Запустить
cd /path/to/your-project
kimi
# в чате: /flow:code-factory
```

Либо через SDK:

```bash
python3 .agents/examples/run_factory_sdk.py task.yaml
```

## Формат бизнес-задачи (task.yaml)

Скопируйте `.example.task.yaml` в `task.yaml` и заполните поля (обязательны только
`title` и `description`):

```yaml
title: "Стратегия не генерирует сигналы для CNY"
repo_path: ./repo            # только для существующих проектов
description: |
  Опишите проблему бизнес-языком, без технических деталей.
priority: high               # high | medium | low
mode: hitl                   # hitl (по умолчанию) | auto
acceptance_criteria:
  - "Стратегия генерирует не менее 5 сигналов LONG/SHORT для CNY"
```

Полное описание всех полей — в комментариях самого `.example.task.yaml`.

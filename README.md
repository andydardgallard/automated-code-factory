# Autonomous Code Factory v11.1.0

Автономная фабрика по написанию кода для **Kimi Code CLI** (0.34+, Node).

Принимает бизнес-задачу от нетехнического пользователя, анализирует проект, планирует
изменения, уточняет только бизнес-логику, согласует план, реализует код и гоняет
интеграционные / регрессионные / бизнес-тесты с автоматическим откатом при неудаче, проводит
обязательное code review перед приёмкой и проверяет критерии приёмки.

Поддерживает **любые языки** и **любые типы проектов** (фронтенд, бэкенд, CLI, библиотека,
green-field) — стек определяется автоматически.

## Возможности

- **Работа из терминала** Kimi Code CLI: `/skill:code-factory`
- **Два режима**: `hitl` (уточняет бизнес-вопросы, план на согласование) и `auto` (полный автомат)
- **Два типа задач**: `implement` (написать/изменить код) и `review` (code review всего кода)
- **Обязательный code-review gate** перед приёмкой (сабагент `factory-code-reviewer`)
- **Детерминированная маршрутизация ошибок** (~90% без LLM) + **Diagnostician** (LLM-fallback) + Human → FAILED (никогда не падает молча)
- **Откат при неудаче** любого теста (бэкапы + манифест + git)
- **Checkpoint / resume** — продолжает с места сбоя
- **Git-native**: `git init` при отсутствии репозитория, feature-ветка на задачу, `commit_exclude`
- **Настраиваемые модели** для ролей — `model_preference` в `.md`-сабагентах + `config.toml`
- **Автоотчёты**: `report.md` (история прогона) + `report_code_changes.md` (diff «было→стало»)

## Структура

```
├── .agents/
│   ├── README.md                    # полная инструкция по фабрике
│   ├── skills/code-factory/         # flow skill (SKILL.md) + references + scripts
│   ├── agents/                      # главный агент + сабагенты (.md)
│   └── assets/task-template.yaml    # шаблон бизнес-задачи
├── AGENTS.md                        # контекст для агентов Kimi
├── CHANGELOG.md                     # история версий (SemVer)
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
# в чате: /skill:code-factory
```

Или сразу с готовой задачей:

```bash
kimi --agent-file .agents/agents/code-factory.md "Прочитай task.yaml и реши задачу"
```

Полный автомат: `kimi --auto` → `/skill:code-factory`.

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
task_type: implement         # implement (по умолчанию) | review
acceptance_criteria:
  - "Стратегия генерирует не менее 5 сигналов LONG/SHORT для CNY"
```

Полное описание всех полей — в комментариях самого `.example.task.yaml`.

## Модели

Модели задаются в `~/.kimi-code/config.toml` (`default_model` + `[secondary_model]`),
сабагентам — `model_preference: primary|secondary` в `.md`-файлах. Для разделения моделей
сабагентов обязателен `export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`.

Переменную нужно экспортировать в **том же терминале**, где запускается `kimi`, и **до** его
запуска. Если `kimi` запущен из нового терминала, лаунчера или через `sudo`, переменная
теряется и фабрика увидит `unset` — это особенность окружения запуска, а не ошибка фабрики.

Рекомендуемое соответствие: primary (рассуждающие) — main/planner, analyzer, diagnostician,
reviewer; secondary (быстрые) — coder, tester.

## Кэширование промптов (DeepSeek)

Промпты собираются по принципу append-only, чтобы автоматический context-cache DeepSeek
переиспользовал префикс: статичные блоки (системный промпт сабагента, контекст файлов проекта)
всегда в начале, динамические данные (история ходов, логи ошибок) — строго в конце. Любое
изменение начала или середины промпта сбрасывает кэш.

## Версия

Версия — по [Semantic Versioning](https://semver.org/). История изменений — в
[`CHANGELOG.md`](./CHANGELOG.md). Текущая версия: **11.1.0**.

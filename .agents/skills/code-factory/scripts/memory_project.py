#!/usr/bin/env python3
"""
Project-scoped long-term memory helper for the Code Factory (stdlib only, zero LLM tokens).

`memory/` is the durable memory of ONE target project — the project named by the
`repo_path` field of the task, NOT the factory itself. These subcommands make that
ownership explicit and machine-checkable:

  name  --repo <path>            print the project name = basename of the resolved path.
  init  --repo <deploy_root>     create memory/change-log.md and memory/summary.md from the
                                 canonical templates, but ONLY if they are missing; existing
                                 files are never overwritten or modified, not even partially.
  check --repo <deploy_root>     verify that memory belongs to exactly one project: the
                                 `project:` values of the journal records must agree with
                                 each other and with the declaration in memory/summary.md
                                 (optionally --expect <name>).

The templates carry the canonical markers required by scripts/check_factory_model.py and
declare `project: <name>`; `check` falls back to that declaration while the journal has no
records yet, so a fresh memory is never mistaken for a legacy one. `<name>` defaults to the
basename of the resolved deploy root; `init --project <name>` overrides it, e.g. when the
task's `repo_path` points to a SUBDIRECTORY of the deploy root — memory/ still lives in the
deploy root, but the project is named after that subdirectory.

Exit codes: 0 = OK, 1 = FAIL (memory mixes projects, or belongs to an unexpected project).
This script imports nothing from the factory: it runs from anywhere.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

CHANGE_LOG_MARKER = "<!-- code-factory-memory: change-log -->"
SUMMARY_MARKER = "<!-- code-factory-memory: summary -->"
ENTRY_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}")
# Top-level `key: value` field; lines starting with indentation (unfinished items) never match.
FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")

LEGACY_NO_PROJECT = "(legacy, no project field)"


def project_name(repo: str | pathlib.Path) -> str:
    """Return the project name: basename of the resolved path."""
    return pathlib.Path(repo).resolve().name


def change_log_template(project: str) -> str:
    """Canonical `memory/change-log.md` skeleton (append-only journal, no entries yet)."""
    return f"""# Change Log — {project}

{CHANGE_LOG_MARKER}

Append-only журнал прогонов фабрики по проекту `{project}`. Одна запись на завершённую
задачу (успех ИЛИ FAILED), пишет единственный писатель — главный агент в конце задачи.
Записи не удаляются и не переупорядочиваются; при превышении порога (50 записей) старые
сворачиваются в `memory/summary.md`, здесь остаётся последние 20 записей.

Память принадлежит ОДНОМУ проекту — тому, что указан в поле `repo_path` задачи. Поле
`project:` = basename каталога `repo_path` (для этого журнала — `{project}`). Разные
значения `project:` в одном журнале — ошибка; записи без поля `project:` — legacy
(предупреждение, не ошибка). Проверка: `scripts/memory_project.py check` и
`scripts/check_factory_model.py --memory-only`.

Формат записи (плоский, проверяется `scripts/check_factory_model.py`):

```
## <ISO timestamp> — <title>
title: <строка>
project: <имя проекта — basename(repo_path задачи), здесь всегда {project}>
timestamp: <ISO8601 дата>
branch: <ветка или "(none)">
commit: <sha или "(none)">
task_type: implement | review | refactor | security_audit
goal: <краткая цель>
changed_files: <список через "; ">
created_files: <список через "; ">
results: integration=<PASS|FAIL|SKIP>; regression=<...>; business=<...>; review=<approve|request_changes|SKIP>
decisions: <принятые решения>
assumptions: <допущения>
models_used: analyzer=<модель>; coder=<модель>; tester=<модель>; reviewer=<модель>
factory_version: <X.Y.Z — версия фабрики на момент прогона>
unfinished: нет незавершённых элементов
```

Однострочный пример записи (одна запись — один блок, поля построчно):
`title: Короткий заголовок | project: {project} | timestamp: 2026-01-01T00:00:00+0300 | task_type: implement | ...`

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

Секция `unfinished` заполняется обязательно при каждой записи, даже если пуста (явный маркер
`нет незавершённых элементов`). При компакции элементы с severity=critical или follow_up=true
сохраняются обязательно. Записи без `project`, `unfinished` или `factory_version` проходят
валидацию с предупреждением (не ошибкой) — это legacy-совместимость.
"""


def summary_template(project: str, repo_path: str) -> str:
    """Canonical `memory/summary.md` skeleton (declares the owning project + empty sections)."""
    return f"""# Project Summary — {project}

{SUMMARY_MARKER}
project: {project}
repo_path: {repo_path}

Сжатая сводка проекта. Сворачивается из старых записей `memory/change-log.md` при компакции
(порог 50 записей) и читается в начале каждой задачи, чтобы не выводить историю проекта заново.

## Current state

## Key decisions

## Recent history
"""


def cmd_name(args: argparse.Namespace) -> int:
    print(project_name(args.repo))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo).resolve()
    project = args.project or root.name
    memdir = root / "memory"
    memdir.mkdir(parents=True, exist_ok=True)
    templates = {
        "change-log.md": change_log_template(project),
        "summary.md": summary_template(project, args.repo),
    }
    for name, text in templates.items():
        path = memdir / name
        if path.is_file():
            print(f"exists: {path}")
            continue
        path.write_text(text, encoding="utf-8")
        print(f"created: {path}")
    return 0


def journal_projects(change_log: pathlib.Path) -> list[str]:
    """Return the distinct non-empty top-level `project:` values of all journal entries."""
    found: list[str] = []
    in_entry = False
    for line in change_log.read_text(encoding="utf-8").splitlines():
        if ENTRY_RE.match(line):
            in_entry = True
            continue
        if not in_entry:
            continue
        m = FIELD_RE.match(line)
        if m and m.group(1) == "project":
            value = m.group(2).strip()
            if value and value not in found:
                found.append(value)
    return found


def entry_count(change_log: pathlib.Path) -> int:
    """Number of journal entries (lines starting a dated `## <timestamp>` record)."""
    return sum(1 for line in change_log.read_text(encoding="utf-8").splitlines()
               if ENTRY_RE.match(line))


def summary_project(summary: pathlib.Path) -> str:
    """Return the `project:` declared by memory/summary.md ("" when it declares none).

    Only the declaration area counts — right after the canonical marker and before the first
    `## ` section — so a `project: <name>` example inside a fenced code block is never mistaken
    for a declaration (same rule as scripts/check_factory_model.py).
    """
    if not summary.is_file():
        return ""
    lines = summary.read_text(encoding="utf-8").splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if SUMMARY_MARKER in ln), None)
    if start is None:
        return ""
    for line in lines[start:]:
        if line.startswith("## "):
            break
        m = FIELD_RE.match(line)
        if m and m.group(1) == "project":
            return m.group(2).strip()
    return ""


def cmd_check(args: argparse.Namespace) -> int:
    memdir = pathlib.Path(args.repo).resolve() / "memory"
    change_log = memdir / "change-log.md"
    if not change_log.is_file():
        print("note: memory/change-log.md not found (fresh project)")
        return 0

    projects = journal_projects(change_log)
    if len(projects) > 1:
        print("FAIL - memory mixes projects: " + ", ".join(sorted(projects)), file=sys.stderr)
        return 1

    journal_owner = projects[0] if projects else ""
    declared = summary_project(memdir / "summary.md")
    if journal_owner and declared and journal_owner != declared:
        print(f"FAIL - memory/summary.md declares project '{declared}' but the journal "
              f"belongs to '{journal_owner}'", file=sys.stderr)
        return 1

    # Owner = the journal's own value; while the journal has no records yet, the declaration
    # in summary.md is authoritative (otherwise a fresh memory would look like a legacy one).
    owner = journal_owner or declared
    if args.expect and owner and owner != args.expect:
        print(f"FAIL - memory belongs to project '{owner}', expected '{args.expect}'",
              file=sys.stderr)
        return 1

    print(f"ok - memory belongs to project '{owner or LEGACY_NO_PROJECT}' "
          f"({entry_count(change_log)} entries)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_name = sub.add_parser("name", help="print the project name (basename of the resolved path)")
    p_name.add_argument("--repo", required=True, help="Path to the target project")
    p_name.set_defaults(func=cmd_name)

    p_init = sub.add_parser("init", help="create memory files if they are missing (never overwrites)")
    p_init.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_init.add_argument("--project", default="",
                        help="Project name (default: basename of the resolved deploy root)")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="verify that memory belongs to a single project")
    p_check.add_argument("--repo", required=True, help="Deploy root that holds memory/")
    p_check.add_argument("--expect", default="", help="Expected project name")
    p_check.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

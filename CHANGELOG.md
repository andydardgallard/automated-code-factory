# Changelog

Все заметные изменения в проекте Autonomous Code Factory документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — на [Semantic Versioning](https://semver.org/lang/ru/).

## [12.11.0] — 2026-09-24

### Added
- **Явная классификация `git stash` в `action_gate.py`** — мутирующие формы
  (push/pop/apply/drop/clear, голый `git stash`) → CONFIRM с деловым объяснением риска гонки на
  общем рабочем дереве и отсылкой к правилу `no-shared-tree-git-mutations`; `stash list`/`show`
  → ALLOW; разбор опций как у git (`-m`/`--message` поглощают значение — мутирующий push не
  маскируется под чтение, кейс 17 `test_action_gate.py` с negative-control).
- **23-е правило rulebook `memory-actuality`** — в начале прогона открытый backlog сверяется с
  деревом (`memory_project.py backlog`), в конце каждый пункт закрывается блоком `closed:` с
  обязательным `evidence:` или остаётся в `unfinished` с причиной; пункт не может исчезнуть без
  доказательства закрытия; `summary.md` актуализируется каждым прогоном. Носители (5): `AGENTS.md`,
  `.agents/README.md`, `code-factory.md`, `SKILL.md`, `references/planning-guide.md`
  (`check_factory_rules.py` — 23 правила, 86 блоков, exit 0).
- **`memory_project.py backlog [--check] [--json]`** — детерминированный fold открытых
  follow_up=true/severity=critical по всей истории журнала; `--check` → exit 1 при открытых
  пунктах, закрытии без `evidence:` и закрытии несуществующего пункта; WARN при расхождении версии
  в `## Current state` с VERSION. Протокол `closed:` в формате записи; кейсы 17–23
  `test_memory_project.py`.
- **Project-learned patterns — документированный overlay** в `error_router.py`: битый
  авто-найденный `.code-factory/state/error-patterns.json` деградирует до default с деловым
  stderr-предупреждением (маскировка невозможна), явный `--project-patterns` остаётся exit 2;
  справочник `error-routing.md` §1.2; кейсы 9a/9b `test_error_router.py`.
- **`providers.md` §5.2** — второй планировщик комитета (plan-committee) — единственная роль, где
  матрица `models` задачи не применяется: контрастное семейство обязательно.

### Changed
- **Контентный fingerprint видит unstaged-правки** — хэш считается по содержимому рабочего дерева
  отслеживаемых файлов (CRLF→LF-нормализация, недоступный файл → запись индекса); unstaged-правка
  двигает хэш и валит `check_factory_model.py` (intended); вне хэша остаются только
  untracked-файлы (`worktree_dirty` → `untracked_files`, stderr-заметка + WARNING). Кейс 29
  `test_factory_model.py` переписан строго строже; одноразовая регенерация встроенных
  fingerprint'ов AGENTS.md у развёрнутых проектов — ожидаемое следствие.

### Fixed
- **`prepare_factory.ps1`** — fallback копирования `Get-ChildItem | Copy-Item` обёрнут в
  try/catch (`-ErrorAction Stop`, `$script:HardError`): при жёстком сбое — одна деловая строка
  вместо сырых записей PowerShell (CategoryInfo/FullyQualifiedErrorId); контракт (exit 1, без
  баннера «Готово») подтверждён живым ACL-deny воспроизведением.
- **`prepare_factory.sh`** — при сбое `memory_project.py init` в предупреждение попадает короткая
  причина (последняя непустая строка) вместо первой строки traceback.
- **`.gitattributes`** — пин `*.sh text eol=lf` (`.cmd`/`.ps1` уже были покрыты): окончания строк
  shell-скриптов не зависят от `core.autocrlf`.
- **`references/planning-guide.md`** — «init --repo \<project root\>» → «--repo \<deployment root\>»
  (канон memory-ownership).

## [12.10.2] — 2026-09-23

### Fixed
- **`action_gate.py --help` больше не падает на cp1251-консоли** — модульный docstring содержит `→`
  (U+2192), которого нет в cp1251, и `description=__doc__` уводил `print_help()` в
  UnicodeEncodeError с traceback. Добавлен эталонный `use_utf8_output()` (как в
  `gen_code_changes_report.py`), вызываемый первой строкой `main()`; контракт `--help` → exit 0,
  ошибки использования → exit 2 без traceback запинен кейсом 16 в `test_action_gate.py`
  (subprocess под `PYTHONIOENCODING=cp1251`, вакцинация — на pre-fix коде кейс падает).

### Added
- **UTF-8 guard во всех argparse-скриптах фабрики** — `use_utf8_output()` первой строкой `main()`
  в 22 `scripts/*.py` (в `log_tail.py`/`precedent_index.py` прежний слабый guard стоял после
  `parse_args()` и не защищал `--help` — перемещён; в `error_router.py`/`plan_arbiter.py` —
  усилен до stdout+stderr). cp1251/cp866 sweep `--help`: 24/24 exit 0 без traceback.
- **22-е правило rulebook `no-shared-tree-git-mutations`** — сабагенты не выполняют
  `git stash`/`git reset`/`git checkout`/`git clean` на общем рабочем дереве прогона (риск гонки с
  главным агентом и другими сабагентами); базовая версия файла — через `git show HEAD:<file>` или
  temp-клон. Byte-identical носители: `AGENTS.md`, `.agents/README.md`, `code-factory.md`,
  `SKILL.md`, `references/handoff-briefing.md`, `sub-agents/coder.md`; сверка —
  `check_factory_rules.py` (22 правила, 81 блок, exit 0).

## [12.10.1] — 2026-09-23

### Added
- **`test_gen_code_changes_report.py`** — self-тест генератора `report_code_changes.md`: `--help` и
  ошибки использования на cp1251/cp866-консоли, happy-path во временном git-репозитории. Набор
  self-тестов — 26 (25 существующих без ослабления).
- **Предупреждение о dirty-дереве** (`project_fingerprint.py`, `check_factory_model.py`): контентный
  хэш по-прежнему читает git-индекс (решение сохранено — индекс commit-стабилен и платформенно
  нейтрален, а AGENTS.md может встроить пару своих хэшей), но слепое пятно больше не молчит:
  `--content`/`--all` печатают stderr-заметку, а проверка модели — предупреждение о N
  unstaged/untracked правках, которых индекс не видит. Хэши и exit-коды не меняются.
- **`.gitattributes`: `*.cmd`/`*.ps1` → `text eol=crlf`** — Windows-лаунчеры (`prepare_factory.cmd`,
  `prepare_factory.ps1`, `start.cmd`) получают CRLF при checkout независимо от `core.autocrlf`;
  блобы остаются LF, ренормализация не требуется. Анти-регрессионная проверка обеих строк добавлена
  в `test_windows_scripts.py`.

### Changed
- **`action_gate.py`: новый exit code 3** (инфраструктурная ошибка журнала) — незаписываемый журнал
  (OSError) печатает классификацию на stdout, `error: cannot write the action-gate journal …` на
  stderr и завершает работу кодом 3 вместо traceback; коды решений 0/1/2 не изменены, молчаливого
  ALLOW по-прежнему нет.
- **Калибровка ревьюера (§7)**: правило про нейтральный ре-нейминг уточнено —
  `references/code-review.md` §3 и `sub-agents/code-reviewer.md` требуют молчания (не nit) при
  равно ясных именах. После правки промпта ревьюер перекалиброван: accuracy 7/7, macro precision
  1.000 (было 0.857), recall 1.000 (`logs/reviewer-calibration.md`).
- **Golden set закоммичен**: 7 кейсов калибровки ревьюера в `skill-base/golden-set/` стали частью
  репозитория (ранее каталог исключался как фикстура через `commit_exclude`) — свежий клон
  воспроизводит калибровку без восстановления из соседнего развёртывания. В FTS5-индекс прецедентов
  кейсы по-прежнему не попадают.
- **Гигиена документации**: устаревшие советы `--memory-only` для корня фабрики убраны из
  `references/tech-stack-detection.md` и шаблона журнала `memory_project.py` — авто-детект корня
  (3 сигнала) делает `SKIP` сам, сам флаг сохранён как живой CLI-контракт. `AGENTS.md`,
  `.agents/README.md` и `references/tech-stack-detection.md` описывают dirty-worktree warning и
  актуальные метрики калибровки.

### Fixed
- **`gen_code_changes_report.py`: `--help` без traceback** — `main()` переводит stdout/stderr в
  UTF-8 (`reconfigure(encoding="utf-8", errors="replace")` под try/except), поэтому не-ASCII
  help-текст (`→`, кириллица) больше не падает `UnicodeEncodeError` на консоли с cp1251/cp866;
  контракт argparse сохранён: `--help` → exit 0, ошибка использования → exit 2, сообщение без
  traceback.

## [12.10.0] — 2026-09-23

### Added
- **Committee при двойном rejection плана** (hitl): первое отклонение плана возвращает его на
  доработку, второе запускает второго независимого planner-сабагента (`sub-agents/planner.md`,
  контрастное семейство моделей, отклонённый план он не видит), а `scripts/plan_arbiter.py`
  детерминированно сливает оба плана по машиночитаемым секциям (`## Tasks (DAG)`, `## Risks`,
  `## Business tests`) и печатает список расхождений; пользователю предъявляется merged-план,
  дальнейшие правки идут по нему, комитет срабатывает не более одного раза на задачу. Новое
  правило `plan-committee` в `references/factory-rules.md` и его носители (SKILL.md,
  code-factory.md, AGENTS.md, planning-guide.md) — правило сверяет `check_factory_rules.py`.
- **`plan_arbiter.py`** (stdlib): слияние задач по id — одинаковое тело схлопывается, одинаковый id
  с разным телом уходит в `## Расхождения` и НЕ попадает в merged-список; риски и бизнес-тесты
  объединяются дедуплицированным объединением. Контрактные ошибки (нет секции `## Tasks (DAG)`,
  пустой список задач, строка задачи без `verification:`, один id дважды в ОДНОМ плане, нечитаемый
  файл, незаписываемый `--out`) — exit 2 с сообщением и без traceback.
- **`precedent_index.py`** (stdlib sqlite3): FTS5-индекс прецедентов `build`/`query` — память
  проекта (`memory/change-log.md`, `memory/summary.md`) плюс кодовая база (`git ls-files`, fallback —
  обход `repo_inventory.py`; симлинки и бинарные/слишком большие файлы пропускаются) в
  `.code-factory/state/precedents.db`; детерминированный rebuild, поиск «как это решали раньше»
  вместо повторного чтения истории. Подключён к analyzer и diagnostician.
- **Авто-детект hand-authored корня фабрики** в `check_factory_model.py`: три сигнала вместе — в
  первой строке `AGENTS.md` НЕТ маркера `code-factory-fingerprint`, но ЕСТЬ собственный маркер
  фабрики `code-factory-version`, и рядом развёрнут `.agents/skills/code-factory/SKILL.md` → проверки
  AGENTS.md дают `SKIP` с пояснением (память и WIP-фиксатор проверяются как обычно), поэтому корень
  фабрики проходит без `--memory-only`. У целевого проекта AGENTS.md без fingerprint остаётся
  ошибкой, а устаревший fingerprint — ошибкой даже в корне фабрики.

### Changed
- **Граница severity в code review** (`references/code-review.md` §3): critical — дефект или
  ослабление СУЩЕСТВУЮЩЕГО поведения (crash/bug на существующем пути, порча данных, безопасность,
  ослабленная проверка), major — незащищённый НОВЫЙ путь или потерянное покрытие без замены; добавлены
  примеры на границе и Reporting discipline (одна первопричина — одно finding, taste-замечания не
  заявляются). `references/code-review.md` §7 делает калибровку периодической: обязательна после
  каждой правки промпта ревьюера и не реже одного раза на 5 прогонов ревью, мягкие пороги — verdict
  accuracy 100% и macro precision ≥ 0.8. Повторная калибровка на golden-set: verdict accuracy 7/7
  (100%), macro precision 0.619 → 0.857, recall 0.857 → 1.000 (`logs/reviewer-calibration.md`).
- Документация затронутого поведения: `AGENTS.md`, `.agents/README.md`, `SKILL.md`,
  `code-factory.md`, `references/planning-guide.md`, `code-reviewer.md`, `analyzer.md`,
  `diagnostician.md` описывают committee, индекс прецедентов, границу severity и SKIP-режим корня
  фабрики.

### Fixed
- `test_run_id.py` пиннит закоммиченный fixture `assets/task-template.yaml` (digest `4b918a06`)
  вместо эфемерного `.code-factory/state/task.yaml`: алгоритм доказан против реального файла задачи,
  и пин не «гниёт» на следующем прогоне — дата проверяется только форматом `YYYYMMDD-`.

## [12.9.1] — 2026-09-23

## [12.9.0] — 2026-09-23

## [12.8.0] — 2026-09-24

### Added
- **Shard-протокол whole-repo операций** (review, security_audit): `repo_inventory.py`
  (детерминированный inventory + нарезка на шарды ≤ N тысяч строк, дефолт 20k) → параллельные
  reviewer/auditor сабагенты по шардам → `merge_findings.py` (дедупликация по
  (file,line,title), сортировка по severity, merged verdict). Закрывает переполнение контекста
  на проектах 100k+ строк.
- **Двухуровневый fingerprint проекта**: структурный (commit-стабильный) + контентный
  (`git ls-files -s`, fallback — хэш дерева без git); AGENTS.md встраивает оба хэша, SKIP
  регенерации — только при совпадении обоих; `check_factory_model.py` валидирует оба
  (legacy однохэшевый формат — warning).
- **Think in Code**: `log_tail.py` (счётчики + tail длинных логов), `repo_stats.py`
  (sizes/entry-points/imports); правила для analyzer/tester/diagnostician — скрипт вместо
  чтения ради подсчёта, длинный вывод тестов в `.code-factory/logs/`, в контекст — выжимка.
- **Верифицируемая приёмка (anti-tautology)**: `verify_acceptance.py` — acceptance_criteria
  поддерживают `verify: <команда>`; acceptance.md заполняется по факту запуска (exit code +
  выдержка); критерии без verify помечаются derived/unverified; деградированный baseline →
  вердикт DEGRADED.
- **Evidence ledger FRESH/STALE**: `evidence_ledger.py` — результаты тестов/приёмки подписаны
  fingerprint'ом затронутых файлов; ревьюер и приёмка принимают evidence только FRESH.
- **Антигаллюцинационные цитаты**: `verify_quotes.py` — цитаты Diagnostician/ревьюера/Advisor
  проверяются как точные подстроки источника; несовпадение → «недоверенный» + fallback на
  полный лог.
- **Сабагент `factory-advisor`** (secondary, no-edits): эскалация после Diagnostician;
  лестница regex → Diagnostician → Advisor → Human → FAILED, бюджет advisor=1 per root cause;
  машиночитаемое поле `agreement: agree|disagree`.
- **Handoff-шаблон брифинга** `references/handoff-briefing.md` (Task/Context/Relevant files/
  Current state/What was tried/Decisions/Acceptance criteria/Constraints) + контракт concise
  output; файлы — путями, не вставками.
- **Инфраструктурные скрипты**: `factory_preflight.py` (проба окружения → capabilities),
  `action_gate.py` (детерминированный гейт деструктивных действий: HARD_DENY/CONFIRM/ALLOW +
  журнал), `task_graph.py` (дисковый граф state/tasks/*.json, валидация циклов, sha256).
- **Память**: enforced owner = basename(repo_path) в `memory_project.py check`; команды
  `rename` (миграция владельца), `compact-check` (сохранность critical/follow_up при
  компакции), `validate-fix-tasks` (валидатор схемы fix-tasks.yaml).
- **Model diversity generator≠judge** в providers.md + «trajectory is the truth» в чек-листе
  ревьюера; модель передаётся в Agent tool явно по матрице `models` задачи (правило «не
  передавать» устарело).

### Changed
- **Единый канонический review-гейт** в 5 документах (references/code-review.md,
  code-factory.md, SKILL.md, AGENTS.md, .agents/README.md): приёмка запрещена при открытых
  critical findings; auto-exhaustion = conditional pass с `unverified_review` в acceptance.md
  и unresolved findings в report.md; консистентность проверяется `test_review_gate.py`.

### Fixed
- nit-фиксы code-review 2026-09-23: encoding="utf-8" в gen_code_changes_report.py (+парсинг
  quoted/octal путей), newline="" в version_manager.py, list.index при дублях в
  validate_documentation.py, git init fallback для git<2.28 и точное сравнение паттернов
  .gitignore в prepare_factory.sh/.ps1, prepare_factory.sh в IGNORE_TOP_LEVEL fingerprint,
  нечитаемые файлы не рушат repo_inventory.py, дерево скриптов в .agents/README.md,
  дрейфы verification-strategy §6.1 и reference-docs record.

## [12.7.0] — 2026-09-21

### Added
- **Развёртывание и запуск фабрики в Windows без Git Bash**: `prepare_factory.cmd` (двойной клик
  в Проводнике / `cmd` / PowerShell) вызывает `prepare_factory.ps1` и возвращает его код выхода.
  PowerShell-деплойер повторяет шаги bash-версии 1:1: поиск рабочего Python с пробным запуском
  (`py -3` → `py` → `python` → `python3`, заглушка Microsoft Store не побеждает), `git init -b main`,
  копирование `.agents/`, создание/проверка памяти проекта (никогда не перезаписывается),
  `start.sh` (LF) + `start.cmd` (CRLF), те же 9 правил `.gitignore`, тот же отчёт готовности.
  Без Python развёртывание всё равно завершается успешно (шаг памяти деградирует с понятным текстом).
- **`start.cmd`** — Windows-launcher: выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`,
  проверяет наличие `kimi`, передаёт аргументы и код возврата; Git Bash не нужен.
- **Самотест `scripts/test_windows_scripts.py`**: контракты Windows-скриптов (BOM/CRLF, `chcp 65001`,
  передача аргументов и кода возврата, совпадение inline-шаблона `start.cmd` с файлом, реальное
  развёртывание с пробелом и с кириллицей в пути, идемпотентность памяти). В проекте, развёрнутом
  фабрикой, тест аккуратно пропускается (SKIP, exit 0) вместо ложного падения.

### Fixed
- `prepare_factory.ps1` больше не выдаёт жёсткий сбой за успех: сбой копирования `.agents/` или
  записи `start.sh`/`start.cmd`/`.gitignore` → `exit 1` и «Развёртывание не завершено» без баннера
  «Готово». Ожидаемые деградации остались нефатальными (нет Python → `не проверено (нет python)`, exit 0).
- `prepare_factory.ps1` выставляет `PYTHONUTF8=1` для своих вызовов python: кириллица в пути больше
  не превращается в мусор и не даёт ложное «память не создана».
- `prepare_factory.ps1` предупреждает с именем файла, прежде чем заменить существующий
  пользовательский `start.cmd`.

## [12.6.0] — 2026-09-21

### Added
- **Признак принадлежности памяти проекту**: запись журнала несёт обязательное для новых
  записей поле `project: <имя проекта>` (= basename разрешённого `repo_path`), а
  `memory/summary.md` объявляет `project:` и `repo_path:`. Память `memory/` описывает
  ЦЕЛЕВОЙ проект фабрики, а не саму фабрику.
- **Обнаружение смешения проектов**: `check_factory_model.py` считает записи с разными
  значениями `project:` в одной памяти ошибкой (пустое значение `project:` — тоже ошибка),
  а отсутствие объявления проекта в сводке — предупреждением.
- **Скрипт `memory_project.py`** (только stdlib): `name` (имя проекта), `init` (создать
  память проекта из шаблонов, только если её нет), `check` (проверить принадлежность и
  смешение), с self-тестом `test_memory_project.py`.
- **Память заводится при развёртывании**: `prepare_factory.sh` создаёт `memory/` с именем
  проекта, если её нет, НИКОГДА не перезаписывает существующую и предупреждает, если память
  объявлена за другой проект (`ПРОВЕРИТЬ ✗`) или смешивает проекты (`НЕСОГЛАСОВАНА ✗`).

### Changed
- Документация и инструкции (`AGENTS.md`, `README.md`, `.agents/README.md`, `SKILL.md`,
  справочники, главный агент и сабагенты) описывают `memory/` как память целевого проекта,
  создаваемую в корне развёртывания, и правило «одна память — один проект».
- Legacy-записи без `project:` остаются совместимыми: предупреждение, не ошибка.

## [12.5.1] — 2026-09-08

### Fixed
- **Защита от утечки API-ключей**: `.gitignore` теперь игнорирует `.env`, `.env.*`, `*.env`,
  `*.pem`, `*.key`; `prepare_factory.sh` добавляет те же паттерны в автодобавляемый блок
  `.gitignore` новых проектов.

## [12.5.0] — 2026-09-08

### Added
- **Сабагент документирования `factory-documenter`**: после каждого успешного
  implement/refactor-прогона обновляет документацию изменённых файлов (только doc-комментарии
  и `.md`, никогда код/тесты/конфиги). Встроенный валидатор `validate_documentation.py`
  (бюджет 1 retry); при исчерпании документационный долг фиксируется в отчёте, фабрика
  продолжает. Использует secondary-модель; не вызывается для review/security_audit.
- **Память «что НЕ реализовано»**: секция `unfinished` в записях журнала (item/reason/
  severity/follow_up) + поле `factory_version`. Главный агент заполняет секцию обязательно,
  даже если она пуста; компакция сохраняет critical/follow_up элементы; legacy-записи
  проходят валидацию с предупреждением.
- **Справочники-навыки `reference_docs`/`reference_skills`**: персистентная база `skill-base/`
  (SHA256-актуальность, переиспользование, инкрементальное обновление), сабагент
  `factory-skill-manager`, скрипт `skill_base.py`, детерминированная матрица релевантности для
  8 сабагентов, динамический (append-only) контекст.
- **Сквозное версионирование**: `VERSION` — единый источник истины; скрипт `version_manager.py`
  (get/bump/sync/validate/set/suggest, stdlib only); детерминированная матрица типов
  (major/minor/patch/none), валидация ревьюером (с правом переопределения с объяснением);
  синхронизация версии в README/CHANGELOG/AGENTS.md/SKILL.md/инструкцию; коммит с префиксом
  `v<версия>: `.

### Changed
- `check_factory_model.py` валидирует секцию `unfinished` и поле `factory_version` (legacy —
  предупреждение, не ошибка); self-тест расширен (12+ кейсов).
- Сабагенты `code-reviewer` валидируют предложенный матрицей тип версии.

## [12.1.0] — 2026-09-01

### Added
- **AGENTS.md как единый источник правды**: фабрика сама генерирует `AGENTS.md` проекта с ровно
  8 секциями `##` и встраивает детерминированный fingerprint структурных сигналов
  (`scripts/project_fingerprint.py`). При совпадении fingerprint анализ/Scout пропускается, при
  расхождении AGENTS.md перегенерируется; обновление в двух точках (начало/конец задачи).
- **Переносимая долгосрочная память `memory/`** (коммитимая, не игнорируется): `change-log.md`
  (append-only журнал, одна запись на прогон; единственный писатель — главный агент) и
  `summary.md` (сводка). Компакция журнала в сводку по порогу 50 записей.
- **Скрипты проверки модели**: `scripts/check_factory_model.py` (детерминированная проверка
  «8 секций + fingerprint + формат журнала») и `scripts/test_factory_model.py` (self-тест).

### Changed
- Сабагенты `analyzer`, `coder`, `tester`, `code-reviewer`, `diagnostician` читают `AGENTS.md` и
  `memory/` как источник правды, а не выводят структуру проекта заново.

### Removed
- Вызов `/init` из Scout-потока полностью удалён — фабрика генерирует `AGENTS.md` сама, без
  отдельного init-шага.

## [12.0.0] — 2026-08-29

### Added
- **User story**: поле `user_story` в шаблоне задачи; обязательный анализ и использование
  контекста пользователя агентами фабрики на этапах анализа, планирования и реализации.
- **Тип задачи `refactor`**: выделенный поток со специализированным сабагентом
  `factory-refactorer` и справочником `references/refactoring.md`. Ключевое требование —
  «заморозка» функциональности: успех = структурное улучшение при 100% прохождении
  существующих тестов без изменений; любое изменение поведения — критическая ошибка и автооткат.
- **Тип задачи `security_audit`**: универсальный адаптивный полный аудит кибербезопасности
  (`references/security-audit.md` + сабагент `factory-security-auditor`, read-only).
  Автоматическое определение типов артефактов (код, IaC, контейнеры, сеть, секреты,
  зависимости), автономный выбор инструментов, отчёты + сгенерированный файл задач на
  исправление. Фабрика НЕ чинит уязвимости сама.
- **Провайдеры Kimi (K3) и Qwen**: `references/providers.md` — маршрутизация моделей через поле
  `models` задачи, корректная аутентификация/формат запросов, аддитивная интеграция без поломки
  существующих провайдеров. Ошибки провайдеров интегрированы в детерминированную маршрутизацию
  (`references/error-routing.md` §1.1).
- **Запуск одним действием**: `prepare_factory.sh` генерирует launcher `start.sh` в целевом
  проекте (автоматически выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`) и обновляет
  `.agents/` целиком (фабрика — source of truth).

### Removed
- **BREAKING**: поле `priority` полностью удалено из шаблонов, документации, инструкций агентов
  и логики. Все задачи по умолчанию обрабатываются с наивысшим приоритетом (`high`),
  приоритизацией фабрика не занимается.

## [11.1.0] — 2026-08-23

### Added
- `prepare_factory.sh`: при развёртывании фабрики добавляет `.agents/` в `.gitignore` целевого
  проекта (не ломая чтение/запись данных фабрики — `.gitignore` влияет только на git-трекинг).
- Блок «Лестница Ленивого Сеньора» (Ponytail) в `code-factory.md` и `coder.md`: обязательная
  лестница решений перед генерацией кода + фиксация выбора в `<thinking>`.
- Скрипты `scripts/test_prompt_structure.py` и `scripts/test_env_propagation.sh` — детерминированные
  проверки append-only структуры промптов и проброски env-переменной.

### Changed
- Документировано правило append-only сборки промптов (для автоматического кэша DeepSeek).
- Документирована причина потери `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL` и требование
  экспортировать его в том же терминале до запуска `kimi`.

## [11.0.0] — 2026-08-12

### Added
- Сабагент `factory-code-reviewer` (read-only, `model_preference: primary`) и справочник
  `references/code-review.md`: статический quality gate перед приёмкой.
- Поле `task_type: implement | review` в шаблоне задачи.
- Правило code-review gate: обычная задача ревьюит diff, `task_type: review` — весь код в начале;
  задача не принимается при открытом вердикте `request_changes`; бюджет ревью = 2 итерации.

### Removed
- **BREAKING**: поддержка Kimi CLI 1.12 и Kimi Agents SDK — удалены `code-factory.yaml`,
  `system.md`, `models.yaml`, `sub-agents/*.yaml`, `examples/`. Модели теперь задаются только
  через `model_preference` в `.md`-сабагентах + `config.toml`.

## [10.2.0] — 2026-08-12

### Added
- Pre-flight проверка `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`: при отсутствии флага
  фабрика пишет `models_warning` в `pipeline.yaml`/`report.md`.

### Fixed
- `factory-analyzer` переведён на `model_preference: primary` (deepseek-v4-pro).
- Инструкции моделей: сабагентам больше не передаётся `model=` в Agent tool (не поддерживается
  в новой CLI) — модели задаются `model_preference` + `config.toml`.

## [10.1.0] — 2026-08-12

### Added
- Markdown-агенты для Kimi Code 0.34+: `code-factory.md` и сабагенты
  `analyzer|coder|tester|diagnostician.md` (frontmatter: name, description, tools,
  `model_preference`).
- Документация secondary-модели (`[secondary_model]` в `config.toml`).

### Changed
- `task.yaml` с личными данными заменён на `.example.task.yaml` (шаблон без секретов).
- Уточнена команда `/init` в `SKILL.md`/`system.md`: это slash-команда
  (`kimi -p /init --print --yolo -w <project>`), а не CLI subcommand.

## [10.0.0] — 2026-08-11

### Added
- Первая версия Autonomous Code Factory (flow skill `code-factory` + agents + SDK):
  оркестратор `SKILL.md`, справочники (planning-guide, verification-strategy, error-routing,
  tech-stack-detection), сабагенты analyzer/coder/tester/diagnostician, `models.yaml`,
  `prepare_factory.sh`, генератор `report_code_changes.md`.

[12.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v12.0.0...v12.1.0
[12.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.1.0...v12.0.0
[11.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.0.0...v11.1.0
[11.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.2.0...v11.0.0
[10.2.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.1.0...v10.2.0
[10.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.0.0...v10.1.0
[10.0.0]: https://github.com/andydardgallard/automated-code-factory/releases/tag/v10.0.0

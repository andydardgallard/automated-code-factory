<!-- code-factory-version: 12.9.0 -->
# Project: Autonomous Code Factory

Этот проект содержит автономную фабрику по написанию кода для Kimi Code CLI.
Фабрика принимает бизнес-задачу от нетехнического пользователя, анализирует проект, планирует
изменения, уточняет только бизнес-логику, согласует план, реализует код и гоняет
интеграционные / регрессионные / бизнес-тесты с автоматическим откатом при неудаче, проводит
обязательное code review перед приёмкой.

## Структура

- `task.yaml` — пример бизнес-задачи (эталон формата)
- `.agents/skills/code-factory/` — flow skill фабрики (`SKILL.md`), справочники
  (`references/`: planning-guide, verification-strategy, error-routing, tech-stack-detection,
  code-review, providers, refactoring, security-audit, handoff-briefing — обязательный шаблон
  брифинга сабагентов; `factory-rules.md` — единый rulebook обязательных правил, носители которого
  сверяет `check_factory_rules.py`; `error-patterns.default.json` — машинный слепок таблиц
  error-routing для `error_router.py`) и шаблон задачи (`assets/`)
- `.agents/skills/code-factory/scripts/` — детерминированные stdlib-скрипты (0 токенов):
  `repo_inventory.py` (инвентарь + шарды ≤20k строк), `merge_findings.py` (слияние findings
  шардов + merged verdict), `verify_acceptance.py` (критерии с `verify` → acceptance.md),
  `verify_quotes.py` (дословность цитат), `evidence_ledger.py` (подписи FRESH/STALE),
  `factory_preflight.py` (проба окружения), `action_gate.py` (деструктивные действия),
  `task_graph.py` (граф задач на диске), `log_tail.py` (хвост длинного лога), `repo_stats.py`
  (анализы кодом), `project_fingerprint.py`, `memory_project.py`, `version_manager.py`,
  `check_factory_rules.py` (сверка rulebook с носителями: блоки `factory-rule` байт-в-байт),
  `run_id.py` (run_id прогона: `gen` по task.yaml / `check` — артефакты без run_id),
  `error_router.py` (JSON-first классификация ошибок: `classify`/`merge`),
  `calibrate_reviewer.py` (golden-set калибровка ревьюера: precision/recall/accuracy)
- `.agents/agents/` — главный агент фабрики (Markdown `code-factory.md`) и сабагенты
  (`sub-agents/analyzer|coder|tester|diagnostician|advisor|code-reviewer|refactorer|security-auditor|documenter|skill-manager.md`)
- `VERSION` — единый источник истины для версии фабрики (одна строка X.Y.Z)
- `skill-base/` — персистентная база навыков из `reference_docs`/`reference_skills` (опционально)
- `.agents/README.md` — полная инструкция по использованию фабрики
- `prepare_factory.sh` — подготовка проекта одним действием (создаёт launcher `start.sh`)
- `prepare_factory.cmd` / `prepare_factory.ps1` — то же самое в Windows без Git Bash (точка входа
  и реализация; создают launcher `start.cmd`), `start.cmd` — запуск фабрики в Windows
- `memory/` — переносимая долгосрочная память ЦЕЛЕВОГО проекта (коммитится); создаётся В КОРНЕ
  РАЗВЁРТЫВАНИЯ (том каталоге, который передан `prepare_factory.sh`; в Windows —
  `prepare_factory.cmd`), базовое имя проекта = basename этого каталога: `change-log.md`
  (append-only журнал прогонов) и `summary.md` (сжатая сводка); признак проекта — `project: <имя>`
  в записи и `project:`/`repo_path:` в сводке

## Как использовать

- Kimi Code 0.34+: `kimi`, затем `/skill:code-factory`; либо
  `kimi --agent-file .agents/agents/code-factory.md "задача"`
- Полный автомат: `kimi --auto` → `/skill:code-factory`
- **Одно действие**: `./prepare_factory.sh <проект>` затем `./<проект>/start.sh` (launcher сам
  выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`)
- **Одно действие в Windows**: `prepare_factory.cmd <проект>` затем `cd <проект>` и `start.cmd`
  (интерактивно; в чате `/skill:code-factory`) либо `start.cmd --auto` — Git Bash не нужен; для
  развёртывания Python не требуется (сама фабрика использует Python для скриптов памяти и версии)
- `mode: auto` в `task.yaml` управляет только бизнес-вопросами фабрики; запросы разрешения
  CLI отключаются отдельно — флагом `kimi --auto`/`--yolo` или `default_permission_mode`
  в `config.toml`.

## Соглашения

- Рантайм-состояние фабрики — `.code-factory/` внутри проекта (не коммитить):
  `state/` (задача, план, pipeline.yaml, acceptance.md, ledger доказательств, граф задач),
  `logs/` (baseline, ошибки, результаты, code-review, findings шардов),
  `backups/`, `manifest.json`.
- **AGENTS.md — единый источник правды**: фабрика генерирует его с ровно 8 секциями `##` и
  детерминированным ДВУХУРОВНЕВЫМ fingerprint в первой строке — структурный (манифесты стека,
  CI-конфиги, README, список каталогов) + контентный (SHA индексированных git-файлов) —
  `scripts/project_fingerprint.py --all`, маркер
  `<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->`. Перегенерирует при расхождении
  ЛЮБОГО из двух хэшей (начало задачи) или изменении структуры/стека/точек входа (конец задачи)
  и коммитит (без отдельного init-шага Kimi); ветка «SKIP regeneration» разрешена ТОЛЬКО при
  совпадении ОБОИХ хэшей — совпадение одного структурного уровня недостаточно (изменения глубже
  первого уровня видит контентный хэш). Сабагенты читают AGENTS.md вместо повторного вывода
  структуры.
- **Долгосрочная память `memory/`** (коммитится, не игнорируется) — память ТОГО проекта, который
  указан в `repo_path` задачи (для этого репозитория целевой проект — сама фабрика), а не память
  фабрики: одна память принадлежит ровно одному проекту. Каталог `memory/` живёт В КОРНЕ
  РАЗВЁРТЫВАНИЯ — том, который передан `prepare_factory.sh`; базовое имя проекта при развёртывании =
  basename этого каталога. Когда `repo_path` задачи указывает на ПОДКАТАЛОГ корня развёртывания,
  главный агент создаёт память явно, назвав проект: `memory_project.py init --repo <корень
  развёртывания> --project <basename разрешённого repo_path>`, и имя фиксируется в объявлении
  `project:` сводки. Каждая запись журнала несёт обязательный для НОВЫХ записей признак
  `project: <имя проекта>` (то же имя, что объявлено в сводке); сводка `summary.md` объявляет проект
  строками `project:`/`repo_path:` сразу после канонического маркера. Записи без `project:` — legacy
  (предупреждение); записи разных проектов в одном журнале — ошибка (`check_factory_model.py`,
  `memory_project.py check`). Единственный писатель — главный агент (одна запись в `change-log.md`
  на прогон, компакция в `summary.md` по порогу 50 записей); читается в начале задачи и ролями по
  необходимости. Если `memory/` отсутствует (первое обращение к проекту), фабрика создаёт её той же
  командой `init` с `--project <имя>`. История разработки самой фабрики НИКОГДА не попадает в память
  целевого проекта. Проверка модели — `scripts/check_factory_model.py`.
<!-- factory-rule: memory-ownership begin -->
**Владение памятью (каноническая формулировка):** одна память принадлежит ровно одному проекту — тому, что назван в `repo_path` задачи; каталог `memory/` живёт в КОРНЕ РАЗВЁРТЫВАНИЯ, базовое имя проекта = basename разрешённого `repo_path` и фиксируется в объявлении `project:` сводки. Единственный писатель — главный агент: одна запись в `memory/change-log.md` на прогон, компакция в `memory/summary.md` при пороге 50 записей (остаются последние 20, элементы severity=critical и follow_up=true сохраняются всегда). Записи разных проектов в одном журнале — ошибка (`check_factory_model.py`, `memory_project.py check`), записи без `project:` — legacy (предупреждение, не ошибка). История разработки самой фабрики в память целевого проекта не попадает.
<!-- factory-rule: memory-ownership end -->
<!-- factory-rule: memory-provenance begin -->
**Происхождение записей памяти (каноническая формулировка):** запись считается записью формата v2, если её `factory_version` новее 12.8.0 ИЛИ она уже несёт v2-поле (`run_id` или метку происхождения) — так полумигрированная запись тоже проверяется; у такой записи обязательны `run_id` формата `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) и метки происхождения в полях `decisions` и `results`: `[verified: <evidence>]` — утверждение подтверждено доказательством прогона (лог, acceptance, цитата), `[inferred]` — вывод без прямого доказательства. Запись формата v2 без `run_id` или без меток в этих полях — ошибка формата (`memory_project.py check`, `check_factory_model.py`), тогда как записи, написанные фабрикой не новее 12.8.0 и не несущие v2-полей, и legacy-записи без `project:` дают только предупреждение. Метка `[verified: ...]` обязана ссылаться на конкретное доказательство (команда/тест/лог); валидаторы проверяют наличие и форму метки.
<!-- factory-rule: memory-provenance end -->
- **run_id и WIP-фиксатор**: `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>` вычисляется в начале
  прогона (`run_id.py gen --task .code-factory/state/task.yaml`) и проставляется в `pipeline.yaml`,
  `acceptance.md`, `logs/*.md`, `report.md` и memory-запись; `run_id.py check --dir .code-factory`
  перечисляет артефакты прогона без `run_id`. Фиксатор `pipeline.yaml` несёт обязательные ключи
  `run_id`, `phase`, `status` (`ok|failed|in_progress`), `updated_at` и опциональные
  `files_touched`, `pending_decision`, `resume_hint`, `retry_counters`, `models_used`; проверяет
  `scripts/check_factory_model.py` (файла нет — SKIP). Запись v2 памяти несёт `run_id` и
  provenance-метки `[verified: <evidence>]`/`[inferred]` в `decisions` и `results`.

- Общение с пользователем — только на бизнес-языке.
- **Артефакты до изменений**: перед правкой любого исходника в `.code-factory/` должны уже
  существовать `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
<!-- factory-rule: artifacts-first begin -->
**Артефакты до изменений (каноническая формулировка):** фабрика не правит ни одного исходника, пока в `.code-factory/` не материализованы `state/task.yaml` (разобранная задача), `state/plan.md` (план), `logs/baseline.md` (базовый прогон тестов), `backups/` (бэкап каждого файла, который будет изменён, с сохранением относительных путей) и `manifest.json` (изменённые и созданные файлы). Состояние прогона живёт на диске, а не в переписке: неперсистентное знание теряется при рестарте и делает откат невозможным.
<!-- factory-rule: artifacts-first end -->
<!-- factory-rule: run-id begin -->
**Идентификатор прогона (каноническая формулировка):** в начале прогона детерминированно вычисляется `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` (`scripts/run_id.py`) и проставляется в `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` и в memory-запись прогона. Один прогон — один идентификатор, по нему артефакты связываются между собой. `scripts/run_id.py check` находит артефакты прогона без `run_id` и перечисляет их.
<!-- factory-rule: run-id end -->

- **Репо-гейт**: если задача ссылается на отсутствующие в репозитории файлы/символы/конфиги —
  в режиме hitl остановиться и спросить пользователя, в режиме auto зафиксировать допущение.
- **Маршрутизация ошибок**: детерминированный regex → Diagnostician (LLM) → Advisor (secondary,
  контрастное семейство диагностика, бюджет 1) → Human → FAILED; ретраи по бюджетам ролей
  (coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2).
<!-- factory-rule: retry-budgets begin -->
**Бюджеты ретраев (каноническая формулировка):** у каждой роли свой бюджет повторов — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; счётчики ведутся в `.code-factory/state/pipeline.yaml` (`retry_counters`). Исчерпанный бюджет не продлевается: прогон эскалируется по лестнице детерминированный regex → Diagnostician (LLM) → Advisor (LLM, secondary модель, контрастное семейство, бюджет 1) → Human (hitl) → FAILED с полным логом. Фабрика не зацикливается, не смягчает тесты ради зелёного прогона и не падает молча.
<!-- factory-rule: retry-budgets end -->

- **Code review**: каждая задача проходит через сабагента `factory-code-reviewer` перед
  приёмкой. Обычная задача — ревью diff изменений; `task_type: review` и `security_audit` —
  ревью/аудит всего кода ШАРДАМИ (`repo_inventory.py shards --max-lines 20000` → параллельные
  сабагенты по шардам → `merge_findings.py` даёт детерминированный merged verdict), замечания
  review-задачи становятся планом.
<!-- factory-rule: vaccination begin -->
**Вакцинация (каноническая формулировка):** баг, найденный ПОСЛЕ приёмки задачи, сначала получает регрессионный тест, который его воспроизводит (тест падает на текущем коде), и только потом исправление. Фикс без воспроизводящего теста не принимается, а сам тест остаётся в наборе как вакцина против повторения. Код-ревьюер проверяет наличие такого теста у каждого пост-приёмочного фикса и считает его отсутствие замечанием severity ≥ major.
<!-- factory-rule: vaccination end -->

<!-- factory-rule: review-gate-policy begin -->
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- factory-rule: review-gate-policy end -->
<!-- factory-rule: shard-protocol begin -->
**Шард-протокол (каноническая формулировка):** whole-repo ревью и security_audit никогда не помещаются в один контекст: `scripts/repo_inventory.py shards --max-lines 20000` режет репозиторий на шарды ≤20000 строк, каждый шард обрабатывает свой параллельный сабагент (ревьюер или аудитор) и пишет один findings-файл. Итог даёт детерминированный `scripts/merge_findings.py` (дедупликация, сортировка по severity, merged verdict), и канонический review-гейт применяется к MERGED findings, а не к отдельным шардам. Обычная задача `implement` ревьюится по diff и шардирования не требует.
<!-- factory-rule: shard-protocol end -->

- **Проверяемая приёмка**: критерии с `verify` исполняются реально (`scripts/verify_acceptance.py`
  → `.code-factory/state/acceptance.md`; exit 0 только при SUCCESS — хотя бы один критерий с
  `verify`, все MET, baseline доказан), а доказательства несут подписи FRESH/STALE
  (`scripts/evidence_ledger.py`): зелёный лог устаревшей ревизии приёмкой не считается.
<!-- factory-rule: verified-acceptance begin -->
**Проверяемая приёмка (каноническая формулировка):** приёмка машинно-проверяемая — `scripts/verify_acceptance.py` реально исполняет критерии с `verify` и пишет exit-коды и выдержки вывода в `.code-factory/state/acceptance.md`. Exit 0 возможен только при SUCCESS: хотя бы один критерий с `verify`, все критерии MET, baseline доказан; критерии без `verify` помечаются `derived`/`unverified` и доказательством не являются. STALE-доказательства или деградированный baseline понижают вердикт до DEGRADED; SUCCESS без регрессионного доказательства невозможен.
<!-- factory-rule: verified-acceptance end -->
<!-- factory-rule: evidence-ledger begin -->
**Реестр доказательств и цитаты (каноническая формулировка):** каждое доказательство (baseline, тесты, ревью) подписывается отпечатком рабочего дерева через `scripts/evidence_ledger.py` и принимается только со статусом FRESH; доказательство STALE (после подписи файлы изменились) приёмкой не считается. Каждая цитата ревьюера, диагноста или советника перепроверяется дословно `scripts/verify_quotes.py` (точная подстрока, нормализуется только CRLF→LF). Неподтверждённая цитата помечается UNTRUSTED и на вердикт не влияет.
<!-- factory-rule: evidence-ledger end -->

- **Брифинг каждой делегации**: сабагент получает самодостаточный брифинг по
  `.agents/skills/code-factory/references/handoff-briefing.md` — Task / Context / релевантные
  файлы ПУТЯМИ (без вставки содержимого) / что уже пробовали и почему не сработало; файлы пишет
  только главный агент, read-only роли идут с суффиксом «без правок».
<!-- factory-rule: handoff-briefing begin -->
**Брифинг каждой делегации (каноническая формулировка):** каждая делегация сабагенту — самодостаточный брифинг по `references/handoff-briefing.md` (Task / Context / релевантные файлы ПУТЯМИ, без вставки содержимого / что уже пробовали и почему не сработало). Файлы пишет только главный агент; read-only роли (analyzer, reviewer, security-auditor, diagnostician, advisor) идут с суффиксом «без правок». Сабагент возвращает сжатый структурированный результат с путями к артефактам, а не пересказ контекста.
<!-- factory-rule: handoff-briefing end -->

- **Формат задачи**: `title`, `repo_path`, `description`, опционально `user_story`, `mode`,
  `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria`
  (у критерия опционально `verify: <команда>` и `derived: true`), `business_tests`
  (сценарий/конфиги/ожидаемые бизнес-результаты), `commit_exclude`, `models`.
  Поля `priority` нет — все задачи по умолчанию high.
<!-- factory-rule: task-format begin -->
**Формат задачи (каноническая формулировка):** задача несёт `title`, `repo_path`, `description`, опционально `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (критерий может нести `verify: <команда>` и `derived: true`), `business_tests` (сценарий, конфиги, ожидаемые бизнес-результаты), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. Поля `priority` НЕТ — все задачи по умолчанию high, фабрика их не приоритизирует. Отсутствие обязательного поля — ошибка разбора задачи, а не повод домыслить его по ходу прогона.
<!-- factory-rule: task-format end -->

- **User story**: при наличии `user_story` фабрика анализирует и использует его на этапах
  анализа, планирования и реализации (всеми агентами).
- **`task_type: refactor`** — заморозка функциональности: 100% существующих тестов проходят без
  изменений, любое изменение поведения — критическая ошибка и автооткат.
- **`task_type: security_audit`** — адаптивный полный аудит (без живого сканирования сетей и
  пентеста); результат — отчёты + файл задач на исправление; фабрика НЕ чинит уязвимости сама.
- **Git-native**: если нет git-репозитория — `git init`; изменения идут через git
  (feature-ветка на задачу), откат к базовому коммиту при неудаче.
<!-- factory-rule: git-native begin -->
**Git-native (каноническая формулировка):** если в проекте нет git-репозитория, фабрика делает `git init` — отдельного init-шага в CLI нет. Все изменения идут через git: на задачу создаётся feature-ветка, базовый коммит и его HEAD фиксируются в `.code-factory/state/`, при неудаче прогон откатывается к базовому коммиту. Рабочее дерево держится чистым: build-артефакты авто-унтрекаются, артефакты фабрики коммитятся.
<!-- factory-rule: git-native end -->

- **Модели**: модели задаются в `config.toml` (`default_model` + `[secondary_model]`),
  сабагентам — `model_preference: primary|secondary`. Фактические модели логируются в
  `pipeline.yaml`/`report.md` (`models_used`). Для разделения моделей нужен
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — launcher `start.sh`/`start.cmd` выставляет его сам; фабрика
  проверяет его в pre-flight и при отсутствии пишет `models_warning` в pipeline.yaml/report.md.
  Модели Kimi (K3) и Qwen маршрутизируются через поле `models` задачи (см.
  `references/providers.md`).
<!-- factory-rule: models-generator-ne-judge begin -->
**Модели: генератор ≠ судья (каноническая формулировка):** главный агент передаёт модель явно в Agent tool (`model:`) по матрице `models` задачи и правилу generator≠judge: coder/tester и reviewer/diagnostician/advisor берутся из разных семейств моделей. `model_preference: primary|secondary` в `.md` сабагента — только FALLBACK для ролей, не названных задачей. Фактические модели ролей логируются в `.code-factory/state/pipeline.yaml` (`models_used`) и в `report.md`; secondary-модель работает только при `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, иначе фабрика пишет `models_warning` и продолжает на primary.
<!-- factory-rule: models-generator-ne-judge end -->

- **Отчёты**: `report.md` (история прогона) + `report_code_changes.md` (diff «было→стало»)
  генерируются автоматически в `.code-factory/` при завершении.
- **Коммиты**: поле `commit_exclude` в задаче исключает файлы из git-коммита
  (например, личную стратегию); ядро и документация коммитятся.
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (каноническая формулировка):** файлы, попадающие под шаблоны `commit_exclude` задачи, НИКОГДА не коммитятся — ни в одном коммите прогона, включая коммит версии и памяти. Стейджится всё, кроме исключённых шаблонов; код-ревьюер проверяет гигиену коммита и попадание исключённого файла в индекс считает замечанием severity ≥ major.
<!-- factory-rule: commit-exclude end -->

- При изменении файлов фабрики обновлять `.agents/README.md` и эти инструкции.
- **Документирование**: после каждого успешного implement/refactor вызывается сабагент
  `factory-documenter` (secondary) — обновляет только doc-комментарии и `.md`, валидатор
  `validate_documentation.py` с бюджетом 1 retry; для review/security_audit не вызывается.
<!-- factory-rule: documentation begin -->
**Документирование (каноническая формулировка):** после каждого успешного `implement`/`refactor` главный агент вызывает сабагента `factory-documenter` (secondary) с манифестом прогона; он обновляет ТОЛЬКО doc-комментарии и `.md` файлы и никогда код, тесты или конфиги. Свою работу он валидирует `scripts/validate_documentation.py` с бюджетом 1 retry; при исчерпании бюджета документационный долг фиксируется в отчёте прогона, и фабрика продолжает. Для `review`/`security_audit` документирование не вызывается.
<!-- factory-rule: documentation end -->

- **Версия**: `VERSION` — единый источник истины; тип версии определяет детерминированная
  матрица, валидирует код-ревьюер (может переопределить с объяснением), применяет
  `version_manager.py`; review/security_audit версию не меняют.
<!-- factory-rule: versioning begin -->
**Версионирование (каноническая формулировка):** `VERSION` (одна строка `X.Y.Z`) — единый источник истины, все остальные файлы синхронизируются ИЗ него через `scripts/version_manager.py`. Тип версии предлагает детерминированная матрица (`suggest`), валидирует код-ревьюер (может переопределить с объяснением, но не выбирает с нуля), применяет `bump`/`set` + `sync` + `validate` exit 0. Коммит версии идёт в ОДНОМ коммите с изменениями и несёт префикс `v<версия>: `. Задачи `review`/`security_audit` версию НЕ меняют.
<!-- factory-rule: versioning end -->


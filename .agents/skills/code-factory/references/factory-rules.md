# Factory Rules — единый каталог обязательных правил фабрики

Mandatory rules used to live scattered across five or more documents: every prose copy could
drift, and nothing detected the drift. This file is the ONE machine-checked home of the mandatory
rules — the rulebook.

Every rule is one section:

- a heading `## <id>` — the rule id used everywhere (markers, `--rule`, findings);
- a machine-readable carrier line `carriers: <path>; <path>; ...` — every document that MUST
  quote the rule verbatim, repository-relative;
- a marked canonical block:

```
<!-- factory-rule: <id> begin -->
<canonical wording>
<!-- factory-rule: <id> end -->
```

`scripts/check_factory_rules.py` parses this file, pulls the marked block out of every carrier and
fails when a carrier is missing the block, carries it twice, or holds a block that differs by even
one byte after `.strip()` (CRLF-safe because the canonical wordings are single lines). The
carriers stay byte-identical to the block below — when a rule changes, it changes HERE first and
the carriers are re-synced in the same commit.

```bash
python .agents/skills/code-factory/scripts/check_factory_rules.py                  # all rules
python .agents/skills/code-factory/scripts/check_factory_rules.py --rule <id>      # one rule
```

Exit code 0 = every candidate rule is consistent, 1 = the list of discrepancies. `--root <path>`
points the checker at another repository root (default: this repository).

## review-gate-policy
carriers: AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: review-gate-policy begin -->
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- factory-rule: review-gate-policy end -->

## artifacts-first
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: artifacts-first begin -->
**Артефакты до изменений (каноническая формулировка):** фабрика не правит ни одного исходника, пока в `.code-factory/` не материализованы `state/task.yaml` (разобранная задача), `state/plan.md` (план), `logs/baseline.md` (базовый прогон тестов), `backups/` (бэкап каждого файла, который будет изменён, с сохранением относительных путей) и `manifest.json` (изменённые и созданные файлы). Состояние прогона живёт на диске, а не в переписке: неперсистентное знание теряется при рестарте и делает откат невозможным.
<!-- factory-rule: artifacts-first end -->

## retry-budgets
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/error-routing.md
<!-- factory-rule: retry-budgets begin -->
**Бюджеты ретраев (каноническая формулировка):** у каждой роли свой бюджет повторов — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; счётчики ведутся в `.code-factory/state/pipeline.yaml` (`retry_counters`). Исчерпанный бюджет не продлевается: прогон эскалируется по лестнице детерминированный regex → Diagnostician (LLM) → Advisor (LLM, secondary модель, контрастное семейство, бюджет 1) → Human (hitl) → FAILED с полным логом. Фабрика не зацикливается, не смягчает тесты ради зелёного прогона и не падает молча.
<!-- factory-rule: retry-budgets end -->

## task-format
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: task-format begin -->
**Формат задачи (каноническая формулировка):** задача несёт `title`, `repo_path`, `description`, опционально `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (критерий может нести `verify: <команда>` и `derived: true`), `business_tests` (сценарий, конфиги, ожидаемые бизнес-результаты), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. Поля `priority` НЕТ — все задачи по умолчанию high, фабрика их не приоритизирует. Отсутствие обязательного поля — ошибка разбора задачи, а не повод домыслить его по ходу прогона.
<!-- factory-rule: task-format end -->

## memory-ownership
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: memory-ownership begin -->
**Владение памятью (каноническая формулировка):** одна память принадлежит ровно одному проекту — тому, что назван в `repo_path` задачи; каталог `memory/` живёт в КОРНЕ РАЗВЁРТЫВАНИЯ, базовое имя проекта = basename разрешённого `repo_path` и фиксируется в объявлении `project:` сводки. Единственный писатель — главный агент: одна запись в `memory/change-log.md` на прогон, компакция в `memory/summary.md` при пороге 50 записей (остаются последние 20, элементы severity=critical и follow_up=true сохраняются всегда). Записи разных проектов в одном журнале — ошибка (`check_factory_model.py`, `memory_project.py check`), записи без `project:` — legacy (предупреждение, не ошибка). История разработки самой фабрики в память целевого проекта не попадает.
<!-- factory-rule: memory-ownership end -->

## versioning
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: versioning begin -->
**Версионирование (каноническая формулировка):** `VERSION` (одна строка `X.Y.Z`) — единый источник истины, все остальные файлы синхронизируются ИЗ него через `scripts/version_manager.py`. Тип версии предлагает детерминированная матрица (`suggest`), валидирует код-ревьюер (может переопределить с объяснением, но не выбирает с нуля), применяет `bump`/`set` + `sync` + `validate` exit 0. Коммит версии идёт в ОДНОМ коммите с изменениями и несёт префикс `v<версия>: `. Задачи `review`/`security_audit` версию НЕ меняют.
<!-- factory-rule: versioning end -->

## models-generator-ne-judge
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: models-generator-ne-judge begin -->
**Модели: генератор ≠ судья (каноническая формулировка):** главный агент передаёт модель явно в Agent tool (`model:`) по матрице `models` задачи и правилу generator≠judge: coder/tester и reviewer/diagnostician/advisor берутся из разных семейств моделей. `model_preference: primary|secondary` в `.md` сабагента — только FALLBACK для ролей, не названных задачей. Фактические модели ролей логируются в `.code-factory/state/pipeline.yaml` (`models_used`) и в `report.md`; secondary-модель работает только при `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, иначе фабрика пишет `models_warning` и продолжает на primary.
<!-- factory-rule: models-generator-ne-judge end -->

## commit-exclude
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (каноническая формулировка):** файлы, попадающие под шаблоны `commit_exclude` задачи, НИКОГДА не коммитятся — ни в одном коммите прогона, включая коммит версии и памяти. Стейджится всё, кроме исключённых шаблонов; код-ревьюер проверяет гигиену коммита и попадание исключённого файла в индекс считает замечанием severity ≥ major.
<!-- factory-rule: commit-exclude end -->

## git-native
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: git-native begin -->
**Git-native (каноническая формулировка):** если в проекте нет git-репозитория, фабрика делает `git init` — отдельного init-шага в CLI нет. Все изменения идут через git: на задачу создаётся feature-ветка, базовый коммит и его HEAD фиксируются в `.code-factory/state/`, при неудаче прогон откатывается к базовому коммиту. Рабочее дерево держится чистым: build-артефакты авто-унтрекаются, артефакты фабрики коммитятся.
<!-- factory-rule: git-native end -->

## handoff-briefing
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: handoff-briefing begin -->
**Брифинг каждой делегации (каноническая формулировка):** каждая делегация сабагенту — самодостаточный брифинг по `references/handoff-briefing.md` (Task / Context / релевантные файлы ПУТЯМИ, без вставки содержимого / что уже пробовали и почему не сработало). Файлы пишет только главный агент; read-only роли (analyzer, reviewer, security-auditor, diagnostician, advisor) идут с суффиксом «без правок». Сабагент возвращает сжатый структурированный результат с путями к артефактам, а не пересказ контекста.
<!-- factory-rule: handoff-briefing end -->

## shard-protocol
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: shard-protocol begin -->
**Шард-протокол (каноническая формулировка):** whole-repo ревью и security_audit никогда не помещаются в один контекст: `scripts/repo_inventory.py shards --max-lines 20000` режет репозиторий на шарды ≤20000 строк, каждый шард обрабатывает свой параллельный сабагент (ревьюер или аудитор) и пишет один findings-файл. Итог даёт детерминированный `scripts/merge_findings.py` (дедупликация, сортировка по severity, merged verdict), и канонический review-гейт применяется к MERGED findings, а не к отдельным шардам. Обычная задача `implement` ревьюится по diff и шардирования не требует.
<!-- factory-rule: shard-protocol end -->

## verified-acceptance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: verified-acceptance begin -->
**Проверяемая приёмка (каноническая формулировка):** приёмка машинно-проверяемая — `scripts/verify_acceptance.py` реально исполняет критерии с `verify` и пишет exit-коды и выдержки вывода в `.code-factory/state/acceptance.md`. Exit 0 возможен только при SUCCESS: хотя бы один критерий с `verify`, все критерии MET, baseline доказан; критерии без `verify` помечаются `derived`/`unverified` и доказательством не являются. STALE-доказательства или деградированный baseline понижают вердикт до DEGRADED; SUCCESS без регрессионного доказательства невозможен.
<!-- factory-rule: verified-acceptance end -->

## evidence-ledger
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: evidence-ledger begin -->
**Реестр доказательств и цитаты (каноническая формулировка):** каждое доказательство (baseline, тесты, ревью) подписывается отпечатком рабочего дерева через `scripts/evidence_ledger.py` и принимается только со статусом FRESH; доказательство STALE (после подписи файлы изменились) приёмкой не считается. Каждая цитата ревьюера, диагноста или советника перепроверяется дословно `scripts/verify_quotes.py` (точная подстрока, нормализуется только CRLF→LF). Неподтверждённая цитата помечается UNTRUSTED и на вердикт не влияет.
<!-- factory-rule: evidence-ledger end -->

## preflight
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: preflight begin -->
**Pre-flight окружения (каноническая формулировка):** перед первыми командами фабрика пробует реальное окружение через `scripts/factory_preflight.py --out .code-factory/state/preflight.json` — рабочая python-команда (`python`/`python3`/`py`), git, bash/sh, ОС и `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`. Дальнейшие команды эмитятся под НАЙДЕННЫЕ capabilities, поэтому догадка о `python3` на Windows не ломает прогон. Отсутствие secondary-модели прогон не останавливает, а даёт `models_warning` в pipeline.yaml и report.md.
<!-- factory-rule: preflight end -->

## documentation
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: documentation begin -->
**Документирование (каноническая формулировка):** после каждого успешного `implement`/`refactor` главный агент вызывает сабагента `factory-documenter` (secondary) с манифестом прогона; он обновляет ТОЛЬКО doc-комментарии и `.md` файлы и никогда код, тесты или конфиги. Свою работу он валидирует `scripts/validate_documentation.py` с бюджетом 1 retry; при исчерпании бюджета документационный долг фиксируется в отчёте прогона, и фабрика продолжает. Для `review`/`security_audit` документирование не вызывается.
<!-- factory-rule: documentation end -->

## checkpoint-resume
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: checkpoint-resume begin -->
**Checkpoint/resume (каноническая формулировка):** после каждой фазы главный агент пишет `.code-factory/state/pipeline.yaml` (фаза, статус, затронутые файлы, ожидаемое решение, resume-hint, run_id, время) — состояние прогона живёт на диске, а не в контексте. При рестарте фабрика сверяет фиксатор плана и, если задача не изменилась, продолжает с ЗАПИСАННОЙ фазы, а не с начала. `resume` восстанавливает счётчики ретраев, поэтому исчерпанные бюджеты не обнуляются рестартом.
<!-- factory-rule: checkpoint-resume end -->

## rollback-on-retry
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: rollback-on-retry begin -->
**Откат перед ретраем (каноническая формулировка):** каждый провал тестов или сборки сначала маршрутизируется детерминированно (`references/error-routing.md`), затем состояние откатывается: файлы восстанавливаются из `.code-factory/backups/`, созданные фабрикой файлы удаляются, состояние git приводится к зафиксированному. Только после отката ошибка отдаётся роли-исполнителю — иначе повторный прогон идёт по уже испорченному состоянию. Инфраструктурные авто-фиксы (окружение, зависимости) код не откатывают.
<!-- factory-rule: rollback-on-retry end -->

## vaccination
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: vaccination begin -->
**Вакцинация (каноническая формулировка):** баг, найденный ПОСЛЕ приёмки задачи, сначала получает регрессионный тест, который его воспроизводит (тест падает на текущем коде), и только потом исправление. Фикс без воспроизводящего теста не принимается, а сам тест остаётся в наборе как вакцина против повторения. Код-ревьюер проверяет наличие такого теста у каждого пост-приёмочного фикса и считает его отсутствие замечанием severity ≥ major.
<!-- factory-rule: vaccination end -->

## run-id
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: run-id begin -->
**Идентификатор прогона (каноническая формулировка):** в начале прогона детерминированно вычисляется `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` (`scripts/run_id.py`) и проставляется в `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` и в memory-запись прогона. Один прогон — один идентификатор, по нему артефакты связываются между собой. `scripts/run_id.py check` находит артефакты прогона без `run_id` и перечисляет их.
<!-- factory-rule: run-id end -->

## memory-provenance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: memory-provenance begin -->
**Происхождение записей памяти (каноническая формулировка):** запись считается записью формата v2, если её `factory_version` новее 12.8.0 ИЛИ она уже несёт v2-поле (`run_id` или метку происхождения) — так полумигрированная запись тоже проверяется; у такой записи обязательны `run_id` формата `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) и метки происхождения в полях `decisions` и `results`: `[verified: <evidence>]` — утверждение подтверждено доказательством прогона (лог, acceptance, цитата), `[inferred]` — вывод без прямого доказательства. Запись формата v2 без `run_id` или без меток в этих полях — ошибка формата (`memory_project.py check`, `check_factory_model.py`), тогда как записи, написанные фабрикой не новее 12.8.0 и не несущие v2-полей, и legacy-записи без `project:` дают только предупреждение. Метка `[verified: ...]` обязана ссылаться на конкретное доказательство (команда/тест/лог); валидаторы проверяют наличие и форму метки.
<!-- factory-rule: memory-provenance end -->

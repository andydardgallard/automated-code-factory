# Golden set — калибровка код-ревьюера

Эталонные diff'ы с ожидаемым вердиктом: ревьюер прогоняется по каждому кейсу, его вердикт и
severity findings сверяются с эталоном (`calibrate_reviewer.py score`), и метрики показывают,
где ревьюер пере- или недо-ревьюит. Кейсы синтетические и самодостаточные — они не связаны с
кодом фабрики (репозиторий можно менять, не переписывая эталон).

Формат кейса — `cases/<id>/`:
- `diff.patch` — небольшой unified diff (10–40 строк), ровно то, что видит ревьюер;
- `expected.yaml` — плоский YAML (`key: value`, список в `[a, b]`, `#` — комментарий):
  `verdict: approve|request_changes` и `severities: [critical, major, minor, nit]` — severity,
  которые ревьюер ОБЯЗАН найти; `[]` = идеальный ревьюер не сообщает ничего, а любая лишняя
  severity в его выводе считается false positive и снижает precision (пере-ревью).
  `nit`/`minor` не влияют на вердикт: `approve` ожидается при `[]` даже если в diff'е есть nit.

Результат прогона ревьюера — `<results>/<id>.json` — его штатный вердикт по кейсу
(`references/code-review.md` §6: `{"verdict": ..., "findings": [{"file", "line", "severity",
"issue", "quote", "fix"}, ...]}`; форма findings шарда из §1.1 с `title`/`detail` считается так же).
Подсчёт читает только `verdict` и `severity` каждого finding, поэтому остальные поля в обеих формах
произвольны. Кейс без результата или нечитаемый/некорректный файл — exit 2 с указанием проблемы.

```bash
python .agents/skills/code-factory/scripts/calibrate_reviewer.py score \
  --golden skill-base/golden-set/cases \
  --results .code-factory/logs/golden-results \
  --out .code-factory/logs/reviewer-calibration.md
```

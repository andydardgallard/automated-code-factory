# Golden set — code reviewer calibration

Reference diffs with an expected verdict: the reviewer is run against each case, its verdict and
finding severities are compared with the reference (`calibrate_reviewer.py score`), and the metrics show
where the reviewer over- or under-reviews. The cases are synthetic and self-contained — they are not tied to the
factory code (the repository can change without rewriting the reference).

Case format — `cases/<id>/`:
- `diff.patch` — a small unified diff (10–40 lines), exactly what the reviewer sees;
- `expected.yaml` — flat YAML (`key: value`, list as `[a, b]`, `#` — comment):
  `verdict: approve|request_changes` and `severities: [critical, major, minor, nit]` — the severities
  the reviewer MUST find; `[]` = a perfect reviewer reports nothing, and any extra
  severity in its output counts as a false positive and lowers precision (over-reviewing).
  `nit`/`minor` do not affect the verdict: `approve` is expected with `[]` even if the diff contains a nit.

The result of a reviewer run — `<results>/<id>.json` — is its standard per-case verdict
(`references/code-review.md` §6: `{"verdict": ..., "findings": [{"file", "line", "severity",
"issue", "quote", "fix"}, ...]}`; the shard findings form from §1.1 with `title`/`detail` counts the same way).
Scoring reads only the `verdict` and the `severity` of each finding, so the remaining fields in both forms
are arbitrary. A case without a result, or an unreadable/invalid file, is exit 2 with the problem stated.

```bash
python .agents/skills/code-factory/scripts/calibrate_reviewer.py score \
  --golden skill-base/golden-set/cases \
  --results .code-factory/logs/golden-results \
  --out .code-factory/logs/reviewer-calibration.md
```

# Code Review

Goal: a static quality gate on the factory's work. The `factory-code-reviewer` subagent checks
the produced code before the task can be accepted. It either **approves** the change or returns a
**rework list** (a task for the coder).

## 0. Review gate (canonical policy)

This block is the normative statement of the acceptance rule: where any other sentence in this
file, in an agent instruction or in a run document phrases it differently, this block wins. The
wording is byte-identical everywhere it is quoted.

<!-- review-gate-policy: begin -->
**Review-гейт (каноническая формулировка):** задача НЕ принимается, пока у ревьюера открыты замечания severity=critical (вердикт `request_changes` с open critical findings). Бюджет ревьюера = 2 итерации. Если бюджет исчерпан, а critical findings остались: в режиме hitl фабрика ОСТАНАВЛИВАЕТСЯ и спрашивает пользователя; в режиме auto допускается только conditional pass — соответствующий критерий помечается `unverified_review` в `.code-factory/state/acceptance.md`, а нерешённые findings попадают в `.code-factory/report.md` (раздел unresolved findings), никогда молча. Полный SUCCESS при открытых critical findings невозможен.
<!-- review-gate-policy: end -->

The reviewer does NOT fix code and does NOT run the full test suite. Its job is a fresh,
critical look at the code itself.

## 1. Scope — what the reviewer sees

Two modes, chosen by the task:

- **Normal task (`task_type: implement`, the default)** — the reviewer sees **only the factory's
  diff**, not the whole project:
  - tracked changes: `git diff` (working tree vs `git HEAD` recorded in
    `.code-factory/state/git-head.txt`), and
  - new/untracked files listed in `.code-factory/manifest.json` (`created_files`).
  - It must NOT review unrelated legacy code that the factory did not touch.
- **Review task (`task_type: review`)** — the reviewer sees the **whole codebase** (or the
  explicitly listed files/areas from the task), because the deliverable is the review itself.
  Above the size budget this scope is sharded (see §1.1).

## 1.1 Shard protocol — whole-repo review (P0.1)

A whole-repo review of a large project does not fit into one reviewer context. When the
repository exceeds the size budget — **N = 20 000 lines by default** (`--max-lines`) — the
whole-repo review runs sharded, and **no subagent ever receives the whole-repo context**. Small
repos and the ordinary diff-scope `implement` task keep the single-reviewer flow: the protocol
bounds context, it is not extra ceremony.

1. **Inventory (deterministic, zero LLM).** `repo_inventory.py` walks the tree (VCS/build/vendor
   dirs excluded, symlinks never followed, binaries skipped) and greedily packs the sorted file
   list into shards of at most N lines; a file longer than N lines becomes its own shard flagged
   `oversized`:

   ```bash
   python .agents/skills/code-factory/scripts/repo_inventory.py inventory --repo <project-root>
   python .agents/skills/code-factory/scripts/repo_inventory.py shards --repo <project-root> --max-lines 20000
   ```

   Both print JSON (`{"files": [{"path","lines","bytes"}]}` /
   `{"shards": [{"id","files","lines"}], "total_shards"}`); the shard list IS the review plan.
2. **Parallel reviewer subagents.** One `factory-code-reviewer` per shard, launched in parallel;
   each gets ONLY its shard's file list, the task/acceptance criteria and the canonical gate
   policy (§0). A shard reviewer must not ask for whole-repo context — cross-shard reasoning is
   the merge's job, not a subagent's.
3. **One findings file per shard**, written to
   `.code-factory/logs/code-review-shards/<shard-id>.json`, exactly this contract:

   ```json
   {"shard": "<id>",
    "verdict": "approve | request_changes",
    "findings": [{"severity": "critical | major | minor | nit",
                  "file": "<path>", "line": 42,
                  "title": "short one-line statement",
                  "detail": "what is wrong + the fix, with the §2.1 quote"}]}
   ```

   `severity` is exactly `critical | major | minor | nit` (the merge validates it), `line` is an
   integer or `null`, and the shard `verdict` follows the ordinary rule: `request_changes` when
   the shard has a critical or major finding.
4. **Deterministic merge (zero LLM).** The main agent merges the shard files with the script —
   never by hand, so no prose can soften the result:

   ```bash
   python .agents/skills/code-factory/scripts/merge_findings.py \
     --inputs .code-factory/logs/code-review-shards/*.json \
     --report .code-factory/logs/code-review-merged.json \
     --md .code-factory/logs/code-review.md
   ```

   - deduplication by `(file, line, normalized title)`; duplicates collapse into one finding
     carrying `occurrences: [<shard ids>]`;
   - sorting by severity (critical → major → minor → nit), then file, line, title, so the merged
     order never depends on the input order (the same shards in any order give a byte-identical
     report);
   - merged verdict = `request_changes` when at least one shard returned `request_changes` **OR**
     any critical finding exists, else `approve`;
   - exit code `0` = merged `approve`, `1` = merged `request_changes`, `2` = broken input (stderr
     names the file and the problem) or an unwritable output path.
5. **The merged verdict IS the run's review verdict.** It is what the acceptance step consumes,
   and the canonical gate policy (§0) is applied to the MERGED findings (never per shard). The
   shard files stay as the evidence behind it, and `verify_quotes.py` (§2.1) re-checks the merged
   headline findings.

## 2. What to check (checklist)

For every file in scope, assess:

1. **Correctness vs plan** — does the change implement exactly what the plan/task asked, and
   nothing unrelated? No scope creep, no silently dropped requirements.
2. **Style / format** — run the project's formatter/linter if present
   (`cargo fmt --check`, `cargo clippy`, `ruff check`, `eslint`, `gofmt -l`, `black --check`…)
   and report violations. Follow the existing project style.
3. **Dead code** — unused functions, imports, variables, commented-out blocks, unreachable paths.
4. **Unreadable code** — misleading names, overly complex/obfuscated constructs, magic numbers
   without meaning, missing comments where the intent is non-obvious.
5. **Inefficient code** — obviously wasteful patterns: unnecessary clones/allocations, O(n²)
   where O(n) is trivial, repeated computation, needless re-reads of files/config.
6. **Unsafe / panic-prone code** — `unsafe` blocks, `unwrap`/`expect`/`panic!`/`assert!` on the
   production (non-test) path, unchecked indexing, integer overflow, division by zero, missing
   error handling.
7. **Duplication** — copy-pasted logic that should be factored into a shared helper.
8. **Documentation** — public API / new modules / new config fields are documented; README or
   in-project docs updated where the task requires it.
9. **Artifacts / commit hygiene** — no build artifacts, temp files, output dirs (`target/`,
   `node_modules/`, `__pycache__/`, `opt_results/`, logs) accidentally included in the change;
   `commit_exclude` patterns from the task are not staged.
10. **Run trajectory (P1.13 — "trajectory is the truth")** — the diff is not the whole story.
    Read `.code-factory/state/pipeline.yaml` (`retry_counters`, `models_used`),
    `.code-factory/logs/errors.md`, `diagnostic.md` and the stage logs and judge HOW the code
    turned green: how many retries preceded the first green run, which roles were escalated and
    why, where the run got stuck, whether the same step was "fixed" twice. A change that only
    passes after repeated rollbacks, or one made green by weakening a test instead of fixing the
    code, is a finding (severity ≥ major), not a footnote. Retry counts and stuck points are
    quoted like code (item 11).
11. **Evidence quotes** — every finding carries a verbatim quote of the code or log it refers to
    (file:line + exact fragment). An unquoted finding is UNTRUSTED and must not influence the
    verdict — see §2.1.

## 2.1 Evidence: verbatim quotes (P0.6)

A finding is an assertion about reality, so it must come with the reality: `file:line` plus the
verbatim fragment of the code or log it is about. A finding whose quote cannot be produced is
dropped or marked UNTRUSTED instead of being passed on.

Before the verdict is consumed, the main agent re-checks the quotes deterministically:

```bash
python .agents/skills/code-factory/scripts/verify_quotes.py --claims claims.json
# claims.json:  [{"quote": "exact text from the source", "source": ".code-factory/logs/baseline.md"}, ...]
```

- A quote counts only as an EXACT substring of its source. Normalization is deliberately minimal
  (CRLF → LF) so a log written on Windows matches a quote pasted on POSIX; case and whitespace are
  evidence and are never normalized — an approximate match is a failed match.
- A missing/unreadable source, an empty quote or a non-matching quote is reported as **UNTRUSTED**
  together with an explicit `fallback to full log` note: the caller re-reads the raw archive
  (`.code-factory/logs/…`) instead of trusting the summarized reduction.
- Exit code is 0 only when EVERY quote is verified, so a partly invented evidence set can never be
  silently accepted. The same check covers the shard-merged verdict (§1.1) and the
  Diagnostician/Advisor findings (`error-routing.md`), which quote the archived logs the same way.

## 3. Severity & verdict

Classify every finding by severity:

| Severity | Meaning | Blocks acceptance? |
|----------|---------|--------------------|
| critical | bug, crash, data corruption, security issue, violates an acceptance criterion | yes |
| major | bad design, significant inefficiency, dead code in the hot path, scope creep, missing required docs | yes |
| minor | style nit, duplication, unclear naming, minor missing comment | no (reported) |
| nit | cosmetic, optional | no (reported) |

**Verdict:**
- `approve` — no critical/major findings. minor/nit findings are listed but do NOT block.
- `request_changes` — at least one critical or major finding. The reviewer MUST produce a rework
  task (see below).

This table classifies findings and picks the reviewer verdict; it is not the acceptance rule. What
keeps a task unaccepted, and what happens when the reviewer budget runs out, is defined only by the
canonical review-gate policy in §0 (severity=critical is the hard acceptance blocker there).

## 4. Rework task (on request_changes)

The reviewer returns a concise, actionable rework list for the `factory-coder`, NOT prose
essays. Each item:

```
- file: <path> (or "scope: whole repo" for review tasks)
  line: <line number, or "n/a">
  severity: critical|major
  issue: <what is wrong, 1 sentence>
  quote: <verbatim fragment of the code/log, §2.1>
  fix: <concrete change to make, 1-2 sentences>
```

The main agent passes this verbatim to the coder as the next task. minor/nit findings are
attached separately as "optional" and the coder may skip them.

## 5. Iteration & budget

- Review is bounded: **reviewer budget = 2** iterations per task (track `retry_counters.reviewer`
  in `.code-factory/state/pipeline.yaml`).
- After a `request_changes` round, the coder applies the rework list, then the factory MUST
  re-run **integration + regression** tests (and business tests only if the rework touched
  business logic) before re-invoking the reviewer.
- When the budget is exhausted (the 2nd `request_changes` for the same task), escalate instead of
  looping — exactly as the canonical review-gate policy in §0 defines it:
  - hitl mode: show the user the findings and ask how to proceed — the run STOPS there;
  - auto mode: conditional pass only — the affected criterion is marked `unverified_review` in
    `.code-factory/state/acceptance.md` and the unresolved findings go to `.code-factory/report.md`
    (section `unresolved findings`), never silently. A full SUCCESS with open critical findings is
    impossible.

## 5.5 Version-type validation (implement/refactor tasks)

For `implement`/`refactor` tasks the main agent proposes a version bump type from the
deterministic matrix (`scripts/version_manager.py suggest`: new subagent/task-type/field →
minor, breaking change → major, fix → patch, review/security_audit → none). The reviewer receives
the proposed type + the change list and **validates** it:

- The reviewer does **not** determine the type from scratch — it only checks that the proposed
  type matches the observed change list against the matrix.
- It may **override** the type (raise or lower) when the proposal disagrees with the matrix; every
  override MUST carry a one-sentence explanation.
- The final decision (including any override + explanation) is reported in the verdict YAML
  (`version_type` field) and recorded by the main agent in the run report.

## 6. Output format

The reviewer's final message IS the complete handoff. Return ONLY this YAML:

```yaml
verdict: approve | request_changes
scope: diff | whole_repo
summary: |
  1-2 sentences.
findings:
  - file: <path>
    line: <line number, or n/a>
    severity: critical | major | minor | nit
    issue: <1 sentence>
    quote: <verbatim fragment of the code/log backing this finding, §2.1>
    fix: <1-2 sentences>   # required for critical/major, optional for minor/nit
rework:                    # only when verdict=request_changes
  - file: <path>
    line: <line number, or n/a>
    severity: critical | major
    issue: <1 sentence>
    quote: <verbatim fragment>
    fix: <1-2 sentences>
version_type:              # implement/refactor only — validation of the proposed bump
  proposed: major | minor | patch | none
  validated: major | minor | patch | none
  override: true | false
  explanation: <1 sentence>  # required when override=true
```

The main agent writes the verdict to `.code-factory/logs/code-review.md` (or appends to it), runs
`verify_quotes.py` over the quotes (§2.1), and records `models_used.reviewer` in
`.code-factory/state/pipeline.yaml`. For a sharded review the merged verdict from
`merge_findings.py` is the file that lands there (§1.1).

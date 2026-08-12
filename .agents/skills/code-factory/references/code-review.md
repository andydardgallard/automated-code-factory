# Code Review

Goal: a static quality gate on the factory's work. The `factory-code-reviewer` subagent checks
the produced code before the task can be accepted. It either **approves** the change or returns a
**rework list** (a task for the coder). A task is never accepted while the reviewer has an open
`request_changes` verdict.

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

## 4. Rework task (on request_changes)

The reviewer returns a concise, actionable rework list for the `factory-coder`, NOT prose
essays. Each item:

```
- file: <path> (or "scope: whole repo" for review tasks)
  severity: critical|major
  issue: <what is wrong, 1 sentence>
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
- On the 2nd `request_changes` for the same task, escalate instead of looping:
  - hitl mode: show the user the findings and ask how to proceed;
  - auto mode: proceed to acceptance but record the unresolved findings prominently in
    `report.md` (`review: approved with open major findings` — never silently).

## 6. Output format

The reviewer's final message IS the complete handoff. Return ONLY this YAML:

```yaml
verdict: approve | request_changes
scope: diff | whole_repo
summary: |
  1-2 sentences.
findings:
  - file: <path>
    severity: critical | major | minor | nit
    issue: <1 sentence>
    fix: <1-2 sentences>   # required for critical/major, optional for minor/nit
rework:                    # only when verdict=request_changes
  - file: <path>
    severity: critical | major
    issue: <1 sentence>
    fix: <1-2 sentences>
```

The main agent writes the verdict to `.code-factory/logs/code-review.md` (or appends to it) and
records `models_used.reviewer` in `.code-factory/state/pipeline.yaml`.

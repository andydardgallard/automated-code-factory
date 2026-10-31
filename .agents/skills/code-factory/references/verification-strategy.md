# Verification Strategy & Rollback

Goal: prove the task works on three levels (integration, regression, business) for ANY project
type (frontend, backend, CLI, library, green-field) and, on ANY failure, safely return the
project to its pre-change state before retrying.

## 0. Order of execution (fixed)

1. **Artifacts first** — before any source change, `.code-factory/` must contain:
   `state/task.yaml`, `state/plan.md`, `logs/baseline.md`, `backups/`, `manifest.json`.
   (Factory state lives in files, not in the conversation.)
2. Baseline (before changes) → `logs/baseline.md`
3. Integration tests (changed modules)
4. Regression tests (full existing suite)
5. Business tests (run the real program, compare business results)
6. Acceptance check (verify acceptance_criteria)

If a stage fails, roll back and retry implementation with the error context. Do not proceed to a
later stage while an earlier one is failing.

## 0.1 Task-type specifics

- **refactor** — see `refactoring.md`. The success criterion is inverted vs a normal task: the
  ONLY acceptable proof is that 100% of the EXISTING integration/regression/business tests pass
  with zero changes. Any test that needs to be edited (not because it was broken before, but to
  match new behavior) is a critical failure → automatic rollback.
- **security_audit** — see `security-audit.md`. No code is changed and no tests are written;
  the deliverable is a set of reports plus a generated fix-task file. Verification here means
  "the reports exist, cover every present artifact type, and the fix-task file is valid".

## 1. Integration tests

- Focused tests that verify the changed modules work together correctly (new function + its
  callers, new module + platform API, etc.).
- Use the project's existing test framework. Follow the style of existing tests.
- Include edge cases relevant to the task (e.g., fractional prices, zero/empty input, boundary
  values).
- Do NOT delete or weaken existing tests.

## 2. Regression tests

- Run the full existing test suite with the canonical command from `tech-stack-detection.md`.
- Compare against the baseline: any previously-passing test that now fails is a regression and
  triggers rollback.

## 2.1 Think in Code — big output lives on disk, not in context

Test and build output is bulky and mostly uninformative: the agent needs the counters and the tail,
not 4000 lines. So:

- Run every test/build/business command with its FULL output redirected to
  `.code-factory/logs/<stage>.log` (e.g. `integration.log`, `regression.log`,
  `business-test.log`) — an output above a few KB (guideline: >100 lines) is never truncated away,
  the file keeps all of it. That log is the evidence a quote refers to
  (`references/code-review.md` §2.1).
- Into the agent's context comes only the deterministic reduction:

  ```bash
  python .agents/skills/code-factory/scripts/log_tail.py .code-factory/logs/regression.log \
    --lines 50 --grep 'FAILED|ERROR|error'
  ```

  It prints `total_lines`, `total_bytes`, the match count per `--grep` pattern and the last N
  lines — nothing more, and no LLM tokens. The same rule applies to counting/scanning anything
  large: write a small stdlib script that prints only the answer instead of reading files into the
  context.
- Reports and handoffs reference the log by path plus the counters/tail excerpt
  (`test-results.md`, section §5), never by pasting the full log.
- A log is only evidence for the tree it was produced from — that is what the ledger below
  enforces.

## 2.2 Evidence ledger — FRESH/STALE (P1.9)

A green log from an older revision is not proof about the current code. Every test/acceptance
result is therefore signed with the fingerprint of the files it depends on, and re-checked before
anyone relies on it.

The task's `repo_path` is resolved ONCE to an absolute path and the examples below are anchored
there: every one of them passes `--repo <resolved repo_path>` explicitly, `--files` are
repo-relative paths, and a `.code-factory/...` path means `<resolved repo_path>/.code-factory/...` —
the artifact tree lives INSIDE the resolved repository, never in the launch/deployment folder. Run
the commands with the cwd at the resolved repo root (an explicit cwd), or spell those paths out
absolutely.

```bash
# sign: print the SHA-256 fingerprint of the files this evidence depends on (repo-relative)
python .agents/skills/code-factory/scripts/evidence_ledger.py sign \
  --repo <resolved repo_path> --files src/a.py src/b.py

# stamp: write/refresh one evidence entry in the ledger
python .agents/skills/code-factory/scripts/evidence_ledger.py stamp \
  --repo <resolved repo_path> --ledger .code-factory/state/evidence.json --name regression \
  --result pass --files src/a.py src/b.py --log .code-factory/logs/regression.log

# check: recompute the fingerprints of the signed files and print FRESH/STALE per entry
python .agents/skills/code-factory/scripts/evidence_ledger.py check \
  --repo <resolved repo_path> --ledger .code-factory/state/evidence.json --files src/a.py src/b.py
```

- The fingerprint is SHA-256 over `<relative path>:<content sha256>` lines, sorted and
  de-duplicated, so neither the order of `--files` nor the platform separator matters. A deleted
  file contributes `:missing` and an unreadable one `:unreadable`, so a deletion counts as a change
  instead of an error. Re-stamping a name refreshes that entry (one current entry per name).
- **FRESH** = every signed file is byte-identical to the moment the evidence was produced;
  **STALE** = at least one signed file changed afterwards. Each entry records the exact `--files`
  scope it was stamped with and is re-measured against THAT scope: a caller `--files` that differs
  is a scope mismatch (STALE, fail-closed, with the reason naming the scope instead of a file
  change), and `check` with no `--files` verifies every entry against its own recorded scope, so a
  mixed-scope ledger can be verified. An entry written before the `files` field existed has no
  recorded scope: it is measured against the caller's `--files` when one is given, and is reported
  **UNSCOPED** (fail-closed, the reason naming the missing scope) when the caller gave none.
  `check` exits 0 only when every entry is
  FRESH and every result is `pass`; STALE or UNSCOPED evidence, a failed result or an
  empty/unreadable ledger is exit 1.
- **The reviewer and the acceptance step accept evidence only while it is FRESH.** A green test log
  whose files changed since (the very common "tests passed, then the coder touched the code again")
  proves nothing about the current tree. Implementation: after any change to signed files, re-run
  the stage and re-stamp; never carry a stale stamp forward.
- **STALE downgrades the verdict**: passing `--ledger` to the acceptance gate makes it re-check the
  ledger in-process, and a STALE entry — or the absence of a FRESH `regression=pass` entry —
  downgrades an otherwise SUCCESS run to **DEGRADED** with the reason quoted in `acceptance.md`.
  Omitting `--ledger` is not a loophole: without a ledger there is no freshness proof at all, so
  the verdict is DEGRADED as well — SUCCESS always requires a usable FRESH `regression=pass`
  ledger entry, and an entry stamped with an EMPTY scope (`--files` empty) is UNSCOPED and never
  counts as that proof:

  ```bash
  python .agents/skills/code-factory/scripts/verify_acceptance.py \
    --input criteria.json --output .code-factory/state/acceptance.md \
    --repo <resolved repo_path> \
    --regression pass --ledger .code-factory/state/evidence.json --evidence-files src/a.py
  ```

- The ledger is not a second source of truth: it only answers "is this evidence still about the
  code we have?", while the logs stay the evidence itself.

## 3. Business tests

Business test = run the actual (built/started) program with the user-specified configs and input
data, and check that the **business results** match what the user expected.

1. Build/start the program exactly as it will be used (see plan: "Config / inputs").
2. Collect the actual business results (program output, generated files, logs, metrics — whatever
   the domain produces).
3. Compare with the expected business results from the plan.
4. Record both actual and expected in `logs/business-tests.md` with PASS/FAIL per item.
5. If they differ — show the user the actual vs expected (HITL) or auto-decide (auto): the
   difference may mean (a) the code is wrong → fix; or (b) the expectation was described
   inaccurately → revise the expectation with the user and re-run.

### Practical notes (learned on a real run)

- **Output location**: configs often have an `exit_results_path`; the factory should read it
  from the config and verify the generated report files exist and have expected row counts.
- **Distinct-outcomes check**: if the user says "the wrong result was only N variants", verify
  the new run produces MORE than N distinct result rows (e.g., count unique metric tuples in the
  output CSV). This is a strong, objective business-test check.
- **Distinguish "filter works" from "broken"**: a scenario may legitimately produce 0 deals
  (e.g., a CNY-tuned threshold on an expensive Si instrument). Prove the filter is working by
  re-running with a price-proportional threshold and showing deals appear — not by forcing deals.
- **Build then run**: for compiled stacks, business tests must use the exact commands the user
  gave (e.g., `cargo build -p <lib> --release` then `cargo run -- -c <config>`). Record which
  artifacts the run consumes (e.g., which `.so`/binary) and verify they exist.
- **Sandbox side effects**: a run may create output dirs (e.g., `opt_results/`). Treat them as
  temporary; remove them after verifying, or add them to `.gitignore`.

### 3.1 Browser business tests (Web GUI tasks) — tester-owned acceptance

When the task's Web GUI path is applicable (`references/chrome-devtools-mcp.md`), the business test
of the user scenario runs in a real browser through the Chrome DevTools MCP tools and is owned by
`factory-tester`:

- **Independence**: `factory-gui-expert` may capture a baseline and debug during implementation, but
  the final scenario is executed by the tester AFTER the last code change — never by the
  implementer, and never by reusing the specialist's diagnostic run as acceptance.
- **Evidence location**: the artifacts live under the resolved repository's
  `.code-factory/logs/browser/` and carry the run_id — scenario and URL, the actions, the
  expected/actual results, the fresh accessibility snapshots/screenshots at the required viewport,
  and the console/network findings. The specialist's files are marked DIAGNOSTIC and stay distinct
  from the tester's ACCEPTANCE files; both sets are referenced from `business-tests.md`,
  `test-results.md` and `report.md`.
- **A screenshot alone is not proof of behavior**: acceptance needs the executed scenario and its
  observed result, with the relevant console errors and failed network requests reported. A console
  error or a failed request on the accepted path is a failure, not a cosmetic note, and is routed
  through the normal error routing (CODER route).
- **FRESH/STALE applies** (§2.2): any code change after the browser run makes that evidence STALE —
  the scenario is re-run and re-stamped, never carried forward.
- **Degradation**: when Node.js, Chrome/Chrome for Testing or the MCP server is missing, the browser
  criterion is reported UNVERIFIED (never MET) with an infrastructure diagnosis; no artifact is
  fabricated to fill the gap.


## 4. Rollback mechanism (critical)

Trigger: ANY test failure (integration, regression, business) or acceptance-criteria miss.

The task's `repo_path` is resolved ONCE to an absolute path and the whole mechanism is anchored
there: git always runs as `git -C <resolved repo_path>`, and `.code-factory/` is
`<resolved repo_path>/.code-factory/` INSIDE the resolved repository — state, backups and manifest
included. The launch/deployment folder is never written to by the run.

### 4.1 Prepare before changes (done in Phase 4 of the flow)

```bash
# Record git state — every git operation targets the resolved repo
git -C <resolved repo_path> rev-parse HEAD > <resolved repo_path>/.code-factory/state/git-head.txt
git -C <resolved repo_path> rev-parse --abbrev-ref HEAD > <resolved repo_path>/.code-factory/state/git-branch.txt
git -C <resolved repo_path> status --porcelain > <resolved repo_path>/.code-factory/state/git-status-before.txt

# Backup every file that will be modified (preserve relative paths, INSIDE the resolved repo)
mkdir -p <resolved repo_path>/.code-factory/backups
# example: cp --parents src/lib.rs <resolved repo_path>/.code-factory/backups/
# (copy each changed file into <resolved repo_path>/.code-factory/backups/ keeping its path)
```

The feature branch and the run's commits use the same anchored form
(`git -C <resolved repo_path> switch -c <feature-branch>`, `git -C <resolved repo_path> commit ...`),
so the branch, the base commit and its HEAD all belong to the resolved repository.

### 4.2 Manifest

Maintain `<resolved repo_path>/.code-factory/manifest.json`. Every path in it is relative to the
resolved repo root and `backup_root` points INSIDE that repository:

```json
{
  "changed_files": ["src/lib.rs", "configs/trading.toml"],
  "created_files": ["tests/integration_fractional.rs", "scripts/gen_report.py"],
  "backup_root": ".code-factory/backups"
}
```

Update it after every file operation by the factory.

### 4.3 Rollback steps (on failure)

Run every step with the cwd at `<resolved repo_path>`, or prefix each path with it. Every
destructive restoring command below (`rm -f`, `git reset --hard`, `git checkout --`, the branch
deletion) is classified FIRST with
`python .agents/skills/code-factory/scripts/action_gate.py check --action "<command>" --scope
<resolved repo_path> --mode <hitl|auto>` and its verdict is respected (canonical rule
`destructive-action-gate`): ALLOW proceeds, CONFIRM needs an explicit user decision (in `auto`
mode the factory proceeds and records the assumption), HARD_DENY is never executed — and a
CONFIRM or HARD_DENY answer is not a reason to skip the classification of the next command.

```bash
# 1. Remove files created by the factory (manifest paths are relative to the resolved repo)
while read -r f; do rm -f "$f"; done < <(python -c "import json;print('\n'.join(json.load(open('.code-factory/manifest.json'))['created_files']))")

# 2. If the run moved HEAD (it made commits on the feature branch — the normal implement case),
#    git restores the base state FIRST; restoring file backups before this step is wasted work,
#    because the git restore overwrites them again. Reset BEFORE switching — a dirty tree makes
#    `switch` refuse, and deleting the feature branch afterwards drops the run's commits:
#    git -C <resolved repo_path> reset --hard <base commit from .code-factory/state/git-head.txt>
#    git -C <resolved repo_path> switch <pre-run branch from .code-factory/state/git-branch.txt>
#    git -C <resolved repo_path> branch -D <feature branch>
#    (the main agent alone performs these working-tree mutations, on the resolved repo)

# 3. If HEAD was NOT moved (no run commits): restore modified files from backups
#    (all inside the resolved repo) — for each changed file: cp .code-factory/backups/<path> <path>;
#    for tracked files git can double-check: git -C <resolved repo_path> checkout -- <changed files>
#    (created/untracked files must be removed manually — step 1)

# 4. Verify: git -C <resolved repo_path> status should now match .code-factory/state/git-status-before.txt
```

After rollback the resolved repository MUST be byte-identical to the pre-change state — and the
launch/deployment root MUST be untouched: no artifact, backup or commit of the run ever lands
there. The ONE documented exception is the deployment-root state the canonical rules REQUIRE
(rule `repo-scoping`): the run's long-term memory record in `memory/` (`memory/change-log.md`,
`memory/summary.md`) and the `VERSION` bump applied through `scripts/version_manager.py` live at
the DEPLOYMENT ROOT even when `repo_path` is a subdirectory of it. They are legitimate state of
the run, not a leak of artifacts into the root, so neither rollback nor the finish gate removes or
suppresses them; every OTHER artifact (`.code-factory/`, backups, plan, reports) stays scoped to
the resolved repository.

### 4.4 Iteration

- Append the failure context to `.code-factory/logs/errors.md` (what test failed, the error
  output, what was rolled back).
- Pass the error context back to the coder subagent: "the previous attempt failed on X, rollback
  was done, fix accordingly."
- Limit retries per root cause by the retry budgets in `error-routing.md` (coder=1, ba=2,
  planner=2). On exhaustion, escalate to the Diagnostician instead of looping.

## 5. Reporting

Write `.code-factory/logs/test-results.md`:

| Stage | Command/Scenario | Result | Evidence |
|-------|------------------|--------|----------|
| Baseline | `cargo test` | PASS (42) | logs/baseline.md |
| Integration | ... | PASS | logs/integration.log |
| Regression | `cargo test` | PASS (42) | logs/regression.log |
| Business | run on CNY-3.23.txt | PASS | logs/business-test.log |

Keep the report short — evidence by file reference, not by pasting full logs. Each row's full
output lives in `.code-factory/logs/<stage>.log` (see §2.1); the row links the log, and a green
result is only quoted as evidence while its ledger entry is FRESH (§2.2).

## 6. Final report (.code-factory/report.md)

On finish (success OR FAILED) write `.code-factory/report.md` — ONE self-contained file that
summarizes the whole run. It is the hand-off artifact to the factory developer; it must allow
analyzing the run without reading the rest of `.code-factory/`.

```markdown
# Factory Report: <task title>

## Result
SUCCESS | FAILED

## Task (business)
<parsed task: title, description, user_story (if any), acceptance criteria>

## Models used
| Role | Model |
|------|-------|
| main agent (planning) | <session model> |
| analyzer | <model from models_used> |
| coder | ... |
| gui_expert | ... (only when the Web GUI path applied) |
| tester | ... |
| diagnostician | ... |

## What changed (manifest)
<from .code-factory/manifest.json: changed_files + created_files>

## Test results
| Stage | Command/Scenario | Result | Evidence |

## Business results
<actual vs expected per user story>

## Errors & diagnosis
- errors.md summary (each failure: stage, root cause, resolution)
- diagnostic.md summary (if Diagnostician ran: root_cause, recommended_role, action)

## Acceptance check
|criterion|status|evidence|

## Git
- branch: <feature-branch> · commit: <sha> · excluded from commit: <commit_exclude>
```

## 6.1 Code-changes report (.code-factory/report_code_changes.md)

Next to `report.md`, write `.code-factory/report_code_changes.md` — a deterministic
was-became diff of the commit (only changed lines, no context). Generate it with the bundled
script (zero LLM tokens):

```bash
python .agents/skills/code-factory/scripts/gen_code_changes_report.py \
  --repo <project-root> --commit <sha>
```

The report shows for each file: changed lines as a "Was | Became" table, and pure additions and
removals as code blocks. Every block — including a new file's content — is truncated at 30 lines
(`MAX_BLOCK`) with a `... (+N lines, full code in git)` pointer to git. Run it after the
factory's commit so the reported commit sha exists in the repo.



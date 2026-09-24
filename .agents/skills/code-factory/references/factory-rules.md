# Factory Rules — the single rulebook of the factory's mandatory rules

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
**Review gate (canonical wording):** a task is NOT accepted while the reviewer has open severity=critical findings (verdict `request_changes` with open critical findings). The reviewer budget = 2 iterations. If the budget is exhausted and critical findings remain: in hitl mode the factory STOPS and asks the user; in auto mode only a conditional pass is allowed — the corresponding criterion is marked `unverified_review` in `.code-factory/state/acceptance.md`, and the unresolved findings go into `.code-factory/report.md` (unresolved findings section), never silently. A full SUCCESS with open critical findings is impossible.
<!-- factory-rule: review-gate-policy end -->

## artifacts-first
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: artifacts-first begin -->
**Artifacts before changes (canonical wording):** the factory edits no source file until `.code-factory/` already holds `state/task.yaml` (the parsed task), `state/plan.md` (the plan), `logs/baseline.md` (the baseline test run), `backups/` (a backup of every file that will be changed, relative paths preserved) and `manifest.json` (the changed and created files). The run state lives on disk, not in the conversation: non-persistent knowledge is lost on restart and makes rollback impossible.
<!-- factory-rule: artifacts-first end -->

## retry-budgets
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/error-routing.md
<!-- factory-rule: retry-budgets begin -->
**Retry budgets (canonical wording):** every role has its own retry budget — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; the counters are kept in `.code-factory/state/pipeline.yaml` (`retry_counters`). An exhausted budget is not extended: the run escalates along the ladder deterministic regex → Diagnostician (LLM) → Advisor (LLM, secondary model, contrasting model family, budget 1) → Human (hitl) → FAILED with the full log. The factory does not loop, does not soften tests for a green run and does not fail silently.
<!-- factory-rule: retry-budgets end -->

## task-format
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: task-format begin -->
**Task format (canonical wording):** a task carries `title`, `repo_path`, `description`, optionally `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (a criterion may carry `verify: <command>` and `derived: true`), `business_tests` (scenario, configs, expected business results), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. There is NO `priority` field — all tasks are high by default, the factory does not prioritize them. A missing required field is a task parsing error, not a reason to guess it mid-run.
<!-- factory-rule: task-format end -->

## memory-ownership
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: memory-ownership begin -->
**Memory ownership (canonical wording):** one memory belongs to exactly one project — the one named in the task's `repo_path`; the `memory/` directory lives at the DEPLOYMENT ROOT, the base project name = basename of the resolved `repo_path` and is fixed in the summary's `project:` declaration. The only writer is the main agent: one entry in `memory/change-log.md` per run, compaction into `memory/summary.md` at the 50-entry threshold (the last 20 remain, severity=critical and follow_up=true items are always preserved). Entries from different projects in one journal are an error (`check_factory_model.py`, `memory_project.py check`), entries without `project:` are legacy (a warning, not an error). The development history of the factory itself never enters the target project's memory.
<!-- factory-rule: memory-ownership end -->

## versioning
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: versioning begin -->
**Versioning (canonical wording):** `VERSION` (one line `X.Y.Z`) is the single source of truth, all other files are synced FROM it via `scripts/version_manager.py`. The version type is suggested by a deterministic matrix (`suggest`), validated by the code reviewer (may override with an explanation, but does not choose from scratch), applied by `bump`/`set` + `sync` + `validate` exit 0. The version commit goes in ONE commit with the changes and carries the prefix `v<version>: `. `review`/`security_audit` tasks do NOT change the version.
<!-- factory-rule: versioning end -->

## models-generator-ne-judge
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: models-generator-ne-judge begin -->
**Models: generator ≠ judge (canonical wording):** the main agent passes the model explicitly in the Agent tool (`model:`) per the task's `models` matrix and the generator≠judge rule: coder/tester and reviewer/diagnostician/advisor are taken from different model families. `model_preference: primary|secondary` in a subagent's `.md` is only a FALLBACK for roles not named by the task. The actual role models are logged in `.code-factory/state/pipeline.yaml` (`models_used`) and in `report.md`; the secondary model works only with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, otherwise the factory writes `models_warning` and continues on primary.
<!-- factory-rule: models-generator-ne-judge end -->

## commit-exclude
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (canonical wording):** files matching the task's `commit_exclude` patterns are NEVER committed — in no commit of the run, including the version and memory commit. Everything except the excluded patterns is staged; the code reviewer checks commit hygiene and counts an excluded file landing in the index as a finding of severity ≥ major.
<!-- factory-rule: commit-exclude end -->

## git-native
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: git-native begin -->
**Git-native (canonical wording):** if the project has no git repository, the factory runs `git init` — there is no separate init step in the CLI. All changes go through git: a feature branch is created per task, the base commit and its HEAD are recorded in `.code-factory/state/`, and on failure the run rolls back to the base commit. The working tree is kept clean: build artifacts are auto-untracked, factory artifacts are committed.
<!-- factory-rule: git-native end -->

## handoff-briefing
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: handoff-briefing begin -->
**Briefing of every delegation (canonical wording):** every delegation to a subagent is a self-contained briefing per `references/handoff-briefing.md` (Task / Context / relevant files BY PATH, without inlining their contents / what has already been tried and why it failed). Only the main agent writes files; read-only roles (analyzer, reviewer, security-auditor, diagnostician, advisor) carry the "no edits" suffix. The subagent returns a compact structured result with paths to artifacts, not a retelling of the context.
<!-- factory-rule: handoff-briefing end -->

## shard-protocol
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: shard-protocol begin -->
**Shard protocol (canonical wording):** whole-repo review and security_audit never fit into one context: `scripts/repo_inventory.py shards --max-lines 20000` cuts the repository into shards of ≤20000 lines, each shard is processed by its own parallel subagent (reviewer or auditor) and writes one findings file. The result is produced by the deterministic `scripts/merge_findings.py` (deduplication, sorting by severity, merged verdict), and the canonical review gate is applied to the MERGED findings, not to individual shards. A regular `implement` task is reviewed by diff and needs no sharding.
<!-- factory-rule: shard-protocol end -->

## verified-acceptance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: verified-acceptance begin -->
**Verified acceptance (canonical wording):** acceptance is machine-verifiable — `scripts/verify_acceptance.py` actually executes the criteria with `verify` and writes exit codes and output excerpts into `.code-factory/state/acceptance.md`. Exit 0 is possible only on SUCCESS: at least one criterion with `verify`, all criteria MET, baseline proven; criteria without `verify` are marked `derived`/`unverified` and are not evidence. STALE evidence or a degraded baseline lowers the verdict to DEGRADED; SUCCESS without regression evidence is impossible.
<!-- factory-rule: verified-acceptance end -->

## evidence-ledger
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md
<!-- factory-rule: evidence-ledger begin -->
**Evidence ledger and quotes (canonical wording):** every piece of evidence (baseline, tests, review) is signed with the working-tree fingerprint via `scripts/evidence_ledger.py` and is accepted only with FRESH status; STALE evidence (files changed after signing) does not count as acceptance. Every quote from the reviewer, diagnostician or advisor is re-checked verbatim by `scripts/verify_quotes.py` (exact substring, only CRLF→LF is normalized). An unconfirmed quote is marked UNTRUSTED and does not affect the verdict.
<!-- factory-rule: evidence-ledger end -->

## preflight
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: preflight begin -->
**Environment pre-flight (canonical wording):** before the first commands the factory probes the real environment via `scripts/factory_preflight.py --out .code-factory/state/preflight.json` — a working python command (`python`/`python3`/`py`), git, bash/sh, OS and `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`. Further commands are emitted for the FOUND capabilities, so a guess about `python3` on Windows does not break the run. A missing secondary model does not stop the run, it yields `models_warning` in pipeline.yaml and report.md.
<!-- factory-rule: preflight end -->

## documentation
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: documentation begin -->
**Documentation (canonical wording):** after every successful `implement`/`refactor` the main agent invokes the `factory-documenter` subagent (secondary) with the run's manifest; it updates ONLY doc comments and `.md` files and never code, tests or configs. It validates its work with `scripts/validate_documentation.py` with a budget of 1 retry; when the budget is exhausted, the documentation debt is recorded in the run report and the factory continues. Documentation is not invoked for `review`/`security_audit`.
<!-- factory-rule: documentation end -->

## checkpoint-resume
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: checkpoint-resume begin -->
**Checkpoint/resume (canonical wording):** after every phase the main agent writes `.code-factory/state/pipeline.yaml` (phase, status, files touched, pending decision, resume hint, run_id, time) — the run state lives on disk, not in the context. On restart the factory reconciles the plan checkpoint and, if the task has not changed, continues from the RECORDED phase, not from the beginning. `resume` restores the retry counters, so exhausted budgets are not reset by a restart.
<!-- factory-rule: checkpoint-resume end -->

## rollback-on-retry
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: rollback-on-retry begin -->
**Rollback before retry (canonical wording):** every test or build failure is first routed deterministically (`references/error-routing.md`), then the state is rolled back: files are restored from `.code-factory/backups/`, factory-created files are deleted, the git state is brought back to the recorded one. Only after the rollback is the error handed to the executing role — otherwise the retry runs on an already corrupted state. Infrastructure auto-fixes (environment, dependencies) do not roll back code.
<!-- factory-rule: rollback-on-retry end -->

## vaccination
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: vaccination begin -->
**Vaccination (canonical wording):** a bug found AFTER the task's acceptance first gets a regression test that reproduces it (the test fails on the current code), and only then the fix. A fix without a reproducing test is not accepted, and the test itself stays in the suite as a vaccine against recurrence. The code reviewer checks that every post-acceptance fix has such a test and counts its absence as a finding of severity ≥ major.
<!-- factory-rule: vaccination end -->

## run-id
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: run-id begin -->
**Run identifier (canonical wording):** at the start of a run `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` is computed deterministically (`scripts/run_id.py`) and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` and the run's memory entry. One run — one identifier; it links the artifacts to each other. `scripts/run_id.py check` finds the run's artifacts without a `run_id` and lists them.
<!-- factory-rule: run-id end -->

## memory-provenance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/README.md
<!-- factory-rule: memory-provenance begin -->
**Memory entry provenance (canonical wording):** an entry counts as a v2-format entry if its `factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a provenance marker) — so a half-migrated entry is checked too; such an entry must carry a `run_id` in the format `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) and provenance markers in the `decisions` and `results` fields: `[verified: <evidence>]` — the claim is confirmed by run evidence (log, acceptance, quote), `[inferred]` — an inference without direct evidence. A v2-format entry without a `run_id` or without markers in these fields is a format error (`memory_project.py check`, `check_factory_model.py`), whereas entries written by a factory no newer than 12.8.0 and carrying no v2 fields, and legacy entries without `project:`, yield only a warning. The `[verified: ...]` marker must reference concrete evidence (command/test/log); the validators check the marker's presence and form.
<!-- factory-rule: memory-provenance end -->

## memory-actuality
carriers: AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/planning-guide.md
<!-- factory-rule: memory-actuality begin -->
**Memory actuality (canonical wording):** at the start of a run the open backlog is reconciled with the tree (`memory_project.py backlog --repo <root>` — a fold of all follow_up=true/severity=critical over the journal history); at the end of a run every item is either closed with a `closed:` block with a mandatory `evidence:` in the run entry, or stays in `unfinished` with a reason — an item cannot disappear without evidence of closing: `backlog --check` gives exit 1 for open items, closing without `evidence:` and closing a nonexistent item. The `summary.md` summary (`## Current state`) is actualized by EVERY run, not only at compaction; a divergence between the version it declares and VERSION is a mechanism warning.
<!-- factory-rule: memory-actuality end -->

## plan-committee
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; AGENTS.md; .agents/skills/code-factory/references/planning-guide.md
<!-- factory-rule: plan-committee begin -->
**Committee on double plan rejection (canonical wording):** if the user rejected the plan twice (hitl, Revise branch), the main agent launches a second independent planner subagent from a contrasting model family, which builds an alternative plan from the same task and the user's accumulated remarks; the deterministic `scripts/plan_arbiter.py` (stdlib) compares both plans by machine-readable sections (DAG tasks, verify commands, risks, business tests) and forms a merged variant with a list of discrepancies; the user is presented with the merged plan and the discrepancies, and further edits are made against it.
<!-- factory-rule: plan-committee end -->

## no-shared-tree-git-mutations
carriers: AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/handoff-briefing.md; .agents/agents/sub-agents/coder.md
<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

## english-only
carriers: AGENTS.md; .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/planning-guide.md; .agents/agents/sub-agents/coder.md; .agents/agents/sub-agents/tester.md; .agents/agents/sub-agents/documenter.md
<!-- factory-rule: english-only begin -->
**English-only (canonical wording):** every artifact the factory produces is written in English only: code and comments of target projects, documentation, docstrings, commit messages, reports (`.code-factory/report*.md`, logs), memory entries, plans and subagent briefings. The factory accepts a task file in any language, but everything it produces from it is English. EXCEPTION: live communication with the user stays in the user's business language, and history (CHANGELOG and old memory entries) is never rewritten.
<!-- factory-rule: english-only end -->

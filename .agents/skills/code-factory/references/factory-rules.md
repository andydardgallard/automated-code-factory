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

A VERBATIM carrier and a POINTER are different things, and only the first is declared here. The
root `AGENTS.md` is the factory's hand-authored MAP of the rules: it names every rule it relies on
as one line — the rule id, then this file, then the rule's heading — and quotes nothing, so it is
NOT a carrier of any rule (it once was 24 times, and that is exactly how it grew to 38 KB — over the
32 KB instruction-file limit the size gate enforces). A document that must be biteable by a reader
in one file (`SKILL.md`, `.agents/agents/code-factory.md`, `.agents/README.md`,
`references/code-review.md`, …) stays a verbatim carrier. Which one a document is, is a deliberate
decision recorded in its `carriers:` line, never an accident of copy-paste.

## review-gate-policy
carriers: .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: review-gate-policy begin -->
**Review gate (canonical wording):** a task is NOT accepted while the reviewer has open severity=critical findings (verdict `request_changes` with open critical findings). The reviewer budget = 2 iterations. If the budget is exhausted and critical findings remain: in hitl mode the factory STOPS and asks the user; in auto mode only a conditional pass is allowed — the corresponding criterion is marked `unverified_review` in `.code-factory/state/acceptance.md`, and the unresolved findings go into `.code-factory/report.md` (unresolved findings section), never silently. A full SUCCESS with open critical findings is impossible. For a `task_type: review` run the gate judges the delivered review, not the reviewed code: the verdict stays `request_changes` in `results.review=` while the run's own acceptance records whether the report and the follow-up task file were produced.
<!-- factory-rule: review-gate-policy end -->

## review-report-only
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: review-report-only begin -->
**Report-only review (canonical wording):** a `task_type: review` run never edits the project: no review verdict, in either mode, reaches a node that starts a coder, writes a backup or changes a tracked source, test, config, documentation or data file — the run's own `.code-factory/` artifacts and its single `memory/` record are the only writes. The deliverable is the report (`.code-factory/logs/code-review.md` + `.code-factory/report.md`) plus a generated follow-up task file (`.code-factory/review/fix-tasks.yaml`, produced by `scripts/review_followup_task.py`) that the owner runs later as a separate `implement` task; the findings never become this run's plan. A review criterion that is not MET stops the run and asks the owner — it is never routed into error routing's coder branch — and because the run changes nothing, every `verify:` criterion of a review task must be satisfiable on the unmodified tree: a criterion that needs a change is an authoring error the run reports. A review run's acceptance judges the delivered report, while the verdict on the reviewed code stays recorded as `results.review=`; the two facts are never conflated. `security_audit` keeps its own guarantee (reports plus a fix-task file, no auto-fixing) unchanged, and this rule does not restate it.
<!-- factory-rule: review-report-only end -->

## artifacts-first
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: artifacts-first begin -->
**Artifacts before changes (canonical wording):** the factory edits no source file until `.code-factory/` already holds `state/task.yaml` (the parsed task), `state/plan.md` (the plan), `logs/baseline.md` (the baseline test run), `backups/` (a backup of every file that will be changed, relative paths preserved) and `manifest.json` (the changed and created files). The run state lives on disk, not in the conversation: non-persistent knowledge is lost on restart and makes rollback impossible.
<!-- factory-rule: artifacts-first end -->

## retry-budgets
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/skills/code-factory/references/error-routing.md
<!-- factory-rule: retry-budgets begin -->
**Retry budgets (canonical wording):** every role has its own retry budget — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; the counters are kept in `.code-factory/state/pipeline.yaml` (`retry_counters`). An exhausted budget is not extended: the run escalates along the ladder deterministic regex → Diagnostician (LLM) → Advisor (LLM, a judge-side model contrasting with the Diagnostician's family, budget 1) → Human (hitl) → FAILED with the full log. The factory does not loop, does not soften tests for a green run and does not fail silently.
<!-- factory-rule: retry-budgets end -->

## task-format
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: task-format begin -->
**Task format (canonical wording):** a task carries `title`, `repo_path`, `description`, optionally `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (a criterion may carry `verify: <command>` and `derived: true`), `business_tests` (scenario, configs, expected business results), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. `repo_path` is REQUIRED for every task except a green-field one (a brand-new project created in place) and is always resolved ONCE to an absolute path at the start of the run. There is NO `priority` field — all tasks are high by default, the factory does not prioritize them. A missing required field is a task parsing error, not a reason to guess it mid-run.
<!-- factory-rule: task-format end -->

## memory-ownership
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: memory-ownership begin -->
**Memory ownership (canonical wording):** one memory belongs to exactly one project — the one named in the task's `repo_path`. The `memory/` directory lives at the DEPLOYMENT ROOT; the summary declares `project: <name>` (the project's name) and `project_id: <identity>`, where the identity is the first 12 hex characters of the sha256 of the repository's root commit, so renaming the folder or taking a versioned copy never invalidates the memory and a memory of a different repository is refused. A memory that declares no `project_id` falls back to the deployment-root basename, which is only a fallback and says so. The only writer is the main agent: exactly one entry in `memory/change-log.md` per run (`run_id`-addressed; a run with no record or with two records is an error), compaction into `memory/summary.md` at the 50-entry threshold (the last 20 remain, severity=critical and follow_up=true items always survive, and the flow invokes `memory_project.py compact`). Entries from different projects in one journal are an error (`check_factory_model.py`, `memory_project.py check`), entries without `project:` are legacy (a warning, not an error). The development history of the factory itself never enters the target project's memory.
<!-- factory-rule: memory-ownership end -->

## versioning
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: versioning begin -->
**Versioning (canonical wording):** `VERSION` (one line `X.Y.Z`) is the single source of truth, all other files are synced FROM it via `scripts/version_manager.py`. The version type is suggested by a deterministic matrix (`suggest`), validated by the code reviewer (may override with an explanation, but does not choose from scratch), applied by `bump`/`set` + `sync` + `validate` exit 0. The version commit goes in ONE commit with the changes and carries the prefix `v<version>: `. `review`/`security_audit` tasks do NOT change the version.
<!-- factory-rule: versioning end -->

## models-generator-ne-judge
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: models-generator-ne-judge begin -->
**Models: task first, then the default matrix (canonical wording):** exactly two cases and no third. (a) When the task's `models:` matrix names a role, that exact model is used and is NEVER substituted: a generator/judge family collision is a WARNING naming both roles and both models, never a reason to swap. (b) When the task does not name the role, its model comes from the factory's DEFAULT MATRIX — the CLI config's `default_model` / `[secondary_model] default_model` selected by the role's `model_preference` — where the generator≠judge rule IS enforced: a same-family coder/tester/gui_expert versus reviewer/diagnostician/advisor pair with either side taken from the default matrix is an ERROR naming the fix (widen `[secondary_model]` or pin `models.<role>` in the task). (c) There is no third path: the main agent never picks a model on its own. The ONE exception is the plan committee's second planner, which always comes from a family contrasting the first planner. `scripts/model_matrix.py` is the single implementation of this precedence, `scripts/test_model_precedence.py` pins it, and the model actually served is confirmed by an ARTIFACT: `scripts/model_attribution.py` reads the CLI session wire and cross-checks `models_used`, a mismatch fails the run, and a missing wire is DEGRADED — never silently green. The secondary model works only with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`; otherwise the factory writes `models_warning` and continues on the primary. The actual role models are logged in `.code-factory/state/pipeline.yaml` (`models_used`) and in `report.md`.
<!-- factory-rule: models-generator-ne-judge end -->

## model-unavailable-stop
carriers: .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/code-review.md; .agents/skills/code-factory/references/providers.md
<!-- factory-rule: model-unavailable-stop begin -->
**Named-model unavailability stops the run (canonical wording):** when a model named in the task's `models:` matrix is unavailable — a provider auth/rate/model error at launch or probe of its role — the run STOPS: in hitl mode the factory asks the owner via `AskUserQuestion` whether to change the matrix (the answer is written to `state/task.yaml`) or to stop, and in auto mode the run ends FAILED with the explicit reason naming the model and the provider error. The main agent NEVER performs the named role's work itself and NEVER substitutes another model, in no mode and under no pretext — "otherwise the run stalls" is not a reason — and no artifact presented as that role's result is produced. A provider failure of a task-named model is classified first with `scripts/error_router.py classify`: a `PROVIDER_*` category routes to infrastructure with budget 3, the record goes to `logs/errors.md` and the counter to `state/pipeline.yaml`, but every retry uses the SAME named model, and an exhausted budget means stop-and-ask, never degradation. An unknown role written into `models_used` — a key absent from the `ROLES` registry of `scripts/model_matrix.py` (`main` aside) — is a run error that exits 1 naming the role, never DEGRADED.
<!-- factory-rule: model-unavailable-stop end -->

## commit-exclude
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: commit-exclude begin -->
**commit_exclude (canonical wording):** files matching the task's `commit_exclude` patterns are NEVER committed — in no commit of the run, including the version and memory commit. Everything except the excluded patterns is staged; the code reviewer checks commit hygiene and counts an excluded file landing in the index as a finding of severity ≥ major.
<!-- factory-rule: commit-exclude end -->

## git-native
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: git-native begin -->
**Git-native (canonical wording):** if the target repository has no git repository, the factory runs `git -C <resolved repo_path> init` — there is no separate init step in the CLI. EVERY git operation of the run targets the resolved repo_path — executed as `git -C <resolved repo_path>` (or with the cwd set to it): the init check, the feature branch created per task, the recording of the base commit and its HEAD in `<repo>/.code-factory/state/`, the commits, and the rollback to the base commit on failure. The working tree of the TARGET repository is kept clean: build artifacts are auto-untracked, factory artifacts are committed; a run never touches the factory's own deployment `.git`.
<!-- factory-rule: git-native end -->

## repo-scoping
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: repo-scoping begin -->
**Repo-path scoping (canonical wording):** at the start of a run the factory resolves the task's `repo_path` ONCE to an absolute path (relative to the launch directory) and then performs EVERYTHING relative to that resolved target repository: the `.code-factory/` artifact tree (`state/`, `logs/`, `backups/`, `manifest.json`, reports), backups, git operations (`git -C <repo>` or an explicit cwd), source edits and rollback. The documented exceptions that stay DEPLOYMENT-ROOT-scoped are `memory/` (the long-term memory lives at the deployment root) and `scripts/version_manager.py` (`VERSION` lives at the deployment root) — they receive their root explicitly, never a silent default to the launch directory.
<!-- factory-rule: repo-scoping end -->

## handoff-briefing
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: handoff-briefing begin -->
**Briefing of every delegation (canonical wording):** every delegation to a subagent is a self-contained briefing per `references/handoff-briefing.md` (Task / Context / relevant files BY PATH, without inlining their contents / what has already been tried and why it failed / the MEMORY FACTS: the open backlog items that touch this work and the relevant past decisions read from `memory/summary.md` and the journal, so a subagent never re-derives the project's history). Only the main agent writes files; read-only roles (analyzer, planner, reviewer, security-auditor, diagnostician, advisor) carry the "no edits" suffix. The subagent returns a compact structured result with paths to artifacts, not a retelling of the context.
<!-- factory-rule: handoff-briefing end -->

## shard-protocol
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: shard-protocol begin -->
**Shard protocol (canonical wording):** whole-repo review and security_audit never fit into one context: `scripts/repo_inventory.py shards --tracked --max-lines 20000` cuts the TRACKED tree (`git ls-files -z` at `--repo`, so an untracked or ignored machine-local file stays out of the review) into shards of ≤20000 lines, each shard is processed by its own parallel subagent (reviewer or auditor) and writes one findings file. The result is produced by the deterministic `scripts/merge_findings.py` (deduplication, sorting by severity, merged verdict), and the canonical review gate is applied to the MERGED findings, not to individual shards. A regular `implement` task is reviewed by diff and needs no sharding.
<!-- factory-rule: shard-protocol end -->

## verified-acceptance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: verified-acceptance begin -->
**Verified acceptance (canonical wording):** acceptance is machine-verifiable — `scripts/verify_acceptance.py` actually executes the criteria with `verify` and writes exit codes and output excerpts into `.code-factory/state/acceptance.md`. Exit 0 is possible only on SUCCESS: at least one criterion with `verify`, all criteria that carry `verify` are MET, baseline proven; criteria without `verify` are marked `derived`/`unverified` and are not evidence. STALE evidence or a degraded baseline lowers the verdict to DEGRADED; SUCCESS without regression evidence is impossible.
<!-- factory-rule: verified-acceptance end -->

## evidence-ledger
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: evidence-ledger begin -->
**Evidence ledger and quotes (canonical wording):** every piece of evidence (baseline, tests, review) is signed with the working-tree fingerprint via `scripts/evidence_ledger.py` and is accepted only with FRESH status; STALE evidence (files changed after signing) does not count as acceptance. Every quote from the reviewer, diagnostician or advisor is re-checked verbatim by `scripts/verify_quotes.py` (exact substring, only CRLF→LF is normalized). An unconfirmed quote is marked UNTRUSTED and does not affect the verdict.
<!-- factory-rule: evidence-ledger end -->

## preflight
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md
<!-- factory-rule: preflight begin -->
**Environment pre-flight (canonical wording):** before the first commands the factory probes the real environment via `scripts/factory_preflight.py --out .code-factory/state/preflight.json` — a working python command (`python`/`python3`/`py`), git, bash/sh, OS and `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`. Further commands are emitted for the FOUND capabilities, so a guess about `python3` on Windows does not break the run. A missing secondary model does not stop the run, it yields `models_warning` in pipeline.yaml and report.md.
<!-- factory-rule: preflight end -->

## documentation
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
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
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/skills/code-factory/references/code-review.md
<!-- factory-rule: vaccination begin -->
**Vaccination (canonical wording):** a bug found AFTER the task's acceptance first gets a regression test that reproduces it (the test fails on the current code), and only then the fix. A fix without a reproducing test is not accepted, and the test itself stays in the suite as a vaccine against recurrence. The code reviewer checks that every post-acceptance fix has such a test and counts its absence as a finding of severity ≥ major.
<!-- factory-rule: vaccination end -->

## run-id
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: run-id begin -->
**Run identifier (canonical wording):** at the start of a run `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` is computed deterministically (`scripts/run_id.py`) and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` and the run's memory entry. One run — one identifier; it links the artifacts to each other. `scripts/run_id.py check` finds the run's artifacts without a `run_id` and lists them.
<!-- factory-rule: run-id end -->

## memory-provenance
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: memory-provenance begin -->
**Memory entry provenance (canonical wording):** an entry counts as a v2-format entry if its `factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a provenance marker) — so a half-migrated entry is checked too; such an entry must carry a `run_id` in the format `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) and provenance markers in the `decisions` and `results` fields: `[verified: <evidence>]` — the claim is confirmed by run evidence (log, acceptance, quote), `[inferred]` — an inference without direct evidence. A v2-format entry without a `run_id` or without markers in these fields is a format error (`memory_project.py check`, `check_factory_model.py`), whereas entries written by a factory no newer than 12.8.0 and carrying no v2 fields, and legacy entries without `project:`, yield only a warning. The `[verified: ...]` marker must reference concrete evidence (command/test/log); the validators check the marker's presence and form.
<!-- factory-rule: memory-provenance end -->

## memory-actuality
carriers: .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/planning-guide.md
<!-- factory-rule: memory-actuality begin -->
**Memory actuality (canonical wording):** at the start of a run the open backlog is reconciled with the tree (`memory_project.py backlog --repo <root>`, a fold of every follow_up=true/severity=critical item over the journal history); at the end of a run each item is either closed with a `closed:` block carrying a mandatory `evidence:` in the run entry, or carried in `unfinished` with a `reason:` — a carried item is legal and the finish gate accepts it, while an item mentioned in no current record is a fatal silent disappearance, so `backlog --check` exits 1 for a disappeared item, a carried item without a reason, a closing without `evidence:` and a closing that names no existing item, and exits 0 when nothing disappeared. `memory_project.py check --run-id <run_id>` is the finish command: it requires exactly one record for the run. The summary's `## Current state` is actualized by EVERY run, not only at compaction — its version, open-backlog and closed counts and test-file count are compared with reality (`--strict`, implied by `--run-id`, turns a divergence into an error; a plain check reports it as a warning).
<!-- factory-rule: memory-actuality end -->

## plan-committee
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/skills/code-factory/references/planning-guide.md; .agents/README.md
<!-- factory-rule: plan-committee begin -->
**Committee on double plan rejection (canonical wording):** if the user rejected the plan twice (hitl, Revise branch), the main agent launches a second independent planner subagent from a contrasting model family, which builds an alternative plan from the same task and the user's accumulated remarks; the deterministic `scripts/plan_arbiter.py` (stdlib) compares both plans by machine-readable sections (DAG tasks, verify commands, risks, business tests) and forms a merged variant with a list of discrepancies; the user is presented with the merged plan and the discrepancies, and further edits are made against it.
<!-- factory-rule: plan-committee end -->

## no-shared-tree-git-mutations
carriers: .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/handoff-briefing.md; .agents/agents/sub-agents/coder.md; .agents/agents/sub-agents/gui-expert.md; .agents/agents/sub-agents/refactorer.md
<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

## english-only
carriers: .agents/README.md; .agents/agents/code-factory.md; .agents/skills/code-factory/SKILL.md; .agents/skills/code-factory/references/planning-guide.md; .agents/agents/sub-agents/coder.md; .agents/agents/sub-agents/gui-expert.md; .agents/agents/sub-agents/tester.md; .agents/agents/sub-agents/documenter.md
<!-- factory-rule: english-only begin -->
**English-only (canonical wording):** every artifact the factory produces is written in English only: code and comments of target projects, documentation, docstrings, commit messages, reports (`.code-factory/report*.md`, logs), memory entries, plans and subagent briefings. The factory accepts a task file in any language, but everything it produces from it is English. EXCEPTION: live communication with the user stays in the user's business language, and HISTORY is never rewritten — `CHANGELOG.md` and memory records written before this rule are frozen by `memory/.english-freeze` (one record heading per line) and are never edited; every NEW memory record is gated by `scripts/check_english_only.py`, whose memory pass runs by default over v2 records that are not frozen (`--no-memory` is the one documented escape).
<!-- factory-rule: english-only end -->

## destructive-action-gate
carriers: .agents/skills/code-factory/SKILL.md; .agents/agents/code-factory.md; .agents/README.md
<!-- factory-rule: destructive-action-gate begin -->
**Destructive-action gate (canonical wording):** before the main agent runs a destructive shell action — `git push`, `git reset --hard`, `git clean`, a `git checkout`/`git restore` of paths, `rm -rf`, or a branch deletion — it classifies the command FIRST with `python .agents/skills/code-factory/scripts/action_gate.py check --action "<command>" --scope <resolved repo_path> --mode <hitl|auto>`: `ALLOW` proceeds, `CONFIRM` proceeds only on an explicit user decision (in `auto` mode the factory proceeds and records the assumption), and `HARD_DENY` is never executed. The classification is the MAIN agent's step because only the main agent mutates the shared working tree; a subagent never runs these commands at all (rule `no-shared-tree-git-mutations`). The rollback procedure classifies its own `git checkout`/`git reset`/`rm` the same way before restoring the tree, and a CONFIRM or HARD_DENY answer is not a reason to skip the classification of the next command.
<!-- factory-rule: destructive-action-gate end -->

# Code Factory (for Kimi Code CLI)
<!-- code-factory-version: 12.12.0 -->

An autonomous code-writing factory. It takes a business task from a user who does not
know programming, analyzes the project, plans changes, clarifies only business logic,
gets the plan approved, and then writes the code itself, runs
integration / regression / business tests with automatic rollback on any failure,
performs a mandatory code review before acceptance, and verifies the acceptance criteria.

Supports **any languages** (the stack is detected automatically) and works with existing
projects or creates projects from scratch.

## Structure

```
.agents/
├── README.md                        # this file
├── skills/
│   └── code-factory/
│       ├── SKILL.md                 # Flow skill — main orchestrator (type: flow)
│       ├── references/
│       │   ├── planning-guide.md    # project analysis, DAG plan, business-test questions
│       │   ├── verification-strategy.md  # integration/regression/business tests + rollback
│       │   ├── error-routing.md     # deterministic error routing + Diagnostician
│       │   ├── tech-stack-detection.md  # stack detection + Scout pipeline
│       │   ├── code-review.md       # static quality gate: checklist, severity, verdict
│       │   ├── providers.md         # model routing for Kimi (K3) and Qwen
│       │   ├── refactoring.md       # refactor task type: freeze-functionality invariant
│       │   ├── security-audit.md    # security_audit task type: adaptive full audit
│       │   ├── documentation.md     # documentation subagent: methodology + validator
│       │   ├── handoff-briefing.md  # mandatory subagent briefing template (files by path)
│       │   ├── reference-docs.md    # reference_docs/reference_skills: skill base + matrix
│       │   ├── factory-rules.md     # single rulebook of mandatory rules + carriers line
│       │   └── error-patterns.default.json  # snapshot of the error-routing tables: defaults on which the project's project-learned overlay is layered
│       ├── scripts/
│       │   ├── gen_code_changes_report.py  # report_code_changes.md generator (before→after diff)
│       │   ├── test_gen_code_changes_report.py  # self-test of the report generator (argparse, UTF-8)
│       │   ├── project_fingerprint.py      # two-level fingerprint: structural + content
│       │   ├── check_factory_model.py      # check: 8 sections + both fingerprints + memory format (factory root — SKIP)
│       │   ├── test_factory_model.py       # self-test of the model scripts
│       │   ├── memory_project.py           # project memory: init/name/check/rename/backlog/compact-check/validate-fix-tasks
│       │   ├── test_memory_project.py      # self-test of the project memory script
│       │   ├── check_factory_rules.py      # reconciliation of rulebook and carriers: factory-rule blocks byte-for-byte
│       │   ├── test_factory_rules.py       # self-test of the rule reconciliation
│       │   ├── check_english_only.py       # English-only gate: no Cyrillic left in the tracked files outside the exceptions CHANGELOG.md/memory/task*.yaml/.code-factory
│       │   ├── test_check_english_only.py  # English-only gate self-test
│       │   ├── check_translation_structure.py # translation skeleton comparator: only the text may change, never the structure (--allow-added-rule)
│       │   ├── test_check_translation_structure.py # translation skeleton self-test
│       │   ├── run_id.py                   # run run_id: gen from task.yaml / check — artifacts without run_id
│       │   ├── test_run_id.py              # run_id self-test
│       │   ├── error_router.py             # JSON-first error classification: classify/merge/export-defaults; the project's project-learned patterns ON TOP of defaults (a broken auto-discovered file — warning + defaults)
│       │   ├── test_error_router.py        # error router self-test
│       │   ├── calibrate_reviewer.py       # reviewer golden-set calibration: precision/recall/accuracy
│       │   ├── test_calibrate_reviewer.py  # reviewer calibration self-test
│       │   ├── precedent_index.py          # FTS5 precedent index: memory + codebase (build/query)
│       │   ├── test_precedent_index.py     # precedent index self-test
│       │   ├── test_prompt_structure.py    # self-test: append-only prompt structure
│       │   ├── test_env_propagation.sh     # self-test: model env-flag propagation
│       │   ├── validate_documentation.py   # documentation validator (documentation subagent)
│       │   ├── test_validate_documentation.py  # documentation validator self-test
│       │   ├── skill_base.py               # persistent skill base (reference_docs)
│       │   ├── test_skill_base.py          # skill base self-test
│       │   ├── version_manager.py          # single version source: get/bump/sync/validate/set/suggest
│       │   ├── test_version_manager.py     # version script self-test (≥12 cases)
│       │   ├── validate_mermaid.py         # structural Mermaid diagram validator
│       │   ├── test_validate_mermaid.py    # Mermaid validator self-test
│       │   ├── repo_inventory.py           # repository inventory + shards (shard protocol)
│       │   ├── test_repo_inventory.py      # inventory self-test
│       │   ├── merge_findings.py           # deterministic merge of shard findings + verdict
│       │   ├── test_merge_findings.py      # findings merge self-test
│       │   ├── plan_arbiter.py             # merge of two competing plans + list of discrepancies
│       │   ├── test_plan_arbiter.py        # plan arbiter self-test
│       │   ├── repo_stats.py               # code-based repository analyses: sizes/entry-points/imports
│       │   ├── test_repo_stats.py          # analyses self-test
│       │   ├── log_tail.py                 # counters + tail of a long log (without pulling it into context)
│       │   ├── test_log_tail.py            # log tail self-test
│       │   ├── factory_preflight.py        # environment pre-flight (python/python3/py etc.)
│       │   ├── test_factory_preflight.py   # pre-flight self-test
│       │   ├── action_gate.py              # destructive actions: ALLOW/CONFIRM/HARD_DENY (mutating git stash → CONFIRM, `stash list/show` → ALLOW)
│       │   ├── test_action_gate.py         # action gate self-test (+ --help/usage under cp1251)
│       │   ├── task_graph.py               # on-disk task graph: create/claim/complete/ready/list
│       │   ├── test_task_graph.py          # task graph self-test
│       │   ├── evidence_ledger.py          # evidence ledger with FRESH/STALE signatures
│       │   ├── test_evidence_ledger.py     # evidence ledger self-test
│       │   ├── verify_acceptance.py        # machine verification of acceptance criteria (anti-tautology)
│       │   ├── test_verify_acceptance.py   # acceptance check self-test
│       │   ├── verify_quotes.py            # verbatim quote check of evidence quotes (Evidence-Preserving Reducer)
│       │   ├── test_verify_quotes.py       # quote check self-test
│       │   ├── test_review_gate.py         # canonical review gate self-test (5 documents)
│       │   └── test_windows_scripts.py     # Windows deployment/launch scripts self-test
│       └── assets/
│           └── task-template.yaml   # business task template
└── agents/
    ├── code-factory.md              # main agent (Kimi Code 0.34+, --agent-file Markdown)
    └── sub-agents/
        ├── analyzer.md              # subagent: project analysis (read-only)
        ├── planner.md               # subagent: independent alternative plan (committee, read-only)
        ├── coder.md                 # subagent: code implementation
        ├── tester.md                # subagent: tests and result verification
        ├── diagnostician.md         # subagent: deep error analysis (read-only)
        ├── advisor.md               # subagent: second opinion on an error after the Diagnostician
        ├── code-reviewer.md         # subagent: static code review (read-only)
        ├── refactorer.md            # subagent: refactoring without behavior changes
        ├── security-auditor.md      # subagent: security audit (read-only)
        ├── documenter.md            # subagent: documentation of changed files (secondary)
        └── skill-manager.md         # subagent: skill base management (reference_docs)
```

The factory's runtime state lives in `.code-factory/` inside the project (not committed):
`state/` (task, plan, pipeline.yaml, acceptance.md, evidence ledger, task graph,
FTS5 precedent index `precedents.db`),
`backups/` (backups of modified files), `manifest.json` (list of changed/created files),
`logs/` (errors, test results, code review, shard findings).
<!-- factory-rule: run-id begin -->
**Run identifier (canonical wording):** at the start of a run `run_id = YYYYMMDD-<sha256(task.yaml)[:8]>` is computed deterministically (`scripts/run_id.py`) and stamped into `.code-factory/state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md` and the run's memory entry. One run — one identifier; it links the artifacts to each other. `scripts/run_id.py check` finds the run's artifacts without a `run_id` and lists them.
<!-- factory-rule: run-id end -->
Each run gets a deterministic `run_id` = `YYYYMMDD-<sha256(task.yaml)[:8]>` (the
`run_id.py gen --task .code-factory/state/task.yaml` script at the start of the run) and stamps it into
`state/pipeline.yaml`, `state/acceptance.md`, `logs/*.md`, `report.md`, and the run's memory entry;
`run_id.py check --dir .code-factory` lists the run's artifacts that lack a `run_id`. Format of the
WIP checkpoint `state/pipeline.yaml`: required keys `run_id`, `phase`, `status`
(`ok|failed|in_progress`), `updated_at`; optional `files_touched`, `pending_decision`,
`resume_hint`, `retry_counters`, `models_used` (validated by `scripts/check_factory_model.py`;
missing file — SKIP; the optional list/mapping may be empty: `files_touched: []`).

The portable long-term memory lives in the committed `memory/` directory of THE project named in the
task's `repo_path` (NOT in `.gitignore`): `memory/change-log.md` (append-only run journal, one
entry per task) and `memory/summary.md` (condensed summary). The `memory/` directory is created AT THE
DEPLOYMENT ROOT — the directory passed to `prepare_factory.sh` (on Windows — `prepare_factory.cmd`, which
runs `prepare_factory.ps1`); the base project name at deployment = basename of that directory,
and the factory is launched from it via `./start.sh` (Git Bash/Linux) or `start.cmd` (Windows). One
memory belongs to exactly one project: every new journal entry
carries the `project: <project name>` marker, and the summary declares `project:`/`repo_path:` right after the
canonical marker; entries without `project:` are legacy, and entries from different projects in one journal are an
error (`check_factory_model.py`, `memory_project.py check`). If the task's `repo_path` points to a
SUBDIRECTORY of the deployment root, the project name = basename of the resolved `repo_path`, and the main agent
creates the memory explicitly: `memory_project.py init --repo <deployment root> --project <basename
of the resolved repo_path>`. The only writer is the main agent at the end of each task; it is read
by the main agent/planner/analyzer at the start and by other roles as needed.
<!-- factory-rule: memory-ownership begin -->
**Memory ownership (canonical wording):** one memory belongs to exactly one project — the one named in the task's `repo_path`; the `memory/` directory lives at the DEPLOYMENT ROOT, the base project name = basename of the resolved `repo_path` and is fixed in the summary's `project:` declaration. The only writer is the main agent: one entry in `memory/change-log.md` per run, compaction into `memory/summary.md` at the 50-entry threshold (the last 20 remain, severity=critical and follow_up=true items are always preserved). Entries from different projects in one journal are an error (`check_factory_model.py`, `memory_project.py check`), entries without `project:` are legacy (a warning, not an error). The development history of the factory itself never enters the target project's memory.
<!-- factory-rule: memory-ownership end -->
<!-- factory-rule: memory-provenance begin -->
**Memory entry provenance (canonical wording):** an entry counts as a v2-format entry if its `factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a provenance marker) — so a half-migrated entry is checked too; such an entry must carry a `run_id` in the format `YYYYMMDD-<8 hex>` (`scripts/run_id.py`) and provenance markers in the `decisions` and `results` fields: `[verified: <evidence>]` — the claim is confirmed by run evidence (log, acceptance, quote), `[inferred]` — an inference without direct evidence. A v2-format entry without a `run_id` or without markers in these fields is a format error (`memory_project.py check`, `check_factory_model.py`), whereas entries written by a factory no newer than 12.8.0 and carrying no v2 fields, and legacy entries without `project:`, yield only a warning. The `[verified: ...]` marker must reference concrete evidence (command/test/log); the validators check the marker's presence and form.
<!-- factory-rule: memory-provenance end -->
<!-- factory-rule: memory-actuality begin -->
**Memory actuality (canonical wording):** at the start of a run the open backlog is reconciled with the tree (`memory_project.py backlog --repo <root>` — a fold of all follow_up=true/severity=critical over the journal history); at the end of a run every item is either closed with a `closed:` block with a mandatory `evidence:` in the run entry, or stays in `unfinished` with a reason — an item cannot disappear without evidence of closing: `backlog --check` gives exit 1 for open items, closing without `evidence:` and closing a nonexistent item. The `summary.md` summary (`## Current state`) is actualized by EVERY run, not only at compaction; a divergence between the version it declares and VERSION is a mechanism warning.
<!-- factory-rule: memory-actuality end -->
A v2-format entry carries `run_id: <YYYYMMDD-8hex>` and provenance markers `[verified: <evidence>]` /
`[inferred]` in the `decisions` and `results` fields. An entry counts as v2 if its
`factory_version` is newer than 12.8.0 OR it already carries a v2 field (`run_id` or a marker): for it,
a missing `run_id` (or a malformed `run_id`) or a missing marker is a format error, whereas entries
written by a factory no newer than 12.8.0 without v2 fields, and legacy entries without `project:`, produce only a
warning.

## Launch (Kimi Code 0.34+, Node)

Preparation and launch are a single action. First prepare the project:

```bash
./prepare_factory.sh /path/to/your-project
```

The script copies the factory, configures `.gitignore`/git, and creates a `start.sh` launcher in the project
(with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` already set in it). Then — just launch:

```bash
cd /path/to/your-project
./start.sh                 # opens Kimi Code; in the chat: /skill:code-factory
./start.sh --auto          # fully autonomous mode
```

No additional `export` commands need to be memorized.

### Windows (without Git Bash)

The same one-action preparation via `prepare_factory.cmd`: it invokes `prepare_factory.ps1`
(the Windows version of the deployer; PowerShell ships with Windows) and forwards its exit code. The script
copies the factory, configures git/`.gitignore`, creates the `start.cmd` (Windows) and
`start.sh` (Git Bash/Linux) launchers in the project, and prints a readiness report:

```bat
rem prepare the project (copies the factory, configures git/.gitignore, and creates the launchers)
prepare_factory.cmd C:\work\my-project

rem launch in a single action
cd C:\work\my-project
start.cmd
rem in the chat: /skill:code-factory

rem fully autonomous:
start.cmd --auto
```

Python is not required for deployment: without it, the long-term memory step (`memory/`) degrades with a
clear warning, the deployment still completes successfully, and the factory will create the memory on
first access to the project. The factory itself uses Python for the memory and version scripts
(`memory_project.py`, `version_manager.py`, etc.).

The Windows launchers get CRLF on checkout regardless of the `core.autocrlf` setting: the `.cmd`
and `.ps1` files are marked in `.gitattributes` as `text eol=crlf` (the same protection as
`error-patterns.default.json` with `eol=lf`), so `.cmd`/`.ps1` look identical on Linux/Windows
and `cmd.exe` does not trip over LF line endings.

A legacy code page on the console (cp866/cp1251) does not break the factory CLI: every argparse script in
`scripts/*.py` first reconfigures its stdout/stderr to UTF-8
(`stream.reconfigure(encoding="utf-8", errors="replace")` under try/except), so `--help` with
non-ASCII characters (`→`, `—`, Cyrillic) prints in full instead of crashing with a `UnicodeEncodeError`
traceback; if the stream cannot be reconfigured (old interpreter, substituted stream),
`errors="replace"` keeps printing from failing. The argparse contract stays standard: `--help` → exit 0,
usage error → exit 2, never a traceback. Self-tests pin this guarantee
(`test_action_gate.py` — the `--help`/usage case under `PYTHONIOENCODING=cp1251`,
`test_gen_code_changes_report.py`).

Or manually, without a launcher:

```sh
kimi --agent-file .agents/agents/code-factory.md "Read task.yaml and solve the task"
```

Models: `default_model` and `[secondary_model]` in `~/.kimi-code/config.toml`; for subagents —
`model_preference: primary|secondary` in the `.md` files. Splitting subagent models
requires `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — the `start.sh`/`start.cmd` launcher sets it itself.

## AGENTS.md and long-term memory

The factory itself keeps the project's `AGENTS.md` an up-to-date single source of truth:

- it generates exactly 8 `##` sections (Project Overview, Technology Stack, Architecture Overview,
  Directory Structure, Key Configuration Files, Build & Run Instructions,
  Dependencies & Integrations, Known Constraints & Limitations) and embeds a
  deterministic TWO-LEVEL fingerprint — structural + content — into the first line:
  `<!-- code-factory-fingerprint: <64-hex> content: <64-hex> -->`;
- the fingerprint is computed by `scripts/project_fingerprint.py --all`: the structural level —
  stack manifests, CI configs, README, directory list; the content level — SHA-256 of the contents
  of the tracked working-tree files with CRLF→LF normalization (the factory's own artifacts are
  excluded at both levels). The content level reads the working tree, so unstaged edits are
  visible to it, and only untracked files stay outside the hash — it warns about this rather than staying
  silent: `--content`/`--all` print a note to stderr, and `check_factory_model.py` prints a warning
  (hashes and exit codes do not change; `git add` brings an untracked file into the hash). If BOTH match,
  analysis/Scout and regeneration are skipped; if either one differs, AGENTS.md is regenerated (edits
  deeper than the first level are seen by the content level);
- it is updated at two points: the start of a task (external changes) and the end of a task (the factory's own
  changes), after which it is committed; the factory produces a good AGENTS.md itself, with no
  separate init step.

The portable memory in `memory/` (committed, not ignored) is the memory of the TARGET project from the
task's `repo_path`, not the history of the factory's development. The `memory/` directory is created AT THE
DEPLOYMENT ROOT (the one passed to `prepare_factory.sh`, or on Windows — `prepare_factory.cmd`);
the base project name at deployment = basename of that directory; with a `repo_path` in a SUBDIRECTORY
of the deployment root, the project name = basename of the
resolved `repo_path`. Files: `change-log.md` (run journal, one entry per task,
with the `project: <project name>` marker mandatory for new entries) and `summary.md` (summary with the
`project:`/`repo_path:` declaration right after the canonical marker; journal compaction at the
50-entry threshold).

The journal is read together with a reconciliation against the tree: `memory_project.py backlog --repo <deployment
root>` folds the open items (`follow_up=true`/`severity=critical`) across the ENTIRE journal
history, and at the end of a run each item is either closed with a `closed:` block with a mandatory
`evidence:`, or remains in `unfinished` with a reason — an item cannot disappear without proof of
closure. `memory_project.py backlog --check` exits 0 only with `open: 0`; the
`## Current state` section of the summary is actualized by EVERY run, not only at compaction. On first
access to a project, if `memory/` is missing, it is created with the command
`python .agents/skills/code-factory/scripts/memory_project.py init --repo <deployment root>
--project <basename of the resolved repo_path>` (the name is fixed in the summary's `project:` declaration).
Model check — the `scripts/check_factory_model.py` script (8 sections + fingerprint + journal format);
self-test — `scripts/test_factory_model.py`; memory ownership — `memory_project.py
check`. On the FACTORY'S OWN ROOT the script works without the `--memory-only` flag: it auto-detects a
hand-authored `AGENTS.md` by THREE signals — the first line has NO `code-factory-fingerprint` marker,
but DOES have the factory's own `code-factory-version` marker, and
`.agents/skills/code-factory/SKILL.md` is deployed alongside — and prints `SKIP` with an explanation: this is not an error, the memory and
WIP checkpoint are checked as usual. For target projects the behavior is unchanged: the skill is deployed by
`prepare_factory` into EVERY project, so its presence alone is not enough — an AGENTS.md without a fingerprint
remains an error, and a stale fingerprint remains an error even at the factory root.

## Business task format

The minimal format is free text. The recommended one is `task.yaml` (see the template in
`.agents/skills/code-factory/assets/task-template.yaml`):

```yaml
title: "The strategy does not generate signals for CNY"
repo_path: ./repo            # only for existing projects
description: |
  Describe the problem in business terms, without technical details.
user_story: |                # optional, but recommended
  As a trader, I want signals for CNY so that I can trade a fractional instrument like Si.
mode: hitl                   # hitl (default) | auto
task_type: implement         # implement | review | refactor | security_audit
acceptance_criteria:         # a criterion may optionally have verify: <command> and derived: true
  - "The strategy generates at least 5 LONG/SHORT signals for CNY"
  - criterion: "Behavior for the Si instrument is unchanged"
    verify: "python -m pytest -q tests/test_si_regression.py"
business_tests:              # optional: scenario, configs, and expected business results
  - scenario: "Run the strategy on CNY data"
    config: "path/to/config.toml"
    expected_results: "At least 5 LONG/SHORT signals and a positive equity curve"
```
There is no `priority` field — all tasks are processed with the highest priority by default.
`business_tests` is read in Phase 0 together with the task; if the field is absent, the factory clarifies the scenario,
configs, and expected business results with the user at the planning stage (hitl).
<!-- factory-rule: task-format begin -->
**Task format (canonical wording):** a task carries `title`, `repo_path`, `description`, optionally `user_story`, `mode` (`hitl`|`auto`), `task_type` (`implement`|`review`|`refactor`|`security_audit`), `acceptance_criteria` (a criterion may carry `verify: <command>` and `derived: true`), `business_tests` (scenario, configs, expected business results), `commit_exclude`, `models`, `reference_docs`, `reference_skills`. There is NO `priority` field — all tasks are high by default, the factory does not prioritize them. A missing required field is a task parsing error, not a reason to guess it mid-run.
<!-- factory-rule: task-format end -->

`task_type: review` — a "do a code review of existing code" task: the factory runs the
reviewer over **all** the code at the start, and its findings become the work plan.

`task_type: refactor` — reducing technical debt/duplication/simplifying architecture **without changing
behavior**: 100% of the existing tests must pass unchanged; any behavior change is a
critical error and an automatic rollback (see `references/refactoring.md`).

`task_type: security_audit` — a full adaptive cybersecurity audit of the project: the factory itself
detects the artifact types (code, infrastructure, containers, network) and runs only the
relevant checks. The result is reports + a generated fix-task file. The factory does
NOT fix vulnerabilities itself (see `references/security-audit.md`).

## Modes

- **hitl (default)** — the factory asks the user for the business scenario, the run
  configs, and the expected business results, then presents the plan for approval.
- **auto** — the factory makes reasonable assumptions (recording them in the plan as assumptions) and
  works without questions.

In hitl the user can reject the plan: the FIRST rejection sends the plan back for revision; the second
(double) one launches a committee — a second independent planner subagent (`sub-agents/planner.md`,
from a contrasting model family; it does not see the rejected plan) and the deterministic
`scripts/plan_arbiter.py` (`--plan-a` / `--plan-b` / `--out`), which merges both plans by their
machine-readable sections (`## Tasks (DAG)`, `## Risks`, `## Business tests`) and prints a list of
discrepancies; the user is presented with the merged plan, and further edits are made against it.
<!-- factory-rule: plan-committee begin -->
**Committee on double plan rejection (canonical wording):** if the user rejected the plan twice (hitl, Revise branch), the main agent launches a second independent planner subagent from a contrasting model family, which builds an alternative plan from the same task and the user's accumulated remarks; the deterministic `scripts/plan_arbiter.py` (stdlib) compares both plans by machine-readable sections (DAG tasks, verify commands, risks, business tests) and forms a merged variant with a list of discrepancies; the user is presented with the merged plan and the discrepancies, and further edits are made against it.
<!-- factory-rule: plan-committee end -->

> **Important:** `mode: auto` controls ONLY the factory's business questions and plan approval.
> It does NOT disable the Kimi Code CLI permission prompts for tool execution (Bash, Write,
> Edit, etc.). For a fully autonomous run (no permission prompts), launch
> `kimi --auto` (or `--yolo`), or set `default_permission_mode = "auto"` in
> `~/.kimi-code/config.toml`.

## Code review (mandatory gate)

Before acceptance, every task passes through the `factory-code-reviewer` subagent:

- **regular task** — the reviewer examines the **diff** of the changes (not the whole project);
- **`task_type: review` / `security_audit`** — a review/audit of **all the code** in SHARDS at the start:
  `scripts/repo_inventory.py shards --max-lines 20000` → one subagent per shard →
  a deterministic merged verdict by `scripts/merge_findings.py` (each subagent
  sees only the files of its own shard); the findings of a review task become the plan.

A verdict of `approve` → the task proceeds to acceptance; `request_changes` → a rework list
is produced for the coder, and after the fixes the tests and the review are run again. When the budget is exhausted, the
auto-escape policy applies: in auto mode only a conditional pass is allowed, with the criterion marked
`unverified_review` (see the canonical block below); in hitl mode the factory stops.

**Severity boundary and calibration.** Each finding is classified on the
`critical/major/minor/nit` scale; where the critical/major boundary lies and how findings are formatted is set by
`references/code-review.md` §3: critical damages EXISTING behavior (crash/bug on an
existing path, data corruption, security, a weakened check); major leaves a
NEW path unprotected or loses test coverage without replacement; one root cause — one finding. §7 requires
periodic calibration of the reviewer on the golden set (`scripts/calibrate_reviewer.py`): after every
edit of the reviewer prompt and at least once per 5 review runs, with soft thresholds of verdict
accuracy 100% and macro precision ≥ 0.8 (run 20260923-3540d5dc: accuracy 7/7, macro precision
1.000, recall 1.000; previous run 20260923-bcbe68b3: macro precision 0.619 → 0.857).
A neutral renaming between equally clear names (`result` → `res` in a short function) deserves
silence, not a nit: a naming finding is warranted only when the new name is materially less clear or
misleading (§3, "Reporting discipline"). A missed defect and severity inflation are calibration
errors, and they are cured by editing the reviewer prompt, not the golden set.

<!-- factory-rule: review-gate-policy begin -->
**Review gate (canonical wording):** a task is NOT accepted while the reviewer has open severity=critical findings (verdict `request_changes` with open critical findings). The reviewer budget = 2 iterations. If the budget is exhausted and critical findings remain: in hitl mode the factory STOPS and asks the user; in auto mode only a conditional pass is allowed — the corresponding criterion is marked `unverified_review` in `.code-factory/state/acceptance.md`, and the unresolved findings go into `.code-factory/report.md` (unresolved findings section), never silently. A full SUCCESS with open critical findings is impossible.
<!-- factory-rule: review-gate-policy end -->

Acceptance is additionally verified by machine: criteria with `verify` are executed for real
(`scripts/verify_acceptance.py` → `.code-factory/state/acceptance.md`), and SUCCESS (exit 0)
requires at least one criterion to carry `verify`, all criteria with `verify` to be MET, and the
regression baseline to be proven. A run without a single `verify` or with stale
evidence gets DEGRADED, not SUCCESS: the FRESH/STALE evidence signatures are computed by
`scripts/evidence_ledger.py`, so a green log from an old revision does not count as acceptance.
<!-- factory-rule: verified-acceptance begin -->
**Verified acceptance (canonical wording):** acceptance is machine-verifiable — `scripts/verify_acceptance.py` actually executes the criteria with `verify` and writes exit codes and output excerpts into `.code-factory/state/acceptance.md`. Exit 0 is possible only on SUCCESS: at least one criterion with `verify`, all criteria MET, baseline proven; criteria without `verify` are marked `derived`/`unverified` and are not evidence. STALE evidence or a degraded baseline lowers the verdict to DEGRADED; SUCCESS without regression evidence is impossible.
<!-- factory-rule: verified-acceptance end -->

## Change rollback and error routing

On the failure of any test, the factory does NOT roll back blindly:
1. **It classifies the error** deterministically (regex, ~90% of cases, 0 tokens) —
   compile→coder, missing file→BA, bad command→Planner, infrastructure→auto-fix,
   wrong results/unknown→Diagnostician (see `references/error-routing.md`). The pattern tables live
   in data: the project appends its own error families to `.code-factory/state/error-patterns.json`,
   and `error_router.py classify` tries them FIRST — project-first on top of the built-in snapshot
   (a matching `id` replaces the built-in row; a partial file loses nothing). A broken auto-discovered
   file does not bring routing down: a `warning:` to stderr and classification by defaults alone; an invalid
   file passed explicitly (`--project-patterns`) is a hard error (exit 2)
   (see `references/error-routing.md` §1.2).
2. **Rollback**: restores files from `.code-factory/backups/`, deletes the created files
   (per `manifest.json`), and returns the project to its pre-change state.
3. **Retry budgets**: coder=1, BA=2, Planner=2, Diagnostician=1, advisor=1, infrastructure=3,
   reviewer=2. On exhaustion — escalation to the Diagnostician (LLM analysis, writes
   `.code-factory/logs/diagnostic.md`), then to the Advisor (`factory-advisor`, a secondary model
   from a contrasting model family, read-only, budget 1; the route is decided by the machine-readable `agreement` field
   of the report — see `references/error-routing.md` §4.1).
4. **Human**: if the Advisor or Diagnostician recommends it — show the user and ask.
5. **FAILED**: only when all budgets are exhausted, with a full log in
   `.code-factory/logs/errors.md`. The factory never fails silently.
<!-- factory-rule: rollback-on-retry begin -->
**Rollback before retry (canonical wording):** every test or build failure is first routed deterministically (`references/error-routing.md`), then the state is rolled back: files are restored from `.code-factory/backups/`, factory-created files are deleted, the git state is brought back to the recorded one. Only after the rollback is the error handed to the executing role — otherwise the retry runs on an already corrupted state. Infrastructure auto-fixes (environment, dependencies) do not roll back code.
<!-- factory-rule: rollback-on-retry end -->
<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

Checkpoint/resume: after each phase, `.code-factory/state/pipeline.yaml` is written — on
restart the factory resumes from the same point.
<!-- factory-rule: checkpoint-resume begin -->
**Checkpoint/resume (canonical wording):** after every phase the main agent writes `.code-factory/state/pipeline.yaml` (phase, status, files touched, pending decision, resume hint, run_id, time) — the run state lives on disk, not in the context. On restart the factory reconciles the plan checkpoint and, if the task has not changed, continues from the RECORDED phase, not from the beginning. `resume` restores the retry counters, so exhausted budgets are not reset by a restart.
<!-- factory-rule: checkpoint-resume end -->

Final report: on completion (success or FAILED) the factory writes `.code-factory/report.md` —
a single self-contained file with the full history of the run (task, plan, changes, tests,
errors, diagnostics, code review, acceptance). Alongside it,
`.code-factory/report_code_changes.md` is generated — a visual "before → after" report of the changed lines
of the commit (by the `scripts/gen_code_changes_report.py` script, at no LLM cost). Forwarding both files
to the factory developer is enough for analysis — there is no need to read all of `.code-factory/`.

## Business tests

A business test = running the real (fixed/created) program with the user's configs and
verifying that the **business results** match the expected ones. The scenario, configs, and expected
results are clarified by the factory with the user at the planning stage (in hitl mode).

Practical techniques (proven on a real run):
- read `exit_results_path` from the config and check the generated reports (rows, columns);
- if the user says "wrong result — only N variants", verify that after
  the fix the number of unique result variants became GREATER than N (a result-difference check);
- distinguish "the filter works" from "broken": 0 trades with an unsuitable threshold is the norm; prove
  the filter works by rerunning with a threshold commensurate with the instrument's price;
- run business tests with exactly the commands the user provided (build + run);
- delete the run's side artifacts (results folders) after verification, or ignore them in git.

## Auto-documentation, debt, and version

**Auto-documentation**: after every successful `implement`/`refactor` run, the factory
invokes the `factory-documenter` subagent (secondary model). It takes the list of changed files
from `.code-factory/manifest.json` and brings the documentation in line with the code — only
doc comments and `.md` files, never code/tests/configs. The result is checked by the built-in
validator `scripts/validate_documentation.py` (budget 1 retry); on exhaustion the debt
is recorded in the run report and the factory continues. It is not invoked for `review`/`security_audit`.
<!-- factory-rule: documentation begin -->
**Documentation (canonical wording):** after every successful `implement`/`refactor` the main agent invokes the `factory-documenter` subagent (secondary) with the run's manifest; it updates ONLY doc comments and `.md` files and never code, tests or configs. It validates its work with `scripts/validate_documentation.py` with a budget of 1 retry; when the budget is exhausted, the documentation debt is recorded in the run report and the factory continues. Documentation is not invoked for `review`/`security_audit`.
<!-- factory-rule: documentation end -->

**"What is NOT implemented" memory**: every `memory/change-log.md` entry contains the
`project: <project name>` field, an `unfinished` section (an explicit "no unfinished items" marker or a
list of `item`/`reason`/`severity`/`follow_up` items), and the `factory_version` field. The main agent
fills these in without fail, even when there is no debt. Compaction preserves critical or
follow_up items.

**Reference skills**: the task fields `reference_docs` (`{path, skill}`) and `reference_skills`
(names) attach books/documents as reusable skills. The `skill-base/` base is persistent;
freshness is determined by the SHA256 hash of the source; management is done by the `factory-skill-manager` subagent
and the `scripts/skill_base.py` script. Skills enter the subagents' dynamic context via a
deterministic matrix (see `references/reference-docs.md`).

**Version (single source of truth)**: the `VERSION` file (one line X.Y.Z). After a successful
run, the version type is determined by a deterministic matrix (`scripts/version_manager.py suggest`),
the reviewer validates it (may override with an explanation), then `bump`/`sync` synchronizes the
version into README/CHANGELOG/AGENTS.md/SKILL.md/the manual, and `validate` checks it (exit 0).
`review`/`security_audit` do not change the version. The user does not need to update the version manually.
<!-- factory-rule: english-only begin -->
**English-only (canonical wording):** every artifact the factory produces is written in English only: code and comments of target projects, documentation, docstrings, commit messages, reports (`.code-factory/report*.md`, logs), memory entries, plans and subagent briefings. The factory accepts a task file in any language, but everything it produces from it is English. EXCEPTION: live communication with the user stays in the user's business language, and history (CHANGELOG and old memory entries) is never rewritten.
<!-- factory-rule: english-only end -->

## Models

The factory's roles use different models. Models are assigned per role via `model_preference`
(`primary|secondary`) in the `.md` subagents + `config.toml` (`default_model` + `[secondary_model]`).
Providers and families can be changed (deepseek, qwen, kimi/moonshot, etc.):
- CLI: `kimi -m <model>` or `/model` in a session;
- in the task: the `models:` field in `task.yaml` (see the template).

Kimi (K3) and Qwen support is additive: when a Kimi or Qwen model is specified, the factory itself
detects the vendor and routes requests to the corresponding API endpoint with the correct
authentication, without breaking already connected models. Details, configs, and error handling are in
`references/providers.md` and `references/error-routing.md` §1.1.

The main agent passes the model to each subagent explicitly: the `model:` argument of the Agent tool
is supported by the CLI — the model is taken from the task's `models` matrix under the generator≠judge rule
(coder/tester and reviewer/diagnostician/advisor come from different model families), while `model_preference`
(`primary|secondary`) in the `.md` subagents serves as a fallback for roles the task did not name.
The only exception where the matrix is NOT applied is the committee's second planner (double plan
rejection): the committee rule is stronger than the matrix, and its family is chosen deterministically —
contrasting with the first planner (`references/providers.md` §5.2).
The actual model is recorded in `.code-factory/state/pipeline.yaml` (`models_used`) and in
`report.md` (the "Models used" section). If after a run all roles in `pipeline.yaml` show the same
model, the models were not split. Splitting requires the flag
`export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — without it, coder/tester fall back to primary.
The factory checks this in pre-flight and writes `models_warning` to pipeline.yaml/report.md.
<!-- factory-rule: models-generator-ne-judge begin -->
**Models: generator ≠ judge (canonical wording):** the main agent passes the model explicitly in the Agent tool (`model:`) per the task's `models` matrix and the generator≠judge rule: coder/tester and reviewer/diagnostician/advisor are taken from different model families. `model_preference: primary|secondary` in a subagent's `.md` is only a FALLBACK for roles not named by the task. The actual role models are logged in `.code-factory/state/pipeline.yaml` (`models_used`) and in `report.md`; the secondary model works only with `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`, otherwise the factory writes `models_warning` and continues on primary.
<!-- factory-rule: models-generator-ne-judge end -->

Export the variable in the **same terminal** where `kimi` is launched, and **before** launching it.
If `kimi` is started from a new terminal, a launcher, or via `sudo`, the variable is lost and
the factory will see `unset` — this is a property of the launch environment, not a factory bug.

Recommended role mapping:
- primary (reasoning): main/planner, analyzer, diagnostician, reviewer;
- secondary (fast): coder, tester;
- planner-2 (committee on double rejection): a model from a family CONTRASTING with the planner
  (`sub-agents/planner.md`; `model_preference: secondary` is only a fallback), so that the second plan is
  truly independent rather than a retelling of the first.

## Prompt caching (DeepSeek)

Prompts are assembled append-only for DeepSeek's automatic context cache:
the static prefix (the subagent's system prompt, file context) always goes first; dynamic
data (turn history, error logs) goes strictly at the end. Changing the beginning/middle invalidates the cache.

## Commits

The factory commits changes to a feature branch. The `commit_exclude` field in the task allows
excluding files from the commit (for example, a personal strategy) — the factory may still
modify them (backups/tests/rollback), but they will not land in the git commit.

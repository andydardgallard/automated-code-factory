# Changelog

Все заметные изменения в проекте Autonomous Code Factory документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — на [Semantic Versioning](https://semver.org/lang/ru/).

## [12.15.0] — 2026-10-25

### Changed
- **A `task_type: review` run is report-only** (new canonical rule `review-report-only`, 5
  carriers). No review verdict, in either mode, reaches a node that starts a coder, writes a backup
  or edits a tracked file: both former write edges (`CRV0 -> G`, `CRV -> RCR`) now end at the new
  delivery node `RD`, and the acceptance-failure edge splits by task type — `X -->|No,
  implement/refactor| RR` for the coder route and `X -->|No, review/security_audit| XR`, a
  stop-and-ask decision point, for a report-only run. The deliverable is the report plus a generated
  follow-up task file (`.code-factory/review/fix-tasks.yaml`); a review's `verify:` criteria must
  hold on the unmodified tree. `security_audit`'s guarantee is untouched and not restated.
- **Model precedence is stated once and implemented once.** The task's `models:` matrix wins
  verbatim for every role it names (a generator/judge family collision is a WARNING, never a
  substitution); an unnamed role takes its model from the factory's default matrix, where the
  generator != judge rule is enforced as an ERROR naming the fix; the plan committee's second
  planner is the only override. `scripts/model_matrix.py` is the single implementation and
  `scripts/test_model_precedence.py` pins it.
- **Memory has one contract.** `memory_project.validate_memory` is the implementation;
  `check_factory_model.py` delegates to it and the six previously divergent axes (owner, record
  kind, required keys, `results` sub-keys, empty `project:`, `closed:` without `evidence:`) are
  asserted equal in both directions. `task_type: backlog` becomes a documented record kind with its
  own `results` contract, so the record the factory itself wrote is legal without rewriting history.
- **Memory ownership no longer depends on the folder name.** The summary declares
  `project_id` (the first 12 hex of the sha256 of the repository's root commit); a rename or a
  versioned copy keeps the memory valid, while a memory of a different repository is refused.
- **The English-only rule acts on new memory records.** The gate's memory pass runs by default over
  v2 records that are not listed in the new `memory/.english-freeze` (history) and over
  `memory/summary.md`; an internal reason the pass cannot run is exit 3, never a silent `ok`.
- `## Current state` is actualized every run and compared on the version, the open-backlog and
  closed counts and the test-file count — a warning under `check`, an error under `--strict`
  (implied by `run_id check`).
- The precedent index is a build product of the flow (`build`/`status`/`query --fresh`) instead of
  standing runtime state; `query --fresh` refuses a stale index with exit 3.

### Added
- `scripts/model_matrix.py` — the single model-precedence resolver (family table incl. DeepSeek,
  the two documented cases, the committee exception).
- `scripts/model_attribution.py` — derives the model actually served per role from the CLI session
  wire and cross-checks `models_used`: `match`/`mismatch` (exit 1)/`degraded` (exit 3).
- `scripts/review_followup_task.py` — deterministic merged-findings → follow-up task generator.
- `memory_project.py compact` — the real 50/20 compaction (critical and follow_up items and every
  folded closure survive, semantic pre-write verification, idempotent), invoked by the Finish node.
- `memory_project.py check --run-id/--strict/--allow-fresh`, duplicate-`run_id` detection, the
  carried-with-a-reason backlog semantics (`backlog --check` exits 0 when nothing disappeared).
- `version_manager.py` now validates and syncs the version in a Rust workspace/member `Cargo.toml`.
- `check_factory_rules.py`'s pass line no longer reads a count as a collection; `merge_findings.py`
  sorts shard ids numerically; `gen_code_changes_report.py` reports a bad `--commit` as one
  `error:` line instead of a traceback.
- Self-tests: `test_model_precedence.py`, `test_model_attribution.py`, `test_review_followup_task.py`,
  `test_review_report_only.py`, `test_security_audit_guarantee.py`, `test_flow_contracts.py`,
  `test_vaccination.py` (24 vaccines proven to fail on the pre-fix tree and pass here).

### Fixed
- `validate_documentation.py` no longer classifies a code line starting `*` or `|` as documentation
  and protects test files by name, not only by directory.
- `verify_acceptance.py` takes `--task-type`, so a review run's failed criterion is reported as an
  owner decision on the unmodified tree instead of a rework order.
- The task templates (`.example.task.yaml`, `assets/task-template.yaml`) state `repo_path` as
  required (except green-field), show the `verify:` / `derived: true` criterion forms, and describe
  a review run as report-only.

## [12.14.3] — 2026-10-17

### Fixed
- **`action_gate.py` — decoded PowerShell payloads are split with PowerShell's quote/backslash
  semantics** (critical, safety gate; backlog item 1). The recursive splitter of a decoded
  `powershell`/`pwsh` `-Command`/`-c` payload used POSIX backslash escapes, but PowerShell treats a
  backslash as a LITERAL character, so `pwsh -Command 'echo "\"; rm -rf /'` and
  `powershell -c 'echo "\"; git push origin main'` were ALLOWED although PowerShell closes the
  string before the `;` and really runs the destructive tail. Decoded PowerShell payloads are now
  split in PowerShell's own dialect (backslash literal, only doubled `''`/`""` escape), so both
  review vectors and their pwsh/powershell, -Command/-c and hitl/auto equivalents are HARD_DENY,
  balanced benign backslash/quote strings keep their previous ALLOW/CONFIRM result, and unreadable
  or ambiguous input CONFIRMs. The cmd.exe and POSIX splitters are untouched.
- **`action_gate.py` — launcher prefixes and `$(...)` substitutions can no longer hide a destructive
  command** (warning, safety gate; backlog item 2). `env`, `sudo` and `builtin` are transparent:
  their own options (separate or joined values), the `NAME=VALUE` assignments `env`/`sudo` document
  and the `--` option terminator — including after `builtin` (`builtin -- rm -rf /` is the deletion
  it really is) — are parsed, never executed, and the inner command is classified recursively at
  every supported nesting level, in either order with the shell wrappers. Readable `$(...)`
  substitutions are analyzed as commands the shell runs, nested substitutions included, inside
  POSIX and PowerShell double quotes; substitutions inside literal single quotes or behind an
  escaped `$` stay inert ALLOW. Unknown, unsupported or ambiguous syntax (`env -S`, a valued option
  without its value, `sudo -i`/`-s`, an unsupported `builtin` option such as `-v`, an unclosed or
  empty substitution, nesting beyond the depth limit) CONFIRMs instead of ALLOWing, and benign
  launchers/substitutions (`env python -m pytest`, `builtin -- echo hi`, `echo $(git status)`) stay
  ALLOW. No general shell evaluation was added and no launcher or substitution is executed to
  classify it.
- **`error_router.py` — the installer-side missing-Node line reaches the infrastructure route**
  (warning, deterministic routing; backlog item 3). `vendor_install()` in
  `chrome_devtools_mcp.py` reports `<node|npm> was not found on PATH: the pinned
  chrome-devtools-mcp@<version> cannot be installed ...`, which matched no I1 alternative and fell
  through to the diagnostician. Row I1 of `error-patterns.default.json` (and the byte-consistent
  `references/error-routing.md` cell) gained the installer alternative naming the pinned-package
  tail, so the REAL emitted line is classified BROWSER_TOOLCHAIN → infrastructure while a bare
  `... was not found on PATH` from an unrelated tool is not stolen, and the existing Web GUI probe
  route is unchanged.

### Tests
- Vaccination-first regressions for all three fixes: `test_action_gate.py` sections 22-27
  (PowerShell backslash matrix, launchers, substitutions, quoted control words, and the
  `builtin --` terminator with benign negative controls) and the REAL `vendor_install()` line in
  `test_error_router.py` were each observed failing on the pre-fix code and passing after it; no
  existing assertion was weakened.

## [12.14.2] — 2026-10-17

### Fixed
- **`action_gate.py` — PowerShell single-quoted `-Command` payloads are classified** (major, safety
  gate). `powershell`/`pwsh` with `-Command` (or its `-c` abbreviation) now rebuilds the command
  string with PowerShell's OWN tokenizer, where `'` is real quoting, so the payload is ONE argument
  and its inner text is classified as a POTENTIAL command: `pwsh -Command 'rm -rf /'`,
  `pwsh -Command 'Remove-Item -Recurse -Force C:\'` and `powershell -c 'git push origin main'` are
  the SAME class as their double-quoted and bare twins (HARD_DENY for a root deletion or a
  default-branch push, CONFIRM for in-scope destruction) instead of ALLOW. From bash the outer shell
  strips those quotes and pwsh really runs the text, from cmd.exe they are literal and pwsh prints a
  string — the gate cannot know the caller's shell, so it takes the fail-safe reading. A doubled `''`
  inside such a literal is ONE escaped quote (PowerShell's rule), and a payload whose own quoting
  never closes — including a doubled quote that lost its partner, as in
  `pwsh -Command 'echo ''; rm -rf /'`, which decodes to `echo '; rm -rf /` — is unreadable and
  CONFIRMs (mode mapping applied) instead of being called harmless. Benign inner text
  (`pwsh -Command 'Write-Host hi'`) stays ALLOW, so single quotes are not denied as a class. The
  exit-code contract (ALLOW 0, HARD_DENY 1, CONFIRM 2 in hitl / 0 in auto, journal failure 3), the
  `cmd` and POSIX wrapper handling and the git/stash classification are unchanged.
- **`action_gate.py` — dead `simple_commands` helper removed** (minor). It had no callers since the
  shell-wrapper tokenizer rewrite of 12.14.1; no behavior changes with it.

### Tests
- `test_action_gate.py` section 21 (a–f) covers the whole contract in hitl and auto: the three
  destructive payloads across pwsh/powershell, `-Command`/`-c` and the single/double/bare spellings
  compared against each other, in-scope destruction as CONFIRM_REQUIRED / ALLOW_WITH_ASSUMPTION,
  benign negative controls (`Write-Host hi`, `hello`) proving no over-deny, unreadable payloads (an
  open quote, an empty or blank payload) as CONFIRM, destructive tails behind an escaped `''`, and
  the unmatched-decoded-quote vectors of review iteration 1. Failures are COLLECTED, so one red run
  lists every failing vector instead of stopping at the first.
- Vaccination first: the new vectors were observed failing on the pre-fix code and passing after the
  fix (`logs/vaccination/single-quote-pre-fix.log` / `single-quote-post-fix.log` for the original
  fail-open, `review-round1-pre-fix.log` / `review-round1-post-fix.log` for the iteration-1 rework).
  No existing assertion was weakened, skipped or deleted.

Conditional pass (open major, backlog). Review iteration 2 returned `request_changes` with 0 critical
and ONE major still open: the DECODED payload of a PowerShell wrapper is still split into simple
commands with the POSIX backslash rules, not PowerShell's, so the two exact vectors
`pwsh -Command 'echo "\"; rm -rf /'` and `powershell -c 'echo "\"; git push origin main'` still
classify ALLOW (reproduced in both modes) although a real pwsh closes the string before the `;` and
runs the destructive tail. The entry above therefore does not close the single-quote class as a
whole — it closes the plain-literal and the unmatched-decoded-quote vectors only. Reviewer budget
2/2 and coder budget 1/1 were exhausted, the affected acceptance criterion is marked
`unverified_review`, and the residual is carried in the project backlog and stated as a KNOWN
LIMITATION in the `action_gate.py` docstring. The two pre-existing limitations (launcher prefixes and
`$(...)` substitutions are not expanded) remain open as well.

## [12.14.1] — 2026-10-17

### Fixed
- **`action_gate.py` — shell wrappers are transparent** (v12 review, critical). The payload of
  `sh`/`bash`/`dash`/`zsh`/`ksh` with `-c` (combined flags such as `-ec`/`-lc` included), of `cmd`
  with `/c` or `/k` and of `powershell`/`pwsh` with `-Command` (the short `-c` included) is now
  classified RECURSIVELY with the same rules, so a root deletion or a default-branch push can no
  longer hide behind the wrapper's name. Quoting is resolved before the line is cut, escapes are read
  per quote type (a single-quoted string has NONE, a double-quoted one takes `\\` and `\"`), and
  adjacent quoted/unquoted runs CONCATENATE into one argument as in a real shell — `sh -c "echo "hi"
  && rm -rf X"` is read as `echo hi && rm -rf X`. A payload that cannot be read as command TEXT
  (script file, encoded block, unknown or ambiguous flag, no payload, an open quote), an unreadable
  wrapper and nesting deeper than `MAX_WRAPPER_DEPTH` are CONFIRM — never ALLOW.
- **`repo_inventory.py` — `--tracked`** (critical). `inventory` and `shards` accept `--tracked`,
  which takes the file set from a NUL-safe `git ls-files -z` at `--repo`: untracked and git-ignored
  paths (machine-local configs, build output, leftovers) can no longer enter a tracked-only review,
  while a tracked file under `build/` or `node_modules/` is inventoried like any other. Without git
  or a repository the flag fails with the reason instead of silently falling back to the walk; the
  flag-less filesystem walk is unchanged and stays the documented escape hatch.
- **HITL plan approval routed through the pre-flight** (major) — `SKILL.md` and the reference flow
  no longer jump from plan approval straight to the execution node: the approval edge passes the
  pre-flight (PF) and preserves PF to the next node, as the auto path already did.
- **`factory_preflight.py --web-gui` — `mcp_usable` requires a real deployment** (major). The block
  now passes the resolved repository's `.kimi-code/mcp.json` into the delegated probe and is usable
  only when that config is valid AND the pinned vendored entry it launches is on disk at the pinned
  version; otherwise the MCP server is reported missing with the exact reason, so the shipped
  template alone can never make a clean clone look like a deployed browser path.
- **`chrome_devtools_mcp.py` — malformed `env` and credential-like variable NAMES** (major). A
  non-object `env` (string, list, number, boolean) is a validation problem instead of an
  `AttributeError` (only `null`/absent means "no environment"), and secret scanning now also rejects
  a credential-like NAME with a non-empty value, reporting the variable name and the reason — never
  the value.
- **`chrome_devtools_mcp.py` — probe wording matched by I1** (major). The actual probe message
  (`<node|npm|npx> was not found on PATH; a Web GUI run cannot start …`) is part of the I1 pattern
  in `references/error-patterns.default.json` and `references/error-routing.md`, and the router test
  classifies that real line instead of a paraphrase.
- **`skill_base.py` — `hash --repo` anchor, supervised clone, `record --resolved-hash`** (major). A
  relative local path passed to `hash` is resolved against the declared `--repo`, exactly like
  `resolve` and `record`, so the caller's working directory no longer decides which bytes are
  hashed; a clone is supervised WHILE its temporary tree grows and is aborted (with the partial
  content removed and an explicit reason) as soon as it crosses `--max-bytes` or the deadline,
  instead of being measured after the transfer; and `record --resolved-hash <hex>` records the
  materialization `resolve` already produced without a second fetch, refusing a divergent digest
  (exit 1) so the manifest can never describe different bytes from the generated skill.
- **`validate_documentation.py` — position-based line classification** (major). Changed lines are
  mapped through the diff opcodes (old↔new positions) instead of the first content match, so a
  deleted executable line can no longer be classified as a docstring line when the same text also
  appears inside one.
- **`prepare_factory.sh` / `prepare_factory.ps1` — `.kimi-code/mcp.json` is git-ignored** (major).
  Both deployer pattern lists add the machine-local managed config next to `.kimi-code/vendor/`
  (its entry holds an absolute launch path of that installation), so a prepared project never
  commits it and a fresh clone is never handed a path that does not exist there.
- **`test_windows_scripts.py` — clean-clone suite and independent safety expectations** (major). The
  Windows suite no longer requires the git-ignored machine-local MCP state (it validates the
  committed asset or generates a config in a temporary fixture), so it passes in a clean clone; its
  MCP safety assertions now compare against independent constants and carry a mutation check, instead
  of deriving the expectations from the asset under test.

### Changed
- **Documentation** — `references/reference-docs.md` documents the transfer-time `--max-bytes`
  enforcement, the `hash --repo` anchor and the no-second-fetch `record`; `references/chrome-devtools-mcp.md`
  documents the `mcp_usable` deployment gate, the `validate-config` rules (non-object `env`,
  credential-like names) and the I1 wording; `README.md` and `.agents/README.md` carry the tracked
  review command (`repo_inventory.py shards --repo <root> --max-lines 20000 --tracked`), the extended
  deployer ignore list, the clean-clone consequence and the pre-flight usable gate; the
  `action_gate.py` docstring states the wrapper rules and their KNOWN limitation.

Conditional pass (open major, backlog). `powershell`/`pwsh` with a SINGLE-quoted `-Command` payload
is still fail-open — `pwsh -Command 'rm -rf /'` classifies ALLOW while the double-quoted form is
HARD_DENY — and launcher prefixes (`env`/`sudo`) and `$(...)` substitutions are not expanded; the
limitation is now documented in the `action_gate.py` docstring instead of being an undocumented
assumption. A minor (dead `simple_commands` helper) is carried in the backlog as well. Nothing above
claims more than the suite and the deterministic gates prove: the 14 findings of the v12.14.0
whole-project review are closed, these two items are not.

## [12.14.0] — 2026-10-16

### Added
- **`factory-gui-expert` subagent** — a coder-class Web GUI specialist
  (`.agents/agents/sub-agents/gui-expert.md`) that implements and interactively debugs the ASSIGNED UI
  files in a real browser: it reproduces defects, inspects DOM/CSS/console/network and records
  DIAGNOSTIC artifacts under `.code-factory/logs/browser/`, but never treats its own run as acceptance
  and never issues a final PASS for its own work. Registered in the main agent allowlist and in both
  orchestration flows (`code-factory.md`, `SKILL.md`), in the reference-skill relevance matrix with
  coder-like access and in the handoff-briefing roster. Only `factory-gui-expert` and `factory-tester`
  receive the `mcp__chrome-devtools__*` tools; the tester independently repeats the FINAL browser
  scenario after the last code change and owns the acceptance evidence; analyzer, planner,
  diagnostician and reviewer stay read-only and generic `factory-coder` keeps non-GUI work.
- **Conditional Chrome DevTools MCP browser path** — `scripts/chrome_devtools_mcp.py` (stdlib) decides
  applicability from the task with a recorded REASON and never by a model call (`decide`: an explicit
  `backend-only` / `no web UI` exclusion always wins; a repository that merely contains a frontend never
  forces activation, while a green-field Web GUI task still activates), discovers the project's EXISTING
  browser/E2E stack and its config file (`discover-e2e`), derives the required browser matrix from the
  acceptance criteria (`browser-matrix`), merges the managed server into `.kimi-code/mcp.json`
  (`merge-config`) and probes the environment fail-soft (`probe`). Workflow reference:
  `references/chrome-devtools-mcp.md`; opt-in real-Chrome smoke fixture:
  `assets/chrome-devtools-smoke.html`.
- **Deployer-managed MCP configuration** — `assets/chrome-devtools.mcp.json` defines the single managed
  `chrome-devtools` stdio server (PINNED `chrome-devtools-mcp@1.11.0`, never `@latest`) with the safety
  defaults: isolated temporary Chrome profile and test data, usage statistics and CrUX lookups disabled,
  update checks disabled, sensitive network headers redacted, no blanket tool permission and no attaching
  to a running browser. `prepare_factory.sh` and the Windows `prepare_factory.cmd` →
  `prepare_factory.ps1` path first vendor the pinned package into `.kimi-code/vendor/chrome-devtools-mcp/`
  (`npm install --no-save --ignore-scripts --omit=dev`) and then merge a node-direct entry
  (`node <vendored entry point>` — the CLI spawns stdio servers without a shell, so `npx`/`npx.cmd`
  cannot launch on Windows) into the project's `.kimi-code/mcp.json` idempotently: every other server
  and user setting is
  preserved byte-for-byte, an existing DIFFERENT `chrome-devtools` entry is preserved and reported
  instead of overwritten (exit 3, nothing written), a target that is not valid JSON is never
  overwritten, and without a working Python the file is left untouched while the deployment still
  completes. The readiness report prints created/updated/unchanged/conflict and reminds that the
  configuration takes effect in a NEW Kimi session, where `/mcp` shows the connection status.
- **Remote `reference_docs` sources** — `skill_base.py resolve` classifies `reference_docs[].path`
  deterministically as a local path, a public HTTP(S) document (`http_doc`) or a public HTTP(S) Git
  repository (`http_git` — a URL whose path ends in `.git`) and materializes remote sources under the
  resolved repository's uncommitted runtime cache `.code-factory/cache/reference-docs/`
  (`http/<key>/`, `git/<key>/`, `_clones/<key>/`, `_meta/<key>.json`; `<key>` = stable hash of the
  canonical URL), then handles them exactly like local documents — the `{path, skill}` task schema is
  unchanged. Freshness stays content-hash based and stable across platforms and fresh clones (clone with
  `core.autocrlf=false`, `core.eol=lf`; hooks, filters, symlinks and the host git config ignored; `.git`
  and the cache metadata excluded from the hash). The manifest keeps the canonical URL as `source` plus
  the optional `source_type`/`resolved_revision` keys, and old manifests load and are written unchanged.
  New flags `--offline`, `--allow-stale`, `--timeout <seconds>`, `--max-bytes <n>`: a cached copy is
  never fresh remote content — it is marked `offline: true`/`stale: true` — and a fetch failure without
  a usable cache reports the source and reason and skips the skill instead of inventing one.
- **Tests** — new `test_chrome_devtools_mcp.py` (decision reasons and exclusions, E2E-stack discovery,
  browser matrix, idempotent merge, conflict preservation, probe degradation, safety invariants) and
  `test_remote_reference_docs.py` (loopback HTTP server + temporary local/bare Git fixtures ONLY:
  classification, create/reuse/update, redirects, rejected schemes and credentials, size/time limits,
  deterministic hashing, offline/stale, old-manifest compatibility; the default suite needs no internet
  access). `test_factory_preflight.py` covers the opt-in `--web-gui` block and `--simulate-missing`
  (the base schema without the flag stays byte-compatible), `test_error_router.py` covers the
  browser/MCP infrastructure rows I1–I4 and the absence of a GUI-specific `recommended_role`,
  `test_windows_scripts.py` covers the deployer MCP step, conflict preservation and the no-Python
  fallback, and `test_run_id.py` re-pins the digest of the changed task-template fixture.

### Changed
- **Error routing** — `references/error-patterns.default.json` and `references/error-routing.md` gained
  the browser/MCP INFRASTRUCTURE rows I1–I4 (node/npm/npx missing, Chrome / Chrome for Testing missing,
  MCP connection/startup failure, chrome-devtools-mcp launch error), placed between the git-hygiene and
  the generic rows so a browser capability line cannot be stolen by `command not found` (PLANNER) or
  `file not found` (BA); they route through the existing infrastructure auto-fix path (budget 3) with no
  new role and no new budget, and existing ids are untouched so project-learned overrides keep matching.
  GUI implementation failures and review rework are NOT infrastructure: they keep the existing coder
  route and `retry_counters.coder`.
- **Pre-flight** — `factory_preflight.py --web-gui` appends the nested `web_gui` capability block
  (node/npm/npx versions, Chrome / Chrome for Testing presence, MCP server start feasibility) for an
  applicable Web GUI run, delegated to `chrome_devtools_mcp.py`; it is OPT-IN, so a non-Web-GUI run
  keeps the previous output schema and never requires Node.js or Chrome, and a missing capability is
  DATA with a reason, never a fatal error — the affected browser criteria stay explicitly UNVERIFIED,
  never MET.
- **Models and briefings** — `references/providers.md` documents the optional `models.gui_expert` role
  key (generator-side like `models.coder`, so its family differs from the judge family, while coder and
  gui_expert may share one generator family; logged as `models_used.gui_expert` with
  `model_preference: secondary` as the fallback); `references/handoff-briefing.md`,
  `references/verification-strategy.md` §3.1 (browser evidence split and FRESH/STALE rules) and
  `agents/sub-agents/tester.md` state the browser evidence split;
  `agents/sub-agents/skill-manager.md` and `references/reference-docs.md` state the remote-source
  lifecycle and security contract; `assets/task-template.yaml` and `.example.task.yaml` show the
  `gui_expert` models key.
- **Manuals** — `README.md`, `.agents/README.md` and `AGENTS.md` document the two delivered scopes: the
  conditional Web GUI path (activation decision, specialist/tester evidence split, deployer-managed
  `.kimi-code/mcp.json`, safety defaults, pre-flight and I1–I4 degradation) and the remote-URL
  `reference_docs` capability (URL kinds, cache layout, deterministic hashing, offline/stale semantics,
  security contract). The scripts trees list `chrome_devtools_mcp.py` and the two new self-tests, and
  the assets list `chrome-devtools.mcp.json` and `chrome-devtools-smoke.html`.
- **Factory rule carriers** — `references/factory-rules.md` adds
  `.agents/agents/sub-agents/gui-expert.md` as a carrier of `no-shared-tree-git-mutations` and
  `english-only` (`check_factory_rules.py` stays exit 0, rule bodies byte-identical).

## [12.13.0] — 2026-09-29

### Added
- **25th rulebook rule `repo-scoping`** — at the start of a run the task's `repo_path` is resolved
  ONCE to an absolute path (relative to the launch directory) and EVERYTHING that follows is
  relative to that resolved target repository: the `.code-factory/` artifact tree (`state/`,
  `logs/`, `backups/`, `manifest.json`, reports), backups, git operations (`git -C <repo>` or an
  explicit cwd), source edits and rollback. The documented exceptions that stay
  DEPLOYMENT-ROOT-scoped are `memory/` (the long-term memory) and `scripts/version_manager.py`
  (`VERSION`) — they receive their root explicitly, never a silent default to the launch directory.
  Carriers (4): `SKILL.md`, `code-factory.md`, `AGENTS.md`, `.agents/README.md`
  (`check_factory_rules.py` — 25 rules, 98 carrier blocks, exit 0).
- **`--repo <root>` on the deterministic scripts** — `run_id.py`, `factory_preflight.py` and
  `task_graph.py` accept `--repo`/`--root` (before or after the subcommand), `verify_quotes.py`
  accepts `--repo`/`--base`, and `error_router.py` gained the option on `merge` next to the
  existing `classify`/`export-defaults`. When it is given, the RELATIVE paths of the invocation
  (`--task`, `--dir`, `--out`, `--log`, the patterns files, the quote sources, `--claims`,
  `--report`) are resolved against the resolved repo_path, while an absolute path is always taken
  as it is — so a run whose repo_path is not its launch directory reads and writes the artifacts of
  that repository and of no other. The flag is OPTIONAL and the default is unchanged (the caller's
  working directory, fail-safe: a missing anchor never silently re-points a path at the wrong
  repository), so every earlier invocation behaves exactly as before. Self-tests
  `test_run_id.py`, `test_factory_preflight.py`, `test_task_graph.py`, `test_error_router.py` and
  `test_verify_quotes.py` cover the flag and its default.
- **`scripts/test_repo_scoping.py`** — script-level regression test of the contract: a scripted
  mini-run whose `repo_path` is NOT the launch directory invokes run_id gen/check, the pre-flight,
  the task graph, error routing and quote verification with the flag and asserts that every
  artifact lands under `<repo>/.code-factory/`, that the launch directory, its work tree, its HEAD
  and its reflog stay byte-identical (the git half runs as `git -C <repo>`), and that the flag-less
  invocation still resolves against the cwd (backward compatibility).
- **Launcher anchor `KIMI_FACTORY_LAUNCH_DIR`** — the `start.sh` and `start.cmd` launchers export
  the absolute path of the launch directory — the machine-checkable anchor against which the
  instruction layer resolves the task's `repo_path` — next to the already exported
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` (`test_windows_scripts.py` pins both).

### Changed
- **Instruction layer scoped to the resolved repo_path** — `SKILL.md` and `code-factory.md` gained
  the mandatory Phase-0 resolve-repo_path step and the warning about a leftover `task.yaml` of a
  previous run; `references/verification-strategy.md` (git-state recording, evidence ledger and
  rollback examples), `references/error-routing.md`, `references/documentation.md`,
  `references/tech-stack-detection.md` (the generated AGENTS.md states the scope) and
  `references/handoff-briefing.md` (the briefing carries the mandatory
  `Repository root: <absolute resolved repo_path>` line) now pass the resolved root explicitly; the
  `analyzer`/`diagnostician`/`documenter` sub-agents pass it as `--repo` instead of the literal
  `--repo .`; `assets/task-template.yaml` states that `repo_path` is required except for a
  green-field task.
- **`git-native` and `task-format` rule wording** — every git operation of a run is spelled
  `git -C <resolved repo_path>` (init, feature branch per task, recording of the base commit and its
  HEAD, commits, rollback to the base commit), and `repo_path` is REQUIRED for every task except a
  green-field one, always resolved ONCE at the start of the run.
- **`.gitignore` patterns of a deployed project** — `prepare_factory.sh` and `prepare_factory.ps1`
  additionally ignore `task.yaml`, `start.cmd` and `start.sh`: a leftover task file or launcher in a
  target project is never mistaken for a new task and never committed.

### Fixed
- **`references/verification-strategy.md` §4.3** — rollback order for the HEAD-moved case: the git
  restore runs BEFORE the branch switch — `reset --hard <base commit>` (from
  `.code-factory/state/git-head.txt`), then `switch <pre-run branch>` (recorded during preparation
  in `.code-factory/state/git-branch.txt`), then `branch -D <feature branch>` — because a dirty tree
  makes `switch` refuse and deleting the feature branch first would drop the run's commits.
- **`test_error_router.py`** — path assertions compare two spellings of one path through
  `realpath` + `normcase` instead of raw string equality, so a non-ASCII / 8.3 short-name temp base
  no longer fails a passing tool (vaccination: the failing case was reproduced first); the tool's
  output is decoded as UTF-8, the encoding the script forces itself.

## [12.12.1] — 2026-09-24

### Fixed
- **check_translation_structure.py** — a file deleted from the worktree whose type has no
  skeleton (.json/.toml/binary) was silently skipped and the check exited 0; the
  deleted-at-worktree probe now runs BEFORE the no-skeleton family skip, so every file that
  existed at base but is gone fails the check, per the contract "a translation never removes a
  file" (v8 whole-project review, major; vaccination regression test
  `check_deleted_no_skeleton_file_fails`).
- **security-auditor.md** — severity mapping contradicted `references/security-audit.md` §5.1
  and inflated shard findings by one grade; now critical→critical, high→major, medium→minor,
  low→nit.
- **prepare_factory.ps1** — deployer parity with the sh version: `git init -b main` failure
  (git < 2.28) falls back to `git init` + `git symbolic-ref` instead of a hard exit 1; the
  project-memory failure diagnostic shows the LAST non-empty output line (the actual exception)
  instead of the first ("Traceback…").
- **skill_base.py** — added the `use_utf8_output()` guard pinned as universal for argparse
  scripts (cp1251/cp866 consoles) and fixed the docstring usage lines (`--base` is a top-level
  option and precedes the subcommand).
- **README.md** — structure tree: `assets/task-template.yaml` moved under
  `.agents/skills/code-factory/` (its real location).
- **test_version_manager.py** — `suggest()` helper annotation corrected to `tuple[str, int]`.

## [12.12.0] — 2026-09-24

### Changed
- **The entire factory is now English-only** — full RU→EN translation of everything the factory
  produces: user-facing strings, error messages and argparse help of all `scripts/*.py`, the
  deployers (`prepare_factory.sh`/`.ps1`/`.cmd`, `start.cmd`), code comments and docstrings,
  `README.md`, `AGENTS.md`, `.agents/README.md`, the whole skill (`SKILL.md` incl. the mermaid
  flow labels, all `references/*.md`, `assets/`), all agents (`code-factory.md` + sub-agents),
  `.example.task.yaml` and `skill-base/`. Behavior, logic, CLI contracts and exit codes are
  unchanged (freeze-functionality refactor): 26/26 pre-existing self-tests PASS with only
  synchronous token translation, mermaid edge contract intact (85 edge lines), encoding contracts
  preserved (BOM/CRLF/LF per `.gitattributes`). History is NOT rewritten: CHANGELOG and old
  memory/ entries stay in Russian.

### Added
- **24th rulebook rule `english-only`** — every artifact the factory produces is written in
  English only (code and comments of target projects, docs, docstrings, commit messages, reports,
  memory entries, plans, subagent briefings); the factory accepts a task file in any language;
  exceptions: live communication with the user (user's business language) and history (never
  rewritten). Carriers (8): `AGENTS.md`, `.agents/README.md`, `code-factory.md`, `SKILL.md`,
  `references/planning-guide.md`, sub-agents `coder.md`/`tester.md`/`documenter.md`
  (`check_factory_rules.py` — 24 rules, 94 carrier blocks, exit 0).
- **`check_english_only.py`** — deterministic guarantee carrier: scans `git ls-files` for
  Cyrillic outside the exceptions (CHANGELOG.md, memory/, task*.yaml, .code-factory/, .git/),
  exit 0 only when clean; self-test `test_check_english_only.py`.
- **`check_translation_structure.py`** — deterministic translation-quality gate: compares the
  structural skeleton of every changed file against a git base (markdown headings/list
  items/fences/rule markers/mermaid arrows; Python defs/classes/argparse/raise/print; non-empty
  and comment lines for scripts/configs), `--allow-added-rule <id>` neutralizes a deliberately
  added rule on both sides, `--exclude` declares files that are supposed to grow (history);
  self-test `test_check_translation_structure.py`.
- **Sharded semantic audit as a run gate** — six parallel LLM auditors compared every translated
  file against `git show HEAD:<file>` item by item (meaning preserved, glossary terms enforced,
  verbatim quotes re-checked); deterministic merged verdict via `merge_findings.py`: approve
  (0 critical / 0 major).
- **Translation glossary** — the canonical RU→EN terminology map (run, entry, journal, summary,
  carriers, canonical wording, deployment root, retry budget, evidence ledger, ...) is now
  mandatory in every translator/QA briefing.


## [12.11.0] — 2026-09-24

### Added
- **Явная классификация `git stash` в `action_gate.py`** — мутирующие формы
  (push/pop/apply/drop/clear, голый `git stash`) → CONFIRM с деловым объяснением риска гонки на
  общем рабочем дереве и отсылкой к правилу `no-shared-tree-git-mutations`; `stash list`/`show`
  → ALLOW; разбор опций как у git (`-m`/`--message` поглощают значение — мутирующий push не
  маскируется под чтение, кейс 17 `test_action_gate.py` с negative-control).
- **23-е правило rulebook `memory-actuality`** — в начале прогона открытый backlog сверяется с
  деревом (`memory_project.py backlog`), в конце каждый пункт закрывается блоком `closed:` с
  обязательным `evidence:` или остаётся в `unfinished` с причиной; пункт не может исчезнуть без
  доказательства закрытия; `summary.md` актуализируется каждым прогоном. Носители (5): `AGENTS.md`,
  `.agents/README.md`, `code-factory.md`, `SKILL.md`, `references/planning-guide.md`
  (`check_factory_rules.py` — 23 правила, 86 блоков, exit 0).
- **`memory_project.py backlog [--check] [--json]`** — детерминированный fold открытых
  follow_up=true/severity=critical по всей истории журнала; `--check` → exit 1 при открытых
  пунктах, закрытии без `evidence:` и закрытии несуществующего пункта; WARN при расхождении версии
  в `## Current state` с VERSION. Протокол `closed:` в формате записи; кейсы 17–23
  `test_memory_project.py`.
- **Project-learned patterns — документированный overlay** в `error_router.py`: битый
  авто-найденный `.code-factory/state/error-patterns.json` деградирует до default с деловым
  stderr-предупреждением (маскировка невозможна), явный `--project-patterns` остаётся exit 2;
  справочник `error-routing.md` §1.2; кейсы 9a/9b `test_error_router.py`.
- **`providers.md` §5.2** — второй планировщик комитета (plan-committee) — единственная роль, где
  матрица `models` задачи не применяется: контрастное семейство обязательно.

### Changed
- **Контентный fingerprint видит unstaged-правки** — хэш считается по содержимому рабочего дерева
  отслеживаемых файлов (CRLF→LF-нормализация, недоступный файл → запись индекса); unstaged-правка
  двигает хэш и валит `check_factory_model.py` (intended); вне хэша остаются только
  untracked-файлы (`worktree_dirty` → `untracked_files`, stderr-заметка + WARNING). Кейс 29
  `test_factory_model.py` переписан строго строже; одноразовая регенерация встроенных
  fingerprint'ов AGENTS.md у развёрнутых проектов — ожидаемое следствие.

### Fixed
- **`prepare_factory.ps1`** — fallback копирования `Get-ChildItem | Copy-Item` обёрнут в
  try/catch (`-ErrorAction Stop`, `$script:HardError`): при жёстком сбое — одна деловая строка
  вместо сырых записей PowerShell (CategoryInfo/FullyQualifiedErrorId); контракт (exit 1, без
  баннера «Готово») подтверждён живым ACL-deny воспроизведением.
- **`prepare_factory.sh`** — при сбое `memory_project.py init` в предупреждение попадает короткая
  причина (последняя непустая строка) вместо первой строки traceback.
- **`.gitattributes`** — пин `*.sh text eol=lf` (`.cmd`/`.ps1` уже были покрыты): окончания строк
  shell-скриптов не зависят от `core.autocrlf`.
- **`references/planning-guide.md`** — «init --repo \<project root\>» → «--repo \<deployment root\>»
  (канон memory-ownership).

## [12.10.2] — 2026-09-23

### Fixed
- **`action_gate.py --help` больше не падает на cp1251-консоли** — модульный docstring содержит `→`
  (U+2192), которого нет в cp1251, и `description=__doc__` уводил `print_help()` в
  UnicodeEncodeError с traceback. Добавлен эталонный `use_utf8_output()` (как в
  `gen_code_changes_report.py`), вызываемый первой строкой `main()`; контракт `--help` → exit 0,
  ошибки использования → exit 2 без traceback запинен кейсом 16 в `test_action_gate.py`
  (subprocess под `PYTHONIOENCODING=cp1251`, вакцинация — на pre-fix коде кейс падает).

### Added
- **UTF-8 guard во всех argparse-скриптах фабрики** — `use_utf8_output()` первой строкой `main()`
  в 22 `scripts/*.py` (в `log_tail.py`/`precedent_index.py` прежний слабый guard стоял после
  `parse_args()` и не защищал `--help` — перемещён; в `error_router.py`/`plan_arbiter.py` —
  усилен до stdout+stderr). cp1251/cp866 sweep `--help`: 24/24 exit 0 без traceback.
- **22-е правило rulebook `no-shared-tree-git-mutations`** — сабагенты не выполняют
  `git stash`/`git reset`/`git checkout`/`git clean` на общем рабочем дереве прогона (риск гонки с
  главным агентом и другими сабагентами); базовая версия файла — через `git show HEAD:<file>` или
  temp-клон. Byte-identical носители: `AGENTS.md`, `.agents/README.md`, `code-factory.md`,
  `SKILL.md`, `references/handoff-briefing.md`, `sub-agents/coder.md`; сверка —
  `check_factory_rules.py` (22 правила, 81 блок, exit 0).

## [12.10.1] — 2026-09-23

### Added
- **`test_gen_code_changes_report.py`** — self-тест генератора `report_code_changes.md`: `--help` и
  ошибки использования на cp1251/cp866-консоли, happy-path во временном git-репозитории. Набор
  self-тестов — 26 (25 существующих без ослабления).
- **Предупреждение о dirty-дереве** (`project_fingerprint.py`, `check_factory_model.py`): контентный
  хэш по-прежнему читает git-индекс (решение сохранено — индекс commit-стабилен и платформенно
  нейтрален, а AGENTS.md может встроить пару своих хэшей), но слепое пятно больше не молчит:
  `--content`/`--all` печатают stderr-заметку, а проверка модели — предупреждение о N
  unstaged/untracked правках, которых индекс не видит. Хэши и exit-коды не меняются.
- **`.gitattributes`: `*.cmd`/`*.ps1` → `text eol=crlf`** — Windows-лаунчеры (`prepare_factory.cmd`,
  `prepare_factory.ps1`, `start.cmd`) получают CRLF при checkout независимо от `core.autocrlf`;
  блобы остаются LF, ренормализация не требуется. Анти-регрессионная проверка обеих строк добавлена
  в `test_windows_scripts.py`.

### Changed
- **`action_gate.py`: новый exit code 3** (инфраструктурная ошибка журнала) — незаписываемый журнал
  (OSError) печатает классификацию на stdout, `error: cannot write the action-gate journal …` на
  stderr и завершает работу кодом 3 вместо traceback; коды решений 0/1/2 не изменены, молчаливого
  ALLOW по-прежнему нет.
- **Калибровка ревьюера (§7)**: правило про нейтральный ре-нейминг уточнено —
  `references/code-review.md` §3 и `sub-agents/code-reviewer.md` требуют молчания (не nit) при
  равно ясных именах. После правки промпта ревьюер перекалиброван: accuracy 7/7, macro precision
  1.000 (было 0.857), recall 1.000 (`logs/reviewer-calibration.md`).
- **Golden set закоммичен**: 7 кейсов калибровки ревьюера в `skill-base/golden-set/` стали частью
  репозитория (ранее каталог исключался как фикстура через `commit_exclude`) — свежий клон
  воспроизводит калибровку без восстановления из соседнего развёртывания. В FTS5-индекс прецедентов
  кейсы по-прежнему не попадают.
- **Гигиена документации**: устаревшие советы `--memory-only` для корня фабрики убраны из
  `references/tech-stack-detection.md` и шаблона журнала `memory_project.py` — авто-детект корня
  (3 сигнала) делает `SKIP` сам, сам флаг сохранён как живой CLI-контракт. `AGENTS.md`,
  `.agents/README.md` и `references/tech-stack-detection.md` описывают dirty-worktree warning и
  актуальные метрики калибровки.

### Fixed
- **`gen_code_changes_report.py`: `--help` без traceback** — `main()` переводит stdout/stderr в
  UTF-8 (`reconfigure(encoding="utf-8", errors="replace")` под try/except), поэтому не-ASCII
  help-текст (`→`, кириллица) больше не падает `UnicodeEncodeError` на консоли с cp1251/cp866;
  контракт argparse сохранён: `--help` → exit 0, ошибка использования → exit 2, сообщение без
  traceback.

## [12.10.0] — 2026-09-23

### Added
- **Committee при двойном rejection плана** (hitl): первое отклонение плана возвращает его на
  доработку, второе запускает второго независимого planner-сабагента (`sub-agents/planner.md`,
  контрастное семейство моделей, отклонённый план он не видит), а `scripts/plan_arbiter.py`
  детерминированно сливает оба плана по машиночитаемым секциям (`## Tasks (DAG)`, `## Risks`,
  `## Business tests`) и печатает список расхождений; пользователю предъявляется merged-план,
  дальнейшие правки идут по нему, комитет срабатывает не более одного раза на задачу. Новое
  правило `plan-committee` в `references/factory-rules.md` и его носители (SKILL.md,
  code-factory.md, AGENTS.md, planning-guide.md) — правило сверяет `check_factory_rules.py`.
- **`plan_arbiter.py`** (stdlib): слияние задач по id — одинаковое тело схлопывается, одинаковый id
  с разным телом уходит в `## Расхождения` и НЕ попадает в merged-список; риски и бизнес-тесты
  объединяются дедуплицированным объединением. Контрактные ошибки (нет секции `## Tasks (DAG)`,
  пустой список задач, строка задачи без `verification:`, один id дважды в ОДНОМ плане, нечитаемый
  файл, незаписываемый `--out`) — exit 2 с сообщением и без traceback.
- **`precedent_index.py`** (stdlib sqlite3): FTS5-индекс прецедентов `build`/`query` — память
  проекта (`memory/change-log.md`, `memory/summary.md`) плюс кодовая база (`git ls-files`, fallback —
  обход `repo_inventory.py`; симлинки и бинарные/слишком большие файлы пропускаются) в
  `.code-factory/state/precedents.db`; детерминированный rebuild, поиск «как это решали раньше»
  вместо повторного чтения истории. Подключён к analyzer и diagnostician.
- **Авто-детект hand-authored корня фабрики** в `check_factory_model.py`: три сигнала вместе — в
  первой строке `AGENTS.md` НЕТ маркера `code-factory-fingerprint`, но ЕСТЬ собственный маркер
  фабрики `code-factory-version`, и рядом развёрнут `.agents/skills/code-factory/SKILL.md` → проверки
  AGENTS.md дают `SKIP` с пояснением (память и WIP-фиксатор проверяются как обычно), поэтому корень
  фабрики проходит без `--memory-only`. У целевого проекта AGENTS.md без fingerprint остаётся
  ошибкой, а устаревший fingerprint — ошибкой даже в корне фабрики.

### Changed
- **Граница severity в code review** (`references/code-review.md` §3): critical — дефект или
  ослабление СУЩЕСТВУЮЩЕГО поведения (crash/bug на существующем пути, порча данных, безопасность,
  ослабленная проверка), major — незащищённый НОВЫЙ путь или потерянное покрытие без замены; добавлены
  примеры на границе и Reporting discipline (одна первопричина — одно finding, taste-замечания не
  заявляются). `references/code-review.md` §7 делает калибровку периодической: обязательна после
  каждой правки промпта ревьюера и не реже одного раза на 5 прогонов ревью, мягкие пороги — verdict
  accuracy 100% и macro precision ≥ 0.8. Повторная калибровка на golden-set: verdict accuracy 7/7
  (100%), macro precision 0.619 → 0.857, recall 0.857 → 1.000 (`logs/reviewer-calibration.md`).
- Документация затронутого поведения: `AGENTS.md`, `.agents/README.md`, `SKILL.md`,
  `code-factory.md`, `references/planning-guide.md`, `code-reviewer.md`, `analyzer.md`,
  `diagnostician.md` описывают committee, индекс прецедентов, границу severity и SKIP-режим корня
  фабрики.

### Fixed
- `test_run_id.py` пиннит закоммиченный fixture `assets/task-template.yaml` (digest `4b918a06`)
  вместо эфемерного `.code-factory/state/task.yaml`: алгоритм доказан против реального файла задачи,
  и пин не «гниёт» на следующем прогоне — дата проверяется только форматом `YYYYMMDD-`.

## [12.9.1] — 2026-09-23

## [12.9.0] — 2026-09-23

## [12.8.0] — 2026-09-24

### Added
- **Shard-протокол whole-repo операций** (review, security_audit): `repo_inventory.py`
  (детерминированный inventory + нарезка на шарды ≤ N тысяч строк, дефолт 20k) → параллельные
  reviewer/auditor сабагенты по шардам → `merge_findings.py` (дедупликация по
  (file,line,title), сортировка по severity, merged verdict). Закрывает переполнение контекста
  на проектах 100k+ строк.
- **Двухуровневый fingerprint проекта**: структурный (commit-стабильный) + контентный
  (`git ls-files -s`, fallback — хэш дерева без git); AGENTS.md встраивает оба хэша, SKIP
  регенерации — только при совпадении обоих; `check_factory_model.py` валидирует оба
  (legacy однохэшевый формат — warning).
- **Think in Code**: `log_tail.py` (счётчики + tail длинных логов), `repo_stats.py`
  (sizes/entry-points/imports); правила для analyzer/tester/diagnostician — скрипт вместо
  чтения ради подсчёта, длинный вывод тестов в `.code-factory/logs/`, в контекст — выжимка.
- **Верифицируемая приёмка (anti-tautology)**: `verify_acceptance.py` — acceptance_criteria
  поддерживают `verify: <команда>`; acceptance.md заполняется по факту запуска (exit code +
  выдержка); критерии без verify помечаются derived/unverified; деградированный baseline →
  вердикт DEGRADED.
- **Evidence ledger FRESH/STALE**: `evidence_ledger.py` — результаты тестов/приёмки подписаны
  fingerprint'ом затронутых файлов; ревьюер и приёмка принимают evidence только FRESH.
- **Антигаллюцинационные цитаты**: `verify_quotes.py` — цитаты Diagnostician/ревьюера/Advisor
  проверяются как точные подстроки источника; несовпадение → «недоверенный» + fallback на
  полный лог.
- **Сабагент `factory-advisor`** (secondary, no-edits): эскалация после Diagnostician;
  лестница regex → Diagnostician → Advisor → Human → FAILED, бюджет advisor=1 per root cause;
  машиночитаемое поле `agreement: agree|disagree`.
- **Handoff-шаблон брифинга** `references/handoff-briefing.md` (Task/Context/Relevant files/
  Current state/What was tried/Decisions/Acceptance criteria/Constraints) + контракт concise
  output; файлы — путями, не вставками.
- **Инфраструктурные скрипты**: `factory_preflight.py` (проба окружения → capabilities),
  `action_gate.py` (детерминированный гейт деструктивных действий: HARD_DENY/CONFIRM/ALLOW +
  журнал), `task_graph.py` (дисковый граф state/tasks/*.json, валидация циклов, sha256).
- **Память**: enforced owner = basename(repo_path) в `memory_project.py check`; команды
  `rename` (миграция владельца), `compact-check` (сохранность critical/follow_up при
  компакции), `validate-fix-tasks` (валидатор схемы fix-tasks.yaml).
- **Model diversity generator≠judge** в providers.md + «trajectory is the truth» в чек-листе
  ревьюера; модель передаётся в Agent tool явно по матрице `models` задачи (правило «не
  передавать» устарело).

### Changed
- **Единый канонический review-гейт** в 5 документах (references/code-review.md,
  code-factory.md, SKILL.md, AGENTS.md, .agents/README.md): приёмка запрещена при открытых
  critical findings; auto-exhaustion = conditional pass с `unverified_review` в acceptance.md
  и unresolved findings в report.md; консистентность проверяется `test_review_gate.py`.

### Fixed
- nit-фиксы code-review 2026-09-23: encoding="utf-8" в gen_code_changes_report.py (+парсинг
  quoted/octal путей), newline="" в version_manager.py, list.index при дублях в
  validate_documentation.py, git init fallback для git<2.28 и точное сравнение паттернов
  .gitignore в prepare_factory.sh/.ps1, prepare_factory.sh в IGNORE_TOP_LEVEL fingerprint,
  нечитаемые файлы не рушат repo_inventory.py, дерево скриптов в .agents/README.md,
  дрейфы verification-strategy §6.1 и reference-docs record.

## [12.7.0] — 2026-09-21

### Added
- **Развёртывание и запуск фабрики в Windows без Git Bash**: `prepare_factory.cmd` (двойной клик
  в Проводнике / `cmd` / PowerShell) вызывает `prepare_factory.ps1` и возвращает его код выхода.
  PowerShell-деплойер повторяет шаги bash-версии 1:1: поиск рабочего Python с пробным запуском
  (`py -3` → `py` → `python` → `python3`, заглушка Microsoft Store не побеждает), `git init -b main`,
  копирование `.agents/`, создание/проверка памяти проекта (никогда не перезаписывается),
  `start.sh` (LF) + `start.cmd` (CRLF), те же 9 правил `.gitignore`, тот же отчёт готовности.
  Без Python развёртывание всё равно завершается успешно (шаг памяти деградирует с понятным текстом).
- **`start.cmd`** — Windows-launcher: выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`,
  проверяет наличие `kimi`, передаёт аргументы и код возврата; Git Bash не нужен.
- **Самотест `scripts/test_windows_scripts.py`**: контракты Windows-скриптов (BOM/CRLF, `chcp 65001`,
  передача аргументов и кода возврата, совпадение inline-шаблона `start.cmd` с файлом, реальное
  развёртывание с пробелом и с кириллицей в пути, идемпотентность памяти). В проекте, развёрнутом
  фабрикой, тест аккуратно пропускается (SKIP, exit 0) вместо ложного падения.

### Fixed
- `prepare_factory.ps1` больше не выдаёт жёсткий сбой за успех: сбой копирования `.agents/` или
  записи `start.sh`/`start.cmd`/`.gitignore` → `exit 1` и «Развёртывание не завершено» без баннера
  «Готово». Ожидаемые деградации остались нефатальными (нет Python → `не проверено (нет python)`, exit 0).
- `prepare_factory.ps1` выставляет `PYTHONUTF8=1` для своих вызовов python: кириллица в пути больше
  не превращается в мусор и не даёт ложное «память не создана».
- `prepare_factory.ps1` предупреждает с именем файла, прежде чем заменить существующий
  пользовательский `start.cmd`.

## [12.6.0] — 2026-09-21

### Added
- **Признак принадлежности памяти проекту**: запись журнала несёт обязательное для новых
  записей поле `project: <имя проекта>` (= basename разрешённого `repo_path`), а
  `memory/summary.md` объявляет `project:` и `repo_path:`. Память `memory/` описывает
  ЦЕЛЕВОЙ проект фабрики, а не саму фабрику.
- **Обнаружение смешения проектов**: `check_factory_model.py` считает записи с разными
  значениями `project:` в одной памяти ошибкой (пустое значение `project:` — тоже ошибка),
  а отсутствие объявления проекта в сводке — предупреждением.
- **Скрипт `memory_project.py`** (только stdlib): `name` (имя проекта), `init` (создать
  память проекта из шаблонов, только если её нет), `check` (проверить принадлежность и
  смешение), с self-тестом `test_memory_project.py`.
- **Память заводится при развёртывании**: `prepare_factory.sh` создаёт `memory/` с именем
  проекта, если её нет, НИКОГДА не перезаписывает существующую и предупреждает, если память
  объявлена за другой проект (`ПРОВЕРИТЬ ✗`) или смешивает проекты (`НЕСОГЛАСОВАНА ✗`).

### Changed
- Документация и инструкции (`AGENTS.md`, `README.md`, `.agents/README.md`, `SKILL.md`,
  справочники, главный агент и сабагенты) описывают `memory/` как память целевого проекта,
  создаваемую в корне развёртывания, и правило «одна память — один проект».
- Legacy-записи без `project:` остаются совместимыми: предупреждение, не ошибка.

## [12.5.1] — 2026-09-08

### Fixed
- **Защита от утечки API-ключей**: `.gitignore` теперь игнорирует `.env`, `.env.*`, `*.env`,
  `*.pem`, `*.key`; `prepare_factory.sh` добавляет те же паттерны в автодобавляемый блок
  `.gitignore` новых проектов.

## [12.5.0] — 2026-09-08

### Added
- **Сабагент документирования `factory-documenter`**: после каждого успешного
  implement/refactor-прогона обновляет документацию изменённых файлов (только doc-комментарии
  и `.md`, никогда код/тесты/конфиги). Встроенный валидатор `validate_documentation.py`
  (бюджет 1 retry); при исчерпании документационный долг фиксируется в отчёте, фабрика
  продолжает. Использует secondary-модель; не вызывается для review/security_audit.
- **Память «что НЕ реализовано»**: секция `unfinished` в записях журнала (item/reason/
  severity/follow_up) + поле `factory_version`. Главный агент заполняет секцию обязательно,
  даже если она пуста; компакция сохраняет critical/follow_up элементы; legacy-записи
  проходят валидацию с предупреждением.
- **Справочники-навыки `reference_docs`/`reference_skills`**: персистентная база `skill-base/`
  (SHA256-актуальность, переиспользование, инкрементальное обновление), сабагент
  `factory-skill-manager`, скрипт `skill_base.py`, детерминированная матрица релевантности для
  8 сабагентов, динамический (append-only) контекст.
- **Сквозное версионирование**: `VERSION` — единый источник истины; скрипт `version_manager.py`
  (get/bump/sync/validate/set/suggest, stdlib only); детерминированная матрица типов
  (major/minor/patch/none), валидация ревьюером (с правом переопределения с объяснением);
  синхронизация версии в README/CHANGELOG/AGENTS.md/SKILL.md/инструкцию; коммит с префиксом
  `v<версия>: `.

### Changed
- `check_factory_model.py` валидирует секцию `unfinished` и поле `factory_version` (legacy —
  предупреждение, не ошибка); self-тест расширен (12+ кейсов).
- Сабагенты `code-reviewer` валидируют предложенный матрицей тип версии.

## [12.1.0] — 2026-09-01

### Added
- **AGENTS.md как единый источник правды**: фабрика сама генерирует `AGENTS.md` проекта с ровно
  8 секциями `##` и встраивает детерминированный fingerprint структурных сигналов
  (`scripts/project_fingerprint.py`). При совпадении fingerprint анализ/Scout пропускается, при
  расхождении AGENTS.md перегенерируется; обновление в двух точках (начало/конец задачи).
- **Переносимая долгосрочная память `memory/`** (коммитимая, не игнорируется): `change-log.md`
  (append-only журнал, одна запись на прогон; единственный писатель — главный агент) и
  `summary.md` (сводка). Компакция журнала в сводку по порогу 50 записей.
- **Скрипты проверки модели**: `scripts/check_factory_model.py` (детерминированная проверка
  «8 секций + fingerprint + формат журнала») и `scripts/test_factory_model.py` (self-тест).

### Changed
- Сабагенты `analyzer`, `coder`, `tester`, `code-reviewer`, `diagnostician` читают `AGENTS.md` и
  `memory/` как источник правды, а не выводят структуру проекта заново.

### Removed
- Вызов `/init` из Scout-потока полностью удалён — фабрика генерирует `AGENTS.md` сама, без
  отдельного init-шага.

## [12.0.0] — 2026-08-29

### Added
- **User story**: поле `user_story` в шаблоне задачи; обязательный анализ и использование
  контекста пользователя агентами фабрики на этапах анализа, планирования и реализации.
- **Тип задачи `refactor`**: выделенный поток со специализированным сабагентом
  `factory-refactorer` и справочником `references/refactoring.md`. Ключевое требование —
  «заморозка» функциональности: успех = структурное улучшение при 100% прохождении
  существующих тестов без изменений; любое изменение поведения — критическая ошибка и автооткат.
- **Тип задачи `security_audit`**: универсальный адаптивный полный аудит кибербезопасности
  (`references/security-audit.md` + сабагент `factory-security-auditor`, read-only).
  Автоматическое определение типов артефактов (код, IaC, контейнеры, сеть, секреты,
  зависимости), автономный выбор инструментов, отчёты + сгенерированный файл задач на
  исправление. Фабрика НЕ чинит уязвимости сама.
- **Провайдеры Kimi (K3) и Qwen**: `references/providers.md` — маршрутизация моделей через поле
  `models` задачи, корректная аутентификация/формат запросов, аддитивная интеграция без поломки
  существующих провайдеров. Ошибки провайдеров интегрированы в детерминированную маршрутизацию
  (`references/error-routing.md` §1.1).
- **Запуск одним действием**: `prepare_factory.sh` генерирует launcher `start.sh` в целевом
  проекте (автоматически выставляет `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`) и обновляет
  `.agents/` целиком (фабрика — source of truth).

### Removed
- **BREAKING**: поле `priority` полностью удалено из шаблонов, документации, инструкций агентов
  и логики. Все задачи по умолчанию обрабатываются с наивысшим приоритетом (`high`),
  приоритизацией фабрика не занимается.

## [11.1.0] — 2026-08-23

### Added
- `prepare_factory.sh`: при развёртывании фабрики добавляет `.agents/` в `.gitignore` целевого
  проекта (не ломая чтение/запись данных фабрики — `.gitignore` влияет только на git-трекинг).
- Блок «Лестница Ленивого Сеньора» (Ponytail) в `code-factory.md` и `coder.md`: обязательная
  лестница решений перед генерацией кода + фиксация выбора в `<thinking>`.
- Скрипты `scripts/test_prompt_structure.py` и `scripts/test_env_propagation.sh` — детерминированные
  проверки append-only структуры промптов и проброски env-переменной.

### Changed
- Документировано правило append-only сборки промптов (для автоматического кэша DeepSeek).
- Документирована причина потери `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL` и требование
  экспортировать его в том же терминале до запуска `kimi`.

## [11.0.0] — 2026-08-12

### Added
- Сабагент `factory-code-reviewer` (read-only, `model_preference: primary`) и справочник
  `references/code-review.md`: статический quality gate перед приёмкой.
- Поле `task_type: implement | review` в шаблоне задачи.
- Правило code-review gate: обычная задача ревьюит diff, `task_type: review` — весь код в начале;
  задача не принимается при открытом вердикте `request_changes`; бюджет ревью = 2 итерации.

### Removed
- **BREAKING**: поддержка Kimi CLI 1.12 и Kimi Agents SDK — удалены `code-factory.yaml`,
  `system.md`, `models.yaml`, `sub-agents/*.yaml`, `examples/`. Модели теперь задаются только
  через `model_preference` в `.md`-сабагентах + `config.toml`.

## [10.2.0] — 2026-08-12

### Added
- Pre-flight проверка `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`: при отсутствии флага
  фабрика пишет `models_warning` в `pipeline.yaml`/`report.md`.

### Fixed
- `factory-analyzer` переведён на `model_preference: primary` (deepseek-v4-pro).
- Инструкции моделей: сабагентам больше не передаётся `model=` в Agent tool (не поддерживается
  в новой CLI) — модели задаются `model_preference` + `config.toml`.

## [10.1.0] — 2026-08-12

### Added
- Markdown-агенты для Kimi Code 0.34+: `code-factory.md` и сабагенты
  `analyzer|coder|tester|diagnostician.md` (frontmatter: name, description, tools,
  `model_preference`).
- Документация secondary-модели (`[secondary_model]` в `config.toml`).

### Changed
- `task.yaml` с личными данными заменён на `.example.task.yaml` (шаблон без секретов).
- Уточнена команда `/init` в `SKILL.md`/`system.md`: это slash-команда
  (`kimi -p /init --print --yolo -w <project>`), а не CLI subcommand.

## [10.0.0] — 2026-08-11

### Added
- Первая версия Autonomous Code Factory (flow skill `code-factory` + agents + SDK):
  оркестратор `SKILL.md`, справочники (planning-guide, verification-strategy, error-routing,
  tech-stack-detection), сабагенты analyzer/coder/tester/diagnostician, `models.yaml`,
  `prepare_factory.sh`, генератор `report_code_changes.md`.

[12.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v12.0.0...v12.1.0
[12.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.1.0...v12.0.0
[11.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v11.0.0...v11.1.0
[11.0.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.2.0...v11.0.0
[10.2.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.1.0...v10.2.0
[10.1.0]: https://github.com/andydardgallard/automated-code-factory/compare/v10.0.0...v10.1.0
[10.0.0]: https://github.com/andydardgallard/automated-code-factory/releases/tag/v10.0.0

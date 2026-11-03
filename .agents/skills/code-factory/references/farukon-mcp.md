# Farukon MCP (conditional platform path)

The factory's ONLY trading-platform MCP, and a conditional capability: it exists for tasks that
develop, build, run, test or debug the Farukon trading platform, and is invisible for every other
task.

## 1. When the path activates

The decision is deterministic and carries a REASON (never a model call):
`farukon_mcp.py decide --task-file .code-factory/state/task.yaml --repo <resolved repo_path>`.

- `applicable` / `not_applicable` plus the matched platform terms and repository signals. TWO
  independent conditions must hold: the repository HOSTS the platform (`farukon_mcp/Cargo.toml`, a
  `farukon_mcp` workspace member, or an existing `farukon` entry in `.kimi-code/mcp.json`) AND the
  task scope names a platform OPERATION (build/run/test/debug, start/stop, connectors, portfolio
  snapshot, message log, web health) BOUND to the platform itself. The scope needs both a platform
  IDENTITY term and an OPERATION term, and the operation must operate on the platform: "run / test /
  debug / build the platform" is applicable, while naming the platform alone, an operation on some
  OTHER subject ("run the parser test suite"), and an operation on DOCUMENTATION ("run the
  documentation build" — even when the same task also edits the Farukon README) all stay
  `not_applicable`. A documentation-only task — or a task that merely mentions the platform in
  passing — therefore stays `not_applicable`.
- The keyword scoring is weighted and explicit: identity terms name the platform but carry one point
  each, so naming the project can never reach the threshold; a scope only activates the role when
  its weighted score is at least `SCOPE_APPLICABLE_SCORE` (3), it carries at least one IDENTITY term
  and at least one OPERATION term, and at least ONE occurrence of that operation term is not bound
  to a documentation/media object (`NON_PLATFORM_OBJECTS` — `documentation`, `readme`, `doc`,
  `report`, `diagram`, … — inspected three words before and after the occurrence). Binding is per
  OCCURRENCE, so "update the Farukon README and run the cargo test for the platform" still counts.
- The emitted reason states all of it, so a `not_applicable` decision is auditable without reading
  the code: the identity terms matched, the operation terms bound to the platform, and the operation
  terms DISCARDED because they bind to another subject, plus the score and the host signals.
- Task-file METADATA is not task scope: `models:`, `repo_path:`, `commit_exclude:`, `mode:` and
  `task_type:` are stripped before classification, so a task whose only mention of the platform is
  the `models.farukon_expert` key (a MODEL pin) never activates the specialist.
- An explicit exclusion phrase in the task text (`no mcp`, `without farukon`, `out of scope`) always
  wins: deactivating by mistake costs a missed specialist run, activating by mistake puts a
  cargo/MCP session on unrelated work — the conservative direction is deliberate.
- Decision and reasons go into the run plan/state; repository signals never force activation, and a
  green-field platform task still activates.
- Reference: `references/error-routing.md` §1 rows F1–F2 for the infrastructure failures of this
  path (ordered BEFORE the generic rows, so a cargo/MCP failure never matches a code row).

## 2. Server and configuration facts

- Server name `farukon`, transported over stdio, launched as
  `cargo run --quiet -p farukon_mcp --` with `cwd` = the ABSOLUTE, normalized platform root: the
  workspace has to resolve from the platform repository, not from whichever directory the Kimi
  session happens to use. The managed entry is ONE definition:
  `{"command": "cargo", "args": ["run", "--quiet", "-p", "farukon_mcp", "--"], "cwd": <repo>}`.
- `farukon_mcp.py merge-config --target <project>/.kimi-code/mcp.json` inserts only the
  `mcpServers.farukon` member and is IDEMPOTENT: every unrelated byte (other servers, settings, line
  endings) survives, an equal entry is reported `unchanged`, and a DIFFERENT existing `farukon`
  entry is preserved byte-for-byte and reported as a conflict (exit 3) instead of being overwritten.
  `--dry-run` prints the plan without writing.
- `merge-config` refuses a `--repo` that is not a Farukon platform root, a `--target` that escapes
  the repository (checked on the RESOLVED path, so a symlink or junction inside the repository that
  points outside it is refused too), and a config that is not valid JSON: nothing is written in
  those cases, because a config whose launch command cannot work is worse than no config. The write
  is ATOMIC (a same-directory temp file plus replace) and a write that cannot happen — a directory
  target, an unwritable path — is the documented exit-1 error, never a traceback and never a partial
  file.
- `validate-config --path <config>` checks a managed `farukon` entry against the reviewed invariants
  (`command`/`args` exactly the managed shape, `cwd` ABSOLUTE and an EXISTING directory) and reports
  EVERY problem, not just the first. Secrets are never echoed back: every human and `--json`
  diagnostic names the offending KEY and the managed shape, never the value an entry supplies (an MCP
  entry may carry a credential in `command`, `args` or another key), and a merge conflict reports the
  differing key NAMES only.
- MCP configuration takes effect in a NEW Kimi session; `/mcp` shows the connection status. A session
  started before the entry was merged has no `mcp__farukon__*` tools, whatever the config says.
- Workspace trust gates project MCP servers the same way it does for every stdio server: a HEADLESS
  run (`kimi -p`) cannot answer the trust prompt, so a scripted platform session sets
  `KIMI_CODE_TRUST_WORKSPACE=1` for that process only, after the reviewed config is in place.

## 3. Who does what (evidence split)

- `factory-farukon-expert` (coder-class, `sub-agents/farukon-expert.md`) implements, builds, runs and
  debugs the ASSIGNED platform files through the eight MCP tools and records SPECIALIST/DIAGNOSTIC
  artifacts under `.code-factory/logs/farukon/<run_id>/`. It never issues a final PASS for its own
  work.
- `factory-tester` independently executes the FINAL replay business scenario AFTER the last code
  change and owns the ACCEPTANCE artifacts in the same run directory, labelled and distinct from the
  specialist's (`references/verification-strategy.md` §3.2).
- `factory-coder` keeps non-platform work without routine platform access; analyzer, planner,
  diagnostician and reviewer stay read-only (the reviewer examines the diff and the signed evidence,
  never a live instance; the diagnostician reads saved artifacts and requests a rerun through the
  tester).
- Only these two roles receive the `mcp__farukon__*` tools. Platform implementation failures and
  review rework use the EXISTING coder route and `retry_counters.coder` — no separate budget or key.

## 4. Working with the platform (specialist and tester)

The platform is driven ONLY through the eight tools — a raw `cargo`/`curl`/`pkill` workaround is not
a substitute for a tool that exists:

1. `farukon_build` — compile the platform (no raw `cargo build`).
2. `farukon_cargo_test` — run the selected test targets (no raw `cargo test`).
3. `farukon_start` — start in `live` or `replay` mode; REPLAY is the preferred mode for evidence.
4. `farukon_stop` — always stop a started instance with a bounded wait, and verify it is gone.
5. `farukon_connector_state` — read connector state after a start.
6. `farukon_portfolio_snapshot` — read the portfolio snapshot.
7. `farukon_message_log` — read the bounded message log.
8. `farukon_web_health` — read the web/health endpoint.

A raw command is allowed only for an operation the eight tools do not cover, and the handoff names
that exception explicitly. Follow the project's coding style; minimal changes; re-check the scenario
on the current working tree after the change. A snapshot alone is not proof of behavior.

## 5. Safety defaults

- Read-only stage-1 platform: `order_capable` is false and there is NO order path. Never issue an
  order-like call, never enable an order path, never claim execution capability.
- Never connect to live QUIK unless the task explicitly says `live`; replay is the preferred mode for
  evidence.
- Every start gets a bounded stop in a `try/finally`; a leaked instance is a failure, not a note.
- No secrets in commands or artifacts: tokens, credentials and account identifiers are redacted
  before any evidence is written, and secrets stay out of configuration, artifacts and reports.
- Instance state, logs and snapshots are run artifacts under `.code-factory/logs/farukon/`, never
  committed into `memory/`.

## 6. Degradation contract

`farukon_mcp.py probe` (a WORKING cargo — present on PATH AND answering `--version`; whether the
repository really is a Farukon platform root; whether it holds a BUILDABLE `farukon_mcp` crate —
`farukon_mcp/Cargo.toml` or the manifest of a declared workspace member that really exists on disk; a
`members = [...]` declaration whose directory is missing builds nothing; the
managed `farukon` config entry, whose `cwd` must be THIS platform root and not merely an existing
directory; and — only with the opt-in `--check-mcp-start` — a bounded newline-delimited JSON-RPC
handshake that verifies all eight tools, up to 30 min for a cold cargo build) is fail-soft: a missing
or unproven capability is DATA with a reason, never a crash, and it never changes the exit code of
the run. The handshake claims no protocol version of its own: it sends one `initialize`, and the
`protocol_version` it reports is the one the SERVER answers (the platform server is the authority on
what it speaks, and a version mismatch shows up as that answer, not as a helper assumption).
`factory_preflight.py --farukon` appends the same block for an applicable run, without
building anything and without starting the server; its `usable` verdict is this probe's own, so a
registered `farukon` entry in a repository with no buildable crate is degraded, never usable, and an
exception inside the delegated probe is `degraded` with `probe_error` set — a failed inspection proves
nothing about the repository, so it is never reported `not_applicable` and its criteria stay
UNVERIFIED like any other degraded verdict. On a missing or incompatible capability:

- it is reported through the INFRASTRUCTURE route (`references/error-routing.md` §1 rows F1–F2:
  cargo not found / platform not buildable, and MCP connection/startup failure including
  farukon_mcp launch errors) — no new role, no new budget; a Rust `error[Exxxx]` in the log is an
  IMPLEMENTATION failure and keeps the coder route even when the log also carries cargo's final
  `could not compile` summary;
- the affected platform criteria stay explicitly UNVERIFIED — never MET, and no build output,
  connector state, snapshot or acceptance artifact is fabricated;
- a non-Farukon run never invokes the specialist, never starts the server and does not need cargo or
  a Rust toolchain to succeed.

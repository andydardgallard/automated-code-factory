# Chrome DevTools MCP (conditional browser path)

The factory's ONLY browser MCP, and a conditional capability: it exists for tasks that create,
change, fix or visually validate a browser-based Web GUI, and is invisible for every other task.

## 1. When the path activates

The decision is deterministic and carries a REASON (never a model call):
`chrome_devtools_mcp.py decide --task-file .code-factory/state/task.yaml --repo <resolved repo_path>`.

- `applicable` / `not_applicable` plus the matched GUI/backend terms and repository signals; an
  explicit exclusion in the task text (`backend-only`, `no web UI`, `out of scope`) always wins.
- `discover-e2e --repo <root>` names the project's EXISTING browser/E2E stack (Playwright Test,
  Cypress, WebdriverIO, Selenium) and its config file.
- `browser-matrix` derives the required matrix from the acceptance criteria — never assumed.
- Decision, discovered stack and reasons go into the run plan/state; repository signals (an existing
  frontend) never force activation, while a green-field Web GUI task still activates.

## 2. Server and configuration facts

- Server name `chrome-devtools`, transport `stdio`, launched as
  `node <ABSOLUTE path of the vendored package entry>` — never `npx`/`npx.cmd`: the Kimi Code CLI
  spawns stdio servers WITHOUT a shell, so `command: "npx"` dies with `spawn npx ENOENT` and
  `command: "npx.cmd"` with `spawn EINVAL` on Windows (a `.cmd` is not an executable image). The
  release is PINNED (`chrome-devtools-mcp@1.11.0`, never `@latest`) and the template is
  `assets/chrome-devtools.mcp.json`.
- That template carries the entry path as the placeholder `{CHROME_DEVTOOLS_MCP_ENTRY}` (the path is
  per-installation) and the reviewed pin in its `codeFactory` block; the block is TEMPLATE metadata
  and never lands in a deployed `mcp.json`, the `type: "stdio"` field is not part of the documented
  Kimi schema and is not written either.
- Deployment installs the pinned package ONCE into
  `<project>/.kimi-code/vendor/chrome-devtools-mcp/` and only THEN merges the entry:
  `chrome_devtools_mcp.py vendor-install --target <vendor dir> --asset <template>` runs
  `npm install --prefix <vendor dir> --no-save --ignore-scripts --omit=dev chrome-devtools-mcp@1.11.0`
  — `--ignore-scripts` because npm package scripts are arbitrary code and must never run at deploy
  time — and `merge-config --target <project>/.kimi-code/mcp.json` deep-merges the managed entry:
  idempotent, every other server and setting preserved byte-for-byte, an existing different
  `chrome-devtools` entry reported (exit 3) instead of overwritten.
- When python, node or npm is missing, or the install fails, NOTHING is written: an absent server
  that is REPORTED (`chrome-devtools MCP: package install skipped/failed — <reason>` in both
  deployers, `prepare_factory.sh` and `prepare_factory.cmd` → `prepare_factory.ps1`) is strictly
  better than a config whose launch file does not exist, and `merge-config` refuses to point at a
  missing entry at all. Without a working interpreter an existing `.kimi-code/mcp.json` is left
  untouched and no new one is created.
- Both deployers add `.kimi-code/vendor/` AND `.kimi-code/mcp.json` to the prepared project's
  `.gitignore`. Both are machine-local: the vendored package belongs to that installation, and the
  managed entry carries the ABSOLUTE path of this installation's vendored entry, so a committed
  config would hand a fresh clone a launch path that does not exist there. A clean clone therefore
  has no browser path until it is deployed itself — ignoring the config never removes it from disk,
  so the readiness report still prints its created/updated/unchanged/conflict state.
- `validate-config --path <config>` checks a managed config against the reviewed safety invariants
  and reports EVERY problem, not just the first: a non-object `env` (string, list, number, boolean)
  is a validation problem — only JSON `null` or an absent key means "no environment" — so a
  malformed `env` is reported as data and never raises. Secret scanning rejects a credential-like
  VALUE and equally a credential-like variable NAME (`API_KEY`, `token`, `password`, …) carrying a
  non-empty value; the report names the variable and the reason and never the value, because an
  opaque value contains no keyword to match.
- MCP configuration takes effect in a NEW Kimi session; `/mcp` shows the connection status. A session
  started before the deployment has no browser tools, whatever the config says.
- Workspace trust gates project MCP servers: an interactive session shows the trust prompt listing each
  server's launch target; a HEADLESS run (`kimi -p`) cannot prompt, so project-level servers stay
  disabled unless the workspace is already trusted — for scripted browser runs set
  `KIMI_CODE_TRUST_WORKSPACE=1` for that process only (never a global/user-level trust change), after
  the reviewed local config is in place.
- Flag details (`--isolated`, `--channel`, redaction, statistics/CrUX switches) come from the upstream
  docs — read the materialized snapshot of the `reference_docs` entry `chrome-devtools-mcp`; this
  file does not duplicate them.

## 3. Who does what (evidence split)

- `factory-gui-expert` (coder-class, `sub-agents/gui-expert.md`) implements and interactively debugs
  the ASSIGNED UI files, may capture a baseline, and records DIAGNOSTIC artifacts under
  `.code-factory/logs/browser/` (run_id-stamped). It never issues a final PASS for its own work.
- `factory-tester` independently executes the FINAL browser business scenario AFTER the last code
  change and owns the ACCEPTANCE artifacts in the same directory, labelled and distinct from the
  specialist's (`references/verification-strategy.md` §3.1).
- `factory-coder` keeps non-GUI work without routine browser access; analyzer, planner, diagnostician
  and reviewer stay read-only (the reviewer examines the diff and the signed evidence, never the
  browser; the diagnostician reads saved artifacts and requests a rerun through the tester).
- Only these two roles receive the `mcp__chrome-devtools__*` tools. GUI implementation failures and
  review rework use the EXISTING coder route and `retry_counters.coder` — no separate budget or key.

## 4. Working with the browser (specialist and tester)

1. Navigate to the resolved LOCAL/test application and take a FRESH accessibility snapshot before
   interacting — element interaction uses the snapshot, not guessed selectors.
2. Exercise the user scenario; inspect console and network for errors and failed requests, and
   capture visual evidence at the viewport the acceptance criteria require.
3. Add performance traces only when performance is in scope.
4. Follow the project's coding style; minimal changes; re-check the scenario on the current working
   tree after the change. A screenshot alone is not proof of behavior.

## 5. Safety defaults (enforced by the managed config)

- Isolated TEMPORARY Chrome profile and test data; never the user's personal profile, cookies or
  saved credentials; no attaching to a running browser (`autoConnect`/remote-debugging) unless the
  user explicitly opts in; no blanket MCP permission rule.
- Usage statistics and CrUX lookups disabled, update checks disabled; sensitive network headers
  redacted; secrets stay out of configuration, artifacts and reports.
- Automated navigation and mutations are restricted to the local/test application required by the
  task. Browser profiles, screenshots and traces are run artifacts, never committed into `memory/`.

## 6. Degradation contract

`chrome_devtools_mcp.py probe` (Node.js, npm/npx, Google Chrome or Chrome for Testing, the vendored
package entry of a given project config — `probe --target <project>/.kimi-code/mcp.json` — and MCP
server start feasibility) is fail-soft: a missing capability is DATA with a reason, never a crash;
`factory_preflight.py --web-gui` appends the same block for an applicable run. Its `mcp_usable` is
true only for a REAL deployment: the run's resolved repository must have a valid
`.kimi-code/mcp.json` (the `validate-config` invariants) AND the pinned vendored entry that config
launches must be on disk at the pinned version. Anything less reports the MCP server as missing with
the exact reason, because a usable verdict from the shipped template alone would make a clean clone
look deployed; `--simulate-missing <name>` forces one capability to report missing without touching
the host, and the block never changes the pre-flight exit code. On a missing or incompatible
capability:

- it is reported through the INFRASTRUCTURE route (`references/error-routing.md` §1 rows I1–I4:
  node/npm/npx not found, Chrome/Chrome for Testing missing, MCP connection/startup failure,
  chrome-devtools-mcp launch errors) — no new role, no new budget. Row I1 matches BOTH lines this
  module really emits, in their own wording: the probe's
  `<node|npm|npx> was not found on PATH; a Web GUI run cannot start …` AND the installer's
  `<node|npm> was not found on PATH: the pinned chrome-devtools-mcp@<version> cannot be
  installed …` (`vendor-install` checks those two tools only — never `npx`). A missing-Node
  deployment therefore reaches the same automatic infrastructure route as a missing-Node run, and
  neither line is retranslated to be classified;
- the affected browser criteria stay explicitly UNVERIFIED — never MET, and no screenshot, console
  result or acceptance artifact is fabricated;
- a non-Web-GUI run never invokes the specialist, launches Chrome or calls a browser tool, and does
  not need Node.js or Chrome to succeed.

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
- `.kimi-code/vendor/` is machine-local and git-ignored (the deployers add the pattern to the target
  project too); the repo's own `.kimi-code/mcp.json` is machine-local as well, since the managed
  entry holds an absolute path.
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
`factory_preflight.py --web-gui` appends the same block for an applicable run. On a missing or
incompatible capability:

- it is reported through the INFRASTRUCTURE route (`references/error-routing.md` §1 rows I1–I4:
  node/npm/npx not found, Chrome/Chrome for Testing missing, MCP connection/startup failure,
  chrome-devtools-mcp launch errors) — no new role, no new budget;
- the affected browser criteria stay explicitly UNVERIFIED — never MET, and no screenshot, console
  result or acceptance artifact is fabricated;
- a non-Web-GUI run never invokes the specialist, launches Chrome or calls a browser tool, and does
  not need Node.js or Chrome to succeed.

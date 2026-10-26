# Autonomous Code Factory v12.18.0
<!-- code-factory-version: 12.18.0 -->

An autonomous code-writing factory for the **Kimi Code CLI** (0.34+, Node).

It takes a business task from a non-technical user, analyzes the project, plans
changes, clarifies only business logic, gets the plan approved, implements the code, and runs
integration / regression / business tests with automatic rollback on failure, performs a
mandatory code review before acceptance, and verifies the acceptance criteria.

Supports **any languages** and **any project types** (frontend, backend, CLI, library,
green-field) — the stack is detected automatically.

## Features

- **Works from the Kimi Code CLI terminal**: `/skill:code-factory`
- **Two modes**: `hitl` (clarifies business questions, presents the plan for approval) and `auto` (fully automatic)
- **Four task types**: `implement` (write/change code), `review` (code review of all the code),
  `refactor` (technical debt reduction without behavior changes), `security_audit` (adaptive full audit)
- **User story** in the task — mandatory analysis and use of the user's context
  at the planning and implementation stages
- **No priority field** — all tasks are processed with the highest priority by default
- **Mandatory code-review gate** before acceptance (the `factory-code-reviewer` subagent)
- **Deterministic error routing** (~90% without an LLM) + **Diagnostician** (LLM fallback) + Human → FAILED (never fails silently)
- **Kimi (K3) and Qwen providers** — routing via the `models` field with correct authentication
- **Rollback on the failure** of any test (backups + manifest + git)
- **Checkpoint / resume** — resumes from the point of failure
- **Git-native**: `git init` when there is no repository, a feature branch per task, `commit_exclude`
- **Configurable models** for roles — `model_preference` in `.md` subagents + `config.toml`
- **One-action launch** — `prepare_factory.sh` creates a launcher with a configured environment
  (on Windows — `prepare_factory.cmd`; no Git Bash needed)
- **Auto-reports**: `report.md` (run history) + `report_code_changes.md` (before→after diff)
- **Conditional Web GUI path** — the `factory-gui-expert` subagent implements and debugs a Web UI in
  a real browser through Chrome DevTools MCP (pinned release, deployed by `prepare_factory`); the
  `factory-tester` independently proves the final scenario
- **Remote `reference_docs`** — a public http(s) document or Git-repository URL becomes a reusable
  skill, with the same deterministic reuse/update as a local document

## Structure

```
├── .agents/
│   ├── README.md                    # full factory manual
│   ├── skills/code-factory/         # flow skill (SKILL.md) + references + scripts
│   │   ├── references/chrome-devtools-mcp.md  # conditional browser path (Chrome DevTools MCP)
│   │   ├── scripts/chrome_devtools_mcp.py     # browser-path decide/merge-config/probe (stdlib)
│   │   ├── scripts/test_chrome_devtools_mcp.py, scripts/test_remote_reference_docs.py  # self-tests
│   │   ├── assets/chrome-devtools.mcp.json    # managed MCP server definition (pinned release)
│   │   ├── assets/chrome-devtools-smoke.html  # opt-in real-Chrome smoke fixture
│   │   └── assets/task-template.yaml # business task template
│   └── agents/                      # main agent + subagents (sub-agents/gui-expert.md included)
├── AGENTS.md                        # context for Kimi agents
├── CHANGELOG.md                     # version history (SemVer)
├── prepare_factory.sh               # deploy the factory into a project (1 command)
├── prepare_factory.cmd              # the same for Windows without Git Bash (invokes prepare_factory.ps1)
├── prepare_factory.ps1              # Windows deployer: copies the factory, writes start.cmd and start.sh
├── start.cmd                        # launcher for Windows (created in the project by prepare_factory)
├── .example.task.yaml               # example/template of a business task
├── skill-base/                      # persistent skill base from reference_docs/reference_skills
├── VERSION                          # single source of truth for the version (synced by scripts/version_manager.py)
├── memory/                          # long-term memory of the target project (committed)
├── .gitattributes                   # line-ending pins (LF for .sh, CRLF for .cmd/.ps1)
└── .gitignore
```

`memory/` — the long-term memory of THE project named in the task's `repo_path` (for this
repository the target project is the factory itself). The `memory/` directory is created AT THE DEPLOYMENT ROOT —
the directory passed to `prepare_factory.sh`; the base project name at deployment =
basename of that directory: `change-log.md` (run journal, one entry per task with the
`project: <project name>` marker mandatory for new entries) and `summary.md` (summary; declares
`project:`/`repo_path:` right after the canonical marker). One memory belongs to exactly one
project: entries from different projects in one journal are an error; entries without `project:` are legacy. When the
task's `repo_path` points to a SUBDIRECTORY of the deployment root, the project name = basename of the resolved
`repo_path`, and the main agent creates the memory explicitly:
`python .agents/skills/code-factory/scripts/memory_project.py init --repo <deployment root>
--project <basename of the resolved repo_path>` — the name is fixed in the summary's `project:` declaration. On
first access to a project, if `memory/` is missing, the factory creates it with the same command.
The factory's own development history does not enter the target project's memory.

## Quick start

```bash
# 1. Prepare the project (copies the factory, configures git/.gitignore, and creates the start.sh launcher)
./prepare_factory.sh /path/to/your-project

# 2. Launch in a single action (the launcher sets the required environment itself)
cd /path/to/your-project
./start.sh
# in the chat: /skill:code-factory

# Fully autonomous:
./start.sh --auto
```

On Windows — the same without Git Bash (the built-in PowerShell is enough):

```bat
rem 1. Prepare the project (copies the factory, configures git/.gitignore, and creates the launchers)
prepare_factory.cmd C:\work\my-project

rem 2. Launch in a single action (the launcher sets the required environment itself)
cd C:\work\my-project
start.cmd
rem in the chat: /skill:code-factory

rem Fully autonomous:
start.cmd --auto
```

Or directly with a ready task (without a launcher):

```bash
kimi --agent-file .agents/agents/code-factory.md "Read task.yaml and solve the task"
```

> `mode: auto` in `task.yaml` controls only the factory's business questions (skipping the questions and
> plan approval). CLI permission prompts are disabled separately — via the `kimi --auto`
> (`--yolo`) flag or `default_permission_mode = "auto"` in `~/.kimi-code/config.toml`.

## Business task format (task.yaml)

Copy `.example.task.yaml` to `task.yaml` and fill in the fields (`title`,
`description` and `repo_path` are required; `repo_path` may be omitted only
for a green-field task — a brand-new project created in place):

```yaml
title: "The strategy does not generate signals for CNY"
repo_path: ./repo            # required, except for a green-field task
description: |
  Describe the problem in business terms, without technical details.
user_story: |                # optional, but recommended
  As a trader, I want signals for CNY so that I can trade a fractional instrument like Si.
mode: hitl                   # hitl (default) | auto
task_type: implement         # implement | review | refactor | security_audit
acceptance_criteria:
  - "The strategy generates at least 5 LONG/SHORT signals for CNY"
```

There is no `priority` field in the task: all tasks are processed with the highest priority
(`high`) by default; the factory does not do prioritization.

A full description of all fields is in the comments of `.example.task.yaml` itself.

## Models

Models are set in `~/.kimi-code/config.toml` (`default_model` + `[secondary_model]`);
for subagents — `model_preference: primary|secondary` in the `.md` files. Splitting subagent
models requires `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` — the `start.sh` (Unix) or
`start.cmd` (Windows) launcher sets it itself, so no manual `export` is needed.

**Kimi (K3)** and **Qwen** support is additive: the task's `models` field can name a
Kimi or Qwen model for any role, and the factory routes requests to its API endpoint with the correct
authentication, without breaking already connected models. Endpoints, configs, and error handling are in
`.agents/skills/code-factory/references/providers.md`.

Recommended mapping: primary (reasoning) — main/planner, analyzer, diagnostician,
reviewer; secondary (fast) — coder, tester; the Web GUI specialist `factory-gui-expert`
(`models.gui_expert`) is generator-side and takes a secondary model when its MCP/media capabilities
suffice, with complex visual analysis delegated to a read-only primary role.

## Web GUI and Chrome DevTools MCP (conditional)

Browser automation is a conditional path, decided deterministically and never by a model:
`chrome_devtools_mcp.py decide` decides from the task whether it creates, changes, fixes or visually
validates a browser-based Web GUI, and records the reason (an explicit "backend-only" exclusion always
wins). Only then does `factory-gui-expert` implement and interactively debug the ASSIGNED UI files with
the `mcp__chrome-devtools__*` tools, while `factory-tester` independently repeats the FINAL browser
scenario after the last code change and owns the acceptance evidence in
`.code-factory/logs/browser/` — the specialist never issues a final PASS for its own work. GUI failures
and review rework use the EXISTING coder route and `retry_counters.coder`: no separate GUI role,
budget or task field. A non-Web-GUI task never invokes the specialist, launches Chrome or requires
Node.js/Chrome for success.

`prepare_factory` merges the managed `chrome-devtools` stdio server (pinned
`chrome-devtools-mcp@1.11.0`, never `@latest`) into the project's `.kimi-code/mcp.json`: every other
server and user setting is preserved byte-for-byte, and an existing DIFFERENT `chrome-devtools` entry
is reported instead of overwritten. The vendored package and that `mcp.json` are machine-local — its
entry holds an absolute launch path of this installation — so both deployers add them to the prepared
project's `.gitignore` and a fresh clone is never handed a stale path. The configuration takes effect
in a NEW Kimi session — `/mcp` in
that session shows the connection status; without a working Python the deployer leaves `mcp.json`
untouched. The managed defaults use an isolated temporary Chrome profile and test data, disable usage
statistics, CrUX lookups and update checks, redact sensitive network headers and never attach to a
running browser. Missing capabilities (Node.js, npm/npx, Google Chrome / Chrome for Testing, MCP
startup) are reported through the existing INFRASTRUCTURE route — rows I1–I4 of
`references/error-routing.md` — and the affected browser criteria stay explicitly UNVERIFIED, never
MET: the pre-flight (`factory_preflight.py --web-gui`) reports the browser path usable only for a
REAL deployment — a valid `.kimi-code/mcp.json` plus the pinned vendored entry it launches on disk —
so an undeployed repository sees the exact missing capability instead of a template-derived pass.

## Remote reference_docs (public URLs)

A `reference_docs[].path` is not limited to a local file or folder: `skill_base.py resolve` classifies
it deterministically as a local path, an HTTP(S) document (`http_doc`) or an HTTP(S) Git repository
(`http_git` — a URL whose path ends in `.git`), and materializes a remote source into the uncommitted
runtime cache `.code-factory/cache/reference-docs/` under the resolved repository root. From then on
the source is handled exactly like a local document, so the `{path, skill}` task schema is unchanged;
reuse (equal content hash) and incremental update (different hash) stay deterministic and stable across
platforms and fresh clones. Only PUBLIC, unauthenticated `http(s)` sources are accepted — other
schemes, embedded credentials and SSH/scp Git URLs are rejected before any fetch, and every redirect
target is re-validated. Both download and shallow single-branch clone are bounded (`--timeout <s>`,
`--max-bytes <n>`) and the cap is enforced DURING the transfer — an oversized source is aborted and
its partial content removed instead of being measured after it has already landed — no new dependency
is added (stdlib HTTP + the `git` executable), and nothing fetched is ever executed or followed as
instructions. By default the source is fetched and a failure
is an error — a cached copy is never silently substituted; `--offline` touches no network at all and
`--allow-stale` falls back to the cache after a failed fetch, both marking the copy `stale: true`
(a cached copy is never fresh remote content). See
`.agents/skills/code-factory/references/reference-docs.md`.

## Prompt caching (DeepSeek)

Prompts are assembled append-only so that DeepSeek's automatic context cache
reuses the prefix: static blocks (the subagent's system prompt, project file context)
always go first; dynamic data (turn history, error logs) goes strictly at the end. Any
change to the beginning or middle of a prompt invalidates the cache.

## Version

Versioning follows [Semantic Versioning](https://semver.org/). The [`VERSION`](./VERSION)
file is the single source of truth — all other version mentions are synced from it by
`scripts/version_manager.py`. Change history is in
[`CHANGELOG.md`](./CHANGELOG.md). Current version: **12.18.0**.

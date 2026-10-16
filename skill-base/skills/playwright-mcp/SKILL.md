---
name: playwright-mcp
description: Factual reference on the Playwright MCP server (@playwright/mcp) — installation, core features, configuration and security caveats. Comparative reference material only; Playwright MCP itself is NOT part of the factory's tooling.
---

# Playwright MCP

## Overview

The Playwright MCP server (`@playwright/mcp`, Microsoft) provides browser automation to LLM
agents through the Model Context Protocol. Its defining trait: it drives pages via **structured
accessibility snapshots** (the a11y tree with element roles and `ref=eN` handles), not pixels or
screenshots, so no vision model is required. It works with any MCP client (VS Code, Cursor,
Windsurf, Claude Code/Desktop, etc.).

This skill is **comparative reference material** for the factory: it documents what Playwright MCP
is and how it behaves so agents can compare it with the factory's actual browser tooling. Do not
assume Playwright MCP is installed or available in the factory runtime.

## Key concepts

- **Installation**: standard MCP client config — `{"command": "npx", "args": ["@playwright/mcp@latest"]}`;
  VS Code also supports `code --add-mcp '{...}'`, Claude Code `claude mcp add playwright npx @playwright/mcp@latest`.
  Prerequisites: Node.js 20+ and an MCP client.
- **Accessibility snapshots**: tools return a structured snapshot (e.g. `textbox "..." [ref=e5]`);
  the LLM interacts with elements by those refs.
- **Interaction tools**: navigation (open URL, back/forward, reload), clicking/typing/form fill,
  dropdown selection, keyboard/mouse (hover, drag & drop), dialog accept/dismiss, tab management,
  screenshots for visual verification.
- **`browser_run_code_unsafe`**: executes arbitrary Playwright JavaScript in the server process —
  **RCE-equivalent**, only for trusted MCP clients.
- **Network**: list requests since page load, mock routes by URL pattern, read console messages.
- **Storage state**: save/restore cookies + localStorage; per-cookie list/get/set/delete.
- **WebMCP tools (experimental)**: pages can register their own tools exposed as `webmcp_<tool>`;
  tool names/schemas/results come from the page and must be treated as untrusted input.

## How to use

- Configuration flags passed via `args`:
  - `--headless` — headed mode is the default.
  - `--browser=chrome|firefox|webkit|msedge` — browser selection.
  - Profile modes: **persistent** (default; profile stored under
    `ms-playwright/mcp-{channel}-{workspace-hash}` in the OS cache dir, per-project isolation;
    override with `--user-data-dir`), **isolated** (`--isolated`, fresh session each time,
    optional `--storage-state`), **browser extension** (`--extension`, attach to existing tabs).
  - `--idle-timeout=<ms>` — a server-launched headless browser is closed after 1h without tool
    calls (0 disables); with `--isolated` an idle close loses in-memory cookies/storage; with
    `--cdp-endpoint`/`--extension` the browser is never auto-closed (an explicit timeout only
    disconnects); with `--shared-browser-context` the timer spans all clients.
  - `--config path/to/config.json` — JSON config file (browser/context options, network rules,
    timeouts); full schema in the `playwright-mcp` repo's `config.d.ts`.
  - Standalone HTTP server: `npx @playwright/mcp@latest --port 8931`, then point the client at
    `http://localhost:8931/mcp`. HTTP sessions use a 5s heartbeat; tune with
    `PLAYWRIGHT_MCP_PING_TIMEOUT_MS` (0 disables).
- Typical agent usage is prompt-driven ("Navigate to X and add todo items"); a quick-reference
  table maps actions (navigate, click, fill form, screenshot, run code, mock API) to prompts.

## Constraints

- Playwright MCP is **out of scope for the factory**: this skill is reference only; never plan
  factory work that requires it to be installed or executed.
- Requires Node.js 20+; browsers are the Playwright-managed ones (chrome/firefox/webkit/msedge).
- `browser_run_code_unsafe` is remote-code-execution-equivalent — a hard security boundary.
- WebMCP-provided tools are page-supplied and untrusted.
- Content source: https://playwright.dev/docs/getting-started-mcp (snapshot of the stable docs page).

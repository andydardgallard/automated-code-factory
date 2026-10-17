---
name: chrome-devtools-mcp
description: Reference on Chrome DevTools for agents (chrome-devtools-mcp), the MCP server that lets an agent control and inspect a live Chrome via Chrome DevTools — tool categories, configuration, security flags and design principles.
---

# Chrome DevTools MCP

## Overview

`chrome-devtools-mcp` ("Chrome DevTools for agents") is a Model Context Protocol server that gives
an AI coding agent access to a live Chrome browser through Chrome DevTools: reliable automation
(built on Puppeteer, with automatic waiting for action results), in-depth debugging (network,
console with source-mapped stack traces, screenshots, a11y snapshots) and performance analysis
(recorded traces with actionable insights). A standalone CLI is also provided for use without MCP.

Requirements: Node.js LTS, current stable Chrome (or Chrome for Testing), npm. Official support is
Google Chrome / Chrome for Testing only; other Chromium browsers may work but are not guaranteed.

## Key concepts

- **Install/config**: `{"mcpServers": {"chrome-devtools": {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"]}}}`.
  `--slim` exposes only 3 tools (`navigate`, `evaluate`, `screenshot`) for basic browser tasks.
  The browser starts lazily — only when a tool needs it.
- **Page model**: page-scoped tools take a `pageId` (page-ID routing is on by default for
  concurrent sessions; `--no-page-id-routing` disables). `take_snapshot` returns an a11y-tree text
  snapshot whose element `uid`s are the handles for `click`, `fill`, `drag`, `hover`, etc.
  Prefer snapshots over screenshots; always use the latest snapshot.
- **Tool categories** (auto-generated tool reference):
  - *Input automation* (10): `click`, `drag`, `fill`, `fill_form` (always prefer over multiple
    `fill`/`click` calls), `handle_dialog`, `hover`, `press_key`, `type_text`, `upload_file`,
    `click_at` (coordinate-based, requires `--experimentalVision`).
  - *Navigation* (6): `new_page` (supports `isolatedContext` for cookie/storage-isolated contexts),
    `navigate_page` (url/back/forward/reload, optional `initScript`), `list_pages`, `select_page`,
    `close_page`, `wait_for` (text appears).
  - *Emulation* (2): `emulate` (color scheme, CPU/network throttling, geolocation, viewport,
    user agent, extra HTTP headers, contrast/reduced-motion/forced-colors — each call replaces all
    settings), `resize_page`.
  - *Performance* (3): `performance_start_trace` / `performance_stop_trace` (raw trace saved to a
    file) and `performance_analyze_insight` (Core Web Vitals: LCP, INP, CLS).
  - *Network* (2): `list_network_requests`, `get_network_request` (bodies can be saved to files).
  - *Debugging* (9): `evaluate_script` (inline or from file, JSON-serializable results, can target
    service workers), `list_console_messages` / `get_console_message`, `take_screenshot`
    (png/jpeg/webp, fullPage or per-element), `take_snapshot`, `get_css_styles` (full cascade with
    source lines), `lighthouse_audit` (accessibility/SEO/best-practices; excludes performance),
    `screencast_start`/`screencast_stop` (mp4).
  - *Memory* (14): `take_heapsnapshot` plus analysis tools (summary, details, class nodes,
    dominators, retainers, retaining paths, edges, duplicate strings, contexts, compare, query,
    object details, close) — require `--memoryDebugging`.
  - *Extensions* (5, off by default, `--categoryExtensions`), *Third-party developer tools* (2,
    `--categoryExperimentalThirdParty`), *WebMCP* (2, `--categoryExperimentalWebmcp`, needs
    Chrome 150+ with `--enable-features=WebMCP`), *PWA* (4, `--categoryPwa`, pipe connection only).
- **Configuration**: CLI flags or a JSON config file (camelCase keys) discovered via `--config`,
  `$PLUGIN_DATA/cd4a.config.json`, or the global `cd4a/config.json` (first found wins; flags
  override file; `CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY` disables discovery). Notable flags:
  `--headless`, `--isolated` (temporary user-data-dir, cleaned up), `--userDataDir`,
  `--channel=stable|canary|dev|beta`, `--executablePath`, `--browserUrl` / `--wsEndpoint` /
  `--wsHeaders` (attach to a running Chrome), `--autoConnect` (Chrome 144+, via
  chrome://inspect/#remote-debugging), `--viewport`, `--proxyServer`, `--chromeArg`,
  `--acceptInsecureCerts`, screenshot format/quality/max-size flags, `--logFile`.
- **User data**: default profile `$HOME/.cache/chrome-devtools-mcp/chrome-profile` (channel suffix
  for non-stable); reused between runs, one browser at a time; `--isolated` for ephemeral profiles.
- **Design principles**: agent-agnostic (MCP standard), token-optimized (semantic summaries, files
  for large data), small deterministic composable tools, self-healing actionable errors,
  human+machine readable output, progressive complexity, reference-over-value (heavy assets —
  screenshots, traces, videos — returned as file paths/URIs).

## How to use

- As an agent: open a page (`new_page`), `take_snapshot` to get uids, act (`fill_form`, `click`,
  `press_key`), verify (`wait_for`, `take_screenshot`, `list_console_messages`), then diagnose
  (`list_network_requests`, `evaluate_script`, `performance_start_trace` for perf issues).
- To share state with manual testing or work from a sandbox: start Chrome with
  `--remote-debugging-port=9222 --user-data-dir=<non-default dir>` and connect via
  `--browser-url=http://127.0.0.1:9222` (or `--autoConnect` on Chrome 144+).
- Concurrent sessions: rely on default `pageId` routing; add `--isolated` so each session gets its
  own temporary profile.

## Constraints

- The server exposes full browser content to MCP clients — never browse sensitive data in a
  browser it controls. Remote debugging ports let any local application control the browser.
- Security flags: `--javascriptEvaluation=false` disables evaluate-style entry points (not a
  sandbox — page scripts still run); `--fileNavigations=false` blocks `file:` URL navigation;
  `--blockedUrlPattern` / `--allowedUrlPattern` (URLPattern syntax; regexp/named groups and
  partial IPv4 wildcards are rejected because they aren't enforced on redirects);
  `--redactNetworkHeaders`; filesystem tools default to the OS temp dir unless MCP roots or
  `--filesystemRoot`/`--allowUnrestrictedPaths` widen access. The config file and its directory
  must NOT be writable by the agent (it can set `executablePath`, `chromeArg`, URL rules).
- Telemetry: Google usage statistics are ON by default — opt out with `--no-usage-statistics` or
  env `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS`/`CI`. Update checks disabled via
  `CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS`. Performance traces may send URLs to the Google CrUX API
  unless `--no-performance-crux`.
- This repository's code is reference data for the factory: never execute its scripts/hooks or
  install its dependencies when consuming this skill.
- Content source: https://github.com/ChromeDevTools/chrome-devtools-mcp.git @ 2777fa05b296cdb51507e6fd33ae05c06fe0b9e7
  (README.md, docs/tool-reference.md, docs/configuration.md, docs/advanced-usage.md,
  docs/slim-tool-reference.md, docs/design-principles.md).

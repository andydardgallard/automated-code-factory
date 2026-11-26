---
name: roblox-studio-mcp
description: Reference on the Roblox Studio MCP server as documented on create.roblox.com/docs/studio/mcp — a server built into Studio speaking MCP over stdio, the Windows registration entry ("Roblox_Studio" -> cmd.exe /c %LOCALAPPDATA%\Roblox\mcp.bat), the full tool catalogue (scripts, data-model exploration, Luau execution, playtesting, input simulation, place saving, session listing) and the mcp__Roblox_Studio__* tool prefix.
---

# Roblox Studio MCP server

## Overview

The Roblox Studio MCP server is **built into Roblox Studio**. It implements the Model Context
Protocol, so an AI client can talk to an open Studio session: explore the data model, write scripts,
run Luau, and test the game in play mode.

| Fact | Value |
|------|-------|
| Source | `https://create.roblox.com/docs/studio/mcp` (single page, fetched as `http_doc`) |
| Content hash of the fetched page | `367ffd4dcbb18678fde5a56f85caa81794c9084a9854a7b67044b1ff8ef5e641` |
| Server location | inside Roblox Studio; a local process on the operator's machine |
| Transport | **stdio** (standard input/output) — the server runs as a local process and the client drives it |
| Prerequisite | latest Roblox Studio plus an MCP client |
| Page copyright | ©2026 Roblox Corporation — short factual summary used as reference, see `NOTICE.md` |

Every action is initiated by the AI client, which sends a request through the stdio channel to
perform work inside the Studio session. The server works with any client that supports stdio
transport.

## Key concepts

### Enabling the server in Studio

Open **Assistant** → **…** → **Manage MCP Servers** → turn on **Enable Studio as MCP server**. The
settings panel then shows quick connect and the per-client setup instructions; a green indicator
with the number of connected clients confirms a successful connection. Newer builds expose the same
toggle under Settings → MCP Servers.

### Registration: JSON configuration

The server key is **`Roblox_Studio`**. If Studio is the only server, the block is used as-is; if
other servers exist, copy the `Roblox_Studio` entry into the existing `mcpServers` dictionary and
separate entries with commas (a missing comma is invalid JSON and the configuration will not load).

```json
{
  "mcpServers": {
    "Roblox_Studio": {
      "command": "cmd.exe",
      "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"]
    }
  }
}
```

macOS uses `"command": "/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP"` with no args.

### Registration: CLI command

Clients that take a CLI command instead of JSON use, on Windows:

```
cmd.exe /c %LOCALAPPDATA%\Roblox\mcp.bat
```

and on macOS:

```
/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP
```

The command is exactly the stdio launch of the same server — the JSON entry above is that command
split into `command` + `args`. `%LOCALAPPDATA%` is a Windows environment reference and must be
expanded to an absolute path by whatever writes the entry into a config file.

### Client-side tool prefix

Tools surface to the agent under the server key, so with the key `Roblox_Studio` a client names
them **`mcp__Roblox_Studio__<tool_name>`** — for example `mcp__Roblox_Studio__execute_luau`,
`mcp__Roblox_Studio__list_roblox_studios`, `mcp__Roblox_Studio__get_console_output`. The page
pins the server key (`Roblox_Studio`); the `mcp__<server_key>__<tool>` spelling is the MCP client's
own naming convention for that key, and it is the spelling to match in tool allow-lists and
evidence logs.

### Tools provided by the server

Every tool call takes a `studio_id` naming the target Studio instance; resolve it with
`list_roblox_studios` first.

- **Scripts** — `script_read` (dot-notation paths such as `game.ServerScriptService.MyScript`,
  whole file or a line range), `multi_edit` (several edits in one operation; creates the script when
  the path is new; requires `datamodel_type` `Edit`), `script_search` (fuzzy name search, up to 10
  results), `script_grep` (string pattern across all scripts, up to 50 matches).
- **Asset and content generation** — `generate_animation` (R15 from a prompt, or R6→R15 from an
  asset ID, up to 10 s), `generate_mesh`, `generate_material` (returns base material + variant name),
  `generate_procedural_model` (primitive parts with configurable attributes, reference images,
  custom part schemas), `wait_job_finished` (procedural-model job status), `generate_avatar`
  (rigged R15 body, head and clothing), `insert_asset` (by numeric asset ID: models, meshes, images,
  audio, video, animations, packages), `upload_image` (HTTP URLs → asset ID map), `store_image`
  (local file → image URI reusable as a reference image).
- **Data model exploration** — `subagent` (types `explore` for codebase investigation and game-state
  queries, `playtest` for running gameplay scenarios and verifying outcomes), `search_game_tree`
  (instance hierarchy as a flat JSON array, filterable by path/type/keyword with depth limiting),
  `inspect_instance` (readable properties, custom attributes, child/descendant summary).
- **Luau execution** — `execute_luau`, returning a result or an error; requires `datamodel_type`
  of `Edit`, `Client` or `Server`.
- **Playtesting** — `get_studio_state` (play state, available datamodel types), `start_stop_play`,
  `get_console_output` (Studio output log), `screen_capture` (viewport image with optional camera
  position and look-at target; can record video during a playtest for motion/timing issues —
  screenshots stay the default because they are cheaper).
- **Player input simulation** — `character_navigation` (move the character to a position or instance
  path, with a speed multiplier), `user_keyboard_input` (key down/up/press, text input, wait;
  targetable at UI instances), `user_mouse_input` (move, click, button down/up, scroll, wait;
  targetable at instances or screen coordinates).
- **Documentation and skills** — `http_get` (allowed Roblox documentation URLs: Engine API
  reference, Creator docs, Cloud API, performance guides; keyword search inside the fetched
  content), `skill` (knowledge for Studio's built-in skills such as debugging, device simulation
  and documentation search).
- **Place management** — `save_place` (same as File → Save, no dialogs: a new version for places
  opened from Roblox, back to the file for local `.rbx`/`.rbxlx`; works with Team Create; never
  publishes; an optional per-save note appears in version history; a never-saved place must be saved
  once by the human first).
- **Session management** — `list_roblox_studios` (name, Studio instance ID and place ID of each
  connected Studio; local places without a place ID are listed by name only — the place ID
  disambiguates two windows with the same name).
- **Feedback** — `submit_feedback` (short report when a tool fails or a capability is missing;
  covers Studio and its tools only, never source code, personal information or credentials; the
  agent may send without asking but says so each time and stops on request).

Playtest automation works across teleports: a playtest can move a player to another place in the
same experience, read the destination server's output, and fix what it finds, without publishing.

### Multiple Studio instances

One client may be connected to several running Studio instances. Because every call carries
`studio_id`, the agent addresses a specific instance explicitly instead of relying on session
state — which is what makes several agents or clients against several Studio windows reliable.

## How to use

1. **Enable** the server in Studio (Assistant → … → Manage MCP Servers → *Enable Studio as MCP
   server*).
2. **Register** it in the client: quick connect if the client is supported (Antigravity, Codex CLI,
   Claude Code, Claude Desktop, Cursor, Gemini CLI, Visual Studio Code), otherwise the JSON entry
   above, otherwise the CLI command. Restart the client to apply the change.
3. **Verify**: reopen Assistant → … → Manage MCP Servers and look for the green indicator with the
   connected-client count.
4. **Open a place and list sessions**: `list_roblox_studios` — an empty result means Studio is
   closed, no place is open, or the setting is off.
5. **Work in the order the workflow implies**: inventory (`search_game_tree`, `inspect_instance`,
   `script_read`, `script_grep`) → edit (`multi_edit`, `execute_luau` on `Edit`) → run
   (`get_studio_state`, `start_stop_play`, `execute_luau` on `Edit`/`Client`/`Server`) → evidence
   (`get_console_output`, `screen_capture`) → optionally `save_place`.
6. **Troubleshooting** (from the page): restart both Studio and the client; verify the command or
   binary path exists; check the JSON syntax — a single missing comma or bracket prevents loading.

## Business criteria

Rules a reviewer or tester can check on a claim that used these tools:

- **Explicit target**: every tool call names a `studio_id` obtained from `list_roblox_studios`; an
  edit whose target instance is unstated is unverified.
- **Real evidence**: a play-mode claim is backed by `get_console_output` (and, when visual, a
  `screen_capture`); "looks right" is not evidence, and a screenshot is never a substitute for
  console output.
- **No hidden publishing**: `save_place` never publishes — players see nothing until a human
  publishes; a claim of a published change needs the publish step named.
- **Source-of-truth discipline**: an edit made through `multi_edit`/`execute_luau` lands in the
  open place; a Rojo-synced script edited in Studio is overwritten by the next sync, so the source
  of truth is stated before editing.
- **Third-party content**: an inserted Creator Store asset can carry its own Scripts; its
  descendants are inspected before it is kept.
- **Never an installer**: the existence of this server never authorises running an upstream
  installer; the registration facts above are reference text.

## Constraints

- **Single page only.** The skill was generated from the one page
  `https://create.roblox.com/docs/studio/mcp`; pages it links to (Open Cloud with the Studio MCP
  server, test teleports, Assistant skills, the agent-plugin repository) are **not** part of it.
- **The page is dated.** Tool names and client lists change with Studio releases; when this list
  disagrees with the tools the client actually exposes, trust the client. The page states no
  version or date of its own.
- **Mutating by nature.** Connected clients can read and change every open place; a human is asked
  to save or publish a version before large edits, because not every change can be undone from
  Studio. Only trusted clients are connected.
- **Playtest limits.** `start_stop_play` runs one solo client; multi-client checks need Server &
  Clients or a `StudioTestService` plugin harness. `screen_capture` video is a deliberate
  exception, not the default.
- **Credentials and secrets.** Nothing in an MCP configuration entry contains a secret; the
  surface described here carries none, and none may be added when the entry is written.
- **Reference, not instruction.** The page is summarised as data; nothing in it is an instruction
  to execute.

#!/usr/bin/env bash
# =============================================================================
# prepare_factory.sh — prepare a project for running Code Factory in one action.
#
# Purpose: copy the factory (.agents/) into the project, create the memory of
# THIS specific project (`memory/` — the long-term memory of the target project:
# journal `memory/change-log.md` + summary `memory/summary.md`), configure the
# Kimi Code MCP servers (`.kimi-code/mcp.json` — the managed `chrome-devtools`
# entry plus the pinned package vendored beside it, merged without clobbering
# anything already there), configure
# .gitignore, initialize a git repository if needed, create the `start.sh`
# launcher (it sets the required environment variables itself) and verify readiness.
#
# Where the memory lives and how the project is named:
#   * `memory/` is created IN THE DEPLOYMENT ROOT — the directory passed to this
#     script; the base project name at deployment = basename of that directory.
#   * If the task's `repo_path` points to a SUBDIRECTORY of the deployment root,
#     the main agent creates the memory explicitly, naming the project:
#       memory_project.py init --repo <deployment root> --project <basename of the resolved repo_path>
#     The name is recorded in the `project:` declaration of the `memory/summary.md`
#     summary (and in the `project:` of every new journal entry), so both sides name the project the same way.
# Existing project memory is NEVER overwritten: missing files are created, while
# existing ones (the project's run history) are left untouched. If the memory is
# declared for ANOTHER project or mixes projects — only a warning (the script
# still exits with exit 0).
#
# Usage:
#   ./prepare_factory.sh <path-to-project>
#
# Example:
#   ./prepare_factory.sh /path/to/your-project
#
# After preparation a single action is enough:
#   cd <path-to-project> && ./start.sh          # interactive (in the chat: /skill:code-factory)
#   cd <path-to-project> && ./start.sh --auto   # fully autonomous
#
# The script does NOT commit anything. All steps are safe and idempotent, with one
# documented exception: an existing start.sh that differs from the template is first
# backed up to start.sh.bak and then replaced (a byte-identical file is overwritten
# silently).
# =============================================================================
set -euo pipefail

# --- Paths --------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FACTORY_SRC="$SCRIPT_DIR/.agents"          # the ready-made factory (this repository)
PROJECT_DIR="${1:-}"

# --- Colors -------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${GREEN}%s${NC}\n" "$*"; }
warn()  { printf "${YELLOW}%s${NC}\n" "$*"; }
err()   { printf "${RED}%s${NC}\n" "$*" >&2; }

# --- Python interpreter --------------------------------------------------------
# Needed for the factory scripts (project memory). May be missing — that is not an error.
# The Microsoft Store `python3` stub (Windows) exists as a file but does not work,
# so we take the first WORKING interpreter (priority: python3, then python).
PY_BIN="$(command -v python3 || command -v python || true)"
if [[ -n "$PY_BIN" ]] && ! "$PY_BIN" -c 'pass' >/dev/null 2>&1; then
    PY_BIN=""
    for py_cand in python3 python; do
        py_path="$(command -v "$py_cand" || true)"
        if [[ -n "$py_path" ]] && "$py_path" -c 'pass' >/dev/null 2>&1; then
            PY_BIN="$py_path"
            break
        fi
    done
fi

# --- Argument check ------------------------------------------------------------
if [[ -z "$PROJECT_DIR" ]]; then
    err "Specify the project path:  ./prepare_factory.sh <path-to-project>"
    exit 1
fi
if [[ ! -d "$PROJECT_DIR" ]]; then
    err "Project folder not found: $PROJECT_DIR"
    exit 1
fi
if [[ ! -d "$FACTORY_SRC" ]]; then
    err "Factory not found: $FACTORY_SRC (run the script from the factory repository root)"
    exit 1
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
info "==> Preparing project: $PROJECT_DIR"

# --- 1. Git repository ----------------------------------------------------------
if [[ -d "$PROJECT_DIR/.git" ]]; then
    info "    Git: repository already exists ✓"
else
    warn "    Git: no repository — running git init"
    # `git init -b main` exists only since git 2.28; on older git we do init + symbolic-ref
    # (the unborn branch is renamed without creating a commit).
    if ! git -C "$PROJECT_DIR" init -b main 2>/dev/null; then
        git -C "$PROJECT_DIR" init
        git -C "$PROJECT_DIR" symbolic-ref HEAD refs/heads/main
    fi
fi

# --- 2. Copying the factory ------------------------------------------------------
if [[ "$PROJECT_DIR" == "$SCRIPT_DIR" ]]; then
    warn "    The project is the factory repository itself: .agents/ is already in place, skipping the copy."
elif [[ -d "$PROJECT_DIR/.agents" ]]; then
    info "    .agents/ already exists — updating the factory contents (the factory is the source of truth)"
    # We overwrite all factory files with the current versions. User files that are not
    # part of the factory are left untouched (cp does not delete extras).
    cp -r "$FACTORY_SRC"/. "$PROJECT_DIR/.agents/"
else
    info "    Factory: copying .agents/ → $PROJECT_DIR/.agents"
    cp -r "$FACTORY_SRC" "$PROJECT_DIR/.agents"
fi

# --- 3. Project memory ------------------------------------------------------------
# memory/ — the long-term memory of THE project the factory works on. The memory
# directory always lives IN THE DEPLOYMENT ROOT ($PROJECT_DIR), and the base project name
# at deployment = basename of that directory. If the task's `repo_path` points to a
# SUBDIRECTORY of the deployment root, the main agent records the project name explicitly:
#   memory_project.py init --repo <deployment root> --project <basename of the resolved repo_path>
# (the name lands in the `project:` of the journal entries and in the `project:`
# declaration of the summary). The only writer of the journal is the factory's main agent,
# so here only MISSING files are created: existing memory (the project's run history) is
# never overwritten or modified — only its ownership is checked.
MEMORY_DIR="$PROJECT_DIR/memory"
MEM_DIR_SCRIPT="$PROJECT_DIR/.agents/skills/code-factory/scripts/memory_project.py"
MEM_STATE="absent"          # created | ok | mixed | other | unavailable
MEM_PROJECT=""              # project name (created state)
MEM_OWNER=""                # memory owner per memory_project.py check
MEM_CHECK_OUT=""
MEM_REPORT=""             # one-line verdict + WARN count (the only part of `check` ever printed)
# The expected project name = basename of the deployment root. Computed once and
# resilient to set -euo pipefail: an interpreter/script error must not interrupt the deployment.
MEM_NAME_EXPECT="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || true)"

if [[ ! -f "$MEMORY_DIR/change-log.md" || ! -f "$MEMORY_DIR/summary.md" ]]; then
    if [[ -n "$PY_BIN" && -f "$MEM_DIR_SCRIPT" ]]; then
        if MEM_INIT_OUT="$("$PY_BIN" "$MEM_DIR_SCRIPT" init --repo "$PROJECT_DIR" 2>&1)"; then
            MEM_STATE="created"
            MEM_PROJECT="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || true)"
            info "    Project memory: created — $MEMORY_DIR (project ${MEM_PROJECT:-?})"
            printf '%s\n' "$MEM_INIT_OUT" | sed 's/^/      /'
        else
            # The failure reason is the last non-empty line of the output (for an interpreter
            # crash that is the exception line, not the whole traceback: a raw stack in the
            # warning only gets in the way). Empty output yields an empty reason — replaced by "no output".
            MEM_INIT_REASON="$(printf '%s\n' "$MEM_INIT_OUT" | awk 'NF{last=$0}END{print last}')"
            warn "    Project memory: failed to create — ${MEM_INIT_REASON:-no output}"
            warn "    The factory will create it on first access to the project."
        fi
    else
        MEM_STATE="unavailable"
        if [[ -z "$PY_BIN" ]]; then
            warn "    Project memory: not created — python not found"
        else
            warn "    Project memory: not created — script $MEM_DIR_SCRIPT is missing"
        fi
        warn "    The factory will create it on first access to the project."
    fi
elif [[ -n "$PY_BIN" && -f "$MEM_DIR_SCRIPT" ]]; then
    # Memory already exists: we change nothing (the project's history is never overwritten).
    # Check three outcomes: the journal mixes projects | the memory is declared for ANOTHER
    # project | everything is fine. `|| MEM_CHECK_RC=$?` does not crash the script: any state is only a warning.
    MEM_CHECK_RC=0
    MEM_CHECK_OUT="$("$PY_BIN" "$MEM_DIR_SCRIPT" check --repo "$PROJECT_DIR" 2>&1)" || MEM_CHECK_RC=$?
    # `check` prints ONE WARN line per legacy-format entry and the verdict last, so the whole blob is
    # ~50 wrapped lines with the verdict buried in them (owner evidence: warnings.md). Only the
    # verdict plus a WARN count may be PRINTED: MEM_CHECK_OUT stays for PARSING (owner, entry count,
    # mixed/other detection) and never reaches the console. Same contract as prepare_factory.ps1.
    MEM_WARN_COUNT="$(printf '%s\n' "$MEM_CHECK_OUT" | grep -c '^WARN -' || true)"
    MEM_VERDICT="$(printf '%s\n' "$MEM_CHECK_OUT" | grep -E '^(ok|FAIL)[[:space:]]*-' | tail -n 1 || true)"
    if [[ -z "$MEM_VERDICT" ]]; then
        # No verdict line at all (an empty output, an interpreter crash): the last non-empty line.
        MEM_VERDICT="$(printf '%s\n' "$MEM_CHECK_OUT" | awk 'NF{last=$0}END{print last}')"
    fi
    MEM_VERDICT="${MEM_VERDICT:-no output}"
    if [[ "$MEM_WARN_COUNT" -gt 0 ]]; then
        MEM_REPORT="$MEM_VERDICT ($MEM_WARN_COUNT legacy warnings — run memory_project.py check for details)"
    else
        MEM_REPORT="$MEM_VERDICT"
    fi
    MEM_OWNER=""
    if [[ "$MEM_CHECK_OUT" =~ belongs\ to\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    elif [[ "$MEM_CHECK_OUT" =~ declares\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    fi
    if [[ "$MEM_CHECK_OUT" == *"mixes projects"* ]]; then
        MEM_STATE="mixed"
        warn "    Project memory: INCONSISTENT — entries from different projects in memory ($MEM_REPORT)"
        warn "    Check ownership: the project: field in entries must match the project."
    elif [[ "$MEM_CHECK_OUT" == *"expected"* ]] \
      || { [[ -n "$MEM_OWNER" ]] && [[ "$MEM_OWNER" != "$MEM_NAME_EXPECT" ]] \
           && [[ "$MEM_OWNER" != "(legacy, no project field)" ]]; } \
      || [[ "$MEM_CHECK_RC" -ne 0 ]]; then
        # The memory belongs to (or is declared for) ANOTHER project — we are deploying to the wrong place.
        MEM_STATE="other"
        warn "    Project memory: CHECK — the memory is declared for project '${MEM_OWNER:-?}', but the factory is being deployed in directory '$MEM_NAME_EXPECT' ($MEM_REPORT)"
        warn "    Verify this is the same project: the project: field in the memory/change-log.md entries."
    else
        MEM_STATE="ok"
        info "    Project memory: in place — $MEM_REPORT"
    fi
else
    MEM_STATE="unavailable"
    if [[ -z "$PY_BIN" ]]; then
        warn "    Project memory: present but not verified — python not found"
    else
        warn "    Project memory: present but not verified — script $MEM_DIR_SCRIPT is missing"
    fi
fi

# --- 4. Launcher --------------------------------------------------------------------
LAUNCHER="$PROJECT_DIR/start.sh"
LAUNCHER_TEMPLATE="$(cat <<'EOF'
#!/usr/bin/env bash
# Code Factory launcher — created by prepare_factory.sh. Run it with no extra commands:
#   ./start.sh          — interactive (in the chat: /skill:code-factory)
#   ./start.sh --auto   — fully autonomous
set -euo pipefail
# The launch directory — the absolute path of the directory holding this launcher. It is the
# machine-checkable anchor against which the instruction layer resolves the task's repo_path.
export KIMI_FACTORY_LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Subagent model split (primary/secondary) is enabled here automatically.
export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1
# Portable user-scope agent catalog: the CLI's PROJECT-scoped profile registry can lose a factory
# role ("Unknown agent type"), while its USER-scope catalog — $KIMI_CODE_HOME/agents, else
# ~/.kimi-code/agents — survives that loss. Every factory role is copied there BEFORE the CLI
# starts, with native commands only (a machine without an interpreter still launches), and only
# this factory's own role profiles are written: the user's agents in that directory are untouched.
# A refresh that cannot complete ABORTS the launch — a session with missing or stale roles is
# exactly the failure this fallback exists to prevent.
CF_AGENT_ROLES="advisor analyzer business-tester code-reviewer coder diagnostician documenter farukon-expert roblox-expert gui-expert planner refactorer security-auditor skill-manager supervisor tester"
CF_AGENT_SRC="$KIMI_FACTORY_LAUNCH_DIR/.agents/agents/sub-agents"
if [ -n "${KIMI_CODE_HOME:-}" ]; then
    CF_AGENT_DST="$KIMI_CODE_HOME/agents"
elif [ -n "${HOME:-}" ]; then
    CF_AGENT_DST="$HOME/.kimi-code/agents"
else
    CF_AGENT_DST=""
fi
CF_AGENT_ERROR=""
if [ -z "$CF_AGENT_DST" ]; then
    CF_AGENT_ERROR="neither KIMI_CODE_HOME nor HOME is set, so the user-scope agent catalog cannot be located"
elif ! mkdir -p "$CF_AGENT_DST"; then
    CF_AGENT_ERROR="the directory cannot be created: $CF_AGENT_DST"
elif [ -d "$CF_AGENT_SRC" ]; then
    # A project catalog is only as good as its WORST role: a profile missing here would leave
    # whatever an older release wrote in the user catalog, and that role would launch stale.
    for CF_AGENT_ROLE in $CF_AGENT_ROLES; do
        if [ ! -f "$CF_AGENT_SRC/$CF_AGENT_ROLE.md" ]; then
            CF_AGENT_ERROR="the project agent catalog $CF_AGENT_SRC is incomplete: $CF_AGENT_ROLE.md is missing, so that role would launch from a stale copy — the launch is refused"
            break
        fi
        if ! cp -f "$CF_AGENT_SRC/$CF_AGENT_ROLE.md" "$CF_AGENT_DST/$CF_AGENT_ROLE.md"; then
            CF_AGENT_ERROR="the profile $CF_AGENT_ROLE.md could not be copied to $CF_AGENT_DST — the launch is refused"
            break
        fi
        # Byte-for-byte proof, not the exit code of the copy: a copy that silently kept the old
        # file is exactly the stale-role failure this refresh exists to prevent.
        if ! cmp -s "$CF_AGENT_SRC/$CF_AGENT_ROLE.md" "$CF_AGENT_DST/$CF_AGENT_ROLE.md"; then
            CF_AGENT_ERROR="the profile $CF_AGENT_ROLE.md could not be refreshed in $CF_AGENT_DST: the copy there differs from $CF_AGENT_SRC/$CF_AGENT_ROLE.md — the launch is refused"
            break
        fi
    done
else
    # The project catalog is ABSENT. That is legal ONLY over a COMPLETE user-scope fallback:
    # starting a session with a half-filled catalog is the missing-role failure this forbids.
    printf 'Code Factory: the project agent catalog is absent (%s) — verifying the user-scope agent catalog instead.\n' "$CF_AGENT_SRC"
    for CF_AGENT_ROLE in $CF_AGENT_ROLES; do
        if [ ! -f "$CF_AGENT_DST/$CF_AGENT_ROLE.md" ]; then
            CF_AGENT_ERROR="the project agent catalog is absent and the user-scope catalog $CF_AGENT_DST does not carry $CF_AGENT_ROLE.md, so that role would be missing — the launch is refused"
            break
        fi
    done
fi
if [ -n "$CF_AGENT_ERROR" ]; then
    printf 'Code Factory: the launch was refused — the user-scope agent catalog could not be refreshed or verified: %s\n' "$CF_AGENT_ERROR" >&2
    printf 'Code Factory: no Kimi session was started — the factory roles would be missing or stale.\n' >&2
    exit 1
fi
exec kimi "$@"
EOF
)"
# We do not silently lose an existing user start.sh: if it differs from the template —
# warn and keep the old file as start.sh.bak (one backup, not a chain); a byte-identical
# file is overwritten silently.
if [[ -f "$LAUNCHER" ]] && ! cmp -s "$LAUNCHER" <(printf '%s\n' "$LAUNCHER_TEMPLATE"); then
    warn "    Launcher: $LAUNCHER already exists and differs from the template — overwriting (the old file is kept as $LAUNCHER.bak)"
    cp "$LAUNCHER" "$LAUNCHER.bak"
fi
printf '%s\n' "$LAUNCHER_TEMPLATE" > "$LAUNCHER"
chmod +x "$LAUNCHER"
info "    Launcher: created $LAUNCHER"

# --- 5. Portable user-scope agent catalog -------------------------------------------
# The Kimi Code CLI's PROJECT-scoped profile registry has repeatedly dropped a factory role
# ("Unknown agent type") although the profile was on disk. The durable answer is the CLI's
# USER-scope catalog — `<KIMI_CODE_HOME>/agents` when that variable is set (it relocates the whole
# data root of the CLI), else `~/.kimi-code/agents` — which every session reads: each factory role
# is copied there BYTE-FOR-BYTE here, and the generated launchers refresh the copies BEFORE every
# start (a project catalog lost between runs then cannot leave the CLI without the roles).
# Native commands only: deploying and launching must both work without an interpreter. Only this
# factory's role profiles are written — a profile the factory does not manage is a copy the user
# owns and is never modified or deleted (its own agents live in the same directory).
AGENT_SRC="$PROJECT_DIR/.agents/agents/sub-agents"
# The 16 role profiles the factory ships — the same roster the generated launcher verifies
# (model_matrix.ROLES/ROLE_FILES is the one source; test_stable_agent_catalog.py pins the two).
AGENT_ROLES="advisor analyzer business-tester code-reviewer coder diagnostician documenter farukon-expert roblox-expert gui-expert planner refactorer security-auditor skill-manager supervisor tester"
if [[ -n "${KIMI_CODE_HOME:-}" ]]; then
    AGENT_CATALOG="$KIMI_CODE_HOME/agents"
elif [[ -n "${HOME:-}" ]]; then
    AGENT_CATALOG="$HOME/.kimi-code/agents"
else
    AGENT_CATALOG=""
fi
AGENT_INSTALLED=0
AGENT_SYNC_ERROR=""
if [[ -z "$AGENT_CATALOG" ]]; then
    AGENT_SYNC_ERROR="neither KIMI_CODE_HOME nor HOME is set, so the user-scope agent catalog cannot be located"
elif ! mkdir -p "$AGENT_CATALOG"; then
    AGENT_SYNC_ERROR="the directory cannot be created: $AGENT_CATALOG"
elif [[ ! -d "$AGENT_SRC" ]]; then
    AGENT_SYNC_ERROR="the factory's own agent profiles are missing: $AGENT_SRC"
else
    for AGENT_ROLE in $AGENT_ROLES; do
        if [[ ! -f "$AGENT_SRC/$AGENT_ROLE.md" ]]; then
            AGENT_SYNC_ERROR="the factory's own agent catalog $AGENT_SRC is incomplete: $AGENT_ROLE.md is missing"
            break
        fi
        if ! cp -f "$AGENT_SRC/$AGENT_ROLE.md" "$AGENT_CATALOG/$AGENT_ROLE.md"; then
            AGENT_SYNC_ERROR="the profile $AGENT_ROLE.md could not be copied to $AGENT_CATALOG"
            break
        fi
        if ! cmp -s "$AGENT_SRC/$AGENT_ROLE.md" "$AGENT_CATALOG/$AGENT_ROLE.md"; then
            AGENT_SYNC_ERROR="the profile $AGENT_ROLE.md could not be refreshed in $AGENT_CATALOG: the copy there differs from $AGENT_SRC/$AGENT_ROLE.md"
            break
        fi
        AGENT_INSTALLED=$((AGENT_INSTALLED + 1))
    done
fi
if [[ -n "$AGENT_SYNC_ERROR" ]]; then
    err "Code Factory: the user-scope agent catalog could not be refreshed — $AGENT_SYNC_ERROR"
    err "    Without it a session that loses the project catalog has no roles left, so the deployment is aborted."
    exit 1
fi
info "    Agent catalog: $AGENT_INSTALLED factory profiles installed — $AGENT_CATALOG (refreshed by start.sh before every launch)"

# --- 6. Chrome DevTools MCP configuration --------------------------------------------
# The Kimi Code CLI reads its stdio MCP servers from `.kimi-code/mcp.json` at the project
# root. The factory manages exactly ONE entry there — the `chrome-devtools` server (the PINNED
# chrome-devtools-mcp release, isolated temporary browser profile, usage statistics, CrUX
# lookups and update checks disabled) — and touches nothing else: unrelated servers and user
# settings survive byte-for-byte, and an existing DIFFERENT `chrome-devtools` entry is
# preserved and reported (never silently replaced). Only this project's file is written;
# user-level configuration is never modified.
# The launch shape is `node <vendored entry>`: the Kimi Code CLI spawns stdio servers WITHOUT a
# shell, so `npx` fails with ENOENT and `npx.cmd` with EINVAL on Windows. The deployer therefore
# installs the pinned package ONCE into `.kimi-code/vendor/chrome-devtools-mcp/` (npm with
# --no-save --ignore-scripts --omit=dev — package scripts never run at deploy time) and merges
# the entry that points at it. When python, node or npm is unavailable, or the install fails,
# NO entry is written: an absent server that is REPORTED is far better than a config whose
# launch file does not exist, which would break every Kimi session in this project.
# Deployment must not newly require Python: without a working interpreter an existing mcp.json
# is left untouched and nothing new is created (the per-installation entry path is derived by
# the helper, so a copied template would be a broken config).
MCP_DIR="$PROJECT_DIR/.kimi-code"
MCP_FILE="$MCP_DIR/mcp.json"
MCP_VENDOR="$MCP_DIR/vendor/chrome-devtools-mcp"
MCP_ASSET="$PROJECT_DIR/.agents/skills/code-factory/assets/chrome-devtools.mcp.json"
MCP_MERGE="$PROJECT_DIR/.agents/skills/code-factory/scripts/chrome_devtools_mcp.py"
# created | updated | unchanged | conflict | failed | vendor-skipped | no-python-skipped
MCP_STATE="absent"
MCP_REASON=""

if [[ -n "$PY_BIN" && -f "$MCP_MERGE" ]]; then
    # 5a. The pinned package comes first: an entry may only point at an installed file.
    VENDOR_RC=0
    VENDOR_OUT="$("$PY_BIN" "$MCP_MERGE" vendor-install --target "$MCP_VENDOR" --asset "$MCP_ASSET" 2>&1)" || VENDOR_RC=$?
    # The reported line is the LAST non-empty one: it is the helper's message, never a traceback.
    VENDOR_MSG="$(printf '%s\n' "$VENDOR_OUT" | awk 'NF{last=$0}END{print last}')"
    if [[ "$VENDOR_RC" -ne 0 ]]; then
        MCP_STATE="vendor-skipped"
        MCP_REASON="${VENDOR_MSG:-no output}"
        warn "    chrome-devtools MCP: package install skipped/failed — ${MCP_REASON}"
        warn "      No managed entry is written: a server launched from a file that does not exist would break every Kimi session in this project."
        if [[ -f "$MCP_FILE" ]]; then
            warn "      The existing $MCP_FILE is left untouched."
        fi
    else
        info "    MCP package: ${VENDOR_MSG:-pinned chrome-devtools-mcp is vendored}"
        MCP_EXISTED=false
        if [[ -f "$MCP_FILE" ]]; then MCP_EXISTED=true; fi
        MCP_OUT=""
        MCP_RC=0
        MCP_OUT="$("$PY_BIN" "$MCP_MERGE" merge-config --target "$MCP_FILE" --asset "$MCP_ASSET" 2>&1)" || MCP_RC=$?
        # The reason shown for a failure is the LAST non-empty line of the helper's output: a
        # conflict message is explicit, while a crashed interpreter would only add a traceback.
        MCP_REASON="$(printf '%s\n' "$MCP_OUT" | awk 'NF{last=$0}END{print last}')"
        case "$MCP_RC" in
            0)
                if [[ "$MCP_EXISTED" != true ]]; then
                    MCP_STATE="created"
                    info "    MCP config: created — $MCP_FILE (server chrome-devtools, node + the vendored pinned package)"
                elif [[ "$MCP_OUT" == unchanged* ]]; then
                    MCP_STATE="unchanged"
                    info "    MCP config: already in place — $MCP_FILE (server chrome-devtools, no diff)"
                else
                    MCP_STATE="updated"
                    info "    MCP config: updated — $MCP_FILE (server chrome-devtools merged; existing servers and settings preserved)"
                fi
                ;;
            3)
                # A DIFFERENT `chrome-devtools` entry already exists: it is preserved byte-for-byte and
                # nothing is overwritten — resolving the difference stays an explicit user decision.
                MCP_STATE="conflict"
                warn "    MCP config: CONFLICT — an existing 'chrome-devtools' entry differs from the factory definition; it is preserved and nothing was overwritten"
                warn "      reason: ${MCP_REASON:-an existing chrome-devtools entry differs from the factory definition}"
                warn "      Resolve the difference in $MCP_FILE explicitly, then run prepare_factory.sh again."
                ;;
            *)
                MCP_STATE="failed"
                warn "    MCP config: not configured — ${MCP_REASON:-no output}"
                warn "    The factory starts without the managed server; the existing $MCP_FILE is left as it is."
                ;;
        esac
    fi
else
    # No working Python (or the helper is missing): an existing mcp.json is NEVER touched, and no
    # new one is created — its managed entry needs the per-installation vendored entry path.
    MCP_STATE="no-python-skipped"
    if [[ -z "$PY_BIN" ]]; then
        MCP_REASON="python not found"
    else
        MCP_REASON="merge helper $MCP_MERGE is missing"
    fi
    if [[ -f "$MCP_FILE" ]]; then
        warn "    MCP config: skipped — ${MCP_REASON}: the existing $MCP_FILE is left untouched (no merge, nothing clobbered)"
    else
        warn "    MCP config: skipped — ${MCP_REASON}: no managed entry is written (its launch path is per-installation and only the helper derives it)"
    fi
fi
info "      The MCP configuration takes effect in a NEW Kimi session — /mcp in that session shows the connection status."

# --- 7. .gitignore ------------------------------------------------------------------
# Note: .gitignore only affects git tracking, not access to files on disk.
# Ignoring .agents/ does not break reading/writing the factory's data (cache,
# history, context) — the factory works with .agents/ directly through the file
# system, not through git.
GITIGNORE="$PROJECT_DIR/.gitignore"
# Exact line match (-x): a substring match would consider a pattern present even
# when .gitignore only has a similar line. `tr -d '\r'` — so a CRLF file (Windows)
# does not break the check and patterns are not duplicated on a rerun.
gitignore_has() {
    [[ -f "$GITIGNORE" ]] && tr -d '\r' < "$GITIGNORE" | grep -qxF "$1"
}
# The factory's own files inside a DEPLOYED project — the task file and the launchers — must never
# be mistaken for a new task and never get committed: a leftover from a previous run in a TARGET
# project stays invisible to git. The managed MCP config is ignored too: its `chrome-devtools` entry
# carries the ABSOLUTE path of the vendored package of THIS installation, so a committed config
# would hand a fresh clone a launch path that does not exist there (ignoring the vendor directory
# alone protects the package, not the config pointing at it).
NEED_GITIGNORE=false
for pat in ".agents/" ".code-factory/" ".kimi-code/mcp.json" ".kimi-code/vendor/" "__pycache__/" "*.pyc" ".env" ".env.*" "*.env" "*.pem" "*.key" "task.yaml" "start.cmd" "start.sh"; do
    gitignore_has "$pat" || NEED_GITIGNORE=true
done

if [[ "$NEED_GITIGNORE" == true ]]; then
    warn "    .gitignore: adding the factory's utility patterns"
    {
        [[ -f "$GITIGNORE" ]] && echo ""
        echo "# --- Code Factory (auto-added by prepare_factory.sh) ---"
        echo ".agents/"
        echo ".code-factory/"
        echo ".kimi-code/mcp.json"
        echo ".kimi-code/vendor/"
        echo "__pycache__/"
        echo "*.pyc"
        echo ".env"
        echo ".env.*"
        echo "*.env"
        echo "*.pem"
        echo "*.key"
        echo "task.yaml"
        echo "start.cmd"
        echo "start.sh"
    } >> "$GITIGNORE"
fi

# --- 8. Readiness check -------------------------------------------------------------
# The memory line is assembled from the state of step 3 (we do not run init again).
# Three distinguishable states: ok — the memory belongs to this project; mixed —
# entries from different projects; other — the memory is declared for another project (we are deploying to the wrong place).
case "$MEM_STATE" in
    created)  MEM_LINE="created ✓ (project ${MEM_PROJECT:-?})" ;;
    ok)
        if [[ "$MEM_CHECK_OUT" =~ project\ \'([^\']+)\'\ \(([0-9]+)\ entries\) ]]; then
            MEM_NAME="${BASH_REMATCH[1]}"
            MEM_COUNT="${BASH_REMATCH[2]}"
            # Memory without a project marker (neither project: in entries nor a declaration
            # in the summary): substitute the project name from the deployment root basename.
            if [[ "$MEM_NAME" == "(legacy, no project field)" ]]; then
                MEM_NAME="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || echo '?')"
            fi
            MEM_LINE="OK ✓ (project $MEM_NAME, $MEM_COUNT entries)"
        else
            MEM_LINE="OK ✓"
        fi
        ;;
    mixed)    MEM_LINE="INCONSISTENT ✗ (entries from different projects in memory — check project:)" ;;
    other)    MEM_LINE="CHECK ✗ (declared project ${MEM_OWNER:-?}, deploying into ${MEM_NAME_EXPECT:-?})" ;;
    unavailable)
        if [[ -z "$PY_BIN" ]]; then
            MEM_LINE="not verified (no python)"
        else
            MEM_LINE="not verified (no memory_project.py)"
        fi
        ;;
    *)        MEM_LINE="MISSING ✗" ;;
esac

# The MCP line is assembled from the state of step 6. A conflict, an uninstalled package or a
# skipped merge is REPORTED here — a managed server that silently did not arrive costs a browser run.
case "$MCP_STATE" in
    created)           MCP_LINE="created ✓ (server chrome-devtools, node + the vendored pinned package)" ;;
    updated)           MCP_LINE="updated ✓ (server chrome-devtools merged; existing servers and settings preserved)" ;;
    unchanged)         MCP_LINE="OK ✓ (server chrome-devtools, already pinned)" ;;
    conflict)          MCP_LINE="CONFLICT ✗ (existing chrome-devtools entry preserved — resolve it explicitly, then re-run)" ;;
    failed)            MCP_LINE="not configured ✗ (${MCP_REASON:-merge failed})" ;;
    vendor-skipped)    MCP_LINE="skipped ✗ (chrome-devtools MCP: package install skipped/failed — ${MCP_REASON:-no output}; no managed entry written)" ;;
    no-python-skipped) MCP_LINE="skipped (${MCP_REASON}) — no managed entry written" ;;
    *)                 MCP_LINE="MISSING ✗" ;;
esac
echo ""
info "==> Readiness check:"
echo "    • .agents/:            $([ -f "$PROJECT_DIR/.agents/skills/code-factory/SKILL.md" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • start.sh:            $([ -x "$LAUNCHER" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • agent catalog:       OK ✓ ($AGENT_INSTALLED factory profiles in $AGENT_CATALOG — refreshed by start.sh before every launch)"
echo "    • .git/:               $([ -d "$PROJECT_DIR/.git" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • .gitignore:          $(gitignore_has '.agents/' && gitignore_has '.code-factory/' && echo 'OK ✓ (.agents/ + .code-factory/)' || echo 'no .agents/ or .code-factory/ ✗')"
echo "    • memory/:              $MEM_LINE"
echo "    • .kimi-code/mcp.json: $MCP_LINE"
echo "    • git status:"
git -C "$PROJECT_DIR" status --short | head -20 || true
[[ -z "$(git -C "$PROJECT_DIR" status --short)" ]] && echo "      (clean tree)"
echo ""

info "==> Done! Starting the factory is a single action:"
echo "    cd $PROJECT_DIR"
echo "    ./start.sh            # in the chat: /skill:code-factory"
echo "    ./start.sh --auto     # fully autonomous"
echo ""
echo "    The launcher sets KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 itself —"
echo "    no extra export commands to remember."

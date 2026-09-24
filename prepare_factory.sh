#!/usr/bin/env bash
# =============================================================================
# prepare_factory.sh — prepare a project for running Code Factory in one action.
#
# Purpose: copy the factory (.agents/) into the project, create the memory of
# THIS specific project (`memory/` — the long-term memory of the target project:
# journal `memory/change-log.md` + summary `memory/summary.md`), configure
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
#   ./prepare_factory.sh /home/adar/ai-factories/my-test-project
#
# After preparation a single action is enough:
#   cd <path-to-project> && ./start.sh          # interactive (in the chat: /skill:code-factory)
#   cd <path-to-project> && ./start.sh --auto   # fully autonomous
#
# The script does NOT commit anything. All steps are safe and idempotent.
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
    MEM_OWNER=""
    if [[ "$MEM_CHECK_OUT" =~ belongs\ to\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    elif [[ "$MEM_CHECK_OUT" =~ declares\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    fi
    if [[ "$MEM_CHECK_OUT" == *"mixes projects"* ]]; then
        MEM_STATE="mixed"
        warn "    Project memory: INCONSISTENT — entries from different projects in memory ($MEM_CHECK_OUT)"
        warn "    Check ownership: the project: field in entries must match the project."
    elif [[ "$MEM_CHECK_OUT" == *"expected"* ]] \
      || { [[ -n "$MEM_OWNER" ]] && [[ "$MEM_OWNER" != "$MEM_NAME_EXPECT" ]] \
           && [[ "$MEM_OWNER" != "(legacy, no project field)" ]]; } \
      || [[ "$MEM_CHECK_RC" -ne 0 ]]; then
        # The memory belongs to (or is declared for) ANOTHER project — we are deploying to the wrong place.
        MEM_STATE="other"
        warn "    Project memory: CHECK — the memory is declared for project '${MEM_OWNER:-?}', but the factory is being deployed in directory '$MEM_NAME_EXPECT' ($MEM_CHECK_OUT)"
        warn "    Verify this is the same project: the project: field in the memory/change-log.md entries."
    else
        MEM_STATE="ok"
        info "    Project memory: in place — $MEM_CHECK_OUT"
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
cat > "$LAUNCHER" <<'EOF'
#!/usr/bin/env bash
# Code Factory launcher — created by prepare_factory.sh. Run it with no extra commands:
#   ./start.sh          — interactive (in the chat: /skill:code-factory)
#   ./start.sh --auto   — fully autonomous
set -euo pipefail
# Subagent model split (primary/secondary) is enabled here automatically.
export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1
exec kimi "$@"
EOF
chmod +x "$LAUNCHER"
info "    Launcher: created $LAUNCHER"

# --- 5. .gitignore ------------------------------------------------------------------
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
NEED_GITIGNORE=false
for pat in ".agents/" ".code-factory/" "__pycache__/" "*.pyc" ".env" ".env.*" "*.env" "*.pem" "*.key"; do
    gitignore_has "$pat" || NEED_GITIGNORE=true
done

if [[ "$NEED_GITIGNORE" == true ]]; then
    warn "    .gitignore: adding the factory's utility patterns"
    {
        [[ -f "$GITIGNORE" ]] && echo ""
        echo "# --- Code Factory (auto-added by prepare_factory.sh) ---"
        echo ".agents/"
        echo ".code-factory/"
        echo "__pycache__/"
        echo "*.pyc"
        echo ".env"
        echo ".env.*"
        echo "*.env"
        echo "*.pem"
        echo "*.key"
    } >> "$GITIGNORE"
fi

# --- 6. Readiness check -------------------------------------------------------------
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
echo ""
info "==> Readiness check:"
echo "    • .agents/:            $([ -f "$PROJECT_DIR/.agents/skills/code-factory/SKILL.md" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • start.sh:            $([ -x "$LAUNCHER" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • .git/:               $([ -d "$PROJECT_DIR/.git" ] && echo 'OK ✓' || echo 'MISSING ✗')"
echo "    • .gitignore:          $(gitignore_has '.agents/' && gitignore_has '.code-factory/' && echo 'OK ✓ (.agents/ + .code-factory/)' || echo 'no .agents/ or .code-factory/ ✗')"
echo "    • memory/:              $MEM_LINE"
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

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

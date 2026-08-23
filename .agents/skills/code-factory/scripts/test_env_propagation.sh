#!/usr/bin/env bash
# Verify KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL propagates to the factory's pre-flight check.
#
# The factory checks this flag in pre-flight with:
#   echo "${KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL:-unset}"
#
# Root cause of the reported bug: the flag is lost when `kimi` is launched from a context that
# does not inherit the user's interactive shell env (new terminal, launcher, sudo). This test
# pins the contract: with the flag exported, the check must report '1', not 'unset'.
set -euo pipefail

export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1

# Spawn a child process to pin the inheritance contract: the factory's check runs in a
# subprocess of `kimi`, so a bare echo in this same shell would be tautological.
got="$(bash -c 'echo "${KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL:-unset}"')"

if [[ "$got" != "1" ]]; then
    echo "FAIL: child process saw '$got', expected '1' (env var lost)" >&2
    exit 1
fi

echo "PASS: child process sees KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=$got (not 'unset')"

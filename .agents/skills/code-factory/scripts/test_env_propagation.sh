#!/usr/bin/env bash
# Verify KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL really reaches the factory's pre-flight probe.
#
# The contract is not "an exported variable reaches a child shell" -- bash guarantees that, so
# asserting it cannot fail. The contract is that factory_preflight.py READS the flag: it reports
# the flag's state in its console summary and as `secondary_model_env` in the capabilities JSON.
# This test drives the preflight twice -- flag exported, flag removed -- and asserts both reported
# states; a preflight that stops reading the variable turns this test red.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFLIGHT="$SCRIPT_DIR/factory_preflight.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PY=""
for candidate in python python3 py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [[ -z "$PY" ]]; then
    echo "FAIL: no python interpreter on PATH (python/python3/py)" >&2
    exit 1
fi

assert_case() {
    # $1 = case name ("set"/"unset"), $2 = expected console state, $3 = expected JSON value.
    # A missing python/git probe makes the preflight exit 1 AFTER reporting, so the exit code is
    # not the signal here: the reported line and the JSON field are.
    local name="$1" expected_state="$2" expected_json="$3"
    local out="$TMP/preflight-$name.json" log="$TMP/preflight-$name.log"
    if [[ "$name" == "set" ]]; then
        KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 "$PY" "$PREFLIGHT" --out "$out" >"$log" || true
    else
        env -u KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL "$PY" "$PREFLIGHT" --out "$out" >"$log" || true
    fi
    if ! grep -qF "KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL: $expected_state" "$log"; then
        echo "FAIL: preflight with the flag $name did not report '$expected_state':" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! grep -qF "\"secondary_model_env\": $expected_json" "$out"; then
        echo "FAIL: capabilities JSON with the flag $name lacks secondary_model_env=$expected_json:" >&2
        cat "$out" >&2
        exit 1
    fi
}

assert_case set "set (model split active)" true
assert_case unset "not set (model split inactive)" false

echo "PASS: factory_preflight.py reports KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL 'set' when exported and 'not set' when removed"

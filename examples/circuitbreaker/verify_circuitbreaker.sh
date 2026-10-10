#!/bin/bash
# Verify the circuit-breaker demo. One failing provider plus a consecutive-error
# rule should make later client calls report that the circuit is open.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_verify_lib.sh
source "${SCRIPT_DIR}/../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-CircuitBreakerCallee}"
PROVIDER_PORT="${PROVIDER_PORT:-19102}"
RULE_NAME="${RULE_NAME:-${SERVICE_NAME}-auto-cb}"
CONSECUTIVE_ERROR="${CONSECUTIVE_ERROR:-3}"
CLIENT_COUNT="${CLIENT_COUNT:-20}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; RULE_NAME="${SERVICE_NAME}-auto-cb"; shift 2 ;;
        --provider-port) PROVIDER_PORT="$2"; shift 2 ;;
        --consecutive-error) CONSECUTIVE_ERROR="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--service NAME] [--consecutive-error N]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_circuitbreaker"
require_tools curl uv python3
free_port "$PROVIDER_PORT"

log_step "start failing provider"
start_demo provider examples/circuitbreaker/provider.py \
    --service "$SERVICE_NAME" --namespace "$NAMESPACE" \
    --host 127.0.0.1 --port "$PROVIDER_PORT" --initial-error
wait_for_http "http://127.0.0.1:${PROVIDER_PORT}/health" 20 "circuit-breaker provider" "$LAST_PID" \
    || { dump_log provider; exit 1; }
http_get "http://127.0.0.1:${PROVIDER_PORT}/echo"
if [[ "$HTTP_CODE" != "500" ]]; then
    log_error "failing provider returned ${HTTP_CODE}, expected 500"
    exit 1
fi

log_step "create circuit-breaker rule ${RULE_NAME}"
rule_body="$(SERVICE_NAME="$SERVICE_NAME" NAMESPACE="$NAMESPACE" RULE_NAME="$RULE_NAME" CONSECUTIVE_ERROR="$CONSECUTIVE_ERROR" python3 -c '
import json, os
print(json.dumps({
    "name": os.environ["RULE_NAME"],
    "namespace": os.environ["NAMESPACE"],
    "enable": True,
    "level": "INSTANCE",
    "description": "auto-created by verify_circuitbreaker.sh",
    "rule_matcher": {
        "source": {"namespace": "*", "service": "*"},
        "destination": {
            "namespace": os.environ["NAMESPACE"],
            "service": os.environ["SERVICE_NAME"],
            "method": {"type": "EXACT", "value": "*"},
        },
    },
    "trigger_condition": [{
        "triggerType": "CONSECUTIVE_ERROR",
        "errorCount": int(os.environ["CONSECUTIVE_ERROR"]),
    }],
    "recoverCondition": {"sleep_window": 30, "consecutiveSuccess": 1},
    "block_configs": [{
        "name": "default-bc",
        "error_conditions": [{
            "inputType": "RET_CODE",
            "condition": {"type": "EXACT", "value": "500"},
        }],
        "trigger_conditions": [{
            "triggerType": "CONSECUTIVE_ERROR",
            "errorCount": int(os.environ["CONSECUTIVE_ERROR"]),
        }],
        "api": {"path": {"value": ""}},
    }],
}))
')"
polaris_api POST "/naming/v1/circuitbreaker/rules" "$rule_body"
if [[ "$API_HTTP" != "200" ]] || ! polaris_ok; then
    log_error "create circuit-breaker rule failed http=${API_HTTP} body=${API_BODY}"
    exit 1
fi
log_info "circuit-breaker rule created"

log_step "run client until the circuit opens"
client_log="${LOG_DIR}/client.log"
(
    cd "$REPO_ROOT"
    export POLARIS_SERVER_ADDRESSES="${POLARIS_SERVER}:8091"
    export POLARIS_NAMESPACE="${NAMESPACE}"
    export POLARIS_TOKEN="${POLARIS_TOKEN}"
    exec uv run python examples/circuitbreaker/client.py \
        --service "$SERVICE_NAME" --count "$CLIENT_COUNT"
) >"$client_log" 2>&1 || { log_error "client failed"; cat "$client_log" >&2; dump_log provider; exit 1; }

if ! grep -q "status=500" "$client_log"; then
    log_error "client never observed the failing provider"
    cat "$client_log" >&2
    exit 1
fi
if ! grep -q "blocked by Polaris circuit breaker" "$client_log"; then
    log_error "client never reported an open circuit"
    cat "$client_log" >&2
    dump_log provider
    exit 1
fi
log_info "client observed provider failures and an open circuit"
log_info "circuit-breaker verification passed"

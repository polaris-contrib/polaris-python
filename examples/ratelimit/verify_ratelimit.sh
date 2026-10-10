#!/bin/bash
# Verify the rate-limit demo. A local QPS rule is created on Polaris, then
# the provider and the one-shot client are exercised.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_verify_lib.sh
source "${SCRIPT_DIR}/../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-RateLimitEchoServer}"
PROVIDER_PORT="${PROVIDER_PORT:-28201}"
RULE_NAME="${RULE_NAME:-${SERVICE_NAME}-auto-qps}"
MAX_AMOUNT="${MAX_AMOUNT:-2}"
BURST_COUNT="${BURST_COUNT:-12}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; RULE_NAME="${SERVICE_NAME}-auto-qps"; shift 2 ;;
        --provider-port) PROVIDER_PORT="$2"; shift 2 ;;
        --max-amount) MAX_AMOUNT="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--service NAME] [--max-amount N]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_ratelimit"
require_tools curl uv python3
free_port "$PROVIDER_PORT"

log_step "start provider"
start_demo provider examples/ratelimit/provider.py \
    --service "$SERVICE_NAME" --host 127.0.0.1 --port "$PROVIDER_PORT"
wait_for_http "http://127.0.0.1:${PROVIDER_PORT}/health" 20 "rate-limit provider" "$LAST_PID" \
    || { dump_log provider; exit 1; }

log_step "create local QPS rule ${RULE_NAME}"
rule_body="$(SERVICE_NAME="$SERVICE_NAME" NAMESPACE="$NAMESPACE" RULE_NAME="$RULE_NAME" MAX_AMOUNT="$MAX_AMOUNT" python3 -c '
import json, os
print(json.dumps([{
    "name": os.environ["RULE_NAME"],
    "service": os.environ["SERVICE_NAME"],
    "namespace": os.environ["NAMESPACE"],
    "priority": 0,
    "resource": "QPS",
    "type": "LOCAL",
    "method": {"type": "EXACT", "value": "/echo"},
    "amounts": [{"maxAmount": int(os.environ["MAX_AMOUNT"]), "validDuration": "60s"}],
    "action": "REJECT",
    "disable": False,
}]))
')"
polaris_api POST "/naming/v1/ratelimits" "$rule_body"
if [[ "$API_HTTP" != "200" ]] || ! polaris_ok; then
    log_error "create rate-limit rule failed http=${API_HTTP} body=${API_BODY}"
    exit 1
fi

log_step "wait until the provider observes the rule"
limited=0
allowed=0
for _ in $(seq 1 30); do
    allowed=0
    limited=0
    for _ in $(seq 1 "$BURST_COUNT"); do
        http_get "http://127.0.0.1:${PROVIDER_PORT}/echo"
        if [[ "$HTTP_CODE" == "200" ]]; then
            allowed=$((allowed + 1))
        elif [[ "$HTTP_CODE" == "429" ]]; then
            limited=$((limited + 1))
        fi
    done
    if [[ "$allowed" -gt 0 && "$limited" -gt 0 ]]; then
        break
    fi
    sleep 1
done
if [[ "$allowed" -eq 0 || "$limited" -eq 0 ]]; then
    log_error "provider did not both allow and reject: allowed=${allowed} limited=${limited}"
    dump_log provider
    exit 1
fi
log_info "provider burst allowed=${allowed} limited=${limited}"

log_step "run client"
client_log="${LOG_DIR}/client.log"
(
    cd "$REPO_ROOT"
    export POLARIS_SERVER_ADDRESSES="${POLARIS_SERVER}:8091"
    export POLARIS_NAMESPACE="${NAMESPACE}"
    export POLARIS_TOKEN="${POLARIS_TOKEN}"
    exec uv run python examples/ratelimit/client.py --service "$SERVICE_NAME" --count 8
) >"$client_log" 2>&1 || { log_error "client failed"; cat "$client_log" >&2; exit 1; }
if ! grep -q "status=" "$client_log"; then
    log_error "client produced no status lines"
    cat "$client_log" >&2
    exit 1
fi
log_info "client completed"
log_info "rate-limit verification passed"

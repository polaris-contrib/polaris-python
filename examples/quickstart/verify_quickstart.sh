#!/bin/bash
# Verify examples/quickstart: register a provider, then call it through the
# async HTTP consumer and the synchronous one-shot consumer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_verify_lib.sh
source "${SCRIPT_DIR}/../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-polaris-python-demo}"
PROVIDER_PORT="${PROVIDER_PORT:-28111}"
CONSUMER_PORT="${CONSUMER_PORT:-18080}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; shift 2 ;;
        --provider-port) PROVIDER_PORT="$2"; shift 2 ;;
        --consumer-port) CONSUMER_PORT="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--polaris-token TOKEN] [--service NAME]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_quickstart"
require_tools curl uv python3
free_port "$PROVIDER_PORT"
free_port "$CONSUMER_PORT"

log_step "start provider"
start_demo provider examples/quickstart/provider.py \
    --service "$SERVICE_NAME" --host 127.0.0.1 --port "$PROVIDER_PORT"
PROVIDER_PID="$LAST_PID"
wait_for_http "http://127.0.0.1:${PROVIDER_PORT}/echo" 20 "provider" "$PROVIDER_PID" \
    || { dump_log provider; exit 1; }

log_step "async consumer proxy"
start_demo consumer examples/quickstart/consumer.py \
    --service "$SERVICE_NAME" --port "$CONSUMER_PORT"
CONSUMER_PID="$LAST_PID"
wait_for_http "http://127.0.0.1:${CONSUMER_PORT}/echo" 30 "async consumer" "$CONSUMER_PID" \
    || { dump_log provider; dump_log consumer; exit 1; }

ok=0
for _ in $(seq 1 "$REQUEST_COUNT"); do
    http_get "http://127.0.0.1:${CONSUMER_PORT}/echo"
    if [[ "$HTTP_CODE" == "200" ]] && grep -q "127.0.0.1:${PROVIDER_PORT}" <<<"$HTTP_BODY"; then
        ok=$((ok + 1))
    else
        log_warn "async consumer unexpected code=${HTTP_CODE} body=${HTTP_BODY}"
    fi
done
if [[ "$ok" -ne "$REQUEST_COUNT" ]]; then
    log_error "async consumer matched ${ok}/${REQUEST_COUNT}"
    dump_log consumer
    exit 1
fi
log_info "async consumer matched ${ok}/${REQUEST_COUNT}"

log_step "sync consumer"
sync_log="${LOG_DIR}/consumer_sync.log"
(
    cd "$REPO_ROOT"
    export POLARIS_SERVER_ADDRESSES="${POLARIS_SERVER}:8091"
    export POLARIS_NAMESPACE="${NAMESPACE}"
    export POLARIS_TOKEN="${POLARIS_TOKEN}"
    exec uv run python examples/quickstart/consumer_sync.py --service "$SERVICE_NAME"
) >"$sync_log" 2>&1 || { log_error "consumer_sync failed"; cat "$sync_log" >&2; exit 1; }
if ! grep -q "127.0.0.1:${PROVIDER_PORT}" "$sync_log"; then
    log_error "sync consumer did not reach the provider"
    cat "$sync_log" >&2
    exit 1
fi
log_info "sync consumer reached 127.0.0.1:${PROVIDER_PORT}"
log_info "quickstart verification passed"

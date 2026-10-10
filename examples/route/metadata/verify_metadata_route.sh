#!/bin/bash
# Verify metadata routing. Matching is done by the consumer request metadata,
# so this script does not create a server routing rule.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../_verify_lib.sh
source "${SCRIPT_DIR}/../../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-RouteMetadataEchoServer}"
CONSUMER_PORT="${CONSUMER_PORT:-18090}"
ROUTE_ENVS="${ROUTE_ENVS:-dev,test,pre,prod}"
NEGATIVE_ENV="${NEGATIVE_ENV:-noexist}"
PROVIDER_PORTS=(28071 28072 28073 28074)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; shift 2 ;;
        --consumer-port) CONSUMER_PORT="$2"; shift 2 ;;
        --request-count) REQUEST_COUNT="$2"; shift 2 ;;
        --route-envs) ROUTE_ENVS="$2"; shift 2 ;;
        --negative-env) NEGATIVE_ENV="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--service NAME] [--request-count N]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_metadata_route"
require_tools curl uv python3
free_port "$CONSUMER_PORT"

log_step "start providers"
index=0
IFS=',' read -r -a envs <<<"$ROUTE_ENVS"
for env_name in "${envs[@]}"; do
    port="${PROVIDER_PORTS[$index]}"
    free_port "$port"
    start_demo "provider_${env_name}" examples/route/metadata/provider.py \
        --service "$SERVICE_NAME" --namespace "$NAMESPACE" \
        --port "$port" --metadata "env=${env_name}"
    wait_for_http "http://127.0.0.1:${port}/echo" 20 "provider-${env_name}" "$LAST_PID" \
        || { dump_log "provider_${env_name}"; exit 1; }
    index=$((index + 1))
done

log_step "start consumer"
start_demo consumer examples/route/metadata/consumer.py \
    --service "$SERVICE_NAME" --namespace "$NAMESPACE" \
    --port "$CONSUMER_PORT" --metadata "env=${envs[0]}"
wait_for_http "http://127.0.0.1:${CONSUMER_PORT}/echo?env=${envs[0]}" 40 "metadata consumer" "$LAST_PID" \
    || { dump_log consumer; exit 1; }

log_step "positive cases"
for env_name in "${envs[@]}"; do
    matched=0
    for _ in $(seq 1 "$REQUEST_COUNT"); do
        http_get "http://127.0.0.1:${CONSUMER_PORT}/echo?env=${env_name}"
        if [[ "$HTTP_CODE" == "200" ]] && grep -q "'env': '${env_name}'" <<<"$HTTP_BODY"; then
            matched=$((matched + 1))
        fi
    done
    if [[ "$matched" -ne "$REQUEST_COUNT" ]]; then
        log_error "env=${env_name} matched ${matched}/${REQUEST_COUNT} last=${HTTP_BODY}"
        dump_log consumer
        exit 1
    fi
    log_info "env=${env_name} matched ${matched}/${REQUEST_COUNT}"
done

log_step "negative case env=${NEGATIVE_ENV}"
rejected=0
for _ in $(seq 1 "$REQUEST_COUNT"); do
    http_get "http://127.0.0.1:${CONSUMER_PORT}/echo?env=${NEGATIVE_ENV}"
    if [[ "$HTTP_CODE" != "200" ]]; then
        rejected=$((rejected + 1))
    fi
done
if [[ "$rejected" -ne "$REQUEST_COUNT" ]]; then
    log_error "env=${NEGATIVE_ENV} rejected ${rejected}/${REQUEST_COUNT} last_code=${HTTP_CODE}"
    exit 1
fi
log_info "env=${NEGATIVE_ENV} rejected ${rejected}/${REQUEST_COUNT}"
log_info "metadata route verification passed"

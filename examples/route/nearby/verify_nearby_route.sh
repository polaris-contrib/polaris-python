#!/bin/bash
# Verify nearby routing. The script creates a campus-level nearby rule and
# checks that the consumer stays on its own campus.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../_verify_lib.sh
source "${SCRIPT_DIR}/../../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-RouteNearbyEchoServer}"
CONSUMER_PORT="${CONSUMER_PORT:-18080}"
REGION="${REGION:-china}"
ZONE="${ZONE:-ap-guangzhou}"
CONSUMER_CAMPUS="${CONSUMER_CAMPUS:-ap-guangzhou-1}"
PROVIDER_CAMPUSES=(ap-guangzhou-1 ap-guangzhou-2 ap-guangzhou-3)
PROVIDER_PORTS=(28091 28092 28093)
RULE_NAME="${RULE_NAME:-${SERVICE_NAME}-auto-nearby}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; RULE_NAME="${SERVICE_NAME}-auto-nearby"; shift 2 ;;
        --consumer-port) CONSUMER_PORT="$2"; shift 2 ;;
        --request-count) REQUEST_COUNT="$2"; shift 2 ;;
        --consumer-campus) CONSUMER_CAMPUS="$2"; shift 2 ;;
        --rule-name) RULE_NAME="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--service NAME] [--request-count N]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_nearby_route"
require_tools curl uv python3
free_port "$CONSUMER_PORT"

log_step "start providers"
index=0
for campus in "${PROVIDER_CAMPUSES[@]}"; do
    port="${PROVIDER_PORTS[$index]}"
    free_port "$port"
    start_demo "provider_${index}" examples/route/nearby/provider.py \
        --service "$SERVICE_NAME" --namespace "$NAMESPACE" --port "$port" \
        --region "$REGION" --zone "$ZONE" --campus "$campus"
    wait_for_http "http://127.0.0.1:${port}/echo" 20 "provider-${campus}" "$LAST_PID" \
        || { dump_log "provider_${index}"; exit 1; }
    index=$((index + 1))
done

log_step "create nearby rule ${RULE_NAME}"
rule_body="$(SERVICE_NAME="$SERVICE_NAME" NAMESPACE="$NAMESPACE" RULE_NAME="$RULE_NAME" python3 -c '
import json, os
print(json.dumps([{
    "name": os.environ["RULE_NAME"],
    "namespace": os.environ["NAMESPACE"],
    "enable": True,
    "routing_policy": "NearbyPolicy",
    "routing_config": {
        "@type": "type.googleapis.com/v1.NearbyRoutingConfig",
        "service": os.environ["SERVICE_NAME"],
        "namespace": os.environ["NAMESPACE"],
        "match_level": "CAMPUS",
        "max_match_level": "REGION",
        "strict_nearby": False,
    },
    "priority": 0,
    "description": "auto-created by verify_nearby_route.sh",
}]))
')"
polaris_api POST "/naming/v2/routings" "$rule_body"
if [[ "$API_HTTP" != "200" ]] || ! polaris_ok; then
    log_error "create nearby rule failed http=${API_HTTP} body=${API_BODY}"
    exit 1
fi
log_info "nearby rule created"
wait_for_discover_rule NEARBY_ROUTE_RULE "$SERVICE_NAME" "$RULE_NAME" || exit 1

log_step "start consumer campus=${CONSUMER_CAMPUS}"
start_demo consumer examples/route/nearby/consumer.py \
    --service "$SERVICE_NAME" --namespace "$NAMESPACE" --port "$CONSUMER_PORT" \
    --region "$REGION" --zone "$ZONE" --campus "$CONSUMER_CAMPUS"
if ! wait_for_http "http://127.0.0.1:${CONSUMER_PORT}/echo" 40 "nearby consumer" "$LAST_PID"; then
    dump_log consumer
    exit 1
fi

log_step "requests should stay on ${CONSUMER_CAMPUS}"
matched=0
for _ in $(seq 1 "$REQUEST_COUNT"); do
    http_get "http://127.0.0.1:${CONSUMER_PORT}/echo"
    if [[ "$HTTP_CODE" == "200" ]] && grep -q "'campus': '${CONSUMER_CAMPUS}'" <<<"$HTTP_BODY"; then
        matched=$((matched + 1))
    else
        log_warn "nearby miss code=${HTTP_CODE} body=${HTTP_BODY}"
    fi
done
if [[ "$matched" -ne "$REQUEST_COUNT" ]]; then
    log_error "nearby matched ${matched}/${REQUEST_COUNT}"
    dump_log consumer
    exit 1
fi
log_info "nearby matched ${matched}/${REQUEST_COUNT}"
log_info "nearby route verification passed"

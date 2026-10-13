#!/bin/bash
# Verify rule routing. The script creates a Polaris rule that maps query env
# to provider metadata, then calls examples/route/rule.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../_verify_lib.sh
source "${SCRIPT_DIR}/../../_verify_lib.sh"

SERVICE_NAME="${SERVICE_NAME:-RouteEchoServer}"
CONSUMER_PORT="${CONSUMER_PORT:-18080}"
ROUTE_ENVS="${ROUTE_ENVS:-dev,test,pre,prod}"
RULE_NAME="${RULE_NAME:-${SERVICE_NAME}-auto-rule}"
PROVIDER_PORTS=(28081 28082 28083 28084)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --polaris-server) POLARIS_SERVER="$2"; POLARIS_HTTP="http://${POLARIS_SERVER}:8090"; shift 2 ;;
        --polaris-token) POLARIS_TOKEN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --service) SERVICE_NAME="$2"; RULE_NAME="${SERVICE_NAME}-auto-rule"; shift 2 ;;
        --consumer-port) CONSUMER_PORT="$2"; shift 2 ;;
        --request-count) REQUEST_COUNT="$2"; shift 2 ;;
        --route-envs) ROUTE_ENVS="$2"; shift 2 ;;
        --rule-name) RULE_NAME="$2"; shift 2 ;;
        -h|--help)
            echo "usage: $0 [--polaris-server HOST] [--service NAME] [--request-count N]"
            exit 0
            ;;
        *) log_error "unknown argument: $1"; exit 1 ;;
    esac
done

verify_init "verify_rule_route"
require_tools curl uv python3
free_port "$CONSUMER_PORT"

log_step "start providers"
index=0
IFS=',' read -r -a envs <<<"$ROUTE_ENVS"
for env_name in "${envs[@]}"; do
    port="${PROVIDER_PORTS[$index]}"
    free_port "$port"
    start_demo "provider_${env_name}" examples/route/rule/provider.py \
        --service "$SERVICE_NAME" --namespace "$NAMESPACE" \
        --port "$port" --metadata "env=${env_name}"
    wait_for_http "http://127.0.0.1:${port}/echo" 20 "provider-${env_name}" "$LAST_PID" \
        || { dump_log "provider_${env_name}"; exit 1; }
    index=$((index + 1))
done

log_step "create routing rule ${RULE_NAME}"
rule_body="$(ROUTE_ENVS="$ROUTE_ENVS" SERVICE_NAME="$SERVICE_NAME" NAMESPACE="$NAMESPACE" RULE_NAME="$RULE_NAME" python3 -c '
import json, os
envs = [item.strip() for item in os.environ["ROUTE_ENVS"].split(",") if item.strip()]
rules = []
for env_name in envs:
    rules.append({
        "name": f"env-{env_name}",
        "sources": [{
            "service": "*",
            "namespace": "*",
            "arguments": [{
                "type": "QUERY",
                "key": "env",
                "value": {"type": "EXACT", "value": env_name, "value_type": "TEXT"},
            }],
        }],
        "destinations": [{
            "service": os.environ["SERVICE_NAME"],
            "namespace": os.environ["NAMESPACE"],
            "labels": {"env": {"type": "EXACT", "value": env_name, "value_type": "TEXT"}},
            "priority": 0,
            "weight": 100,
            "name": f"dest-{env_name}",
        }],
    })
print(json.dumps([{
    "name": os.environ["RULE_NAME"],
    "namespace": os.environ["NAMESPACE"],
    "enable": True,
    "routing_policy": "RulePolicy",
    "routing_config": {"@type": "type.googleapis.com/v1.RuleRoutingConfig", "rules": rules},
    "priority": 0,
    "description": "auto-created by verify_rule_route.sh",
}]))
')"
polaris_api POST "/naming/v2/routings" "$rule_body"
if [[ "$API_HTTP" != "200" ]] || ! polaris_ok; then
    log_error "create routing rule failed http=${API_HTTP} body=${API_BODY}"
    exit 1
fi
log_info "routing rule created"
wait_for_discover_rule ROUTING "$SERVICE_NAME" "$RULE_NAME" || exit 1

log_step "start consumer"
start_demo consumer examples/route/rule/consumer.py \
    --service "$SERVICE_NAME" --namespace "$NAMESPACE" --port "$CONSUMER_PORT"
if ! wait_for_http "http://127.0.0.1:${CONSUMER_PORT}/echo?env=${envs[0]}" 40 "rule consumer" "$LAST_PID"; then
    dump_log consumer
    exit 1
fi

log_step "matched query env"
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
log_info "rule route verification passed"

#!/bin/bash
# Run every example verification script. Each script talks to a local Polaris
# server. Override the address with POLARIS_SERVER and POLARIS_TOKEN.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts=(
    quickstart/verify_quickstart.sh
    route/metadata/verify_metadata_route.sh
    route/rule/verify_rule_route.sh
    route/nearby/verify_nearby_route.sh
    ratelimit/verify_ratelimit.sh
    circuitbreaker/verify_circuitbreaker.sh
)

failed=0
for script in "${scripts[@]}"; do
    echo ""
    echo "===== ${script} ====="
    if ! bash "${ROOT}/${script}"; then
        echo "FAILED ${script}"
        failed=1
    else
        echo "PASSED ${script}"
    fi
done

if [[ "$failed" -ne 0 ]]; then
    echo "one or more example verifications failed"
    exit 1
fi
echo "all example verifications passed"

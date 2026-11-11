#!/usr/bin/env bash
set -euo pipefail
integration_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${integration_dir}/_scripts.sh"
integration_manage --directory "$integration_dir" verify-e2e "$@"

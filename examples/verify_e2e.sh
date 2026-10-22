#!/usr/bin/env bash
set -euo pipefail
example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${example_dir}/_internal/_scripts.sh"
example_manage "$example_dir" verify-e2e "$@"

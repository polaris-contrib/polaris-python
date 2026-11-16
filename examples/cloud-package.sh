#!/usr/bin/env bash
# Build the cloud E2E deployment package from the examples entry point.
set -euo pipefail
examples_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${examples_dir}/../integration/cloud/build-package.sh" "$@"

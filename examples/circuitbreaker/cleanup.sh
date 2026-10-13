#!/bin/bash
# 清理 examples/circuitbreaker 残留的 provider / client 进程，以及 .logs / .build。
#
#   ./cleanup.sh           # 先展示再确认
#   ./cleanup.sh -f        # 直接清理
#   ./cleanup.sh --dry-run # 只展示

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_cleanup_lib.sh
source "${SCRIPT_DIR}/../_cleanup_lib.sh"

cleanup_main "CircuitBreaker 示例进程清理工具" \
    'examples/circuitbreaker/provider\.py' \
    'examples/circuitbreaker/client\.py' \
    "$@"

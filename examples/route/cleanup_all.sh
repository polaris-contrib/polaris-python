#!/bin/bash
# 依次清理 examples/route 下 metadata、rule、nearby 三个 demo。
#
#   ./cleanup_all.sh           # 每个子目录各自确认
#   ./cleanup_all.sh -f        # 全部直接清理
#   ./cleanup_all.sh --dry-run # 只展示

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
demos=(metadata rule nearby)

echo ""
echo "========================================"
echo "  Route 示例聚合清理"
echo "========================================"

for demo in "${demos[@]}"; do
    echo ""
    echo "----- ${demo} -----"
    bash "${SCRIPT_DIR}/${demo}/cleanup.sh" "$@"
done

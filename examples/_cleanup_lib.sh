# Shared cleanup for example demos. Source from a demo directory after setting
# SCRIPT_DIR to that directory. Requires bash 3.2.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

cleanup_parse_args() {
    FORCE=false
    DRY_RUN=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f|--force) FORCE=true; shift ;;
            --dry-run) DRY_RUN=true; shift ;;
            -h|--help)
                echo "用法: $0 [-f|--force] [--dry-run]"
                echo "  -f, --force    直接清理，不需要确认"
                echo "  --dry-run      仅展示匹配的进程，不执行清理"
                exit 0
                ;;
            *) echo -e "${RED}未知参数: $1${NC}"; exit 1 ;;
        esac
    done
}

cleanup_dirs() {
    local has_dir=false
    local dir_name target_dir dir_size
    for dir_name in .build .logs; do
        if [[ -d "${SCRIPT_DIR}/${dir_name}" ]]; then
            has_dir=true
            break
        fi
    done
    if [[ "$has_dir" == false ]]; then
        return
    fi

    echo ""
    echo -e "${YELLOW}发现构建/日志目录:${NC}"
    for dir_name in .build .logs; do
        target_dir="${SCRIPT_DIR}/${dir_name}"
        if [[ -d "$target_dir" ]]; then
            dir_size=$(du -sh "$target_dir" 2>/dev/null | awk '{print $1}')
            echo -e "  ${dir_name}/  (${dir_size})"
        fi
    done

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[dry-run] 仅展示，未清理目录。${NC}"
        return
    fi

    if [[ "$FORCE" != true ]]; then
        read -r -p "是否清理以上目录? [y/N] " response
        case "$response" in
            [yY]|[yY][eE][sS]) ;;
            *)
                echo -e "${YELLOW}跳过目录清理。${NC}"
                return
                ;;
        esac
    fi

    for dir_name in .build .logs; do
        target_dir="${SCRIPT_DIR}/${dir_name}"
        if [[ -d "$target_dir" ]]; then
            rm -rf "$target_dir"
            echo -e "  ${GREEN}✓${NC} 已清理目录: ${dir_name}/"
        fi
    done
}

cleanup_print_table() {
    local line pid ppid cmd start_time
    printf "  ${CYAN}%-8s %-8s %-22s %s${NC}\n" "PID" "PPID" "启动时间" "命令"
    printf "  %-8s %-8s %-22s %s\n" "--------" "--------" "----------------------" "------------------------------"
    for line in "$@"; do
        pid=$(echo "$line" | awk '{print $2}')
        ppid=$(echo "$line" | awk '{print $3}')
        cmd=$(echo "$line" | awk '{for(j=8;j<=NF;j++) printf "%s ", $j; print ""}')
        start_time=$(ps -p "$pid" -o lstart= 2>/dev/null || echo "N/A")
        if [[ "$start_time" != "N/A" ]] && [[ -n "$start_time" ]]; then
            start_time=$(echo "$start_time" | awk '{printf "%s %s %s %s", $4, $2, $3, $5}')
        fi
        printf "  %-8s %-8s %-22s %s\n" "$pid" "$ppid" "$start_time" "$cmd"
    done
}

cleanup_kill_pids() {
    local killed=0 failed=0 force_killed=0 pid
    local all_pids=("$@")
    for pid in "${all_pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            if kill "$pid" 2>/dev/null; then
                pkill -P "$pid" 2>/dev/null || true
                echo -e "  ${GREEN}✓${NC} 已终止 PID $pid (SIGTERM)"
                killed=$((killed + 1))
            else
                echo -e "  ${RED}✗${NC} 无法终止 PID $pid"
                failed=$((failed + 1))
            fi
        else
            echo -e "  ${YELLOW}-${NC} PID $pid 已不存在，跳过"
        fi
    done
    sleep 1
    for pid in "${all_pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${YELLOW}!${NC} PID $pid 未响应 SIGTERM，发送 SIGKILL..."
            kill -9 "$pid" 2>/dev/null || true
            pkill -9 -P "$pid" 2>/dev/null || true
            force_killed=$((force_killed + 1))
        fi
    done
    echo -e "  ${GREEN}清理完成:${NC} 终止 ${killed} 个进程" \
        "$( [[ $force_killed -gt 0 ]] && echo ", 强制杀掉 ${force_killed} 个" )" \
        "$( [[ $failed -gt 0 ]] && echo -e ", ${RED}${failed} 个失败${NC}" )"
}

cleanup_collect() {
    local pattern="$1"
    local line pid
    CLEANUP_PIDS=()
    CLEANUP_DESCS=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        pid=$(echo "$line" | awk '{print $2}')
        CLEANUP_PIDS+=("$pid")
        CLEANUP_DESCS+=("$line")
    done < <(ps -ef 2>/dev/null | grep -E "$pattern" | grep -v grep || true)
}

cleanup_group() {
    local label="$1"
    local pattern="$2"
    cleanup_collect "$pattern"
    if [[ ${#CLEANUP_PIDS[@]} -eq 0 ]]; then
        return 1
    fi
    echo -e "${YELLOW}发现 ${#CLEANUP_PIDS[@]} 个残留 ${label} 进程:${NC}"
    echo ""
    cleanup_print_table "${CLEANUP_DESCS[@]}"
    echo ""
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[dry-run] 仅展示 ${label} 进程，未执行清理。${NC}"
    elif [[ "$FORCE" == true ]]; then
        cleanup_kill_pids "${CLEANUP_PIDS[@]}"
    else
        read -r -p "确认清理以上 ${label} 进程? [y/N] " response
        case "$response" in
            [yY]|[yY][eE][sS]) cleanup_kill_pids "${CLEANUP_PIDS[@]}" ;;
            *) echo -e "${YELLOW}跳过 ${label} 进程清理。${NC}" ;;
        esac
    fi
    echo ""
    return 0
}

# cleanup_main TITLE PROVIDER_REGEX CONSUMER_REGEX [args...]
cleanup_main() {
    local title="$1"
    local provider_pattern="$2"
    local consumer_pattern="$3"
    shift 3
    cleanup_parse_args "$@"

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${title}${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    local found=false
    if cleanup_group "Provider" "$provider_pattern"; then
        found=true
    fi
    if cleanup_group "Consumer" "$consumer_pattern"; then
        found=true
    fi

    if [[ "$found" == false ]]; then
        echo -e "${GREEN}未发现残留进程，无需清理。${NC}"
    elif [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[dry-run] 以上为进程展示结果，未执行任何清理操作。${NC}"
    else
        echo -e "${GREEN}进程清理流程完成。${NC}"
    fi

    cleanup_dirs
    echo ""
}

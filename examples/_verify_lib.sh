# Shared helpers for example verification scripts.
# Source this file after setting SCRIPT_DIR. Requires bash 3.2.

VERIFY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${VERIFY_LIB_DIR}/.." && pwd)"

POLARIS_SERVER="${POLARIS_SERVER:-127.0.0.1}"
POLARIS_TOKEN="${POLARIS_TOKEN:-}"
NAMESPACE="${NAMESPACE:-default}"
REQUEST_COUNT="${REQUEST_COUNT:-10}"
POLARIS_HTTP="http://${POLARIS_SERVER}:8090"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PIDS=()
LAST_PID=""
HTTP_CODE=""
HTTP_BODY=""
API_HTTP=""
API_BODY=""

log_info() { printf '%b\n' "${GREEN}[INFO]${NC} $(date '+%H:%M:%S') $*" | tee -a "${LOG_FILE:-/dev/null}"; }
log_warn() { printf '%b\n' "${YELLOW}[WARN]${NC} $(date '+%H:%M:%S') $*" | tee -a "${LOG_FILE:-/dev/null}"; }
log_error() { printf '%b\n' "${RED}[ERROR]${NC} $(date '+%H:%M:%S') $*" | tee -a "${LOG_FILE:-/dev/null}"; }
log_step() {
    echo "" | tee -a "${LOG_FILE:-/dev/null}"
    printf '%b\n' "${CYAN}==== $* ====${NC}" | tee -a "${LOG_FILE:-/dev/null}"
}

verify_init() {
    local name="$1"
    LOG_DIR="${SCRIPT_DIR}/.logs"
    mkdir -p "$LOG_DIR"
    LOG_FILE="${LOG_DIR}/${name}-$(date +%Y%m%d_%H%M%S).log"
    : >"$LOG_FILE"
    trap verify_cleanup EXIT
    log_info "repo=${REPO_ROOT}"
    log_info "polaris=${POLARIS_SERVER}:8091 http=${POLARIS_HTTP} namespace=${NAMESPACE}"
    log_info "log=${LOG_FILE}"
}

verify_cleanup() {
    local pid
    for pid in "${PIDS[@]:-}"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            pkill -P "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
}

require_tools() {
    local tool
    for tool in "$@"; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "missing command: ${tool}"
            exit 1
        fi
    done
}

free_port() {
    local port="$1"
    local pids
    pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then
        return 0
    fi
    log_warn "port ${port} is in use, stopping pid ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
}

http_get() {
    local url="$1"
    local body_file="${LOG_DIR}/http_body"
    HTTP_CODE="$(curl -sS -o "$body_file" -w '%{http_code}' --connect-timeout 5 --max-time 10 "$url" 2>/dev/null || echo 000)"
    HTTP_BODY="$(cat "$body_file" 2>/dev/null || true)"
}

wait_for_http() {
    local url="$1"
    local max_wait="${2:-30}"
    local desc="${3:-service}"
    local pid="${4:-}"
    local waited=0
    while [[ "$waited" -lt "$max_wait" ]]; do
        if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
            log_error "${desc} exited before ${url} was ready"
            return 1
        fi
        http_get "$url"
        if [[ "$HTTP_CODE" == "200" ]]; then
            log_info "${desc} ready (${url})"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    log_error "${desc} not ready (${url}) last_code=${HTTP_CODE} body=${HTTP_BODY}"
    return 1
}

start_demo() {
    local name="$1"
    shift
    local log="${LOG_DIR}/${name}.log"
    (
        cd "$REPO_ROOT"
        export POLARIS_SERVER_ADDRESSES="${POLARIS_SERVER}:8091"
        export POLARIS_NAMESPACE="${NAMESPACE}"
        export POLARIS_TOKEN="${POLARIS_TOKEN}"
        exec uv run python "$@"
    ) >"$log" 2>&1 &
    LAST_PID=$!
    PIDS+=("$LAST_PID")
    log_info "started ${name} pid=${LAST_PID}"
    sleep 1
    if ! kill -0 "$LAST_PID" 2>/dev/null; then
        log_error "${name} exited immediately"
        cat "$log" >&2 || true
        exit 1
    fi
}

dump_log() {
    local name="$1"
    log_error "----- ${name} log -----"
    cat "${LOG_DIR}/${name}.log" >&2 || true
}

polaris_api() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local out="${LOG_DIR}/api_last.json"
    if [[ -n "$body" ]]; then
        API_HTTP="$(curl -sS -o "$out" -w '%{http_code}' --connect-timeout 5 --max-time 15 \
            -X "$method" "${POLARIS_HTTP}${path}" \
            -H "X-Polaris-Token:${POLARIS_TOKEN}" \
            -H 'Content-Type: application/json' \
            --data-raw "$body" 2>/dev/null || echo 000)"
    else
        API_HTTP="$(curl -sS -o "$out" -w '%{http_code}' --connect-timeout 5 --max-time 15 \
            -X "$method" "${POLARIS_HTTP}${path}" \
            -H "X-Polaris-Token:${POLARIS_TOKEN}" \
            -H 'Content-Type: application/json' 2>/dev/null || echo 000)"
    fi
    API_BODY="$(cat "$out" 2>/dev/null || true)"
}

# wait_for_discover_rule TYPE SERVICE RULE_NAME [MAX_WAIT]
# New rules reach Discover only after the server refreshes its cache.
wait_for_discover_rule() {
    local discover_type="$1"
    local service="$2"
    local rule_name="$3"
    local max_wait="${4:-30}"
    local body="{\"service\":{\"name\":\"${service}\",\"namespace\":\"${NAMESPACE}\"},\"type\":\"${discover_type}\"}"
    local waited=0
    while [[ "$waited" -lt "$max_wait" ]]; do
        polaris_api POST "/v1/Discover" "$body"
        if [[ "$API_HTTP" == "200" ]] && grep -qF "$rule_name" <<<"$API_BODY"; then
            log_info "${discover_type} rule ${rule_name} visible in Discover after ${waited}s"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    log_error "${discover_type} rule ${rule_name} not visible in Discover after ${max_wait}s"
    return 1
}

polaris_ok() {
    python3 -c 'import json,sys; data=json.load(sys.stdin); code=data.get("code", 0); raise SystemExit(0 if code in (200000, 200001) else 1)' <<<"$API_BODY"
}

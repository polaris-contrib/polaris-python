#!/usr/bin/env bash
# Run polaris-python real-service E2E inside an extracted cloud deployment package.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    ROOT="$SCRIPT_DIR"
elif [[ -f "${SCRIPT_DIR}/../../pyproject.toml" ]]; then
    ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
elif [[ -f "${SCRIPT_DIR}/../pyproject.toml" ]]; then
    ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
else
    echo "ERROR: cannot locate deployment package root" >&2
    exit 1
fi

SERVER="${POLARIS_SERVER_ADDRESS:-}"
NAMESPACE="${POLARIS_E2E_NAMESPACE:-polaris-python-integration}"
ONLY=""
TIMEOUT=""
PYTHON_BIN="${CLOUD_PYTHON:-}"
RUN_ID=""
RUNS_ROOT="${CLOUD_RUNS_DIR:-${ROOT}/cloud-runs}"
CREATE_ARCHIVE=true
EXTRA_ARGS=()

usage() {
    cat <<EOF
Usage: $0 --server HOST:8091 [options] [-- extra verify_e2e args]

Options:
  --server ADDRESS       Polaris registry address; default: POLARIS_SERVER_ADDRESS
  --namespace NS         E2E namespace; default: ${NAMESPACE}
  --only LIST            Comma-separated E2E scenarios
  --timeout SECONDS      Per-scenario timeout passed to verify_e2e.sh
  --python PATH          Python 3.12 executable for bundled runtime
  --run-id ID            Stable run directory name
  --runs-root DIR        Output root; default: ${RUNS_ROOT}
  --no-archive           Do not create the log archive automatically
  -h, --help             Show this help

Credentials are read only from environment variables:
  POLARIS_TOKEN, POLARIS_SERVICE_TOKEN, POLARIS_E2E_SERVICE_TOKEN

The script does not delete retained processes or remote services.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            SERVER="$2"
            shift 2
            ;;
        --namespace)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            NAMESPACE="$2"
            shift 2
            ;;
        --only)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            ONLY="$2"
            shift 2
            ;;
        --timeout)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            TIMEOUT="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            PYTHON_BIN="$2"
            shift 2
            ;;
        --run-id)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            RUN_ID="$2"
            shift 2
            ;;
        --runs-root)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            RUNS_ROOT="$2"
            shift 2
            ;;
        --no-archive)
            CREATE_ARCHIVE=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[[ -n "$SERVER" ]] || die "--server or POLARIS_SERVER_ADDRESS is required"
[[ "$NAMESPACE" != "default" ]] || die "POLARIS_E2E_NAMESPACE must not be default"
if [[ -n "$RUN_ID" && ! "$RUN_ID" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    die "--run-id may contain only letters, digits, dot, underscore and dash"
fi

find_python() {
    local candidate
    for candidate in "$PYTHON_BIN" python3.12 python3; do
        [[ -n "$candidate" ]] || continue
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' 2>/dev/null; then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python)" || die "Python >=3.12 is required"
RUNTIME_DIR="${ROOT}/runtime"
if [[ -d "$RUNTIME_DIR" ]]; then
    "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
        || die "bundled runtime targets Python 3.12; pass a 3.12 executable with --python"
    export PYTHONPATH="${RUNTIME_DIR}:${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
    export POLARIS_PYTHON="$PYTHON_BIN"
else
    command -v uv >/dev/null 2>&1 || die "source-only package requires uv or use a runtime-bundled package"
    uv sync --project "$ROOT" --locked --no-dev --python 3.12 >/dev/null
    POLARIS_PYTHON="${ROOT}/.venv/bin/python"
    [[ -x "$POLARIS_PYTHON" ]] || die "uv sync did not create ${POLARIS_PYTHON}"
    export POLARIS_PYTHON
    export PYTHONPATH="${ROOT}/src:${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
fi

RUN_ID="${RUN_ID:-run-$(date '+%Y%m%d_%H%M%S')-$$}"
RUN_DIR="${RUNS_ROOT}/${RUN_ID}"
[[ ! -e "$RUN_DIR" ]] || die "run directory already exists: $RUN_DIR"
mkdir -p "$RUN_DIR"
RUN_LOG="${RUN_DIR}/run.log"
STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

log() {
    printf '%s\n' "$*" | tee -a "$RUN_LOG"
}

log "Run ID: ${RUN_ID}"
log "Root: ${ROOT}"
log "Server: ${SERVER}"
log "Namespace: ${NAMESPACE}"
log "Python: $("$PYTHON_BIN" --version 2>&1)"
log "Started: ${STARTED_AT}"

{
    echo "date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "hostname=$(hostname 2>/dev/null || true)"
    echo "uname=$(uname -a 2>/dev/null || true)"
    echo "python=$("$PYTHON_BIN" --version 2>&1)"
    echo "server=${SERVER}"
    echo "namespace=${NAMESPACE}"
    echo "only=${ONLY}"
    echo "timeout=${TIMEOUT}"
    echo "runtime_bundled=$([[ -d "$RUNTIME_DIR" ]] && echo true || echo false)"
    echo "POLARIS_TOKEN_set=$([[ -n "${POLARIS_TOKEN:-}" ]] && echo true || echo false)"
    echo "POLARIS_SERVICE_TOKEN_set=$([[ -n "${POLARIS_SERVICE_TOKEN:-}" ]] && echo true || echo false)"
} > "${RUN_DIR}/environment.txt"

PACKAGE_NAME="$(basename "$ROOT")"
export RUN_DIR RUN_ID RUN_LOG SERVER NAMESPACE ONLY TIMEOUT PACKAGE_NAME STARTED_AT
python3 - "$RUN_DIR" <<'PY'
import json
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = {
    "run_id": os.environ["RUN_ID"],
    "package": os.environ["PACKAGE_NAME"],
    "server": os.environ["SERVER"],
    "namespace": os.environ["NAMESPACE"],
    "only": os.environ["ONLY"],
    "timeout": os.environ["TIMEOUT"],
    "started_at": os.environ["STARTED_AT"],
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

export POLARIS_SERVER_ADDRESS="$SERVER"
export POLARIS_E2E_NAMESPACE="$NAMESPACE"
COMMAND=("${ROOT}/integration/verify_e2e.sh")
[[ -n "$ONLY" ]] && COMMAND+=(--only "$ONLY")
[[ -n "$TIMEOUT" ]] && COMMAND+=(--timeout "$TIMEOUT")
COMMAND+=("${EXTRA_ARGS[@]}")

set +e
"${COMMAND[@]}" 2>&1 | tee -a "$RUN_LOG"
EXIT_CODE=${PIPESTATUS[0]}
set -e

FINISHED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
export EXIT_CODE FINISHED_AT
python3 - "$RUN_DIR" <<'PY'
import json
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1]) / "manifest.json"
manifest = json.loads(path.read_text(encoding="utf-8"))
manifest["finished_at"] = os.environ["FINISHED_AT"]
manifest["exit_code"] = int(os.environ["EXIT_CODE"])
path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

mkdir -p "${RUN_DIR}/logs"
if [[ -d "${ROOT}/integration/.logs" ]]; then
    cp -R "${ROOT}/integration/.logs/." "${RUN_DIR}/logs/"
fi
if [[ -d "${ROOT}/integration/.runtime" ]]; then
    cp -R "${ROOT}/integration/.runtime" "${RUN_DIR}/runtime-records"
fi

SUMMARIZER="${ROOT}/summarize-results.py"
[[ -f "$SUMMARIZER" ]] || SUMMARIZER="${ROOT}/integration/cloud/summarize-results.py"
"$PYTHON_BIN" "$SUMMARIZER" "$RUN_DIR" --output "${RUN_DIR}/analysis.txt" || true

log "Finished: ${FINISHED_AT}"
log "Exit code: ${EXIT_CODE}"
log "Run directory: ${RUN_DIR}"

if [[ "$CREATE_ARCHIVE" == true ]]; then
    PACKER="${ROOT}/pack-logs.sh"
    [[ -f "$PACKER" ]] || PACKER="${ROOT}/integration/cloud/pack-logs.sh"
    ARCHIVE="${RUNS_ROOT}/${RUN_ID}-logs.tar.gz"
    "$PACKER" --run-dir "$RUN_DIR" --output "$ARCHIVE"
    log "Log archive: ${ARCHIVE}"
fi

if [[ "$EXIT_CODE" -eq 0 ]]; then
    log "Cloud E2E passed."
else
    log "Cloud E2E failed; inspect analysis.txt and logs/."
fi
exit "$EXIT_CODE"

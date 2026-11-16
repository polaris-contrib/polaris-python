#!/usr/bin/env bash
# Pack one or more polaris-python cloud E2E runs for transfer back to the local host.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    ROOT="$SCRIPT_DIR"
elif [[ -f "${SCRIPT_DIR}/../../pyproject.toml" ]]; then
    ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
else
    echo "ERROR: cannot locate package root" >&2
    exit 1
fi

RUNS_ROOT="${CLOUD_RUNS_DIR:-${ROOT}/cloud-runs}"
RUN_DIR=""
LOG_DIR=""
OUTPUT=""
PACK_ALL=false

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --run-dir DIR        Pack one completed cloud run
  --log-dir DIR        Pack an integration/.logs directory directly
  --runs-root DIR      Cloud run root; default: ${RUNS_ROOT}
  --all                Pack every run below --runs-root
  --output FILE        Archive path; default: polaris-python-e2e-logs-<time>.tar.gz
  -h, --help           Show this help

With no arguments, all cloud-runs/* directories are packed. If none exist,
integration/.logs is packed as a manual run.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            RUN_DIR="$2"
            shift 2
            ;;
        --log-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            LOG_DIR="$2"
            shift 2
            ;;
        --runs-root)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            RUNS_ROOT="$2"
            shift 2
            ;;
        --all)
            PACK_ALL=true
            shift
            ;;
        --output)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            OUTPUT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[[ -z "$RUN_DIR" || -z "$LOG_DIR" ]] || die "--run-dir and --log-dir are mutually exclusive"

TMP_DIR=""
cleanup() {
    [[ -z "$TMP_DIR" ]] || rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT

SUMMARIZER="${ROOT}/summarize-results.py"
[[ -f "$SUMMARIZER" ]] || SUMMARIZER="${ROOT}/integration/cloud/summarize-results.py"
PYTHON_BIN="${CLOUD_PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "python3 is required"

BASE_DIR=""
ENTRIES=()
if [[ -n "$RUN_DIR" ]]; then
    [[ -d "$RUN_DIR" ]] || die "run directory not found: $RUN_DIR"
    RUN_DIR="$(cd "$RUN_DIR" && pwd)"
    BASE_DIR="$(dirname "$RUN_DIR")"
    ENTRIES=("$(basename "$RUN_DIR")")
elif [[ -n "$LOG_DIR" ]]; then
    [[ -d "$LOG_DIR" ]] || die "log directory not found: $LOG_DIR"
    TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/polaris-python-pack.XXXXXX")"
    manual="manual-$(date '+%Y%m%d_%H%M%S')"
    mkdir -p "${TMP_DIR}/${manual}"
    cp -R "$LOG_DIR" "${TMP_DIR}/${manual}/logs"
    {
        echo "run_id=${manual}"
        echo "source_log_dir=$(cd "$LOG_DIR" && pwd)"
        echo "packed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    } > "${TMP_DIR}/${manual}/environment.txt"
    printf '{"run_id":"%s","source":"manual-log-dir"}\n' "$manual" \
        > "${TMP_DIR}/${manual}/manifest.json"
    "$PYTHON_BIN" "$SUMMARIZER" "${TMP_DIR}/${manual}" || true
    BASE_DIR="$TMP_DIR"
    ENTRIES=("$manual")
else
    RUNS_ROOT="$(cd "$RUNS_ROOT" 2>/dev/null && pwd || true)"
    if [[ -n "$RUNS_ROOT" && -d "$RUNS_ROOT" ]]; then
        while IFS= read -r directory; do
            ENTRIES+=("$(basename "$directory")")
        done < <(find "$RUNS_ROOT" -mindepth 1 -maxdepth 1 -type d | sort)
    fi
    if [[ ${#ENTRIES[@]} -gt 0 ]]; then
        BASE_DIR="$RUNS_ROOT"
        PACK_ALL=true
    else
        LOG_DIR="${ROOT}/integration/.logs"
        [[ -d "$LOG_DIR" ]] || die "no cloud runs and integration/.logs does not exist"
        TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/polaris-python-pack.XXXXXX")"
        manual="manual-$(date '+%Y%m%d_%H%M%S')"
        mkdir -p "${TMP_DIR}/${manual}"
        cp -R "$LOG_DIR" "${TMP_DIR}/${manual}/logs"
        "$PYTHON_BIN" "$SUMMARIZER" "${TMP_DIR}/${manual}" || true
        BASE_DIR="$TMP_DIR"
        ENTRIES=("$manual")
    fi
fi

for entry in "${ENTRIES[@]}"; do
    directory="${BASE_DIR}/${entry}"
    if [[ -d "${directory}/logs" && -f "$SUMMARIZER" ]]; then
        "$PYTHON_BIN" "$SUMMARIZER" "$directory" || true
    fi
done

if [[ -z "$OUTPUT" ]]; then
    if [[ "$PACK_ALL" == true ]]; then
        OUTPUT="${ROOT}/polaris-python-e2e-logs-all-$(date '+%Y%m%d_%H%M%S').tar.gz"
    elif [[ ${#ENTRIES[@]} -eq 1 ]]; then
        OUTPUT="${ROOT}/${ENTRIES[0]}-logs.tar.gz"
    else
        OUTPUT="${ROOT}/polaris-python-e2e-logs-$(date '+%Y%m%d_%H%M%S').tar.gz"
    fi
fi
mkdir -p "$(dirname "$OUTPUT")"
OUTPUT="$(cd "$(dirname "$OUTPUT")" && pwd)/$(basename "$OUTPUT")"

tar -czf "$OUTPUT" -C "$BASE_DIR" "${ENTRIES[@]}"
if command -v sha256sum >/dev/null 2>&1; then
    (
        cd "$(dirname "$OUTPUT")"
        sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256"
    )
else
    (
        cd "$(dirname "$OUTPUT")"
        shasum -a 256 "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256"
    )
fi

echo "Log archive: ${OUTPUT}"
echo "Checksum:    ${OUTPUT}.sha256"
echo "Transfer:    scp $(whoami 2>/dev/null || echo user)@<cloud-host>:${OUTPUT} ."

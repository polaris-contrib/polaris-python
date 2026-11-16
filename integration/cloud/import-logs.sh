#!/usr/bin/env bash
# Safely import a cloud E2E log archive into the local integration log area.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_ROOT="${REPO_ROOT}/integration/.logs/imported"
FORCE=false

usage() {
    cat <<EOF
Usage: $0 ARCHIVE [options]

Options:
  --output-dir DIR   Extraction directory; default: ${OUTPUT_ROOT}/<archive-name>
  --force            Replace an existing extraction directory
  -h, --help         Show this help

The adjacent ARCHIVE.sha256 file is verified when present.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

ARCHIVE=""
OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            die "unknown argument: $1"
            ;;
        *)
            [[ -z "$ARCHIVE" ]] || die "only one archive may be imported"
            ARCHIVE="$1"
            shift
            ;;
    esac
done

[[ -n "$ARCHIVE" ]] || die "ARCHIVE is required"
[[ -f "$ARCHIVE" ]] || die "archive not found: $ARCHIVE"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"
base="$(basename "$ARCHIVE")"
base="${base%.tar.gz}"
base="${base%.tgz}"
OUTPUT_DIR="${OUTPUT_DIR:-${OUTPUT_ROOT}/${base}}"

if [[ -e "$OUTPUT_DIR" ]]; then
    [[ "$FORCE" == true ]] || die "output exists: $OUTPUT_DIR (use --force)"
    rm -rf -- "$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR"

python3 - "$ARCHIVE" "$OUTPUT_DIR" <<'PY'
import hashlib
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2]).resolve()
sidecar = archive.with_name(archive.name + ".sha256")
if sidecar.is_file():
    first = sidecar.read_text(encoding="utf-8").split()
    if not first:
        raise SystemExit(f"invalid checksum file: {sidecar}")
    expected = first[0].lower()
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(
            f"checksum mismatch for {archive}: expected {expected}, got {actual}"
        )

with tarfile.open(archive, "r:gz") as package:
    members = package.getmembers()
    for member in members:
        target = (destination / member.name).resolve()
        if not target.is_relative_to(destination):
            raise SystemExit(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk():
            raise SystemExit(f"archive links are not accepted: {member.name}")
    package.extractall(destination, filter="data")
PY

entries=()
while IFS= read -r path; do
    entries+=("$path")
done < <(
    find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 \
        \( -type f -o -type d \) | sort
)

RUN_DIR="$OUTPUT_DIR"
if [[ ${#entries[@]} -eq 1 && -d "${entries[0]}" ]]; then
    RUN_DIR="${entries[0]}"
fi

SUMMARIZER="${REPO_ROOT}/integration/cloud/summarize-results.py"
python3 "$SUMMARIZER" "$RUN_DIR" --output "${RUN_DIR}/analysis.txt" || true

echo "Imported: ${OUTPUT_DIR}"
echo "Analysis: ${RUN_DIR}/analysis.txt"

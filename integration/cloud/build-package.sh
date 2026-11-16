#!/usr/bin/env bash
# Build a cloud deployment package for the polaris-python real-service E2E suite.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BUILD_ROOT="${SCRIPT_DIR}/.build"
OUTPUT_DIR="${SCRIPT_DIR}/dist"
PACKAGE_NAME=""
PACKAGE_NAME_EXPLICIT=false
PYTHON_VERSION="3.12"
PYTHON_PLATFORM="x86_64-manylinux_2_28"
BUNDLE_RUNTIME=true
WHEEL_OVERRIDE=""
KEEP_OLD=false

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --output-dir DIR       Archive output directory; default: ${OUTPUT_DIR}
  --build-root DIR       Temporary build root; default: ${BUILD_ROOT}
  --name NAME            Package basename; default: generated from version/git/time
  --python-version VER   Runtime Python version; default: ${PYTHON_VERSION}
  --python-platform TAG  Runtime platform; default: ${PYTHON_PLATFORM}
  --without-runtime      Do not bundle dependencies; cloud needs uv and network
  --wheel PATH           Use an existing wheel instead of running uv build
  --keep-old             Keep older timestamped packages in the output directory
  --clean                Remove build and output directories, then exit
  -h, --help             Show this help
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --build-root)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            BUILD_ROOT="$2"
            shift 2
            ;;
        --name)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            PACKAGE_NAME="$2"
            PACKAGE_NAME_EXPLICIT=true
            shift 2
            ;;
        --python-version)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --python-platform)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            PYTHON_PLATFORM="$2"
            shift 2
            ;;
        --without-runtime)
            BUNDLE_RUNTIME=false
            shift
            ;;
        --wheel)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            WHEEL_OVERRIDE="$2"
            shift 2
            ;;
        --keep-old)
            KEEP_OLD=true
            shift
            ;;
        --clean)
            rm -rf -- "$BUILD_ROOT" "$OUTPUT_DIR"
            echo "Removed ${BUILD_ROOT} and ${OUTPUT_DIR}"
            exit 0
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

[[ -f "${REPO_ROOT}/pyproject.toml" ]] || die "pyproject.toml not found in ${REPO_ROOT}"
[[ -f "${REPO_ROOT}/uv.lock" ]] || die "uv.lock not found in ${REPO_ROOT}"
command -v uv >/dev/null 2>&1 || die "uv is required to build the deployment package"

VERSION="$(
    python3 - "${REPO_ROOT}/src/polaris/_version.py" <<'PY'
import ast
import pathlib
import sys

tree = ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for node in tree.body:
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__version__"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        print(node.value.value)
        raise SystemExit(0)
raise SystemExit("__version__ assignment not found")
PY
)"
GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)" ]]; then
    GIT_DIRTY=true
else
    GIT_DIRTY=false
fi
STAMP="$(date '+%Y%m%d_%H%M%S')"
PACKAGE_NAME="${PACKAGE_NAME:-polaris-python-cloud-${VERSION}-${GIT_COMMIT}-${STAMP}}"
STAGE_DIR="${BUILD_ROOT}/${PACKAGE_NAME}"
WHEEL_DIR="${BUILD_ROOT}/wheels"

rm -rf -- "$STAGE_DIR" "$WHEEL_DIR"
mkdir -p "$STAGE_DIR" "$WHEEL_DIR" "$OUTPUT_DIR"

echo "[1/5] Copying source, examples and integration material"
cp -R "${REPO_ROOT}/src" "${STAGE_DIR}/src"
cp -R "${REPO_ROOT}/examples" "${STAGE_DIR}/examples"
cp -R "${REPO_ROOT}/integration" "${STAGE_DIR}/integration"
cp "${REPO_ROOT}/pyproject.toml" "${REPO_ROOT}/uv.lock" "$STAGE_DIR/"
for file in README.md README-zh.md LICENSE; do
    [[ -f "${REPO_ROOT}/${file}" ]] && cp "${REPO_ROOT}/${file}" "$STAGE_DIR/"
done

find "$STAGE_DIR" -type d \
    \( -name __pycache__ -o -name .logs -o -name .runtime -o -name .build \
       -o -name .pytest_cache -o -name .ruff_cache -o -name dist \) \
    -prune -exec rm -rf -- {} +
find "$STAGE_DIR" -type f \
    \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \
       -o -name bin -o -name x86-bin \) \
    -delete
rm -rf -- "$STAGE_DIR/integration/cloud/dist" "$STAGE_DIR/integration/cloud/.build"

install -m 0755 "${SCRIPT_DIR}/run-e2e.sh" "${STAGE_DIR}/run-e2e.sh"
install -m 0755 "${SCRIPT_DIR}/pack-logs.sh" "${STAGE_DIR}/pack-logs.sh"
install -m 0755 "${SCRIPT_DIR}/import-logs.sh" "${STAGE_DIR}/import-logs.sh"
install -m 0755 "${SCRIPT_DIR}/summarize-results.py" "${STAGE_DIR}/summarize-results.py"
cp "${SCRIPT_DIR}/README-zh.md" "${STAGE_DIR}/CLOUD-README-zh.md"
cp "${SCRIPT_DIR}/README.md" "${STAGE_DIR}/CLOUD-README.md"

echo "[2/5] Preparing wheel and locked requirements"
if [[ -n "$WHEEL_OVERRIDE" ]]; then
    [[ -f "$WHEEL_OVERRIDE" ]] || die "wheel not found: $WHEEL_OVERRIDE"
    cp "$WHEEL_OVERRIDE" "$WHEEL_DIR/"
else
    uv build --wheel --out-dir "$WHEEL_DIR" "$REPO_ROOT" >/dev/null
fi
WHEEL="$(find "$WHEEL_DIR" -maxdepth 1 -type f -name '*.whl' | head -n 1)"
[[ -n "$WHEEL" ]] || die "wheel build produced no artifact"
mkdir -p "$STAGE_DIR/wheels"
cp "$WHEEL" "$STAGE_DIR/wheels/"
uv export \
    --project "$REPO_ROOT" \
    --locked \
    --no-dev \
    --no-emit-project \
    --no-hashes \
    --format requirements.txt \
    --output-file "$STAGE_DIR/requirements.txt" >/dev/null

echo "[3/5] Preparing runtime"
RUNTIME_BUNDLED=false
if [[ "$BUNDLE_RUNTIME" == true ]]; then
    mkdir -p "$STAGE_DIR/runtime"
    uv pip install \
        --target "$STAGE_DIR/runtime" \
        --python-version "$PYTHON_VERSION" \
        --python-platform "$PYTHON_PLATFORM" \
        --only-binary :all: \
        --no-cache \
        --requirements "$STAGE_DIR/requirements.txt" \
        "$WHEEL"
    RUNTIME_BUNDLED=true
fi

echo "[4/5] Writing manifest and checksums"
BUILD_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
export PACKAGE_NAME VERSION GIT_COMMIT GIT_DIRTY PYTHON_VERSION PYTHON_PLATFORM
export RUNTIME_BUNDLED BUILD_AT STAGE_DIR REPO_ROOT
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

stage = Path(os.environ["STAGE_DIR"])
manifest = {
    "package": os.environ["PACKAGE_NAME"],
    "version": os.environ["VERSION"],
    "git_commit": os.environ["GIT_COMMIT"],
    "git_dirty": os.environ["GIT_DIRTY"] == "true",
    "built_at": os.environ["BUILD_AT"],
    "source_root": os.environ["REPO_ROOT"],
    "target_python": os.environ["PYTHON_VERSION"],
    "target_platform": os.environ["PYTHON_PLATFORM"],
    "runtime_bundled": os.environ["RUNTIME_BUNDLED"] == "true",
    "entrypoints": ["run-e2e.sh", "pack-logs.sh", "import-logs.sh"],
}
(stage / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

checksums = []
for path in sorted(stage.rglob("*")):
    if not path.is_file() or path.name == "SHA256SUMS":
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksums.append(f"{digest}  {path.relative_to(stage).as_posix()}")
(stage / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
PY

echo "[5/5] Creating archive"
if [[ "$KEEP_OLD" == false && "$PACKAGE_NAME_EXPLICIT" == false ]]; then
    rm -f -- "$OUTPUT_DIR/polaris-python-cloud-${VERSION}-${GIT_COMMIT}-"*.tar.gz \
        "$OUTPUT_DIR/polaris-python-cloud-${VERSION}-${GIT_COMMIT}-"*.sha256
fi
ARCHIVE="${OUTPUT_DIR}/${PACKAGE_NAME}.tar.gz"
tar -czf "$ARCHIVE" -C "$BUILD_ROOT" "$PACKAGE_NAME"
if command -v sha256sum >/dev/null 2>&1; then
    (
        cd "$OUTPUT_DIR"
        sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
    )
else
    (
        cd "$OUTPUT_DIR"
        shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
    )
fi
rm -rf -- "$STAGE_DIR" "$WHEEL_DIR"

cat <<EOF

Package:  ${ARCHIVE}
Checksum: ${ARCHIVE}.sha256
Runtime:  $([[ "$RUNTIME_BUNDLED" == true ]] && echo bundled || echo cloud-install)

Upload:
  scp ${ARCHIVE} ${ARCHIVE}.sha256 <user>@<cloud-host>:~/

On the cloud host:
  tar xzf $(basename "$ARCHIVE")
  cd ${PACKAGE_NAME}
  ./run-e2e.sh --server <polaris-host>:8091
EOF

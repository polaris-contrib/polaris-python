#!/usr/bin/env bash
# Shared entry point for integration commands.
set -euo pipefail

integration_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${integration_dir}/.." && pwd)"

integration_manage() {
    if [[ -n "${POLARIS_PYTHON:-}" ]]; then
        exec "$POLARIS_PYTHON" "${integration_dir}/_manage.py" "$@"
    elif [[ -x "${repo_dir}/.venv/bin/python" ]]; then
        exec "${repo_dir}/.venv/bin/python" "${integration_dir}/_manage.py" "$@"
    elif command -v uv >/dev/null 2>&1; then
        exec uv run --project "$repo_dir" --locked python "${integration_dir}/_manage.py" "$@"
    else
        exec python3 "${integration_dir}/_manage.py" "$@"
    fi
}

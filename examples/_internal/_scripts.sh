#!/usr/bin/env bash
# Shared entry point; paths are derived from the invoking script, never from $PWD.
set -euo pipefail

example_scripts_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
example_repo_dir="$(cd -- "${example_scripts_dir}/../.." && pwd)"

example_manage() {
    if [[ -n "${POLARIS_PYTHON:-}" ]]; then
        exec "$POLARIS_PYTHON" "${example_scripts_dir}/_manage.py" --directory "$@"
    elif [[ -x "${example_repo_dir}/.venv/bin/python" ]]; then
        exec "${example_repo_dir}/.venv/bin/python" "${example_scripts_dir}/_manage.py" --directory "$@"
    elif command -v uv >/dev/null 2>&1; then
        exec uv run --project "$example_repo_dir" --locked python "${example_scripts_dir}/_manage.py" --directory "$@"
    else
        exec python3 "${example_scripts_dir}/_manage.py" --directory "$@"
    fi
}

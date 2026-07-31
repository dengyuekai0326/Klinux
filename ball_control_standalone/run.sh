#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

preflight_args=()
for argument in "$@"; do
    if [[ "$argument" == "--no-serial" ]]; then
        preflight_args+=(--no-serial)
    fi
done

python3 tools/preflight.py "${preflight_args[@]}"
exec python3 main.py "$@"

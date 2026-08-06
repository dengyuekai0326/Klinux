#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

main_args=(--model models/best.pt "$@")
preflight_args=(--allow-missing-engine)

for argument in "$@"; do
    if [[ "$argument" == "--no-serial" ]]; then
        preflight_args+=(--no-serial)
    fi
done

python3 tools/preflight.py "${preflight_args[@]}"
exec python3 main.py "${main_args[@]}"

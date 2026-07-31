#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

main_args=(--model models/best.pt "$@")
preflight_args=(--allow-missing-engine)

serial_present=false
if [[ -e /dev/ttyACM0 ]]; then
    serial_present=true
fi
for argument in "$@"; do
    if [[ "$argument" == "--no-serial" ]]; then
        serial_present=false
    fi
done
if [[ "$serial_present" == false ]]; then
    preflight_args+=(--no-serial)
    main_args+=(--no-serial)
    echo "Desktop: /dev/ttyACM0 not active, serial disabled"
fi

python3 tools/preflight.py "${preflight_args[@]}"
exec python3 main.py "${main_args[@]}"

#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

# 手动启动与桌面自启动共用同一把锁，杜绝重复占用摄像头和串口。
lock_dir="${XDG_RUNTIME_DIR:-/tmp}"
lock_file="$lock_dir/ball-control-v2-${UID}.lock"
exec 9>"$lock_file"
if ! flock -n 9; then
    echo "Ball Control v2 is already running."
    echo "Use the existing debug window; do not start a second instance."
    exit 73
fi

preflight_args=()
for argument in "$@"; do
    if [[ "$argument" == "--no-serial" ]]; then
        preflight_args+=(--no-serial)
    fi
done

python3 tools/preflight.py "${preflight_args[@]}"
exec python3 main.py "$@"

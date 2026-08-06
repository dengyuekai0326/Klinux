#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="${YOLO_VENV:-$HOME/venvs/yolo}"
log_dir="$project_dir/logs"
mkdir -p "$log_dir"
cd "$project_dir"

if [[ ! -f "$venv_dir/bin/activate" ]]; then
    echo "Python environment not found: $venv_dir" >&2
    exit 1
fi

source "$venv_dir/bin/activate"
exec >>"$log_dir/autostart.log" 2>&1

echo
echo "===== Ball Control v2 desktop session: $(date --iso-8601=seconds) ====="

# 图形桌面刚登录时USB设备可能尚未就绪。异常退出自动重试；用户按Q/Esc
# 得到退出码0后停止重试。退出码73表示已有实例，避免生成第二个重试进程。
while true; do
    set +e
    "$project_dir/run.sh"
    return_code=$?
    set -e
    if [[ "$return_code" -eq 0 || "$return_code" -eq 73 ]]; then
        exit 0
    fi
    echo "Startup failed with code $return_code; retrying in 3 seconds..."
    sleep 3
done

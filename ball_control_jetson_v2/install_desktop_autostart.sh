#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
autostart_dir="$HOME/.config/autostart"
desktop_file="$autostart_dir/ball-control-v2.desktop"
venv_dir="${YOLO_VENV:-$HOME/venvs/yolo}"
action="${1:-install}"

show_status() {
    if [[ -f "$desktop_file" ]]; then
        echo "Autostart: ENABLED"
        echo "Entry:     $desktop_file"
    else
        echo "Autostart: DISABLED"
    fi
    if pgrep -af 'python.*main.py' >/dev/null; then
        echo "Process:"
        pgrep -af 'python.*main.py'
    else
        echo "Process:   not running"
    fi
}

disable_autostart() {
    if [[ ! -f "$desktop_file" ]]; then
        echo "Autostart is already disabled."
        return
    fi
    backup_dir="$autostart_dir/disabled-ball-control"
    mkdir -p "$backup_dir"
    mv -- "$desktop_file" "$backup_dir/ball-control-v2.desktop"
    echo "Autostart disabled (recoverable backup kept in $backup_dir)."
}

install_autostart() {
    if [[ ! -f "$venv_dir/bin/activate" ]]; then
        echo "ERROR: YOLO environment not found: $venv_dir" >&2
        echo "If it is elsewhere, run:" >&2
        echo "  YOLO_VENV=/your/venv/path ./install_desktop_autostart.sh" >&2
        exit 1
    fi
    if [[ ! -f "$project_dir/models/best.engine" ]]; then
        echo "ERROR: models/best.engine is missing." >&2
        echo "Run ./export_engine.sh on this Jetson first." >&2
        exit 1
    fi
    if [[ ! -f "$project_dir/config/system.yaml" ]]; then
        echo "ERROR: config/system.yaml is missing." >&2
        exit 1
    fi

    chmod +x \
        "$project_dir/run.sh" \
        "$project_dir/run_autostart.sh" \
        "$project_dir/install_desktop_autostart.sh"
    mkdir -p "$autostart_dir"

    # 将同一用户下旧版球控桌面入口移动到带时间戳的备份目录，避免双启动。
    backup_dir="$autostart_dir/backup-$(date +%Y%m%d_%H%M%S)"
    old_entry_found=false
    while IFS= read -r -d '' entry; do
        [[ "$entry" == "$desktop_file" ]] && continue
        entry_name="${entry##*/}"
        lower_name="${entry_name,,}"
        case "$lower_name" in
            *ball*control*.desktop|*ball*vision*.desktop)
                if [[ "$old_entry_found" == false ]]; then
                    mkdir -p "$backup_dir"
                    old_entry_found=true
                fi
                mv -- "$entry" "$backup_dir/"
                echo "Backed up old entry: $entry_name"
                ;;
        esac
    done < <(find "$autostart_dir" -maxdepth 1 -type f -name '*.desktop' -print0)

    {
        echo "[Desktop Entry]"
        echo "Type=Application"
        echo "Name=Ball Control v2"
        echo "Comment=Low-latency ball vision and serial controller"
        echo "Exec=$project_dir/run_autostart.sh"
        echo "TryExec=$project_dir/run_autostart.sh"
        echo "Path=$project_dir"
        echo "Terminal=false"
        echo "StartupNotify=false"
        echo "X-GNOME-Autostart-enabled=true"
        echo "X-GNOME-Autostart-Delay=3"
    } >"$desktop_file"
    chmod 644 "$desktop_file"

    echo
    echo "AUTOSTART_INSTALL_OK"
    echo "Project: $project_dir"
    echo "Entry:   $desktop_file"
    echo "Venv:    $venv_dir"
    echo "Log:     $project_dir/logs/autostart.log"
    echo
    echo "Reboot once to verify: sudo reboot"
}

case "$action" in
    install)
        install_autostart
        ;;
    status)
        show_status
        ;;
    disable)
        disable_autostart
        ;;
    *)
        echo "Usage: $0 [install|status|disable]" >&2
        exit 2
        ;;
esac

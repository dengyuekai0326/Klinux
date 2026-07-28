#!/usr/bin/env bash
set -euo pipefail

KWORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [[ -z "${DESKTOP_DIR}" || ! -d "${DESKTOP_DIR}" ]]; then
  if [[ -d "${HOME}/桌面" ]]; then
    DESKTOP_DIR="${HOME}/桌面"
  else
    DESKTOP_DIR="${HOME}/Desktop"
  fi
fi
APP_DIR="${HOME}/.local/share/applications"

mkdir -p "${DESKTOP_DIR}" "${APP_DIR}"

write_desktop_file() {
  local name="$1"
  local comment="$2"
  local run_script="$3"
  local workdir="$4"
  local desktop_path="$5"
  local terminal="${6:-true}"

  cat > "${desktop_path}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=${name}
Comment=${comment}
Exec=${run_script}
Path=${workdir}
Terminal=${terminal}
StartupNotify=true
Categories=Utility;
EOF
  chmod +x "${desktop_path}"
}

install_one() {
  local app_id="$1"
  local name="$2"
  local comment="$3"
  local rel_dir="$4"
  local run_name="$5"
  local terminal="${6:-true}"
  local workdir="${KWORK_DIR}/${rel_dir}"
  local run_script="${workdir}/${run_name}"

  if [[ ! -x "${run_script}" ]]; then
    echo "[skip] ${name}: missing executable ${run_script}"
    return
  fi

  local desktop_file="${DESKTOP_DIR}/${name}.desktop"
  local app_file="${APP_DIR}/${app_id}.desktop"
  write_desktop_file "${name}" "${comment}" "${run_script}" "${workdir}" "${desktop_file}" "${terminal}"
  write_desktop_file "${name}" "${comment}" "${run_script}" "${workdir}" "${app_file}" "${terminal}"

  gio set "${desktop_file}" metadata::trusted true 2>/dev/null || true
  echo "[ok] ${name}"
  echo "     desktop: ${desktop_file}"
  echo "     appmenu: ${app_file}"
}

install_one "hsv-segmenter" "HSV分割调参" "Open HSV segmentation tuning UI" "hsv_segmenter" "run_hsv_segmenter.sh" "true"
install_one "ros2-panel" "ROS2控制面板" "Open ROS2 command control panel" "ros2_panel" "run_ros2_panel.sh" "true"
install_one "yolo-image-collector" "YOLO图像采集" "Collect camera images for YOLO training" "yolo_image_collector" "run_yolo_image_collector.sh" "true"

update-desktop-database "${APP_DIR}" 2>/dev/null || true

echo
echo "完成。桌面目录: ${DESKTOP_DIR}"
echo "如果桌面仍显示为文本文件，请右键图标，选择“允许启动”。"

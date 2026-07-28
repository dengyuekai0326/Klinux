#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [[ -z "${DESKTOP_DIR}" || ! -d "${DESKTOP_DIR}" ]]; then
  DESKTOP_DIR="${HOME}/Desktop"
fi
if [[ ! -d "${DESKTOP_DIR}" && -d "${HOME}/桌面" ]]; then
  DESKTOP_DIR="${HOME}/桌面"
fi
mkdir -p "${DESKTOP_DIR}" "${HOME}/.local/share/applications"

DESKTOP_FILE="${DESKTOP_DIR}/HSV分割调参.desktop"
MENU_FILE="${HOME}/.local/share/applications/hsv-segmenter.desktop"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=HSV分割调参
Comment=Open HSV segmentation tuning UI
Exec=${APP_DIR}/run_hsv_segmenter.sh
Path=${APP_DIR}
Terminal=true
StartupNotify=true
Categories=Utility;
EOF

cp "${DESKTOP_FILE}" "${MENU_FILE}"
chmod +x "${APP_DIR}/run_hsv_segmenter.sh" "${DESKTOP_FILE}" "${MENU_FILE}"
gio set "${DESKTOP_FILE}" metadata::trusted true 2>/dev/null || true
update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true

echo "已安装桌面启动器: ${DESKTOP_FILE}"
echo "已安装应用菜单入口: ${MENU_FILE}"

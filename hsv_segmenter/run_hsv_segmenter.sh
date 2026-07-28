#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 hsv_segmenter_gui.py --camera 0 --output hsv_params.json

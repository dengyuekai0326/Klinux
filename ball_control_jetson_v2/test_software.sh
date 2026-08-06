#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

python3 -m py_compile main.py ball_control/*.py tools/*.py
python3 -m pytest -q
python3 tools/preflight.py --allow-missing-engine --no-hardware

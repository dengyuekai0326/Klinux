#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

python3 tools/preflight.py --allow-missing-engine --no-hardware
python3 tools/export_engine_jetson.py
python3 tools/preflight.py --no-hardware

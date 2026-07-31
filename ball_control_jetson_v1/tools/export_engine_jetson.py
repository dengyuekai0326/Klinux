#!/usr/bin/env python3
"""Export best.pt to the fixed rectangular TensorRT FP16 engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ball_control.config import load_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "best.pt",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "system.yaml",
    )
    parser.add_argument("--workspace", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        raise SystemExit(f"model not found: {model_path}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable; export this engine on the Jetson")
    config = load_config(args.config)
    height, width = config.model.imgsz
    print(f"Exporting TensorRT FP16 engine: input={width}x{height}, batch=1")
    output = YOLO(str(model_path)).export(
        format="engine",
        imgsz=(height, width),
        batch=1,
        half=True,
        dynamic=False,
        workspace=args.workspace,
        device=0,
        simplify=True,
    )
    print(f"TensorRT engine: {output}")


if __name__ == "__main__":
    main()

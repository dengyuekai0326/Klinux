#!/usr/bin/env python3
"""Check standalone runtime dependencies, model, camera and serial devices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ball_control.config import load_config  # noqa: E402
from ball_control.camera import resolve_camera_device  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "system.yaml",
    )
    parser.add_argument("--allow-missing-engine", action="store_true")
    parser.add_argument("--no-hardware", action="store_true")
    parser.add_argument("--no-serial", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    config = load_config(args.config)
    print(f"Python:      {sys.version.split()[0]}")
    try:
        import cv2

        print(f"OpenCV:      {cv2.__version__}")
    except ImportError:
        errors.append("opencv-python is not installed")
    try:
        import serial

        print(f"PySerial:    {serial.VERSION}")
    except ImportError:
        errors.append("pyserial is not installed")
    try:
        import torch
        import ultralytics

        print(f"PyTorch:     {torch.__version__}")
        print(f"Ultralytics: {ultralytics.__version__}")
        print(f"CUDA:        {torch.version.cuda}")
        if not torch.cuda.is_available():
            errors.append("CUDA is unavailable")
        else:
            print(f"GPU:         {torch.cuda.get_device_name(0)}")
    except ImportError as exc:
        errors.append(f"model dependency missing: {exc}")

    engine = config.resolve(config.model.path)
    fallback = config.resolve(config.model.fallback_path)
    print(f"Engine:      {engine}")
    if not engine.is_file() and not args.allow_missing_engine:
        errors.append(f"TensorRT engine is missing: {engine}")
    if not fallback.is_file():
        errors.append(f"PyTorch fallback is missing: {fallback}")

    if not args.no_hardware:
        try:
            camera = Path(resolve_camera_device(config.camera.device))
        except (FileNotFoundError, ValueError) as exc:
            camera = Path(config.camera.device)
            errors.append(str(exc))
        serial_port = Path(config.serial.port)
        print(f"Camera:      {camera}")
        print(f"Serial:      {serial_port}")
        if not camera.exists():
            errors.append(f"camera device is missing: {camera}")
        if (
            config.serial.enabled
            and not args.no_serial
            and not serial_port.exists()
        ):
            errors.append(f"serial device is missing: {serial_port}")

    if errors:
        print("\nFAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("\nPREFLIGHT_OK")


if __name__ == "__main__":
    main()

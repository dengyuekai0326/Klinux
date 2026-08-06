#!/usr/bin/env python3
"""Benchmark TensorRT using pre-decoded memory frames, matching live inference."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ball_control.calibration import PipeCalibration  # noqa: E402
from ball_control.config import load_config  # noqa: E402
from ball_control.detector import BallDetector  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("images", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "system.yaml",
    )
    parser.add_argument("--warmup", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_paths = sorted(args.images.expanduser().resolve().glob("*.jpg"))
    frames = [cv2.imread(str(path)) for path in image_paths]
    if not frames or any(frame is None for frame in frames):
        raise SystemExit(f"failed to load test images from {args.images}")
    print(f"Preloaded {len(frames)} decoded frames into memory")

    config = load_config(args.config)
    detector = BallDetector(
        config.model,
        PipeCalibration(config.calibration),
        args.model.expanduser().resolve(),
    )
    detector.warmup(
        width=frames[0].shape[1],
        height=frames[0].shape[0],
        count=args.warmup,
    )
    for frame in frames:
        detector.detect(frame)

    frame_count, detections, mean, median, p95 = detector.stats()
    print(f"Images:       {len(frames)}")
    print(f"Detections:   {detections}")
    print(f"Mean latency: {mean:.2f} ms ({1000.0 / mean:.1f} FPS)")
    print(f"Median:       {median:.2f} ms")
    print(f"P95 latency:  {p95:.2f} ms")
    print(f"30 FPS P95:   {'PASS' if p95 <= 33.33 else 'FAIL'}")
    if frame_count != len(frames):
        raise SystemExit("internal benchmark frame count mismatch")


if __name__ == "__main__":
    main()

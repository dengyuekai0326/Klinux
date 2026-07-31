#!/usr/bin/env python3
"""Benchmark TensorRT using pre-decoded memory frames, matching live inference."""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("images", type=Path)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.15)
    parser.add_argument("--warmup", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_paths = sorted(args.images.expanduser().resolve().glob("*.jpg"))
    frames = [cv2.imread(str(path)) for path in image_paths]
    if not frames or any(frame is None for frame in frames):
        raise SystemExit(f"failed to load test images from {args.images}")
    print(f"Preloaded {len(frames)} decoded frames into memory")

    model = YOLO(str(args.model.expanduser().resolve()), task="detect")
    options = dict(
        imgsz=args.imgsz,
        conf=args.conf,
        classes=[0],
        max_det=3,
        device=0,
        verbose=False,
    )
    for index in range(args.warmup):
        model.predict(frames[index % len(frames)], **options)
    torch.cuda.synchronize()

    latencies: list[float] = []
    detections = 0
    for frame in frames:
        started = time.perf_counter()
        result = model.predict(frame, **options)[0]
        torch.cuda.synchronize()
        latencies.append((time.perf_counter() - started) * 1000.0)
        detections += len(result.boxes)

    ordered = sorted(latencies)
    mean = statistics.mean(ordered)
    median = statistics.median(ordered)
    p95 = ordered[round((len(ordered) - 1) * 0.95)]
    print(f"Images:       {len(frames)}")
    print(f"Detections:   {detections}")
    print(f"Mean latency: {mean:.2f} ms ({1000.0 / mean:.1f} FPS)")
    print(f"Median:       {median:.2f} ms")
    print(f"P95 latency:  {p95:.2f} ms")
    print(f"30 FPS P95:   {'PASS' if p95 <= 33.33 else 'FAIL'}")


if __name__ == "__main__":
    main()

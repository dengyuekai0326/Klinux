#!/usr/bin/env python3
"""Click left endpoint, zero point, and right endpoint to obtain fixed ratios."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from ball_control.camera import LatestFrameCamera  # noqa: E402
from ball_control.config import load_config  # noqa: E402


WINDOW = "Pipe Calibration"
LABELS = ("LEFT -12.5cm", "CENTER 0cm", "RIGHT +12.5cm")
COLORS = ((255, 0, 0), (0, 255, 255), (255, 0, 0))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "system.yaml",
    )
    return parser.parse_args()


def main() -> None:
    config = load_config(parse_args().config)
    camera = LatestFrameCamera(config.camera)
    points: list[int] = []

    def on_mouse(event, x, _y, _flags, _data) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 3:
            points.append(x)
            print(f"{LABELS[len(points) - 1]}: x={x}")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW, on_mouse)
    camera.start()
    last_sequence = 0
    last_frame = None
    print("Click LEFT, CENTER, RIGHT in order. R resets, S prints ratios, Q quits.")
    try:
        while True:
            sample = camera.wait_for_new(last_sequence, timeout=0.2)
            if sample is not None:
                last_sequence = sample.sequence
                last_frame = sample.frame
            if last_frame is None:
                continue
            output = last_frame.copy()
            height, width = output.shape[:2]
            for index, x in enumerate(points):
                cv2.line(output, (x, 0), (x, height - 1), COLORS[index], 2)
                cv2.putText(
                    output,
                    LABELS[index],
                    (max(0, x - 70), 30 + index * 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    COLORS[index],
                    2,
                )
            prompt = (
                LABELS[len(points)]
                if len(points) < 3
                else "Press S to print calibration"
            )
            cv2.putText(
                output,
                prompt,
                (12, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            cv2.imshow(WINDOW, output)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                points.clear()
                print("Calibration reset")
            if key in (ord("s"), ord("S")) and len(points) == 3:
                if not points[0] < points[1] < points[2]:
                    print("Invalid order: must satisfy LEFT < CENTER < RIGHT")
                    points.clear()
                    continue
                print("\nCopy into config/system.yaml:")
                print("calibration:")
                print(f"  left_x_ratio: {points[0] / width:.6f}")
                print(f"  center_x_ratio: {points[1] / width:.6f}")
                print(f"  right_x_ratio: {points[2] / width:.6f}")
                time.sleep(0.2)
                break
    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Interactive HSV segmentation and camera-control helper."""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


WINDOW_CONTROLS = "HSV Controls"
WINDOW_PREVIEW = "Preview"
WINDOW_MASK = "Mask"
WINDOW_RESULT = "Segmented"


TRACKBARS = {
    "H min": (0, 179),
    "H max": (179, 179),
    "S min": (0, 255),
    "S max": (255, 255),
    "V min": (0, 255),
    "V max": (255, 255),
    "Auto exposure": (1, 1),
    "Exposure": (50, 100),
    "Auto WB": (1, 1),
    "WB temp": (45, 100),
    "Gain": (0, 100),
    "Brightness": (50, 100),
    "Contrast": (50, 100),
    "Saturation": (50, 100),
}


CAMERA_PROPS = {
    "Exposure": cv2.CAP_PROP_EXPOSURE,
    "Auto WB": cv2.CAP_PROP_AUTO_WB,
    "WB temp": cv2.CAP_PROP_WB_TEMPERATURE,
    "Gain": cv2.CAP_PROP_GAIN,
    "Brightness": cv2.CAP_PROP_BRIGHTNESS,
    "Contrast": cv2.CAP_PROP_CONTRAST,
    "Saturation": cv2.CAP_PROP_SATURATION,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tune HSV segmentation and camera controls with OpenCV UI."
    )
    parser.add_argument("--camera", type=int, default=0, help="Initial camera index.")
    parser.add_argument("--max-camera", type=int, default=8, help="Highest UI camera index.")
    parser.add_argument("--width", type=int, default=1280, help="Requested capture width.")
    parser.add_argument("--height", type=int, default=720, help="Requested capture height.")
    parser.add_argument("--fps", type=int, default=30, help="Requested capture FPS.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("hsv_params.json"),
        help="Path to save exported parameters.",
    )
    return parser.parse_args()


def empty_callback(_: int) -> None:
    pass


def create_trackbars(initial_camera: int, max_camera: int) -> None:
    cv2.namedWindow(WINDOW_CONTROLS, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_CONTROLS, 520, 760)
    cv2.createTrackbar("Camera", WINDOW_CONTROLS, initial_camera, max_camera, empty_callback)
    for name, (initial, maximum) in TRACKBARS.items():
        cv2.createTrackbar(name, WINDOW_CONTROLS, initial, maximum, empty_callback)


def get_trackbar(name: str) -> int:
    return cv2.getTrackbarPos(name, WINDOW_CONTROLS)


def set_trackbar(name: str, value: int) -> None:
    cv2.setTrackbarPos(name, WINDOW_CONTROLS, int(value))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def slider_to_signed(value: int) -> float:
    return float(value - 50)


def slider_to_percent(value: int) -> float:
    return float(value)


def slider_to_wb_temp(value: int) -> float:
    return float(2000 + value * 80)


def auto_exposure_value(enabled: bool) -> float:
    # V4L2 commonly uses 1=manual and 3=aperture priority auto.
    if platform.system() == "Linux":
        return 3.0 if enabled else 1.0
    # DirectShow often uses 0.75=auto and 0.25=manual.
    return 0.75 if enabled else 0.25


def open_camera(index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    backend = cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def set_prop(cap: cv2.VideoCapture, prop: int, value: float) -> bool:
    if not cap.isOpened():
        return False
    ok = cap.set(prop, value)
    time.sleep(0.01)
    actual = cap.get(prop)
    if np.isnan(actual):
        return False
    return bool(ok)


def apply_camera_controls(cap: cv2.VideoCapture, last_values: dict[str, int]) -> None:
    values = {
        name: get_trackbar(name)
        for name in (
            "Auto exposure",
            "Exposure",
            "Auto WB",
            "WB temp",
            "Gain",
            "Brightness",
            "Contrast",
            "Saturation",
        )
    }
    if values == last_values:
        return

    changed = {key for key, value in values.items() if last_values.get(key) != value}
    if "Auto exposure" in changed:
        set_prop(cap, cv2.CAP_PROP_AUTO_EXPOSURE, auto_exposure_value(bool(values["Auto exposure"])))
    if "Exposure" in changed or "Auto exposure" in changed:
        set_prop(cap, cv2.CAP_PROP_EXPOSURE, slider_to_signed(values["Exposure"]))
    if "Auto WB" in changed:
        set_prop(cap, cv2.CAP_PROP_AUTO_WB, float(values["Auto WB"]))
    if "WB temp" in changed or "Auto WB" in changed:
        set_prop(cap, cv2.CAP_PROP_WB_TEMPERATURE, slider_to_wb_temp(values["WB temp"]))
    for name in ("Gain", "Brightness", "Contrast", "Saturation"):
        if name in changed:
            set_prop(cap, CAMERA_PROPS[name], slider_to_percent(values[name]))

    last_values.clear()
    last_values.update(values)


def read_camera_state(cap: cv2.VideoCapture) -> dict[str, float]:
    state: dict[str, float] = {
        "width": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
        "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "auto_exposure": cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
    }
    for name, prop in CAMERA_PROPS.items():
        state[name.lower().replace(" ", "_")] = cap.get(prop)
    return state


def collect_params(camera_index: int, cap: cv2.VideoCapture) -> dict[str, Any]:
    h_min = get_trackbar("H min")
    h_max = get_trackbar("H max")
    s_min = get_trackbar("S min")
    s_max = get_trackbar("S max")
    v_min = get_trackbar("V min")
    v_max = get_trackbar("V max")
    return {
        "camera_index": camera_index,
        "hsv": {
            "lower": [h_min, s_min, v_min],
            "upper": [h_max, s_max, v_max],
        },
        "ui_controls": {
            "auto_exposure": bool(get_trackbar("Auto exposure")),
            "exposure_slider": get_trackbar("Exposure"),
            "auto_white_balance": bool(get_trackbar("Auto WB")),
            "white_balance_temp_slider": get_trackbar("WB temp"),
            "gain_slider": get_trackbar("Gain"),
            "brightness_slider": get_trackbar("Brightness"),
            "contrast_slider": get_trackbar("Contrast"),
            "saturation_slider": get_trackbar("Saturation"),
        },
        "camera_readback": read_camera_state(cap),
    }


def save_params(path: Path, params: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(params, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[saved] {path.resolve()}")
    print(json.dumps(params["hsv"], ensure_ascii=False))


def draw_overlay(frame: np.ndarray, camera_index: int, output: Path) -> np.ndarray:
    overlay = frame.copy()
    lines = [
        f"Camera: {camera_index}",
        "q/ESC quit | s save | p print | r reset HSV",
        f"Output: {output}",
    ]
    y = 28
    for line in lines:
        cv2.putText(overlay, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 0, 0), 4)
        cv2.putText(overlay, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 1)
        y += 28
    return overlay


def reset_hsv() -> None:
    defaults = {
        "H min": 0,
        "H max": 179,
        "S min": 0,
        "S max": 255,
        "V min": 0,
        "V max": 255,
    }
    for name, value in defaults.items():
        set_trackbar(name, value)


def main() -> int:
    args = parse_args()
    create_trackbars(args.camera, args.max_camera)
    cv2.namedWindow(WINDOW_PREVIEW, cv2.WINDOW_NORMAL)
    cv2.namedWindow(WINDOW_MASK, cv2.WINDOW_NORMAL)
    cv2.namedWindow(WINDOW_RESULT, cv2.WINDOW_NORMAL)

    camera_index = args.camera
    cap = open_camera(camera_index, args.width, args.height, args.fps)
    last_control_values: dict[str, int] = {}

    print("Keys: q/ESC quit, s save JSON, p print JSON, r reset HSV.")
    print("Tip: switch the Camera trackbar to reopen another camera index.")

    try:
        while True:
            requested_camera = get_trackbar("Camera")
            if requested_camera != camera_index:
                cap.release()
                camera_index = requested_camera
                cap = open_camera(camera_index, args.width, args.height, args.fps)
                last_control_values.clear()
                print(f"[camera] switched to index {camera_index}, opened={cap.isOpened()}")

            if not cap.isOpened():
                blank = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(
                    blank,
                    f"Camera {camera_index} unavailable",
                    (40, 180),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 255),
                    2,
                )
                cv2.imshow(WINDOW_PREVIEW, blank)
                key = cv2.waitKey(100) & 0xFF
            else:
                apply_camera_controls(cap, last_control_values)
                ok, frame = cap.read()
                if not ok:
                    print(f"[warn] failed to read from camera {camera_index}")
                    key = cv2.waitKey(30) & 0xFF
                    continue

                h_min = get_trackbar("H min")
                h_max = get_trackbar("H max")
                s_min = get_trackbar("S min")
                s_max = get_trackbar("S max")
                v_min = get_trackbar("V min")
                v_max = get_trackbar("V max")
                lower = np.array([min(h_min, h_max), min(s_min, s_max), min(v_min, v_max)])
                upper = np.array([max(h_min, h_max), max(s_min, s_max), max(v_min, v_max)])

                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                mask = cv2.inRange(hsv, lower, upper)
                result = cv2.bitwise_and(frame, frame, mask=mask)

                cv2.imshow(WINDOW_PREVIEW, draw_overlay(frame, camera_index, args.output))
                cv2.imshow(WINDOW_MASK, mask)
                cv2.imshow(WINDOW_RESULT, result)
                key = cv2.waitKey(1) & 0xFF

            if key in (27, ord("q")):
                break
            if key == ord("s") and cap.isOpened():
                save_params(args.output, collect_params(camera_index, cap))
            if key == ord("p") and cap.isOpened():
                print(json.dumps(collect_params(camera_index, cap), indent=2, ensure_ascii=False))
            if key == ord("r"):
                reset_hsv()
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

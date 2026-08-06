"""Dedicated latest-frame V4L2 camera capture."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import CameraConfig


@dataclass(frozen=True)
class FrameSample:
    sequence: int
    timestamp: float
    frame: np.ndarray


class LatestFrameCamera:
    """Continuously drain the camera and expose only the newest frame."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.capture: cv2.VideoCapture | None = None
        self.latest: FrameSample | None = None
        self.sequence = 0
        self.read_failures = 0
        self.started_at = 0.0
        self.resolved_device: str | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.started_at = time.monotonic()
        self.thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        capture = self.capture
        if capture is not None:
            capture.release()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None

    def wait_for_new(
        self, after_sequence: int, timeout: float = 0.2
    ) -> FrameSample | None:
        deadline = time.monotonic() + timeout
        with self.condition:
            while (
                not self.stop_event.is_set()
                and (
                    self.latest is None
                    or self.latest.sequence <= after_sequence
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return self.latest

    def stats(self) -> tuple[int, float, int]:
        elapsed = max(1e-6, time.monotonic() - self.started_at)
        return self.sequence, self.sequence / elapsed, self.read_failures

    def _capture_loop(self) -> None:
        while not self.stop_event.is_set():
            capture = self._open()
            if capture is None:
                self.read_failures += 1
                self.stop_event.wait(self.config.reconnect_delay_sec)
                continue
            self.capture = capture
            print(
                "Camera opened: "
                f"{self.resolved_device}, "
                f"{int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                f"{int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
                f"{capture.get(cv2.CAP_PROP_FPS):g} FPS"
            )
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                timestamp = time.monotonic()
                if not ok or frame is None:
                    self.read_failures += 1
                    break
                with self.condition:
                    self.sequence += 1
                    self.latest = FrameSample(self.sequence, timestamp, frame)
                    self.condition.notify_all()
            capture.release()
            self.capture = None
            if not self.stop_event.is_set():
                self.stop_event.wait(self.config.reconnect_delay_sec)

    def _open(self) -> cv2.VideoCapture | None:
        try:
            self.resolved_device = resolve_camera_device(self.config.device)
        except FileNotFoundError as exc:
            print(f"Camera discovery failed: {exc}")
            return None
        capture = cv2.VideoCapture(self.resolved_device, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.fourcc))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        capture.set(cv2.CAP_PROP_FPS, self.config.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.config.buffer_size)
        actual_width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = capture.get(cv2.CAP_PROP_FPS)
        if (
            actual_width != self.config.width
            or actual_height != self.config.height
            or abs(actual_fps - self.config.fps) > 0.5
        ):
            print(
                "WARNING: camera did not accept requested mode: "
                f"requested={self.config.width}x{self.config.height}"
                f"@{self.config.fps:g}, "
                f"actual={actual_width}x{actual_height}@{actual_fps:g}"
            )
        return capture


def resolve_camera_device(configured_device: str) -> str:
    """Resolve /dev path directly or discover a capture node by V4L2 name."""
    prefix = "auto:"
    if not configured_device.startswith(prefix):
        path = Path(configured_device)
        if not path.exists():
            raise FileNotFoundError(configured_device)
        return str(path)

    requested_name = configured_device[len(prefix) :].strip().casefold()
    if not requested_name:
        raise ValueError("automatic camera name cannot be empty")
    sysfs_root = Path("/sys/class/video4linux")
    candidates: list[Path] = []
    for entry in sorted(sysfs_root.glob("video*")):
        name_file = entry / "name"
        try:
            device_name = name_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if requested_name in device_name.casefold():
            candidates.append(Path("/dev") / entry.name)
    for candidate in candidates:
        capture = cv2.VideoCapture(str(candidate), cv2.CAP_V4L2)
        usable = capture.isOpened() and capture.get(cv2.CAP_PROP_FRAME_WIDTH) > 0
        capture.release()
        if usable:
            return str(candidate)
    names = ", ".join(str(path) for path in candidates) or "none"
    raise FileNotFoundError(
        f"no capture node matching {configured_device!r}; candidates: {names}"
    )

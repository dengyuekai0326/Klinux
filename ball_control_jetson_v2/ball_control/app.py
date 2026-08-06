"""Standalone latest-frame YOLO + tracking + serial control application."""

from __future__ import annotations

import argparse
import signal
import threading
import time
from dataclasses import replace
from pathlib import Path

import cv2

from .calibration import PipeCalibration
from .camera import LatestFrameCamera
from .config import AppConfig, load_config
from .detector import BallDetector, Detection, draw_debug
from .pipeline import VisionPipeline
from .recording import AsyncVideoRecorder
from .serial_link import SerialWorker
from .tracking import MotionState, MotionTracker


WINDOW_NAME = "Standalone Ball Control"


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "config" / "system.yaml",
    )
    parser.add_argument("--model", type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-serial", action="store_true")
    return parser.parse_args()


def resolve_model(config: AppConfig, override: Path | None) -> Path:
    if override is not None:
        path = override.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"model not found: {path}")
        return path
    preferred = config.resolve(config.model.path)
    if preferred.is_file():
        return preferred
    fallback = config.resolve(config.model.fallback_path)
    if fallback.is_file():
        print(
            f"WARNING: {preferred.name} not found; using {fallback.name}. "
            "TensorRT engine is required for final 30 FPS operation."
        )
        return fallback
    raise FileNotFoundError(
        f"neither model exists: {preferred}, {fallback}"
    )


def status_lines(
    motion: MotionState | None,
    detection: Detection | None,
    calibration: PipeCalibration,
    recorder: AsyncVideoRecorder,
    display_age_sec: float,
) -> list[str]:
    if motion is None:
        position_line = "ball: LOST"
    else:
        position_line = (
            f"x={motion.x:+.1f} "
            f"cm={calibration.control_to_cm(motion.x):+.2f} "
            f"v={motion.velocity:+.1f}/s "
            f"age={motion.measurement_age * 1000:.0f}ms"
        )
    confidence_line = (
        f"conf={detection.confidence:.2f}"
        if detection is not None
        else "conf=--"
    )
    recording = recorder.stats()
    if recording.active:
        recording_line = (
            f"REC ON frames={recording.frames_written} "
            f"drop={recording.frames_dropped}"
        )
    elif recording.requested:
        recording_line = "REC STARTING"
    else:
        recording_line = "REC OFF"
    return [
        position_line,
        confidence_line,
        recording_line,
        f"display_age={display_age_sec * 1000:.0f}ms",
        "Q/Esc: quit",
    ]


def run(config: AppConfig, model_path: Path) -> int:
    cv2.setNumThreads(1)
    cv2.setUseOptimized(True)
    calibration = PipeCalibration(config.calibration)
    tracker = MotionTracker(config.tracking)
    camera = LatestFrameCamera(config.camera)
    detector = BallDetector(config.model, calibration, model_path)
    recorder = AsyncVideoRecorder(
        config.recording,
        config.resolve(config.recording.output_dir),
        config.camera.width,
        config.camera.height,
    )
    serial_worker = SerialWorker(
        config.serial,
        tracker,
        recording_callback=recorder.request,
    )
    pipeline = VisionPipeline(
        config,
        calibration,
        tracker,
        camera,
        detector,
        recorder,
        serial_worker,
    )
    stop_event = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    last_debug_sequence = 0
    next_debug_at = time.monotonic()

    try:
        detector.warmup(config.camera.width, config.camera.height)
        recorder.start()
        serial_worker.start()
        camera.start()
        pipeline.start()
        if config.debug.enabled:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

        while not stop_event.is_set():
            pipeline.raise_if_failed()
            if not config.debug.enabled:
                stop_event.wait(0.10)
                continue

            snapshot = pipeline.wait_for_debug(
                last_debug_sequence,
                timeout=0.05,
            )
            now = time.monotonic()
            if snapshot is not None:
                last_debug_sequence = snapshot.sequence
            if snapshot is not None and now >= next_debug_at:
                display_age = now - snapshot.captured_at
                if display_age <= config.debug.maximum_display_age_sec:
                    output = draw_debug(
                        snapshot.frame,
                        snapshot.detection,
                        calibration,
                        (
                            snapshot.motion.x
                            if snapshot.motion is not None
                            else None
                        ),
                        status_lines(
                            snapshot.motion,
                            snapshot.detection,
                            calibration,
                            recorder,
                            display_age,
                        ),
                        config.model.crop_top_ratio,
                        config.model.crop_bottom_ratio,
                    )
                    cv2.imshow(WINDOW_NAME, output)
                next_debug_at = now + 1.0 / config.debug.display_rate_hz

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                stop_event.set()
    finally:
        pipeline.stop()
        serial_worker.stop()
        camera.stop()
        recorder.stop()
        cv2.destroyAllWindows()
    return 0


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.headless:
        config = replace(config, debug=replace(config.debug, enabled=False))
    if args.no_serial:
        config = replace(config, serial=replace(config.serial, enabled=False))
    model_path = resolve_model(config, args.model)
    return run(config, model_path)

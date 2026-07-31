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
from .modes import ModeController
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
    modes: ModeController,
) -> list[str]:
    state, _ = modes.snapshot()
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
    mode_line = (
        f"mode={state.mode} step={state.step + 1} "
        f"target={state.target_cm:+.1f}cm status={state.status_code}"
    )
    return [position_line, confidence_line, mode_line, "Q/Esc: quit"]


def log_performance(
    camera: LatestFrameCamera,
    detector: BallDetector,
    tracker: MotionTracker,
    serial_worker: SerialWorker,
    processed: int,
    dropped: int,
    stale_dropped: int,
    pipeline_latencies_ms: list[float],
    started_at: float,
) -> None:
    _, camera_fps, camera_failures = camera.stats()
    frames, detections, mean_ms, _, p95_ms = detector.stats()
    accepted, rejected, missed = tracker.counters()
    serial_stats = serial_worker.stats()
    elapsed = max(1e-6, time.monotonic() - started_at)
    processed_fps = processed / elapsed
    detection_rate = detections / frames * 100.0 if frames else 0.0
    ordered_pipeline = sorted(pipeline_latencies_ms)
    pipeline_p95_ms = (
        ordered_pipeline[round((len(ordered_pipeline) - 1) * 0.95)]
        if ordered_pipeline
        else 0.0
    )
    print(
        "PERF "
        f"camera={camera_fps:.1f}fps "
        f"inference_loop={processed_fps:.1f}fps "
        f"latency_mean={mean_ms:.1f}ms "
        f"latency_p95={p95_ms:.1f}ms "
        f"pipeline_p95={pipeline_p95_ms:.1f}ms "
        f"detected={detection_rate:.1f}% "
        f"accepted/rejected/missed={accepted}/{rejected}/{missed} "
        f"dropped={dropped} stale_dropped={stale_dropped} "
        f"camera_failures={camera_failures} "
        f"tx={serial_stats.ball_frames} "
        f"tx_jitter_max={serial_stats.maximum_jitter_ms:.2f}ms"
    )


def run(config: AppConfig, model_path: Path) -> int:
    cv2.setNumThreads(1)
    cv2.setUseOptimized(True)
    calibration = PipeCalibration(config.calibration)
    tracker = MotionTracker(config.tracking)
    modes = ModeController(config.modes, config.calibration.half_length_cm)
    camera = LatestFrameCamera(config.camera)
    detector = BallDetector(config.model, calibration, model_path)
    serial_worker = SerialWorker(
        config.serial, calibration, tracker, modes
    )
    stop_event = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    detector.warmup(config.camera.width, config.camera.height)
    serial_worker.start()
    camera.start()
    started_at = time.monotonic()
    last_sequence = 0
    processed = 0
    dropped = 0
    stale_dropped = 0
    pipeline_latencies_ms: list[float] = []
    next_debug_at = started_at
    next_log_at = started_at + config.debug.performance_log_period_sec

    try:
        while not stop_event.is_set():
            sample = camera.wait_for_new(last_sequence, timeout=0.25)
            if sample is None:
                continue
            dropped += max(0, sample.sequence - last_sequence - 1)
            last_sequence = sample.sequence
            frame_age = time.monotonic() - sample.timestamp
            if frame_age > config.camera.maximum_frame_age_sec:
                stale_dropped += 1
                continue
            detection = detector.detect(sample.frame)
            if detection is None:
                tracker.mark_missed()
            else:
                x_axis = calibration.pixel_to_control(
                    detection.center_x, sample.frame.shape[1]
                )
                if not tracker.observe(sample.timestamp, x_axis):
                    tracker.mark_missed()
            processed += 1
            now = time.monotonic()
            pipeline_latencies_ms.append(
                (now - sample.timestamp) * 1000.0
            )
            if len(pipeline_latencies_ms) > 600:
                del pipeline_latencies_ms[:300]
            motion = tracker.snapshot(
                now, config.serial.prediction_horizon_sec
            )

            if config.debug.enabled and now >= next_debug_at:
                output = draw_debug(
                    sample.frame,
                    detection,
                    calibration,
                    motion.x if motion is not None else None,
                    status_lines(
                        motion, detection, calibration, modes
                    ),
                )
                cv2.imshow(WINDOW_NAME, output)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    stop_event.set()
                next_debug_at = now + 1.0 / config.debug.display_rate_hz

            if now >= next_log_at:
                log_performance(
                    camera,
                    detector,
                    tracker,
                    serial_worker,
                    processed,
                    dropped,
                    stale_dropped,
                    pipeline_latencies_ms,
                    started_at,
                )
                next_log_at = now + config.debug.performance_log_period_sec
    finally:
        camera.stop()
        serial_worker.stop()
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

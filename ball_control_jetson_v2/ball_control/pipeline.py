"""Real-time vision pipeline isolated from the potentially slow GUI thread."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from .calibration import PipeCalibration
from .camera import LatestFrameCamera
from .config import AppConfig
from .detector import BallDetector, Detection
from .recording import AsyncVideoRecorder
from .serial_link import SerialWorker
from .tracking import MotionState, MotionTracker


@dataclass(frozen=True)
class DebugSnapshot:
    sequence: int
    captured_at: float
    completed_at: float
    frame: np.ndarray
    detection: Detection | None
    motion: MotionState | None


class VisionPipeline:
    """Process only fresh camera frames and publish only the newest GUI snapshot."""

    def __init__(
        self,
        config: AppConfig,
        calibration: PipeCalibration,
        tracker: MotionTracker,
        camera: LatestFrameCamera,
        detector: BallDetector,
        recorder: AsyncVideoRecorder,
        serial_worker: SerialWorker,
    ) -> None:
        self.config = config
        self.calibration = calibration
        self.tracker = tracker
        self.camera = camera
        self.detector = detector
        self.recorder = recorder
        self.serial_worker = serial_worker
        self.stop_event = threading.Event()
        self.condition = threading.Condition()
        self.thread: threading.Thread | None = None
        self.latest_debug: DebugSnapshot | None = None
        self.error: BaseException | None = None
        self.processed = 0
        self.dropped = 0
        self.stale_dropped = 0
        self.pipeline_latencies_ms: list[float] = []
        self.started_at = 0.0

    def start(self) -> None:
        if self.thread is not None:
            return
        self.started_at = time.monotonic()
        self.thread = threading.Thread(
            target=self._run_guarded,
            name="vision-pipeline",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=3.0)
            self.thread = None

    def wait_for_debug(
        self,
        after_sequence: int,
        timeout: float,
    ) -> DebugSnapshot | None:
        deadline = time.monotonic() + timeout
        with self.condition:
            while (
                not self.stop_event.is_set()
                and self.error is None
                and (
                    self.latest_debug is None
                    or self.latest_debug.sequence <= after_sequence
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return self.latest_debug

    def raise_if_failed(self) -> None:
        if self.error is not None:
            raise RuntimeError("vision pipeline stopped unexpectedly") from self.error

    def _run_guarded(self) -> None:
        try:
            self._run()
        except BaseException as exc:
            self.error = exc
            self.stop_event.set()
            with self.condition:
                self.condition.notify_all()

    def _run(self) -> None:
        last_sequence = 0
        next_log_at = self.started_at + self.config.debug.performance_log_period_sec
        while not self.stop_event.is_set():
            sample = self.camera.wait_for_new(last_sequence, timeout=0.20)
            if sample is None:
                continue
            self.dropped += max(0, sample.sequence - last_sequence - 1)
            last_sequence = sample.sequence
            frame_age = time.monotonic() - sample.timestamp
            if frame_age > self.config.camera.maximum_frame_age_sec:
                self.stale_dropped += 1
                continue

            self.recorder.submit(sample.frame)
            detection = self.detector.detect(sample.frame)
            if detection is None:
                self.tracker.mark_missed()
            else:
                x_axis = self.calibration.pixel_to_control(
                    detection.center_x,
                    sample.frame.shape[1],
                )
                if not self.tracker.observe(sample.timestamp, x_axis):
                    self.tracker.mark_missed()

            completed_at = time.monotonic()
            motion = self.tracker.snapshot(
                completed_at,
                self.config.serial.prediction_horizon_sec,
            )
            self.processed += 1
            self.pipeline_latencies_ms.append(
                (completed_at - sample.timestamp) * 1000.0
            )
            if len(self.pipeline_latencies_ms) > 600:
                del self.pipeline_latencies_ms[:300]

            snapshot = DebugSnapshot(
                sequence=sample.sequence,
                captured_at=sample.timestamp,
                completed_at=completed_at,
                frame=sample.frame,
                detection=detection,
                motion=motion,
            )
            with self.condition:
                self.latest_debug = snapshot
                self.condition.notify_all()

            if completed_at >= next_log_at:
                self._log_performance()
                next_log_at = (
                    completed_at
                    + self.config.debug.performance_log_period_sec
                )

    def _log_performance(self) -> None:
        _, camera_fps, camera_failures = self.camera.stats()
        frames, detections, mean_ms, _, p95_ms = self.detector.stats()
        accepted, rejected, missed = self.tracker.counters()
        serial_stats = self.serial_worker.stats()
        recording = self.recorder.stats()
        elapsed = max(1e-6, time.monotonic() - self.started_at)
        processed_fps = self.processed / elapsed
        detection_rate = detections / frames * 100.0 if frames else 0.0
        ordered_pipeline = sorted(self.pipeline_latencies_ms)
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
            f"dropped={self.dropped} stale_dropped={self.stale_dropped} "
            f"camera_failures={camera_failures} "
            f"tx={serial_stats.ball_frames} "
            f"tx_jitter_max={serial_stats.maximum_jitter_ms:.2f}ms "
            f"rec={'on' if recording.active else 'off'} "
            f"rec_frames={recording.frames_written} "
            f"rec_dropped={recording.frames_dropped}"
        )

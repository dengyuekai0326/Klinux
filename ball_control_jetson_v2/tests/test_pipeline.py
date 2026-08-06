import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ball_control.calibration import PipeCalibration
from ball_control.camera import FrameSample
from ball_control.config import load_config
from ball_control.detector import Detection
from ball_control.pipeline import VisionPipeline
from ball_control.tracking import MotionTracker


class FakeCamera:
    def __init__(self, sample):
        self.sample = sample

    def wait_for_new(self, after_sequence, timeout):
        if after_sequence < self.sample.sequence:
            return self.sample
        time.sleep(min(timeout, 0.01))
        return None

    def stats(self):
        return 1, 30.0, 0


class FakeDetector:
    def detect(self, _frame):
        return Detection(306.8, 170.0, 326.8, 190.0, 0.9)

    def stats(self):
        return 1, 1, 1.0, 1.0, 1.0


class FakeRecorder:
    def __init__(self):
        self.frames = []

    def submit(self, frame):
        self.frames.append(frame)

    def stats(self):
        return SimpleNamespace(
            active=False,
            frames_written=0,
            frames_dropped=0,
        )


class FakeSerial:
    def stats(self):
        return SimpleNamespace(ball_frames=0, maximum_jitter_ms=0.0)


def test_pipeline_publishes_latest_debug_snapshot():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "system.yaml")
    calibration = PipeCalibration(config.calibration)
    tracker = MotionTracker(config.tracking)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    sample = FrameSample(1, time.monotonic(), frame)
    camera = FakeCamera(sample)
    recorder = FakeRecorder()
    pipeline = VisionPipeline(
        config,
        calibration,
        tracker,
        camera,
        FakeDetector(),
        recorder,
        FakeSerial(),
    )

    pipeline.start()
    snapshot = pipeline.wait_for_debug(0, timeout=0.5)
    pipeline.stop()
    pipeline.raise_if_failed()

    assert snapshot is not None
    assert snapshot.sequence == 1
    assert snapshot.motion is not None
    assert abs(snapshot.motion.x) < 1.0
    assert len(recorder.frames) == 1
    assert recorder.frames[0] is frame

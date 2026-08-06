import unittest
from pathlib import Path

from ball_control.calibration import PipeCalibration
from ball_control.config import load_config
from ball_control.tracking import MotionTracker


ROOT = Path(__file__).resolve().parents[1]


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config" / "system.yaml")
        self.calibration = PipeCalibration(self.config.calibration)

    def test_control_coordinate_mapping(self):
        left, center, right = self.calibration.pixel_guides(1000)
        self.assertAlmostEqual(
            self.calibration.pixel_to_control(left, 1000), -320, places=4
        )
        self.assertAlmostEqual(
            self.calibration.pixel_to_control(center, 1000), 0, places=4
        )
        self.assertAlmostEqual(
            self.calibration.pixel_to_control(right, 1000), 320, places=4
        )
        self.assertAlmostEqual(self.calibration.control_to_cm(320), 12.5)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        config = load_config(ROOT / "config" / "system.yaml")
        self.tracker = MotionTracker(config.tracking)

    def test_tracks_motion_and_short_dropout(self):
        self.assertTrue(self.tracker.observe(1.0, 0.0))
        for index in range(1, 10):
            timestamp = 1.0 + index / 30.0
            self.assertTrue(self.tracker.observe(timestamp, index * 3.0))
        state = self.tracker.snapshot(1.32, 0.08)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertGreater(state.velocity, 0.0)
        predicted = self.tracker.snapshot(1.37, 0.08)
        self.assertIsNotNone(predicted)
        assert predicted is not None
        self.assertGreater(predicted.x, state.x)
        self.assertTrue(predicted.predicted)

    def test_stale_measurement_is_not_transmitted(self):
        self.tracker.observe(1.0, 0.0)
        self.assertIsNone(self.tracker.snapshot(1.2, 0.08))

if __name__ == "__main__":
    unittest.main()

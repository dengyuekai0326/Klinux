import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from ball_control.config import RecordingConfig
from ball_control.recording import AsyncVideoRecorder


class RecordingTests(unittest.TestCase):
    def test_serial_style_start_write_stop(self):
        config = RecordingConfig(
            enabled=True,
            output_dir="unused",
            filename_prefix="test",
            fourcc="MJPG",
            fps=10.0,
            queue_size=4,
        )
        with tempfile.TemporaryDirectory() as directory:
            recorder = AsyncVideoRecorder(
                config, Path(directory), width=64, height=32
            )
            recorder.start()
            try:
                recorder.request(True)
                self._wait_for(lambda: recorder.stats().active)
                frame = np.zeros((32, 64, 3), dtype=np.uint8)
                for _ in range(3):
                    recorder.submit(frame)
                recorder.request(False)
                self._wait_for(lambda: not recorder.stats().active)
                self.assertEqual(recorder.stats().frames_written, 3)
            finally:
                recorder.stop()
            videos = list(Path(directory).glob("test_*.avi"))
            self.assertEqual(len(videos), 1)
            self.assertGreater(videos[0].stat().st_size, 0)

    def _wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for recorder state")


if __name__ == "__main__":
    unittest.main()

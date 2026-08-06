"""Non-blocking, serial-controlled video recording."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .config import RecordingConfig


@dataclass(frozen=True)
class RecordingStats:
    requested: bool
    active: bool
    frames_written: int
    frames_dropped: int
    current_path: str | None


class AsyncVideoRecorder:
    """Write camera frames on a dedicated thread with a bounded queue."""

    def __init__(
        self,
        config: RecordingConfig,
        output_dir: Path,
        width: int,
        height: int,
    ) -> None:
        self.config = config
        self.output_dir = output_dir
        self.frame_size = (width, height)
        self.condition = threading.Condition()
        self.pending: deque[np.ndarray] = deque()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.writer: cv2.VideoWriter | None = None
        self.requested = False
        self.active = False
        self.frames_written = 0
        self.frames_dropped = 0
        self.current_path: Path | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(
            target=self._run,
            name="video-recorder",
            daemon=True,
        )
        self.thread.start()

    def request(self, enabled: bool) -> None:
        if enabled and not self.config.enabled:
            print("Recording command ignored: recording feature is disabled")
            return
        with self.condition:
            if self.requested == enabled:
                return
            self.requested = enabled
            self.condition.notify_all()

    def submit(self, frame: np.ndarray) -> None:
        """Queue an immutable camera frame without waiting for disk I/O."""
        with self.condition:
            if not self.requested:
                return
            if len(self.pending) >= self.config.queue_size:
                self.pending.popleft()
                self.frames_dropped += 1
            self.pending.append(frame)
            self.condition.notify()

    def stop(self) -> None:
        with self.condition:
            self.requested = False
            self.condition.notify_all()
            self.condition.wait_for(lambda: not self.active, timeout=2.0)
            self.stop_event.set()
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=3.0)
            self.thread = None

    def stats(self) -> RecordingStats:
        with self.condition:
            return RecordingStats(
                requested=self.requested,
                active=self.active,
                frames_written=self.frames_written,
                frames_dropped=self.frames_dropped,
                current_path=(
                    str(self.current_path)
                    if self.current_path is not None
                    else None
                ),
            )

    def _run(self) -> None:
        try:
            while not self.stop_event.is_set():
                action: str
                frame: np.ndarray | None = None
                with self.condition:
                    self.condition.wait_for(
                        lambda: (
                            self.stop_event.is_set()
                            or self.requested != self.active
                            or (self.active and bool(self.pending))
                        ),
                        timeout=0.25,
                    )
                    if self.stop_event.is_set():
                        break
                    if self.active and self.pending:
                        action = "write"
                        frame = self.pending.popleft()
                    elif self.requested and not self.active:
                        action = "open"
                    elif not self.requested and self.active:
                        action = "close"
                    else:
                        continue

                if action == "open":
                    self._open_writer()
                elif action == "close":
                    self._close_writer()
                elif frame is not None:
                    self._write_frame(frame)
        finally:
            self._close_writer()

    def _open_writer(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.output_dir / (
            f"{self.config.filename_prefix}_{timestamp}.avi"
        )
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*self.config.fourcc),
            self.config.fps,
            self.frame_size,
        )
        if not writer.isOpened():
            writer.release()
            with self.condition:
                self.requested = False
                self.pending.clear()
            print(f"Recording failed: cannot open {path}")
            return
        with self.condition:
            if self.stop_event.is_set() or not self.requested:
                writer.release()
                return
            self.writer = writer
            self.current_path = path
            self.active = True
        print(f"Recording started: {path}")

    def _close_writer(self) -> None:
        with self.condition:
            writer = self.writer
            path = self.current_path
            was_active = self.active
            self.writer = None
            self.active = False
            self.pending.clear()
        if writer is not None:
            writer.release()
        if was_active:
            print(f"Recording stopped: {path}")

    def _write_frame(self, frame: np.ndarray) -> None:
        writer = self.writer
        if writer is None:
            return
        if (frame.shape[1], frame.shape[0]) != self.frame_size:
            with self.condition:
                self.frames_dropped += 1
            return
        try:
            writer.write(frame)
        except cv2.error as exc:
            with self.condition:
                self.frames_dropped += 1
            print(f"Recording write error: {exc}")
            return
        with self.condition:
            self.frames_written += 1

"""Full-duplex serial worker with an absolute-deadline 30 Hz TX loop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial

from .config import SerialConfig
from .protocol import (
    RecordingFrameParser,
    build_ball_frame,
)
from .tracking import MotionTracker


@dataclass(frozen=True)
class SerialStats:
    ball_frames: int
    received_commands: int
    maximum_jitter_ms: float


class SerialWorker:
    def __init__(
        self,
        config: SerialConfig,
        tracker: MotionTracker,
        recording_callback: Callable[[bool], None] | None = None,
    ) -> None:
        self.config = config
        self.tracker = tracker
        self.recording_callback = recording_callback
        self.port: serial.Serial | None = None
        self.stop_event = threading.Event()
        self.write_lock = threading.Lock()
        self.reader: threading.Thread | None = None
        self.transmitter: threading.Thread | None = None
        self.parser = RecordingFrameParser()
        self.ball_frames = 0
        self.received_commands = 0
        self.maximum_jitter_ms = 0.0
        self.last_ball_tx: float | None = None

    def start(self) -> None:
        if not self.config.enabled:
            print("Serial disabled")
            return
        self.port = serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            timeout=self.config.timeout_sec,
            write_timeout=self.config.timeout_sec,
            exclusive=True,
        )
        print(f"Serial opened: {self.config.port} @ {self.config.baudrate}")
        self.reader = threading.Thread(
            target=self._read_loop,
            name="serial-rx",
            daemon=True,
        )
        self.transmitter = threading.Thread(
            target=self._transmit_loop,
            name="serial-tx",
            daemon=True,
        )
        self.reader.start()
        self.transmitter.start()

    def stop(self) -> None:
        self.stop_event.set()
        port = self.port
        if port is not None:
            try:
                port.cancel_read()
            except (AttributeError, OSError, serial.SerialException):
                pass
            port.close()
        for thread in (self.reader, self.transmitter):
            if thread is not None:
                thread.join(timeout=1.5)
        self.reader = None
        self.transmitter = None
        self.port = None

    def stats(self) -> SerialStats:
        return SerialStats(
            ball_frames=self.ball_frames,
            received_commands=self.received_commands,
            maximum_jitter_ms=self.maximum_jitter_ms,
        )

    def _read_loop(self) -> None:
        assert self.port is not None
        while not self.stop_event.is_set():
            try:
                available = self.port.in_waiting
                data = self.port.read(max(1, available))
            except (OSError, serial.SerialException) as exc:
                if not self.stop_event.is_set():
                    print(f"Serial RX error: {exc}")
                break
            if not data:
                continue
            if self.config.log_rx:
                print("RX:", data.hex(" "))
            for command in self.parser.feed(data):
                self.received_commands += 1
                if self.recording_callback is not None:
                    self.recording_callback(command.enabled)
                print(
                    "Recording command: "
                    f"{'START' if command.enabled else 'STOP'}"
                )

    def _transmit_loop(self) -> None:
        period = 1.0 / self.config.tx_rate_hz
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now < deadline:
                self.stop_event.wait(deadline - now)
                continue
            if now - deadline > period:
                deadline = now
            self._transmit_cycle(now, period)
            deadline += period

    def _transmit_cycle(self, timestamp: float, period: float) -> None:
        motion = self.tracker.snapshot(
            timestamp, self.config.prediction_horizon_sec
        )
        if self.config.send_ball_state and motion is not None:
            velocity_per_frame = motion.velocity / self.config.tx_rate_hz
            acceleration_per_frame2 = motion.acceleration / (
                self.config.tx_rate_hz * self.config.tx_rate_hz
            )
            frame = build_ball_frame(
                motion.x, velocity_per_frame, acceleration_per_frame2
            )
            if self._write(frame):
                self.ball_frames += 1
                if self.last_ball_tx is not None:
                    jitter = abs(
                        (timestamp - self.last_ball_tx) - period
                    ) * 1000.0
                    self.maximum_jitter_ms = max(
                        self.maximum_jitter_ms, jitter
                    )
                self.last_ball_tx = timestamp
                if self.config.log_tx:
                    print("TX ball:", frame.hex(" "))
        elif motion is None:
            # Do not count a deliberate stale-measurement pause as TX jitter.
            self.last_ball_tx = None

    def _write(self, frame: bytes) -> bool:
        port = self.port
        if port is None or not port.is_open:
            return False
        try:
            with self.write_lock:
                port.write(frame)
            return True
        except (OSError, serial.SerialException) as exc:
            if not self.stop_event.is_set():
                print(f"Serial TX error: {exc}")
            return False

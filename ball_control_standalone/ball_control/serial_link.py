"""Full-duplex serial worker with an absolute-deadline 30 Hz TX loop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import serial

from .calibration import PipeCalibration
from .config import SerialConfig
from .modes import ModeController, ModeState
from .protocol import (
    TaskFrameParser,
    build_ball_frame,
    build_task_state_frame,
)
from .tracking import MotionTracker


@dataclass(frozen=True)
class SerialStats:
    ball_frames: int
    task_frames: int
    received_commands: int
    maximum_jitter_ms: float


class SerialWorker:
    def __init__(
        self,
        config: SerialConfig,
        calibration: PipeCalibration,
        tracker: MotionTracker,
        modes: ModeController,
    ) -> None:
        self.config = config
        self.calibration = calibration
        self.tracker = tracker
        self.modes = modes
        self.port: serial.Serial | None = None
        self.stop_event = threading.Event()
        self.write_lock = threading.Lock()
        self.reader: threading.Thread | None = None
        self.transmitter: threading.Thread | None = None
        self.parser = TaskFrameParser()
        self.ball_frames = 0
        self.task_frames = 0
        self.received_commands = 0
        self.maximum_jitter_ms = 0.0
        self.last_ball_tx: float | None = None
        self.last_task_tx = 0.0
        self.last_task_signature: tuple[int, int, int, int] | None = None
        self.last_mode_event_serial = -1

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
            task_frames=self.task_frames,
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
            timestamp = time.monotonic()
            for command in self.parser.feed(data):
                self.received_commands += 1
                state = self.modes.start(command, timestamp)
                print(
                    f"Mode {state.mode} started: "
                    f"target={state.target_cm:.1f} cm"
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
        actual_cm = (
            self.calibration.control_to_cm(motion.x)
            if motion is not None
            else None
        )
        mode_state, mode_changed = self.modes.update(timestamp, actual_cm)
        if mode_changed:
            print(self._format_mode_event(mode_state))

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

        if self.config.send_task_state and mode_state.mode != 0:
            self._maybe_send_task_state(timestamp, mode_state)

    def _maybe_send_task_state(
        self, timestamp: float, state: ModeState
    ) -> None:
        target_x = self.calibration.cm_to_control(state.target_cm)
        signature = (
            state.mode,
            state.step,
            round(target_x),
            state.status_code,
        )
        _, event_serial = self.modes.snapshot()
        due = (
            signature != self.last_task_signature
            or event_serial != self.last_mode_event_serial
            or timestamp - self.last_task_tx
            >= self.config.task_state_keepalive_sec
        )
        if not due:
            return
        frame = build_task_state_frame(*signature)
        if self._write(frame):
            self.task_frames += 1
            self.last_task_signature = signature
            self.last_mode_event_serial = event_serial
            self.last_task_tx = timestamp
            if self.config.log_tx:
                print("TX task:", frame.hex(" "))

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

    @staticmethod
    def _format_mode_event(state: ModeState) -> str:
        if state.timed_out:
            return f"Mode {state.mode} timed out"
        if state.completed:
            return f"Mode {state.mode} completed"
        return (
            f"Mode {state.mode} step {state.step + 1}: "
            f"target={state.target_cm:.1f} cm"
        )

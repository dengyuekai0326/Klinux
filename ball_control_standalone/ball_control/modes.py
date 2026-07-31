"""Thread-safe implementation of the three competition modes."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .config import ModesConfig
from .protocol import TaskCommand


@dataclass(frozen=True)
class ModeState:
    mode: int
    step: int
    target_cm: float
    actual_cm: float | None
    in_tolerance: bool
    held_sec: float
    completed: bool
    timed_out: bool
    detected: bool

    @property
    def status_code(self) -> int:
        if self.timed_out:
            return 2
        if self.completed:
            return 1
        if not self.detected:
            return 3
        return 0


class ModeController:
    def __init__(self, config: ModesConfig, half_length_cm: float) -> None:
        self.config = config
        self.half_length_cm = half_length_cm
        self.lock = threading.Lock()
        self.mode = 0
        self.step = 0
        self.target_cm = 0.0
        self.started_at = 0.0
        self.tolerance_entered_at: float | None = None
        self.completed = False
        self.timed_out = False
        self.last_state = ModeState(
            mode=0,
            step=0,
            target_cm=0.0,
            actual_cm=None,
            in_tolerance=False,
            held_sec=0.0,
            completed=False,
            timed_out=False,
            detected=False,
        )
        self.event_serial = 0

    def start(self, command: TaskCommand, timestamp: float) -> ModeState:
        with self.lock:
            self.mode = command.mode
            self.step = 0
            self.started_at = timestamp
            self.tolerance_entered_at = None
            self.completed = False
            self.timed_out = False
            if command.mode == 1:
                self.target_cm = self.config.mode1_target_cm
            elif command.mode == 2:
                self.target_cm = self.config.mode2_targets_cm[0]
            else:
                self.target_cm = max(
                    -self.half_length_cm,
                    min(self.half_length_cm, command.target_cm),
                )
            self.event_serial += 1
            self.last_state = self._make_state(None, False, timestamp)
            return self.last_state

    def update(
        self, timestamp: float, actual_cm: float | None
    ) -> tuple[ModeState, bool]:
        with self.lock:
            changed = False
            detected = actual_cm is not None
            if self.mode == 0:
                self.last_state = self._make_state(actual_cm, detected, timestamp)
                return self.last_state, changed

            if (
                self.mode == 2
                and not self.completed
                and timestamp - self.started_at > self.config.mode2_timeout_sec
            ):
                if not self.timed_out:
                    changed = True
                    self.event_serial += 1
                self.timed_out = True

            if not detected or self.completed or self.timed_out:
                self.tolerance_entered_at = None
                self.last_state = self._make_state(actual_cm, detected, timestamp)
                return self.last_state, changed

            error = actual_cm - self.target_cm
            if abs(error) <= self._tolerance():
                if self.tolerance_entered_at is None:
                    self.tolerance_entered_at = timestamp
                if timestamp - self.tolerance_entered_at >= self._hold_time():
                    changed = True
                    self.event_serial += 1
                    self._complete_target()
            else:
                self.tolerance_entered_at = None

            self.last_state = self._make_state(actual_cm, detected, timestamp)
            return self.last_state, changed

    def snapshot(self) -> tuple[ModeState, int]:
        with self.lock:
            return self.last_state, self.event_serial

    def _complete_target(self) -> None:
        self.tolerance_entered_at = None
        if self.mode == 2 and self.step < 2:
            self.step += 1
            self.target_cm = self.config.mode2_targets_cm[self.step]
        else:
            self.completed = True

    def _tolerance(self) -> float:
        if self.mode == 1:
            return self.config.mode1_tolerance_cm
        if self.mode == 2:
            return self.config.mode2_tolerance_cm
        return self.config.mode3_tolerance_cm

    def _hold_time(self) -> float:
        if self.mode == 1:
            return self.config.mode1_hold_sec
        if self.mode == 2:
            return self.config.mode2_hold_sec[self.step]
        return self.config.mode3_hold_sec

    def _make_state(
        self, actual_cm: float | None, detected: bool, timestamp: float
    ) -> ModeState:
        in_tolerance = (
            detected
            and actual_cm is not None
            and abs(actual_cm - self.target_cm) <= self._tolerance()
            if self.mode != 0
            else False
        )
        held_sec = (
            max(0.0, timestamp - self.tolerance_entered_at)
            if in_tolerance and self.tolerance_entered_at is not None
            else 0.0
        )
        return ModeState(
            mode=self.mode,
            step=self.step,
            target_cm=self.target_cm,
            actual_cm=actual_cm,
            in_tolerance=in_tolerance,
            held_sec=held_sec,
            completed=self.completed,
            timed_out=self.timed_out,
            detected=detected,
        )

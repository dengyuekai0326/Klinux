"""Low-latency alpha-beta tracking with bounded short-dropout prediction."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .config import TrackingConfig


@dataclass(frozen=True)
class MotionState:
    x: float
    velocity: float
    acceleration: float
    measurement_age: float
    predicted: bool


class MotionTracker:
    def __init__(self, config: TrackingConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.initialized = False
        self.x = 0.0
        self.velocity = 0.0
        self.acceleration = 0.0
        self.state_time = 0.0
        self.last_measurement_time = 0.0
        self.accepted = 0
        self.rejected = 0
        self.missed = 0

    def observe(self, timestamp: float, measurement: float) -> bool:
        with self.lock:
            if not self.initialized:
                self._initialize(timestamp, measurement)
                self.accepted += 1
                return True

            dt = timestamp - self.state_time
            if dt <= 1e-4:
                self.rejected += 1
                return False
            dt = min(dt, self.config.measurement_timeout_sec)
            predicted_x = self.x + self.velocity * dt
            residual = measurement - predicted_x
            gate = (
                self.config.reacquire_gate_units
                + self.config.maximum_speed_units_per_sec * dt
            )
            measurement_gap = timestamp - self.last_measurement_time
            if (
                abs(residual) > gate
                and measurement_gap <= self.config.maximum_prediction_sec
            ):
                self.rejected += 1
                return False

            old_velocity = self.velocity
            if measurement_gap > self.config.measurement_timeout_sec:
                self._initialize(timestamp, measurement)
            else:
                self.x = predicted_x + self.config.alpha * residual
                self.velocity += self.config.beta * residual / dt
                self.velocity = max(
                    -self.config.maximum_speed_units_per_sec,
                    min(self.config.maximum_speed_units_per_sec, self.velocity),
                )
                if (
                    abs(self.velocity)
                    < self.config.velocity_deadband_units_per_sec
                    and abs(residual) < 2.0
                ):
                    self.velocity = 0.0
                raw_acceleration = (self.velocity - old_velocity) / dt
                alpha = self.config.acceleration_alpha
                self.acceleration = (
                    alpha * raw_acceleration + (1.0 - alpha) * self.acceleration
                )
                self.state_time = timestamp
                self.last_measurement_time = timestamp
            self.accepted += 1
            return True

    def mark_missed(self) -> None:
        with self.lock:
            self.missed += 1

    def snapshot(
        self, timestamp: float, prediction_horizon_sec: float
    ) -> MotionState | None:
        with self.lock:
            if not self.initialized:
                return None
            measurement_age = max(0.0, timestamp - self.last_measurement_time)
            if measurement_age > self.config.measurement_timeout_sec:
                return None
            prediction_age = min(
                measurement_age,
                self.config.maximum_prediction_sec,
                max(0.0, prediction_horizon_sec),
            )
            predicted_x = self.x + self.velocity * prediction_age
            return MotionState(
                x=max(-320.0, min(320.0, predicted_x)),
                velocity=self.velocity,
                acceleration=self.acceleration,
                measurement_age=measurement_age,
                predicted=measurement_age > 0.001,
            )

    def counters(self) -> tuple[int, int, int]:
        with self.lock:
            return self.accepted, self.rejected, self.missed

    def _initialize(self, timestamp: float, measurement: float) -> None:
        self.initialized = True
        self.x = max(-320.0, min(320.0, measurement))
        self.velocity = 0.0
        self.acceleration = 0.0
        self.state_time = timestamp
        self.last_measurement_time = timestamp

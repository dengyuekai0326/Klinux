"""Resolution-independent mapping between camera, control, and physical coordinates."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CalibrationConfig


@dataclass(frozen=True)
class PipeCalibration:
    config: CalibrationConfig

    def accepts_detection(
        self, center_x: float, center_y: float, width: int, height: int
    ) -> bool:
        x_ratio = center_x / width
        y_ratio = center_y / height
        margin = self.config.detection_x_margin_ratio
        return (
            self.config.left_x_ratio - margin
            <= x_ratio
            <= self.config.right_x_ratio + margin
            and self.config.detection_y_min_ratio
            <= y_ratio
            <= self.config.detection_y_max_ratio
        )

    def pixel_to_control(self, center_x: float, width: int) -> float:
        x_ratio = center_x / width
        if x_ratio <= self.config.center_x_ratio:
            span = self.config.center_x_ratio - self.config.left_x_ratio
        else:
            span = self.config.right_x_ratio - self.config.center_x_ratio
        value = (x_ratio - self.config.center_x_ratio) / span * 320.0
        return max(-320.0, min(320.0, value))

    def control_to_pixel(self, x_axis: float, width: int) -> float:
        normalized = max(-320.0, min(320.0, x_axis)) / 320.0
        if normalized <= 0:
            span = self.config.center_x_ratio - self.config.left_x_ratio
        else:
            span = self.config.right_x_ratio - self.config.center_x_ratio
        return (self.config.center_x_ratio + normalized * span) * width

    def control_to_cm(self, x_axis: float) -> float:
        value = x_axis / 320.0 * self.config.half_length_cm
        return max(
            -self.config.half_length_cm,
            min(self.config.half_length_cm, value),
        )

    def cm_to_control(self, position_cm: float) -> float:
        value = position_cm / self.config.half_length_cm * 320.0
        return max(-320.0, min(320.0, value))

    def pixel_guides(self, width: int) -> tuple[int, int, int]:
        return (
            round(self.config.left_x_ratio * width),
            round(self.config.center_x_ratio * width),
            round(self.config.right_x_ratio * width),
        )

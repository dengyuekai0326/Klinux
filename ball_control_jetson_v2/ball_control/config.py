"""Typed configuration loader for the standalone controller."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CameraConfig:
    device: str
    width: int
    height: int
    fps: float
    fourcc: str
    buffer_size: int
    reconnect_delay_sec: float
    maximum_frame_age_sec: float


@dataclass(frozen=True)
class ModelConfig:
    path: str
    fallback_path: str
    imgsz: tuple[int, int]
    crop_top_ratio: float
    crop_bottom_ratio: float
    confidence: float
    iou: float
    max_detections: int
    device: int
    half: bool


@dataclass(frozen=True)
class CalibrationConfig:
    left_x_ratio: float
    center_x_ratio: float
    right_x_ratio: float
    half_length_cm: float
    detection_x_margin_ratio: float
    detection_y_min_ratio: float
    detection_y_max_ratio: float


@dataclass(frozen=True)
class TrackingConfig:
    alpha: float
    beta: float
    acceleration_alpha: float
    velocity_deadband_units_per_sec: float
    maximum_speed_units_per_sec: float
    reacquire_gate_units: float
    maximum_prediction_sec: float
    measurement_timeout_sec: float


@dataclass(frozen=True)
class SerialConfig:
    enabled: bool
    port: str
    baudrate: int
    timeout_sec: float
    tx_rate_hz: float
    prediction_horizon_sec: float
    send_ball_state: bool
    log_tx: bool
    log_rx: bool


@dataclass(frozen=True)
class RecordingConfig:
    enabled: bool
    output_dir: str
    filename_prefix: str
    fourcc: str
    fps: float
    queue_size: int


@dataclass(frozen=True)
class DebugConfig:
    enabled: bool
    display_rate_hz: float
    maximum_display_age_sec: float
    performance_log_period_sec: float


@dataclass(frozen=True)
class AppConfig:
    root: Path
    camera: CameraConfig
    model: ModelConfig
    calibration: CalibrationConfig
    tracking: TrackingConfig
    serial: SerialConfig
    recording: RecordingConfig
    debug: DebugConfig

    def resolve(self, configured_path: str) -> Path:
        path = Path(configured_path).expanduser()
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"missing configuration section: {name}")
    return section


def _image_size(values: Any) -> tuple[int, int]:
    if isinstance(values, int):
        return values, values
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("model.imgsz must be an integer or [height, width]")
    return int(values[0]), int(values[1])


def load_config(path: Path) -> AppConfig:
    path = path.expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")

    camera = CameraConfig(**_section(raw, "camera"))
    model_raw = _section(raw, "model").copy()
    model_raw["imgsz"] = _image_size(model_raw["imgsz"])
    model = ModelConfig(**model_raw)
    calibration = CalibrationConfig(**_section(raw, "calibration"))
    tracking = TrackingConfig(**_section(raw, "tracking"))
    serial = SerialConfig(**_section(raw, "serial"))
    recording = RecordingConfig(**_section(raw, "recording"))
    debug = DebugConfig(**_section(raw, "debug"))
    config = AppConfig(
        root=path.parent.parent,
        camera=camera,
        model=model,
        calibration=calibration,
        tracking=tracking,
        serial=serial,
        recording=recording,
        debug=debug,
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    camera = config.camera
    if camera.width <= 0 or camera.height <= 0 or camera.fps <= 0:
        raise ValueError("camera width, height and fps must be positive")
    if camera.maximum_frame_age_sec <= 0:
        raise ValueError("camera maximum_frame_age_sec must be positive")
    if len(camera.fourcc) != 4:
        raise ValueError("camera fourcc must contain four characters")

    model = config.model
    if (
        any(value <= 0 or value % 32 != 0 for value in model.imgsz)
        or not 0.0 < model.confidence <= 1.0
    ):
        raise ValueError("invalid model imgsz or confidence")
    if not 0.0 <= model.crop_top_ratio < model.crop_bottom_ratio <= 1.0:
        raise ValueError("invalid model crop ratios")
    if not 0.0 < model.iou <= 1.0 or model.max_detections <= 0:
        raise ValueError("invalid model iou or max_detections")

    calibration = config.calibration
    if not (
        0.0
        <= calibration.left_x_ratio
        < calibration.center_x_ratio
        < calibration.right_x_ratio
        <= 1.0
    ):
        raise ValueError("calibration must satisfy 0 <= left < center < right <= 1")
    if not 0.0 <= calibration.detection_y_min_ratio < calibration.detection_y_max_ratio <= 1.0:
        raise ValueError("invalid detection Y range")
    if calibration.half_length_cm <= 0:
        raise ValueError("half_length_cm must be positive")

    tracking = config.tracking
    if not 0.0 < tracking.alpha <= 1.0 or not 0.0 < tracking.beta <= 1.0:
        raise ValueError("tracking alpha and beta must be in (0, 1]")
    if tracking.measurement_timeout_sec < tracking.maximum_prediction_sec:
        raise ValueError("measurement timeout must cover maximum prediction")

    serial = config.serial
    if serial.baudrate <= 0 or serial.tx_rate_hz <= 0:
        raise ValueError("serial baudrate and tx_rate_hz must be positive")

    recording = config.recording
    if (
        len(recording.fourcc) != 4
        or recording.fps <= 0
        or recording.queue_size <= 0
        or not recording.filename_prefix
    ):
        raise ValueError("invalid recording configuration")

    debug = config.debug
    if (
        debug.display_rate_hz <= 0
        or debug.maximum_display_age_sec <= 0
        or debug.performance_log_period_sec <= 0
    ):
        raise ValueError("invalid debug configuration")

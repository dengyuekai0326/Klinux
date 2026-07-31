"""Ultralytics YOLO detector optimized for a single in-memory camera frame."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from .calibration import PipeCalibration
from .config import ModelConfig


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) * 0.5

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) * 0.5


class BallDetector:
    def __init__(
        self,
        config: ModelConfig,
        calibration: PipeCalibration,
        model_path: Path,
    ) -> None:
        self.config = config
        self.calibration = calibration
        self.model_path = model_path
        self.use_half = config.half and model_path.suffix.lower() == ".pt"
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")
        self.model = YOLO(str(model_path), task="detect")
        self.latencies_ms: list[float] = []
        self.frames = 0
        self.detections = 0

    def warmup(self, width: int, height: int, count: int = 10) -> None:
        print(f"Loading model: {self.model_path}")
        print(f"PyTorch FP16: {'enabled' if self.use_half else 'not applicable'}")
        print(
            "Model ROI: "
            f"y={self.config.crop_top_ratio:.2f}.."
            f"{self.config.crop_bottom_ratio:.2f}, "
            f"input={self.config.imgsz[1]}x{self.config.imgsz[0]}"
        )
        dummy = np.zeros((height, width, 3), dtype=np.uint8)
        for _ in range(count):
            self._predict(dummy)
        self.latencies_ms.clear()
        self.frames = 0
        self.detections = 0
        print("Model warmup complete")

    def detect(self, frame: np.ndarray) -> Detection | None:
        started = time.perf_counter()
        result, crop_top = self._predict(frame)
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        if len(self.latencies_ms) > 600:
            del self.latencies_ms[:300]
        self.frames += 1

        height, width = frame.shape[:2]
        candidates: list[Detection] = []
        if result.boxes is not None:
            xyxy = result.boxes.xyxy.detach().cpu().numpy()
            confidence = result.boxes.conf.detach().cpu().numpy()
            for box, score in zip(xyxy, confidence):
                x1, y1, x2, y2 = map(float, box)
                detection = Detection(
                    x1,
                    y1 + crop_top,
                    x2,
                    y2 + crop_top,
                    float(score),
                )
                if self.calibration.accepts_detection(
                    detection.center_x,
                    detection.center_y,
                    width,
                    height,
                ):
                    candidates.append(detection)
        if not candidates:
            return None
        self.detections += 1
        return max(candidates, key=lambda item: item.confidence)

    def stats(self) -> tuple[int, int, float, float, float]:
        if not self.latencies_ms:
            return self.frames, self.detections, 0.0, 0.0, 0.0
        values = sorted(self.latencies_ms)
        mean = sum(values) / len(values)
        median = values[len(values) // 2]
        p95 = values[round((len(values) - 1) * 0.95)]
        return self.frames, self.detections, mean, median, p95

    def _predict(self, frame: np.ndarray):
        height = frame.shape[0]
        crop_top = round(height * self.config.crop_top_ratio)
        crop_bottom = round(height * self.config.crop_bottom_ratio)
        inference_frame = frame[crop_top:crop_bottom]
        result = self.model.predict(
            source=inference_frame,
            imgsz=self.config.imgsz,
            conf=self.config.confidence,
            iou=self.config.iou,
            classes=[0],
            max_det=self.config.max_detections,
            device=self.config.device,
            half=self.use_half,
            verbose=False,
        )[0]
        return result, crop_top


def draw_debug(
    frame: np.ndarray,
    detection: Detection | None,
    calibration: PipeCalibration,
    tracked_x: float | None,
    status_lines: list[str],
    crop_top_ratio: float,
    crop_bottom_ratio: float,
) -> np.ndarray:
    output = frame.copy()
    height, width = output.shape[:2]
    left, center, right = calibration.pixel_guides(width)
    cv2.line(output, (left, 0), (left, height - 1), (255, 0, 0), 2)
    cv2.line(output, (center, 0), (center, height - 1), (0, 255, 255), 2)
    cv2.line(output, (right, 0), (right, height - 1), (255, 0, 0), 2)
    crop_top = round(crop_top_ratio * height)
    crop_bottom = round(crop_bottom_ratio * height)
    cv2.line(output, (0, crop_top), (width - 1, crop_top), (255, 0, 255), 1)
    cv2.line(
        output,
        (0, crop_bottom),
        (width - 1, crop_bottom),
        (255, 0, 255),
        1,
    )
    if detection is not None:
        p1 = (round(detection.x1), round(detection.y1))
        p2 = (round(detection.x2), round(detection.y2))
        cv2.rectangle(output, p1, p2, (0, 255, 0), 2)
        cv2.putText(
            output,
            f"ball {detection.confidence:.2f}",
            (p1[0], max(20, p1[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )
    if tracked_x is not None:
        tracked_pixel = round(calibration.control_to_pixel(tracked_x, width))
        tracked_y = round(
            (
                calibration.config.detection_y_min_ratio
                + calibration.config.detection_y_max_ratio
            )
            * 0.5
            * height
        )
        cv2.circle(output, (tracked_pixel, tracked_y), 8, (0, 0, 255), -1)
    for index, line in enumerate(status_lines):
        cv2.putText(
            output,
            line,
            (12, 28 + index * 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (0, 255, 255),
            2,
        )
    return output

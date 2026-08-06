"""Binary serial protocol shared with the lower controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordingCommand:
    enabled: bool


def clamp_int(value: float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, round(value)))


def decode_control_frame(frame: bytes) -> RecordingCommand | None:
    """Decode one of the two recording control commands."""
    if frame == bytes((0xAA, 0xBB, 0xBB, 0xFF)):
        return RecordingCommand(enabled=True)
    if frame == bytes((0xAA, 0xCC, 0xCC, 0xFF)):
        return RecordingCommand(enabled=False)
    return None


class RecordingFrameParser:
    """Recover fixed four-byte control frames from an arbitrary byte stream."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[RecordingCommand]:
        self.buffer.extend(data)
        commands: list[RecordingCommand] = []
        while self.buffer:
            start = self.buffer.find(0xAA)
            if start < 0:
                self.buffer.clear()
                break
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 4:
                break
            if self.buffer[3] != 0xFF:
                del self.buffer[0]
                continue
            frame = bytes(self.buffer[:4])
            del self.buffer[:4]
            command = decode_control_frame(frame)
            if command is not None:
                commands.append(command)
        return commands


def build_ball_frame(x_axis: float, velocity: float, acceleration: float) -> bytes:
    """Build AA | signed X_H | X_L | signed V | signed A | FF."""
    x_value = clamp_int(x_axis, -320, 320) & 0xFFFF
    velocity_value = clamp_int(velocity, -128, 127) & 0xFF
    acceleration_value = clamp_int(acceleration, -128, 127) & 0xFF
    return bytes(
        (
            0xAA,
            (x_value >> 8) & 0xFF,
            x_value & 0xFF,
            velocity_value,
            acceleration_value,
            0xFF,
        )
    )

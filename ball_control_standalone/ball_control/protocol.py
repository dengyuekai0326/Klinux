"""Binary serial protocol shared with the lower controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskCommand:
    mode: int
    target_cm: float


def clamp_int(value: float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, round(value)))


def signed_int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def decode_task_frame(frame: bytes) -> TaskCommand | None:
    """Decode AA | integer/mode | decimal | FF."""
    if len(frame) != 4 or frame[0] != 0xAA or frame[3] != 0xFF:
        return None
    integer_byte, decimal_byte = frame[1], frame[2]
    if integer_byte == 0x00 and decimal_byte == 0x00:
        return TaskCommand(mode=1, target_cm=0.0)
    if integer_byte == 0x55 and decimal_byte == 0x00:
        return TaskCommand(mode=2, target_cm=0.0)

    integer_part = signed_int8(integer_byte)
    if not -12 <= integer_part <= 12 or not 0 <= decimal_byte <= 9:
        return None
    decimal_part = decimal_byte / 10.0
    target_cm = (
        integer_part - decimal_part
        if integer_part < 0
        else integer_part + decimal_part
    )
    if not -12.5 <= target_cm <= 12.5:
        return None
    return TaskCommand(mode=3, target_cm=target_cm)


class TaskFrameParser:
    """Recover fixed four-byte command frames from an arbitrary byte stream."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[TaskCommand]:
        self.buffer.extend(data)
        commands: list[TaskCommand] = []
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
            command = decode_task_frame(frame)
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


def build_task_state_frame(
    mode: int, step: int, target_x: float, status: int
) -> bytes:
    """Build AB | MODE_STEP | signed TARGET_H | TARGET_L | STATUS | FF."""
    mode_step = (
        (clamp_int(mode, 0, 3) & 0x0F) << 4
    ) | (clamp_int(step, 0, 2) & 0x0F)
    target_value = clamp_int(target_x, -320, 320) & 0xFFFF
    return bytes(
        (
            0xAB,
            mode_step,
            (target_value >> 8) & 0xFF,
            target_value & 0xFF,
            clamp_int(status, 0, 3),
            0xFF,
        )
    )

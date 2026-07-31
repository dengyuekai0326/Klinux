import unittest

from ball_control.protocol import (
    TaskCommand,
    TaskFrameParser,
    build_ball_frame,
    build_task_state_frame,
    decode_task_frame,
)


class ProtocolTests(unittest.TestCase):
    def test_decode_modes(self):
        self.assertEqual(
            decode_task_frame(bytes.fromhex("AA 00 00 FF")),
            TaskCommand(1, 0.0),
        )
        self.assertEqual(
            decode_task_frame(bytes.fromhex("AA 55 00 FF")),
            TaskCommand(2, 0.0),
        )
        self.assertEqual(
            decode_task_frame(bytes.fromhex("AA 05 03 FF")),
            TaskCommand(3, 5.3),
        )
        self.assertEqual(
            decode_task_frame(bytes.fromhex("AA FB 03 FF")),
            TaskCommand(3, -5.3),
        )

    def test_parser_recovers_from_noise_and_fragmentation(self):
        parser = TaskFrameParser()
        self.assertEqual(parser.feed(bytes.fromhex("10 20 AA 55")), [])
        commands = parser.feed(bytes.fromhex("00 FF 33 AA 00 00 FF"))
        self.assertEqual(
            commands,
            [TaskCommand(2, 0.0), TaskCommand(1, 0.0)],
        )

    def test_ball_frame_signed_encoding_and_clamp(self):
        self.assertEqual(
            build_ball_frame(-320, -2, 127),
            bytes.fromhex("AA FE C0 FE 7F FF"),
        )
        self.assertEqual(
            build_ball_frame(999, 999, -999),
            bytes.fromhex("AA 01 40 7F 80 FF"),
        )

    def test_task_state_frame(self):
        self.assertEqual(
            build_task_state_frame(2, 1, -128, 0),
            bytes.fromhex("AB 21 FF 80 00 FF"),
        )


if __name__ == "__main__":
    unittest.main()

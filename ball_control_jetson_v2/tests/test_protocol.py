import unittest

from ball_control.protocol import (
    RecordingCommand,
    RecordingFrameParser,
    build_ball_frame,
    decode_control_frame,
)


class ProtocolTests(unittest.TestCase):
    def test_decode_recording_commands(self):
        self.assertEqual(
            decode_control_frame(bytes.fromhex("AA BB BB FF")),
            RecordingCommand(True),
        )
        self.assertEqual(
            decode_control_frame(bytes.fromhex("AA CC CC FF")),
            RecordingCommand(False),
        )
        self.assertIsNone(
            decode_control_frame(bytes.fromhex("AA 00 00 FF"))
        )

    def test_parser_recovers_from_noise_and_fragmentation(self):
        parser = RecordingFrameParser()
        self.assertEqual(parser.feed(bytes.fromhex("10 20 AA BB")), [])
        commands = parser.feed(bytes.fromhex("BB FF 33 AA CC CC FF"))
        self.assertEqual(
            commands,
            [RecordingCommand(True), RecordingCommand(False)],
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

if __name__ == "__main__":
    unittest.main()

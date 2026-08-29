import unittest

from app.realtime.protocol import ProtocolError, parse_message


class ProtocolTests(unittest.TestCase):
    def test_parses_v2_pixel_command(self):
        message = parse_message('{"type":"pixel.place","request_id":"abc","data":{"x":1}}', 4096)
        self.assertEqual('pixel.place', message.type)
        self.assertEqual('abc', message.request_id)

    def test_rejects_non_object_data(self):
        with self.assertRaises(ProtocolError):
            parse_message('{"type":"pixel.place","data":[]}', 4096)

    def test_rejects_oversized_payload(self):
        with self.assertRaises(ProtocolError):
            parse_message('x' * 10, 2)

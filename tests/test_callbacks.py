import unittest

from bot.callbacks import (
    NOOP,
    encode_inbound_page,
    encode_online_page,
    parse_inbound_page,
    parse_online_page,
)


class CallbackTests(unittest.TestCase):
    def test_noop_constant(self) -> None:
        self.assertEqual(NOOP, "noop")

    def test_online_roundtrip_with_query(self) -> None:
        data = encode_online_page("sr", 12, 3, "Ali:Test")
        parsed = parse_online_page(data)
        self.assertEqual(parsed.mode, "sr")
        self.assertEqual(parsed.panel_id, 12)
        self.assertEqual(parsed.page, 3)
        self.assertIn("Ali", parsed.query or "")
        self.assertNotIn(":", parsed.query or "")

    def test_online_roundtrip_without_query(self) -> None:
        data = encode_online_page("on", 8, 2)
        parsed = parse_online_page(data)
        self.assertEqual(parsed.mode, "on")
        self.assertEqual(parsed.panel_id, 8)
        self.assertEqual(parsed.page, 2)
        self.assertIsNone(parsed.query)

    def test_inbound_roundtrip(self) -> None:
        data = encode_inbound_page(9, 33, 4)
        parsed = parse_inbound_page(data)
        self.assertEqual(parsed.panel_id, 9)
        self.assertEqual(parsed.inbound_id, 33)
        self.assertEqual(parsed.page, 4)

    def test_invalid_callbacks(self) -> None:
        with self.assertRaises(ValueError):
            parse_online_page("bad:data")
        with self.assertRaises(ValueError):
            parse_inbound_page("uip:1:2")


if __name__ == "__main__":
    unittest.main()

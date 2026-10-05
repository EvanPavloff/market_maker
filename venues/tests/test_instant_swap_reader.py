import unittest
from unittest import mock

from ..instant_swap import reader
from ..instant_swap.client import InstantSwapAPIError, _get_json, exolix_quote


class TestExolixReader(unittest.TestCase):
    @mock.patch.object(reader, "exolix_quote", return_value=(0.5, 0.0006))
    def test_normalizes_quote_as_xmr_sell_offer(self, _):
        (o,) = reader.ExolixQuoteReader(probe_btc=0.0032).list_public_offers("xmr", "btc")
        self.assertEqual((o.venue, o.coin_from, o.coin_to), ("exolix", "xmr", "btc"))
        self.assertAlmostEqual(o.implied_rate, 0.0064)  # BTC per XMR
        self.assertAlmostEqual(o.amount_from, 0.5)
        self.assertAlmostEqual(o.amount_to, 0.0032)
        self.assertAlmostEqual(o.min_bid_amount, 0.0006 / 0.0064)
        self.assertFalse(o.is_own_offer)

    def test_reverse_direction_is_empty(self):
        self.assertEqual(reader.ExolixQuoteReader(probe_btc=0.0032).list_public_offers("btc", "xmr"), [])

    def test_other_pair_raises(self):
        with self.assertRaises(ValueError):
            reader.ExolixQuoteReader(probe_btc=0.0032).list_public_offers("ltc", "btc")

    @mock.patch.dict("os.environ", {"VENUES_QUOTE_PROBE_BTC": "0.01"})
    def test_probe_size_from_env(self):
        self.assertEqual(reader.ExolixQuoteReader().probe_btc, 0.01)


class TestChangeNowReader(unittest.TestCase):
    @mock.patch.object(reader, "changenow_quote", return_value=0.4)
    def test_normalizes_quote(self, _):
        (o,) = reader.ChangeNowQuoteReader(probe_btc=0.0032).list_public_offers("XMR", "BTC")
        self.assertEqual(o.venue, "changenow")
        self.assertAlmostEqual(o.implied_rate, 0.008)
        self.assertIsNone(o.min_bid_amount)


class TestClient(unittest.TestCase):
    @mock.patch("venues.instant_swap.client._get_json", return_value={"message": "no pair"})
    def test_missing_amount_raises(self, _):
        with self.assertRaises(InstantSwapAPIError):
            exolix_quote(0.0032)

    def test_network_error_wrapped(self):
        with self.assertRaises(InstantSwapAPIError):
            _get_json("https://127.0.0.1:1/nothing", timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()

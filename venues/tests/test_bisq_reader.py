import unittest
from unittest import mock

from ..bisq.reader import BisqOfferBookReader

# Shape verified live against markets.bisq.network 2026-09-18.
_RAW_OFFERS = {
    "buys": [
        {
            "offer_id": "buy-1",
            "direction": "BUY",
            "min_amount": "0.02000000",
            "amount": "4.84895365",
            "price": "0.00692933",
            "volume": "0.03360000",
        }
    ],
    "sells": [
        {
            "offer_id": "sell-1",
            "direction": "SELL",
            "min_amount": "0.03680000",
            "amount": "5.28972757",
            "price": "0.00695688",
            "volume": "0.03680000",
        }
    ],
}


class TestBisqOfferBookReader(unittest.TestCase):
    def setUp(self):
        self.client = mock.MagicMock()
        self.client.get_offers.return_value = _RAW_OFFERS
        self.reader = BisqOfferBookReader(client=self.client)

    def test_sell_side_maps_base_to_quote_directly(self):
        offers = self.reader.list_public_offers("xmr", "btc")
        self.client.get_offers.assert_called_once_with("xmr_btc")
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.venue, "bisq")
        self.assertEqual(o.offer_id, "sell-1")
        self.assertEqual(o.coin_from, "xmr")
        self.assertEqual(o.coin_to, "btc")
        self.assertAlmostEqual(o.amount_from, 5.28972757)
        self.assertAlmostEqual(o.amount_to, 0.03680000)
        self.assertAlmostEqual(o.implied_rate, 0.00695688)
        self.assertAlmostEqual(o.min_bid_amount, 0.03680000)
        self.assertIsNone(o.expire_at)
        self.assertFalse(o.is_own_offer)

    def test_buy_side_maps_quote_to_base_inverted(self):
        offers = self.reader.list_public_offers("btc", "xmr")
        self.client.get_offers.assert_called_once_with("xmr_btc")
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.offer_id, "buy-1")
        self.assertEqual(o.coin_from, "btc")
        self.assertEqual(o.coin_to, "xmr")
        self.assertAlmostEqual(o.amount_from, 0.03360000)
        self.assertAlmostEqual(o.amount_to, 4.84895365)
        self.assertAlmostEqual(o.implied_rate, 1.0 / 0.00692933)
        # min_amount (0.02, base/xmr units) converted to quote/btc units via price.
        self.assertAlmostEqual(o.min_bid_amount, 0.02 * 0.00692933)

    def test_unconfigured_pair_raises(self):
        with self.assertRaises(ValueError):
            self.reader.list_public_offers("ltc", "btc")

    def test_malformed_entry_is_skipped_not_fatal(self):
        self.client.get_offers.return_value = {
            "buys": [],
            "sells": [{"offer_id": "bad", "amount": "not-a-number", "volume": "1", "price": "1"}],
        }
        offers = self.reader.list_public_offers("xmr", "btc")
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()

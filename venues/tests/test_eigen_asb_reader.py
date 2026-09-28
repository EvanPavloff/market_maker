import unittest
from unittest import mock

from ..eigen_asb.reader import EigenAsbOfferBookReader

# Shape verified live against the real network 2026-09-19 (see next_steps.md #13).
_RAW_QUOTES = [
    {
        "peer": "12D3KooWabc",
        "address": "/dns4/example.com/tcp/443/wss/p2p/12D3KooWabc",
        "price_btc_display": "0.00680000 BTC",
        "min_quantity_btc_display": "0.00500000 BTC",
        "max_quantity_btc_display": "0.60000000 BTC",
        "agent_version": "4.14.0",
    },
    {
        "peer": "12D3KooWzero",
        "address": "/dns4/zero.example.com/tcp/443/wss/p2p/12D3KooWzero",
        "price_btc_display": "0.00798000 BTC",
        "min_quantity_btc_display": "0 BTC",
        "max_quantity_btc_display": "0 BTC",
        "agent_version": "4.11.5",
    },
]


class TestEigenAsbOfferBookReader(unittest.TestCase):
    def setUp(self):
        self.client = mock.MagicMock()
        self.client.fetch_quotes.return_value = _RAW_QUOTES
        self.reader = EigenAsbOfferBookReader(client=self.client)

    def test_xmr_to_btc_maps_quotes_directly(self):
        offers = self.reader.list_public_offers("xmr", "btc")
        self.client.fetch_quotes.assert_called_once()
        self.assertEqual(len(offers), 2)

        o = offers[0]
        self.assertEqual(o.venue, "eigen_asb")
        self.assertEqual(o.offer_id, "12D3KooWabc")
        self.assertEqual(o.coin_from, "xmr")
        self.assertEqual(o.coin_to, "btc")
        self.assertAlmostEqual(o.implied_rate, 0.00680000)
        self.assertAlmostEqual(o.amount_to, 0.60000000)
        self.assertAlmostEqual(o.amount_from, 0.60000000 / 0.00680000)
        self.assertAlmostEqual(o.min_bid_amount, 0.00500000 / 0.00680000)
        self.assertIsNone(o.expire_at)
        self.assertFalse(o.is_own_offer)

    def test_zero_quantity_quote_kept_not_skipped(self):
        offers = self.reader.list_public_offers("xmr", "btc")
        zero_offer = next(o for o in offers if o.offer_id == "12D3KooWzero")
        self.assertEqual(zero_offer.amount_to, 0.0)
        self.assertEqual(zero_offer.amount_from, 0.0)
        self.assertEqual(zero_offer.min_bid_amount, 0.0)

    def test_reverse_direction_returns_empty_not_error(self):
        offers = self.reader.list_public_offers("btc", "xmr")
        self.assertEqual(offers, [])
        self.client.fetch_quotes.assert_not_called()

    def test_unrelated_pair_raises(self):
        with self.assertRaises(ValueError):
            self.reader.list_public_offers("ltc", "btc")

    def test_malformed_entry_is_skipped_not_fatal(self):
        self.client.fetch_quotes.return_value = [
            {"peer": "bad", "price_btc_display": "not-a-number BTC",
             "min_quantity_btc_display": "0 BTC", "max_quantity_btc_display": "0 BTC"}
        ]
        offers = self.reader.list_public_offers("xmr", "btc")
        self.assertEqual(offers, [])

    def test_zero_price_entry_is_skipped_not_fatal(self):
        self.client.fetch_quotes.return_value = [
            {"peer": "bad", "price_btc_display": "0 BTC",
             "min_quantity_btc_display": "0 BTC", "max_quantity_btc_display": "1 BTC"}
        ]
        offers = self.reader.list_public_offers("xmr", "btc")
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()

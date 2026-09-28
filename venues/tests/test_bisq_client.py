import json
import unittest
import urllib.error
from unittest import mock

from ..bisq.client import BisqMarketsAPIError, BisqMarketsClient


def _fake_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    return cm


class TestBisqMarketsClient(unittest.TestCase):
    def test_get_offers_parses_valid_response(self):
        payload = {"buys": [{"offer_id": "a"}], "sells": [{"offer_id": "b"}]}
        client = BisqMarketsClient()
        with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            result = client.get_offers("xmr_btc")
        self.assertEqual(result, payload)

    def test_get_offers_unwraps_market_keyed_response(self):
        # The real live endpoint nests one level deeper than its own docs
        # suggest — verified 2026-09-18: {"xmr_btc": {"buys": [...], "sells": [...]}}.
        inner = {"buys": [{"offer_id": "a"}], "sells": [{"offer_id": "b"}]}
        payload = {"xmr_btc": inner}
        client = BisqMarketsClient()
        with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            result = client.get_offers("xmr_btc")
        self.assertEqual(result, inner)

    def test_get_offers_raises_on_network_error(self):
        client = BisqMarketsClient()
        with mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("boom")
        ):
            with self.assertRaises(BisqMarketsAPIError):
                client.get_offers("xmr_btc")

    def test_get_offers_raises_on_invalid_json(self):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = b"not json"
        cm.__exit__.return_value = False
        client = BisqMarketsClient()
        with mock.patch("urllib.request.urlopen", return_value=cm):
            with self.assertRaises(BisqMarketsAPIError):
                client.get_offers("xmr_btc")

    def test_get_offers_raises_on_unexpected_shape(self):
        client = BisqMarketsClient()
        with mock.patch(
            "urllib.request.urlopen", return_value=_fake_response({"unexpected": True})
        ):
            with self.assertRaises(BisqMarketsAPIError):
                client.get_offers("xmr_btc")


class TestBisqGetTrades(unittest.TestCase):
    def test_get_trades_returns_list_and_passes_params(self):
        payload = [{"price": "0.0068", "amount": "1.0", "volume": "0.0068",
                    "payment_method": "BLOCK_CHAINS", "trade_date": 1790275792210}]
        with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)) as m:
            result = BisqMarketsClient().get_trades("xmr_btc", since_ts=1790000000.5, limit=50)
        self.assertEqual(result, payload)
        url = m.call_args[0][0].full_url
        self.assertIn("/api/trades?", url)
        self.assertIn("market=xmr_btc", url)
        self.assertIn("timestamp_from=1790000000", url)
        self.assertIn("limit=50", url)

    def test_get_trades_rejects_non_list(self):
        with mock.patch("urllib.request.urlopen", return_value=_fake_response({"oops": 1})):
            with self.assertRaises(BisqMarketsAPIError):
                BisqMarketsClient().get_trades("xmr_btc", since_ts=0)


class TestTradeFlowSummary(unittest.TestCase):
    def test_premium_and_below_vwap_shares(self):
        import time as _time

        from ..bisq.trade_flow import summarize

        now = _time.time()
        hour = int(now // 3600 * 3600)
        trades = [
            {"price": "0.0102", "volume": "0.3", "trade_date": now * 1000},  # +2% premium
            {"price": "0.0099", "volume": "0.1", "trade_date": now * 1000},  # -1%
            {"price": "0.0100", "volume": "0.1", "trade_date": (now - 40 * 86400) * 1000},  # outside window
        ]
        out = summarize(trades, {hour: 0.01}, days=30)
        self.assertEqual(out["trades"], 2)
        self.assertEqual(out["matched_to_kraken"], 2)
        self.assertAlmostEqual(out["share_trades_below_vwap"], 0.5)
        self.assertAlmostEqual(out["share_btc_volume_below_vwap"], 0.25)


if __name__ == "__main__":
    unittest.main()

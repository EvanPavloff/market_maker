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


if __name__ == "__main__":
    unittest.main()

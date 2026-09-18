import json
import unittest
from unittest.mock import MagicMock, patch

from ..api_client import BasicSwapAPIError, BasicSwapClient


def _fake_response(body: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class BasicSwapClientTests(unittest.TestCase):
    def setUp(self):
        self.client = BasicSwapClient("http://localhost:12701")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_offers_parses_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response([{"offer_id": "aa11"}])
        offers = self.client.get_offers(coin_from="xmr", coin_to="btc")
        self.assertEqual(offers, [{"offer_id": "aa11"}])

        sent_req = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_req.full_url, "http://localhost:12701/json/offers")
        sent_payload = json.loads(sent_req.data)
        self.assertEqual(sent_payload["coin_from"], "xmr")
        self.assertEqual(sent_payload["coin_to"], "btc")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_offers_rejects_non_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"unexpected": "shape"})
        with self.assertRaises(BasicSwapAPIError):
            self.client.get_offers()

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_error_body_raises(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"error": "Wallet locked"})
        with self.assertRaises(BasicSwapAPIError):
            self.client.get_rate("xmr", "btc")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_timeout_during_response_read_raises_basicswap_api_error(self, mock_urlopen):
        # Real incident 2026-09-18: a timeout during resp.read() (headers
        # arrived, body didn't in time) is a bare TimeoutError from the socket
        # layer, not a urllib.error.URLError — it crashed live_maker's bid loop
        # because this was previously uncaught here.
        resp = MagicMock()
        resp.read.side_effect = TimeoutError("timed out")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        mock_urlopen.return_value = resp
        with self.assertRaises(BasicSwapAPIError):
            self.client.get_wallet_balance("btc")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_basic_auth_header_set_when_password_given(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"rate": "0.005"})
        authed_client = BasicSwapClient(
            "http://localhost:12701", auth_user="evan", auth_password="secret"
        )
        authed_client.get_rate("xmr", "btc")
        sent_req = mock_urlopen.call_args[0][0]
        self.assertTrue(sent_req.get_header("Authorization").startswith("Basic "))

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_wallet_balance_parses_by_uppercase_ticker(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            {"BTC": {"balance": "0.00858011"}, "XMR": {"balance": "0.38555176"}}
        )
        self.assertAlmostEqual(self.client.get_wallet_balance("btc"), 0.00858011)

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_wallet_balance_raises_for_unknown_coin(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"BTC": {"balance": "0.008"}})
        with self.assertRaises(BasicSwapAPIError):
            self.client.get_wallet_balance("xmr")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_sent_offers_parses_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response([{"offer_id": "aa11", "is_own_offer": True}])
        offers = self.client.get_sent_offers(coin_from="btc", coin_to="xmr")
        self.assertEqual(offers, [{"offer_id": "aa11", "is_own_offer": True}])
        sent_req = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_req.full_url, "http://localhost:12701/json/sentoffers")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_get_sent_offers_rejects_non_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"error": "nope"})
        with self.assertRaises(BasicSwapAPIError):
            self.client.get_sent_offers()

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_post_offer_sends_expected_payload_and_returns_id(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"offer_id": "deadbeef"})
        offer_id = self.client.post_offer("btc", "xmr", "0.00800000", "150.99789150")
        self.assertEqual(offer_id, "deadbeef")

        sent_req = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_req.full_url, "http://localhost:12701/json/offers/new")
        payload = json.loads(sent_req.data)
        self.assertEqual(payload["coin_from"], "btc")
        self.assertEqual(payload["coin_to"], "xmr")
        self.assertEqual(payload["amt_from"], "0.00800000")
        self.assertEqual(payload["rate"], "150.99789150")
        self.assertEqual(payload["automation_strat_id"], "1")
        self.assertEqual(payload["lockhrs"], "24")
        self.assertEqual(payload["validhrs"], "6")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_post_offer_omits_automation_strat_id_when_none(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"offer_id": "deadbeef"})
        self.client.post_offer("btc", "xmr", "0.008", "150.0", automation_strat_id=None)
        payload = json.loads(mock_urlopen.call_args[0][0].data)
        self.assertNotIn("automation_strat_id", payload)

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_post_offer_rejects_unexpected_response_shape(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"unexpected": "shape"})
        with self.assertRaises(BasicSwapAPIError):
            self.client.post_offer("btc", "xmr", "0.008", "150.0")

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_revoke_offer_posts_to_correct_url_with_flag(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"revoked_offer": "deadbeef"})
        self.client.revoke_offer("deadbeef", refuse_if_negotiating=True)
        sent_req = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_req.full_url, "http://localhost:12701/json/revokeoffer/deadbeef")
        payload = json.loads(sent_req.data)
        self.assertEqual(payload["refuse_if_negotiating"], True)

    @patch("strategy.api_client.urllib.request.urlopen")
    def test_revoke_offer_raises_on_error_body(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"error": "Offer has expired"})
        with self.assertRaises(BasicSwapAPIError):
            self.client.revoke_offer("deadbeef")


if __name__ == "__main__":
    unittest.main()

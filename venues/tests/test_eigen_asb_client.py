import json
import subprocess
import unittest
from unittest import mock

from ..eigen_asb.client import EigenAsbClient, EigenAsbClientError

_FAKE_QUOTES = [
    {
        "peer": "12D3KooWabc",
        "address": "/dns4/example.com/tcp/443/wss/p2p/12D3KooWabc",
        "price_btc_display": "0.00680000 BTC",
        "min_quantity_btc_display": "0.00500000 BTC",
        "max_quantity_btc_display": "0.60000000 BTC",
        "agent_version": "4.14.0",
    }
]


def _fake_result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestEigenAsbClient(unittest.TestCase):
    def setUp(self):
        # subprocess.run is mocked in every test below, so the binary's actual
        # content/executability doesn't matter -- just needs to exist on disk
        # for the isfile() precondition check. This test file itself works on
        # any platform, unlike a hardcoded /bin/true (not present on macOS).
        self.client = EigenAsbClient(binary_path=__file__)

    def test_fetch_quotes_parses_valid_response(self):
        with mock.patch(
            "subprocess.run", return_value=_fake_result(stdout=json.dumps(_FAKE_QUOTES))
        ):
            result = self.client.fetch_quotes()
        self.assertEqual(result, _FAKE_QUOTES)

    def test_fetch_quotes_empty_list_is_not_an_error(self):
        with mock.patch("subprocess.run", return_value=_fake_result(stdout="[]")):
            result = self.client.fetch_quotes()
        self.assertEqual(result, [])

    def test_fetch_quotes_raises_on_missing_binary(self):
        client = EigenAsbClient(binary_path="/no/such/binary/here")
        with self.assertRaises(EigenAsbClientError):
            client.fetch_quotes()

    def test_fetch_quotes_raises_on_nonzero_exit(self):
        with mock.patch(
            "subprocess.run", return_value=_fake_result(returncode=1, stderr="boom")
        ):
            with self.assertRaises(EigenAsbClientError):
                self.client.fetch_quotes()

    def test_fetch_quotes_raises_on_invalid_json(self):
        with mock.patch("subprocess.run", return_value=_fake_result(stdout="not json")):
            with self.assertRaises(EigenAsbClientError):
                self.client.fetch_quotes()

    def test_fetch_quotes_raises_on_unexpected_shape(self):
        with mock.patch(
            "subprocess.run", return_value=_fake_result(stdout=json.dumps({"not": "a list"}))
        ):
            with self.assertRaises(EigenAsbClientError):
                self.client.fetch_quotes()

    def test_fetch_quotes_raises_on_timeout(self):
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="fake", timeout=40.0),
        ):
            with self.assertRaises(EigenAsbClientError):
                self.client.fetch_quotes()

    def test_use_tor_env_var_respected(self):
        client = EigenAsbClient(binary_path=__file__)
        with mock.patch(
            "os.environ.get", side_effect=lambda k, d=None: "1" if k == "EIGEN_ASB_USE_TOR" else d
        ):
            client2 = EigenAsbClient(binary_path=__file__)
        self.assertFalse(client.use_tor)
        self.assertTrue(client2.use_tor)


if __name__ == "__main__":
    unittest.main()

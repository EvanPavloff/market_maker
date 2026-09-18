"""Tests for external_rates.py (next_steps.md §2 fix).

Imports external_rates.py directly by file path rather than via `from .. import
external_rates` / `strategy.tests` package discovery. This session hit a real,
workspace-wide file-access issue (dataless/evicted iCloud placeholders under this
git-tracked Desktop folder timing out on read — see TASKS.md, and
project_status.md's 2026-09-16 entry) that made `python -m unittest discover`
unable to even import `strategy/tests/__init__.py` or the pre-existing sibling
test files. Loading this one new file by path sidesteps that package-import path
entirely, so it can still be run standalone:

    ~/coinswaps/venv/bin/python3 basicswap/strategy/tests/test_external_rates.py

(needs a 3.10+ interpreter for `X | None` annotations — the project's own
~/coinswaps/venv is 3.13; the shell's default `python3` resolves to the
workspace-root venv, which is the other thing the same underlying issue affects,
and macOS's bundled /usr/bin/python3 is only 3.9). Once the dataless-file issue
clears, this can be switched to the normal
`from .. import external_rates` + `python -m unittest discover` convention the
other three test files use, matching them exactly.
"""

import importlib.util
import os
import sys
import unittest
from unittest import mock

_MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "external_rates.py")
_spec = importlib.util.spec_from_file_location("external_rates", _MODULE_PATH)
external_rates = importlib.util.module_from_spec(_spec)
sys.modules["external_rates"] = external_rates
_spec.loader.exec_module(external_rates)


class TestGetReferenceRate(unittest.TestCase):
    def test_coingecko_only_pair_no_kraken_cross_check(self):
        # dash/btc has no configured Kraken pair (_KRAKEN_PAIRS only has xmr/btc,
        # ltc/btc) — should still succeed on CoinGecko alone.
        with mock.patch.object(
            external_rates, "_coingecko_usd_prices", return_value={"dash": 30.0, "bitcoin": 60000.0}
        ):
            rate = external_rates.get_reference_rate("dash", "btc")

        self.assertAlmostEqual(rate.coingecko_rate, 30.0 / 60000.0)
        self.assertIsNone(rate.kraken_rate)
        self.assertIsNone(rate.disagreement_pct)
        self.assertIsNotNone(rate.kraken_error)
        self.assertIsNone(rate.coingecko_error)
        self.assertAlmostEqual(rate.mid, 30.0 / 60000.0)

    def test_xmr_btc_uses_both_sources_and_computes_disagreement(self):
        with mock.patch.object(
            external_rates,
            "_coingecko_usd_prices",
            return_value={"monero": 150.0, "bitcoin": 60000.0},
        ), mock.patch.object(external_rates, "_kraken_ticker_rate", return_value=0.00251):
            rate = external_rates.get_reference_rate("xmr", "btc")

        expected_coingecko = 150.0 / 60000.0  # 0.0025
        self.assertAlmostEqual(rate.coingecko_rate, expected_coingecko)
        self.assertAlmostEqual(rate.kraken_rate, 0.00251)
        self.assertIsNotNone(rate.disagreement_pct)
        self.assertGreater(rate.disagreement_pct, 0.0)
        self.assertLess(rate.disagreement_pct, 0.01)
        # CoinGecko is preferred for `.mid` when both sources succeed.
        self.assertAlmostEqual(rate.mid, expected_coingecko)

    def test_kraken_pair_is_direction_aware(self):
        # Querying btc/xmr (reverse of the configured xmr/btc Kraken pair) should
        # invert Kraken's xmr-per-btc... no: Kraken's XMRXBT quotes btc-per-xmr
        # (coin_to-per-coin_from for xmr->btc), so querying the reverse direction
        # must invert it to xmr-per-btc.
        with mock.patch.object(external_rates, "_coingecko_usd_prices", return_value={}), mock.patch.object(
            external_rates, "_kraken_ticker_rate", return_value=0.0025
        ):
            rate = external_rates.get_reference_rate("btc", "xmr")

        self.assertAlmostEqual(rate.kraken_rate, 1.0 / 0.0025)
        self.assertAlmostEqual(rate.mid, 1.0 / 0.0025)

    def test_coingecko_failure_falls_back_to_kraken(self):
        with mock.patch.object(
            external_rates, "_coingecko_usd_prices", side_effect=external_rates.ExternalRateError("boom")
        ), mock.patch.object(external_rates, "_kraken_ticker_rate", return_value=0.0025):
            rate = external_rates.get_reference_rate("xmr", "btc")

        self.assertIsNone(rate.coingecko_rate)
        self.assertIsNotNone(rate.coingecko_error)
        self.assertAlmostEqual(rate.kraken_rate, 0.0025)
        self.assertAlmostEqual(rate.mid, 0.0025)

    def test_both_sources_fail_raises(self):
        with mock.patch.object(
            external_rates, "_coingecko_usd_prices", side_effect=external_rates.ExternalRateError("boom")
        ), mock.patch.object(
            external_rates, "_kraken_ticker_rate", side_effect=external_rates.ExternalRateError("also boom")
        ):
            with self.assertRaises(external_rates.ExternalRateError):
                external_rates.get_reference_rate("xmr", "btc")

    def test_unmapped_coin_id_with_no_kraken_pair_raises(self):
        # Neither ticker is in _COINGECKO_IDS or _KRAKEN_PAIRS — must raise without
        # making any real network call (wow/nmc used to serve this purpose but were
        # since added to _COINGECKO_IDS, which silently turned this into a live
        # network test masked only by an unrelated SSL bug in this venv — see
        # external_rates.py's certifi fix, project_status.md 2026-09-16).
        with self.assertRaises(external_rates.ExternalRateError):
            external_rates.get_reference_rate("zzz1", "zzz2")


class TestGetUsdPrice(unittest.TestCase):
    def test_returns_price_for_mapped_coin(self):
        with mock.patch.object(external_rates, "_coingecko_usd_prices", return_value={"monero": 510.68}):
            price = external_rates.get_usd_price("xmr")
        self.assertAlmostEqual(price, 510.68)

    def test_is_case_insensitive(self):
        with mock.patch.object(external_rates, "_coingecko_usd_prices", return_value={"bitcoin": 76546.0}):
            price = external_rates.get_usd_price("BTC")
        self.assertAlmostEqual(price, 76546.0)

    def test_unmapped_coin_raises_without_network_call(self):
        with self.assertRaises(external_rates.ExternalRateError):
            external_rates.get_usd_price("zzz1")

    def test_network_failure_raises(self):
        with mock.patch.object(
            external_rates, "_coingecko_usd_prices", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(external_rates.ExternalRateError):
                external_rates.get_usd_price("xmr")


class TestKrakenTickerParsing(unittest.TestCase):
    def test_takes_last_trade_price_regardless_of_echoed_pair_key(self):
        # Kraken echoes back its own canonical key (e.g. "XXMRXXBT"), not
        # necessarily the altname ("XMRXBT") the request used.
        fake_response = {"error": [], "result": {"XXMRXXBT": {"c": ["0.00251000", "1.5"]}}}
        with mock.patch.object(external_rates, "_get_json", return_value=fake_response):
            rate = external_rates._kraken_ticker_rate("XMRXBT", timeout=5.0)
        self.assertAlmostEqual(rate, 0.00251)

    def test_kraken_error_field_raises(self):
        fake_response = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with mock.patch.object(external_rates, "_get_json", return_value=fake_response):
            with self.assertRaises(external_rates.ExternalRateError):
                external_rates._kraken_ticker_rate("XMRXBT", timeout=5.0)


if __name__ == "__main__":
    unittest.main()

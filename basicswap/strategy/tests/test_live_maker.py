import time
import unittest
from unittest.mock import MagicMock, patch

from .. import storage
from ..external_rates import ReferenceRate
from ..live_maker import (
    AmbiguousLiveOffersError,
    InsufficientBalanceError,
    LiveMakerConfig,
    _resolve_amount_from,
    decide_and_act,
    run_cycle,
)
from ..volatility import VolatilityMonitor


def _cfg(**overrides) -> LiveMakerConfig:
    defaults = dict(
        coin_from="btc",
        coin_to="xmr",
        side="ask",
        amount_from=0.008,
        half_spread_pct=0.0066,
        reprice_threshold_pct=0.005,
        offer_valid_hours=0.7,
        lock_hours=24,
        valid_hours=6,
        automation_strat_id=1,
    )
    defaults.update(overrides)
    return LiveMakerConfig(**defaults)


class DecideAndActTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        # Comfortably more than any amount_from used below (0.008) — tests that
        # care about the insufficient-funds path override this explicitly.
        self.client.get_wallet_balance.return_value = 1.0

    def test_no_live_offer_posts_a_new_one(self):
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"

        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1000.0)

        self.assertEqual(action, "post")
        self.client.post_offer.assert_called_once()
        args, kwargs = self.client.post_offer.call_args
        self.assertEqual(args[0], "btc")
        self.assertEqual(args[1], "xmr")
        self.assertEqual(args[2], "0.00800000")
        # target rate = 150.0 * 1.0066
        self.assertEqual(args[3], "150.99000000")
        self.assertEqual(kwargs["automation_strat_id"], 1)
        self.client.revoke_offer.assert_not_called()

        events = storage.fetch_live_quote_events(self.conn, "Bitcoin", "Monero", side="ask")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["offer_id"], "aaaa")

    def test_fresh_offer_with_small_drift_does_nothing(self):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": 1000.0,
             "is_expired": False, "is_revoked": False}
        ]
        # Reference barely moved.
        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.01, now=1010.0)
        self.assertIsNone(action)
        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    def test_large_drift_revokes_then_reposts(self):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": 1000.0,
             "is_expired": False, "is_revoked": False}
        ]
        self.client.post_offer.return_value = "bbbb"
        # Reference moves 2% — well past the 0.5% threshold.
        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=153.0, now=1010.0)

        self.assertEqual(action, "reprice")
        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)
        self.client.post_offer.assert_called_once()

        events = storage.fetch_live_quote_events(self.conn, "Bitcoin", "Monero", side="ask")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["previous_offer_id"], "aaaa")
        self.assertEqual(events[0]["offer_id"], "bbbb")

    def test_revoke_called_before_post_in_reprice(self):
        # Order matters for real capital — never post a second live offer
        # before the first one is actually revoked.
        call_order = []
        self.client.revoke_offer.side_effect = lambda *a, **k: call_order.append("revoke")
        self.client.post_offer.side_effect = lambda *a, **k: call_order.append("post") or "bbbb"
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": 1000.0,
             "is_expired": False, "is_revoked": False}
        ]
        decide_and_act(self.client, self.conn, _cfg(), reference_mid=153.0, now=1010.0)
        self.assertEqual(call_order, ["revoke", "post"])

    def test_stale_offer_with_no_drift_expires_and_reposts(self):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": 1000.0,
             "is_expired": False, "is_revoked": False}
        ]
        self.client.post_offer.return_value = "bbbb"
        # Reference unchanged, but offer_valid_hours (0.7h = 2520s) has elapsed.
        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1000.0 + 2521.0)
        self.assertEqual(action, "expire_repost")
        self.client.revoke_offer.assert_called_once()
        self.client.post_offer.assert_called_once()

    def test_ambiguous_live_offers_raises_and_takes_no_action(self):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.0", "created_at": 1000.0, "is_expired": False, "is_revoked": False},
            {"offer_id": "bbbb", "rate": "151.0", "created_at": 1000.0, "is_expired": False, "is_revoked": False},
        ]
        with self.assertRaises(AmbiguousLiveOffersError):
            decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1010.0)
        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    def test_expired_or_revoked_offers_are_ignored_as_not_live(self):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.0", "created_at": 1000.0, "is_expired": True, "is_revoked": False},
            {"offer_id": "bbbb", "rate": "150.0", "created_at": 1000.0, "is_expired": False, "is_revoked": True},
        ]
        self.client.post_offer.return_value = "cccc"
        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1010.0)
        self.assertEqual(action, "post")

    def test_insufficient_balance_on_first_post_raises_and_does_not_post(self):
        self.client.get_sent_offers.return_value = []
        self.client.get_wallet_balance.return_value = 0.0005  # less than amount_from=0.008

        with self.assertRaises(InsufficientBalanceError):
            decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1000.0)
        self.client.post_offer.assert_not_called()

    def test_insufficient_balance_on_reprice_does_not_revoke_the_working_offer(self):
        # A filled/partially-drained wallet must not lose its one good, funded
        # offer just because repricing discovered it can't afford the
        # replacement — checking funds before revoking is the whole point.
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": 1000.0,
             "is_expired": False, "is_revoked": False}
        ]
        self.client.get_wallet_balance.return_value = 0.0005
        with self.assertRaises(InsufficientBalanceError):
            decide_and_act(self.client, self.conn, _cfg(), reference_mid=153.0, now=1010.0)
        self.client.revoke_offer.assert_not_called()
        self.client.post_offer.assert_not_called()

    def test_sufficient_balance_still_works_normally(self):
        self.client.get_sent_offers.return_value = []
        self.client.get_wallet_balance.return_value = 0.009  # just enough
        self.client.post_offer.return_value = "aaaa"
        action = decide_and_act(self.client, self.conn, _cfg(), reference_mid=150.0, now=1000.0)
        self.assertEqual(action, "post")

    def test_bid_side_quotes_below_mid(self):
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        decide_and_act(
            self.client, self.conn, _cfg(side="bid", coin_from="xmr", coin_to="btc"),
            reference_mid=150.0, now=1000.0,
        )
        args, _ = self.client.post_offer.call_args
        self.assertEqual(args[3], "149.01000000")  # 150 * (1 - 0.0066)


class LiveMakerConfigValidationTests(unittest.TestCase):
    def test_neither_amount_from_nor_reserve_usd_raises(self):
        with self.assertRaises(ValueError):
            _cfg(amount_from=None, reserve_usd=None)

    def test_both_amount_from_and_reserve_usd_raises(self):
        with self.assertRaises(ValueError):
            _cfg(amount_from=0.008, reserve_usd=210.0)

    def test_reserve_usd_alone_is_valid(self):
        cfg = _cfg(amount_from=None, reserve_usd=210.0)
        self.assertEqual(cfg.reserve_usd, 210.0)


class ResolveAmountFromTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()

    def test_fixed_amount_from_passes_through_without_touching_client(self):
        cfg = _cfg(amount_from=0.008, reserve_usd=None)
        amount = _resolve_amount_from(self.client, cfg)
        self.assertEqual(amount, 0.008)
        self.client.get_wallet_balance.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_reserve_usd_computes_amount_above_reserve(self, mock_usd_price):
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.return_value = 0.5
        cfg = _cfg(amount_from=None, reserve_usd=210.0, coin_from="xmr", coin_to="btc", side="bid")

        amount = _resolve_amount_from(self.client, cfg)

        reserve_coin = 210.0 / 510.68
        self.assertAlmostEqual(amount, 0.5 - reserve_coin)

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_reserve_usd_exceeding_balance_returns_none(self, mock_usd_price):
        # This is exactly today's real situation: 0.38555176 XMR (~$196.9 at
        # $510.68) is below a $210 reserve.
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.return_value = 0.38555176
        cfg = _cfg(amount_from=None, reserve_usd=210.0, coin_from="xmr", coin_to="btc", side="bid")

        amount = _resolve_amount_from(self.client, cfg)
        self.assertIsNone(amount)

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_usd_price_failure_returns_none_rather_than_raising(self, mock_usd_price):
        from ..external_rates import ExternalRateError

        mock_usd_price.side_effect = ExternalRateError("boom")
        cfg = _cfg(amount_from=None, reserve_usd=210.0, coin_from="xmr", coin_to="btc", side="bid")
        self.assertIsNone(_resolve_amount_from(self.client, cfg))


def _rate(**overrides) -> ReferenceRate:
    defaults = dict(
        coin_from="btc", coin_to="xmr", coingecko_rate=150.0, kraken_rate=None,
        disagreement_pct=None, coingecko_error=None, kraken_error=None,
    )
    defaults.update(overrides)
    return ReferenceRate(**defaults)


class RunCycleKillSwitchTests(unittest.TestCase):
    """market_maker/next_steps.md #1 — decide_and_act itself has no notion of
    volatility; run_cycle is where the kill-switch decides whether to call it
    at all this cycle."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.return_value = 1.0
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_large_move_within_window_skips_the_cycle_entirely(self, mock_rate):
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(time.time() - 60, 150.0)  # prior cycle's sample, still inside the window
        # (154 - 150) / mean(150, 154) ~= 2.6%, well past the 0.85% default threshold.
        mock_rate.return_value = _rate(coingecko_rate=154.0)

        run_cycle(self.client, self.conn, _cfg(), monitor)

        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_small_move_within_window_does_not_trigger_the_kill_switch(self, mock_rate):
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=150.05)  # tiny move, well under threshold

        run_cycle(self.client, self.conn, _cfg(), monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_first_ever_sample_cannot_trigger_the_kill_switch(self, mock_rate):
        # No prior sample yet -> volatility_pct() is None -> must not block the
        # very first cycle a process runs just because it has no history yet.
        monitor = VolatilityMonitor(window_seconds=900)
        mock_rate.return_value = _rate(coingecko_rate=150.0)

        run_cycle(self.client, self.conn, _cfg(), monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_kill_switch_leaves_an_existing_live_offer_untouched(self, mock_rate):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=154.0)

        run_cycle(self.client, self.conn, _cfg(), monitor)

        self.client.revoke_offer.assert_not_called()
        self.client.post_offer.assert_not_called()


if __name__ == "__main__":
    unittest.main()

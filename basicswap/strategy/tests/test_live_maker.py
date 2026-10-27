import time
import unittest
from unittest.mock import MagicMock, patch

from .. import storage
from ..api_client import BasicSwapAPIError
from ..external_rates import ExternalRateError, ReferenceRate
from ..live_maker import (
    AmbiguousLiveOffersError,
    InsufficientBalanceError,
    LiveMakerConfig,
    _dynamic_half_spread_pct,
    _resolve_amount_from,
    SATS_PER_BTC,
    decide_and_act,
    guard_anchor,
    guard_check,
    run_cycle,
)
from ..economics import restock_half_spread_pct
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
        self.assertIsNone(kwargs["min_bid_amount"])
        self.client.revoke_offer.assert_not_called()

        events = storage.fetch_live_quote_events(self.conn, "Bitcoin", "Monero", side="ask")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["offer_id"], "aaaa")

    def test_min_bid_amount_is_passed_and_capped_at_offer_size(self):
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"

        decide_and_act(self.client, self.conn, _cfg(amount_from=0.55, min_bid_amount=0.25),
                       reference_mid=150.0, now=1000.0)
        self.assertEqual(self.client.post_offer.call_args.kwargs["min_bid_amount"], "0.25000000")

        # An offer smaller than the minimum is posted take-whole.
        decide_and_act(self.client, self.conn, _cfg(amount_from=0.15, min_bid_amount=0.25),
                       reference_mid=150.0, now=1000.0)
        self.assertEqual(self.client.post_offer.call_args.kwargs["min_bid_amount"], "0.15000000")

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

    def test_bid_side_sells_coin_from_above_mid(self):
        # 2026-09-25 incident: the bid side (coin_from=xmr, coin_to=btc) used to
        # quote mid*(1-h) in BTC per XMR, selling XMR below market. An offer
        # always sells coin_from, so both sides must quote above mid.
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        decide_and_act(
            self.client, self.conn, _cfg(side="bid", coin_from="xmr", coin_to="btc"),
            reference_mid=0.0066, now=1000.0,
        )
        args, _ = self.client.post_offer.call_args
        self.assertGreater(float(args[3]), 0.0066)
        self.assertAlmostEqual(float(args[3]), 0.0066 * 1.0066, places=8)

    def test_both_sides_quote_the_same_rate_for_the_same_pair_and_mid(self):
        for side in ("ask", "bid"):
            client = MagicMock()
            client.get_wallet_balance.return_value = 1.0
            client.get_sent_offers.return_value = []
            client.post_offer.return_value = "aaaa"
            decide_and_act(client, storage.connect(":memory:"), _cfg(side=side), 150.0, now=1000.0)
            self.assertEqual(client.post_offer.call_args[0][3], "150.99000000", side)

    def test_refuses_to_quote_at_or_below_mid(self):
        self.client.get_sent_offers.return_value = []
        with self.assertRaises(ValueError):
            decide_and_act(self.client, self.conn, _cfg(half_spread_pct=0.0), 150.0, now=1000.0)
        with self.assertRaises(ValueError):
            decide_and_act(self.client, self.conn, _cfg(half_spread_pct=-0.02), 150.0, now=1000.0)
        self.client.post_offer.assert_not_called()


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

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_wallet_balance_failure_returns_none_rather_than_raising(self, mock_usd_price):
        # Real incident 2026-09-18: this exact call (get_wallet_balance inside
        # _resolve_amount_from, not decide_and_act) was the one uncaught path
        # that crashed the whole bid-side loop on a transient timeout.
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.side_effect = BasicSwapAPIError("request timed out")
        cfg = _cfg(amount_from=None, reserve_usd=210.0, coin_from="xmr", coin_to="btc", side="bid")
        self.assertIsNone(_resolve_amount_from(self.client, cfg))

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_amount_step_quantizes_down_rather_than_offering_exact_leftover(self, mock_usd_price):
        # Stolen from BasicSwap's own createoffers.py ("amount_step: REQUIRED -
        # Offer size increment for privacy"): without quantization, this would
        # offer the exact ~0.08878358 leftover, disclosing the wallet's precise
        # balance to anyone watching. With amount_step=0.05, it should round
        # down to the nearest whole step (1 step = 0.05), not reveal the odd
        # remainder.
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.return_value = 0.5  # ~$255.34
        cfg = _cfg(
            amount_from=None, reserve_usd=210.0, amount_step=0.05,
            coin_from="xmr", coin_to="btc", side="bid",
        )
        amount = _resolve_amount_from(self.client, cfg)
        self.assertAlmostEqual(amount, 0.05)

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_amount_step_none_preserves_exact_leftover_default_behavior(self, mock_usd_price):
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.return_value = 0.5
        cfg = _cfg(
            amount_from=None, reserve_usd=210.0, amount_step=None,
            coin_from="xmr", coin_to="btc", side="bid",
        )
        amount = _resolve_amount_from(self.client, cfg)
        reserve_coin = 210.0 / 510.68
        self.assertAlmostEqual(amount, 0.5 - reserve_coin)

    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_amount_step_larger_than_leftover_returns_none(self, mock_usd_price):
        # ~$255.34 available, $210 reserve -> ~0.117 XMR free, but a single
        # 0.2 XMR step doesn't fit -> nothing postable this cycle, same
        # "leave any existing offer untouched" posture as every other
        # nothing-to-offer path in this module.
        mock_usd_price.return_value = 510.68
        self.client.get_wallet_balance.return_value = 0.5
        cfg = _cfg(
            amount_from=None, reserve_usd=210.0, amount_step=0.2,
            coin_from="xmr", coin_to="btc", side="bid",
        )
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
    def test_kill_switch_leaves_a_still_profitable_live_offer_untouched(self, mock_rate):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "156.00000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=154.0)

        run_cycle(self.client, self.conn, _cfg(min_live_edge_pct=0.01), monitor)

        self.client.revoke_offer.assert_not_called()
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_kill_switch_revokes_a_live_offer_the_move_left_underwater(self, mock_rate):
        # 2026-10-22 02:14: the pause left a below-mid ask up until it was taken.
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=154.0)

        run_cycle(self.client, self.conn, _cfg(), monitor)

        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_cooldown_revokes_an_offer_under_the_min_live_edge(self, mock_rate):
        # +0.5% over mid clears 0 but not a 1% floor.
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.75000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.last_trip_at = time.time() - 60
        mock_rate.return_value = _rate(coingecko_rate=150.0)

        run_cycle(self.client, self.conn, _cfg(min_live_edge_pct=0.01), monitor)

        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_restock_leg_floor_is_its_cap_plus_reprice_tolerance(self, mock_rate):
        # Restock offers sit below mid by design, often right at the cap; the floor
        # is -(restock_max_premium_pct + reprice_threshold_pct) = -1.0% here.
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "149.40000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.last_trip_at = time.time() - 60
        cfg = _cfg(objective="btc", restock_expected_sell_premium_pct=0.021, restock_max_premium_pct=0.005)
        mock_rate.return_value = _rate(coingecko_rate=150.0)  # -0.4%: within the cap

        run_cycle(self.client, self.conn, cfg, monitor)
        self.client.revoke_offer.assert_not_called()

        mock_rate.return_value = _rate(coingecko_rate=150.3)  # ~-0.6%: past the cap, inside the floor
        run_cycle(self.client, self.conn, cfg, monitor)
        self.client.revoke_offer.assert_not_called()

        mock_rate.return_value = _rate(coingecko_rate=151.2)  # ~-1.2%: past the floor
        run_cycle(self.client, self.conn, cfg, monitor)
        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)


class RunCycleKillSwitchHysteresisTests(unittest.TestCase):
    """2026-09-24 recalibration (volatility.py's note): the long window and
    cooldown that close the 2026-09-18 flicker, where one calm 15-min reading
    mid-spike let run_cycle reprice into the top of the move."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.return_value = 1.0
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=3600)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_one_calm_reading_during_cooldown_does_not_repost(self, mock_rate):
        now = time.time()
        self.monitor.add(now - 600, 150.0)
        self.monitor.add(now - 300, 150.0)
        self.monitor.last_trip_at = now - 300  # tripped last cycle
        mock_rate.return_value = _rate(coingecko_rate=150.0)  # calm on both windows

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_quoting_resumes_once_cooldown_has_elapsed(self, mock_rate):
        now = time.time()
        self.monitor.add(now - 600, 150.0)
        self.monitor.last_trip_at = now - 31 * 60
        mock_rate.return_value = _rate(coingecko_rate=150.0)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_zero_cooldown_restores_the_old_flicker_behavior(self, mock_rate):
        now = time.time()
        self.monitor.add(now - 300, 150.0)
        self.monitor.last_trip_at = now - 300
        mock_rate.return_value = _rate(coingecko_rate=150.0)

        run_cycle(self.client, self.conn, _cfg(kill_switch_cooldown_minutes=0), self.monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_long_window_trips_when_short_window_looks_calm(self, mock_rate):
        # The 09-18 shape: a big move 20-50 min ago, then a flat plateau inside
        # the last 15 min — short window calm, 60-min window ~5%.
        now = time.time()
        self.monitor.add(now - 50 * 60, 143.0)
        self.monitor.add(now - 20 * 60, 136.5)
        self.monitor.add(now - 10 * 60, 136.4)
        self.monitor.add(now - 5 * 60, 136.4)
        mock_rate.return_value = _rate(coingecko_rate=136.4)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()
        self.assertIsNotNone(self.monitor.last_trip_at)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_long_window_disabled_by_zero_threshold(self, mock_rate):
        now = time.time()
        self.monitor.add(now - 50 * 60, 143.0)
        self.monitor.add(now - 10 * 60, 136.4)
        mock_rate.return_value = _rate(coingecko_rate=136.4)

        run_cycle(
            self.client, self.conn, _cfg(kill_switch_long_volatility_pct=0), self.monitor
        )

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_short_window_trip_records_trip_time(self, mock_rate):
        self.monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=154.0)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.assertIsNotNone(self.monitor.last_trip_at)


class RunCycleInFlightSwapTests(unittest.TestCase):
    """2026-09-25 incident: reprices posted fresh offers while earlier swaps
    were still in flight, so the same surplus sold twice and cut into the
    reserve. run_cycle must not post while any swap in this direction is live."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.return_value = 1.0
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=3600)

    def _bid(self, state, coin_from="Bitcoin", coin_to="Monero"):
        return {"bid_id": "b" * 56, "offer_id": "o" * 56, "bid_state": state,
                "coin_from": coin_from, "coin_to": coin_to}

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_in_flight_swap_blocks_posting(self, mock_rate):
        self.client.get_bids.return_value = [self._bid("Script coin locked")]
        mock_rate.return_value = _rate()

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_in_flight_swap_revokes_our_live_offer(self, mock_rate):
        self.client.get_bids.return_value = [self._bid("Script coin locked")]
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live1", "rate": "150.99", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        mock_rate.return_value = _rate()

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.revoke_offer.assert_called_once_with("live1", refuse_if_negotiating=True)
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_revoke_failure_still_blocks_posting(self, mock_rate):
        self.client.get_bids.return_value = [self._bid("Script coin locked")]
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live1", "rate": "150.99", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        self.client.revoke_offer.side_effect = BasicSwapAPIError("negotiating")
        mock_rate.return_value = _rate()

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_terminal_and_other_direction_bids_do_not_block(self, mock_rate):
        self.client.get_bids.return_value = [
            self._bid("Completed"), self._bid("Abandoned"), self._bid("Expired"),
            self._bid("Script coin locked", coin_from="Monero", coin_to="Bitcoin"),
        ]
        mock_rate.return_value = _rate()

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_get_bids_failure_skips_the_cycle(self, mock_rate):
        self.client.get_bids.side_effect = BasicSwapAPIError("timeout")
        mock_rate.return_value = _rate()

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()


class RunCycleSourceDisagreementTests(unittest.TestCase):
    """market_maker/next_steps.md #10 — closes the real 2026-09-18 incident
    where a single bad CoinGecko reading (undetected by the volatility
    kill-switch, since it only sees trouble in the trailing window) priced a
    real ask ~6.7% below fair value. run_cycle now checks CoinGecko vs.
    Kraken agreement on the reading itself, before ever using it."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.return_value = 1.0
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=900)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_large_disagreement_skips_the_cycle_entirely(self, mock_rate):
        # coingecko=136.17 vs kraken=145.0 -> ~6.2% disagreement, well past
        # the 1.5% default threshold — this is the shape of the real incident.
        mock_rate.return_value = _rate(coingecko_rate=136.17, kraken_rate=145.0, disagreement_pct=0.062)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_large_disagreement_does_not_poison_the_volatility_window(self, mock_rate):
        mock_rate.return_value = _rate(coingecko_rate=136.17, kraken_rate=145.0, disagreement_pct=0.062)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.assertEqual(len(self.monitor._samples), 0)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_small_disagreement_does_not_trigger_the_gate(self, mock_rate):
        mock_rate.return_value = _rate(coingecko_rate=150.0, kraken_rate=150.3, disagreement_pct=0.002)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_no_kraken_coverage_proceeds_on_coingecko_alone(self, mock_rate):
        # Most BasicSwap pairs have no Kraken cross-check at all —
        # disagreement_pct is None, not zero, and must not block quoting.
        mock_rate.return_value = _rate(coingecko_rate=150.0, kraken_rate=None, disagreement_pct=None)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.post_offer.assert_called_once()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_large_disagreement_leaves_an_existing_live_offer_untouched(self, mock_rate):
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "150.99000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        mock_rate.return_value = _rate(coingecko_rate=136.17, kraken_rate=145.0, disagreement_pct=0.062)

        run_cycle(self.client, self.conn, _cfg(), self.monitor)

        self.client.revoke_offer.assert_not_called()
        self.client.post_offer.assert_not_called()


class DynamicHalfSpreadPctTests(unittest.TestCase):
    """market_maker/next_steps.md #15 Phase A."""

    def test_no_usd_price_falls_back_to_the_floor_unchanged(self):
        cfg = _cfg(half_spread_pct=0.02)
        result = _dynamic_half_spread_pct(cfg, amount_from=0.008, usd_price_from=None, vol_pct=0.02)
        self.assertEqual(result, 0.02)

    def test_calm_volatility_stays_at_the_floor(self):
        cfg = _cfg(half_spread_pct=0.02, assumed_fill_hours=2.5)
        result = _dynamic_half_spread_pct(
            cfg, amount_from=0.008, usd_price_from=110_000.0, vol_pct=0.0022  # ~p50, real calibration
        )
        self.assertEqual(result, 0.02)

    def test_elevated_volatility_widens_above_the_floor(self):
        cfg = _cfg(half_spread_pct=0.02, assumed_fill_hours=2.5)
        result = _dynamic_half_spread_pct(
            cfg, amount_from=0.008, usd_price_from=110_000.0, vol_pct=0.0084  # ~p99
        )
        self.assertGreater(result, 0.02)

    def test_no_live_vol_reading_yet_does_not_crash_and_stays_at_or_above_floor(self):
        # First cycle of a fresh process — volatility_monitor.volatility_pct() is
        # None until it has 2+ samples. Must not raise, and must never drop below
        # the floor even with no live vol data (falls back to the static
        # ANNUALIZED_CROSS_VOL_PCT assumption inside economics.dynamic_half_spread_pct).
        cfg = _cfg(half_spread_pct=0.02, assumed_fill_hours=2.5)
        result = _dynamic_half_spread_pct(cfg, amount_from=0.008, usd_price_from=110_000.0, vol_pct=None)
        self.assertGreaterEqual(result, 0.02)


class RunCycleDynamicSpreadTests(unittest.TestCase):
    """market_maker/next_steps.md #15 Phase A — end-to-end through run_cycle."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.return_value = 1.0
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=900)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_elevated_volatility_posts_wider_than_the_configured_floor(self, mock_rate):
        # Seed the window with a real p99-magnitude move (150 -> 151.26, ~0.84%)
        # so volatility_pct() is not None on the cycle that posts.
        self.monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=151.26, usd_price_from=110_000.0)
        cfg = _cfg(half_spread_pct=0.02, assumed_fill_hours=2.5)

        run_cycle(self.client, self.conn, cfg, self.monitor)

        self.client.post_offer.assert_called_once()
        args, _ = self.client.post_offer.call_args
        posted_rate = float(args[3])
        floor_rate = 151.26 * 1.02
        self.assertGreater(posted_rate, floor_rate)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_no_usd_price_from_posts_at_the_floor_exactly(self, mock_rate):
        mock_rate.return_value = _rate(coingecko_rate=150.0, usd_price_from=None)
        cfg = _cfg(half_spread_pct=0.02, assumed_fill_hours=2.5)

        run_cycle(self.client, self.conn, cfg, self.monitor)

        self.client.post_offer.assert_called_once()
        args, _ = self.client.post_offer.call_args
        self.assertAlmostEqual(float(args[3]), 150.0 * 1.02)


class BtcObjectiveConfigTests(unittest.TestCase):
    def test_restock_target_rejected_on_sell_leg(self):
        with self.assertRaises(ValueError):
            _cfg(coin_from="xmr", coin_to="btc", side="bid", objective="btc", restock_target_to=0.5)

    def test_restock_target_rejected_under_usd_objective(self):
        with self.assertRaises(ValueError):
            _cfg(restock_target_to=0.5)

    def test_restock_target_needs_fixed_cap(self):
        with self.assertRaises(ValueError):
            _cfg(amount_from=None, reserve_coin=0.001, objective="btc", restock_target_to=0.5)

    def test_btc_objective_needs_btc_in_pair(self):
        with self.assertRaises(ValueError):
            _cfg(coin_from="ltc", coin_to="xmr", objective="btc")

    def test_two_sizings_rejected(self):
        with self.assertRaises(ValueError):
            _cfg(reserve_coin=0.1)

    def test_restock_floor_must_stay_above_mid(self):
        with self.assertRaises(ValueError):
            _cfg(objective="btc", restock_min_half_spread_pct=0.0)


class ReserveCoinTests(unittest.TestCase):
    @patch("strategy.live_maker.external_rates.get_usd_price")
    def test_reserve_coin_needs_no_usd_price(self, mock_usd_price):
        client = MagicMock()
        client.get_wallet_balance.return_value = 0.5
        cfg = _cfg(coin_from="xmr", coin_to="btc", side="bid", amount_from=None, reserve_coin=0.3)
        self.assertAlmostEqual(_resolve_amount_from(client, cfg), 0.2)
        mock_usd_price.assert_not_called()

    def test_reserve_coin_above_balance_returns_none(self):
        client = MagicMock()
        client.get_wallet_balance.return_value = 0.2
        cfg = _cfg(coin_from="xmr", coin_to="btc", side="bid", amount_from=None, reserve_coin=0.3)
        self.assertIsNone(_resolve_amount_from(client, cfg))


class RunCycleBtcObjectiveTests(unittest.TestCase):
    """--objective btc end-to-end through run_cycle (mid = 150 XMR per BTC)."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.balances = {"btc": 1.0, "xmr": 0.0}
        self.client.get_wallet_balance.side_effect = lambda coin: self.balances[coin]
        self.client.get_bids.return_value = []
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=900)

    def _restock_cfg(self, **overrides):
        base = dict(half_spread_pct=0.02, objective="btc", assumed_fill_hours=2.5,
                    restock_expected_sell_premium_pct=0.018)
        base.update(overrides)
        return _cfg(**base)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_restock_leg_quotes_below_the_usd_floor(self, mock_rate):
        mock_rate.return_value = _rate(usd_price_from=110_000.0)
        run_cycle(self.client, self.conn, self._restock_cfg(), self.monitor)

        args, _ = self.client.post_offer.call_args
        expected_h = restock_half_spread_pct(0.0025, 0.008 * SATS_PER_BTC, 2.5, 0.018, None, 900)
        self.assertLess(expected_h, 0.02)
        self.assertAlmostEqual(float(args[3]), 150.0 * (1 + expected_h), places=6)
        self.assertGreater(float(args[3]), 150.0)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_restock_target_reached_posts_nothing_and_revokes(self, mock_rate):
        mock_rate.return_value = _rate()
        self.balances["xmr"] = 1.5
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live", "rate": "150.5", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        run_cycle(self.client, self.conn, self._restock_cfg(restock_target_to=1.2), self.monitor)

        self.client.post_offer.assert_not_called()
        self.client.revoke_offer.assert_called_once_with("live", refuse_if_negotiating=True)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_restock_sizes_to_the_deficit(self, mock_rate):
        mock_rate.return_value = _rate()
        self.balances["xmr"] = 0.6  # target 1.0 -> needs 0.4 XMR, ~0.00266 BTC < 0.008 cap
        run_cycle(self.client, self.conn, self._restock_cfg(restock_target_to=1.0), self.monitor)

        args, _ = self.client.post_offer.call_args
        amount, rate = float(args[2]), float(args[3])
        self.assertLess(amount, 0.008)
        self.assertAlmostEqual(amount * rate, 0.4, places=4)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_restock_deficit_below_min_amount_stands_down(self, mock_rate):
        mock_rate.return_value = _rate()
        self.balances["xmr"] = 0.95  # 0.05 XMR ~ 0.00033 BTC < 0.001 min
        run_cycle(self.client, self.conn, self._restock_cfg(restock_target_to=1.0), self.monitor)
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_oversized_live_restock_offer_is_resized(self, mock_rate):
        mock_rate.return_value = _rate()
        self.balances["xmr"] = 0.6
        cfg = self._restock_cfg(restock_target_to=1.0)
        h = restock_half_spread_pct(0.0025, 0.0026 * SATS_PER_BTC, 2.5, 0.018, None, 900)
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live", "rate": f"{150.0 * (1 + h):.8f}", "amount_from": "0.008",
             "created_at": time.time(), "is_expired": False, "is_revoked": False}
        ]
        self.client.post_offer.return_value = "bbbb"
        run_cycle(self.client, self.conn, cfg, self.monitor)

        self.client.revoke_offer.assert_called_once_with("live", refuse_if_negotiating=True)
        self.assertLess(float(self.client.post_offer.call_args[0][2]), 0.008)
        events = storage.fetch_live_quote_events(self.conn, "Bitcoin", "Monero", side="ask")
        self.assertEqual(events[0]["action"], "reprice")

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_usd_objective_never_resizes_on_amount_alone(self, mock_rate):
        mock_rate.return_value = _rate(usd_price_from=None)
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live", "rate": f"{150.0 * 1.02:.8f}", "amount_from": "0.05",
             "created_at": time.time(), "is_expired": False, "is_revoked": False}
        ]
        run_cycle(self.client, self.conn, _cfg(half_spread_pct=0.02), self.monitor)
        self.client.revoke_offer.assert_not_called()
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_sell_leg_prices_in_sats_without_a_usd_price(self, mock_rate):
        # xmr->btc: mid is BTC per XMR. usd_price_from=None would pin the USD
        # path to its floor; the sats path still widens on elevated volatility.
        self.balances["xmr"] = 1.0
        self.monitor.add(time.time() - 60, 0.006605)
        mock_rate.return_value = _rate(coin_from="xmr", coin_to="btc", coingecko_rate=0.00666, usd_price_from=None)
        cfg = _cfg(coin_from="xmr", coin_to="btc", side="bid", amount_from=0.5,
                   half_spread_pct=0.02, objective="btc", assumed_fill_hours=2.5)
        run_cycle(self.client, self.conn, cfg, self.monitor)

        args, _ = self.client.post_offer.call_args
        self.assertGreater(float(args[3]), 0.00666 * 1.02)


class RestockBookPricingTests(unittest.TestCase):
    """2026-10-01 restock_pricing='book' (mid = 150 XMR per BTC; lower rate wins)."""

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.client.get_wallet_balance.side_effect = lambda coin: {"btc": 1.0, "xmr": 0.0}[coin]
        self.client.get_bids.return_value = []
        self.client.get_sent_offers.return_value = []
        self.client.post_offer.return_value = "aaaa"
        self.monitor = VolatilityMonitor(window_seconds=900)

    def _cfg(self, **overrides):
        base = dict(half_spread_pct=0.02, objective="btc", assumed_fill_hours=2.5,
                    restock_expected_sell_premium_pct=0.018, restock_pricing="book",
                    restock_max_premium_pct=0.005)
        base.update(overrides)
        return _cfg(**base)

    def _book(self, *offers):
        self.client.get_offers.return_value = [
            dict(dict(is_own_offer=False, is_expired=False, is_revoked=False, min_bid_amount="0.001"), **o)
            for o in offers
        ]

    def _posted_rate(self, mock_rate):
        mock_rate.return_value = _rate()
        run_cycle(self.client, self.conn, self._cfg(), self.monitor)
        return float(self.client.post_offer.call_args[0][3])

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_quotes_just_inside_the_best_competitor_below_mid(self, mock_rate):
        self._book({"rate": "149.4"}, {"rate": "149.9"})  # best pays 0.4% over mid
        self.assertAlmostEqual(self._posted_rate(mock_rate), 150.0 * (149.4 / 150.0 - 0.0001), places=6)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_never_pays_more_than_the_cap(self, mock_rate):
        self._book({"rate": "148.5"})  # 1% over mid
        self.assertAlmostEqual(self._posted_rate(mock_rate), 150.0 * 0.995, places=6)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_weak_book_quotes_above_the_cost_price(self, mock_rate):
        self._book({"rate": "152.0"})
        self.assertAlmostEqual(self._posted_rate(mock_rate), 150.0 * (152.0 / 150.0 - 0.0001), places=6)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_ignores_own_unusable_and_dead_offers(self, mock_rate):
        self._book(
            {"rate": "140.0", "is_own_offer": True},
            {"rate": "140.0", "is_revoked": True},
            {"rate": "140.0", "min_bid_amount": "0.0624"},  # can't serve a taker our size
            {"rate": "151.0"},
        )
        self.assertAlmostEqual(self._posted_rate(mock_rate), 150.0 * (151.0 / 150.0 - 0.0001), places=6)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_empty_book_or_api_error_falls_back_to_cost_price(self, mock_rate):
        expected = 150.0 * (1 + restock_half_spread_pct(0.0025, 0.008 * SATS_PER_BTC, 2.5, 0.018, None, 900))
        self._book()
        self.assertAlmostEqual(self._posted_rate(mock_rate), expected, places=6)
        self.client.get_offers.side_effect = BasicSwapAPIError("down")
        self.monitor = VolatilityMonitor(window_seconds=900)  # same vol reading as the first call
        self.assertAlmostEqual(self._posted_rate(mock_rate), expected, places=6)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_reprices_when_outbid_by_less_than_the_drift_threshold(self, mock_rate):
        self._book({"rate": "149.7"})
        self.client.get_sent_offers.return_value = [
            {"offer_id": "live", "rate": "149.8", "amount_from": "0.008", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]
        self.client.post_offer.return_value = "bbbb"
        self._posted_rate(mock_rate)
        self.client.revoke_offer.assert_called_once_with("live", refuse_if_negotiating=True)

    @patch("strategy.live_maker.external_rates.get_reference_rate")
    def test_no_churn_when_already_on_top_or_capped(self, mock_rate):
        mock_rate.return_value = _rate()
        live = {"offer_id": "live", "amount_from": "0.008", "created_at": time.time(),
                "is_expired": False, "is_revoked": False}
        for live_rate, book_rate in (("149.6", "149.7"), (f"{150 * 0.995:.8f}", "148.0")):
            self.client.reset_mock()
            self._book({"rate": book_rate})
            self.client.get_sent_offers.return_value = [dict(live, rate=live_rate)]
            run_cycle(self.client, self.conn, self._cfg(), self.monitor)
            self.client.revoke_offer.assert_not_called()

    def test_config_guards(self):
        with self.assertRaises(ValueError):
            self._cfg(restock_max_premium_pct=0.018)  # >= sell premium: no round-trip profit
        with self.assertRaises(ValueError):
            self._cfg(restock_max_premium_pct=-0.001)
        with self.assertRaises(ValueError):
            _cfg(coin_from="xmr", coin_to="btc", side="bid", objective="btc", restock_pricing="book",
                 restock_expected_sell_premium_pct=0.018)

    def test_decide_and_act_refuses_below_the_cap(self):
        cfg = self._cfg(half_spread_pct=-0.006)
        with self.assertRaises(ValueError):
            decide_and_act(self.client, self.conn, cfg, 150.0)


class InFlightSentBidTests(unittest.TestCase):
    def test_sent_topup_blocks_the_restock_leg(self):
        from ..live_maker import _in_flight_swaps

        client = MagicMock()
        client.get_bids.return_value = []
        # A top-up we sent into someone's XMR-selling offer spends BTC for XMR,
        # the same thing the btc->xmr restock leg does.
        client.get_sent_bids.return_value = [
            {"bid_id": "t", "bid_state": "Script coin locked", "coin_from": "Monero", "coin_to": "Bitcoin"},
            {"bid_id": "done", "bid_state": "Completed", "coin_from": "Monero", "coin_to": "Bitcoin"},
        ]
        self.assertEqual([b["bid_id"] for b in _in_flight_swaps(client, "btc", "xmr")], ["t"])
        self.assertEqual(_in_flight_swaps(client, "xmr", "btc"), [])

    def test_amount_step_quantization_is_float_safe(self):
        client = MagicMock()
        client.get_wallet_balance.return_value = 0.985
        cfg = _cfg(coin_from="xmr", coin_to="btc", side="bid", amount_from=None, reserve_coin=0.385, amount_step=0.05)
        self.assertAlmostEqual(_resolve_amount_from(client, cfg), 0.6)

    def test_max_amount_from_caps_dynamic_offer(self):
        # 2026-09-30: restock fills grow the XMR balance; the sell offer must stay 0.55.
        client = MagicMock()
        client.get_wallet_balance.return_value = 1.585
        cfg = _cfg(
            coin_from="xmr", coin_to="btc", side="bid", amount_from=None, reserve_coin=0.385,
            amount_step=0.05, max_amount_from=0.55,
        )
        self.assertAlmostEqual(_resolve_amount_from(client, cfg), 0.55)

    def test_max_amount_from_leaves_smaller_offer_alone(self):
        client = MagicMock()
        client.get_wallet_balance.return_value = 0.7
        cfg = _cfg(
            coin_from="xmr", coin_to="btc", side="bid", amount_from=None, reserve_coin=0.385,
            amount_step=0.05, max_amount_from=0.55,
        )
        self.assertAlmostEqual(_resolve_amount_from(client, cfg), 0.3)


class GuardCheckTests(unittest.TestCase):
    """2026-10-22: the 30s revoke-only check between full cycles."""

    def setUp(self):
        self.client = MagicMock()
        self.client.get_sent_offers.return_value = [
            {"offer_id": "aaaa", "rate": "151.50000000", "created_at": time.time(),
             "is_expired": False, "is_revoked": False}
        ]

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=150.0)
    def test_leaves_an_offer_above_its_floor(self, _):
        self.assertFalse(guard_check(self.client, _cfg(min_live_edge_pct=0.01)))
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=150.5)
    def test_revokes_an_offer_below_its_floor_and_never_posts(self, _):
        self.assertTrue(guard_check(self.client, _cfg(min_live_edge_pct=0.01)))
        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)
        self.client.post_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_kraken_mid", side_effect=ExternalRateError("down"))
    def test_rate_failure_skips_without_touching_the_offer(self, _):
        self.assertFalse(guard_check(self.client, _cfg(min_live_edge_pct=0.01)))
        self.client.get_sent_offers.assert_not_called()
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=150.5)
    def test_anchor_cancels_a_steady_source_gap(self, _):
        # Cycle priced off 150.0 while Kraken read 150.5; Kraken hasn't moved since.
        self.assertFalse(guard_check(self.client, _cfg(min_live_edge_pct=0.01), anchor=(150.0, 150.5)))
        self.client.revoke_offer.assert_not_called()

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=152.0)
    def test_anchor_still_catches_a_real_move(self, _):
        # Kraken +1% since the cycle: 151.5 is now ~-0.5% vs. the moved mid.
        self.assertTrue(guard_check(self.client, _cfg(min_live_edge_pct=0.01), anchor=(150.0, 150.5)))
        self.client.revoke_offer.assert_called_once_with("aaaa", refuse_if_negotiating=True)

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=150.5)
    def test_guard_anchor_only_from_a_sample_this_cycle_added(self, _):
        monitor = VolatilityMonitor(window_seconds=900)
        self.assertIsNone(guard_anchor(_cfg(), monitor, cycle_started=1000.0))
        monitor.add(990.0, 150.0)  # previous cycle's sample
        self.assertIsNone(guard_anchor(_cfg(), monitor, cycle_started=1000.0))
        monitor.add(1001.0, 150.0)
        self.assertEqual(guard_anchor(_cfg(), monitor, cycle_started=1000.0), (150.0, 150.5))

    @patch("strategy.live_maker.external_rates.get_kraken_mid", return_value=160.0)
    def test_revoke_refused_mid_negotiation_is_logged_not_raised(self, _):
        self.client.revoke_offer.side_effect = BasicSwapAPIError("negotiating")
        self.assertFalse(guard_check(self.client, _cfg()))


if __name__ == "__main__":
    unittest.main()

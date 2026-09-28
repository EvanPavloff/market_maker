import time
import unittest
from unittest.mock import MagicMock, patch

from .. import storage
from ..api_client import BasicSwapAPIError
from ..bid_scanner import (
    BidScannerConfig,
    _already_bid_offer_ids,
    _classify_bid_state,
    _size_bid,
    reconcile_bid_outcomes,
    run_cycle,
    scan_candidates,
)
from ..external_rates import ReferenceRate
from ..volatility import VolatilityMonitor


def _cfg(**overrides) -> BidScannerConfig:
    defaults = dict(
        coin_from="btc",
        coin_to="xmr",
        half_spread_pct=0.02,
        max_bid_amount=0.01,
        max_cycle_exposure=0.02,
        min_offer_remaining_seconds=300.0,
        max_bids_per_cycle=3,
        assumed_fill_hours=2.5,
        kill_switch_window_minutes=15.0,
        kill_switch_volatility_pct=0.0085,
        max_source_disagreement_pct=0.015,
    )
    defaults.update(overrides)
    return BidScannerConfig(**defaults)


def _offer(**overrides) -> dict:
    # created_at/expire_at default to real wall-clock time (not an arbitrary
    # small epoch) — run_cycle's own staleness filter compares expire_at
    # against a real time.time() it computes internally, not an injectable
    # "now", so fixtures have to be real-time-relative to survive it.
    now = time.time()
    defaults = dict(
        offer_id="offer1", rate="147.00000000", amount_from="0.02",
        min_bid_amount="0.001", is_own_offer=False, is_expired=False,
        is_revoked=False, created_at=now - 600, expire_at=now + 3600,
    )
    defaults.update(overrides)
    return defaults


class ScanCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.cfg = _cfg()

    def test_filters_own_expired_revoked_and_excluded_offers(self):
        self.client.get_offers.return_value = [
            _offer(offer_id="own", is_own_offer=True),
            _offer(offer_id="expired", is_expired=True),
            _offer(offer_id="revoked", is_revoked=True),
            _offer(offer_id="excluded"),
            _offer(offer_id="good"),
        ]
        candidates = scan_candidates(
            self.client, self.cfg, target_rate=150.0, exclude_offer_ids={"excluded"}, now=1000.0
        )
        self.assertEqual([o["offer_id"] for o in candidates], ["good"])

    def test_filters_rate_above_target(self):
        self.client.get_offers.return_value = [
            _offer(offer_id="cheap", rate="149.0"),
            _offer(offer_id="expensive", rate="151.0"),
        ]
        candidates = scan_candidates(self.client, self.cfg, target_rate=150.0, exclude_offer_ids=set(), now=1000.0)
        self.assertEqual([o["offer_id"] for o in candidates], ["cheap"])

    def test_filters_offers_expiring_too_soon(self):
        self.client.get_offers.return_value = [
            _offer(offer_id="soon", expire_at=1000 + 100),  # only 100s left, < 300s min
            _offer(offer_id="plenty", expire_at=1000 + 3600),
        ]
        candidates = scan_candidates(self.client, self.cfg, target_rate=150.0, exclude_offer_ids=set(), now=1000.0)
        self.assertEqual([o["offer_id"] for o in candidates], ["plenty"])

    def test_sorts_cheapest_rate_first(self):
        self.client.get_offers.return_value = [
            _offer(offer_id="mid", rate="148.0"),
            _offer(offer_id="cheapest", rate="145.0"),
            _offer(offer_id="priciest", rate="149.9"),
        ]
        candidates = scan_candidates(self.client, self.cfg, target_rate=150.0, exclude_offer_ids=set(), now=1000.0)
        self.assertEqual([o["offer_id"] for o in candidates], ["cheapest", "mid", "priciest"])


class SizeBidTests(unittest.TestCase):
    def test_capped_by_offer_amount(self):
        cfg = _cfg(max_bid_amount=1.0, max_cycle_exposure=1.0)
        offer = _offer(amount_from="0.015", min_bid_amount="0.001")
        self.assertAlmostEqual(_size_bid(offer, cfg, remaining_cycle_budget=1.0), 0.015)

    def test_capped_by_our_own_max_bid_amount(self):
        cfg = _cfg(max_bid_amount=0.005, max_cycle_exposure=1.0)
        offer = _offer(amount_from="0.015", min_bid_amount="0.001")
        self.assertAlmostEqual(_size_bid(offer, cfg, remaining_cycle_budget=1.0), 0.005)

    def test_capped_by_remaining_cycle_budget(self):
        cfg = _cfg(max_bid_amount=1.0, max_cycle_exposure=1.0)
        offer = _offer(amount_from="0.015", min_bid_amount="0.001")
        self.assertAlmostEqual(_size_bid(offer, cfg, remaining_cycle_budget=0.003), 0.003)

    def test_none_when_below_offers_own_min_bid_amount(self):
        cfg = _cfg(max_bid_amount=1.0, max_cycle_exposure=1.0)
        offer = _offer(amount_from="0.015", min_bid_amount="0.001")
        self.assertIsNone(_size_bid(offer, cfg, remaining_cycle_budget=0.0005))

    def test_none_when_budget_exhausted(self):
        cfg = _cfg()
        offer = _offer()
        self.assertIsNone(_size_bid(offer, cfg, remaining_cycle_budget=0.0))


def _rate(**overrides) -> ReferenceRate:
    # usd_price_from defaults to None (matching ReferenceRate's own default,
    # same convention test_live_maker.py's own _rate() helper uses) so
    # half_spread_pct stays exactly cfg.half_spread_pct (the floor) in most
    # tests here -- set it explicitly only in tests that specifically target
    # the dynamic-spread composition (economics.dynamic_half_spread_pct).
    defaults = dict(
        coin_from="btc", coin_to="xmr", coingecko_rate=150.0, kraken_rate=None,
        disagreement_pct=None, coingecko_error=None, kraken_error=None,
    )
    defaults.update(overrides)
    return ReferenceRate(**defaults)


class RunCycleTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        self.monitor = VolatilityMonitor(window_seconds=900.0)
        self.cfg = _cfg(half_spread_pct=0.02, max_bid_amount=0.01, max_cycle_exposure=0.02)

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_dry_run_does_not_call_post_bid_or_write_storage(self, mock_rate):
        mock_rate.return_value = _rate()
        self.client.get_offers.return_value = [_offer(rate="147.0", amount_from="0.005")]

        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=False)

        self.assertEqual(bid_ids, [])
        self.client.post_bid.assert_not_called()
        self.assertEqual(len(storage.fetch_bid_scan_events(self.conn, "btc", "xmr")), 0)

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_live_bids_on_a_good_offer_and_logs_it(self, mock_rate):
        mock_rate.return_value = _rate()
        self.client.get_offers.return_value = [_offer(rate="147.0", amount_from="0.005")]
        self.client.post_bid.return_value = "bidid1"
        self.client.get_wallet_balance.return_value = 10.0  # plenty of xmr to pay with

        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)

        self.assertEqual(bid_ids, ["bidid1"])
        self.client.post_bid.assert_called_once()
        args, _ = self.client.post_bid.call_args
        self.assertEqual(args[0], "offer1")
        self.assertEqual(args[1], "0.00500000")
        self.assertEqual(args[2], "147.00000000")

        events = storage.fetch_bid_scan_events(self.conn, "btc", "xmr")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["bid_id"], "bidid1")
        self.assertEqual(events[0]["offer_id"], "offer1")
        self.assertAlmostEqual(events[0]["offer_rate"], 147.0)
        self.assertAlmostEqual(events[0]["reference_mid"], 150.0)
        # edge_pct = (150 - 147) / 150
        self.assertAlmostEqual(events[0]["edge_pct"], 0.02)
        self.assertEqual(events[0]["resolved"], 0)

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_offer_rate_above_target_is_never_bid(self, mock_rate):
        mock_rate.return_value = _rate()  # mid=150, half_spread_pct=0.02 -> target=147.0
        self.client.get_offers.return_value = [_offer(rate="148.0", amount_from="0.005")]
        self.client.get_wallet_balance.return_value = 10.0

        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, [])
        self.client.post_bid.assert_not_called()

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_insufficient_funds_stops_the_cycle_without_raising(self, mock_rate):
        mock_rate.return_value = _rate()
        self.client.get_offers.return_value = [_offer(rate="147.0", amount_from="0.005")]
        self.client.get_wallet_balance.return_value = 0.01  # far below what 0.005 BTC @ 147 costs

        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, [])
        self.client.post_bid.assert_not_called()

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_respects_max_bids_per_cycle(self, mock_rate):
        mock_rate.return_value = _rate()
        cfg = _cfg(max_bid_amount=0.001, max_cycle_exposure=1.0, max_bids_per_cycle=2)
        self.client.get_offers.return_value = [
            _offer(offer_id="a", rate="145.0", amount_from="0.001"),
            _offer(offer_id="b", rate="146.0", amount_from="0.001"),
            _offer(offer_id="c", rate="147.0", amount_from="0.001"),
        ]
        self.client.post_bid.side_effect = ["bid_a", "bid_b", "bid_c"]
        self.client.get_wallet_balance.return_value = 10.0

        bid_ids = run_cycle(self.client, self.conn, cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, ["bid_a", "bid_b"])

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_already_bid_offer_is_excluded_on_next_scan(self, mock_rate):
        mock_rate.return_value = _rate()
        self.client.get_offers.return_value = [_offer(rate="147.0", amount_from="0.005")]
        self.client.post_bid.return_value = "bidid1"
        self.client.get_wallet_balance.return_value = 10.0

        run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        excluded = _already_bid_offer_ids(self.conn, "btc", "xmr")
        self.assertEqual(excluded, {"offer1"})

        # A second cycle should see the same offer still live but skip it.
        self.client.post_bid.reset_mock()
        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, [])
        self.client.post_bid.assert_not_called()

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_source_disagreement_skips_the_cycle(self, mock_rate):
        mock_rate.return_value = _rate(disagreement_pct=0.03)  # exceeds 0.015 threshold
        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, [])
        self.client.get_offers.assert_not_called()

    @patch("strategy.bid_scanner.external_rates.get_reference_rate")
    def test_volatility_kill_switch_skips_the_cycle(self, mock_rate):
        # Prior sample still inside the real window (run_cycle stamps its own
        # sample with time.time(), so this has to be recent wall-clock time,
        # not an arbitrary epoch — same convention as test_live_maker.py's
        # own kill-switch tests).
        self.monitor.add(time.time() - 60, 150.0)
        mock_rate.return_value = _rate(coingecko_rate=165.0)  # ~9.5% swing, past the 0.85% threshold
        bid_ids = run_cycle(self.client, self.conn, self.cfg, self.monitor, live=True)
        self.assertEqual(bid_ids, [])
        self.client.get_offers.assert_not_called()


class ClassifyBidStateTests(unittest.TestCase):
    def test_completed_is_terminal_success(self):
        self.assertEqual(_classify_bid_state("Completed"), (True, "success"))

    def test_abandoned_is_terminal_failure(self):
        self.assertEqual(_classify_bid_state("Abandoned"), (True, "failure"))

    def test_in_progress_states_are_not_resolved(self):
        for state in ("Sent", "Accepted", "Initiated", "Participating", "Delaying"):
            self.assertEqual(_classify_bid_state(state), (False, None))


class ReconcileBidOutcomesTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.client = MagicMock()
        storage.insert_bid_scan_event(
            self.conn, "btc", "xmr", "offer1", "bid1", 147.0, 150.0, 0.02, 0.005, 0.735,
            created_at=time.time(),
        )

    def test_completed_bid_gets_marked_resolved_with_success(self):
        self.client.get_bid.return_value = {"bid_id": "bid1", "bid_state": "Completed"}
        n = reconcile_bid_outcomes(self.client, self.conn)
        self.assertEqual(n, 1)
        row = storage.fetch_bid_scan_events(self.conn, "btc", "xmr")[0]
        self.assertEqual(row["resolved"], 1)
        self.assertEqual(row["outcome"], "success")
        self.assertEqual(row["bid_state"], "Completed")

    def test_still_in_progress_bid_stays_unresolved(self):
        self.client.get_bid.return_value = {"bid_id": "bid1", "bid_state": "Accepted"}
        n = reconcile_bid_outcomes(self.client, self.conn)
        self.assertEqual(n, 0)
        row = storage.fetch_bid_scan_events(self.conn, "btc", "xmr")[0]
        self.assertEqual(row["resolved"], 0)
        self.assertIsNone(row["outcome"])
        self.assertEqual(row["bid_state"], "Accepted")  # latest known state still recorded

    def test_abandoned_bid_gets_marked_resolved_with_failure(self):
        self.client.get_bid.return_value = {"bid_id": "bid1", "bid_state": "Abandoned"}
        n = reconcile_bid_outcomes(self.client, self.conn)
        self.assertEqual(n, 1)
        row = storage.fetch_bid_scan_events(self.conn, "btc", "xmr")[0]
        self.assertEqual(row["outcome"], "failure")

    def test_get_bid_failure_is_skipped_not_raised(self):
        self.client.get_bid.side_effect = BasicSwapAPIError("timed out")
        n = reconcile_bid_outcomes(self.client, self.conn)
        self.assertEqual(n, 0)
        row = storage.fetch_bid_scan_events(self.conn, "btc", "xmr")[0]
        self.assertIsNone(row["bid_state"])

    def test_already_resolved_bids_are_not_requeried(self):
        storage.update_bid_scan_event_outcome(self.conn, "bid1", "Completed", True, "success", resolved_at=time.time())
        n = reconcile_bid_outcomes(self.client, self.conn)
        self.assertEqual(n, 0)
        self.client.get_bid.assert_not_called()


if __name__ == "__main__":
    unittest.main()

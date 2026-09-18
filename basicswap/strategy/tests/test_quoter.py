import unittest

from .. import storage
from ..quoter import (
    decide_and_record,
    format_summary,
    half_spread_rate,
    summarize_quote_events,
)


class HalfSpreadRateTests(unittest.TestCase):
    def test_ask_is_above_mid(self):
        self.assertAlmostEqual(half_spread_rate(100.0, 0.01, "ask"), 101.0)

    def test_bid_is_below_mid(self):
        self.assertAlmostEqual(half_spread_rate(100.0, 0.01, "bid"), 99.0)

    def test_rejects_unknown_side(self):
        with self.assertRaises(ValueError):
            half_spread_rate(100.0, 0.01, "mid")


class DecideAndRecordTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")

    def test_no_prior_quote_posts(self):
        action = decide_and_record(
            self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0
        )
        self.assertEqual(action, "post")
        events = storage.fetch_simulated_quote_events(self.conn, "Monero", "Bitcoin", side="ask")
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["new_rate"], 101.0)

    def test_small_drift_within_threshold_and_fresh_does_nothing(self):
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0)
        # Reference barely moved and the quote isn't stale yet.
        action = decide_and_record(
            self.conn, "Monero", "Bitcoin", "ask", 100.05, 0.01, 0.005, 3600, now=1010.0
        )
        self.assertIsNone(action)
        events = storage.fetch_simulated_quote_events(self.conn, "Monero", "Bitcoin", side="ask")
        self.assertEqual(len(events), 1)  # nothing new logged

    def test_large_drift_reprices(self):
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0)
        # Reference moves 2% — well past the 0.5% reprice threshold.
        action = decide_and_record(
            self.conn, "Monero", "Bitcoin", "ask", 102.0, 0.01, 0.005, 3600, now=1010.0
        )
        self.assertEqual(action, "reprice")
        events = storage.fetch_simulated_quote_events(self.conn, "Monero", "Bitcoin", side="ask")
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[1]["previous_rate"], 101.0)
        self.assertAlmostEqual(events[1]["new_rate"], 103.02)

    def test_stale_quote_with_no_drift_expires_and_reposts(self):
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0)
        # Reference unchanged, but the quote is older than offer_valid_seconds.
        action = decide_and_record(
            self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0 + 3601.0
        )
        self.assertEqual(action, "expire_repost")

    def test_ask_and_bid_are_tracked_independently(self):
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=1000.0)
        decide_and_record(self.conn, "Monero", "Bitcoin", "bid", 100.0, 0.01, 0.005, 3600, now=1000.0)
        asks = storage.fetch_simulated_quote_events(self.conn, "Monero", "Bitcoin", side="ask")
        bids = storage.fetch_simulated_quote_events(self.conn, "Monero", "Bitcoin", side="bid")
        self.assertEqual(len(asks), 1)
        self.assertEqual(len(bids), 1)
        self.assertAlmostEqual(asks[0]["new_rate"], 101.0)
        self.assertAlmostEqual(bids[0]["new_rate"], 99.0)


class SummarizeQuoteEventsTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")

    def test_empty_history_is_empty_not_error(self):
        summary = summarize_quote_events(self.conn, "Monero", "Bitcoin", "ask")
        self.assertEqual(summary.n_events, 0)
        self.assertEqual(summary.n_reprices, 0)
        self.assertIsNone(summary.mean_seconds_between_reprices)
        format_summary(summary)  # doesn't raise on empty data

    def test_counts_reprices_and_gap_between_them(self):
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 100.0, 0.01, 0.005, 3600, now=0.0)
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 105.0, 0.01, 0.005, 3600, now=1800.0)
        decide_and_record(self.conn, "Monero", "Bitcoin", "ask", 110.0, 0.01, 0.005, 3600, now=5400.0)
        summary = summarize_quote_events(self.conn, "Monero", "Bitcoin", "ask")
        self.assertEqual(summary.n_events, 3)
        self.assertEqual(summary.n_reprices, 2)
        # gaps are [1800-0, 5400-1800] = [1800, 3600] -> mean/median both 2700
        self.assertAlmostEqual(summary.mean_seconds_between_reprices, 2700.0)
        self.assertAlmostEqual(summary.median_seconds_between_reprices, 2700.0)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from .. import storage
from ..analysis import build_poll_snapshots, summarize_pair

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        storage.insert_offer_snapshots(
            self.conn, _load("offers_xmr_to_btc.json"), polled_at=100.0
        )
        storage.insert_offer_snapshots(
            self.conn, _load("offers_btc_to_xmr.json"), polled_at=100.0
        )
        storage.insert_rate_snapshot(
            self.conn, "Monero", "Bitcoin", _load("rate_xmr_btc.json"), polled_at=100.0
        )

    def test_best_ask_ignores_revoked_offer(self):
        snaps = build_poll_snapshots(self.conn, "Monero", "Bitcoin")
        self.assertEqual(len(snaps), 1)
        snap = snaps[0]
        # best ask is 0.0055 (aa11), not the revoked 0.0020 (aa33) or the
        # worse 0.0057 (aa22)
        self.assertAlmostEqual(snap.best_ask, 0.0055)
        self.assertEqual(snap.ask_depth_count, 2)
        self.assertAlmostEqual(snap.ask_depth_notional, 15.0)

    def test_best_bid_is_inverted_rate(self):
        snaps = build_poll_snapshots(self.conn, "Monero", "Bitcoin")
        snap = snaps[0]
        # bb11: rate=192.30769231 XMR/BTC -> implied BTC/XMR = 1/192.30769231
        self.assertAlmostEqual(snap.best_bid, 1.0 / 192.30769231, places=6)
        self.assertEqual(snap.bid_depth_count, 1)

    def test_spread_computed_against_reference_mid(self):
        snaps = build_poll_snapshots(self.conn, "Monero", "Bitcoin")
        snap = snaps[0]
        self.assertAlmostEqual(snap.spread_abs, 0.0003, places=6)
        self.assertAlmostEqual(snap.reference_mid, 0.00535)
        self.assertAlmostEqual(snap.spread_pct, 0.0003 / 0.00535, places=6)

    def test_summarize_pair_reports_two_sided_fraction(self):
        summary = summarize_pair(self.conn, "Monero", "Bitcoin")
        self.assertEqual(summary.n_polls, 1)
        self.assertEqual(summary.n_two_sided_polls, 1)
        self.assertEqual(summary.two_sided_fraction, 1.0)
        self.assertAlmostEqual(summary.mean_spread_pct, 0.0003 / 0.00535, places=6)

    def test_summarize_pair_with_no_data_is_empty_not_error(self):
        summary = summarize_pair(self.conn, "Litecoin", "Bitcoin")
        self.assertEqual(summary.n_polls, 0)
        self.assertIsNone(summary.mean_spread_pct)
        self.assertEqual(summary.two_sided_fraction, 0.0)


if __name__ == "__main__":
    unittest.main()

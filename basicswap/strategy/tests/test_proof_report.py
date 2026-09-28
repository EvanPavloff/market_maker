import unittest

from .. import proof_report, storage
from ..external_rates import KrakenBook
from ..proof_report import SellFill, TrialMetrics, Presence, classify

T0 = 1_790_000_000.0
MID = 0.0065  # BTC per XMR
WEEK = 7 * 86400


def _snap(conn, t, offers):
    conn.execute(
        "INSERT INTO direct_rate_snapshots (polled_at, coin_from, coin_to, coingecko_rate, kraken_rate) "
        "VALUES (?, 'Monero', 'Bitcoin', ?, NULL)", (t, MID),
    )
    for i, (cf, ct, af, at, own) in enumerate(offers):
        conn.execute(
            "INSERT INTO offer_snapshots (polled_at, offer_id, coin_from, coin_to, amount_from, amount_to, rate, "
            "is_expired, is_own_offer, is_revoked, is_public) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 1)",
            (t, f"o{i}", cf, ct, af, at, at / af, own),
        )
    conn.commit()


def _fill(conn, bid_id, t, gave, got, a_gave, a_got, side="bid", edge=0.018, m1h=0.015):
    storage.upsert_fill(
        conn, bid_id=bid_id, offer_id="x", venue="basicswap", side=side, coin_from=gave, coin_to=got,
        amount_from=a_gave, amount_to=a_got, rate=a_got / a_gave, bid_state="Completed", bid_created_at=t,
        reference_mid_at_fill=None, edge_pct_at_fill=edge, markout_1h_pct=m1h, markout_24h_pct=None, synced_at=t,
    )


def _metrics(weeks=4.0, uptime=(90, 100), fills=(), margins=()):
    m = TrialMetrics(since=T0, until=T0 + weeks * WEEK,
                     sell_presence=Presence(polls=uptime[1], live=uptime[0], best=0), restock_presence=Presence())
    m.sell_fills = [SellFill(T0, 0.5, 0.0033, None, None, "@fill", 0.001, True, mg) for mg in margins] or list(fills)
    return m


class PresenceTests(unittest.TestCase):
    def test_uptime_and_best_share(self):
        conn = storage.connect(":memory:")
        # poll 1: our XMR-sell offer cheapest; poll 2: undercut; poll 3: not live.
        _snap(conn, T0, [("Monero", "Bitcoin", 1.0, MID * 1.018, 1), ("Monero", "Bitcoin", 1.0, MID * 1.03, 0)])
        _snap(conn, T0 + 300, [("Monero", "Bitcoin", 1.0, MID * 1.018, 1), ("Monero", "Bitcoin", 1.0, MID * 1.01, 0)])
        _snap(conn, T0 + 600, [("Monero", "Bitcoin", 1.0, MID * 1.03, 0)])
        p = proof_report.presence(conn, T0, T0 + 900, "xmr", "btc")
        self.assertEqual((p.polls, p.live, p.best), (3, 2, 1))

    def test_other_direction_offers_are_ignored(self):
        conn = storage.connect(":memory:")
        _snap(conn, T0, [("Bitcoin", "Monero", 0.01, 1.5, 1)])
        p = proof_report.presence(conn, T0, T0 + 1, "xmr", "btc")
        self.assertEqual((p.polls, p.live), (1, 0))


class SellFillMarginTests(unittest.TestCase):
    def test_margin_uses_measured_kraken_cost_and_1h_basis(self):
        conn = storage.connect(":memory:")
        storage.insert_kraken_book_snapshot(conn, KrakenBook(0.00649, 0.00651, {1.0: 0.0012, 5.0: 0.002}), polled_at=T0)
        _fill(conn, "s", T0 + 60, "Monero", "Bitcoin", 0.5, 0.0033, edge=0.018, m1h=0.015)
        f = proof_report.sell_fill(conn, storage.fetch_fills(conn)[0])
        self.assertTrue(f.kraken_cost_measured)
        self.assertEqual(f.basis_label, "+1h")
        expected = 0.015 - 0.0012 - proof_report.KRAKEN_TAKER_FEE_PCT - proof_report.TRANSFER_FEE_SATS / 330_000
        self.assertAlmostEqual(f.margin_pct, expected)

    def test_falls_back_without_snapshot_or_markout(self):
        conn = storage.connect(":memory:")
        _fill(conn, "s", T0, "Monero", "Bitcoin", 2.0, 0.013, edge=0.02, m1h=None)
        f = proof_report.sell_fill(conn, storage.fetch_fills(conn)[0])
        self.assertFalse(f.kraken_cost_measured)
        self.assertEqual(f.kraken_cost_pct, proof_report.KRAKEN_FALLBACK_BUY_COST_PCT)
        self.assertEqual(f.basis_label, "@fill")


class CollectTests(unittest.TestCase):
    def test_splits_legs_and_respects_window(self):
        conn = storage.connect(":memory:")
        _fill(conn, "sell", T0 + 10, "Monero", "Bitcoin", 0.5, 0.0033)
        _fill(conn, "restock", T0 + 20, "Bitcoin", "Monero", 0.003, 0.466, side="ask")
        _fill(conn, "taker", T0 + 30, "Bitcoin", "Monero", 0.001, 0.15, side="taker")
        _fill(conn, "before", T0 - 10, "Monero", "Bitcoin", 0.5, 0.0033)
        m = proof_report.collect(conn, T0, T0 + WEEK, btc_per_xmr_now=MID)
        self.assertEqual((len(m.sell_fills), len(m.restock_fills), len(m.taker_fills)), (1, 1, 1))
        flows_btc = 0.0033 - 0.003 - 0.001
        flows_xmr = -0.5 + 0.466 + 0.15
        self.assertAlmostEqual(m.net_sats, (flows_btc + flows_xmr * MID) * 1e8, places=3)


class ClassifyTests(unittest.TestCase):
    def test_low_uptime_is_inconclusive_not_pessimistic(self):
        verdict, _ = classify(_metrics(uptime=(10, 100)))
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_negative_margin_over_enough_fills_is_pessimistic_even_with_low_uptime(self):
        verdict, _ = classify(_metrics(uptime=(10, 100), margins=(-0.01,) * 4))
        self.assertEqual(verdict, "PESSIMISTIC")

    def test_too_few_fills_after_four_weeks_is_pessimistic(self):
        verdict, _ = classify(_metrics(margins=(0.01,)))
        self.assertEqual(verdict, "PESSIMISTIC")

    def test_optimistic_needs_rate_count_and_margin(self):
        self.assertEqual(classify(_metrics(margins=(0.009,) * 8))[0], "OPTIMISTIC")
        self.assertEqual(classify(_metrics(margins=(0.005,) * 8))[0], "BASE")

    def test_middle_is_base(self):
        self.assertEqual(classify(_metrics(margins=(0.004,) * 3))[0], "BASE")

    def test_provisional_before_four_weeks(self):
        verdict, _ = classify(_metrics(weeks=1.0, margins=(0.009,) * 2))
        self.assertTrue(verdict.startswith("PROVISIONAL "))

    def test_report_renders(self):
        text = proof_report.report(_metrics(margins=(0.009,) * 8))
        self.assertIn("VERDICT: OPTIMISTIC", text)
        self.assertIn("projection for a $5k pot", text)


if __name__ == "__main__":
    unittest.main()

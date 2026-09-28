import unittest

from .. import fill_ledger, storage

T0 = 1_789_749_048.0  # real 2026-09-18 ask fill


def _bid(bid_id, offer_id, state="Completed", t=T0):
    return {
        "bid_id": bid_id, "offer_id": offer_id, "bid_state": state, "created_at": t,
        "coin_from": "Bitcoin", "coin_to": "Monero",
        "amount_from": "0.00800000", "amount_to": "1.089356406320", "bid_rate": "136.16955079",
    }


class FillLedgerTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.conn.execute(
            "INSERT INTO live_quote_events (created_at, coin_from, coin_to, side, action, offer_id, "
            "amount_from, new_rate, reference_mid) VALUES (?, 'Bitcoin', 'Monero', 'ask', 'post', 'own', 0.008, 136.17, 135.28)",
            (T0 - 400,),
        )
        # Stored as BTC per XMR (Monero->Bitcoin), under both naming conventions.
        for dt, cg, kr, cf, ct in (
            (15, 1 / 136.65, 1 / 136.35, "Monero", "Bitcoin"),
            (3600, 1 / 145.0, None, "xmr", "btc"),
        ):
            self.conn.execute(
                "INSERT INTO direct_rate_snapshots (polled_at, coin_from, coin_to, coingecko_rate, kraken_rate) "
                "VALUES (?, ?, ?, ?, ?)", (T0 + dt, cf, ct, cg, kr),
            )
        self.conn.commit()

    def test_reference_mid_inverts_stored_direction(self):
        mid = fill_ledger.reference_mid(self.conn, T0, "btc", "xmr")
        self.assertAlmostEqual(mid, 136.5, delta=0.05)

    def test_reference_mid_none_when_too_far(self):
        self.assertIsNone(fill_ledger.reference_mid(self.conn, T0 + 3 * 86400, "btc", "xmr"))

    def test_reference_mid_falls_back_to_live_quote_events(self):
        self.conn.execute("DELETE FROM direct_rate_snapshots")
        self.assertAlmostEqual(fill_ledger.reference_mid(self.conn, T0, "Bitcoin", "Monero"), 135.28)

    def test_sync_only_own_offers_and_computes_edges(self):
        n = fill_ledger.sync(
            self.conn,
            [_bid("b1", "own"), _bid("b2", "someone_else"), _bid("b3", "own", state="Expired", t=T0 + 60)],
            now=T0 + 2 * 3600,
        )
        self.assertEqual(n, 2)
        rows = {r["bid_id"]: r for r in storage.fetch_fills(self.conn)}
        self.assertEqual(set(rows), {"b1", "b3"})
        self.assertAlmostEqual(rows["b1"]["edge_pct_at_fill"], -0.0024, delta=0.0005)
        self.assertAlmostEqual(rows["b1"]["markout_1h_pct"], 136.17 / 145.0 - 1, delta=0.0005)
        self.assertIsNone(rows["b1"]["markout_24h_pct"])  # horizon not elapsed yet
        self.assertIsNone(rows["b3"]["edge_pct_at_fill"])  # expiries carry no P&L
        self.assertEqual(rows["b1"]["side"], "ask")

    def test_resync_does_not_erase_computed_markout(self):
        fill_ledger.sync(self.conn, [_bid("b1", "own")], now=T0 + 2 * 3600)
        self.conn.execute("DELETE FROM direct_rate_snapshots")
        fill_ledger.sync(self.conn, [_bid("b1", "own")], now=T0 + 3 * 3600)
        row = storage.fetch_fills(self.conn)[0]
        self.assertIsNotNone(row["markout_1h_pct"])

    def test_report_summarizes(self):
        fill_ledger.sync(self.conn, [_bid("b1", "own")], now=T0 + 2 * 3600)
        out = fill_ledger.report(self.conn)
        self.assertIn("mean edge @fill", out)
        self.assertIn("{'Completed': 1}", out)



    def test_pnl_btc_giving_btc(self):
        # Gave 0.008 BTC at -0.24% edge -> lost 0.008 * 0.0024 BTC = 1,920 sats.
        self.assertAlmostEqual(fill_ledger.pnl_btc("Bitcoin", "Monero", 0.008, 1.0893, -0.0024), -0.0000192)

    def test_pnl_btc_receiving_btc_matches_direct_computation(self):
        a_from, a_to, mid = 1.09758672, 0.00750848, 0.00690  # mid = BTC per XMR
        edge = fill_ledger.edge_pct(a_from, a_to, mid)
        self.assertAlmostEqual(fill_ledger.pnl_btc("Monero", "Bitcoin", a_from, a_to, edge), a_to - a_from * mid)

    def test_pnl_btc_none_without_btc_leg_or_edge(self):
        self.assertIsNone(fill_ledger.pnl_btc("Monero", "Litecoin", 1.0, 1.0, 0.01))
        self.assertIsNone(fill_ledger.pnl_btc("Bitcoin", "Monero", 1.0, 1.0, None))

    def test_net_flows_only_completed(self):
        fill_ledger.sync(self.conn, [_bid("b1", "own"), _bid("b3", "own", state="Expired", t=T0 + 60)], now=T0 + 2 * 3600)
        flows = fill_ledger.net_flows(storage.fetch_fills(self.conn))
        self.assertAlmostEqual(flows["Bitcoin"], -0.008)
        self.assertAlmostEqual(flows["Monero"], 1.089356406320)

    def test_report_btc_numeraire_sections(self):
        fill_ledger.sync(self.conn, [_bid("b1", "own")], now=T0 + 2 * 3600)
        out = fill_ledger.report(self.conn, lambda t: 100_000.0, {"Monero": 1 / 140.0}, 100_000.0)
        self.assertIn("total sats @fill", out)
        self.assertIn("100,000", out)
        # -0.008 BTC + 1.089356 XMR / 140 = -0.00021889 BTC -> -21,888 sats
        self.assertIn("net: -21,888 sats", out)

    def test_report_without_prices_prints_na(self):
        fill_ledger.sync(self.conn, [_bid("b1", "own")], now=T0 + 2 * 3600)
        out = fill_ledger.report(self.conn)
        self.assertIn("net: n/a", out)


if __name__ == "__main__":
    unittest.main()

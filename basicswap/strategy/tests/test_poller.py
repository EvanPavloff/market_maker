import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from .. import poller, storage

CONFIG = SimpleNamespace(pairs=[("xmr", "btc")])


def _client(wallets, bids=(), sent=()):
    c = MagicMock()
    c.get_wallets.return_value = wallets
    c.get_bids.return_value = list(bids)
    c.get_sent_bids.return_value = list(sent)
    return c


class SnapshotWalletsTests(unittest.TestCase):
    def test_records_balances_and_counts_in_flight_swaps(self):
        conn = storage.connect(":memory:")
        storage.insert_exolix_swap(conn, {
            "exolix_id": "e1", "created_at": 1.0, "updated_at": 1.0, "status": "sent", "amount_btc": 0.003,
            "quoted_xmr": 0.4, "reference_mid": 0.007, "all_in_premium_pct": 0.006,
            "deposit_address": "d", "withdrawal_address": "w",
        })
        client = _client(
            {"BTC": {"balance": "0.0078", "unconfirmed": "0.0001"}, "XMR": {"balance": "0.43", "unconfirmed": "0"},
             "PART": {"balance": "0"}},
            bids=[{"bid_state": "Completed"}, {"bid_state": "Script coin locked"}],
            sent=[{"bid_state": "Expired"}],
        )
        poller.snapshot_wallets(client, conn, CONFIG, 100.0)
        rows = conn.execute("SELECT coin, balance, unconfirmed, active_swaps FROM wallet_snapshots ORDER BY coin").fetchall()
        self.assertEqual(rows, [("Bitcoin", 0.0078, 0.0001, 2), ("Monero", 0.43, 0.0, 2)])
        self.assertIsNone(storage.latest_clean_wallet_snapshot(conn, ("Bitcoin", "Monero")))

    def test_missing_balance_key_raises_for_poll_once_to_catch(self):
        # 2026-09-19: /json/wallets once returned an XMR entry with no "balance".
        conn = storage.connect(":memory:")
        client = _client({"BTC": {"balance": "0.0078"}, "XMR": {"unconfirmed": "0"}})
        with self.assertRaises(KeyError):
            poller.snapshot_wallets(client, conn, CONFIG, 100.0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM wallet_snapshots").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

import sqlite3
import unittest

from .. import storage
from ..offer_book import NormalizedOffer


def _offer(**overrides):
    defaults = dict(
        venue="bisq",
        offer_id="o1",
        coin_from="xmr",
        coin_to="btc",
        amount_from=1.0,
        amount_to=0.007,
        implied_rate=0.007,
        expire_at=None,
        min_bid_amount=0.5,
        is_own_offer=False,
    )
    defaults.update(overrides)
    return NormalizedOffer(**defaults)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(storage._SCHEMA)

    def test_insert_and_fetch_round_trip(self):
        n = storage.insert_offer_snapshots(self.conn, [_offer()], polled_at=100.0)
        self.assertEqual(n, 1)
        rows = storage.fetch_offer_snapshots(self.conn, "bisq", "xmr", "btc")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["venue"], "bisq")
        self.assertEqual(row["offer_id"], "o1")
        self.assertAlmostEqual(row["implied_rate"], 0.007)
        self.assertEqual(row["is_own_offer"], 0)

    def test_fetch_filters_by_venue_and_pair(self):
        storage.insert_offer_snapshots(self.conn, [_offer(venue="bisq")], polled_at=100.0)
        storage.insert_offer_snapshots(
            self.conn, [_offer(venue="eigen_asb", offer_id="o2")], polled_at=100.0
        )
        storage.insert_offer_snapshots(
            self.conn,
            [_offer(coin_from="ltc", coin_to="btc", offer_id="o3")],
            polled_at=100.0,
        )
        rows = storage.fetch_offer_snapshots(self.conn, "bisq", "xmr", "btc")
        self.assertEqual([r["offer_id"] for r in rows], ["o1"])

    def test_fetch_since_filters_by_time(self):
        storage.insert_offer_snapshots(self.conn, [_offer(offer_id="old")], polled_at=100.0)
        storage.insert_offer_snapshots(self.conn, [_offer(offer_id="new")], polled_at=200.0)
        rows = storage.fetch_offer_snapshots(self.conn, "bisq", "xmr", "btc", since=150.0)
        self.assertEqual([r["offer_id"] for r in rows], ["new"])


if __name__ == "__main__":
    unittest.main()

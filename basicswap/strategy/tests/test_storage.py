import json
import unittest
from pathlib import Path

from .. import storage

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")

    def test_insert_and_fetch_offer_snapshots(self):
        offers = _load("offers_xmr_to_btc.json")
        n = storage.insert_offer_snapshots(self.conn, offers, polled_at=100.0)
        self.assertEqual(n, 3)

        rows = storage.fetch_offer_snapshots(self.conn, "Monero", "Bitcoin")
        self.assertEqual(len(rows), 3)
        by_id = {r["offer_id"]: r for r in rows}
        self.assertAlmostEqual(by_id["aa11"]["rate"], 0.0055)
        self.assertEqual(by_id["aa33-revoked"]["is_revoked"], 1)

    def test_fetch_respects_since(self):
        offers = _load("offers_xmr_to_btc.json")
        storage.insert_offer_snapshots(self.conn, offers, polled_at=100.0)
        storage.insert_offer_snapshots(self.conn, offers, polled_at=200.0)

        rows = storage.fetch_offer_snapshots(self.conn, "Monero", "Bitcoin", since=150.0)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["polled_at"] == 200.0 for r in rows))

    def test_insert_and_fetch_rate_snapshot(self):
        rate_response = _load("rate_xmr_btc.json")
        storage.insert_rate_snapshot(self.conn, "xmr", "btc", rate_response, polled_at=100.0)

        rows = storage.fetch_rate_snapshots(self.conn, "xmr", "btc")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["rate"], 0.00535)
        self.assertEqual(json.loads(rows[0]["raw_json"]), rate_response)

    def test_rate_snapshot_survives_source_failure(self):
        # Real shape when every rate source fails (basicswap.py lookupRates,
        # output_array branch) — still stored, just with rate=None.
        storage.insert_rate_snapshot(
            self.conn, "xmr", "btc", [["coingecko.com", "error", "6"]], polled_at=1.0
        )
        rows = storage.fetch_rate_snapshots(self.conn, "xmr", "btc")
        self.assertIsNone(rows[0]["rate"])


if __name__ == "__main__":
    unittest.main()

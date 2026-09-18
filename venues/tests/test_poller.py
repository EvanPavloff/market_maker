import sqlite3
import unittest
from unittest import mock

from .. import storage
from ..config import Config
from ..offer_book import NormalizedOffer
from ..poller import _build_readers, poll_once


def _offer(coin_from, coin_to, offer_id):
    return NormalizedOffer(
        venue="fake",
        offer_id=offer_id,
        coin_from=coin_from,
        coin_to=coin_to,
        amount_from=1.0,
        amount_to=1.0,
        implied_rate=1.0,
        expire_at=None,
        min_bid_amount=None,
        is_own_offer=False,
    )


class TestPollOnce(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(storage._SCHEMA)
        self.config = Config(venues=["fake"], pairs=[("xmr", "btc")])

    def test_polls_both_directions_and_stores_results(self):
        reader = mock.MagicMock()
        reader.list_public_offers.side_effect = lambda a, b: [_offer(a, b, f"{a}-{b}")]
        poll_once({"fake": reader}, self.conn, self.config)

        self.assertEqual(
            sorted(reader.list_public_offers.call_args_list),
            sorted([mock.call("xmr", "btc"), mock.call("btc", "xmr")]),
        )
        rows = self.conn.execute("SELECT offer_id FROM venue_offer_snapshots").fetchall()
        self.assertEqual(sorted(r[0] for r in rows), ["btc-xmr", "xmr-btc"])

    def test_one_direction_failing_does_not_block_the_other(self):
        reader = mock.MagicMock()

        def side_effect(a, b):
            if (a, b) == ("xmr", "btc"):
                raise RuntimeError("boom")
            return [_offer(a, b, f"{a}-{b}")]

        reader.list_public_offers.side_effect = side_effect
        poll_once({"fake": reader}, self.conn, self.config)

        rows = self.conn.execute("SELECT offer_id FROM venue_offer_snapshots").fetchall()
        self.assertEqual([r[0] for r in rows], ["btc-xmr"])


class TestBuildReaders(unittest.TestCase):
    def test_unregistered_venue_is_skipped_not_fatal(self):
        readers = _build_readers(["bisq", "not_a_real_venue"])
        self.assertEqual(list(readers), ["bisq"])


if __name__ == "__main__":
    unittest.main()

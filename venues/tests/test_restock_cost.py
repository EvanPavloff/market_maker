import unittest

from ..restock_cost import BUCKET_SECONDS, Offer, all_in_premium, compute, walk_book


class TestWalkBook(unittest.TestCase):
    def test_takes_cheapest_first_and_vwaps(self):
        offers = [Offer(0.0070, 1.0, 0.0), Offer(0.0060, 0.2, 0.0), Offer(0.0065, 0.2, 0.0)]
        # 0.2 @ 0.0060 + 0.2 @ 0.0065 + 0.1 @ 0.0070
        self.assertAlmostEqual(walk_book(offers, 0.5), (0.0012 + 0.0013 + 0.0007) / 0.5)

    def test_insufficient_depth_returns_none(self):
        self.assertIsNone(walk_book([Offer(0.0064, 0.3, 0.0)], 0.5))

    def test_skips_offer_whose_minimum_overshoots(self):
        offers = [Offer(0.0060, 2.0, 1.0), Offer(0.0066, 1.0, 0.0)]
        self.assertAlmostEqual(walk_book(offers, 0.5), 0.0066)

    def test_zero_size_offer_is_ignored(self):
        # Eigen ASBs quoting 0/0 min/max (eigen_asb/reader.py docstring).
        offers = [Offer(0.0050, 0.0, 0.0), Offer(0.0066, 1.0, 0.0)]
        self.assertAlmostEqual(walk_book(offers, 0.5), 0.0066)

    def test_size_flexible_quote_fills_any_target(self):
        self.assertAlmostEqual(walk_book([Offer(0.0064, 0.49, 0.0)], 0.5, size_flexible=True), 0.0064)


class TestAllInPremium(unittest.TestCase):
    def test_adds_pct_and_flat_fees(self):
        mid = 0.0064
        # bisq: 0.8625% + 1,000 sats over 0.5 * 0.0064 BTC = 320,000 sats
        got = all_in_premium("bisq", mid * 1.02, mid, 0.5)
        self.assertAlmostEqual(got, 0.02 + 0.008625 + 1000 / 320_000)


class TestCompute(unittest.TestCase):
    def test_ranks_venues_and_adds_kraken_baseline(self):
        t = 100 * BUCKET_SECONDS + 10
        mid = 0.0064
        kraken = [(t, mid, 0.001, 0.003)]
        books = {
            ("exolix", 100): [Offer(mid * 1.005, 0.5, 0.0)],
            ("bisq", 100): [Offer(mid * 1.02, 1.0, 0.0)],
            ("eigen_asb", 100): [Offer(mid * 1.01, 0.1, 0.0)],  # can't fill 0.5
        }
        stats, n = compute(books, kraken, 0.5)
        self.assertEqual(n, 1)
        self.assertEqual(stats["exolix"].cheapest, 1)
        self.assertEqual(stats["eigen_asb"].filled, [])
        self.assertAlmostEqual(stats["kraken"].filled[0], 0.001 + 0.004 + 1650 / 320_000)

    def test_cycle_without_kraken_mid_is_dropped(self):
        stats, n = compute({("bisq", 5): [Offer(0.0064, 1.0, 0.0)]}, [], 0.5)
        self.assertEqual((stats, n), ({}, 0))


if __name__ == "__main__":
    unittest.main()

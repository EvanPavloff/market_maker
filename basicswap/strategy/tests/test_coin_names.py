import unittest

from .. import coin_names


class ToDisplayNameTests(unittest.TestCase):
    def test_known_tickers_map_to_basicswap_display_names(self):
        self.assertEqual(coin_names.to_display_name("xmr"), "Monero")
        self.assertEqual(coin_names.to_display_name("btc"), "Bitcoin")
        self.assertEqual(coin_names.to_display_name("BTC"), "Bitcoin")
        self.assertEqual(coin_names.to_display_name("bch"), "Bitcoin Cash")
        self.assertEqual(coin_names.to_display_name("pivx"), "PIVX")

    def test_unmapped_input_passes_through_unchanged(self):
        self.assertEqual(coin_names.to_display_name("Monero"), "Monero")
        self.assertEqual(coin_names.to_display_name("SomeNewCoin"), "SomeNewCoin")


if __name__ == "__main__":
    unittest.main()

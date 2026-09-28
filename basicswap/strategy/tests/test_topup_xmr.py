import unittest
from unittest.mock import MagicMock, patch

from ..external_rates import ReferenceRate
from ..topup_xmr import plan_topup


def _rate(mid=0.0066, disagreement=None):
    return ReferenceRate(coin_from="xmr", coin_to="btc", coingecko_rate=mid, kraken_rate=None,
                         disagreement_pct=disagreement, coingecko_error=None, kraken_error=None)


def _offer(rate, amount="1.0", min_bid="0.1", oid="o1"):
    return {"offer_id": oid, "rate": str(rate), "amount_from": amount, "min_bid_amount": min_bid,
            "is_own_offer": False, "is_expired": False, "is_revoked": False}


@patch("strategy.topup_xmr.external_rates.get_usd_price", return_value=500.0)
@patch("strategy.topup_xmr.external_rates.get_reference_rate", return_value=_rate())
class PlanTopupTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.get_bids.return_value = []
        self.client.get_wallet_balance.side_effect = lambda c: {"xmr": 0.2, "btc": 0.01}[c]

    def _plan(self, **kw):
        args = dict(target_usd=210.0, max_premium_pct=0.03, buffer_pct=0.05,
                    max_source_disagreement_pct=0.015)
        args.update(kw)
        return plan_topup(self.client, **args)

    def test_no_topup_when_already_above_target(self, *_):
        self.client.get_wallet_balance.side_effect = lambda c: {"xmr": 0.5, "btc": 0.01}[c]
        self.assertEqual(self._plan()["action"], "none")

    def test_aborts_while_a_monero_to_bitcoin_swap_is_in_flight(self, *_):
        self.client.get_bids.return_value = [
            {"bid_id": "x" * 56, "bid_state": "Script coin locked", "coin_from": "Monero", "coin_to": "Bitcoin"}
        ]
        plan = self._plan()
        self.assertEqual(plan["action"], "abort")
        self.assertIn("in-flight", plan["reason"])

    def test_picks_cheapest_offer_that_fits_within_premium_cap(self, *_):
        self.client.get_offers.return_value = [
            _offer(0.0066 * 1.01, amount="0.1", oid="too_small"),
            _offer(0.0066 * 1.05, oid="too_pricey"),
            _offer(0.0066 * 1.02, oid="ok"),
        ]
        plan = self._plan()
        self.assertEqual(plan["action"], "bid")
        self.assertEqual(plan["offer"]["offer_id"], "ok")
        # (210/500 - 0.2) * 1.05 = 0.231
        self.assertAlmostEqual(plan["need_xmr"], 0.231)

    def test_aborts_when_btc_wallet_cannot_cover(self, *_):
        self.client.get_wallet_balance.side_effect = lambda c: {"xmr": 0.2, "btc": 0.0001}[c]
        self.client.get_offers.return_value = [_offer(0.0066 * 1.02)]
        self.assertEqual(self._plan()["action"], "abort")

    def test_aborts_when_nothing_under_cap(self, *_):
        self.client.get_offers.return_value = [_offer(0.0066 * 1.05)]
        self.assertEqual(self._plan()["action"], "abort")

    def test_aborts_on_source_disagreement(self, mock_rate, _):
        mock_rate.return_value = _rate(disagreement=0.05)
        self.assertEqual(self._plan()["action"], "abort")
        self.client.get_offers.assert_not_called()


if __name__ == "__main__":
    unittest.main()

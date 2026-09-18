import unittest

from ..analysis import PairSummary
from ..economics import (
    CostAssumptions,
    evaluate_pair,
    expected_apy,
    required_spread_pct,
    vol_buffer_pct_for_hours,
)


def _summary(**overrides) -> PairSummary:
    defaults = dict(
        coin_from="Monero",
        coin_to="Bitcoin",
        n_polls=200,
        n_two_sided_polls=200,
        two_sided_fraction=1.0,
        mean_spread_pct=0.02,
        median_spread_pct=0.02,
        mean_ask_depth_count=10.0,
        mean_bid_depth_count=10.0,
    )
    defaults.update(overrides)
    return PairSummary(**defaults)


class RequiredSpreadPctTests(unittest.TestCase):
    def test_combines_fee_vol_and_margin(self):
        # $1.00 fee on $1000 notional = 0.1%, plus 5% vol buffer, plus 1% margin.
        req = required_spread_pct(1000.0, 1.00, 0.05, 0.01)
        self.assertAlmostEqual(req, 0.001 + 0.05 + 0.01)

    def test_fee_dominates_on_small_notional(self):
        small = required_spread_pct(50.0, 1.00, 0.0, 0.0)
        large = required_spread_pct(50_000.0, 1.00, 0.0, 0.0)
        self.assertGreater(small, large)

    def test_rejects_non_positive_notional(self):
        with self.assertRaises(ValueError):
            required_spread_pct(0.0, 1.0, 0.05, 0.01)


class EvaluatePairTests(unittest.TestCase):
    def test_wide_spread_large_notional_clears_every_scenario(self):
        # 20% observed spread on a $10k trade should clear even the stressed-fee,
        # 2-sigma bar (stressed fee is negligible pct-wise at this notional).
        summary = _summary(median_spread_pct=0.20)
        verdict = evaluate_pair(summary, notional_usd=10_000.0)
        self.assertTrue(all(verdict.clears.values()))
        self.assertEqual(verdict.notes, [])  # 200 polls, fully two-sided — no caveats

    def test_thin_spread_small_notional_fails_every_scenario(self):
        # A spread barely above zero on a $50 trade can't cover even the cheap
        # fee scenario once the vol buffer's added.
        summary = _summary(median_spread_pct=0.001)
        verdict = evaluate_pair(summary, notional_usd=50.0)
        self.assertFalse(any(verdict.clears.values()))

    def test_one_sided_market_flagged_regardless_of_spread(self):
        summary = _summary(two_sided_fraction=0.1, median_spread_pct=0.20)
        verdict = evaluate_pair(summary, notional_usd=10_000.0)
        self.assertTrue(any("two-sided fraction" in n for n in verdict.notes))

    def test_no_data_yields_no_verdict(self):
        summary = _summary(n_polls=0, two_sided_fraction=0.0, median_spread_pct=None, mean_spread_pct=None)
        verdict = evaluate_pair(summary, notional_usd=1000.0)
        self.assertTrue(verdict.insufficient_data)
        self.assertTrue(all(v is None for v in verdict.clears.values()))

    def test_few_polls_gets_a_sample_size_caveat(self):
        summary = _summary(n_polls=4, n_two_sided_polls=4)
        verdict = evaluate_pair(summary, notional_usd=1000.0)
        self.assertTrue(any("only 4 poll" in n for n in verdict.notes))

    def test_custom_assumptions_are_respected(self):
        summary = _summary(median_spread_pct=0.10)
        strict = CostAssumptions(min_profit_margin_pct=0.5)  # impossible to clear
        verdict = evaluate_pair(summary, notional_usd=10_000.0, assumptions=strict)
        self.assertFalse(any(verdict.clears.values()))

    def test_lock_hours_shrinks_vol_buffer_vs_24h_default(self):
        # A ~0.7h real measured exposure window (2026-09-17 test swap) should
        # require a far smaller spread than the 24h UI-ceiling default.
        summary = _summary(median_spread_pct=0.02)
        default_verdict = evaluate_pair(summary, notional_usd=10_000.0)
        short_verdict = evaluate_pair(summary, notional_usd=10_000.0, lock_hours=0.708)
        self.assertLess(
            short_verdict.required_spread_pct["today_1sigma"],
            default_verdict.required_spread_pct["today_1sigma"],
        )
        self.assertTrue(any("0.708h lock window" in n for n in short_verdict.notes))

    def test_lock_hours_matches_helper_directly(self):
        summary = _summary(median_spread_pct=0.02)
        verdict = evaluate_pair(summary, notional_usd=10_000.0, lock_hours=1.0)
        assumptions = CostAssumptions()
        fee_today = (
            assumptions.fee_round_trip_usd_today_low + assumptions.fee_round_trip_usd_today_high
        ) / 2
        expected_req = required_spread_pct(
            10_000.0,
            fee_today,
            vol_buffer_pct_for_hours(1.0, sigma=1),
            assumptions.min_profit_margin_pct,
        )
        self.assertAlmostEqual(verdict.required_spread_pct["today_1sigma"], expected_req)


class ExpectedApyTests(unittest.TestCase):
    def _verdict(self, median_spread_pct=0.02, notional_usd=10_000.0):
        summary = _summary(median_spread_pct=median_spread_pct)
        return evaluate_pair(summary, notional_usd=notional_usd)

    def test_more_frequent_fills_yield_higher_apy_for_a_positive_edge(self):
        verdict = self._verdict()
        monthly = expected_apy(verdict, fills_per_year=12)
        weekly = expected_apy(verdict, fills_per_year=52)
        self.assertGreater(weekly.apy_compound_raw, monthly.apy_compound_raw)

    def test_negative_edge_never_returns_below_total_loss(self):
        # Required spread on a $50 notional swamps a 2% observed spread —
        # risk-adjusted edge goes deeply negative; compounding that shouldn't
        # raise or produce a nonsensical value, just floor at -100%.
        verdict = self._verdict(median_spread_pct=0.02, notional_usd=50.0)
        apy = expected_apy(verdict, fills_per_year=365, scenario="stressed_2sigma")
        self.assertLess(apy.risk_adjusted_edge_pct, 0)
        self.assertEqual(apy.apy_compound_risk_adjusted, -1.0)

    def test_rejects_unknown_scenario(self):
        verdict = self._verdict()
        with self.assertRaises(ValueError):
            expected_apy(verdict, fills_per_year=52, scenario="not_a_real_scenario")

    def test_rejects_non_positive_fills(self):
        verdict = self._verdict()
        with self.assertRaises(ValueError):
            expected_apy(verdict, fills_per_year=0)

    def test_rejects_insufficient_data(self):
        summary = _summary(n_polls=0, two_sided_fraction=0.0, median_spread_pct=None, mean_spread_pct=None)
        verdict = evaluate_pair(summary, notional_usd=1000.0)
        with self.assertRaises(ValueError):
            expected_apy(verdict, fills_per_year=52)

    def test_raw_edge_ignores_vol_buffer_risk_adjusted_includes_it(self):
        # Raw edge only nets out the fee; risk-adjusted edge also nets out the
        # vol buffer + margin, so it should always be <= raw edge here.
        verdict = self._verdict()
        apy = expected_apy(verdict, fills_per_year=52, scenario="today_1sigma")
        self.assertLessEqual(apy.risk_adjusted_edge_pct, apy.raw_edge_pct)


if __name__ == "__main__":
    unittest.main()

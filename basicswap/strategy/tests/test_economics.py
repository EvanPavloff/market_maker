import math
import unittest

from ..analysis import PairSummary
from ..economics import (
    ANNUALIZED_CROSS_VOL_PCT,
    CostAssumptions,
    dynamic_half_spread_pct,
    evaluate_pair,
    evaluate_pair_sats,
    expected_apy,
    live_annualized_vol_pct,
    required_spread_pct,
    restock_half_spread_pct,
    sell_leg_half_spread_pct,
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


class LiveAnnualizedVolPctTests(unittest.TestCase):
    """market_maker/next_steps.md #15 Phase A."""

    def test_matches_manual_sqrt_time_scaling(self):
        # A 0.3% move over a 900s (15-minute) window.
        result = live_annualized_vol_pct(0.003, 900.0)
        window_years = 900.0 / (24 * 3600 * 365)
        self.assertAlmostEqual(result, 0.003 / math.sqrt(window_years))

    def test_zero_window_vol_is_zero_annualized(self):
        self.assertEqual(live_annualized_vol_pct(0.0, 900.0), 0.0)

    def test_rejects_non_positive_window(self):
        with self.assertRaises(ValueError):
            live_annualized_vol_pct(0.003, 0.0)

    def test_roundtrips_through_vol_buffer_pct_for_hours(self):
        # Scaling an annualized figure down to a window with vol_buffer_pct_for_hours
        # and then back up with live_annualized_vol_pct should reproduce the input
        # annualized vol -- the two functions are meant to be inverses of each other.
        annualized = 0.90
        hours = 6.0
        buffer_pct = vol_buffer_pct_for_hours(hours, sigma=1, annualized_vol_pct=annualized)
        self.assertAlmostEqual(
            live_annualized_vol_pct(buffer_pct, hours * 3600), annualized
        )


class DynamicHalfSpreadPctTests(unittest.TestCase):
    """market_maker/next_steps.md #15 Phase A."""

    def test_never_returns_below_the_operator_floor(self):
        # Calm/no volatility data -> required spread should be tiny relative to a
        # generous floor, so the floor wins.
        result = dynamic_half_spread_pct(
            operator_floor_pct=0.5,  # absurdly high floor, guarantees it dominates
            notional_usd=880.0,
            lock_hours=2.5,
            live_vol_pct=0.0022,
            live_vol_window_seconds=900.0,
        )
        self.assertEqual(result, 0.5)

    def test_high_volatility_widens_spread_above_the_floor(self):
        low_vol = dynamic_half_spread_pct(
            operator_floor_pct=0.02,
            notional_usd=880.0,
            lock_hours=2.5,
            live_vol_pct=0.0022,  # ~p50 per volatility.py's real calibration
            live_vol_window_seconds=900.0,
        )
        high_vol = dynamic_half_spread_pct(
            operator_floor_pct=0.02,
            notional_usd=880.0,
            lock_hours=2.5,
            live_vol_pct=0.0084,  # ~p99, just under the kill-switch's own default threshold
            live_vol_window_seconds=900.0,
        )
        self.assertEqual(low_vol, 0.02)  # calm reading -> floor wins
        self.assertGreater(high_vol, 0.02)  # elevated reading -> computed value wins

    def test_no_live_vol_data_falls_back_to_static_annualized_assumption(self):
        result = dynamic_half_spread_pct(
            operator_floor_pct=0.0,  # floor of zero isolates the computed value
            notional_usd=10_000.0,
            lock_hours=24.0,
            live_vol_pct=None,
            live_vol_window_seconds=None,
        )
        assumptions = CostAssumptions()
        fee_today = (
            assumptions.fee_round_trip_usd_today_low + assumptions.fee_round_trip_usd_today_high
        ) / 2
        expected = required_spread_pct(
            10_000.0,
            fee_today,
            vol_buffer_pct_for_hours(24.0, sigma=1, annualized_vol_pct=ANNUALIZED_CROSS_VOL_PCT),
            assumptions.min_profit_margin_pct,
        )
        self.assertAlmostEqual(result, expected)

    def test_rejects_non_positive_notional(self):
        with self.assertRaises(ValueError):
            dynamic_half_spread_pct(
                operator_floor_pct=0.02,
                notional_usd=0.0,
                lock_hours=2.5,
                live_vol_pct=None,
                live_vol_window_seconds=None,
            )



class SatsNumeraireTests(unittest.TestCase):
    def test_default_sats_fees_derived_from_vbytes(self):
        a = CostAssumptions()
        self.assertAlmostEqual(a.fee_round_trip_sats_today, (300 * 1 + 500 * 2) / 2)
        self.assertAlmostEqual(a.fee_round_trip_sats_stressed, (300 * 25 + 500 * 2 * 50) / 2)

    def test_sats_verdict_uses_sats_fee_over_sats_notional(self):
        a = CostAssumptions()
        verdict = evaluate_pair_sats(_summary(), notional_sats=800_000.0)
        self.assertEqual(verdict.notional_unit, "sats")
        expected = a.fee_round_trip_sats_today / 800_000.0 + a.vol_buffer_pct_1sigma_24h + a.min_profit_margin_pct
        self.assertAlmostEqual(verdict.required_spread_pct["today_1sigma"], expected)

    def test_sats_and_usd_verdicts_agree_at_matching_btc_price(self):
        # 650 sats today-fee == $1.00 USD today-fee only at BTC/USD ~153,846 — at
        # that price the two numeraires must give the same required spread.
        a = CostAssumptions()
        btc_usd = a.fee_round_trip_usd_today / (a.fee_round_trip_sats_today / 1e8)
        sats = evaluate_pair_sats(_summary(), notional_sats=1_000_000.0)
        usd = evaluate_pair(_summary(), notional_usd=0.01 * btc_usd)
        self.assertAlmostEqual(sats.required_spread_pct["today_1sigma"], usd.required_spread_pct["today_1sigma"])

    def test_expected_apy_on_sats_verdict_uses_sats_fee(self):
        verdict = evaluate_pair_sats(_summary(median_spread_pct=0.03), notional_sats=650_000.0)
        apy = expected_apy(verdict, fills_per_year=10)
        self.assertAlmostEqual(apy.raw_edge_pct, 0.03 - 0.001)


class BtcObjectiveSpreadTests(unittest.TestCase):
    """2026-09-28 accumulate-BTC objective: sats-native spread + restock pricing."""

    VOL_2_5H = ANNUALIZED_CROSS_VOL_PCT * math.sqrt(2.5 / (24 * 365))

    def test_sell_leg_quotes_target_premium_at_baseline_vol(self):
        self.assertEqual(sell_leg_half_spread_pct(0.018, 2.5, None, None), 0.018)

    def test_sell_leg_never_narrows_below_target_when_calm(self):
        self.assertEqual(sell_leg_half_spread_pct(0.018, 2.5, 0.0001, 900), 0.018)

    def test_sell_leg_widens_by_excess_vol_only(self):
        live = live_annualized_vol_pct(0.02, 900)
        excess = vol_buffer_pct_for_hours(2.5, 1.0, live) - self.VOL_2_5H
        self.assertAlmostEqual(sell_leg_half_spread_pct(0.018, 2.5, 0.02, 900), 0.018 + excess)

    def test_round_trip_charged_once_across_both_legs(self):
        premium = 0.018
        sell = sell_leg_half_spread_pct(premium, 2.5, None, None)
        restock = restock_half_spread_pct(0.0001, 800_000, 2.5, premium, None, None)
        self.assertAlmostEqual(sell + restock, 2 * 650 / 800_000 + self.VOL_2_5H + 0.005)

    def test_restock_without_premium_must_cover_two_fees_alone(self):
        got = restock_half_spread_pct(0.0025, 800_000, 2.5, 0.0, None, None)
        self.assertAlmostEqual(got, 2 * 650 / 800_000 + self.VOL_2_5H + 0.005)

    def test_restock_credits_expected_sell_premium(self):
        full = restock_half_spread_pct(0.0001, 800_000, 2.5, 0.0, None, None)
        got = restock_half_spread_pct(0.0001, 800_000, 2.5, 0.018, None, None)
        self.assertAlmostEqual(got, full - 0.018)

    def test_restock_floored_when_premium_covers_everything(self):
        self.assertEqual(restock_half_spread_pct(0.0025, 800_000, 2.5, 0.10, None, None), 0.0025)

    def test_restock_rejects_nonpositive_notional(self):
        with self.assertRaises(ValueError):
            restock_half_spread_pct(0.0025, 0, 2.5, 0.0, None, None)


if __name__ == "__main__":
    unittest.main()

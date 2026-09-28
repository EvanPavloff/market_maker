"""Turns next_steps.md's §4 research (fee overhead, lock-window volatility) plus
analysis.py's observed spread into the actual go/no-go comparison next_steps.md's
"What 'yes, build Phase 2' actually requires" section describes only in prose:

    sustained observed spread > round-trip on-chain fees + a volatility buffer
    sized to the real lock window + a minimum profit margin

This module does not gather any new data — DEFAULT_ASSUMPTIONS below are the
directional (not continuously monitored) numbers already researched 2026-09-16
(see next_steps.md §4): current vs. historically-stressed BTC fee environments
(XMR fees are separately negligible, so BTC dominates round-trip on-chain cost),
and a volatility buffer sized to BasicSwap's own 24h UI lock-window ceiling
(`page_offers.py`'s `"lockhrs": 24` default/max). Treat every number here as a
snapshot to revisit, not a live-monitored one — same caveat next_steps.md gives
them.

Fee cost matters as a *percentage* of a specific offer's notional value, which
the poller/analysis layer above never has to think about (it works in
coin_to-per-coin_from rate units, not USD) — that's the whole reason this needs
its own module rather than another analysis.py field: the same $0.50-$75
round-trip fee is negligible on a $10,000 offer and can eat the entire observed
spread on a $50 one, so "does an edge exist" only has an answer once a
notional size is also chosen.
"""

import math
from dataclasses import dataclass, field

from .analysis import PairSummary

# Midpoint of next_steps.md §4's researched ~85-95% XMR/BTC annualized cross-vol
# estimate — the input the 24h-ceiling 1-sigma/2-sigma figures below were derived
# from (annualized_vol * sigma * sqrt(hours / (24*365)); at hours=24, sigma=1
# this reproduces ~4.7%, sigma=2 ~9.4%, matching the cited ~5%/~10%).
ANNUALIZED_CROSS_VOL_PCT = 0.90


def vol_buffer_pct_for_hours(
    hours: float, sigma: float, annualized_vol_pct: float = ANNUALIZED_CROSS_VOL_PCT
) -> float:
    """Illustrative sqrt-time scaling to a lock window shorter than BasicSwap's
    24h UI ceiling. NOT itself researched — next_steps.md §4 only measured/cited
    the 24h-ceiling number, since the *actual* observed lock time for a real
    BTC/XMR swap is still unmeasured (§4(a)/§5, sync-gated). Useful only to see
    how much the required-spread bar would move if a real swap later confirms a
    much shorter actual lock time than the 24h ceiling this module defaults to."""
    return annualized_vol_pct * sigma * math.sqrt(hours / (24 * 365))


@dataclass(frozen=True)
class CostAssumptions:
    """All directional, researched 2026-09-16 (next_steps.md §4) — revisit before
    relying on these for a real capital decision, they are not live-monitored."""

    # BTC round-trip on-chain fee (HTLC lock + claim, ~300-500 vbytes/tx at
    # today's ~1-2 sat/vB) — XMR-side fees are negligible (~$0.02-$0.06/tx) and
    # omitted. "Today" reflects a multi-month fee low; "stressed" reflects BTC's
    # historical 25-50x congestion fee spikes.
    fee_round_trip_usd_today_low: float = 0.50
    fee_round_trip_usd_today_high: float = 1.50
    fee_round_trip_usd_stressed_low: float = 15.0
    fee_round_trip_usd_stressed_high: float = 75.0

    # Same BTC round-trip fee in its native unit (added 2026-09-25 for the
    # accumulate-BTC goal — BTC network fees are paid in sats, so a sats
    # numeraire shouldn't route them through a USD price). Derived from the
    # same §4 inputs the USD figures above summarize: ~300-500 vbytes per
    # round trip at today's ~1-2 sat/vB, stressed = 25-50x that.
    btc_round_trip_vbytes_low: float = 300.0
    btc_round_trip_vbytes_high: float = 500.0
    sat_per_vb_today_low: float = 1.0
    sat_per_vb_today_high: float = 2.0
    stressed_fee_multiplier_low: float = 25.0
    stressed_fee_multiplier_high: float = 50.0

    # XMR/BTC cross volatility over BasicSwap's 24h UI lock-window ceiling
    # (actual observed lock times are likely well under this, but unmeasured
    # until a real swap runs — see next_steps.md §4/§5). ~85-95% annualized
    # cross vol -> ~5% one-day (1-sigma), ~10% two-day-equivalent (2-sigma) over
    # the full 24h ceiling.
    vol_buffer_pct_1sigma_24h: float = 0.05
    vol_buffer_pct_2sigma_24h: float = 0.10

    # Placeholder minimum profit margin on top of break-even — not researched,
    # just a round number pending an actual target return; override per call.
    min_profit_margin_pct: float = 0.005

    # Below this two-sided fraction, a spread number isn't trustworthy regardless
    # of its value (next_steps.md §3/"What 'yes' actually requires") — no
    # research behind the exact threshold, a conservative round number.
    min_two_sided_fraction: float = 0.5


    @property
    def fee_round_trip_sats_today(self) -> float:
        """Midpoint of the today range: (300*1 + 500*2) / 2 = 650 sats by default."""
        low = self.btc_round_trip_vbytes_low * self.sat_per_vb_today_low
        high = self.btc_round_trip_vbytes_high * self.sat_per_vb_today_high
        return (low + high) / 2

    @property
    def fee_round_trip_sats_stressed(self) -> float:
        """Midpoint of the stressed range: (300*1*25 + 500*2*50) / 2 = 28,750 sats by default."""
        low = self.btc_round_trip_vbytes_low * self.sat_per_vb_today_low * self.stressed_fee_multiplier_low
        high = self.btc_round_trip_vbytes_high * self.sat_per_vb_today_high * self.stressed_fee_multiplier_high
        return (low + high) / 2

    @property
    def fee_round_trip_usd_today(self) -> float:
        return (self.fee_round_trip_usd_today_low + self.fee_round_trip_usd_today_high) / 2

    @property
    def fee_round_trip_usd_stressed(self) -> float:
        return (self.fee_round_trip_usd_stressed_low + self.fee_round_trip_usd_stressed_high) / 2


DEFAULT_ASSUMPTIONS = CostAssumptions()


def required_spread_pct(
    notional_usd: float,
    fee_round_trip_usd: float,
    vol_buffer_pct: float,
    min_margin_pct: float,
) -> float:
    """The minimum spread (as a fraction, e.g. 0.02 = 2%) a market maker would
    need to realize on this notional to cover the fee, the price-risk buffer,
    and the desired margin. Pure arithmetic — see module docstring for the
    bar this compares against. Unit-agnostic despite the names: notional and
    fee just have to share a unit (evaluate_pair_sats passes both in sats)."""
    if notional_usd <= 0:
        raise ValueError(f"notional_usd must be positive, got {notional_usd}")
    fee_pct = fee_round_trip_usd / notional_usd
    return fee_pct + vol_buffer_pct + min_margin_pct


def live_annualized_vol_pct(window_vol_pct: float, window_seconds: float) -> float:
    """market_maker/next_steps.md #15 Phase A: extrapolates volatility.py's
    VolatilityMonitor rolling-window reading ((max-min)/mean over window_seconds,
    already computed every live_maker cycle for the kill-switch) to an
    annualized-vol-equivalent, using the same sqrt-time convention
    vol_buffer_pct_for_hours already uses to scale an annualized figure *down* to a
    shorter window -- this runs that scaling in reverse. A range-based estimator
    standing in for a stdev-based one, same documented approximation volatility.py's
    kill-switch already relies on (calibrated against real percentiles, not a
    rigorous vol model) -- good enough to tell "louder than usual right now" apart
    from "calm," not a precision instrument."""
    if window_seconds <= 0:
        raise ValueError(f"window_seconds must be positive, got {window_seconds}")
    window_years = window_seconds / (24 * 3600 * 365)
    return window_vol_pct / math.sqrt(window_years)


def dynamic_half_spread_pct(
    operator_floor_pct: float,
    notional_usd: float,
    lock_hours: float,
    live_vol_pct: float | None,
    live_vol_window_seconds: float | None,
    assumptions: CostAssumptions = DEFAULT_ASSUMPTIONS,
    sigma: float = 1.0,
) -> float:
    """market_maker/next_steps.md #15 Phase A: live_maker.py's per-cycle computed
    half_spread_pct, composing a live volatility reading with this module's
    already-built cost model instead of quoting at a static, hand-edited CLI
    default every cycle regardless of current conditions (next_steps.md #14's fix
    was the last hand-edit of that kind). `operator_floor_pct` is read as a floor,
    never a target -- the result never drops below it, even when live inputs would
    otherwise justify a thinner number, matching this project's standing
    fail-safe-toward-caution posture (the kill-switch/disagreement gate are the
    same shape: always more conservative, never less, on their own initiative).

    `lock_hours` here is an assumed exposure window (still a static guess pending
    next_steps.md #15 Phase C's real fill-time measurement), NOT
    LiveMakerConfig.lock_hours (the offer's technical HTLC ceiling passed to
    post_offer) -- the two are unrelated numbers that happen to share a name
    across modules. Uses "today" (not "stressed") fees and sigma=1 by default,
    matching next_steps.md #14's own 0.02 derivation and this project's existing
    today_1sigma default scenario elsewhere."""
    if notional_usd <= 0:
        raise ValueError(f"notional_usd must be positive, got {notional_usd}")
    fee_usd = assumptions.fee_round_trip_usd_today
    if live_vol_pct is not None and live_vol_window_seconds:
        annualized_vol_pct = live_annualized_vol_pct(live_vol_pct, live_vol_window_seconds)
    else:
        annualized_vol_pct = ANNUALIZED_CROSS_VOL_PCT
    vol_buffer = vol_buffer_pct_for_hours(lock_hours, sigma, annualized_vol_pct)
    required = required_spread_pct(notional_usd, fee_usd, vol_buffer, assumptions.min_profit_margin_pct)
    return max(operator_floor_pct, required)


@dataclass
class EconomicsVerdict:
    coin_from: str
    coin_to: str
    notional: float
    notional_unit: str  # "usd" or "sats" — the unit notional and the fee were compared in
    n_polls: int
    two_sided_fraction: float
    observed_median_spread_pct: float | None
    # keyed "today"/"stressed" x "1sigma"/"2sigma"
    required_spread_pct: dict[str, float] = field(default_factory=dict)
    clears: dict[str, bool | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def insufficient_data(self) -> bool:
        return self.observed_median_spread_pct is None


def evaluate_pair(
    summary: PairSummary,
    notional_usd: float,
    assumptions: CostAssumptions = DEFAULT_ASSUMPTIONS,
    lock_hours: float | None = None,
) -> EconomicsVerdict:
    """USD-numeraire verdict. Compare `summary` (from analysis.summarize_pair) against the go/no-go bar
    across both fee scenarios and both volatility-buffer sizings. Uses the
    *median* observed spread, not the mean — one favorable outlier poll
    shouldn't carry the verdict (next_steps.md's "sustained ... not a one-off
    favorable snapshot").

    `lock_hours`: by default (None) uses `assumptions`' pre-computed 24h-UI-
    ceiling vol buffers, same as before. Pass a real measured exposure time
    (e.g. the 2026-09-17 test swap's ~0.708h) to size the vol buffer off that
    instead via `vol_buffer_pct_for_hours` — this is what next_steps.md's
    "Real test swap completed" section re-ran by hand; passing it here makes
    that a repeatable call instead of one-off arithmetic."""
    return _evaluate(
        summary, notional_usd, "usd",
        assumptions.fee_round_trip_usd_today, assumptions.fee_round_trip_usd_stressed,
        assumptions, lock_hours,
    )


def evaluate_pair_sats(
    summary: PairSummary,
    notional_sats: float,
    assumptions: CostAssumptions = DEFAULT_ASSUMPTIONS,
    lock_hours: float | None = None,
) -> EconomicsVerdict:
    """BTC-numeraire verdict (goal = accumulate BTC). Same bar as evaluate_pair,
    with the notional and the BTC network fee both in sats, so no BTC/USD
    price enters the comparison. The vol buffer needs no conversion: it was
    always XMR/BTC cross vol (ANNUALIZED_CROSS_VOL_PCT), which is exactly the
    only price risk a BTC-denominated holder carries."""
    return _evaluate(
        summary, notional_sats, "sats",
        assumptions.fee_round_trip_sats_today, assumptions.fee_round_trip_sats_stressed,
        assumptions, lock_hours,
    )


def _evaluate(
    summary: PairSummary,
    notional: float,
    notional_unit: str,
    fee_today: float,
    fee_stressed: float,
    assumptions: CostAssumptions,
    lock_hours: float | None,
) -> EconomicsVerdict:
    notes: list[str] = []

    if summary.n_polls == 0:
        notes.append("no polls yet — observation window hasn't started producing data")
    elif summary.two_sided_fraction < assumptions.min_two_sided_fraction:
        notes.append(
            f"two-sided fraction {summary.two_sided_fraction:.0%} is below the "
            f"{assumptions.min_two_sided_fraction:.0%} gate — a market this often "
            "one-sided can't be reliably quoted into regardless of spread"
        )
    if summary.n_polls > 0 and summary.n_polls < 100:
        notes.append(
            f"only {summary.n_polls} poll(s) so far — next_steps.md §3 calls for "
            "1-2 weeks minimum before trusting this number as sustained, not a "
            "one-off snapshot"
        )

    if lock_hours is None:
        vol_1sigma = assumptions.vol_buffer_pct_1sigma_24h
        vol_2sigma = assumptions.vol_buffer_pct_2sigma_24h
    else:
        vol_1sigma = vol_buffer_pct_for_hours(lock_hours, sigma=1)
        vol_2sigma = vol_buffer_pct_for_hours(lock_hours, sigma=2)
        notes.append(
            f"vol buffer sized to a {lock_hours:.3f}h lock window, not the "
            "24h UI ceiling — only as reliable as that hours figure (see "
            "next_steps.md §4(a)/§7 on n=1 for the real measured swap)"
        )

    scenarios = {
        "today_1sigma": (fee_today, vol_1sigma),
        "today_2sigma": (fee_today, vol_2sigma),
        "stressed_1sigma": (fee_stressed, vol_1sigma),
        "stressed_2sigma": (fee_stressed, vol_2sigma),
    }

    required: dict[str, float] = {}
    clears: dict[str, bool | None] = {}
    for key, (fee, vol_pct) in scenarios.items():
        req = required_spread_pct(notional, fee, vol_pct, assumptions.min_profit_margin_pct)
        required[key] = req
        if summary.median_spread_pct is None:
            clears[key] = None
        else:
            clears[key] = summary.median_spread_pct > req

    return EconomicsVerdict(
        coin_from=summary.coin_from,
        coin_to=summary.coin_to,
        notional=notional,
        notional_unit=notional_unit,
        n_polls=summary.n_polls,
        two_sided_fraction=summary.two_sided_fraction,
        observed_median_spread_pct=summary.median_spread_pct,
        required_spread_pct=required,
        clears=clears,
        notes=notes,
    )


@dataclass(frozen=True)
class ExpectedAPY:
    """next_steps.md §7's formula result for one (scenario, fills_per_year)
    pair. `fills_per_year` is taken directly as cycles/year, matching §7's own
    illustrative table — it does not separately model capital-lockup time as a
    throughput ceiling (see that section's caveat: at realistic fill
    frequencies the ~0.7h measured lockup is never the binding constraint)."""

    scenario: str
    fills_per_year: float
    raw_edge_pct: float
    risk_adjusted_edge_pct: float
    apr_simple_raw: float
    apy_compound_raw: float
    apr_simple_risk_adjusted: float
    apy_compound_risk_adjusted: float


def _compound(edge_pct: float, cycles_per_year: float) -> float:
    # A per-cycle edge of -100% or worse compounded means capital hits zero,
    # not a defined (1+x)**n — guard rather than let a negative base under a
    # non-integer exponent blow up. Same failure class next_steps.md's §7
    # already flags: hyperliquid_bot's backtest producing a >1e+275x return
    # artifact before a real bug was found — an absurd number here should be
    # read as "the input edge is nonsensical," not reported as a result.
    base = 1 + edge_pct
    if base <= 0:
        return -1.0
    return base**cycles_per_year - 1


def expected_apy(
    verdict: EconomicsVerdict,
    fills_per_year: float,
    scenario: str = "today_1sigma",
    assumptions: CostAssumptions = DEFAULT_ASSUMPTIONS,
) -> ExpectedAPY:
    """next_steps.md §7: turns a spread-vs-cost verdict into an actual
    annualized-return projection, comparable to `finance/crypto_yield/`'s
    quoted yields. `fills_per_year` is the one input nothing built so far
    measures (§7's table: "idle_hours_waiting_for_the_next_fill") — it's an
    assumption you supply, not something this function looks up. Treat the
    output the same way next_steps.md's own sensitivity table does: a
    sensitivity check on that missing variable, not a forecast."""
    if verdict.observed_median_spread_pct is None:
        raise ValueError("no observed spread yet (insufficient_data) — nothing to project")
    if fills_per_year <= 0:
        raise ValueError(f"fills_per_year must be positive, got {fills_per_year}")
    if scenario not in verdict.required_spread_pct:
        raise ValueError(
            f"unknown scenario {scenario!r}, choose from {sorted(verdict.required_spread_pct)}"
        )

    today = scenario.startswith("today")
    if verdict.notional_unit == "sats":
        fee = assumptions.fee_round_trip_sats_today if today else assumptions.fee_round_trip_sats_stressed
    else:
        fee = assumptions.fee_round_trip_usd_today if today else assumptions.fee_round_trip_usd_stressed
    fee_pct = fee / verdict.notional

    raw_edge_pct = verdict.observed_median_spread_pct - fee_pct
    risk_adjusted_edge_pct = verdict.observed_median_spread_pct - verdict.required_spread_pct[scenario]

    return ExpectedAPY(
        scenario=scenario,
        fills_per_year=fills_per_year,
        raw_edge_pct=raw_edge_pct,
        risk_adjusted_edge_pct=risk_adjusted_edge_pct,
        apr_simple_raw=raw_edge_pct * fills_per_year,
        apy_compound_raw=_compound(raw_edge_pct, fills_per_year),
        apr_simple_risk_adjusted=risk_adjusted_edge_pct * fills_per_year,
        apy_compound_risk_adjusted=_compound(risk_adjusted_edge_pct, fills_per_year),
    )


def format_expected_apy(a: ExpectedAPY) -> str:
    return (
        f"  {a.fills_per_year:>8.1f} fills/yr vs. {a.scenario:>16}: "
        f"raw edge {a.raw_edge_pct * 100:.3f}%/cycle -> "
        f"APR {a.apr_simple_raw * 100:.1f}% / APY {a.apy_compound_raw * 100:.1f}%  |  "
        f"risk-adj edge {a.risk_adjusted_edge_pct * 100:.3f}%/cycle -> "
        f"APR {a.apr_simple_risk_adjusted * 100:.1f}% / APY {a.apy_compound_risk_adjusted * 100:.1f}%"
    )


def format_verdict(v: EconomicsVerdict) -> str:
    size = f"{v.notional:,.0f} sats" if v.notional_unit == "sats" else f"${v.notional:,.0f}"
    lines = [f"{v.coin_from}/{v.coin_to} @ {size} notional, {v.n_polls} poll(s):"]
    if v.observed_median_spread_pct is None:
        lines.append("  no two-sided data yet — no verdict possible")
    else:
        lines.append(f"  observed median spread: {v.observed_median_spread_pct * 100:.3f}%")
        for key in ("today_1sigma", "today_2sigma", "stressed_1sigma", "stressed_2sigma"):
            req = v.required_spread_pct[key]
            verdict = "CLEARS" if v.clears[key] else "does not clear"
            lines.append(f"  vs. {key:>16}: requires {req * 100:.3f}% -> {verdict}")
    for note in v.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def main() -> None:
    """CLI: python -m strategy.economics --notional-usd 1000 [--notional-usd 100 ...]
    or --notional-sats 800000 [...] for the BTC-numeraire verdict
    (reads config for db_path/pairs, matching analysis.py's convention)."""
    import argparse

    from . import coin_names, storage
    from .analysis import summarize_pair
    from .config import load_config

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--notional-usd",
        type=float,
        action="append",
        default=None,
        help="offer notional in USD to evaluate against (repeatable). Default: 100, 1000, 10000",
    )
    parser.add_argument(
        "--notional-sats",
        type=float,
        action="append",
        default=None,
        help="evaluate in BTC numeraire at this notional in sats (repeatable); "
        "fees compared in sats, no BTC/USD price used. Replaces the USD default when given",
    )
    parser.add_argument(
        "--lock-hours",
        type=float,
        default=None,
        help="size the vol buffer off this exposure window instead of the 24h UI "
        "ceiling default (e.g. 0.708 for the 2026-09-17 real test swap)",
    )
    parser.add_argument(
        "--fills-per-year",
        type=float,
        action="append",
        default=None,
        help="assumed fill frequency to project APR/APY at (repeatable, §7's "
        "sensitivity table). Not measured by this project yet — see next_steps.md §7",
    )
    parser.add_argument(
        "--apy-scenario",
        default="today_1sigma",
        choices=["today_1sigma", "today_2sigma", "stressed_1sigma", "stressed_2sigma"],
        help="which required-spread scenario to use for the risk-adjusted APY column",
    )
    args = parser.parse_args()
    if args.notional_sats:
        runs = [(evaluate_pair_sats, n) for n in args.notional_sats]
    else:
        runs = [(evaluate_pair, n) for n in (args.notional_usd or [100.0, 1000.0, 10000.0])]

    config = load_config()
    conn = storage.connect(config.db_path)
    for coin_from, coin_to in config.pairs:
        display_from = coin_names.to_display_name(coin_from)
        display_to = coin_names.to_display_name(coin_to)
        summary = summarize_pair(conn, display_from, display_to)
        for evaluate, notional in runs:
            verdict = evaluate(summary, notional, lock_hours=args.lock_hours)
            print(format_verdict(verdict))
            if args.fills_per_year and not verdict.insufficient_data:
                print("  --- expected APR/APY sensitivity (§7 — fills_per_year is an assumption, not a measurement) ---")
                for fills in args.fills_per_year:
                    apy = expected_apy(verdict, fills, scenario=args.apy_scenario)
                    print(format_expected_apy(apy))
            print()


if __name__ == "__main__":
    main()

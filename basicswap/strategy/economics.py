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
    bar this compares against."""
    if notional_usd <= 0:
        raise ValueError(f"notional_usd must be positive, got {notional_usd}")
    fee_pct = fee_round_trip_usd / notional_usd
    return fee_pct + vol_buffer_pct + min_margin_pct


@dataclass
class EconomicsVerdict:
    coin_from: str
    coin_to: str
    notional_usd: float
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
    """Compare `summary` (from analysis.summarize_pair) against the go/no-go bar
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
        "today_1sigma": (
            (assumptions.fee_round_trip_usd_today_low + assumptions.fee_round_trip_usd_today_high) / 2,
            vol_1sigma,
        ),
        "today_2sigma": (
            (assumptions.fee_round_trip_usd_today_low + assumptions.fee_round_trip_usd_today_high) / 2,
            vol_2sigma,
        ),
        "stressed_1sigma": (
            (assumptions.fee_round_trip_usd_stressed_low + assumptions.fee_round_trip_usd_stressed_high) / 2,
            vol_1sigma,
        ),
        "stressed_2sigma": (
            (assumptions.fee_round_trip_usd_stressed_low + assumptions.fee_round_trip_usd_stressed_high) / 2,
            vol_2sigma,
        ),
    }

    required: dict[str, float] = {}
    clears: dict[str, bool | None] = {}
    for key, (fee_usd, vol_pct) in scenarios.items():
        req = required_spread_pct(notional_usd, fee_usd, vol_pct, assumptions.min_profit_margin_pct)
        required[key] = req
        if summary.median_spread_pct is None:
            clears[key] = None
        else:
            clears[key] = summary.median_spread_pct > req

    return EconomicsVerdict(
        coin_from=summary.coin_from,
        coin_to=summary.coin_to,
        notional_usd=notional_usd,
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

    fee_usd = (
        (assumptions.fee_round_trip_usd_today_low + assumptions.fee_round_trip_usd_today_high) / 2
        if scenario.startswith("today")
        else (assumptions.fee_round_trip_usd_stressed_low + assumptions.fee_round_trip_usd_stressed_high) / 2
    )
    fee_pct = fee_usd / verdict.notional_usd

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
    lines = [f"{v.coin_from}/{v.coin_to} @ ${v.notional_usd:,.0f} notional, {v.n_polls} poll(s):"]
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
    notionals = args.notional_usd or [100.0, 1000.0, 10000.0]

    config = load_config()
    conn = storage.connect(config.db_path)
    for coin_from, coin_to in config.pairs:
        display_from = coin_names.to_display_name(coin_from)
        display_to = coin_names.to_display_name(coin_to)
        summary = summarize_pair(conn, display_from, display_to)
        for notional_usd in notionals:
            verdict = evaluate_pair(summary, notional_usd, lock_hours=args.lock_hours)
            print(format_verdict(verdict))
            if args.fills_per_year and not verdict.insufficient_data:
                print("  --- expected APR/APY sensitivity (§7 — fills_per_year is an assumption, not a measurement) ---")
                for fills in args.fills_per_year:
                    apy = expected_apy(verdict, fills, scenario=args.apy_scenario)
                    print(format_expected_apy(apy))
            print()


if __name__ == "__main__":
    main()

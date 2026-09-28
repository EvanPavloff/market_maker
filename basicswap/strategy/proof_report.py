"""Proof-step report for the accumulate-BTC trial (market_maker/next_steps.md #17,
built 2026-09-28). Read-only. Scores the trial since `~/coinswaps/proof_trial_start`
(written by restart_live_maker_btc.sh) against the success bar, which asks one
question: will anyone buy our XMR at a premium often enough, and at a good enough
price, that restocking it on Kraken would net BTC?

What it measures, all over the trial window:
  - Sell-leg presence: share of poller cycles with our XMR-sell offer live, and
    share where it was the cheapest on BasicSwap's book (offer_snapshots). A fill
    rate means nothing if the offer wasn't up, so low uptime makes the verdict
    INCONCLUSIVE rather than PESSIMISTIC.
  - Sell fills per week, and each one's Kraken-restock margin: edge vs. the mid an
    hour after the fill (a realistic time to buy back on Kraken), minus Kraken's
    depth cost at fill time (kraken_book_snapshots), Kraken's trading fee, and
    network/transfer fees. Only an estimate of a leg we haven't built.
  - Restock-leg fills (our own maker offer buying XMR). If these come regularly
    and cheaply, Kraken may not be needed at all.
  - Net sats vs. never having traded, over the trial, marked at today's price.

The verdict maps onto the three cases in next_steps.md #17 (pessimistic / base /
optimistic). It's PROVISIONAL until MIN_WEEKS have passed.

Usage: ./run_fill_ledger.sh first (syncs fills), then
       python3 -m strategy.proof_report [--since "2026-09-29 09:00"]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import economics, storage
from .coin_names import to_display_name
from .config import load_config
from .fill_ledger import BTC, SATS_PER_BTC, TAKER, mark_to_btc, net_flows

XMR = "Monero"
TRIAL_START_FILE = os.path.expanduser("~/coinswaps/proof_trial_start")

# Kraken's entry-tier taker fee. The public API doesn't return fees for XMR/BTC,
# so this is an assumption to verify on Kraken's fee page before relying on it.
KRAKEN_TAKER_FEE_PCT = 0.004
# Used only when no kraken_book_snapshots row is near a fill (measured 2026-09-28:
# buying 1-5 XMR cost +0.116-0.123% over mid).
KRAKEN_FALLBACK_BUY_COST_PCT = 0.0012
# Per round trip: the atomic swap's BTC fees (economics.py's "today" figure) plus
# an assumed ~1,000 sats for the BTC deposit to Kraken and the XMR withdrawal fee.
TRANSFER_FEE_SATS = economics.DEFAULT_ASSUMPTIONS.fee_round_trip_sats_today + 1000
# For the $/yr projection: each fill scaled to about half a $5k pot, which is also
# roughly Bisq's median XMR trade (~0.03 BTC). Assumes the fill rate holds at that
# size, which is optimistic.
PROJECTION_LOT_USD = 2500.0


@dataclass(frozen=True)
class SuccessBar:
    min_weeks: float = 4.0
    min_sell_uptime: float = 0.5  # below this the trial isn't really testing the sell leg
    pessimistic_max_fills_per_week: float = 0.5
    optimistic_min_fills_per_week: float = 2.0
    optimistic_min_fills: int = 8
    optimistic_min_margin_pct: float = 0.008
    margin_min_fills: int = 4  # fills needed before the margin alone can condemn the desk


SUCCESS_BAR = SuccessBar()


@dataclass
class Presence:
    polls: int = 0
    live: int = 0
    best: int = 0

    @property
    def uptime(self) -> float | None:
        return self.live / self.polls if self.polls else None

    @property
    def best_share_when_live(self) -> float | None:
        return self.best / self.live if self.live else None


@dataclass
class SellFill:
    created_at: float
    xmr: float
    btc: float
    edge_at_fill: float | None
    basis: float | None  # +1h markout, else edge at fill
    basis_label: str
    kraken_cost_pct: float
    kraken_cost_measured: bool
    margin_pct: float | None


@dataclass
class TrialMetrics:
    since: float
    until: float
    sell_presence: Presence
    restock_presence: Presence
    sell_fills: list[SellFill] = field(default_factory=list)
    restock_fills: list[sqlite3.Row] = field(default_factory=list)
    taker_fills: list[sqlite3.Row] = field(default_factory=list)
    net_sats: float | None = None

    @property
    def weeks(self) -> float:
        return max(self.until - self.since, 0.0) / (7 * 86400)

    @property
    def sell_fills_per_week(self) -> float | None:
        return len(self.sell_fills) / self.weeks if self.weeks > 0 else None

    @property
    def mean_margin_pct(self) -> float | None:
        vals = [f.margin_pct for f in self.sell_fills if f.margin_pct is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def n_margins(self) -> int:
        return sum(f.margin_pct is not None for f in self.sell_fills)


def presence(conn: sqlite3.Connection, since: float, until: float, give: str, get: str) -> Presence:
    """Per poller cycle in [since, until): was our offer selling `give` for `get`
    live, and was it the cheapest such offer on the book? The poll clock is
    direct_rate_snapshots (one row per cycle, even when the book is empty)."""
    give, get = to_display_name(give), to_display_name(get)
    mids: dict[float, float] = {}
    for pt, cf, ct, cg, kr in conn.execute(
        "SELECT polled_at, coin_from, coin_to, coingecko_rate, kraken_rate FROM direct_rate_snapshots "
        "WHERE polled_at >= ? AND polled_at < ?", (since, until)
    ):
        vals = [v for v in (cg, kr) if v]
        if not vals:
            continue
        m = sum(vals) / len(vals)
        a, b = to_display_name(cf), to_display_name(ct)
        if (a, b) == (give, get):
            mids[pt] = m
        elif (a, b) == (get, give):
            mids[pt] = 1 / m
    offers: dict[float, list[tuple[float, int]]] = {}
    for pt, cf, ct, af, at, own in conn.execute(
        "SELECT polled_at, coin_from, coin_to, amount_from, amount_to, is_own_offer FROM offer_snapshots "
        "WHERE polled_at >= ? AND polled_at < ? AND is_expired = 0 AND is_revoked = 0", (since, until)
    ):
        if to_display_name(cf) == give and to_display_name(ct) == get and af > 0:
            offers.setdefault(pt, []).append((at / af, own))
    p = Presence()
    for pt, mid in mids.items():
        p.polls += 1
        book = offers.get(pt, [])
        own = [rate for rate, is_own in book if is_own]
        if not own:
            continue
        p.live += 1
        # A seller of `give` competes by asking for LESS `get` per unit.
        others = [rate for rate, is_own in book if not is_own]
        if not others or min(own) <= min(others):
            p.best += 1
    return p


def kraken_restock_cost(conn: sqlite3.Connection, t: float, xmr: float) -> tuple[float, bool]:
    """(cost to buy `xmr` on Kraken vs. mid at time t, before fees; measured?)"""
    row = storage.nearest_kraken_book_snapshot(conn, t)
    if row is not None:
        cost = row["buy_cost_1xmr_pct"] if xmr <= 1.0 else row["buy_cost_5xmr_pct"]
        if cost is not None:
            return cost, True
    return KRAKEN_FALLBACK_BUY_COST_PCT, False


def sell_fill(conn: sqlite3.Connection, r: sqlite3.Row) -> SellFill:
    basis, label = (r["markout_1h_pct"], "+1h") if r["markout_1h_pct"] is not None else (r["edge_pct_at_fill"], "@fill")
    cost, measured = kraken_restock_cost(conn, r["bid_created_at"], r["amount_from"])
    margin = None
    if basis is not None and r["amount_to"] > 0:
        fee_pct = TRANSFER_FEE_SATS / (r["amount_to"] * SATS_PER_BTC)
        margin = basis - cost - KRAKEN_TAKER_FEE_PCT - fee_pct
    return SellFill(
        created_at=r["bid_created_at"], xmr=r["amount_from"], btc=r["amount_to"],
        edge_at_fill=r["edge_pct_at_fill"], basis=basis, basis_label=label,
        kraken_cost_pct=cost, kraken_cost_measured=measured, margin_pct=margin,
    )


def collect(
    conn: sqlite3.Connection, since: float, until: float, btc_per_xmr_now: float | None
) -> TrialMetrics:
    rows = [
        r for r in storage.fetch_fills(conn)
        if since <= r["bid_created_at"] < until and r["bid_state"] == "Completed"
    ]
    m = TrialMetrics(
        since=since, until=until,
        sell_presence=presence(conn, since, until, "xmr", "btc"),
        restock_presence=presence(conn, since, until, "btc", "xmr"),
    )
    for r in rows:
        if r["side"] == TAKER:
            m.taker_fills.append(r)
        elif r["coin_from"] == XMR and r["coin_to"] == BTC:
            m.sell_fills.append(sell_fill(conn, r))
        elif r["coin_from"] == BTC and r["coin_to"] == XMR:
            m.restock_fills.append(r)
    m.net_sats = None
    marked = mark_to_btc(net_flows(rows), {XMR: btc_per_xmr_now} if btc_per_xmr_now else None)
    if marked is not None:
        m.net_sats = marked * SATS_PER_BTC
    return m


def classify(m: TrialMetrics, bar: SuccessBar = SUCCESS_BAR) -> tuple[str, list[str]]:
    """(verdict, reasons). Verdicts: PESSIMISTIC, BASE, OPTIMISTIC, INCONCLUSIVE,
    each prefixed PROVISIONAL until bar.min_weeks have passed."""
    reasons: list[str] = []
    rate = m.sell_fills_per_week
    margin = m.mean_margin_pct
    provisional = m.weeks < bar.min_weeks
    if provisional:
        reasons.append(f"only {m.weeks:.1f} of {bar.min_weeks:.0f} weeks elapsed")

    if m.n_margins >= bar.margin_min_fills and margin is not None and margin <= 0:
        reasons.append(f"mean Kraken-restock margin {margin:+.2%} over {m.n_margins} fills is not positive")
        verdict = "PESSIMISTIC"
    elif m.sell_presence.uptime is None or m.sell_presence.uptime < bar.min_sell_uptime:
        up = "no polls" if m.sell_presence.uptime is None else f"{m.sell_presence.uptime:.0%}"
        reasons.append(f"sell offer live in {up} of poller cycles (< {bar.min_sell_uptime:.0%}): the sell leg isn't being tested")
        verdict = "INCONCLUSIVE"
    elif not provisional and rate is not None and rate < bar.pessimistic_max_fills_per_week:
        reasons.append(f"{rate:.2f} sell fills/week < {bar.pessimistic_max_fills_per_week}")
        verdict = "PESSIMISTIC"
    elif (
        rate is not None and rate >= bar.optimistic_min_fills_per_week
        and m.n_margins >= bar.optimistic_min_fills
        and margin is not None and margin >= bar.optimistic_min_margin_pct
    ):
        reasons.append(
            f"{rate:.2f} fills/week, mean margin {margin:+.2%} over {m.n_margins} fills clears the optimistic bar"
        )
        verdict = "OPTIMISTIC"
    else:
        reasons.append(
            f"{'n/a' if rate is None else f'{rate:.2f}'} fills/week, mean margin "
            f"{'n/a' if margin is None else f'{margin:+.2%}'} over {m.n_margins} fill(s): between the bars"
        )
        verdict = "BASE"
    return (f"PROVISIONAL {verdict}" if provisional else verdict), reasons


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2%}"


def _share(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def _when(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def report(m: TrialMetrics, bar: SuccessBar = SUCCESS_BAR) -> str:
    verdict, reasons = classify(m, bar)
    lines = [
        f"Accumulate-BTC proof trial: {_when(m.since)} -> {_when(m.until)} ({m.weeks:.1f} weeks)",
        "",
        f"VERDICT: {verdict}",
        *[f"  - {r}" for r in reasons],
        "",
        "Sell leg (we sell XMR for BTC):",
        f"  offer live in {_share(m.sell_presence.uptime)} of {m.sell_presence.polls} poller cycles; "
        f"cheapest on BasicSwap in {_share(m.sell_presence.best_share_when_live)} of those",
        f"  completed fills: {len(m.sell_fills)}"
        + (f" ({m.sell_fills_per_week:.2f}/week)" if m.sell_fills_per_week is not None else ""),
    ]
    if m.sell_fills:
        lines.append(f"  {'filled':16} {'XMR':>11} {'BTC':>11} {'@fill':>7} {'basis':>12} {'kraken':>8} {'margin':>7}")
        for f in m.sell_fills:
            lines.append(
                f"  {_when(f.created_at):16} {f.xmr:11.6f} {f.btc:11.8f} {_pct(f.edge_at_fill):>7} "
                f"{_pct(f.basis):>7} {f.basis_label:>4} {_pct(f.kraken_cost_pct):>7}{'' if f.kraken_cost_measured else '*'} "
                f"{_pct(f.margin_pct):>7}"
            )
        lines.append(
            f"  margin = basis - Kraken depth cost - {KRAKEN_TAKER_FEE_PCT:.2%} Kraken fee (assumed) - "
            f"{TRANSFER_FEE_SATS:,.0f} sats network/transfer fees (partly assumed); * = no Kraken snapshot, "
            f"{KRAKEN_FALLBACK_BUY_COST_PCT:.2%} used"
        )
        lines.append(f"  mean margin: {_pct(m.mean_margin_pct)} over {m.n_margins} fill(s)")
        if m.sell_fills_per_week is not None and m.mean_margin_pct is not None:
            proj = m.sell_fills_per_week * 52 * PROJECTION_LOT_USD * m.mean_margin_pct
            lines.append(
                f"  projection for a $5k pot: {'-' if proj < 0 else '+'}${abs(proj):,.0f}/yr "
                f"(this fill rate x ${PROJECTION_LOT_USD:,.0f} per fill x mean margin; assumes the rate holds at 5-10x our size)"
            )
    lines += [
        "",
        "Restock leg (our maker offer buying XMR with BTC):",
        f"  offer live in {_share(m.restock_presence.uptime)} of cycles; cheapest in "
        f"{_share(m.restock_presence.best_share_when_live)} of those",
        f"  completed fills: {len(m.restock_fills)}",
    ]
    edges = [r["edge_pct_at_fill"] for r in m.restock_fills if r["edge_pct_at_fill"] is not None]
    if edges:
        lines.append(f"  mean edge @fill: {_pct(sum(edges) / len(edges))} (positive = we bought XMR below mid)")
    if m.taker_fills:
        lines.append(f"\nBids we sent (top-ups/bid_scanner) in the window: {len(m.taker_fills)}")
    lines += [
        "",
        "Net position vs. never having traded (all completed fills in the window, today's price): "
        + ("n/a" if m.net_sats is None else f"{m.net_sats:+,.0f} sats"),
        "",
        f"Bar: >= {bar.min_weeks:.0f} weeks. PESSIMISTIC < {bar.pessimistic_max_fills_per_week} sell fills/week, or "
        f"mean margin <= 0 over >= {bar.margin_min_fills} fills. OPTIMISTIC >= {bar.optimistic_min_fills_per_week} "
        f"fills/week AND >= {bar.optimistic_min_fills} fills AND mean margin >= {bar.optimistic_min_margin_pct:.1%}. "
        "BASE otherwise. See next_steps.md #17.",
    ]
    return "\n".join(lines)


def read_trial_start(path: str = TRIAL_START_FILE) -> float | None:
    try:
        with open(path) as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def _parse_since(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help='trial start, epoch or "YYYY-MM-DD HH:MM" local; default: ' + TRIAL_START_FILE)
    args = ap.parse_args(argv)
    since = _parse_since(args.since) if args.since else read_trial_start()
    if since is None:
        print(f"No trial start: pass --since or run restart_live_maker_btc.sh (writes {TRIAL_START_FILE}).")
        return 1
    conn = storage.connect(load_config().db_path)
    from . import external_rates

    try:
        btc_per_xmr = external_rates.get_reference_rate("xmr", "btc").mid
    except external_rates.ExternalRateError as e:
        print(f"warning: no current XMR/BTC price, net position will show n/a: {e}", file=sys.stderr)
        btc_per_xmr = None
    print(report(collect(conn, since, time.time(), btc_per_xmr)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

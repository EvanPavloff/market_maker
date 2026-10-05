"""What would it cost to restock XMR right now, on each venue we watch?

Read-only report over data the pollers already write. It answers the trial's
question in `next_steps.md` #17 from the supply side: is there a non-KYC place
to buy XMR with BTC cheaply enough that we don't need a CEX (Kraken) for the
restock leg?

For every poll cycle and venue it walks the XMR-sell offers, cheapest first, to
fill `--xmr` (default 0.5, the restock leg's top-up size). It prices the result
against the Kraken mid at the same moment, then adds that venue's fees. Sources:
  - Bisq, Eigen ASB, Exolix, ChangeNOW: `venue_offer_snapshots` (venues/poller.py)
  - BasicSwap: `offer_snapshots` (basicswap/strategy/poller.py), our own offers excluded
  - Kraken mid and depth cost: `kraken_book_snapshots` (same DB as BasicSwap)

Run from `market_maker/`:

    python3 -m venues.restock_cost             # last 7 days, 0.5 XMR
    python3 -m venues.restock_cost --days 1 --xmr 1.0

The sell leg quotes about +1.8% over mid (`--restock-expected-sell-premium-pct`),
so a restock path matters only if its all-in cost sits well under that.
"""

import argparse
import math
import os
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass

VENUES_DB = os.path.expanduser("~/coinswaps/venue_observations.db")
BASICSWAP_DB = os.path.expanduser("~/coinswaps/basicswap_observations.db")

BUCKET_SECONDS = 300  # both pollers run every 5 minutes, at different offsets
KRAKEN_MAX_GAP_SECONDS = 900
SELL_PREMIUM_PCT = 0.018  # what the sell leg charges (restart_live_maker_btc.sh)

# Instant-swap quotes are for one probe size but re-quote at any size we'd use,
# so they count as able to fill the whole target.
QUOTE_VENUES = {"exolix", "changenow"}


@dataclass(frozen=True)
class VenueCosts:
    """Fees on top of the price walked from the book. Rough and partly assumed;
    edit here when better numbers come in."""

    pct: float  # trading fee, fraction of notional
    flat_sats: int  # network fees we pay per restock
    access: str  # custody / KYC posture, printed with the results


VENUE_COSTS: dict[str, VenueCosts] = {
    # 650 sats = economics.DEFAULT_ASSUMPTIONS.fee_round_trip_sats_today, the
    # atomic-swap network fees proof_report.py already uses.
    "basicswap": VenueCosts(0.0, 650, "DEX, atomic swap, no KYC"),
    "eigen_asb": VenueCosts(0.0, 650, "DEX, atomic swap, no KYC"),
    # Bisq taker fee paid in BSQ is 0.8625% (1.15% in BTC), per bisq.wiki/Trading_fees
    # (2026-10-02); ~1,000 sats of deposit/payout tx fees is assumed. Also needs a
    # security deposit locked for the trade.
    "bisq": VenueCosts(0.008625, 1000, "DEX, P2P escrow, no KYC; needs Bisq app + deposit"),
    # Quotes are net of the service's own fee; we only pay to send our BTC.
    "exolix": VenueCosts(0.0, 300, "custodial instant swap; no account, can freeze/ask KYC"),
    "changenow": VenueCosts(0.0, 300, "custodial instant swap; no account, can freeze/ask KYC"),
    # Kraken: 0.40% taker fee + 1,650 sats network/transfer, same as proof_report.py.
    "kraken": VenueCosts(0.004, 1650, "CEX, KYC account"),
}


@dataclass(frozen=True)
class Offer:
    rate: float  # BTC per XMR
    amount_xmr: float
    min_xmr: float


def walk_book(offers: list[Offer], target_xmr: float, size_flexible: bool = False) -> float | None:
    """Volume-weighted BTC per XMR to buy `target_xmr`, cheapest first, or None
    if the book can't fill it. Offers whose minimum would overshoot the target
    are skipped rather than over-bought."""
    remaining, btc = target_xmr, 0.0
    for o in sorted(offers, key=lambda o: o.rate):
        if o.rate <= 0:
            continue
        available = math.inf if size_flexible else o.amount_xmr
        take = min(available, remaining)
        if take <= 0 or take < o.min_xmr:
            continue
        btc += take * o.rate
        remaining -= take
        if remaining <= 1e-9:
            return btc / target_xmr
    return None


def all_in_premium(venue: str, vwap: float, mid: float, target_xmr: float) -> float:
    c = VENUE_COSTS[venue]
    notional_sats = target_xmr * mid * 1e8
    return (vwap / mid - 1.0) + c.pct + c.flat_sats / notional_sats


def _bucket(t: float) -> int:
    return int(t // BUCKET_SECONDS)


def load_books(since: float) -> dict[tuple[str, int], list[Offer]]:
    """(venue, bucket) -> the XMR-sell offers seen in that poll cycle."""
    books: dict[tuple[str, int], list[Offer]] = {}
    seen_cycle: dict[tuple[str, int], float] = {}

    def add(venue: str, polled_at: float, offer: Offer) -> None:
        key = (venue, _bucket(polled_at))
        # Keep only one poll per bucket (the first), so a bucket never double-counts.
        first = seen_cycle.setdefault(key, polled_at)
        if polled_at == first:
            books.setdefault(key, []).append(offer)

    if os.path.exists(VENUES_DB):
        conn = sqlite3.connect(f"file:{VENUES_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT venue, polled_at, implied_rate, amount_from, min_bid_amount "
            "FROM venue_offer_snapshots WHERE coin_from = 'xmr' AND coin_to = 'btc' "
            "AND is_own_offer = 0 AND polled_at >= ? ORDER BY polled_at",
            (since,),
        )
        for venue, t, rate, amount, min_amt in rows:
            add(venue, t, Offer(rate, amount, min_amt or 0.0))
        conn.close()

    if os.path.exists(BASICSWAP_DB):
        conn = sqlite3.connect(f"file:{BASICSWAP_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT polled_at, rate, amount_from, min_bid_amount FROM offer_snapshots "
            "WHERE coin_from = 'Monero' AND coin_to = 'Bitcoin' AND is_own_offer = 0 "
            "AND is_expired = 0 AND is_revoked = 0 AND is_public = 1 AND polled_at >= ? "
            "ORDER BY polled_at",
            (since,),
        )
        for t, rate, amount, min_amt in rows:
            add("basicswap", t, Offer(rate, amount, min_amt or 0.0))
        conn.close()
    return books


def load_kraken(since: float) -> list[tuple[float, float, float | None, float | None]]:
    """[(polled_at, mid BTC/XMR, depth cost for 1 XMR, for 5 XMR)], time-ordered."""
    if not os.path.exists(BASICSWAP_DB):
        return []
    conn = sqlite3.connect(f"file:{BASICSWAP_DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT polled_at, (best_bid + best_ask) / 2, buy_cost_1xmr_pct, buy_cost_5xmr_pct "
        "FROM kraken_book_snapshots WHERE polled_at >= ? ORDER BY polled_at",
        (since - KRAKEN_MAX_GAP_SECONDS,),
    ).fetchall()
    conn.close()
    return rows


def _nearest(kraken: list, t: float):
    lo, hi = 0, len(kraken)
    while lo < hi:
        mid = (lo + hi) // 2
        if kraken[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best = None
    for i in (lo - 1, lo):
        if 0 <= i < len(kraken) and abs(kraken[i][0] - t) <= KRAKEN_MAX_GAP_SECONDS:
            if best is None or abs(kraken[i][0] - t) < abs(best[0] - t):
                best = kraken[i]
    return best


@dataclass
class VenueStats:
    cycles: int = 0
    filled: list[float] | None = None
    cheapest: int = 0

    def __post_init__(self):
        self.filled = []


def compute(books, kraken, target_xmr: float) -> tuple[dict[str, VenueStats], int]:
    stats: dict[str, VenueStats] = {}
    by_bucket: dict[int, dict[str, float | None]] = {}
    for (venue, bucket), offers in books.items():
        k = _nearest(kraken, (bucket + 0.5) * BUCKET_SECONDS)
        if k is None:
            continue
        mid = k[1]
        vwap = walk_book(offers, target_xmr, size_flexible=venue in QUOTE_VENUES)
        prem = all_in_premium(venue, vwap, mid, target_xmr) if vwap else None
        by_bucket.setdefault(bucket, {})[venue] = prem

    for bucket, venues in by_bucket.items():
        k = _nearest(kraken, (bucket + 0.5) * BUCKET_SECONDS)
        depth = k[2] if target_xmr <= 1.0 else k[3]
        if depth is not None:
            venues["kraken"] = all_in_premium("kraken", k[1] * (1 + depth), k[1], target_xmr)
        priced = {v: p for v, p in venues.items() if p is not None}
        winner = min(priced, key=priced.get) if priced else None
        for venue, prem in venues.items():
            s = stats.setdefault(venue, VenueStats())
            s.cycles += 1
            if prem is not None:
                s.filled.append(prem)
            if venue == winner:
                s.cheapest += 1
    return stats, len(by_bucket)


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def render(stats: dict[str, VenueStats], n_cycles: int, target_xmr: float, days: float) -> str:
    lines = [
        f"Cost to restock {target_xmr:g} XMR with BTC, last {days:g} day(s), "
        f"{n_cycles} poll cycle(s) with a Kraken mid.",
        "All-in = price walked from the book vs. Kraken mid + trading fee + network fees.",
        "cycles = poll cycles where the venue showed at least one XMR-sell offer.",
        "",
        f"  {'venue':10} {'cycles':>6} {'can fill':>8} {'median':>8} {'p25':>8} {'best':>8} "
        f"{'cheapest':>8}  access",
    ]
    ordered = sorted(
        stats.items(),
        key=lambda kv: statistics.median(kv[1].filled) if kv[1].filled else math.inf,
    )
    for venue, s in ordered:
        fill_share = len(s.filled) / s.cycles if s.cycles else 0.0
        if s.filled:
            q = sorted(s.filled)
            med, p25, best = statistics.median(q), q[len(q) // 4], q[0]
            nums = f"{_pct(med):>8} {_pct(p25):>8} {_pct(best):>8}"
        else:
            nums = f"{'n/a':>8} {'n/a':>8} {'n/a':>8}"
        lines.append(
            f"  {venue:10} {s.cycles:>6} {fill_share:>8.0%} {nums} "
            f"{s.cheapest / s.cycles if s.cycles else 0:>8.0%}  {VENUE_COSTS[venue].access}"
        )
    lines += [
        "",
        f"The sell leg charges about {_pct(SELL_PREMIUM_PCT)} over mid. A restock path only "
        "helps if its all-in cost sits well under that; Kraken's row is the CEX baseline.",
        "Fees are partly assumed — see VENUE_COSTS in venues/restock_cost.py.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xmr", type=float, default=0.5, help="restock size in XMR (default 0.5)")
    parser.add_argument("--days", type=float, default=7.0, help="look-back window (default 7)")
    args = parser.parse_args(argv)
    since = time.time() - args.days * 86400
    stats, n = compute(load_books(since), load_kraken(since), args.xmr)
    if not stats:
        print("No poll cycles with both offers and a Kraken mid in the window.")
        return 1
    print(render(stats, n, args.xmr, args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())

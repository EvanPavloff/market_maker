"""Phase 1 evaluation (ARCHITECTURE.md §6): turn accumulated poller snapshots into
the answer to "does an edge exist" — before any strategy/offer-posting code (Phase
2+) gets built.

Market convention used here for a pair (coin_from, coin_to), e.g. (xmr, btc):
  - "ask" side  = live offers selling coin_from for coin_to (rate = coin_to per
    coin_from). The best ask is the LOWEST such rate — the cheapest a buyer of
    coin_from can currently get filled at.
  - "bid" side  = live offers selling coin_to for coin_from, inverted to the same
    coin_to-per-coin_from units (1 / rate). The best bid is the HIGHEST implied
    price — the most a seller of coin_from can currently get filled at.
  - spread = best_ask - best_bid, in coin_to-per-coin_from units. A *negative*
    spread means the two sides are already crossed (someone's mispriced, or one
    side's offer is stale) — kept as-is rather than clamped, since that itself is
    a signal worth seeing.

Only live, public, non-revoked, non-expired, not-our-own offers count — matches
what a market maker would actually see and could actually quote against.
"""

import sqlite3
import statistics
from dataclasses import dataclass

from . import storage


def _live_public(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [
        r
        for r in rows
        if not r["is_expired"] and not r["is_revoked"] and r["is_public"] and not r["is_own_offer"]
    ]


@dataclass
class PollSnapshot:
    polled_at: float
    best_ask: float | None
    best_bid: float | None
    ask_depth_count: int
    ask_depth_notional: float  # sum of amount_from across live ask offers
    bid_depth_count: int
    bid_depth_notional: float  # sum of amount_from-equivalent across live bid offers
    reference_mid: float | None
    spread_abs: float | None
    spread_pct: float | None


def _group_by_poll(rows: list[sqlite3.Row]) -> dict[float, list[sqlite3.Row]]:
    grouped: dict[float, list[sqlite3.Row]] = {}
    for r in rows:
        grouped.setdefault(r["polled_at"], []).append(r)
    return grouped


def build_poll_snapshots(
    conn: sqlite3.Connection, coin_from: str, coin_to: str, since: float | None = None
) -> list[PollSnapshot]:
    ask_rows = _group_by_poll(
        _live_public(storage.fetch_offer_snapshots(conn, coin_from, coin_to, since=since))
    )
    bid_rows = _group_by_poll(
        _live_public(storage.fetch_offer_snapshots(conn, coin_to, coin_from, since=since))
    )
    # Reference mid, preferred in this order (next_steps.md §2): a direct,
    # BasicSwap-independent lookup (external_rates.py) > BasicSwap's own (currently
    # broken) coingecko lookup > (best_ask + best_bid) / 2 below, which is circular
    # on a thin book and only used when neither external source has anything.
    direct_rate_rows = {
        r["polled_at"]: r["coingecko_rate"] if r["coingecko_rate"] is not None else r["kraken_rate"]
        for r in storage.fetch_direct_rate_snapshots(conn, coin_from, coin_to, since=since)
    }
    rate_rows = {
        r["polled_at"]: r["rate"]
        for r in storage.fetch_rate_snapshots(conn, coin_from, coin_to, since=since)
    }

    snapshots = []
    for polled_at in sorted(set(ask_rows) | set(bid_rows)):
        asks = ask_rows.get(polled_at, [])
        bids = bid_rows.get(polled_at, [])

        best_ask = min((a["rate"] for a in asks), default=None)
        # bid side offers are quoted coin_to->coin_from; invert to coin_to-per-coin_from
        best_bid = max((1.0 / b["rate"] for b in bids if b["rate"]), default=None)

        reference_mid = direct_rate_rows.get(polled_at)
        if reference_mid is None:
            reference_mid = rate_rows.get(polled_at)
        spread_abs = None
        spread_pct = None
        if best_ask is not None and best_bid is not None:
            spread_abs = best_ask - best_bid
            mid = reference_mid if reference_mid else (best_ask + best_bid) / 2
            if mid:
                spread_pct = spread_abs / mid

        snapshots.append(
            PollSnapshot(
                polled_at=polled_at,
                best_ask=best_ask,
                best_bid=best_bid,
                ask_depth_count=len(asks),
                ask_depth_notional=sum(a["amount_from"] for a in asks),
                bid_depth_count=len(bids),
                bid_depth_notional=sum(b["amount_to"] for b in bids),
                reference_mid=reference_mid,
                spread_abs=spread_abs,
                spread_pct=spread_pct,
            )
        )
    return snapshots


@dataclass
class PairSummary:
    coin_from: str
    coin_to: str
    n_polls: int
    n_two_sided_polls: int  # polls where both an ask and a bid existed at all
    two_sided_fraction: float
    mean_spread_pct: float | None
    median_spread_pct: float | None
    mean_ask_depth_count: float
    mean_bid_depth_count: float


def summarize_pair(
    conn: sqlite3.Connection, coin_from: str, coin_to: str, since: float | None = None
) -> PairSummary:
    snaps = build_poll_snapshots(conn, coin_from, coin_to, since=since)
    two_sided = [s for s in snaps if s.spread_pct is not None]
    spreads = [s.spread_pct for s in two_sided]

    return PairSummary(
        coin_from=coin_from,
        coin_to=coin_to,
        n_polls=len(snaps),
        n_two_sided_polls=len(two_sided),
        two_sided_fraction=(len(two_sided) / len(snaps)) if snaps else 0.0,
        mean_spread_pct=statistics.fmean(spreads) if spreads else None,
        median_spread_pct=statistics.median(spreads) if spreads else None,
        mean_ask_depth_count=statistics.fmean(s.ask_depth_count for s in snaps) if snaps else 0.0,
        mean_bid_depth_count=statistics.fmean(s.bid_depth_count for s in snaps) if snaps else 0.0,
    )


def format_summary(summary: PairSummary) -> str:
    pct = lambda x: "n/a" if x is None else f"{x * 100:.3f}%"
    return (
        f"{summary.coin_from}/{summary.coin_to}: {summary.n_polls} polls, "
        f"{summary.n_two_sided_polls} two-sided ({summary.two_sided_fraction:.0%}). "
        f"spread mean={pct(summary.mean_spread_pct)} median={pct(summary.median_spread_pct)}. "
        f"avg depth: {summary.mean_ask_depth_count:.1f} ask offers / "
        f"{summary.mean_bid_depth_count:.1f} bid offers."
    )


def main() -> None:
    """CLI: python -m basicswap.strategy.analysis (reads config for db_path/pairs)."""
    from . import coin_names
    from .config import load_config

    config = load_config()
    conn = storage.connect(config.db_path)
    for coin_from, coin_to in config.pairs:
        # config.pairs are tickers ("xmr", "btc"); storage keys on BasicSwap's
        # display name ("Monero", "Bitcoin") — see coin_names.py/poller.py.
        summary = summarize_pair(
            conn, coin_names.to_display_name(coin_from), coin_names.to_display_name(coin_to)
        )
        print(format_summary(summary))


if __name__ == "__main__":
    main()

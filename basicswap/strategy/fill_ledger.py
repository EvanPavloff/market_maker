"""Per-fill P&L ledger (market_maker/next_steps.md #3 + #4, built 2026-09-24).

Read-only against BasicSwap: pulls /json/bids, keeps only bids that landed
on offers live_maker.py itself posted (matched via live_quote_events.offer_id,
so a manual/bid_scanner bid never gets mistaken for a maker fill), and
records each Completed/Expired/etc. outcome into a `fills` table keyed by
bid_id. That's the fill-vs-expiry distinction #4 asked for — BasicSwap's own
bid_state already carries it, no log parsing needed.

For each Completed fill it values the trade against the reference mid at
fill time and again at +1h and +24h (markouts), so edge-at-fill can be
separated from adverse selection / inventory drift — the 2026-09-18 ask
fill is the motivating case: ~-0.2% at fill, ~-7% by the next hour.

Reference mid = mean of the available CoinGecko/Kraken readings in
direct_rate_snapshots nearest the timestamp (within MAX_REF_GAP_SECONDS),
falling back to live_quote_events.reference_mid. Network fees are NOT
netted (BasicSwap doesn't expose them per bid) — edge figures are gross.

BTC numeraire (added 2026-09-25, market_maker goal = accumulate BTC, not
USD): every edge/markout is also shown as sats gained/lost, alongside its USD
value at the fill-time BTC/USD price. Per fill the two are proportional (one
BTC price scales the other) — where they genuinely diverge is inventory, so
the report also nets every completed fill into a per-coin position change and
marks it to today's XMR/BTC mid: that sats figure is "how many more (or fewer)
BTC do I have than if I had never traded", the number the BTC goal is scored on.

Usage: ./run_fill_ledger.sh            (sync + print report)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from . import storage
from .api_client import BasicSwapClient
from .coin_names import to_display_name, to_ticker
from .config import load_config

MAX_REF_GAP_SECONDS = 20 * 60
MARKOUT_HORIZONS = {"1h": 3600, "24h": 86400}
SATS_PER_BTC = 100_000_000
BTC = "Bitcoin"


def _nearest(rows: list[tuple[float, float]], t: float) -> float | None:
    best = min(rows, key=lambda r: abs(r[0] - t), default=None)
    if best is None or abs(best[0] - t) > MAX_REF_GAP_SECONDS:
        return None
    return best[1]


def reference_mid(conn: sqlite3.Connection, t: float, coin_from: str, coin_to: str) -> float | None:
    """Mid in units of coin_to per 1 coin_from at time t, or None if no
    reading lies within MAX_REF_GAP_SECONDS. Checks both stored directions and
    both naming conventions (poller has written "xmr" and "Monero")."""
    cf, ct = to_display_name(coin_from), to_display_name(coin_to)
    lo, hi = t - MAX_REF_GAP_SECONDS, t + MAX_REF_GAP_SECONDS
    for a, b, invert in ((cf, ct, False), (ct, cf, True)):
        rows = []
        for pt, cg, kr, rf, rt in conn.execute(
            "SELECT polled_at, coingecko_rate, kraken_rate, coin_from, coin_to "
            "FROM direct_rate_snapshots WHERE polled_at BETWEEN ? AND ?", (lo, hi)
        ):
            if to_display_name(rf) != a or to_display_name(rt) != b:
                continue
            vals = [v for v in (cg, kr) if v]
            if vals:
                m = sum(vals) / len(vals)
                rows.append((pt, 1 / m if invert else m))
        mid = _nearest(rows, t)
        if mid is not None:
            return mid
    for a, b, invert in ((cf, ct, False), (ct, cf, True)):
        rows = [
            (ts, 1 / m if invert else m)
            for ts, m in conn.execute(
                "SELECT created_at, reference_mid FROM live_quote_events "
                "WHERE coin_from = ? AND coin_to = ? AND created_at BETWEEN ? AND ?", (a, b, lo, hi)
            )
        ]
        mid = _nearest(rows, t)
        if mid is not None:
            return mid
    return None


def edge_pct(amount_from: float, amount_to: float, mid: float | None) -> float | None:
    """Signed edge of receiving amount_to for giving amount_from, vs. mid
    (coin_to per coin_from). Positive = we got more than fair value."""
    if not mid:
        return None
    return amount_to / (amount_from * mid) - 1


def pnl_btc(coin_from: str, coin_to: str, amount_from: float, amount_to: float, edge: float | None) -> float | None:
    """BTC gained (negative = lost) vs. fair value, from a stored edge_pct —
    no mid lookup needed, since edge = amount_to / (amount_from * mid) - 1
    already pins the mid down. Giving BTC: amount_from * edge. Receiving BTC:
    amount_to * edge / (1 + edge). None for a pair with no BTC leg."""
    if edge is None:
        return None
    if to_display_name(coin_from) == BTC:
        return amount_from * edge
    if to_display_name(coin_to) == BTC:
        return amount_to * edge / (1 + edge)
    return None


def net_flows(rows) -> dict[str, float]:
    """Per-coin position change summed over Completed fills (display-name keyed)."""
    flows: dict[str, float] = {}
    for r in rows:
        if r["bid_state"] != "Completed":
            continue
        flows[r["coin_from"]] = flows.get(r["coin_from"], 0.0) - r["amount_from"]
        flows[r["coin_to"]] = flows.get(r["coin_to"], 0.0) + r["amount_to"]
    return flows


def own_offer_sides(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT DISTINCT offer_id, side FROM live_quote_events"))


def sync(conn: sqlite3.Connection, bids: list[dict], now: float | None = None) -> int:
    """Upsert every bid on one of our own offers. Markouts whose horizon
    hasn't elapsed yet (or has no reference reading) stay NULL and get
    filled in on a later sync. Returns the number of rows written."""
    now = time.time() if now is None else now
    sides = own_offer_sides(conn)
    n = 0
    for b in bids:
        side = sides.get(b.get("offer_id"))
        if side is None:
            continue
        cf, ct = b["coin_from"], b["coin_to"]
        a_from, a_to = float(b["amount_from"]), float(b["amount_to"])
        t = float(b["created_at"])
        completed = b.get("bid_state") == "Completed"
        mid = reference_mid(conn, t, cf, ct) if completed else None
        marks = {}
        for label, dt in MARKOUT_HORIZONS.items():
            m = reference_mid(conn, t + dt, cf, ct) if completed and now >= t + dt else None
            marks[label] = edge_pct(a_from, a_to, m)
        storage.upsert_fill(
            conn,
            bid_id=b["bid_id"], offer_id=b["offer_id"], venue="basicswap", side=side,
            coin_from=to_display_name(cf), coin_to=to_display_name(ct),
            amount_from=a_from, amount_to=a_to, rate=float(b["bid_rate"]),
            bid_state=b.get("bid_state", ""), bid_created_at=t,
            reference_mid_at_fill=mid, edge_pct_at_fill=edge_pct(a_from, a_to, mid),
            markout_1h_pct=marks["1h"], markout_24h_pct=marks["24h"], synced_at=now,
        )
        n += 1
    return n


def _fmt(p: float | None) -> str:
    return "     n/a" if p is None else f"{p * 100:+7.2f}%"


def _sats(b: float | None) -> str:
    return "      n/a" if b is None else f"{b * SATS_PER_BTC:+9,.0f}"


def _usd(v: float) -> str:
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def report(
    conn: sqlite3.Connection,
    btc_usd_at=None,
    btc_per_coin_now: dict[str, float] | None = None,
    btc_usd_now: float | None = None,
) -> str:
    """`btc_usd_at(t)` -> BTC/USD at time t; `btc_per_coin_now` maps a coin's
    display name to its current BTC price; `btc_usd_now` is today's BTC/USD.
    All optional (network-sourced in main()) — anything missing prints n/a."""
    rows = storage.fetch_fills(conn)
    lines = [f"{'created':16} {'side':4} {'state':10} {'gave':>22} {'got':>22} {'@fill':>8} {'+1h':>8} {'+24h':>8}"]
    done = []
    for r in rows:
        lines.append(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['bid_created_at']))} {r['side']:4} "
            f"{r['bid_state'][:10]:10} {r['amount_from']:13.8f} {r['coin_from'][:8]:>8} "
            f"{r['amount_to']:13.8f} {r['coin_to'][:8]:>8} {_fmt(r['edge_pct_at_fill'])} "
            f"{_fmt(r['markout_1h_pct'])} {_fmt(r['markout_24h_pct'])}"
        )
        if r["bid_state"] == "Completed":
            done.append(r)
    states: dict[str, int] = {}
    for r in rows:
        states[r["bid_state"]] = states.get(r["bid_state"], 0) + 1
    lines.append(f"\nbids on own offers: {len(rows)}  by state: {states}")
    for key, label in (("edge_pct_at_fill", "@fill"), ("markout_1h_pct", "+1h"), ("markout_24h_pct", "+24h")):
        vals = [r[key] for r in done if r[key] is not None]
        if vals:
            lines.append(f"mean edge {label:5} over {len(vals)} completed fill(s): {sum(vals) / len(vals) * 100:+.2f}% (gross of network fees)")

    lines.append("\n--- BTC numeraire: sats gained vs. fair value (gross of network fees) ---")
    lines.append(f"{'created':16} {'side':4} {'@fill':>9} {'+1h':>9} {'+24h':>9} {'BTC/USD@fill':>13} {'USD@fill':>9}")
    totals: dict[str, list[float]] = {"@fill": [], "+1h": [], "+24h": []}
    usd_total: list[float] = []
    for r in done:
        pnl = {
            label: pnl_btc(r["coin_from"], r["coin_to"], r["amount_from"], r["amount_to"], r[key])
            for key, label in (("edge_pct_at_fill", "@fill"), ("markout_1h_pct", "+1h"), ("markout_24h_pct", "+24h"))
        }
        for label, v in pnl.items():
            if v is not None:
                totals[label].append(v)
        px = None
        if btc_usd_at is not None:
            try:
                px = btc_usd_at(r["bid_created_at"])
            except Exception:  # noqa: BLE001 - a missing price prints n/a, never kills the report
                px = None
        usd = pnl["@fill"] * px if px is not None and pnl["@fill"] is not None else None
        if usd is not None:
            usd_total.append(usd)
        lines.append(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['bid_created_at']))} {r['side']:4} "
            f"{_sats(pnl['@fill'])} {_sats(pnl['+1h'])} {_sats(pnl['+24h'])} "
            f"{'n/a' if px is None else f'{px:,.0f}':>13} {'n/a' if usd is None else _usd(usd):>9}"
        )
    for label, vals in totals.items():
        if vals:
            lines.append(f"total sats {label:5} over {len(vals)} fill(s): {sum(vals) * SATS_PER_BTC:+,.0f}")
    if usd_total:
        lines.append(f"total USD  @fill over {len(usd_total)} fill(s): {_usd(sum(usd_total))}  (each fill at its own BTC/USD)")

    flows = net_flows(rows)
    if flows:
        lines.append("\n--- Net position change from completed fills (vs. never having traded) ---")
        marked, missing = 0.0, False
        for coin, qty in sorted(flows.items()):
            if coin == BTC:
                btc_val: float | None = qty
            else:
                p = (btc_per_coin_now or {}).get(coin)
                btc_val = qty * p if p is not None else None
            lines.append(f"  {coin:8} {qty:+.8f}  = {_sats(btc_val).strip()} sats at today's price")
            if btc_val is None:
                missing = True
            else:
                marked += btc_val
        if missing:
            lines.append("  net: n/a (no current price for every coin)")
        else:
            usd = f"  ({_usd(marked * btc_usd_now)} at BTC/USD {btc_usd_now:,.0f})" if btc_usd_now else ""
            lines.append(f"  net: {marked * SATS_PER_BTC:+,.0f} sats{usd}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report-only", action="store_true", help="skip the BasicSwap sync, just print")
    args = ap.parse_args(argv)
    cfg = load_config()
    conn = storage.connect(cfg.db_path)
    if not args.report_only:
        n = sync(conn, BasicSwapClient(cfg.api_url).get_bids())
        print(f"synced {n} bid(s) on own offers")
    from . import external_rates

    btc_per_coin_now: dict[str, float] = {}
    for coin in net_flows(storage.fetch_fills(conn)):
        if coin != BTC:
            try:
                mid = external_rates.get_reference_rate(to_ticker(coin), "btc").mid
                if mid is not None:
                    btc_per_coin_now[coin] = mid
            except external_rates.ExternalRateError as e:
                print(f"warning: no current {coin}/BTC price: {e}", file=sys.stderr)
    try:
        btc_usd_now = external_rates.get_usd_price("btc")
    except external_rates.ExternalRateError as e:
        print(f"warning: no current BTC/USD price: {e}", file=sys.stderr)
        btc_usd_now = None
    print(report(conn, external_rates.get_btc_usd_at, btc_per_coin_now, btc_usd_now))
    return 0


if __name__ == "__main__":
    sys.exit(main())

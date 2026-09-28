"""Bisq XMR/BTC trade-flow analysis — how big is the market we're competing
for, and which direction pays (market_maker/project_status.md's 2026-09-24
handoff item 5). Read-only, on-demand, not part of the scheduled poller.

Bisq's trade API has no direction field, so the paying side is inferred by
comparing each trade's price to Kraken's hourly VWAP for the same hour
(Kraken's public OHLC endpoint returns ~30 days at 60-min resolution). A
price above VWAP (in BTC per XMR) means the XMR buyer paid a premium, so the
XMR seller earned it.

    python -m venues.bisq.trade_flow [--days 30]
"""

import argparse
import json
import statistics
import time
import urllib.request

from .client import _SSL_CONTEXT, _USER_AGENT, BisqMarketsClient

_KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC?pair=XMRXBT&interval=60"


def _kraken_hourly_vwap() -> dict[int, float]:
    req = urllib.request.Request(_KRAKEN_OHLC_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(f"Kraken OHLC error: {data['error']}")
    rows = next(v for k, v in data["result"].items() if k != "last")
    # [time, open, high, low, close, vwap, volume, count]; vwap is 0 in an empty hour
    return {int(r[0]): float(r[5]) or float(r[4]) for r in rows}


def summarize(trades: list[dict], vwap_by_hour: dict[int, float], days: float) -> dict:
    now = time.time()
    rows = []
    for t in trades:
        ts = t["trade_date"] / 1000
        if ts < now - days * 86400:
            continue
        price, btc = float(t["price"]), float(t["volume"])
        vwap = vwap_by_hour.get(int(ts // 3600 * 3600))
        rows.append((btc, price / vwap - 1 if vwap else None))
    sizes = sorted(b for b, _ in rows)
    devs = [(b, d) for b, d in rows if d is not None]
    dev_sorted = sorted(d for _, d in devs)
    matched_btc = sum(b for b, _ in devs)

    def q(xs, p):
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None

    return {
        "days": days,
        "trades": len(rows),
        "trades_per_day": len(rows) / days,
        "btc_per_day": sum(sizes) / days,
        "size_btc_p25_p50_p75": (q(sizes, 0.25), statistics.median(sizes) if sizes else None, q(sizes, 0.75)),
        "matched_to_kraken": len(devs),
        "premium_vs_vwap_p10_p50_p90": (q(dev_sorted, 0.1), q(dev_sorted, 0.5), q(dev_sorted, 0.9)),
        "share_trades_below_vwap": sum(d < 0 for d in dev_sorted) / len(dev_sorted) if devs else None,
        "share_btc_volume_below_vwap": (
            sum(b for b, d in devs if d < 0) / matched_btc if matched_btc else None
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=float, default=30.0, help="<= 30 to stay inside Kraken's hourly history")
    args = parser.parse_args(argv)
    trades = BisqMarketsClient(timeout_seconds=20).get_trades("xmr_btc", time.time() - args.days * 86400)
    for k, v in summarize(trades, _kraken_hourly_vwap(), args.days).items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

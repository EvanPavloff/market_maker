"""Record money moved into or out of the BasicSwap wallets by hand (2026-10-21).

proof_report.py scores actual P&L as the latest wallet balances minus these
flows, so a deposit never reads as profit and a withdrawal never as a loss.
Record one every time funds go in or out other than through a trade: a seed
top-up, a Kraken transfer, moving BTC out to cold storage. Swaps (BasicSwap
fills, Exolix restocks) are trades, not flows; never record those here.

A `baseline` row per coin marks the starting balance of a scoring window.

Usage:
    python3 -m strategy.capital_flows add --coin xmr --amount 0.5 --kind deposit --note "from Kraken"
    python3 -m strategy.capital_flows add --coin btc --amount -0.002 --kind withdrawal --at "2026-10-22 09:00"
    python3 -m strategy.capital_flows list
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from . import coin_names, storage
from .config import load_config

KINDS = ("baseline", "deposit", "withdrawal")


def _parse_at(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--coin", required=True, help="ticker, e.g. btc or xmr")
    add.add_argument("--amount", type=float, required=True, help="+ into the wallets, - out")
    add.add_argument("--kind", choices=KINDS, required=True)
    add.add_argument("--at", help='epoch or "YYYY-MM-DD HH:MM" local; default: now')
    add.add_argument("--note")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    conn = storage.connect(load_config().db_path)
    if args.cmd == "add":
        if args.kind == "deposit" and args.amount <= 0 or args.kind == "withdrawal" and args.amount >= 0:
            print("a deposit must be positive and a withdrawal negative", file=sys.stderr)
            return 1
        at = _parse_at(args.at) if args.at else time.time()
        storage.insert_capital_flow(conn, at, coin_names.to_display_name(args.coin), args.amount, args.kind, args.note)
    for f in storage.fetch_capital_flows(conn, until=float("inf")):
        when = datetime.fromtimestamp(f["at"]).strftime("%Y-%m-%d %H:%M")
        print(f"{f['id']:>4}  {when}  {f['kind']:<10} {f['coin']:<8} {f['amount']:+.8f}  {f['note'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

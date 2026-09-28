"""One-shot XMR top-up: if the XMR wallet is worth less than --target-usd, buy
the shortfall (plus a small buffer) with BTC by bidding into the cheapest
public BasicSwap offer selling XMR for BTC, at that offer's own posted rate.
Asked for by Evan 2026-09-25 ("if I don't have at least $210 of XMR by 7PM,
swap BTC to XMR"), after the bid-side incident took the wallet to ~$87.

Unlike bid_scanner.py (which only bids when an offer is priced BELOW mid,
i.e. an opportunistic edge), this accepts paying up to --max-premium-pct
ABOVE the reference mid. XMR sellers normally charge a premium (Bisq trades
clear ~+2% over Kraken VWAP), so a top-up has to pay it.

Refuses to bid (exits non-zero, nothing submitted) if:
  - any non-terminal Monero->Bitcoin swap exists. On 2026-09-25 three accepted
    swaps sat retrying a lock of XMR the wallet didn't have; new XMR arriving
    would be locked straight into them at below-market prices. Abandon them
    in the BasicSwap UI first.
  - CoinGecko and Kraken disagree by more than --max-source-disagreement-pct.
  - no offer is at or under the premium cap with room for the needed amount,
    or the BTC wallet can't cover it.

Every submitted bid is logged to bid_scan_events (same audit trail as
bid_scanner.py). Without --live it only prints what it would do.

    python -m strategy.topup_xmr                # dry run
    python -m strategy.topup_xmr --live         # actually bid
"""

import argparse
import logging
import sys
import time

from . import external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .bid_scanner import BidScannerConfig, _bid_one, scan_candidates
from .config import load_config
from .external_rates import ExternalRateError
from .live_maker import _in_flight_swaps

log = logging.getLogger("basicswap.strategy.topup_xmr")


def plan_topup(
    client: BasicSwapClient,
    target_usd: float,
    max_premium_pct: float,
    buffer_pct: float,
    max_source_disagreement_pct: float,
    now: float | None = None,
) -> dict:
    """Decides what (if anything) to bid. Returns a dict with "action" in
    {"none", "abort", "bid"} and the numbers behind it. Makes no writes."""
    now = now if now is not None else time.time()
    stuck = _in_flight_swaps(client, "xmr", "btc")
    if stuck:
        return {"action": "abort", "reason": "in-flight Monero->Bitcoin swaps: " + ", ".join(
            f"{b.get('bid_id', '?')[:16]} ({b.get('bid_state')})" for b in stuck)}

    rate = external_rates.get_reference_rate("xmr", "btc")
    if rate.disagreement_pct is not None and rate.disagreement_pct > max_source_disagreement_pct:
        return {"action": "abort", "reason": f"CoinGecko/Kraken disagree by {rate.disagreement_pct:.2%}"}
    mid = rate.coingecko_rate if rate.coingecko_rate is not None else rate.kraken_rate
    xmr_usd = external_rates.get_usd_price("xmr")
    if mid is None or not xmr_usd:
        return {"action": "abort", "reason": "no usable reference rate / XMR USD price"}

    xmr_balance = client.get_wallet_balance("xmr")
    value_usd = xmr_balance * xmr_usd
    plan = {"xmr_balance": xmr_balance, "xmr_usd": xmr_usd, "value_usd": value_usd,
            "reference_mid_btc_per_xmr": mid}
    if value_usd >= target_usd:
        return {**plan, "action": "none", "reason": f"${value_usd:.2f} >= ${target_usd:.2f}"}

    need_xmr = (target_usd / xmr_usd - xmr_balance) * (1 + buffer_pct)
    ceiling = mid * (1 + max_premium_pct)
    cfg = BidScannerConfig(coin_from="xmr", coin_to="btc", half_spread_pct=0.0,
                           max_bid_amount=need_xmr, max_cycle_exposure=need_xmr)
    btc_balance = client.get_wallet_balance("btc")
    for offer in scan_candidates(client, cfg, ceiling, exclude_offer_ids=set(), now=now):
        offer_amount = float(offer.get("amount_from") or 0)
        min_bid = float(offer.get("min_bid_amount") or 0)
        if offer_amount < need_xmr or min_bid > need_xmr:
            continue
        btc_cost = need_xmr * float(offer["rate"])
        if btc_cost > btc_balance:
            return {**plan, "action": "abort", "reason": (
                f"cheapest fitting offer needs {btc_cost:.8f} BTC, wallet has {btc_balance:.8f}")}
        return {**plan, "action": "bid", "offer": offer, "need_xmr": need_xmr,
                "btc_cost": btc_cost, "premium_pct": float(offer["rate"]) / mid - 1,
                "usd_price_from": xmr_usd}
    return {**plan, "action": "abort", "need_xmr": need_xmr, "reason": (
        f"no offer at <= {max_premium_pct:.1%} over mid ({ceiling:.8f} BTC/XMR) with room for "
        f"{need_xmr:.8f} XMR")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot BTC->XMR top-up to a USD target.")
    parser.add_argument("--live", action="store_true", help="actually submit the bid")
    parser.add_argument("--target-usd", type=float, default=210.0)
    parser.add_argument("--max-premium-pct", type=float, default=0.03,
                        help="max offer rate over reference mid (BTC per XMR) we'll pay")
    parser.add_argument("--buffer-pct", type=float, default=0.05,
                        help="buy this much extra so a small XMR dip doesn't leave us short again")
    parser.add_argument("--max-source-disagreement-pct", type=float, default=0.015)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = load_config()
    client = BasicSwapClient(config.api_url, auth_user=config.auth_user,
                             auth_password=config.auth_password, timeout_seconds=60)
    try:
        plan = plan_topup(client, args.target_usd, args.max_premium_pct, args.buffer_pct,
                          args.max_source_disagreement_pct)
    except (BasicSwapAPIError, ExternalRateError) as e:
        log.error("ABORT: %s", e)
        return 2

    shown = {k: v for k, v in plan.items() if k != "offer"}
    if plan["action"] == "none":
        log.info("no top-up needed: %s", shown)
        return 0
    if plan["action"] == "abort":
        log.error("ABORT, nothing submitted: %s", shown)
        return 1

    offer = plan["offer"]
    log.info("%s: bid %.8f XMR on offer %s @ %s BTC/XMR (%.2f%% over mid), ~%.8f BTC — %s",
             "LIVE" if args.live else "DRY RUN", plan["need_xmr"], offer["offer_id"], offer["rate"],
             plan["premium_pct"] * 100, plan["btc_cost"], shown)
    if not args.live:
        return 0
    conn = storage.connect(config.db_path)
    bid_id = _bid_one(
        client, conn, BidScannerConfig(coin_from="xmr", coin_to="btc", half_spread_pct=0.0,
                                       max_bid_amount=plan["need_xmr"],
                                       max_cycle_exposure=plan["need_xmr"]),
        offer, plan["reference_mid_btc_per_xmr"], plan["need_xmr"], plan["usd_price_from"],
        time.time(),
    )
    log.info("submitted bid %s — track it in the BasicSwap UI (Bids)", bid_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Automated BTC->XMR restock through Exolix (instant swap) for the accumulate-BTC
trial's sell leg. Built 2026-10-21 on Evan's explicit go-ahead ("build the Exolix
auto-restock with those caps"), because the sell offer was live only 32% of the
time: the trial was short of XMR to sell, not of buyers, and our own maker restock
offer filled too rarely (12 in 3 weeks) to keep up. Exolix's all-in cost for
0.5 XMR was a +0.66% median over 7 days (`python3 -m venues.restock_cost`).

Exolix is custodial for the few minutes a swap takes and can hold a deposit its
security system flags and ask for documents (its AML/KYC policy). Every cap below
exists to bound that exposure to about one swap.

One run (launchd runs it every 15 minutes):
  1. If the halt file exists, stop. A human clears it after checking.
  2. Reconcile swaps in flight against Exolix. Halts on: a row left in `created`
     (BTC may or may not have gone out) or `send_error`; Exolix reporting
     overdue/refunded; no success within MAX_IN_FLIGHT_HOURS; delivered XMR under
     MIN_DELIVERED_RATIO of the quote.
  3. Only one swap at a time, and none within COOLDOWN after a success (the new
     XMR needs ~20 minutes of confirmations before the sell leg can use it).
  4. Trigger: XMR above the reserve (balance + unconfirmed) under trigger_xmr.
     Refill to reserve + target_working_xmr. Skips if our own restock offer has a
     swap in flight (XMR already on its way).
  5. Caps: max_btc_per_swap, max_swaps_per_day, max_btc_per_week. Price: skip if
     the all-in cost (Exolix float quote + assumed BTC network fee) is more than
     max_premium_pct over the Kraken mid.
  6. Live only: create the Exolix exchange, check it echoed our own XMR address
     and gave a plausible BTC deposit address, re-check the price on its quote,
     record the row, THEN send BTC from BasicSwap's wallet.

Without --live it stops after step 5 and logs what it would do.

    python -m strategy.exolix_restock           # dry run
    python -m strategy.exolix_restock --live    # real swap when triggered
    rm ~/coinswaps/exolix_restock.halt          # clear a halt after checking
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .config import load_config
from .external_rates import ExternalRateError
from .live_maker import _in_flight_swaps

log = logging.getLogger("basicswap.strategy.exolix_restock")

HALT_FILE = os.path.expanduser("~/coinswaps/exolix_restock.halt")
EXOLIX_API = "https://exolix.com/api/v2"
# Exolix sits behind Cloudflare, which blocks urllib's default User-Agent and
# curl's; this one is what venues/instant_swap/client.py has polled with since 10-02.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

EXOLIX_SUCCESS = {"success"}
EXOLIX_FAILED = {"overdue", "refunded", "failed"}
_BTC_ADDRESS = re.compile(r"^(bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
_XMR_PRIMARY_ADDRESS = re.compile(r"^4[1-9AB][1-9A-HJ-NP-Za-km-z]{93}$")


@dataclass(frozen=True)
class RestockConfig:
    reserve_xmr: float = 0.385          # matches restart_live_maker_btc.sh RESERVE_XMR
    trigger_xmr: float = 0.2            # restock when XMR above the reserve is under this
    target_working_xmr: float = 0.55    # refill to reserve + this (one full sell offer)
    min_swap_xmr: float = 0.2           # don't bother below this
    max_btc_per_swap: float = 0.004
    max_swaps_per_day: int = 2
    max_btc_per_week: float = 0.015
    max_premium_pct: float = 0.010      # all-in, vs. the Kraken mid
    network_fee_btc: float = 0.00001    # assumed ~1,000 sats for the BTC send
    btc_floor: float = 0.0002           # leave at least this in the BTC wallet after sending
    max_source_disagreement_pct: float = 0.015
    max_in_flight_hours: float = 4.0
    cooldown_minutes: float = 60.0
    min_delivered_ratio: float = 0.97
    quote_markup: float = 0.007         # sizes the BTC amount: need_xmr * mid * (1 + this)


class ExolixError(RuntimeError):
    pass


class ExolixClient:
    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{EXOLIX_API}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=_SSL_CONTEXT) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise ExolixError(f"{method} {path} -> HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ExolixError(f"{method} {path} failed: {e}") from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ExolixError(f"{method} {path} returned non-JSON: {raw[:200]!r}") from e

    def rate(self, amount_btc: float) -> dict:
        q = urllib.parse.urlencode({
            "coinFrom": "BTC", "networkFrom": "BTC", "coinTo": "XMR", "networkTo": "XMR",
            "amount": f"{amount_btc:.8f}", "rateType": "float",
        })
        rv = self._call("GET", f"/rate?{q}")
        if not isinstance(rv, dict) or not rv.get("toAmount"):
            raise ExolixError(f"rate has no toAmount: {rv!r}")
        return rv

    def create(self, amount_btc: float, withdrawal_address: str, refund_address: str) -> dict:
        rv = self._call("POST", "/transactions", {
            "coinFrom": "BTC", "networkFrom": "BTC", "coinTo": "XMR", "networkTo": "XMR",
            "amount": f"{amount_btc:.8f}", "withdrawalAddress": withdrawal_address,
            "refundAddress": refund_address, "rateType": "float",
        })
        if not isinstance(rv, dict):
            raise ExolixError(f"create returned {rv!r}")
        return rv

    def get(self, exolix_id: str) -> dict:
        rv = self._call("GET", f"/transactions/{urllib.parse.quote(exolix_id)}")
        if not isinstance(rv, dict):
            raise ExolixError(f"transaction {exolix_id} returned {rv!r}")
        return rv


def _coin_code(v: Any) -> str | None:
    return v.get("coinCode") if isinstance(v, dict) else v


def validate_created(tx: dict, amount_btc: float, xmr_address: str) -> str | None:
    """Reason not to send BTC to this exchange, or None if it checks out."""
    if not tx.get("id"):
        return f"no id in {tx!r}"
    if tx.get("withdrawalAddress") != xmr_address:
        return f"withdrawalAddress {tx.get('withdrawalAddress')!r} is not our XMR address"
    if not _BTC_ADDRESS.match(str(tx.get("depositAddress") or "")):
        return f"depositAddress {tx.get('depositAddress')!r} doesn't look like a BTC address"
    try:
        if abs(float(tx.get("amount")) - amount_btc) > 1e-8:
            return f"amount {tx.get('amount')!r} != requested {amount_btc:.8f}"
        if float(tx.get("amountTo") or 0) <= 0:
            return f"no amountTo in {tx!r}"
    except (TypeError, ValueError):
        return f"unparseable amounts in {tx!r}"
    for key, want in (("coinFrom", "BTC"), ("coinTo", "XMR")):
        got = _coin_code(tx.get(key))
        if got is not None and str(got).upper() != want:
            return f"{key} is {got!r}, expected {want}"
    return None


def all_in_premium(amount_btc: float, xmr_out: float, mid: float, cfg: RestockConfig) -> float:
    """Effective BTC per XMR including the BTC network fee, vs. the reference mid."""
    return (amount_btc + cfg.network_fee_btc) / xmr_out / mid - 1


def reconcile(conn, exolix: ExolixClient, cfg: RestockConfig, now: float) -> tuple[str | None, bool]:
    """Updates open swaps from Exolix. Returns (halt reason or None, any still in flight)."""
    in_flight = False
    for row in storage.fetch_exolix_swaps(conn):
        sid, status = row["exolix_id"], row["status"]
        if status in ("success", "failed"):
            continue
        if status in ("created", "send_error"):
            return (f"swap {sid} is '{status}': check in BasicSwap's BTC wallet whether "
                    f"{row['amount_btc']:.8f} BTC went to {row['deposit_address']}, then fix the row"), True
        in_flight = True  # status == "sent"
        age_h = (now - row["created_at"]) / 3600
        try:
            tx = exolix.get(sid)
        except ExolixError as e:
            if age_h > cfg.max_in_flight_hours:
                return f"swap {sid} unresolved after {age_h:.1f}h and Exolix lookup failed: {e}", True
            log.warning("Exolix lookup for %s failed (%.1fh old), will retry: %s", sid, age_h, e)
            continue
        ex_status = str(tx.get("status") or "").lower()
        if ex_status in EXOLIX_SUCCESS:
            delivered = float(tx.get("amountTo") or 0)
            storage.update_exolix_swap(conn, sid, status="success", exolix_status=ex_status,
                                       delivered_xmr=delivered, updated_at=now)
            log.info("swap %s complete: %.8f XMR delivered (quoted %.8f)", sid, delivered, row["quoted_xmr"])
            in_flight = False
            if delivered < row["quoted_xmr"] * cfg.min_delivered_ratio:
                return (f"swap {sid} delivered {delivered:.8f} XMR, under {cfg.min_delivered_ratio:.0%} "
                        f"of the {row['quoted_xmr']:.8f} quoted"), False
        elif ex_status in EXOLIX_FAILED:
            storage.update_exolix_swap(conn, sid, status="failed", exolix_status=ex_status, updated_at=now)
            return f"swap {sid}: Exolix status '{ex_status}' (check whether the BTC was refunded)", False
        else:
            storage.update_exolix_swap(conn, sid, exolix_status=ex_status, updated_at=now)
            if age_h > cfg.max_in_flight_hours:
                return f"swap {sid} still '{ex_status}' after {age_h:.1f}h", True
    return None, in_flight


def plan(client: BasicSwapClient, conn, exolix: ExolixClient, cfg: RestockConfig, now: float) -> dict:
    """{"action": "none" | "skip" | "swap", ...}. Makes no writes."""
    rows = storage.fetch_exolix_swaps(conn, since=now - 7 * 86400)
    last_success = max((r["updated_at"] for r in rows if r["status"] == "success"), default=None)
    if last_success is not None and now - last_success < cfg.cooldown_minutes * 60:
        return {"action": "none", "reason": f"cooldown: last swap finished {(now - last_success) / 60:.0f} min ago"}

    xmr = client.get_wallet("xmr")
    have_xmr = float(xmr["balance"]) + float(xmr.get("unconfirmed") or 0)
    above_reserve = have_xmr - cfg.reserve_xmr
    info = {"have_xmr": have_xmr, "above_reserve": above_reserve}
    if above_reserve >= cfg.trigger_xmr:
        return {**info, "action": "none", "reason": f"{above_reserve:.4f} XMR above reserve >= trigger {cfg.trigger_xmr}"}
    need_xmr = cfg.reserve_xmr + cfg.target_working_xmr - have_xmr
    if need_xmr < cfg.min_swap_xmr:
        return {**info, "action": "none", "reason": f"need {need_xmr:.4f} XMR < min swap {cfg.min_swap_xmr}"}
    restocking = _in_flight_swaps(client, "btc", "xmr")
    if restocking:
        return {**info, "action": "skip", "reason": f"{len(restocking)} BTC->XMR swap(s) already in flight on BasicSwap"}

    day = [r for r in rows if r["created_at"] >= now - 86400]
    if len(day) >= cfg.max_swaps_per_day:
        return {**info, "action": "skip", "reason": f"{len(day)} swaps in the last 24h (cap {cfg.max_swaps_per_day})"}
    week_btc = sum(r["amount_btc"] for r in rows if r["status"] != "failed" or r["btc_txid"])

    rate = external_rates.get_reference_rate("xmr", "btc")
    if rate.disagreement_pct is not None and rate.disagreement_pct > cfg.max_source_disagreement_pct:
        return {**info, "action": "skip", "reason": f"CoinGecko/Kraken disagree by {rate.disagreement_pct:.2%}"}
    mid = rate.kraken_rate if rate.kraken_rate is not None else rate.coingecko_rate
    if not mid:
        return {**info, "action": "skip", "reason": "no reference rate"}

    amount_btc = min(round(need_xmr * mid * (1 + cfg.quote_markup), 8), cfg.max_btc_per_swap)
    if week_btc + amount_btc > cfg.max_btc_per_week:
        return {**info, "action": "skip",
                "reason": f"{week_btc:.8f} BTC sent in 7 days + {amount_btc:.8f} > cap {cfg.max_btc_per_week}"}
    btc_balance = float(client.get_wallet("btc")["balance"])
    if btc_balance - amount_btc - cfg.network_fee_btc < cfg.btc_floor:
        return {**info, "action": "skip", "reason": f"BTC wallet {btc_balance:.8f} too small for {amount_btc:.8f}"}

    quote = exolix.rate(amount_btc)
    xmr_out = float(quote["toAmount"])
    premium = all_in_premium(amount_btc, xmr_out, mid, cfg)
    info.update(need_xmr=need_xmr, amount_btc=amount_btc, quoted_xmr=xmr_out, mid=mid, premium=premium)
    if premium > cfg.max_premium_pct:
        return {**info, "action": "skip", "reason": f"Exolix all-in {premium:+.2%} > cap {cfg.max_premium_pct:+.2%}"}
    return {**info, "action": "swap"}


def execute(client: BasicSwapClient, conn, exolix: ExolixClient, cfg: RestockConfig, p: dict, now: float) -> str | None:
    """Creates the exchange and sends the BTC. Returns a halt reason, or None."""
    xmr_address = client.get_wallet("xmr").get("main_address")
    refund_address = client.get_wallet("btc").get("deposit_address")
    if not _XMR_PRIMARY_ADDRESS.match(str(xmr_address or "")):
        return f"BasicSwap's XMR main_address {xmr_address!r} doesn't look like a primary address"
    if not _BTC_ADDRESS.match(str(refund_address or "")):
        return f"BasicSwap's BTC deposit_address {refund_address!r} doesn't look like a BTC address"

    amount_btc = p["amount_btc"]
    tx = exolix.create(amount_btc, xmr_address, refund_address)
    problem = validate_created(tx, amount_btc, xmr_address)
    if problem:
        return f"Exolix exchange failed checks, no BTC sent: {problem}"
    quoted_xmr = float(tx["amountTo"])
    premium = all_in_premium(amount_btc, quoted_xmr, p["mid"], cfg)
    row = {
        "exolix_id": tx["id"], "created_at": now, "updated_at": now, "status": "created",
        "exolix_status": str(tx.get("status") or ""), "amount_btc": amount_btc, "quoted_xmr": quoted_xmr,
        "reference_mid": p["mid"], "all_in_premium_pct": premium, "deposit_address": tx["depositAddress"],
        "withdrawal_address": xmr_address,
    }
    if premium > cfg.max_premium_pct:
        # Never funded, so the exchange just expires on Exolix's side.
        storage.insert_exolix_swap(conn, {**row, "status": "failed", "note": f"not funded: quote moved to {premium:+.2%}"})
        log.warning("Exolix exchange %s quoted %+.2f%% all-in, over the cap: not sending BTC", tx["id"], premium * 100)
        return None
    storage.insert_exolix_swap(conn, row)
    try:
        txid = client.withdraw("btc", tx["depositAddress"], f"{amount_btc:.8f}")
    except Exception as e:  # noqa: BLE001 — any failure here leaves it unknown whether BTC went out
        storage.update_exolix_swap(conn, tx["id"], status="send_error", note=str(e)[:500], updated_at=time.time())
        return f"BTC send for Exolix swap {tx['id']} failed or is unknown: {e}"
    storage.update_exolix_swap(conn, tx["id"], status="sent", btc_txid=txid, updated_at=time.time())
    log.info("LIVE: sent %.8f BTC to Exolix %s (deposit %s, txid %s) for ~%.8f XMR, %+.2f%% all-in",
             amount_btc, tx["id"], tx["depositAddress"], txid, quoted_xmr, premium * 100)
    _notify("Exolix restock sent", f"{amount_btc:.8f} BTC -> ~{quoted_xmr:.4f} XMR ({premium:+.2%} all-in)")
    return None


def _notify(title: str, message: str) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    subprocess.run(["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"'],
                   capture_output=True)


def _halt(reason: str) -> int:
    with open(HALT_FILE, "w") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {reason}\n")
    log.error("HALTED: %s (clear with: rm %s)", reason, HALT_FILE)
    _notify("Exolix restock HALTED", reason[:200])
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated BTC->XMR restock through Exolix (see module docstring).")
    parser.add_argument("--live", action="store_true", help="actually create the exchange and send BTC")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if os.path.exists(HALT_FILE):
        with open(HALT_FILE) as f:
            log.error("halted, doing nothing until a human clears it: %s", f.read().strip())
        return 1

    cfg = RestockConfig()
    config = load_config()
    client = BasicSwapClient(config.api_url, auth_user=config.auth_user,
                             auth_password=config.auth_password, timeout_seconds=60)
    conn = storage.connect(config.db_path)
    exolix = ExolixClient()
    now = time.time()

    halt, in_flight = reconcile(conn, exolix, cfg, now)
    if halt:
        return _halt(halt)
    if in_flight:
        log.info("a swap is in flight, waiting for it")
        return 0
    try:
        p = plan(client, conn, exolix, cfg, now)
    except (BasicSwapAPIError, ExternalRateError, ExolixError) as e:
        log.warning("skipping this run: %s", e)
        return 0
    shown = {k: (round(v, 8) if isinstance(v, float) else v) for k, v in p.items()}
    if p["action"] != "swap":
        log.info("%s: %s", p["action"], shown)
        return 0
    if not args.live:
        log.info("DRY RUN, would swap: %s", shown)
        return 0
    try:
        halt = execute(client, conn, exolix, cfg, p, now)
    except (BasicSwapAPIError, ExolixError) as e:
        # Raised before any row was written, so no BTC can have moved.
        log.warning("exchange not created, nothing sent: %s", e)
        return 0
    return _halt(halt) if halt else 0


if __name__ == "__main__":
    sys.exit(main())

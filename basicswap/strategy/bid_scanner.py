"""Opportunistic bid-scanning — actively bid into OTHER makers' live offers when
priced better than our own target rate, rather than only posting our own offer
and waiting (live_maker.py's job). Scoped in next_steps.md #9 (2026-09-20) at
Evan's request ("is BasicSwap's own AMM offer-posting bot worth stealing
from?" — see that item for the full comparison), built the same day at his
explicit "go ahead and build" follow-up.

Distinct risk profile from live_maker.py, worth restating even though the
--live gate and funding checks below mirror it closely: posting/revoking OUR
OWN offer is a free, reversible, off-chain SMSG broadcast (next_steps.md §8).
Bidding into someone else's offer is not reversible the same way — it
actually starts a real atomic swap and commits capital for the swap's full
duration (42m30s observed in the one real test swap so far, next_steps.md's
"Real test swap completed" section) to a counterparty whose willingness to
complete isn't under our control. Every bid here is submitted at the offer's
OWN posted rate (bid_rate = offer's rate, matching createoffers.py's own
place_bid_on_offer convention and this project's existing exact_rate_only
posture) — never negotiated, same rate_negotiable danger next_steps.md §8
already flagged.

Auditability (Evan's explicit requirement when authorizing this feature,
2026-09-20): every bid this module submits is logged to its own
`bid_scan_events` table (storage.py), kept separate from live_maker.py's
`live_quote_events` — so this activity's own P&L can be evaluated
independently of the ask/bid maker-offer strategy, not conflated with it.
Each row records the EXTERNAL reference_mid at decision time (external_rates
.py, never anything from BasicSwap's own offer book) alongside the offer's
own posted rate, so `edge_pct` measures what a bid captured against an
independent price source. reconcile_bid_outcomes() (run every live cycle,
or standalone via --reconcile-only) polls api_client.get_bid() for each
still-unresolved bid and records its real terminal BidStates outcome
(Completed vs. Abandoned/Failed/Timed-out/etc) — this closes a gap
live_maker.py's own docstring explicitly flagged as not built ("for our OWN
offers /json/bids could in principle answer this"), and matters more here
than it would there: a bid that never completes still tied up capital for
nothing, and only a real outcome check can tell that apart from a success.

Safety posture, mirrored from live_maker.py for consistency:
  - Requires --live to actually call post_bid(). Without it, this module
    scans and logs what it WOULD bid (dry-run) but never submits anything
    and never writes to bid_scan_events — unlike live_maker.py, this dry-run
    mode IS built in here directly (no separate quoter.py-style module),
    since there's no live offer state to reconcile against in dry-run mode,
    only a read-only scan.
  - Same reference-rate guards as live_maker.py's run_cycle, in the same
    order: source-disagreement gate first (external_rates.py's independent
    Kraken cross-check), then the volatility kill-switch — both skip the
    whole cycle's bidding, same fail-safe-toward-caution posture as
    everywhere else in this project.
  - Funding is checked in coin_to units (what we'd pay) immediately before
    each bid, using the live wallet balance — never assumed from a prior
    cycle's reading.
  - Never re-bids an offer this process already has an unresolved bid
    against (_already_bid_offer_ids) — avoids stacking a second commitment
    on top of a still-in-flight one against the same counterparty offer.
  - half_spread_pct is a FLOOR (the minimum edge vs. reference_mid required
    before bidding at all), composed each cycle with economics.py's already-
    built dynamic_half_spread_pct — same volatility-scaled cost model
    live_maker.py's own dynamic spread uses (next_steps.md #15 Phase A),
    reused rather than re-derived.
"""

import argparse
import logging
import time
from dataclasses import dataclass

from . import coin_names, economics, external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .config import load_config
from .external_rates import ExternalRateError
from .quoter import half_spread_rate
from .volatility import VolatilityMonitor

log = logging.getLogger("basicswap.strategy.bid_scanner")

# BidStates display strings (basicswap_util.py's strBidState, read directly
# from source 2026-09-20 — not guessed) that represent a genuinely finished
# bid, successful or not. Everything else (Sent, Accepted, Initiated,
# Participating, Delaying, Auto accept delay, ...) is still in progress.
# Hardcoded rather than imported: this project's strategy code never imports
# basicswap's own package (keeps the API boundary at the JSON layer, same
# posture api_client.py's own docstring already states).
_TERMINAL_SUCCESS = {"Completed"}
_TERMINAL_FAILURE = {
    "Timed-out", "Abandoned", "Error", "Rejected", "Expired",
    "Auto accept failed", "Failed", "Failed, refunded", "Failed, swiped",
    "Failed, swiped, sending mercy", "Failed, swiped, recovering",
    "Failed, swiped, recovered", "Failed, swiped, mercy unused",
}


@dataclass
class BidScannerConfig:
    coin_from: str  # the OFFER's own coin_from -- what counterparties are selling, what we're buying
    coin_to: str  # the OFFER's own coin_to -- what we pay with
    half_spread_pct: float  # floor edge required vs reference_mid -- see economics.dynamic_half_spread_pct
    max_bid_amount: float  # per-bid cap, in coin_from units
    max_cycle_exposure: float  # total coin_from committed across one cycle's bids
    min_offer_remaining_seconds: float = 300.0
    max_bids_per_cycle: int = 3
    assumed_fill_hours: float = 2.5  # see live_maker.py's own field of the same name/meaning
    kill_switch_window_minutes: float = 15.0
    kill_switch_volatility_pct: float = 0.0085
    max_source_disagreement_pct: float = 0.015


def _target_rate_ceiling(reference_mid: float, half_spread_pct: float) -> float:
    """Max offer rate (coin_to per coin_from) worth bidding on -- reuses
    quoter.py's half_spread_rate with side='bid' (quote below mid), since
    bidding is inherently the buying half of market-making: a LOWER rate
    means paying less coin_to per unit of coin_from, which is better for us."""
    return half_spread_rate(reference_mid, half_spread_pct, "bid")


def _already_bid_offer_ids(conn, coin_from: str, coin_to: str) -> set[str]:
    """Offer ids with a still-unresolved bid_scan_events row -- skip these on
    a rescan so a slow-resolving bid never gets a second bid stacked on top
    of it against the same offer."""
    rows = storage.fetch_bid_scan_events(conn, coin_from, coin_to, resolved=False)
    return {r["offer_id"] for r in rows}


def scan_candidates(
    client: BasicSwapClient,
    cfg: BidScannerConfig,
    target_rate: float,
    exclude_offer_ids: set[str],
    now: float | None = None,
) -> list[dict]:
    """Live public offers on (coin_from, coin_to) priced at or better than
    target_rate, excluding our own offers, already-expired/revoked ones,
    ones we already have an unresolved bid against, and ones about to expire
    (cfg.min_offer_remaining_seconds). Sorted cheapest-rate-first (best for
    us as the buyer)."""
    now = now if now is not None else time.time()
    offers = client.get_offers(coin_from=cfg.coin_from, coin_to=cfg.coin_to)
    candidates = []
    for o in offers:
        if o.get("is_own_offer") or o.get("is_expired") or o.get("is_revoked"):
            continue
        offer_id = o.get("offer_id")
        if offer_id in exclude_offer_ids:
            continue
        try:
            rate = float(o["rate"])
        except (KeyError, TypeError, ValueError):
            continue
        if rate > target_rate:
            continue
        expire_at = o.get("expire_at")
        if expire_at is not None and (expire_at - now) < cfg.min_offer_remaining_seconds:
            continue
        candidates.append(o)
    candidates.sort(key=lambda o: float(o["rate"]))
    return candidates


def _size_bid(offer: dict, cfg: BidScannerConfig, remaining_cycle_budget: float) -> float | None:
    """How much of offer_coin_from to bid for -- bounded by the offer's own
    posted amount_from and (if set) min_bid_amount, our own per-bid cap, and
    whatever's left of this cycle's exposure budget. None means nothing
    viable fits (e.g. the offer's own min_bid_amount exceeds everything else
    allows, or the budget is already exhausted)."""
    try:
        offer_amount = float(offer["amount_from"])
    except (KeyError, TypeError, ValueError):
        return None
    min_bid = float(offer.get("min_bid_amount") or 0.0)
    ceiling = min(offer_amount, cfg.max_bid_amount, remaining_cycle_budget)
    if ceiling <= 0 or ceiling < min_bid:
        return None
    return ceiling


def _bid_one(
    client: BasicSwapClient,
    conn,
    cfg: BidScannerConfig,
    offer: dict,
    reference_mid: float,
    amount_from: float,
    usd_price_from: float | None,
    now: float,
) -> str:
    """Submits one real bid at the offer's own posted rate (never negotiated
    -- see module docstring) and logs it to bid_scan_events. Caller is
    responsible for the funding check before calling this, same
    check-before-act convention as live_maker.py's _check_funded. Returns
    the new bid_id."""
    offer_rate = float(offer["rate"])
    offer_id = offer["offer_id"]
    amount_from_str = f"{amount_from:.8f}"
    rate_str = f"{offer_rate:.8f}"
    bid_id = client.post_bid(offer_id, amount_from_str, rate_str)
    amount_to = amount_from * offer_rate
    edge_pct = (reference_mid - offer_rate) / reference_mid
    usd_notional = amount_from * usd_price_from if usd_price_from is not None else None
    storage.insert_bid_scan_event(
        conn, cfg.coin_from, cfg.coin_to, offer_id, bid_id, offer_rate,
        reference_mid, edge_pct, amount_from, amount_to,
        usd_notional=usd_notional,
        offer_created_at=offer.get("created_at"), offer_expire_at=offer.get("expire_at"),
        created_at=now,
    )
    log.info(
        "%s/%s: BID %s on offer %s, amount_from=%s @ rate=%s (reference_mid=%.8f, edge=%.3f%%)",
        coin_names.to_display_name(cfg.coin_from), coin_names.to_display_name(cfg.coin_to),
        bid_id, offer_id, amount_from_str, rate_str, reference_mid, edge_pct * 100,
    )
    return bid_id


def run_cycle(
    client: BasicSwapClient,
    conn,
    cfg: BidScannerConfig,
    volatility_monitor: VolatilityMonitor,
    live: bool = True,
) -> list[str]:
    """One scan(+bid) cycle. Returns the bid_ids actually submitted this
    cycle (always empty when live=False — dry-run mode only scans and logs,
    never calls post_bid or writes to bid_scan_events). Guard ordering
    mirrors live_maker.py's run_cycle for a consistent safety posture:
    reference rate -> source-disagreement gate -> volatility kill-switch."""
    try:
        rate = external_rates.get_reference_rate(cfg.coin_from, cfg.coin_to)
    except ExternalRateError as e:
        log.warning("get_reference_rate(%s, %s) failed, skipping this cycle: %s", cfg.coin_from, cfg.coin_to, e)
        return []
    reference_mid = rate.coingecko_rate if rate.coingecko_rate is not None else rate.kraken_rate
    if reference_mid is None:
        log.warning("no usable reference rate for %s/%s this cycle, skipping", cfg.coin_from, cfg.coin_to)
        return []

    if rate.disagreement_pct is not None and rate.disagreement_pct > cfg.max_source_disagreement_pct:
        log.warning(
            "%s/%s: CoinGecko/Kraken disagree by %.3f%% (coingecko=%s kraken=%s), exceeds "
            "%.3f%% threshold — skipping bid-scanning this cycle.",
            cfg.coin_from, cfg.coin_to, rate.disagreement_pct * 100,
            rate.coingecko_rate, rate.kraken_rate, cfg.max_source_disagreement_pct * 100,
        )
        return []

    now = time.time()
    volatility_monitor.add(now, reference_mid)
    vol_pct = volatility_monitor.volatility_pct()
    if vol_pct is not None and vol_pct > cfg.kill_switch_volatility_pct:
        log.warning(
            "%s/%s: volatility kill-switch active (%.3f%% move over the last %.0fm exceeds "
            "%.3f%% threshold) — skipping bid-scanning this cycle.",
            cfg.coin_from, cfg.coin_to, vol_pct * 100,
            cfg.kill_switch_window_minutes, cfg.kill_switch_volatility_pct * 100,
        )
        return []

    half_spread_pct = cfg.half_spread_pct
    if rate.usd_price_from is not None:
        notional_usd_estimate = cfg.max_bid_amount * rate.usd_price_from
        half_spread_pct = economics.dynamic_half_spread_pct(
            operator_floor_pct=cfg.half_spread_pct,
            notional_usd=notional_usd_estimate,
            lock_hours=cfg.assumed_fill_hours,
            live_vol_pct=vol_pct,
            live_vol_window_seconds=cfg.kill_switch_window_minutes * 60,
        )
    target_rate = _target_rate_ceiling(reference_mid, half_spread_pct)

    exclude = _already_bid_offer_ids(conn, cfg.coin_from, cfg.coin_to)
    try:
        candidates = scan_candidates(client, cfg, target_rate, exclude, now=now)
    except BasicSwapAPIError as e:
        log.error("get_offers failed, skipping this cycle: %s", e)
        return []

    if not candidates:
        return []

    bid_ids: list[str] = []
    remaining_budget = cfg.max_cycle_exposure
    for offer in candidates:
        if len(bid_ids) >= cfg.max_bids_per_cycle or remaining_budget <= 0:
            break
        amount_from = _size_bid(offer, cfg, remaining_budget)
        if amount_from is None:
            continue

        if not live:
            log.info(
                "[DRY RUN] would bid %.8f %s on offer %s @ rate=%s (reference_mid=%.8f) — "
                "pass --live to actually submit.",
                amount_from, cfg.coin_from.upper(), offer.get("offer_id"), offer["rate"], reference_mid,
            )
            remaining_budget -= amount_from
            continue

        amount_to_needed = amount_from * float(offer["rate"])
        try:
            available = client.get_wallet_balance(cfg.coin_to)
        except BasicSwapAPIError as e:
            log.warning("get_wallet_balance(%s) failed, skipping this cycle: %s", cfg.coin_to, e)
            break
        if available < amount_to_needed:
            log.info(
                "%s/%s: %.8f %s available, need %.8f to bid on offer %s — stopping this "
                "cycle's bidding rather than continuing to other candidates (expected once "
                "the wallet is mostly committed to open bids/offers).",
                cfg.coin_from, cfg.coin_to, available, cfg.coin_to.upper(),
                amount_to_needed, offer.get("offer_id"),
            )
            break

        try:
            bid_id = _bid_one(
                client, conn, cfg, offer, reference_mid, amount_from, rate.usd_price_from, now
            )
        except BasicSwapAPIError as e:
            log.error("post_bid failed for offer %s, skipping: %s", offer.get("offer_id"), e)
            continue
        bid_ids.append(bid_id)
        remaining_budget -= amount_from

    return bid_ids


def _classify_bid_state(bid_state: str) -> tuple[bool, str | None]:
    """(resolved, outcome) for a BidStates display string. outcome is only
    ever 'success'/'failure' once resolved, else None."""
    if bid_state in _TERMINAL_SUCCESS:
        return True, "success"
    if bid_state in _TERMINAL_FAILURE:
        return True, "failure"
    return False, None


def reconcile_bid_outcomes(client: BasicSwapClient, conn) -> int:
    """Polls api_client.get_bid() for every bid_scan_events row not yet
    resolved and updates its real BidStates outcome. This is the audit
    mechanism Evan explicitly required when authorizing this feature
    (2026-09-20): without it, bid_scan_events would only ever show what was
    ATTEMPTED, never what actually happened — a bid that silently never
    completes would look identical to one that did. Returns the number of
    rows newly marked resolved this call."""
    rows = storage.fetch_bid_scan_events(conn, resolved=False)
    newly_resolved = 0
    for row in rows:
        try:
            detail = client.get_bid(row["bid_id"])
        except BasicSwapAPIError as e:
            log.warning("get_bid(%s) failed, will retry next reconcile: %s", row["bid_id"], e)
            continue
        bid_state = detail.get("bid_state", "")
        resolved, outcome = _classify_bid_state(bid_state)
        storage.update_bid_scan_event_outcome(
            conn, row["bid_id"], bid_state, resolved, outcome,
            resolved_at=time.time() if resolved else None,
        )
        if resolved:
            newly_resolved += 1
            log.info("bid %s resolved: %s (%s)", row["bid_id"], bid_state, outcome)
    return newly_resolved


def run(cfg: BidScannerConfig, loop: bool, live: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = BasicSwapClient(
        config.api_url,
        auth_user=config.auth_user,
        auth_password=config.auth_password,
        timeout_seconds=config.request_timeout_seconds,
    )
    conn = storage.connect(config.db_path)
    volatility_monitor = VolatilityMonitor(window_seconds=cfg.kill_switch_window_minutes * 60)
    log.info(
        "%s BID-SCANNING: %s/%s half_spread_floor_pct=%.4f max_bid_amount=%.8f "
        "max_cycle_exposure=%.8f max_bids_per_cycle=%d min_offer_remaining_seconds=%.0f "
        "assumed_fill_hours=%.2f kill_switch_window_minutes=%.1f kill_switch_volatility_pct=%.4f "
        "max_source_disagreement_pct=%.4f db=%s",
        "LIVE" if live else "DRY-RUN",
        cfg.coin_from, cfg.coin_to, cfg.half_spread_pct, cfg.max_bid_amount,
        cfg.max_cycle_exposure, cfg.max_bids_per_cycle, cfg.min_offer_remaining_seconds,
        cfg.assumed_fill_hours, cfg.kill_switch_window_minutes, cfg.kill_switch_volatility_pct,
        cfg.max_source_disagreement_pct, config.db_path,
    )

    def _cycle():
        run_cycle(client, conn, cfg, volatility_monitor, live=live)
        if live:
            try:
                reconcile_bid_outcomes(client, conn)
            except BasicSwapAPIError as e:
                log.warning("reconcile_bid_outcomes failed this cycle: %s", e)

    _cycle()
    while loop:
        time.sleep(config.poll_interval_seconds)
        _cycle()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="REQUIRED to actually call post_bid. Without it, this script only scans "
        "and logs what it WOULD bid — no bid is submitted, nothing is written to "
        "bid_scan_events.",
    )
    parser.add_argument("--loop", action="store_true", help="poll forever instead of a single cycle")
    parser.add_argument(
        "--reconcile-only", action="store_true",
        help="skip scanning entirely — just poll get_bid() for every unresolved "
        "bid_scan_events row, update its real outcome, print a count, and exit.",
    )
    parser.add_argument("--coin-from", default="btc", help="the OFFER's own coin_from -- what we're buying")
    parser.add_argument("--coin-to", default="xmr", help="the OFFER's own coin_to -- what we pay with")
    parser.add_argument("--max-bid-amount", type=float, help="per-bid cap, coin_from units (required unless --reconcile-only)")
    parser.add_argument("--max-cycle-exposure", type=float, help="total coin_from committed per cycle (required unless --reconcile-only)")
    parser.add_argument(
        "--half-spread-pct", type=float, default=0.02,
        help="floor edge required vs reference_mid before bidding at all -- same "
        "derivation as live_maker.py's --half-spread-pct (economics.py's cost model).",
    )
    parser.add_argument("--max-bids-per-cycle", type=int, default=3)
    parser.add_argument("--min-offer-remaining-seconds", type=float, default=300.0)
    parser.add_argument("--assumed-fill-hours", type=float, default=2.5)
    parser.add_argument("--kill-switch-window-minutes", type=float, default=15.0)
    parser.add_argument("--kill-switch-volatility-pct", type=float, default=0.0085)
    parser.add_argument("--max-source-disagreement-pct", type=float, default=0.015)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = BasicSwapClient(
        config.api_url, auth_user=config.auth_user, auth_password=config.auth_password,
        timeout_seconds=config.request_timeout_seconds,
    )

    if args.reconcile_only:
        conn = storage.connect(config.db_path)
        n = reconcile_bid_outcomes(client, conn)
        print(f"Reconciled: {n} bid(s) newly resolved.")
        return 0

    if args.max_bid_amount is None or args.max_cycle_exposure is None:
        print("--max-bid-amount and --max-cycle-exposure are both required unless --reconcile-only.")
        return 1

    if not args.live:
        print(
            "Running in DRY-RUN mode (no --live passed): will scan and log what it WOULD "
            "bid, but will not call post_bid or write to bid_scan_events. Pass --live to "
            "actually submit bids."
        )

    cfg = BidScannerConfig(
        coin_from=args.coin_from,
        coin_to=args.coin_to,
        half_spread_pct=args.half_spread_pct,
        max_bid_amount=args.max_bid_amount,
        max_cycle_exposure=args.max_cycle_exposure,
        max_bids_per_cycle=args.max_bids_per_cycle,
        min_offer_remaining_seconds=args.min_offer_remaining_seconds,
        assumed_fill_hours=args.assumed_fill_hours,
        kill_switch_window_minutes=args.kill_switch_window_minutes,
        kill_switch_volatility_pct=args.kill_switch_volatility_pct,
        max_source_disagreement_pct=args.max_source_disagreement_pct,
    )
    try:
        run(cfg, loop=args.loop, live=args.live)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

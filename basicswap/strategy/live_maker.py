"""Live market-making loop — real BasicSwap offers, real BTC/XMR. Built 2026-09-17
with Evan's explicit go-ahead for a first live test (see project_status.md's
matching entry). Same decision logic as quoter.py's dry-run simulator (drift past
a threshold, or a stale quote past its validity window -> revoke + repost), but
this module actually calls api_client.py's post_offer()/revoke_offer() instead of
only logging to a simulated table.

Safety notes:
  - Requires --live on the command line (no default-on path) — running this
    module with no flags does nothing but print what it *would* do, one extra
    layer under quoter.py's own dry-run-only design.
  - Uses BasicSwap's real /json/sentoffers as the source of truth for "what's
    currently live" every cycle, not just this script's own local log — if the
    process restarts, or an offer disappears between polls (filled, expired, or
    revoked some other way), the next cycle reconciles against real state rather
    than trusting stale local memory.
  - automation_strat_id=1 (BasicSwap's own built-in "Accept All" strategy) is
    used by default — confirmed live 2026-09-17 to already have
    exact_rate_only=True and max_concurrent_bids=1 baked in, so bids can't fill
    at an off-quote rate and only one bid is processed at a time.
  - If a previously-tracked offer_id is no longer in /json/sentoffers, that's
    logged loudly (WARN) rather than silently treated as "nothing to see here"
    — it could mean the offer simply expired, or it could mean a real bid filled
    it. Disambiguating those needs checking basicswap.log/`/json/bids` by hand
    (next_steps.md §3 already found passive polling can't tell fills from
    cancellations for offers generally; for our OWN offers /json/bids could in
    principle answer this — not built here, a real gap for a future pass, not a
    blocker for a first live test).
"""

import argparse
import dataclasses
import logging
import time
from dataclasses import dataclass

from . import coin_names, external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .config import load_config
from .external_rates import ExternalRateError
from .quoter import half_spread_rate

log = logging.getLogger("basicswap.strategy.live_maker")

# analysis.py's convention: "ask" = selling coin_from for coin_to. A pair
# (coin_from="btc", coin_to="xmr") with side="ask" means offering BTC, wanting
# XMR back — the only side fundable right now (only BTC is in the wallet).
SIDE_TO_OFFER_DIRECTION = {"ask": (0, 1), "bid": (1, 0)}  # index into (coin_from, coin_to)


@dataclass
class LiveMakerConfig:
    coin_from: str
    coin_to: str
    side: str
    half_spread_pct: float
    reprice_threshold_pct: float
    offer_valid_hours: float  # our own repricing cadence backstop
    lock_hours: float  # the offer's own HTLC lock window
    valid_hours: float  # the offer's own BasicSwap-enforced expiry (a backstop under ours)
    amount_from: float | None = None  # fixed offer size; mutually exclusive with reserve_usd
    reserve_usd: float | None = None  # "offer everything above this USD value" — see _dynamic_amount_from
    automation_strat_id: int | None = 1

    def __post_init__(self):
        has_fixed = self.amount_from is not None
        has_reserve = self.reserve_usd is not None
        if has_fixed == has_reserve:
            raise ValueError("exactly one of amount_from or reserve_usd must be set")


class InsufficientBalanceError(RuntimeError):
    """The wallet no longer has enough of coin_from to post/replace this quote
    — most likely because the live offer was actually filled. Not treated as a
    loop-halting anomaly like AmbiguousLiveOffersError: it's an expected outcome
    (this is exactly how "will all my BTC turn into XMR" gets answered — it
    doesn't, because this stops the loop from re-offering funds it doesn't
    have), so run_cycle logs it and moves on rather than crashing."""


class AmbiguousLiveOffersError(RuntimeError):
    """More than one live own offer found for a pair/side that should have at
    most one — real state doesn't match what this loop's own logic should ever
    produce (it always revokes before posting again). Raised, not silently
    resolved, so decide_and_act never "fixes" this by posting a third offer on
    top of an already-confused state."""


def _find_own_live_offer(client: BasicSwapClient, coin_from: str, coin_to: str) -> dict | None:
    """Real state, not our own log — /json/sentoffers, filtered to this exact
    direction and still-live. None means no live offer (safe to post fresh);
    raises AmbiguousLiveOffersError if more than one is found."""
    offers = client.get_sent_offers(coin_from=coin_from, coin_to=coin_to)
    live = [o for o in offers if not o.get("is_expired") and not o.get("is_revoked")]
    if len(live) > 1:
        raise AmbiguousLiveOffersError(
            f"found {len(live)} live own offers for {coin_from}->{coin_to}, expected at "
            f"most 1 (ids: {[o.get('offer_id') for o in live]}) — resolve manually before "
            "this loop will act again on this pair"
        )
    return live[0] if live else None


def decide_and_act(
    client: BasicSwapClient,
    conn,
    cfg: LiveMakerConfig,
    reference_mid: float,
    now: float | None = None,
) -> str | None:
    now = now if now is not None else time.time()
    coin_from, coin_to = coin_names.to_display_name(cfg.coin_from), coin_names.to_display_name(cfg.coin_to)
    target_rate = half_spread_rate(reference_mid, cfg.half_spread_pct, cfg.side)
    target_rate_str = f"{target_rate:.8f}"
    amount_str = f"{cfg.amount_from:.8f}"

    prior_logged = storage.fetch_latest_live_quote_event(conn, coin_from, coin_to, cfg.side)
    real_live_offer = _find_own_live_offer(client, cfg.coin_from, cfg.coin_to)

    if prior_logged is not None and real_live_offer is None:
        log.warning(
            "%s/%s %s: previously-tracked offer %s is no longer live (expired, revoked, or "
            "possibly FILLED — check basicswap.log to tell which). Will try to post a fresh "
            "quote if the wallet still has funds for it.",
            coin_from,
            coin_to,
            cfg.side,
            prior_logged["offer_id"],
        )

    def _check_funded() -> None:
        # BasicSwap itself doesn't check wallet balance at offer-post time
        # (validateOfferAmounts only checks chain min/max, not funds) — an
        # unfunded offer would otherwise post "successfully" and only fail
        # later, when a real bid tries to fund the lock tx. Checked BEFORE any
        # revoke, not just before posting — a reprice/expire_repost that revokes
        # a perfectly good, funded offer and then discovers it can't afford the
        # replacement would leave nothing live at all, which is worse than
        # leaving the (slightly stale) original offer alone.
        available = client.get_wallet_balance(cfg.coin_from)
        if available < cfg.amount_from:
            raise InsufficientBalanceError(
                f"{coin_from}/{coin_to} {cfg.side}: wallet has {available:.8f} {cfg.coin_from.upper()}, "
                f"need {cfg.amount_from:.8f} to post this quote — not posting/revoking. This is "
                f"expected once the live offer has actually been filled; fund the wallet again or "
                f"lower --amount-from to keep quoting."
            )

    def _post_new_quote() -> str:
        return client.post_offer(
            cfg.coin_from,
            cfg.coin_to,
            amount_str,
            target_rate_str,
            lock_hours=cfg.lock_hours,
            valid_hours=cfg.valid_hours,
            automation_strat_id=cfg.automation_strat_id,
        )

    if real_live_offer is None:
        _check_funded()
        offer_id = _post_new_quote()
        storage.insert_live_quote_event(
            conn, coin_from, coin_to, cfg.side, "post", offer_id, cfg.amount_from,
            target_rate, reference_mid, created_at=now,
        )
        log.info("%s/%s %s: POSTED offer %s @ rate=%s", coin_from, coin_to, cfg.side, offer_id, target_rate_str)
        return "post"

    live_rate = float(real_live_offer["rate"])
    live_offer_id = real_live_offer["offer_id"]
    live_created_at = real_live_offer.get("created_at", now)
    drift_pct = abs(target_rate - live_rate) / live_rate
    age_seconds = now - live_created_at

    if drift_pct > cfg.reprice_threshold_pct:
        action = "reprice"
    elif age_seconds > cfg.offer_valid_hours * 3600:
        action = "expire_repost"
    else:
        return None

    _check_funded()
    client.revoke_offer(live_offer_id, refuse_if_negotiating=True)
    new_offer_id = _post_new_quote()
    storage.insert_live_quote_event(
        conn, coin_from, coin_to, cfg.side, action, new_offer_id, cfg.amount_from,
        target_rate, reference_mid,
        previous_offer_id=live_offer_id, previous_rate=live_rate,
        previous_posted_at=live_created_at, drift_pct=drift_pct, created_at=now,
    )
    log.info(
        "%s/%s %s: %s — revoked %s @ %.8f, posted %s @ %.8f (drift=%.3f%%)",
        coin_from, coin_to, cfg.side, action, live_offer_id, live_rate,
        new_offer_id, target_rate, drift_pct * 100,
    )
    return action


def _resolve_amount_from(client: BasicSwapClient, cfg: LiveMakerConfig) -> float | None:
    """cfg.amount_from if fixed; otherwise (cfg.reserve_usd set) computes
    "everything above the reserve" fresh each cycle — a dollar reserve has to
    be converted against a live price, not a number picked once and reused,
    since both the wallet balance and the coin's USD price move over time.
    Returns None (meaning: skip this cycle, don't call decide_and_act at all)
    if nothing is available above the reserve — deliberately does NOT touch an
    already-live offer in that case; only new posts are blocked, matching
    decide_and_act's own "never destroy a working offer" caution elsewhere."""
    if cfg.amount_from is not None:
        return cfg.amount_from

    try:
        usd_price = external_rates.get_usd_price(cfg.coin_from)
    except ExternalRateError as e:
        log.warning("get_usd_price(%s) failed, skipping this cycle: %s", cfg.coin_from, e)
        return None
    available = client.get_wallet_balance(cfg.coin_from)
    reserve_coin = cfg.reserve_usd / usd_price
    dynamic_amount = available - reserve_coin
    if dynamic_amount <= 0:
        log.info(
            "%s: %.8f available, reserving %.8f (~$%.2f at $%.2f/coin) — nothing free to offer "
            "this cycle, any existing live offer is left untouched.",
            cfg.coin_from, available, reserve_coin, cfg.reserve_usd, usd_price,
        )
        return None
    return dynamic_amount


def run_cycle(client: BasicSwapClient, conn, cfg: LiveMakerConfig) -> None:
    try:
        rate = external_rates.get_reference_rate(cfg.coin_from, cfg.coin_to)
    except ExternalRateError as e:
        log.warning("get_reference_rate(%s, %s) failed, skipping this cycle: %s", cfg.coin_from, cfg.coin_to, e)
        return
    reference_mid = rate.coingecko_rate if rate.coingecko_rate is not None else rate.kraken_rate
    if reference_mid is None:
        log.warning("no usable reference rate for %s/%s this cycle, skipping", cfg.coin_from, cfg.coin_to)
        return

    amount_from = _resolve_amount_from(client, cfg)
    if amount_from is None:
        return
    cfg_for_cycle = (
        cfg
        if cfg.amount_from is not None
        else dataclasses.replace(cfg, amount_from=amount_from, reserve_usd=None)
    )

    try:
        decide_and_act(client, conn, cfg_for_cycle, reference_mid)
    except InsufficientBalanceError as e:
        log.error("%s — will keep checking each cycle in case the wallet is funded again.", e)
    except BasicSwapAPIError as e:
        log.error("live_maker cycle failed against BasicSwap's API, skipping: %s", e)


def run(cfg: LiveMakerConfig, loop: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = BasicSwapClient(
        config.api_url,
        auth_user=config.auth_user,
        auth_password=config.auth_password,
        timeout_seconds=config.request_timeout_seconds,
    )
    conn = storage.connect(config.db_path)
    sizing = f"amount={cfg.amount_from:.8f}" if cfg.amount_from is not None else f"reserve_usd=${cfg.reserve_usd:.2f}"
    log.info(
        "LIVE market-making: %s/%s %s, %s half_spread_pct=%.4f "
        "reprice_threshold_pct=%.4f offer_valid_hours=%.2f lock_hours=%.1f valid_hours=%.1f "
        "automation_strat_id=%s db=%s",
        cfg.coin_from, cfg.coin_to, cfg.side, sizing, cfg.half_spread_pct,
        cfg.reprice_threshold_pct, cfg.offer_valid_hours, cfg.lock_hours, cfg.valid_hours,
        cfg.automation_strat_id, config.db_path,
    )

    try:
        run_cycle(client, conn, cfg)
        while loop:
            time.sleep(config.poll_interval_seconds)
            run_cycle(client, conn, cfg)
    except AmbiguousLiveOffersError as e:
        log.error(
            "HALTING live_maker — real order-book state doesn't match what this loop's own "
            "logic should ever produce: %s",
            e,
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="REQUIRED to actually call post_offer/revoke_offer. Without it, this "
        "script does nothing (no dry-run fallback here — use strategy.quoter for that).",
    )
    parser.add_argument("--loop", action="store_true", help="poll forever instead of a single cycle")
    parser.add_argument("--coin-from", default="btc")
    parser.add_argument("--coin-to", default="xmr")
    parser.add_argument("--side", default="ask", choices=["ask", "bid"])
    parser.add_argument(
        "--amount-from", type=float, default=None,
        help="fixed amount of coin_from to offer. Exactly one of --amount-from/--reserve-usd is required.",
    )
    parser.add_argument(
        "--reserve-usd", type=float, default=None,
        help="offer everything above this USD value of coin_from, recomputed each cycle against "
        "a live price (e.g. --reserve-usd 210 keeps at least $210 worth back). Exactly one of "
        "--amount-from/--reserve-usd is required.",
    )
    parser.add_argument("--half-spread-pct", type=float, default=0.0066)
    parser.add_argument("--reprice-threshold-pct", type=float, default=0.005)
    parser.add_argument("--offer-valid-hours", type=float, default=0.7, help="our own reprice-cadence backstop")
    parser.add_argument("--lock-hours", type=float, default=24, help="the offer's HTLC lock window")
    parser.add_argument("--valid-hours", type=float, default=6, help="BasicSwap's own offer-expiry backstop")
    parser.add_argument("--automation-strat-id", type=int, default=1)
    args = parser.parse_args(argv)

    if not args.live:
        print(
            "Refusing to run: --live was not passed, and this module has no dry-run "
            "fallback. Use `python -m strategy.quoter` to simulate without --live."
        )
        return 1

    if (args.amount_from is None) == (args.reserve_usd is None):
        print("Exactly one of --amount-from or --reserve-usd must be given.")
        return 1

    cfg = LiveMakerConfig(
        coin_from=args.coin_from,
        coin_to=args.coin_to,
        side=args.side,
        amount_from=args.amount_from,
        reserve_usd=args.reserve_usd,
        half_spread_pct=args.half_spread_pct,
        reprice_threshold_pct=args.reprice_threshold_pct,
        offer_valid_hours=args.offer_valid_hours,
        lock_hours=args.lock_hours,
        valid_hours=args.valid_hours,
        automation_strat_id=args.automation_strat_id,
    )
    try:
        run(cfg, loop=args.loop)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

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
  - Volatility kill-switch (market_maker/next_steps.md #1, built 2026-09-18):
    run_cycle tracks a rolling window of reference-mid samples via
    volatility.VolatilityMonitor and skips posting/reposting for a cycle
    (existing live offer left up, unless _revoke_if_unprofitable pulls it —
    2026-10-22) if the window's (max-min)/mean move
    exceeds cfg.kill_switch_volatility_pct — see volatility.py for the
    real-data calibration behind the default. This is the one control decide_and_act's
    own drift-based repricing doesn't cover: reprice chases a moved price
    after the fact every cycle; the kill-switch instead pauses quoting into a
    market that's still actively moving. 2026-09-24: a second, longer window
    (cfg.kill_switch_long_window_minutes / _long_volatility_pct) and a
    cooldown (cfg.kill_switch_cooldown_minutes — once tripped, stay paused
    until that long passes with no new trip) were added after the 09-18 ask
    fill showed the 15-min window alone could flicker off for one cycle
    mid-spike and reprice into the top of the move — see volatility.py's
    2026-09-24 note for the reconstruction and calibration.
  - Source-disagreement gate (market_maker/next_steps.md #10, built 2026-09-18,
    real incident): the volatility kill-switch only sees trouble *after* a bad
    reference_mid is already in its rolling window. Built in response to the
    2026-09-18 12:24 ask repost at 136.17 XMR/BTC, originally read as a single
    bad CoinGecko reading — CORRECTED 2026-09-24 (basicswap/project_status.md):
    both sources agreed, it was a real ~7% move, so this gate wouldn't have
    stopped it (the kill-switch cooldown/long window above addresses that
    one). The gate still guards the failure it was designed for, a single bad
    source reading. external_rates.get_reference_rate() already computes an
    independent Kraken cross-check and a disagreement_pct between it and
    CoinGecko on every call, for every pair with Kraken coverage — this was
    simply never read before using reference_mid. run_cycle now skips
    posting/reposting for a cycle (existing offer left untouched, same
    posture as every other guard here) when disagreement_pct is available and
    exceeds cfg.max_source_disagreement_pct — an independent check on the
    input itself, not on its trailing volatility, so a single bad read gets
    caught on the very cycle it happens rather than only in the noise it
    leaves behind. When no Kraken pair is configured for a given coin pair
    (most of BasicSwap's supported coins aren't listed on Kraken —
    external_rates._KRAKEN_PAIRS only covers xmr/btc and ltc/btc today),
    disagreement_pct is None and this check is a no-op — there's no
    independent source to disagree with, so run_cycle proceeds on CoinGecko
    alone exactly as before, rather than refusing to quote pairs that simply
    have no cross-check available.
  - Dynamic per-cycle spread (market_maker/next_steps.md #15 Phase A, built
    2026-09-19): cfg.half_spread_pct is now read as an operator-set FLOOR, not
    the quoted value itself. Each cycle, run_cycle composes the same
    VolatilityMonitor reading the kill-switch already computes with
    economics.dynamic_half_spread_pct (fee + live-vol-scaled buffer + margin,
    against the cycle's live USD notional) and quotes at
    max(floor, computed) — so the spread widens automatically during real
    volatility spikes (a smoother, earlier reaction than the kill-switch's
    binary skip-the-cycle behavior) and narrows back toward the floor when the
    market's calm, but never goes thinner than the floor Evan set via
    --half-spread-pct (next_steps.md #14). Falls back to the floor untouched,
    unchanged, if this cycle's CoinGecko USD cross wasn't available (no extra
    external call is made just to recover it) — an enhancement failing never
    blocks quoting outright, same posture as every other guard in this module.
    The exposure window used to scale the volatility buffer is
    cfg.assumed_fill_hours, a separate static guess from cfg.lock_hours (the
    offer's technical HTLC ceiling) — see next_steps.md #15 Phase C for why
    it's still a guess, not a real measurement, and dynamic_half_spread_pct's
    own docstring for why the two "lock hours" concepts are unrelated despite
    the shared name.
  - 2026-09-25 incident fixes (market_maker/project_status.md's matching
    entry): (1) PRICING DIRECTION. This used quoter.half_spread_rate, whose
    'bid' branch quotes mid*(1-h) — correct in the shadow quoter, where both
    sides are expressed in the ask pair's units, but wrong here: the bid side
    flips the pair (coin_from=xmr, coin_to=btc), so its rate is BTC per XMR,
    and mid*(1-h) SOLD XMR 2-3% BELOW market (five takers in an hour on
    09-25; the 09-18 bid fill's -0.77% edge was the same bug). A BasicSwap
    offer always sells coin_from, so the only correct rate is
    _offer_rate()'s mid*(1+h), whatever cfg.side says; decide_and_act also
    refuses to post anything at or below mid. (2) IN-FLIGHT SWAPS. The wallet
    balance doesn't drop until our lock tx publishes, and each reprice posts
    a fresh offer (BasicSwap's max_concurrent_bids=1 is per offer), so the
    same surplus was sold twice, cutting into the --reserve-usd floor, and
    three more accepted swaps sat retrying a lock we couldn't fund.
    run_cycle now checks /json/bids first: while any non-terminal swap sells
    coin_from for coin_to, it posts nothing, revokes our live offer in that
    direction (so a second taker can't start a parallel swap), and waits.
  - Offer-size quantization (cfg.amount_step, built 2026-09-20, stolen from
    BasicSwap's own built-in "AMM" offer-posting bot, scripts/createoffers.py
    — see that script's own template docs: "amount_step: REQUIRED - Offer
    size increment for privacy"). Only relevant to --reserve-usd sizing:
    --amount-from is a fixed constant regardless of wallet balance, so it
    never leaks anything about the wallet. --reserve-usd, by contrast,
    computes "everything above the reserve" fresh each cycle in
    _resolve_amount_from — offered at the *exact* leftover value unless
    quantized, which hands anyone watching the offer book a precise reading
    of the wallet's balance (offer_amount + reserve_usd/price ~= wallet
    balance, to eight decimals). When cfg.amount_step is set,
    _resolve_amount_from rounds the dynamic amount DOWN to the nearest whole
    multiple of the step (matching createoffers.py's own
    `min_offer_amount * min_steps` logic exactly) before it ever reaches
    decide_and_act, so the posted amount only ever discloses "wallet balance
    is somewhere in this step-wide bracket," not the exact figure. Opt-in
    (default None — disabled, current live behavior unchanged) rather than
    on-by-default, matching this module's standing posture that a live-money
    behavior change needs Evan to actually pass the flag on the next
    restart, not just have it built.
  - Objective (2026-09-28, --objective btc; basicswap/project_status.md's
    matching entry). The default "usd" is every behavior above, unchanged.
    "btc" scores the desk in sats: idle BTC is the benchmark and XMR is working
    stock. The loop is BTC -> XMR (restock leg: an offer selling btc) -> BTC
    (sell leg: an offer selling XMR at a premium). The round trip's fees, vol
    buffer and margin are charged once, on the restock leg
    (economics.restock_half_spread_pct): only what the sell leg's expected
    premium doesn't already cover, floored at
    --restock-min-half-spread-pct (always > 0, never at or below mid). With
    --restock-target-coin-to it also buys only up to a total coin_to balance
    and withdraws its offer at target, since XMR held beyond that is only
    XMR/BTC risk. The sell leg quotes --half-spread-pct as its target premium
    and widens only when live vol exceeds the baseline assumption
    (economics.sell_leg_half_spread_pct); pricing each leg with the full
    single-leg cost model would count vol buffer and margin twice. Set
    --restock-expected-sell-premium-pct to the sell leg's --half-spread-pct.
    Opt-in; a restart without these flags changes nothing.
"""

import argparse
import dataclasses
import logging
import time
from dataclasses import dataclass

from . import coin_names, economics, external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .config import load_config
from .external_rates import ExternalRateError
from .volatility import VolatilityMonitor

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
    half_spread_pct: float  # read as a FLOOR, not the quoted value — see run_cycle's dynamic-spread note
    reprice_threshold_pct: float
    offer_valid_hours: float  # our own repricing cadence backstop
    lock_hours: float  # the offer's own HTLC lock window
    valid_hours: float  # the offer's own BasicSwap-enforced expiry (a backstop under ours)
    amount_from: float | None = None  # fixed offer size; mutually exclusive with reserve_usd
    reserve_usd: float | None = None  # "offer everything above this USD value" — see _dynamic_amount_from
    amount_step: float | None = None  # quantize --reserve-usd's dynamic amount down to this — see module docstring
    automation_strat_id: int | None = 1
    kill_switch_window_minutes: float = 15.0  # rolling window volatility.VolatilityMonitor evaluates
    kill_switch_volatility_pct: float = 0.0085  # see volatility.py's module docstring for calibration
    # 2026-09-24 (volatility.py's recalibration note): a longer window that one flat
    # reading can't clear, plus hysteresis. <= 0 disables either.
    kill_switch_long_window_minutes: float = 60.0
    kill_switch_long_volatility_pct: float = 0.03
    kill_switch_cooldown_minutes: float = 30.0
    max_source_disagreement_pct: float = 0.015  # see run_cycle's docstring note below for calibration
    # next_steps.md #15 Phase A: the exposure window the dynamic spread's volatility
    # buffer is sized off — a static guess (midpoint of the "2-3h realistic fill"
    # estimate next_steps.md #14's 0.02 derivation used), unrelated to lock_hours
    # above (the offer's technical HTLC ceiling). Stays a guess until #15 Phase C
    # measures real fill times.
    assumed_fill_hours: float = 2.5
    # Accumulate-BTC objective (2026-09-28, see the module docstring's
    # "Objective" note). "usd" keeps every pre-09-28 behavior unchanged.
    objective: str = "usd"
    reserve_coin: float | None = None  # like reserve_usd, but in coin_from units
    restock_target_to: float | None = None  # btc objective, restock leg: total coin_to wallet target
    restock_expected_sell_premium_pct: float = 0.0
    restock_min_half_spread_pct: float = 0.0025
    restock_min_amount_from: float = 0.001
    # 2026-09-30: cap on a dynamic (reserve-sized) offer, applied before amount_step.
    # Keeps the sell leg's offer size fixed while restock fills grow the balance.
    max_amount_from: float | None = None
    # 2026-10-21: smallest partial fill to accept (coin_from units). Each swap
    # pays ~650 sats of BTC network fees whatever its size, so a dust fill (the
    # 10-18 0.018 XMR sell) loses money at any premium. An offer smaller than
    # this is posted take-whole (min = its own size).
    min_bid_amount: float | None = None
    # 2026-10-01: restock leg pricing. "cost" = economics.restock_half_spread_pct
    # alone (always above mid). "book" = just inside the best competing BasicSwap
    # offer, never paying more than restock_max_premium_pct over mid for coin_to
    # (see _restock_book_half_spread_pct).
    restock_pricing: str = "cost"
    restock_max_premium_pct: float = 0.005
    restock_book_improve_pct: float = 0.0001
    # 2026-10-22: smallest premium over the current mid a live non-restock offer may
    # keep before it's revoked (_revoke_if_unprofitable). Checked every cycle,
    # including kill-switch/cooldown cycles that otherwise leave the offer alone.
    # The restock leg's floor is -restock_max_premium_pct instead.
    min_live_edge_pct: float = 0.0
    # 2026-10-22: between full cycles, re-check the live offer against Kraken's mid
    # this often (guard_check, revoke-only). <= 0 disables it.
    guard_interval_seconds: float = 30.0

    def __post_init__(self):
        sizings = [self.amount_from, self.reserve_usd, self.reserve_coin]
        if sum(s is not None for s in sizings) != 1:
            raise ValueError("exactly one of amount_from, reserve_usd or reserve_coin must be set")
        if self.objective not in ("usd", "btc"):
            raise ValueError(f"objective must be 'usd' or 'btc', got {self.objective!r}")
        if self.objective == "btc" and "btc" not in (self.coin_from, self.coin_to):
            raise ValueError("objective='btc' needs btc on one side of the pair")
        if self.restock_target_to is not None:
            if not self.is_restock_leg:
                raise ValueError("restock_target_to only applies to objective='btc' offers that sell btc")
            if self.amount_from is None:
                raise ValueError("restock_target_to needs amount_from as the per-offer size cap")
        if self.is_restock_leg and not self.restock_min_half_spread_pct > 0:
            raise ValueError("restock_min_half_spread_pct must be > 0 (offers never go at or below mid)")
        if self.restock_pricing not in ("cost", "book"):
            raise ValueError(f"restock_pricing must be 'cost' or 'book', got {self.restock_pricing!r}")
        if self.restock_pricing == "book":
            if not self.is_restock_leg:
                raise ValueError("restock_pricing='book' only applies to the objective='btc' restock leg")
            # Paying p over mid to restock and selling at the sell leg's premium s
            # nets s - p before fees; p >= s can't be a profitable round trip.
            if not 0 <= self.restock_max_premium_pct < self.restock_expected_sell_premium_pct:
                raise ValueError(
                    "restock_max_premium_pct must be >= 0 and below restock_expected_sell_premium_pct "
                    f"(got {self.restock_max_premium_pct} vs {self.restock_expected_sell_premium_pct})"
                )

    @property
    def is_restock_leg(self) -> bool:
        """BTC objective, selling BTC to buy the other coin: this leg only
        restocks inventory the sell leg earns sats on."""
        return self.objective == "btc" and self.coin_from == "btc"


# Mirrors bid_scanner._TERMINAL_*: any other bid_state is a swap still in
# progress (or a bid still pending acceptance), which can still move funds.
_TERMINAL_BID_STATES = {
    "Completed", "Timed-out", "Abandoned", "Error", "Rejected", "Expired",
    "Auto accept failed", "Failed", "Failed, refunded", "Failed, swiped",
    "Failed, swiped, sending mercy", "Failed, swiped, recovering",
    "Failed, swiped, recovered", "Failed, swiped, mercy unused",
}


def _offer_rate(reference_mid: float, half_spread_pct: float) -> float:
    """Rate (coin_to per coin_from) for an offer that sells coin_from. Always
    above mid: the offer's direction is already encoded in coin_from/coin_to,
    so cfg.side must not flip the sign (see the 2026-09-25 note above)."""
    return reference_mid * (1 + half_spread_pct)


def _in_flight_swaps(client: BasicSwapClient, coin_from: str, coin_to: str) -> list[dict]:
    """Non-terminal swaps that spend coin_from for coin_to: bids on our own
    offers in this direction, plus bids we SENT into someone else's offer that
    spend the same coin (topup_xmr/bid_scanner). A sent bid carries the offer's
    direction, so it matches reversed. The docstring always claimed sent bids
    were covered, but /json/bids never returns them (found 2026-09-28), so a
    top-up in flight could run in parallel with a restock offer until
    get_sent_bids() was added here."""
    cf, ct = coin_names.to_display_name(coin_from), coin_names.to_display_name(coin_to)
    live = lambda b: b.get("bid_state") not in _TERMINAL_BID_STATES  # noqa: E731
    received = [b for b in client.get_bids() if b.get("coin_from") == cf and b.get("coin_to") == ct and live(b)]
    sent = [b for b in client.get_sent_bids() if b.get("coin_from") == ct and b.get("coin_to") == cf and live(b)]
    return received + sent


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
    beat_rate: float | None = None,
) -> str | None:
    """beat_rate: book-priced restock only, the best competing offer's rate."""
    now = now if now is not None else time.time()
    coin_from, coin_to = coin_names.to_display_name(cfg.coin_from), coin_names.to_display_name(cfg.coin_to)
    target_rate = _offer_rate(reference_mid, cfg.half_spread_pct)
    if cfg.restock_pricing == "book":
        # Book-priced restock may pay up to restock_max_premium_pct over mid, never more.
        floor_rate = _offer_rate(reference_mid, -cfg.restock_max_premium_pct)
        if target_rate < floor_rate * (1 - 1e-9):
            raise ValueError(
                f"refusing to quote {coin_from}->{coin_to} at {target_rate}: below the "
                f"restock_max_premium_pct floor {floor_rate} (mid {reference_mid})"
            )
    elif not target_rate > reference_mid:
        raise ValueError(
            f"refusing to quote {coin_from}->{coin_to} at {target_rate} <= reference mid "
            f"{reference_mid}: an offer always sells coin_from, so this would sell below market"
        )
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

    min_bid_str = (
        None if cfg.min_bid_amount is None else f"{min(cfg.min_bid_amount, cfg.amount_from):.8f}"
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
            min_bid_amount=min_bid_str,
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

    # Restock leg only: a live offer bigger than this cycle's target-limited size
    # would overshoot cfg.restock_target_to, so shrink it. Every other path keeps
    # its pre-09-28 behavior (a size change alone never reposts).
    live_amount = real_live_offer.get("amount_from")
    oversized = (
        cfg.is_restock_leg
        and live_amount is not None
        and float(live_amount) > cfg.amount_from * (1 + cfg.reprice_threshold_pct)
    )

    # Book-priced restock: a competitor now matches or beats our live offer
    # (lower rate = fewer coin_to asked per BTC = better for the taker) and this
    # cycle's target would win the top back. Too small a move for the drift
    # threshold, but it decides who gets taken.
    outbid = beat_rate is not None and live_rate >= beat_rate and target_rate < beat_rate

    if drift_pct > cfg.reprice_threshold_pct or outbid:
        action = "reprice"
    elif oversized:
        action = "resize"
    elif age_seconds > cfg.offer_valid_hours * 3600:
        action = "expire_repost"
    else:
        return None

    _check_funded()
    client.revoke_offer(live_offer_id, refuse_if_negotiating=True)
    new_offer_id = _post_new_quote()
    # live_quote_events' CHECK constraint predates "resize", and the production
    # table can't be altered in place, so a resize is stored as a reprice row.
    storage.insert_live_quote_event(
        conn, coin_from, coin_to, cfg.side, "reprice" if action == "resize" else action,
        new_offer_id, cfg.amount_from,
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

    usd_price = None
    if cfg.reserve_usd is not None:
        try:
            usd_price = external_rates.get_usd_price(cfg.coin_from)
        except ExternalRateError as e:
            log.warning("get_usd_price(%s) failed, skipping this cycle: %s", cfg.coin_from, e)
            return None
    try:
        available = client.get_wallet_balance(cfg.coin_from)
    except BasicSwapAPIError as e:
        # Real incident 2026-09-18: an uncaught TimeoutError here (before
        # api_client.py wrapped it as BasicSwapAPIError, see that module's
        # matching fix) crashed the whole bid-side loop rather than just
        # skipping a cycle like every other transient failure in this
        # function already does.
        log.warning("get_wallet_balance(%s) failed, skipping this cycle: %s", cfg.coin_from, e)
        return None
    # reserve_coin (2026-09-28, accumulate-BTC objective) holds back a fixed coin
    # amount instead, so the reserve doesn't drift with the coin's USD price.
    reserve_coin = cfg.reserve_coin if cfg.reserve_coin is not None else cfg.reserve_usd / usd_price
    dynamic_amount = available - reserve_coin
    if cfg.max_amount_from is not None and dynamic_amount > cfg.max_amount_from:
        dynamic_amount = cfg.max_amount_from
    if dynamic_amount <= 0:
        reserve_desc = (
            f"~${cfg.reserve_usd:.2f} at ${usd_price:.2f}/coin" if usd_price is not None else "fixed coin reserve"
        )
        log.info(
            "%s: balance %.8f, reserve %.8f (%s) — nothing free to offer "
            "this cycle, any existing live offer is left untouched.",
            cfg.coin_from, available, reserve_coin, reserve_desc,
        )
        return None

    if cfg.amount_step is not None and cfg.amount_step > 0:
        steps = int(dynamic_amount / cfg.amount_step + 1e-9)  # 0.6/0.05 is 11.999... in floats
        quantized_amount = cfg.amount_step * steps
        if quantized_amount <= 0:
            log.info(
                "%s: %.8f available above reserve, but below one amount_step (%.8f) — nothing "
                "to offer this cycle, any existing live offer is left untouched.",
                cfg.coin_from, dynamic_amount, cfg.amount_step,
            )
            return None
        return quantized_amount

    return dynamic_amount


def _dynamic_half_spread_pct(
    cfg: LiveMakerConfig, amount_from: float, usd_price_from: float | None, vol_pct: float | None
) -> float:
    """next_steps.md #15 Phase A: this cycle's half_spread_pct, composing the live
    volatility reading with economics.py's cost model — see the module docstring's
    "Dynamic per-cycle spread" note for the full picture. Falls back to
    cfg.half_spread_pct (the floor) untouched if usd_price_from isn't available this
    cycle (CoinGecko's USD cross failed) — deliberately makes no extra external call
    here to recover it, only composes what this cycle already fetched."""
    if usd_price_from is None:
        return cfg.half_spread_pct
    notional_usd = amount_from * usd_price_from
    return economics.dynamic_half_spread_pct(
        operator_floor_pct=cfg.half_spread_pct,
        notional_usd=notional_usd,
        lock_hours=cfg.assumed_fill_hours,
        live_vol_pct=vol_pct,
        live_vol_window_seconds=cfg.kill_switch_window_minutes * 60,
    )


SATS_PER_BTC = 100_000_000


def _notional_sats(cfg: LiveMakerConfig, amount_from: float, reference_mid: float) -> float:
    """reference_mid is coin_to per coin_from, so a non-BTC coin_from converts via it."""
    if cfg.coin_from == "btc":
        return amount_from * SATS_PER_BTC
    return amount_from * reference_mid * SATS_PER_BTC


def _stand_down_restock(client: BasicSwapClient, cfg: LiveMakerConfig, held_to: float) -> None:
    """Restock target reached: holding more of coin_to is pure XMR/BTC risk under
    the BTC objective, so withdraw the live restock offer rather than leave it."""
    try:
        live = _find_own_live_offer(client, cfg.coin_from, cfg.coin_to)
        if live is not None:
            client.revoke_offer(live["offer_id"], refuse_if_negotiating=True)
            log.info("%s/%s %s: revoked restock offer %s", cfg.coin_from, cfg.coin_to, cfg.side, live["offer_id"])
    except (BasicSwapAPIError, AmbiguousLiveOffersError) as e:
        log.warning("%s/%s %s: couldn't revoke restock offer at target: %s", cfg.coin_from, cfg.coin_to, cfg.side, e)
    log.info(
        "%s/%s %s: holding %.8f %s against a restock target of %.8f — not buying more this cycle.",
        cfg.coin_from, cfg.coin_to, cfg.side, held_to, cfg.coin_to.upper(), cfg.restock_target_to,
    )


def _best_competing_rate(client: BasicSwapClient, cfg: LiveMakerConfig) -> float | None:
    """Lowest rate (best for the taker) among other makers' live offers in our
    direction that a taker of our size could also use (min_bid_amount <= our
    per-offer cap). None if there are none."""
    best = None
    for o in client.get_offers(coin_from=cfg.coin_from, coin_to=cfg.coin_to):
        if o.get("is_own_offer") or o.get("is_expired") or o.get("is_revoked"):
            continue
        try:
            rate = float(o["rate"])
            min_bid = float(o.get("min_bid_amount") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if rate <= 0 or min_bid > cfg.amount_from:
            continue
        best = rate if best is None else min(best, rate)
    return best


def _restock_book_half_spread_pct(
    cost_h: float, best_rate: float | None, reference_mid: float, cfg: LiveMakerConfig
) -> float:
    """2026-10-01, restock_pricing='book'. A seller of coin_to takes whichever
    offer asks the fewest coin_to per BTC, so quote just inside the best
    competitor (restock_book_improve_pct) -- even above our cost-model price
    when the book is weak -- but never pay more than restock_max_premium_pct over
    mid (that cap, below the sell leg's premium, is what keeps every round trip
    profitable before fees). No competitor: the cost-model price."""
    if best_rate is None:
        return cost_h
    book_h = best_rate / reference_mid - 1 - cfg.restock_book_improve_pct
    return max(book_h, -cfg.restock_max_premium_pct)


def _btc_objective_plan(
    client: BasicSwapClient,
    cfg: LiveMakerConfig,
    amount_from: float,
    reference_mid: float,
    vol_pct: float | None,
) -> tuple[float, float, float | None] | None:
    """(amount_from, half_spread_pct, beat_rate) for this cycle under objective='btc', or None
    to post nothing. Sell leg: cfg.half_spread_pct as its target premium, widened
    only by excess live vol (economics.sell_leg_half_spread_pct). Restock leg: priced by
    economics.restock_half_spread_pct (floored at cfg.restock_min_half_spread_pct,
    NOT cfg.half_spread_pct), and sized so the wallet's coin_to balance only
    tops up to cfg.restock_target_to when that's set."""
    window_seconds = cfg.kill_switch_window_minutes * 60
    if not cfg.is_restock_leg:
        return amount_from, economics.sell_leg_half_spread_pct(
            target_premium_pct=cfg.half_spread_pct,
            hold_hours=cfg.assumed_fill_hours,
            live_vol_pct=vol_pct,
            live_vol_window_seconds=window_seconds,
        ), None

    def cost_h(amount: float) -> float:
        return economics.restock_half_spread_pct(
            min_half_spread_pct=cfg.restock_min_half_spread_pct,
            notional_sats=amount * SATS_PER_BTC,
            hold_hours=cfg.assumed_fill_hours,
            expected_sell_premium_pct=cfg.restock_expected_sell_premium_pct,
            live_vol_pct=vol_pct,
            live_vol_window_seconds=window_seconds,
        )

    best_rate = None
    if cfg.restock_pricing == "book":
        try:
            best_rate = _best_competing_rate(client, cfg)
        except BasicSwapAPIError as e:
            log.warning("get_offers failed, restock falls back to cost pricing this cycle: %s", e)
        log.info(
            "%s/%s %s: book pricing, best competitor %s (mid %.8f, cap -%.4f)",
            cfg.coin_from, cfg.coin_to, cfg.side,
            "none" if best_rate is None else f"{best_rate:.8f} ({best_rate / reference_mid - 1:+.4%})",
            reference_mid, cfg.restock_max_premium_pct,
        )

    def restock_h(amount: float) -> float:
        h = cost_h(amount)
        if cfg.restock_pricing == "book":
            h = _restock_book_half_spread_pct(h, best_rate, reference_mid, cfg)
        return h

    if cfg.restock_target_to is None:
        return amount_from, restock_h(amount_from), best_rate

    try:
        held_to = client.get_wallet_balance(cfg.coin_to)
    except BasicSwapAPIError as e:
        log.warning("get_wallet_balance(%s) failed, skipping this cycle: %s", cfg.coin_to, e)
        return None
    deficit_to = cfg.restock_target_to - held_to
    amount, h = amount_from, restock_h(amount_from)
    if deficit_to > 0:
        # The spread depends on size (fee share) and size on the spread (coin_to
        # received per BTC); two passes settle it well inside a satoshi.
        for _ in range(2):
            amount = min(amount_from, deficit_to / (reference_mid * (1 + h)))
            h = restock_h(amount)
    if deficit_to <= 0 or amount < cfg.restock_min_amount_from:
        _stand_down_restock(client, cfg, held_to)
        return None
    return amount, h, best_rate


def _revoke_if_unprofitable(client: BasicSwapClient, cfg: LiveMakerConfig, reference_mid: float) -> bool:
    """2026-10-22 (Evan: "cancel any offer once we determine it isn't profitable").
    The 10-22 02:14 sell fill went 2.75% below mid: XMR jumped ~5%, the kill-switch
    paused repricing from 01:49 and left the old ask up for six cycles until it was
    taken. Runs before every pause, so a pause never leaves an underwater offer live.
    True if an offer was revoked. Restock floor: the max-premium cap plus the
    cycle's own reprice tolerance. The cap alone is where book pricing usually
    quotes, so any adverse tick revoked it (14:13 redeploy); buying at cap+0.5%
    still clears the round trip against the sell premium."""
    if cfg.is_restock_leg:
        floor = -(cfg.restock_max_premium_pct + cfg.reprice_threshold_pct)
    else:
        floor = cfg.min_live_edge_pct
    try:
        live = _find_own_live_offer(client, cfg.coin_from, cfg.coin_to)
        if live is None:
            return False
        premium = float(live["rate"]) / reference_mid - 1
        if float(live["rate"]) >= reference_mid * (1 + floor) * (1 - 1e-9):
            return False
        client.revoke_offer(live["offer_id"], refuse_if_negotiating=True)
    except (BasicSwapAPIError, AmbiguousLiveOffersError) as e:
        log.warning("%s/%s %s: couldn't check/revoke an unprofitable live offer: %s",
                    cfg.coin_from, cfg.coin_to, cfg.side, e)
        return False
    log.warning(
        "%s/%s %s: revoked live offer %s @ %s: %+.3f%% vs. mid %.8f is below the %+.3f%% floor",
        cfg.coin_from, cfg.coin_to, cfg.side, live["offer_id"], live["rate"],
        premium * 100, reference_mid, floor * 100,
    )
    return True


def guard_anchor(
    cfg: LiveMakerConfig, monitor: VolatilityMonitor, cycle_started: float
) -> tuple[float, float] | None:
    """(the mid the full cycle just priced off, Kraken's mid right now), or None if
    that cycle never got a trusted mid (it skips before adding a sample)."""
    latest = monitor.latest()
    if latest is None or latest[0] < cycle_started:
        return None
    try:
        return latest[1], external_rates.get_kraken_mid(cfg.coin_from, cfg.coin_to)
    except ExternalRateError as e:
        log.warning("%s/%s %s: no guard anchor this cycle: %s", cfg.coin_from, cfg.coin_to, cfg.side, e)
        return None


def guard_check(
    client: BasicSwapClient, cfg: LiveMakerConfig, anchor: tuple[float, float] | None = None
) -> bool:
    """2026-10-22: the fast check between full cycles, revoke-only: never posts,
    never feeds the VolatilityMonitor (its thresholds were calibrated on 5-min
    samples). With an anchor it applies Kraken's move since the full cycle to the
    mid that cycle priced off, so a steady CoinGecko/Kraken gap can't make it
    fight the cycle (first deploy, 14:10: it revoked a restock offer quoted at
    exactly its cap within 30s). Without one, Kraken's mid as-is. Any failure
    just skips this check."""
    try:
        kraken_mid = external_rates.get_kraken_mid(cfg.coin_from, cfg.coin_to)
    except ExternalRateError as e:
        log.warning("%s/%s %s: guard check skipped: %s", cfg.coin_from, cfg.coin_to, cfg.side, e)
        return False
    mid = kraken_mid if anchor is None else anchor[0] * kraken_mid / anchor[1]
    return _revoke_if_unprofitable(client, cfg, mid)


def _pause_for_in_flight_swaps(client: BasicSwapClient, cfg: LiveMakerConfig, in_flight: list[dict]) -> None:
    ids = ", ".join(f"{b.get('bid_id', '?')[:16]} ({b.get('bid_state')})" for b in in_flight)
    try:
        live = _find_own_live_offer(client, cfg.coin_from, cfg.coin_to)
        if live is not None:
            client.revoke_offer(live["offer_id"], refuse_if_negotiating=True)
            log.warning(
                "%s/%s %s: revoked live offer %s so no second taker can start a parallel swap",
                cfg.coin_from, cfg.coin_to, cfg.side, live["offer_id"],
            )
    except (BasicSwapAPIError, AmbiguousLiveOffersError) as e:
        log.warning("%s/%s %s: couldn't revoke live offer while a swap is in flight: %s",
                    cfg.coin_from, cfg.coin_to, cfg.side, e)
    log.warning(
        "%s/%s %s: %d swap(s) in flight [%s] — not posting until they finish; the wallet "
        "balance doesn't reflect them yet.",
        cfg.coin_from, cfg.coin_to, cfg.side, len(in_flight), ids,
    )


def run_cycle(
    client: BasicSwapClient, conn, cfg: LiveMakerConfig, volatility_monitor: VolatilityMonitor
) -> None:
    try:
        rate = external_rates.get_reference_rate(cfg.coin_from, cfg.coin_to)
    except ExternalRateError as e:
        log.warning("get_reference_rate(%s, %s) failed, skipping this cycle: %s", cfg.coin_from, cfg.coin_to, e)
        return
    reference_mid = rate.coingecko_rate if rate.coingecko_rate is not None else rate.kraken_rate
    if reference_mid is None:
        log.warning("no usable reference rate for %s/%s this cycle, skipping", cfg.coin_from, cfg.coin_to)
        return

    if rate.disagreement_pct is not None and rate.disagreement_pct > cfg.max_source_disagreement_pct:
        log.warning(
            "%s/%s %s: CoinGecko/Kraken disagree by %.3f%% (coingecko=%s kraken=%s), exceeds "
            "%.3f%% threshold — skipping post/reprice this cycle, any existing live offer is "
            "left untouched. Not feeding this reading into the volatility window either, since "
            "it's already flagged unreliable.",
            cfg.coin_from, cfg.coin_to, cfg.side, rate.disagreement_pct * 100,
            rate.coingecko_rate, rate.kraken_rate, cfg.max_source_disagreement_pct * 100,
        )
        return

    _revoke_if_unprofitable(client, cfg, reference_mid)

    now = time.time()
    volatility_monitor.add(now, reference_mid)
    vol_pct = volatility_monitor.volatility_pct(cfg.kill_switch_window_minutes * 60)
    trips = []
    if vol_pct is not None and vol_pct > cfg.kill_switch_volatility_pct:
        trips.append(
            f"{vol_pct * 100:.3f}% move over the last {cfg.kill_switch_window_minutes:.0f}m "
            f"exceeds {cfg.kill_switch_volatility_pct * 100:.3f}%"
        )
    if cfg.kill_switch_long_window_minutes > 0 and cfg.kill_switch_long_volatility_pct > 0:
        long_vol_pct = volatility_monitor.volatility_pct(cfg.kill_switch_long_window_minutes * 60)
        if long_vol_pct is not None and long_vol_pct > cfg.kill_switch_long_volatility_pct:
            trips.append(
                f"{long_vol_pct * 100:.3f}% move over the last "
                f"{cfg.kill_switch_long_window_minutes:.0f}m exceeds "
                f"{cfg.kill_switch_long_volatility_pct * 100:.3f}%"
            )
    if trips:
        volatility_monitor.last_trip_at = now
        log.warning(
            "%s/%s %s: volatility kill-switch active (%s) — skipping post/reprice this cycle; "
            "a live offer is left up only while it clears its profitability floor.",
            cfg.coin_from, cfg.coin_to, cfg.side, "; ".join(trips),
        )
        return
    cooldown_seconds = cfg.kill_switch_cooldown_minutes * 60
    if volatility_monitor.cooling_down(now, cooldown_seconds):
        log.warning(
            "%s/%s %s: volatility kill-switch cooling down (last tripped %.0fs ago, %.0fm "
            "cooldown) — skipping post/reprice this cycle; a live offer is left up only while "
            "it clears its profitability floor.",
            cfg.coin_from, cfg.coin_to, cfg.side, now - volatility_monitor.last_trip_at,
            cfg.kill_switch_cooldown_minutes,
        )
        return

    try:
        in_flight = _in_flight_swaps(client, cfg.coin_from, cfg.coin_to)
    except BasicSwapAPIError as e:
        log.warning("get_bids failed, skipping this cycle (can't rule out an in-flight swap): %s", e)
        return
    if in_flight:
        _pause_for_in_flight_swaps(client, cfg, in_flight)
        return

    amount_from = _resolve_amount_from(client, cfg)
    if amount_from is None:
        return

    if cfg.objective == "btc":
        plan = _btc_objective_plan(client, cfg, amount_from, reference_mid, vol_pct)
        if plan is None:
            return
        amount_from, half_spread_pct, beat_rate = plan
        log.info(
            "%s/%s %s: objective=btc %s half_spread_pct=%.4f amount=%.8f (%.0f sats notional)",
            cfg.coin_from, cfg.coin_to, cfg.side, "restock" if cfg.is_restock_leg else "sell",
            half_spread_pct, amount_from, _notional_sats(cfg, amount_from, reference_mid),
        )
    else:
        beat_rate = None
        half_spread_pct = _dynamic_half_spread_pct(cfg, amount_from, rate.usd_price_from, vol_pct)
    if cfg.objective == "usd" and half_spread_pct != cfg.half_spread_pct:
        log.info(
            "%s/%s %s: dynamic half_spread_pct=%.4f (floor=%.4f, notional=$%.2f, "
            "vol_pct=%s over %.0fm)",
            coin_names.to_display_name(cfg.coin_from), coin_names.to_display_name(cfg.coin_to),
            cfg.side, half_spread_pct, cfg.half_spread_pct, amount_from * rate.usd_price_from,
            f"{vol_pct * 100:.3f}%" if vol_pct is not None else "n/a",
            cfg.kill_switch_window_minutes,
        )
    cfg_for_cycle = dataclasses.replace(
        cfg, amount_from=amount_from, reserve_usd=None, reserve_coin=None, half_spread_pct=half_spread_pct
    )

    try:
        decide_and_act(client, conn, cfg_for_cycle, reference_mid, now=now, beat_rate=beat_rate)
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
    volatility_monitor = VolatilityMonitor(
        window_seconds=max(cfg.kill_switch_window_minutes, cfg.kill_switch_long_window_minutes) * 60
    )
    if cfg.amount_from is not None:
        sizing = f"amount={cfg.amount_from:.8f}"
    elif cfg.reserve_coin is not None:
        sizing = f"reserve_coin={cfg.reserve_coin:.8f}"
        if cfg.amount_step is not None:
            sizing += f" amount_step={cfg.amount_step:.8f}"
    else:
        sizing = f"reserve_usd=${cfg.reserve_usd:.2f}"
        if cfg.amount_step is not None:
            sizing += f" amount_step={cfg.amount_step:.8f}"
    if cfg.max_amount_from is not None and cfg.amount_from is None:
        sizing += f" max_amount_from={cfg.max_amount_from:.8f}"
    if cfg.min_bid_amount is not None:
        sizing += f" min_bid_amount={cfg.min_bid_amount:.8f}"
    log.info(
        "LIVE market-making: %s/%s %s, %s half_spread_floor_pct=%.4f "
        "assumed_fill_hours=%.2f reprice_threshold_pct=%.4f offer_valid_hours=%.2f "
        "lock_hours=%.1f valid_hours=%.1f "
        "automation_strat_id=%s kill_switch_window_minutes=%.1f kill_switch_volatility_pct=%.4f "
        "kill_switch_long_window_minutes=%.1f kill_switch_long_volatility_pct=%.4f "
        "kill_switch_cooldown_minutes=%.1f max_source_disagreement_pct=%.4f db=%s",
        cfg.coin_from, cfg.coin_to, cfg.side, sizing, cfg.half_spread_pct,
        cfg.assumed_fill_hours, cfg.reprice_threshold_pct, cfg.offer_valid_hours,
        cfg.lock_hours, cfg.valid_hours,
        cfg.automation_strat_id, cfg.kill_switch_window_minutes, cfg.kill_switch_volatility_pct,
        cfg.kill_switch_long_window_minutes, cfg.kill_switch_long_volatility_pct,
        cfg.kill_switch_cooldown_minutes, cfg.max_source_disagreement_pct, config.db_path,
    )
    if cfg.objective == "btc":
        log.info(
            "objective=btc (%s leg)%s", "restock" if cfg.is_restock_leg else "sell",
            (
                f": restock_target_to={cfg.restock_target_to} "
                f"restock_expected_sell_premium_pct={cfg.restock_expected_sell_premium_pct:.4f} "
                f"restock_min_half_spread_pct={cfg.restock_min_half_spread_pct:.4f} "
                f"restock_min_amount_from={cfg.restock_min_amount_from:.8f} "
                "(half_spread_floor_pct does not apply to this leg)"
            ) if cfg.is_restock_leg else "",
        )

    try:
        cycle_started = time.time()
        run_cycle(client, conn, cfg, volatility_monitor)
        while loop:
            next_cycle = cycle_started + config.poll_interval_seconds
            anchor = None
            if cfg.guard_interval_seconds > 0:
                anchor = guard_anchor(cfg, volatility_monitor, cycle_started)
            while cfg.guard_interval_seconds > 0 and time.time() + cfg.guard_interval_seconds < next_cycle:
                time.sleep(cfg.guard_interval_seconds)
                guard_check(client, cfg, anchor)
            time.sleep(max(0.0, next_cycle - time.time()))
            cycle_started = time.time()
            run_cycle(client, conn, cfg, volatility_monitor)
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
    parser.add_argument(
        "--reserve-coin", type=float, default=None,
        help="like --reserve-usd, but a fixed amount of coin_from (e.g. XMR) kept back, so the "
        "reserve doesn't move with the coin's USD price. Exactly one of --amount-from/"
        "--reserve-usd/--reserve-coin is required.",
    )
    parser.add_argument(
        "--max-amount-from", type=float, default=None,
        help="with --reserve-usd/--reserve-coin: cap the dynamic offer size at this many "
        "coin_from units (applied before --amount-step). Default None (no cap).",
    )
    parser.add_argument(
        "--objective", default="usd", choices=["usd", "btc"],
        help="usd (default, unchanged behavior) or btc: cost the spread in sats, and price an "
        "offer that sells BTC as a restock leg (see the module docstring's Objective note).",
    )
    parser.add_argument(
        "--restock-target-coin-to", type=float, default=None,
        help="--objective btc restock leg only: total coin_to wallet balance to top up to "
        "(include any bid-side reserve). --amount-from becomes the per-offer cap, and the "
        "offer is withdrawn once the wallet is at target.",
    )
    parser.add_argument(
        "--restock-expected-sell-premium-pct", type=float, default=0.0,
        help="--objective btc restock leg: premium the sell leg is expected to earn, credited "
        "against the round-trip cost. 0 (default) makes the restock leg cover it all alone.",
    )
    parser.add_argument(
        "--restock-min-half-spread-pct", type=float, default=0.0025,
        help="--objective btc restock leg: floor for its markup (must be > 0). Replaces "
        "--half-spread-pct for this leg only.",
    )
    parser.add_argument(
        "--restock-min-amount-from", type=float, default=0.001,
        help="--objective btc restock leg: don't post a target-limited offer smaller than this.",
    )
    parser.add_argument(
        "--restock-pricing", choices=("cost", "book"), default="cost",
        help="--objective btc restock leg: 'cost' (default) prices off the cost model, always "
        "above mid; 'book' quotes just inside the best competing BasicSwap offer, capped by "
        "--restock-max-premium-pct.",
    )
    parser.add_argument(
        "--restock-max-premium-pct", type=float, default=0.005,
        help="--restock-pricing book: the most to pay over mid for coin_to. Must stay below "
        "--restock-expected-sell-premium-pct so a round trip nets positive before fees.",
    )
    parser.add_argument(
        "--min-bid-amount", type=float, default=None,
        help="smallest partial fill to accept, in coin_from units (BasicSwap's amt_bid_min). "
        "An offer smaller than this is posted take-whole. Default None: BasicSwap's own minimum.",
    )
    parser.add_argument(
        "--min-live-edge-pct", type=float, default=0.0,
        help="revoke a live (non-restock) offer whose premium over the current mid falls below "
        "this, checked every cycle including kill-switch pauses. Default 0: never sit below mid.",
    )
    parser.add_argument(
        "--guard-interval-seconds", type=float, default=30.0,
        help="between full cycles, re-check the live offer against Kraken's mid this often and "
        "revoke it if it's below its floor (never posts). <= 0 disables.",
    )
    parser.add_argument(
        "--amount-step", type=float, default=None,
        help="only used with --reserve-usd: quantize the dynamic offer amount DOWN to the "
        "nearest whole multiple of this (coin_from units) before posting, so the posted "
        "amount doesn't disclose the wallet's exact leftover balance to anyone watching the "
        "offer book — see live_maker.py's module docstring. Default None (disabled, current "
        "behavior unchanged): pass this explicitly to turn it on.",
    )
    parser.add_argument(
        "--half-spread-pct", type=float, default=0.02,
        # Raised 0.011 -> 0.02 on 2026-09-19 (Evan's explicit "fix the BS
        # rate" call), after finding the 0.011 justification above was
        # itself miscalibrated: it compared our *round-trip-equivalent*
        # (2x half_spread = 2.2%) against this market's *two-sided* median
        # spread (~2.05-2.09%) as if that were the profitability bar. It
        # isn't -- `economics.py`'s already-built, already-researched cost
        # model is the actual bar for a SINGLE-sided fill (which is what
        # live_maker.py actually exposes itself to, one side at a time):
        # fee_pct + vol_buffer_pct(actual lock/fill hours) + margin_pct,
        # compared *directly* against half_spread_pct, no /2. Run at our
        # real ~$880 notional with today's fee assumptions
        # (required_spread_pct in economics.py), even a fast 30-min fill
        # needs ~1.35% one-sided to cover fee+risk+margin -- already above
        # the old 0.011 -- and a more realistic 2-3h fill (plausible given
        # Monero's own confirmation requirements) needs ~2.0-2.3%. This
        # independently converges with `next_steps.md` #14's cross-venue
        # read (Eigen ASB's competitive tier: median 2.67% one-sided
        # markup; Bisq: median 4.64%) and with this project's actual P&L
        # so far (all 3 real fills have been losses). 0.02 sits just above
        # the "realistic fill time" cost-model bar, below Eigen ASB's
        # professional-tier benchmark, and meaningfully wider than the old
        # value -- a deliberate correction, not a guess. Real fill time
        # (BasicSwap's own `next_steps.md` §4(a)/§5) is still unmeasured,
        # so this remains a revisit-when-real-fill-data-exists number, not
        # a final one -- see `next_steps.md` #14's follow-on plan for
        # moving toward a data-driven, continuously-recalibrated value.
        # 2026-09-19, next_steps.md #15 Phase A: this is now read as a FLOOR, not
        # the quoted value itself -- run_cycle computes a per-cycle spread off the
        # live volatility reading + economics.py's cost model and quotes at
        # max(this floor, that computed value), so the real quoted spread can be
        # wider than this number but never thinner.
    )
    parser.add_argument(
        "--assumed-fill-hours", type=float, default=2.5,
        help="next_steps.md #15 Phase A: static guess for the exposure window the "
        "dynamic spread's volatility buffer is sized off (midpoint of the '2-3h "
        "realistic fill' estimate --half-spread-pct's own 0.02 derivation used) -- "
        "NOT the same thing as --lock-hours (the offer's technical HTLC ceiling). "
        "Stays a guess until Phase C measures real fill times.",
    )
    parser.add_argument("--reprice-threshold-pct", type=float, default=0.005)
    parser.add_argument("--offer-valid-hours", type=float, default=0.7, help="our own reprice-cadence backstop")
    parser.add_argument("--lock-hours", type=float, default=24, help="the offer's HTLC lock window")
    parser.add_argument("--valid-hours", type=float, default=6, help="BasicSwap's own offer-expiry backstop")
    parser.add_argument("--automation-strat-id", type=int, default=1)
    parser.add_argument(
        "--kill-switch-window-minutes", type=float, default=15.0,
        help="rolling window the volatility kill-switch evaluates (see volatility.py)",
    )
    parser.add_argument(
        "--kill-switch-volatility-pct", type=float, default=0.0085,
        help="(max-min)/mean over the window above which posting/reposting is skipped for "
        "that cycle; default calibrated from real poller history, see volatility.py",
    )
    parser.add_argument(
        "--kill-switch-long-window-minutes", type=float, default=60.0,
        help="second, longer kill-switch window (<= 0 disables) — see volatility.py's "
        "2026-09-24 note",
    )
    parser.add_argument(
        "--kill-switch-long-volatility-pct", type=float, default=0.03,
        help="(max-min)/mean over the long window above which quoting pauses (<= 0 disables); "
        "default ~p95 of a real week of 60-min ranges",
    )
    parser.add_argument(
        "--kill-switch-cooldown-minutes", type=float, default=30.0,
        help="after any kill-switch trip, stay paused until this long passes with no new "
        "trip (0 disables)",
    )
    parser.add_argument(
        "--max-source-disagreement-pct", type=float, default=0.015,
        help="skip posting/reposting for a cycle if CoinGecko and Kraken disagree on the "
        "reference rate by more than this (when both are available for the pair) — see "
        "live_maker.py's module docstring for the real 2026-09-18 incident this closes and "
        "real poller-history calibration (p99=0.96%%, max=1.45%% over 559 samples).",
    )
    args = parser.parse_args(argv)

    if not args.live:
        print(
            "Refusing to run: --live was not passed, and this module has no dry-run "
            "fallback. Use `python -m strategy.quoter` to simulate without --live."
        )
        return 1

    if sum(a is not None for a in (args.amount_from, args.reserve_usd, args.reserve_coin)) != 1:
        print("Exactly one of --amount-from, --reserve-usd or --reserve-coin must be given.")
        return 1

    cfg = LiveMakerConfig(
        coin_from=args.coin_from,
        coin_to=args.coin_to,
        side=args.side,
        amount_from=args.amount_from,
        reserve_usd=args.reserve_usd,
        reserve_coin=args.reserve_coin,
        amount_step=args.amount_step,
        max_amount_from=args.max_amount_from,
        min_bid_amount=args.min_bid_amount,
        min_live_edge_pct=args.min_live_edge_pct,
        guard_interval_seconds=args.guard_interval_seconds,
        objective=args.objective,
        restock_target_to=args.restock_target_coin_to,
        restock_expected_sell_premium_pct=args.restock_expected_sell_premium_pct,
        restock_min_half_spread_pct=args.restock_min_half_spread_pct,
        restock_min_amount_from=args.restock_min_amount_from,
        restock_pricing=args.restock_pricing,
        restock_max_premium_pct=args.restock_max_premium_pct,
        half_spread_pct=args.half_spread_pct,
        assumed_fill_hours=args.assumed_fill_hours,
        reprice_threshold_pct=args.reprice_threshold_pct,
        offer_valid_hours=args.offer_valid_hours,
        lock_hours=args.lock_hours,
        valid_hours=args.valid_hours,
        automation_strat_id=args.automation_strat_id,
        kill_switch_window_minutes=args.kill_switch_window_minutes,
        kill_switch_volatility_pct=args.kill_switch_volatility_pct,
        kill_switch_long_window_minutes=args.kill_switch_long_window_minutes,
        kill_switch_long_volatility_pct=args.kill_switch_long_volatility_pct,
        kill_switch_cooldown_minutes=args.kill_switch_cooldown_minutes,
        max_source_disagreement_pct=args.max_source_disagreement_pct,
    )
    try:
        run(cfg, loop=args.loop)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

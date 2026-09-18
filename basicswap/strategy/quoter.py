"""Shadow quoter — ARCHITECTURE.md's original Phase 2 definition: "compute what
our strategy would have quoted against the Phase 1 data and whether it would have
filled/profited, still posting nothing." Answers "how would I handle maintaining
the correct rate" without ever posting or revoking a real offer.

Each cycle, for both sides of a pair (ask = selling coin_from for coin_to, bid =
selling coin_to for coin_from, both expressed in coin_to-per-coin_from units to
match analysis.py's convention):

  1. Pull the real external reference price (external_rates.py — same source
     poller.py already uses).
  2. Compute a target quote rate: reference_mid * (1 +/- half_spread_pct).
  3. Compare against the last simulated quote for that side (storage.py's
     simulated_quote_events, an append-only log — the "quote" is whatever
     the latest row's new_rate says):
       - no prior quote                          -> action="post"
       - drift beyond reprice_threshold_pct       -> action="reprice"
       - prior quote older than offer_valid_hours -> action="expire_repost"
       - otherwise                                -> no DB write, nothing to log

`api_client.py` gains no write methods from this module — there is no code path
here that can call BasicSwap's real /json/offers/new or /json/revokeoffer. This
answers "how often would I need to reprice to track the market" (a real, useful
number for design purposes), NOT "how often would I actually get filled" — §3
of next_steps.md already found that fill frequency is fundamentally unmeasurable
from passive/simulated data; only a real posted offer being bid by a real
counterparty (Phase 3, gated on Evan's sign-off) can answer that.
"""

import argparse
import logging
import statistics
import time
from dataclasses import dataclass

from . import coin_names, external_rates, storage
from .config import load_config
from .external_rates import ExternalRateError

log = logging.getLogger("basicswap.strategy.quoter")

SIDES = ("ask", "bid")


def half_spread_rate(reference_mid: float, half_spread_pct: float, side: str) -> float:
    if side == "ask":
        return reference_mid * (1 + half_spread_pct)
    if side == "bid":
        return reference_mid * (1 - half_spread_pct)
    raise ValueError(f"side must be 'ask' or 'bid', got {side!r}")


def decide_and_record(
    conn,
    coin_from: str,
    coin_to: str,
    side: str,
    reference_mid: float,
    half_spread_pct: float,
    reprice_threshold_pct: float,
    offer_valid_seconds: float,
    now: float | None = None,
) -> str | None:
    """Returns the action taken ("post"/"reprice"/"expire_repost"), or None if
    the existing simulated quote is still fine and nothing was logged."""
    now = now if now is not None else time.time()
    target_rate = half_spread_rate(reference_mid, half_spread_pct, side)
    prior = storage.fetch_latest_simulated_quote_event(conn, coin_from, coin_to, side)

    if prior is None:
        storage.insert_simulated_quote_event(
            conn, coin_from, coin_to, side, "post", target_rate, reference_mid, created_at=now
        )
        return "post"

    drift_pct = abs(target_rate - prior["new_rate"]) / prior["new_rate"]
    age_seconds = now - prior["created_at"]

    if drift_pct > reprice_threshold_pct:
        action = "reprice"
    elif age_seconds > offer_valid_seconds:
        action = "expire_repost"
    else:
        return None

    storage.insert_simulated_quote_event(
        conn,
        coin_from,
        coin_to,
        side,
        action,
        target_rate,
        reference_mid,
        previous_rate=prior["new_rate"],
        previous_posted_at=prior["created_at"],
        drift_pct=drift_pct,
        created_at=now,
    )
    return action


def run_cycle(
    client,
    conn,
    coin_from: str,
    coin_to: str,
    half_spread_pct: float,
    reprice_threshold_pct: float,
    offer_valid_seconds: float,
) -> None:
    try:
        rate = external_rates.get_reference_rate(coin_from, coin_to)
    except ExternalRateError as e:
        log.warning("get_reference_rate(%s, %s) failed, skipping this cycle: %s", coin_from, coin_to, e)
        return
    reference_mid = rate.coingecko_rate if rate.coingecko_rate is not None else rate.kraken_rate
    if reference_mid is None:
        log.warning("no usable reference rate for %s/%s this cycle, skipping", coin_from, coin_to)
        return

    display_from = coin_names.to_display_name(coin_from)
    display_to = coin_names.to_display_name(coin_to)
    for side in SIDES:
        action = decide_and_record(
            conn,
            display_from,
            display_to,
            side,
            reference_mid,
            half_spread_pct,
            reprice_threshold_pct,
            offer_valid_seconds,
        )
        if action:
            log.info(
                "%s/%s %s: %s @ reference_mid=%.8f",
                display_from,
                display_to,
                side,
                action,
                reference_mid,
            )


@dataclass
class QuoteEventsSummary:
    coin_from: str
    coin_to: str
    side: str
    n_events: int
    n_reprices: int  # excludes the initial "post"
    mean_seconds_between_reprices: float | None
    median_seconds_between_reprices: float | None


def summarize_quote_events(conn, coin_from: str, coin_to: str, side: str) -> QuoteEventsSummary:
    """The number this module actually produces: how often the simulated quote
    needed to move just to track the real market (not fill frequency — see the
    module docstring)."""
    events = storage.fetch_simulated_quote_events(conn, coin_from, coin_to, side=side)
    reprice_events = [e for e in events if e["action"] in ("reprice", "expire_repost")]
    gaps = [
        e["created_at"] - e["previous_posted_at"]
        for e in reprice_events
        if e["previous_posted_at"] is not None
    ]
    return QuoteEventsSummary(
        coin_from=coin_from,
        coin_to=coin_to,
        side=side,
        n_events=len(events),
        n_reprices=len(reprice_events),
        mean_seconds_between_reprices=statistics.fmean(gaps) if gaps else None,
        median_seconds_between_reprices=statistics.median(gaps) if gaps else None,
    )


def format_summary(s: QuoteEventsSummary) -> str:
    def fmt_hours(seconds: float | None) -> str:
        return "n/a" if seconds is None else f"{seconds / 3600:.2f}h"

    return (
        f"{s.coin_from}/{s.coin_to} {s.side}: {s.n_events} event(s), {s.n_reprices} reprice(s). "
        f"mean gap={fmt_hours(s.mean_seconds_between_reprices)} "
        f"median gap={fmt_hours(s.median_seconds_between_reprices)}"
    )


def run(loop: bool, half_spread_pct: float, reprice_threshold_pct: float, offer_valid_hours: float) -> None:
    from .api_client import BasicSwapClient

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = BasicSwapClient(
        config.api_url,
        auth_user=config.auth_user,
        auth_password=config.auth_password,
        timeout_seconds=config.request_timeout_seconds,
    )
    conn = storage.connect(config.db_path)
    offer_valid_seconds = offer_valid_hours * 3600
    log.info(
        "shadow-quoting pairs=%s half_spread_pct=%.4f reprice_threshold_pct=%.4f "
        "offer_valid_hours=%.2f db=%s (dry-run only — never calls a write endpoint)",
        config.pairs,
        half_spread_pct,
        reprice_threshold_pct,
        offer_valid_hours,
        config.db_path,
    )

    def cycle() -> None:
        for coin_from, coin_to in config.pairs:
            run_cycle(
                client, conn, coin_from, coin_to, half_spread_pct, reprice_threshold_pct, offer_valid_seconds
            )

    cycle()
    while loop:
        time.sleep(config.poll_interval_seconds)
        cycle()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="poll forever instead of a single cycle")
    parser.add_argument(
        "--half-spread-pct",
        type=float,
        default=0.0066,
        help="offset each side of the reference mid by this fraction (default 0.0066, "
        "half of economics.py's real 2026-09-17 today/1sigma required spread at $10k notional)",
    )
    parser.add_argument(
        "--reprice-threshold-pct",
        type=float,
        default=0.005,
        help="revoke+repost (simulated) once the target rate drifts this far from the "
        "last simulated quote (default 0.5%%)",
    )
    parser.add_argument(
        "--offer-valid-hours",
        type=float,
        default=0.7,
        help="repost (simulated) once a quote is this old regardless of drift (default "
        "0.7h, close to the ~42min real offer-validity average found in next_steps.md §3)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print summarize_quote_events() for each configured pair/side and exit "
        "(no polling)",
    )
    args = parser.parse_args(argv)

    if args.summary:
        config = load_config()
        conn = storage.connect(config.db_path)
        for coin_from, coin_to in config.pairs:
            display_from = coin_names.to_display_name(coin_from)
            display_to = coin_names.to_display_name(coin_to)
            for side in SIDES:
                print(format_summary(summarize_quote_events(conn, display_from, display_to, side)))
        return 0

    try:
        run(args.loop, args.half_spread_pct, args.reprice_threshold_pct, args.offer_valid_hours)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

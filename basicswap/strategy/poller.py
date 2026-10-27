"""Phase 1 poller (ARCHITECTURE.md §6): read-only, observes real BasicSwap offer-book
depth/spread on candidate pairs over time. Places no offer, moves no funds, holds no
key material — it only talks to the local JSON API and writes to a SQLite file.

Needs `basicswap-run` actually up (own terminal, not through Claude) with real
offers/rates on the wire. Run this from the same venv BasicSwap itself uses:

    source ~/coinswaps/venv/bin/activate
    cd basicswap
    ./run_poller.sh          # one poll cycle, or:
    ./run_poller.sh --loop   # poll forever at BASICSWAP_POLL_INTERVAL_SECONDS
"""

import argparse
import dataclasses
import logging
import sys
import time

from . import coin_names, external_rates, storage
from .api_client import BasicSwapAPIError, BasicSwapClient
from .config import Config, load_config
from .external_rates import ExternalRateError

log = logging.getLogger("basicswap.strategy.poller")


def poll_once(client: BasicSwapClient, conn, config: Config) -> None:
    polled_at = time.time()
    for coin_from, coin_to in config.pairs:
        # BasicSwap's own /json/offers always returns each offer's coin_from/
        # coin_to as its display name ("Bitcoin", "Monero"), regardless of the
        # ticker used to query it — storage.py/analysis.py store and join on
        # that display name (see coin_names.py). Only the query params below
        # (a, b) stay as raw tickers, since that's what the API call itself
        # (and external_rates.py's CoinGecko/Kraken lookups) expect.
        display_from = coin_names.to_display_name(coin_from)
        display_to = coin_names.to_display_name(coin_to)

        # Both directions: an offer selling coin_from for coin_to, and the
        # opposite-direction offer — together these are the two sides of one
        # market's spread (see analysis.py).
        for a, b in ((coin_from, coin_to), (coin_to, coin_from)):
            try:
                offers = client.get_offers(coin_from=a, coin_to=b)
            except BasicSwapAPIError as e:
                log.warning("get_offers(%s, %s) failed: %s", a, b, e)
                continue
            n = storage.insert_offer_snapshots(conn, offers, polled_at=polled_at)
            log.info("polled %d live offer(s) for %s->%s", n, a, b)

        try:
            rate_response = client.get_rate(coin_from, coin_to)
            storage.insert_rate_snapshot(
                conn, display_from, display_to, rate_response, polled_at=polled_at
            )
        except BasicSwapAPIError as e:
            log.warning("get_rate(%s, %s) failed: %s", coin_from, coin_to, e)

        # Independent of BasicSwap's own (broken) coingecko lookup above — see
        # external_rates.py (next_steps.md §2). Best-effort: a failure here still
        # leaves analysis.py's (best_ask + best_bid) / 2 fallback intact.
        try:
            direct = external_rates.get_reference_rate(coin_from, coin_to)
        except ExternalRateError as e:
            log.warning("get_reference_rate(%s, %s) failed: %s", coin_from, coin_to, e)
        else:
            # get_reference_rate echoes back lowercase tickers, not BasicSwap's
            # display-name convention — normalize before storing (coin_names.py).
            direct = dataclasses.replace(direct, coin_from=display_from, coin_to=display_to)
            storage.insert_direct_rate_snapshot(conn, direct, polled_at=polled_at)

    # Proof step (2026-09-28): Kraken XMR/BTC depth, so proof_report.py can cost
    # "restock on Kraken" at each sell fill's time. Best-effort, like the above.
    if any({a, b} == {"xmr", "btc"} for a, b in config.pairs):
        try:
            storage.insert_kraken_book_snapshot(conn, external_rates.get_kraken_xmr_book(), polled_at=polled_at)
        except (ExternalRateError, OSError, KeyError, ValueError) as e:
            log.warning("get_kraken_xmr_book failed: %s", e)

    # 2026-10-21: real wallet balances, so proof_report.py can score P&L net of
    # every fee (the fills ledger is gross). Best-effort, like the above.
    try:
        snapshot_wallets(client, conn, config, polled_at)
    except (BasicSwapAPIError, KeyError, TypeError, ValueError) as e:
        log.warning("wallet snapshot failed: %s", e)


def snapshot_wallets(client: BasicSwapClient, conn, config: Config, polled_at: float) -> None:
    from .live_maker import _TERMINAL_BID_STATES

    tickers = sorted({c for pair in config.pairs for c in pair})
    wallets = client.get_wallets()
    balances = {
        coin_names.to_display_name(t): (float(wallets[t.upper()]["balance"]), float(wallets[t.upper()].get("unconfirmed") or 0))
        for t in tickers
    }
    active = sum(
        b.get("bid_state") not in _TERMINAL_BID_STATES for b in client.get_bids() + client.get_sent_bids()
    )
    active += sum(s["status"] in ("created", "sent") for s in storage.fetch_exolix_swaps(conn))
    storage.insert_wallet_snapshot(conn, polled_at, balances, active)
    log.info(
        "wallets: %s, %d swap(s) in flight",
        ", ".join(f"{c} {b + u:.8f}" for c, (b, u) in balances.items()), active,
    )


def run(loop: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = BasicSwapClient(
        config.api_url,
        auth_user=config.auth_user,
        auth_password=config.auth_password,
        timeout_seconds=config.request_timeout_seconds,
    )
    conn = storage.connect(config.db_path)
    log.info("polling pairs=%s db=%s api=%s", config.pairs, config.db_path, config.api_url)

    poll_once(client, conn, config)
    while loop:
        time.sleep(config.poll_interval_seconds)
        poll_once(client, conn, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--loop", action="store_true", help="poll forever instead of a single cycle"
    )
    args = parser.parse_args(argv)
    try:
        run(loop=args.loop)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

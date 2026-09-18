"""Cross-venue observation poller — read-only, places no offer, moves no funds,
holds no key material anywhere. First venue: Bisq, via its own hosted public
API (no node/daemon/wallet required — see `bisq/client.py`). Registry-based so a
second `OfferBookReader` implementation (Eigen ASB, Haveno — `ARCHITECTURE.md`
§7) is a new entry here, not a rewrite.

Run from `market_maker/` (this package's parent), same convention as
`basicswap/strategy/poller.py`:

    ./venues/run_poller.sh          # one poll cycle, or:
    ./venues/run_poller.sh --loop   # poll forever at VENUES_POLL_INTERVAL_SECONDS
"""

import argparse
import logging
import sys
import time

from . import storage
from .bisq.reader import BisqOfferBookReader
from .config import Config, load_config
from .offer_book import OfferBookReader

log = logging.getLogger("market_maker.venues.poller")

_READERS: dict[str, type[OfferBookReader]] = {
    "bisq": BisqOfferBookReader,
}


def _build_readers(venue_names: list[str]) -> dict[str, OfferBookReader]:
    readers = {}
    for name in venue_names:
        reader_cls = _READERS.get(name)
        if reader_cls is None:
            log.warning("no OfferBookReader registered for venue %r — skipping", name)
            continue
        readers[name] = reader_cls()
    return readers


def poll_once(readers: dict[str, OfferBookReader], conn, config: Config) -> None:
    polled_at = time.time()
    for venue, reader in readers.items():
        for coin_from, coin_to in config.pairs:
            for a, b in ((coin_from, coin_to), (coin_to, coin_from)):
                try:
                    offers = reader.list_public_offers(a, b)
                except Exception as e:  # noqa: BLE001 - one venue/pair failing shouldn't stop the rest
                    log.warning("%s.list_public_offers(%s, %s) failed: %s", venue, a, b, e)
                    continue
                n = storage.insert_offer_snapshots(conn, offers, polled_at=polled_at)
                log.info("%s: polled %d live offer(s) for %s->%s", venue, n, a, b)


def run(loop: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    readers = _build_readers(config.venues)
    conn = storage.connect(config.db_path)
    log.info("polling venues=%s pairs=%s db=%s", list(readers), config.pairs, config.db_path)

    poll_once(readers, conn, config)
    while loop:
        time.sleep(config.poll_interval_seconds)
        poll_once(readers, conn, config)


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

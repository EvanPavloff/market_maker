"""Normalizes instant-swap quotes into the shared `NormalizedOffer` shape.

An instant-swap service has no order book, just a quote for a given size. Each
poll asks for one probe size (`VENUES_QUOTE_PROBE_BTC`, default 0.0032 BTC, or
about 0.5 XMR, the size the restock leg tops up) and stores the answer as a
single offer from the service's side: it gives XMR (coin_from) for our BTC
(coin_to). `implied_rate` is BTC per XMR, the same direction as Bisq and Eigen
ASB XMR-sell offers, so `venues/restock_cost.py` can rank all three together.

Only that direction is quoted. Buying XMR with BTC is what restocking needs, and
it's also what our sell leg's customers do, so this one quote covers both
questions. The reverse direction returns no offers rather than an error.
"""

import os

from ..offer_book import NormalizedOffer
from .client import changenow_quote, exolix_quote

_DEFAULT_PROBE_BTC = 0.0032


def _probe_btc() -> float:
    return float(os.environ.get("VENUES_QUOTE_PROBE_BTC", _DEFAULT_PROBE_BTC))


def _quote_offer(venue: str, probe_btc: float, xmr_out: float, min_btc: float | None) -> NormalizedOffer:
    rate = probe_btc / xmr_out  # BTC per XMR
    return NormalizedOffer(
        venue=venue,
        offer_id=f"quote:{probe_btc:.8f}",
        coin_from="xmr",
        coin_to="btc",
        amount_from=xmr_out,
        amount_to=probe_btc,
        implied_rate=rate,
        expire_at=None,
        min_bid_amount=(min_btc / rate) if min_btc else None,  # XMR units
        is_own_offer=False,
    )


class _QuoteReader:
    venue = ""

    def __init__(self, probe_btc: float | None = None, timeout_seconds: float = 10.0):
        self.probe_btc = probe_btc if probe_btc is not None else _probe_btc()
        self.timeout_seconds = timeout_seconds

    def list_public_offers(self, coin_from: str, coin_to: str) -> list[NormalizedOffer]:
        coin_from, coin_to = coin_from.lower(), coin_to.lower()
        if (coin_from, coin_to) == ("btc", "xmr"):
            return []  # not quoted, see the module docstring
        if (coin_from, coin_to) != ("xmr", "btc"):
            raise ValueError(f"{self.venue} reader only quotes xmr/btc, got {coin_from}/{coin_to}")
        return [self._quote()]

    def _quote(self) -> NormalizedOffer:
        raise NotImplementedError


class ExolixQuoteReader(_QuoteReader):
    venue = "exolix"

    def _quote(self) -> NormalizedOffer:
        xmr_out, min_btc = exolix_quote(self.probe_btc, self.timeout_seconds)
        return _quote_offer(self.venue, self.probe_btc, xmr_out, min_btc)


class ChangeNowQuoteReader(_QuoteReader):
    venue = "changenow"

    def _quote(self) -> NormalizedOffer:
        xmr_out = changenow_quote(self.probe_btc, self.timeout_seconds)
        return _quote_offer(self.venue, self.probe_btc, xmr_out, None)

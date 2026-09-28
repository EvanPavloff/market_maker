"""Normalizes Eigen ASB quotes into the shared `NormalizedOffer` shape
(`venues/offer_book.py`).

Unlike Bisq/BasicSwap, Eigen ASB is a **one-directional** market: an ASB
("Automated Swap Backend") only ever sells XMR for BTC — there is no "buy
XMR" side, no order book, just each live ASB continuously quoting a rate. So
the maker's perspective (`venues/offer_book.py`'s convention: coin_from =
what the maker gives up) is always coin_from="xmr", coin_to="btc"; the
reverse direction genuinely has zero offers, not an error.

Field-unit mapping, confirmed against `swap-p2p`'s own `BidQuote` struct
(`swap-p2p/src/protocols/quote.rs`, doc comment: "Represents a quote for
buying XMR" — from the maker's perspective, the maker is quoting the price at
which it will buy BTC / sell XMR) — all three fields
(`price`/`min_quantity`/`max_quantity`) are typed `bitcoin::Amount`, i.e. all
in **BTC** units, not XMR:

  - `price` = BTC per 1 XMR (implied_rate directly, no inversion needed,
    since coin_from=xmr/coin_to=btc already matches this rate's direction).
  - `min_quantity`/`max_quantity` = the BTC amount range the ASB will accept
    from a taker per swap — converted to XMR (coin_from) units via `price`
    for `amount_from`/`min_bid_amount`, matching `NormalizedOffer`'s
    "in coin_from units" contract.

A `0`/`0` min/max quantity has been observed live (2026-09-19) on a couple of
real ASBs — not malformed, just an ASB that hasn't configured explicit
liquidity bounds (or has them misconfigured). Kept as a real `0.0` amount
rather than skipped: worth keeping visible since, in the first live sample,
the `0`/`0` ASBs were also among the most price-outlying ones — a real,
possibly explanatory correlation, not something to quietly drop.
"""

from ..offer_book import NormalizedOffer
from .client import EigenAsbClient, EigenAsbClientError


def _parse_btc_display(value: str) -> float:
    # "0.00688977 BTC" -> 0.00688977. Defensive split rather than a fixed
    # slice, in case the binary's Display formatting ever changes precision.
    return float(value.split()[0])


class EigenAsbOfferBookReader:
    venue = "eigen_asb"

    def __init__(self, client: EigenAsbClient | None = None):
        self.client = client or EigenAsbClient()

    def list_public_offers(self, coin_from: str, coin_to: str) -> list[NormalizedOffer]:
        coin_from, coin_to = coin_from.lower(), coin_to.lower()

        if (coin_from, coin_to) != ("xmr", "btc"):
            if {coin_from, coin_to} == {"xmr", "btc"}:
                # Valid pair, but the only direction Eigen ASB ever quotes is
                # xmr->btc (the maker selling XMR) -- genuinely zero offers on
                # the reverse side, not a failure.
                return []
            raise ValueError(
                f"Eigen ASB only ever quotes xmr/btc, got {coin_from}/{coin_to}"
            )

        try:
            raw_quotes = self.client.fetch_quotes()
        except EigenAsbClientError:
            raise

        offers = []
        for entry in raw_quotes:
            try:
                offers.append(self._normalize(entry))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                # One malformed/unparseable quote shouldn't drop the whole
                # poll -- same fail-soft posture as bisq/reader.py.
                continue
        return offers

    def _normalize(self, entry: dict) -> NormalizedOffer:
        price = _parse_btc_display(entry["price_btc_display"])  # BTC per XMR
        min_quantity_btc = _parse_btc_display(entry["min_quantity_btc_display"])
        max_quantity_btc = _parse_btc_display(entry["max_quantity_btc_display"])

        if price <= 0:
            raise ValueError("non-positive price on Eigen ASB quote")

        amount_to = max_quantity_btc  # BTC the maker would receive, max size
        amount_from = amount_to / price  # XMR the maker would give, converted
        min_bid_amount = min_quantity_btc / price  # XMR units, per the schema contract

        return NormalizedOffer(
            venue="eigen_asb",
            offer_id=entry["peer"],  # no discrete offer id -- ASBs quote continuously
            coin_from="xmr",
            coin_to="btc",
            amount_from=amount_from,
            amount_to=amount_to,
            implied_rate=price,
            expire_at=None,  # not a listing with an expiry -- a live re-quoted price
            min_bid_amount=min_bid_amount,
            is_own_offer=False,  # no Eigen ASB identity -- pure market-data read
        )

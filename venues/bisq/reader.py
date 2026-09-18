"""Normalizes Bisq Markets API offers into the shared `NormalizedOffer` shape
(`venues/offer_book.py`).

Bisq's own convention (confirmed live 2026-09-18 against `xmr_btc`): a market pair
code like "xmr_btc" has a fixed base/left currency (xmr) and quote/right currency
(btc). Every offer's `amount` field is in base-currency units, `volume` is in
quote-currency units, and `price` is quote-per-base — regardless of the offer's
own `direction`:

  - a SELL offer: the maker is selling the base currency for the quote currency
    (coin_from=base, coin_to=quote; implied_rate = price directly).
  - a BUY offer: the maker is buying the base currency by selling the quote
    currency (coin_from=quote, coin_to=base; implied_rate = 1/price — this is
    the inverse direction, same as `external_rates.py`'s Kraken-pair inversion).

`min_bid_amount` is likewise always base-currency in Bisq's own `min_amount`
field; converted to quote-currency units (via `price`) when this reader is
returning the quote->base direction, so it stays in the returned offer's own
`coin_from` units either way.
"""

from ..offer_book import NormalizedOffer
from .client import BisqMarketsAPIError, BisqMarketsClient

# (coin_from, coin_to) -> Bisq market pair code, keyed by Bisq's own base/quote
# order. Only pairs actually observed live so far — extend as more get checked
# against the real API (some pair codes may not exist even if both coins are
# individually supported).
_MARKET_PAIRS: dict[tuple[str, str], str] = {
    ("xmr", "btc"): "xmr_btc",
}


class BisqOfferBookReader:
    venue = "bisq"

    def __init__(self, client: BisqMarketsClient | None = None):
        self.client = client or BisqMarketsClient()

    def list_public_offers(self, coin_from: str, coin_to: str) -> list[NormalizedOffer]:
        coin_from, coin_to = coin_from.lower(), coin_to.lower()
        base, quote, market, want_sell_side = self._resolve_market(coin_from, coin_to)

        try:
            raw = self.client.get_offers(market)
        except BisqMarketsAPIError:
            raise

        entries = raw["sells"] if want_sell_side else raw["buys"]
        offers = []
        for entry in entries:
            try:
                offers.append(self._normalize(entry, base, quote, want_sell_side))
            except (KeyError, TypeError, ValueError):
                # A single malformed entry shouldn't drop the whole poll — skip it,
                # same fail-soft posture as basicswap/strategy/poller.py's
                # per-pair try/except around each API call.
                continue
        return offers

    def _resolve_market(self, coin_from: str, coin_to: str) -> tuple[str, str, str, bool]:
        market = _MARKET_PAIRS.get((coin_from, coin_to))
        if market is not None:
            return coin_from, coin_to, market, True  # base->quote == SELL side
        market = _MARKET_PAIRS.get((coin_to, coin_from))
        if market is not None:
            return coin_to, coin_from, market, False  # quote->base == BUY side
        raise ValueError(
            f"no Bisq market pair configured for {coin_from}/{coin_to} — "
            f"add it to _MARKET_PAIRS once confirmed live"
        )

    def _normalize(self, entry: dict, base: str, quote: str, is_sell_side: bool) -> NormalizedOffer:
        amount = float(entry["amount"])  # base-currency units
        volume = float(entry["volume"])  # quote-currency units
        price = float(entry["price"])  # quote-per-base
        min_amount = float(entry["min_amount"]) if entry.get("min_amount") is not None else None

        if is_sell_side:
            coin_from, coin_to = base, quote
            amount_from, amount_to = amount, volume
            implied_rate = price
            min_bid_amount = min_amount
        else:
            coin_from, coin_to = quote, base
            amount_from, amount_to = volume, amount
            implied_rate = (1.0 / price) if price else None
            min_bid_amount = (min_amount * price) if min_amount is not None else None

        if implied_rate is None:
            raise ValueError("zero price on Bisq offer — cannot invert")

        return NormalizedOffer(
            venue="bisq",
            offer_id=entry["offer_id"],
            coin_from=coin_from,
            coin_to=coin_to,
            amount_from=amount_from,
            amount_to=amount_to,
            implied_rate=implied_rate,
            expire_at=None,  # not exposed by this API
            min_bid_amount=min_bid_amount,
            is_own_offer=False,  # no Bisq identity configured — pure market-data read
        )

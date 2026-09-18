"""Shared shape for a public offer, normalized the same way regardless of which
venue produced it — the interface `next_steps.md` #11 speced for the (not yet
built) cross-venue mispriced-offer scanner, built now because venue #2's own
observation poller needs the identical shape (`ARCHITECTURE.md` §7).

`coin_from`/`coin_to` follow `basicswap/strategy/`'s own convention: an offer
always describes what its maker is giving up (`coin_from`) for what they're
receiving (`coin_to`), lowercase tickers. `implied_rate` is coin_to-per-coin_from,
matching `basicswap/strategy/external_rates.py`'s `ReferenceRate` convention, so
values from different venues are directly comparable without a caller having to
know each venue's own quoting convention.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NormalizedOffer:
    venue: str
    offer_id: str
    coin_from: str
    coin_to: str
    amount_from: float
    amount_to: float
    implied_rate: float  # coin_to per coin_from
    expire_at: float | None
    min_bid_amount: float | None  # in coin_from units, when known
    is_own_offer: bool


class OfferBookReader(Protocol):
    """One implementation per venue. Read-only by design — no method here can
    place, accept, or cancel anything; that's a deliberately separate, higher-risk
    capability (next_steps.md #11 item 6) not built by this interface.
    """

    venue: str

    def list_public_offers(self, coin_from: str, coin_to: str) -> list[NormalizedOffer]:
        """Offers currently on the venue's book selling coin_from for coin_to —
        i.e. one direction only, matching basicswap/strategy/poller.py's own
        convention of calling this twice per pair (once per direction) rather
        than returning both sides from one call.
        """
        ...

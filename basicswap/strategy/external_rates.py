"""Direct, BasicSwap-independent reference-rate lookup (next_steps.md §2).

Motivation: the Phase 1 smoke test found BasicSwap's own `/json/rateslist` lookup
(a server-side call to coingecko.com) failing (`[["coingecko.com", "error", "6"]]`).
`analysis.py` falls back to `(best_ask + best_bid) / 2` when that happens, which is
circular on a thin book — it can't tell you whether the book itself is mispriced
relative to the outside world. This module bypasses BasicSwap's own lookup entirely
(a direct call to CoinGecko's public REST API) and adds a second, independent
cross-check (a public Kraken ticker, for the handful of pairs Kraken actually lists)
so a mid-price can be trusted even when the order book is thin or one-sided.

Stdlib-only (urllib), matching api_client.py's convention — no new pip dependency,
no API key (both endpoints used here are public/keyless).
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# This venv's framework-Python install has no root CA bundle at its default
# ssl.get_default_verify_paths() location (the classic python.org-installer gap
# normally closed by running "Install Certificates.command" — a GUI/human step
# this project avoids requiring). certifi happens to already be present in
# ~/coinswaps/venv (pulled in transitively, not a pin this project added) — use
# its bundle opportunistically for real cert verification without depending on
# that human step; fall back to the interpreter's own default context (which
# will simply keep failing until certifi is present or the human step is run,
# same as today) if certifi isn't importable. Never disables verification.
try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# BasicSwap-supported coins (ARCHITECTURE.md §1) with a CoinGecko coin id. Coins
# BasicSwap supports but CoinGecko doesn't meaningfully price (or that aren't worth
# wiring until a pair actually gets observed) are simply omitted — get_reference_rate
# raises a clear error rather than guessing at an id.
_COINGECKO_IDS = {
    "btc": "bitcoin",
    "xmr": "monero",
    "ltc": "litecoin",
    "dash": "dash",
    "bch": "bitcoin-cash",
    "doge": "dogecoin",
    "firo": "firo",
    "pivx": "pivx",
    "dcr": "decred",
    "wow": "wownero",
    "part": "particl",
    "nmc": "namecoin",
}

# Kraken altname pairs for the handful of BasicSwap pairs Kraken also lists directly
# — used only as an independent cross-check, never as the primary source (Kraken
# doesn't list most of BasicSwap's flagship privacy/altcoin pairs). Extend this as
# more pairs get observed in practice; an unlisted pair just skips the cross-check
# rather than failing.
_KRAKEN_PAIRS = {
    ("xmr", "btc"): "XMRXBT",
    ("ltc", "btc"): "LTCXBT",
}


class ExternalRateError(RuntimeError):
    """Raised only when every configured source fails outright (network/parse
    error) — a source that responds but disagrees with another is not an error,
    see ReferenceRate.disagreement_pct."""


def _get_json(url: str, timeout: float) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _coingecko_usd_prices(coin_ids: list[str], timeout: float) -> dict[str, float]:
    url = (
        "https://api.coingecko.com/api/v3/simple/price?"
        + urllib.parse.urlencode({"ids": ",".join(coin_ids), "vs_currencies": "usd"})
    )
    data = _get_json(url, timeout)
    if not isinstance(data, dict):
        raise ExternalRateError(f"unexpected CoinGecko response shape: {data!r}")
    return {coin_id: entry["usd"] for coin_id, entry in data.items() if "usd" in entry}


def _kraken_ticker_rate(pair: str, timeout: float) -> float:
    url = "https://api.kraken.com/0/public/Ticker?" + urllib.parse.urlencode({"pair": pair})
    data = _get_json(url, timeout)
    if not isinstance(data, dict) or data.get("error"):
        raise ExternalRateError(f"Kraken error for {pair}: {data.get('error') if isinstance(data, dict) else data!r}")
    result = data.get("result", {})
    if not result:
        raise ExternalRateError(f"Kraken returned no result for {pair}")
    # Kraken echoes back its own canonical pair key (not necessarily the altname we
    # queried with) — there's exactly one entry for a single-pair query, so just take it.
    ticker = next(iter(result.values()))
    return float(ticker["c"][0])  # last trade closed price


@dataclass
class ReferenceRate:
    coin_from: str
    coin_to: str
    coingecko_rate: float | None  # coin_to-per-coin_from, via a USD cross (see below)
    kraken_rate: float | None  # coin_to-per-coin_from, direct pair (cross-check only)
    disagreement_pct: float | None  # |coingecko - kraken| / mean, when both present
    coingecko_error: str | None
    kraken_error: str | None

    @property
    def mid(self) -> float | None:
        """Best available reference mid: prefer CoinGecko (always attempted), fall
        back to Kraken alone if CoinGecko failed but a cross-check pair exists."""
        return self.coingecko_rate if self.coingecko_rate is not None else self.kraken_rate


def get_usd_price(coin: str, timeout: float = 10.0) -> float:
    """Single coin's USD price — added 2026-09-17 for live_maker.py's
    `--reserve-usd` sizing (a dollar-denominated reserve has to be converted
    to a coin quantity against a live price, not a fixed number chosen once).
    Reuses the same CoinGecko endpoint get_reference_rate's cross-rate already
    calls; raises ExternalRateError on any failure rather than degrading,
    since a caller sizing a real offer needs a real number, not a guess."""
    coin = coin.lower()
    try:
        coin_id = _COINGECKO_IDS[coin]
    except KeyError as e:
        raise ExternalRateError(f"no CoinGecko id mapped for {e}") from e
    try:
        return _coingecko_usd_prices([coin_id], timeout)[coin_id]
    except Exception as e:  # noqa: BLE001 - any network/parse failure surfaces as ExternalRateError
        raise ExternalRateError(f"failed to fetch USD price for {coin}: {e}") from e


def get_reference_rate(coin_from: str, coin_to: str, timeout: float = 10.0) -> ReferenceRate:
    """coin_to-per-coin_from reference rate, independent of BasicSwap's own
    (currently broken) lookup. Never raises for a single source's failure — only
    ExternalRateError if there is nothing at all to return (which callers should
    treat the same way analysis.py already treats a wholly missing reference_mid:
    fall back to (best_ask + best_bid) / 2 on the book itself).
    """
    coin_from, coin_to = coin_from.lower(), coin_to.lower()

    coingecko_rate = None
    coingecko_error = None
    try:
        id_from = _COINGECKO_IDS[coin_from]
        id_to = _COINGECKO_IDS[coin_to]
    except KeyError as e:
        coingecko_error = f"no CoinGecko id mapped for {e}"
    else:
        try:
            usd_prices = _coingecko_usd_prices([id_from, id_to], timeout)
            price_from = usd_prices[id_from]
            price_to = usd_prices[id_to]
            coingecko_rate = price_from / price_to
        except Exception as e:  # noqa: BLE001 - any network/parse failure degrades, doesn't raise
            coingecko_error = str(e)

    kraken_rate = None
    kraken_error = None
    kraken_pair = _KRAKEN_PAIRS.get((coin_from, coin_to))
    inverted = False
    if kraken_pair is None:
        kraken_pair = _KRAKEN_PAIRS.get((coin_to, coin_from))
        inverted = kraken_pair is not None
    if kraken_pair is None:
        kraken_error = f"no Kraken pair configured for {coin_from}/{coin_to}"
    else:
        try:
            rate = _kraken_ticker_rate(kraken_pair, timeout)
            kraken_rate = (1.0 / rate) if inverted else rate
        except Exception as e:  # noqa: BLE001
            kraken_error = str(e)

    disagreement_pct = None
    if coingecko_rate is not None and kraken_rate is not None:
        mean = (coingecko_rate + kraken_rate) / 2
        if mean:
            disagreement_pct = abs(coingecko_rate - kraken_rate) / mean

    if coingecko_rate is None and kraken_rate is None:
        raise ExternalRateError(
            f"no external reference rate available for {coin_from}/{coin_to}: "
            f"coingecko={coingecko_error}, kraken={kraken_error}"
        )

    return ReferenceRate(
        coin_from=coin_from,
        coin_to=coin_to,
        coingecko_rate=coingecko_rate,
        kraken_rate=kraken_rate,
        disagreement_pct=disagreement_pct,
        coingecko_error=coingecko_error,
        kraken_error=kraken_error,
    )

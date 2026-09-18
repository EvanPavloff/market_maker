"""Ticker abbreviation -> BasicSwap's own canonical coin display name.

Found live 2026-09-16, first real offers on the wire: `config.py`'s
`BASICSWAP_PAIRS` env var uses short ticker abbreviations ("xmr/btc", matching
`external_rates.py`'s `_COINGECKO_IDS` convention), but BasicSwap's own
`/json/offers` responses always return the coin's title-cased display name
regardless of what ticker was used to query it (`coin_from: "Bitcoin"`,
`coin_to: "Monero"` — verified live, not "btc"/"xmr"). That display name comes
from `basicswap/ui/util.py`'s `getCoinName()`: a coin's chainparams
`display_name` if one is set (e.g. "Bitcoin Cash", "PIVX"), else its `name`
field capitalized (read directly from each coin's `interface/<coin>/
chainparams.py` — not guessed).

`storage.py`/`analysis.py` store and query offer rows keyed on that display
name (matches the real API response and this package's existing test
fixtures, which predate this file and already use "Monero"/"Bitcoin"). Any
ticker abbreviation coming from `config.py` must be translated through this
module before it's used as a storage/query key, or `build_poll_snapshots`
silently joins against zero rows even when the poller is correctly capturing
real offers — exactly the bug this file fixes (see project_status.md's
2026-09-16 entry).

Only covers the coins this project has actually configured pairs for or
cross-checked externally so far (matches `external_rates.py`'s
`_COINGECKO_IDS` keys, plus `nav`) — extend both together as new pairs get
added.
"""

_DISPLAY_NAMES = {
    "btc": "Bitcoin",
    "xmr": "Monero",
    "ltc": "Litecoin",
    "dash": "Dash",
    "bch": "Bitcoin Cash",
    "doge": "Dogecoin",
    "firo": "Firo",
    "pivx": "PIVX",
    "dcr": "Decred",
    "wow": "Wownero",
    "part": "Particl",
    "nmc": "Namecoin",
    "nav": "Navcoin",
}


def to_display_name(ticker_or_name: str) -> str:
    """Idempotent: a known ticker ("xmr") maps to its display name ("Monero");
    anything else (already a display name, or an unmapped coin) passes through
    unchanged rather than raising — callers already treat "no data for this
    pair" as a legitimate empty result, not an error (see
    summarize_pair_with_no_data_is_empty_not_error)."""
    return _DISPLAY_NAMES.get(ticker_or_name.lower(), ticker_or_name)

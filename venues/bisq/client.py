"""Thin client for Bisq's own hosted, public, keyless market-data REST API
(`markets.bisq.network` — the `bisq.markets` frontend's backend; "powered by the
Mempool backend" per the bisq-network/bisq-markets README). Verified live
2026-09-18: `GET /api/offers?market=xmr_btc` returned real buy/sell offers with no
auth. Unlike BasicSwap, Haveno, or Eigen ASB, this needs no locally-run node,
daemon, or wallet at all — it's a hosted aggregation of Bisq's own P2P network
offer data, so reading it carries zero capital/setup cost.

Stdlib-only (urllib), matching `basicswap/strategy/external_rates.py`'s convention
for talking to a public third-party API (no new pip dependency).
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_DEFAULT_BASE_URL = "https://markets.bisq.network"


class BisqMarketsAPIError(RuntimeError):
    """Raised on any network/HTTP/parse failure talking to the Bisq Markets API."""


class BisqMarketsClient:
    def __init__(self, base_url: str = _DEFAULT_BASE_URL, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_offers(self, market: str) -> dict[str, Any]:
        """`{"buys": [...], "sells": [...]}` for one Bisq market pair code (e.g.
        "xmr_btc") — verbatim, un-normalized (see `bisq/reader.py` for the
        NormalizedOffer mapping). The live endpoint nests this one level deeper
        than its own docs excerpt suggested — verified live 2026-09-18:
        `GET /api/offers?market=xmr_btc` actually returns `{"xmr_btc": {"buys":
        [...], "sells": [...]}}`, keyed by the requested market — this unwraps
        that key so callers always get the same flat shape regardless.
        """
        url = f"{self.base_url}/api/offers?" + urllib.parse.urlencode({"market": market})
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=_SSL_CONTEXT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            raise BisqMarketsAPIError(f"GET {url} failed: {e}") from e
        except json.JSONDecodeError as e:
            raise BisqMarketsAPIError(f"GET {url} returned invalid JSON: {e}") from e
        if isinstance(data, dict) and market in data:
            data = data[market]
        if not isinstance(data, dict) or "buys" not in data or "sells" not in data:
            raise BisqMarketsAPIError(f"GET {url} returned unexpected shape: {data!r}")
        return data

"""Thin clients for instant-swap services' public, keyless quote endpoints.

These aren't DEXes. An instant-swap service takes your BTC, holds it for a few
minutes, and sends XMR back, usually hedging on a CEX behind the scenes. You
don't need an account, but the service can freeze a "flagged" deposit and ask
for KYC. `ARCHITECTURE.md` §7 lists aggregators as the REPLENISHMENT tier, a
last resort. They're observed here only to price restocking against the DEX
venues and Kraken. Nothing here creates an exchange or sends funds.

Checked live 2026-10-02, no API key needed:
  - Exolix   `GET /api/v2/rate` -> {"fromAmount", "toAmount", "rate", "minAmount", ...}
  - ChangeNOW `GET /v1/exchange-amount/{amount}/btc_xmr` -> {"estimatedAmount", ...}
Checked the same day and not usable: Trocador (HTTP 401, needs a key), SideShift
("Settle method is disabled" for XMR), exch.cx / Majestic Bank / FixedFloat
(no connection from here). THORChain, Maya and Chainflip don't list XMR.

Stdlib-only (urllib), same as `venues/bisq/client.py`.
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


class InstantSwapAPIError(RuntimeError):
    """Raised on any network/HTTP/parse failure, or a quote with no usable amount."""


def _get_json(url: str, timeout_seconds: float) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise InstantSwapAPIError(f"GET {url} failed: {e}") from e
    except json.JSONDecodeError as e:
        raise InstantSwapAPIError(f"GET {url} returned non-JSON: {e}") from e


def exolix_quote(amount_btc: float, timeout_seconds: float = 10.0) -> tuple[float, float | None]:
    """XMR received for `amount_btc` at Exolix's floating rate, and its minimum
    deposit in BTC (None if not given)."""
    url = "https://exolix.com/api/v2/rate?" + urllib.parse.urlencode(
        {
            "coinFrom": "BTC", "networkFrom": "BTC",
            "coinTo": "XMR", "networkTo": "XMR",
            "amount": f"{amount_btc:.8f}", "rateType": "float",
        }
    )
    raw = _get_json(url, timeout_seconds)
    to_amount = raw.get("toAmount") if isinstance(raw, dict) else None
    if not to_amount:
        raise InstantSwapAPIError(f"Exolix quote has no toAmount: {raw!r}")
    min_amount = raw.get("minAmount")
    return float(to_amount), (float(min_amount) if min_amount else None)


def changenow_quote(amount_btc: float, timeout_seconds: float = 10.0) -> float:
    """XMR ChangeNOW estimates for `amount_btc` (its standard floating flow)."""
    url = f"https://api.changenow.io/v1/exchange-amount/{amount_btc:.8f}/btc_xmr"
    raw = _get_json(url, timeout_seconds)
    estimated = raw.get("estimatedAmount") if isinstance(raw, dict) else None
    if not estimated:
        raise InstantSwapAPIError(f"ChangeNOW quote has no estimatedAmount: {raw!r}")
    return float(estimated)

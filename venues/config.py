"""Poller config — env-driven, same convention as
`basicswap/strategy/config.py`, so this can run unattended (launchd) without a
code edit. See `.env.example` for the full list with defaults and comments.
"""

import os
from dataclasses import dataclass, field


def _parse_pairs(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        coin_from, _, coin_to = chunk.partition("/")
        if not coin_from or not coin_to:
            raise ValueError(f"Invalid pair '{chunk}' in VENUES_PAIRS — expected FROM/TO")
        pairs.append((coin_from.strip().lower(), coin_to.strip().lower()))
    return pairs


def _parse_venues(raw: str) -> list[str]:
    return [v.strip().lower() for v in raw.split(",") if v.strip()]


@dataclass(frozen=True)
class Config:
    venues: list[str] = field(default_factory=lambda: ["bisq"])
    pairs: list[tuple[str, str]] = field(default_factory=lambda: [("xmr", "btc")])
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: int = 300
    db_path: str = os.path.expanduser("~/coinswaps/venue_observations.db")


def load_config() -> Config:
    return Config(
        venues=_parse_venues(os.environ.get("VENUES_ENABLED", "bisq")),
        pairs=_parse_pairs(os.environ.get("VENUES_PAIRS", "xmr/btc")),
        request_timeout_seconds=float(os.environ.get("VENUES_REQUEST_TIMEOUT_SECONDS", "10")),
        poll_interval_seconds=int(os.environ.get("VENUES_POLL_INTERVAL_SECONDS", "300")),
        db_path=os.path.expanduser(
            os.environ.get("VENUES_DB_PATH", "~/coinswaps/venue_observations.db")
        ),
    )

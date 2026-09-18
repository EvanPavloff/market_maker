"""Phase 1 poller config — all knobs come from the environment so this can run
unattended (launchd, matching this workspace's other schedulers) without a code edit.

See ../.env.example for the full list with defaults and comments.
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
            raise ValueError(f"Invalid pair '{chunk}' in BASICSWAP_PAIRS — expected FROM/TO")
        pairs.append((coin_from.strip().lower(), coin_to.strip().lower()))
    return pairs


@dataclass(frozen=True)
class Config:
    api_url: str = "http://localhost:12700"
    auth_user: str | None = None
    auth_password: str | None = None
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: int = 300
    db_path: str = os.path.expanduser("~/coinswaps/basicswap_observations.db")
    pairs: list[tuple[str, str]] = field(default_factory=lambda: [("xmr", "btc")])


def load_config() -> Config:
    return Config(
        api_url=os.environ.get("BASICSWAP_API_URL", "http://localhost:12700"),
        auth_user=os.environ.get("BASICSWAP_AUTH_USER") or None,
        auth_password=os.environ.get("BASICSWAP_AUTH_PASSWORD") or None,
        request_timeout_seconds=float(os.environ.get("BASICSWAP_REQUEST_TIMEOUT_SECONDS", "10")),
        poll_interval_seconds=int(os.environ.get("BASICSWAP_POLL_INTERVAL_SECONDS", "300")),
        db_path=os.path.expanduser(
            os.environ.get("BASICSWAP_DB_PATH", "~/coinswaps/basicswap_observations.db")
        ),
        pairs=_parse_pairs(os.environ.get("BASICSWAP_PAIRS", "xmr/btc")),
    )

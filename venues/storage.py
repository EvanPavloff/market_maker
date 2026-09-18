"""SQLite storage for cross-venue offer-book observations. Append-only, same
convention as `basicswap/strategy/storage.py`'s `offer_snapshots` — one row per
polled offer, never mutated, so spread/depth/fill-rate can be reconstructed over
time per venue. Lives outside this git repo by default (`~/coinswaps/`,
alongside BasicSwap's own runtime data and its poller's own DB file — a separate
file, not a shared one, so a schema change on one never risks the other).
"""

import sqlite3
import time
from typing import Any

from .offer_book import NormalizedOffer

_SCHEMA = """
CREATE TABLE IF NOT EXISTS venue_offer_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    polled_at REAL NOT NULL,
    venue TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    implied_rate REAL NOT NULL,
    expire_at REAL,
    min_bid_amount REAL,
    is_own_offer INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_venue_offer_snapshots_venue_pair_time
    ON venue_offer_snapshots (venue, coin_from, coin_to, polled_at);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def insert_offer_snapshots(
    conn: sqlite3.Connection,
    offers: list[NormalizedOffer],
    polled_at: float | None = None,
) -> int:
    polled_at = polled_at if polled_at is not None else time.time()
    rows = [
        (
            polled_at,
            o.venue,
            o.offer_id,
            o.coin_from,
            o.coin_to,
            o.amount_from,
            o.amount_to,
            o.implied_rate,
            o.expire_at,
            o.min_bid_amount,
            int(o.is_own_offer),
        )
        for o in offers
    ]
    conn.executemany(
        """
        INSERT INTO venue_offer_snapshots (
            polled_at, venue, offer_id, coin_from, coin_to, amount_from,
            amount_to, implied_rate, expire_at, min_bid_amount, is_own_offer
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def fetch_offer_snapshots(
    conn: sqlite3.Connection,
    venue: str,
    coin_from: str,
    coin_to: str,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = (
        "SELECT * FROM venue_offer_snapshots WHERE venue = ? AND coin_from = ? AND coin_to = ?"
    )
    params: list[Any] = [venue, coin_from, coin_to]
    if since is not None:
        query += " AND polled_at >= ?"
        params.append(since)
    query += " ORDER BY polled_at ASC"
    return conn.execute(query, params).fetchall()

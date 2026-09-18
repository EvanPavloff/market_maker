"""SQLite storage for Phase 1 observations.

One append-only snapshot per poll — never mutated, never deleted (that's what
lets analysis.py reconstruct depth/spread *over time*, not just the latest
poll). Lives outside this git repo by default (~/coinswaps/, alongside
BasicSwap's own runtime data), same convention as everything else under
`~/coinswaps`.
"""

import sqlite3
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import external_rates

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offer_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    polled_at REAL NOT NULL,
    offer_id TEXT NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    rate REAL NOT NULL,
    min_bid_amount REAL,
    created_at INTEGER,
    expire_at INTEGER,
    is_expired INTEGER NOT NULL,
    is_own_offer INTEGER NOT NULL,
    is_revoked INTEGER NOT NULL,
    is_public INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_offer_snapshots_pair_time
    ON offer_snapshots (coin_from, coin_to, polled_at);

CREATE TABLE IF NOT EXISTS rate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    polled_at REAL NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    rate REAL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rate_snapshots_pair_time
    ON rate_snapshots (coin_from, coin_to, polled_at);

-- Independent of BasicSwap's own (currently broken) coingecko lookup above — see
-- external_rates.py (next_steps.md §2). A separate, purely additive table rather
-- than new columns on rate_snapshots, so this never touches the existing schema/data.
CREATE TABLE IF NOT EXISTS direct_rate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    polled_at REAL NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    coingecko_rate REAL,
    kraken_rate REAL,
    disagreement_pct REAL,
    coingecko_error TEXT,
    kraken_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_direct_rate_snapshots_pair_time
    ON direct_rate_snapshots (coin_from, coin_to, polled_at);

-- quoter.py's shadow-mode output (ARCHITECTURE.md's original Phase 2 definition:
-- "compute what our strategy would have quoted ... still posting nothing"). One
-- row per decision that actually changes the simulated quote (initial post,
-- reprice past the drift threshold, or expiry-driven repost) — NOT one row per
-- poll, to avoid an "unchanged" row every cycle. api_client.py never gains a
-- postOffer/revokeOffer method, so nothing here can ever touch a real offer —
-- this table only records what a live version *would* have done.
CREATE TABLE IF NOT EXISTS simulated_quote_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('ask', 'bid')),
    action TEXT NOT NULL CHECK (action IN ('post', 'reprice', 'expire_repost')),
    new_rate REAL NOT NULL,
    reference_mid REAL NOT NULL,
    previous_rate REAL,
    previous_posted_at REAL,
    drift_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_simulated_quote_events_pair_side_time
    ON simulated_quote_events (coin_from, coin_to, side, created_at);

-- live_maker.py's real counterpart to simulated_quote_events, added 2026-09-17
-- with Evan's explicit go-ahead for a live test — same append-only convention,
-- but every row here corresponds to a real BasicSwap offer_id that was actually
-- posted/revoked (offer_id and amount_from are new vs. the simulated table).
CREATE TABLE IF NOT EXISTS live_quote_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    coin_from TEXT NOT NULL,
    coin_to TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('ask', 'bid')),
    action TEXT NOT NULL CHECK (action IN ('post', 'reprice', 'expire_repost')),
    offer_id TEXT NOT NULL,
    amount_from REAL NOT NULL,
    new_rate REAL NOT NULL,
    reference_mid REAL NOT NULL,
    previous_offer_id TEXT,
    previous_rate REAL,
    previous_posted_at REAL,
    drift_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_live_quote_events_pair_side_time
    ON live_quote_events (coin_from, coin_to, side, created_at);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def insert_offer_snapshots(
    conn: sqlite3.Connection, offers: list[dict[str, Any]], polled_at: float | None = None
) -> int:
    polled_at = polled_at if polled_at is not None else time.time()
    rows = [
        (
            polled_at,
            o["offer_id"],
            o["coin_from"],
            o["coin_to"],
            float(o["amount_from"]),
            float(o["amount_to"]),
            float(o["rate"]),
            float(o["min_bid_amount"]) if o.get("min_bid_amount") is not None else None,
            o.get("created_at"),
            o.get("expire_at"),
            int(bool(o.get("is_expired"))),
            int(bool(o.get("is_own_offer"))),
            int(bool(o.get("is_revoked"))),
            int(bool(o.get("is_public"))),
        )
        for o in offers
    ]
    conn.executemany(
        """
        INSERT INTO offer_snapshots (
            polled_at, offer_id, coin_from, coin_to, amount_from, amount_to,
            rate, min_bid_amount, created_at, expire_at, is_expired,
            is_own_offer, is_revoked, is_public
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def insert_rate_snapshot(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    rate_response: list,
    polled_at: float | None = None,
) -> None:
    import json

    polled_at = polled_at if polled_at is not None else time.time()
    rate = _extract_rate(rate_response)
    conn.execute(
        "INSERT INTO rate_snapshots (polled_at, coin_from, coin_to, rate, raw_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (polled_at, coin_from, coin_to, rate, json.dumps(rate_response)),
    )
    conn.commit()


def insert_direct_rate_snapshot(
    conn: sqlite3.Connection,
    rate: "external_rates.ReferenceRate",
    polled_at: float | None = None,
) -> None:
    polled_at = polled_at if polled_at is not None else time.time()
    conn.execute(
        """
        INSERT INTO direct_rate_snapshots (
            polled_at, coin_from, coin_to, coingecko_rate, kraken_rate,
            disagreement_pct, coingecko_error, kraken_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            polled_at,
            rate.coin_from,
            rate.coin_to,
            rate.coingecko_rate,
            rate.kraken_rate,
            rate.disagreement_pct,
            rate.coingecko_error,
            rate.kraken_error,
        ),
    )
    conn.commit()


def fetch_direct_rate_snapshots(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM direct_rate_snapshots WHERE coin_from = ? AND coin_to = ?"
    params: list[Any] = [coin_from, coin_to]
    if since is not None:
        query += " AND polled_at >= ?"
        params.append(since)
    query += " ORDER BY polled_at ASC"
    return conn.execute(query, params).fetchall()


def _extract_rate(rate_response: list) -> float | None:
    """/json/rateslist returns a list with one entry per rate source. A working
    coingecko.com entry is a 6-element array whose last element is the
    coin_to-per-coin_from rate as a formatted decimal string; a failed one is a
    3-element ["coingecko.com", "error", "<message>"] (verified live 2026-09-15 —
    see basicswap.py's lookupRates, output_array branch). Returns None (raw_json is
    always kept regardless) if every source failed or the shape doesn't match.
    """
    if not isinstance(rate_response, list):
        return None
    for entry in rate_response:
        if isinstance(entry, list) and len(entry) >= 6 and entry[1] != "error":
            try:
                return float(entry[5])
            except (TypeError, ValueError):
                continue
    return None


def insert_simulated_quote_event(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    side: str,
    action: str,
    new_rate: float,
    reference_mid: float,
    previous_rate: float | None = None,
    previous_posted_at: float | None = None,
    drift_pct: float | None = None,
    created_at: float | None = None,
) -> None:
    created_at = created_at if created_at is not None else time.time()
    conn.execute(
        """
        INSERT INTO simulated_quote_events (
            created_at, coin_from, coin_to, side, action, new_rate,
            reference_mid, previous_rate, previous_posted_at, drift_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            coin_from,
            coin_to,
            side,
            action,
            new_rate,
            reference_mid,
            previous_rate,
            previous_posted_at,
            drift_pct,
        ),
    )
    conn.commit()


def fetch_latest_simulated_quote_event(
    conn: sqlite3.Connection, coin_from: str, coin_to: str, side: str
) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM simulated_quote_events WHERE coin_from = ? AND coin_to = ? "
        "AND side = ? ORDER BY created_at DESC LIMIT 1",
        (coin_from, coin_to, side),
    ).fetchone()


def fetch_simulated_quote_events(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    side: str | None = None,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM simulated_quote_events WHERE coin_from = ? AND coin_to = ?"
    params: list[Any] = [coin_from, coin_to]
    if side is not None:
        query += " AND side = ?"
        params.append(side)
    if since is not None:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at ASC"
    return conn.execute(query, params).fetchall()


def insert_live_quote_event(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    side: str,
    action: str,
    offer_id: str,
    amount_from: float,
    new_rate: float,
    reference_mid: float,
    previous_offer_id: str | None = None,
    previous_rate: float | None = None,
    previous_posted_at: float | None = None,
    drift_pct: float | None = None,
    created_at: float | None = None,
) -> None:
    created_at = created_at if created_at is not None else time.time()
    conn.execute(
        """
        INSERT INTO live_quote_events (
            created_at, coin_from, coin_to, side, action, offer_id, amount_from,
            new_rate, reference_mid, previous_offer_id, previous_rate,
            previous_posted_at, drift_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            coin_from,
            coin_to,
            side,
            action,
            offer_id,
            amount_from,
            new_rate,
            reference_mid,
            previous_offer_id,
            previous_rate,
            previous_posted_at,
            drift_pct,
        ),
    )
    conn.commit()


def fetch_latest_live_quote_event(
    conn: sqlite3.Connection, coin_from: str, coin_to: str, side: str
) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM live_quote_events WHERE coin_from = ? AND coin_to = ? "
        "AND side = ? ORDER BY created_at DESC LIMIT 1",
        (coin_from, coin_to, side),
    ).fetchone()


def fetch_live_quote_events(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    side: str | None = None,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM live_quote_events WHERE coin_from = ? AND coin_to = ?"
    params: list[Any] = [coin_from, coin_to]
    if side is not None:
        query += " AND side = ?"
        params.append(side)
    if since is not None:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at ASC"
    return conn.execute(query, params).fetchall()


def fetch_offer_snapshots(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM offer_snapshots WHERE coin_from = ? AND coin_to = ?"
    params: list[Any] = [coin_from, coin_to]
    if since is not None:
        query += " AND polled_at >= ?"
        params.append(since)
    query += " ORDER BY polled_at ASC"
    return conn.execute(query, params).fetchall()


def fetch_rate_snapshots(
    conn: sqlite3.Connection,
    coin_from: str,
    coin_to: str,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM rate_snapshots WHERE coin_from = ? AND coin_to = ?"
    params: list[Any] = [coin_from, coin_to]
    if since is not None:
        query += " AND polled_at >= ?"
        params.append(since)
    query += " ORDER BY polled_at ASC"
    return conn.execute(query, params).fetchall()

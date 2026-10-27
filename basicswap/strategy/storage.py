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

-- Opportunistic bid-scanning (next_steps.md #9, built 2026-09-20 at Evan's
-- explicit go-ahead) — bid_scanner.py bidding into OTHER makers' live
-- offers, a fundamentally different activity from live_quote_events above
-- (which only ever records OUR OWN posted offers). Kept in its own table,
-- not folded into live_quote_events, specifically so this activity's own
-- profitability can be audited independently of the ask/bid maker-offer
-- strategy (Evan's explicit requirement when authorizing this feature) —
-- joining the two tables together would conflate two different trading
-- activities into one number. reference_mid is the EXTERNAL rate at
-- decision time (external_rates.py, not anything from BasicSwap's own
-- offer book), so edge_pct measures what a bid captured against an
-- independent price source, not against our own quoting.
CREATE TABLE IF NOT EXISTS bid_scan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    offer_coin_from TEXT NOT NULL,  -- what the OFFER sells (what we're buying)
    offer_coin_to TEXT NOT NULL,    -- what the OFFER wants (what we're paying)
    offer_id TEXT NOT NULL,
    bid_id TEXT NOT NULL,
    offer_rate REAL NOT NULL,       -- offer_coin_to per offer_coin_from, taken exactly (never negotiated)
    reference_mid REAL NOT NULL,
    edge_pct REAL NOT NULL,         -- how much better than reference_mid this bid bought at
    amount_from REAL NOT NULL,      -- amount of offer_coin_from bid for
    amount_to REAL NOT NULL,        -- implied amount of offer_coin_to paid (amount_from * offer_rate)
    usd_notional REAL,
    offer_created_at INTEGER,
    offer_expire_at INTEGER,
    bid_state TEXT,                 -- last known BidStates display string from get_bid(), via reconcile_bid_outcomes()
    resolved INTEGER NOT NULL DEFAULT 0,  -- 0 = still in progress, 1 = reached a terminal state
    outcome TEXT,                   -- 'success' | 'failure' | NULL while unresolved
    resolved_at REAL
);

CREATE INDEX IF NOT EXISTS idx_bid_scan_events_pair_time
    ON bid_scan_events (offer_coin_from, offer_coin_to, created_at);
CREATE INDEX IF NOT EXISTS idx_bid_scan_events_resolved
    ON bid_scan_events (resolved);

-- Per-fill P&L ledger (market_maker/next_steps.md #3/#4): one row per bid
-- that landed on an offer live_maker.py posted, whatever its outcome.
-- edge/markout columns: signed % of amount_to vs. fair value of amount_from
-- at reference mid (at fill, +1h, +24h); gross of network fees. See
-- fill_ledger.py.
CREATE TABLE IF NOT EXISTS fills (
    bid_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL,
    venue TEXT NOT NULL,
    side TEXT NOT NULL,
    coin_from TEXT NOT NULL,        -- what we gave
    coin_to TEXT NOT NULL,          -- what we received
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    rate REAL NOT NULL,
    bid_state TEXT NOT NULL,
    bid_created_at REAL NOT NULL,
    reference_mid_at_fill REAL,     -- coin_to per coin_from
    edge_pct_at_fill REAL,
    markout_1h_pct REAL,
    markout_24h_pct REAL,
    synced_at REAL NOT NULL
);

-- Kraken XMR/BTC top of book per poll (2026-09-28, proof step): what
-- restocking XMR on Kraken would have cost at any fill time. BTC per XMR;
-- buy_cost_*_pct = average fill price for that XMR size / mid - 1, before
-- Kraken's trading fee. NULL = not enough depth in the fetched levels.
CREATE TABLE IF NOT EXISTS kraken_book_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    polled_at REAL NOT NULL,
    best_bid REAL NOT NULL,
    best_ask REAL NOT NULL,
    buy_cost_1xmr_pct REAL,
    buy_cost_5xmr_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_kraken_book_snapshots_time ON kraken_book_snapshots (polled_at);

-- Automated BTC->XMR restocks through Exolix (2026-10-21, exolix_restock.py).
-- status: created (Exolix exchange made, BTC not yet sent) -> sent -> success,
-- or failed / send_error. A row left in created or send_error halts the job.
CREATE TABLE IF NOT EXISTS exolix_swaps (
    exolix_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,
    exolix_status TEXT,
    amount_btc REAL NOT NULL,
    quoted_xmr REAL NOT NULL,
    reference_mid REAL NOT NULL,       -- BTC per XMR at create
    all_in_premium_pct REAL NOT NULL,  -- vs. reference_mid, incl. the assumed BTC network fee
    deposit_address TEXT NOT NULL,
    withdrawal_address TEXT NOT NULL,
    btc_txid TEXT,
    delivered_xmr REAL,
    note TEXT
);

-- 2026-10-21: ground-truth P&L. The fills ledger is gross of network fees, so
-- proof_report.py also scores the real wallet balances (poller.py, every cycle)
-- against a baseline plus any money Evan moves in or out (capital_flows).
CREATE TABLE IF NOT EXISTS wallet_snapshots (
    polled_at REAL NOT NULL,
    coin TEXT NOT NULL,                -- display name, e.g. "Bitcoin"
    balance REAL NOT NULL,
    unconfirmed REAL NOT NULL,
    active_swaps INTEGER NOT NULL,     -- in-flight bids + Exolix swaps; balances mid-swap undercount
    PRIMARY KEY (polled_at, coin)
);

CREATE TABLE IF NOT EXISTS capital_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    coin TEXT NOT NULL,                -- display name
    amount REAL NOT NULL,              -- + into the BasicSwap wallets, - out
    kind TEXT NOT NULL,                -- baseline | deposit | withdrawal
    note TEXT
);
"""


def insert_exolix_swap(conn: sqlite3.Connection, row: dict) -> None:
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO exolix_swaps ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    conn.commit()


def update_exolix_swap(conn: sqlite3.Connection, exolix_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE exolix_swaps SET {sets} WHERE exolix_id = ?", (*fields.values(), exolix_id))
    conn.commit()


def fetch_exolix_swaps(conn: sqlite3.Connection, since: float = 0.0) -> list[dict]:
    cur = conn.execute("SELECT * FROM exolix_swaps WHERE created_at >= ? ORDER BY created_at", (since,))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def insert_wallet_snapshot(
    conn: sqlite3.Connection, polled_at: float, balances: dict[str, tuple[float, float]], active_swaps: int
) -> None:
    """balances: {display name: (balance, unconfirmed)}."""
    conn.executemany(
        "INSERT OR REPLACE INTO wallet_snapshots VALUES (?, ?, ?, ?, ?)",
        [(polled_at, coin, bal, unc, active_swaps) for coin, (bal, unc) in balances.items()],
    )
    conn.commit()


def latest_clean_wallet_snapshot(
    conn: sqlite3.Connection, coins: tuple[str, ...], until: float | None = None
) -> tuple[float, dict[str, float]] | None:
    """(polled_at, {coin: balance + unconfirmed}) from the newest snapshot with no swap
    in flight that has every coin in `coins`, or None."""
    rows = conn.execute(
        "SELECT polled_at, coin, balance + unconfirmed FROM wallet_snapshots "
        "WHERE active_swaps = 0 AND polled_at <= ? ORDER BY polled_at DESC LIMIT 200",
        (until if until is not None else time.time(),),
    ).fetchall()
    by_time: dict[float, dict[str, float]] = {}
    for t, coin, total in rows:
        by_time.setdefault(t, {})[coin] = total
    for t in sorted(by_time, reverse=True):
        if all(c in by_time[t] for c in coins):
            return t, by_time[t]
    return None


def insert_capital_flow(
    conn: sqlite3.Connection, at: float, coin: str, amount: float, kind: str, note: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO capital_flows (at, coin, amount, kind, note) VALUES (?, ?, ?, ?, ?)",
        (at, coin, amount, kind, note),
    )
    conn.commit()


def fetch_capital_flows(conn: sqlite3.Connection, until: float | None = None) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM capital_flows WHERE at <= ? ORDER BY at, id",
        (until if until is not None else time.time(),),
    )
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


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


def insert_bid_scan_event(
    conn: sqlite3.Connection,
    offer_coin_from: str,
    offer_coin_to: str,
    offer_id: str,
    bid_id: str,
    offer_rate: float,
    reference_mid: float,
    edge_pct: float,
    amount_from: float,
    amount_to: float,
    usd_notional: float | None = None,
    offer_created_at: int | None = None,
    offer_expire_at: int | None = None,
    created_at: float | None = None,
) -> int:
    created_at = created_at if created_at is not None else time.time()
    cur = conn.execute(
        """
        INSERT INTO bid_scan_events (
            created_at, offer_coin_from, offer_coin_to, offer_id, bid_id,
            offer_rate, reference_mid, edge_pct, amount_from, amount_to,
            usd_notional, offer_created_at, offer_expire_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at, offer_coin_from, offer_coin_to, offer_id, bid_id,
            offer_rate, reference_mid, edge_pct, amount_from, amount_to,
            usd_notional, offer_created_at, offer_expire_at,
        ),
    )
    conn.commit()
    return cur.lastrowid


def fetch_bid_scan_events(
    conn: sqlite3.Connection,
    offer_coin_from: str | None = None,
    offer_coin_to: str | None = None,
    resolved: bool | None = None,
    since: float | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM bid_scan_events WHERE 1=1"
    params: list[Any] = []
    if offer_coin_from is not None:
        query += " AND offer_coin_from = ?"
        params.append(offer_coin_from)
    if offer_coin_to is not None:
        query += " AND offer_coin_to = ?"
        params.append(offer_coin_to)
    if resolved is not None:
        query += " AND resolved = ?"
        params.append(int(resolved))
    if since is not None:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at ASC"
    return conn.execute(query, params).fetchall()


def update_bid_scan_event_outcome(
    conn: sqlite3.Connection,
    bid_id: str,
    bid_state: str,
    resolved: bool,
    outcome: str | None,
    resolved_at: float | None = None,
) -> None:
    """Called by bid_scanner.reconcile_bid_outcomes() after polling
    api_client.get_bid() for this bid's real current state — always updates
    bid_state (even while unresolved, so the latest known state is visible
    without waiting for a terminal one), and only sets resolved/outcome/
    resolved_at once BidStates has actually reached a terminal value."""
    conn.execute(
        """
        UPDATE bid_scan_events
        SET bid_state = ?, resolved = ?, outcome = ?, resolved_at = ?
        WHERE bid_id = ?
        """,
        (bid_state, int(resolved), outcome, resolved_at, bid_id),
    )
    conn.commit()


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


_FILL_COLUMNS = (
    "bid_id", "offer_id", "venue", "side", "coin_from", "coin_to", "amount_from",
    "amount_to", "rate", "bid_state", "bid_created_at", "reference_mid_at_fill",
    "edge_pct_at_fill", "markout_1h_pct", "markout_24h_pct", "synced_at",
)


def upsert_fill(conn: sqlite3.Connection, **row: Any) -> None:
    """Insert or refresh one fills row. A NULL markout never overwrites an
    already-computed one (the reference data it came from may have aged out
    of a later sync's reach, but the number stays true)."""
    cols = ", ".join(_FILL_COLUMNS)
    marks = ", ".join("?" for _ in _FILL_COLUMNS)
    keep = ("reference_mid_at_fill", "edge_pct_at_fill", "markout_1h_pct", "markout_24h_pct")
    updates = ", ".join(
        f"{c} = COALESCE(excluded.{c}, fills.{c})" if c in keep else f"{c} = excluded.{c}"
        for c in _FILL_COLUMNS if c != "bid_id"
    )
    conn.execute(
        f"INSERT INTO fills ({cols}) VALUES ({marks}) ON CONFLICT(bid_id) DO UPDATE SET {updates}",
        [row[c] for c in _FILL_COLUMNS],
    )
    conn.commit()


def fetch_fills(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM fills ORDER BY bid_created_at ASC").fetchall()


def insert_kraken_book_snapshot(
    conn: sqlite3.Connection, book: "external_rates.KrakenBook", polled_at: float | None = None
) -> None:
    conn.execute(
        "INSERT INTO kraken_book_snapshots (polled_at, best_bid, best_ask, buy_cost_1xmr_pct, "
        "buy_cost_5xmr_pct) VALUES (?, ?, ?, ?, ?)",
        (
            polled_at if polled_at is not None else time.time(),
            book.best_bid, book.best_ask, book.buy_cost_pct.get(1.0), book.buy_cost_pct.get(5.0),
        ),
    )
    conn.commit()


def nearest_kraken_book_snapshot(
    conn: sqlite3.Connection, t: float, max_gap_seconds: float = 20 * 60
) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM kraken_book_snapshots WHERE polled_at BETWEEN ? AND ? "
        "ORDER BY ABS(polled_at - ?) LIMIT 1",
        (t - max_gap_seconds, t + max_gap_seconds, t),
    ).fetchone()

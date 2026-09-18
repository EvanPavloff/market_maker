# Market Maker — Next Steps

Framework-level build queue. Ordered by how directly each item closes a gap
identified in `ARCHITECTURE.md` §§6–9, not by how interesting it is. Items
already tracked in `basicswap/next_steps.md` at the venue level are referenced,
not duplicated, unless this level changes their priority.

**Reviewed 2026-09-17, later the same day** (repo now pushed to
`github.com/EvanPavloff/market_maker`, live loops re-verified healthy — see
`project_status.md`): priorities below are unchanged from this morning's
version, with one addition (#9) found during that re-verification.

## 1. Volatility-based kill-switch `[NOT STARTED]`

**Gap**: `ARCHITECTURE.md` §6 — the PDF's "pause quoting if reference volatility
spikes" control doesn't exist. `live_maker.py` reprices on drift after the fact
(every cycle, if drift > `reprice_threshold_pct`) but never *stops* quoting
during a fast move — it just chases the new price every 5 minutes, which is
exactly the stale-quote-arbitrage exposure the PDF's kill-switch exists to
prevent.

**Why this is first**: it's the cheapest control to add (one new check in
`decide_and_act()`, reusing the reference-rate history `external_rates.py`
already pulls) and it's the one piece of §6's risk-control table with zero
built equivalent, unlike UTXO hygiene (not applicable at this scale) or
passive-first rebalancing (trivially true with one venue).

**Concrete shape**: compute rolling N-minute volatility off
`external_rates.get_reference_rate()`'s own polling cadence (already fetched
every cycle for the mid price — no new API surface needed); if it exceeds a
configurable threshold, skip posting/reposting for that cycle (log why) rather
than revoking-and-reposting into a market that's still moving. Needs a
threshold picked from real data — the observation window's poller history
(`basicswap/strategy/poller.py`'s logged mid-prices) already has enough samples
to compute a realistic baseline volatility distribution before picking a
number, so this doesn't need to start from a guess.

## 2. Replace the hand-picked `--reserve-usd 210` with a real MVB calculation `[NOT STARTED, blocked on data]`

**Gap**: `ARCHITECTURE.md` §8. The PDF's `MVB = (D_max(T_fallback) * S_fill) +
Safety_Margin(P99_delay)` formula needs a `T_fallback` (worst-case fallback
failover window) that presupposes a fallback route exists. One doesn't (§5 of
`ARCHITECTURE.md`). **Do not build this yet** — faking `T_fallback` off
single-venue data would produce a number that looks rigorous but means nothing.

**What actually unblocks it**: either (a) a second venue/fallback route gets
scoped and built (see #4), giving a real failover window to measure, or (b) a
decision that "MVB" for a single-venue system should instead be redefined as
something measurable today — e.g., sized off this venue's own P99 time-to-fill
rather than a fallback-failover window. That's a real design choice, not a
data-collection task — flag for Evan's input once the observation window
(`basicswap/next_steps.md` §3, still short of its 1–2 week bar) has enough
fills to make either option meaningful.

## 3. Per-fill P&L ledger `[NOT STARTED]`

**Gap**: `ARCHITECTURE.md` §9 item 1. `storage.py`'s `live_quote_events` table
logs every post/revoke decision but nothing distinguishes "this offer expired
untouched" from "this offer was actually filled" (a known, already-flagged gap
— `basicswap/project_status.md`'s "Not done / real open items" under the first
live offer entry) and there is no row anywhere that says "this fill, this
realized spread, this fee, this net edge."

**Why this matters more at the framework level than the venue level**: the
moment a second venue exists, two independent per-venue logs stop being
sufficient — profitability has to be evaluated against the *global* inventory
position (§4 of `ARCHITECTURE.md`), which needs one consolidated ledger schema
now, even while there's only one venue writing to it. Building the schema
single-venue and adding rows as they occur is cheap; retrofitting a
multi-venue-shaped ledger after venue #2 ships is not.

**Concrete shape**: extend `storage.py` with a `fills` table (offer id, venue,
pair, side, amount, rate, realized spread vs. reference mid at fill time,
network fee, lock duration, net edge) populated once real fill-detection (item
below) exists. Blocked on:

## 4. Real fill-vs-expiry detection `[BLOCKED on Monero/BasicSwap read, carried from basicswap/project_status.md]`

Already flagged at the venue level: `live_maker.py` logs a loud warning either
way when a tracked offer disappears (filled or simply expired) because it
doesn't yet read `/json/bids` or `basicswap.log` to tell the two apart. This
blocks #3 directly — there's no fill to log a P&L row for until this
distinguishes a fill from an expiry. Promoting this to the framework level
because #3 now depends on it; still lives in `basicswap/strategy/live_maker.py`
as the actual code change.

## 5. Tax lot tracking `[NOT STARTED, carried from basicswap/next_steps.md §6]`

Already flagged at the venue level (light research done 2026-09-16: each swap
is very likely a taxable disposal event, no record-keeping mechanism built).
Restating here per `ARCHITECTURE.md` §9 item 3: this gets harder, not easier,
the longer it's deferred past venue #2. No urgency change from the venue-level
doc — still gated behind #3/#4 existing first (a tax ledger needs the same
per-fill data the P&L ledger needs), just noting the dependency runs through
this level now.

## 6. Venue #2 scoping — NOT started, and deliberately not prioritized yet

`ARCHITECTURE.md` §7: Eigen ASB, Haveno, Bisq, and a Trocador-based
replenishment router are all named in the source PDFs as CORE/REPLENISHMENT but
none has had even light research done. **Do not scope a second venue before**:

- `basicswap/next_steps.md`'s observation window clears its 1–2 week bar (still
  short as of 2026-09-17), and
- more than one real fill exists to move the exposure-window/fill-duration
  measurement past n=1, and
- items #1 and #3 above exist, since a second venue makes both harder to
  retrofit later (per §4/§9's inventory-controller and ledger arguments).

The PDFs' own phased rollout (Phase 2: venue expansion once Phase 1 shows
positive net realized edge) already encodes this ordering — this item exists
mainly to make explicit that the framework isn't waiting on a decision, it's
waiting on the single-venue edge finishing its own proof.

## 7. Inventory controller — NOT started, correctly deferred

`ARCHITECTURE.md` §4: building a global-ledger abstraction with one venue
feeding it is solving a coordination problem that doesn't exist yet. Trigger:
the day venue #2 (item #6) is actually scoped, not before. Listed here only so
it isn't silently forgotten once #6 does happen.

## 8. Testnet/shadow-engine backfill — open question, not a commitment

`ARCHITECTURE.md` §6's last row: this project validated mechanics via tiny real
trades instead of the PDF's testnet/stagenet + ghost-quote approach. That's
already produced real data (the 42m30s exposure measurement) that a testnet run
never could. Whether it's worth *also* standing up Signet/Testnet4/Stagenet
daemons for lower-stakes regression testing before scaling real capital further
is Evan's call, not a default next step — raise it explicitly if/when capital
sizing is about to increase materially (e.g., before any move past the current
~0.008 BTC / reserve-based XMR sizing).

## 9. Duplicate-instance guard for `run_live_maker.sh` `[NOT STARTED, real gap found 2026-09-17]`

**Gap**, found during today's restructure, not from the source PDFs: earlier
same-day restarts left 5 real `live_maker --live` processes running instead of
2 (orphaned duplicates — a wrapper shell got killed but its Python child kept
running independently, `PPID=1`). No collision actually occurred (verified via
`/json/sentoffers` and the logs before cleanup), but nothing currently stops
it from happening again — `AmbiguousLiveOffersError` only guards against
BasicSwap's own state (a second real offer), not against a second local
process racing the first. Also logged in the outer workspace's `TASKS.md`
(2026-09-17 entry).

**Concrete shape**: a PID-file (`flock` or a simple `<side>.pid` file checked
and written at startup, matching this workspace's other single-instance
scripts) in `run_live_maker.sh`, refusing to start a second instance for the
same `--side`/pair if one's PID file already points to a live process.
Cheap, mechanical, no strategy-logic risk — could be picked up independently
of #1-#8 whenever convenient, doesn't need to wait on more fill data the way
most of this list does.

**Also worth noting for future debugging, not a to-do**: while re-verifying
health today, `tail` on `basicswap_live_maker_bid.log` looked stale (last
visible line ~3 hours old) purely because the since-killed duplicate's
buffered output flushed to disk on termination, landing physically after the
live process's own more recent lines. `grep`ing for the live process's actual
log-message pattern (not just `tail`) resolved it in under a minute — worth
reaching for that first next time a `nohup`-redirected log looks stale on one
of these loops, rather than assuming the process itself has stopped.

## Explicitly not on this list

- **UTXO hygiene** (`ARCHITECTURE.md` §6) — not applicable at current capital
  scale (single fixed-size offer, not fragmenting a larger balance). Revisit if
  and when position sizing grows enough that a single swap could lock up most
  of available BTC.
- **CEX perpetual hedge** — the source PDF itself drops this (§6 of the v3.1
  doc's own "Considered and Dropped" table) for the same reason it doesn't fit
  here: custody/funding-rate/liquidation risk not worth it for small working
  buffers. No reason to revisit unless capital scale changes that calculus.

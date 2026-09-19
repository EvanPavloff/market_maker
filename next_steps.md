# Market Maker — Next Steps

Framework-level build queue. Ordered by how directly each item closes a gap
identified in `ARCHITECTURE.md` §§6–9, not by how interesting it is. Items
already tracked in `basicswap/next_steps.md` at the venue level are referenced,
not duplicated, unless this level changes their priority.

## Status at a glance (as of 2026-09-19 — verify before trusting, this is a snapshot)

| # | Item | Status |
|---|------|--------|
| 1 | Volatility-based kill-switch | **DONE, deployed** |
| 2 | Real MVB sizing (replace `--reserve-usd 210`) | Blocked — no fallback route to measure a real `T_fallback` off |
| 3 | Per-fill P&L ledger | Blocked on #4 |
| 4 | Real fill-vs-expiry detection | Blocked — n=2 real fills now, not yet enough to start; not gated on a fixed count, a judgment call |
| 5 | Tax lot tracking | Blocked on #3 |
| 6 | Venue #2 scoping (capital) | Deliberately not started — needs explicit human sign-off first |
| 7 | Inventory controller | Deliberately not started — trigger is #6 actually happening |
| 8 | Testnet/shadow-engine backfill | Open question, not a commitment — raise before any capital-size increase |
| 9 | Duplicate-instance PID guard | **DONE, deployed** |
| 10 | Source-disagreement gate | **DONE, deployed** (built same-day in response to a real, quantified loss — see its entry) |
| 11 | Mispriced-offer opportunity scanner (cross-venue) | **Designed only, deliberately NOT built** — Evan's explicit instruction |
| 12 | Bisq read-only observation poller (venue #2, observation-only) | **DONE, verified live** — no capital, no write path |
| 13 | Eigen ASB read-only discovery (venue #3, observation-only) | **Wallet-free path found + built; blocked on a WebSocket transport gap** — not yet returning real quotes |

**The four `DONE` items (#1, #9, #10, #12) are all live/verified right now**
(#1/#9/#10 confirmed via both live BasicSwap processes' startup logs; #12
confirmed via a real poll against Bisq's live API — see its own entry below).
**#11 is fully speced but
must not be started without checking with Evan first** — it's a new,
higher-risk capability (acting on other participants' public data), not
just a documentation gap to fill in.

**The #10-incident follow-ons are now resolved** (checked live 2026-09-19,
not just re-read from the old note): the ask wallet holds 0.00808069 BTC
(refunded — above the 0.008 the offer quotes), and the stale
136.17-XMR/BTC-priced offer now shows `is_revoked: true` on
`/json/sentoffers`. Neither this session nor any documented one revoked it
or refunded the wallet, so it happened via some other path (Evan directly,
or an unwritten-up session) — worth a quick confirmation with him, not
reopening the item over.

**New as of 2026-09-19, replacing the above as the current pending item**:
the bid-side loop crashed again on a *different* bug (`KeyError: 'balance'`
in `api_client.get_wallet_balance`, ~19h down as of the fix) — root-caused
and fixed in code, plus `--half-spread-pct` bumped 0.0066 → 0.011 (Evan's
call, in response to the ~0.3-0.4% adverse-noise loss on the bid side's one
real fill — see `basicswap/project_status.md`). 98/98 tests passing.
**Restart is not yet deployed** — the sandbox blocked killing/restarting the
live processes directly; a purpose-built script,
`basicswap/restart_live_maker.sh`, is ready for Evan to run himself. **First
action for a fresh session: check whether that restart has happened**
(`ps aux | grep live_maker` — expect exactly 2 processes; check both
startup log lines for `half_spread_pct=0.0110`, not `0.0066`, to confirm the
new build is actually running, not just that a process exists) before
assuming anything below is safe to build on.

Every other item (#2–#8) is genuinely blocked per its own entry's specific
gate, not just deprioritized — read that entry before starting, don't infer
from this table alone. Full incident histories, calibration data, and
build rationale for the `DONE` items are preserved in each item's own
section below and in `project_status.md`'s dated entries — this table is a
map, not a replacement for reading the item you're about to touch.

## 1. Volatility-based kill-switch `[DONE 2026-09-18]`

**Gap**: `ARCHITECTURE.md` §6 — the PDF's "pause quoting if reference volatility
spikes" control doesn't exist. `live_maker.py` reprices on drift after the fact
(every cycle, if drift > `reprice_threshold_pct`) but never *stops* quoting
during a fast move — it just chases the new price every 5 minutes, which is
exactly the stale-quote-arbitrage exposure the PDF's kill-switch exists to
prevent.

**Built**: `basicswap/strategy/volatility.py`'s new `VolatilityMonitor` — an
in-memory rolling window of `(timestamp, reference_mid)` samples, fed by the
same `external_rates.get_reference_rate()` call `run_cycle` already made every
cycle (no new API surface). `run_cycle` now adds each cycle's mid to the
monitor and, if the window's `(max-min)/mean` exceeds
`cfg.kill_switch_volatility_pct`, skips `decide_and_act` entirely for that
cycle (logs why; any existing live offer is left untouched — same "never
destroy a working offer" posture as the existing insufficient-balance path).
Threshold is real-data-calibrated, not guessed: computed 2026-09-18 against
512 real `direct_rate_snapshots` samples (~42.6h of `basicswap/strategy/
poller.py`'s own observation-window history for Monero/Bitcoin) — a 15-minute
rolling range showed p50=0.22%, p90=0.49%, p95=0.63%, p99=0.84%, max=1.10%;
the shipped default (0.85%, 15-minute window) sits just above that p99, so the
kill-switch only fires on moves more extreme than ~99% of what this pair has
actually done, not on the routine noise `reprice_threshold_pct` (0.5%) already
handles. Both values are CLI flags (`--kill-switch-window-minutes`,
`--kill-switch-volatility-pct`) if the calibration needs revisiting later. 14
new tests (`test_volatility.py` + `test_live_maker.py`'s
`RunCycleKillSwitchTests`), full suite green (90/90). **Deployed same day** —
both live `run_live_maker.sh --loop` processes restarted and verified running
the new code (startup log shows the kill-switch settings; the ask side's one
live offer survived the restart untouched) — see `project_status.md`/
`basicswap/project_status.md`.

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

## 4. Real fill-vs-expiry detection `[STILL BLOCKED, n=2 now — see 2026-09-18 update]`

Already flagged at the venue level: `live_maker.py` logs a loud warning either
way when a tracked offer disappears (filled or simply expired) because it
doesn't yet read `/json/bids` or `basicswap.log` to tell the two apart. This
blocks #3 directly — there's no fill to log a P&L row for until this
distinguishes a fill from an expiry. Promoting this to the framework level
because #3 now depends on it; still lives in `basicswap/strategy/live_maker.py`
as the actual code change.

**2026-09-18 update**: a real counterparty bid landed on the live ask offer
at 12:33 (bid `000000006aad6738cffa3f91108af3639330b9ad29e11e0fb543d7c6`) and
**completed normally** (confirmed `Completed` state) — the project's second
real fill ever, and the first fill of the *automated* offer specifically
(2026-09-17's was Evan manually bidding into someone else's offer to
exercise the mechanism). That's n=2 now, not n=1 — worth revisiting whether
that's "enough" to start this item, though the more urgent finding from this
same fill isn't the count, it's that **the offer that got filled was
mispriced ~6.7% below fair value** — see #10 below for the full incident and
the fix. This item (fill-vs-expiry detection) is still genuinely useful and
still not built, but #10's fix is the higher-priority pickup from this same
event.

## 5. Tax lot tracking `[NOT STARTED, carried from basicswap/next_steps.md §6]`

Already flagged at the venue level (light research done 2026-09-16: each swap
is very likely a taxable disposal event, no record-keeping mechanism built).
Restating here per `ARCHITECTURE.md` §9 item 3: this gets harder, not easier,
the longer it's deferred past venue #2. No urgency change from the venue-level
doc — still gated behind #3/#4 existing first (a tax ledger needs the same
per-fill data the P&L ledger needs), just noting the dependency runs through
this level now.

## 6. Venue #2 scoping (live capital) — NOT started, and deliberately not prioritized yet

**Scope note added 2026-09-18, after Evan pushed back on this gate being read
too broadly**: everything below is about putting *capital* on a second venue
(a live offer, a funded wallet, the inventory-controller retrofit risk). It
was never meant to also gate *read-only observation* — that has no capital,
no wallet, and doesn't touch the inventory-controller/ledger retrofit
argument, so it doesn't need any of the conditions below. See #12: Bisq's
read-only observation poller is built and live today, independent of this
gate, precisely because "how can we observe anything until we build [some
observation]" turned out to be true for the *poller*, just not for *going
live with capital* — those are two different asks this item used to conflate.

`ARCHITECTURE.md` §7: Eigen ASB, Haveno, Bisq, and a Trocador-based
replenishment router are all named in the source PDFs as CORE/REPLENISHMENT.
Bisq now has a real observation poller (#12); Eigen ASB and Haveno remain
unbuilt in any form. **Do not put real capital on a second venue before**:

- `basicswap/next_steps.md`'s observation window clears its 1–2 week bar (still
  short as of 2026-09-18), and
- more than one real fill exists to move the exposure-window/fill-duration
  measurement past n=1 (now at n=2, still thin), and
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

## 9. Duplicate-instance guard for `run_live_maker.sh` `[DONE 2026-09-18]`

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

**Built 2026-09-18**: went one step past "just add a PID file" once the actual
2026-09-17 failure mode was reconsidered — a plain PID file keyed on the
wrapper shell's own PID would *not* have caught that incident, since the bug
was specifically that the wrapper shell (one PID) died while its `python3`
child (a different PID) kept running orphaned. A lock tied to the shell's PID
would go stale (shell PID dead) while the very process it was supposed to be
guarding against was still alive under an untracked PID. Fixed by changing
`run_live_maker.sh`'s last line from `python3 -m strategy.live_maker ...` to
`exec python3 -m strategy.live_maker ...` — `exec` replaces the shell's
process image with python3 in place, keeping the same PID, so there is only
ever one process for the lifetime of the run (no wrapper/child pair left to
split apart). The lock file itself (`$SWAP_DATADIR/locks/live_maker_<coin
-from>-<coin-to>-<side>.pid`, one per side/pair so ask and bid don't collide
with each other) is written with that same PID before `exec`, and a later
start refuses to proceed only if the recorded PID is both alive (`kill -0`)
and still actually running `strategy.live_maker` (`ps -o command=` check, so
an unrelated process that happens to reuse a recycled PID can't block a
legitimate restart). Verified without touching the live processes: read-only
confirmed the block path fires correctly against the real running ask-side
PID (76467), plus isolated shell tests of the arg-parsing (coin-from/coin-to/
side extraction, both `--flag value` and `--flag=value` forms) and the
stale-lock-passthrough path. `TASKS.md`'s matching entry marked resolved.

**Deployed same day, on Evan's go-ahead**: both real live loops restarted
onto the new script (old PIDs 76467 ask/76468 bid → new PIDs 1894/1895).
`ps aux` confirmed exactly 2 processes post-restart with **no separate
wrapper shell** (proof `exec` actually collapsed the two-PID pattern), lock
files at `~/coinswaps/locks/live_maker_{btc-xmr-ask,xmr-btc-bid}.pid` each
hold their process's real PID, and the ask side's live offer survived the
restart. Full verification detail and one unrelated benign observation
(a pre-existing reserve-floor edge case surfacing as a raw API error for one
cycle, not caused by this change) in `project_status.md`'s matching entries.

## 10. Source-disagreement gate for the reference rate `[DONE 2026-09-18, real incident]`

**Gap, found via a real loss, not a design review**: on 2026-09-18 the live ask
offer reposted at 12:24:49 priced 0.008 BTC at 136.1695 XMR/BTC — about 6.7%
below the ~145 XMR/BTC both CoinGecko and Kraken were independently showing
within a minute of that same post (confirmed via `basicswap/strategy/
poller.py`'s own concurrent, independent readings, which stayed in a tight
144.9–145.6 band through the whole window with no comparable dip). A real
counterparty bid into it and the swap completed — real, realized value lost,
estimated ~6.7% of the trade (~$45–50 at the time). The volatility kill-switch
(#1) didn't catch it: that control only reacts to a bad reading's *trailing
effect* on a rolling window, not to the reading itself, so it fired on the
cycles *after* this one (elevated volatility from the bad point still sitting
in the window) rather than blocking the bad post itself.

**Built**: `external_rates.get_reference_rate()` already computed an
independent Kraken cross-check and a `disagreement_pct` between it and
CoinGecko on every call, for every pair with Kraken coverage — this was
simply never read before using `reference_mid`. `live_maker.run_cycle` now
checks `rate.disagreement_pct` immediately after fetching the rate, before
it's fed into anything else: if it's available and exceeds
`cfg.max_source_disagreement_pct` (new CLI flag
`--max-source-disagreement-pct`, default 1.5%), the cycle is skipped
entirely — existing live offer left untouched, same posture as every other
guard here — and, importantly, **the bad reading is not added to the
volatility monitor either**, so it can't poison later cycles' kill-switch
checks the way the real incident's bad point did.

**Threshold calibration, from real data**: `direct_rate_snapshots` already
had a `disagreement_pct` column (poller.py has been computing this every
cycle since 2026-09-16, just never acting on it) — 559 real samples across
~46.6h: p50=0.18%, p90=0.43%, p95=0.54%, p99=0.96%, max=1.45%. Same
methodology as #1's kill-switch: picked just above the observed max (1.5%),
so it only fires on disagreement more extreme than anything CoinGecko/Kraken
have shown on this pair in practice, not on their normal cross-source noise.
The real incident's implied disagreement (~6.2%, using the closest
independent readings) would have tripped this by a wide margin.

**When there's no Kraken coverage** (most BasicSwap-supported coins aren't on
Kraken — `external_rates._KRAKEN_PAIRS` only has xmr/btc and ltc/btc today),
`disagreement_pct` is `None` and this check is a deliberate no-op — `run_cycle`
proceeds on CoinGecko alone exactly as before, rather than refusing to quote
pairs that simply have no independent source to cross-check against.

**Tested**: 5 new tests in `RunCycleSourceDisagreementTests`
(`strategy/tests/test_live_maker.py`) — the real-incident shape (large
disagreement skips the cycle), confirms the skipped reading doesn't reach the
volatility monitor, small/normal disagreement doesn't trigger, no-Kraken-
coverage proceeds normally, and an existing live offer survives untouched.

**Also found and fixed the same session, not originally part of this item**:
while checking on the live processes to plan this deploy, the bid-side loop
had crashed on an uncaught `TimeoutError` from `get_wallet_balance` sometime
after 13:04:52 — a bare socket timeout during `resp.read()` (headers arrived,
body didn't in time) that `api_client.py`'s `_request` only caught for
`urllib.error.URLError`, not `TimeoutError` itself, so it propagated past
`api_client.py`'s own `BasicSwapAPIError` wrapping entirely. Fixed at both
layers: `api_client._request` now catches `TimeoutError` too, and
`live_maker._resolve_amount_from`'s wallet-balance call — the one path that
sat outside `run_cycle`'s existing `decide_and_act` try/except — now has its
own try/except matching the pattern already used one line above it for
`get_usd_price` failures. 3 more new tests (1 in `test_api_client.py`, 2 in
`test_live_maker.py`). **Full suite: 97/97 passing (was 90 at the start of
this item).**

**Deployed 2026-09-18, on Evan's go-ahead**: both live loops restarted (old
PIDs 33177 ask/33178 bid onto the code with both fixes — the process before
this restart was PID 1894 ask only, since the bid side was down from the
crash). Verified: exactly 2 processes, no orphaned wrapper (the #9 guard
still working), both startup logs show
`max_source_disagreement_pct=0.0150`, and the bid side immediately posted a
fresh offer (1.0926 XMR, funded by the XMR received from the earlier fill) —
proof the crash fix works, not just that the process didn't immediately die
again. The ask side correctly still refuses to post/revoke (wallet only has
0.00057685 of the 0.008 BTC the offer quotes) — expected, not a bug, but see
`TASKS.md`'s 2026-09-18 entry for two real follow-on items this surfaced
that need a human decision: the ask wallet needs refunding (or
`--amount-from` lowered) to resume quoting, and the stale, already-filled,
still-136.17-priced offer is **still listed as active** on BasicSwap's own
book (`live_maker.py`'s "never revoke what I can't afford to replace" logic
wasn't written with "permanently unfundable" in mind) — not fixed, flagged.

## 11. Mispriced-offer opportunity scanner — cross-venue, design only, NOT STARTED

**The idea, from Evan directly (2026-09-18)**: item #10 defends *our* offers
against getting mispriced by a bad reference-rate reading. The same
underlying event — a real, current participant on a real order book quoting
meaningfully away from fair value — is also a real opportunity if it happens
to someone *else*. If our own automated pricing can glitch and hand away
~6.7% of a trade's value, other makers on the same venues can and likely do
make the same kind of mistake (bad price feed, stale offer left up during a
fast move, a human fat-fingering a manual quote). A venue-agnostic layer that
watches each connected platform's public order book for offers priced
meaningfully off fair value — and flags them for us to potentially take — is
a legitimate, ordinary maker/taker-market opportunity, not something
ethically different from what happened to our own offer today.

**Why this belongs at the framework level, not inside `basicswap/`**: the
whole point is "for each platform we're using," per Evan's framing — this
needs to work the same way once venue #2 exists (`ARCHITECTURE.md` §7:
Eigen ASB, Haveno, Bisq, Trocador), even though today there's exactly one
venue to scan. Building the interface venue-agnostic from day one, even
with only one real implementation behind it, avoids the exact
retrofit-cost problem `next_steps.md` #6/#7 already flag for the inventory
controller — except this piece is lower-risk to build early since it's
read-only/detection-only, not the actual cross-venue capital-allocation
logic #7 is deliberately deferred on.

**How I'd build this, when it's time** (not started, no code — this is the
design to pick up):

1. **A venue-agnostic offer-book reader interface.** Something like
   `OfferBookReader.list_public_offers(coin_from, coin_to) ->
   list[NormalizedOffer]` (`NormalizedOffer`: venue, offer_id, coin_from,
   coin_to, amount_from, amount_to, implied_rate, expire_at,
   min_bid_amount, is_own_offer). BasicSwap's implementation is nearly free
   — `strategy/poller.py` already pulls the full `/json/offers` book every
   cycle for spread/depth analysis; this just means normalizing that data
   into the shared shape instead of (or alongside) its current
   BasicSwap-specific handling. A second venue later just adds a second
   `OfferBookReader` implementation behind the same interface.

2. **Reuse #10's trust gate, don't reinvent it.** Before judging anything
   as "mispriced," get `external_rates.get_reference_rate()` and apply the
   *exact same* `max_source_disagreement_pct` check #10 just built — a
   scanner acting on a bad reference reading has the identical failure mode
   #10 exists to prevent, just pointed outward instead of inward (it could
   flag a perfectly ordinary counterparty offer as a great deal, or worse,
   actually act on one, because *our own* reference rate was the thing that
   was wrong). This is the single most important design constraint here:
   don't let today's bug become tomorrow's false-positive-driven bad trade.

3. **A real, calibrated "worth acting on" threshold — wider than our own
   quoting spread.** Median observed BasicSwap spread is ~2.06%
   (`basicswap/next_steps.md` §3, 268+ polls). A "mispricing" worth
   flagging needs to clear that ordinary market noise by a real margin —
   something in the 3-5% range as a starting guess, but this should get the
   same real-data treatment #1 and #10 got: once this scanner exists and
   logs candidate mispricings for a while, look at the actual distribution
   of how far real counterparty offers sit from fair value and calibrate
   off that, the same way the kill-switch and disagreement-gate thresholds
   were, rather than shipping a guessed number permanently.

4. **Direction-aware, per side.** A BTC-for-XMR ask priced *below* fair
   value is a deal for whoever bids it (cheap BTC); one priced *above* fair
   value is not. Same asymmetry `quoter.py`'s `half_spread_rate` already
   encodes for our own quoting — reuse that logic's shape rather than
   rederiving it.

5. **Viability filtering before ever surfacing something as "actionable."**
   `expire_at` (don't flag something about to disappear), `min_bid_amount`
   (does a realistic bid size clear it), and the same lock-window
   price-exposure math `basicswap/strategy/economics.py` already has for
   judging whether *our own* offers are worth the exposure — a
   great-looking rate that takes 24 hours to settle carries real price risk
   during that lock, exactly the risk #1's kill-switch and this project's
   whole go/no-go analysis are built around for our own quoting. The same
   math applies to a "taken" opportunity, not just a "made" one.

6. **Detection/logging only for the first version — no auto-bid.** This is
   a materially different, higher-risk capability than passive
   two-sided quoting: it's an active, directional trading decision made off
   public data from a counterparty whose motives/reliability aren't known
   (a stale offer that won't actually honor, or worse, an offer deliberately
   left mispriced as bait). Matches this project's existing phased pattern
   everywhere else (BasicSwap's own Phase 1→2→3, the kill-switch itself
   built and tested before deployment, #10 above). A first version should
   log candidates (maybe a new `flagged_opportunities` table, mirroring
   `storage.py`'s existing event-log tables) for Evan to review by hand;
   actually bidding into someone else's offer also needs a real, new
   BasicSwap API write path (`api_client.py` currently only has
   `post_offer`/`revoke_offer`/`get_wallet_balance` — accepting/bidding into
   an *existing* offer is a different endpoint, not wired up at all today)
   — building that write path is its own step, gated on Evan's sign-off
   before it's ever live, same as every other real-money capability here.

**Not started. No code, no schema, no API wiring.** Logged here per Evan's
explicit instruction to record the idea and the build approach, not to build
it.

## 12. Bisq read-only observation poller `[DONE 2026-09-18]`

**Why this exists**: Evan pushed back on #6's gate after this doc reported
"venue #2 not close" — the fair objection was "how can we observe anything
until we build [it]." That's true for going live with capital (the actual
subject of #6's gate), but turned out to be false for read-only observation
on at least one of the three CORE/PILOT candidates. Checked all three before
writing any code:

- **Bisq**: `markets.bisq.network` (the `bisq.markets` frontend's backend) is a
  live, public, **keyless, hosted REST API** — `GET /api/offers?market=xmr_btc`
  returns real current buy/sell offers, no node/daemon/wallet needed at all.
  Confirmed live 2026-09-18.
- **Eigen ASB**: the `swap` CLI's `list-sellers` subcommand discovers ASB
  maker quotes over libp2p rendezvous; its documented flags
  (`--rendezvous-point`, `--tor-socks5-port`) don't include a wallet-dir,
  suggesting no funded wallet is needed just to list sellers — but it still
  needs the compiled binary + Tor. Lighter than expected, not yet built.
- **Haveno**: no hosted public read endpoint exists anywhere — the gRPC
  `getOffers()` call is only served by your own running Haveno
  daemon/AppImage (a remote Monero node can stand in for a local one, but the
  Haveno application itself still has to run). Heaviest of the three, not
  built.

So only Bisq was actually a "zero build cost" claim — built that one now
rather than waiting on the other two.

**Built**: `venues/` — new framework-level package, sibling to `basicswap/`,
holding the venue-agnostic layer #11's design already called for:

- `venues/offer_book.py` — `NormalizedOffer` (venue, offer_id, coin_from,
  coin_to, amount_from, amount_to, implied_rate, expire_at, min_bid_amount,
  is_own_offer) and an `OfferBookReader` protocol
  (`list_public_offers(coin_from, coin_to)`), exactly the shape #11's design
  section proposed — built now with one real implementation behind it instead
  of speced-only, since a second venue's own observation poller needed it
  regardless of whether the cross-venue scanner (#11) ever gets built.
- `venues/bisq/client.py` + `reader.py` — stdlib-only HTTP client (matches
  `basicswap/strategy/external_rates.py`'s convention, no new pip dependency)
  plus the SELL/BUY → coin_from/coin_to normalization (Bisq's `amount` is
  always base-currency units, `volume` always quote, `price` always
  quote-per-base, regardless of offer direction — a BUY offer is a maker
  selling quote for base, so it maps to the *inverted* direction, `min_amount`
  converted to the returned offer's own `coin_from` units via `price`).
- `venues/storage.py` — a new `venue_offer_snapshots` SQLite table
  (venue-tagged, append-only, same convention as `basicswap/strategy/
  storage.py`'s `offer_snapshots`), its own DB file
  (`~/coinswaps/venue_observations.db`, separate from BasicSwap's own
  `basicswap_observations.db` so a schema change on one never risks the
  other).
- `venues/poller.py` + `run_poller.sh` — registry-based (`_READERS: dict[str,
  type[OfferBookReader]]`), so Eigen ASB/Haveno become a second/third
  dict entry, not a rewrite; polls both directions per configured pair, one
  venue/pair failing doesn't block the others.

**A real bug caught by testing against the live endpoint, not the docs**:
the Bisq Markets API's own doc excerpt (and a first WebFetch summary of it)
implied a flat `{"buys": [...], "sells": [...]}` response. The real live
endpoint actually nests one level deeper — `{"xmr_btc": {"buys": [...],
"sells": [...]}}`, keyed by the requested market. Caught by running the real
client against the real URL before trusting the summarized "verbatim" sample;
`client.py` now unwraps that key defensively (falls through unchanged if a
future response shape drops the nesting).

**Verified live, not just unit-tested**: 15/15 unit tests pass (mocked HTTP),
plus a real end-to-end run — `python3 -m venues.poller` against the real API
polled 110 real `xmr->btc` sell offers (rate range 0.00696–0.00861 BTC/XMR)
and 43 real `btc->xmr` buy offers (rate range 144.3–193.0 XMR/BTC) into a real
SQLite file the same session.

**Scheduled 2026-09-19**: `venues/com.market_maker.venues-poller.plist`, a
launchd agent (`StartInterval=300`, matching `basicswap/strategy/poller.py`'s
own default cadence) calling `~/coinswaps/venv/bin/python3 -m venues.poller`
directly — not through `run_poller.sh`'s bash wrapper, since launchd-spawned
bash has previously hit a real `getcwd: Operation not permitted` error
reading under `~/Desktop` on this machine (see `watch_value_tracker`'s and
`world_tracker`'s daily plists). Installed and verified: `launchctl load` +
an explicit `launchctl start` both completed cleanly (exit 0), writing two
independent real batches of offers (128 sell / 34 buy, then a second poll)
into `~/coinswaps/venue_observations.db` with no lock conflict between the
launchd-triggered run and a concurrent manual run. Continuous history is now
accumulating toward feeding #11's threshold calibration whenever that gets
built.

**Deliberately not done yet, and not implied by this**:
- **No cross-check against `basicswap/strategy/external_rates.py`'s reference
  rate yet** — Bisq's own implied rate isn't compared against CoinGecko/
  Kraken the way BasicSwap's `direct_rate_snapshots` does. Worth adding once
  there's a second live venue's worth of data to actually compare, not before.
- **No write path, no Bisq identity, no capital** — this is exactly and only
  the read-only piece #6's capital gate was never meant to block. Actually
  trading on Bisq is still fully subject to #6's existing conditions.
- **Eigen ASB and Haveno remain unbuilt** — see the research above; Eigen ASB
  is the more likely next pickup given its lighter apparent setup cost, not
  yet confirmed by actually building it.

**A real hang happened during this same-day verification, not just a clean
7-second run** — a manual foreground re-check of the poller got stuck 2h45m+
on a stalled `urlopen()` call (sleep/wake vs. Python's per-socket timeout,
not a Bisq API problem), and was found and killed by a second concurrent
Claude session. Full incident + why no code fix was needed is in
`project_status.md`'s "Bisq poller hang, same day" entry; the recovery steps
are now standing guidance in `../CLAUDE.md`'s session-start checklist — run
that checklist before touching this poller in any future session.

## 13. Eigen ASB read-only discovery `[BUILT, BLOCKED on a WebSocket transport gap — 2026-09-19]`

**Where this picks up from #12's own note**: "Eigen ASB is the more likely
next pickup given its lighter apparent setup cost, not yet confirmed by
actually building it." Actually building it found that the earlier
characterization (from `ARCHITECTURE.md`'s pre-2026-09-19 §7 row, itself
sourced from stale `comit-network/xmr-btc-swap` dev-docs) was wrong on the
specifics, but a real wallet-free path exists anyway once you look at the
current source directly instead of trusting old docs.

**What was actually wrong with the old assumption**: downloaded and
GPG-verified the real `swap` v4.14.0 binary from `github.com/eigenwallet/core`
(signature checked against the project's own published key). Two real
findings:
1. **No `list-sellers` subcommand exists any more** — checked `swap --help`
   directly; the CLI's current subcommand set is `balance`, `cancel-and-
   refund`, `config`, `export-bitcoin-wallet`, `history`, `logs`, `monero-
   recovery`, `resume`, `withdraw-btc`. Discovery moved elsewhere.
2. **Every one of those subcommands, including the least-stateful-looking
   `config`, unconditionally creates a real Monero wallet keyfile + a
   libp2p identity seed on disk** — confirmed both by watching it happen
   live (`swap-tool-blockchain-monitoring-wallet.keys`, `seed.pem`
   appeared after a bare `swap config`) and by reading
   `ContextBuilder::build()` in `swap/src/cli/api.rs` directly: every
   `CliCommand` branch in `command.rs`'s `apply_defaults()` calls
   `.build()`, and `build()` calls `wallet_setup::open_monero_wallet(...)`
   unconditionally, regardless of `self.monero_config` being `Some` or
   `None`. This isn't a flag you're missing — there's no observe-only mode
   in the CLI as currently written. The generated wallet was deleted before
   anything could touch it (created seconds before deletion, never funded).

**The actual wallet-free path**: `swap-p2p` (the crate implementing the
libp2p networking layer both the CLI and GUI share) ships its own example,
`examples/fetch_quotes.rs`, gated behind a `fetch-quotes-example` Cargo
feature. It does rendezvous discovery + quote fetching using only an
in-memory `identity::Keypair::generate_ed25519()` — generated fresh per run,
never written to disk, holds no funds. Confirmed via `swap-p2p`'s own
`Cargo.toml` dependency list (`swap-core`, `swap-machine`, `swap-env`,
`swap-serde`, `bitcoin-wallet` — none of these pull in `monero-sys`, the
crate that makes the full `swap`/`asb` binaries so large and wallet-heavy)
that this example never touches Monero wallet code at all.

**Built and verified real, not just read about**:
- Shallow-cloned `eigenwallet/core` (33MB, no submodules needed — the
  `monero-sys/monero` submodule is irrelevant to `swap-p2p`).
- Built the unmodified upstream `fetch_quotes` example successfully —
  confirms the wallet-free claim isn't just a reading of the dependency
  graph, it actually compiles without the heavy Monero C++ toolchain.
- Wrote a second example in the same crate, `fetch_quotes_json.rs` (not
  upstream code — this project's own addition, `#![allow(unused_crate_
  dependencies)]` at the top same as the original): runs for a bounded
  window (`FETCH_QUOTES_TIMEOUT_SECS`, default 25s) instead of looping
  forever, keeps the latest `CachedQuotes` snapshot (each event already
  carries the full current set, not a delta), and prints exactly one JSON
  array to stdout on exit — all logging routed to stderr so stdout stays
  parseable. This is the shape a Python poller needs (`subprocess.run()`
  once per cycle, matching `venues/poller.py`'s existing per-cycle-call
  pattern). Compiles clean (4.34s incremental build once the base
  dependency graph was already resolved).

**Ran it for real against the live network — this is where it's currently
blocked**: Tor (`arti-client`, a pure-Rust in-process Tor client — no system
`tor` daemon needed) bootstraps fine every time (real consensus loaded, real
guards found, ~10-12s). But discovery against all 4 of
`swap_env::defaults::default_rendezvous_points()`'s rendezvous nodes
(eigenwallet x2, atomicworld, stealthswap — each with a clearnet-`wss` +
`onion3` address) consistently returns zero quotes. Root-caused via
`libp2p_swarm=debug` trace logging, not guessed — **two distinct, confirmed
failure modes, not one vague "network issue"**:

1. **Clearnet `wss` addresses fail with `ProtocolError(InvalidMessage)`** at
   the multistream-select layer. `fetch_quotes_json.rs`'s `create_transport()`
   (copied verbatim from the upstream example — not something this session
   changed) tunnels Tor-proxied TCP straight into noise/yamux with no actual
   WebSocket/TLS layer wrapped around it for the `/wss` multiaddr suffix.
   This looks like a real gap in the *upstream* example too, likely unnoticed
   by its maintainers because normal operation relies on the onion path
   succeeding instead — worth checking if this is a known issue upstream
   before assuming it needs fixing here from scratch.
2. **All 4 onion addresses fail via `ObtainHsCircuit` → `DescriptorDownload`
   errors** — repeated `HTTP 404 Not Found` from multiple independent Tor
   hidden-service directory nodes trying to fetch each service's descriptor,
   for every one of the 4 independently-operated services. Tor's base
   directory/consensus loads fine (this isn't a broader Tor problem on this
   machine) — it's specifically hidden-service descriptor lookups failing.
   Consistent across 4 unrelated operators reads as more likely a
   directory-freshness/`arti-client` quirk than 4 simultaneous real outages,
   but this isn't confirmed either way — could also just be real.

**Concrete next step, not yet attempted**: add a real WebSocket transport
layer to `create_transport()` for the clearnet path — `libp2p`'s own
`websocket` transport crate (or equivalent), wrapped under the existing
Tor-proxied-TCP → noise → yamux stack, specifically for addresses ending in
`/wss`. This would resolve failure mode #1 independently of whatever's
going on with #2's onion lookups, and clearnet succeeding alone would be
enough to get real quotes flowing. If clearnet still fails after that fix,
revisit #2 (try a plain non-Tor dial to the clearnet `wss` addresses as a
diagnostic — bypasses Tor entirely to isolate whether Tor-tunneling is part
of the WebSocket problem, separate from the onion-specific HSDir issue).

**Where things are saved**: `eigenwallet-core` clone (with both the
unmodified `fetch_quotes.rs` and the new `fetch_quotes_json.rs`, plus the
`Cargo.toml` edits adding `serde_json` and the second `[[example]]` entry)
is in this session's scratchpad, not yet copied into this repo — a fresh
session should either recreate the clone (fast, 33MB, no submodules needed)
or ask whether the scratchpad copy is still around. No production Python
code (`venues/eigen_asb/` client+reader, matching `venues/bisq/`'s shape) has
been written yet — that's the step *after* real quotes are flowing, not
before, so it isn't built against a binary that returns nothing.

## Explicitly not on this list

- **UTXO hygiene** (`ARCHITECTURE.md` §6) — not applicable at current capital
  scale (single fixed-size offer, not fragmenting a larger balance). Revisit if
  and when position sizing grows enough that a single swap could lock up most
  of available BTC.
- **CEX perpetual hedge** — the source PDF itself drops this (§6 of the v3.1
  doc's own "Considered and Dropped" table) for the same reason it doesn't fit
  here: custody/funding-rate/liquidation risk not worth it for small working
  buffers. No reason to revisit unless capital scale changes that calculus.

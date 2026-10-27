# Market Maker — Next Steps

Framework-level build queue. Ordered by how directly each item closes a gap
identified in `ARCHITECTURE.md` §§6–9, not by how interesting it is. Items
already tracked in `basicswap/next_steps.md` at the venue level are referenced,
not duplicated, unless this level changes their priority.

## Status at a glance (as of 2026-09-19 — verify before trusting, this is a snapshot)

| # | Item | Status |
|---|------|--------|
| 1 | Volatility-based kill-switch | **DONE, deployed**; 60-min window + 30-min cooldown added 2026-09-24, built/tested, awaiting restart |
| 2 | Real MVB sizing (replace `--reserve-usd 210`) | Blocked — no fallback route to measure a real `T_fallback` off |
| 3 | Per-fill P&L ledger | **DONE 2026-09-24** — `basicswap/strategy/fill_ledger.py`, `fills` table, edge @fill/+1h/+24h; not yet scheduled |
| 4 | Real fill-vs-expiry detection | **DONE 2026-09-24** — via `/json/bids` bid_state in `fill_ledger.py` (Completed vs Expired) |
| 5 | Tax lot tracking | Unblocked — #3 exists now |
| 6 | Venue #2 scoping (capital) | Deliberately not started — needs explicit human sign-off first |
| 7 | Inventory controller (incl. cross-platform liquidity/wallet-automation rough idea, 2026-09-19) | Deliberately not started — trigger is #6 actually happening; a staged rough shape (same-asset transfers vs. cross-asset replenishment, manual → unattended) is now sketched in its own entry |
| 8 | Testnet/shadow-engine backfill | Open question, not a commitment — raise before any capital-size increase |
| 9 | Duplicate-instance PID guard | **DONE, deployed** |
| 10 | Source-disagreement gate | **DONE, deployed** (built same-day in response to a real, quantified loss — see its entry) |
| 11 | Mispriced-offer opportunity scanner (cross-venue) | **Designed only, deliberately NOT built** — Evan's explicit instruction |
| 12 | Bisq read-only observation poller (venue #2, observation-only) | **DONE, verified live** — no capital, no write path |
| 13 | Eigen ASB read-only discovery (venue #3, observation-only) | **DONE, DEPLOYED, 2026-09-19**: same shape as #12 (Bisq) — `libp2p` bumped, `venues/eigen_asb/` built (29/29 tests), scheduled via the existing poller (no new plist needed), verified writing real rows into production `~/coinswaps/venue_observations.db` on its own natural cycle |
| 14 | Cross-venue spread/size analysis ("what can we learn from others' offers") | **DONE, ACTED ON, 2026-09-19** — corrected an apples-to-oranges comparison, cross-checked against `economics.py`'s cost model, `half_spread_pct` raised 0.011→0.02 on Evan's "fix the BS rate" call, deployed and verified |
| 15 | Dynamic, cross-venue-aware pricing roadmap | Phase A **DONE, DEPLOYED, 2026-09-19**; Phases B–D still not started |
| 16 | Opportunistic bid-scanning | Built/tested 2026-09-20, not run with `--live` |
| 17 | Accumulate-BTC proof trial + success bar | **BUILT 2026-09-28** — `proof_report.py`, Kraken book snapshots, sent-bid ledger; trial starts when Evan runs `restart_live_maker_btc.sh` |

## Gemini review (2026-10-02): "XMR toll booth" — mostly already running

Source: the 2026-10-02 Gemini 3.1 Pro review (full context and the net-new ideas are in the workspace-root `profitable_strategies_to_explore.md`). Not started. Same pre-registered, backtest-first rule as everything else here.

Gemini's top pick overall was to quote only the XMR-sell side, at a premium, into Bisq's ~96% one-way XMR-buying flow. That's essentially the #17 proof trial live since 2026-09-30, which ends 2026-10-28 at the earliest. Don't change the trial. Two post-trial items to consider:

- **A higher-premium sensitivity check.** Gemini proposed +4% over spot vs the trial's ~+1.8%. Bisq's median premium is ~1.95%, so +4% likely fills rarely. Read it from the trial's fill-rate-vs-premium data rather than running it live.
- **Reject Gemini's "hedge BTC back to USD weekly".** It conflicts with the BTC objective (see the 09-28 objective decision).
- **Legal read before scaling capital.** Gemini framed the edge as "regulatory friction" (buyers paying for privacy/no-KYC). Before scaling past personal-account size, get a lawyer's read on whether repeated market making for others raises money-transmitter questions. Not needed for the current trial.

## Available to pick up right now (no human decision needed first)

**2026-09-28, later (read this first)**: #17's proof trial and success bar are
built (226/226 tests). Starting it takes Evan: optionally seed the sell stock, then run
`basicswap/restart_live_maker_btc.sh`. Score it with `strategy/proof_report.py`.

**2026-09-28**: the accumulate-BTC retarget is built
(`--objective btc`, restock-priced ask + target-premium sell leg + XMR inventory
target, 206/206 tests), and `basicswap/restart_live_maker_btc.sh` is ready. It is
**not deployed**, because a live-pricing change needs Evan's go-ahead. Launchd
plists for the BasicSwap poller and fill ledger are written but not installed. See
`project_status.md`'s 2026-09-28 handoff for the ordered list.

**2026-09-24, later**: handoff items 4 (kill-switch long window + cooldown:
built, 159/159 tests, awaiting `restart_live_maker.sh`) and 5 (Bisq trade flow:
~2.6 BTC/day, ~96% of volume pays XMR sellers a premium, so the ask side
quotes the direction nobody trades) are done. See `project_status.md`.

**As of 2026-09-24 (read this first)**: #3/#4 are DONE (`basicswap/strategy/fill_ledger.py`).
The profitability review found no evidence of a money-making strategy yet
(2 fills, round trip about -$46, 0 fills at the 2% spread). See
`project_status.md`'s 2026-09-24 "Handoff for the next session" for the
ordered pickup list. Top items: restore the BasicSwap poller (down since
09-23) under launchd (needs Evan's permission), commit the 09-24 work, then
the markup/fill-rate experiment (needs Evan's sign-off) and kill-switch
recalibration.

**As of 2026-09-19, #13 (Eigen ASB) is DONE and deployed** — the
`libp2p` bump was authorized and completed, `venues/eigen_asb/` is built,
tested, and running on the same 5-minute schedule as Bisq, writing real
rows into production. It's no longer a blocked or pending item; see its own
entry for the full build record and the zero-liquidity root-cause finding.

**As of 2026-09-19, later the same day: #14 is also DONE (the spread fix)
and #15 (Phase A specifically) is the one genuinely unblocked, ready-to-
build item on this whole list.** #15's Phase A — composing `volatility.py`
and `economics.py` (both already built, already tested) into a per-cycle
computed `half_spread_pct` instead of a static CLI default — needs no new
human sign-off to build and test, since it's assembling two already-
approved modules; only the final live-capital deploy step needs review,
same as every other change to `live_maker.py`. Phases B–D of #15 are each
gated on the phase before them (real cross-venue context needs Phase A's
plumbing; real lock-time precision needs #4, which needs more real fills
first).

With #13/#14 closed, the rest of the framework-level list is split
cleanly: real fill data that hasn't accumulated yet (#2–#5), an explicit
capital/venue decision only Evan can make (#6, #7, #11), or already done
(#1, #9, #10, #12, #13, #14).

**What actually changes now that two observation venues (Bisq + Eigen ASB)
are both live and accumulating**: the case for #11 (the cross-venue
mispriced-offer scanner, designed but deliberately not built) gets
materially stronger once there's real multi-venue data to calibrate a
"worth acting on" threshold against, per its own item's design step 3 — but
this is still explicitly gated on Evan's sign-off before any code gets
written, not a default next step just because the data now exists. Note
this is a different capability from #15's Phase B (using the same data as
*context* for our own price vs. *acting* on another venue's price) — #15
Phase B doesn't need the same sign-off #11 does.

Two secondary, heavier-scoping options, lower-confidence than #13 was:
- **A third observation venue candidate, Haveno**, is unevaluated
  (`ARCHITECTURE.md` §7 names it CORE/REPLENISHMENT alongside Eigen ASB and
  Bisq, but nobody's checked its actual setup cost the way #12/#13 did for
  the other two). Heavier than Bisq or Eigen ASB though — no hosted public
  read endpoint exists; it needs your own Haveno daemon/AppImage running,
  not just a library call — so this is a scoping task, not a quick build.
- **#8, testnet/shadow-engine backfill** isn't a build task at all — it's a
  question worth raising with Evan (not a default next step) the next time
  capital sizing is about to increase.

**The #10-incident follow-ons (see below) and the bid-side restart are
resolved, not open action items** — don't re-open either without new
evidence.

**The six `DONE` items (#1, #9, #10, #12, #13, #14) are all live/verified
right now** (#1/#9/#10/#14 confirmed via both live BasicSwap processes'
startup logs — #14 specifically shows `half_spread_pct=0.0200`; #12/#13
confirmed via real polls against Bisq's live API and Eigen ASB's live
quote discovery, both writing into production `~/coinswaps/
venue_observations.db` on the same 5-minute schedule — see their own
entries below). **#11 is fully speced but must not be started without
checking with Evan first** — it's a new, higher-risk capability (acting on
other participants' public data), not just a documentation gap to fill in.

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
**Restart confirmed deployed, 2026-09-19** — resolved, not an open item
anymore. The sandbox had blocked killing/restarting the live processes
directly at the time this was written, so `basicswap/restart_live_maker.sh`
was built for Evan to run himself; a later same-day check confirmed both
processes' startup logs show `half_spread_pct=0.0110` (not `0.0066`), i.e.
the new build is actually running. Still worth a quick sanity check at the
start of a fresh session (`ps aux | grep live_maker` — expect exactly 2
processes) since that's cheap, but this is no longer a pending action.

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

**Characterization question, discussed 2026-09-20, current best idea logged,
not resolved:** whether this activity's profit can reasonably be reported as
**ordinary business income** rather than per-swap capital gain/loss on every
disposed unit. Two paths were evaluated and one was ruled out:

- **Ruled out**: treating captured spread as analogous to mining/staking
  reward income. Mining/staking ordinary treatment (Notice 2014-21,
  Rev. Rul. 2023-14) rests specifically on *receiving newly-created property
  with nothing given up* — a pure receipt event. Every BasicSwap fill is the
  opposite: disposing of already-owned property (BTC) for already-owned-type
  property (XMR) at an agreed rate — a disposal, not a receipt, under
  Reg. §1.1001-1. No field in BasicSwap's own protocol (checked directly
  against the live `~/coinswaps` install — `db.py`'s `a_fee_rate`/
  `b_fee_rate`, `js_server.py`'s `offer_fee_estimate`) represents a payment
  *to* the maker; every "fee" shown in the UI/API (e.g. "Chain A offer fee
  rate") is the on-chain network fee rate used to size the HTLC lock/spend
  transaction — a cost paid to miners, already modeled as a cost in
  `basicswap/strategy/economics.py`, not an isolable revenue line. There is
  no protocol-level fee mechanism to decompose a swap into a "fair value leg"
  plus a "service fee leg."
- **Current best idea**: the dealer/inventory exception, IRC §1221(a)(1) —
  property "held by the taxpayer primarily for sale to customers in the
  ordinary course of his trade or business" is excluded from capital-asset
  treatment, so a genuine dealer's trading profit is ordinary business income
  computed in aggregate (like COGS accounting), not itemized per disposal.
  This is independent of §475 mark-to-market (which crypto doesn't currently
  qualify for — not a "security" or "commodity" under current §475
  definitions; a bill that would extend §475 eligibility to digital-asset
  dealers, the Digital Asset Tax Certainty Act (H.R. 10357), cleared House
  Ways & Means committee 2026-09-16 but is not law). The factual case for
  dealer status has real support — public two-sided standing quotes any
  counterparty can take, profit structurally defined as spread capture net
  of cost (`ARCHITECTURE.md` §3's net-edge equation) rather than price
  appreciation — but it is genuinely untested for an individual running
  non-custodial P2P swaps with no formal dealer registration, at modest
  scale, as one of many projects. Real trade-offs if pursued and granted:
  ordinary characterization doesn't lower the rate on gains that would
  otherwise be short-term capital gains (already taxed at ordinary federal
  rates) — the real upsides are fuller business-expense deductibility and
  more favorable loss netting (relevant given the desk's live fills have so
  far been losses), and the real cost is self-employment tax exposure unless
  mitigated by entity structure. **Not decided, not a build item** — needs a
  crypto-savvy CPA/tax attorney to evaluate against actual activity/scale
  before any return relies on it. Logged in `TASKS.md`.

**Required before going live at scale (noted 2026-10-02).** If the proof trial
(#17) passes and the desk is sized up, build this first. 2026 trial fills are
already taxable, so it should at least cover them before year-end.
- **Per-fill record:** dollar value of what was received at the fill (fill_ledger
  already stores BTC/USD per fill), the purchase lot it draws from, the wallet it
  sits in, and network fees (these reduce the gain).
- **Specific identification, recorded at the time of each fill.** Since 2025
  (Rev. Proc. 2024-28), cost basis is tracked per wallet, and a lot choice made
  after the fact doesn't count; without one, first-in-first-out applies. Default
  to the highest-cost lot to keep short-term gains low.
- **Keep low-cost BTC out of the pool.** Spending old BTC on a restock realizes
  its whole built-up gain. Fund the pool from recent purchases (e.g.
  `coinbase_dca`) and keep long-held BTC in a separate wallet.
- **Output:** Form 8949 lines (short-term digital assets, no 1099-DA) plus a PA-40
  Schedule D total. No DEX issues a 1099-DA (the DeFi broker rule was repealed in
  2025); Kraken would, if it's used for restocking.
- **Scale:** each round trip is about 2 reportable sales, so ~200 lines a year at
  ~8 round trips a month and ~1,000+ at ~40. Generate them; don't hand-enter.
- Rough tax at Evan's rates (22% federal, short-term, plus PA 3.07%): about 25% of
  net gains. The CPA question above (dealer vs. capital) still decides
  self-employment tax.

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

**Rough idea for cross-platform liquidity management and wallet automation,
sketched 2026-09-19 (Evan asked for this to be captured) — not decided, not
built, still gated on #6 exactly like the rest of this item.**

**The structural fact driving all of this**: every venue this framework
touches is non-custodial and keeps its own separate wallet under our own
control, with no shared-balance/sub-account model the way a CEX would
have. BasicSwap's lives at `~/coinswaps`; the reference `swap`/`asb`
binaries this session's Eigen ASB research touched unconditionally create
their own local Monero+Bitcoin wallet the same way (`ContextBuilder::
build()`, confirmed by reading the source — see `next_steps.md` #13's
history); Bisq/Haveno would each need their own too. Liquidity is
inherently siloed per-venue wallet unless something moves it between them.

**Two genuinely different mechanisms, worth keeping separate rather than
conflating into one "rebalancing" idea**:
1. **Same-asset rebalancing across venue wallets** — e.g., XMR sitting
   idle in an Eigen ASB wallet while BasicSwap's bid side is starved of
   XMR. A plain on-chain transfer between two wallets we already control:
   same asset in, same asset out, no swap, no aggregator, no third party.
   Because it never touches a third-party custodial/semi-custodial
   provider, it doesn't trigger `ARCHITECTURE.md` §8's KYC-resilience
   posture at all — stays at today's zero KYC surface area no matter how
   many venues eventually exist.
2. **Cross-asset replenishment** (need more BTC, only have XMR, or vice
   versa) — already covered by §5's existing "replenishment routing
   hierarchy": passive resting-bid-on-the-same-venue first (already how
   BasicSwap's ask/bid pair works today), a fee-bearing instant-swap
   aggregator (Trocador) only as a last resort. More venues don't change
   that doctrine, they just add a "which venue's resting bid to try
   first" decision on top of it.

**A staged rough shape for mechanism 1 above (same-asset transfers),
matching this project's own established rollout pattern elsewhere**
(`coinbase_dca`'s
dry-run → small approved live test → unattended; `basicswap/CLAUDE.md`'s
"any further escalation is its own separate decision, not implied by this
one"):
- **Stage 0** (comes free once #6/§4's inventory controller exists): a
  read-only view of available/reserved/locked/in-flight balance *per
  venue wallet*, aggregated to a total — visibility before any action,
  no new capability beyond what #7's own base scope already implies.
- **Stage 1**: manual, human-approved rebalancing — Evan personally sends
  a normal on-chain transfer between venue wallets when Stage 0's view
  shows a real, sustained imbalance. Nothing to build beyond the
  visibility layer; this is just "Evan does a normal send," same posture
  as every other real-money action in this project today.
- **Stage 2** (only after Stage 1 shows a real, repeated need — not a
  default next step): a semi-automated version that proposes/logs a
  suggested rebalancing transfer each cycle but still requires explicit
  approval before executing — same "propose, don't act" posture #11's
  scanner design already established for a different capability.
- **Stage 3** (a real, separate decision, not implied by reaching Stage
  1 or 2): fully unattended cross-wallet transfers. Genuinely hard to
  reverse, moves real capital with no human in the loop each time — the
  same category of action this project treats cautiously everywhere else
  (`basicswap/CLAUDE.md`'s "no mnemonic/private key ever generated
  through or logged into a Claude session," `coinbase_dca`'s 3-stage
  gate). Not on the table until Stage 1/2 produce enough real operating
  history to justify it, and even then it's Evan's call, not a default.

**What this doesn't answer yet, honestly**: how large a same-asset
imbalance has to get before it's worth the on-chain fee + settlement time
of a transfer vs. just letting one venue's quote go temporarily unfunded
(the same shape of question `#2`/MVB's own still-open "how big a buffer"
gap already has) — no real multi-venue capital history exists yet to
calibrate that against, same gate as everything else in this item. Not
the same question as `#15`'s Phase B (which only ever reads other venues'
*public* data as pricing context, no capital or wallet involved) — this
item only becomes relevant the day we actually hold capital and quote on
more than one venue at once, which is #6's decision, not Phase B's.

**Dynamic, demand-driven sizing across venues — added 2026-09-20, in
response to Evan asking whether per-venue liquidity should be dynamically
sized off demand rather than a fixed split.** Yes — that's the intended
shape, but it's not decided or built, and it can't be calibrated yet. The
mechanism: extend Stage 0's per-venue-wallet visibility to also track
per-venue fill velocity and net edge — the same underlying data `#2`'s MVB
reserve formula and `#3`'s per-fill P&L ledger already need, so one data
pipeline feeds three things instead of three separate ones. A Stage
2-level suggestion would then recommend shifting idle capital toward
whichever venue is currently filling faster / at better realized edge,
rather than a hand-picked static split per venue — same philosophy as
`#15`'s dynamic spread work, which replaced a hardcoded `half_spread_pct`
constant with something computed from real signals instead of a fixed
number.

Honest blocker, same shape as the gap above: you can't demand-weight an
allocation across venues you don't have comparable fill history on. Today
there's exactly one venue with any live capital (BasicSwap, n=3 fills, all
losses so far per `basicswap/project_status.md`) and zero fills on any
second venue. This stays a stated design intent — captured here so it's
ready to build the day `#6`'s gate clears (BasicSwap edge proven + venue #2
actually scoped with capital) — not something to start calibrating on
today's thin data.

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

## 13. Eigen ASB read-only discovery `[DONE, DEPLOYED — libp2p bumped, Python integration built + scheduled, verified live — 2026-09-19]`

**2026-09-19, fourth continuation**: Evan asked to "build, run, and schedule
what we need to understand the profitability of eigen" — closed this item
out fully, matching #12's (Bisq) shape exactly.

**Built**: `venues/eigen_asb/` (new, sibling to `venues/bisq/`) —
`client.py` (subprocess wrapper around the compiled `fetch_quotes_json`
binary, not an HTTP client like Bisq's since none exists for this venue;
raises `EigenAsbClientError` on missing binary/non-zero exit/bad
JSON/timeout, matches `bisq/client.py`'s error-handling shape) and
`reader.py` (`EigenAsbOfferBookReader`, implementing the same
`OfferBookReader` protocol #12 already established). Confirmed the exact
field-unit mapping against `swap-p2p`'s own `BidQuote` struct source (not
guessed): `price`/`min_quantity`/`max_quantity` are all `bitcoin::Amount` —
i.e. **BTC** units, not XMR — so `reader.py` converts to XMR (`coin_from`)
units via `price` for `amount_from`/`min_bid_amount`, matching
`NormalizedOffer`'s contract. Registered in `poller.py`'s `_READERS` and
`config.py`'s default `venues` list (now `["bisq", "eigen_asb"]`). 14 new
unit tests (8 client, 6 reader) — full `venues/` suite now 29/29 passing.

**The compiled Rust binary now lives permanently at `~/eigenwallet-core`**
(release build, `cargo build --release --example fetch_quotes_json
--features swap-p2p/fetch-quotes-example -p swap-p2p`) — a sibling to
BasicSwap's own `~/coinswaps`, this project's established convention for
runtime state that doesn't belong in the git repo. Copied from *this*
session's scratchpad clone (source only, not the 8.3GB debug `target/`) and
rebuilt clean there — no longer session-scoped, survives across sessions
and reboots.

**Verified live end-to-end, twice**: once manually (11 real ASB quotes,
data landed correctly in a scratch DB with the BTC→XMR unit conversion
producing sane XMR-scale amounts), and once for real — **the pre-existing
`com.market_maker.venues-poller` launchd job (already running on its own
5-minute schedule since 2026-09-18) picked up the code change on its own
very next cycle and wrote 11 real `eigen_asb` rows into the actual
production `~/coinswaps/venue_observations.db`**, no plist edit or reload
needed, confirming the registry-based design worked exactly as intended.

**A real, immediate finding, already visible in the very first sample**: 8
of 11 ASBs cluster tightly (0.00675–0.00688 BTC/XMR); the other 3 are 17–29%
above that cluster. **Correction, made same-day after pulling a second,
fresh sample to double-check rather than trusting the first inference**:
the original claim that *all 3* outliers reported `0`/`0` min/max liquidity
was wrong — only 2 of the 3 (`xmr.swapexchange.club`, `bestchange24.
duckdns.org`) do. The 3rd (`pulse.mikaswap.com`) has real, nonzero,
tradeable size (`min_quantity`≈0.00005 BTC, `max_quantity`≈0.035 BTC) in
**both** the original sample and a fresh one pulled ~2h later, at a
persistently high markup (~27–29% above fair value both times) — see
#14 below for what that specific pattern likely means. This correction
matters: it means the "not an opportunity" reasoning below applies cleanly
to 2 of the 3 outliers, not all 3 — the 3rd is a structurally different
case. **Root-caused precisely for the 2 zero-liquidity cases, 2026-09-19,
not left as a guess**: read
the reference ASB's own quote-generation source
(`~/eigenwallet-core/swap/src/asb/event_loop.rs`'s `make_quote()`). It
computes `ask_price` fresh from the operator's own rate feed (a
Kraken/Bitfinex/KuCoin/Exolix average + configured spread, or occasionally
a manually-fixed rate — `swap-feed/src/rate.rs`) *before* any balance
check, then explicitly zeroes both `min_quantity` and `max_quantity` when
its own unreserved Monero balance can't cover even its configured minimum
swap size:
```rust
return Ok(Arc::new(BidQuote {
    price: ask_price,
    min_quantity: bitcoin::Amount::ZERO,
    max_quantity: bitcoin::Amount::ZERO,
    ...
}));
```
That's a genuine, real-time "I'm out of usable Monero right now" signal
from the maker's own inventory check, not a stale config or a bug — the ASB
still answers the quote request (rather than going silent) so it stays
visible as registered-but-currently-unfillable. **Why this isn't an
opportunity despite the attractive-looking price**: a real swap request
must specify an amount inside `[min_quantity, max_quantity]`; at `[0, 0]`
that interval is empty, so there is no valid trade size — the maker lacks
the underlying asset to fulfill any order, by its own declaration,
regardless of how the quoted price compares to fair value. This is a
different situation from #10's real BasicSwap incident, where the
mispriced offer *was* fillable and a real counterparty filled it for real
value — here the mispricing and the unfillability share the same root
cause and can't be pulled apart. Applies to 2 of the 3 outliers
(`xmr.swapexchange.club`, `bestchange24.duckdns.org`) — see #14 for the
3rd. One honest caveat: this doesn't rule out operator-specific
rate-feed/spread choices *also* contributing to some of the divergence —
but the reason these 2 specific quotes sit far outside the cluster,
unfillable, traces to this documented code path, not an inference from a
correlation alone. Still thin history — not enough to say anything about
profitability yet, but the pipeline that will accumulate that evidence is
now live and unattended.

**Scheduled**: no new plist — this reuses the existing
`com.market_maker.venues-poller.plist` (5-minute `StartInterval`, already
loaded), since `venues/poller.py`'s registry design meant enabling Eigen ASB
was a config-default change, not a new scheduled job. Continuous history is
now accumulating toward the same 1–2 week observation bar `next_steps.md`
#6 already uses elsewhere in this project.

**Deliberate design choices, not oversights**: (1) the scheduled poller
does **not** use Tor by default (`EIGEN_ASB_USE_TOR=0`) — pure read-only,
no-stakes market data, verified to return identical quotes without Tor's
~10-12s bootstrap cost every cycle; (2) `expire_at` is always `None` — a
quote isn't a listing with an expiry, it's a continuously-requoted price,
unlike BasicSwap/Bisq offers; (3) `is_own_offer` is always `False` — no
Eigen ASB identity/wallet exists, matches the standing "no wallet, no key
material" posture for this whole venue.

**Still correctly not done**: no cross-check against
`external_rates.py`'s reference rate (same as Bisq's own still-open item —
worth adding once there's more than one live venue's data to compare
against), no write path, no ASB identity, no capital. Actually trading on
this venue remains fully subject to `next_steps.md` #6's existing
capital-gate conditions, unchanged by any of this.

### Superseded: dependency-bump root-cause diagnosis (kept for the record)

**2026-09-19, third continuation**: Evan authorized the `libp2p` dependency
bump the entry below identified as the real fix ("you just need my
permission to change versions of libp2p? ... go ahead"). Did it, and it
worked.

**What was done**: bumped the workspace `Cargo.toml`'s `libp2p = "0.53.2"`
to `"0.57.0"` (pulls in `libp2p-rendezvous` 0.18.0, the `prost`-based
release that fixed this exact bug), removed the temporary debugging patch
from the entry below (irrelevant once on a real newer version; its
`vendor-patches/` dir was deleted). `cargo update -p libp2p` resolved
cleanly. Building `swap-p2p` (the only crate this venue actually needs)
surfaced **43 real compile errors** from the libp2p 0.53→0.57 API
migration — all confined to this project's own `swap-p2p`/`libp2p-tor`
source, none inside third-party crates, and all fell into 5 known,
mechanical patterns:

1. `NetworkBehaviour::handle_established_outbound_connection` gained a 6th
   parameter (`PortUse`, added in libp2p-swarm ~0.54 for port-reuse
   decisions during hole-punching) — 12 call sites across both crates
   needed the param added to their signature and threaded through to any
   delegating `self.inner.…` call.
2. `request_response::Event::InboundFailure`/`OutboundFailure` and
   `identify::Event::Received` gained new non-exhaustive fields
   (`connection_id`) — field-list patterns needed `..` added, both in the
   shared `impl_from_rr_event!` macro (one fix covering 4 macro-expansion
   sites) and in `quotes.rs`'s own manual matches.
3. `redial.rs`'s `poll()` used the `void` crate's `Void` as its
   never-type; the trait now requires `std::convert::Infallible` —
   straight type swap.
4. `libp2p_tor::TorTransport`'s `Transport` impl: `dial_as_listener` and
   `address_translation` were removed from the trait entirely (subsumed by
   a new `DialOpts` parameter on `dial()` itself, which now needs a 3rd
   `opts` argument, unused here since Tor dialing doesn't need to
   distinguish role/port-reuse).
5. One deprecation warning only (`websocket::WsConfig` → `Config`), not an
   error — left as-is, cosmetic.

**Verified against the live network immediately after the fix compiled**:
`fetch_quotes_json` returned **real price quotes from 11 distinct live
Eigen ASBs** — not just rendezvous registrations, actual quotes with real
prices, size limits, and agent versions. First snapshot (2026-09-19, no
Tor, 15s window): 8 of 11 clustered tightly around 0.0068 BTC/XMR
(0.006746–0.006890), but 3 were priced 17–25% above that cluster
(`xmr.swapexchange.club` 0.00798, `bestchange24.duckdns.org` 0.00798,
`pulse.mikaswap.com` 0.00856) — a real, immediate hint of the same kind of
per-maker mispricing this project has already found and traded around on
other venues (`#10`'s BasicSwap incident), though this is one snapshot, not
a distribution — not enough yet to call it a real, persistent pattern.

**Not done yet, correctly**: this run was manual and one-shot, same
posture as #12's Bisq work before it got a scheduled poller. No persistent
storage, no schedule, no `venues/eigen_asb/` Python `OfferBookReader`
implementation wired into `venues/poller.py`'s registry — the standing gate
("no production client until quotes flow") is now cleared, but building
the actual production integration is new, additional scope beyond what was
authorized this turn (a dependency bump), not something to do silently.
The Rust-side fix (16 files, `+796/-676` per `git diff --stat`) lives only
in *this* session's scratchpad `eigenwallet-core` clone — not copied into
this repo yet. If this venue moves forward, it needs the same treatment
#12 got: a stdlib-only Python `reader.py` that shells out to this compiled
binary (matching `venues/bisq/`'s convention), a storage table, and a
launchd schedule — real, scoped follow-up work, not done here.

### Superseded: root-cause diagnosis (kept for the record)

**2026-09-19, second continuation (picks up from the "rendezvous-protocol
gap" entry directly below)**: found the actual root cause of the
`discover`-fails-with-`Unavailable` blocker — not a proxy, not Tor, not a
transport issue at all. It's a real, deterministic wire-format bug in the
exact `libp2p-rendezvous` version this workspace's `eigenwallet-core` clone
pins, and it's already fixed upstream in a release 8 days newer than what's
pinned here.

**How this was isolated — real wire bytes, not more inference from the
generic error code, per this item's own "concrete next step"**: rather than
attempt a packet capture, patched a local vendored copy of the
`libp2p-rendezvous` 0.14.0 crate (via a `[patch.crates-io]` path override in
the workspace `Cargo.toml`, pointing at
`vendor-patches/libp2p-rendezvous-0.14.0/` — a debugging-only change, not
committed anywhere) to log the real `OutboundFailure` that
`client.rs::event_for_outbound_failure` was discarding before collapsing it
to the generic `ErrorCode::Unavailable`, and separately to log the raw bytes
entering the protobuf decode. Two findings, in order:

1. The real error is `Io(Custom { kind: InvalidData, error:
   Deprecated("group") })` — a `quick-protobuf` decode error, not a
   network-layer failure. This alone proves the response **is** arriving —
   an `Io` decode error can only fire on bytes that were actually received.
2. The captured raw response (9020 bytes, consistent across 8 real requests
   in one run) is a **perfectly well-formed protobuf message** — manually
   walked it byte-by-byte in Python against this exact crate's own
   `rpc.proto` schema (proto2, `rendezvous.pb.Message` →
   `DiscoverResponse` → repeated `Register`) and it parses cleanly end to
   end: 32 real `xmr-btc-swap-mainnet` ASB registrations, a cookie, and
   `status=OK`, landing exactly on the buffer's last byte. Zero unknown
   fields, zero group-wire-type tags anywhere in the actual `Message`
   content.

**The actual bug**: `quick-protobuf-codec`'s `Decoder::decode` (the layer
*around* the raw protobuf message — see its `src/lib.rs`) expects an
`unsigned_varint`-encoded length prefix before each message, and this
crate's own `Encoder` writes one symmetrically on the outbound side. But the
live server's response has **no such prefix** — it's the bare
`rendezvous.pb.Message` bytes directly. Given that, the codec misreads the
response's own first byte (`0x08`, the real message's `type` field tag,
which also happens to be a syntactically valid one-byte varint = 8) as if it
were an 8-byte length prefix, then tries to parse only 8 bytes as the entire
message. The second byte of that wrongly-bounded 8-byte slice (`0x04`)
decodes as field 0 / wire type 4 (`END_GROUP`) under plain protobuf tag
math — which is exactly what `read_unknown()` rejects with
`Deprecated("group")`. Confirmed this maps byte-for-byte against the actual
generated decoder in `src/generated/rendezvous/pb.rs` — not a guess.

**Why this is a version mismatch, not a local bug to fix here**: checked
`libp2p-rendezvous`'s real crates.io history (`https://crates.io/api/v1/
crates/libp2p-rendezvous` + upstream `rust-libp2p`'s
`protocols/rendezvous/CHANGELOG.md`, both fetched live 2026-09-19). Current
latest is **0.18.0, published 2026-09-11** — 8 days before this session —
and its changelog entry reads verbatim: **"Revert migration to
`quick-protobuf`, migrate back to `prost`."** This project's workspace
`Cargo.toml` pins `libp2p = "0.53.2"`, which resolves to the old, pre-revert
`libp2p-rendezvous` 0.14.0 (`quick-protobuf`-based) — the exact version this
session patched and traced the bug in. The live rendezvous nodes
(`discovery.eigenwallet.org`, `dht.stealthswap.ninja`) are almost certainly
running server code built against a `prost`-based (0.18.0+) release, which
is why `identify` (an unrelated protocol/codec) succeeds on the same
connection while `discover` fails deterministically, every time, at the same
byte.

**The real fix, not attempted this session — a scoping decision, not a quick
patch**: bump `libp2p` (workspace-wide, `Cargo.toml`'s
`libp2p = { version = "0.53.2" }`) to a release that pulls in
`libp2p-rendezvous` ≥0.18.0. This is a **much bigger change than anything
else on this list** — `libp2p` is a workspace dependency shared across 10+
member crates in this large upstream fork (`swap`, `swap-asb`,
`swap-controller`, `swap-p2p`, `libp2p-rendezvous-node`, etc.), not something
scoped to the read-only quote-fetching example this project cares about.
Whether that bump is worth taking on — and whether it's even compatible with
everything else this fork depends on `libp2p` 0.53.2 for — is Evan's call,
not a default next step. **Not recommended to work around this locally**
(e.g., a custom non-length-prefixed decoder bolted onto the old crate) —
that would diverge from the real, correct, already-upstream fix for a
temporary read-only research tool.

**Where things are saved**: the debugging patches (client.rs's real-error
logging, codec.rs's raw-bytes logging, the `vendor-patches/` copy, and the
`[patch.crates-io]` entry pointing at it) live in *this* session's scratchpad
clone alongside the two earlier (WebSocket transport) fixes — same path as
noted in the entry below, session-scoped, recreate if gone. These are
debugging instrumentation only, not meant to ship; the underlying fix is the
dependency bump described above, not these patches.

**Status, plainly**: this item is **no longer "needs wire-level visibility"**
— it has a complete, evidenced root cause and a known correct fix path. It's
now blocked on the same kind of decision `next_steps.md` #6/#8 already flag
elsewhere in this file: not more engineering effort, but whether Evan wants
to take on a real (and workspace-wide) dependency upgrade for a still
read-only, no-capital research venue. Until that's decided, quotes still
don't flow and no production Python client (`venues/eigen_asb/`) should be
built — same standing gate as before.

### Earlier the same day: WebSocket transport fixed, rendezvous-protocol gap first found

**2026-09-19, continuation of the same day's earlier entry below**: built
the concrete next step this item had scoped (a real WebSocket transport
layer for `create_transport()`) and it works — but it uncovers a second,
deeper blocker, not a full fix. Full detail first, then what's still open.

**What was built**: `fetch_quotes_json.rs`'s `create_transport()` was
tunneling Tor-proxied TCP straight into noise/yamux, with no WebSocket layer
for the `/wss` half of `default_rendezvous_points()`'s addresses (the
`/onion3` addresses don't need one). Rather than inventing a fix, found and
mirrored the production CLI's own answer to the identical problem:
`swap/src/cli/transport.rs::new()` already builds exactly this — a
`websocket::WsConfig`-wrapped Tor-or-TCP+DNS transport combined via
`.or_transport()` with a second, plain (non-`ws`) Tor-or-TCP+DNS transport,
with the `ws` transport listed first so it claims `/wss`-suffixed addresses
before the plain transport can eagerly grab them and skip the WebSocket
handshake. Ported that shape into `create_transport()` (minus the CLI's
`TorDialLimiter`/priority-tracker plumbing — unneeded for a low-concurrency,
bounded example), added libp2p's `websocket` feature to `swap-p2p`'s
dev-dependencies. Compiles clean (`cargo build --example fetch_quotes_json
--features swap-p2p/fetch-quotes-example -p swap-p2p`).

**Verified against the live network, not just compiled**: real `wss`
connections now establish to 2 of the 4 clearnet rendezvous nodes
(`discovery.eigenwallet.org`, `dht.stealthswap.ninja`) — previously this
path *never* connected at all (`ProtocolError(InvalidMessage)` at the
multistream-select layer, every time). Confirmed via `libp2p_swarm=debug`
logs showing real `Connection established` events, and confirmed the fix
isn't Tor-dependent by also running with `FETCH_QUOTES_USE_TOR=0` (bypasses
Tor entirely, dials the same clearnet `wss` addresses directly) — same
result, connections establish either way. The other 2 clearnet nodes fail
for reasons unrelated to this fix and already distinct from each other:
`discovery2.eigenwallet.org` returns `server rejected handshake; status code
= 530` (a Cloudflare-style error, likely that specific server/proxy, not a
protocol issue) and `rendezvous.atomicworld.fun` fails DNS resolution
through the Tor-proxied resolver (`NXDomain` even with Tor off, so this is a
real DNS problem with that hostname specifically, not a Tor artifact). The 4
onion addresses still fail exactly as this item's earlier entry described
(HSDir descriptor-lookup errors) — unrelated to this fix, unchanged.

**The new blocker, found once connections actually succeeded**: even over a
live, established `wss` connection, the rendezvous `discover` request still
fails — logged as `swap_p2p::protocols::rendezvous::discovery: Failed to
discover peers at rendezvous node ... error=Unavailable`. This is **not**
the same failure as before (dead in the water at the transport layer) — it's
one layer up, at the rendezvous request-response protocol itself. Isolated,
not guessed: on the same connection, `identify` succeeds first (logged:
`Received version from peer via identify ... version=0.2.0`), confirming
the connection, noise/yamux, and at least one application protocol all work
correctly — the failure is specific to the rendezvous protocol's `discover`
request. Traced the `Unavailable` error code to
`libp2p-rendezvous-0.14.0/src/client.rs`'s `event_for_outbound_failure()`:
it's the client crate's own generic fallback for *any* `OutboundFailure` on
the underlying request-response substream (timeout, protocol mismatch,
connection-level I/O error, etc. all collapse to this same code) — so
"Unavailable" here is not a genuine "zero registrations" response from the
server, it's our own request never getting a usable reply. Protocol ID
itself checks out (`/rendezvous/1.0.0`, the spec-standard string, matches
what this repo's own rendezvous-node server implementation
(`libp2p-rendezvous-node/`) uses — no custom/forked protocol name in play),
and the namespace sent (`XmrBtcNamespace::Mainnet`) matches what the
production CLI itself uses for a non-testnet discover. One more real,
possibly-relevant data point surfaced by the same debug run, not yet
followed up: the `identify` response's `observed_addr` for us comes back as
a Docker-internal-range address (`/ip4/172.21.0.7/tcp/57322/ws`,
`/ip4/172.19.0.7/tcp/45674/ws`) — suggesting these rendezvous nodes sit
behind a reverse proxy that terminates the `wss` connection and forwards to
an internal container, which is at least consistent with (though not proven
to cause) a proxy that mishandles or drops the specific request-response
substream a `discover` call opens.

**Concrete next step, not yet attempted**: this needs actual wire-level
visibility, not more inference from generic error codes — either a packet
capture / `RUST_LOG` at the `libp2p_request_response` crate's own trace
target (this session's attempts at that didn't surface any distinguishing
log line, worth re-checking whether that crate logs at all or needs a raw
capture instead), or a minimal, protocol-only reproduction (e.g., a tiny
throwaway example that only does `noise`+`yamux`+`identify` to confirm the
proxy theory, then adds the rendezvous request-response protocol alone, so
each layer's success/failure is unambiguous rather than inferred from an
already-composed swarm). Given the identify-succeeds-but-discover-fails
split, the proxy theory above is the most concrete lead to chase first.

**Where things are saved**: the `eigenwallet-core` clone with both fixes
(the transport-layer change to `swap-p2p/examples/fetch_quotes_json.rs` and
`swap-p2p/Cargo.toml`'s new `websocket` feature) is in *this* session's
scratchpad
(`/private/tmp/claude-501/-Users-evanpavloff-Desktop-Claude/a50b5ddf-adc0-4c46-8eaa-338a36e32635/scratchpad/eigenwallet-core`
— a different scratchpad path than the one the original discovery session
used, since scratchpads are session-scoped and don't persist across
sessions). Still not copied into this repo — still true, per the original
entry below, that no production Python code should get built against this
until real quotes are actually flowing, and they still aren't. A fresh
session should recreate the clone (fast, 33MB, no submodules) and reapply
the two changes described above (`git diff` against upstream
`eigenwallet/core` if the scratchpad clone itself doesn't survive to the
next session) rather than assume the exact same scratchpad path is still
readable.

### Original entry, 2026-09-19 (earlier the same day) — wallet-free path found

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

**Resolved, 2026-09-19, same day — see the entry above this one**: the
WebSocket transport layer described below as the next step is now built and
verified (real `wss` connections establish). The non-Tor diagnostic this
paragraph also proposed was run too and rules Tor out as a factor. Clearnet
succeeding did *not*, on its own, get real quotes flowing though — a second,
deeper rendezvous-protocol-layer blocker showed up once the transport layer
stopped being the bottleneck; see the entry above for that gap and its own
concrete next step. Left the original paragraph below intact as the record
of what was scoped and why, rather than deleting it now that it's done.

**Where things are saved**: superseded by the entry above — that one has
the current scratchpad path (session-scoped, changes each session) and the
current state of the clone (two files now changed, not just the one new
example file this original entry describes).

## 14. What real operators' offers teach us — cross-venue spread/size analysis `[DONE, ACTED ON — half_spread_pct fixed and deployed 2026-09-19]`

**Evan asked what we can learn from how others have set up their offers.**
Rather than reason abstractly, pulled fresh live data from both observation
venues (Eigen ASB, Bisq) against a real reference rate
(`basicswap/strategy/external_rates.py`'s `get_reference_rate('xmr', 'btc')`
— CoinGecko 0.00671875, Kraken 0.006714, tightly agreeing) and computed the
same markup-over-fair-value metric everywhere, so the numbers are directly
comparable rather than eyeballed.

### Finding 1: three real postures, not one undifferentiated market

**Eigen ASB (11 live ASBs, this session's fresh pull)**:
- **8 of 11 — the "competitive" tier**: markup 1.7%–3.8% above fair value
  (median 2.67%), size 0.035–12 BTC max (median 0.6 BTC). Tight pricing,
  meaningful size — this is where real trade flow most likely goes.
- **2 of 11 — out of liquidity**: `min_quantity`/`max_quantity` both zero
  (root-caused in #13 above — the ASB's own balance can't cover its
  configured minimum), prices 20%+ above fair but genuinely untradeable.
- **1 of 11 — a persistent "premium/thin" poster**
  (`pulse.mikaswap.com`): ~27–29% markup above fair value **in both this
  session's original sample and a fresh one pulled ~2h later**, but with
  real, nonzero, tradeable size the whole time (`min_quantity`≈0.00005 BTC,
  `max_quantity`≈0.035 BTC — roughly $5–$4,000 at current prices, not
  disqualified by #13's zero-liquidity mechanism at all). A persistent,
  repeated pattern across two independent samples reads as a deliberate
  strategy — charge a large markup, accept only very small size — not a
  bug or a stale price. Plausible explanations: a manually-configured
  static/`FixedRate` price the operator hasn't updated, a deliberately
  wide margin on a small float they're willing to risk, or genuinely
  different operating costs. Not enough samples yet to tell which, and
  this project has no write path to act on it even if it were a genuine
  gap — logged as a real market-structure observation, not a lead to chase.

**Bisq (113 live sell-side offers, same fresh pull, same direction —
maker selling XMR for BTC)**: markup p10=+1.9%, **median +4.64%**,
p90=+14.2%, max=+25.2% — a much wider and more dispersed market than
either Eigen ASB tier. Size: median 3.5 XMR, p90 35.8 XMR (roughly
0.024–0.24 BTC equivalent at current prices — bigger than Eigen ASB's
competitive-tier median). Minimum bid size much smaller (median 0.013 XMR)
than Eigen ASB's (median 0.005 BTC ≈ 0.74 XMR) — Bisq's market structure
looks more retail-friendly (many small, high-dispersion offers) than Eigen
ASB's (fewer, larger, tighter-clustered quotes from what read as more
professionally-run makers).

### Finding 2: our own BasicSwap spread was thinner than every real
reference point checked — `[FIXED 2026-09-19, half_spread_pct 0.011 -> 0.02]`

**Correction to this finding's first version**: the original table
compared our round-trip-equivalent (2×half_spread) against BasicSwap's own
*two-sided* observed median spread (~2.06%, `next_steps.md` #11) as if that
were an apples-to-apples check — it isn't. `live_maker.py` only ever
exposes itself to ONE side of a fill at a time, so the correct same-unit
comparison is `half_spread_pct` directly against a one-sided cost bar, not
against half of a two-sided market number.

**The correct bar, using this project's own already-built cost model**
(`basicswap/strategy/economics.py`'s `required_spread_pct` — fee + lock-
window volatility buffer + margin, researched 2026-09-16, never actually
cross-checked against `half_spread_pct` until now): run at our real ~$880
ask notional with the module's own fee assumptions, even a fast 30-minute
fill needs ~1.35% one-sided markup to break even with margin — already
above the old 0.011 — and a more realistic 2–3h fill (plausible given
Monero's own confirmation requirements) needs ~2.0–2.3%. This independently
converges with the cross-venue read below (Eigen ASB's competitive tier:
median 2.67% one-sided; Bisq: median 4.64%) — **two different methods,
bottom-up cost model and top-down competitor pricing, landing in the same
2.0–2.6% range.** All three real fills to date have been losses.

| Source | One-sided markup (same units as `half_spread_pct`) |
|---|---|
| **BasicSwap (ours, before this fix)** | 1.1% |
| **BasicSwap (ours, after this fix)** | **2.0%** |
| Cost model, `required_spread_pct` at a realistic 2–3h fill | ~2.0–2.3% |
| Eigen ASB, competitive tier (this session) | ~2.67% |
| Bisq, sell-side (this session) | ~4.64% |

**Fixed same session, on Evan's explicit "fix the BS rate" instruction**:
`strategy/live_maker.py`'s `--half-spread-pct` default raised 0.011→0.02.
98/98 tests still pass. `./restart_live_maker.sh` run — both processes
confirmed restarted with `half_spread_pct=0.0200` in their startup logs,
ask side immediately reposted at the new markup. Bid side's pre-existing,
deliberately-deferred reserve constraint (see `basicswap/project_status.md`)
is unrelated and unaffected. Full derivation kept inline in
`live_maker.py`'s own argparse comment, same convention as the previous
bump, so the number and its justification never drift apart. Full record
in `basicswap/project_status.md`'s 2026-09-19 entry.

**Still open**: the real lock/fill time this whole calculation is most
sensitive to (`basicswap/next_steps.md` §4(a)/§5) remains unmeasured — 0.02
is a defensible correction given what's known today, not a final number.
See #15 below for the roadmap toward a dynamic, data-driven replacement.

### Finding 3: what this does and doesn't unblock elsewhere in this doc

Doesn't unblock `#2` (real MVB sizing) — that item specifically needs a
measured `T_fallback` from a real fallback route, which this data doesn't
provide. But the real operator size data above (Eigen ASB's competitive
tier running 0.035–12 BTC max, Bisq running up to ~0.24 BTC-equivalent) is
a useful sanity check that BasicSwap's own fixed 0.008 BTC ask size is
small even relative to real competitors' *floors*, not just their
ceilings — context worth having if/when sizing ever comes up for
discussion, without being a formal MVB calculation.

## 15. Dynamic, cross-venue-aware pricing — roadmap `[PLANNED, 2026-09-19, not built]`

**The ask, from Evan**: lay out the next steps for using all of this data
(BasicSwap's own book, Eigen ASB, Bisq, `economics.py`'s cost model) to
price ourselves both *responsively per-market* and *consistently across
markets* — not just the one static-number fix in #14. This item is the
plan; nothing below is built yet, and none of it should be, without
picking it back up deliberately (most of it needs no further sign-off
since it's read-only computation feeding an already-human-approved
pricing knob, but the actual code changes to `live_maker.py` touch live
capital and should be reviewed before deploying, same posture as #14's
fix).

**Why this is a staged plan, not one item**: the three inputs this needs
(per-cycle volatility, real fill-time data, cross-venue context) are at
very different levels of readiness today. Sequencing matters — building
the cross-venue layer before the within-BasicSwap layer would mean
reacting to *other* markets' noise before we can even react to our own.

### Phase A — per-cycle responsiveness within BasicSwap `[DONE, DEPLOYED 2026-09-19]`

**Built as planned below.** `strategy/economics.py` gained two new functions:
`live_annualized_vol_pct(window_vol_pct, window_seconds)` (extrapolates
`VolatilityMonitor`'s rolling-window reading to an annualized-vol-equivalent,
the inverse of `vol_buffer_pct_for_hours`'s existing scaling) and
`dynamic_half_spread_pct(operator_floor_pct, notional_usd, lock_hours,
live_vol_pct, live_vol_window_seconds, ...)` (the actual `max(floor,
required_spread_pct(...))` composition this section originally specced).
`strategy/external_rates.py`'s `ReferenceRate` gained a `usd_price_from`
field so `live_maker.py` can compute a live USD notional from data the
cycle already fetched, with no new external call. `live_maker.py` now
reads `cfg.half_spread_pct` as a floor (`--half-spread-pct` unchanged as
the CLI flag name) and computes the real per-cycle spread via a new
`_dynamic_half_spread_pct` helper, using a new `assumed_fill_hours` field/
`--assumed-fill-hours` flag (default 2.5h, the midpoint of #14's own "2-3h
realistic fill" estimate) as the vol-buffer horizon — deliberately kept
separate from `cfg.lock_hours` (the offer's technical HTLC ceiling, still
24h), matching this section's original note that the lock-time input
stays a static guess in Phase A (Phase C replaces it with a real
measurement). 14 new tests (98→112 total, all passing): sanity checks on
the two new economics functions (never below floor, calm→floor,
elevated→widens, falls back to the static `ANNUALIZED_CROSS_VOL_PCT`
assumption when no live reading exists yet), plus `run_cycle`-level
integration tests confirming a real posted offer is priced wider than the
floor under an elevated volatility reading and exactly at the floor when
the USD cross isn't available that cycle.

**Deployed same day, on Evan's go-ahead.** `restart_live_maker.sh` run —
both processes stopped and relaunched cleanly, exactly 2 confirmed
running, both startup logs show `half_spread_floor_pct=0.0200
assumed_fill_hours=2.50`. The ask side's first live cycle already
exercised the dynamic path for real (`dynamic half_spread_pct=0.0217
(floor=0.0200, notional=$650.10, vol_pct=n/a over 15m)` — correctly
fell back to the static `ANNUALIZED_CROSS_VOL_PCT` assumption with no
volatility history yet on the fresh process). Bid side unchanged (still
in its known "nothing free to offer" state). Re-verified stable a few
seconds after restart — still exactly 2 processes, no errors.

Original spec, for reference:

**Gap**: `half_spread_pct` is a static CLI default, hand-edited and
manually redeployed (twice now — 0.66%→1.1%→2%) each time evidence
changes. Meanwhile `live_maker.py` already computes, every single cycle,
two of the three real-time inputs `economics.py`'s `required_spread_pct`
needs: `VolatilityMonitor`'s rolling-window recent volatility (built for
#1's kill-switch) and the live notional (recomputed every cycle for the
`--reserve-usd` bid side already). Only the fee/margin assumptions and the
lock-time guess are still static.

**Concrete shape**: replace the fixed `--half-spread-pct` value with a
per-cycle computed floor — `half_spread_pct = max(operator_floor,
required_spread_pct(current_notional, fee_assumption,
vol_buffer_pct_for_hours(assumed_lock_hours, sigma), margin_pct))` — using
the *live* volatility reading (already computed for the kill-switch) to
pick `sigma`/scale the buffer instead of a fixed constant, so the spread
widens automatically during real volatility spikes (a smoother, earlier
reaction than the kill-switch's binary skip-the-cycle behavior) and can
narrow back toward the operator's floor when the market's calm. This is
almost entirely composing two modules (`volatility.py`, `economics.py`)
that already exist and are already tested — the main new work is the
composition itself plus tests for the new blended function, not new
infrastructure. Lowest-risk, highest-value item on this list.

**Explicitly not doing**: letting the computed spread go *below* a
human-set floor automatically — #14's 0.02 (or whatever it becomes) should
remain a floor Evan sets, not something the algorithm can undercut on its
own even if the model says a thinner spread would "pencil out" for one
calm cycle. Matches this project's standing pattern (kill-switch/
disagreement-gate are always fail-safe toward *less* aggressive quoting,
never more).

### Phase B — cross-venue context (after Phase A, needs Phase A's plumbing)

**Gap**: BasicSwap's own pricing today has zero visibility into Eigen
ASB's or Bisq's live prices — the two venues #12/#13 built are pure
observation, feeding nothing back into our own quoting. #11 (the
mispriced-offer scanner) is a different, higher-risk capability
(*acting* on other venues' data) that Evan has explicitly gated; this is
lower-risk by design — using the same already-collected data as *context*
for our own price, never to take a position on another venue.

**Concrete shape**: a small read-only helper (`market_maker/venues/
cross_market_reference.py` or similar) that reads the latest
`venue_offer_snapshots` rows for Bisq + Eigen ASB (already accumulating
every 5 minutes) and computes a cross-venue reference markup (e.g. the
median of each venue's *competitive tier* — #14 already shows raw medians
mix outliers/thin-liquidity quotes in, undesirably, so this needs the same
tier-splitting logic #14 did by hand, not a naive median). `live_maker.py`
would treat this as a *sanity band*, not a target to copy: if Phase A's
computed spread sits far outside the current cross-venue band, log a
warning (and optionally require the wider of the two, never the
narrower — same fail-safe-toward-caution posture as Phase A's floor) —
this catches the kind of miscalibration #14 just found (a spread justified
by flawed same-platform reasoning that no one cross-checked against the
wider market) automatically, going forward, instead of needing a human to
notice and redo the analysis by hand again.

**Worth being precise about scope**: Phase B only ever *reads* Bisq's and
Eigen ASB's public data as context for BasicSwap's own price — it needs no
capital, wallet, or write path on either venue, same posture as #12/#13
themselves. That's a different, later question from actually *quoting* on
more than one venue at once, which would need #6's sign-off and #7's
liquidity/wallet-automation answer (see #7's own entry) — Phase B doesn't
imply or require either.

**Why this is gated on Phase A, not parallel**: Phase B's "sanity band"
check only makes sense once Phase A gives `live_maker.py` a *computed*
spread to sanity-check in the first place — bolting cross-venue context
onto a still-static number doesn't buy anything Phase A doesn't already
give for free.

### Phase C — real lock-time measurement (closes the biggest remaining unknown)

**Gap**: every number in #14 and Phase A above still guesses at the
actual swap lock/fill time (2–4h "plausible given Monero's confirmation
requirements") — `basicswap/next_steps.md` §4(a)/§5 has flagged this as
unmeasured since before this project went live. It's the single input
`required_spread_pct` is most sensitive to (5.4% one-sided at the 24h UI
ceiling vs. ~1.3% at 30 minutes — an order of magnitude swing).

**Concrete shape**: this is `next_steps.md` #4 (real fill-vs-expiry
detection, already on this list, still blocked on accumulating more real
fills) plus a new, small addition once #4 exists — timestamp each fill
from offer-post to swap-completion and feed the *real* measured
distribution into Phase A's `vol_buffer_pct_for_hours(hours, sigma)` call
instead of a guessed constant. Not started, correctly — needs #4 first,
which needs more real fills first, which is exactly the kind of thing
widening the spread (#14's fix) should *produce* more of over time by
making each fill more likely to be profitable enough to keep the desk
running and accumulating data.

### Phase D — per-fill P&L ledger closes the loop (already `#3`, still blocked)

Once #3 exists (blocked on #4, same as Phase C), the entire chain above
becomes verifiable rather than reasoned-about: did the Phase A/B computed
spread actually produce profitable fills, in a way #14's informal
three-incident tracking never could. Nothing new to plan here beyond what
#3/#4 already describe — listed for completeness, so this roadmap reads
as one coherent chain from "fix today's number" (#14, done) through
"prove it worked" (#3/#4, still blocked) rather than four disconnected
items.

**Status, 2026-09-19**: Phase A is built, tested, and deployed (see its
own section above) — both live processes restarted on Evan's go-ahead and
confirmed quoting with it. Phases B–D each depend on the one before and
remain not started.

## 16. Opportunistic bid-scanning (OBS) — built and tested 2026-09-20, NOT run with `--live`

Full detail lives in `basicswap/next_steps.md` #9 (scoping, API research,
build, and live-node verification) — this entry is a framework-level
pointer, not a duplicate. Summary: `basicswap/strategy/bid_scanner.py`
actively bids into *other* makers' live offers when priced better than a
target rate, instead of only posting our own offer and waiting — see
`ARCHITECTURE.md` §5's matching update for how this changes (and doesn't
change) the replenishment-hierarchy picture. Ships with its own audit trail
(`bid_scan_events`, kept independent of `live_quote_events` per Evan's
explicit requirement) and outcome reconciliation
(`reconcile_bid_outcomes()`), closing a real-outcome-tracking gap
`live_maker.py`'s own docstring had flagged as never built. 29 new tests,
144/144 passing across `strategy/tests/`; verified read-only against real
live BasicSwap offers. **Not run with `--live`** — a first trivial live run
needs Evan's explicit go-ahead, same gating posture as every other
live-capital escalation in this project (the first live offer, the first
trivial test swap, the volatility kill-switch). Don't redo this build; the
next action here is a live decision, not more code.

## 17. Accumulate-BTC proof trial + success bar `[BUILT 2026-09-28, trial not started]`

**The question the trial answers:** will anyone buy our XMR at a premium often
enough, and at a good enough price, that restocking it on Kraken would net BTC?
Kraken only fixes the restock side, so it's worth setting up only if the sell side
fills. Scored by `basicswap/strategy/proof_report.py` from the day
`restart_live_maker_btc.sh` first runs (it writes `~/coinswaps/proof_trial_start`).

**Setup:** `--objective btc` (see `basicswap/project_status.md`
2026-09-28): sell XMR at +1.8% above a 0.385 XMR reserve; restock as a maker at
about +0.4–0.6%, up to 0.985 XMR total. Optional one-time seed of the 0.6 XMR
working stock via `topup_xmr.py --target-xmr 0.985` (about +3% on 09-28, ~11.7k
sats), so the sell leg is tested from day one rather than after a rare restock fill.

**Metrics** (per trial window; all in `proof_report.py`):
- Sell-leg uptime and best-price share (offer_snapshots). Below 50% uptime the
  verdict is INCONCLUSIVE: a fill rate means nothing if the offer wasn't up.
- Sell fills per week.
- Kraken-restock margin per sell fill = edge vs. the mid at +1h (a realistic
  buy-back time) − Kraken depth cost at fill time (new `kraken_book_snapshots`,
  written by the poller) − 0.40% Kraken fee (assumed) − ~1,650 sats network and
  transfer fees (partly assumed).
- Restock-leg fills and their edge: if these come regularly and cheaply, Kraken
  may not be needed.
- Net sats vs. never trading over the window, including bids we sent.

**The bar** (minimum 4 weeks; PROVISIONAL before that):

| Verdict | Condition | What it means | Next step |
|---|---|---|---|
| PESSIMISTIC | < 0.5 sell fills/week, or mean margin ≤ 0 over ≥ 4 fills | a $5k pot loses money or makes ~nothing | drop the Kraken plan; decide whether to retire the desk |
| BASE | anything between | ~$100–300/yr at $5k | keep running small; Kraken not worth the setup |
| OPTIMISTIC | ≥ 2 sell fills/week AND ≥ 8 fills AND mean margin ≥ 0.8% | ~$2k/yr at $5k if the fill rate holds at larger size | Kraken account + API key (Evan), then size the capital |
| INCONCLUSIVE | sell offer live < 50% of cycles | the sell leg wasn't really tested | fix stock/uptime, extend the trial |

The report also prints a $/yr projection for a $5k pot (fill rate × $2,500 per fill
× mean margin). That assumes the fill rate holds at 5–10× our current size, which is
optimistic, so read it as a ceiling.

**Run:** `./run_fill_ledger.sh` (syncs fills, including sent bids), then
`python3 -m strategy.proof_report` from `basicswap/`. The fill-ledger launchd job
does the sync hourly once it's installed.

**2026-10-21 changes (mid-trial, on purpose):** sell offers now carry a 0.15 XMR minimum fill
(`--min-bid-amount`), and the report charges the Kraken transfer per 0.55 XMR batch and
size-weights the margin. See `basicswap/project_status.md` 2026-10-21.

**2026-10-21, after the reboot: Exolix restock live + real P&L.** `strategy/exolix_restock.py`
runs live every 15 min (Evan's go-ahead after a sane dry run). It refills the sell leg when
stock above the 0.385 reserve drops under 0.2 XMR, capped at +1.0% all-in vs. Kraken mid. By
10-23 it had completed 2 swaps: 0.00764 BTC -> 1.00357 XMR, +0.40% mean all-in. That's
cheaper than the +0.66% median the restock study measured, and no halt so far.
**Score the trial on the report's "Actual wallet P&L" line, not "Net position".** The fills
ledger is gross of network fees. The new line uses real wallet balances (`wallet_snapshots`,
written by the poller) less a baseline and recorded deposits/withdrawals
(`strategy/capital_flows.py`). Readings: 10-21 -4,389 sats (vs. +7,876 gross), 10-23
-8,364 sats (vs. +5,222 gross), i.e. ~400 sats of fees per fill. On 10-23 the size-weighted
sell margin was +0.09% over 21 fills (was +0.46% over 19). Still open: the node-health alert,
and Evan's call on judging by fill count instead of uptime.

**Restock side (added 2026-10-02):** `python3 -m venues.restock_cost` from
`market_maker/` shows the all-in cost to buy 0.5 XMR on each venue we poll
(BasicSwap, Bisq, Eigen ASB, Exolix, ChangeNOW) against Kraken. If a no-KYC
venue stays under Kraken's ~+1.0%, a CEX may not be needed for restocking.

## Explicitly not on this list

- **UTXO hygiene** (`ARCHITECTURE.md` §6) — not applicable at current capital
  scale (single fixed-size offer, not fragmenting a larger balance). Revisit if
  and when position sizing grows enough that a single swap could lock up most
  of available BTC.
- **CEX perpetual hedge** — the source PDF itself drops this (§6 of the v3.1
  doc's own "Considered and Dropped" table) for the same reason it doesn't fit
  here: custody/funding-rate/liquidation risk not worth it for small working
  buffers. No reason to revisit unless capital scale changes that calculus.

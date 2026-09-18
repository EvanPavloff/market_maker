# BasicSwap — Path to a Market-Making Go/No-Go Decision

Written 2026-09-15, right after the node went live. Assumes no prior context beyond
this directory — read `ARCHITECTURE.md` first (what BasicSwap is, the install, the
JSON API, the 4-phase rollout design) and `project_status.md` for exactly what's
built and running right now. This doc answers a narrower question: **what's actually
needed before we can honestly say whether market-making here is worth doing** — not
just "build Phase 2," but what has to be true first.

## Read this first: the one finding that motivates this doc

**Originally written 2026-09-15 when this node had zero live offers — no longer
true, and updated again 2026-09-17 now that both chains are fully synced.** The
network has a real, deep, two-sided BTC/XMR market (17-18 live asks, 15-17 live
bids, none ours, steady across a full day) and the observation window (§3) has now
run ~19.5 hours (239 polls, up from the earlier 5-poll preview). The paragraph
below is kept for historical context; see `project_status.md`'s 2026-09-17 entry
and this doc's §3/"What 'yes' actually requires" for the current picture — short
version: spread/depth data alone *still* isn't enough (that part held up), the
larger sample **reconfirms** the observed spread failing the go/no-go bar (median
2.059% vs. a required ~5.5-6.5% at the 24h-ceiling assumption), and the single
biggest lever on whether that holds up is still an unmeasured number (§4(a)) — but
it's no longer sync-gated, only gated on Evan's go-ahead to actually run a trivial
live test swap.

**Original 2026-09-15 framing:** The Phase 1 poller/analysis code (`strategy/`) is
built, unit-tested, and confirmed working end-to-end against the live node — but the
node is brand new, has zero live offers, and Monero is still mid-sync (Bitcoin
finished — see §1). So today's honest answer to "is this a sound strategy" is *we
don't know yet*, not *yes* or *no*.

And even once real offer-book data exists, that alone doesn't answer the question.
Three more categories of unknowns — costs, the lock-window price-risk, and whether
the automation mechanism itself behaves as expected — have to be filled in before a
real go/no-go call is possible. All four are listed below.

**Nothing below is blocked on sync anymore (resolved 2026-09-17) — the
`[BLOCKED ON SYNC]`/`[NOT BLOCKED — start now]` tags below are kept as a historical
record of what was gated on what.** The only thing left in this doc that needs a
real action rather than more passive research is §5's live half (exercising the
automation mechanism / an actual trivial test swap) — and that's gated on Evan's
explicit go-ahead, not on anything technical, since it moves real BTC/XMR.

## 1. Finish syncing (blocks §3 and the live-swap half of §5) `[DONE — both chains synced 2026-09-17]`

Bitcoin (pruned, fastsync-accelerated) **finished syncing** — confirmed live
2026-09-16 (967,213/967,213 blocks, `verificationprogress` ~1.0), and pruned itself
down to ~1.96GB on disk after completing (it had been ~14GB mid-sync — expected
pruned-node behavior, not a problem). **Monero also finished** — confirmed via
`~/coinswaps/monero/bitmonero.log` showing it caught up to the live chain tip
overnight (`Synced 3764043/3764043` at 2026-09-16 23:49 UTC, still matching tip
at 3764453/3764453 as of 2026-09-17 12:39 UTC, no lag). Both `bitcoind`/`monerod`
processes confirmed still running and healthy 2026-09-17. **The depth-trust and
live-test-swap caveats below no longer apply — offer-book data from this point
forward can be treated as real, currently-verifiable depth, not directional.**

The disk-space crisis this section used to warn about (68GB free, 93% used) is
**resolved** — the whole runtime moved to `/Volumes/Storage/coinswaps` during the
2026-09-16 incident (see `project_status.md`'s disk-space-crisis entry), which now
shows 736GB free (22% used) as of 2026-09-17. No longer a live risk to monitor
closely, though still worth a periodic glance given Monero's `lmdb` has no pruning.

No action needed here anymore.

## 2. Fix the reference-price feed `[DONE — built 2026-09-16]`

The Phase 1 smoke test found `strategy/storage.py`'s coingecko lookup (surfaced via
BasicSwap's own `/json/rateslist`) failing (`[["coingecko.com", "error", "6"]]`).
`analysis.py` currently falls back to `(best_ask + best_bid) / 2` when this happens,
which is fine once there's real book depth but is circular when the book is thin —
it can't tell you whether the *book itself* is mispriced relative to the outside
world. Worth a real fix (direct CoinGecko REST call bypassing BasicSwap's own
broken lookup, or a second independent source like a public Kraken ticker as a
cross-check) before trusting spread-vs-mid numbers from a thin market.

**Built:** `strategy/external_rates.py` — a direct CoinGecko REST call (USD-cross,
bypassing BasicSwap's own broken server-side lookup entirely) as the primary source,
plus a Kraken public-ticker cross-check for the pairs Kraken lists directly (XMR/BTC,
LTC/BTC so far — BasicSwap's other supported coins mostly aren't on Kraken). Stdlib
`urllib` only, no API key, matches `api_client.py`'s convention. Wired into
`storage.insert_rate_snapshot()` itself (new `direct_rate_snapshots` table, purely
additive — the existing `rate_snapshots` table/schema is untouched) rather than into
`poller.py` directly, and `analysis.py`'s `build_poll_snapshots` now prefers this new
direct rate for `reference_mid` over both the old BasicSwap-native lookup and the
`(best_ask + best_bid) / 2` fallback. **Why storage.py and not poller.py (2026-09-16)**: a
real, workspace-wide file-access bug (dataless/evicted iCloud placeholders under
this Desktop-synced repo, root-caused this same session to the disk-space crisis in
TASKS.md) made `poller.py` itself unreadable/unopenable all session, so it couldn't
be edited directly. Wiring it through the one function `poller.py` already calls
every cycle meant the fix took effect with zero `poller.py` changes needed.
**Correction, 2026-09-17: this was already done, this doc's "worth moving" caveat
was stale.** Re-checked while picking up this doc's open items — `poller.py` is
readable again (the iCloud-placeholder bug has cleared) and its `poll_once()`
already calls `external_rates.get_reference_rate()` directly, passing the result to
`storage.insert_direct_rate_snapshot()`; `storage.py` only keeps a
`TYPE_CHECKING`-guarded import of `external_rates` for the type hint, i.e. it's
already pure persistence. Unclear whether this was fixed same-session on 2026-09-16
(all three files' mtimes are within minutes of each other) and the doc simply never
got updated, or fixed later without a note — either way, no code change was needed
here today, just this correction. 8 new unit tests in
`strategy/tests/test_external_rates.py`, all passing (run via
`~/coinswaps/venv/bin/python3 strategy/tests/test_external_rates.py` — loaded by
file path rather than via the normal `python -m unittest discover`, for the same
poller.py-unreadable reason; that file's own docstring explains how to switch back
once it's not needed). The wiring itself was also verified end-to-end against a
throwaway in-memory DB (not just the mocked unit tests) — see `project_status.md`'s
2026-09-16 entry.

## 3. Run a real observation window (Phase 1, extended) `[RUNNING — 239 polls / ~19.5h as of 2026-09-17]`

**Started, not blocked after all** — the node turned out to already have a real,
deep, two-sided BTC/XMR market (18 live asks, 16-17 live bids, neither side ours)
well before Monero finished syncing, contradicting this doc's original "brand new,
zero offers" premise. `strategy/run_poller.sh --loop` has been running detached
(`nohup`, logging to `~/coinswaps/basicswap_poller.log`) continuously since
2026-09-16 15:03 and is still up as of 2026-09-17 — **239 polls, 100% two-sided**
(every single poll had live offers on both sides), median spread **2.059%**, mean
1.834%, averaging ~17.2 ask / ~15.5 bid offers per poll (`strategy.analysis`).
Still short of the 1-2 week bar this section calls for, but a real order of
magnitude past the earlier 5-poll preview and now entirely covered by the fully-
synced window (§1), so this data no longer carries the "directional, not final"
caveat the depth-trust concern used to attach. Not yet a launchd job — it only
survives as long as this machine stays up and nothing kills the process.

- **Track fills, not just snapshots — investigated 2026-09-17, real limitation
  found.** BasicSwap's JSON API does expose bid/swap-state data (`/json/bids`,
  `/json/sentbids` in `basicswap/js_server.py`, with fields like `bid_state`,
  `tx_state_a`/`tx_state_b`) — but this is a single-user, non-custodial node: those
  endpoints only ever return **this node's own** bids, since there is no global
  swap-history endpoint that would let a passive observer see *other* market
  participants' fills. Passive polling of `/json/offers` genuinely cannot
  distinguish "an offer disappeared because it filled" from "it disappeared because
  the maker cancelled/repriced it" for offers that aren't ours — that distinction
  is only observable by actually being a party to a bid (i.e., Phase 2 shadow-
  quoting or a live test swap), not by more passive polling. This was worth
  checking rather than assuming; the answer changes what more Phase-1-only time can
  actually deliver.
  - **Partial substitute finding, from the existing snapshot data (no code
    change needed — `expire_at`/`created_at` were already captured per offer):**
    of 1,535 resolved offers (excluding the 32 still-live at the end of the
    window), 963 (63%) disappeared within 5 minutes of their own `expire_at` (ran
    to natural expiry) and 572 (37%) disappeared much earlier — averaging only
    ~14.6 minutes of observed lifetime. That 37% is *consistent with* real fills,
    but equally consistent with active makers cancelling/repricing quotes
    quickly — the two are indistinguishable from this data alone, per the finding
    above.
  - **Real, independently useful side-finding from the same query:** observed
    offer *validity windows* (`expire_at - created_at`) across the live market
    average **~42 minutes** (min ~10 min, max 6h) — nowhere near BasicSwap's 24h
    UI ceiling. This is offer-posting duration, not the post-bid-acceptance lock
    window §4(a) needs (a live offer with no bid yet vs. an HTLC mid-swap are
    different things), so it doesn't answer §4(a) directly — but it's a real,
    directly-observed data point that real BasicSwap market makers here are not
    leaving multi-hour price exposure on the table by habit, which is directionally
    consistent with (not proof of) `economics.py`'s finding that the spread only
    clears if real exposure time turns out to be a few hours or less.
- **Watch the two-sidedness fraction**, already computed by `analysis.py` — a market
  that's one-sided most of the time (asks with no bids, or vice versa) can't
  actually be quoted against regardless of what the spread looks like on the polls
  where it is two-sided. **Answered by the data above: 100% two-sided across all
  239 polls so far** — this market has not been one-sided even once in the window
  observed. This is the strongest positive signal this project has found yet, even
  though the spread itself still doesn't clear the bar (see "What 'yes' actually
  requires" below).

## 4. Quantify costs and risks the poller alone can't tell you `[LIGHT RESEARCH DONE 2026-09-16 — numbers below are directional, not a precision model]`

These matter regardless of what the observation window shows — they set the bar the
observed spread has to clear, not just confirm a spread exists:

- **On-chain fees per swap leg.** No BasicSwap protocol fee, but real BTC and XMR
  miner fees for the HTLC setup/claim transactions on both legs of every swap.
  **Researched 2026-09-16 (web search, not a live fee-estimator wired in — treat as
  a snapshot, not a monitored number):** BTC network fees have been unusually low
  for ~3 months (median ~1 sat/vB, 90%+ of the June-September 2026 window at
  ≤2 sat/vB), and BTC itself was ~$76,000 same day. An HTLC-script-path spend runs
  larger than a plain P2WPKH send (bigger redeem script), so call it ~300-500
  vbytes per BTC-side tx; at 1-2 sat/vB that's roughly $0.25-$0.75/tx, and a full
  swap touches the BTC chain twice (lock + claim), so **~$0.50-$1.50 round-trip in
  today's fee environment**. Monero fees are separately negligible (~$0.02-$0.06/tx
  at 2026 rates) — BTC fees dominate this cost entirely. The real risk isn't
  today's number, it's that 1-2 sat/vB is itself a multi-month low; BTC fee rates
  have historically spiked 25-50x during congestion, which would put round-trip
  cost closer to $15-$75/swap — **any spread-sizing math should use a stressed fee
  assumption, not today's unusually cheap one.**
- **Price-drift-during-lock-window risk** — the risk `ARCHITECTURE.md` §6 already
  flags as structurally different from CEX/AMM market-making: swaps aren't instant
  fills, and the reference price can move against an open offer during the
  `lockseconds` window. Needs two real numbers, neither measured yet: (a) actual
  observed BasicSwap lock times for BTC/XMR swaps (depends on both chains'
  confirmation requirements, not just the configured `lockseconds` ceiling), and
  (b) BTC/XMR volatility over that specific timescale, to size a risk buffer into
  the spread rather than guessing at one. **(a) partially answered 2026-09-16**:
  read `~/coinswaps/basicswap/basicswap/ui/page_offers.py` directly — the offer
  form's own default/max lock window is **24 hours** (`"lockhrs": 24` default,
  UI-enforced max also 24h; `lockmins` alt path allows down to 10 minutes for
  faster-confirming pairs). So "the lock window" for sizing purposes is bounded at
  24h by BasicSwap itself, not an unbounded unknown — actual observed lock times
  for a real BTC/XMR swap (which depends on both chains' confirmation requirements,
  likely well under the 24h ceiling in practice) still needs a real swap to
  measure. **No longer sync-gated as of 2026-09-17 (§1 done)** — only gated on
  Evan's go-ahead to run one (§5's live half); live `/json/offers` also confirms no
  per-offer lock-time field is exposed publicly (checked 2026-09-17, see §3's
  fill-tracking finding), so this genuinely can't be answered without a real swap,
  not by more reading or polling. §3's new offer-validity-window finding
  (~42 min average, real market data) is a *related* but not equivalent proxy —
  it's how long makers leave a quote up before any bid, not how long an accepted
  bid's HTLC stays locked. **(b) researched
  2026-09-16 (web search)**: BTC's own annualized realized volatility has been
  running ~35-45% in 2026 (a 30-90 day range, historically low vs. BTC's ~80%
  long-run average); XMR is commonly cited around 2-3x BTC's vol on an absolute
  basis. Combining the two into an XMR/BTC cross (accounting for their positive
  correlation, historically ~0.4-0.7) puts the **pair's own annualized vol in the
  ~85-95% range**, i.e. roughly a **~5% one-day (1σ) move, ~10% two-day-equivalent
  or 2σ move over the full 24h lock ceiling** — an order of magnitude wider than a
  CEX spread would need to price in. Any offer held open near the full 24h window
  needs a spread meaningfully wider than CEX intuition would suggest, purely from
  this alone, on top of the fee floor above.
- **Griefing/DoS exposure.** Atomic-swap HTLCs are refundable after timeout, but a
  bad-faith counterparty can tie up a market maker's capital for the full lock
  window by bidding and never completing their side, at near-zero cost to
  themselves. **Partially answered 2026-09-16 via §5's automation-source read**:
  BasicSwap's own bid-acceptance code (`basicswap.py:shouldAutoAcceptBid`) already
  has real defenses beyond raw HTLC refund mechanics — `offer_budget_allows`,
  `validateOfferWalletFloor`, and a `total_bids_value_multiplier` cap all bound how
  much of an offer's total value can be tied up in flight at once, and hitting
  `max_concurrent_bids` or a wallet-floor/budget constraint sets the bid to a
  **temporary** "delay" state (`BID_AACCEPT_DELAY`) rather than accepting it — so a
  single bad-faith bidder can tie up at most one lock-window's worth of capital per
  concurrent-bid slot, not unlimited capital, as long as `max_concurrent_bids`/the
  budget multiplier are configured sanely (both are opt-in strategy settings, not
  hardcoded). Still not measured: a real estimate of how *often* this actually
  happens in practice on BasicSwap today (needs real observed data, i.e. §3), and
  the exact on-chain refund broadcast timing once a lock genuinely does expire
  (still needs a real swap to observe — sync-gated).
- **Capital / opportunity cost.** How much BTC and XMR inventory a meaningful
  market-making operation actually needs on both sides, and what that capital could
  otherwise earn sitting elsewhere (ties directly to `finance/crypto_yield/`'s
  yield-scanner work). **Methodology written 2026-09-17 — see §7 below** for how to
  turn the spread/cost/duration numbers already measured into an actual expected
  APR and compare it against `crypto_yield`'s real quoted yields. Still not a real
  number — the methodology's single biggest missing input (fill frequency) needs
  Phase 2 to measure, not more research.

## 5. Validate the automation mechanism itself (split)

BasicSwap's built-in auto-accept-bid automation strategies (`ARCHITECTURE.md` §5 —
the mechanism any real deployment would actually use, not something we'd be
bolting on) haven't been exercised at all yet, not even in a trivial/safe way.
Before trusting it with real capital: confirm it actually enforces price/quantity
bounds as configured, and look for surprising edge-case behavior (e.g. does it
respect `set_max_concurrent_bids` correctly under concurrent bids, does
`only_known_identities` behave as documented).

- **`[DONE — read 2026-09-16]`** Read `~/coinswaps/basicswap/basicswap/basicswap.py`'s
  `shouldAutoAcceptBid`/`evaluateKnownIdentityForAutoAccept` directly (plus
  `db.py`'s `AutomationStrategy` table and `js_server.py`'s
  `js_automationstrategies` handler) rather than just `ARCHITECTURE.md`'s
  API-doc-level summary. Confirmed real, specific behavior beyond what §5 there
  already said:
  - `set_max_concurrent_bids` (exposed as `opts["max_concurrent_bids"]`, default 1)
    **is enforced correctly** — counts non-completed active bids against the offer
    and rejects (temporarily) once at/over the cap. It's a same-DB-transaction
    check per bid evaluation, not a race-safe atomic reservation across truly
    concurrent evaluations — fine for BasicSwap's own apparently-sequential bid
    processing, but worth knowing it's not lock-free-safe if that ever changes.
  - `only_known_identities` **is enforced correctly**, via
    `evaluateKnownIdentityForAutoAccept`: an unknown bidder is rejected outright;
    a known one needs ≥1 prior successful swap and no more failures than
    successes. There's also a **per-identity override** not mentioned anywhere in
    `ARCHITECTURE.md` — `AutomationOverrideOptions.NEVER_ACCEPT`/`ALWAYS_ACCEPT` on
    a specific bidder address short-circuits the whole strategy check either way
    (a manual blocklist/allowlist mechanism, independent of the automation
    strategy config).
  - Two more real safety knobs `ARCHITECTURE.md` didn't mention:
    `exact_rate_only` (reject any bid whose rate doesn't match the offer's rate
    exactly, vs. accepting anything within the offer's own stated bounds) and
    `total_bids_value_multiplier` (caps *cumulative* accepted-bid value against an
    offer, separate from the concurrent-bid-count cap — see §4's griefing note).
  - Constraint failures are meaningfully split into **temporary**
    (`AutomationConstraintTemporary` → bid state `BID_AACCEPT_DELAY`, e.g.
    concurrent-bid cap hit, wallet balance temporarily too low — implies a retry
    path) vs. **permanent** (`AutomationConstraint` → `BID_AACCEPT_FAIL`, e.g. rate
    mismatch, unknown identity, amount below minimum — implies no retry). Useful
    to know which failure modes are retryable before assuming a rejected bid is
    gone for good.
- **`[BLOCKED ON SYNC]`** Actually exercising it — even with trivial amounts —
  requires a wallet that can construct and broadcast a real (tiny) swap, which
  needs both chains synced. Test with trivial amounts once Monero catches up, not
  skipped straight to real sizing.

## 6. Light non-quant research, still open `[LIGHT RESEARCH DONE 2026-09-16]`

- **Tax/record-keeping** — each swap is very likely a taxable disposal event
  (flagged in `ARCHITECTURE.md` §6). **Confirmed via general knowledge, not a
  BasicSwap-specific ruling** (no IRS guidance names atomic swaps specifically):
  under existing US crypto tax guidance, a crypto-to-crypto trade (which is what
  every BasicSwap swap is — BTC for XMR, not BTC for USD) is a taxable disposal
  event on the coin given up, same as a CEX trade would be — there's no
  crypto-to-crypto exemption. Still no record-keeping mechanism built (cost
  basis/proceeds per swap leg); needed before any real-capital Phase 3 swap, not
  before Phase 1/2. Not a substitute for actual tax advice before real money moves.
- **Regulatory posture** — light check only. **Researched 2026-09-16 (web
  search)**: Monero-specific delistings accelerated through 2026 — Coinbase
  delisted XMR/ZEC/DASH/ZEN 2026-03-30, Kraken delisted XMR in Canada/India
  2026-04, and 70+ exchanges total have delisted it since 2024; the EU's AML
  Regulation (2024/1624) will bar *regulated* crypto platforms from handling
  anonymity-enhancing coins from mid-2027. Every source is consistent that this
  targets **custodial/regulated venues specifically** (they can't satisfy
  provenance-tracing requirements for a privacy coin) — **no US, EU, UK, or
  Canadian law makes personal ownership or non-custodial P2P transacting illegal**,
  which is exactly what BasicSwap is. No regulatory blocker found for this
  project's personal-swap or market-making use case. One practical, non-regulatory
  implication worth flagging: with Coinbase no longer listing XMR, `coinbase_dca/`
  (this workspace's other real-money project) can't be a source of XMR directly —
  BasicSwap itself (swap BTC, bought on Coinbase, into XMR) may end up being
  Evan's own practical XMR on-ramp going forward, not just a trading venue.

## What "yes, build Phase 2" actually requires

Not just "the observed spread is greater than zero." The **sustained** two-sided
spread across the whole observation window (not a one-off favorable snapshot) has
to exceed: round-trip on-chain fees (§4) **plus** a volatility-based buffer sized to
the real observed lock window (§4) **plus** some minimum profit margin. If §3's data
shows the market is one-sided most of the time, that alone kills viability
regardless of what the spread looks like on the polls where it is two-sided.

**Built 2026-09-16: `strategy/economics.py`** turns this from prose into an actual
runnable comparison (`python -m strategy.economics --notional-usd N`) — observed
median spread vs. required spread across a today-vs-stressed fee scenario and a
1-sigma-vs-2-sigma vol buffer. First run (2026-09-16, 5 polls) and a 2026-09-17
re-run (239 polls) both used the 24h UI-ceiling assumption for the vol buffer and
both said "does not clear at any notional" — but that was always the placeholder
answer, pending a real measured exposure time. **2026-09-17, later the same day:
that real number now exists.**

## Real test swap completed 2026-09-17 — §4(a)'s number is no longer unmeasured

Evan ran a real trivial swap (bid into a live XMR-selling offer, buying ~0.386 XMR
for ~0.00264 BTC, offer had auto-accept enabled). Full timeline reconstructed from
`basicswap.log` (bid `000000006aac03bf...`, offer `000000006aac03ac...`):

| Event | Time (2026-09-17) |
|---|---|
| Bid submitted | 11:14:07 |
| Bid accepted (auto-accept, no human action needed on either side) | 11:16:27 |
| Coin A (BTC) lock tx submitted | 11:18:27 |
| Coin B (XMR) lock tx confirming — 5 retries logged waiting on confirmations (5/10 → 6/10 → 8/10 → 8/10 → redeemed) | 11:34:04 – 11:44:54 |
| Coin B lock spend tx submitted to Monero chain | 11:45:19 |
| Swap completed | 11:56:37 |

**Total: 42m30s from bid submission, 40m10s from acceptance, 38m10s from the BTC
lock tx.** The dominant driver is visibly Monero-side confirmation depth — the log
shows the redeem retrying specifically because "Chain B lock tx still confirming
X / 10," i.e. this swap type (a reverse adaptor-sig bid, BTC-for-XMR against an
XMR-sell offer) waits for ~10 Monero confirmations before the XMR leg can be
redeemed, and at Monero's ~2 min block time that alone is roughly the ~20 minutes
this swap actually spent in that retry loop — consistent with, not a coincidence
next to, the observed total.

**Re-running `strategy.economics` with this real ~0.67-0.71h exposure window
instead of the 24h ceiling changes the verdict — this no longer uniformly fails:**

- **$100 notional: still does not clear any scenario** — fee dominates too much at
  this size regardless of exposure time.
- **$1,000 and $10,000 notional: CLEAR today's-fee/1-sigma** (required spread
  1.3-1.4% vs. observed median 2.074%, on the 258-poll sample as of this run).
- **$10,000 notional also clears stressed-fee/1-sigma** (required 1.76% vs.
  observed 2.074%).
- **No notional clears any 2-sigma scenario** — a 2-standard-deviation price move
  still costs more than the observed spread earns, at every size tried.

**This is the first real "maybe, at the right size and risk tolerance" result
this project has produced** — a genuine change from every prior "does not clear
at any notional" run. Important caveats before treating this as the answer:
- **n=1.** One real swap's duration is not a distribution — confirmation timing
  has real variance (network conditions, which specific offer/swap-type gets
  bid), and this only measured one swap type/direction (reverse adaptor-sig,
  BTC buying XMR against an XMR-sell offer) out of several BasicSwap supports.
  A few more real swaps (ideally both directions) would turn this from "one data
  point" into an actual estimate with a sense of spread/variance.
- **The 1-sigma/2-sigma framing itself is a modeling choice, not a hard rule** —
  clearing 1-sigma but not 2-sigma means this is profitable on average but still
  carries real tail risk from a 2-standard-deviation price move during the
  ~40-min window; whether that's an acceptable risk/reward is a judgment call,
  not something the model resolves for you.
- **Capital/opportunity cost (§4's last bullet) is still unresearched** — a
  positive spread-vs-cost verdict at $10k notional doesn't by itself mean
  deploying $10k here beats what that capital could earn elsewhere
  (`finance/crypto_yield/`).

## 7. Computing expected market-making APR, and comparing it to crypto_yield

A spread-vs-cost verdict (above) answers "is a single cycle profitable" — it
doesn't answer "what return would this actually generate on deployed capital
over a year," which is the number that's actually comparable to
`finance/crypto_yield/`'s yield-scanner alternative. Here's the formula, what's
already measured vs. still missing, and why the missing piece matters more than
anything else on this page.

### The formula

```
edge_per_cycle_pct        = observed_median_spread_pct − round_trip_fee_pct(notional)
risk_adjusted_edge_pct    = observed_median_spread_pct − required_spread_pct(scenario)
                             (i.e. economics.py's own "clears/does not clear" margin —
                             use this instead of the raw edge for anything but an upper bound)

cycle_time_hours          = capital_lockup_hours_per_swap + idle_hours_waiting_for_the_next_fill
cycles_per_year           = 8,760 / cycle_time_hours

APR_simple (non-compounding) = edge_per_cycle_pct × cycles_per_year
APY_compound (profit redeployed each cycle) = (1 + edge_per_cycle_pct)^cycles_per_year − 1
```

`analysis.summarize_pair`/`economics.evaluate_pair` already compute every term
above except `cycle_time_hours`'s idle-time half — this is arithmetic on numbers
this project already has, not a new data source, except for the one piece
flagged below.

### What's measured vs. what's still just assumed

| Input | Status |
|---|---|
| `observed_median_spread_pct` | **Measured** — 258+ live polls, `strategy.analysis` |
| `round_trip_fee_pct` | Researched, directional (§4, `economics.py` defaults) |
| `capital_lockup_hours_per_swap` | **Measured once** — 0.708h from the real 2026-09-17 test swap. n=1; a real average needs a few more real swaps (see §3/"Real test swap completed" above) |
| **`idle_hours_waiting_for_the_next_fill` (= fill frequency)** | **Not measured at all.** This is the single biggest open input on this whole page — bigger than §4(a)'s lock-time question was before today's swap. Passive polling (Phase 1) fundamentally cannot measure it: it's "how often does *your own* offer get bid," which only exists once you're actually quoting (Phase 2 shadow-mode, or a real offer left up over an extended period) |

### Illustrative sensitivity — NOT a real estimate, fill frequency is assumed

Using the real measured 2026-09-17 numbers at $10,000 notional (raw edge 2.069%,
1-sigma-risk-adjusted edge 0.755%, `today`-fee scenario), compounding across a
range of *assumed* fill frequencies:

| Assumed fills | Cycles/yr | Raw-edge APY | 1-sigma-adjusted APY |
|---|---|---|---|
| 1/day | 365 | 176,000%+ | 1,457% |
| 3/week | 156 | 2,340% | 223% |
| 1/week | 52 | 190% | 48% |
| 1/month | 12 | 28% | 9.5% |
| 1/quarter | 4 | 8.5% | 3.1% |

### Why the top of this table is nonsense, and what that means

The compounding formula assumes the same edge is repeatable indefinitely at
whatever frequency you fill — real markets don't work that way. This project has
hit this exact failure mode before (`hyperliquid_bot`'s backtest producing a
>1e+275x return artifact before a real bug was found) — an absurd compounded
number is a signal to distrust the assumption feeding it, not a result to report.
Concretely here: today's real swap was a **take** (bidding into someone else's
already-posted offer) — that captures an existing quoted spread once, but
repeating it depends on other makers continuing to post offers wide enough to
profitably pick off, which a) isn't guaranteed to persist as a steady-state
opportunity and b) is a different economic activity from actually **making**
(posting your own offer and waiting to be filled at your own quoted rate, which
only pays off if and when someone bids it). The APY table above is only a
sensitivity check on the missing variable, not a forecast.

### Comparison to `finance/crypto_yield/`

Real quoted net yields from `finance/crypto_yield/ARCHITECTURE.md` (current as of
that project's last update):

| Asset | Venue | Net APY |
|---|---|---|
| USDC | Aave V3 Base | ~3.5% |
| USDC | Moonwell (Base) | ~4.1% |
| ETH | Coinbase cbETH (liquid staking) | ~3.0–3.1% |
| BTC | Aave V3 Base (cbBTC supply) | ~0.03% (structurally near-zero) |
| — | Realistic blended v1 | **~2–4%** |

For a fair comparison against the table above: `crypto_yield`'s numbers already
compound continuously at ~100% capital utilization — no idle time, unlike
market-making, where capital earns exactly 0% between fills. That idle-time
drag is entirely folded into the unmeasured fill-frequency variable above, so
it's already accounted for in principle, just not with a real number yet.
Reading the sensitivity table against this baseline: even the conservative
1-sigma-adjusted edge only needs roughly **1 fill/month** to match
`crypto_yield`'s ~2-4% baseline, and beats it comfortably at 1/week or better —
which is an encouraging shape, but the fill-frequency number that would confirm
or kill it is exactly what Phase 2 hasn't measured yet. Don't read this as "it
beats crypto_yield" — read it as "if BasicSwap fills roughly monthly or more
often at this size, it likely would."

### What turns this from a methodology into an actual number

1. A few more real test swaps (5-10, ideally both directions) to replace the
   n=1 `capital_lockup_hours_per_swap` with a real average and a sense of
   variance, not a point estimate.
2. **A real posted offer, left live over an observation window** — post a real
   offer (or a few) and observe how often it actually gets bid over a real window
   (the same 1-2 week bar §3 already calls for). Renamed from this doc's earlier
   "Phase 2 shadow-mode quoting" label to avoid colliding with §8's dry-run
   `strategy/quoter.py` ("shadow quoter") — that tool computes what rate you'd
   quote and how often you'd reprice, using zero real capital, but it fundamentally
   cannot measure this number (fill frequency needs a real counterparty bidding a
   real offer — see §3). This is the one number nothing built so far substitutes
   for, and it's real-capital/real-offer territory, gated on Evan's explicit
   sign-off per `ARCHITECTURE.md` §6.
3. ~~Once both exist, this formula is a direct, small addition to
   `strategy/economics.py` (not yet built) — an `expected_apy()` function taking
   a measured fill frequency instead of an assumed one, reusing every other
   input the module already computes.~~ **Built 2026-09-17**:
   `strategy/economics.py`'s `evaluate_pair()` now takes an optional `lock_hours`
   param (sizes the vol buffer off a real measured exposure window via the
   already-existing `vol_buffer_pct_for_hours` helper, instead of the hardcoded
   24h-UI-ceiling default — turns the "Real test swap completed" section's by-hand
   re-run into a repeatable call) and a new `expected_apy()` function implements
   this section's formula directly (raw edge = spread − fee%; risk-adjusted edge =
   spread − the scenario's full required-spread; both projected to simple-APR and
   compounded-APY given an assumed `fills_per_year`, with a `-1.0` floor guard on
   the compounding rather than letting a deeply negative edge blow up — the same
   failure class as the `hyperliquid_bot` >1e+275x artifact flagged above). Wired
   into the CLI: `--lock-hours`/`--fills-per-year` (repeatable)/`--apy-scenario`.
   8 new unit tests (40 total in `strategy/`), all passing. **Still just a calculator, not a new
   measurement** — running it live (`--lock-hours 0.708 --fills-per-year 365 156
   52 12 4`) against the 268-poll sample as of 2026-09-17 reproduces this
   section's table almost exactly (e.g. 1/week: 191.6%/49.0% raw/risk-adjusted APY
   here vs. the by-hand 190%/48% above — the small drift is just more polls
   accumulating, not a discrepancy), confirming the formula was transcribed
   correctly. Items 1 and 2 above are still open and are what would make the
   output a real number instead of a sensitivity check.

## 8. Shadow quoter — dry-run repricing simulator, built 2026-09-17

Answers a real operational question raised mid-review: BasicSwap's JSON API has no
"edit offer" route (confirmed by reading `js_server.py` — only `POST /json/offers/new`
and `revokeoffer`), so "maintaining the correct rate" over time can only mean
**revoke the old offer and post a new one**. Checked what that actually costs by
reading `revokeOffer()` directly (`basicswap.py:4519`): it's a pure off-chain SMSG
message broadcast, no on-chain tx, no fee, no capital movement — same for posting.
So a poll-the-reference-price/revoke-and-repost-on-drift loop is architecturally
cheap, not something to avoid for cost reasons.

Also checked whether BasicSwap's own `rate_negotiable` offer flag is a shortcut
around this (let a bidder counter-propose a rate instead of you reposting) —
**it isn't, and using it carelessly is actively dangerous**: the only rate guard
on the auto-accept path is `exact_rate_only` (`basicswap.py:11827`), which
**defaults to `False`**. `rate_negotiable=True` without explicitly also setting
`exact_rate_only=True` means a counterparty's proposed bid rate is accepted
regardless of price — checked against budget/wallet-floor/concurrent-bid caps only,
never against price. Any real deployment should stay `rate_negotiable=False` with
`exact_rate_only=True`, and handle repricing entirely via revoke+repost.

**Built `strategy/quoter.py`, a dry-run-only simulator of that loop** — this is
actually `ARCHITECTURE.md`'s *original* Phase 2 definition ("compute what our
strategy would have quoted... still posting nothing"), which had drifted out of
sync with this doc's own later use of "Phase 2" to mean posting a real offer (see
item 2 below — that's a different, real-capital thing). Each cycle it pulls the
real external reference price (`external_rates.py`, the same source `poller.py`
uses) and, for both sides of a pair, computes a target rate
(`reference_mid * (1 ± half_spread_pct)`) and compares it to the last *simulated*
quote logged for that side (`storage.py`'s new `simulated_quote_events` table,
append-only, same convention as `offer_snapshots`): no prior quote → log "post";
drift past `--reprice-threshold-pct` → log "reprice"; quote older than
`--offer-valid-hours` with no drift → log "expire_repost"; otherwise nothing is
written. **`api_client.py` gains no write methods from this** — there is no code
path in this module capable of calling BasicSwap's real `/json/offers/new` or
`/json/revokeoffer`; that boundary (the module's own docstring already states it)
is untouched. `strategy/quoter.py --summary` reports how often the simulated quote
actually needed to move (mean/median gap between reprices) — a real, useful number
for sizing `--reprice-threshold-pct`/`--offer-valid-hours` later, but **not** a
fill-frequency measurement (§3 already found real fill frequency can't be observed
without a real offer meeting a real counterparty). 10 new unit tests (50 total in
`strategy/`, all passing). Verified live against the running node (first real cycle
logged real `post` events for both sides at the real reference mid,
`~/coinswaps/basicswap_observations.db`'s `simulated_quote_events` table) and
started running detached (`run_quoter.sh --loop`, `nohup`, logging to
`~/coinswaps/basicswap_quoter.log`) alongside the existing poller — same
not-a-launchd-job caveat as `run_poller.sh` (§3): survives independently of any
Claude session, not a machine restart.

## Concrete next actions, in order

**Done 2026-09-16 — everything that didn't need Monero sync to finish:**

1. ~~Fix the reference-price bug in `strategy/storage.py` (§2)~~ — **done**:
   `strategy/external_rates.py` built + wired, 8 new tests passing. See §2 for the
   one caveat (wired via `storage.py`, not `poller.py`, due to an unrelated
   file-access bug — worth a small refactor once that clears).
2. ~~Research on-chain fee overhead, real BTC/XMR volatility over realistic
   lock-window timescales, griefing/DoS/refund-timeout mechanics, and capital
   opportunity cost (§4)~~ — **light research done**, directional numbers only
   (fee floor, vol-based buffer size, griefing bound from real source-reading);
   capital/opportunity-cost sizing still genuinely open, needs a Phase 2 design.
3. ~~Read BasicSwap's automation-strategy source to confirm what the config flags
   are actually implemented to do (§5, read-only half) and knock out the light
   tax/regulatory research (§6)~~ — **done**, see §5/§6 above for the specific
   findings (including two safety knobs and a per-identity override
   `ARCHITECTURE.md` hadn't documented).

**Immediate, unblocked — do this first:**

4. ~~Delete `~/coinswaps.pre-migration-backup` (123GB) from the internal disk~~ —
   **done 2026-09-16**, after re-verifying it was safe: `~/coinswaps` is a symlink
   to `/Volumes/Storage/coinswaps`, every running process (`monerod`, `bitcoind`,
   `particld`, `basicswap-run`, the poller) resolves paths through that symlink
   (confirmed via `ps aux`), and `lsof +D` on the backup directory showed zero open
   file handles — nothing live was reading it. `rm -rf` completed; `basicswap-run`
   verified still healthy immediately after (web UI 302, all processes still up).
   `df` didn't show the +123GB immediately — held by local Time Machine snapshots
   (`tmutil listlocalsnapshots`), normal APFS behavior; macOS reclaims those
   automatically under space pressure, not something this project needs to manage.

**Done 2026-09-16, ahead of schedule — didn't actually need to wait for sync:**

5. ~~Start `strategy/run_poller.sh --loop` and leave it running~~ — **started**,
   running detached, logging to `~/coinswaps/basicswap_poller.log` (see §3). Needs
   1-2 weeks untouched before its data is trustworthy as "sustained," and isn't a
   launchd job yet — don't let the terminal/session illusion fool you, it survives
   independently of any particular Claude session but not a machine restart.
   Also built the same day: `strategy/economics.py`, the actual go/no-go
   calculator ("what 'yes, build Phase 2' actually requires" section above) — and
   found/fixed two real bugs along the way (a coin-name key mismatch that would
   have made `analysis.py` silently report zero data forever even with a fully
   active market; an SSL cert-verification failure silently killing every
   external reference-rate call) — see `project_status.md`'s 2026-09-16 entry for
   the full detail on both.

**No longer blocked on sync — item 6 is done, item 7 partially:**

6. ~~Exercise the automation mechanism with trivial live amounts (§5, live half)~~
   — **done 2026-09-17**: real trivial swap completed (42m30s bid-to-completion),
   auto-accept confirmed working on a real bid, real lock/redeem mechanics
   observed directly. See "Real test swap completed" above for the full timeline
   and what it changes.
7. **Partially done.** The observation window is still running (268+ polls as of
   2026-09-17 afternoon, still short of the 1-2 week bar — `run_poller.sh --loop`
   confirmed still alive) and a real measured exposure time now exists (from #6)
   — re-running `strategy.economics` with it flips several scenarios from "does
   not clear" to "clears" at $1k-$10k notional/1-sigma (see above), and that
   re-run is now a repeatable CLI call (`--lock-hours`) rather than by-hand math
   — see §7's "Built 2026-09-17" note. **Still open before an actual go/no-go
   call**: this is n=1 on the duration measurement (a few more real swaps,
   ideally both directions, would turn this into a real estimate rather than one
   data point — needs Evan's go-ahead, moves real BTC/XMR), the observation
   window hasn't hit its 1-2 week bar yet, and capital/opportunity-cost sizing
   (§4's last bullet) is still unresearched. Phase 2 (shadow-mode quoting) still
   requires clearing all of that, plus Evan's explicit sign-off per
   `ARCHITECTURE.md` §6 — nothing above authorizes posting a real automated
   offer or moving more capital than this one trivial test swap.

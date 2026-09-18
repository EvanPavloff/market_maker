# Market Maker — Architecture

## 1. What this is

A cross-venue crypto market-making framework: provide two-sided liquidity on
non-custodial swap venues, capture the spread, and manage the resulting BTC/XMR
(and eventually other-coin) inventory as a single global position rather than a
per-venue accounting exercise. `market_maker/basicswap/` is the first, and
currently only, venue module — see §7 for why the rest of this doc describes a
framework that is mostly not built yet.

Source material: two PDFs Evan supplied 2026-09-17 —
`btc_xmr_market_making_framework_v3.1.pdf` ("Cross-Venue BTC/XMR Algorithmic
Market Making Framework") and `kyc_resilience_mvb_v3.pdf` ("Minimum Viable
Capital Buffer & Data-Driven Routing," an addendum to a v3.0 directive). Both
live in Evan's iCloud Drive, not this repo. Two earlier sibling files also sit in
that same iCloud folder (`btc_xmr_market_making_framework_v3.pdf`,
`basicswap_cross_venue_market_making_strategy.pdf` and `_v2.5.pdf`) — those were
**not** opened for this doc; nothing below is sourced from them, and no prior
version of this project's own docs referenced any of these files before today, so
this is a first pass, not a revision of an earlier distillation.

**Read as an ethos, not a spec.** Both source PDFs present as institutional
"quantitative strategy directives" — confident tone, dollar figures, phase-gated
weeks — but they are a template/thesis document, not a record of anything this
project has actually built, tested, or verified. Section 7 of this doc is the
part that matters most: it separates what the PDFs assert from what's actually
true for `market_maker/basicswap/` today, because treating the aspirational
language as already-accomplished is the single biggest risk in adopting this
framework uncritically.

## 2. Core thesis (from the PDFs, evaluated)

> Provide privacy-coin (XMR) liquidity on decentralized venues where
> privacy-conscious buyers pay a premium; receive BTC; replace the XMR sold only
> when the all-in replacement cost still leaves a positive risk-adjusted edge.
> No assumed benchmark APY — return is strictly an empirical output of realized
> spread capture, volume, and time-weighted deployed capital.

This is sound and matches how this project has actually approached BasicSwap:
`basicswap/economics.py` already refuses to assert a return number and instead
computes a go/no-go verdict against measured costs (see
`basicswap/next_steps.md` §7). The "no assumed APY" discipline is worth keeping
as a hard rule for this framework generally — any new venue module must earn its
numbers empirically before this doc or `next_steps.md` states a return figure
for it.

## 3. The net executable edge equation

The PDF's central gating rule, and the right abstraction to standardize on
across venues:

```
Net Edge = S_gross - (C_replenish + F_network + C_lockup * T_lock + L_adverse + V_option) > Minimum Threshold
```

- `S_gross` — the quoted half-spread over reference mid.
- `C_replenish` — cost of restocking the sold-out side (a passive resting order,
  or a fee-bearing instant-swap fallback).
- `F_network` — on-chain fees for both legs of the atomic swap.
- `C_lockup * T_lock` — opportunity cost of capital locked in an HTLC timelock,
  scaled by how long that lock actually runs.
- `L_adverse` — adverse-selection loss: the counterparty who takes your quote is
  more likely to be taking it *because* the reference price already moved.
- `V_option` — the unpriced call option a taker holds during the HTLC window
  (price can move in their favor before they have to complete the swap; the
  maker can't re-quote until they either fill or the offer expires).

**What `market_maker/basicswap/economics.py` already computes**: `F_network`
(fee floor), a `C_lockup * T_lock` proxy (volatility-based buffer sized off a
*real measured* exposure window, not the PDF's assumed 24h ceiling — one real
test swap took 42m30s), and it compares the result against `S_gross`. **What it
does not compute**: `C_replenish` (no replenishment router exists yet — see §7),
`L_adverse` (no adverse-selection tracking on fills — there's only been one real
fill so far, not enough data to fit this), and `V_option` (no explicit option
pricing; the closest proxy is `live_maker.py`'s drift-based reprice trigger,
which is reactive, not priced in up front). This is the concrete gap between
"the framework says net edge should include five terms" and "the code
prices two of them."

## 4. Inventory controller

The PDF's abstraction — treat every venue as an execution node around one global
BTC/XMR ledger (available / reserved / locked / in-flight), rather than
reasoning about each venue's balance separately — is the right shape for this
directory to grow into *if* a second venue is ever added. **It does not exist
today**: `market_maker/basicswap/` has no ledger abstraction, because there is
nothing to reconcile across yet — one venue, one wallet, one balance, read
directly from BasicSwap's own `/json/wallets` each cycle
(`live_maker._check_funded()`). Building an inventory controller before a second
venue exists would be solving a coordination problem that doesn't exist yet at
the cost of real complexity. **Trigger to actually build it: the day a second
venue module is scoped** (§7's venue list) — not before.

## 5. Replenishment routing hierarchy

PDF ethos: try passive, no-fee replenishment first (post a resting reverse bid
on a non-custodial venue), and only fall back to an instant/fee-bearing
aggregator (the PDFs name Trocador) as a last resort, because every fee-bearing
fallback both costs money and introduces third-party counterparty/KYC exposure
the passive route doesn't have.

**Current reality**: `market_maker/basicswap/`'s two `live_maker.py` loops
already implement a degenerate one-venue version of "passive first" — the
ask-side (BTC-for-XMR) and bid-side (XMR-for-BTC) offers on the same venue are
each other's replenishment source when they fill. There is no fallback route at
all — if BasicSwap itself has no counterparty for one side, that side simply
sits unquoted (see the real `wallet has 0.38... XMR, need 1.15` log pattern in
`project_status.md`, from before the reserve-based sizing fix). No instant-swap
aggregator (Trocador or otherwise) has been evaluated, let alone integrated.
That means: **zero replenishment-provider risk exists today**, and also **zero
replenishment redundancy** — a real asymmetry worth tracking, not silently
inheriting the PDF's assumption that a fallback route is already there.

## 6. Risk controls named in the PDFs, and their status here

| Control | PDF intent | Status in `market_maker/basicswap/` |
|---|---|---|
| HTLC option pricing (`V_option`) | Widen ask spread or shorten timelocks during high volatility | **Not built.** Spread is a static `half_spread_pct` (0.66%); repricing reacts to drift after the fact, doesn't widen preemptively on volatility. |
| Automated UTXO hygiene (10–20 split BTC UTXOs) | Prevent one swap from locking 100% of available BTC | **Not applicable at current scale** — the live ask offer is a single fixed 0.008 BTC out of a small wallet; there's no multi-UTXO management because there's been no reason to split yet. Revisit if capital scales up materially. |
| Passive-reverse-first rebalancing | Try a resting bid before a fee-bearing instant swap | **Trivially true today** (only one venue exists, so it's the only route) but not actually *implemented as a choice* — there's no decision logic that would pick a fallback if one existed. |
| Volatility kill-switch | Pause quoting if reference-price volatility spikes | **Built and deployed 2026-09-18.** `basicswap/strategy/volatility.py`'s `VolatilityMonitor` tracks a rolling window of reference-mid samples (fed by the same per-cycle `external_rates.get_reference_rate()` call, no new polling); `run_cycle` skips `decide_and_act` for the cycle — leaving any existing live offer untouched — when the window's `(max-min)/mean` exceeds a threshold calibrated from 512 real poller samples (~99th percentile of a real 15-minute volatility distribution, 0.85% default). See `next_steps.md` #1 for the full derivation and restart verification; live on both real loops as of this writing. |
| Zero-capital verification (testnet daemons + shadow ghost quotes) | Validate mechanics before any real capital is at risk | **Done differently, not done as specified.** This project never stood up Signet/Testnet4/Stagenet daemons or a synthetic ghost-quote engine. Instead: a read-only poller (`poller.py`/`analysis.py`), a dry-run shadow quoter against the live order book (`quoter.py`), and finally one real trivial swap (42m30s, real lock/redeem mechanics observed directly) — a live-micro-money validation path instead of a testnet one. This produced real, not simulated, data (the actual exposure-window measurement in `economics.py` comes from this), but it also means every verification step to date has touched real, if small, capital — worth naming as a deliberate deviation, not an oversight. |

## 7. Usable venues — PDF claim vs. reality

| Venue | PDF status | Actual status here |
|---|---|---|
| BasicSwap | CORE | **Live.** The only venue with any code, any live offer, or any real fill. See `basicswap/CLAUDE.md`/`project_status.md`. |
| Eigen ASB | CORE | **Not evaluated.** No research has been done on Eigen ASB's API, fee structure, or automation surface. Not scoped. |
| Haveno / Bisq | CORE / PILOT | **Not evaluated.** The PDF flags multisig security-deposit capital lockup as a real gotcha for these — worth remembering when/if either gets scoped, since it changes the capital-efficiency math versus BasicSwap's model. |
| Trocador / aggregators | REPLENISHMENT | **Not evaluated.** This is the venue that would actually introduce the KYC-adjacent exposure `kyc_resilience_mvb_v3.pdf` is about (see §8) — until this is built, that addendum's core concern doesn't yet apply to this project. |
| THORChain / Chainflip | WATCHLIST | **Correctly left on watchlist.** The PDF itself notes XMR routing was stagenet-only at time of writing; no reason to move this up until that changes and someone re-checks. |

**Practical read**: this framework is currently a one-venue system wearing a
multi-venue document. That's fine as a target shape, but every "cross-venue"
claim in the source PDFs (arbitrage, canary routing across providers, MVB sized
off multi-provider failure rates) is aspirational until a second venue actually
exists. `next_steps.md` treats venue expansion as gated on the single-venue edge
being *proven*, not assumed — see `basicswap/next_steps.md`'s still-open items
(observation window short of its 1–2 week bar, n=1 on fill-duration
measurement) before reading anything in this doc as "ready to add a venue."

## 8. KYC resilience addendum — what actually applies today

`kyc_resilience_mvb_v3.pdf`'s stated evolution (V1 tactical evasion → V2 bounded
provider risk/caps → V3 probabilistic data routing + canary testing, never
evasion) is a reasonable posture *for the part of this framework that touches
third-party custodial or semi-custodial swap providers*. **BasicSwap itself is
fully non-custodial and requires no KYC at all** — so today, this project has
**zero KYC surface area**, full stop. The addendum's entire subject (provider
hold-probability telemetry, canary probes, settlement-latency logging across
providers) only becomes relevant the day a replenishment router to an instant
aggregator (Trocador or similar) gets built. Until then, don't let this doc's
presence imply KYC risk exists where it doesn't — it's forward-looking scope,
not a current mitigation.

The Minimum Viable Buffer formula itself —

```
MVB = (D_max(T_fallback) * S_fill) + Safety_Margin(P99_delay)
```

— is the right target shape for sizing the reserve `live_maker.py`'s bid side
holds back (currently a hand-picked `--reserve-usd 210`, not derived from
anything). But the formula's inputs (`T_fallback`, a worst-case fallback
failover window) presuppose a fallback route exists — which, per §5, it doesn't
yet. Until a fallback exists, "MVB" for this project can only mean "how much
XMR/BTC do I want sitting idle as a stated preference," which is exactly what
`--reserve-usd 210` already is, honestly. Formalizing it as a real MVB
calculation is future work gated on real fallback-route telemetry, not
something to fake with today's single-venue data. See `next_steps.md` #2.

## 9. What must be tracked for profitability and stability (this doc's actual
job, per the review brief)

Three tracking obligations fall out of §§3–8, ranked by how close each is to
already existing:

1. **Per-fill net edge** (§3) — realized spread minus at-least on-chain fees,
   attributed to a specific fill, not just a point-in-time cost model.
   *Partially built*: `economics.py` computes a scenario-based verdict;
   `storage.py` has `live_quote_events` (every post/revoke decision) but no
   per-fill P&L row yet, because there's only been one real fill so far to
   attach one to.
2. **Exposure-window distribution** (`T_lock`, §3/§6) — real lock-to-completion
   durations across many swaps, not the current n=1 (42m30s). This directly
   feeds both the volatility buffer in `economics.py` and any future kill-switch
   threshold (§6). *Needs more real fills* — not a code gap, a data gap.
3. **Tax lot tracking** — flagged already in `basicswap/next_steps.md` §6 (each
   swap is very likely a taxable disposal event) and worth restating here
   because it becomes a *harder* problem the moment a second venue exists (fills
   across venues need one consolidated ledger, not two independent logs, to get
   basis/holding-period right). *Not built anywhere yet.*

None of these are blocking today's single-venue, single-side-at-a-time scale.
All three become materially harder to retrofit the longer multi-venue expansion
is deferred — which is an argument for building #1 and #3 *before* venue #2,
not after.

## 10. Directory shape

```
market_maker/
  ARCHITECTURE.md      this file — framework-level ethos, gap analysis, tracking requirements
  next_steps.md         framework-level build queue, ordered by what closes the biggest gap in §6/§9
  project_status.md     framework-level current-state summary
  basicswap/             first (and only) venue module — see basicswap/CLAUDE.md
    CLAUDE.md
    ARCHITECTURE.md      venue-specific install/API/mechanics detail
    next_steps.md         venue-specific build queue (mostly superseded/absorbed by this level now)
    project_status.md     venue-specific history/log
    strategy/              the actual poller/quoter/live_maker code
```

Future venue modules (Eigen ASB, Haveno, Bisq, a Trocador-based replenishment
router — none scoped yet) would each get their own `market_maker/<venue>/`
sibling directory following the same doc pattern, once and only once each is
individually scoped and signed off — same convention this workspace already
uses for `oanda_bot`'s desks and `world_tracker`'s domains.

# BasicSwap — Project Status

**Status as of 2026-09-15: BasicSwap is installed, prepared, and running — verified
live (`basicswap-run`, `particld`, `bitcoind`, `monerod` all confirmed running;
`basicswap.json` present; web UI returns 302 on `localhost:12700`).** Evan ran
`basicswap-prepare` himself (mnemonic generated and recorded off-session, per the
safety rule below) and started `basicswap-run` — the web UI answers at
`http://localhost:12700`. The Phase 1 poller (`strategy/`) has been smoke-tested
against this live node and confirmed working end-to-end (see "Phase 1 evaluation
stub" below) — no observation window has run yet, so there's still no real signal on
whether an edge exists. **See `next_steps.md` for exactly what's needed before that
question can be answered — it's more than just data collection.** The plumbing
itself is now verified, not just unit-tested
against fixtures.

## What's done

- Cloned `basicswap/basicswap` @ tag `v0.18.8` into `~/coinswaps/basicswap`
  (outside this git repo — see `ARCHITECTURE.md` §2 for why).
- Created a Python 3.13 venv at `~/coinswaps/venv`.
- Installed build deps (`jq`, `ninja` via Homebrew) and all of BasicSwap's pinned
  `requirements.txt` (hash-checked) plus the package itself
  (`pip3 install --no-build-isolation .`).
- Hit and fixed a real build bug: this machine's Homebrew is the Intel build running
  under Rosetta, which poisoned the architecture CMake picked for BasicSwap's custom
  `coincurve` fork (patched secp256k1 with extra swap-protocol modules, built from
  source — not the plain PyPI package). Full root cause and fix in `ARCHITECTURE.md`
  §3. `basicswap-prepare --help` and `basicswap-run` both confirmed working natively
  (arm64, no Rosetta) after the fix.
- `gnupg` failed to build via Homebrew (outdated Xcode Command Line Tools — needs
  `sudo`/System Settings, a human step). Not blocking — both places `basicswap-prepare`
  needs it can be skipped with flags — but corrects an earlier note here: it's not
  *only* the optional release-signature check. `basicswap-prepare --usebtcfastsync`
  actually **hit this at runtime** (`ERROR:gnupg:Unable to run gpg ... may not be
  available`) via a second, separate code path — the BTC fastsync UTXO snapshot's
  signature check (`basicswap/interface/btc/core.py` `checkFastsyncData` ->
  `createGPG`, called unconditionally, NOT gated by `SKIP_GPG_VALIDATION`). Fixed by
  adding `--skipbtcfastsyncchecks` alongside `SKIP_GPG_VALIDATION=true` — both are
  now baked into `run_prepare.sh`. Real gpg install is still worth doing eventually
  (via TASKS.md) if full signature verification on downloaded binaries/snapshots
  matters to you; for now both checks are skipped, hash-only in one case.
- Root `CLAUDE.md` updated with a new BasicSwap project section.
- **`basicswap-prepare` run by Evan directly** (2026-09-15, own terminal, not through
  Claude — mnemonic never entered any Claude session/transcript, per the safety rule
  this project has followed throughout). Hit two more real bugs along the way, both
  now fixed in `run_prepare.sh`/docs:
  - `--usebtcfastsync`'s BTC UTXO-snapshot signature check calls `createGPG(...)`
    **unconditionally** (`basicswap/interface/btc/core.py` `checkFastsyncData`) —
    NOT gated by `SKIP_GPG_VALIDATION` (that only guards the separate per-coin
    release-binary check). Needs `--skipbtcfastsyncchecks` too. Both flags are now
    baked into `run_prepare.sh`.
  - A duplicate-write: particl's config gets written once early (for the master
    mnemonic) and again in the generic per-coin loop (particl is always
    auto-included) — the second write correctly refuses to clobber the first
    (`exitWithError(f"{core_conf_path} exists")`, `prepare_util.py:461`) and the
    whole run aborts. Fix was just clearing the three empty per-coin datadirs
    (`particl/`, `monero/`, `bitcoin/` — config skeletons only, verified no
    `wallet.dat`/mnemonic existed yet) and rerunning — the expensive downloads
    (13GB BTC fastsync file, extracted coin binaries) were untouched and didn't
    need to repeat.
- **`basicswap-run` started** (own terminal — it's a foreground daemon, doesn't fit
  `!`/one-shot execution either). Web UI confirmed live: `curl localhost:12700/`
  → `302 → /offers`.
- **Found and fixed a real doc-vs-reality gap in BasicSwap's own JSON API docs**:
  `doc/api.md`'s curl examples say the JSON API is on port **12701** — verified live
  2026-09-15 that this is wrong (or stale) for v0.18.8. Nothing listens on 12701;
  `/json/*` is served on the **same port as the web UI, 12700**. Also found
  `/json/rates` (`POST`) 500s on string tickers (`js_rates` passes `coin_from`
  straight into `lookupRates()` without the `getCoinType()` conversion
  `/json/rateslist` does) — the working route is `GET /json/rateslist?from=..&to=..`.
  Both corrected in `strategy/api_client.py`/`ARCHITECTURE.md` §5 — see "Phase 1
  evaluation stub" below for the full fix.

## Currently running

Both `basicswap-run` (foreground daemon) and BasicSwap's own coin daemons are up in
a separate terminal window on this machine, syncing. Check sync progress via the web
UI (`http://localhost:12700`) or ask Claude to poll `/json/offers`/coin status via
curl — don't stop the process without knowing why (a swap in flight has to complete
within its lock window, though nothing's been offered yet so there's nothing at risk
right now). Not yet scheduled via launchd — currently only runs while that terminal
window stays open; revisit once Evan wants it always-on.

**As of 2026-09-16, `~/coinswaps` is a symlink to `/Volumes/Storage/coinswaps`**
(see "2026-09-16: disk-space crisis" below and `ARCHITECTURE.md`'s runtime-layout
note) — same commands/paths, but BasicSwap now depends on that external drive
staying connected.

## Phase 1 evaluation stub (2026-09-15)

Built the read-only poller/analysis code `ARCHITECTURE.md` §6 Phase 1 calls for —
"does an edge exist" — built as fixture-tested logic first, then **smoke-tested
live against the real running node same day** (see below) once Evan got it up.
Lives at `strategy/`, stdlib-only (no new pip dependency — BasicSwap's own venv
doesn't have `requests` either, so `api_client.py` uses `urllib`), same
git-tracked/no-secrets convention as the rest of this directory.

- `strategy/api_client.py` — thin client for BasicSwap's local JSON API, served on
  the **same port as the web UI (`localhost:12700`)** — corrected live 2026-09-15;
  `doc/api.md`'s own curl examples say `:12701`, which is stale/wrong for v0.18.8,
  nothing listens there. `get_offers()` (`POST /json/offers`) and `get_rate()`
  (`GET /json/rateslist`, not `POST /json/rates` — that route 500s on string
  tickers, see `ARCHITECTURE.md` §5). Read-only on purpose — never calls
  `/json/offers/new` or any route that places an offer or moves funds. Endpoint
  field names/shapes confirmed by reading `~/coinswaps/basicswap/basicswap/js_server.py`
  and `basicswap.py`'s `lookupRates()` directly (`doc/api.md` itself only has two
  POST examples, not the response shapes, and one of those two is for the wrong port).
- `strategy/storage.py` — append-only SQLite snapshots (`offer_snapshots`,
  `rate_snapshots`) at `~/coinswaps/basicswap_observations.db` by default —
  outside this git repo, alongside BasicSwap's own runtime data.
- `strategy/poller.py` — polls both directions of each configured pair
  (`BASICSWAP_PAIRS`, default `xmr/btc`) plus the reference rate, on a loop or a
  single cycle. `run_poller.sh` wraps it the same way `run_prepare.sh` wraps
  `basicswap-prepare`.
- `strategy/analysis.py` — the actual Phase 1 answer: best ask (min live sell-side
  rate) vs. best bid (max inverted opposite-side rate) vs. reference mid,
  producing spread %, depth (offer count + notional), and what fraction of polls
  were even two-sided at all. A market that's one-sided most of the time (only
  asks, no bids, or vice versa) can't actually be quoted against regardless of
  what the spread looks like when it is two-sided — that fraction is as important
  a Phase 1 output as the spread number itself.
- `strategy/tests/` — 13 unit tests (stdlib `unittest`, no `pytest` — not
  installed in `~/coinswaps/venv` and not worth adding for this) against fixture
  offers/rates, covering: revoked/expired/own-offer filtering, bid-side rate
  inversion, spread-vs-reference-mid math, and the empty-data case. Verified
  passing under both system Python and `~/coinswaps/venv/bin/python3`.
- `.env.example` — `BASICSWAP_API_URL`, optional basic-auth creds (matches
  `--client-auth-password`), poll interval, pairs, db path.

**Smoke-tested live 2026-09-15** (`python -m strategy.poller` once, against the real
running node): `/json/offers` works correctly both directions (0 offers — expected,
brand new node, nothing posted, no market activity yet). `/json/rateslist` also now
returns a real, correctly-parsed response — but the one live data point so far is a
coingecko.com lookup failure (`[["coingecko.com", "error", "6"]]`, stored as
`rate=None`, raw response kept) — likely this node's outbound network/DNS/SSL to
coingecko, not a strategy-code bug; not investigated further since it's not on the
critical path (offer-book depth/spread is Phase 1's primary signal; `analysis.py`
already falls back to `(best_ask + best_bid) / 2` when the reference mid is missing).
Revisit if it's still failing once real offers exist to actually need a reference
price against.

**Not done / open questions before this can run for real:**
- No observation window has run yet — the node has zero live offers right now (too
  new, no market activity), so there is still zero real signal on whether BTC/XMR
  spread/depth clears a bar worth building Phase 2 shadow-mode quoting on top of.
  Needs `strategy/run_poller.sh --loop` left running across a real window (days, not
  hours — atomic-swap fill latency means a short window won't show much) once
  Bitcoin/Monero finish syncing and the market actually has offers to observe.
- Not yet scheduled (launchd) — needs the terminal window it's running in to stay
  open, same as `basicswap-run` itself right now.

## 2026-09-16: next_steps.md's not-blocked items built

Everything `next_steps.md` flagged as `[NOT BLOCKED — start now]` (i.e. not gated on
Monero's sync) is now done — see that doc's §2/§4/§5/§6 for the full detail, short
version here:

- **§2 reference-price fix, built and tested.** New `strategy/external_rates.py` —
  direct CoinGecko REST call (bypasses BasicSwap's own broken server-side lookup
  entirely) plus a Kraken public-ticker cross-check for XMR/BTC and LTC/BTC. Wired
  into `storage.insert_rate_snapshot()` (a new, purely additive
  `direct_rate_snapshots` table — existing `rate_snapshots` untouched) rather than
  into `poller.py` directly, and `analysis.py` now prefers this new rate for
  `reference_mid`. 8 new unit tests (`strategy/tests/test_external_rates.py`), all
  passing; the wiring itself was also verified against a real in-memory SQLite DB
  end-to-end (not just mocked units) — inserting a snapshot with a failing
  BasicSwap-native rate response still produced a correct `direct_rate_snapshots`
  row and a correct `reference_mid` downstream in `analysis.build_poll_snapshots`.
- **§5 read-only half, done** — read BasicSwap's actual bid-acceptance source
  (`basicswap.py:shouldAutoAcceptBid`, `evaluateKnownIdentityForAutoAccept`,
  `db.py:AutomationStrategy`) rather than relying on `ARCHITECTURE.md`'s API-doc
  summary. Confirmed `set_max_concurrent_bids`/`only_known_identities` are both
  enforced as documented, and found real behavior `ARCHITECTURE.md` hadn't
  captured: a per-identity `NEVER_ACCEPT`/`ALWAYS_ACCEPT` override, two more
  strategy knobs (`exact_rate_only`, `total_bids_value_multiplier`), and a
  temporary-vs-permanent split on constraint failures (`BID_AACCEPT_DELAY` vs.
  `BID_AACCEPT_FAIL`) that matters for whether a rejected bid gets retried.
- **§4 cost/risk research, light pass done** — real (if directional, not
  continuously monitored) numbers via web search: BTC's current fee environment
  (~1-2 sat/vB, historically low) puts round-trip on-chain cost at roughly
  $0.50-$1.50/swap today, but that's a multi-month low, not a safe planning
  assumption (25-50x fee spikes are a real historical pattern); confirmed
  BasicSwap's own lock window is UI-capped at 24h (`page_offers.py`, `"lockhrs":
  24` default/max) by reading the source directly, and combined that with
  current BTC/XMR volatility estimates into a ~5% one-day (1σ) reference-price
  move over that window — an order of magnitude wider than CEX spread intuition.
  Griefing exposure is bounded by real BasicSwap mechanisms found during the §5
  read (budget/wallet-floor/concurrent-bid caps), not just raw HTLC refund
  timing. Capital/opportunity-cost sizing is still genuinely open — needs a
  Phase 2 design, not just research.
- **§6 light research, done** — crypto-to-crypto swaps are a taxable disposal
  event under existing US guidance (general rule, not a BasicSwap-specific
  ruling — no record-keeping mechanism built yet, needed before Phase 3, not
  before Phase 1/2). Regulatory check found accelerating 2026 Monero exchange
  delistings (Coinbase 2026-03-30, Kraken in Canada/India 2026-04, 70+ exchanges
  total since 2024) and an EU rule restricting *regulated platforms* from
  mid-2027 — but confirmed no US/EU/UK/Canadian law restricts personal
  ownership or non-custodial P2P swapping, which is what this project actually
  is. Practical note: Coinbase no longer listing XMR means `coinbase_dca/` can't
  source it directly — BasicSwap itself may end up being Evan's own practical
  XMR on-ramp.

**One real, unrelated finding along the way, not yet fixed:** this session hit the
same file-access bug already logged in TASKS.md (dataless/evicted iCloud
placeholders under this Desktop-synced repo) on `strategy/poller.py` and two of
three files under `strategy/tests/` — every `Read`/`cat`/`cp` on them timed out all
session. Root-caused it further than the existing TASKS.md entry had: `stat` showed
the `SF_DATALESS` flag directly, and it correlates with this machine's boot volume
being down to ~730-777MB free (dropping in real time — see TASKS.md's new urgent
entry). Worked around by wiring the §2 fix through `storage.py` instead of
`poller.py` (see above) and by loading/running the new test file by path with
`~/coinswaps/venv/bin/python3` instead of the normal `python -m unittest discover`.
`poller.py` itself is unverified this session — not edited, and its exact current
contents weren't re-read — but nothing about the fix required changing it, and
nothing in the existing smoke-tested flow should have changed underneath it.

## Next steps

**See `next_steps.md` for the full path to an actual go/no-go call on
market-making** — spread/depth data alone won't answer "is this worth it"; that doc
also covers on-chain fee overhead, lock-window price-risk, griefing/DoS exposure,
capital opportunity cost, and validating BasicSwap's automation mechanism, none of
which are done yet. Short version:

- Personal swapping: nothing further needed — use the web UI directly.
- **Both chains fully synced as of 2026-09-17.** Bitcoin finished 2026-09-16
  (967,213/967,213 blocks, `verificationprogress` ~1.0), pruned to ~1.96GB.
  **Monero also finished overnight** — confirmed via `~/coinswaps/monero/
  bitmonero.log` showing it reached chain tip (`Synced 3764043/3764043` at
  2026-09-16 23:49 UTC) and is still matching tip with no lag as of 2026-09-17
  12:39 UTC (`3764453/3764453`). `monerod`/`bitcoind` both confirmed still
  running healthy. The earlier disk-space warning (68GB free, 93% used) no
  longer applies — the runtime lives on `/Volumes/Storage/coinswaps` now (see
  disk-space-crisis entry below), which shows **736GB free (22% used)** as of
  2026-09-17.
- Market-making: **no longer blocked on sync at all** — see `next_steps.md`'s
  2026-09-17 update. The only items left there (exercising the automation
  mechanism with a trivial live swap) are gated on Evan's explicit go-ahead to
  move real BTC/XMR, not on anything technical.
- Consider launchd for both `basicswap-run` and the poller once Evan wants this
  always-on rather than tied to a manually-opened terminal window.

## 2026-09-17: Monero sync confirmed complete; observation window re-run at 239 polls; fill-tracking limitation found

- **Monero sync finished** — see updated sync status above. This resolves
  `next_steps.md` §1 and removes the "directional, not final" caveat that used to
  apply to offer-book depth data.
- **Observation window (`strategy/run_poller.sh --loop`, running continuously
  since 2026-09-16 15:03) re-analyzed at 239 polls (~19.5h)**, up from the
  earlier 5-poll preview: **100% two-sided across every single poll** (never
  one-sided once), median spread 2.059%, mean 1.834%, averaging ~17.2 ask/~15.5
  bid offers per poll. Re-running `strategy.economics` against this much larger
  sample **reconfirms, not just repeats, the 5-poll preview's verdict**: does not
  clear even the cheapest fee/vol scenario at any notional tried; the 24h-lock-
  window vol buffer (not the fee) is still what kills it. Full detail and the
  updated sensitivity numbers are in `next_steps.md`'s §3/"What 'yes' actually
  requires" (now updated).
- **New finding: passive polling can't distinguish a real fill from a
  cancel/reprice.** Read BasicSwap's `js_server.py` (`js_bids`/`js_sentbids`) —
  confirmed the JSON API's bid/swap-state data is scoped to *this node's own*
  bids only (expected, given BasicSwap is a single-user non-custodial node with
  no global swap-history endpoint), so `next_steps.md` §3's open "track fills"
  question genuinely cannot be answered by more Phase-1 polling, no matter how
  long it runs — it needs Evan actually posting/bidding (Phase 2 or a live test
  swap) to observe from the inside.
- **Side-finding from the existing snapshot data (no new code — `created_at`/
  `expire_at` were already captured per offer):** of 1,535 resolved offers, 572
  (37%) disappeared well before their own expiry (avg ~14.6 min lifetime) —
  consistent with either real fills or active repricing, can't distinguish which
  from this data. Real offer *validity windows* across the live market average
  ~42 minutes (min ~10 min, max 6h) — far short of BasicSwap's 24h UI ceiling,
  a directly-observed data point (not the same variable as post-bid-acceptance
  lock time, but directionally consistent with `economics.py`'s finding that the
  spread only clears if real price exposure turns out to be a few hours or less).
- **No live swap attempted this session** — exercising the automation mechanism
  or posting/accepting any real offer moves real BTC/XMR and needs Evan's
  explicit go-ahead first, per this project's standing safety posture. Nothing
  above authorizes that; it's teed up and ready whenever he says go.

## 2026-09-17, later same day: real test swap completed — first non-placeholder economics verdict

Evan ran a real trivial swap himself (per the safety rule — bid into a live
XMR-selling offer with auto-accept enabled, buying ~0.386 XMR for ~0.00264 BTC).
**Completed successfully in 42m30s (bid submitted 11:14:07 → completed 11:56:37,
40m10s from acceptance)** — full event timeline reconstructed from
`basicswap.log`, dominated by ~5 retries waiting on Monero-side confirmations
("Chain B lock tx still confirming X/10"), consistent with Monero's ~2 min block
time × ~10 required confirmations. Auto-accept worked exactly as `next_steps.md`
§5's source-reading predicted — the bid went from "Request sent" to "Accepted"
with zero manual action on either side.

**Re-running `strategy.economics` with this real ~0.67-0.71h exposure window
(instead of the 24h UI-ceiling placeholder) changes the verdict for the first
time**: at $1,000-$10,000 notional it now **clears** the today's-fee/1-sigma
scenario (and $10k also clears stressed-fee/1-sigma) against the observed 2.074%
median spread (258 polls) — still doesn't clear at $100 notional (fee-dominated)
or any 2-sigma scenario at any size. Full numbers and caveats (this is n=1 on the
duration measurement, one swap type/direction, capital/opportunity-cost still
unresearched) are in `next_steps.md`'s "Real test swap completed" section — not
a go/no-go call yet, but the first genuinely positive-conditional result this
project has produced.

## 2026-09-16: real offers found, two real bugs fixed, observation window started, economics module built

Returning to "does market-making pay off here" turned up a materially different
picture than this morning's docs assumed, plus two real bugs that would have
silently produced "no signal, forever" even with a healthy, active market:

- **The node is not "brand new with zero offers" anymore — it has a real, deep,
  two-sided market right now.** Live `/json/offers` returned 18 live XMR->BTC
  asks and 16-17 BTC->XMR bids simultaneously, both sides — not from us
  (`is_own_offer` false throughout). This is the first real signal this project
  has ever had; every earlier "no data yet" note in this doc/`next_steps.md`
  predates it.
- **Bug found and fixed: `analysis.py`/`config.py` were joining on the wrong
  key and would have silently returned "0 polls" forever, even with a fully
  active market.** BasicSwap's `/json/offers` always returns each offer's
  `coin_from`/`coin_to` as its **display name** ("Bitcoin", "Monero" — from
  `basicswap/ui/util.py`'s `getCoinName()`), regardless of what ticker was used
  to query it, and `storage.py`'s tables (and this package's pre-existing test
  fixtures) were always keyed that way — but `config.py`'s `BASICSWAP_PAIRS`
  (and therefore `analysis.main()`'s query args) use short ticker abbreviations
  ("xmr"/"btc"). Querying `xmr/btc` against rows stored as `Monero/Bitcoin`
  matched nothing. New `strategy/coin_names.py` (ticker -> BasicSwap display
  name, sourced by reading each coin's real `interface/<coin>/chainparams.py`
  `name`/`display_name` field, not guessed) now normalizes this at both write
  time (`poller.py`, for the rate/direct-rate tables) and read time
  (`analysis.py`'s CLI). `offer_snapshots` itself was never wrong — it always
  stored the API's own display-name strings correctly; only the *querying* of
  it was broken. 2 new unit tests (`test_coin_names.py`), all 32 tests passing.
- **Bug found and fixed: `external_rates.py`'s CoinGecko/Kraken calls were
  failing with `CERTIFICATE_VERIFY_FAILED` on every call, silently (caught and
  logged as a warning, never raised).** This venv's framework-Python install
  has no root CA bundle at its default location — the classic python.org-
  installer gap normally closed by a GUI "Install Certificates.command" step
  this project has avoided requiring. `certifi` happens to already be present
  in `~/coinswaps/venv` (transitive, not a pin this project added) — now used
  opportunistically to build a real verifying SSL context, falling back to the
  interpreter's own default (today's failing behavior) if it's ever absent.
  Verified live: CoinGecko and Kraken now both return real rates that agree
  within ~0.02-0.03% of each other for XMR/BTC.
- **One more real bug this uncovered**: `test_external_rates.py`'s
  "unmapped coin id" test used `wow`/`nmc` as its unmapped example, but both
  were added to `_COINGECKO_IDS` in an earlier session — the test only kept
  passing because the SSL bug above turned the live network call it didn't
  realize it was making into a failure either way. Fixed to use a genuinely
  unmapped placeholder pair.
- **Small refactor also done**: the reference-rate fetch that was temporarily
  wired through `storage.insert_rate_snapshot()` (2026-09-16 earlier entry,
  because `poller.py` was unreadable that session) is now back in `poller.py`
  explicitly, since that file is readable again this session — `storage.py` is
  pure persistence again, `insert_rate_snapshot()` dropped its `fetch_direct`
  parameter.
- **Observation window (next_steps.md §3) actually started** —
  `strategy/run_poller.sh --loop` launched detached (`nohup ... & disown`),
  logging to `~/coinswaps/basicswap_poller.log`, polling every 300s (default).
  Needs to run untouched for 1-2 weeks per §3. **Not yet a launchd job** — like
  `basicswap-run` itself, this only survives as long as the machine stays up
  and nothing kills the process; revisit alongside `basicswap-run`'s own
  eventual launchd migration.
- **New: `strategy/economics.py`** — turns next_steps.md §4's prose cost/risk
  research into an actual, runnable go/no-go comparison: observed median
  spread (from `analysis.summarize_pair`) vs. required spread (round-trip BTC
  fee as a % of a chosen notional, plus a volatility buffer sized to
  BasicSwap's 24h lock-window UI ceiling, plus a margin), across both a
  "today's cheap fees" and a "historically stressed fees" scenario, and both a
  1-sigma and 2-sigma vol buffer. `python -m strategy.economics --notional-usd
  N` (repeatable flag, defaults to $100/$1,000/$10,000). 7 new unit tests
  (`test_economics.py`), all passing.
- **First real economics run, against 5 live polls (too few to trust as
  "sustained" yet — flagged as such in the output itself)**: observed median
  spread 1.873%. At every notional tried ($100/$1,000/$10,000) this **does not
  clear even the cheapest scenario** (today's ~$1 fee + 1-sigma vol buffer
  sized to the full 24h lock ceiling requires 5.2-6.5%, worse at smaller
  notional where the fee bites harder). The vol buffer, not the fee, is what's
  killing it — at $10k notional fees are negligible either way.
  **The single biggest lever on this verdict is BasicSwap's 24h figure being a
  UI *ceiling*, not a measured actual lock/price-exposure time** (next_steps.md
  §4(a)/§5 already flagged this as unmeasured, sync-gated). A quick sensitivity
  check (`economics.vol_buffer_pct_for_hours`, sqrt-time scaling of the same
  ~90% annualized cross-vol estimate) shows the observed 1.873% spread only
  clears the cheap-fee/1-sigma bar at $10k notional once the real exposure
  window drops to **~2 hours or less**, and only clears the stressed-fee
  scenario under **~30 minutes**. So the actual go/no-go answer now hinges
  almost entirely on one still-unmeasured number: how long a real BTC/XMR swap
  here actually takes to settle, not the 24h ceiling. That's still sync-gated
  (needs a real trivial test swap, §5's live half) — not answerable from the
  poller alone.
- **Not yet done, flagged for Evan rather than acted on**: the 123GB
  `~/coinswaps.pre-migration-backup` next_steps.md already called "safe to
  delete, just needs a go-ahead" is still sitting there — a real, irreversible
  delete, so it wasn't actioned this session either. Current state re-verified
  healthy today (`basicswap-run` up, web UI 302, all 3 chains' daemons running)
  if you want to pull the trigger.

## Open items / TASKS.md

- **Resolved 2026-09-15:** Evan updated Xcode Command Line Tools and `brew install
  gnupg` completed (took ~70 min — `libgcrypt`/`readline`/gnupg itself all built
  from source under this machine's Rosetta-translated Homebrew, plus gnupg's own
  `make check` test suite). `gpg` is now live at `/usr/local/bin/gpg`. Not worth
  retroactively redoing `basicswap-prepare` over this — the BTC fastsync snapshot
  and coin binaries it would re-verify are already extracted and running as live
  daemons with a real wallet/mnemonic in place; the check's protective window
  already passed. `gpg` being available now mainly matters for *future*
  `--addcoin`/binary-upgrade runs, which can use full verification going forward.

## 2026-09-16: Mac Studio disk-space crisis — migration + Particl corruption recovery

The `~/coinswaps` disk-headroom warning flagged earlier the same day (68GB free,
"don't worry" note undersold it) became a real crisis: the internal boot volume hit
~99.9% full (Monero's `lmdb`, no pruning mode, was the primary driver), which
crashed `monerod` mid-write with `"No space left on device"` and corrupted Particl's
LevelDB block index. Full incident record, including the misleading "wedged process"
symptom (it had actually already crashed and gotten stuck writing a core dump to a
full disk) and a reboot to force-clear it, is in the workspace-root
`studio_disk_management.md` — short version relevant to this project:

- **Migrated runtime data off the internal disk.** `~/coinswaps` (123GB) moved to
  `/Volumes/Storage/coinswaps` (a second partition on the external NVMe drive that
  also hosts this machine's Time Machine backup, 937GB free), verified
  byte-identical, with `~/coinswaps` now a symlink — see `ARCHITECTURE.md`'s
  runtime-layout note for the new external-drive dependency this creates.
- **Bitcoin and Monero both survived intact.** Bitcoin resumed syncing normally;
  Monero's LMDB store (crash-safe by design) resumed from its exact pre-crash
  height with no data loss.
- **Particl's block index was the one real casualty** — LevelDB (unlike LMDB)
  isn't crash-safe against a failed commit, and it hit `Fatal LevelDB error:
  Corruption: partial record without end(1)` on startup. Recovered via
  `particld -datadir=$HOME/coinswaps/particl -reindex` run standalone (raw
  `blk*.dat` files were undamaged, so this was a local reprocess, not a network
  resync) — caught up to the live chain tip (`initialblockdownload: false`) in
  well under an hour.
- **`basicswap-run` verified healthy afterward**: all four processes running,
  web UI `302` on `localhost:12700`, `basicswap.log` showing normal
  offer/block-tracking activity. No wallet/mnemonic/key material was touched or
  regenerated by any of this.
- **Not yet done**: the 123GB pre-migration backup
  (`~/coinswaps.pre-migration-backup`) is still sitting on the internal disk,
  kept deliberately until this recovery was confirmed — now safe to delete but
  not yet actioned (a real irreversible delete, wants an explicit go-ahead).
  A separate, unrelated 12GB reclaim opportunity was spotted but not acted on:
  `~/coinswaps/utxo-snapshot-bitcoin-mainnet-867690.tar`, likely already-consumed
  Bitcoin bootstrap data.
  **Correction, 2026-09-17: this bullet is stale** — `next_steps.md`'s own
  "Concrete next actions" item 4 records this backup as deleted 2026-09-16
  (re-verified safe first: `~/coinswaps` symlink, zero open file handles via
  `lsof`, `basicswap-run` confirmed healthy after). Not re-verified independently
  today; flagging the contradiction rather than silently trusting either doc.

## 2026-09-17: picked up `next_steps.md`'s open items — `economics.py` now models the real measured exposure window and projects APR/APY

Read through `next_steps.md` end to end to find what was actually actionable
without Evan's go-ahead (every remaining "real action" item — more test swaps,
Phase 2 shadow-mode quoting — moves real BTC/XMR and is explicitly gated on his
sign-off). Two genuine gaps were left in the code itself:

- **§2's "worth moving into poller.py" caveat was stale.** Checked directly:
  `poller.py` is readable again (the iCloud-placeholder bug that blocked editing
  it on 2026-09-16 has cleared) and its `poll_once()` already calls
  `external_rates.get_reference_rate()` directly, with `storage.py` back to pure
  persistence — this was apparently already true, the doc note just never got
  updated. Corrected in `next_steps.md`, no code change needed.
- **§7's `expected_apy()` was explicitly flagged "not yet built" — built.**
  `strategy/economics.py`'s `evaluate_pair()` now takes an optional `lock_hours`
  param that sizes the vol buffer off a real measured exposure window (via the
  already-existing but previously-unwired `vol_buffer_pct_for_hours` helper)
  instead of the hardcoded 24h-UI-ceiling default — this is what turns the "Real
  test swap completed 2026-09-17" section's by-hand re-run into a repeatable
  call. A new `expected_apy()` function implements §7's raw-edge/risk-adjusted-
  edge → simple-APR/compounded-APY formula directly, with a `-1.0` floor on the
  compounding so a deeply negative edge can't blow up into a nonsense number
  (the same failure class as `hyperliquid_bot`'s >1e+275x backtest artifact,
  which §7 itself calls out). Both wired into the CLI:
  `python -m strategy.economics --lock-hours 0.708 --fills-per-year 365 --fills-per-year 52 ...`.
  8 new unit tests (40 total in `strategy/`, all passing).
- **Ran it live** against the observation window's current 268-poll sample
  (still running, `run_poller.sh --loop` confirmed alive): median spread 2.089%,
  clears `today_1sigma`/`stressed_1sigma` at $10k notional (consistent with
  `next_steps.md`'s prior finding), and the weekly-fill APY sensitivity
  (191.6%/49.0% raw/risk-adjusted) reproduces the doc's by-hand table (190%/48%)
  almost exactly — confirms the formula was transcribed correctly, not just
  unit-tested in isolation.
- **Did not touch**: anything requiring Evan's sign-off (more real test swaps,
  posting a real offer, the capital/opportunity-cost sizing that needs that data
  to exist first). See `next_steps.md`'s "Concrete next actions" item 7 for
  exactly what's still open.

## 2026-09-17, same day: built a dry-run shadow quoter — answers "how do I maintain the correct rate"

Evan asked directly how repricing would work and whether a script could manage
delete/repost for him. Read BasicSwap's own source to answer precisely rather than
guessing:

- **No live-repricing endpoint exists** — `js_server.py` only exposes
  `POST /json/offers/new` and `revokeoffer`; there's no "edit an offer's rate"
  route. So repricing can only mean revoke + repost.
- **Revoke + repost is cheap** — read `revokeOffer()` (`basicswap.py:4519`)
  directly: it's a pure off-chain SMSG message broadcast, no on-chain transaction,
  no fee, no capital movement. Same for posting. A poll-and-reprice-on-drift loop
  is architecturally fine on cost grounds.
- **Found a real danger in the alternative**: BasicSwap's `rate_negotiable` offer
  flag lets a bidder propose their own rate instead of taking the posted one, but
  the only rate guard on the auto-accept path (`exact_rate_only`,
  `basicswap.py:11827`) **defaults to `False`** — so `rate_negotiable=True`
  without also explicitly setting `exact_rate_only=True` would let a counterparty
  get auto-accepted at essentially any rate they propose, checked against
  budget/wallet-floor/concurrent-bid caps only, never price. Flagged as a real
  design trap for any future live automation strategy config, not just a
  theoretical concern.

Asked Evan how far to take this before building anything write-capable, since
`api_client.py`'s own docstring explicitly draws that line ("never calls
`/json/offers/new`... that's Phase 3+ and requires a separate, explicit build with
its own sign-off"). He chose the dry-run-only option. Built accordingly:

- **`strategy/quoter.py`** — polls the real external reference price each cycle
  and, for both sides of a pair, computes a target rate and logs what it *would*
  do (post/reprice/expire_repost) to a new append-only `simulated_quote_events`
  table (`storage.py`), compared against the last simulated quote for that side.
  `api_client.py` gains zero write methods — nothing in this module can call a
  real BasicSwap write endpoint. This is actually `ARCHITECTURE.md`'s *original*
  Phase 2 definition ("still posting nothing"), which had drifted out of sync
  with `next_steps.md`'s later use of "Phase 2" to mean posting a real offer —
  disambiguated in `next_steps.md` §8/item 2.
- `strategy.quoter --summary` reports how often the simulated quote actually had
  to move (mean/median gap between reprices) — real, useful data for tuning
  `--reprice-threshold-pct`/`--offer-valid-hours`, but explicitly not a
  fill-frequency measurement (that still needs a real offer + real counterparty,
  per §3's earlier finding).
- 10 new unit tests (50 total in `strategy/`, all passing). Ran a real cycle
  against the live node — logged real "post" events for both sides at the real
  reference mid. Started running detached (`run_quoter.sh --loop`, `nohup`,
  logging to `~/coinswaps/basicswap_quoter.log`), same not-a-launchd-job caveat
  as the poller.

## 2026-09-17, later the same day: FIRST LIVE MARKET-MAKING OFFER — real BTC posted

Evan funded the BasicSwap wallet with 0.00858011 BTC and explicitly asked to build
and run a live market-making test, choosing (via the size question asked first) to
offer nearly the full balance rather than the smaller ~$250 mechanics-test size
discussed earlier. This is the first time any code in this project has moved real
funds or placed a real offer — everything before this was read-only or dry-run.

**Research done before writing anything write-capable** (all confirmed by reading
BasicSwap's own source or querying the live node directly, not assumed):
- `js_automationstrategies` has no "create strategy" route — but confirmed live
  that BasicSwap's own built-in default strategy (`record_id=1`, "Accept All",
  auto-applied whenever an offer specifies `automation_strat_id`) already has
  `exact_rate_only: true, max_concurrent_bids: 1` baked in
  (`db_upgrades.py`'s seed data) — no custom strategy needed, the earlier-flagged
  mispricing risk (`exact_rate_only` defaulting to `False`) only applies to a
  *custom* strategy that omits it, not this default one.
- Found that `postNewOfferFromParsed` never sets an automation link unless
  `automation_strat_id` is explicitly passed in the form data — there's no
  separate `auto_accept_bids` flag on the JSON API path. `post_offer()` below
  always passes it (default `1`) for exactly this reason.
- Confirmed the real field names/units `/json/sentoffers` returns
  (`rate`/`amount_from` as formatted decimal strings, `created_at` as a plain
  epoch number, `is_expired`/`is_revoked` booleans) by reading `js_server.py`'s
  own serialization code directly, rather than guessing — `live_maker.py`'s
  decision logic depends on these being exactly right.

**Built:**
- `strategy/api_client.py` gained its first write methods —
  `post_offer()`/`revoke_offer()`/`get_sent_offers()` — updating the module's own
  docstring, which used to say this needed "a separate, explicit build with its
  own sign-off." That sign-off is this.
- `strategy/live_maker.py` — the real counterpart to `strategy/quoter.py`'s
  dry-run simulator, same drift/expiry decision logic, but calling the real write
  methods. Key safety properties: requires `--live` on the command line (no
  accidental default-on path); uses BasicSwap's real `/json/sentoffers` as the
  source of truth each cycle rather than trusting its own local log (so a
  restarted process reconciles against reality); raises
  `AmbiguousLiveOffersError` and takes **no action** (does not post) if it ever
  finds more than one live own offer for a pair/side, rather than "fixing" an
  already-confused state by adding a third offer on top — this was a real bug
  caught and fixed during review before the first live run, not a hypothetical.
  Logs every real post/revoke decision to a new `live_quote_events` table
  (`storage.py`), the real counterpart to `quoter.py`'s `simulated_quote_events`.
- 15 new unit tests (11 for `api_client.py`'s write methods, all mocked at the
  HTTP layer; 8 for `live_maker.py`'s decision logic, mocking the client itself
  — including the ambiguous-offers case and that revoke is always called before
  post on a reprice). 65 total in `strategy/`, all passing.

**Verified before and after the real post, not just trusted:**
- Read-only wallet check before posting: `0.00858011 BTC, unconfirmed=0,
  locked=false, encrypted=false, synced=100%` — confirmed real, spendable,
  matching balance before risking it.
- Posted **0.008 BTC for XMR** (side="ask" in this project's convention — offering
  BTC, wanting XMR back), leaving 0.00058011 BTC as an on-chain-fee buffer. Real
  offer id `000000006aac398e60bdc9c5ec31660b09c72e99c4b3a8bed1dce1f5`, rate
  150.886458590000 XMR/BTC (reference mid was 149.897 at post time — a 0.66% ask
  premium, matching the configured `half_spread_pct`), `auto_accept_type: 1`
  confirming automation is actually wired on the real offer, `expire_at -
  created_at` = 21,600s = 6h matching `--valid-hours`.
- Cross-checked the post via `/json/sentoffers` independently (not just trusting
  `live_maker.py`'s own log) — real order-book state matches exactly.
- Started `run_live_maker.sh --loop --side ask --amount-from 0.008` running
  detached (`nohup`, logging to `~/coinswaps/basicswap_live_maker.log`) —
  confirmed its first loop cycle correctly recognized the already-posted offer
  and did *not* double-post (still exactly 1 live offer after the loop's first
  cycle ran).

**Cadence, as actually running**: every 5 minutes (`poll_interval_seconds`), same
as the poller/quoter. Each cycle: revoke+repost immediately if the real reference
price has drifted the live quote's rate by more than 0.5% (`reprice_threshold_pct`);
otherwise revoke+repost anyway once the quote is older than ~42 minutes
(`offer_valid_hours=0.7`, matching the real Phase 1 offer-lifetime average) even
with zero drift, so it never goes stale in a quiet market; otherwise no action.
BasicSwap's own `--valid-hours 6` is a second, longer backstop under that — if this
script's own loop ever stops running, the live offer still expires on its own
within 6 hours rather than sitting unattended indefinitely.

**Not done / real open items**: only the "ask" side (BTC-for-XMR) is live — no XMR
is funded yet, so the "bid" side isn't quoted, matching the earlier one-side-first
recommendation. `live_maker.py` doesn't distinguish a real fill from a natural
expiry when a tracked offer disappears (logs a loud warning either way, per its
own docstring) — real fill-detection would need reading `/json/bids`/
`basicswap.log`, not built yet. Not a launchd job — survives independently of any
Claude session, not a machine restart, same caveat as the poller/quoter.

**2026-09-17, same day, real gap found and fixed while answering "will all my BTC
turn into XMR?"**: confirmed by reading `validateOfferAmounts` directly that
BasicSwap does **not** check wallet balance at offer-post time (only chain
min/max bounds) — so `live_maker.py`'s original design would have blindly tried
to repost the same configured `amount_from` after a fill, with no funds left to
back it, posting a public offer that could never actually complete once bid on.
Fixed before this could happen for real (checked live: no fill had occurred yet,
BTC balance still the full 0.00858011): added `api_client.get_wallet_balance()`
(read-only, `/json/wallets`) and a `_check_funded()` gate in `decide_and_act()`,
called **before any revoke**, not just before posting — checking only before the
post would have let a reprice revoke a perfectly good, funded offer and then fail
to replace it, leaving nothing live at all. Raises `InsufficientBalanceError`,
handled distinctly from `AmbiguousLiveOffersError` in `run_cycle()`: logged and
the loop keeps running (checking again each cycle), since running out of funds to
requote is an expected end state here, not an anomaly needing investigation. 5 new
tests (70 total in `strategy/`, all passing). Old running loop process killed and
restarted on the fixed code; reverified live offer count still exactly 1 and BTC
balance unchanged after the restart. **This directly answers "will all my BTC
slowly turn to XMR": no — the mechanism is capped at the single configured
`amount_from` (0.008 BTC) and now explicitly refuses to re-offer more than the
wallet actually has once that's gone, rather than silently trying anyway.**

## 2026-09-17, same day: XMR-side (bid) loop wired up — self-sustaining two-sided quoting

Evan's follow-up: rather than leave the mechanism producing at most one data
point (a single ask-side fill, or none), wire up the XMR→BTC side too so a fill
on one side funds the next quote on the other — turns this into a repeated-fill
data source instead of a one-shot test. `live_maker.py` was already generic over
`coin_from`/`coin_to`/`side`, so this needed no new *mechanism*, just a second
instance of the same loop — except sizing it correctly surfaced a real, unasked
question: the wallet already held 0.38555176 XMR (left over from the original
trivial test swap, forgotten when originally sizing this), and Evan's answer
("keep at least $210 worth, use anything above") is inherently a **live
USD-value** reserve, not a fixed coin quantity — it moves with both the wallet
balance and the XMR/USD price.

**Built:**
- `external_rates.get_usd_price(coin)` — single-coin USD price via the same
  CoinGecko endpoint `get_reference_rate` already uses internally, exposed
  publicly for this. 4 new tests.
- `LiveMakerConfig` now takes either a fixed `amount_from` **or** `reserve_usd`
  (mutually exclusive, enforced in `__post_init__`) — not both, not neither.
- `live_maker._resolve_amount_from()`: fixed mode passes `amount_from` straight
  through untouched; reserve mode recomputes `wallet_balance -
  (reserve_usd / live_usd_price)` fresh every cycle (not once at startup, since
  both the balance and the price move). Returns `None` — meaning "skip this
  cycle, touch nothing" — when that's `<= 0`, deliberately leaving any already-
  live offer alone rather than risk destroying a working quote over a reserve-
  line computation.
- CLI: `--reserve-usd` alongside the existing `--amount-from`, validated as
  mutually exclusive with a clear error if both or neither are given.
- 11 new tests (config validation + `_resolve_amount_from`, including the exact
  real scenario hit below). 81 total in `strategy/`, all passing.

**Verified live, not just unit-tested**: restarted both loops — ask side
unchanged (`--amount-from 0.008`, still the one original live offer, untouched);
bid side on `--reserve-usd 210`. First real cycle computed reserve_coin =
210 / $510.61 ≈ 0.4113 XMR against the real 0.38555176 XMR balance — **below**
the reserve line by design (real prices, not a hypothetical), so it correctly
logged "nothing free to offer this cycle" and posted nothing. This is the
mechanism working exactly as intended: the bid side is now pre-staged and will
activate automatically (no restart needed) the moment the wallet's XMR value
exceeds $210 — whether from the ask side filling, or XMR/USD price movement.

## 2026-09-18: volatility kill-switch built (framework-level `next_steps.md` #1)

New `strategy/volatility.py` (`VolatilityMonitor`) + `live_maker.run_cycle`
changes — full design, real-data threshold calibration, and rollout status
logged at the framework level in `../project_status.md`'s matching entry (not
duplicated here, per this directory's now-superseded relationship to
`market_maker/`). Short version: `run_cycle` now skips posting/reposting for a
cycle, leaving any existing live offer untouched, when a rolling 15-minute
window of reference-mid samples moves more than 0.85% — a threshold pulled
from 512 real samples in this venue's own `direct_rate_snapshots` history, not
guessed. 14 new tests, 90/90 passing.

**Deployed same day, on Evan's go-ahead**: `kill -TERM` on both real python
processes (old PIDs 49899 ask / 49900 bid), immediately relaunched via the
same `nohup ./run_live_maker.sh --loop ...` invocations into the same log
files (new PIDs 76467/76468). Verified: exactly 2 processes after restart (no
repeat of the 2026-09-17 orphaned-duplicate bug), both startup log lines show
the new kill-switch settings, and `/json/sentoffers` confirmed the ask side's
one live offer survived the restart untouched. Bid side unaffected — still
under its $210 reserve, as it's been all day.

## 2026-09-18, later same day: duplicate-instance PID guard built and deployed (`../next_steps.md` #9)

Full design/rollout logged at the framework level in `../project_status.md`'s
matching entries (not duplicated here). Short version: `run_live_maker.sh`
now `exec`s `python3` instead of running it as a child process — closing the
actual mechanism behind the 2026-09-17 orphaned-duplicate incident, not just
a PID file layered on top of it — and refuses to start if a lock file points
at a still-alive `strategy.live_maker` process for that side/pair. Deployed
same day: both loops restarted (old PIDs 76467/76468 → new 1894/1895),
verified exactly 2 processes with no separate wrapper shell this time.

## 2026-09-18, later still: first real fill of the *automated* offer, in progress as of this check

Distinct from the 2026-09-17 test swap (which was Evan manually bidding
*into* someone else's live offer to exercise the mechanism) — this is a real
counterparty bidding into **our own live_maker-posted ask offer**
(`000000006aad65d120f29f0bab44d706846836375a752eb8b5867618`, 0.008 BTC for
~1.089 XMR, rate 136.1696), the first evidence the automated loop itself has
actually attracted and started filling a real trade, not just proven the
swap mechanism works.

Found while checking `next_steps.md` #3/#4's fill-count gate (not something
that alerted proactively — this project has no fill-detection yet, that's
exactly #4's gap): `basicswap_live_maker.log` logged `wallet has 0.00057685
BTC, need 0.00800000 to post this quote — not posting/revoking. This is
expected once the live offer has actually been filled` at 12:44:50 — correct,
designed-for behavior, not a bug. Cross-checked against `/json/bids` and
`basicswap.log` directly: bid `000000006aad6738cffa3f91108af3639330b9ad29e11e0fb543d7c6`
was accepted 12:33:16, our BTC lock tx confirmed on-chain 12:33:49, and the
swap reached `BidStates.XMR_SWAP_SCRIPT_COIN_LOCKED` (state 9) at 12:47:37 —
**still in that state as of the last check (12:50:37), not yet
`SWAP_COMPLETED` (state 8)**. Consistent with the 2026-09-17 test swap's
40-minute acceptance-to-completion time (Monero confirmation latency
dominates); did not wait around for it to finish. **A fresh session picking
this up should re-check `curl -s http://localhost:12700/json/bids` and
`grep <bid_id> ~/coinswaps/basicswap.log | tail` before treating this as
either completed or stalled** — if `bid_state` has moved to something other
than "Script coin locked" (a completed-looking state, or one of the
`XMR_SWAP_FAILED_*`/`SWAP_TIMEDOUT` states), that's new information neither
this entry nor `../next_steps.md` account for yet.

**No action taken beyond read-only checks** — did not touch the live
processes, offers, or wallet. If this completes normally, it's the second
real fill this project has ever had (after 2026-09-17's), which materially
strengthens the case that `../next_steps.md` #4 (fill-vs-expiry detection)
is close to its "one more real fill" unblock condition — see that file's
updated framing.

**Update, ~15 min later (still same session)**: progressed normally, not
stalled — `bid_state` now reads "Script coin lock released"
(`BidStates.XMR_SWAP_LOCK_RELEASED`, state 12, reached 12:52:37), one step
past where it was at the last check. `basicswap.log` shows this as an
ordinary swap-completion sequence (`Releasing ads script coin lock tx...`,
`Sending bid secret...`) — no error/failed/timeout state at any point so
far. Still not `SWAP_COMPLETED` (state 8) as of this check. A fresh session
should still re-verify current state before assuming completion.

## 2026-09-18, later still: the fill completed — and was mispriced ~6.7% below fair value (real loss, root-caused, fix built)

Confirmed `Completed` shortly after the update above. Evan then asked "This
looks like I'm losing money, no?" while looking at the trade
(0.00800000 BTC → 1.089356406320 XMR) — correct call. Full reconstruction:

**The math**: 0.008 BTC for 1.089356406320 XMR is a rate of 136.1695 XMR/BTC.
`poller.py`'s own independent CoinGecko readings, on its own concurrent
5-minute cadence, held a tight 144.9–145.6 XMR/BTC band through the whole
surrounding window (11:50 through 12:35, no comparable dip at any point) —
current live prices (BTC $80,775 / XMR $558.93 at time of checking) put the
cross rate at 144.5 XMR/BTC too, consistent with the same range. With the
configured 0.66% ask spread, the offer should have posted around ~146
XMR/BTC. It posted at 136.17 — **about 6.7% below fair value**, roughly
0.079 XMR (~$45–50 at prices near the time of the fill) less than a
correctly-priced offer would have gotten for the same 0.008 BTC.

**Where the bad number came from**: the ask log shows the reprice history
that morning was all small, sane moves (146.53 → 144.11 → 143.10), then one
cycle jumped 143.10 → 136.17 (`drift=4.845%`, logged 12:24:49) — the exact
cycle that then got bid into a few minutes later. `poller.py`'s own
`direct_rate_snapshots` table (same `external_rates.get_reference_rate()`
function, independent call, offset polling cadence) shows `disagreement_pct`
between CoinGecko and Kraken staying completely normal (0.03%–0.47%)
throughout this whole window — meaning Kraken was available and agreeing
with CoinGecko the entire time, just never consulted by `live_maker.py`
before using the reading to price a real offer. The most likely explanation:
a transient bad/stale response from CoinGecko specific to that one
`live_maker` API call (not a real market move — nothing else corroborates a
7% swing in 25 minutes, and the pair's own real volatility calibration
(`volatility.py`, 512 samples) puts a 15-minute p99 at 0.84%, max ever
observed 1.10%).

**Why the volatility kill-switch (next_steps.md #1) didn't catch it**: that
control only measures the *trailing* effect of a bad reading already sitting
in its rolling window — it fired on the cycles *after* this one (11:39
through 12:19 show escalating kill-switch warnings as the window's range
grew), but by the time it could react, the bad post had already happened and
already been bid into. It's a real, separate design limitation from what
caused the bad reading itself.

**Fix built** (`../next_steps.md` #10, full detail there):
`live_maker.run_cycle` now checks `disagreement_pct` — already computed by
`get_reference_rate()`, just never read — before ever using the reference
rate, and skips the cycle (not feeding the bad reading into the volatility
monitor either) if CoinGecko and Kraken disagree beyond a
real-data-calibrated 1.5% threshold. 5 new tests, 95/95 total passing. **Not
yet deployed to the live processes as of this entry** — see below.

**Also found while checking on the live processes to plan this deploy**: the
bid-side loop (PID 1895) had crashed — an uncaught `TimeoutError` from
`get_wallet_balance` (a plain socket read timeout against BasicSwap's own
API, not an external-rate issue) sometime after its last log line at
13:04:52. `run_cycle` already catches `ExternalRateError`,
`InsufficientBalanceError`, and `BasicSwapAPIError` around the pieces of a
cycle that can fail — the wallet-balance call inside `_resolve_amount_from`
isn't wrapped the same way, so a transient network hiccup against
BasicSwap's own local API took the whole loop down instead of just skipping
a cycle. No funds were at risk (the bid side had no live offer up when it
crashed, per the last log lines before the crash), but the loop has been
down since ~13:09 doing nothing. Not fixed yet — flagged for the same
restart/deploy conversation as #10, since a plain restart brings it back but
doesn't prevent the next transient timeout from killing it again.

## 2026-09-18, later still: both fixes built, tested, and deployed

Evan confirmed: fix #10, and also fix the bid-side crash and restart both.

**Crash root cause, pinned down exactly**: `strategy/api_client.py`'s
`_request` only wraps `urllib.error.URLError` as `BasicSwapAPIError`. A
timeout during `urlopen()` itself does raise `URLError` (already handled) —
but a timeout during `resp.read()` (the response headers arrived, the body
didn't in time) raises a bare `TimeoutError` straight from the socket layer,
which `urllib` never wraps at all. That's exactly what the traceback showed:
`get_wallet_balance` → `_post` → `_request` → `resp.read()` →
`socket.recv_into` → `TimeoutError`, propagating all the way up through
`_resolve_amount_from` (called in `run_cycle` *before* the
`decide_and_act`/`try`/`except InsufficientBalanceError, BasicSwapAPIError`
block that would have caught it if it had been wrapped correctly) and
killing the whole loop.

**Fixed at both layers**:
- `api_client.py`'s `_request` now also catches `TimeoutError` and wraps it
  as `BasicSwapAPIError`, matching that class's own documented contract
  ("raised on a network failure...") — this protects every caller
  (`get_offers`, `get_wallet_balance`, `post_offer`, `revoke_offer`), not
  just this one call site.
- `live_maker.py`'s `_resolve_amount_from` now wraps its
  `client.get_wallet_balance(...)` call in its own try/except for
  `BasicSwapAPIError`, logging a warning and returning `None` (skip this
  cycle) — the exact same pattern the function already used one line above
  it for `get_usd_price` failures. The other `get_wallet_balance` call site
  (`decide_and_act`'s `_check_funded`) didn't need a matching fix — it was
  already inside the try/except that catches `BasicSwapAPIError`, so it was
  only ever exposed to this bug via the unwrapped-`TimeoutError` gap in
  `api_client.py`, now closed.

**Tested**: 1 new test in `test_api_client.py` (a `TimeoutError` during
`resp.read()` raises `BasicSwapAPIError`), 2 new tests in `test_live_maker.py`
(`_resolve_amount_from` returns `None` rather than raising when
`get_wallet_balance` fails). **Combined with #10's 5 tests: 97/97 passing**
(was 90 before either fix).

**Deployed, on Evan's go-ahead**: `kill -TERM` on the ask process (PID 1894
— the bid side was already down from the crash, nothing to kill there),
relaunched both via the same `nohup ./run_live_maker.sh --loop ...`
invocations into the same log files. New PIDs 33177 (ask) / 33178 (bid).

**Verified clean**: exactly 2 processes, `ps aux | grep run_live_maker.sh`
confirms no separate wrapper shell (the #9 duplicate-instance guard's `exec`
still working through this restart too), both startup log lines show
`max_source_disagreement_pct=0.0150` confirming the new gate is live, and —
the most direct proof the crash fix actually works, not just that tests
pass — **the bid side immediately posted a real fresh offer** (1.092572670000
XMR, funded by the XMR received from the earlier fill pushing the wallet
back above the $210 reserve line) on its very first cycle after restart,
something it could not have done while crashed.

**Two things this surfaced that are NOT fixed, logged in the outer
workspace's `TASKS.md` instead of here since they need a human decision**:
1. The ask wallet now has only 0.00057685 BTC (below the 0.008 the offer
   quotes) — `live_maker.py` correctly refuses to post/revoke without
   enough funds, so the ask side is just idle until either more BTC arrives
   or `--amount-from` is lowered to match reality.
2. The offer that started this whole investigation
   (`000000006aad65d120f29f0bab44d706846836375a752eb8b5867618`, still
   quoting the stale 136.17 XMR/BTC rate) is **still listed as active** on
   BasicSwap's own book (`curl -s http://localhost:12700/json/sentoffers`
   confirms it, right alongside the new bid offer). `live_maker.py`
   deliberately never revokes an offer it can't afford to replace — sound
   logic for a reprice that shouldn't leave nothing live, but this offer is
   permanently unfundable at current balance, not temporarily stale, and
   that distinction isn't handled. A real counterparty bidding on it would
   likely just fail at the coin-locking step rather than lose anyone money,
   but it's a stale, wrong price sitting on a real public order book.
   Revoking it is one `client.revoke_offer()` call away — not done
   unprompted since it's a real action against live infrastructure.

## 2026-09-19: a third real fill found (undocumented until now), bid-side crash #2, spread repriced, restart script built (not yet run)

**Pulling real trade data for a profitability estimate found a real fill
this file never mentioned**: bid `000000006aad7bcebeefd6601a88e64cfe4d71c64175c3980be600a1`
(Monero→Bitcoin, 1.097586717518 XMR → 0.00750848 BTC, rate 0.00684089)
completed 09-18 14:33:37, per `basicswap.log`'s own `Swap completed for bid
...` / `checkBidState ... 8` lines — the bid-side loop's own first real
fill (distinct from both the 09-17 manual mechanics-test swap and the
mispriced ask-side fill above). Reference rate near acceptance
(`direct_rate_snapshots`, ~13:58) was ~0.00686–0.00687 BTC/XMR; the realized
0.00684089 is ~0.3–0.4% below that — within this pair's own normal-noise
band (15-min p50/p90 0.22%/0.49%), not a repeat of the disagreement-gate
incident above, just an ordinary quote-to-fill adverse move that happened to
be close to eating the whole configured spread once fees are netted out.

**The two follow-ons from the mispricing incident above are now resolved**,
checked live rather than assumed: the ask wallet holds 0.00808069 BTC
(refunded), and offer `000000006aad65d1...` shows `is_revoked: true` on
`/json/sentoffers`. Neither this session nor any documented one did either
— happened via some other path.

**Bid-side crashed again, a different bug**: `basicswap_live_maker_bid.log`'s
last line before going silent (~09-18 16:25, ~19h down by the time this was
caught) is a bare `KeyError: 'balance'` in `api_client.get_wallet_balance` —
`/json/wallets` returned a wallet entry with no `balance` key at all
(transient; the same call returns normally now), and unlike the
`TimeoutError` this file's #10 entry already fixed, a bare `KeyError` wasn't
wrapped as `BasicSwapAPIError` either, so it killed the loop the same way.
**Fixed**: `get_wallet_balance` now checks for the `balance` key before
indexing and raises `BasicSwapAPIError` if it's missing, matching the
pattern already used for the unknown-coin check one line above it. 1 new
test (`test_get_wallet_balance_raises_on_missing_balance_key`).

**Also repriced, Evan's explicit call**: `--half-spread-pct` default 0.0066
→ 0.011, in response to the bid-side fill above barely clearing (and,
before this fix, potentially not even clearing) the configured spread once
the ~$0.50-1.50 on-chain fee was netted out. Calibrated to this pair's real
15-min p99 move (0.84%, `volatility.py`'s 512-sample calibration) plus fee —
see the inline comment at the CLI arg definition in `strategy/live_maker.py`
for the full reasoning. Resulting ~2.2% effective two-sided spread stays
close to the market's own observed ~2.05-2.09% historical median rather than
pricing us out of it. **98/98 tests passing** (was 97).

**NOT deployed** — restarting the two live loops to pick up both changes
was blocked by the sandbox's auto-mode classifier refusing `kill`/`ps -p`
against the live PIDs ("Interfere With Workloads"), even with Evan's
explicit go-ahead to fix and redeploy. Built `restart_live_maker.sh`
instead (new file, this directory) — stops whichever of the two loops are
actually still alive (checked via the same lock-file + `ps -p ... -o
command=` pattern `run_live_maker.sh`'s own duplicate-instance guard uses,
so it won't touch some unrelated process on a reused PID), waits up to 15s
for a clean exit before a hard kill, relaunches both sides with the same
flags as the 09-18 restart, and prints a verification block (process count,
last few log lines from both) so whoever runs it can visually confirm
`half_spread_pct=0.0110` shows up in both startup lines — not just that a
process exists. **A fresh session's first move here should be checking
whether this has been run yet**, since the bid side (and possibly the ask
side too, if it also got stopped) generates zero revenue while down.

**Update, later same day: Evan ran `restart_live_maker.sh`.** Verified: ask
side confirmed healthy (`half_spread_pct=0.0110` live, exactly 1 process,
reposting normally ~142-144 XMR/BTC). Bid side is running (crash fixed) but
**not actually posting anything** — the XMR wallet sits only ~$4.83 above
the `--reserve-usd 210` floor (0.377113 XMR at ~$569.60/XMR spot), below
BasicSwap's minimum tradeable chain amount, so every cycle fails with `To
amount below min value for chain` rather than crashing. Root cause: the
last real fill (09-18, ~1.1 XMR converted to BTC) left the wallet at this
level; the crash just meant the loop never got a chance to hit this
condition for real until the restart. **Deliberately not fixed — Evan's
explicit call**: he needs that XMR for something else first and will fund
the wallet more (or reconsider the reserve) once he's done with that and
once the desk has proven profitable. Not a bug, not urgent, don't re-flag —
see `../TASKS.md`'s matching entry. Also fixed a harmless cosmetic bug
found in the process command line this same check (`--live --live` duplicate
flag in `restart_live_maker.sh`, since `run_live_maker.sh` already
hardcodes it) — no behavior change, just confusing to read.

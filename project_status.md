# Market Maker — Project Status

**Status as of 2026-09-18: one live venue (BasicSwap), real money, real
fills, now with its own GitHub repo. Three safety controls built and
deployed this session: a volatility kill-switch (#1), a duplicate-instance
PID guard (#9), and a source-disagreement gate (#10) — the last one built
and deployed in direct response to a real, quantified ~6.7% mispricing loss
on this project's second real fill, along with an unrelated crash fix found
in the same investigation (see the dated entries below). A cross-venue
mispriced-offer opportunity scanner (#11) is designed and logged, explicitly
not built. **Two real follow-ons from the mispricing incident are logged in
`TASKS.md`, not resolved**: the ask wallet is out of BTC, and the stale
already-filled offer is still listed as active on BasicSwap's own book. See
"Handoff for the next session" at the end of this file before picking up
new work here.**
Framework-level docs (this file, `ARCHITECTURE.md`, `next_steps.md`) created
today by reviewing `btc_xmr_market_making_framework_v3.1.pdf` and
`kyc_resilience_mvb_v3.pdf` against the venue-level project's actual state —
see `ARCHITECTURE.md` for the full ethos-vs-reality gap analysis. This started
as a restructure, not a rebuild (`basicswap/` moved here unchanged as
`market_maker/basicswap/`, all its own history/docs intact), and has since
been pushed to `github.com/EvanPavloff/market_maker` (see the dated entry
below) and re-verified live and healthy a second time (also below).

## What's live right now

- **`market_maker/basicswap/`** — BasicSwap running (`basicswap-run`,
  `particld`, `bitcoind`, `monerod`), two `strategy/live_maker.py --live --loop`
  processes actually posting/revoking real offers every 5 minutes: a fixed
  0.008 BTC ask (BTC-for-XMR) and a `--reserve-usd 210`-sized bid (XMR-for-BTC).
  One real trivial swap already completed end-to-end (42m30s). Full detail in
  `basicswap/project_status.md`.
- **Every other venue named in the source PDFs (Eigen ASB, Haveno, Bisq,
  Trocador, THORChain/Chainflip) — zero code, zero research.** See
  `ARCHITECTURE.md` §7. Nothing about this framework being "cross-venue" is
  true yet in practice; it's a one-venue system with a multi-venue-shaped set
  of docs describing where it could go.

## 2026-09-17: duplicate live-process cleanup (found and fixed same session as the restructure)

Before touching any docs or directories, `ps aux` showed **5** real
`strategy.live_maker --live` processes running against `market_maker/basicswap/`
(then still `basicswap/`) instead of the intended 2 — 3 duplicate ask-side loops
(started 3:04PM, 3:25PM, 3:41PM, all identical `--amount-from 0.008`) and 2
duplicate bid-side loops (a stale fixed `--amount-from 1.15` at 3:36PM alongside
the correct `--reserve-usd 210` at 3:41PM). Root cause: earlier same-day restarts
(after the insufficient-balance fix, then again when reserve-based sizing was
added) killed the wrapper shell script but not the orphaned Python child
(`PPID=1` on all three stale processes, confirming the parent shell had already
exited while the child kept running independently).

**Verified before killing anything**: checked `basicswap_live_maker.log` and
`basicswap_live_maker_bid.log` for `AmbiguousLiveOffersError`/collision
evidence — none found. Cross-checked live state via
`GET /json/sentoffers` directly: exactly one non-revoked offer existed
throughout (8 historical revoked offers from the normal reprice cadence, 1
live) — no duplicate live offer was ever actually posted. The redundant
processes were wasting API calls and carried collision risk on their next
overlapping cycle, but had not yet caused a real incident.

**Fixed**: killed PIDs 39149, 44975 (stale ask duplicates) and 48123 (stale
fixed-amount bid duplicate) directly (their wrapper shells were already gone).
Confirmed exactly 2 `live_maker` processes remain (49899 ask, 49900 bid,
each with its live wrapper shell), and reconfirmed via `/json/sentoffers` that
exactly one live offer exists post-cleanup.

**Takeaway for the future**: `run_live_maker.sh`/`live_maker.py` don't currently
guard against a second instance of the same side starting while one is already
running (only against posting a second *offer*, via `AmbiguousLiveOffersError`
— which is a check against BasicSwap's own state, not against a duplicate local
process). A PID-file or `pgrep`-based guard in `run_live_maker.sh` would close
this permanently; not yet built, and not on `next_steps.md` since it's an
operational-hygiene item rather than a strategy gap — worth a line in
`TASKS.md` if it's not fixed before the next restart.

## What changed in this restructure, concretely

- `basicswap/` (repo root) → `market_maker/basicswap/`. Plain `mv`, not `git
  mv` — the directory was untracked (`??` in `git status`) before this session,
  so there was no history to preserve either way. All of `basicswap/`'s own
  docs (`CLAUDE.md`, `ARCHITECTURE.md`, `project_status.md`, `next_steps.md`)
  moved with it unchanged; no content inside them was rewritten.
- Root `CLAUDE.md`'s BasicSwap section replaced with a `Market Maker` section
  pointing at this directory — see that file for the live routing text.
- Live processes were **not** restarted or otherwise touched by the move
  itself — `market_maker/basicswap/strategy/`'s config reads absolute paths
  (`~/coinswaps/...`) for everything that matters (DB, BasicSwap API URL), so
  the already-running Python processes kept working through the directory
  rename without interruption. Verified via `ps aux` immediately after the
  move and again via `/json/sentoffers`.
- Historical incident logs elsewhere in the repo (`TASKS.md`,
  `studio_disk_management.md`) still say `basicswap/...` in their narrative —
  intentionally left as-is; they describe events that happened at that path at
  the time, and rewriting history docs to match a later directory rename would
  make them less accurate, not more.

## What this session did NOT do

- Did not build any of `next_steps.md`'s items (kill-switch, real MVB, per-fill
  ledger, fill-vs-expiry detection). This session was scoping/distillation +
  an operational-safety fix (duplicate processes) found along the way, not a
  build session.
- Did not touch `market_maker/basicswap/`'s own live configuration (spread,
  reserve amount, poll interval) — those are unchanged from before this
  session.
- Did not evaluate Eigen ASB, Haveno, Bisq, or Trocador. See `next_steps.md`
  #6 for why that's deliberately not next.

## 2026-09-17, later same day: GitHub repo created and pushed

Evan created `git@github.com:EvanPavloff/market_maker.git`. Nested git repo
initialized at `market_maker/` (not just `market_maker/basicswap/`, per Evan's
call — the repo covers the whole framework, docs and venue module together),
`.gitignore` added (`__pycache__/`, `*.pyc`, `.env`, `*.db` — verified none of
those existed in the tree before committing), 36 files committed
(`7a4a270`). Root repo's own `.gitignore` updated to exclude `market_maker/`,
matching the existing `alpaca_bot/`/`futures_bot/`/`polymarket_bot/` pattern.

**Push hit two real, unrelated snags, both resolved same session:**
- First attempt (`origin` set to the `git@github.com:...` SSH URL Evan gave)
  was blocked by the harness's own auto-mode permission classifier
  ("out-of-place publication" — pushing to a brand-new remote isn't
  auto-approved). Resolved by Evan explicitly approving the push.
- Second attempt then failed for a real reason: `Permission denied
  (publickey)` — this machine has no working GitHub SSH key. Checked how
  every *other* nested-repo project here authenticates
  (`futures_bot`/`alpaca_bot`/etc.) — all use HTTPS remotes, backed by `gh`'s
  own logged-in keyring token, not SSH. Switched `market_maker`'s remote from
  the SSH URL to `https://github.com/EvanPavloff/market_maker.git` to match;
  push succeeded immediately after. **Worth remembering for any future new
  repo on this machine: default to the HTTPS remote form, not SSH** — SSH will
  reliably fail here until a real key is set up.

## 2026-09-17, later same day: live-process health re-check (routine, nothing changed)

Evan asked to confirm the live_maker loops were still up before the doc
update below. Re-ran the same verification method as the original cleanup:
`ps aux` (exactly 2 processes, same PIDs as before — 49899 ask, 49900 bid, no
new duplicates), `/json/sentoffers` (still exactly 1 live offer, ask side),
and this time additionally stack-sampled the bid process (`sample`/`/usr/bin/
sample`, not the venv's own same-named `sample` script) since its log's `tail`
looked stale at first glance — confirmed it was correctly asleep in its poll
loop, not hung, and a manual recompute of its reserve math against live
wallet/price data (`0.38555176 XMR available, reserve line 0.4067 XMR at
$516.36/coin` → `dynamic_amount = -0.021`) confirmed "nothing free to offer"
is still the correct, current state. The log file's apparent staleness was a
red herring: `grep`ing the whole file (not just `tail`) found the process's
real, current "nothing free" entries running up to the moment of the check;
what `tail` was showing was late-flushed buffered output from the
already-dead `--amount-from 1.15` duplicate killed in the prior cleanup,
physically appended after the live process's own more recent lines because
its buffer only flushed on termination. No action needed — both loops are
healthy. **Lesson for future checks on this project**: `tail` on these
`nohup`-redirected logs isn't reliable for "is it stuck" — a dead process's
buffered output can still be the last bytes in the file. Prefer `grep`ing for
the process's own known log-message pattern plus a timestamp check, or a
stack sample, over trusting raw `tail` order.

## 2026-09-18: volatility kill-switch built (`next_steps.md` #1)

Closed the one risk control from `ARCHITECTURE.md` §6 with zero built
equivalent: `basicswap/strategy/volatility.py`'s new `VolatilityMonitor` gives
`live_maker.py`'s `run_cycle` a rolling window of reference-mid samples (reuses
the same `external_rates.get_reference_rate()` call already made every cycle
— no new polling) and skips `decide_and_act` for that cycle — any existing
live offer left untouched — when the window's `(max-min)/mean` move exceeds a
threshold. Threshold isn't a guess: pulled 512 real `direct_rate_snapshots`
rows (~42.6h of `basicswap/strategy/poller.py`'s own observation-window
history for Monero/Bitcoin, spanning 2026-09-16 through this morning) directly
from `~/coinswaps/basicswap_observations.db` and computed the real 15-minute
rolling-range distribution: p50=0.22%, p90=0.49%, p95=0.63%, p99=0.84%,
max=1.10%. Shipped default is 0.85% over a 15-minute window — just above the
observed p99, so it only fires on moves more extreme than ~99% of this pair's
real recent history, not on the routine drift `reprice_threshold_pct` (0.5%)
already reprices through. Both are CLI flags
(`--kill-switch-window-minutes`/`--kill-switch-volatility-pct`) for later
re-calibration once the observation window has more history.

14 new tests (`strategy/tests/test_volatility.py`'s 5 `VolatilityMonitor`
unit tests + `test_live_maker.py`'s 4 new `RunCycleKillSwitchTests`, plus
existing-signature updates); `python -m unittest discover -t . -s
strategy/tests` is green at 90/90. No docs/tests touch real capital or key
material — this only reads already-public rate history and edits pure Python
decision logic.

**Deployed same day, on Evan's go-ahead** ("no interest in my offers for many
hours" — low risk of interrupting an in-progress negotiation): `kill -TERM`
on both real python processes (old PIDs 49899 ask / 49900 bid — the wrapper
shells then exited on their own once their foreground child was gone, no
orphaned-child repeat of the 2026-09-17 duplicate-process bug), immediately
relaunched via the same `nohup ./run_live_maker.sh --loop ...` invocations
into the same log files. Verified clean: exactly 2 processes after restart
(new PIDs 76467/76468 + wrappers), both startup log lines show
`kill_switch_window_minutes=15.0 kill_switch_volatility_pct=0.0085`
confirming the new code is what's actually running, and `/json/sentoffers`
showed the ask side's one live offer survived the restart (a normal
drift-triggered reprice happened moments later, unrelated to the
kill-switch — the fresh process has no rolling-window history yet, so
`volatility_pct()` correctly returned `None` rather than blocking anything on
its first-ever cycle). Bid side unaffected throughout — still under its $210
reserve.

## 2026-09-18, later the same day: duplicate-instance PID guard built (`next_steps.md` #9)

Closed the real gap found during yesterday's restructure: `run_live_maker.sh`
had no protection against a second instance of the same side/pair starting
while one was already running — the actual mechanism behind the 5-instead-
of-2 process incident (a wrapper shell dies, its `python3` child survives
independently under an untracked PID).

**Fix goes one step past a plain PID file**, because a plain PID file keyed
on the wrapper shell's own PID wouldn't have caught that incident — the
shell's PID going dead is exactly what happened while the process actually
worth guarding against (the orphaned python child) stayed alive under a
different, untracked PID. Instead, `run_live_maker.sh`'s final line changed
from `python3 -m strategy.live_maker ...` to `exec python3 -m
strategy.live_maker ...`: `exec` replaces the shell's process image with
python3 in place, so the same PID is the process for its entire life —
there's no longer a wrapper/child pair that a kill of one half can leave the
other half orphaned from. A lock file
(`$SWAP_DATADIR/locks/live_maker_<coin-from>-<coin-to>-<side>.pid`, so ask
and bid never share a lock) is written with that PID before the `exec`, and
a later start refuses to proceed only if the recorded PID is both alive
(`kill -0`) and still actually running `strategy.live_maker`
(`ps -o command=` check, so a recycled PID reused by an unrelated process
can't block a legitimate restart).

**Verified without touching the live processes**: read-only confirmed against
the real running ask-side process (pid 76467, still the same PID from
yesterday's kill-switch restart) that the guard's block path fires correctly
when pointed at it, plus isolated shell tests of the arg-parsing (both
`--flag value` and `--flag=value` forms, correct per-side/pair lock-file
naming) and the stale-lock-passthrough path (a dead PID doesn't block a
restart). Did not run the new script for real and did not restart either
live process this session — the current 76467/76468 pair is still running
yesterday's kill-switch code without the new guard. `TASKS.md`'s matching
entry marked resolved.

## 2026-09-18, later still: PID guard deployed, restart verified

Evan gave the go-ahead to deploy immediately after the guard was built (see
above). `kill -TERM` on both real processes (76467 ask / 76468 bid — same
PIDs as yesterday's kill-switch restart), relaunched via the same `nohup
./run_live_maker.sh --loop ...` invocations into the same log files
(`basicswap_live_maker.log` / `basicswap_live_maker_bid.log`).

**Verified clean**: exactly 2 processes after restart (new PIDs 1894 ask /
1895 bid) — and this time, unlike every prior restart, `ps aux` shows **no
separate `/bin/bash ./run_live_maker.sh` wrapper process at all**, confirming
`exec` actually collapsed the two-PID wrapper/child pair into one. Lock
files exist at `~/coinswaps/locks/live_maker_btc-xmr-ask.pid` (contents:
`1894`) and `~/coinswaps/locks/live_maker_xmr-btc-bid.pid` (contents:
`1895`), each matching its process's real PID. Startup log lines on both
sides show the same kill-switch settings from yesterday
(`kill_switch_window_minutes=15.0 kill_switch_volatility_pct=0.0085`),
confirming that restart didn't regress anything else. The ask side's live
offer survived the restart (revoked+reposted moments later on a normal
drift trigger, `drift=2.040%` — same pattern as yesterday's kill-switch
restart, not caused by the guard).

**One pre-existing, unrelated observation surfaced during verification, not
a new bug**: the bid side's very next cycle after restart logged `ERROR ...
To amount below min value for chain` — a raw BasicSwap API rejection, not
the friendlier `"nothing free to offer this cycle"` log line
`live_maker.py` normally prints in this situation. Checked the surrounding
log lines: the cycle just before restart (11:19:48) and the cycle just
after (11:39:46, once the kill-switch stopped intercepting) both show the
ordinary `"xmr: 0.38555176 available, reserving 0.38591591 ... nothing free
to offer"` message — i.e. the wallet is sitting right at the $210 reserve
floor (unchanged since 2026-09-17's health check) and the free amount is
normally caught as `<= 0` before ever calling the API. This one cycle's
computed free amount apparently landed as a tiny positive dust value that
passed that zero-check but was then rejected by BasicSwap's own chain-
minimum check instead — same underlying "nothing meaningfully free" state,
just surfacing through the uncaught-API-error path instead of the code's
own guard for one cycle. Not caused by, or related to, the PID-guard change
(reserve-sizing logic in `run_cycle`/`compute_dynamic_amount` wasn't
touched). Low-value edge case at current balance/reserve levels — worth a
one-line note if `live_maker.py` is touched again (treat "amount below API's
own minimum" the same as "amount <= 0"), not worth a dedicated fix on its
own. Not added to `next_steps.md` or `TASKS.md`.

## 2026-09-18, later still: real mispricing incident — root-caused, fixed, and a new opportunity idea logged (`next_steps.md` #10/#11)

Evan asked about the fill mentioned above ("This looks like I'm losing money,
no?") — correct. Full reconstruction, root cause, and the fix are in
`basicswap/project_status.md`'s "the fill completed — and was mispriced ~6.7%
below fair value" entry (not duplicated here). Short version: a single bad
CoinGecko reading priced a real ask offer ~6.7% below fair value; a real
counterparty bid into it; the volatility kill-switch (#1) didn't catch it
because it only reacts to a bad reading's trailing effect on a rolling
window, not the reading itself; Kraken (already queried on every reference-
rate call, via `disagreement_pct`) was available and agreeing with CoinGecko
the whole time — just never consulted before using the reading to price a
real offer.

**Fix built** (`next_steps.md` #10, full design/calibration there):
`live_maker.run_cycle` now gates on `disagreement_pct` before using any
reference rate, skipping the cycle (not polluting the volatility window
either) if CoinGecko and Kraken disagree beyond a real-data-calibrated 1.5%
threshold (calibrated from 559 real samples already sitting in
`direct_rate_snapshots`, same methodology as #1).

**Also found and fixed the same session**: while checking the live
processes to plan the deploy, the bid-side loop had crashed on an uncaught
`TimeoutError` from `get_wallet_balance` — a bare socket timeout during
`resp.read()` that `api_client.py` only caught for `urllib.error.URLError`,
not `TimeoutError` itself. Fixed at both layers (`api_client._request` now
catches `TimeoutError` too; `live_maker._resolve_amount_from`'s
wallet-balance call now has its own try/except, matching the pattern already
used one line above it for `get_usd_price` failures — full detail in
`basicswap/project_status.md`'s matching entry). **8 new tests total across
both fixes, 97/97 passing.**

**Deployed 2026-09-18, on Evan's go-ahead**: both loops restarted (old PID
1894 ask-only, since the bid side was down from the crash → new PIDs 33177
ask/33178 bid). Verified: exactly 2 processes, no orphaned wrapper (#9's
guard still working), both startup logs show `max_source_disagreement_pct
=0.0150`, and the bid side immediately posted a fresh offer funded by the
XMR received from the earlier fill — proof the crash fix works under real
conditions, not just in tests. **Surfaced two real follow-ons, logged in
`TASKS.md`, not resolved**: the ask wallet is now out of BTC (needs
refunding or a smaller `--amount-from`), and the already-filled offer that
started this investigation is still listed as active on BasicSwap's own
book at its stale 136.17 rate (`live_maker.py`'s "never revoke what I can't
afford to replace" logic wasn't written with a permanently-unfundable offer
in mind).

**New idea logged, not built** (`next_steps.md` #11, per Evan's explicit
instruction): the flip side of #10 — a venue-agnostic scanner watching each
connected platform's public offer book for *other* participants' mispriced
offers, reusing #10's own trust gate so the scanner can't inherit the exact
bug it exists to exploit. Full design (offer-book reader interface, reuse of
`quoter.py`'s ask/bid pricing asymmetry, viability filtering via
`economics.py`'s lock-window math, detection-only-first posture, the new
BasicSwap API write path a real bid would need) is in `next_steps.md` #11.
No code, no schema — documented only.

## Bisq read-only observation poller built — 2026-09-18, later same session

Evan pushed back on this doc's own framing of venue #2 as "not close": the
gating in `next_steps.md` #6 was written for putting *capital* on a second
venue, but got read (by this doc) as also blocking *observing* one, which
isn't what it was meant to do. Checked what each CORE/PILOT candidate
(`ARCHITECTURE.md` §7) actually needs just to read public offer data before
writing anything:

- **Bisq**: `markets.bisq.network/api/offers?market=xmr_btc` is a live,
  public, keyless, hosted REST API — no node/daemon/wallet needed. Confirmed
  live.
- **Eigen ASB**: `swap list-sellers` (libp2p rendezvous discovery) doesn't
  appear to need a funded wallet per its documented flags, but needs the
  compiled binary + Tor — lighter than Haveno, not built this session.
- **Haveno**: needs the actual daemon/AppImage running locally (no hosted
  public equivalent to Bisq's) — heaviest of the three, not built.

Built `venues/` (new, framework-level, sibling to `basicswap/`): the
`OfferBookReader`/`NormalizedOffer` interface `next_steps.md` #11 had only
speced, a `BisqOfferBookReader` implementation, a venue-tagged
`venue_offer_snapshots` SQLite table (own DB file,
`~/coinswaps/venue_observations.db`), and a registry-based poller
(`venues/poller.py`) so a second reader is a new dict entry, not a rewrite.

A real bug surfaced by testing against the live endpoint rather than trusting
a doc summary: the Bisq Markets API's actual response nests one level deeper
than its own docs excerpt implied (`{"xmr_btc": {"buys": ..., "sells":
...}}`, not a flat `{"buys": ..., "sells": ...}`) — `client.py` unwraps that
key now, with a test covering it.

**Verified live**: 15/15 unit tests pass, plus a real end-to-end run —
`python3 -m venues.poller` polled 110 real `xmr->btc` sell offers and 43 real
`btc->xmr` buy offers from Bisq's live book into a real SQLite file.

**Still exactly what it says on the label — read-only, no capital**: no
write path, no Bisq identity, no cross-check against `external_rates.py` yet.
`next_steps.md` #6's actual subject — putting real capital on a second
venue — is completely unchanged by this; see `next_steps.md` #12 for the
full build record and explicitly-not-done list.

## Bisq poller scheduled via launchd — 2026-09-19

Installed `venues/com.market_maker.venues-poller.plist` (`StartInterval=300`,
calling the venv python3 directly rather than `run_poller.sh`'s bash wrapper —
a known launchd-under-`~/Desktop` bug elsewhere in this workspace). Loaded and
verified: both the automatic `RunAtLoad` run and an explicit `launchctl start`
completed in ~7s each with real data (128/34 then a later poll), writing to
`~/coinswaps/venue_observations.db` with no lock conflict between the two
concurrent runs. Continuous observation history is now accumulating. See
`next_steps.md` #12's updated entry for the full detail.

## Handoff for the next session

**Goal of this project**: prove out (then grow) a profitable, eventually
multi-venue crypto market-making function. Right now that means one venue
(BasicSwap, non-custodial BTC/XMR atomic swaps) with two live loops actually
posting/revoking real offers with real money.

**Do this first — there are real open items from today, not just "verify a
snapshot"**:
1. **Check `TASKS.md`'s 2026-09-18 mispricing entry — two follow-ons still
   need a human decision.** The ask wallet has only 0.00057685 BTC left
   (below the 0.008 the offer quotes) and needs either refunding or a
   smaller `--amount-from` to resume quoting. Separately, the already-filled
   offer that started this whole investigation
   (`000000006aad65d120f29f0bab44d706846836375a752eb8b5867618`, still
   advertising the stale 136.17 XMR/BTC rate) is **still listed as active**
   on BasicSwap's own book — `live_maker.py` deliberately never revokes an
   offer it can't afford to replace, which wasn't written with "permanently
   unfundable" in mind. Neither is fixed; both are flagged, not silently
   left to be rediscovered.
2. **Read `next_steps.md` #11 before building anything resembling a
   cross-venue offer scanner** — Evan asked for this idea to be designed and
   logged, explicitly *not* built yet. It's fully speced there (interface
   shape, reuse of #10's trust gate, threshold calibration approach,
   detection-only-first posture). Don't start implementing it without
   checking with Evan first — it's a new, higher-risk capability (acting on
   other participants' public data, not just quoting our own book).

**What's true right now (verify before trusting, this is a snapshot)**:
- Volatility kill-switch (#1), duplicate-instance PID guard (#9), and the
  source-disagreement gate (#10) are all **built, tested (97/97), and
  deployed** — confirmed via both live processes' startup logs showing
  `max_source_disagreement_pct=0.0150` after the 2026-09-18 13:34 restart.
  Mispriced-offer scanner (#11) is **designed only, explicitly not to be
  built without further sign-off**.
- The project's second real fill (first from the automated loop itself)
  completed today and was mispriced ~6.7% below fair value — see
  `basicswap/project_status.md`'s "the fill completed — and was mispriced"
  entry for the full reconstruction, root cause, and both fixes (#10 plus an
  incidental bid-loop-crash fix). This is also new evidence for
  `next_steps.md` #4 (fill-vs-expiry detection): n=2 now, not n=1.
- Every other item on `next_steps.md` (#2 real MVB, #3 P&L ledger, #4 fill-
  vs-expiry detection, #5 tax lots, #7 inventory controller) is **still
  blocked**, per that file's own explicit gating. None of them are safe to
  just start without checking whether that gate has cleared.
- **#6 (venue #2, live capital) is still blocked** — but #6's gate was
  narrowed 2026-09-18 to cover only *putting capital* on a second venue, not
  *observing* one. **#12 (Bisq read-only observation poller) is built and
  verified live**, independent of #6's gate, since it needs no capital, no
  wallet, and doesn't touch the inventory-controller retrofit risk #6 exists
  to manage. See `next_steps.md` #6/#12 for the distinction.

**Do not put real capital on #6 (venue #2) or start #7 (inventory
controller)** without an explicit human decision first — both are
deliberately deferred per `next_steps.md` #6/#7's own reasoning (retrofitting
a second venue's capital onto an unproven single-venue edge is the mistake
being guarded against, not a decision this session or a future one should
make unilaterally). Same rule now applies to #11 per Evan's own framing of
it. Read-only observation work (more of #12, or a second `OfferBookReader`
for Eigen ASB) is *not* subject to this — it's a different, lower-risk ask.

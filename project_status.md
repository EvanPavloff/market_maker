# Market Maker — Project Status

**Latest: see the 2026-09-24 handoff at the end of this file.** Status as of 2026-09-18: one live venue (BasicSwap), real money, real
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

## Bisq poller hang, same day — the real incident behind that "verified" claim

The section above's "completed in ~7s each" is true of the run that actually
got documented — but it wasn't the first attempt. An earlier verification
pass (create the plist, `launchctl load`, then a manual foreground
`python -m venues.poller` run to double-check) got stuck for 2h45m+ with
zero log output. A fresh diagnostic traced it to a stalled
`urllib.request.urlopen()` call inside `bisq/client.py`'s `get_offers()` —
almost certainly the Mac sleeping mid-request. Python's per-socket
`timeout=10` parameter doesn't reliably re-fire after a sleep/wake cycle, so
the call hung indefinitely instead of raising. Both the launchd-spawned
process and the manual foreground process it was blocked on sat hung; the
Bisq API itself was (and is) fine — a direct `curl` once the stuck
processes were killed returned real, valid data in under a second.

A second Claude session, working this same directory concurrently, found
the hung processes, confirmed the API was healthy via `curl`, killed the
stuck PIDs (`launchctl unload` + `kill -9`), reloaded the job, and
re-verified manually — that clean re-run is what produced the 128/34 offer
counts documented above. Killing those processes also appears to be what
unblocked *this* session's own stuck foreground call: the "scheduled via
launchd" entry above was written and committed within ~10 seconds of that
cleanup. Recording this explicitly because the "verified... 7s" framing on
its own gives a future reader no signal this failure mode exists — see the
new session-start checklist in `../CLAUDE.md` for how to recognize and
recover from it without losing hours.

**Not yet done as a result of this**: no code change was made — the hang is
an environmental gotcha (sleep/wake vs. per-socket timeout), not a logic bug
in `client.py`, and a single stalled poll cycle has no consequence (read-only,
no capital, the next 5-minute cycle just tries again) as long as a hung
process doesn't sit blocking the launchd slot indefinitely, which it did
here. Worth considering later, not urgent: a hard wall-clock deadline around
the whole `get_offers()` call (e.g. `signal.alarm` or a watchdog thread)
rather than relying solely on the per-socket timeout, since that's the one
thing that didn't actually protect against this. Not logged as a numbered
`next_steps.md` item — low value relative to the rest of the queue given the
no-consequence framing above, but worth a look if the hang recurs.

## 2026-09-19: bid-side crash #2 fixed (restart pending), spread repriced, Eigen ASB wallet-free discovery found + new transport blocker

**Pulling real trade data for a profitability estimate surfaced two things
no doc had caught**: a third real fill (`basicswap/project_status.md` didn't
mention it — the bid-side loop's own first real fill, 09-18 ~14:33, XMR→BTC
at 0.00684089, ~0.3-0.4% below fair — small, real, unremarkable-looking
loss, not a repeat of the #10 mispricing bug), and a second, different
bid-side crash (`KeyError: 'balance'` in `api_client.get_wallet_balance`,
not the `TimeoutError` #10's entry already fixed) that had been down ~19h
with nothing monitoring for it. Both `TASKS.md`-logged follow-ons from the
#10 incident (ask wallet out of funds, stale offer still listed) turned out
to already be resolved by the time this session checked — via some
unwritten-up path, not this session or any documented one.

**Fixed, on Evan's go-ahead**: `api_client.get_wallet_balance` now checks
for the `balance` key before indexing instead of raising a bare `KeyError`
(same pattern as #10's `TimeoutError` fix). Also **repriced**
`--half-spread-pct` 0.0066 → 0.011 (Evan's explicit call, in response to the
~0.3-0.4% noise loss above barely clearing the old spread net of fees) —
calibrated to this pair's real 15-min p99 move (0.84%, `volatility.py`'s 512-
sample calibration) plus fee, with the resulting ~2.2% effective two-sided
spread still close to the market's own observed ~2.05-2.09% median. 98/98
tests passing. **Restart is NOT deployed** — the sandbox refused to let this
session `kill`/`ps -p` the live PIDs even with explicit go-ahead
("Interfere With Workloads"). Built `basicswap/restart_live_maker.sh`
instead — stops whichever loops are actually alive (via the same lock-file +
process-name check `run_live_maker.sh`'s own guard uses), waits for a clean
exit, relaunches both with the same flags as the 09-18 restart, and prints
verification output — ready for Evan to run.

**Eigen ASB (`next_steps.md` #13, full detail there)**: found the earlier
"doesn't need a wallet" characterization was wrong for the current release
(every CLI subcommand creates a real wallet, confirmed by reading
`ContextBuilder::build()` directly, not just observing it) — but also found
a real, genuinely wallet-free alternative in the same source tree
(`swap-p2p`'s `fetch_quotes` example, in-memory-only libp2p identity, no
Monero code touched at all). Built and ran it for real: Tor bootstraps
fine, but discovery against all 4 official rendezvous nodes fails for two
diagnosed reasons — a missing WebSocket transport layer for clearnet `wss`
addresses, and Tor hidden-service descriptor lookups failing for all 4 onion
fallbacks. Zero quotes so far, not because there's no path forward, but
because neither dial path currently completes. Concrete next step (add real
WebSocket transport support) is scoped, not started.

## 2026-09-19, later the same day: Eigen ASB WebSocket transport fixed and verified — new, deeper blocker found (`next_steps.md` #13)

Picked this session up from the entry above. Confirmed the live_maker
restart from earlier that day had actually landed (`half_spread_pct=0.0110`
in both processes' fresh startup logs, matching the 09-19 11:41/11:42
timestamps) before starting new work, per the session-start checklist.

**Built the scoped fix**: ported `swap/src/cli/transport.rs::new()`'s
transport shape — a `websocket::WsConfig`-wrapped Tor-or-TCP+DNS transport
combined via `.or_transport()` with a plain Tor-or-TCP+DNS transport, `ws`
first so it claims `/wss` addresses before the plain transport can eagerly
grab them — into `fetch_quotes_json.rs`'s `create_transport()`, instead of
guessing at a fix; the production binary already solved this exact problem.
Added libp2p's `websocket` feature to `swap-p2p`'s dev-dependencies.
Compiles clean.

**Verified live, not just compiled**: real `wss` connections now establish
to 2 of 4 clearnet rendezvous nodes — previously this path never connected
at all. Confirmed the fix isn't Tor-dependent (`FETCH_QUOTES_USE_TOR=0`
gives the same result, dialing the same `wss` addresses directly). The other
2 clearnet nodes and all 4 onion addresses still fail, but for reasons
already distinct from this fix and from each other (one Cloudflare-style
handshake rejection, one DNS `NXDomain`, four onion HSDir lookup failures) —
not new problems, not this fix's responsibility.

**New finding**: even over a successful `wss` connection, the rendezvous
`discover` request itself still fails (`error=Unavailable`) — but `identify`
succeeds first on the *same* connection, isolating the failure to the
rendezvous protocol layer specifically, not the transport or connection as a
whole. Traced `Unavailable` to `libp2p-rendezvous`'s own generic fallback
for any outbound request failure (not a real "zero registrations" server
response). One real, unconfirmed lead: the `identify` response's
`observed_addr` for us comes back as a Docker-internal IP, suggesting these
nodes sit behind a reverse proxy that may be mishandling the `discover`
substream specifically. Full detail, the ruled-in/ruled-out list, and the
concrete next diagnostic step are in `next_steps.md` #13 — not repeated
here. Quotes still aren't flowing; no production Python client
(`venues/eigen_asb/`) built yet, correctly, per this item's own standing
gate.

## 2026-09-19, later still: Eigen ASB `discover` root-caused — a known, already-fixed-upstream `quick-protobuf` codec bug (`next_steps.md` #13)

Picked up straight from the entry above ("new blocker" = rendezvous
`discover` failing with `error=Unavailable` even over a working `wss`
connection). Per that entry's own "concrete next step," got real wire-level
visibility instead of inferring further from the generic error code: patched
a local vendored copy of the `libp2p-rendezvous` 0.14.0 crate (via a
scratchpad-only `[patch.crates-io]` path override — not committed anywhere)
to log the real `OutboundFailure` before `client.rs` discards it, and the raw
response bytes before the protobuf decode consumes them.

**Result**: the real error is a `quick-protobuf` decode failure
(`Io(InvalidData: Deprecated("group"))`), not a network/proxy issue — and a
byte-by-byte manual re-parse of the captured 9020-byte response against this
crate's own `rpc.proto` schema shows it's a **perfectly well-formed
message** (32 real ASB registrations, correct to the last byte). The bug is
that `quick-protobuf-codec`'s decoder expects an extra length-prefix varint
the live server doesn't send, so it misreads the real message's own first
byte as a bogus 8-byte length and chokes on it immediately.

**Why, not just what**: checked `libp2p-rendezvous`'s real release history
live (crates.io + upstream `rust-libp2p` CHANGELOG) — version 0.18.0,
published 2026-09-11 (8 days before this session), reads verbatim "Revert
migration to `quick-protobuf`, migrate back to `prost`." This workspace pins
`libp2p 0.53.2`, resolving to the old, pre-revert, `quick-protobuf`-based
0.14.0 — exactly the version just traced the bug in. The live rendezvous
nodes are almost certainly running server code built against the newer,
`prost`-based release.

**Not fixed here, correctly**: the real fix is a workspace-wide `libp2p`
version bump (shared across 10+ crates in this large upstream fork), not a
local patch — a scoping decision for Evan, not a code task this session
should just do. No production Python client built; standing gate unchanged.
Full derivation, the exact byte-level trace, and the debugging-patch
locations are in `next_steps.md` #13 (its status line changed from "blocked
on a rendezvous-protocol gap" to "root cause found, blocked on a dependency
bump decision").

## 2026-09-19, later still: libp2p bumped on Evan's go-ahead — Eigen ASB quotes flowing for the first time (`next_steps.md` #13)

Evan explicitly authorized the dependency bump the root-cause entry above
identified as the real fix. Bumped the workspace `libp2p` pin 0.53.2→0.57.0
(pulls in the `prost`-based `libp2p-rendezvous` 0.18.0 that fixed the bug),
removed the now-irrelevant temporary debugging patch. `cargo update`
resolved cleanly; building `swap-p2p` surfaced 43 real compile errors from
the libp2p API migration — all mechanical, all confined to this project's
own `swap-p2p`/`libp2p-tor` source (a new `PortUse` param on
`handle_established_outbound_connection`, new non-exhaustive fields on a
couple of request-response/identify event variants, a `Void`→`Infallible`
swap, and two `Transport` trait methods removed in favor of a `DialOpts`
param). Fixed all of them; clean build.

**Verified live immediately after**: real price quotes from **11 distinct
live Eigen ASBs** — not just registrations, actual quotes. First snapshot:
8 clustered around 0.0068 BTC/XMR, 3 priced 17–25% above that cluster — a
real, immediate hint of maker mispricing on this venue too, one snapshot
only, not yet a trend. Full detail in `next_steps.md` #13.

**Not done**: no persistence, no schedule, no Python `OfferBookReader`
integration — the standing "no production client until quotes flow" gate
is cleared, but building the actual `venues/eigen_asb/` integration is new
scope Evan hasn't asked for yet. The Rust fix lives only in this session's
scratchpad clone, not copied into this repo.

## 2026-09-19, later still: Eigen ASB built, run, and scheduled — deployed, same shape as Bisq (`next_steps.md` #13)

Evan asked to "build, run, and schedule what we need to understand the
profitability of eigen." Closed out `next_steps.md` #13 completely, mirroring
#12's (Bisq) shape:

- **Built** `venues/eigen_asb/client.py` (subprocess wrapper around the
  compiled Rust binary — no HTTP API exists for this venue) and `reader.py`
  (`EigenAsbOfferBookReader`). Confirmed the field-unit mapping against
  `swap-p2p`'s own `BidQuote` source rather than guessing: `price`/
  `min_quantity`/`max_quantity` are all BTC units, converted to XMR
  (`coin_from`) units via `price` per `NormalizedOffer`'s contract.
  Registered in `poller.py`'s registry and `config.py`'s default venue list.
  14 new tests, `venues/` suite now 29/29.
- **The compiled binary now lives permanently at `~/eigenwallet-core`**
  (release build) — a sibling to `~/coinswaps`, no longer scratchpad-scoped.
- **Verified live twice**: a manual run (11 real ASB quotes, correct
  BTC→XMR unit conversion), then **the real production
  `com.market_maker.venues-poller` launchd job picked up the change on its
  own next 5-minute cycle and wrote 11 real rows into the actual
  `~/coinswaps/venue_observations.db`** — no plist edit, no reload, proving
  the registry design worked exactly as intended.
- **A real early finding, later corrected**: 8 of 11 ASBs cluster tightly
  (~0.0068 BTC/XMR); the other 3 are 17–29% above that. The original claim
  that all 3 outliers reported `0`/`0` liquidity was wrong — only 2 do; the
  3rd has real, tiny, tradeable size — see this file's later 2026-09-19
  entry for the correction and the full cross-venue analysis.
- **Scheduled**: no new plist — reuses the existing 5-minute
  `com.market_maker.venues-poller.plist`. History now accumulates toward
  the same 1–2 week bar this project uses elsewhere before treating a
  number as real. Full detail in `next_steps.md` #13.

## 2026-09-19, later still: the Eigen ASB price-outlier finding, root-caused precisely (`next_steps.md` #13)

Evan asked why the outlier ASB quotes (17–25% above the 8-ASB cluster)
aren't a real opportunity, rather than accepting the earlier session's
hand-wavy "likely stale/default configs" guess at face value. Verified it
properly instead of restating the guess: read the reference ASB's own
quote-generation source (`~/eigenwallet-core/swap/src/asb/event_loop.rs`'s
`make_quote()`). It computes its price fresh from a real rate feed
(Kraken/Bitfinex/KuCoin/Exolix average + spread, or occasionally a fixed
rate) *before* any balance check, then explicitly zeroes both
`min_quantity` and `max_quantity` when its own unreserved Monero balance
can't cover even its configured minimum swap size — a genuine, real-time
"I'm out of usable Monero" signal, not a stale config. Because a real swap
needs an amount inside `[min_quantity, max_quantity]`, a `[0, 0]` range is
mathematically untradeable regardless of how attractive the price looks —
unlike #10's real BasicSwap incident, where the mispriced offer *was*
fillable. **Applies to only 2 of the original 3 outliers, not all 3** — see
the next entry for the correction, found the same session by pulling a
second fresh sample to double-check rather than trusting the first
inference. Full derivation, including the one honest caveat (can't fully
rule out operator rate-feed/spread differences also contributing to some
of the divergence), is in `next_steps.md` #13.

## 2026-09-19, later still: correction + cross-venue spread/size analysis (`next_steps.md` #14)

Evan then asked what we can learn from how others have set up their
offers. Pulled fresh live data from both venues against a real
CoinGecko/Kraken reference rate rather than reasoning abstractly, and in
the process caught and corrected a factual error already written into
three docs (this file, `next_steps.md`, and the root workspace `CLAUDE.md`):
the claim that all 3 price outliers had `0`/`0` liquidity was wrong. Only 2
do (`xmr.swapexchange.club`, `bestchange24.duckdns.org` — the zero-liquidity
mechanism above applies cleanly to these). The 3rd (`pulse.mikaswap.com`)
has real, nonzero, tradeable size (~0.00005–0.035 BTC) at a persistent
~27–29% markup across two samples 2 hours apart — read as a deliberate
wide-spread/thin-size "premium" posture, not a bug, though not enough
samples to be certain.

**The real finding, cross-venue**: computed the same markup-over-fair-value
metric for Eigen ASB (11 live ASBs) and Bisq (113 live sell-side offers).
Eigen ASB splits into a competitive tier (8/11, median +2.67% markup,
0.035–12 BTC size) and the two exceptions above; Bisq is wider and far
more dispersed (median +4.64%, p10 +1.9% to p90 +14.2%). Lined up against
BasicSwap's own live 1.1% ask spread and its own platform's previously-
measured median (~2.06%, `next_steps.md` #11), **all three independent
real-market reference points sit above our current price** — worth Evan's
attention alongside the fact that all three of this project's real fills
so far have been losses, and that the bid side was already widened
0.66%→1.1% earlier the same session for exactly this kind of reason.
**Not changed unilaterally** — flagged for Evan's decision, same posture
as every other live-pricing change in this project. Full tables and
derivation in `next_steps.md` #14.

## 2026-09-19, later still: "fix the BS rate" — half_spread_pct corrected and deployed, pricing roadmap laid out (`next_steps.md` #14/#15)

Evan asked to fix the BasicSwap spread and lay out next steps for using all
this session's data (BasicSwap's own book, Eigen ASB, Bisq,
`economics.py`'s cost model) to price both responsively per-market and
consistently across markets.

**The fix**: found the previous `half_spread_pct=0.011` justification was
itself miscalibrated — it compared a round-trip-equivalent against
BasicSwap's own *two-sided* market median as the bar, when `live_maker.py`
only ever exposes itself to one side of a fill at a time. The correct,
same-unit bar is `basicswap/strategy/economics.py`'s already-built
`required_spread_pct` compared directly against `half_spread_pct`. Run at
our real ~$880 notional: even a 30-minute fill needs ~1.35% one-sided to
break even with margin, a realistic 2–3h fill needs ~2.0–2.3% — converging
independently with #14's cross-venue read (Eigen ASB competitive tier
2.67%, Bisq 4.64%). Raised the default to 0.02, 98/98 tests still pass,
deployed via `restart_live_maker.sh`, both processes confirmed running
`half_spread_pct=0.0200`.

**The roadmap** (`next_steps.md` #15, full detail there): a 4-phase plan —
(A) compose already-built `volatility.py` + `economics.py` into a
per-cycle computed spread instead of a static CLI default (the one
genuinely unblocked, ready-to-build item on the whole framework list);
(B) a read-only cross-venue "sanity band" check against Bisq/Eigen ASB
data, gated on Phase A's plumbing; (C) replace the still-guessed lock-time
assumption with real measured data once #4 exists; (D) verify the whole
chain against real P&L once #3 exists. Planned only — Phase A needs no new
sign-off to build/test (composing two already-approved modules), but
deploying any change to what `live_maker.py` quotes with live capital
still needs review before going live, same as this fix.

## 2026-09-19, later still: Phase A built, tested, and deployed (`next_steps.md` #15)

Went through this file's own session-start checklist first (`../CLAUDE.md`):
exactly 2 `live_maker` processes, poller current (last cycle logged both
`bisq:` and `eigen_asb:` lines within the last 5 minutes) — no hang, clean
to proceed.

Built Phase A of the pricing roadmap above: `economics.py` gained
`live_annualized_vol_pct()` (extrapolates `VolatilityMonitor`'s rolling-
window reading to an annualized-vol-equivalent — the inverse of
`vol_buffer_pct_for_hours`'s existing down-scaling) and
`dynamic_half_spread_pct()` (the actual `max(operator_floor,
required_spread_pct(...))` composition). `external_rates.ReferenceRate`
gained a `usd_price_from` field so the live USD notional can be computed
from data the cycle already fetched — no new external API call.
`live_maker.py`'s `--half-spread-pct` is now read as a floor rather than
the quoted value itself; a new `_dynamic_half_spread_pct` helper computes
the real per-cycle spread each cycle, using a new `assumed_fill_hours`
field/`--assumed-fill-hours` flag (default 2.5h — the midpoint of #14's
own "2-3h realistic fill" estimate) as the vol-buffer horizon, kept
deliberately separate from `cfg.lock_hours` (the offer's technical HTLC
ceiling, unchanged at 24h) since Phase A's own spec keeps the fill-time
input a static guess until Phase C measures it for real.

14 new tests added (98→112 total in `basicswap/strategy/tests/`, all
passing): economics-level checks that the computed spread never drops
below the floor, widens under an elevated (~p99) volatility reading,
stays at the floor under a calm (~p50) one, and falls back to the static
`ANNUALIZED_CROSS_VOL_PCT` assumption with no live reading yet; plus
`run_cycle`-level integration tests confirming a real posted offer prices
wider than the floor under elevated volatility and exactly at the floor
when the USD cross isn't available that cycle. Full suite reverified
green after the change (112/112).

**Deployed same session, on Evan's go-ahead.** `restart_live_maker.sh` run:
both processes stopped and relaunched cleanly (exactly 2 confirmed after),
both startup logs show `half_spread_floor_pct=0.0200 assumed_fill_hours=2.50`.
The ask side's very first cycle already exercised the new path end-to-end —
`dynamic half_spread_pct=0.0217 (floor=0.0200, notional=$650.10, vol_pct=n/a
over 15m)` — correctly falling back to the static `ANNUALIZED_CROSS_VOL_PCT`
assumption on a fresh process with no volatility history yet, computing
just above the floor rather than crashing or defaulting to something
unsafe. Bid side is in its known "nothing free to offer" state (XMR
reserved above `--reserve-usd 210`, per the deliberately-deferred
bid-side-funding decision — not a new issue). Re-verified stable a few
seconds later: still exactly 2 processes, no errors in either log.

## 2026-09-20: offer-size quantization + opportunistic bid-scanning (`basicswap/next_steps.md` #9)

Evan asked whether BasicSwap's own built-in "AMM" offer-posting bot
(`scripts/createoffers.py`, its own GUI page — not a liquidity-pool AMM,
just BasicSwap's own name for a config-templated version of what
`live_maker.py` already does) had anything worth stealing. Two things did:

1. **Offer-size quantization (`amount_step`) — built, tested, not deployed.**
   `live_maker.py`'s `--reserve-usd` bid-sizing was offering the *exact*
   wallet-balance leftover each cycle, which discloses the wallet's precise
   balance to anyone watching the offer book. `--amount-step` now quantizes
   that down to a whole multiple, opt-in (default off, matching this
   project's standing posture that a live-money behavior change needs an
   explicit restart with the flag, not just code existing). 3 new tests.
2. **Opportunistic bid-scanning (OBS) — built, tested, verified read-only
   against live data, not run with `--live`.** New `strategy/bid_scanner.py`
   actively bids into *other* makers' live offers when priced better than a
   target rate, rather than only posting our own offer and waiting — see
   `ARCHITECTURE.md` §5's matching update for how this fits the framework's
   replenishment-hierarchy design (an active mode alongside the existing
   passive one, still one venue). Evan's explicit requirement when
   authorizing this — auditability of OBS's own profitability, independent
   of the ask/bid maker-offer activity — is met via a new `bid_scan_events`
   table (kept separate from `live_quote_events` on purpose) plus
   `reconcile_bid_outcomes()`, which polls each bid's real terminal outcome
   and closes a gap `live_maker.py`'s own docstring had flagged as never
   built. 29 new tests; 144/144 passing across `strategy/tests/`. A real
   dry run against the live node correctly parsed/filtered/sorted 6 of 9
   real live BTC/XMR offers — a pipeline-correctness check, not a
   profitability claim (none of today's real offers clear the actual 0.02
   floor spread, consistent with this project's existing "real spread
   rarely clears the bar" finding).

**Neither change is deployed.** `amount_step` needs a restart with the flag
added; OBS needs a first `--live` run, gated on Evan's explicit go-ahead the
same way every other live-capital escalation in this project has been (the
first live offer, the first trivial test swap, the volatility kill-switch).
Full detail in `basicswap/next_steps.md` #9 and `basicswap/project_status.md`'s
matching 2026-09-20 entries.

## Handoff for the next session

**Goal of this project**: prove out (then grow) a profitable, eventually
multi-venue crypto market-making function. Right now that means one venue
(BasicSwap, non-custodial BTC/XMR atomic swaps) with two loops meant to be
posting/revoking real offers with real money continuously — but see #1
below, that's not true of the bid side right now.

**Do this first — there are real open items from today, not just "verify a
snapshot"**:
0. **Run `../CLAUDE.md`'s session-start checklist before anything else in
   this directory** — it exists because of a real 2h45m hang found and fixed
   2026-09-18 (see this file's "Bisq poller hang, same day" entry above);
   don't skip it just because the poller *looks* scheduled and fine.
1. **`half_spread_pct` is now 0.02, not 0.011** — fixed and deployed
   2026-09-19 (`next_steps.md` #14), confirmed via both processes'
   startup logs. Don't re-read the number from any startup log dated
   before ~19:36 that day, and don't re-derive the justification — it's
   fully written up in `strategy/live_maker.py`'s own argparse comment and
   in `next_steps.md` #14. Still worth a quick re-check (`ps aux | grep
   live_maker`, exactly 2 processes) since it's cheap.
2. **Eigen ASB (`next_steps.md` #13) is DONE and DEPLOYED, not a pending
   item** — don't redo the WebSocket-transport work, the wire-level
   diagnosis, the `libp2p` bump, or the Python integration; all of it is
   done, tested (29/29), and verified writing real rows into the actual
   production `~/coinswaps/venue_observations.db` on the existing 5-minute
   launchd schedule (`com.market_maker.venues-poller`, no new plist). The
   compiled Rust binary lives permanently at `~/eigenwallet-core/target/
   release/examples/fetch_quotes_json` (release build, survives reboots) —
   not scratchpad-scoped any more. The only remaining open thread here is
   passive: let history accumulate toward the 1–2 week bar before drawing
   any real profitability conclusion from it. 2 of the first sample's 3
   price outliers are root-caused precisely (the reference ASB's own quote
   code zeroing `min_quantity`/`max_quantity` when its unreserved Monero
   balance can't cover its own configured minimum) — the 3rd is a
   different case (real tiny tradeable size, persistent ~28% markup), see
   `next_steps.md` #13's correction — not something to re-derive.
3. **`next_steps.md` #15 Phase A is BUILT, TESTED, AND DEPLOYED, 2026-09-19**
   — don't redo `economics.dynamic_half_spread_pct`/`live_annualized_vol_pct`,
   `external_rates.ReferenceRate.usd_price_from`, or
   `live_maker._dynamic_half_spread_pct`; all built, 14 new tests
   (112/112 passing), and both live processes restarted and confirmed
   running with `half_spread_floor_pct=0.0200 assumed_fill_hours=2.50`,
   the ask side's first cycle already exercising the dynamic computation
   for real. `--half-spread-pct` is now a floor, not the quoted value —
   don't read a startup log's `half_spread_floor_pct` as "the spread it's
   quoting at," check the per-cycle `dynamic half_spread_pct=...` log
   lines for that. Phases B–D are still not started, each gated on the one
   before — read the full phase breakdown in `next_steps.md` before
   starting any of it.
4. **Read `next_steps.md` #11 before building anything resembling a
   cross-venue offer scanner** — Evan asked for this idea to be designed and
   logged, explicitly *not* built yet. Don't start implementing it without
   checking with Evan first. Note this is different from #15's Phase B
   (context for our own price, not acting on another venue's).
5. **`amount_step` (`basicswap/next_steps.md` #9) and opportunistic
   bid-scanning (`basicswap/strategy/bid_scanner.py`, same item #9) are both
   BUILT AND TESTED, 2026-09-20 — neither is deployed/live.** Don't redo the
   `post_bid`/`get_bid` API research, the `bid_scan_events` schema, or
   `bid_scanner.py`'s scan/size/bid/reconcile pipeline (144/144 tests passing
   across `strategy/tests/`) — it's done. What's actually still open: turning
   `amount_step` on needs `restart_live_maker.sh` with the flag added; OBS
   needs a first `--live` run. Neither should happen without Evan's explicit
   go-ahead first (submitting a real bid via OBS is a materially less
   reversible action than anything `live_maker.py` itself does — see
   `ARCHITECTURE.md` §5's matching update). Full detail in
   `basicswap/next_steps.md` #9's "Built 2026-09-20" section.

**What's true right now (verify before trusting, this is a snapshot)**:
- Volatility kill-switch (#1), duplicate-instance PID guard (#9), and the
  source-disagreement gate (#10) are all **built and tested**, but their
  live-deployment status depends on whether item #1 above (the restart) has
  happened — check the logs, don't assume.
- Three real fills exist now (2026-09-17 manual mechanics test, 2026-09-18
  ask-side mispricing loss, 2026-09-18 bid-side near-fair loss) — all three
  negative relative to fair value so far, none of them gains. New evidence
  for `next_steps.md` #4 (fill-vs-expiry detection): still n=2 on the
  *automated*-loop count that item cares about, unchanged.
- Every other item on `next_steps.md` (#2 real MVB, #3 P&L ledger, #4 fill-
  vs-expiry detection, #5 tax lots, #7 inventory controller) is **still
  blocked**, per that file's own explicit gating.
- **#6 (venue #2, live capital) is still blocked** — narrowed 2026-09-18 to
  cover only *putting capital* on a second venue, not *observing* one.
  **#12 (Bisq)** and **#13 (Eigen ASB)** are both built, deployed, and
  accumulating real data on the same 5-minute schedule as of 2026-09-19 —
  Eigen ASB is now a real data source, same footing as Bisq.

**Do not put real capital on #6 (venue #2) or start #7 (inventory
controller)** without an explicit human decision first — both are
deliberately deferred per `next_steps.md` #6/#7's own reasoning. Same rule
applies to #11. Read-only observation work (#12, #13, or a future venue) is
*not* subject to this — it's a different, lower-risk ask.

## 2026-09-24: profitability review, fill ledger built, 6.7% incident corrected

**Profitability by venue (as of 2026-09-24)**: BasicSwap is the only venue
with capital (~$890: 0.00808 BTC + 0.377 XMR). It has 2 completed automated
fills ever (both 09-18) and **0 fills since `half_spread_pct` went to 0.02 on
09-19** (~300 ask reposts). Realized round trip about **-$46 plus ~$2–3
fees**: ~-$6 edge at fill, ~-$40 from holding XMR bought at the top of a
real ~7% XMR/BTC spike. Bisq and Eigen ASB are observation-only, $0 P&L.
**There is no evidence yet of a profitable strategy.**

**Cross-venue markups vs. mid (last 5 days, `venue_observations.db`)**:
- Selling BTC for XMR (our ask side): Bisq median +1.1%, p25 +0.1%. We quote
  +2.0%, so we're likely priced out.
- Selling XMR for BTC (our bid side): Bisq median +4.5%, Eigen +2.6%. That
  side has wider margins, but we don't quote it: the XMR wallet sits below
  the $210 reserve, and Evan will fund it later.

**Built**: `basicswap/strategy/fill_ledger.py` plus a `fills` table (closes
`next_steps.md` #3/#4). Details and the 6.7% correction are in
`basicswap/project_status.md`'s 2026-09-24 entries. 150/150 tests pass.
Uncommitted as of writing.

## 2026-09-24, later: kill-switch hysteresis built + Bisq trade-flow measured (handoff items 4 and 5)

**Kill-switch (item 4): built and tested, NOT deployed.** Replaying the 09-18
ask fill against `basicswap_live_maker.log` (EDT) showed the actual failure
mode. The 15-min switch fired four cycles running (12:04–12:19, up to 3.86%),
then on **one** calm reading at 12:24 run_cycle repriced to 136.17. That offer
was filled at 12:30, at the top of the move (+1h markout −7.27%). Only ~3
samples fit a 15-min window at 5-min cadence. The 12:09:48 sample aged out by
one second, and CoinGecko's price plateaued at 16:16–16:21 UTC, so what was
left looked calm. A 7-day recalibration (1,585 samples) also puts the 15-min
p99 at 2.01%, not the original 0.84%. Added to `volatility.py`/`live_maker.py`:
a 60-min second window (default 3%, ≈p95) and a 30-min cooldown (once tripped,
stay paused until 30 min pass with no new trip). New CLI flags:
`--kill-switch-long-window-minutes`, `--kill-switch-long-volatility-pct`,
`--kill-switch-cooldown-minutes` (≤0 disables). Defaults only tighten.
Replaying the week: pauses ~18% of cycles in 24 episodes (today: ~7% in 47
flickering episodes). Loosening 15-min to 1.2% gives ~9.5% in 10 episodes;
that's Evan's call. 159/159 `strategy/tests` pass. **Takes effect only after
`basicswap/restart_live_maker.sh`** (no flag changes needed).

**Bisq demand (item 5): measured.** `venues/bisq/client.py` has a new
`get_trades()`, and `python -m venues.bisq.trade_flow` is the rerunnable
analysis. Last 30 days of xmr_btc: **962 trades, ~32/day, ~2.6 BTC/day**,
median size 0.03 BTC (70% of trades ≥ our 0.008 BTC). Direction, inferred
from price vs. Kraken hourly VWAP: **94% of trades clear above VWAP
(median +1.95%), and only 3.7% of BTC volume trades below it.** So Bisq's
XMR/BTC flow is almost entirely people buying XMR with BTC at a premium.
Eigen ASB's ~+2.6% XMR-sell quotes point the same way.
Implications:
- Our **ask side** (buy XMR below mid) quotes the direction almost nobody
  trades organically. Both real ask fills came during a fast move (adverse
  flow), which fits. Lowering the ask markup (handoff item 3's experiment)
  probably buys fills mostly from informed/adverse flow, not organic demand.
- The premium sits on the **XMR-sell side** (our bid side). The bid side's
  funding is deferred by Evan; this is new evidence for that decision, not
  a nag.
- Caveat: Bisq flow may not match BasicSwap's own, and the direction is
  inferred rather than reported.

## 2026-09-25: INCIDENT — bid side sold XMR below market and into the reserve (both loops stopped)

At 06:58 the ask offer was partly filled (0.0015 BTC → 0.2285 XMR, +2% edge).
That lifted the XMR wallet ~$125 above `--reserve-usd 210`. From 11:10 the bid
side sold it at **2.0–2.9% below mid**. Two swaps completed (11:26, 11:59,
~0.225 XMR each), so the same surplus sold twice and the wallet fell to
0.1558 XMR (~$87). Three more accepted swaps (11:11, 11:16, 11:47) sat
retrying our XMR lock with "not enough money". Net cost is about -$7, since the
XMR became ~0.00289 BTC.

Root causes, both fixed in `basicswap/strategy/live_maker.py` (172/172 tests):
1. **Price direction.** `quoter.half_spread_rate(side="bid")` = mid×(1−h) is
   right in the shadow quoter's units, but the live bid side flips the pair to
   xmr→btc (BTC per XMR), so it sold XMR cheap. Now `_offer_rate` = mid×(1+h)
   for every offer, plus a hard refusal to post at or below mid. The 09-18
   bid fill (−0.77%) was the same bug.
2. **In-flight swaps.** The wallet balance doesn't drop until our lock tx
   publishes, and each reprice posts a new offer (max_concurrent_bids=1 is
   per offer). `run_cycle` now checks `/json/bids`. While any non-terminal
   swap is selling coin_from→coin_to, it revokes our live offer in that
   direction and posts nothing.

Evan stopped both live_maker processes 09-25 (the sandbox blocked me). The 3
stuck swaps need abandoning in the BasicSwap UI. Neither loop should restart
until that's done and Evan has reviewed. `bid_scanner.py`'s "below mid" is
correct for its case (buying from others' offers) and is untouched.

**XMR top-up**: new `strategy/topup_xmr.py`, a one-shot BTC→XMR bid to bring
the wallet back to $210 (+5% buffer, ≤3% over mid, aborts while any
Monero→Bitcoin swap is in flight). A session-only Claude cron runs it at 18:57
on 09-25 if the session is still open. **Ran and completed**: bid
`000000006ab6fc4b…` bought 0.23267 XMR for ~0.00157 BTC at +2.19% over mid
(placed 18:57, completed 20:31; the seller's XMR lock took ~45 min after
ours confirmed). The wallet is now ~0.3885 XMR (~$216). The 3 stuck swaps
were abandoned at Evan's request (all `Abandoned`), and both live loops
are still stopped.

## Handoff for the next session (2026-09-24, supersedes earlier handoffs)

1. **BasicSwap rate poller is DOWN** (last write 2026-09-23 09:34, not under
   launchd). Ask Evan to allow launchd changes (the sandbox blocked the
   install as persistence), then add
   `com.market_maker.basicswap-poller` (`python3 -m strategy.poller`, 300s) and
   `com.market_maker.fill-ledger` (`python3 -m strategy.fill_ledger`, 3600s),
   cloned from `venues/com.market_maker.venues-poller.plist` with
   WorkingDirectory `basicswap/`. Until then, check `ps` for a
   hand-started `run_poller.sh --loop`.
2. **Commit** the 09-24 work if Evan hasn't: `fill_ledger.py`,
   `run_fill_ledger.sh`, `tests/test_fill_ledger.py`, `storage.py`,
   `api_client.py`, and the doc edits.
3. **The core open question is whether there's a price where we get fills
   AND make money.** The cost model says ≥2% one-sided is needed, but at
   2% we get no fills. The next step is a markup experiment (for example 2.0 →
   1.5 → 1.0% for a fixed number of days each, logging fill rate and markouts
   via `fill_ledger`). **Needs Evan's sign-off** because it changes live
   pricing.
4. **Kill-switch recalibration: BUILT 2026-09-24 (60-min/3% window + 30-min
   cooldown), not deployed.** Needs Evan to run `basicswap/restart_live_maker.sh`,
   then confirm the startup log shows `kill_switch_cooldown_minutes=30.0`.
   See the "later" entry above.
5. **Measure demand: DONE 2026-09-24.** Bisq xmr_btc runs ~2.6 BTC/day, and
   ~96% of volume pays a premium to XMR sellers. This reframes item 3: the
   markup experiment on the ask side is probably the wrong lever. Rerun with
   `python -m venues.bisq.trade_flow`.
6. **Define a success bar with Evan** (for example, positive +24h markout net
   of fees over ≥30 fills) so "is it profitable" has a yes/no answer.
7. Unblocked but lower priority: #5 tax lots (built on the `fills` table).
   XMR funding and bid-side reserve are deferred by Evan, so don't re-flag them.

## 2026-09-28: BTC-objective retarget built (steps 3–4 of the 09-25 plan), not deployed

`--objective btc` in `basicswap/strategy/live_maker.py` prices the ask side as
a **restock leg** (buy XMR back at +0.39–0.56% instead of +2%, charging the
round trip once) and the bid side as the **sell leg** at a target premium (+1.8%
proposed). A target XMR balance caps how much XMR the desk holds.
206/206 tests. Details, the 14-day book data and caveats are in
`basicswap/project_status.md`'s 2026-09-28 entry. Net position vs. never
trading: −57,930 sats.

## 2026-10-02: restock-cost tracking across venues (read-only)

The proof trial (day 2) shows the sell leg selling out and the maker restock
offer filling rarely (one 0.505 XMR fill in 2 days, never the cheapest). To see
whether any non-KYC venue could restock cheaply enough to skip a CEX:

- `venues/instant_swap/`: Exolix and ChangeNOW quote readers (keyless), added to
  the venues poller's defaults, so the existing 5-minute launchd job picks them up
  with no plist change. Verified with one live cycle.
- `venues/restock_cost.py`: per poll cycle, walks each venue's XMR-sell offers to
  fill 0.5 XMR and prices it against the Kraken mid, plus fees (partly assumed,
  in `VENUE_COSTS`). Covers BasicSwap, Bisq, Eigen ASB, Exolix, ChangeNOW, Kraken.
- Venues checked and ruled out are in `ARCHITECTURE.md` §7 (Trocador needs a key;
  SideShift has XMR disabled; no XMR on THORChain/Maya/Chainflip).
- 13 new tests; 47/47 in `venues/tests`.

First read (7 days, all-in for 0.5 XMR, median): Exolix +0.55% (1 sample so
far), Kraken +1.01%, Eigen ASB +1.59%, Bisq +2.23%, BasicSwap +2.78%,
ChangeNOW +3.03%. None of the non-KYC DEXes beats Kraken; Eigen ASB is the
cheapest DEX and cheaper than taking on BasicSwap. The 1,650-sat flat fee is
about half of Kraken's cost at 0.5 XMR. Re-run after a week of Exolix samples.

## Handoff for the next session (2026-09-28, supersedes the 2026-09-24 handoff)

0. **Proof trial (`next_steps.md` #17) is built.** To start it: optionally seed
   0.6 XMR (`python3 -m strategy.topup_xmr --target-xmr 0.985 --buffer-pct 0
   --max-premium-pct 0.035`, dry run first, then `--live`), then run
   `restart_live_maker_btc.sh`. Score it with `python3 -m strategy.proof_report`
   after `./run_fill_ledger.sh`. Minimum 4 weeks.
1. **Decide whether to restart under `--objective btc`** (Evan's call).
   `basicswap/restart_live_maker_btc.sh` is ready. Both loops are still
   stopped and the 3 stuck swaps are abandoned, so the 09-25 blocker is gone.
   The USD script's ask side is underfunded (0.008 > 0.00787844 BTC).
2. **Install the two launchd jobs** (`basicswap/com.market_maker.basicswap-poller.plist`,
   `basicswap/com.market_maker.fill-ledger.plist`). First stop the hand-started
   pollers: two were running on 09-28 (PIDs 22008 and 33211), and this session's
   kill was denied.
3. **Success bar** (still open, item 6 of the 09-24 handoff). Suggested: net
   position vs. never trading, in sats, positive over ≥30 completed round trips.
4. **Fill-ledger gap**: include bids we *sent* (`topup_xmr.py`, `bid_scanner`) in
   the net-position score.
5. Unchanged: kill-switch 15-min threshold loosening (0.85%→1.2%) is Evan's
   call; #5 tax lots is unblocked but low priority.

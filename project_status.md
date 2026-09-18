# Market Maker — Project Status

**Status as of 2026-09-18: one live venue (BasicSwap), real money, real
fills, now with its own GitHub repo, plus a volatility kill-switch built and
deployed to both live loops the same day (see the dated entry below).**
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

## Next action

`next_steps.md` #9 (duplicate-instance PID guard — cheap, independent, no
strategy risk) or #3/#4 (P&L ledger + fill detection), still gated on more
real fill data accumulating. Everything else on that list remains blocked on
the observation window clearing its 1–2 week bar or on the single-venue edge
proving itself first.

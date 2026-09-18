# Market Maker — Project Status

**Status as of 2026-09-17: one live venue (BasicSwap), real money, real fills.
Framework-level docs (this file, `ARCHITECTURE.md`, `next_steps.md`) created
today** by reviewing `btc_xmr_market_making_framework_v3.1.pdf` and
`kyc_resilience_mvb_v3.pdf` against the venue-level project's actual state —
see `ARCHITECTURE.md` for the full ethos-vs-reality gap analysis. This is a
restructure, not a rebuild: `basicswap/` moved here unchanged
(`market_maker/basicswap/`) with all its own history/docs intact.

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

## Next action

See `next_steps.md` #1 (volatility kill-switch) — the single highest-value,
lowest-effort gap between the source PDFs' risk-control table and what's
actually running. Everything else on that list is either blocked on more real
fill data accumulating (`basicswap/next_steps.md`'s observation window, still
short of its 1–2 week bar) or deliberately gated behind the single-venue edge
proving itself first.

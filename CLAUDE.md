# Market Maker (Framework)

Cross-venue crypto market-making framework. `basicswap/` is the first venue
module — live, real money, see `basicswap/CLAUDE.md` for its own working
guide. `venues/` is a second, deliberately lighter venue layer: read-only
offer-book observation across venues that don't (yet) have live capital —
Bisq (`venues/bisq/`, its own hosted public API, no node/wallet needed) and
Eigen ASB (`venues/eigen_asb/`, added 2026-09-19, subprocess-wrapped around a
compiled Rust libp2p client at `~/eigenwallet-core` since no HTTP API
exists), both polled every 5 minutes by the same `venues/poller.py` /
launchd job. See `ARCHITECTURE.md` for the framework-level design and gap
analysis, `project_status.md` for build history, `next_steps.md` for the
build queue.

## Session-start checklist — run this before touching anything else here

A hang in this directory has already cost real session time once
(2026-09-19 — full incident in `project_status.md`'s matching entry), so
check process health before assuming code is broken or trusting a doc claim
at face value.

1. **Look for a hung `venues.poller` or `live_maker` process before starting
   new work.**
   `ps aux | grep -E "venues.poller|live_maker" | grep -v grep`
   - `venues.poller` (no `--loop`) runs one cycle and exits — anything alive
     more than ~30s is hung, not slow.
   - `live_maker --loop` processes are supposed to persist, but should show
     fresh activity in their logs every ~5 min (its repost cadence); no
     fresh activity is the hang signature, not a quiet market.
   - Known cause (2026-09-19): the Mac sleeping mid-request. Python's
     per-socket `urlopen(timeout=...)` doesn't reliably re-fire after a
     sleep/wake cycle, so a request can hang indefinitely even with a
     timeout set. If found: `launchctl unload
     ~/Library/LaunchAgents/com.market_maker.venues-poller.plist`, `kill -9`
     the stuck PIDs, confirm the underlying API is actually reachable
     (`curl -s --max-time 8 <endpoint>`) before assuming a code bug, then
     `launchctl load` again and manually re-run once in the foreground to
     confirm before trusting the schedule.
   - If the hung process turns out to belong to a *different* Claude
     session (another `claude` PID as its parent — check `ps`, or ask
     Evan), say so explicitly wherever the fix gets written up. Killing it
     can unblock that other session's own stuck tool call, and that
     session's own writeup may have no idea a hang happened at all — this
     exact thing happened 2026-09-19, see `project_status.md`.

2. **Verify the venues poller (Bisq + Eigen ASB) is actually current, not
   just loaded.** `launchctl list | grep market_maker` should show
   `com.market_maker.venues-poller`. `tail -5 venues/logs/poller.log` — the
   newest timestamp should be within ~5 min (its `StartInterval`), and
   should show both `bisq:` and `eigen_asb:` poll lines each cycle (added
   2026-09-19 — `eigen_asb: polled 0 live offer(s)` every cycle, not just
   sometimes, means its subprocess is failing silently, e.g. the compiled
   binary at `~/eigenwallet-core/target/release/examples/fetch_quotes_json`
   went missing — check the log's warning line for the real reason). Loaded
   but stale is the hang signature from #1, not a scheduling failure —
   diagnose accordingly rather than just reloading and hoping.

3. **Verify BasicSwap's live process count is exactly what it should be**
   (currently 1, the xmr->btc sell leg; the btc->xmr restock leg was retired 2026-10-27 in favor of Exolix-only restocking): `ps aux | grep live_maker | grep -v grep`. A
   duplicate/orphaned process has happened before (2026-09-17). Cross-check
   via BasicSwap's own `/json/sentoffers` for an actual offer collision
   before assuming one occurred, and before killing anything with real
   capital behind it.

3b. **After any unclean node stop (reboot, crash, `kill -9`), watch the
   first restart for a stale RPC cookie.** The node can read a leftover
   `particl/.cookie` a moment before particld rewrites it, then retries
   PART RPC 15 times and never connects (2026-10-21). Signature:
   `particl/debug.log` shows `ThreadRPCServer incorrect password attempt
   from 127.0.0.1` on every retry, while `basicswap.log` shows "Can't
   connect to PART RPC". Fix: `kill -INT` the `basicswap-run` PID, wait for
   its daemons to exit (a clean stop deletes the cookie), start it once.
   Also run the start command only once; a second `basicswap-run` finds
   the running daemons and tries to stop them.

4. **Read the most recent "Handoff for the next session" in
   `project_status.md`** (this file and `basicswap/project_status.md`)
   before starting new work — it usually has the pending action.

5. **Never generate, hold, or log real key material through a Claude
   session** — unchanged standing rule, restated here since this is now the
   front door to the directory.

This list isn't exhaustive. If a new silent-failure mode turns up, add a
check for it here rather than just fixing it and moving on — same
convention as `Silenus/QA_CHECKLIST.md`.

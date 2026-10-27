#!/bin/bash
# Restart the sell-leg live_maker loop under the accumulate-BTC objective
# (restock leg retired 2026-10-27; restocking is Exolix only, see below)
# (--objective btc, built 2026-09-28 -- see strategy/live_maker.py's "Objective"
# docstring note and basicswap/project_status.md's 2026-09-28 entry). NOT run by
# any Claude session: this changes live pricing and needs Evan's go-ahead.
# restart_live_maker.sh (USD objective) is unchanged and stays the default.
#
#   sell leg    xmr->btc  sells XMR above RESERVE_XMR at +SELL_PREMIUM over mid
#   restock     Exolix float swaps (strategy/exolix_restock.py), not a maker offer
#
# Proof trial (next_steps.md #17): the first run writes $SWAP_DATADIR/proof_trial_start,
# which strategy/proof_report.py scores from; later restarts keep the original
# start. Delete that file to start a new trial.
#
# Optional seed, BEFORE running this: the sell leg only has XMR to sell above
# RESERVE_XMR, and today there's ~0.0035 XMR of that. To test it from day one
# instead of waiting for the restock leg to fill, buy the working stock once
# (checks without --live first; on 09-28 the cheapest fitting offer was ~+3%,
# ~11.7k sats on 0.6 XMR, a one-time seed cost):
#   python3 -m strategy.topup_xmr --target-xmr 0.985 --buffer-pct 0 --max-premium-pct 0.035
#   python3 -m strategy.topup_xmr --target-xmr 0.985 --buffer-pct 0 --max-premium-pct 0.035 --live
#
# Usage: ./restart_live_maker_btc.sh
set -euo pipefail

export SWAP_DATADIR=$HOME/coinswaps
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOCK_DIR="$SWAP_DATADIR/locks"

stop_if_running() {
    local lock_file="$1"
    if [ ! -f "$lock_file" ]; then
        return
    fi
    local pid
    pid="$(cat "$lock_file" 2>/dev/null || true)"
    if [ -z "$pid" ]; then
        return
    fi
    if kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= 2>/dev/null | grep -q "strategy.live_maker"; then
        echo "Stopping live_maker pid $pid ($lock_file)..."
        kill -TERM "$pid"
        for _ in $(seq 1 15); do
            if ! kill -0 "$pid" 2>/dev/null; then
                echo "  stopped."
                return
            fi
            sleep 1
        done
        echo "  still alive after 15s, sending SIGKILL." >&2
        kill -KILL "$pid" 2>/dev/null || true
    else
        echo "Lock file $lock_file points at a dead/unrelated pid ($pid) — nothing to stop."
    fi
}

echo "=== Stopping existing loops (if any) ==="
stop_if_running "$LOCK_DIR/live_maker_btc-xmr-ask.pid"
stop_if_running "$LOCK_DIR/live_maker_xmr-btc-bid.pid"

echo
if [ ! -f "$SWAP_DATADIR/proof_trial_start" ]; then
    date +%s > "$SWAP_DATADIR/proof_trial_start"
    echo "Proof trial starts now: $(date) (written to $SWAP_DATADIR/proof_trial_start)"
fi

RESERVE_XMR=0.385        # ~= today's $210 bid-side reserve, now fixed in XMR
# --amount-step 0.05 on the sell leg: no dust offers (0.3885 - 0.385 would post
# 0.0035 XMR) and the posted size doesn't reveal the exact wallet balance.
MAX_SELL_XMR=0.55        # 2026-09-30: fixed sell-offer size, so restock fills beyond the
                         # working stock don't grow it into one oversized offer
MIN_BID_XMR=0.15         # 2026-10-21: smallest partial fill accepted. Each swap pays ~650 sats
                         # of BTC fees whatever its size (0.43% at 0.15 XMR); the 10-18 0.018 XMR
                         # dust fill lost money at any premium. Every other trial fill was >= 0.15.
MIN_LIVE_EDGE=0.01       # 2026-10-22: revoke the live sell offer once it's under +1.0% vs. the
                         # current mid, even mid-kill-switch (the 10-22 02:14 fill went -2.75%).
                         # Break-even at the smallest accepted fill: 650 sats on 0.15 XMR (~0.6%)
                         # plus the ~0.4% Exolix restock cost.
SELL_PREMIUM=0.021      # 2026-10-21: was 0.018. The trial is stock-constrained, not demand-
                         # constrained (~20 fills per week of sell-offer uptime), so price up.
                         # Drop to 0.020 if fills slow sharply.

# 2026-10-27: restock leg (btc->xmr maker offer) retired on Evan's call; Exolix only
# (strategy/exolix_restock.py, launchd every 15 min). Over the trial it filled 13 times at
# -20,422 sats vs. mid at fill and -38,859 at +1h: it got filled just before XMR dropped,
# plus ~400 sats of network fees per fill. Exolix restocks averaged +0.40% all-in. The stop
# above still runs, so a restart kills any leftover restock process.

echo "=== Starting sell leg (xmr->btc, reserve ${RESERVE_XMR} XMR, premium ${SELL_PREMIUM}) ==="
nohup ./run_live_maker.sh --loop --coin-from xmr --coin-to btc --side bid \
    --objective btc --reserve-coin "$RESERVE_XMR" --half-spread-pct "$SELL_PREMIUM" \
    --amount-step 0.05 --max-amount-from "$MAX_SELL_XMR" --min-bid-amount "$MIN_BID_XMR" \
    --min-live-edge-pct "$MIN_LIVE_EDGE" \
    >>"$SWAP_DATADIR/basicswap_live_maker_bid.log" 2>&1 &
disown

sleep 3
echo
echo "=== Verification ==="
echo "-- processes (expect exactly 1, the sell leg) --"
ps aux | grep live_maker | grep -v grep

echo
echo "-- startup log lines (expect objective=btc) --"
tail -4 "$SWAP_DATADIR/basicswap_live_maker_bid.log"

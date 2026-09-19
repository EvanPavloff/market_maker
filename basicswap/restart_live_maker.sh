#!/bin/bash
# One-shot restart for both live_maker loops (ask: btc->xmr, bid: xmr->btc) —
# picks up whatever's currently in strategy/api_client.py + strategy/live_maker.py
# (2026-09-19: the get_wallet_balance KeyError fix + half_spread_pct 0.0066->0.011).
#
# Usage: ./restart_live_maker.sh
#
# Stops whichever of the two loops are still alive (checked via the same
# lock-file + `ps -p ... -o command=` pattern run_live_maker.sh's own
# duplicate-instance guard uses, so this won't kill an unrelated process that
# happens to reuse a stale PID), waits for a clean exit, then relaunches both
# with the same flags they were started with on 2026-09-18.
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
echo "=== Starting ask side (btc->xmr, fixed 0.008 BTC) ==="
nohup ./run_live_maker.sh --loop --coin-from btc --coin-to xmr --side ask --amount-from 0.008 \
    >>"$SWAP_DATADIR/basicswap_live_maker.log" 2>&1 &
disown

echo "=== Starting bid side (xmr->btc, reserve \$210) ==="
nohup ./run_live_maker.sh --loop --coin-from xmr --coin-to btc --side bid --reserve-usd 210 \
    >>"$SWAP_DATADIR/basicswap_live_maker_bid.log" 2>&1 &
disown

sleep 3
echo
echo "=== Verification ==="
echo "-- processes (expect exactly 2) --"
ps aux | grep live_maker | grep -v grep

echo
echo "-- startup log lines (confirm half_spread_pct=0.0110, not 0.0066) --"
tail -3 "$SWAP_DATADIR/basicswap_live_maker.log"
echo "---"
tail -3 "$SWAP_DATADIR/basicswap_live_maker_bid.log"

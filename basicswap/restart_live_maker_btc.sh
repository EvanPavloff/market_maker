#!/bin/bash
# Restart both live_maker loops under the accumulate-BTC objective
# (--objective btc, built 2026-09-28 -- see strategy/live_maker.py's "Objective"
# docstring note and basicswap/project_status.md's 2026-09-28 entry). NOT run by
# any Claude session: this changes live pricing and needs Evan's go-ahead.
# restart_live_maker.sh (USD objective) is unchanged and stays the default.
#
#   sell leg    xmr->btc  sells XMR above RESERVE_XMR at +SELL_PREMIUM over mid
#   restock leg btc->xmr  buys XMR back only up to RESERVE_XMR + WORKING_XMR,
#                         at whatever markup the sell premium doesn't cover
#                         (+0.39-0.55% at today's inputs, vs. the 2% ask today)
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
WORKING_XMR=0.6          # XMR the loop may hold beyond the reserve (~half the BTC wallet)
# --amount-step 0.05 on the sell leg: no dust offers (0.3885 - 0.385 would post
# 0.0035 XMR) and the posted size doesn't reveal the exact wallet balance.
SELL_PREMIUM=0.018       # inside BasicSwap's cheapest-XMR-seller median (+1.85%, 14d)
RESTOCK_CAP_BTC=0.0075   # per-offer cap; the wallet held 0.00787844 BTC on 2026-09-28
RESTOCK_TARGET=$(python3 -c "print(round($RESERVE_XMR + $WORKING_XMR, 8))")

echo "=== Starting restock leg (btc->xmr, target ${RESTOCK_TARGET} XMR, cap ${RESTOCK_CAP_BTC} BTC) ==="
nohup ./run_live_maker.sh --loop --coin-from btc --coin-to xmr --side ask \
    --objective btc --amount-from "$RESTOCK_CAP_BTC" \
    --restock-target-coin-to "$RESTOCK_TARGET" \
    --restock-expected-sell-premium-pct "$SELL_PREMIUM" \
    >>"$SWAP_DATADIR/basicswap_live_maker.log" 2>&1 &
disown

echo "=== Starting sell leg (xmr->btc, reserve ${RESERVE_XMR} XMR, premium ${SELL_PREMIUM}) ==="
nohup ./run_live_maker.sh --loop --coin-from xmr --coin-to btc --side bid \
    --objective btc --reserve-coin "$RESERVE_XMR" --half-spread-pct "$SELL_PREMIUM" \
    --amount-step 0.05 \
    >>"$SWAP_DATADIR/basicswap_live_maker_bid.log" 2>&1 &
disown

sleep 3
echo
echo "=== Verification ==="
echo "-- processes (expect exactly 2) --"
ps aux | grep live_maker | grep -v grep

echo
echo "-- startup log lines (expect objective=btc on both) --"
tail -4 "$SWAP_DATADIR/basicswap_live_maker.log"
echo "---"
tail -4 "$SWAP_DATADIR/basicswap_live_maker_bid.log"

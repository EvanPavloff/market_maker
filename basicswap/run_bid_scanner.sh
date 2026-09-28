#!/bin/bash
# Opportunistic bid-scanning (next_steps.md #9) — bids into OTHER makers' live
# offers, not our own. Requires --live to actually submit anything (see
# strategy/bid_scanner.py's own refusal-to-submit-without-it default: without
# --live this only scans and logs, never calls post_bid). Needs basicswap-run
# already up. Mirrors run_live_maker.sh's duplicate-instance lock-file guard.
set -euo pipefail

export SWAP_DATADIR=$HOME/coinswaps
source "$SWAP_DATADIR/venv/bin/activate"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

# --- duplicate-instance guard (same pattern as run_live_maker.sh's own,
# added after the real 2026-09-17 orphaned-process incident that guard
# closed for live_maker.py — keyed on the pair, not a "side", since
# bid-scanning isn't ask/bid-labeled the way live_maker.py's two loops are)
coin_from="btc"
coin_to="xmr"
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
    case "${args[$i]}" in
        --coin-from) i=$((i + 1)); coin_from="${args[$i]:-$coin_from}" ;;
        --coin-from=*) coin_from="${args[$i]#*=}" ;;
        --coin-to) i=$((i + 1)); coin_to="${args[$i]:-$coin_to}" ;;
        --coin-to=*) coin_to="${args[$i]#*=}" ;;
    esac
    i=$((i + 1))
done

LOCK_DIR="$SWAP_DATADIR/locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/bid_scanner_${coin_from}-${coin_to}.pid"

if [ -f "$LOCK_FILE" ]; then
    old_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null \
        && ps -p "$old_pid" -o command= 2>/dev/null | grep -q "strategy.bid_scanner"; then
        echo "Refusing to start: a bid_scanner process for" \
            "${coin_from}/${coin_to} is already running" \
            "(pid $old_pid, lock $LOCK_FILE). Stop it first if you meant to replace it." >&2
        exit 1
    fi
fi

# Written before exec: `exec` preserves this shell's PID, same reasoning as
# run_live_maker.sh's own comment on why -- so the lock file stays a true
# liveness check for as long as the strategy is actually running.
echo $$ > "$LOCK_FILE"

exec python3 -m strategy.bid_scanner "$@"

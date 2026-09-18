#!/bin/bash
# LIVE market maker — real BTC/XMR, posts/revokes real offers. Requires --live
# (see strategy/live_maker.py's own refusal-to-run-without-it check). Needs
# basicswap-run already up.
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

# --- duplicate-instance guard (next_steps.md #9) ---
# 2026-09-17 found 5 live_maker processes running instead of 2: a wrapper
# shell was killed but its `python3 ...` child (a separate process, not the
# same PID) kept running independently, orphaned under PPID=1, invisible to
# a later restart of this script. `exec` below collapses this script and the
# python process into a single PID for the rest of this script's life, so
# the lock file (keyed on that PID) stays a true liveness check for as long
# as the strategy is actually running, and there's no longer a wrapper/child
# pair for one half to survive the other's death.
coin_from="btc"
coin_to="xmr"
side="ask"
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
    case "${args[$i]}" in
        --coin-from) i=$((i + 1)); coin_from="${args[$i]:-$coin_from}" ;;
        --coin-from=*) coin_from="${args[$i]#*=}" ;;
        --coin-to) i=$((i + 1)); coin_to="${args[$i]:-$coin_to}" ;;
        --coin-to=*) coin_to="${args[$i]#*=}" ;;
        --side) i=$((i + 1)); side="${args[$i]:-$side}" ;;
        --side=*) side="${args[$i]#*=}" ;;
    esac
    i=$((i + 1))
done

LOCK_DIR="$SWAP_DATADIR/locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/live_maker_${coin_from}-${coin_to}-${side}.pid"

if [ -f "$LOCK_FILE" ]; then
    old_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null \
        && ps -p "$old_pid" -o command= 2>/dev/null | grep -q "strategy.live_maker"; then
        echo "Refusing to start: a live_maker process for" \
            "${coin_from}/${coin_to} side=${side} is already running" \
            "(pid $old_pid, lock $LOCK_FILE). Stop it first if you meant to replace it." >&2
        exit 1
    fi
fi

# Written before exec: `exec` preserves this shell's PID, so $$ is the
# python process's own PID for the rest of its life, not a stale parent.
echo $$ > "$LOCK_FILE"

exec python3 -m strategy.live_maker --live "$@"

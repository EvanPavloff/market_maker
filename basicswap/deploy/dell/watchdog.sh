#!/bin/bash
# Dell watchdog for the BasicSwap node + sell-leg live_maker (cron, every 2 min).
# Added 2026-10-27 when the runtime moved off the Mac's flaky Storage drive.
#
#  - node down (no basicswap-run) and no orphaned coin daemons -> start it once
#  - orphaned daemons without basicswap-run -> don't start (CLAUDE.md 3b: a second
#    start tries to stop them); alert instead
#  - node API answering and no sell loop -> restart_live_maker_btc.sh
#  - node API silent for 15+ min -> one alert (the 10-21 "dead 3h unnoticed" gap)
#
# Pause it for maintenance: touch ~/coinswaps/watchdog.disabled
set -uo pipefail

export SWAP_DATADIR=$HOME/coinswaps
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="$SWAP_DATADIR/watchdog.state"   # epoch of the first failed API check, or empty
ALERTED="$SWAP_DATADIR/watchdog.alerted"
PY="$SWAP_DATADIR/venv/bin/python3"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
alert() { (cd "$REPO" && set -a && { [ -f .env ] && . ./.env; true; } && set +a && "$PY" -m strategy.notify "market_maker (Dell)" "$1"); }

[ -f "$SWAP_DATADIR/watchdog.disabled" ] && exit 0

node_up=0
pgrep -f "basicswap-run --datadir=$SWAP_DATADIR" >/dev/null && node_up=1
daemons=$(pgrep -f "$SWAP_DATADIR/bin/" | wc -l)

if [ "$node_up" = 0 ]; then
    if [ "$daemons" -gt 0 ]; then
        log "node down but $daemons coin daemon(s) still running; not starting (see CLAUDE.md 3b)"
        [ -f "$ALERTED" ] || { alert "Node down with orphaned daemons; needs a manual look"; touch "$ALERTED"; }
        exit 0
    fi
    log "node down; starting basicswap-run"
    rm -f "$SWAP_DATADIR/particl/.cookie" "$SWAP_DATADIR/bitcoin/.cookie"   # 3b: stale cookie after an unclean stop
    nohup "$SWAP_DATADIR/venv/bin/basicswap-run" --datadir="$SWAP_DATADIR" \
        >>"$SWAP_DATADIR/basicswap_run_stdout.log" 2>&1 &
    disown
    exit 0
fi

code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" http://localhost:12700/json/ || true)
if [ "$code" != "200" ]; then
    now=$(date +%s)
    first=$(cat "$STATE" 2>/dev/null || true)
    [ -z "$first" ] && { echo "$now" >"$STATE"; first=$now; }
    if [ $((now - first)) -ge 900 ] && [ ! -f "$ALERTED" ]; then
        log "node API not answering for $(((now - first) / 60)) min (http $code)"
        alert "BasicSwap node API not answering for $(((now - first) / 60)) min"
        touch "$ALERTED"
    fi
    exit 0
fi
if [ -f "$ALERTED" ]; then alert "BasicSwap node API answering again"; fi
rm -f "$STATE" "$ALERTED"

if ! pgrep -f "strategy.live_maker .*--coin-from xmr --coin-to btc" >/dev/null; then
    # Monero lags after any downtime (~2 blocks/s on 10-27); don't post until both wallets are synced.
    for coin in xmr btc; do
        synced=$(curl -s -m 20 "http://localhost:12700/json/wallets/$coin" \
            | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("synced"))' 2>/dev/null || true)
        if [ "$synced" != "100.00" ]; then
            log "node up, sell loop not running; waiting for $coin wallet sync ($synced%)"
            exit 0
        fi
    done
    log "node up, wallets synced, sell loop not running; starting it"
    "$REPO/restart_live_maker_btc.sh"
fi

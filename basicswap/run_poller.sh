#!/bin/bash
# Phase 1 poller — read-only, observes BasicSwap's live offer book. Needs
# basicswap-run already up (see project_status.md). Pass --loop to poll
# continuously instead of once.
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
python3 -m strategy.poller "$@"

#!/bin/bash
# Cross-venue observation poller — read-only, no wallet/node/daemon needed for
# Bisq (its own hosted public API). Pass --loop to poll continuously instead of
# once. Reuses BasicSwap's venv (stdlib + certifi only, no new dependency).
set -euo pipefail

export SWAP_DATADIR=$HOME/coinswaps
source "$SWAP_DATADIR/venv/bin/activate"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR/.."
python3 -m venues.poller "$@"

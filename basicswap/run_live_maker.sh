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
python3 -m strategy.live_maker --live "$@"

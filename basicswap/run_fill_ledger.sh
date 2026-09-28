#!/bin/bash
# Per-fill P&L ledger — read-only: syncs /json/bids into the fills table and
# prints edge-at-fill + 1h/24h markouts. Needs basicswap-run up (unless
# --report-only). See strategy/fill_ledger.py.
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
python3 -m strategy.fill_ledger "$@"

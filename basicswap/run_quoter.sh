#!/bin/bash
# Shadow quoter — dry-run only, never calls a write endpoint (see strategy/quoter.py's
# module docstring / api_client.py's docstring for the boundary this respects). Needs
# basicswap-run already up. Pass --loop to poll continuously, or --summary to print
# strategy.quoter's repricing-frequency summary without polling.
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
python3 -m strategy.quoter "$@"

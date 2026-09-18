#!/bin/bash
set -euo pipefail

export SWAP_DATADIR=$HOME/coinswaps
export SSL_CERT_FILE="$SWAP_DATADIR/venv/lib/python3.13/site-packages/certifi/cacert.pem"
source "$SWAP_DATADIR/venv/bin/activate"
cd "$SWAP_DATADIR/basicswap"

CURRENT_XMR_HEIGHT=$(curl -s http://node2.monerodevs.org:18089/get_info | jq .height)
echo "XMR restore height: $CURRENT_XMR_HEIGHT (save this)"

SKIP_GPG_VALIDATION=true arch -arm64 basicswap-prepare --datadir="$SWAP_DATADIR" \
    --withcoins=monero,bitcoin \
    --usebtcfastsync \
    --skipbtcfastsyncchecks \
    --xmrrestoreheight="$CURRENT_XMR_HEIGHT"
# Both gpg-skip flags are needed: SKIP_GPG_VALIDATION only guards the per-coin
# release-binary signature check; --skipbtcfastsyncchecks separately guards the
# BTC fastsync UTXO snapshot's hash+signature check (basicswap/interface/btc/core.py
# checkFastsyncData -> createGPG, called unconditionally). Both exist because this
# machine's gnupg CLI failed to build (outdated Xcode CLT, see ARCHITECTURE.md §3) —
# revisit once that's fixed if full signature verification matters to you.

# BasicSwap

Non-custodial atomic-swap DEX (personal swapping) + a market-making strategy on top
of it — **live as of 2026-09-17** (a small, single-sided real offer, see below), not
just under design anymore. See `ARCHITECTURE.md` for the install/API/market-making
design, `project_status.md` for current state, and `next_steps.md` for the go/no-go
research trail — check `project_status.md` first, it usually has the pending action.

**This is now a venue module under `market_maker/`** (moved here 2026-09-17,
unchanged otherwise) — see `../ARCHITECTURE.md` for the cross-venue framework
this is the first module of, and `../next_steps.md` for the framework-level
build queue (which now supersedes/absorbs several items that used to live only
in this directory's own `next_steps.md`, e.g. real MVB sizing and the per-fill
ledger).

**Runtime lives at `~/coinswaps`, not in this directory or this git repo** — that's
where the actual BasicSwap clone, venv, wallets, and blockchain data are. BasicSwap
itself is running there now (`basicswap-run`, own terminal). This directory holds
docs plus the market-making strategy code (`strategy/`), which talks to the running
BasicSwap instance's local JSON API — served on the **same port as the web UI,
`localhost:12700`** (not 12701 — `doc/api.md`'s own examples are wrong/stale for
v0.18.8, see `ARCHITECTURE.md` §5) — and never touches key material directly.

**Live market-making, 2026-09-17**: with Evan's explicit go-ahead (funded the
wallet, chose the size, confirmed via `strategy/live_maker.py --live`), both
sides are now running via two `run_live_maker.sh --loop` instances (real
revoke+repost on drift/staleness, every 5 min): a fixed 0.008 BTC ask offer
(BTC-for-XMR), and an XMR-for-BTC bid side sized dynamically off a live USD
reserve (`--reserve-usd 210` — "offer everything above $210 worth of XMR",
recomputed each cycle, not a fixed coin amount) rather than a second fixed
size, since the wallet already held leftover XMR from the earlier test swap.
`strategy/api_client.py` now has real write methods
(`post_offer`/`revoke_offer`/`get_wallet_balance`); before this, nothing in this
project could touch a real offer. See `project_status.md`'s matching entries for
the exact numbers, the real insufficient-funds bug found and fixed before it
could matter, and verification.

**2026-09-18**: a volatility kill-switch (`strategy/volatility.py`) is built,
tested, and deployed to both live loops the same day (restarted, verified
running, existing live offer survived untouched). See `../project_status.md`'s
matching entry for the design, threshold calibration, and restart verification.

Same safety posture as `coinbase_dca/`/
`finance/crypto_yield/`/`copy_trading/` otherwise: personal swaps stay
human-initiated, no mnemonic/private key is ever generated through or logged
into a Claude session (`ARCHITECTURE.md` §4), and any further escalation (a
bigger size, unattended launchd scheduling) is its own separate decision, not
implied by this one.

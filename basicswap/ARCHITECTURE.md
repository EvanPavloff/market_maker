# BasicSwap — Architecture

## 1. What this is

[BasicSwap](https://github.com/basicswap/basicswap) (v0.18.8) is a non-custodial,
peer-to-peer atomic-swap DEX — trustless cross-chain trading (BTC, XMR, LTC, DASH,
BCH, DOGE, FIRO, PIVX, DCR, WOW, PART, NMC, and a couple others) with no protocol fee
and no order-matching intermediary. It runs as a local daemon (`basicswap-run`) that
talks to a set of full/pruned coin-daemon wallets it manages, relays swap offers/bids
over Particl's SMSG messaging layer, and exposes both a web UI (port 12700) and a
local JSON HTTP API (port 12701, `doc/api.md`) for everything the UI can do.

This project has two distinct purposes, with two very different risk postures:

1. **Personal swapping** — Evan using the web UI himself to swap coins he holds.
   Human-initiated, no automation, no strategy code. Low risk.
2. **Market-making** — an automated strategy that posts offers on both sides of a
   spread and profits from the spread itself (no protocol fee exists to compete with
   the way it would on a CEX). This risks real capital and needs the same
   docs-first / phased-rollout / explicit-sign-off gate every other real-money
   project in this workspace uses (`coinbase_dca/`, `finance/crypto_yield/`,
   `copy_trading/`). See §4.

## 2. Install

**Host: this machine** (`MacBook-Pro-4.localdomain` — actually the always-on M1 Ultra
Mac Studio also running Silenus; the hostname is misleading, see
`project_remote_access_teleport` memory). Chosen because a market maker needs to be
online to respond to bids and complete swap protocol steps within their lock-time
window — the same always-on requirement Silenus already has.

**Native venv, not Docker.** Docker isn't installed on this machine and adding it
purely for this would be a new dependency; BasicSwap supports a native install
(`doc/install.md` "Run Without Docker") that fits this workspace's existing
per-project-venv pattern (`gpu_hosting/`, `coinbase_dca/`).

**Runtime data lives at `~/coinswaps`, outside this git repo.** This mirrors
BasicSwap's own default (`$SWAP_DATADIR=$HOME/coinswaps`) and this workspace's
existing convention of keeping secrets/`.env`/wallet material out of git. The repo's
`basicswap/` directory (this one) holds only docs and, eventually, the market-making
strategy code — nothing here ever contains a mnemonic, private key, or wallet file.

```
~/coinswaps/
  venv/                  Python 3.13 venv (arm64-native, see §3)
  basicswap/             git clone of basicswap/basicswap @ v0.18.8 (upstream, not tracked by this repo)
  <datadir, once basicswap-prepare has run>/
    particl/  bitcoin/  monero/   coin datadirs + wallets
    basicswap.json, .basicswap.json   config
```

**Physically relocated 2026-09-16, `~/coinswaps` is now a symlink.** The Mac
Studio's internal boot volume ran to ~99.9% full (Monero's `lmdb` store has no
pruning mode and grew to 91GB+, on top of the rest of `~/coinswaps`), which crashed
`monerod` mid-write and corrupted Particl's LevelDB block index (recovered via
`-reindex` — see `project_status.md`'s 2026-09-16 entry and the full incident
record in the workspace-root `studio_disk_management.md`). The real data now lives
at `/Volumes/Storage/coinswaps` (a second partition, 937GB free, on the same
external NVMe drive as this machine's Time Machine backup), with `~/coinswaps`
kept as a symlink so every path/command above still works unchanged. **New
dependency this creates: BasicSwap now requires that external drive to stay
connected** — if it's ever unplugged, `basicswap-run` will fail to find its
datadir. Worth a note if this machine's external-drive setup ever changes.

### 3. Build issue hit and fixed: Homebrew-under-Rosetta poisons the arch

This machine's Homebrew lives at `/usr/local` — the Intel build, running under
Rosetta, even though the hardware and the venv's Python are native arm64
(`uname -m` → arm64). BasicSwap's `coincurve` dependency is a custom fork
(`basicswap/coincurve@basicswap_v0.4`, not the PyPI package) that compiles a patched
secp256k1 from source via CMake+Ninja — and Homebrew's `cmake`/`ninja` inherited the
Rosetta process's x86_64 identity, so CMake auto-detected `USE_ASM_X86_64=1` and
compiled the C extension for x86_64 while the venv's own `_cffi_backend` was
arm64-only. Result: `ImportError: ... incompatible architecture (have 'arm64', need
'x86_64')` deep inside the build, plus a separate `ninja: not found` failure before
that (Homebrew hadn't had ninja installed at all).

Fix, in order:
1. `brew install ninja jq` (ninja was simply missing).
2. Install `cmake`/`ninja`/`scikit-build-core`/`cffi` **into the venv itself** rather
   than letting pip's isolated build overlay resolve its own (this ensured arm64
   wheels were what got used).
3. Build with `arch -arm64 pip3 install --no-build-isolation ...` and
   `CMAKE_ARGS="-DCMAKE_OSX_ARCHITECTURES=arm64"` — `--no-build-isolation` was the
   key piece; without it pip kept re-provisioning a fresh isolated overlay that
   picked up the Rosetta-tainted arch again.

`gnupg` (used only to verify release GPG signatures, and by `python-gnupg` at
runtime for BasicSwap's own PGP-based release verification) failed to build via brew
— this machine's Xcode Command Line Tools are outdated and updating them needs
`sudo`/System Settings, a human step. Not blocking; flagged in `project_status.md`.

Everything else installed clean: `pip3 install -r requirements.txt --require-hashes`
(all pinned deps) then `pip3 install .` (basicswap itself) — both via the same
`arch -arm64` + `CMAKE_ARGS` combination. `basicswap-prepare`/`basicswap-run` entry
points are live in the venv and run natively (verified via `--help`).

### 4. Why the mnemonic-generating step is a manual handoff, not something I ran

`basicswap-prepare` generates the Particl wallet's recovery mnemonic and prints it to
stdout — BasicSwap's own docs say "Mnemonics should be stored encrypted and/or
air-gapped." Running that command through an agent's tool calls would put the seed
phrase into this session's transcript/logs, which defeats the point of "air-gapped."
So install stopped right before that step — see `project_status.md` for the exact
command Evan needs to run himself, in his own terminal.

## 5. The JSON API and why it makes automated market-making feasible

`doc/api.md` + `basicswap/js_server.py` — a full local HTTP JSON API served under
`/json/*` on the **same port as the web UI itself (12700)**, same auth/session.
(`doc/api.md`'s own curl examples say `:12701` — verified live 2026-09-15 against a
real running node that this is stale/wrong for v0.18.8: nothing listens on 12701,
`/json/offers` answers correctly on 12700.) Relevant endpoints for a market maker:

- `POST /json/offers/new` — post an offer (`coin_from`, `coin_to`, `amt_from`,
  `amt_to`, `lockseconds`).
- `GET /json/offers`, `/json/sentoffers` — read the live order book / your own open
  offers.
- `GET/POST /json/bids/<id>` — inspect and act on incoming bids against your offers.
- `POST /json/automationstrategies` — BasicSwap has a **built-in maker-automation
  mechanism**: strategies that auto-accept incoming bids matching criteria
  (`set_max_concurrent_bids`, `only_known_identities`, custom rules via `set_data`)
  instead of requiring a human to click "accept" on every bid. This is the mechanism
  any BasicSwap market maker (not just us) actually uses — it's a first-class part of
  the product, not something we'd be bolting on. **Verified against the actual
  source 2026-09-16** (`basicswap.py:shouldAutoAcceptBid`, not just this API-doc
  summary) — see `next_steps.md` §5 for the full detail, including two more real
  safety knobs (`exact_rate_only`, `total_bids_value_multiplier`), a per-identity
  `NEVER_ACCEPT`/`ALWAYS_ACCEPT` override, and the temporary-vs-permanent
  constraint-failure split, none of which this summary originally captured.
- `GET /json/rates`, `/json/coinprices` — reference pricing BasicSwap itself pulls in,
  useful for computing what "mid price" a spread should be centered on.

A market-making bot here is a thin poller/quoter talking to `localhost:12700` —
it lives in this repo (`basicswap/strategy/` — Phase 1's poller/analysis/economics
are built and running against the live node as of 2026-09-16, see below) and never
touches key material directly; BasicSwap's own daemon holds the wallets and does the
actual on-chain/atomic-swap work.

## 6. Market-making design (Phase 1 built and running as of 2026-09-16 — see
`project_status.md`/`next_steps.md`; Phases 2-4 still docs-only)

### Mechanics
Post two offers around a reference mid-price with a spread: e.g. offer to sell XMR
for BTC at `mid * (1 + spread/2)`, and separately offer to buy XMR for BTC (i.e. an
offer selling BTC for XMR) at `mid * (1 - spread/2)`. There's no protocol trading fee
on BasicSwap — the entire edge is the spread captured across the two legs, financed
by providing liquidity/convenience the way any DEX/OTC market maker does.

### The risk that's structurally different from CEX or AMM market-making
Atomic swaps are **not instant fills**. Each swap goes through an HTLC-style
lock/reveal sequence bounded by `lockseconds` (can be well over an hour depending on
the coin pair's confirmation requirements), during which the reference price can move
against an open offer — unlike a CEX limit order (cancel/repost in seconds) or an AMM
(price updates continuously with the pool). Spread sizing has to price in this
exposure window explicitly, not just copy CEX-style tight spreads.

### Other risks to design around, not yet resolved
- **Inventory/rebalancing** — need real BTC and XMR (etc.) on both sides to quote in
  both directions; rebalancing itself costs another swap (or an off-BasicSwap trade
  with its own counterparty/KYC exposure).
- **Settlement mechanics, not counterparty risk** — the atomic-swap protocol itself
  means either both legs complete or neither does (no default risk on settlement),
  but *our* node has to stay online and respond within the lock window or a swap
  times out/fails — reinforces the always-on hosting choice in §2, doesn't eliminate
  the need to monitor for stuck/failed swaps.
- **Competition** — other market makers already run automation strategies on
  BasicSwap today. Whether a real edge exists on BTC/XMR (or any other pair) at
  currently-observed depth/spread is an empirical question, not an assumption — Phase
  1 below exists specifically to answer it before any capital is at risk.
- **Tax/record-keeping** — each swap is very likely a taxable disposal event;
  confirmed via light research 2026-09-16 (see `next_steps.md` §6) — no
  record-keeping mechanism built yet, still flagged for before Phase 3.

### Phased rollout (mirrors `coinbase_dca`/`copy_trading`'s gate — nothing here places
a real offer without a separate, explicit sign-off from Evan)

- **Phase 0 (now):** get BasicSwap running for personal, human-initiated swaps only.
  Zero strategy code.
- **Phase 1:** read-only poller against `/json/offers` + `/json/rates` — observe real
  bid/ask depth and spread on candidate pairs (BTC/XMR first — BasicSwap's flagship
  privacy pair) over a real observation window. Answers "does an edge exist" before
  anything else is built.
- **Phase 2:** shadow-mode — compute what our strategy *would* have quoted against
  the Phase 1 data and whether it would have filled/profited, still posting nothing.
- **Phase 3:** small, human-approved live offers with a hard cap, real fills
  monitored against the Phase 2 model.
- **Phase 4:** unattended automation via BasicSwap's built-in automation strategies
  (§5) — only after Phase 3 validates the edge and the risk controls, gated on
  Evan's explicit sign-off.

Nothing past Phase 0 is built. See `project_status.md` for exactly what's done.

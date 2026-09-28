"""Thin client for Eigen ASB (xmr-btc-swap) quote discovery. Unlike Bisq, there
is no hosted HTTP API — quote discovery only exists as a Rust libp2p client
(`fetch_quotes_json`, this project's own addition to `eigenwallet/core`'s
`swap-p2p` crate, see `next_steps.md` #13), so this wraps that compiled binary
via `subprocess` rather than making an HTTP call directly.

That binary does real rendezvous-node discovery + per-ASB quote requests over
libp2p (optionally through Tor) and prints exactly one JSON array to stdout on
exit — see `fetch_quotes_json.rs`'s own header comment for the exact contract.
No wallet, no key material, no capital anywhere in this path — same posture as
`bisq/client.py`.

Getting this far took real work, not a given: `libp2p` had to be bumped
workspace-wide (0.53.2 -> 0.57.0, on Evan's explicit go-ahead 2026-09-19) to
pick up a `libp2p-rendezvous` release that fixed a real, previously-diagnosed
`quick-protobuf` wire-format bug — full derivation in `next_steps.md` #13.
The fixed source (with all migration fixes applied) lives permanently at
`~/eigenwallet-core` (a sibling to BasicSwap's own `~/coinswaps` — this
project's convention for runtime state that doesn't belong in the git repo),
not in this session's scratchpad, so it survives across sessions.

**Deliberately does not use Tor by default** for the scheduled poller, unlike
the real `swap` CLI's own default posture: this is pure, no-stakes, read-only
market-data observation (never a real trade, no wallet, no funds), Tor
bootstrap costs ~10-12s every cycle for no privacy benefit that matters here,
and non-Tor clearnet was verified to return the identical live quotes
(2026-09-19). Set `EIGEN_ASB_USE_TOR=1` to override if that tradeoff ever
needs revisiting.
"""

import json
import os
import subprocess
from typing import Any

_DEFAULT_BINARY_PATH = os.path.expanduser(
    "~/eigenwallet-core/target/release/examples/fetch_quotes_json"
)


class EigenAsbClientError(RuntimeError):
    """Raised on any subprocess/parse failure running the fetch_quotes_json binary."""


class EigenAsbClient:
    def __init__(
        self,
        binary_path: str | None = None,
        fetch_timeout_seconds: float = 20.0,
        use_tor: bool | None = None,
    ):
        self.binary_path = binary_path or os.environ.get(
            "EIGEN_ASB_BINARY_PATH", _DEFAULT_BINARY_PATH
        )
        self.fetch_timeout_seconds = fetch_timeout_seconds
        if use_tor is None:
            use_tor = os.environ.get("EIGEN_ASB_USE_TOR", "0") == "1"
        self.use_tor = use_tor

    def fetch_quotes(self) -> list[dict[str, Any]]:
        """Real, live ASB quotes: `[{"peer", "address", "price_btc_display",
        "min_quantity_btc_display", "max_quantity_btc_display",
        "agent_version"}, ...]` — verbatim, un-normalized (see `reader.py` for
        the NormalizedOffer mapping). Empty list is a valid result (no ASBs
        reachable this cycle), not an error.
        """
        if not os.path.isfile(self.binary_path):
            raise EigenAsbClientError(
                f"fetch_quotes_json binary not found at {self.binary_path!r} — "
                f"build it: cd ~/eigenwallet-core && cargo build --release "
                f"--example fetch_quotes_json --features swap-p2p/fetch-quotes-example -p swap-p2p"
            )

        env = dict(os.environ)
        env["FETCH_QUOTES_TIMEOUT_SECS"] = str(int(self.fetch_timeout_seconds))
        env["FETCH_QUOTES_USE_TOR"] = "1" if self.use_tor else "0"
        env.setdefault("FETCH_QUOTES_LOG", "warn")

        try:
            result = subprocess.run(
                [self.binary_path],
                env=env,
                capture_output=True,
                text=True,
                # Real safety-net margin over the binary's own internal deadline
                # (Tor bootstrap + process startup aren't counted inside
                # FETCH_QUOTES_TIMEOUT_SECS) — a hang here shouldn't be able to
                # block the whole poll cycle indefinitely.
                timeout=self.fetch_timeout_seconds + 20.0,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise EigenAsbClientError(
                f"fetch_quotes_json did not exit within "
                f"{self.fetch_timeout_seconds + 20.0}s: {e}"
            ) from e

        if result.returncode != 0:
            raise EigenAsbClientError(
                f"fetch_quotes_json exited {result.returncode}: {result.stderr[-2000:]}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise EigenAsbClientError(
                f"fetch_quotes_json produced invalid JSON on stdout: {e} "
                f"(stderr: {result.stderr[-500:]!r})"
            ) from e

        if not isinstance(data, list):
            raise EigenAsbClientError(f"fetch_quotes_json returned unexpected shape: {data!r}")

        return data

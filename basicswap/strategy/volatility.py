"""Rolling-window volatility monitor for live_maker.py's kill-switch
(market_maker/next_steps.md #1 / ARCHITECTURE.md §6's "Volatility kill-switch"
row). Reuses the reference-mid samples external_rates.get_reference_rate()
already fetches every live_maker cycle — no new polling, no new API surface.

Threshold calibration: the default 0.85% is just above the ~99th percentile of
a 15-minute range-based volatility metric, (max-min)/mean over the window,
computed 2026-09-18 against 512 real direct_rate_snapshots samples (~42.6h of
basicswap/strategy/poller.py's own observation-window history for
Monero/Bitcoin, 2026-09-16 through 2026-09-18). Percentiles at that window:
p50=0.22%, p90=0.49%, p95=0.63%, p99=0.84%, max=1.10%. Picking just above p99
means the kill-switch fires only on moves more extreme than ~99% of what this
pair has actually done in practice, not on the routine noise decide_and_act's
own reprice_threshold_pct (0.5%) already reprices through. Re-derive this from
a longer/fresher sample once the observation window clears its 1-2 week bar
(basicswap/next_steps.md §3) rather than treating 0.85% as permanent.
"""

from dataclasses import dataclass, field


@dataclass
class VolatilityMonitor:
    """In-memory rolling window of (timestamp, reference_mid) samples for one
    pair/side live_maker process. Deliberately not persisted to storage.py —
    losing this on a restart just means a couple of cycles pass before it has
    enough samples to speak again (volatility_pct() returns None until then),
    which is the same safe fail-open behavior as "not enough data yet", not a
    fail-closed anomaly worth guarding with real state.
    """

    window_seconds: float
    _samples: list[tuple[float, float]] = field(default_factory=list)

    def add(self, ts: float, mid: float) -> None:
        self._samples.append((ts, mid))
        cutoff = ts - self.window_seconds
        self._samples = [(t, m) for t, m in self._samples if t >= cutoff]

    def volatility_pct(self) -> float | None:
        """(max-min)/mean over the current window. None with fewer than 2
        samples in the window — callers must treat that as "kill-switch can't
        evaluate yet," never as zero volatility.
        """
        if len(self._samples) < 2:
            return None
        mids = [m for _, m in self._samples]
        mean = sum(mids) / len(mids)
        if not mean:
            return None
        return (max(mids) - min(mids)) / mean

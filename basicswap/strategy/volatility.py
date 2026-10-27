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

2026-09-24 recalibration (market_maker/project_status.md's matching entry):
re-running the same metric over 1,585 samples (2026-09-16 -> 09-23, ~7 days)
puts the 15-min p99 at 2.01% (p90 0.71%, p95 0.98%, max 4.50%) — the original
42h sample badly understated the tails, and 0.85% now fires on ~7% of cycles.
More importantly, the 2026-09-18 ask fill that lost ~7% on a +1h markout got
through the 15-min switch anyway: it fired four cycles running (up to 3.86%),
then one quiet reading (only ~3 samples fit a 15-min window at a 5-min
cadence; one aged out by a single second, and CoinGecko's price briefly
plateaued) let run_cycle reprice straight into the top of the move. Two
additions close that shape of failure, both evaluated from the same samples:
  - a longer window (default 60 min, ~12 samples — one flat reading can't
    clear it). 60-min range percentiles on the same week: p50 0.96%,
    p90 1.96%, p95 3.12%, p99 6.06%, max 8.66% (the 09-18 spike), so the
    default 3% sits around p95.
  - a cooldown (default 30 min): once either window trips, quoting stays
    paused until that long has passed with no further trip, so a single calm
    cycle mid-spike can't re-arm it.
Replaying the week with 15m>0.85% + 60m>3% + 30m cooldown pauses ~18% of
cycles in 24 episodes (vs. ~7% in 47 flickering episodes today); loosening
the 15-min threshold to 1.2% with the same long window/cooldown gives ~9.5%
in 10 episodes. Defaults keep 0.85% — loosening any guard is Evan's call.
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

    window_seconds is how much history is *retained* — it must cover the
    longest window any caller evaluates via volatility_pct(within_seconds=...).
    last_trip_at is the kill-switch's cooldown state (see run_cycle); in-memory
    for the same reason as the samples.
    """

    window_seconds: float
    _samples: list[tuple[float, float]] = field(default_factory=list)
    last_trip_at: float | None = None

    def add(self, ts: float, mid: float) -> None:
        self._samples.append((ts, mid))
        cutoff = ts - self.window_seconds
        self._samples = [(t, m) for t, m in self._samples if t >= cutoff]

    def latest(self) -> tuple[float, float] | None:
        """The most recent (ts, mid) sample, or None."""
        return self._samples[-1] if self._samples else None

    def volatility_pct(self, within_seconds: float | None = None) -> float | None:
        """(max-min)/mean over the trailing within_seconds (default: the whole
        retained window), measured back from the newest sample. None with fewer
        than 2 samples in that span — callers must treat that as "kill-switch
        can't evaluate yet," never as zero volatility.
        """
        if not self._samples:
            return None
        if within_seconds is None:
            samples = self._samples
        else:
            cutoff = self._samples[-1][0] - within_seconds
            samples = [(t, m) for t, m in self._samples if t >= cutoff]
        if len(samples) < 2:
            return None
        mids = [m for _, m in samples]
        mean = sum(mids) / len(mids)
        if not mean:
            return None
        return (max(mids) - min(mids)) / mean

    def cooling_down(self, now: float, cooldown_seconds: float) -> bool:
        return (
            cooldown_seconds > 0
            and self.last_trip_at is not None
            and now - self.last_trip_at < cooldown_seconds
        )

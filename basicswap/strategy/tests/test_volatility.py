import unittest

from ..volatility import VolatilityMonitor


class VolatilityMonitorTests(unittest.TestCase):
    def test_fewer_than_two_samples_returns_none(self):
        monitor = VolatilityMonitor(window_seconds=900)
        self.assertIsNone(monitor.volatility_pct())
        monitor.add(1000.0, 150.0)
        self.assertIsNone(monitor.volatility_pct())

    def test_stable_price_reports_zero_volatility(self):
        monitor = VolatilityMonitor(window_seconds=900)
        for i in range(5):
            monitor.add(1000.0 + i * 100, 150.0)
        self.assertEqual(monitor.volatility_pct(), 0.0)

    def test_range_over_mean_within_window(self):
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(1000.0, 150.0)
        monitor.add(1100.0, 153.0)
        # (153 - 150) / mean(150, 153) = 3 / 151.5
        self.assertAlmostEqual(monitor.volatility_pct(), 3 / 151.5)

    def test_samples_outside_window_are_dropped(self):
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(1000.0, 150.0)  # will fall outside the window once 2000.0 arrives
        monitor.add(2000.0, 300.0)
        # Only the second sample remains once the first ages out (2000 - 1000 = 1000s > 900s
        # window) — one sample left means "not enough data," not a huge spurious spike.
        self.assertIsNone(monitor.volatility_pct())

    def test_samples_within_window_are_retained(self):
        monitor = VolatilityMonitor(window_seconds=900)
        monitor.add(1000.0, 150.0)
        monitor.add(1800.0, 150.0)  # 800s later, still inside the 900s window
        self.assertEqual(monitor.volatility_pct(), 0.0)

    def test_within_seconds_evaluates_only_the_trailing_subwindow(self):
        monitor = VolatilityMonitor(window_seconds=3600)
        monitor.add(1000.0, 140.0)  # 40 min before the newest sample
        monitor.add(3100.0, 150.0)
        monitor.add(3400.0, 150.0)
        self.assertEqual(monitor.volatility_pct(within_seconds=900), 0.0)
        self.assertAlmostEqual(monitor.volatility_pct(), 10 / (440 / 3))

    def test_within_seconds_with_one_sample_in_span_returns_none(self):
        monitor = VolatilityMonitor(window_seconds=3600)
        monitor.add(1000.0, 140.0)
        monitor.add(3400.0, 150.0)
        self.assertIsNone(monitor.volatility_pct(within_seconds=900))

    def test_cooling_down(self):
        monitor = VolatilityMonitor(window_seconds=900)
        self.assertFalse(monitor.cooling_down(1000.0, 1800))
        monitor.last_trip_at = 1000.0
        self.assertTrue(monitor.cooling_down(2000.0, 1800))
        self.assertFalse(monitor.cooling_down(2800.0, 1800))
        self.assertFalse(monitor.cooling_down(2000.0, 0))


if __name__ == "__main__":
    unittest.main()

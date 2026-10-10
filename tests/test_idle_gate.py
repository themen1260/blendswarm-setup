import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "python"))
from worker_client import IdleGate


class IdleGateTests(unittest.TestCase):
    def test_requires_five_continuous_idle_minutes(self):
        gate = IdleGate(confirmation_seconds=300)
        self.assertFalse(gate.update(10, [], now=100))
        self.assertFalse(gate.update(10, [], now=399))
        self.assertTrue(gate.update(10, [], now=400))

    def test_busy_cpu_resets_idle_period(self):
        gate = IdleGate(confirmation_seconds=300)
        self.assertFalse(gate.update(10, [], now=100))
        self.assertFalse(gate.update(30, [], now=250))
        self.assertFalse(gate.update(10, [], now=549))
        self.assertFalse(gate.update(10, [], now=848))
        self.assertTrue(gate.update(10, [], now=849))

    def test_busy_measurable_gpu_resets_idle_period(self):
        gate = IdleGate(confirmation_seconds=300)
        self.assertFalse(gate.update(10, [10], now=100))
        self.assertFalse(gate.update(10, [21], now=250))
        self.assertFalse(gate.update(10, [10], now=549))
        self.assertFalse(gate.update(10, [10], now=848))
        self.assertTrue(gate.update(10, [10], now=849))

    def test_missing_gpu_telemetry_uses_cpu_only(self):
        gate = IdleGate(confirmation_seconds=300)
        self.assertFalse(gate.update(10, None, now=100))
        self.assertTrue(gate.update(10, None, now=400))


if __name__ == "__main__":
    unittest.main()

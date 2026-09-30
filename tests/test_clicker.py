import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from autoclicker.clicker import ClickerEngine
from autoclicker.settings import Settings


class FakeMouse:
    def __init__(self, clock=time.perf_counter):
        self.events = []
        self.click_times = []
        self._clock = clock

    def move(self, x, y):
        self.events.append(("move", x, y))

    def click(self, button, count=1):
        self.events.append(("click", button, count))
        self.click_times.append(self._clock())


def settings(**overrides):
    """Settings for engine tests: no start delay unless a test asks for one."""
    return Settings(**{"start_delay": 0, **overrides})


class VirtualClock(threading.Event):
    """Replaces the engine's clock and stop event so timing tests don't depend on the machine.

    Timed waits return immediately but move the clock forward by the timeout plus
    `oversleep` (like a throttled OS timer), plus `stall_once` on the first wait.
    The clock stops the engine once it reaches `run_for` seconds.
    """

    def __init__(self, run_for, oversleep=0.0, stall_once=0.0):
        super().__init__()
        self.now = 0.0
        self.run_for = run_for
        self.oversleep = oversleep
        self.stall = stall_once

    def perf_counter(self):
        return self.now

    def wait(self, timeout=None):
        if timeout is None:
            return super().wait()
        self.now += timeout + self.oversleep + self.stall
        self.stall = 0.0
        if self.now >= self.run_for:
            self.set()
        return self.is_set()


def run_virtual(settings, run_for, oversleep=0.0, stall_once=0.0):
    clock = VirtualClock(run_for, oversleep, stall_once)
    mouse = FakeMouse(clock=clock.perf_counter)
    engine = ClickerEngine(mouse)
    engine._stop = clock
    with mock.patch("autoclicker.clicker.time", SimpleNamespace(perf_counter=clock.perf_counter)):
        engine.start(settings)
        engine.join(5)
    return engine, mouse


def run_engine(settings, until=lambda engine: False, timeout=2.0):
    mouse, updates = FakeMouse(), []
    engine = ClickerEngine(mouse, on_update=updates.append)
    engine.start(settings)
    deadline = time.monotonic() + timeout
    while engine.running and not until(engine) and time.monotonic() < deadline:
        time.sleep(0.005)
    engine.stop()
    engine.join(1)
    return engine, mouse, updates


class ClickerEngineTest(unittest.TestCase):
    def test_stop_after_limits_click_count(self):
        engine, mouse, updates = run_engine(settings(cps=1000, stop_after=25))
        self.assertEqual(engine.clicks, 25)
        self.assertEqual(len(mouse.events), 25)
        self.assertEqual(updates[-1], {"state": "idle", "clicks": 25})

    def test_double_click_sends_count_two(self):
        _, mouse, _ = run_engine(settings(cps=1000, click_type="double", button="right", stop_after=3))
        self.assertEqual(mouse.events, [("click", "right", 2)] * 3)

    def test_pinned_position_moves_before_each_click(self):
        _, mouse, _ = run_engine(settings(cps=1000, position=[10, 20], stop_after=2))
        self.assertEqual(mouse.events, [("move", 10, 20), ("click", "left", 1)] * 2)

    def test_rate_is_respected(self):
        engine, _ = run_virtual(settings(cps=50), run_for=0.5)
        self.assertAlmostEqual(engine.clicks, 25, delta=1)

    def test_rate_holds_when_timers_oversleep(self):
        # 100 cps for 0.5 s, minus the final 30 ms oversleep that runs past the end: 47 clicks.
        # Without catch-up each 10 ms wait takes 40 ms (~12 clicks).
        engine, _ = run_virtual(settings(cps=100), run_for=0.5, oversleep=0.03)
        self.assertAlmostEqual(engine.clicks, 47, delta=1)

    def test_catch_up_is_capped(self):
        # One 1 s stall at 1000 cps must not replay 1000 clicks, only MAX_LAG (0.1 s) worth.
        _, mouse = run_virtual(settings(cps=1000, stop_after=300), run_for=10, stall_once=1.0)
        t = mouse.click_times
        self.assertEqual(len(t), 300)
        # Clicks 2..101 are the make-up burst right after the stall...
        self.assertLess(t[100] - t[1], 0.005)
        # ...and the remaining ~200 are paced at 1 ms, not replayed instantly.
        self.assertAlmostEqual(t[299] - t[100], 0.199, delta=0.005)

    def test_stop_during_start_delay_never_clicks(self):
        engine, mouse, updates = run_engine(settings(cps=1000, start_delay=5), timeout=0.2)
        self.assertEqual(mouse.events, [])
        self.assertEqual(updates[0]["state"], "countdown")


class SettingsTest(unittest.TestCase):
    def test_sanitizes_bad_values(self):
        s = Settings.from_dict({"cps": 99999, "button": "nope", "stop_after": "0", "start_delay": -3,
                                "position": "x", "unknown": 1})
        self.assertEqual(s.cps, 1000)
        self.assertEqual(s.button, "left")
        self.assertEqual(Settings.from_dict({"click_type": "hold"}).click_type, "single")  # removed option
        self.assertIsNone(s.stop_after)
        self.assertEqual(s.start_delay, 0)
        self.assertIsNone(s.position)

    def test_default_start_delay_is_three_seconds(self):
        self.assertEqual(Settings().start_delay, 3.0)


if __name__ == "__main__":
    unittest.main()

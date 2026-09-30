import threading
import time
import unittest

from autoclicker.clicker import ClickerEngine
from autoclicker.settings import Settings


class FakeMouse:
    def __init__(self):
        self.events = []
        self.click_times = []

    def move(self, x, y):
        self.events.append(("move", x, y))

    def click(self, button, count=1):
        self.events.append(("click", button, count))
        self.click_times.append(time.perf_counter())

    def press(self, button):
        self.events.append(("press", button))

    def release(self, button):
        self.events.append(("release", button))


class SluggishEvent(threading.Event):
    """Oversleeps every timed wait by 30 ms, like a throttled OS timer."""

    def wait(self, timeout=None):
        return super().wait(None if timeout is None else timeout + 0.03)


def run_engine(settings, until=lambda engine: False, timeout=2.0, should_skip=None, stop_event=None):
    mouse, updates = FakeMouse(), []
    engine = ClickerEngine(mouse, on_update=updates.append)
    if should_skip:
        engine.should_skip = should_skip
    if stop_event:
        engine._stop = stop_event
    engine.start(settings)
    deadline = time.monotonic() + timeout
    while engine.running and not until(engine) and time.monotonic() < deadline:
        time.sleep(0.005)
    engine.stop()
    engine.join(1)
    return engine, mouse, updates


class ClickerEngineTest(unittest.TestCase):
    def test_stop_after_limits_click_count(self):
        engine, mouse, updates = run_engine(Settings(cps=1000, stop_after=25))
        self.assertEqual(engine.clicks, 25)
        self.assertEqual(len(mouse.events), 25)
        self.assertEqual(updates[-1], {"state": "idle", "clicks": 25})

    def test_double_click_sends_count_two(self):
        _, mouse, _ = run_engine(Settings(cps=1000, click_type="double", button="right", stop_after=3))
        self.assertEqual(mouse.events, [("click", "right", 2)] * 3)

    def test_pinned_position_moves_before_each_click(self):
        _, mouse, _ = run_engine(Settings(cps=1000, position=[10, 20], stop_after=2))
        self.assertEqual(mouse.events, [("move", 10, 20), ("click", "left", 1)] * 2)

    def test_rate_is_roughly_respected(self):
        engine, _, _ = run_engine(Settings(cps=50), timeout=0.5)
        self.assertTrue(20 <= engine.clicks <= 30, engine.clicks)

    def test_rate_holds_when_timers_oversleep(self):
        # 100 cps for 0.5 s = 50 clicks; without catch-up each 10 ms wait takes 40 ms (~12 clicks).
        engine, _, _ = run_engine(Settings(cps=100), timeout=0.5, stop_event=SluggishEvent())
        self.assertTrue(40 <= engine.clicks <= 55, engine.clicks)

    def test_catch_up_is_capped(self):
        # One 1 s stall at 1000 cps must not replay 1000 clicks, only MAX_LAG (0.1 s) worth.
        class StallOnce(threading.Event):
            stalled = False

            def wait(self, timeout=None):
                if timeout is not None and not self.stalled:
                    self.stalled = True
                    time.sleep(1.0)
                return super().wait(timeout)

        _, mouse, _ = run_engine(Settings(cps=1000, stop_after=300), timeout=3, stop_event=StallOnce())
        t = mouse.click_times
        self.assertEqual(len(t), 300)
        # Clicks 2..101 are the make-up burst right after the stall...
        self.assertLess(t[100] - t[1], 0.05)
        # ...and the remaining ~200 are paced at 1 ms, not replayed instantly.
        self.assertGreater(t[299] - t[1], 0.15)

    def test_skips_clicks_while_cursor_over_app(self):
        engine, mouse, updates = run_engine(Settings(cps=1000), timeout=0.2, should_skip=lambda: True)
        self.assertEqual(mouse.events, [])
        self.assertIn("paused", [u["state"] for u in updates])

    def test_skip_does_not_apply_to_pinned_position(self):
        _, mouse, _ = run_engine(Settings(cps=1000, position=[1, 1], stop_after=1), should_skip=lambda: True)
        self.assertIn(("click", "left", 1), mouse.events)

    def test_stop_during_start_delay_never_clicks(self):
        engine, mouse, updates = run_engine(Settings(cps=1000, start_delay=5), timeout=0.2)
        self.assertEqual(mouse.events, [])
        self.assertEqual(updates[0]["state"], "countdown")

    def test_hold_presses_until_stopped(self):
        _, mouse, _ = run_engine(Settings(click_type="hold", button="middle"), timeout=0.1)
        self.assertEqual(mouse.events, [("press", "middle"), ("release", "middle")])


class SettingsTest(unittest.TestCase):
    def test_sanitizes_bad_values(self):
        s = Settings.from_dict({"cps": 99999, "button": "nope", "stop_after": "0", "start_delay": -3,
                                "position": "x", "unknown": 1})
        self.assertEqual(s.cps, 1000)
        self.assertEqual(s.button, "left")
        self.assertIsNone(s.stop_after)
        self.assertEqual(s.start_delay, 0)
        self.assertIsNone(s.position)


if __name__ == "__main__":
    unittest.main()

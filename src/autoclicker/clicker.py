"""Click engine: runs the click loop on a worker thread."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .settings import Settings
from .timing import precise_timers

UPDATE_INTERVAL = 0.1  # seconds between status updates sent to the UI
MAX_LAG = 0.1  # seconds of missed clicks to make up after an oversleep; older ones are dropped


class PynputMouse:
    """Mouse backend built on pynput (imported lazily so tests don't need a display)."""

    def __init__(self):
        from pynput.mouse import Button, Controller

        self._mouse = Controller()
        self._buttons = {"left": Button.left, "right": Button.right, "middle": Button.middle}

    def move(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)

    def click(self, button: str, count: int = 1) -> None:
        self._mouse.click(self._buttons[button], count)



class ClickerEngine:
    """Clicks on a background thread; reports progress through on_update(state_dict).

    States sent to on_update: countdown, running, paused, idle.
    """

    def __init__(self, mouse, on_update: Callable[[dict], None] = lambda state: None):
        self._mouse = mouse
        self._on_update = on_update
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.clicks = 0
        # Returns True while clicks should be held back (the cursor is over our own window).
        self.should_skip: Callable[[], bool] = lambda: False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, settings: Settings) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self.clicks = 0
            self._thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def toggle(self, settings: Settings) -> None:
        if self.running:
            self.stop()
        else:
            self.start(settings)

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, s: Settings) -> None:
        try:
            with precise_timers():
                if self._countdown(s.start_delay):
                    self._click_loop(s)
        finally:
            self._emit("idle")

    def _countdown(self, delay: float) -> bool:
        """Wait out the start delay. Returns False if stopped during it."""
        end = time.perf_counter() + delay
        while True:
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return True
            self._emit("countdown", remaining=remaining)
            if self._stop.wait(min(UPDATE_INTERVAL, remaining)):
                return False

    def _skipping(self, s: Settings) -> bool:
        return s.position is None and self.should_skip()

    def _click_loop(self, s: Settings) -> None:
        interval = 1.0 / s.cps
        count = 2 if s.click_type == "double" else 1
        next_click = time.perf_counter()
        last_emit, last_state = 0.0, None
        while not self._stop.is_set():
            if self._skipping(s):
                state = "paused"
            else:
                state = "running"
                if s.position:
                    self._mouse.move(*s.position)
                self._mouse.click(s.button, count)
                self.clicks += 1
                if s.stop_after and self.clicks >= s.stop_after:
                    return
            now = time.perf_counter()
            if state != last_state or now - last_emit >= UPDATE_INTERVAL:
                self._emit(state)
                last_emit, last_state = now, state
            # Schedule against absolute deadlines so sleep overhead doesn't accumulate.
            # If a wait overslept, the next clicks fire immediately to keep the average
            # rate, but never more than MAX_LAG worth of them.
            next_click += interval
            behind = time.perf_counter() - next_click
            if behind > MAX_LAG:
                next_click += behind - MAX_LAG
            wait = next_click - time.perf_counter()
            if wait > 0 and self._stop.wait(wait):
                return

    def _emit(self, state: str, **extra) -> None:
        self._on_update({"state": state, "clicks": self.clicks, **extra})

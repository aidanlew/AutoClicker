"""Bridge between the web UI and the clicker engine.

pywebview exposes every public attribute of Api to JavaScript as
window.pywebview.api.*, so internal state and lifecycle hooks are underscore-prefixed.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from typing import Optional

from .clicker import ClickerEngine, PynputMouse
from .hotkeys import HotkeyListener
from .settings import Settings

PICK_TIMEOUT = 30  # seconds to wait for the user to click a spot when pinning


def platform_warning() -> Optional[str]:
    """A message for the status line if clicking can't work yet on this system."""
    if sys.platform == "darwin":
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        except ImportError:
            return None
        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            return "Needs Accessibility access: System Settings → Privacy & Security → Accessibility."
    elif sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "Wayland session: clicks and hotkeys only reach X11/XWayland apps."
    return None


class Api:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._window = None
        self._cursor_over_app = False
        self._engine = ClickerEngine(PynputMouse(), on_update=self._queue_update)
        self._engine.should_skip = lambda: self._cursor_over_app
        self._hotkeys = HotkeyListener(lambda: self._engine.toggle(self._settings))
        self._latest_update: Optional[dict] = None
        self._update_ready = threading.Event()

    # ---- lifecycle (called from __main__, not from JS) ----

    def _attach(self, window) -> None:
        self._window = window

    def _start_services(self) -> None:
        try:
            self._hotkeys.set(self._settings.hotkey)
        except ValueError:
            self._settings.hotkey = Settings().hotkey
            self._hotkeys.set(self._settings.hotkey)
        threading.Thread(target=self._pump_updates, daemon=True).start()

    def _shutdown(self) -> None:
        self._engine.stop()
        self._hotkeys.stop()

    def _queue_update(self, state: dict) -> None:
        # evaluate_js blocks until the GUI thread runs it, so the click thread only
        # records the latest state and a separate thread delivers it.
        self._latest_update = state
        self._update_ready.set()

    def _pump_updates(self) -> None:
        while True:
            self._update_ready.wait()
            self._update_ready.clear()
            script = f"window.onEngineUpdate && window.onEngineUpdate({json.dumps(self._latest_update)})"
            try:
                self._window.evaluate_js(script)
            except Exception:
                return  # window closed

    # ---- called from JS ----

    def get_state(self) -> dict:
        return {
            "settings": self._settings.to_dict(),
            "platform": sys.platform,
            "warning": platform_warning(),
            "running": self._engine.running,
        }

    def save_settings(self, data: dict) -> dict:
        data = {k: v for k, v in data.items() if k not in ("hotkey", "always_on_top")}
        self._settings = Settings.from_dict({**self._settings.to_dict(), **data})
        self._settings.save()
        return self._settings.to_dict()

    def start(self, data: Optional[dict] = None) -> None:
        if data:
            self.save_settings(data)
        self._engine.start(self._settings)

    def stop(self) -> None:
        self._engine.stop()

    def set_hotkey(self, combo: str) -> dict:
        try:
            self._hotkeys.set(combo)
        except ValueError:
            return {"ok": False, "error": "That shortcut can't be used. Try a function key."}
        self._settings.hotkey = combo
        self._settings.save()
        return {"ok": True}

    def pause_hotkey(self, paused: bool) -> None:
        self._hotkeys.paused = bool(paused)

    def set_cursor_over_app(self, over: bool) -> None:
        self._cursor_over_app = bool(over)

    def set_always_on_top(self, on: bool) -> None:
        self._settings.always_on_top = bool(on)
        self._settings.save()
        self._window.on_top = self._settings.always_on_top

    def pick_position(self) -> Optional[list]:
        """Block until the user clicks anywhere on screen; return that point."""
        from pynput import mouse

        picked = {}
        done = threading.Event()

        def on_click(x, y, button, pressed):
            if pressed:
                picked["pos"] = [int(x), int(y)]
                done.set()
                return False

        with mouse.Listener(on_click=on_click):
            done.wait(PICK_TIMEOUT)
        return picked.get("pos")

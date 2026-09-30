"""Global toggle hotkey that works while any app is focused.

pynput's keyboard listener runs in a child process. On macOS, starting a listener
queries the keyboard layout (TSMGetInputSourceProperty) off the main thread, and
macOS aborts the whole process once the app's own window has handled typing.
A child process without a GUI avoids that; it's used on every OS to keep one code path.
"""
from __future__ import annotations

import multiprocessing
import threading
from typing import Callable

_FIRED = "fired"


def _child_main(commands, events) -> None:
    """Child process: (re)start a GlobalHotKeys listener for each combo received."""
    from pynput import keyboard

    listener = None
    while True:
        try:
            combo = commands.recv()
        except EOFError:
            break  # parent exited
        if listener is not None:
            listener.stop()
            listener = None
        if combo is None:
            break
        listener = keyboard.GlobalHotKeys({combo: lambda: events.send(_FIRED)})
        listener.start()
    if listener is not None:
        listener.stop()


class HotkeyListener:
    def __init__(self, callback: Callable[[], None]):
        self._callback = callback
        self._process = None
        self._commands = None
        self.paused = False  # set while the UI is recording a new hotkey

    def set(self, combo: str) -> None:
        """Listen for combo (pynput format, e.g. '<shift>+c'). Raises ValueError if invalid."""
        from pynput.keyboard import HotKey

        try:
            HotKey.parse(combo)
        except (KeyError, ValueError) as e:
            raise ValueError(f"invalid hotkey {combo!r}") from e
        if self._process is None:
            self._start_child()
        self._commands.send(combo)

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._commands.send(None)
        except OSError:
            pass
        self._process.join(1)
        if self._process.is_alive():
            self._process.terminate()
        self._process = None

    def _start_child(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        events_recv, events_send = ctx.Pipe(duplex=False)
        commands_recv, self._commands = ctx.Pipe(duplex=False)
        self._process = ctx.Process(target=_child_main, args=(commands_recv, events_send), daemon=True)
        self._process.start()
        # Close the parent's copies of the child's ends so EOF propagates when either side exits.
        commands_recv.close()
        events_send.close()
        threading.Thread(target=self._read_events, args=(events_recv,), daemon=True).start()

    def _read_events(self, events) -> None:
        while True:
            try:
                events.recv()
            except (EOFError, OSError):
                return
            if not self.paused:
                self._callback()

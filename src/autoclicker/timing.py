"""Keeps OS timers precise while clicking.

macOS App Nap and timer coalescing can stretch a 1 ms wait to 15+ ms for apps
whose window is in the background (which is where this one sits while clicking),
and Windows rounds waits up to its 15.6 ms default timer tick.
"""
from __future__ import annotations

import contextlib
import sys


@contextlib.contextmanager
def precise_timers():
    if sys.platform == "darwin":
        with _macos_latency_critical():
            yield
    elif sys.platform == "win32":
        with _windows_1ms_timer():
            yield
    else:
        yield


@contextlib.contextmanager
def _macos_latency_critical():
    try:
        from Foundation import NSActivityLatencyCritical, NSActivityUserInitiated, NSProcessInfo
    except ImportError:
        yield
        return
    info = NSProcessInfo.processInfo()
    token = info.beginActivityWithOptions_reason_(
        NSActivityUserInitiated | NSActivityLatencyCritical, "Auto clicking"
    )
    try:
        yield
    finally:
        info.endActivity_(token)


@contextlib.contextmanager
def _windows_1ms_timer():
    import ctypes

    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    try:
        yield
    finally:
        winmm.timeEndPeriod(1)

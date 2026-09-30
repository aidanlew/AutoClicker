"""Entry point: python -m autoclicker"""
import multiprocessing
from pathlib import Path

import darkdetect
import webview

from .api import Api
from .settings import Settings

UI_DIR = Path(__file__).resolve().parent / "ui"

# Must match --bg in ui/style.css so the window doesn't flash before the page paints.
BG_DARK = "#20212b"
BG_LIGHT = "#f2f2f5"


def main() -> None:
    settings = Settings.load()
    api = Api(settings)
    window = webview.create_window(
        "Auto Clicker",
        str(UI_DIR / "index.html"),
        js_api=api,
        # Starting size only; the page resizes the window to fit its content, then shows it.
        width=460,
        height=580,
        resizable=False,
        hidden=True,
        on_top=settings.always_on_top,
        background_color=BG_LIGHT if darkdetect.isLight() else BG_DARK,
    )
    api._attach(window)
    window.events.closed += api._shutdown
    webview.start(api._start_services)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # hotkey child process in frozen (PyInstaller) builds
    main()

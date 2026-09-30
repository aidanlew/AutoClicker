"""User settings, persisted as JSON in the OS config directory."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Optional

from platformdirs import user_config_dir

CONFIG_PATH = Path(user_config_dir("AutoClicker", appauthor=False)) / "settings.json"

BUTTONS = ("left", "right", "middle")
CLICK_TYPES = ("single", "double")
MIN_CPS, MAX_CPS = 0.01, 1000.0


@dataclass
class Settings:
    cps: float = 10.0
    button: str = "left"
    click_type: str = "single"
    position: Optional[List[int]] = None  # None = follow the cursor
    stop_after: Optional[int] = None  # None = run until stopped
    start_delay: float = 3.0  # time to move the cursor to the target after pressing Start
    hotkey: str = "<f6>"  # pynput GlobalHotKeys format
    always_on_top: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        settings._sanitize()
        return settings

    @classmethod
    def load(cls) -> Settings:
        try:
            return cls.from_dict(json.loads(CONFIG_PATH.read_text()))
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.to_dict(), indent=2))

    def to_dict(self) -> dict:
        return asdict(self)

    def _sanitize(self) -> None:
        default = Settings()
        try:
            self.cps = min(max(float(self.cps), MIN_CPS), MAX_CPS)
        except (TypeError, ValueError):
            self.cps = default.cps
        if self.button not in BUTTONS:
            self.button = default.button
        if self.click_type not in CLICK_TYPES:
            self.click_type = default.click_type
        if self.position is not None:
            try:
                x, y = self.position
                self.position = [int(x), int(y)]
            except (TypeError, ValueError):
                self.position = None
        try:
            self.stop_after = int(self.stop_after) if self.stop_after else None
        except (TypeError, ValueError):
            self.stop_after = None
        if self.stop_after is not None and self.stop_after <= 0:
            self.stop_after = None
        try:
            self.start_delay = max(0.0, float(self.start_delay))
        except (TypeError, ValueError):
            self.start_delay = default.start_delay
        if not isinstance(self.hotkey, str) or not self.hotkey:
            self.hotkey = default.hotkey
        self.always_on_top = bool(self.always_on_top)

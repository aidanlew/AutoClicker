# PyInstaller build config. Run from the repo root: pyinstaller packaging/autoclicker.spec
#   macOS   -> dist/AutoClicker.app
#   Windows -> dist/AutoClicker.exe (single file)
#   Linux   -> dist/AutoClicker/ (folder; Qt WebEngine is too large to unpack on every launch)
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = os.environ.get("APP_VERSION", "0.0.0")

# pynput picks its OS backend at runtime, so PyInstaller can't see the import.
backend = {"darwin": "_darwin", "win32": "_win32"}.get(sys.platform, "_xorg")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "autoclicker" / "ui"), "autoclicker/ui")],
    hiddenimports=[f"pynput.keyboard.{backend}", f"pynput.mouse.{backend}"],
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="AutoClicker", console=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AutoClicker", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="AutoClicker")
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="AutoClicker.app",
            bundle_identifier="io.github.autoclicker",
            version=VERSION,
            info_plist={"NSHighResolutionCapable": True},
        )

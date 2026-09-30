"""PyInstaller entry script (PyInstaller needs a script, not `python -m`)."""
import multiprocessing

from autoclicker.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # lets the hotkey child process start in frozen builds
    main()

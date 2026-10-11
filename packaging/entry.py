"""PyInstaller entry script (PyInstaller needs a script, not `python -m`)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()  # lets the hotkey child process start in frozen builds
    from autoclicker.__main__ import main

    main()

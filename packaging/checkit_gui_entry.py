"""PyInstaller entry script for the checkit GUI.

PyInstaller runs this as a top-level script, so it must not use relative
imports. It delegates to checkit.gui:main().
"""

from checkit.gui import main

if __name__ == "__main__":
    raise SystemExit(main())

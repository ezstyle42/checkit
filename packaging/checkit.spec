# PyInstaller spec for building the self-contained checkit GUI application.
# Build with:  pyinstaller packaging/checkit.spec --distpath dist-app --workpath build-app
# Produces a single-file (or single-folder on macOS .app) executable per OS.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# SPECPATH is the directory containing this spec file (PyInstaller sets it
# from the absolute spec path), so the repo root is one level up.
root = Path(SPECPATH).resolve().parent
datas = [
    (str(root / "checkit" / "gui_frontend"), "checkit/gui_frontend"),
]
datas += collect_data_files("webview")

hiddenimports = [
    "webview",
    "webview.platforms",
    "webview.platforms.qt",
    "webview.platforms.gtk",
    "webview.platforms.cocoa",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "requests",
    "bs4",
]

a = Analysis(
    [str(root / "packaging" / "checkit_gui_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="checkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app: no console window on Windows/macOS
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# macOS: wrap in a .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="checkit.app",
        icon=None,
        bundle_identifier="com.ezstyle42.checkit",
        info_plist={
            "CFBundleName": "checkit",
            "CFBundleDisplayName": "checkit",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )

# PyInstaller spec for building the self-contained checkit GUI application.
# Build with:  pyinstaller packaging/checkit.spec --distpath dist-app --workpath build-app
#
# The app uses pywebview with a bundled PySide6 (Qt WebEngine) backend so the
# executables work on Linux, Windows and macOS without any system GUI
# libraries (no python3-gi, no pythonnet, no WebView2 runtime needed).
#
# PyInstaller's Qt hooks pull in the PySide6 plugins (platforms, webengine,
# imageformats, ...) automatically via hook-PySide6 / hook-qtpy.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# SPECPATH is the directory containing this spec file (PyInstaller sets it
# from the absolute spec path), so the repo root is one level up.
root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "checkit" / "gui_frontend"), "checkit/gui_frontend"),
]
datas += collect_data_files("webview")

# Qt plugins: PyInstaller's hook-PySide6 should collect these, but we add
# them explicitly to be safe — without the platform plugin (libqxcb on
# Linux, qwindows on Windows, libqcocoa on macOS) Qt cannot create a window,
# and without the WebEngine process/resources the webview is blank.
try:
    # Don't import PySide6 (it needs system glib at import time, which the
    # build machine may not have). Locate the package directory directly.
    import importlib.util as _ilu
    _spec = _ilu.find_spec("PySide6")
    qt_dir = Path(_spec.origin).resolve().parent
    qt_plugins = qt_dir / "Qt" / "plugins"
    qt_libexec = qt_dir / "Qt" / "libexec"
    qt_resources = qt_dir / "Qt" / "resources"
    qt_translations = qt_dir / "Qt" / "translations"
    if qt_plugins.is_dir():
        datas += [(str(qt_plugins), "PySide6/Qt/plugins")]
    if qt_libexec.is_dir():
        datas += [(str(qt_libexec), "PySide6/Qt/libexec")]
    if qt_resources.is_dir():
        datas += [(str(qt_resources), "PySide6/Qt/resources")]
    if qt_translations.is_dir():
        datas += [(str(qt_translations), "PySide6/Qt/translations")]
except Exception:
    pass  # let PyInstaller's own hooks handle it

hiddenimports = [
    "webview",
    "webview.platforms",
    "webview.platforms.qt",
    # qtpy backend selection
    "qtpy",
    "qtpy.QtCore",
    "qtpy.QtGui",
    "qtpy.QtWidgets",
    "qtpy.QtWebEngineWidgets",
    "qtpy.QtWebEngineCore",
    "qtpy.QtWebChannel",
    "qtpy.QtNetwork",
    # PySide6 modules pywebview touches directly
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtNetwork",
    # shiboken (PySide6 binding layer)
    "shiboken6",
    # app deps
    "requests",
    "bs4",
]
# All PySide6 submodules that may be imported dynamically (plugins, etc.)
hiddenimports += collect_submodules("PySide6")
hiddenimports += collect_submodules("shiboken6")

a = Analysis(
    [str(root / "packaging" / "checkit_gui_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # We ship Qt, not GTK/Cocoa/WinForms backends.
        "gi",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "pythonnet",
        "pytest",
        "matplotlib",
        "numpy",
        "pandas",
    ],
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
            "CFBundleShortVersionString": "0.3.1",
            "NSHighResolutionCapable": True,
            # Qt WebEngine needs these on macOS.
            "NSPrincipalClass": "NSApplication",
            "LSEnvironment": {
                "QT_MAC_WANTS_LAYER": "1",
            },
        },
    )

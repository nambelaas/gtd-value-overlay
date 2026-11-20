# -*- mode: python ; coding: utf-8 -*-
# Build:  python -m PyInstaller --noconfirm --clean packaging/gtd_value.spec
# Hasil:  Mac  -> dist/GTDValue.app      Windows -> dist/GTDValue/GTDValue.exe
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent                   # folder repo (spec ada di packaging/)
SRC = ROOT / "src" / "gtd_value"
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
VERSION = os.environ.get("GTD_VERSION", "0.1.0")    # CI mengisinya dari nama tag (v0.2.0 -> 0.2.0)
ENTRY = os.environ.get("GTD_ENTRY", "gtd_value.py")     # hook untuk tes build; biarkan default

# Yang ikut dibundel (read-only). Data user (values.json yang bisa berubah, log) ditulis ke folder user.
datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "data" / "values.json"), "data"),
    (str(ROOT / "data" / "arrow.png"), "data"),
    (str(ROOT / "data" / "glyphs"), "data/glyphs"),
]

hiddenimports = []
if IS_MAC:        # dipakai lewat import di dalam fungsi, jadi tidak terdeteksi otomatis
    hiddenimports += ["objc", "AppKit", "Foundation", "Quartz", "CoreFoundation"]
if IS_WIN:
    hiddenimports += ["win32gui", "win32con", "win32api", "pywintypes"]

a = Analysis(
    [str(SRC / ENTRY)],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "IPython", "pytest"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GTDValue",
    console=False,                                       # tanpa jendela terminal
    icon=str(ROOT / "packaging" / ("icon.ico" if IS_WIN else "icon.icns")),
)
coll = COLLECT(exe, a.binaries, a.datas, name="GTDValue")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="GTDValue.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier="com.gtdvalue.overlay",
        version=VERSION,
        info_plist={
            "CFBundleName": "GTD Value",
            "CFBundleDisplayName": "GTD Value Overlay",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,                         # tanpa ikon Dock; kontrol lewat ikon tray
            "NSHighResolutionCapable": True,
        },
    )

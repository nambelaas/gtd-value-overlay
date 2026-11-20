"""
Auto-start saat login.

Mode app (hasil PyInstaller):
- Mac    : LaunchAgent yang membuka GTDValue.app langsung (tanpa Terminal).
- Windows: key registry HKCU\\...\\Run yang menjalankan GTDValue.exe.

Mode dev (python src/gtd_value/gtd_value.py):
- Mac    : LaunchAgent -> start.command lewat aplikasi terminal (izin Screen Recording
           menempel ke aplikasi terminal itu, bukan ke binary python).
- Windows: registry Run -> pythonw (tanpa jendela console).

Pemakaian:
    autostart.is_enabled()
    autostart.enable(script)               # script = path gtd_value.py (diabaikan di mode app)
    autostart.disable()
    autostart.refresh_if_enabled(script)   # tulis ulang entri kalau app/venv dipindah
"""
import plistlib
import stat
import sys
from pathlib import Path

from paths import ROOT, RUN_DIR

APP_ID = "com.gtdvalue.overlay"
WIN_VALUE = "GTDValueOverlay"
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Mode dev di Mac: aplikasi terminal yang SUDAH diberi izin Screen Recording
MAC_TERMINAL_APP = "Terminal"


def _frozen():
    return bool(getattr(sys, "frozen", False))


def _plist_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


# ------------------------------------------------------------------ Mac
def _mac_app_bundle():
    """.../GTDValue.app/Contents/MacOS/GTDValue -> .../GTDValue.app (None kalau bukan .app)."""
    for p in Path(sys.executable).resolve().parents:
        if p.suffix == ".app":
            return p
    return None


def _mac_launcher(script):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    sh = RUN_DIR / "start.command"
    sh.write_text(
        f'#!/bin/bash\ncd "{ROOT}"\nexec "{sys.executable}" "{script}"\n',
        encoding="utf-8",
    )
    sh.chmod(sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return sh


def _enable_mac(script):
    bundle = _mac_app_bundle() if _frozen() else None
    if bundle is not None:
        args = ["/usr/bin/open", "-g", str(bundle)]                  # buka .app langsung
    else:
        if script is None:
            raise ValueError("Mode dev butuh path gtd_value.py")
        args = ["/usr/bin/open", "-a", MAC_TERMINAL_APP, str(_mac_launcher(script))]
    plist = _plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    with open(plist, "wb") as f:
        plistlib.dump({"Label": APP_ID, "ProgramArguments": args, "RunAtLoad": True}, f)


def _disable_mac():
    _plist_path().unlink(missing_ok=True)


def _is_enabled_mac():
    return _plist_path().exists()


# -------------------------------------------------------------- Windows
def _win_command(script):
    if _frozen():
        return f'"{sys.executable}"'                                  # GTDValue.exe
    if script is None:
        raise ValueError("Mode dev butuh path gtd_value.py")
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")                                 # tanpa console
    exe = pyw if pyw.exists() else py
    return f'"{exe}" "{script}"'


def _enable_win(script):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, WIN_VALUE, 0, winreg.REG_SZ, _win_command(script))


def _disable_win():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, WIN_VALUE)
    except FileNotFoundError:
        pass


def _is_enabled_win():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, WIN_VALUE)
        return True
    except FileNotFoundError:
        return False


# ------------------------------------------------------------ publik
def is_enabled():
    if sys.platform == "darwin":
        return _is_enabled_mac()
    if sys.platform == "win32":
        return _is_enabled_win()
    return False


def enable(script=None):
    script = Path(script).resolve() if script else None
    if sys.platform == "darwin":
        _enable_mac(script)
    elif sys.platform == "win32":
        _enable_win(script)
    else:
        raise NotImplementedError("Auto-start hanya didukung di Mac dan Windows")


def disable():
    if sys.platform == "darwin":
        _disable_mac()
    elif sys.platform == "win32":
        _disable_win()


def refresh_if_enabled(script=None):
    """Kalau auto-start aktif, tulis ulang entrinya agar menunjuk ke lokasi app/python yang sekarang
    (misalnya setelah .app dipindah ke /Applications atau virtualenv dibuat ulang)."""
    if is_enabled():
        enable(script)
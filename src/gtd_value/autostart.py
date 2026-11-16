"""
Auto-start saat login.

- Mac    : LaunchAgent (~/Library/LaunchAgents) yang membuka start.command lewat aplikasi terminal.
           Lewat terminal karena izin Screen Recording sudah menempel ke aplikasi itu,
           bukan ke binary python.
- Windows: key registry HKCU\\...\\Run, dijalankan dengan pythonw (tanpa jendela console).

Pemakaian:
    autostart.is_enabled()
    autostart.enable(Path("/path/ke/gtd_value.py"))
    autostart.disable()
"""
import plistlib
import stat
import sys
from pathlib import Path

from paths import ROOT, RUN_DIR

APP_ID = "com.gtdvalue.overlay"
WIN_VALUE = "GTDValueOverlay"
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Mac: aplikasi terminal yang SUDAH diberi izin Screen Recording
# (contoh: "Terminal" atau "iTerm"). Harus sama dengan yang kamu pakai menjalankan program.
MAC_TERMINAL_APP = "Terminal"


def _plist_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


# ------------------------------------------------------------------ Mac
def _mac_launcher(script):
    RUN_DIR.mkdir(exist_ok=True)
    sh = RUN_DIR / "start.command"
    sh.write_text(
        f'#!/bin/bash\ncd "{ROOT}"\nexec "{sys.executable}" "{script}"\n',
        encoding="utf-8",
    )
    sh.chmod(sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return sh


def _enable_mac(script):
    sh = _mac_launcher(script)
    plist = _plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    with open(plist, "wb") as f:
        plistlib.dump(
            {
                "Label": APP_ID,
                "ProgramArguments": ["/usr/bin/open", "-a", MAC_TERMINAL_APP, str(sh)],
                "RunAtLoad": True,
            },
            f,
        )


def _disable_mac():
    _plist_path().unlink(missing_ok=True)


def _is_enabled_mac():
    return _plist_path().exists()


# -------------------------------------------------------------- Windows
def _win_command(script):
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")                    # tanpa console
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


def enable(script):
    script = Path(script).resolve()
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
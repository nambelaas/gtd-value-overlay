"""
Lokasi folder.

- Mode dev  (python src/gtd_value/gtd_value.py): semua di folder repo, seperti biasa.
- Mode app  (hasil PyInstaller)                : bawaan app dibaca dari dalam bundle (read-only),
                                                 data user ditulis ke folder standar per OS:
    Mac     ~/Library/Application Support/GTDValue   (log: ~/Library/Logs/GTDValue)
    Windows %LOCALAPPDATA%\\GTDValue                  (log: %LOCALAPPDATA%\\GTDValue\\Logs)
"""
import shutil
import sys
from pathlib import Path

APP_NAME = "GTDValue"
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    from platformdirs import user_data_dir, user_log_dir

    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    ROOT = RESOURCE_DIR
    DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))
    LOG_DIR = Path(user_log_dir(APP_NAME, appauthor=False))
    DOCS_DIR = DATA_DIR / "debug"          # screenshot dan debug_qty.png
    RUN_DIR = DATA_DIR / "run"
else:
    ROOT = Path(__file__).resolve().parents[2]      # folder repo
    RESOURCE_DIR = ROOT
    DATA_DIR = ROOT / "data"
    LOG_DIR = ROOT / "logs"
    DOCS_DIR = ROOT / "docs"
    RUN_DIR = ROOT / ".run"

# Template ikon: bawaan (ikut dibundel) + tambahan/pembaruan milik user. Nama file sama -> milik user menang.
BUNDLED_TEMPLATES = RESOURCE_DIR / "templates"
USER_TEMPLATES = DATA_DIR / "templates"
TEMPLATE_DIRS = (BUNDLED_TEMPLATES, USER_TEMPLATES)
TEMPLATE_DIR = USER_TEMPLATES if FROZEN else BUNDLED_TEMPLATES   # tujuan simpan hasil tool crop

GLYPH_DIR = RESOURCE_DIR / "data" / "glyphs"      # template huruf badge qty (read-only, ikut dibundel)
UPDATES_DIR = ROOT / "updates"
VALUES_FILE = DATA_DIR / "values.json"
ARROW_FILE = DATA_DIR / "arrow.png"

# Salinan awal: dipakai kalau file di DATA_DIR belum ada (pertama kali app dijalankan)
_SEEDS = {
    VALUES_FILE: RESOURCE_DIR / "data" / "values.json",
    ARROW_FILE: RESOURCE_DIR / "data" / "arrow.png",
}


def ensure_user_data():
    """Buat folder data/log dan salin values.json + arrow.png awal kalau belum ada."""
    for d in (DATA_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for dst, src in _SEEDS.items():
        if not dst.exists() and src.exists() and src.resolve() != dst.resolve():
            shutil.copy(src, dst)
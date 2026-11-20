"""
GTD Value Overlay - Garden Tower Defense (Roblox)

Cara kerja:
1. Screenshot layar tiap SCAN_INTERVAL detik
2. Cocokkan ikon unit dengan template di folder templates/
3. Ambil value dari values.json
4. Tampilkan value di atas ikon lewat overlay transparan (click-through)

Program ini cuma BACA layar (tidak menyentuh client Roblox sama sekali).

Pemakaian:
  python gtd_value.py shot      -> ambil screenshot (delay 3 detik) jadi screenshot.png
  python gtd_value.py crop screenshot.png  -> crop ikon unit jadi template
  python gtd_value.py           -> jalankan overlay
"""
import json
import sys
import time
from pathlib import Path

import cv2
import mss
import numpy as np

import re

import os
from concurrent.futures import ThreadPoolExecutor
import logging
import signal
from logging.handlers import RotatingFileHandler

from paths import (TEMPLATE_DIR, TEMPLATE_DIRS, VALUES_FILE, ARROW_FILE,
                   DATA_DIR, DOCS_DIR, LOG_DIR, ensure_user_data)

from pathlib import Path

from single_instance import SingleInstance

import autostart

from qty_digits import read_qty

THRESHOLD = 0.75       # naikkan kalau salah deteksi, turunkan kalau banyak yang lolos
SCAN_INTERVAL = 1.0    # detik
SCALE = 0.5            # downscale biar cepat
SCALES = (1.0,)        # tambah (0.9, 1.0, 1.1) kalau ukuran UI berubah-ubah (lebih lambat)
CENTER_CROP = 0.7      # ambil bagian tengah ikon, biar badge "x2" & border tidak ganggu
CROP = (0.10, 0.50, 0.90, 0.92)  # (x0, y0, x1, y1) pecahan ikon: bagian bawah, bebas badge
DEBUG_QTY = False

ARROW_THRESHOLD = 0.70

ACCEPT_VIEW = False   # True : selisih = kiri - kanan (kamu terima unit kiri, kasih unit kanan)
                     # False: selisih = kanan - kiri (kebalikannya)

USE_GRAY = True     # False kalau ada unit yang tertukar atau salah deteksi
_POOL = ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1))

FRAME_DIFF = 3.0        # makin kecil makin sensitif terhadap perubahan layar
REDETECT_EVERY = 3.0    # paksa deteksi ulang tiap N detik sebagai pengaman

THRESHOLD_GRAY = 0.85

# Area jendela trade relatif terhadap window Roblox: (kiri, atas, kanan, bawah), 0..1
# Angka ini dihitung dari screenshot-mu. None = scan seluruh window
ROI = (0.10, 0.17, 0.87, 0.83)
log = logging.getLogger("gtd")


# ---------------------------------------------------------------- templates
def load_templates():
    """templates/Nama Unit.png ; variasi: 'Nama Unit__2.png', 'Nama Unit__shiny.png'"""
    files = {}
    for d in TEMPLATE_DIRS:                  # bawaan dulu, lalu milik user (menang kalau namanya sama)
        if d.is_dir():
            for p in d.glob("*.png"):
                files[p.name] = p
    result = []  # (name, full_w, full_h, [(img, scale, offset_x, offset_y), ...])
    for p in (files[k] for k in sorted(files)):
        name = p.stem.split("__")[0]
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is None:
            continue
        fh, fw = img.shape[:2]
        x0, y0 = int(fw * CROP[0]), int(fh * CROP[1])
        x1, y1 = int(fw * CROP[2]), int(fh * CROP[3])
        crop = img[y0:y1, x0:x1]
        variants = []
        for s in SCALES:
            t = cv2.resize(crop, None, fx=SCALE * s, fy=SCALE * s, interpolation=cv2.INTER_AREA)
            if t.shape[0] >= 8 and t.shape[1] >= 8:
                variants.append((t, s, x0, y0))
        result.append((name, fw, fh, variants))
    return result


def load_values():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not VALUES_FILE.exists():
        VALUES_FILE.write_text("{}", encoding="utf-8")
    data = json.loads(VALUES_FILE.read_text(encoding="utf-8"))
    out = {}
    for k, v in data.items():
        out[k] = str(v.get("value", "?")) if isinstance(v, dict) else str(v)
    return out


# ---------------------------------------------------------------- detection
def _match_one(small, name, fw, fh, variants):
    found = []
    for tpl, s, ox, oy in variants:
        if USE_GRAY:
            tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        th, tw = tpl.shape[:2]
        if small.shape[0] < th or small.shape[1] < tw:
            continue
        res = cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED)
        thr = THRESHOLD_GRAY if USE_GRAY else THRESHOLD
        for _ in range(20):
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx < thr:
                break
            x, y = loc
            found.append((mx, name, x - ox * SCALE * s, y - oy * SCALE * s,
                          fw * SCALE * s, fh * SCALE * s))
            x0, y0 = max(0, x - tw // 2), max(0, y - th // 2)
            res[y0: y + th // 2 + 1, x0: x + tw // 2 + 1] = -1
    return found


def detect(frame_bgr, templates):
    """Return list of (name, x, y, w, h) dalam pixel fisik."""
    small = cv2.resize(frame_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    if USE_GRAY:
        small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    found = []
    for part in _POOL.map(lambda t: _match_one(small, *t), templates):
        found += part

    found.sort(key=lambda f: -f[0])
    kept = []
    for sc, name, bx, by, fw, fh in found:
        if any(abs(bx - k[2]) < fw * 0.5 and abs(by - k[3]) < fh * 0.5 for k in kept):
            continue
        kept.append((sc, name, bx, by, fw, fh))
    return [(name, bx / SCALE, by / SCALE, fw / SCALE, fh / SCALE)
            for sc, name, bx, by, fw, fh in kept]


# ---------------------------------------------------------------- overlay
def parse_val(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_arrow():
    if not ARROW_FILE.exists():
        return None
    img = cv2.imread(str(ARROW_FILE), cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)


def detect_arrows(frame_bgr, tpl):
    """Return list (cx, cy) pusat panah dalam pixel fisik."""
    if tpl is None:
        return []
    small = cv2.resize(frame_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    th, tw = tpl.shape[:2]
    if small.shape[0] < th or small.shape[1] < tw:
        return []
    res = cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED)
    out = []
    for _ in range(30):
        _, mx, _, (x, y) = cv2.minMaxLoc(res)
        if mx < ARROW_THRESHOLD:
            break
        out.append(((x + tw / 2) / SCALE, (y + th / 2) / SCALE))
        res[max(0, y - th): y + th, max(0, x - tw): x + tw] = -1
    return out


def side_total(group, values):
    total, unknown = 0.0, 0
    for name, qty, *_ in group:
        v = parse_val(values.get(name))
        if v is None:
            unknown += 1          # unit terdeteksi tapi value belum ada di values.json
        else:
            total += v * qty
    return round(total, 2), unknown


def build_trades(units, arrows, values):
    """units: [(name, qty, x, y, w, h)] pixel fisik.
    Return [(kiri_total, kiri_unknown, kanan_total, kanan_unknown, anchor_x, anchor_y)]"""
    trades = []
    for ax, ay in arrows:
        row = [u for u in units if abs(u[3] + u[5] / 2 - ay) < u[5] * 0.5]   # satu baris dengan panah
        left = [u for u in row if u[2] + u[4] / 2 < ax]
        right = [u for u in row if u[2] + u[4] / 2 > ax]
        lt, lu = side_total(left, values)
        rt, ru = side_total(right, values)
        anchor_x = max((u[2] + u[4] for u in right), default=ax + 30)
        trades.append((lt, lu, rt, ru, anchor_x, ay))
    return trades


def fmt_total(total, unknown):
    s = f"{total:g}"
    return f"{s} +?" if unknown else s

def run_overlay():
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt

    setup_logging()
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)      # Ctrl+C di terminal tetap bisa menghentikan app
    app.setQuitOnLastWindowClosed(False)              # app hidup walau tidak ada jendela biasa

    single = SingleInstance()                         # jangan dihapus: harus hidup selama app jalan
    if single.already_running():
        log.warning("Instance lain sudah berjalan. Keluar.")
        return

    templates = load_templates()
    values = load_values()
    arrow_tpl = load_arrow()
    if not templates:
        log.warning("Tidak ada template di: %s", ", ".join(str(d) for d in TEMPLATE_DIRS))
        return
    if arrow_tpl is None:
        log.info("arrow.png belum ada -> total per sisi nonaktif")

    screen = app.primaryScreen()
    geo = screen.geometry()
    qt_ratio = screen.devicePixelRatio() if sys.platform == "win32" else 1.0
    
    class Worker(QtCore.QThread):
        result = QtCore.pyqtSignal(list, list)

        def __init__(self):
            super().__init__()
            self.running, self.paused = True, False
            self.perm_ok = True
            self.last, self.ref, self.cached, self.t_det = [], None, [], 0.0

        def scan(self, sct):
            region = get_roblox_region()
            items, pills = [], []
            if not region:
                self.ref = None
                return items, pills
            if not screen_capture_allowed():
                if self.perm_ok:
                    log.warning("Izin Screen Recording belum aktif untuk app ini. Scan dijeda sampai diizinkan.")
                    self.perm_ok = False
                self.ref = None
                return [], []
            if not self.perm_ok:
                log.info("Izin Screen Recording aktif, scan dilanjutkan.")
                self.perm_ok = True
            frame = np.array(sct.grab(region))[:, :, :3]
            scale = frame.shape[1] / region["width"]
            k = scale * qt_ratio

            def conv(px, py):
                return ((region["left"] + px / scale) / qt_ratio - geo.x(),
                        (region["top"] + py / scale) / qt_ratio - geo.y())

            sub, ox, oy = crop_roi(frame)
            g = cv2.cvtColor(cv2.resize(sub, (192, 108), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY)
            changed = (self.ref is None or self.ref.shape != g.shape
                       or cv2.absdiff(g, self.ref).mean() > FRAME_DIFF
                       or time.time() - self.t_det > REDETECT_EVERY)
            self.ref = g
            if changed:
                self.cached = [(n, x + ox, y + oy, w, h) for n, x, y, w, h in detect(sub, templates)]
                self.t_det = time.time()

            current, units = [], []
            for name, x, y, w, h in self.cached:
                raw = read_qty(frame, x, y, w, h)
                prev = next((p for p in self.last
                             if p[0] == name and abs(p[1] - x) < w * 0.3
                             and abs(p[2] - y) < h * 0.3), None)
                qty = raw if (prev and prev[3] == raw) else 1
                current.append((name, x, y, raw))
                units.append((name, qty, x, y, w, h))
                lx, ly = conv(x, y)
                items.append((name, qty, lx, ly, w / k, h / k))
            self.last = current

            for lt, lu, rt, ru, ax, ay in build_trades(units, detect_arrows(frame, arrow_tpl), values):
                px, py = conv(ax, ay)
                diff = (lt - rt) if ACCEPT_VIEW else (rt - lt)
                pills.append((fmt_total(lt, lu), fmt_total(rt, ru),
                              round(diff, 2), bool(lu or ru), px, py))
            return items, pills

        def run(self):
            with mss.mss() as sct:
                while self.running:
                    t0 = time.time()
                    if self.paused:
                        time.sleep(0.2)
                        continue
                    try:
                        items, pills = self.scan(sct)
                    except Exception:
                        log.exception("Scan gagal, mencoba lagi")
                        items, pills = [], []
                        time.sleep(1)
                    if self.paused:                      # dijeda saat scan berjalan: jangan gambar hasilnya
                        continue
                    self.result.emit(items, pills)
                    time.sleep(max(0.05, SCAN_INTERVAL - (time.time() - t0)))
    
    class Overlay(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                                | Qt.Tool | Qt.WindowTransparentForInput)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setGeometry(geo)
            self.items, self.pills = [], []
            self.font = QtGui.QFont("Arial", 11, QtGui.QFont.Bold)
            self.small = QtGui.QFont("Arial", 10, QtGui.QFont.Bold)
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)

        def update_items(self, items, pills):
            self.items, self.pills = items, pills
            self.update()

        def paintEvent(self, _):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)

            # label value per unit
            p.setFont(self.font)
            fm = QtGui.QFontMetrics(self.font)
            for name, qty, x, y, w, h in self.items:
                text = label_text(values.get(name, "?"), qty)
                tw, th = fm.horizontalAdvance(text) + 12, fm.height() + 2
                rect = QtCore.QRectF(x + (w - tw) / 2, y - th - 1, tw, th)
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(0, 0, 0, 200))
                p.drawRoundedRect(rect, 5, 5)
                p.setPen(QtGui.QColor(255, 215, 0))
                p.drawText(rect, Qt.AlignCenter, text)

            # total per sisi trade + selisih (di kanan unit terakhir tiap baris)
            p.setFont(self.small)
            fm2 = QtGui.QFontMetrics(self.small)
            lh = fm2.height()
            for left, right, diff, partial, x, y in self.pills:
                if partial:                               # ada unit tanpa value -> selisih tidak valid
                    dtxt, dcol = "Selisih: ?", QtGui.QColor(170, 170, 170)
                elif diff > 0:
                    dtxt, dcol = f"Selisih: {diff:+g}", QtGui.QColor(110, 230, 110)
                elif diff < 0:
                    dtxt, dcol = f"Selisih: {diff:+g}", QtGui.QColor(255, 100, 100)
                else:
                    dtxt, dcol = "Selisih: 0", QtGui.QColor(200, 200, 200)
                lines = [
                    (f"Punya: {left}", QtGui.QColor(130, 205, 255)),
                    (f"Cari: {right}", QtGui.QColor(255, 215, 0)),
                    (dtxt, dcol),
                ]
                pw = max(fm2.horizontalAdvance(t) for t, _ in lines) + 16
                ph = lh * len(lines) + 10
                px = min(x + 10, self.width() - pw - 4)
                rect = QtCore.QRectF(px, y - ph / 2, pw, ph)
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(0, 0, 0, 215))
                p.drawRoundedRect(rect, 6, 6)
                for i, (t, c) in enumerate(lines):
                    p.setPen(c)
                    p.drawText(QtCore.QRectF(px + 8, rect.top() + 5 + i * lh, pw - 16, lh),
                               Qt.AlignLeft | Qt.AlignVCenter, t)

        def mac_always_visible(self):
            """Biar overlay tetap tampil di atas Roblox, termasuk saat fullscreen."""
            if sys.platform != "darwin":
                return
            import objc
            from AppKit import NSApp
            view = objc.objc_object(c_void_p=int(self.winId()))
            win = view.window()
            win.setHidesOnDeactivate_(False)
            win.setLevel_(25)                                  # di atas window biasa
            win.setCollectionBehavior_((1 << 0) | (1 << 6) | (1 << 8))  # semua Space, ikut fullscreen app lain
            NSApp.setActivationPolicy_(1)                      # tidak muncul di Dock/app switcher
    
    ov = Overlay()
    ov.show()
    ov.mac_always_visible()
    screen_capture_allowed(request=True)     # dialog izin muncul sekali saja kalau belum diberi
    worker = Worker()
    worker.result.connect(ov.update_items)
    worker.start()

    # ---- hot-reload values.json (cek tiap 1 detik, dict yang sama dipakai overlay dan worker)
    state = {"mtime": VALUES_FILE.stat().st_mtime if VALUES_FILE.exists() else 0}

    def reload_values(force=False):
        try:
            m = VALUES_FILE.stat().st_mtime
        except OSError:
            return
        if not force and m == state["mtime"]:
            return
        try:
            new = load_values()
        except Exception:
            log.exception("Gagal membaca values.json, dicoba lagi")   # mtime tidak diperbarui -> coba lagi
            return
        values.update(new)
        for key in set(values) - set(new):                           # hapus unit yang sudah tidak ada
            del values[key]
        state["mtime"] = m
        log.info("values.json dimuat ulang (%d unit)", len(values))
        ov.update()

    reload_timer = QtCore.QTimer()
    reload_timer.timeout.connect(reload_values)
    reload_timer.start(1000)

    # ---- tray icon
    def make_icon():
        pm = QtGui.QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 215, 0))
        p.drawEllipse(4, 4, 56, 56)
        p.setPen(QtGui.QColor(30, 30, 30))
        p.setFont(QtGui.QFont("Arial", 30, QtGui.QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, "V")
        p.end()
        return QtGui.QIcon(pm)

    def open_dir(path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def toggle_pause(checked):
        worker.paused = checked
        act_pause.setText("Lanjutkan" if checked else "Jeda")
        if checked:
            ov.update_items([], [])
        log.info("Overlay %s", "dijeda" if checked else "dilanjutkan")
    
    def toggle_autostart(checked):
        try:
            if checked:
                autostart.enable(Path(__file__).resolve())
            else:
                autostart.disable()
            log.info("Auto-start %s", "aktif" if checked else "nonaktif")
        except Exception:
            log.exception("Gagal mengubah auto-start")
            act_auto.blockSignals(True)
            act_auto.setChecked(autostart.is_enabled())      # kembalikan sesuai kondisi sebenarnya
            act_auto.blockSignals(False)
            tray.showMessage("GTD Value", "Gagal mengubah auto-start. Cek log.")

    def quit_app():
        worker.running = False
        worker.wait(3000)
        tray.hide()
        app.quit()

    menu = QtWidgets.QMenu()
    act_pause = menu.addAction("Jeda")
    act_pause.setCheckable(True)
    act_pause.toggled.connect(toggle_pause)
    menu.addAction("Muat ulang values").triggered.connect(lambda: reload_values(force=True))
    menu.addAction("Buka folder data").triggered.connect(lambda: open_dir(DATA_DIR))
    menu.addAction("Buka folder log").triggered.connect(lambda: open_dir(LOG_DIR))
    act_auto = menu.addAction("Jalan otomatis saat login")
    act_auto.setCheckable(True)
    act_auto.setChecked(autostart.is_enabled())
    act_auto.toggled.connect(toggle_autostart)
    menu.addSeparator()
    menu.addAction("Keluar").triggered.connect(quit_app)

    tray = QtWidgets.QSystemTrayIcon(make_icon(), app)
    if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        tray.setToolTip("GTD Value Overlay")
        tray.setContextMenu(menu)
        tray.show()
    else:
        log.warning("System tray tidak tersedia. Berhenti lewat Ctrl+C di terminal.")

    try:
        autostart.refresh_if_enabled(Path(__file__).resolve())
    except Exception:
        log.exception("Gagal memperbarui entri auto-start")
    
    log.info("Jalan. %d template, %d value.", len(templates), len(values))
    sys.exit(app.exec_())


# ---------------------------------------------------------------- tools
def get_roblox_region():
    """Return {left, top, width, height} window Roblox, atau None kalau tidak ketemu."""
    if sys.platform == "darwin":  # Mac: pip install pyobjc-framework-Quartz
        from Quartz import (CGWindowListCopyWindowInfo,
                            kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
        for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
            owner = (w.get("kCGWindowOwnerName") or "").lower()
            if "roblox" in owner and w.get("kCGWindowLayer") == 0:
                b = w["kCGWindowBounds"]
                return {"left": int(b["X"]), "top": int(b["Y"]),
                        "width": int(b["Width"]), "height": int(b["Height"])}

    elif sys.platform == "win32":  # Windows: pip install pywin32
        import ctypes
        import win32gui
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # biar koordinat tidak meleset di layar scaling
        hwnd = win32gui.FindWindow(None, "Roblox")
        if hwnd:
            left, top = win32gui.ClientToScreen(hwnd, (0, 0))  # area dalam, tanpa title bar
            _, _, w, h = win32gui.GetClientRect(hwnd)
            return {"left": left, "top": top, "width": w, "height": h}
    return None

def screen_capture_allowed(request=False):
    """Mac: sudah diberi izin Screen Recording? request=True memunculkan dialog izin satu kali."""
    if sys.platform != "darwin":
        return True
    try:
        from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
        if CGPreflightScreenCaptureAccess():
            return True
        if request:
            CGRequestScreenCaptureAccess()
        return False
    except Exception:
        return True          # API tidak tersedia: jangan memblokir scan

def take_shot():
    print("Pindah ke game, screenshot dalam 3 detik...")
    time.sleep(3)
    region = get_roblox_region()
    if region is None:
        print("Window Roblox tidak ketemu, pakai fullscreen.")
    with mss.mss() as sct:
        img = np.array(sct.grab(region or sct.monitors[1]))[:, :, :3]

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(DOCS_DIR / "screenshot.png"), img)
    print("Tersimpan: docs/screenshot.png")

def crop_tool(path):
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(path)
    if img is None:
        print("File tidak ditemukan")
        return
    while True:
        print("Drag kotak di sekitar 1 ikon unit (pas di border), ENTER untuk konfirmasi, ESC/kosong untuk selesai")
        x, y, w, h = cv2.selectROI("crop", img, showCrosshair=False)
        if w == 0 or h == 0:
            break
        name = input("Nama unit (sama persis dengan key di values.json): ").strip()
        if not name:
            continue
        if name.lower() == "arrow":
            ARROW_FILE.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(ARROW_FILE), img[y: y + h, x: x + w])
            print("Disimpan:", ARROW_FILE)       # sebelumnya tertulis docs/arrow.png padahal lokasinya data/
            continue
        out = TEMPLATE_DIR / f"{name}.png"
        n = 2
        while out.exists():
            out = TEMPLATE_DIR / f"{name}__{n}.png"
            n += 1
        cv2.imwrite(str(out), img[y: y + h, x: x + w])
        print("Disimpan:", out.name)
    cv2.destroyAllWindows()

def label_text(base, qty):
    """'2.25', 6 -> '2.25 ×6 = 13.5'. Value non-angka tetap ditampilkan apa adanya."""
    if qty <= 1:
        return base
    try:
        total = float(base.replace(",", "")) * qty
        return f"{total:g}"
    except ValueError:
        return f"{base} × {qty}"

def crop_roi(frame):
    if ROI is None:
        return frame, 0, 0
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = int(W * ROI[0]), int(H * ROI[1]), int(W * ROI[2]), int(H * ROI[3])
    return frame[y0:y1, x0:x1], x0, y0

def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [RotatingFileHandler(LOG_DIR / "gtd_value.log", maxBytes=1_000_000,
                                    backupCount=3, encoding="utf-8")]
    if sys.stderr:                                   # tidak ada saat dijalankan tanpa console
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)
    sys.excepthook = lambda *a: log.critical("Error tak tertangani", exc_info=a)

if __name__ == "__main__":
    ensure_user_data()
    if len(sys.argv) > 1 and sys.argv[1] == "shot":
        take_shot()
    elif len(sys.argv) > 2 and sys.argv[1] == "crop":
        crop_tool(sys.argv[2])
    else:
        run_overlay()
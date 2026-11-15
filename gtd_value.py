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

try:
    import pytesseract
except ImportError:
    pytesseract = None

BASE = Path(__file__).parent
TEMPLATE_DIR = BASE / "templates"
VALUES_FILE = BASE / "values.json"

THRESHOLD = 0.75       # naikkan kalau salah deteksi, turunkan kalau banyak yang lolos
SCAN_INTERVAL = 1.0    # detik
SCALE = 0.5            # downscale biar cepat
SCALES = (1.0,)        # tambah (0.9, 1.0, 1.1) kalau ukuran UI berubah-ubah (lebih lambat)
CENTER_CROP = 0.7      # ambil bagian tengah ikon, biar badge "x2" & border tidak ganggu
CROP = (0.10, 0.50, 0.90, 0.92)  # (x0, y0, x1, y1) pecahan ikon: bagian bawah, bebas badge
DEBUG_QTY = False

ARROW_FILE = BASE / "arrow.png"
ARROW_THRESHOLD = 0.70

ACCEPT_VIEW = False   # True : selisih = kiri - kanan (kamu terima unit kiri, kasih unit kanan)
                     # False: selisih = kanan - kiri (kebalikannya)


# ---------------------------------------------------------------- templates
def load_templates():
    """templates/Nama Unit.png ; variasi: 'Nama Unit__2.png', 'Nama Unit__shiny.png'"""
    TEMPLATE_DIR.mkdir(exist_ok=True)
    result = []  # (name, full_w, full_h, [(img, scale, offset_x, offset_y), ...])
    for p in sorted(TEMPLATE_DIR.glob("*.png")):
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
    if not VALUES_FILE.exists():
        VALUES_FILE.write_text("{}", encoding="utf-8")
    data = json.loads(VALUES_FILE.read_text(encoding="utf-8"))
    out = {}
    for k, v in data.items():
        out[k] = str(v.get("value", "?")) if isinstance(v, dict) else str(v)
    return out


# ---------------------------------------------------------------- detection
def detect(frame_bgr, templates):
    """Return list of (name, x, y, w, h) dalam pixel fisik layar."""
    small = cv2.resize(frame_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    found = []  # (score, name, bx, by, fw, fh) di koordinat small, bx/by = pojok kiri atas ikon penuh
    for name, fw, fh, variants in templates:
        for tpl, s, ox, oy in variants:
            th, tw = tpl.shape[:2]
            if small.shape[0] < th or small.shape[1] < tw:
                continue
            res = cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED)
            for _ in range(20):
                _, mx, _, loc = cv2.minMaxLoc(res)
                if mx < THRESHOLD:
                    break
                x, y = loc
                found.append((mx, name, x - ox * SCALE * s, y - oy * SCALE * s,
                              fw * SCALE * s, fh * SCALE * s))
                x0, y0 = max(0, x - tw // 2), max(0, y - th // 2)
                res[y0: y + th // 2 + 1, x0: x + tw // 2 + 1] = -1

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

    templates = load_templates()
    values = load_values()
    arrow_tpl = load_arrow()
    if not templates:
        print("Folder templates/ masih kosong. Jalankan: python gtd_value.py shot  lalu  crop")
        return
    if arrow_tpl is None:
        print("[INFO] arrow.png belum ada -> total per sisi nonaktif (crop panah dengan nama 'arrow')")

    app = QtWidgets.QApplication(sys.argv)
    screen = app.primaryScreen()
    geo = screen.geometry()
    qt_ratio = screen.devicePixelRatio() if sys.platform == "win32" else 1.0

    class Worker(QtCore.QThread):
        result = QtCore.pyqtSignal(list, list)

        def run(self):
            last = []
            with mss.mss() as sct:
                while True:
                    t0 = time.time()
                    region = get_roblox_region()
                    items, pills = [], []
                    if region:
                        frame = np.array(sct.grab(region))[:, :, :3]
                        scale = frame.shape[1] / region["width"]
                        k = scale * qt_ratio                      # pixel fisik -> koordinat overlay

                        def conv(px, py):
                            return ((region["left"] + px / scale) / qt_ratio - geo.x(),
                                    (region["top"] + py / scale) / qt_ratio - geo.y())

                        current, units = [], []
                        for name, x, y, w, h in detect(frame, templates):
                            raw = read_qty(frame, x, y, w, h)
                            prev = next((p for p in last
                                         if p[0] == name and abs(p[1] - x) < w * 0.3
                                         and abs(p[2] - y) < h * 0.3), None)
                            qty = raw if (prev and prev[3] == raw) else 1
                            current.append((name, x, y, raw))
                            units.append((name, qty, x, y, w, h))
                            lx, ly = conv(x, y)
                            items.append((name, qty, lx, ly, w / k, h / k))
                        last = current

                        for lt, lu, rt, ru, ax, ay in build_trades(
                                units, detect_arrows(frame, arrow_tpl), values):
                            px, py = conv(ax, ay)
                            diff = (lt - rt) if ACCEPT_VIEW else (rt - lt)
                            pills.append((fmt_total(lt, lu), fmt_total(rt, ru),
                                          round(diff, 2), bool(lu or ru), px, py))
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
    
    worker = Worker()
    worker.result.connect(ov.update_items)
    worker.start()
    print(f"Jalan. {len(templates)} template, {len(values)} value. Ctrl+C untuk berhenti.")
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

def take_shot():
    print("Pindah ke game, screenshot dalam 3 detik...")
    time.sleep(3)
    region = get_roblox_region()
    if region is None:
        print("Window Roblox tidak ketemu, pakai fullscreen.")
    with mss.mss() as sct:
        img = np.array(sct.grab(region or sct.monitors[1]))[:, :, :3]
    cv2.imwrite(str(BASE / "screenshot.png"), img)
    print("Tersimpan: screenshot.png")


def crop_tool(path):
    TEMPLATE_DIR.mkdir(exist_ok=True)
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
            cv2.imwrite(str(ARROW_FILE), img[y: y + h, x: x + w])
            print("Disimpan: arrow.png")
            continue
        out = TEMPLATE_DIR / f"{name}.png"
        n = 2
        while out.exists():
            out = TEMPLATE_DIR / f"{name}__{n}.png"
            n += 1
        cv2.imwrite(str(out), img[y: y + h, x: x + w])
        print("Disimpan:", out.name)
    cv2.destroyAllWindows()

def read_qty(frame, x, y, w, h):
    """Baca badge 'xN' di kanan atas ikon. Tidak ada badge / ragu -> 1."""
    if pytesseract is None:
        return 1
    H, W = frame.shape[:2]
    x0, x1 = max(0, int(x + w * 0.45)), min(W, int(x + w * 0.97))
    y0, y1 = max(0, int(y + h * 0.06)), min(H, int(y + h * 0.55))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return 1

    roi = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    white = (roi.min(axis=2) > 200).astype(np.uint8)       # dilonggarkan: tepi huruf ikut terambil
    dark = gray < 80

    # Simpan hanya komponen putih yang dikelilingi outline hitam
    kk = max(3, int(w / 36) // 2 * 2 + 1)
    kernel = np.ones((kk, kk), np.uint8)
    min_area = max(6, int((w / 40) ** 2))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    keep = np.zeros_like(white)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        comp = (labels == i).astype(np.uint8)
        ring = cv2.dilate(comp, kernel) > comp
        if ring.any() and dark[ring].mean() > 0.4:
            keep |= comp
    if keep.sum() < min_area * 2:
        return 1

    # Crop rapat ke teks
    ys, xs = np.where(keep > 0)
    keep = keep[max(0, ys.min() - 2): ys.max() + 3, max(0, xs.min() - 2): xs.max() + 3]

    # Haluskan: upscale -> blur -> threshold ulang (menutup celah, bikin tepi mulus)
    big = cv2.resize(keep * 255, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), 2.2)
    _, big = cv2.threshold(big, 100, 255, cv2.THRESH_BINARY)   # threshold rendah = sedikit lebih tebal
    big = cv2.morphologyEx(big, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    img = 255 - big                                          # teks hitam, background putih
    img = cv2.copyMakeBorder(img, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    if DEBUG_QTY:
        cv2.imwrite("debug_qty.png", img)

    txt = pytesseract.image_to_string(
        img, config="--psm 7 -c tessedit_char_whitelist=xX0123456789").strip()
    if DEBUG_QTY:
        print(f"[qty] OCR mentah: {txt!r}")
    m = re.fullmatch(r"[xX]?\s*(\d{1,3})", txt)
    if m and 2 <= int(m.group(1)) <= 999:
        return int(m.group(1))
    return 1

def label_text(base, qty):
    """'2.25', 6 -> '2.25 ×6 = 13.5'. Value non-angka tetap ditampilkan apa adanya."""
    if qty <= 1:
        return base
    try:
        total = float(base.replace(",", "")) * qty
        return f"{total:g}"
    except ValueError:
        return f"{base} × {qty}"

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "shot":
        take_shot()
    elif len(sys.argv) > 2 and sys.argv[1] == "crop":
        crop_tool(sys.argv[2])
    else:
        run_overlay()
"""
Baca badge qty 'xN' di pojok ikon unit TANPA OCR (tidak perlu Tesseract).

Cara kerja:
1. Ambil piksel putih murni yang dikelilingi outline hitam (teks badge)
2. Pisahkan jadi huruf (komponen terhubung), pecah kalau dua huruf menempel
3. Cocokkan bentuk tiap huruf dengan template di data/glyphs/ (skala-independen)
4. Susun: 'x' lalu digit-digit di kanannya, sejajar dan berdekatan

Template: <karakter>__real.png (dipotong dari screenshot game) dan <karakter>__font.png
(dirender dari font Comic Neue Bold, untuk karakter yang belum punya contoh nyata).
Kalau ada karakter yang sering salah, tambahkan file <karakter>__real.png baru.
"""
import cv2
import numpy as np

from paths import GLYPH_DIR

NORM_SIZE = (20, 28)
MIN_SCORE = 0.55      # kemiripan minimum agar huruf dianggap dikenali
MIN_MARGIN = 0.05     # selisih minimum dengan kelas terbaik kedua
SURE_SCORE = 0.70     # di atas ini komponen utuh langsung diterima (tidak dicoba dipecah)
WHITE_MIN = 170       # ambang "putih" huruf; 200 terlalu ketat di resolusi kecil (tepi huruf terpotong)

_glyphs = None


def _norm(mask):
    m = cv2.resize(mask.astype(np.float32), NORM_SIZE, interpolation=cv2.INTER_AREA)
    return m / max(float(m.max()), 1e-6)


def _iou(a, b):
    return float(np.minimum(a, b).sum() / max(np.maximum(a, b).sum(), 1e-6))


def load_glyphs():
    global _glyphs
    if _glyphs is None:
        g = {}
        for p in sorted(GLYPH_DIR.glob("*.png")):
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                g.setdefault(p.stem.split("__")[0], []).append(_norm(img > 127))
        _glyphs = g
    return _glyphs


def classify(mask):
    """Return (karakter atau None, skor)."""
    glyphs = load_glyphs()
    a = _norm(mask)
    ranked = sorted(((max(_iou(a, t) for t in tpls), ch) for ch, tpls in glyphs.items()), reverse=True)
    if not ranked:
        return None, 0.0
    s1, c1 = ranked[0]
    s2 = ranked[1][0] if len(ranked) > 1 else 0.0
    if s1 < MIN_SCORE or s1 - s2 < MIN_MARGIN:
        return None, s1
    return c1, s1


def _tight(x, y, mask):
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return None
    return (x + int(xs.min()), y + int(ys.min()), int(xs.max() - xs.min() + 1),
            int(ys.max() - ys.min() + 1), mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1])


def _split_at_valley(x, y, mask):
    """Pecah komponen lebar di kolom paling tipis (dekat tengah). Return dua bagian atau None."""
    bw = mask.shape[1]
    if bw < 8:
        return None
    lo, hi = int(bw * 0.3), int(bw * 0.7) + 1
    cut = lo + int(np.argmin(mask.sum(axis=0)[lo:hi]))
    parts = [_tight(x, y, mask[:, :cut]), _tight(x + cut, y, mask[:, cut:])]
    return parts if all(parts) else None


def _components(roi, w):
    """Komponen putih berkerangka hitam yang ukurannya masuk akal untuk huruf badge."""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    white = (roi.min(axis=2) > WHITE_MIN).astype(np.uint8)   # putih (kuning/terang berwarna tidak lolos)
    dark = gray < 80
    kk = max(3, int(w / 36) // 2 * 2 + 1)
    kernel = np.ones((kk, kk), np.uint8)
    min_area = max(6, int((w / 40) ** 2))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < min_area or not (0.10 * w <= bh <= 0.45 * w):
            continue
        comp = (labels == i).astype(np.uint8)
        ring = cv2.dilate(comp, kernel) > comp
        if ring.any() and dark[ring].mean() > 0.4:
            out.append((x, y, bw, bh, comp[y:y + bh, x:x + bw]))
    return out


def _recognize(roi, w):
    """Daftar huruf terbaca: (kiri, kanan, bawah, tinggi, karakter), urut dari kiri."""
    found = []

    def add(x, y, bw, bh, mask, depth=0):
        ch, sc = classify(mask)
        if ch is not None and (sc >= SURE_SCORE or bw <= 0.88 * bh):
            found.append((x, x + bw, y + bh, bh, ch))
            return
        if bw > 0.88 * bh and depth < 2:                  # kemungkinan dua huruf menempel
            parts = _split_at_valley(x, y, mask)
            if parts:
                for px, py, pw, ph, pm in parts:
                    add(px, py, pw, ph, pm, depth + 1)
                return
        if ch is not None:
            found.append((x, x + bw, y + bh, bh, ch))

    for comp in _components(roi, w):
        add(*comp)
    return sorted(found)


def read_qty(frame, x, y, w, h):
    """Baca badge 'xN' di kanan atas ikon (x, y, w, h = kotak ikon dalam pixel frame).
    Tidak ada badge / ragu -> 1."""
    H, W = frame.shape[:2]
    x0, x1 = max(0, int(x + w * 0.30)), min(W, int(x + w * 1.02))
    y0, y1 = max(0, int(y - h * 0.02)), min(H, int(y + h * 0.62))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return 1
    glyphs = _recognize(frame[y0:y1, x0:x1], w)

    for i, gx in enumerate(glyphs):
        if gx[4] != "x":
            continue
        digits, cur = "", gx
        for nxt in glyphs[i + 1:]:
            if nxt[4] == "x" or not nxt[4].isdigit():
                continue
            aligned = abs(nxt[2] - gx[2]) <= 0.30 * nxt[3]       # alas huruf sejajar dengan 'x'
            close = 0 <= nxt[0] - cur[1] <= 0.7 * nxt[3]         # berdekatan, tidak ada celah besar
            if aligned and close:
                digits += nxt[4]
                cur = nxt
                if len(digits) == 3:
                    break
        if digits and 2 <= int(digits) <= 999:
            return int(digits)
    return 1
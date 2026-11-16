"""
Update values.json dari post update value di Discord.

Pakai:
  python update_values.py update_2026-11-13.txt      # dari file (tanggal dibaca dari nama file)
  python update_values.py updates/*.txt              # banyak file sekaligus, urutan bebas
  python update_values.py clip                       # dari clipboard (pip install pyperclip), tanggal = hari ini
  python update_values.py                            # paste di terminal, akhiri Ctrl+D (Mac) / Ctrl+Z lalu Enter (Windows)
  python update_values.py file.txt --date 2026-11-13 # paksa tanggal kalau nama file tidak memuat tanggal

Format tanggal di nama file: 2026-11-13, 20261113, atau 13-11-2026 (hari-bulan-tahun).

Aturan anti-menimpa: tiap unit menyimpan tanggal update terakhirnya ("updated").
Post yang tanggalnya LEBIH LAMA dari tanggal itu dilewati untuk unit tersebut.
Unit yang belum punya tanggal (data lama/manual) tetap ditimpa.
Backup otomatis ke values.json.bak sebelum menulis.
"""
import glob
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from paths import VALUES_FILE

STORE_IN_K = True   # True : simpan dalam ribuan (30.45k -> 30.45 ; 865 -> 0.865)
                    # False: simpan angka penuh   (30.45k -> 30450 ; 865 -> 865)

FIELDS = ("value:", "demand:", "status:")
ARROW = re.compile(r"-->|→|->|=>")
NUM = re.compile(r"(\d[\d,]*\.?\d*)\s*([kKmM]?)")
DEMAND = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*10")


def last_part(line):
    """'Value: 28k+ --> 30.45k+' -> '30.45k+' (ambil sisi kanan panah = nilai terbaru)."""
    return ARROW.split(line.split(":", 1)[1])[-1].strip()


def parse_number(text):
    """'30.45k+' -> 30450.0 ; '865+' -> 865.0 ; None kalau tidak ada angka."""
    m = NUM.search(text)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    mult = {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return n * mult


def parse_post(text):
    lines = [l.strip() for l in text.replace("```", "\n").splitlines()]
    lines = [l for l in lines if l]
    entries, tier, cur = [], None, None
    for i, line in enumerate(lines):
        low = line.lower()
        if low.startswith("value:"):
            if cur is not None:
                v = parse_number(last_part(line))
                if v is not None:
                    cur["value"] = v
        elif low.startswith("demand:"):
            if cur is not None:
                m = DEMAND.search(last_part(line))
                if m:
                    cur["demand"] = float(m.group(1))
        elif low.startswith("status:"):
            if cur is not None:
                cur["status"] = last_part(line)
        else:
            nxt = lines[i + 1].lower() if i + 1 < len(lines) else ""
            if nxt.startswith(FIELDS):                         # baris nama unit (Value/Demand/Status berikutnya)
                cur = {"name": line}
                if tier:
                    cur["tier"] = tier
                entries.append(cur)
            elif re.fullmatch(r"[A-Z][A-Z ]+", line):          # header kategori: EXCLUSIVE, GODLY, dst
                tier, cur = line.title(), None
    return [e for e in entries if any(k in e for k in ("value", "demand", "status"))]


def tidy(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def load_values():
    if not VALUES_FILE.exists():
        return {}
    data = json.loads(VALUES_FILE.read_text(encoding="utf-8"))
    return {k: (dict(v) if isinstance(v, dict) else {"value": v}) for k, v in data.items()}


ISO_DATE = re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
DMY_DATE = re.compile(r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})(?!\d)")


def date_from_name(name):
    """'update_2026-11-13.txt' / '20261113.txt' / '13-11-2026.txt' -> date, atau None."""
    m = ISO_DATE.search(name)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = DMY_DATE.search(name)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            pass
    return None


def apply_post(data, lower, entries, post_date):
    iso = post_date.isoformat()
    updated, added, skipped, partial = [], [], [], []
    for e in entries:
        key = lower.get(e["name"].lower(), e["name"])
        old = data.get(key)
        old_date = old.get("updated") if old else None
        if old_date and iso < old_date:                       # data yang ada lebih baru -> lewati
            skipped.append((key, old_date))
            continue
        rec = dict(old) if old else {}
        if "value" in e:
            new_val = tidy(round(e["value"] / 1000 if STORE_IN_K else e["value"], 4))
            rec["value"] = new_val
        if "demand" in e:
            rec["demand"] = tidy(e["demand"])
        if "status" in e:
            rec["status"] = e["status"]
        if "tier" in e:
            rec["tier"] = e["tier"]
        rec["updated"] = iso
        data[key] = rec
        lower[key.lower()] = key
        if "value" not in e:                                  # post hanya mengubah demand/status
            partial.append((key, old is None))
        elif old is None:
            added.append((key, new_val))
        else:
            updated.append((key, old.get("value"), new_val))
    return updated, added, skipped, partial


def main():
    args = sys.argv[1:]
    forced = None
    if "--date" in args:
        i = args.index("--date")
        try:
            forced = datetime.strptime(args[i + 1], "%Y-%m-%d").date()
        except (IndexError, ValueError):
            print("Format --date harus YYYY-MM-DD, contoh: --date 2026-11-13")
            return
        del args[i: i + 2]

    sources = []   # (label, text, tanggal)
    if args == ["clip"]:
        import pyperclip
        sources.append(("clipboard", pyperclip.paste(), forced or date.today()))
    elif args:
        files = []
        for a in args:
            files += sorted(glob.glob(a)) or [a]             # glob manual, supaya jalan di Windows juga
        for f in files:
            d = forced or date_from_name(Path(f).name)
            if d is None:
                print(f"Tanggal tidak terbaca dari nama file '{Path(f).name}'. "
                      f"Tambahkan --date YYYY-MM-DD atau beri nama file memuat tanggal.")
                return
            sources.append((Path(f).name, Path(f).read_text(encoding="utf-8"), d))
    else:
        print("Paste post update, akhiri dengan Ctrl+D (Mac) / Ctrl+Z lalu Enter (Windows):")
        sources.append(("input terminal", sys.stdin.read(), forced or date.today()))

    sources.sort(key=lambda s: s[2])                          # proses dari yang paling lama
    data = load_values()
    lower = {k.lower(): k for k in data}
    total_changed = 0
    all_added = []

    for label, text, d in sources:
        entries = parse_post(text)
        print(f"\n== {label} (tanggal {d.isoformat()}) ==")
        if not entries:
            print("  Tidak ada unit yang terbaca. Pastikan formatnya 'Nama' lalu 'Value: ... --> ...'.")
            continue
        updated, added, skipped, partial = apply_post(data, lower, entries, d)
        total_changed += len(updated) + len(added) + len(partial)
        all_added += [n for n, _ in added]
        print(f"  {len(entries)} unit terbaca -> {len(updated)} diperbarui, "
              f"{len(added)} baru, {len(partial)} hanya demand/status, {len(skipped)} dilewati (data lebih baru)")
        for name, old, new in updated:
            print(f"    {name}: {old} -> {new}")
        for name, is_new in partial:
            print(f"    (demand/status saja) {name}" + (" - BARU, belum punya value" if is_new else ""))
        for name, od in skipped:
            print(f"    (lewati) {name}: sudah ada data tanggal {od}")

    if total_changed:
        if VALUES_FILE.exists():
            shutil.copy(VALUES_FILE, VALUES_FILE.with_suffix(".json.bak"))
        VALUES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nvalues.json disimpan ({total_changed} perubahan).")
    else:
        print("\nTidak ada perubahan.")
    if all_added:
        print("Unit BARU (cek ejaan nama, harus sama persis dengan nama template): " + ", ".join(all_added))


if __name__ == "__main__":
    main()
#!/bin/bash
# Build GTDValue.app. Jalankan dari mana saja:  bash packaging/build_mac.sh
# Opsional: SIGN_IDENTITY="nama sertifikat code signing di Keychain" (supaya izin Screen Recording
# tidak hilang tiap build ulang). Tanpa itu dipakai tanda tangan ad-hoc.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -r requirements.txt pyinstaller
rm -rf build dist
python3 -m PyInstaller --noconfirm --clean packaging/gtd_value.spec

codesign --force --deep --sign "${SIGN_IDENTITY:--}" dist/GTDValue.app
codesign --verify --deep --strict dist/GTDValue.app && echo "Tanda tangan OK"
echo "Selesai: dist/GTDValue.app"
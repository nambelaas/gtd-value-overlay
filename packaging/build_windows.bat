@echo off
rem Build GTDValue.exe. Jalankan:  packaging\build_windows.bat
cd /d "%~dp0\.."
python -m pip install -r requirements.txt pyinstaller || exit /b 1
rmdir /s /q build dist 2>nul
python -m PyInstaller --noconfirm --clean packaging\gtd_value.spec || exit /b 1
echo Selesai: dist\GTDValue\GTDValue.exe
; Installer Windows untuk GTD Value Overlay (dibangun otomatis oleh GitHub Actions)
; Build manual: ISCC.exe /DMyAppVersion=0.1.0 packaging\installer.iss   (setelah PyInstaller selesai)
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{4A06ED1D-FAC5-41E4-A6E5-C0E2F5E7BBF3}
AppName=GTD Value Overlay
AppVersion={#MyAppVersion}
AppPublisher=GTD Value Overlay
DefaultDirName={autopf}\GTDValue
DefaultGroupName=GTD Value Overlay
PrivilegesRequired=lowest
OutputDir=..\installer
OutputBaseFilename=GTDValue-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\GTDValue.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Buat pintasan di Desktop"; Flags: unchecked

[Files]
Source: "..\dist\GTDValue\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\GTD Value Overlay"; Filename: "{app}\GTDValue.exe"
Name: "{autodesktop}\GTD Value Overlay"; Filename: "{app}\GTDValue.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GTDValue.exe"; Description: "Jalankan GTD Value Overlay"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; hapus entri "jalan otomatis saat login" kalau ada (data user di %LOCALAPPDATA%\GTDValue tidak dihapus)
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v GTDValueOverlay /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"

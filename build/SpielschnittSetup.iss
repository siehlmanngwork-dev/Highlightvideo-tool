; Inno-Setup-Skript fuer SpielschnittSetup.exe
; Wird von build\build.ps1 aufgerufen (Version und Pfade kommen als /D-Parameter).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef DistDir
  #define DistDir "dist\Spielschnitt"
#endif
#ifndef OutDir
  #define OutDir "out"
#endif

[Setup]
AppId={{6B0E3C1A-5D2F-4E8B-9A57-3C1D2E4F5A60}
AppName=Spielschnitt
AppVersion={#AppVersion}
AppVerName=Spielschnitt {#AppVersion}
AppPublisher=Spielschnitt
DefaultDirName={localappdata}\Programs\Spielschnitt
DefaultGroupName=Spielschnitt
DisableProgramGroupPage=yes
; Ohne Administratorrechte installierbar (nur fuer den aktuellen Benutzer)
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=SpielschnittSetup
SetupIconFile=..\app\spielschnitt.ico
UninstallDisplayIcon={app}\Spielschnitt.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Laufende App vor Update/Deinstallation schliessen
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Symbol auf dem Desktop anlegen"; GroupDescription: "Zusätzliche Symbole:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Spielschnitt"; Filename: "{app}\Spielschnitt.exe"
Name: "{group}\Spielschnitt deinstallieren"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Spielschnitt"; Filename: "{app}\Spielschnitt.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Spielschnitt.exe"; Description: "Spielschnitt jetzt starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

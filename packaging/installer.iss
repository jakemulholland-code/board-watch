; Inno Setup script for Board Watch.
; Compile from the repo root with:
;   iscc packaging\installer.iss /DMyAppVersion=1.2.3
; (see packaging\build.ps1 for the full release build, this included)
;
; PrivilegesRequired=lowest + a per-user install dir means teammates can just
; run the installer and click through it — no admin rights or IT ticket needed.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Board Watch"
#define MyAppExeName "BoardWatch.exe"
#define MyAppPublisher "Paramount Digital"
#define MyAppURL "https://github.com/jakemulholland-code/board-watch"

[Setup]
; Fixed AppId — do not change between releases. Inno uses it to recognise
; "this is an upgrade of the same app" so a newer installer replaces the old
; version cleanly instead of installing side-by-side.
AppId={{56E3A0A1-D63B-4CA0-8DFE-163B58CAF5BF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist_installer
OutputBaseFilename=BoardWatchSetup-{#MyAppVersion}
SetupIconFile=..\paramount-boardwatch.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The .exe already has everything bundled in (HTML, icon, example configs) —
; user data (config.json, .env, data/*.json) lives outside the install dir in
; %LOCALAPPDATA%\Board Watch, so re-running this installer over an older
; version never touches it.
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

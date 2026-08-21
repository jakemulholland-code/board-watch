# Building the Board Watch installer

Turns the app into `BoardWatchSetup-<version>.exe` — a normal Windows installer,
no Python required on the machine it's installed on.

## One-time setup (build machine only)
```
pip install pyinstaller
winget install JRSoftware.InnoSetup
```
These are build tools only — they don't ship with the app and aren't needed by
anyone just running the installer.

## Build
1. Bump [`VERSION`](../VERSION) at the repo root (plain `MAJOR.MINOR.PATCH`, no `v` prefix).
2. Run:
   ```
   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
   ```
   This runs PyInstaller (`boardwatch.spec` → `dist\BoardWatch.exe`), then Inno Setup
   (`installer.iss` → `dist_installer\BoardWatchSetup-<version>.exe`).
3. On GitHub, create a release tagged `v<version>` and attach
   `BoardWatchSetup-<version>.exe` as an asset. That's the *only* step that makes the
   app's in-app **Update available** link light up for people on an older version —
   it just reads the latest release off `GET /repos/<repo>/releases/latest` and compares
   tags, it doesn't poll anything else.

`dist/`, `dist_installer/`, and PyInstaller's `build/` are all gitignored — rebuild
locally, don't commit them.

## How the pieces fit together
- **`boardwatch.spec`** bundles `server.py` (which imports `monday_sync.py`) plus the
  static assets (`index.html`, `management.html`, `favicon.svg`, `VERSION`,
  `config.example.json`, `data/*.example.json`) into one onefile .exe.
- **[`../paths.py`](../paths.py)** is what makes onefile packaging safe: it splits
  "bundled read-only assets" (`BASE_DIR`, PyInstaller's temp extraction dir when
  frozen) from "the user's own data" (`APP_DATA_DIR`, `%LOCALAPPDATA%\Board Watch`
  when frozen). Without that split, a onefile .exe's temp extraction dir gets wiped
  and recreated every launch — anything written there (token, boards, synced tasks)
  would vanish the moment the app closed.
- **`installer.iss`** wraps `dist\BoardWatch.exe` in a per-user installer
  (`PrivilegesRequired=lowest`, installs to `%LOCALAPPDATA%\Programs\Board Watch`) so
  teammates can install it without admin rights or an IT ticket. The `AppId` GUID in
  it is fixed on purpose — don't change it — so a newer installer upgrades the same
  install in place instead of creating a second copy.

## Testing a build locally
```
dist_installer\BoardWatchSetup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```
installs without any dialogs; the matching `unins000.exe` in the install dir
(`%LOCALAPPDATA%\Programs\Board Watch`) uninstalls the same way.

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Board Watch. Build from the repo root with:
#   pyinstaller packaging/boardwatch.spec
# (see packaging/build.ps1 for the full release build, installer included)
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

datas = [
    (os.path.join(ROOT, "index.html"), "."),
    (os.path.join(ROOT, "management.html"), "."),
    (os.path.join(ROOT, "favicon.svg"), "."),
    (os.path.join(ROOT, "config.example.json"), "."),
    (os.path.join(ROOT, "VERSION"), "."),
    (os.path.join(ROOT, "data", "boards.example.json"), "data"),
    (os.path.join(ROOT, "data", "teams.example.json"), "data"),
]

a = Analysis(
    [os.path.join(ROOT, "server.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BoardWatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # keep the console window — it's the only sign the local
                     # server is alive, and doubles as a troubleshooting log
    icon=os.path.join(ROOT, "paramount-boardwatch.ico"),
)

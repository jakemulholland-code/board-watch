"""
Where Board Watch's files live — split so the packaged .exe can update itself
in place without touching (or losing) anything the user has configured.

- BASE_DIR: bundled, read-only assets (index.html, management.html,
  favicon.svg, the .example.json templates). Running from source, this is the
  repo root. Running as a PyInstaller onefile .exe, this is the temporary
  extraction dir (sys._MEIPASS) — it's wiped and recreated from the .exe on
  every launch, so nothing that needs to persist can live here.
- APP_DATA_DIR: the user's own data (config.json, .env, data/*.json).
  Running from source, this is the repo root too (unchanged behaviour).
  Running as a packaged .exe, this is %LOCALAPPDATA%\\Board Watch, which
  survives reinstalling a newer version of the .exe over the old one.
"""

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))


def _base_dir():
    if FROZEN:
        return sys._MEIPASS  # noqa: SLF001 - the documented PyInstaller extraction dir
    return os.path.dirname(os.path.abspath(__file__))


def _app_data_dir():
    if not FROZEN:
        return _base_dir()
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(root, "Board Watch")
    os.makedirs(d, exist_ok=True)
    return d


BASE_DIR = _base_dir()
APP_DATA_DIR = _app_data_dir()


def ensure_first_run_files():
    """Seed config.json and data/ from the bundled .example.json templates the
    first time the packaged app runs somewhere new. No-op once those files
    already exist, and a no-op entirely when running from source (start.bat
    already does the config.json copy there, and data/*.json are created by
    the app itself as boards get added)."""
    if not FROZEN:
        return
    os.makedirs(os.path.join(APP_DATA_DIR, "data"), exist_ok=True)
    config_path = os.path.join(APP_DATA_DIR, "config.json")
    example_path = os.path.join(BASE_DIR, "config.example.json")
    if not os.path.exists(config_path) and os.path.exists(example_path):
        with open(example_path, "rb") as src, open(config_path, "wb") as dst:
            dst.write(src.read())

#!/usr/bin/env python3
"""
Local server for the Monday dashboard.

Run:  python server.py
Then open http://localhost:8765 in your browser.
The Management (capacity) view is a separate page at /management.

Serves the static dashboard and exposes a tiny JSON API so the browser can:
  - list tracked boards / people / tasks       GET  /api/data
  - discover a board's columns (for mapping)   GET  /api/board-columns?id=<board_id>
  - save a board + its column mapping          POST /api/save-board
  - remove a board                             POST /api/remove-board
  - export tracked boards + mappings           GET  /api/export-boards
  - import tracked boards + mappings           POST /api/import-boards
  - poll progress of an in-flight sync         GET  /api/sync-progress
  - trigger a fresh pull from Monday           POST /api/sync
  - post an update (comment) back to Monday     POST /api/post-update
  - list/save/remove teams (boards + people)   GET/POST /api/teams, /api/save-team, /api/remove-team

Everything stays on the machine. No data leaves except the calls to Monday's API.
"""

import json
import os
import datetime
import uuid
import webbrowser
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import monday_sync as ms
from paths import BASE_DIR, FROZEN, ensure_first_run_files

HERE = BASE_DIR   # bundled read-only assets: index.html, management.html, favicon.svg, VERSION
PORT = int(os.environ.get("PORT", 8765))

GITHUB_REPO = "jakemulholland-code/board-watch"


def get_version():
    path = os.path.join(HERE, "VERSION")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0-dev"


def _version_tuple(v):
    # "1.4.2" -> (1,4,2); tolerates a leading "v" and trailing junk like "-beta"
    v = v.lstrip("vV").split("-")[0]
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) + (0, 0, 0)


def check_for_update():
    """Ask GitHub for the latest release and compare it to our own VERSION
    file. Only ever reads the public releases API — never downloads or runs
    anything itself, so the actual update stays a deliberate, visible action
    the user takes by clicking the link this returns."""
    current = get_version()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "board-watch-update-check"},
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    latest = (release.get("tag_name") or "").strip()
    assets = release.get("assets") or []
    installer = next((a for a in assets if a.get("name", "").lower().endswith(".exe")), None)
    newer = _version_tuple(latest) > _version_tuple(current)
    return {
        "current": current,
        "latest": latest,
        "newer": newer,
        "release_url": release.get("html_url"),
        "download_url": (installer or {}).get("browser_download_url"),
        "notes": release.get("body") or "",
    }


def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter console
        pass

    def _send(self, code, obj=None, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if obj is not None:
            body = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
            self.wfile.write(body)

    # ---- static + data files ----
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html")

        if route in ("/management", "/management.html"):
            return self._serve_file("management.html", "text/html")

        if route == "/favicon.svg":
            return self._serve_file("favicon.svg", "image/svg+xml")

        if route == "/api/data":
            data = ms.load_json(ms.TASKS_FILE, {"tasks": [], "boards": [], "people": []})
            boards_store = ms.load_json(ms.BOARDS_FILE, {"boards": {}})
            data["tracked"] = list(boards_store["boards"].values())
            return self._send(200, data)

        if route == "/api/token-status":
            return self._send(200, {"has_token": bool(ms.get_token())})

        if route == "/api/version":
            return self._send(200, {"version": get_version()})

        if route == "/api/check-update":
            try:
                return self._send(200, check_for_update())
            except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
                return self._send(200, {"error": f"Could not check for updates: {e}"})

        if route == "/api/sync-progress":
            # Polled every ~700ms during a sync — if a transient read hiccup
            # somehow survives load_json's own retries, just say "unknown"
            # rather than erroring out; the next poll a moment later is fine.
            try:
                return self._send(200, ms.read_progress())
            except Exception:  # noqa: BLE001
                return self._send(200, {"status": "unknown"})

        if route == "/api/teams":
            return self._send(200, ms.load_json(ms.TEAMS_FILE, {"teams": {}}))

        if route == "/api/export-boards":
            # Hand back the raw tracked-boards store (ids, columns, mapping,
            # mapping_mode, done_labels per board) so it can be saved as a
            # file and dropped back in on a fresh clone / after an update —
            # data/boards.json is gitignored, so this is the supported way to
            # carry board setups across machines without redoing every mapping.
            store = ms.load_json(ms.BOARDS_FILE, {"boards": {}})
            return self._send(200, store)

        if route == "/api/board-columns":
            qs = parse_qs(parsed.query)
            bid = (qs.get("id") or [""])[0]
            if not bid:
                return self._send(400, {"error": "missing id"})
            try:
                cfg = ms.load_config()
                board = ms.fetch_board_columns(cfg, bid)
                # "suggested_mapping" is the Default preset guessed from column
                # titles (see monday_sync.guess_mapping). The browser applies it
                # when the Default toggle is on; the user can switch to Custom
                # any time, and whatever they end up with is what gets saved.
                board["suggested_mapping"] = ms.guess_mapping(board["columns"])
                return self._send(200, board)
            except SystemExit as e:
                return self._send(400, {"error": str(e)})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/save-token":
                body = read_body(self)
                token = (body.get("token") or "").strip()
                if not token:
                    return self._send(400, {"error": "No token provided."})
                # validate against Monday before saving
                cfg = ms.load_settings()
                cfg["api_key"] = token
                q = "query { me { name email } }"
                try:
                    data = ms.monday_query(cfg, q)
                except SystemExit as e:
                    return self._send(400, {"error": "That token was rejected by Monday. " + str(e)})
                ms.save_token(token)
                who = (data.get("me") or {}).get("name", "")
                return self._send(200, {"ok": True, "user": who})

            if route == "/api/save-board":
                body = read_body(self)
                store = ms.load_json(ms.BOARDS_FILE, {"boards": {}})
                bid = str(body["id"])
                store["boards"][bid] = {
                    "id": bid,
                    "name": body.get("name", bid),
                    "columns": body.get("columns", []),
                    "mapping": body.get("mapping", {}),
                    "mapping_mode": body.get("mapping_mode") or "custom",
                    "done_labels": [d.strip().lower() for d in body.get("done_labels", ["done"]) if d.strip()],
                }
                ms.save_json(ms.BOARDS_FILE, store)
                return self._send(200, {"ok": True})

            if route == "/api/import-boards":
                body = read_body(self)
                incoming = body.get("boards") if isinstance(body, dict) else None
                if not isinstance(incoming, dict):
                    return self._send(400, {"error": "That doesn't look like a boards export file (expected a top-level \"boards\" object)."})
                store = ms.load_json(ms.BOARDS_FILE, {"boards": {}})
                added, updated, skipped = 0, 0, 0
                for bid, b in incoming.items():
                    if not isinstance(b, dict) or "mapping" not in b or "columns" not in b:
                        skipped += 1
                        continue
                    bid = str(b.get("id") or bid)
                    b["id"] = bid
                    if bid in store["boards"]:
                        updated += 1
                    else:
                        added += 1
                    store["boards"][bid] = b
                ms.save_json(ms.BOARDS_FILE, store)
                return self._send(200, {"ok": True, "added": added, "updated": updated, "skipped": skipped})

            if route == "/api/remove-board":
                body = read_body(self)
                # cmd_remove drops the board from boards.json AND purges its
                # cached tasks from tasks.json, so deleted data disappears now.
                cfg = ms.load_config(require_token=False)
                ms.cmd_remove(cfg, str(body["id"]))
                return self._send(200, {"ok": True})

            if route == "/api/save-team":
                body = read_body(self)
                name = (body.get("name") or "").strip()
                if not name:
                    return self._send(400, {"error": "Team name is required."})
                store = ms.load_json(ms.TEAMS_FILE, {"teams": {}})
                tid = str(body.get("id") or uuid.uuid4().hex[:8])
                store["teams"][tid] = {
                    "id": tid,
                    "name": name,
                    "board_ids": [str(b) for b in (body.get("board_ids") or [])],
                    "people": [p for p in (body.get("people") or []) if p],
                }
                ms.save_json(ms.TEAMS_FILE, store)
                return self._send(200, {"ok": True, "id": tid})

            if route == "/api/remove-team":
                body = read_body(self)
                store = ms.load_json(ms.TEAMS_FILE, {"teams": {}})
                tid = str(body.get("id") or "")
                if store["teams"].pop(tid, None) is None:
                    return self._send(404, {"error": "Team not found."})
                ms.save_json(ms.TEAMS_FILE, store)
                return self._send(200, {"ok": True})

            if route == "/api/sync":
                cfg = ms.load_config()
                ms.cmd_sync(cfg)
                return self._send(200, {"ok": True, "synced_at": datetime.datetime.now().isoformat(timespec="seconds")})

            if route == "/api/post-update":
                body = read_body(self)
                item_id = str(body.get("item_id") or "").strip()
                text = (body.get("text") or "").strip()
                mentions = body.get("mentions") or []   # [{id, name}]
                if not item_id:
                    return self._send(400, {"error": "Missing item id."})
                if not text:
                    return self._send(400, {"error": "The update text is empty."})
                cfg = ms.load_config()
                ok, err = ms.post_update(cfg, item_id, text, mentions=mentions)
                if not ok:
                    return self._send(400, {"error": err or "Could not post the update."})
                # err may carry a soft warning even when ok is True
                return self._send(200, {"ok": True, "warning": err})

        except SystemExit as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            return self._send(500, {"error": repr(e)})

        return self._send(404, {"error": "not found"})

    def _serve_file(self, name, ctype):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            return self._send(404, b"not found", ctype="text/plain")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype=ctype)


if __name__ == "__main__":
    ensure_first_run_files()
    url = f"http://localhost:{PORT}"
    print(f"Monday dashboard running at {url}  (v{get_version()})")
    print("Press Ctrl+C to stop.")
    if FROZEN:
        # Running from source, start.bat/start.sh already open the browser
        # themselves — only the packaged .exe needs to do it here.
        import threading
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass

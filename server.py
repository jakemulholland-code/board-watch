#!/usr/bin/env python3
"""
Local server for the Monday dashboard.

Run:  python server.py
Then open http://localhost:8765 in your browser.

Serves the static dashboard and exposes a tiny JSON API so the browser can:
  - list tracked boards / people / tasks       GET  /api/data
  - discover a board's columns (for mapping)   GET  /api/board-columns?id=<board_id>
  - save a board + its column mapping          POST /api/save-board
  - remove a board                             POST /api/remove-board
  - trigger a fresh pull from Monday           POST /api/sync
  - post an update (comment) back to Monday     POST /api/post-update

Everything stays on the machine. No data leaves except the calls to Monday's API.
"""

import json
import os
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import monday_sync as ms

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765


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

        if route == "/favicon.svg":
            return self._serve_file("favicon.svg", "image/svg+xml")

        if route == "/api/data":
            data = ms.load_json(ms.TASKS_FILE, {"tasks": [], "boards": [], "people": []})
            boards_store = ms.load_json(ms.BOARDS_FILE, {"boards": {}})
            data["tracked"] = list(boards_store["boards"].values())
            return self._send(200, data)

        if route == "/api/token-status":
            return self._send(200, {"has_token": bool(ms.get_token())})

        if route == "/api/board-columns":
            qs = parse_qs(parsed.query)
            bid = (qs.get("id") or [""])[0]
            if not bid:
                return self._send(400, {"error": "missing id"})
            try:
                cfg = ms.load_config()
                board = ms.fetch_board_columns(cfg, bid)
                # No auto-guessing — the user maps every column themselves.
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
                    "done_labels": [d.strip().lower() for d in body.get("done_labels", ["done"]) if d.strip()],
                }
                ms.save_json(ms.BOARDS_FILE, store)
                return self._send(200, {"ok": True})

            if route == "/api/remove-board":
                body = read_body(self)
                # cmd_remove drops the board from boards.json AND purges its
                # cached tasks from tasks.json, so deleted data disappears now.
                cfg = ms.load_config(require_token=False)
                ms.cmd_remove(cfg, str(body["id"]))
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
    print(f"Monday dashboard running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

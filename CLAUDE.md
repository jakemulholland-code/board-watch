# Board Watch — project notes for Claude Code

A self-contained local dashboard that tracks tasks across multiple monday.com
boards, flags overdue / due-soon items, shows comments, and can post updates
back to Monday (tagging the assignee). Python standard library only — no pip
dependencies.

## Architecture

- **`monday_sync.py`** — the engine + CLI. Talks to the Monday GraphQL API,
  applies per-board column mappings, computes each task's state
  (overdue / warning / ok / done / none), applies sync-time prefilters, and
  writes `data/tasks.json`. Also holds the write path (`post_update`).
- **`server.py`** — a tiny `http.server` on port 8765 that serves `index.html`
  and exposes a small JSON API the browser calls (`/api/data`, `/api/sync`,
  `/api/board-columns`, `/api/save-board`, `/api/remove-board`,
  `/api/save-token`, `/api/post-update`).
- **`index.html`** — the whole dashboard: HTML + CSS + JS inline in one file.
  Reads `data/tasks.json` via the server and renders a filterable table, a task
  detail modal, and the "post an update" compose box. Paramount Digital brand
  styling (Fraunces + Sora fonts, teal/amber/red palette).
- **`paths.py`** — resolves where files live, and is the reason the app can be
  packaged into a onefile .exe at all. `BASE_DIR` (bundled read-only assets:
  HTML, favicon, VERSION, the `.example.json` templates) is the repo root when
  running from source, or PyInstaller's temp extraction dir when frozen.
  `APP_DATA_DIR` (the user's own config/token/boards/tasks) is the repo root
  when running from source (unchanged), or `%LOCALAPPDATA%\Board Watch` when
  frozen — kept separate so reinstalling a newer .exe never touches it.
  `monday_sync.py` and `server.py` both import from here instead of deriving
  their own `HERE`.
- **`packaging/`** — turns the app into `BoardWatchSetup-<version>.exe` (a
  PyInstaller onefile build wrapped in an Inno Setup installer). See
  `packaging/README.md`. These are build-time tools only (`pip install
  pyinstaller`, Inno Setup) — they don't become runtime dependencies of the app.

Data flow: `monday_sync.py` (pull) → `data/tasks.json` → `server.py` → browser.

## Files that are personal / not committed (see .gitignore)

- `.env` — the Monday API token (`MONDAY_API_TOKEN`), chmod 600.
- `config.json` — non-secret settings; created from `config.example.json`.
- `data/boards.json` — the user's tracked boards + column mappings.
- `data/tasks.json` — the synced task cache.
- `data/teams.json` — named groups of boards + people, used as a dashboard filter.

`config.example.json`, `data/boards.example.json`, and `data/teams.example.json`
document the shapes.

## Running / testing

- Start locally: `python server.py` (or `start.bat` / `start.sh`), then open
  <http://localhost:8765>.
- There is **no live Monday account in the dev sandbox** — tests mock the API by
  monkeypatching `monday_sync.fetch_board_items` / `fetch_board_columns` /
  `monday_query` / `monday_mutation`, or by seeding `data/tasks.json` directly.
- UI is tested by running the server in-process and driving it with Playwright.
  (Background servers get killed between shell calls in the sandbox, so tests
  spin up `ThreadingHTTPServer` in-process.)
- Always `python -m py_compile monday_sync.py server.py` after edits.

## Monday API gotchas (learned the hard way — don't regress these)

- **Pin a current API version.** `API_VERSION` in `monday_sync.py` (also
  overridable via `config.json` → `api_version`). Versions before 2025-04 are
  deprecated and get silently routed to a maintenance version, which breaks
  things unpredictably. Currently `2025-07`.
- **Tagging in `create_update` uses `mentions_list`**, and the schema input type
  is `UpdateMention`. Do NOT declare it as a typed GraphQL variable with a
  guessed type name — build the literal inline exactly as Monday documents:
  `mentions_list: [{id: 123, type: User}]` (`type: User` is an unquoted enum).
  Keep only `item_id` / `body` as typed variables.
- **Do NOT put `@name` in the update body when using `mentions_list`** — Monday
  renders the mention itself. (The fallback plain-comment path is the only place
  names go in the body as text.)
- To tag someone you need their Monday **user ID**, not their name. IDs come from
  the people column's `value` JSON (`personsAndTeams`), captured during sync as
  `people_ids` on each task.
- `updates(limit:)` caps at 100 per page (we request 50).
- Error responses are GraphQL-standard: `errors: [{message, extensions:{code}}]`,
  and every response now carries `extensions.request_id` — handled already.

## Conventions

- Standard library only — do not add pip dependencies.
- Keep `index.html` a single self-contained file (CSS + JS inline).
- When changing the shape of a task, update `process_item` AND anything that
  reads it in `index.html`, and keep `empty_tasks()` consistent.
- After backend field changes, the user must run "Refresh from Monday" once to
  rewrite `data/tasks.json` in the new shape.
- Preserve the existing DOM class names in `index.html` — the JS depends on them.
- The `/api/check-update` endpoint only ever reads GitHub's public releases API
  and hands back a URL — it never downloads or runs anything itself. Keep it
  that way; the actual update stays a deliberate click by the user.
- Bump `VERSION` (plain `MAJOR.MINOR.PATCH`, no `v` prefix) before cutting a
  release build — see `packaging/README.md`.

## Branch / test workflow

`main` is the stable baseline. Do experimental work on a branch
(`git checkout -b feature/xyz`), test, then merge back. Nothing here needs a
build step — it's plain Python + a static HTML file.

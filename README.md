# Board Watch — a self-contained Monday.com dashboard

Tracks tasks across multiple monday.com boards in one filterable dashboard, and
flags anything overdue or about to be overdue. Boards that don't share a layout
are handled by mapping each board's columns once and saving that mapping to JSON.

Everything runs locally. The only outbound calls are to Monday's own API.

## What's in the box

| File | Purpose |
|------|---------|
| `monday_sync.py` | Pulls boards via the Monday API, applies your column mappings, computes overdue/warning/done state, writes `data/tasks.json`. Works from the CLI on its own. |
| `server.py` | Tiny local web server. Serves the dashboard and lets the browser add/remove/map boards and trigger a refresh. |
| `index.html` | The dashboard: summary counts, filters (person, board, urgency, due date, search), sortable table, and modals for managing/mapping boards. |
| `data/boards.json` | Your tracked boards + saved column mappings. |
| `data/tasks.json` | The synced task data the dashboard reads (created on first sync). |
| `config.json` | Your API token and settings (you create this). |

## Setup

**Requirements:** Python 3.8+ only. There are **no packages to install** — Board Watch
uses the standard library. (`pip install -r requirements.txt` is a safe no-op.)

Just start it:

| OS | Command |
|----|---------|
| macOS / Linux | `./start.sh` |
| Windows | double-click `start.bat` |
| Any (manual) | `python server.py` |

The launcher checks your Python version, creates `config.json` on first run, and
starts the server. Then open <http://localhost:8765>.

### Pinning to the taskbar with the Paramount icon (Windows)
Windows can't pin a `.bat` directly, so run **`create-shortcut.ps1`** once
(right-click → *Run with PowerShell*). It puts a "Board Watch" shortcut on your
Desktop that launches `start.bat` and carries the Paramount + M icon
(`paramount-boardwatch.ico`). Right-click that shortcut → *Pin to taskbar*.

**Your API token is requested in the browser the first time you open the dashboard.**
A "Connect to Monday" screen asks for it, verifies it against Monday, and saves it
automatically to a local `.env` file as `MONDAY_API_TOKEN`. You won't be asked again.

To get the token: in monday.com click your avatar → *Developers* → *My access tokens*,
copy it, and paste it into the prompt. Your personal token carries your own permissions, so
it can read the boards you can see and — for posting updates — write to the items you can
edit. (If posting ever fails with a permissions error, it means the token can't write to that
board.)

> Prefer the command line? `python monday_sync.py set-token <your_token>` saves it the
> same way, or set `MONDAY_API_TOKEN` in your own environment and Board Watch will use it.

### Where things are stored
- **`.env`** — your API token (`MONDAY_API_TOKEN`), written with owner-only permissions. Never committed.
- **`config.json`** — non-secret settings only (see below).
- **`data/boards.json`** — tracked boards + column mappings.
- **`data/tasks.json`** — synced tasks the dashboard reads.

### Settings (`config.json`)
- **`warning_days`** — how many days ahead counts as "due soon" (default 3).
- **`lookback_months`** — trims the data to a rolling due-date window so it stays fast.
  With `4`, syncing in August keeps tasks due June through September (the current month,
  next month, and two months back). Set to `0` to keep all dates.
- **`excluded_departments`** — a list of departments to drop entirely at sync, e.g.
  `["PPC", "Paid Social"]`. Case-insensitive.
- **`monday_account`** — your Monday account slug (the `yourcompany` in
  `yourcompany.monday.com`). Used to build the **Open in Monday** links in the task detail
  view so they jump straight to the item. Set to `""` to fall back to a generic link that
  redirects when you're logged in.
- **`api_version`** — the Monday API version Board Watch talks to (default `2025-07`). Monday
  retires old versions periodically, and calls to a retired version get silently rerouted and
  can misbehave — so if things start acting up after a Monday update, check their developer
  release notes for the current version and set it here (no code change needed).

Both prefilters run at sync time, so excluded/out-of-window tasks never reach `data/tasks.json`
— that's what keeps the dashboard snappy. Tasks with no due date are always kept. The active
window and exclusions are shown in the header line, along with how many tasks were trimmed.

### Adding a board
1. Click **Manage boards**.
2. Paste the board's numeric ID (it's in the board URL, e.g.
   `https://…monday.com/boards/1234567890` → `1234567890`) and click **Add & map**.
3. Every column starts unmapped — nothing is guessed. Set each one yourself:
   **Due date** and **Status** are required; **Owner / Person** and **Department** are
   optional (Task title defaults to the item name).
4. Set which status label(s) mean *done* (e.g. `Done, Complete`).
5. Save. Board Watch pulls that board from Monday straight away, so newly-mapped
   columns (like Department) show up immediately — no separate refresh needed.

Most roles (Due date, Status, Department, Title) belong to a single column, and Board Watch
flags it at save if two columns claim the same one. **Owner / Person is the exception: you
can map it to several columns.** If a board splits ownership into separate *Assignor* and
*Assignee* columns, map **both** to Owner / Person — everyone is pooled together, so filtering
to a person finds every task they're on regardless of which column they sit in. Multiple names
within a single people column are handled the same way.

Boards with different column setups each keep their own mapping, so a "Deadline"
column on one board and a "Due" column on another both work.

### Filtering & flags
- Filter by **person**, **department**, **board**, **urgency**, **status**, **comments**, a
  **due-on-or-before** date, or search titles. The **Status** filter is a checkbox list —
  tick or untick any statuses to show or hide them in any combination, with Select all /
  Clear all shortcuts. Filtering to a person shows every task they're on — as sole owner,
  assignor, assignee, or one of several people. The Owner column shows the first name with a
  **+N** badge (hover for the full list). The Department and Status filters appear only when a
  tracked board actually has those columns.
- The **Comments** column shows a badge with the number of updates (comments) posted on each
  Monday item — hover it to see who wrote the latest one, when, and a short preview. The
  **Comments** filter narrows to tasks that have comments or those with none, handy for
  spotting which tasks have had activity or which are still silent.
- **Click any task row** to open a detail view. It lists every field pulled for that task —
  including columns that aren't shown in the table — and the full list of updates (each with
  author, date, and the complete comment text). An **Open in Monday** link jumps straight to
  the item in Monday (it opens your account's board when you're logged in).
- **Post an update back to Monday** from the detail view: type a comment and click *Post to
  Monday*. If someone's assigned to the task, a **Tag assignee** option (on by default) will
  @mention them so they get notified. Posting writes to the live board, so Board Watch asks
  you to confirm first. After posting, hit *Refresh from Monday* to see the new comment appear
  in the list. (Mentions use Monday's newer API; if your account is pinned to an older API
  version, the comment still posts but the person appears as plain @name text rather than a
  formal tag.)
- Row flags: **Overdue** (red, past due & not done), **Due soon** (amber, within the
  warning window), **On track** (green), **Done** (dimmed, excluded from overdue logic),
  **No date**.
- "Hide done" is on by default. Column headers sort.

## CLI-only usage (no browser)

The sync engine works standalone if you'd rather script it or run it on a schedule:

```
python monday_sync.py set-token <token>  # save your API token to .env
python monday_sync.py add 1234567890     # interactive column mapping in the terminal
python monday_sync.py list               # show tracked boards
python monday_sync.py sync               # pull everything -> data/tasks.json
python monday_sync.py remove 1234567890  # stop tracking a board
```

To keep it fresh automatically, point cron / Task Scheduler at `python monday_sync.py sync`.

## Notes
- Date columns and timelines are both handled; timelines use their end date.
- If a task has no due date it's shown as "No date" and never flagged overdue.
- Removing a board deletes its cached tasks right away — they disappear from the
  dashboard immediately, no refresh needed. Removing the last board clears everything.
- Each refresh fully replaces the previous data, so nothing stale is ever left behind.
- If one board's column mapping is broken, only that board is skipped — the others still
  sync, and a banner at the top of the dashboard names the board so you can fix its mapping.
- The API token lives only in `config.json` on your machine.

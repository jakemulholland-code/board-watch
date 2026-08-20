#!/usr/bin/env python3
"""
Monday Board Dashboard - sync engine.

Usage:
  python monday_sync.py set-token <token>  # save your Monday API token to .env
  python monday_sync.py add <board_id>     # discover columns, create/refresh a mapping
  python monday_sync.py map <board_id>     # (re)interactively map columns for a board
  python monday_sync.py remove <board_id>  # remove a board from tracking
  python monday_sync.py list               # list tracked boards
  python monday_sync.py sync               # pull all tracked boards -> data/tasks.json
  python monday_sync.py                     # same as 'sync'

Column mappings are stored in data/boards.json so non-uniform boards each get
their own person/date/status/title column assignments. Nothing is hard-coded.
"""

import json
import os
import sys
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
BOARDS_FILE = os.path.join(DATA_DIR, "boards.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "sync_progress.json")
CONFIG_FILE = os.path.join(HERE, "config.json")
ENV_FILE = os.path.join(HERE, ".env")
ENV_KEY = "MONDAY_API_TOKEN"

# Monday API version. Versions before 2025-04 are deprecated and get silently
# routed to a maintenance version, which breaks things — so we pin a current
# one. 2025-07 also gives us the mentions_list argument for tagging users in
# updates. Bump this here when Monday releases newer stable versions.
API_VERSION = "2025-07"

# The "roles" a column can be mapped to. due_date/status drive the overdue
# logic; department lets multichannel boards be filtered to one team; title
# overrides the item name; hours feeds the Management (capacity) view. "person"
# is special: it may be mapped to MORE THAN ONE column (e.g. a board with
# separate Assignor and Assignee columns) and all mapped people columns are
# pooled together. Every other role is single-column.
ROLES = ["title", "person", "due_date", "status", "department", "hours", "ignore"]
MULTI_ROLES = ["person"]

# Keyword hints used to build the "default" mapping preset from column titles,
# so a new board starts pre-filled from common Monday naming conventions
# instead of every column starting on "ignore". This is only ever a starting
# point — whatever ends up in boards.json (default or hand-edited) is what's
# actually used. Checked in this order so e.g. "Assignee Name" matches person
# before it could match title on "name".
DEFAULT_ROLE_ORDER = ["person", "due_date", "status", "department", "hours", "title"]
DEFAULT_ROLE_KEYWORDS = {
    "person": ["assignee", "assignor", "person", "people", "owner"],
    "due_date": ["due date", "due"],
    "status": ["status"],
    "department": ["department"],
    "hours": ["hours"],
    "title": ["name", "title"],
}


def guess_role(col_title):
    """Best-effort role guess for a column title, used to build the "default"
    mapping preset. Returns a role from ROLES, or "ignore" if nothing matches."""
    t = (col_title or "").strip().lower()
    for role in DEFAULT_ROLE_ORDER:
        if any(kw in t for kw in DEFAULT_ROLE_KEYWORDS[role]):
            return role
    return "ignore"


def guess_mapping(columns):
    """Build the "default" mapping preset for a board's columns. Unique roles
    only take their first matching column (a later match is left unmapped,
    same as a duplicate would be rejected in manual mode); "person" pools
    every matching column, same as the multi-column rule for manual mapping."""
    mapping = {}
    for c in columns:
        role = guess_role(c.get("title", ""))
        if role == "ignore":
            continue
        if role in MULTI_ROLES:
            mapping.setdefault(role, [])
            if c["id"] not in mapping[role]:
                mapping[role].append(c["id"])
        elif role not in mapping:
            mapping[role] = c["id"]
    return mapping


# --------------------------------------------------------------------------
# small json helpers
# --------------------------------------------------------------------------
def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def write_progress(data):
    """Snapshot of an in-progress (or just-finished) sync, polled by the
    browser to drive the progress bar. Not meant to be durable state — just
    the latest status."""
    save_json(PROGRESS_FILE, data)


def read_progress():
    return load_json(PROGRESS_FILE, {"status": "idle"})


def load_dotenv():
    """Read simple KEY=VALUE lines from .env into os.environ (without overriding
    variables already set in the real environment)."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def get_token():
    """Return the Monday token from the environment (.env is loaded first)."""
    load_dotenv()
    return os.environ.get(ENV_KEY, "").strip()


def save_token(token):
    """Persist the token to .env and set it in the current process so it takes
    effect immediately without a restart. Written with owner-only permissions."""
    token = token.strip()
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if not ln.startswith(ENV_KEY + "=")]
    lines.append(f'{ENV_KEY}={token}')
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    os.environ[ENV_KEY] = token


def load_settings():
    """Non-secret settings live in config.json; the token never does."""
    cfg = load_json(CONFIG_FILE, {})
    cfg.setdefault("api_url", "https://api.monday.com/v2")
    cfg.setdefault("warning_days", 3)
    # Prefilters applied at sync time to keep tasks.json lean:
    #  - lookback_months: keep tasks due within this many months back from the
    #    start of the current month, through the end of this month. e.g. 4 in
    #    August keeps June–September due dates. 0 disables the window.
    #  - excluded_departments: drop tasks whose Department is in this list
    #    (case-insensitive). Tasks with no due date are always kept.
    cfg.setdefault("lookback_months", 4)
    cfg.setdefault("excluded_departments", ["PPC", "Paid Social", "Comms", "Development"])
    # Used by the Management (capacity) view to work out each person's weekly
    # capacity in hours — hours_per_day * work_days_per_week.
    cfg.setdefault("hours_per_day", 7)
    cfg.setdefault("work_days_per_week", 5)
    # Your Monday account slug — the "yourcompany" in yourcompany.monday.com.
    # Used to build "Open in Monday" links straight to each item.
    cfg.setdefault("monday_account", "paramount-digital-ltd")
    # Monday API version. Defaults to a current one; override here if Monday
    # releases a newer stable version and you want to move to it.
    cfg.setdefault("api_version", API_VERSION)
    return cfg


def load_config(require_token=True):
    cfg = load_settings()
    cfg["api_key"] = get_token()
    if require_token and not cfg["api_key"]:
        sys.exit(
            "No Monday API token found.\n"
            "Either open the dashboard (python server.py) and paste it when prompted,\n"
            f"or set it manually:  export {ENV_KEY}=your_token_here"
        )
    return cfg


# --------------------------------------------------------------------------
# Monday API
# --------------------------------------------------------------------------
def monday_query(cfg, query, variables=None):
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        cfg["api_url"],
        data=payload,
        headers={
            "Authorization": cfg["api_key"],
            "Content-Type": "application/json",
            "API-Version": cfg.get("api_version") or API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from Monday: {e.read().decode('utf-8', 'ignore')}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error contacting Monday: {e.reason}")
    if body.get("errors"):
        # Newer API returns GraphQL-standard errors: [{message, extensions:{code}}]
        try:
            first = body["errors"][0]
            msg = first.get("message", "")
            code = (first.get("extensions") or {}).get("code", "")
            detail = f"{msg}{f' [{code}]' if code else ''}" if msg else json.dumps(body["errors"])
        except (KeyError, IndexError, TypeError):
            detail = json.dumps(body["errors"])
        sys.exit("Monday API error: " + detail)
    return body["data"]


def monday_mutation(cfg, query, variables=None, api_version=None):
    """Like monday_query but never exits the process — returns (data, error).
    Used for writes triggered from the browser, where a hard exit would kill
    the running server. On success error is None; on failure data is None."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        cfg["api_url"], data=payload,
        headers={
            "Authorization": cfg["api_key"],
            "Content-Type": "application/json",
            "API-Version": api_version or cfg.get("api_version") or API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        return None, f"HTTP {e.code} from Monday: {detail[:300]}"
    except urllib.error.URLError as e:
        return None, f"Network error contacting Monday: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return None, f"Unexpected error: {e}"
    if "errors" in body:
        try:
            msg = body["errors"][0].get("message", json.dumps(body["errors"]))
        except (KeyError, IndexError, TypeError):
            msg = json.dumps(body["errors"])
        return None, f"Monday API error: {msg}"
    return body.get("data"), None


def post_update(cfg, item_id, text, mentions=None):
    """Post an update (comment) to a Monday item. `mentions` is a list of
    {"id": int, "name": str} for users to @mention — Monday notifies them.
    Returns (ok, error).

    Uses the mentions_list argument (Monday API 2025-07+). The body carries the
    readable "@Name" text; mentions_list creates the actual link + notification.
    """
    text = (text or "").strip()
    if not text:
        return False, "Update text is empty."

    mentions = mentions or []

    def esc_html(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))

    # Monday's docs are explicit: when using mentions_list, DON'T put @ symbols
    # in the body — mentions_list creates the actual mention + notification, and
    # the mention chip is rendered by Monday. So the body is just the message.
    body_html = "<p>" + esc_html(text).replace("\n", "<br>") + "</p>"

    # Build the mentions_list literal exactly as Monday documents it:
    #   mentions_list: [{id: 123, type: User}]
    # We inline it into the query rather than passing it as a typed variable,
    # because Monday's schema input-type name isn't published and guessing it
    # would make the whole mutation fail validation. `type: User` is an enum, so
    # it must be an unquoted literal (not a JSON string). IDs are ints we control.
    valid_ids = [int(m["id"]) for m in mentions if m.get("id") is not None]

    if valid_ids:
        literal = "[" + ", ".join(f"{{id: {i}, type: User}}" for i in valid_ids) + "]"
        q = ("""
        mutation ($itemId: ID!, $body: String!) {
          create_update (item_id: $itemId, body: $body, mentions_list: """ + literal + """) { id }
        }""")
    else:
        q = """
        mutation ($itemId: ID!, $body: String!) {
          create_update (item_id: $itemId, body: $body) { id }
        }"""

    variables = {"itemId": str(item_id), "body": body_html}
    data, err = monday_mutation(cfg, q, variables)
    if err:
        # If mentions caused the failure, retry as a plain comment so at least
        # the update posts. In that case we DO put the names in the body (as
        # plain @name text) so the message still reads as addressed to them.
        if valid_ids and ("mention" in err.lower() or "MentionInput" in err):
            names = " ".join(f"@{esc_html(m.get('name','user'))}" for m in mentions if m.get("id") is not None)
            fallback_body = "<p>" + (names + " " if names else "") + esc_html(text).replace("\n", "<br>") + "</p>"
            q2 = """
            mutation ($itemId: ID!, $body: String!) {
              create_update (item_id: $itemId, body: $body) { id }
            }"""
            data, err2 = monday_mutation(cfg, q2, {"itemId": str(item_id), "body": fallback_body})
            if err2:
                return False, err2
            return True, "posted, but the person wasn't formally tagged (Monday rejected the mention — they appear as plain @name text)"
        return False, err
    return True, None


def fetch_board_columns(cfg, board_id):
    """Fetch a board's columns (id, title, type) for the mapping UI."""
    q = """
    query ($ids: [ID!]) {
      boards (ids: $ids) {
        id
        name
        columns { id title type }
      }
    }"""
    data = monday_query(cfg, q, {"ids": [str(board_id)]})
    boards = data.get("boards") or []
    if not boards:
        sys.exit(f"Board {board_id} not found (check the id and token permissions).")
    return boards[0]


def fetch_board_items(cfg, board_id, on_page=None):
    """Fetch all items on a board, paginating with cursor. If given, on_page(n)
    is called after each page with the number of items that page added —
    used to drive the sync progress bar without needing the total up front."""
    items = []
    cursor = None
    q = """
    query ($ids: [ID!], $cursor: String) {
      boards (ids: $ids) {
        items_page (limit: 100, cursor: $cursor) {
          cursor
          items {
            id
            name
            group { title }
            column_values { id text type value }
            updates (limit: 50) {
              id
              text_body
              created_at
              creator { name }
            }
          }
        }
      }
    }"""
    while True:
        data = monday_query(cfg, q, {"ids": [str(board_id)], "cursor": cursor})
        boards = data.get("boards") or []
        if not boards:
            break
        page = boards[0]["items_page"]
        items.extend(page["items"])
        if on_page:
            on_page(len(page["items"]))
        cursor = page.get("cursor")
        if not cursor:
            break
    return items


def fetch_items_count(cfg, board_ids):
    """Cheap upfront item counts for a set of boards, used only to size the
    sync progress bar/ETA. Best-effort by design — callers should tolerate
    this failing (e.g. via try/except) and fall back to an indeterminate bar
    rather than letting a progress-only query fail the whole sync."""
    if not board_ids:
        return {}
    q = """
    query ($ids: [ID!]) {
      boards (ids: $ids) { id items_count }
    }"""
    data = monday_query(cfg, q, {"ids": [str(b) for b in board_ids]})
    return {b["id"]: b.get("items_count") or 0 for b in (data.get("boards") or [])}


# --------------------------------------------------------------------------
# column mapping
# --------------------------------------------------------------------------
def interactive_map(board):
    cols = board["columns"]
    print(f"\nMapping columns for board: {board['name']} ({board['id']})")
    print("Roles: title | person | due_date | status | department | hours | ignore")
    print("(Press Enter to accept the suggested default shown for each column.")
    print(" 'person' may be used on several columns — e.g. Assignor and")
    print(" Assignee — and all are pooled together.)\n")
    mapping = {}
    done_labels = None
    for c in cols:
        guess = guess_role(c["title"])
        prompt = f"  [{c['type']:>16}] {c['title']}  -> role (default: {guess}): "
        ans = input(prompt).strip().lower()
        role = ans if ans in ROLES else guess
        if role in MULTI_ROLES:
            mapping.setdefault(role, [])
            if c["id"] not in mapping[role]:
                mapping[role].append(c["id"])
        elif role != "ignore":
            mapping[role] = c["id"]  # last column wins for a repeated single role
        if role == "status":
            dl = input("     which status label counts as DONE? (default: Done): ").strip()
            done_labels = [d.strip().lower() for d in (dl or "Done").split(",")]
    return mapping, (done_labels or ["done"])


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_add(cfg, board_id):
    store = load_json(BOARDS_FILE, {"boards": {}})
    board = fetch_board_columns(cfg, board_id)
    mapping, done_labels = interactive_map(board)
    store["boards"][str(board_id)] = {
        "id": str(board_id),
        "name": board["name"],
        "columns": board["columns"],
        "mapping": mapping,
        "done_labels": done_labels,
    }
    save_json(BOARDS_FILE, store)
    print(f"\nSaved mapping for '{board['name']}'. Run: python monday_sync.py sync")


def cmd_map(cfg, board_id):
    cmd_add(cfg, board_id)  # same flow re-runs the mapping


def prune_tasks_for_board(board_id):
    """Remove a single board's tasks from tasks.json so a deleted board's data
    disappears immediately, without waiting for the next full sync. Also refreshes
    the derived people/departments/statuses lists so filters stay in sync."""
    board_id = str(board_id)
    data = load_json(TASKS_FILE, None)
    if not data or "tasks" not in data:
        return
    data["tasks"] = [t for t in data["tasks"] if str(t.get("board_id")) != board_id]
    data["boards"] = [b for b in data.get("boards", []) if str(b.get("id")) != board_id]
    tasks = data["tasks"]
    data["people"] = sorted({n for t in tasks for n in (t.get("people") or [t.get("person")]) if n})
    data["departments"] = sorted({t.get("department") for t in tasks if t.get("department")})
    data["statuses"] = sorted({t.get("status") for t in tasks if t.get("status")})
    save_json(TASKS_FILE, data)


def cmd_remove(cfg, board_id):
    store = load_json(BOARDS_FILE, {"boards": {}})
    if store["boards"].pop(str(board_id), None):
        save_json(BOARDS_FILE, store)
        prune_tasks_for_board(board_id)          # wipe its cached tasks too
        # if that was the last board, clear the task cache entirely
        if not store["boards"]:
            save_json(TASKS_FILE, empty_tasks())
        print(f"Removed board {board_id} and its cached tasks.")
    else:
        print(f"Board {board_id} was not tracked.")


def cmd_list(cfg):
    store = load_json(BOARDS_FILE, {"boards": {}})
    if not store["boards"]:
        print("No boards tracked yet. Add one: python monday_sync.py add <board_id>")
        return
    for b in store["boards"].values():
        print(f"  {b['id']}  {b['name']}   mapping={b['mapping']}  done={b['done_labels']}")


def parse_date(text, raw_value):
    """Monday date columns: 'text' is usually YYYY-MM-DD; timelines use value json."""
    if text:
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            pass
    if raw_value:
        try:
            v = json.loads(raw_value)
            for key in ("date", "to", "from"):
                if isinstance(v, dict) and v.get(key):
                    return datetime.date.fromisoformat(str(v[key])[:10])
        except (ValueError, TypeError):
            pass
    return None


def due_window(today, lookback_months):
    """Return (start_date, end_exclusive) for the due-date prefilter, or None to
    disable. The window is `lookback_months` wide, ending at the last day of NEXT
    month. e.g. lookback_months=4 in August keeps Jun 1 .. Sep 30 (Oct 1 excl),
    i.e. June, July, August, September."""
    months = int(lookback_months or 0)
    if months <= 0:
        return None
    base = today.year * 12 + (today.month - 1)
    start_total = base - (months - 2)      # first month in the window
    end_total = base + 1                    # last month in the window (next month)
    sy, sm = divmod(start_total, 12)
    ey, em = divmod(end_total + 1, 12)      # +1 month -> exclusive upper bound
    return datetime.date(sy, sm + 1, 1), datetime.date(ey, em + 1, 1)


def empty_tasks():
    """A clean, valid tasks.json payload with no tasks."""
    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "today": datetime.date.today().isoformat(),
        "warning_days": 3,
        "hours_per_day": 7, "work_days_per_week": 5,
        "boards": [], "people": [], "departments": [], "statuses": [],
        "tasks": [], "errors": [],
    }


def process_item(it, m, done_labels, board, today, warn):
    """Turn one Monday item into a task dict using this board's mapping.
    Kept separate so a malformed mapping raises here and is caught per-board."""
    cv = {c["id"]: c for c in it["column_values"]}

    title = it["name"]
    if "title" in m and cv.get(m["title"]):
        title = cv[m["title"]]["text"] or title

    person_cols = m.get("person", [])
    if isinstance(person_cols, str):
        person_cols = [person_cols] if person_cols else []
    people = []
    people_ids = []
    for col_id in person_cols:
        c = cv.get(col_id, {}) or {}
        raw = c.get("text", "") or ""
        for n in raw.split(","):
            n = n.strip()
            if n and n not in people:
                people.append(n)
        # The people column's value carries the actual Monday user IDs, which we
        # need to @mention someone in an update. Parse them out defensively.
        val = c.get("value")
        if val:
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
                for pt in (parsed or {}).get("personsAndTeams", []) or []:
                    pid = pt.get("id")
                    kind = pt.get("kind", "person")
                    if pid is not None and kind == "person":
                        pid = int(pid)
                        if pid not in people_ids:
                            people_ids.append(pid)
            except (ValueError, TypeError, AttributeError):
                pass
    person = people[0] if people else "Unassigned"

    status = cv.get(m.get("status", ""), {}).get("text", "") or ""
    department = cv.get(m.get("department", ""), {}).get("text", "") or ""

    hours = None
    if "hours" in m and cv.get(m["hours"]):
        raw_hours = (cv[m["hours"]].get("text") or "").strip()
        if raw_hours:
            try:
                hours = float(raw_hours)
            except ValueError:
                hours = None

    due = None
    if "due_date" in m and cv.get(m["due_date"]):
        dc = cv[m["due_date"]]
        d = parse_date(dc.get("text", ""), dc.get("value"))
        due = d.isoformat() if d else None

    is_done = status.lower() in done_labels

    state = "none"
    days_left = None
    if due and not is_done:
        d = datetime.date.fromisoformat(due)
        days_left = (d - today).days
        state = "overdue" if days_left < 0 else ("warning" if days_left <= warn else "ok")
    elif is_done:
        state = "done"

    # Updates (comments posted on the item). Keep the full list for the detail
    # view (author, date, body), plus the count and the latest snippet for the
    # table badge. Bodies are capped so tasks.json doesn't balloon.
    updates = it.get("updates") or []
    update_count = len(updates)
    all_updates = []
    for u in updates:
        body = (u.get("text_body") or "").strip()
        if len(body) > 2000:
            body = body[:2000] + "…"
        created = u.get("created_at", "") or ""
        all_updates.append({
            "author": (u.get("creator") or {}).get("name", "") or "Someone",
            "date": created[:10] if created else "",
            "datetime": created,
            "body": body,
        })
    last_update = None
    if all_updates:
        u0 = all_updates[0]
        oneline = u0["body"].replace("\n", " ")
        last_update = {
            "author": u0["author"], "date": u0["date"],
            "snippet": (oneline[:140] + "…") if len(oneline) > 140 else oneline,
        }

    # All column values pulled for this item (so the detail view can show
    # everything, not just the mapped fields). Skip empty ones.
    col_titles = {c["id"]: c.get("title", c["id"]) for c in (board.get("columns") or [])}
    all_fields = []
    for c in it["column_values"]:
        txt = (c.get("text") or "").strip()
        if txt:
            all_fields.append({
                "id": c["id"],
                "label": col_titles.get(c["id"], c["id"]),
                "type": c.get("type", ""),
                "text": txt,
            })

    return {
        "id": it["id"], "title": title,
        "board_id": board["id"], "board_name": board["name"],
        "group": (it.get("group") or {}).get("title", ""),
        "person": person, "people": people, "people_ids": people_ids,
        "department": department, "status": status, "hours": hours,
        "is_done": is_done, "due_date": due,
        "days_left": days_left, "state": state,
        "update_count": update_count,
        "has_update": update_count > 0,
        "last_update": last_update,
        "updates": all_updates,
        "fields": all_fields,
    }


def cmd_sync(cfg):
    store = load_json(BOARDS_FILE, {"boards": {}})
    # A fresh pull always replaces the previous cache. With no boards, that means
    # an empty cache — so removing every board leaves nothing stale behind.
    if not store["boards"]:
        save_json(TASKS_FILE, empty_tasks())
        write_progress({"status": "idle"})
        print("No boards tracked — cleared task cache.")
        return

    today = datetime.date.today()
    warn = int(cfg["warning_days"])
    win = due_window(today, cfg.get("lookback_months", 4))
    excluded = {d.strip().lower() for d in cfg.get("excluded_departments", []) if d.strip()}
    out_tasks = []
    errors = []
    filtered_out = 0

    boards_list = list(store["boards"].values())

    # Best-effort upfront item counts, purely to size the progress bar/ETA —
    # a failure here (e.g. a transient API hiccup) must not fail the sync
    # itself, so it just falls back to an indeterminate bar.
    try:
        items_total = sum(fetch_items_count(cfg, [b["id"] for b in boards_list]).values())
    except (SystemExit, Exception):  # noqa: BLE001
        items_total = None

    progress = {
        "status": "running",
        "boards_total": len(boards_list),
        "boards_done": 0,
        "current_board": boards_list[0]["name"] if boards_list else None,
        "items_total": items_total,
        "items_done": 0,
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    write_progress(progress)

    def keep(task):
        # drop excluded departments
        if excluded and (task["department"] or "").strip().lower() in excluded:
            return False
        # drop tasks whose due date is outside the window (undated tasks are kept)
        if win and task["due_date"]:
            d = datetime.date.fromisoformat(task["due_date"])
            if d < win[0] or d >= win[1]:
                return False
        return True

    for idx, board in enumerate(boards_list):
        progress["current_board"] = board["name"]
        write_progress(progress)
        # One board's bad mapping or API hiccup must not sink the whole sync.
        try:
            m = board.get("mapping") or {}
            if not m.get("due_date") or not m.get("status"):
                raise ValueError("mapping is missing a Due date and/or Status column")
            done_labels = [d.lower() for d in board.get("done_labels", ["done"])]

            def on_page(n):
                progress["items_done"] += n
                write_progress(progress)

            items = fetch_board_items(cfg, board["id"], on_page=on_page)
            for it in items:
                task = process_item(it, m, done_labels, board, today, warn)
                if keep(task):
                    out_tasks.append(task)
                else:
                    filtered_out += 1
        except Exception as e:  # noqa: BLE001 - we want to keep going
            msg = f"{board.get('name', board.get('id'))}: {e}"
            errors.append(msg)
            print(f"  ! skipped board {board.get('id')} — {e}")
        finally:
            progress["boards_done"] = idx + 1
            write_progress(progress)

    result = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "warning_days": warn,
        "hours_per_day": float(cfg.get("hours_per_day", 7) or 7),
        "work_days_per_week": float(cfg.get("work_days_per_week", 5) or 5),
        "monday_account": (cfg.get("monday_account") or "").strip(),
        "boards": [{"id": b["id"], "name": b["name"]} for b in store["boards"].values()],
        "people": sorted({n for t in out_tasks for n in t["people"]}),
        "departments": sorted({t["department"] for t in out_tasks if t["department"]}),
        "statuses": sorted({t["status"] for t in out_tasks if t["status"]}),
        "tasks": out_tasks,
        "errors": errors,
        "prefilter": {
            "lookback_months": int(cfg.get("lookback_months", 4) or 0),
            "window_start": win[0].isoformat() if win else None,
            "window_end": (win[1] - datetime.timedelta(days=1)).isoformat() if win else None,
            "excluded_departments": sorted(excluded),
            "filtered_out": filtered_out,
        },
    }
    try:
        save_json(TASKS_FILE, result)   # full replace — old data is wiped
    finally:
        write_progress({"status": "done", "finished_at": datetime.datetime.now().isoformat(timespec="seconds")})
    counts = {}
    for t in out_tasks:
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    print(f"Synced {len(out_tasks)} tasks -> {TASKS_FILE}")
    if counts:
        print("  " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    if filtered_out:
        print(f"  {filtered_out} task(s) trimmed by prefilters (date window / excluded departments).")
    if errors:
        print(f"  {len(errors)} board(s) skipped due to problems (see dashboard).")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "sync"

    # set-token doesn't need an existing token
    if cmd == "set-token" and len(args) == 2:
        save_token(args[1])
        print(f"Saved token to .env as {ENV_KEY}.")
        return
    # remove/list don't strictly need a token to work locally
    if cmd == "remove" and len(args) == 2:
        cmd_remove(load_config(require_token=False), args[1])
        return
    if cmd == "list":
        cmd_list(load_config(require_token=False))
        return

    cfg = load_config()  # token required for the rest
    if cmd == "add" and len(args) == 2:
        cmd_add(cfg, args[1])
    elif cmd == "map" and len(args) == 2:
        cmd_map(cfg, args[1])
    elif cmd == "sync":
        cmd_sync(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

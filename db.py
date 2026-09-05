"""SQLite persistence layer for tasks and calendar events."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "planner.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn, table: str, column: str, decl: str):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                category TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Added later: explicit due date/time (from "YYYY-MM-DD HH:MM" in the
        # task text) and free-form #tags. ALTER TABLE keeps existing rows.
        _ensure_column(conn, "tasks", "due_date", "TEXT")
        _ensure_column(conn, "tasks", "due_time", "TEXT")
        _ensure_column(conn, "tasks", "tags", "TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Added later: where an event came from, so a Google-synced event can
        # be told apart from one created locally (and re-synced without
        # duplicating).
        _ensure_column(conn, "events", "source", "TEXT NOT NULL DEFAULT 'local'")
        _ensure_column(conn, "events", "google_event_id", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('task', 'event')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(name, kind)
            )
            """
        )
        # Backfill categories table from any category values already used,
        # so upgrading an existing planner.db doesn't lose known categories.
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, kind) SELECT DISTINCT category, 'task' FROM tasks"
        )
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, kind) SELECT DISTINCT category, 'event' FROM events"
        )
        conn.commit()


# ---------------- Categories ----------------

def upsert_category(name: str, kind: str):
    """Register a category name if it isn't already known (no-op otherwise)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, kind) VALUES (?, ?)", (name, kind)
        )
        conn.commit()


def get_categories(kind: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM categories WHERE kind = ? ORDER BY id ASC", (kind,)
        ).fetchall()
        return [r["name"] for r in rows]


def delete_category(name: str, kind: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM categories WHERE name = ? AND kind = ?", (name, kind))
        conn.commit()


def rename_category(kind: str, old_name: str, new_name: str):
    """Rename a category, cascading to every task/event that uses it.

    If `new_name` already exists as a separate category, the two are merged
    (every row moves to `new_name` and the now-empty `old_name` row is
    dropped) rather than erroring.
    """
    table = "tasks" if kind == "task" else "events"
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, ?)", (new_name, kind))
        conn.execute(f"UPDATE {table} SET category = ? WHERE category = ?", (new_name, old_name))
        conn.execute("DELETE FROM categories WHERE name = ? AND kind = ?", (old_name, kind))
        conn.commit()


# ---------------- Tasks ----------------

def _task_dict(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (TypeError, ValueError):
        d["tags"] = []
    return d


def insert_task(text: str, category: str, due_date: str = None, due_time: str = None, tags: list = None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (text, category, due_date, due_time, tags)
               VALUES (?, ?, ?, ?, ?)""",
            (text, category, due_date, due_time, json.dumps(tags or [], ensure_ascii=False)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _task_dict(row)


def get_tasks() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [_task_dict(r) for r in rows]


def get_tasks_due_between(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date BETWEEN ? AND ?
               ORDER BY due_date, due_time""",
            (start_date, end_date),
        ).fetchall()
        return [_task_dict(r) for r in rows]


def toggle_task_completed(task_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        new_val = 0 if row["completed"] else 1
        conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (new_val, task_id))
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_dict(row)


def delete_task(task_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()


def set_task_text(task_id: int, text: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE tasks SET text = ? WHERE id = ?", (text, task_id))
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_dict(row)


def set_task_category(task_id: int, category: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE tasks SET category = ? WHERE id = ?", (category, task_id))
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_dict(row)


# ---------------- Events ----------------

def insert_event(title, category, event_date, start_time=None, end_time=None, note=None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO events (title, category, date, start_time, end_time, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, category, event_date, start_time, end_time, note),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def upsert_google_event(
    google_event_id: str, title: str, category: str, event_date: str,
    start_time: str = None, end_time: str = None, note: str = None,
) -> dict:
    """Insert or update an event pulled from Google Calendar, keyed by its
    Google event id so repeated syncs don't create duplicates."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM events WHERE google_event_id = ?", (google_event_id,)
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE events SET title=?, category=?, date=?, start_time=?, end_time=?, note=?
                   WHERE google_event_id=?""",
                (title, category, event_date, start_time, end_time, note, google_event_id),
            )
            event_id = row["id"]
        else:
            cur = conn.execute(
                """INSERT INTO events (title, category, date, start_time, end_time, note, source, google_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'google', ?)""",
                (title, category, event_date, start_time, end_time, note, google_event_id),
            )
            event_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row)


def get_events_between(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start_time",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_event(event_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()

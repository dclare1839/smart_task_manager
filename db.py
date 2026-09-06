"""Postgres (Supabase) persistence layer for tasks and calendar events.

Requires DATABASE_URL in the environment — a standard Postgres connection
string, e.g. from Supabase's Project Settings → Database → Connection string.
"""

import json
import os

import psycopg2
import psycopg2.extras
import psycopg2.pool

# A fresh psycopg2.connect() per request means a full TCP+TLS handshake to
# Supabase every time — the Render↔Supabase cross-region hop makes that cost
# very noticeable (~1s+). Pool connections instead so requests reuse an
# already-open connection.
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL이 설정되어 있지 않습니다 (.env 확인).")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1, 10, dsn, cursor_factory=psycopg2.extras.RealDictCursor
        )
    return _pool


class _PooledConn:
    """`with get_conn() as conn:` borrows a connection from the pool and
    always returns it afterward, instead of opening/closing a new one."""

    def __enter__(self):
        self.conn = _get_pool().getconn()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            try:
                self.conn.rollback()
            except Exception:
                pass
        _get_pool().putconn(self.conn)
        return False


def get_conn():
    return _PooledConn()


def init_db():
    """Idempotently ensure the schema exists (safe to run on every startup)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('task', 'event')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(name, kind)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    completed BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    due_date DATE,
                    due_time TEXT,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    date DATE NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    source TEXT NOT NULL DEFAULT 'local',
                    google_event_id TEXT UNIQUE
                )
                """
            )
            # Backfill categories from any category values already in use.
            cur.execute(
                "INSERT INTO categories (name, kind) "
                "SELECT DISTINCT category, 'task' FROM tasks "
                "ON CONFLICT (name, kind) DO NOTHING"
            )
            cur.execute(
                "INSERT INTO categories (name, kind) "
                "SELECT DISTINCT category, 'event' FROM events "
                "ON CONFLICT (name, kind) DO NOTHING"
            )
        conn.commit()


def _jsonify(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _to_iso(value):
    """Postgres DATE/TIMESTAMPTZ columns come back as date/datetime objects;
    stringify them so the rest of the app (and JSON responses) sees the same
    plain ISO strings it always has."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


# ---------------- Categories ----------------

def upsert_category(name: str, kind: str):
    """Register a category name if it isn't already known (no-op otherwise)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, kind) VALUES (%s, %s) ON CONFLICT (name, kind) DO NOTHING",
                (name, kind),
            )
        conn.commit()


def get_categories(kind: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM categories WHERE kind = %s ORDER BY id ASC", (kind,))
            return [r["name"] for r in cur.fetchall()]


def delete_category(name: str, kind: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM categories WHERE name = %s AND kind = %s", (name, kind))
        conn.commit()


def rename_category(kind: str, old_name: str, new_name: str):
    """Rename a category, cascading to every task/event that uses it.

    If `new_name` already exists as a separate category, the two are merged
    (every row moves to `new_name` and the now-empty `old_name` row is
    dropped) rather than erroring.
    """
    table = "tasks" if kind == "task" else "events"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, kind) VALUES (%s, %s) ON CONFLICT (name, kind) DO NOTHING",
                (new_name, kind),
            )
            cur.execute(f"UPDATE {table} SET category = %s WHERE category = %s", (new_name, old_name))
            cur.execute("DELETE FROM categories WHERE name = %s AND kind = %s", (old_name, kind))
        conn.commit()


# ---------------- Tasks ----------------

def _task_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    tags = d.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = []
    d["tags"] = tags or []
    d["due_date"] = _to_iso(d.get("due_date"))
    d["created_at"] = _to_iso(d.get("created_at"))
    return d


def insert_task(text: str, category: str, due_date: str = None, due_time: str = None, tags: list = None) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tasks (text, category, due_date, due_time, tags)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (text, category, due_date, due_time, _jsonify(tags)),
            )
            task_id = cur.fetchone()["id"]
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
        conn.commit()
        return _task_dict(row)


def get_tasks() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            return [_task_dict(r) for r in cur.fetchall()]


def get_tasks_due_between(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date BETWEEN %s AND %s
                   ORDER BY due_date, due_time""",
                (start_date, end_date),
            )
            return [_task_dict(r) for r in cur.fetchall()]


def get_upcoming_tasks_due(from_date: str, limit: int) -> list:
    """Not-yet-completed tasks due today or later, soonest first — used for
    the home tab's at-a-glance agenda."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date >= %s AND completed = false
                   ORDER BY due_date, due_time LIMIT %s""",
                (from_date, limit),
            )
            return [_task_dict(r) for r in cur.fetchall()]


def toggle_task_completed(task_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT completed FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "UPDATE tasks SET completed = %s WHERE id = %s", (not row["completed"], task_id)
            )
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
        conn.commit()
        return _task_dict(row)


def delete_task(task_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()


def set_task_text(task_id: int, text: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tasks SET text = %s WHERE id = %s", (text, task_id))
            if cur.rowcount == 0:
                return None
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
        conn.commit()
        return _task_dict(row)


def set_task_category(task_id: int, category: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tasks SET category = %s WHERE id = %s", (category, task_id))
            if cur.rowcount == 0:
                return None
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
        conn.commit()
        return _task_dict(row)


# ---------------- Events ----------------

def _event_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d["date"] = _to_iso(d.get("date"))
    d["created_at"] = _to_iso(d.get("created_at"))
    return d


def insert_event(title, category, event_date, start_time=None, end_time=None, note=None) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO events (title, category, date, start_time, end_time, note)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (title, category, event_date, start_time, end_time, note),
            )
            event_id = cur.fetchone()["id"]
            cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        conn.commit()
        return _event_dict(row)


def upsert_google_event(
    google_event_id: str, title: str, category: str, event_date: str,
    start_time: str = None, end_time: str = None, note: str = None,
) -> dict:
    """Insert or update an event pulled from Google Calendar, keyed by its
    Google event id so repeated syncs don't create duplicates."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (title, category, date, start_time, end_time, note, source, google_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'google', %s)
                ON CONFLICT (google_event_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    date = EXCLUDED.date,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    note = EXCLUDED.note
                RETURNING id
                """,
                (title, category, event_date, start_time, end_time, note, google_event_id),
            )
            event_id = cur.fetchone()["id"]
            cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        conn.commit()
        return _event_dict(row)


def get_events_between(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM events WHERE date BETWEEN %s AND %s ORDER BY date, start_time",
                (start_date, end_date),
            )
            return [_event_dict(r) for r in cur.fetchall()]


def get_upcoming_events(from_date: str, limit: int) -> list:
    """Events today or later, soonest first — used for the home tab."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM events WHERE date >= %s ORDER BY date, start_time LIMIT %s",
                (from_date, limit),
            )
            return [_event_dict(r) for r in cur.fetchall()]


def delete_event(event_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        conn.commit()

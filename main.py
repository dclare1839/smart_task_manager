"""FastAPI app: task categorization + calendar with LLM-assisted briefings."""

import base64
import os
import secrets
from datetime import date, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import google_calendar as gcal
import llm
import parsing

app = FastAPI(title="Smart Task Planner")

db.init_db()

# ---------------- Basic auth (for when this is exposed beyond localhost) ----------------
# Set APP_USERNAME / APP_PASSWORD in .env before putting this behind a tunnel
# or port-forward. If either is unset, no login is required — fine for
# localhost-only use, but never expose the app externally without this set.
APP_USERNAME = os.environ.get("APP_USERNAME")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

if not APP_USERNAME or not APP_PASSWORD:
    print(
        "[auth] APP_USERNAME/APP_PASSWORD가 설정되지 않았습니다 — 로그인 없이 동작합니다. "
        "외부에 노출하기 전에 .env에 값을 설정하세요."
    )


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    # StaticFiles sends no Cache-Control header, so browsers fall back to
    # heuristic caching (based on Last-Modified) and can silently keep
    # serving an old app.js/style.css after an edit, even after a reload.
    # This is a small local tool, not something worth tuning cache
    # lifetimes for, so just always require a fresh fetch.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if not APP_USERNAME or not APP_PASSWORD:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            username, password = "", ""
        if secrets.compare_digest(username, APP_USERNAME) and secrets.compare_digest(password, APP_PASSWORD):
            return await call_next(request)

    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Smart Task Planner"'},
        content="Authentication required",
    )


# ---------------- Schemas ----------------

class TaskIn(BaseModel):
    text: str
    category: Optional[str] = None  # skip auto-classification if provided


class TaskCategoryIn(BaseModel):
    category: str


class TaskTextIn(BaseModel):
    text: str


class CategoryRenameIn(BaseModel):
    kind: str
    old_name: str
    new_name: str


class EventIn(BaseModel):
    text: str  # free-form, e.g. "9월 10일 오후 3시 치과 예약"
    # When these are provided, the client already ran /api/events/analyze and
    # is confirming a (possibly user-edited) draft — skip re-analysis.
    title: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    note: Optional[str] = None
    category: Optional[str] = None


class CategoryIn(BaseModel):
    name: str
    kind: str  # "task" or "event"


# ---------------- Tasks ----------------

@app.post("/api/tasks")
def create_task(payload: TaskIn):
    raw_text = payload.text.strip()
    if not raw_text:
        raise HTTPException(400, "할 일 내용을 입력해주세요.")

    # "#tag" tokens and an explicit "YYYY-MM-DD[ HH:MM]" are pulled out of the
    # text up front — they're unambiguous, so there's no need to ask the LLM.
    tags, text_no_tags = parsing.extract_tags(raw_text)
    due_date, due_time, clean_text = parsing.extract_explicit_datetime(text_no_tags)
    display_text = clean_text or text_no_tags or raw_text

    manual_category = (payload.category or "").strip()
    if manual_category:
        category = manual_category
    else:
        category = llm.categorize_task(display_text, db.get_categories("task"))
    db.upsert_category(category, "task")
    return db.insert_task(display_text, category, due_date=due_date, due_time=due_time, tags=tags)


@app.get("/api/tasks")
def list_tasks(grouped: bool = True):
    tasks = db.get_tasks()
    if not grouped:
        return tasks
    # Seed every known category (even ones with zero tasks) so empty
    # categories still render as drop targets in the UI.
    groups: dict = {cat: [] for cat in db.get_categories("task")}
    for t in tasks:
        groups.setdefault(t["category"], []).append(t)
    return groups


@app.patch("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    task = db.toggle_task_completed(task_id)
    if not task:
        raise HTTPException(404, "할 일을 찾을 수 없습니다.")
    return task


@app.patch("/api/tasks/{task_id}")
def edit_task_text(task_id: int, payload: TaskTextIn):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "할 일 내용을 입력해주세요.")
    task = db.set_task_text(task_id, text)
    if not task:
        raise HTTPException(404, "할 일을 찾을 수 없습니다.")
    return task


@app.patch("/api/tasks/{task_id}/category")
def update_task_category(task_id: int, payload: TaskCategoryIn):
    category = payload.category.strip()
    if not category:
        raise HTTPException(400, "카테고리를 입력해주세요.")
    db.upsert_category(category, "task")
    task = db.set_task_category(task_id, category)
    if not task:
        raise HTTPException(404, "할 일을 찾을 수 없습니다.")
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    db.delete_task(task_id)
    return {"ok": True}


# ---------------- Categories ----------------

@app.get("/api/categories")
def list_categories(kind: str):
    if kind not in ("task", "event"):
        raise HTTPException(400, "kind는 task 또는 event여야 합니다.")
    return db.get_categories(kind)


@app.post("/api/categories")
def create_category(payload: CategoryIn):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "카테고리 이름을 입력해주세요.")
    if payload.kind not in ("task", "event"):
        raise HTTPException(400, "kind는 task 또는 event여야 합니다.")
    db.upsert_category(name, payload.kind)
    return {"name": name, "kind": payload.kind}


@app.patch("/api/categories/rename")
def rename_category(payload: CategoryRenameIn):
    if payload.kind not in ("task", "event"):
        raise HTTPException(400, "kind는 task 또는 event여야 합니다.")
    old_name = payload.old_name.strip()
    new_name = payload.new_name.strip()
    if not old_name or not new_name:
        raise HTTPException(400, "카테고리 이름을 입력해주세요.")
    db.rename_category(payload.kind, old_name, new_name)
    return {"kind": payload.kind, "old_name": old_name, "new_name": new_name}


# ---------------- Events / Calendar ----------------

def _analyze_event_text(text: str) -> dict:
    """Parse `text` into a draft event and suggest a category via Claude.

    The suggested category reuses an existing one when it fits, or is a
    short new category summarizing the content when nothing fits — the
    caller can tell which happened via `category_is_new`.
    """
    # An explicit "YYYY-MM-DD[ HH:MM]" is authoritative — use it as-is instead
    # of leaving the date/time to the LLM (or the keyword fallback) to guess.
    explicit_date, explicit_time, clean_text = parsing.extract_explicit_datetime(text)
    parse_source = clean_text or text

    existing_categories = db.get_categories("event")
    parsed = llm.parse_schedule(
        parse_source, existing_categories, reference_date=explicit_date or date.today().isoformat()
    )
    if explicit_date:
        parsed["date"] = explicit_date
        parsed["start_time"] = explicit_time
        parsed["end_time"] = None
        if not parsed.get("title"):
            parsed["title"] = parse_source

    category = parsed["category"]
    return {
        "title": parsed["title"],
        "date": parsed["date"],
        "start_time": parsed.get("start_time"),
        "end_time": parsed.get("end_time"),
        "note": parsed.get("note"),
        "category": category,
        "category_is_new": category not in existing_categories,
        "existing_categories": existing_categories,
    }


@app.post("/api/events/analyze")
def analyze_event(payload: EventIn):
    """Analyze event text and suggest a category, without saving anything yet."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "일정 내용을 입력해주세요.")
    return _analyze_event_text(text)


@app.post("/api/events")
def create_event(payload: EventIn):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "일정 내용을 입력해주세요.")

    if payload.date and payload.category:
        # Client already analyzed this and is confirming the (possibly
        # user-edited) draft — save it as-is, no re-analysis.
        category = payload.category.strip()
        db.upsert_category(category, "event")
        return db.insert_event(
            title=(payload.title or text).strip(),
            category=category,
            event_date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            note=payload.note,
        )

    # No pre-analysis (e.g. the Tasks tab's quick "add as event") — run the
    # full analyze pipeline now and save immediately.
    draft = _analyze_event_text(text)
    db.upsert_category(draft["category"], "event")
    return db.insert_event(
        title=draft["title"],
        category=draft["category"],
        event_date=draft["date"],
        start_time=draft.get("start_time"),
        end_time=draft.get("end_time"),
        note=draft.get("note"),
    )


@app.get("/api/events")
def list_events(start: str, end: str):
    return db.get_events_between(start, end)


@app.get("/api/schedule")
def get_schedule(start: str, end: str):
    """Combined events + due-tasks for a date range (used by the month grid)."""
    return {
        "start": start,
        "end": end,
        "events": db.get_events_between(start, end),
        "tasks": db.get_tasks_due_between(start, end),
    }


@app.get("/api/upcoming")
def get_upcoming(limit: int = 10):
    """The next `limit` events/due-tasks from today onward — the home tab's
    at-a-glance agenda. Completed tasks are left out."""
    today = date.today().isoformat()
    events = db.get_upcoming_events(today, limit)
    tasks = db.get_upcoming_tasks_due(today, limit)

    combined = [
        {"date": e["date"], "time": e.get("start_time") or "", "kind": "event", "data": e} for e in events
    ] + [
        {"date": t["due_date"], "time": t.get("due_time") or "", "kind": "task", "data": t} for t in tasks
    ]
    combined.sort(key=lambda c: (c["date"], c["time"] or "99:99"))
    combined = combined[:limit]

    return {
        "events": [c["data"] for c in combined if c["kind"] == "event"],
        "tasks": [c["data"] for c in combined if c["kind"] == "task"],
    }


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int):
    db.delete_event(event_id)
    return {"ok": True}


# ---------------- Briefing ----------------

@app.get("/api/briefing/{period}")
def briefing(period: str, ref: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None):
    if period not in ("daily", "weekly", "monthly", "custom"):
        raise HTTPException(400, "period는 daily/weekly/monthly/custom 중 하나여야 합니다.")

    today = date.today()

    if period == "custom":
        if not start or not end:
            raise HTTPException(400, "custom 기간은 start, end 파라미터가 필요합니다.")
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        label = f"{start_d.month}월 {start_d.day}일 ~ {end_d.month}월 {end_d.day}일"
    else:
        ref_date = date.fromisoformat(ref) if ref else today
        if period == "daily":
            start_d = end_d = ref_date
            label = "오늘" if ref_date == today else f"{ref_date.month}월 {ref_date.day}일"
        elif period == "weekly":
            start_d = ref_date - timedelta(days=ref_date.weekday())
            end_d = start_d + timedelta(days=6)
            label = "이번 주" if start_d <= today <= end_d else f"{start_d.month}월 {start_d.day}일~{end_d.month}월 {end_d.day}일"
        else:  # monthly
            start_d = ref_date.replace(day=1)
            if start_d.month == 12:
                end_d = start_d.replace(year=start_d.year + 1, month=1) - timedelta(days=1)
            else:
                end_d = start_d.replace(month=start_d.month + 1) - timedelta(days=1)
            label = "이번 달" if (start_d.year, start_d.month) == (today.year, today.month) else f"{start_d.year}년 {start_d.month}월"

    events = db.get_events_between(start_d.isoformat(), end_d.isoformat())
    tasks = db.get_tasks_due_between(start_d.isoformat(), end_d.isoformat())
    text = llm.generate_briefing(events, tasks, period, start_d.isoformat(), end_d.isoformat(), label)

    return {
        "period": period,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "events": events,
        "tasks": tasks,
        "briefing": text,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "llm_enabled": bool(os.environ.get("ANTHROPIC_API_KEY"))}


# ---------------- Google Calendar (read-only pull) ----------------

@app.get("/api/google/status")
def google_status():
    return {"configured": gcal.is_configured(), "connected": gcal.is_connected()}


@app.get("/api/google/auth-url")
def google_auth_url():
    try:
        return {"url": gcal.build_auth_url()}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/google/callback")
def google_callback(code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(f"<p>Google 연동이 취소됐습니다: {error}</p>")
    if not code:
        raise HTTPException(400, "code 파라미터가 없습니다.")
    gcal.exchange_code(code)
    return HTMLResponse(
        "<p>✅ Google 캘린더 연동 완료! 이 탭을 닫고 Smart Task Planner로 돌아가서 "
        "\"지금 동기화\"를 눌러주세요.</p>"
    )


@app.post("/api/google/sync")
def google_sync(days: int = 30):
    try:
        events = gcal.fetch_events(days_ahead=days)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    db.upsert_category(gcal.GOOGLE_CATEGORY, "event")
    for e in events:
        db.upsert_google_event(
            google_event_id=e["google_event_id"],
            title=e["title"],
            category=gcal.GOOGLE_CATEGORY,
            event_date=e["date"],
            start_time=e.get("start_time"),
            end_time=e.get("end_time"),
            note=e.get("note"),
        )
    return {"synced": len(events)}


@app.post("/api/google/disconnect")
def google_disconnect():
    gcal.disconnect()
    return {"ok": True}


# ---------------- Static frontend ----------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

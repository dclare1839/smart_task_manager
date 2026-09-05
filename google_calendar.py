"""Google Calendar integration — read-only pull from the user's primary
calendar into the local `events` table (source='google').

Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI in
.env, from a Google Cloud OAuth 2.0 Client (see README for setup steps).
Nothing in this app writes back to the user's real Google Calendar.
"""

import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = Path(__file__).parent / "google_token.json"
GOOGLE_CATEGORY = "Google 캘린더"


def _client_config():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        return None
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def is_configured() -> bool:
    return _client_config() is not None


def is_connected() -> bool:
    return TOKEN_PATH.exists()


def build_auth_url() -> str:
    from google_auth_oauthlib.flow import Flow

    config = _client_config()
    if not config:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI가 .env에 없습니다.")
    flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=config["web"]["redirect_uris"][0])
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    return auth_url


def exchange_code(code: str):
    from google_auth_oauthlib.flow import Flow

    config = _client_config()
    if not config:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI가 .env에 없습니다.")
    flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=config["web"]["redirect_uris"][0])
    flow.fetch_token(code=code)
    TOKEN_PATH.write_text(flow.credentials.to_json())


def _get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def fetch_events(days_ahead: int = 30) -> list:
    """Return upcoming events from the primary Google Calendar as plain dicts."""
    from datetime import datetime, timedelta, timezone

    from googleapiclient.discovery import build

    creds = _get_credentials()
    if not creds:
        raise RuntimeError("Google 계정이 연결되어 있지 않습니다.")

    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days_ahead)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        date_str = start.get("date") or (start.get("dateTime") or "")[:10]
        if not date_str:
            continue
        events.append(
            {
                "google_event_id": item["id"],
                "title": item.get("summary") or "(제목 없음)",
                "date": date_str,
                "start_time": (start.get("dateTime") or "")[11:16] or None,
                "end_time": (end.get("dateTime") or "")[11:16] or None,
                "note": item.get("location") or None,
            }
        )
    return events


def disconnect():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()

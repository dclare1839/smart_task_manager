"""Small text-parsing helpers shared by task/event creation.

Keeps two conventions explicit and independent of the LLM:
- "#tag" tokens anywhere in the text are pulled out as tags.
- "YYYY-MM-DD" or "YYYY-MM-DD HH:MM" anywhere in the text is treated as an
  authoritative date/time — no LLM guessing needed once this pattern shows up.
"""

import re
from datetime import date

_DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?")
_TAG_RE = re.compile(r"#(\S+)")


def extract_explicit_datetime(text: str):
    """Find an explicit date (optionally with a time) in `text`.

    Returns (date_str, time_str_or_None, text_with_match_removed).
    Returns (None, None, text) unchanged if nothing valid is found.
    """
    for m in _DATETIME_RE.finditer(text):
        date_str, time_str = m.group(1), m.group(2)
        try:
            y, mo, d = (int(x) for x in date_str.split("-"))
            date(y, mo, d)  # raises ValueError for e.g. 2026-13-40
        except ValueError:
            continue
        if time_str:
            hh, mm = (int(x) for x in time_str.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                continue
        cleaned = text[: m.start()] + text[m.end():]
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,:.")
        return date_str, time_str, cleaned
    return None, None, text


def extract_tags(text: str):
    """Pull out "#tag" tokens from `text`.

    Returns (tags_list, text_with_tags_removed).
    """
    tags = [t for t in _TAG_RE.findall(text) if t]
    cleaned = _TAG_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return tags, cleaned

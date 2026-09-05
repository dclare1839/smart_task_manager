"""Claude API integration for task categorization, schedule parsing, and briefings.

If ANTHROPIC_API_KEY is not set (or the call fails for any reason), every
function falls back to a simple keyword-based heuristic so the app keeps
working without an API key.
"""

import os
import re
import json

DEFAULT_CATEGORIES = ["영어", "업무", "학습", "운동/건강", "개인", "재정", "여가", "기타"]

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
# Categorization/parsing is a quick, simple classification task done on every
# add — a fast model keeps that from being the slow part of "add a task".
# Briefing generation (prose) still uses MODEL above for better quality.
FAST_MODEL = os.environ.get("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001")

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        _client = None
        return None
    try:
        import anthropic

        _client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:  # pragma: no cover
        print(f"[llm] Anthropic 클라이언트 초기화 실패: {e}")
        _client = None
    return _client


def _extract_text(resp) -> str:
    """Return the first text block's content. A response can start with a
    non-text block (e.g. a ThinkingBlock) before the actual text, so index 0
    isn't reliable."""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _call_claude_json(prompt: str, max_tokens: int = 500, model: str = FAST_MODEL):
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(resp)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print(f"[llm] Claude 호출 실패: {e}")
    return None


# ---------------- Keyword fallback ----------------

_KEYWORD_MAP = {
    "영어": ["영어", "ielts", "토익", "토플", "단어", "회화", "english"],
    "운동/건강": ["운동", "헬스", "러닝", "요가", "다이어트", "병원", "치과", "약국", "건강검진", "건강"],
    "업무": ["회의", "미팅", "보고서", "업무", "프로젝트", "출근", "회사"],
    "학습": ["공부", "강의", "책", "독서", "스터디", "코딩", "수업"],
    "재정": ["세금", "은행", "이체", "월급", "적금", "카드", "가계부"],
    "여가": ["영화", "여행", "게임", "친구", "약속", "데이트"],
}


def _fallback_category(text: str) -> str:
    lower = text.lower()
    for cat, keywords in _KEYWORD_MAP.items():
        if any(k in lower for k in keywords):
            return cat
    return "기타"


# ---------------- Public API ----------------

def categorize_task(text: str, existing_categories: list) -> str:
    categories_hint = existing_categories or DEFAULT_CATEGORIES
    prompt = f"""다음은 사용자가 입력한 할 일입니다: "{text}"

기존에 사용 중인 카테고리 목록: {json.dumps(categories_hint, ensure_ascii=False)}

이 할 일을 가장 적절한 카테고리 하나로 분류하세요.
- 기존 카테고리 중 잘 맞는 것이 있으면 그것을 그대로 사용하세요.
- 잘 맞는 카테고리가 없으면 새로운 카테고리를 짧은 한글 명사(2~4글자)로 만드세요.
- 너무 세분화하지 말고 상식적인 수준으로 묶으세요 (예: "영어", "운동/건강", "업무", "학습", "재정", "여가", "기타").

다음 JSON 형식으로만 답하세요: {{"category": "카테고리명"}}"""
    result = _call_claude_json(prompt)
    if result and "category" in result and result["category"].strip():
        return result["category"].strip()
    return _fallback_category(text)


def parse_schedule(text: str, existing_categories: list, reference_date: str) -> dict:
    categories_hint = existing_categories or DEFAULT_CATEGORIES
    prompt = f"""오늘 날짜는 {reference_date} 입니다.
다음은 사용자가 입력한 일정입니다: "{text}"

이 문장에서 일정 정보를 추출하세요.
기존에 사용 중인 카테고리 목록: {json.dumps(categories_hint, ensure_ascii=False)}

규칙:
- date는 반드시 YYYY-MM-DD 형식으로, 오늘 날짜를 기준으로 상대 표현(내일, 다음 주 등)을 계산하세요.
- start_time, end_time은 HH:MM 24시간 형식 문자열. 시간이 언급되지 않으면 null.
- category는 기존 카테고리 중 적절한 것을 쓰거나, 없으면 짧은 새 카테고리를 만드세요.
- note에는 장소 등 부가 설명이 있으면 넣고 없으면 null.

다음 JSON 형식으로만 답하세요:
{{"title": "일정 제목", "date": "YYYY-MM-DD", "start_time": "HH:MM 또는 null", "end_time": "HH:MM 또는 null", "category": "카테고리명", "note": "메모 또는 null"}}"""
    result = _call_claude_json(prompt, max_tokens=400)
    if result and result.get("date") and result.get("title"):
        result.setdefault("start_time", None)
        result.setdefault("end_time", None)
        result.setdefault("note", None)
        if not result.get("category"):
            result["category"] = _fallback_category(text)
        return result

    # Fallback: no LLM available (or parsing failed) — best effort today.
    return {
        "title": text,
        "date": reference_date,
        "start_time": None,
        "end_time": None,
        "category": _fallback_category(text),
        "note": None,
    }


def generate_briefing(
    events: list, tasks: list, period: str, start_date: str, end_date: str, period_label: str
) -> str:
    if not events and not tasks:
        return f"{period_label}({start_date} ~ {end_date}) 등록된 일정/할 일이 없습니다."

    # Chronological merge of events + due-dated tasks, used by both the LLM
    # prompt and the no-LLM fallback below.
    combined = [
        {"date": e["date"], "time": e.get("start_time") or "", "kind": "일정", "category": e["category"], "label": e["title"]}
        for e in events
    ] + [
        {
            "date": t["due_date"],
            "time": t.get("due_time") or "",
            "kind": "할일(완료)" if t.get("completed") else "할일",
            "category": t["category"],
            "label": t["text"],
        }
        for t in tasks
    ]
    combined.sort(key=lambda x: (x["date"], x["time"] or "99:99"))

    client = _get_client()
    if client is not None:
        lines_text = "\n".join(
            f"- [{c['kind']}] {c['date']} {c['time']} [{c['category']}] {c['label']}" for c in combined
        )
        prompt = f"""다음은 {period_label} ({start_date} ~ {end_date}) 동안의 일정/할 일 목록입니다:
{lines_text}

이 목록을 바탕으로 자연스러운 한국어 브리핑을 3~6문장으로 작성하세요.
- 일정과 할 일을 구분해서 언급하고, 카테고리별로 묶거나 임박한 순으로 짚어주세요.
- 이미 완료된 할 일은 가볍게만 언급하거나 생략하세요.
- 딱딱한 목록 나열이 아니라 비서가 브리핑하듯 자연스럽게 작성하세요."""
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return _extract_text(resp).strip()
        except Exception as e:
            print(f"[llm] 브리핑 생성 실패: {e}")

    # Fallback: simple chronological summary, no LLM.
    lines = [f"{period_label} 일정/할 일 ({start_date} ~ {end_date}), 총 {len(combined)}건"]
    for c in combined:
        time_str = c["time"] or "시간 미정"
        lines.append(f"[{c['kind']}] {c['date']} {time_str} · {c['category']} · {c['label']}")
    return "\n".join(lines)

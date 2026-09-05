# Smart Task Planner

할 일을 입력하면 Claude가 카테고리로 자동 분류해서 묶어주고, 일정을 입력하면 캘린더에
저장한 뒤 일별/주별/월별/기간별로 자연스러운 브리핑을 만들어주는 로컬 서버 앱입니다.

## 기능

- **할 일 자동 분류**: "아이엘츠 단어 공부하기" → `영어` 카테고리로 자동 분류.
  기존에 쓰던 카테고리가 있으면 재사용하고, 없으면 새 카테고리를 만듭니다.
- **카테고리 직접 관리**: "+ 새 카테고리"로 빈 카테고리를 미리 만들고, 할 일 추가 시
  드롭다운으로 직접 지정하거나, 만든 할 일을 다른 카테고리로 드래그 앤 드롭할 수 있습니다.
- **#태그**: 할 일 텍스트에 `#영어`처럼 적으면 태그로 인식해 텍스트에서 분리·저장됩니다.
- **완료 체크**: 각 할 일에 체크 버튼이 있어 눌러서 완료 처리(취소선 표시)할 수 있습니다.
- **명시적 날짜/시간 인식**: 할 일이나 일정에 `YYYY-MM-DD` 또는 `YYYY-MM-DD HH:MM`
  형식이 포함되면 무조건 그 날짜/시간으로 확정 반영합니다 (LLM이나 키워드 추측을 거치지 않음).
  예: `치과 예약 2026-09-10 15:00`, `아이엘츠 단어 공부하기 #영어 2026-09-10 08:00`
- **할 일도 캘린더에 노출**: 마감 날짜/시간이 있는 할 일은 캘린더 그리드와
  일별/주별/월별/기간별 스케줄에 일정과 함께 표시됩니다. 캘린더 뷰에서 바로 완료 처리도 가능합니다.
- **실제 월간 캘린더 그리드**: 날짜를 클릭해 그 날 기준으로 브리핑을 확인하고,
  카테고리별 색 점으로 일정(●)과 할 일(■)을 구분해서 봅니다.
- **일별/주별/월별/기간별 브리핑**: "기간 선택"으로 임의의 날짜 범위를 지정해
  스케줄을 조회할 수 있고, Claude가 자연스러운 문장으로 브리핑을 생성합니다.
- **API 키 없이도 동작**: `ANTHROPIC_API_KEY`가 없으면 키워드 기반 규칙으로
  대체 동작합니다 (품질은 낮지만 앱 자체는 정상 작동, 명시적 날짜/시간·태그 인식은 API 키와 무관하게 항상 정확합니다).
- **수정 가능**: 할 일 텍스트는 ✏️ 버튼으로 바로 고칠 수 있고, 카테고리 이름도 카테고리
  헤더의 ✏️로 이름을 바꾸면 그 카테고리를 쓰던 할 일/일정이 전부 새 이름으로 따라갑니다.
- **캘린더 상세보기**: 달력에서 날짜를 클릭하면 그 날의 일정/할 일이 모달 팝업으로 바로
  뜨고, 완료 처리·삭제도 그 자리에서 할 수 있습니다.
- **Google 캘린더 연동 (읽기 전용)**: 연결하면 기본 캘린더의 예정된 일정을 가져와
  `Google 캘린더` 카테고리로 표시합니다. 로컬 → Google 방향으로는 아무것도 쓰지 않습니다.
  설정 방법은 아래 "Google 캘린더 연동" 참고.

## 실행 방법

```bash
cd smart_task_planner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY 값을 채워주세요.

uvicorn main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속.

## 다른 기기(휴대폰 등)에서 접속하기

기본적으로 서버는 `127.0.0.1`에만 바인딩되어 이 컴퓨터에서만 접속됩니다. 외부에서 접속하려면:

1. **`.env`에 로그인 정보를 설정하세요** (`APP_USERNAME`, `APP_PASSWORD`). 비워두면 로그인 없이
   동작하는데, 로컬 전용일 때만 안전합니다.
2. 서버를 `--host 0.0.0.0`으로 띄우세요: `uvicorn main:app --host 0.0.0.0 --port 8000`
3. 접속 범위에 따라:
   - **같은 Wi-Fi (집 안)**: 이 컴퓨터의 로컬 IP로 접속 (`ipconfig getifaddr en0` 등으로 확인),
     예 `http://192.168.x.x:8000`
   - **외부(어디서든)**: 터널이 필요합니다. 예:
     ```bash
     brew install cloudflared
     cloudflared tunnel --url http://localhost:8000
     ```
     실행하면 `https://xxxx.trycloudflare.com` 같은 임시 공개 URL이 나옵니다. 로그인 정보를
     입력해야 접속되며, 계정 없는 quick tunnel은 이 컴퓨터/터널 프로세스가 살아있는 동안만
     유효하고 재시작 시 URL이 바뀝니다. 상시 운영하려면 Cloudflare 계정으로 named tunnel을
     만들어 고정 도메인을 연결하세요.

## Google 캘린더 연동

읽기 전용으로 기본(primary) Google 캘린더의 예정된 일정을 가져옵니다. 로컬 데이터를
Google로 보내는 기능은 없습니다.

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만들고
   **Google Calendar API**를 활성화하세요.
2. **APIs & Services → OAuth consent screen**에서 "External"로 동의 화면을 만들고
   (테스트 단계면 본인 이메일을 테스트 사용자로 추가), **Credentials**에서
   **OAuth client ID** (Application type: **Web application**)를 만드세요.
3. 승인된 리디렉션 URI에 `.env`의 `GOOGLE_REDIRECT_URI` 값과 정확히 같은 주소를
   등록하세요 (기본값 `http://localhost:8000/api/google/callback` — 포트가 다르면 맞춰주세요).
4. 발급된 **클라이언트 ID / 보안 비밀번호**를 `.env`의 `GOOGLE_CLIENT_ID` /
   `GOOGLE_CLIENT_SECRET`에 넣고 서버를 재시작하세요.
5. 캘린더 탭 상단의 "연결하기"를 눌러 본인 Google 계정으로 로그인/동의하면 연동됩니다.
   이후 "지금 동기화" 버튼으로 앞으로 30일치 일정을 가져옵니다.

이 프로젝트를 실제로 테스트할 때는 직접 자격 증명을 만들어 연결해야 합니다 —
Claude가 대신 Google 계정에 로그인하거나 동의할 수는 없습니다.

## 구조

```
smart_task_planner/
├── main.py          # FastAPI 라우트 (tasks / events / categories / schedule / briefing)
├── db.py            # SQLite 저장소 (planner.db 자동 생성, 스키마 마이그레이션 포함)
├── llm.py           # Claude API 호출 + 키워드 폴백
├── parsing.py       # "#태그" / "YYYY-MM-DD HH:MM" 추출 유틸
├── google_calendar.py  # Google Calendar OAuth + 읽기 전용 동기화
├── static/          # 프론트엔드 (바닐라 HTML/CSS/JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── requirements.txt
└── .env.example
```

## API 요약

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/tasks` | `{ "text": "...", "category": "..." }` → 태그/마감일시 추출 후 분류·저장 (`category` 생략 시 자동 분류) |
| GET | `/api/tasks?grouped=true` | 카테고리별로 묶인 할 일 목록 (빈 카테고리 포함) |
| PATCH | `/api/tasks/{id}` | `{ "text": "..." }` → 할 일 텍스트 수정 |
| PATCH | `/api/tasks/{id}/toggle` | 완료 체크 토글 |
| PATCH | `/api/tasks/{id}/category` | 카테고리 변경 (드래그 앤 드롭에 사용) |
| DELETE | `/api/tasks/{id}` | 삭제 |
| GET / POST | `/api/categories?kind=task\|event` | 카테고리 목록 조회 / 생성 |
| PATCH | `/api/categories/rename` | `{ "kind", "old_name", "new_name" }` → 이름 변경 (해당 카테고리를 쓰는 할 일/일정에 전부 반영) |
| POST | `/api/events` | `{ "text": "..." }` → 파싱 후 캘린더에 저장 |
| GET | `/api/events?start=YYYY-MM-DD&end=YYYY-MM-DD` | 기간 내 일정 조회 |
| GET | `/api/schedule?start=...&end=...` | 기간 내 일정 + 마감 할 일 통합 조회 (캘린더 그리드용) |
| DELETE | `/api/events/{id}` | 일정 삭제 |
| GET | `/api/briefing/{daily\|weekly\|monthly}?ref=YYYY-MM-DD` | 기간 브리핑 |
| GET | `/api/briefing/custom?start=YYYY-MM-DD&end=YYYY-MM-DD` | 임의 기간 브리핑 |
| GET | `/api/google/status` | `{ configured, connected }` |
| GET | `/api/google/auth-url` | Google 동의 화면 URL |
| GET | `/api/google/callback` | OAuth 리디렉션 처리 (브라우저가 자동으로 호출) |
| POST | `/api/google/sync?days=30` | 앞으로 N일치 일정을 가져와 저장 |
| POST | `/api/google/disconnect` | 연결 해제 |

## 참고

- 데이터는 `planner.db` (SQLite 파일)에 로컬로만 저장됩니다. 외부 전송 없음.
- 카테고리는 고정 목록이 아니라, Claude(또는 사용자)가 기존 카테고리를 재사용하거나
  필요시 새로 만드는 방식으로 자연스럽게 확장됩니다.
- 기존에 만든 `planner.db`가 있어도 서버를 다시 시작하면 새 컬럼(`due_date`, `due_time`,
  `tags`)이 자동으로 추가됩니다 (데이터 손실 없음).

# VibePy

[Live Demo](https://vibepy-gallery.onrender.com) | [English](README.md)

## 빠른 시작

갤러리 실행 (자연어 빌더 + ZIP 다운로드):

```bash
python3 -m venv ~/.venvs/vibepy
source ~/.venvs/vibepy/bin/activate
python3 -m pip install -U pip
python3 -m pip install git+https://github.com/johunsang/vibePy
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
```

브라우저에서 `http://127.0.0.1:9000` 접속

생성된 ZIP 실행 (한 줄 명령):

```bash
cd "/path/to/your/downloaded-app"
bash run.sh
```

브라우저에서 `http://127.0.0.1:8000/admin` 접속

VibePy는 **VibeLang**(Python 호환 DSL)과 **VibeWeb**(DB/API/UI 풀스택 JSON 스펙)을 결합한 JSON 우선, AI 친화적 스택입니다. CPython에서 실행되며 Python 생태계 전체를 사용할 수 있습니다.

## 목차

- 목적 / 사용 시점
- 비교표
- VibeLang 개요
- VibeLang 문법 (JSON IR)
- VibeLang `.vbl` 문법
- VibeLang API 호출 문법
- Hello AI Agent 예제
- VibeLang CLI
- VibeWeb 개요
- VibeWeb 스펙 (JSON)
- VibeWeb API
- VibeWeb 제한사항
- VibeWeb 디자인 문법
- VibeWeb UI 커스터마이징
- VibeWeb CLI
- AI 생성기 (DeepSeek API)
- 배포 (Render)

## 목적 / 사용 시점

- Python 라이브러리 및 C 확장을 유지하면서 AI 친화적 JSON 스펙으로 작성
- 단계별 제어, 검증, 재현 가능한 실행 보고서 적용
- 단일 DB/백엔드/프론트엔드 스펙(VibeWeb)으로 웹 앱 생성 및 운영

## 비교표

| 기존 방식             | VibePy                        |
| --------------------- | ----------------------------- |
| Python 코드 직접 작성 | LLM용 JSON / `.vbl` 스펙 작성 |
| 실행 흐름 감사 어려움 | 단계별 실행 보고서            |
| 웹 스택 별도 구성     | 단일 스펙에서 DB + API + UI   |
| 일관성 없는 재현성    | 결정론적 IR 및 런타임 훅      |

## VibeLang 개요

VibeLang은 JSON 우선, AI 전용 작성 언어로, Python AST로 컴파일되어 최대 호환성을 위해 CPython에서 실행됩니다.

VibeLang은 사람이 직접 작성하도록 설계되지 않았습니다. LLM이 생성하고 사람이 검토하도록 설계되었습니다.

주요 특징:

- CPython 실행 (stdlib + Python 패키지)
- 결정론적 JSON IR 및 `.vbl` S-표현식 문법
- 재시도, 타임아웃, 가드를 통한 단계별 계측
- 실행 보고서 출력

## VibeLang 문법 (JSON IR)

최소 프로그램:

```json
{
  "meta": { "name": "Echo" },
  "steps": [
    {
      "name": "upper",
      "params": ["text"],
      "guard": ["100%"],
      "return": { "call": "str.upper", "args": [{ "name": "text" }] }
    }
  ],
  "run": { "call": "upper", "args": [{ "literal": "hello" }] }
}
```

IR 형식 (v0.1):

- `meta`: 메타데이터 객체
- `imports`: Python import 목록
- `inputs`: 입력값 객체
- `steps`: 단계 정의 목록
- `run`: `__vbl_result__`를 생성하는 표현식, Python 블록 또는 구조화된 블록

단계 필드:

- `name`: 단계 함수명
- `params`: 매개변수 이름 목록
- `retry`: 실패 시 재시도 횟수
- `timeout`: 타임아웃 전 초
- `guard`: 문자열 출력에서 금지된 하위 문자열 목록
- `produces`: 선택적 출력 타입 문자열
- `body`: 문자열/목록 또는 구조화된 `block`으로 된 Python 문
- `return`: 표현식 객체 (`body`의 대안)

표현식 노드:

- `{"name": "x"}` 변수 참조
- `{"literal": 123}` 리터럴
- `{"call": "fn", "args": [..], "kwargs": {..}}`
- `{"attr": {"base": <expr>, "attr": "upper"}}`
- `{"index": {"base": <expr>, "index": <expr>}}`
- `{"list": [..]}`
- `{"tuple": [..]}`
- `{"dict": {"k": <expr>}}`
- `{"binop": {"op": "+", "left": <expr>, "right": <expr>}}`
- `{"validate": {"schema": <expr>, "data": <expr>}}`
- `{"parallel": [{"name": "a", "call": <expr>}, ...]}`
- `{"python": "raw_expr"}` 원시 Python 표현식

구조화된 문 (`body.block` 또는 `run.block`용):

- `{"set": {"name": "x", "value": <expr>}}`
- `{"expr": <expr>}`
- `{"return": <expr>}`
- `{"if": {"cond": <expr>, "then": [..], "else": [..]}}`
- `{"for": {"var": "x", "iter": <expr>, "body": [..]}}`
- `{"while": {"cond": <expr>, "body": [..], "else": [..]}}`
- `{"break": true}` / `{"continue": true}`
- `{"with": {"items": [{"context": <expr>, "as": "var"}], "body": [..]}}`
- `{"assert": {"cond": <expr>, "msg": <expr>}}`
- `{"raise": <expr>}` 또는 `{"raise": null}`
- `{"python": "raw Python lines"}` 원시 Python 블록

Import:

- `"json"`
- `{ "import": "numpy", "as": "np" }`
- `{ "from": "math", "import": ["sqrt", "ceil"] }`

## VibeLang `.vbl` 문법

예제 (`examples/echo.vbl`):

```
(meta (name "Echo Pipeline") (version "0.1"))
(input raw "  hello  ")

(step normalize
  (params text)
  (return (call (attr text strip))))

(step upper
  (params text)
  (guard "100%")
  (return (call (attr text upper))))

(run (upper (normalize raw)))
```

## VibeLang API 호출 문법

최소 HTTP GET + JSON 파싱:

```json
{
  "imports": ["urllib.request", "json"],
  "steps": [
    {
      "name": "fetch_json",
      "params": ["url"],
      "timeout": 10,
      "body": [
        "with urllib.request.urlopen(url, timeout=5) as resp:",
        "    data = resp.read().decode('utf-8')",
        "    return json.loads(data)"
      ]
    }
  ],
  "run": {
    "call": "fetch_json",
    "args": [{ "literal": "https://example.com" }]
  }
}
```

추가 API 예제:

- `examples/api-call/get_json.vbl.json`
- `examples/api-call/post_json.vbl.json`
- `examples/api-call/bearer_auth.vbl.json`
- `examples/api-call/timeout_retry.vbl.json`

## Hello AI Agent 예제

"LLM → VibeLang → 실행 → 보고서" 엔드투엔드 아티팩트:

- `examples/agent/prompt.txt`
- `examples/agent/generated.vbl.json`
- `examples/agent/report.json`

## VibeLang CLI

프로그램 검증:

```bash
python3 -m vibelang validate examples/echo.vbl
```

실행 및 결과 출력:

```bash
python3 -m vibelang run examples/echo.vbl
```

실행 및 보고서 JSON 출력:

```bash
python3 -m vibelang run examples/echo.vbl --json
```

Python 소스로 컴파일:

```bash
python3 -m vibelang compile examples/echo.vbl
```

`.vbl`을 JSON IR로 파싱:

```bash
python3 -m vibelang parse examples/echo.vbl
```

## VibeWeb 개요

VibeWeb은 단일 JSON 스펙을 사용하여 DB, 백엔드, 프론트엔드를 통합하는 최소한의 AI 우선 웹 프레임워크입니다.

주요 특징:

- SQLite 기반 데이터 모델
- 자동 CRUD JSON API
- 최소한의 HTML UI 페이지
- 단일 스펙으로 DB + API + UI 구동

## VibeWeb 스펙 (JSON)

예제:

```json
{
  "name": "Todo App",
  "db": {
    "path": "todo.db",
    "models": [
      {
        "name": "Todo",
        "fields": {
          "title": "text",
          "done": "bool",
          "created_at": "datetime"
        }
      }
    ]
  },
  "api": { "crud": ["Todo"] },
  "ui": {
    "admin": true,
    "admin_path": "/admin",
    "admin_auth": { "type": "basic", "username": "admin", "password": "admin" },
    "pages": [{ "path": "/", "model": "Todo", "title": "Todos" }]
  }
}
```

스펙 개요:

- `name`: 앱 이름
- `db.path`: SQLite 파일 경로
- `db.models`: 모델 및 필드 목록
- `api.crud`: API에 노출할 모델 목록
- `ui.pages`: UI 페이지 목록
- `ui.admin`: 관리자 페이지 활성화
- `ui.admin_path`: 관리자 URL 접두사 (기본값 `/admin`)
- `ui.admin_auth`: 관리자 페이지 기본 인증

필드 타입:

- `text`, `int`, `float`, `bool`, `datetime`, `json`, `ref:<Model>`

## VibeWeb API

라우트:

- `GET /api/<Model>` 행 목록
- `POST /api/<Model>` 행 생성 (JSON 또는 폼)
- `GET /api/<Model>/<id>` 행 조회
- `PUT|PATCH /api/<Model>/<id>` 행 수정
- `DELETE /api/<Model>/<id>` 행 삭제

쿼리 파라미터:

- `q`: 텍스트 필드 전체에서 하위 문자열 검색
- `sort`: `id` 또는 필드명
- `dir`: `asc` 또는 `desc`
- `limit`: 최대 행 수 (기본값 100, 최대 500)
- `offset`: 페이지네이션 오프셋
- `count=1`: `{data, count, offset, limit}` 반환
- `expand`: 확장할 참조 필드 (쉼표 구분, `field__ref`)
- `f_<field>`: 필드 필터 (텍스트는 `LIKE`, 나머지는 정확히 일치)

보안 + 제한:

- `VIBEWEB_API_KEY`: `X-API-Key` 또는 `Authorization: Bearer` 필요
- `VIBEWEB_RATE_LIMIT`: IP당 분당 요청 수 (기본값 120)
- `VIBEWEB_MAX_BODY_BYTES`: 최대 JSON/폼 본문 크기 (기본값 1MB)
- `VIBEWEB_AUDIT_LOG`: JSONL 감사 파일 경로 (기본값 `.logs/vibeweb-audit.log`)

## VibeWeb 제한사항

다음 용도에는 적합하지 않음:

- 고트래픽 프로덕션 앱
- 복잡한 프론트엔드 로직 (SPA)
- 멀티테넌트 인증 시스템

## VibeWeb 디자인 문법

관리자 UI는 단일 테마 맵의 Tailwind 클래스 문자열로 정의됩니다.

디자인 표면 (`vibeweb/server.py`):

- `TAILWIND_HEAD`: 외부 CSS (Tailwind CDN + Google Fonts) 및 토큰
- `THEME`: 레이아웃, 버튼, 테이블, 카드용 클래스 문자열

핵심 `THEME` 키:

- `body`, `grid_overlay`, `shell`, `container`, `topbar`, `brand`, `nav`, `nav_link`
- `surface`, `header`, `header_title`, `header_subtitle`, `header_tag`
- `panel`, `panel_title`, `form_grid`, `label`, `input`
- `btn_primary`, `btn_dark`, `btn_outline`
- `table_wrap`, `table`, `thead`, `tbody`, `row`, `cell`
- `grid`, `card`, `card_title`, `badge`, `link`, `link_muted`, `stack`

갤러리 디자인은 `examples/index.html` (GitHub Pages용 `docs/index.html`)에 있습니다.

페이지별 UI 옵션 (관리자 목록 보기):

```json
{
  "path": "/deals",
  "model": "Deal",
  "default_sort": "close_date",
  "default_dir": "asc",
  "default_filters": { "stage": "Open" },
  "visible_fields": ["account", "name", "amount", "stage", "close_date"]
}
```

## VibeWeb UI 커스터마이징

두 가지 빠른 방법:

1. Tailwind 클래스 (가장 빠름)
   - `docs/index.html` 및 `examples/index.html`의 클래스 편집
   - 레이아웃, 색상, 간격, 타이포그래피 제어

2. 외부 CSS (브랜드 수준)
   - UI 페이지의 `<head>`에 `<link rel="stylesheet" href="...">` 추가
   - HTML 구조는 그대로 유지하고 필요한 CSS만 오버라이드

참고:

- 갤러리 UI는 순수 HTML + Tailwind CDN이므로 편집이 즉시 반영됨
- DOM 구조를 안정적으로 유지하면 API 레이어는 영향받지 않음

## VibeWeb CLI

빠른 시작:

```bash
python3 -m vibeweb validate examples/todo/todo.vweb.json
python3 -m vibeweb run examples/todo/todo.vweb.json --host 127.0.0.1 --port 8000
```

예제 홈페이지 (루트에서 제공):

```bash
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
```

## AI 생성기 (DeepSeek API)

자연어 빌더:

```bash
export VIBEWEB_AI_BASE_URL="https://api.deepseek.com/v1"
export VIBEWEB_AI_MODEL="deepseek-chat"
export VIBEWEB_AI_API_KEY="YOUR_DEEPSEEK_KEY"
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
# 그런 다음 http://127.0.0.1:9000을 열고 양식을 사용하여 ZIP 다운로드
```

DeepSeek으로 스펙 생성:

```bash
python3 -m vibeweb ai --prompt "simple todo app with title and done"
```

관리자 자격 증명 오버라이드 (보안을 위해 권장):

```bash
export VIBEWEB_ADMIN_USER="admin"
export VIBEWEB_ADMIN_PASSWORD="change-me"
```

## 배포 (Render)

이 저장소에는 `/generate`가 포함된 갤러리 배포용 `render.yaml`이 있습니다.

필수 환경 변수 (Render 대시보드에서 설정):

- `VIBEWEB_AI_API_KEY`
- 선택사항: `VIBEWEB_AI_MODEL` (기본값 `deepseek-chat`)
- 선택사항: `VIBEWEB_AI_BASE_URL` (기본값 `https://api.deepseek.com/v1`)

---

## 기여하기

이 프로젝트에 기여하고 싶으시면 [GitHub Issues](https://github.com/johunsang/vibePy/issues)를 확인하거나 Pull Request를 제출해 주세요.

## 라이선스

이 프로젝트의 라이선스는 저장소를 참조하세요.

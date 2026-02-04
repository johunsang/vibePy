# VibePy

VibePy is a JSON-first, AI-friendly stack that combines **VibeLang** (a Python-compatible DSL) and **VibeWeb** (a full‑stack JSON spec for DB/API/UI). It runs on CPython and keeps the full Python ecosystem available.

## Contents
- Purpose / When You Need This
- Comparison Table
- VibeLang Overview
- VibeLang Syntax (JSON IR)
- VibeLang `.vbl` Syntax
- VibeLang API Call Syntax
- Hello AI Agent Example
- VibeLang CLI
- VibeWeb Overview
- VibeWeb Spec (JSON)
- VibeWeb API
- VibeWeb Limitations
- VibeWeb Design Syntax
- VibeWeb CLI
- Local LLM (GLM-4.7-Flash)

## Purpose / When You Need This
- Keep Python libraries and C-extensions, while authoring in AI-friendly JSON specs.
- Enforce step-level control, validation, and reproducible execution reports.
- Generate and operate web apps from a single DB/backend/frontend spec (VibeWeb).

## Comparison Table

| Conventional Approach | VibePy |
| --- | --- |
| Write Python code directly | Author JSON / `.vbl` specs for LLMs |
| Execution flow is hard to audit | Step-level execution report |
| Web stack is assembled separately | DB + API + UI from one spec |
| Reproducibility is inconsistent | Deterministic IR and runtime hooks |

## VibeLang Overview
VibeLang is a JSON-first, AI-only authoring language that compiles to Python AST and runs on CPython for maximum compatibility.

VibeLang is not designed for humans to write by hand. It is designed for LLMs to generate, and humans to review.

Key characteristics
- CPython execution (stdlib + Python packages)
- Deterministic JSON IR and `.vbl` S-expression syntax
- Step-level instrumentation with retries, timeouts, and guards
- Execution report output

## VibeLang Syntax (JSON IR)
Minimal program:
```json
{
  "meta": {"name": "Echo"},
  "steps": [
    {
      "name": "upper",
      "params": ["text"],
      "guard": ["100%"],
      "return": {"call": "str.upper", "args": [{"name": "text"}]}
    }
  ],
  "run": {"call": "upper", "args": [{"literal": "hello"}]}
}
```

IR format (v0.1)
- `meta`: object with metadata
- `imports`: list of Python imports
- `inputs`: object of input values
- `steps`: list of step definitions
- `run`: expression, Python block, or structured block that produces `__vbl_result__`

Step fields
- `name`: step function name
- `params`: list of parameter names
- `retry`: number of retries on failure
- `timeout`: seconds before timeout
- `guard`: list of forbidden substrings in string output
- `produces`: optional output type string
- `body`: Python statements as string/list or structured `block`
- `return`: expression object (alternative to `body`)

Expression nodes
- `{"name": "x"}` variable reference
- `{"literal": 123}` literal
- `{"call": "fn", "args": [..], "kwargs": {..}}`
- `{"attr": {"base": <expr>, "attr": "upper"}}`
- `{"index": {"base": <expr>, "index": <expr>}}`
- `{"list": [..]}`
- `{"tuple": [..]}`
- `{"dict": {"k": <expr>}}`
- `{"binop": {"op": "+", "left": <expr>, "right": <expr>}}`
- `{"validate": {"schema": <expr>, "data": <expr>}}`
- `{"parallel": [{"name": "a", "call": <expr>}, ...]}`
- `{"python": "raw_expr"}` for raw Python expressions

Structured statements (for `body.block` or `run.block`)
- `{"set": {"name": "x", "value": <expr>}}`
- `{"expr": <expr>}`
- `{"return": <expr>}`
- `{"if": {"cond": <expr>, "then": [..], "else": [..]}}`
- `{"for": {"var": "x", "iter": <expr>, "body": [..]}}`
- `{"while": {"cond": <expr>, "body": [..], "else": [..]}}`
- `{"break": true}` / `{"continue": true}`
- `{"with": {"items": [{"context": <expr>, "as": "var"}], "body": [..]}}`
- `{"assert": {"cond": <expr>, "msg": <expr>}}`
- `{"raise": <expr>}` or `{"raise": null}`
- `{"python": "raw Python lines"}` for raw Python blocks

Imports
- `"json"`
- `{ "import": "numpy", "as": "np" }`
- `{ "from": "math", "import": ["sqrt", "ceil"] }`

## VibeLang `.vbl` Syntax
Example (`examples/echo.vbl`):
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

## VibeLang API Call Syntax
Minimal HTTP GET + JSON parse:
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
  "run": { "call": "fetch_json", "args": [ { "literal": "https://example.com" } ] }
}
```

Additional API examples
- `examples/api-call/get_json.vbl.json`
- `examples/api-call/post_json.vbl.json`
- `examples/api-call/bearer_auth.vbl.json`
- `examples/api-call/timeout_retry.vbl.json`

## Hello AI Agent Example
Quick end-to-end artifacts for “LLM → VibeLang → execution → report”:
- `examples/agent/prompt.txt`
- `examples/agent/generated.vbl.json`
- `examples/agent/report.json`

## VibeLang CLI
Validate a program:
```bash
python3 -m vibelang validate examples/echo.vbl
```

Run and print result:
```bash
python3 -m vibelang run examples/echo.vbl
```

Run and print report JSON:
```bash
python3 -m vibelang run examples/echo.vbl --json
```

Compile to Python source:
```bash
python3 -m vibelang compile examples/echo.vbl
```

Parse `.vbl` to JSON IR:
```bash
python3 -m vibelang parse examples/echo.vbl
```

## VibeWeb Overview
VibeWeb is a minimal, AI-first web framework that unifies DB, backend, and frontend using a single JSON spec.

Key characteristics
- SQLite-backed data models
- Auto CRUD JSON API
- Minimal HTML UI pages
- One spec drives DB + API + UI

## VibeWeb Spec (JSON)
Example:
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
  "api": {"crud": ["Todo"]},
  "ui": {
    "admin": true,
    "admin_path": "/admin",
    "admin_auth": { "type": "basic", "username": "admin", "password": "admin" },
    "pages": [
      {"path": "/", "model": "Todo", "title": "Todos"}
    ]
  }
}
```

Spec overview
- `name`: app name
- `db.path`: sqlite file path
- `db.models`: list of models and fields
- `api.crud`: list of models to expose in API
- `ui.pages`: list of UI pages
- `ui.admin`: enable admin page
- `ui.admin_path`: admin URL prefix (default `/admin`)
- `ui.admin_auth`: basic auth for admin page

Field types
- `text`, `int`, `float`, `bool`, `datetime`, `json`, `ref:<Model>`

## VibeWeb API
Routes
- `GET /api/<Model>` list rows
- `POST /api/<Model>` create row (JSON or form)
- `GET /api/<Model>/<id>` get row
- `PUT|PATCH /api/<Model>/<id>` update row
- `DELETE /api/<Model>/<id>` delete row

Query params
- `q`: substring search across text fields
- `sort`: `id` or field name
- `dir`: `asc` or `desc`
- `limit`: max rows (default 100, max 500)
- `offset`: offset for pagination
- `count=1`: return `{data, count, offset, limit}`
- `expand`: comma-separated ref fields to expand (`field__ref`)
- `f_<field>`: field filter (text uses `LIKE`, others exact)

Security + limits
- `VIBEWEB_API_KEY`: require `X-API-Key` or `Authorization: Bearer`
- `VIBEWEB_RATE_LIMIT`: requests/minute per IP (default 120)
- `VIBEWEB_MAX_BODY_BYTES`: max JSON/form body size (default 1MB)
- `VIBEWEB_AUDIT_LOG`: JSONL audit file path (default `.logs/vibeweb-audit.log`)

## VibeWeb Limitations
Not intended for:
- High-traffic production apps
- Complex frontend logic (SPA)
- Multi-tenant auth systems

## VibeWeb Design Syntax
The admin UI is defined by Tailwind class strings in a single theme map.

Design surface (`vibeweb/server.py`)
- `TAILWIND_HEAD`: external CSS (Tailwind CDN + Google Fonts) and tokens
- `THEME`: class strings for layout, buttons, tables, and cards

Core `THEME` keys
- `body`, `grid_overlay`, `shell`, `container`, `topbar`, `brand`, `nav`, `nav_link`
- `surface`, `header`, `header_title`, `header_subtitle`, `header_tag`
- `panel`, `panel_title`, `form_grid`, `label`, `input`
- `btn_primary`, `btn_dark`, `btn_outline`
- `table_wrap`, `table`, `thead`, `tbody`, `row`, `cell`
- `grid`, `card`, `card_title`, `badge`, `link`, `link_muted`, `stack`

Gallery design lives in `examples/index.html` (and `docs/index.html` for GitHub Pages).

## VibeWeb CLI
Quick start
```bash
python3 -m vibeweb validate examples/todo/todo.vweb.json
python3 -m vibeweb run examples/todo/todo.vweb.json --host 127.0.0.1 --port 8000
```

Examples homepage (served from root):
```bash
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
```

## Local LLM (GLM-4.7-Flash)
Natural language builder:
```bash
export VIBEWEB_AI_BASE_URL="http://127.0.0.1:8080/v1"
export VIBEWEB_AI_MODEL="glm-4.7-flash"
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
# Then open http://127.0.0.1:9000 and use the form to download a ZIP.
```

Generate a spec with a local LLM:
```bash
python3 -m vibeweb ai --prompt "simple todo app with title and done"
```

Admin credential overrides (recommended for security):
```bash
export VIBEWEB_ADMIN_USER="admin"
export VIBEWEB_ADMIN_PASSWORD="change-me"
```

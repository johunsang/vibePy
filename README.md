# VibeLang (LLM-First Python-Compatible Language)

VibeLang is a new language designed for AI-only authoring that compiles to Python AST and runs on CPython for maximum package compatibility.

Key points
- CPython execution (stdlib + Python packages)
- JSON IR and `.vbl` S-expression syntax for deterministic, LLM-friendly generation
- Step-level instrumentation with retries, timeouts, and guards
- Execution report output

## Quick Start

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

## IR Format (v0.1)

Top-level fields
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

Imports
- `"json"`
- `{ "import": "numpy", "as": "np" }`
- `{ "from": "math", "import": ["sqrt", "ceil"] }`

---

# VibeWeb (AI-Friendly Full-Stack Framework)

VibeWeb is a minimal, AI-first web framework that unifies DB, backend, and frontend using a single JSON spec.

Key points
- SQLite-backed data models
- Auto CRUD JSON API
- Minimal HTML UI pages
- One spec drives DB + API + UI

Quick start
```bash
python3 -m vibeweb validate examples/todo/todo.vweb.json
python3 -m vibeweb run examples/todo/todo.vweb.json --host 127.0.0.1 --port 8000
```

Examples homepage (served from root):
```bash
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
```

Natural language builder (GLM 4.8 local):
```bash
export VIBEWEB_AI_BASE_URL="http://127.0.0.1:8080/v1"
export VIBEWEB_AI_MODEL="glm-4.8"
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
# Then open http://127.0.0.1:9000 and use the form to download a ZIP.
```

Generate a spec with a local LLM (GLM-4.7-Flash via OpenAI-compatible server):
```bash
python3 -m vibeweb ai --prompt "simple todo app with title and done"
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

Admin credential overrides (recommended for security):
```bash
export VIBEWEB_ADMIN_USER="admin"
export VIBEWEB_ADMIN_PASSWORD="change-me"
```

Field types
- `text`, `int`, `float`, `bool`, `datetime`

API routes
- `GET /api/<Model>` list rows
- `POST /api/<Model>` create row (JSON or form)
- `GET /api/<Model>/<id>` get row
- `PUT|PATCH /api/<Model>/<id>` update row
- `DELETE /api/<Model>/<id>` delete row

Structured statements (for `body.block` or `run.block`)
- `{"set": {"name": "x", "value": <expr>}}`
- `{"if": {"cond": <expr>, "then": [..], "else": [..]}}`
- `{"for": {"var": "x", "iter": <expr>, "body": [..]}}`
- `{"expr": <expr>}`
- `{"return": <expr>}`

## `.vbl` Syntax (S-Expression)
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

## Standard Library Bridge (`vibelang.std`)
- `vbl.log(message, **fields)` writes to the execution report
- `vbl.validate_jsonschema(data, schema)` (requires `jsonschema`)
- `vbl.validate_pydantic(model, data)` (requires `pydantic`)
- `vbl.parallel({...})` executes callables in a thread pool

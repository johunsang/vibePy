# VibeWeb Spec v1

## Goals
- AI-only authoring friendliness
- Single spec drives DB, API, and UI
- CPython runtime with zero custom dependencies

## Spec Structure

Top-level
- `spec_version`: must be `1`
- `name`: string
- `db`: object
- `api`: object
- `ui`: object

DB
- `db.path`: sqlite file path
- `db.models`: list of models

Model
- `name`: string
- `fields`: object of `field_name: field_type`

Field types
- `text`, `int`, `float`, `bool`, `datetime`, `json`, `ref:<Model>`

API
- `api.crud`: list of models exposed as CRUD endpoints
- `api.actions`: custom endpoints (HTTP + LLM)
- `api.hooks`: run actions after CRUD events (optional writeback)

UI
- `ui.pages`: list of pages
- `ui.admin`: enable admin page (boolean)
- `ui.admin_path`: admin URL prefix (default `/admin`)
- `ui.admin_auth`: `{ "type": "basic", "username": "...", "password": "..." }`

Admin credential overrides (env):
- `VIBEWEB_ADMIN_USER`
- `VIBEWEB_ADMIN_PASSWORD`

Page
- `path`: string starting with `/`
- `model`: model name
- `title`: optional title
- `fields`: optional subset of fields to show

## Example
```json
{
  "spec_version": 1,
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

## Routes
- `GET /api/<Model>`
- `POST /api/<Model>`
- `GET /api/<Model>/<id>`
- `PUT /api/<Model>/<id>`
- `PATCH /api/<Model>/<id>`
- `DELETE /api/<Model>/<id>`
- `GET /api/meta` (spec + runtime metadata)
- `GET /healthz` (health check)

Query params (list)
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
- `VIBEWEB_OUTBOUND_ALLOW_HOSTS`: comma-separated host allowlist for outbound HTTP/LLM actions (or `*`)

## Actions (Custom Endpoints)
Actions let you add behavior beyond CRUD without leaving JSON.

Action fields:
- `name`: unique action name
- `kind`: `http`, `llm`, `db`, `value`, or `flow`
- `method`: `GET|POST|PUT|PATCH|DELETE`
- `path`: endpoint path (default: `/api/actions/<name>`)
- `auth`: `api|none|admin`

HTTP action:
- `http.url`: outbound URL
- `http.headers`: optional headers (string values support templates like `${env.VIBEWEB_AI_API_KEY}` and `${input.prompt}`)
- `http.body`: JSON body (defaults to the incoming request JSON)
- `http.timeout_s`, `http.retries`, `http.expect`

LLM action (OpenAI-compatible or Ollama):
- `llm.provider`: `openai` or `ollama`
- `llm.base_url`, `llm.model`
- `llm.api_key_env`: env var name (default `VIBEWEB_AI_API_KEY`)
- `llm.messages`: list of `{role, content}` (content supports `${input.*}` templates)
- `llm.output`: `text` or `json`

DB action (internal CRUD, no outbound HTTP):
- `db.op`: `get|list|insert|update|delete`
- `db.model`: model name
- `db.id`: required for `get|update|delete` (supports templates)
- `db.data`: required for `insert` (supports templates)
- `db.patch`: required for `update` (supports templates)
- `db.limit`, `db.offset`, `db.order_by`: list paging and ordering

Value action (return JSON without DB/HTTP/LLM):
- `value.data`: any JSON (supports `${...}` templates)
- `value.status`: optional HTTP status (default 200)
- `value.ok`: optional boolean (default true)

Flow action (workflow orchestration):
- `flow.vars`: optional initial variables (object)
- `flow.steps`: list of steps (run in order)
- `flow.return_step`: optional step id to return as the action result

Flow step fields:
- `id`: step id (identifier)
- `use`: action name to execute
- `input`: optional step input override (defaults to the flow input)
- `when`: optional condition (see Condition DSL below)
- `on_error`: `stop` (default), `continue`, or `return`
- `set`: optional variables to set after the step runs (values support `${...}` templates)

Example: multi-step workflow with variables and conditional steps
```json
{
  "api": {
    "actions": [
      {"name": "create_invoice", "kind": "db", "db": {"op": "insert", "model": "Invoice", "data": {"number": "INV-${input.deal_id}", "total": "${input.amount}"}}},
      {"name": "notify_slack", "kind": "http", "http": {"url": "${env.SLACK_WEBHOOK_URL}", "body": {"text": "Invoice ${input.invoice_number} created"}}},
      {
        "name": "close_won_workflow",
        "kind": "flow",
        "flow": {
          "vars": {"invoice_number": ""},
          "steps": [
            {
              "id": "invoice",
              "use": "create_invoice",
              "on_error": "continue",
              "set": {"invoice_number": "${steps.invoice.data.number}"}
            },
            {
              "id": "slack",
              "use": "notify_slack",
              "when": {"steps.invoice.ok": true},
              "input": {"invoice_number": "${vars.invoice_number}"}
            }
          ],
          "return_step": "invoice"
        }
      }
    ]
  }
}
```

Example: LLM endpoint that returns JSON
```json
{
  "api": {
    "crud": ["Deal"],
    "actions": [
      {
        "name": "summarize_deal",
        "kind": "llm",
        "method": "POST",
        "path": "/api/actions/summarize_deal",
        "auth": "api",
        "llm": {
          "provider": "openai",
          "base_url": "https://api.deepseek.com/v1",
          "model": "deepseek-chat",
          "api_key_env": "VIBEWEB_AI_API_KEY",
          "messages": [
            {"role": "system", "content": "Return ONLY JSON."},
            {"role": "user", "content": "Summarize: ${input.text}. Return {\"summary\": \"...\"}."}
          ],
          "temperature": 0.2,
          "output": "json"
        }
      }
    ]
  }
}
```

Call it:
```bash
curl -s -X POST http://127.0.0.1:8000/api/actions/summarize_deal \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $VIBEWEB_API_KEY" \
  -d '{"text":"Deal with ACME for $12,000 annual."}'
```

## Hooks (After CRUD Events)
Hooks run actions after CRUD events and can optionally write fields back to the same row.

Hook fields:
- `model`: model name
- `event`: `after_create|after_update|after_delete`
- `action`: action name
- `mode`: `sync` or `async`
- `writeback`: optional list of fields to update on the same model from the action result
- `when_changed`: optional list of fields (only applies to `after_update`). If none of these fields changed, the hook is skipped.
- `when`: optional condition. Shorthand form `{field:value}` means `row.<field> == value`. For complex logic use the Condition DSL.

### Condition DSL
Conditions are safe JSON objects evaluated against a context.

Available context roots:
- `row`: the current row (normalized)
- `old`: previous row (after_update only, normalized)
- `payload`: incoming payload (if any)
- `input`: the full hook input object (event/source/model/row_id/row/old/payload)
- `steps`: (flow only) step results
- `vars`: (flow only) workflow variables

Forms:
- Equality map (AND):
  - `{"row.stage": "Closed Won", "steps.invoice.ok": true}`
- Operators:
  - `{"$and":[cond,cond]}`
  - `{"$or":[cond,cond]}`
  - `{"$not": cond}`
  - `{"$eq":["expr", value]}`, `{"$ne":["expr", value]}`
  - `{"$gt":["expr", number]}`, `{"$gte":["expr", number]}`, `{"$lt":["expr", number]}`, `{"$lte":["expr", number]}`
  - `{"$in":["expr", [values...]]}`
  - `{"$contains":["expr", value]}` (string substring, list membership, or dict key)
  - `{"$regex":["expr", "pattern"]}`
  - `{"$exists":"expr"}` or `{"$exists":["expr", true|false]}`
  - `{"$truthy":"expr"}`

Example: After creating a `Deal`, call an LLM action and write `summary` back onto the row
```json
{
  "db": {
    "models": [
      {"name": "Deal", "fields": {"name": "text", "amount": "float", "summary": "text"}}
    ]
  },
  "api": {
    "crud": ["Deal"],
    "actions": [
      {
        "name": "deal_summary",
        "kind": "llm",
        "method": "POST",
        "path": "/api/actions/deal_summary",
        "auth": "api",
        "llm": {
          "provider": "openai",
          "base_url": "https://api.deepseek.com/v1",
          "model": "deepseek-chat",
          "api_key_env": "VIBEWEB_AI_API_KEY",
          "messages": [
            {"role": "system", "content": "Return ONLY JSON."},
            {"role": "user", "content": "Given this deal: ${input.row}. Return {\"summary\":\"...\"}."}
          ],
          "output": "json"
        }
      }
    ],
    "hooks": [
      {"model": "Deal", "event": "after_create", "action": "deal_summary", "mode": "async", "writeback": ["summary"]}
    ]
  }
}
```

Example: Workflow hook with internal DB write
```json
{
  "api": {
    "actions": [
      {
        "name": "create_invoice_from_deal",
        "kind": "db",
        "method": "POST",
        "path": "/api/actions/create_invoice_from_deal",
        "auth": "api",
        "db": {
          "op": "insert",
          "model": "Invoice",
          "data": {
            "account": "${input.row.account}",
            "number": "INV-${input.row_id}",
            "status": "Open",
            "total": "${input.row.amount}"
          }
        }
      }
    ],
    "hooks": [
      {
        "model": "Deal",
        "event": "after_update",
        "action": "create_invoice_from_deal",
        "mode": "async",
        "when_changed": ["stage"],
        "when": {"$and": [{"row.stage": "Closed Won"}, {"$gt": ["row.amount", 0]}]}
      }
    ]
  }
}
```

## API Call Examples
List rows:
```bash
curl -s http://127.0.0.1:8000/api/Todo
```

Create row:
```bash
curl -s -X POST http://127.0.0.1:8000/api/Todo \
  -H "Content-Type: application/json" \
  -d '{"title":"Ship demo","done":false}'
```

Update row:
```bash
curl -s -X PATCH http://127.0.0.1:8000/api/Todo/1 \
  -H "Content-Type: application/json" \
  -d '{"done":true}'
```

Delete row:
```bash
curl -s -X DELETE http://127.0.0.1:8000/api/Todo/1
```

## Design Customization
VibeWeb is intentionally **spec-driven**: customize the look without patching Python code.

Use `ui.theme`:
- `ui.theme.css_urls`: add external CSS (`https://...`) or a local static path (`/static/...`).
- `ui.theme.tailwind_config`: merge additional Tailwind tokens (colors, fonts, etc).
- `ui.theme.classes`: override any theme key with a class string.

Example:
```json
{
  "ui": {
    "theme": {
      "css_urls": [
        "https://unpkg.com/@picocss/pico@2.0.6/css/pico.min.css"
      ],
      "tailwind_config": {
        "theme": {
          "extend": {
            "fontFamily": {
              "display": ["Urbanist", "sans-serif"]
            }
          }
        }
      },
      "classes": {
        "layout.page": "bg-slate-50 text-slate-900",
        "card": "rounded-2xl border border-slate-900/10 bg-white shadow-sm"
      }
    }
  }
}
```

Gallery homepage design lives in `examples/index.html`.

## Admin UI Options (Per Page)
You can tune the admin list view on each page:
- `default_query`: pre-filled search query.
- `default_sort`: initial sort field (e.g. `created_at`).
- `default_dir`: `asc` or `desc`.
- `default_filters`: object of field → value.
- `visible_fields`: show only these columns.
- `hidden_fields`: hide these columns.

Example:
```json
{
  "path": "/invoices",
  "model": "Invoice",
  "default_sort": "due_date",
  "default_dir": "asc",
  "default_filters": {"status": "Open"},
  "visible_fields": ["account", "number", "status", "total", "due_date", "paid"]
}
```

## Notes
- Uses SQLite via stdlib `sqlite3`.
- HTML UI is intentionally minimal and generated on the fly.

## AI Generator (GLM-4.7-Flash or DeepSeek)
Generate a spec from a prompt using an OpenAI-compatible endpoint.

Cloud (DeepSeek):
```bash
export VIBEWEB_AI_BASE_URL="https://api.deepseek.com/v1"
export VIBEWEB_AI_MODEL="deepseek-chat"
export VIBEWEB_AI_API_KEY="..."

python3 -m vibeweb ai --prompt "Inventory app with items and suppliers"
```

Local (GLM-4.7-Flash via llama.cpp server):
```bash
bash scripts/run_glm47_server.sh

export VIBEWEB_AI_BASE_URL="http://127.0.0.1:8080/v1"
export VIBEWEB_AI_MODEL="glm-4.7-flash"

python3 -m vibeweb ai --prompt "CRM app with accounts, contacts, deals, invoices"
```

The Gallery `POST /generate` endpoint uses the same `VIBEWEB_AI_*` environment variables.

## Roadmap
- v0.2: Relationship helpers and richer admin filters
- v0.3: Async tasks and background jobs
- v0.4: Static export (React or static HTML)
- v1.0: Stable spec + plugin system

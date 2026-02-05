# VibeWeb Spec v0.1

## Goals
- AI-only authoring friendliness
- Single spec drives DB, API, and UI
- CPython runtime with zero custom dependencies

## Spec Structure

Top-level
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
- Admin UI uses Tailwind CDN classes defined in `vibeweb/server.py`.
- Edit `TAILWIND_HEAD` to change fonts, colors, or add external CSS.
- Edit `THEME` to change the class strings for layout, buttons, tables, and cards.
- Gallery homepage design is in `examples/index.html` (and `docs/index.html` for GitHub Pages).

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

## AI Generator (DeepSeek API)
Generate a spec from a prompt using DeepSeek API.

OpenAI-compatible (DeepSeek):
```bash
python3 -m vibeweb ai --prompt "Inventory app with items and suppliers"
```

Environment variables:
- `VIBEWEB_AI_BASE_URL` (default: `https://api.deepseek.com/v1`)
- `VIBEWEB_AI_MODEL` (default: `deepseek-chat`)
- `VIBEWEB_AI_API_KEY` (optional)

## Roadmap
- v0.2: Relationship helpers and richer admin filters
- v0.3: Async tasks and background jobs
- v0.4: Static export (React or static HTML)
- v1.0: Stable spec + plugin system

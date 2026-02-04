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
- `text`, `int`, `float`, `bool`, `datetime`

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

## Notes
- Uses SQLite via stdlib `sqlite3`.
- HTML UI is intentionally minimal and generated on the fly.

## AI Generator (Local GLM-4.7-Flash)
Generate a spec from a prompt using a local LLM server.

OpenAI-compatible (llama.cpp-style):
```bash
python3 -m vibeweb ai --prompt "Inventory app with items and suppliers"
```

Environment variables:
- `VIBEWEB_AI_BASE_URL` (default: `http://127.0.0.1:8080/v1`)
- `VIBEWEB_AI_MODEL` (default: `glm-4.7-flash`)
- `VIBEWEB_AI_API_KEY` (optional)

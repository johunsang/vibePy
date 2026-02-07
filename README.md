# VibePy

[![CI](https://github.com/johunsang/vibePy/actions/workflows/ci.yml/badge.svg)](https://github.com/johunsang/vibePy/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/tag/johunsang/vibePy?label=release)](https://github.com/johunsang/vibePy/releases)

JSON-first, AI-friendly stack that combines **VibeLang** (a Python-compatible DSL) and **VibeWeb** (a full-stack JSON spec for DB/API/UI). Runs on CPython with the full Python ecosystem available.

[Live Demo](https://vibepy-gallery.onrender.com)

## Why VibePy?

| Conventional Approach | VibePy |
| --- | --- |
| Write Python code directly | Author JSON / `.vbl` specs for LLMs |
| Execution flow is hard to audit | Step-level execution report |
| Web stack is assembled separately | DB + API + UI from one spec |
| Reproducibility is inconsistent | Deterministic IR and runtime hooks |

## Quick Start

```bash
git clone https://github.com/johunsang/vibePy.git && cd vibePy
pip install -r requirements.txt

# VibeLang
python3 -m vibelang run examples/echo.vbl

# VibeWeb
python3 -m vibeweb run examples/todo/todo.vweb.json --host 127.0.0.1 --port 8000
```

## VibeLang

JSON-first, AI-only authoring language that compiles to Python AST and runs on CPython.

- CPython execution (stdlib + Python packages)
- Deterministic JSON IR and `.vbl` S-expression syntax
- Step-level instrumentation with retries, timeouts, and guards
- Execution report output

Example (`.vbl`):
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

```bash
python3 -m vibelang validate examples/echo.vbl   # validate
python3 -m vibelang run examples/echo.vbl         # run
python3 -m vibelang run examples/echo.vbl --json  # run with report
python3 -m vibelang compile examples/echo.vbl     # compile to Python
python3 -m vibelang parse examples/echo.vbl       # parse to JSON IR
```

Full syntax reference: [SPEC.md](SPEC.md)

## VibeWeb

Minimal, AI-first web framework that unifies DB, backend, and frontend using a single JSON spec.

- SQLite-backed data models
- Auto CRUD JSON API with actions and hooks
- Minimal HTML UI with admin pages
- One spec drives DB + API + UI

Example:
```json
{
  "name": "Todo App",
  "spec_version": 1,
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
    "pages": [
      {"path": "/", "model": "Todo", "title": "Todos"}
    ]
  }
}
```

```bash
python3 -m vibeweb validate examples/todo/todo.vweb.json                       # validate
python3 -m vibeweb run examples/todo/todo.vweb.json --host 127.0.0.1 --port 8000  # run app
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000           # gallery
```

Full spec reference: [VIBEWEB.md](VIBEWEB.md)

## AI Generator

Natural language builder (recommended: local GLM-4.7-Flash):
```bash
bash scripts/run_glm47_server.sh
export VIBEWEB_AI_BASE_URL="http://127.0.0.1:8080/v1"
export VIBEWEB_AI_MODEL="glm-4.7-flash"

python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
# Open http://127.0.0.1:9000 and use the form to download a ZIP.
```

Cloud option (DeepSeek):
```bash
export VIBEWEB_AI_BASE_URL="https://api.deepseek.com/v1"
export VIBEWEB_AI_MODEL="deepseek-chat"
export VIBEWEB_AI_API_KEY="YOUR_DEEPSEEK_KEY"
python3 -m vibeweb gallery --root examples --host 127.0.0.1 --port 9000
```

Generate a spec directly:
```bash
python3 -m vibeweb ai --prompt "simple todo app with title and done"
```

## Deploy (Render)

This repo includes `render.yaml` to deploy the gallery with `/generate`.

Required env vars (set in Render dashboard):
- `VIBEWEB_AI_API_KEY`
- Optional: `VIBEWEB_AI_MODEL` (default `deepseek-chat`)
- Optional: `VIBEWEB_AI_BASE_URL` (default `https://api.deepseek.com/v1`)

## Docs

| Document | Description |
| --- | --- |
| [SPEC.md](SPEC.md) | VibeLang IR spec (JSON IR + `.vbl`) |
| [VIBEWEB.md](VIBEWEB.md) | VibeWeb spec (DB/API/UI/actions/hooks) |
| [AI_EDITING.md](AI_EDITING.md) | AI editing rules and best practices |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [RELEASE.md](RELEASE.md) | Release process |

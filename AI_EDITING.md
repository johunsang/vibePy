# AI Editing Guide (VibeWeb + VibeLang)

VibePy is optimized for LLM authoring and human review.
This guide documents the rules that keep edits safe, diffable, and machine-friendly.

## Core Principles

- Prefer JSON specs over ad-hoc code edits.
- Make intent explicit:
  - add actions instead of hiding logic in templates
  - add flow steps instead of implicit branching
- Keep changes local:
  - modify a single model/page/action at a time
  - validate after every edit

## Canonical JSON

Use `vibeweb fmt` to keep diffs stable:
```bash
python3 -m vibeweb fmt app.vweb.json --write
```

To enforce formatting in CI:
```bash
python3 -m vibeweb fmt app.vweb.json --check
```

## Templating Rules

Template syntax is `${path}`.

Examples:
- `"INV-${input.row_id}"` renders to a string
- `"${input.row.amount}"` returns a typed value (number/bool/object), not a string

Common roots:
- `input`: request JSON body or hook payload
- `env`: environment variables
- `row`: current row (hooks)
- `old`: previous row (after_update hooks)
- `steps`: flow step outputs (flow actions)
- `vars`: flow variables (flow actions)

## VibeWeb Spec Editing Rules

1. Always set `spec_version: 1`.
2. Models:
   - Names and field names should be identifiers: `Deal`, `Invoice`, `created_at`.
   - Field types: `text|int|float|bool|datetime|json|ref:<Model>`.
3. Prefer actions for behavior:
   - `http` for outbound calls
   - `llm` for model calls
   - `db` for internal CRUD
   - `flow` for workflows
   - `value` for simple constant responses
4. Prefer hooks for automation:
   - `api.hooks` runs after CRUD events
   - use `when_changed` to avoid unnecessary work
   - use `when` + the Condition DSL for guardrails
5. Prefer spec-driven design edits:
   - `ui.theme.css_urls` for external CSS
   - `ui.theme.classes` for Tailwind class overrides
   - `ui.theme.tailwind_config` for tokens and theme extensions

## VibeLang IR Editing Rules

VibeLang is an AI-only authoring format that compiles to Python AST and runs on CPython.
The canonical format is JSON IR (`.vbl.json`). See `SPEC.md` for the full schema.

Rules that make LLM edits predictable:
1. Keep step names stable.
If you rename steps, you must update every call site in `run` (and in other steps).
2. Prefer explicit nodes over raw Python strings.
- Use `{"name":"x"}` for variables.
- Use `{"literal":"..."}`
- Use `{"call": ..., "args": [...]}` for calls.
Raw Python (`{"python":"..."}` or plain string expressions) should be a last resort.
3. Keep step bodies deterministic.
Avoid hidden I/O or global state unless it is required, and log it if it matters.
4. Validate after every change:
```bash
python3 -m vibelang validate program.vbl.json
```

## Condition DSL (Safe Branching)

Conditions are JSON objects evaluated against a context.

Supported patterns:
- Equality map (implicit AND):
  - `{"row.stage": "Closed Won", "steps.invoice.ok": true}`
- Operator form:
  - `{"$and":[cond,cond]}`
  - `{"$gt":["row.amount", 0]}`
- List form (implicit AND):
  - `[cond, cond, ...]`

## Flow Actions (Workflows)

Use `flow` actions when behavior needs:
- multiple steps
- retries/timeouts per step
- parallelizable calls (mark consecutive steps with `"parallel": true`)

Each flow step is explicitly named (`id`) and always produces a structured result:
`{"ok": bool, "status": int, "data": ...}`.

## Validation Loop

After every spec edit:
```bash
python3 -m vibeweb validate app.vweb.json
```

If you changed actions/hooks/flows, also do a quick runtime smoke test:
```bash
python3 -m vibeweb run app.vweb.json --host 127.0.0.1 --port 8000
```

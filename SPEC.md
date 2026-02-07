# VibeLang IR Spec (Draft)

VibeLang is an AI-only authoring format that compiles to Python AST and runs on CPython.
This spec documents:
- the JSON IR format (`.vbl.json`)
- the S-expression front-end (`.vbl`) that parses to the same JSON IR

If you want rules for AI-safe diffs and edits, see `AI_EDITING.md`.

## Goals
- AI-only authoring (LLM generates, humans review)
- 100% Python ecosystem compatibility by running on CPython (stdlib + packages + C-extensions)
- Deterministic, structured programs that are easy to diff and validate
- Step-level observability and control (retry, timeout, guard) with an execution report

## Non-Goals
- A human-friendly programming language
- A custom VM/bytecode or replacing CPython

## Execution Model (High Level)
- `inputs` are injected as Python variables.
- `steps` compile to Python functions decorated with `@step(...)`.
- `run` is evaluated to produce `__vbl_result__`.
- An execution report captures:
  - step attempts, durations, and errors
  - structured events
  - the final result

## File Formats
- `.vbl.json`: JSON IR (canonical, deterministic)
- `.vbl`: S-expression syntax (compiles to the same JSON IR)

## JSON IR (Top Level)
The IR is a single JSON object with:
- `meta`: optional object (free-form metadata)
- `imports`: optional list (Python imports)
- `inputs`: optional object (input values)
- `steps`: optional list (step definitions)
- `run`: required (expression or block)

Minimal example:
```json
{
  "meta": {"name": "Echo"},
  "inputs": {"raw": "hello"},
  "steps": [
    {
      "name": "upper",
      "params": ["text"],
      "guard": ["100%"],
      "return": {
        "call": {"attr": {"base": {"name": "text"}, "attr": "upper"}},
        "args": []
      }
    }
  ],
  "run": {"call": "upper", "args": [{"name": "raw"}]}
}
```

### Imports
`imports` entries can be:
- `"json"` -> `import json`
- `{ "import": "numpy", "as": "np" }` -> `import numpy as np`
- `{ "from": "math", "import": ["sqrt", "ceil"] }` -> `from math import sqrt, ceil`

### Inputs
`inputs` is an object of identifier -> JSON value. At runtime, each key becomes a Python variable:
```json
{ "inputs": { "raw": "hello" } }
```
Compiles to:
```python
raw = __vbl_inputs__.get("raw")
```

## Steps
Each step is an object:
- `name`: required identifier (function name)
- `params`: optional list of identifiers
- `retry`: optional integer (number of retries on failure)
- `timeout`: optional integer seconds (best-effort)
- `guard`: optional list of forbidden substrings (checked on string outputs)
- `produces`: optional string (informational)
- `body`: Python source lines (string or list of strings), or structured `block`
- `return`: expression object (alternative to `body`)

Exactly one of `body` or `return` must exist.

### Step Body Variants
Python lines:
```json
{
  "name": "fetch",
  "params": ["url"],
  "timeout": 10,
  "body": [
    "import urllib.request",
    "with urllib.request.urlopen(url, timeout=5) as resp:",
    "    return resp.read().decode('utf-8')"
  ]
}
```

Structured block:
```json
{
  "name": "normalize",
  "params": ["text"],
  "body": { "block": [
    {"set": {"name": "t", "value": {"call": "str.strip", "args": [{"name": "text"}]}}},
    {"return": {"name": "t"}}
  ] }
}
```

## Expressions
An expression is either a JSON literal (`null|bool|number`) or an object node.

Important:
- Use `{"literal": "..."}` for string literals.
- A plain JSON string is treated as raw Python source. Prefer explicit nodes (`name`, `literal`, `call`, etc) for AI safety.

Supported expression nodes:
- `{"name": "x"}`: variable reference
- `{"literal": "hello"}`: literal value (string/number/bool/null)
- `{"python": "raw_expr"}`: raw Python expression
- `{"call": <expr|string>, "args": [<expr>...], "kwargs": { "k": <expr> } }`
- `{"attr": {"base": <expr>, "attr": "upper"}}`
- `{"index": {"base": <expr>, "index": <expr>}}`
- `{"list": [<expr>...]}` / `{"tuple": [<expr>...]}`
- `{"dict": {"k": <expr>}}` or `{"dict": [{"key": <expr>, "value": <expr>}, ...]}`
- `{"binop": {"op": "+", "left": <expr>, "right": <expr>}}`
- `{"validate": {"schema": <expr>, "data": <expr>}}` (JSON Schema)
- `{"validate": {"model": <expr>, "data": <expr>}}` (Pydantic model)
- `{"parallel": [{"name": "a", "call": <expr>}, ...]}` (concurrent tasks)

### Validation Expression
JSON Schema:
```json
{"validate": {"schema": {"name": "MySchema"}, "data": {"name": "payload"}}}
```
Pydantic model:
```json
{"validate": {"model": {"name": "OrderModel"}, "data": {"name": "payload"}}}
```

### Parallel Expression
```json
{
  "parallel": [
    {"name": "a", "call": {"call": "work_a", "args": []}},
    {"name": "b", "call": {"call": "work_b", "args": []}}
  ]
}
```
This compiles to `vbl.parallel({ "a": (lambda: work_a()), "b": (lambda: work_b()) })`.

## Statements (Structured Blocks)
Structured blocks appear in:
- `step.body.block`
- `run.block`

Supported statement nodes:
- `{"python": "raw lines"}` or `{"python": ["line1", "line2"]}`
- `{"set": {"name": "x", "value": <expr>}}`
- `{"expr": <expr>}`
- `{"return": <expr>}`
- `{"if": {"cond": <expr>, "then": [<stmt>...], "else": [<stmt>...]}}`
- `{"for": {"var": "x", "iter": <expr>, "body": [<stmt>...]}}`
- `{"while": {"cond": <expr>, "body": [<stmt>...], "else": [<stmt>...]}}`
- `{"break": true}` / `{"continue": true}`
- `{"with": {"items": [{"context": <expr>, "as": "var"}], "body": [<stmt>...]}}`
- `{"assert": {"cond": <expr>, "msg": <expr>}}` (msg optional)
- `{"raise": <expr>}` or `{"raise": null}`

Note: In `run.block`, `{"return": ...}` assigns `__vbl_result__` (there is no outer function).

## Run
`run` can be:
- an expression node
- `{ "python": "..." }` (raw Python lines)
- `{ "block": [ ... ] }` (structured statements)

Example `run.block`:
```json
{
  "run": {
    "block": [
      {"set": {"name": "x", "value": {"literal": 2}}},
      {"return": {"binop": {"op": "*", "left": {"name": "x"}, "right": {"literal": 21}}}}
    ]
  }
}
```

## Execution Report
`vibelang run --json` prints a JSON report:
```json
{
  "meta": {"name": "Echo"},
  "started_at": 0,
  "finished_at": 0,
  "duration_ms": 12,
  "steps": [
    {"name": "upper", "status": "ok", "duration_ms": 1, "attempts": 1, "error": null}
  ],
  "events": [
    {"kind": "step_start", "ts": 0, "step": "upper", "attempt": 1},
    {"kind": "step_end", "ts": 0, "step": "upper", "attempt": 1, "status": "ok", "duration_ms": 1}
  ],
  "result": "HELLO"
}
```

## `.vbl` S-Expression Syntax
`.vbl` is an S-expression syntax that parses to JSON IR.

Example:
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

Supported top-level forms:
- `(meta (key value) ...)`
- `(import module)` / `(import module as alias)`
- `(from module import name1 name2 ...)`
- `(input name value)` / `(inputs (name value) ...)`
- `(step name (params ...) (retry n) (timeout n) (guard ...) (produces ...) (body ...) (return ...))`
- `(run expr)` or `(run (block ...))`

## CLI (Reference)
Validate:
```bash
python3 -m vibelang validate examples/echo.vbl.json
```

Run:
```bash
python3 -m vibelang run examples/echo.vbl.json
```

Report JSON:
```bash
python3 -m vibelang run examples/echo.vbl.json --json
```

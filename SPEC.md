# VibeLang Spec v0.1

## Goals
- New language for AI-only authoring
- 100% Python package compatibility via CPython execution
- Deterministic, structured programs for LLM generation and editing
- Step-level observability, retry, guard, and timeout poles

## Non-Goals
- Human-friendly syntax
- Custom VM or bytecode
- Replacing CPython runtime

## Architecture
- Source formats: `.vbl` (S-expression) and `.vbl.json` (IR)
- IR compiles to Python source, parsed to AST, executed by CPython
- Runtime wrapper instruments steps and emits execution reports

## Execution Model
- Inputs are injected as Python variables from `inputs`
- Steps are defined as Python functions with `@step(...)` metadata
- `run` executes an expression, Python block, or structured block
- Execution report captures timing, retries, errors, and events

## IR Statements
- `set`, `if`, `for`, `expr`, `return`, `python` (raw)
- Blocks are allowed in `run.block` and `step.body.block`

## Standard Library Bridge
- `vbl.log()` emits events into the report
- `vbl.validate_jsonschema()` and `vbl.validate_pydantic()` for validation
- `vbl.parallel()` for concurrent execution

## Compatibility
- Uses normal Python imports and runs on CPython
- Pure-Python packages are fully compatible
- C-extensions are compatible to the extent CPython can import them

## Security and Safety
- Guard tokens are checked on string outputs
- Timeouts are best-effort (signal-based)
- Fail fast on guard or runtime errors

## Roadmap
- Deterministic sandboxing and side-effect policy
- IR-to-IR optimization and linting
- Richer expression nodes and control flow

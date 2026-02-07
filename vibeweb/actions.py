from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from vibeweb.conditions import ConditionError, eval_condition, lookup_path
from vibeweb.db import delete_row, get_row, insert_row, list_rows, normalize_row, update_row
from vibeweb.spec import (
    ActionSpec,
    DbActionSpec,
    FlowActionSpec,
    FlowStepSpec,
    HttpActionSpec,
    LlmActionSpec,
    ModelSpec,
    ValueActionSpec,
)


class ActionError(RuntimeError):
    pass


# `${foo.bar}` style string templating.
_TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")


_RETRYABLE_HTTP_STATUS: set[int] = {408, 429, *range(500, 600)}


def _deadline_remaining_s(ctx: dict[str, Any]) -> float | None:
    raw = ctx.get("_deadline_ts")
    if raw is None:
        return None
    try:
        remaining = float(raw) - time.monotonic()
    except Exception:
        return None
    return max(0.0, remaining)


def _clamp_timeout_s(timeout_s: int | float, ctx: dict[str, Any]) -> float:
    try:
        base = float(timeout_s)
    except Exception:
        base = 0.0
    base = max(0.0, base)
    remaining = _deadline_remaining_s(ctx)
    if remaining is None:
        return base
    return max(0.0, min(base, remaining))


def _is_timeout_exc(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, socket.timeout):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(getattr(exc, "reason", None), socket.timeout):
        return True
    return False


def _urlopen_read(
    req: urllib.request.Request,
    *,
    timeout_s: float,
) -> tuple[int, dict[str, str], bytes]:
    """
    urlopen wrapper that returns (status, headers, body).

    - For non-2xx responses, urllib raises HTTPError; we treat it like a response.
    - For connection/timeout errors, the caller handles exceptions.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        headers = dict(getattr(exc, "headers", {}) or {})
        code = int(getattr(exc, "code", 500) or 500)
        return code, headers, body


def _template_lookup(expr: str, ctx: dict[str, Any]) -> Any:
    value = lookup_path(expr, ctx)
    return "" if value is None else value


def render_str(template: str, ctx: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        value = _template_lookup(expr, ctx)
        return str(value)

    return _TEMPLATE_RE.sub(repl, template)


def render_value(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        full = _TEMPLATE_RE.fullmatch(stripped)
        if full:
            expr = full.group(1).strip()
            return lookup_path(expr, ctx)
        return render_str(value, ctx)
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    if isinstance(value, dict):
        return {str(k): render_value(v, ctx) for k, v in value.items()}
    return value


def _openai_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/v1/chat/completions"):
        return base
    return base + "/v1/chat/completions"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return json.loads(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ActionError("LLM did not return JSON")


def _allowed_outbound_hosts() -> set[str] | None:
    raw = (os.environ.get("VIBEWEB_OUTBOUND_ALLOW_HOSTS") or "").strip()
    if raw == "*":
        return None
    # Localhost is always allowed (http is still restricted to localhost in _enforce_outbound_url).
    hosts: set[str] = {"127.0.0.1", "localhost"}
    if raw:
        for part in raw.split(","):
            host = part.strip()
            if host:
                hosts.add(host)
    base_url = os.environ.get("VIBEWEB_AI_BASE_URL")
    if base_url:
        parsed = urlparse(base_url)
        if parsed.hostname:
            hosts.add(parsed.hostname)
    return hosts


def _enforce_outbound_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ActionError("Outbound URL must include scheme and host")
    if parsed.scheme not in ("https", "http"):
        raise ActionError("Outbound URL scheme must be http or https")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ActionError("Outbound http is only allowed for localhost")
    allowed = _allowed_outbound_hosts()
    if allowed is None:
        return
    host = parsed.hostname or ""
    if host not in allowed:
        raise ActionError(
            "Outbound host not allowed. "
            "Set VIBEWEB_OUTBOUND_ALLOW_HOSTS='host1,host2' (or '*') to permit it."
        )


def _json_request(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str] | None,
) -> urllib.request.Request:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(str(key), str(value))
    return req


def _retry_sleep(attempt: int) -> None:
    # Lightweight exponential backoff with jitter.
    delay = min(2.5, 0.25 * (2**attempt))
    time.sleep(delay)


def _execute_http(action: HttpActionSpec, ctx: dict[str, Any], method_fallback: str) -> dict[str, Any]:
    url = render_str(action.url, ctx)
    _enforce_outbound_url(url)
    method = (action.method or method_fallback).upper()
    headers = render_value(action.headers, ctx) if action.headers else {}
    body_value = action.body if action.body is not None else ctx.get("input")
    data = None
    if method not in ("GET", "HEAD"):
        body_rendered = render_value(body_value, ctx)
        data = json.dumps(body_rendered, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")

    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(str(k), str(v))

    last_error: Exception | None = None
    for attempt in range(int(action.retries) + 1):
        timeout_s = _clamp_timeout_s(action.timeout_s, ctx)
        timeout_s = max(0.001, timeout_s)
        try:
            status, resp_headers, body = _urlopen_read(req, timeout_s=timeout_s)

            retryable_status = status in _RETRYABLE_HTTP_STATUS
            if retryable_status and attempt < int(action.retries):
                _retry_sleep(attempt)
                continue

            content_type = (resp_headers.get("Content-Type") or "").lower()
            text = body.decode("utf-8", errors="replace")
            parsed: Any = text
            expect = (action.expect or "auto").lower()
            if expect == "json" or (expect == "auto" and "application/json" in content_type):
                try:
                    parsed = json.loads(text) if text else None
                except Exception:
                    parsed = text
            ok = 200 <= int(status) < 300
            return {"ok": ok, "status": int(status), "data": parsed}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < int(action.retries):
                _retry_sleep(attempt)
                continue

            status = 504 if _is_timeout_exc(exc) else 502
            return {"ok": False, "status": status, "data": {"error": str(exc)}}

    status = 504 if last_error and _is_timeout_exc(last_error) else 502
    return {"ok": False, "status": status, "data": {"error": str(last_error) if last_error else "HTTP failed"}}


def _execute_llm(action: LlmActionSpec, ctx: dict[str, Any]) -> dict[str, Any]:
    provider = (action.provider or "openai").lower()
    base_url = render_str(action.base_url, ctx).strip() if action.base_url else ""
    if not base_url:
        base_url = os.environ.get("VIBEWEB_AI_BASE_URL") or "https://api.deepseek.com/v1"
    model = render_str(action.model, ctx).strip() if action.model else ""
    if not model:
        model = os.environ.get("VIBEWEB_AI_MODEL") or "deepseek-chat"
    api_key = os.environ.get(action.api_key_env) if action.api_key_env else os.environ.get("VIBEWEB_AI_API_KEY")

    messages = []
    for msg in action.messages:
        messages.append({"role": msg["role"], "content": render_str(msg["content"], ctx)})

    def parse_llm_body(status: int, body: bytes) -> tuple[bool, Any]:
        text = body.decode("utf-8", errors="replace")
        try:
            return True, json.loads(text) if text else None
        except Exception:
            return False, text

    last_error: Exception | None = None
    for attempt in range(int(action.retries) + 1):
        timeout_s = _clamp_timeout_s(action.timeout_s, ctx)
        timeout_s = max(0.001, timeout_s)
        try:
            if provider == "openai":
                url = _openai_url(base_url)
                _enforce_outbound_url(url)
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": action.temperature,
                }
                if action.max_tokens is not None:
                    payload["max_tokens"] = action.max_tokens
                headers: dict[str, str] = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                req = _json_request(url, payload=payload, headers=headers)
                status, _, body = _urlopen_read(req, timeout_s=timeout_s)
                ok_json, data = parse_llm_body(status, body)
                if status in _RETRYABLE_HTTP_STATUS and attempt < int(action.retries):
                    _retry_sleep(attempt)
                    continue
                if not (200 <= int(status) < 300):
                    return {
                        "ok": False,
                        "status": int(status),
                        "data": data if ok_json else {"error": str(data)},
                    }
                try:
                    content = data["choices"][0]["message"]["content"]  # type: ignore[index]
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "status": 502, "data": {"error": f"Unexpected LLM response: {data!r}"}}
            elif provider == "ollama":
                url = base_url.rstrip("/") + "/api/chat"
                _enforce_outbound_url(url)
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": action.temperature},
                }
                req = _json_request(url, payload=payload, headers=None)
                status, _, body = _urlopen_read(req, timeout_s=timeout_s)
                ok_json, data = parse_llm_body(status, body)
                if status in _RETRYABLE_HTTP_STATUS and attempt < int(action.retries):
                    _retry_sleep(attempt)
                    continue
                if not (200 <= int(status) < 300):
                    return {
                        "ok": False,
                        "status": int(status),
                        "data": data if ok_json else {"error": str(data)},
                    }
                try:
                    content = data["message"]["content"]  # type: ignore[index]
                except Exception:
                    return {"ok": False, "status": 502, "data": {"error": f"Unexpected Ollama response: {data!r}"}}
            else:
                raise ActionError("LLM provider must be openai or ollama")

            if (action.output or "text") == "json":
                try:
                    parsed = _extract_json(str(content))
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "status": 502, "data": {"error": str(exc), "text": str(content)}}
                return {"ok": True, "status": 200, "data": parsed}
            return {"ok": True, "status": 200, "data": str(content)}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < int(action.retries):
                _retry_sleep(attempt)
                continue
            status = 504 if _is_timeout_exc(exc) else 502
            return {"ok": False, "status": status, "data": {"error": str(exc)}}

    status = 504 if last_error and _is_timeout_exc(last_error) else 502
    return {"ok": False, "status": status, "data": {"error": str(last_error) if last_error else "LLM failed"}}


def _safe_order_by(order_by: str, model: ModelSpec) -> str:
    raw = (order_by or "").strip()
    if not raw:
        return "id DESC"
    parts = [p for p in raw.split() if p]
    if len(parts) > 2:
        raise ActionError("action.db.order_by must be '<field> [asc|desc]'")
    field = parts[0]
    direction = parts[1] if len(parts) == 2 else "desc"
    direction_u = direction.upper()
    if direction_u not in ("ASC", "DESC"):
        raise ActionError("action.db.order_by direction must be 'asc' or 'desc'")
    if field != "id" and field not in model.fields:
        raise ActionError(f"action.db.order_by unknown field: {field}")
    return f"{field} {direction_u}"


def _require_db_services(ctx: dict[str, Any]) -> tuple[Any, Any, dict[str, ModelSpec]]:
    services = ctx.get("services")
    if not isinstance(services, dict):
        raise ActionError("DB action requires services.db (missing 'services' context)")
    db = services.get("db")
    if not isinstance(db, dict):
        raise ActionError("DB action requires services.db")
    conn = db.get("conn")
    lock = db.get("lock")
    models = db.get("models")
    if conn is None or lock is None or not isinstance(models, dict):
        raise ActionError("DB action requires services.db.{conn,lock,models}")
    return conn, lock, models  # type: ignore[return-value]


def _coerce_row_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ActionError("action.db.id must be an int or string")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            raise ActionError("action.db.id is required")
        try:
            return int(stripped)
        except Exception as exc:  # noqa: BLE001
            raise ActionError("action.db.id must be an int or numeric string") from exc
    raise ActionError("action.db.id must be an int or string")


def _execute_db(action: DbActionSpec, ctx: dict[str, Any]) -> dict[str, Any]:
    conn, lock, models = _require_db_services(ctx)
    model = models.get(action.model)
    if not isinstance(model, ModelSpec):
        raise ActionError(f"Unknown model: {action.model}")

    op = action.op
    if op == "list":
        order_by = _safe_order_by(action.order_by or "", model)
        with lock:
            rows = list_rows(conn, model, limit=int(action.limit), offset=int(action.offset), order_by=order_by)
        data = [normalize_row(model, row) for row in rows]
        return {"ok": True, "status": 200, "data": data}

    if op == "get":
        row_id = _coerce_row_id(render_value(action.id, ctx))
        with lock:
            row = get_row(conn, model, row_id)
        if not row:
            return {"ok": False, "status": 404, "data": {"error": "Row not found"}}
        return {"ok": True, "status": 200, "data": normalize_row(model, row)}

    if op == "insert":
        data_value = render_value(action.data or {}, ctx)
        if not isinstance(data_value, dict):
            raise ActionError("action.db.data must be an object")
        with lock:
            row = insert_row(conn, model, data_value)
        return {"ok": True, "status": 201, "data": normalize_row(model, row)}

    if op == "update":
        row_id = _coerce_row_id(render_value(action.id, ctx))
        patch_value = render_value(action.patch or {}, ctx)
        if not isinstance(patch_value, dict):
            raise ActionError("action.db.patch must be an object")
        with lock:
            row = update_row(conn, model, row_id, patch_value)
        if not row:
            return {"ok": False, "status": 404, "data": {"error": "Row not found"}}
        return {"ok": True, "status": 200, "data": normalize_row(model, row)}

    if op == "delete":
        row_id = _coerce_row_id(render_value(action.id, ctx))
        with lock:
            ok = bool(delete_row(conn, model, row_id))
        return {"ok": ok, "status": 200 if ok else 404, "data": {"deleted": ok, "id": row_id}}

    raise ActionError(f"Unknown db op: {op}")


def _execute_value(action: ValueActionSpec, ctx: dict[str, Any]) -> dict[str, Any]:
    data = render_value(action.data, ctx)
    return {"ok": bool(action.ok), "status": int(action.status), "data": data}


def _auth_level(auth: str) -> int:
    # Used for flow-action safety checks.
    if auth == "none":
        return 0
    if auth == "api":
        return 1
    if auth == "admin":
        return 2
    return 0


def _require_action_registry(ctx: dict[str, Any]) -> dict[str, ActionSpec]:
    registry = ctx.get("actions")
    if not isinstance(registry, dict):
        raise ActionError("Flow action requires action registry in ctx['actions']")
    out: dict[str, ActionSpec] = {}
    for key, value in registry.items():
        if isinstance(key, str) and isinstance(value, ActionSpec):
            out[key] = value
    if not out:
        raise ActionError("Flow action requires action registry in ctx['actions']")
    return out


def _flow_depth(ctx: dict[str, Any]) -> int:
    raw = ctx.get("_flow_depth", 0)
    try:
        return int(raw)
    except Exception:
        return 0


def _ensure_dict(ctx: dict[str, Any], key: str) -> dict[str, Any]:
    existing = ctx.get(key)
    if isinstance(existing, dict):
        return existing
    created: dict[str, Any] = {}
    ctx[key] = created
    return created


def _apply_flow_set(step_id: str, mapping: dict[str, Any] | None, ctx: dict[str, Any], vars_out: dict[str, Any]) -> None:
    if not mapping:
        return
    if not isinstance(mapping, dict):
        raise ActionError(f"flow step.set must be an object (step: {step_id})")
    for key, value in mapping.items():
        if not isinstance(key, str) or not key:
            raise ActionError(f"flow step.set keys must be strings (step: {step_id})")
        vars_out[key] = render_value(value, ctx)


def _execute_flow(parent: ActionSpec, flow: FlowActionSpec, ctx: dict[str, Any]) -> dict[str, Any]:
    depth = _flow_depth(ctx)
    if depth > 24:
        raise ActionError("Flow nesting too deep")

    registry = _require_action_registry(ctx)
    steps_out = _ensure_dict(ctx, "steps")
    vars_out = _ensure_dict(ctx, "vars")

    # Optional flow-level var initialization. Useful for defaults and shared constants.
    if flow.vars is not None:
        rendered = render_value(flow.vars, ctx)
        if isinstance(rendered, dict):
            for k, v in rendered.items():
                if isinstance(k, str) and k:
                    vars_out[k] = v

    def _step_deadline_ts(step_timeout_s: int | None) -> float | None:
        base = ctx.get("_deadline_ts")
        parent_deadline: float | None
        try:
            parent_deadline = float(base) if base is not None else None
        except Exception:
            parent_deadline = None

        if step_timeout_s is None:
            return parent_deadline
        try:
            window = float(step_timeout_s)
        except Exception:
            window = 0.0
        window = max(0.0, window)
        proposed = time.monotonic() + window
        if parent_deadline is None:
            return proposed
        return min(parent_deadline, proposed)

    def _step_should_run(step: FlowStepSpec, cond_ctx: dict[str, Any]) -> bool:
        if not step.when:
            return True
        try:
            return bool(eval_condition(step.when, cond_ctx))
        except ConditionError as exc:
            raise ActionError(f"Invalid flow step.when (step: {step.id}): {exc}") from exc

    def _run_step(
        step: FlowStepSpec,
        *,
        steps_snapshot: dict[str, Any] | None = None,
        vars_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sub = registry.get(step.use)
        if not sub:
            raise ActionError(f"Flow step references unknown action: {step.use}")

        # Prevent privilege escalation by "calling" an admin-only action from an api/none flow.
        if _auth_level(sub.auth) > _auth_level(parent.auth):
            raise ActionError(
                f"Flow cannot use action '{sub.name}' with auth='{sub.auth}' from flow auth='{parent.auth}'"
            )

        render_ctx = ctx
        if steps_snapshot is not None or vars_snapshot is not None:
            render_ctx = dict(ctx)
            if steps_snapshot is not None:
                render_ctx["steps"] = steps_snapshot
            if vars_snapshot is not None:
                render_ctx["vars"] = vars_snapshot

        step_input = render_ctx.get("input") if step.input is None else render_value(step.input, render_ctx)

        child_extra: dict[str, Any] = {}
        for k in ("request", "hook", "services", "actions"):
            if k in ctx:
                child_extra[k] = ctx[k]

        # For parallel steps, we pass read-only snapshots (so nested flows can't race on shared dicts).
        if steps_snapshot is None:
            child_extra["steps"] = steps_out
        else:
            child_extra["steps"] = steps_snapshot

        if vars_snapshot is None:
            child_extra["vars"] = vars_out
        else:
            child_extra["vars"] = vars_snapshot

        child_extra["_flow_depth"] = depth + 1
        deadline_ts = _step_deadline_ts(step.timeout_s)
        if deadline_ts is not None:
            child_extra["_deadline_ts"] = deadline_ts

        last_error: Exception | None = None
        for attempt in range(int(step.retries) + 1):
            if deadline_ts is not None and time.monotonic() >= deadline_ts:
                return {"ok": False, "status": 504, "data": {"error": "timeout"}}
            try:
                result = execute_action(
                    sub,
                    input_data=step_input,
                    query=ctx.get("query"),
                    extra=child_extra,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                result = {"ok": False, "status": 500, "data": {"error": str(exc)}}

            if result.get("ok"):
                return result

            if attempt < int(step.retries):
                _retry_sleep(attempt)
                continue

            # Final failure (return the last result).
            if last_error and deadline_ts is not None and time.monotonic() >= deadline_ts:
                return {"ok": False, "status": 504, "data": {"error": "timeout"}}
            return result

        return {"ok": False, "status": 502, "data": {"error": "step failed"}}

    last: dict[str, Any] | None = None
    i = 0
    steps_list = list(flow.steps or [])
    while i < len(steps_list):
        step = steps_list[i]

        if step.parallel:
            group: list[FlowStepSpec] = []
            j = i
            while j < len(steps_list) and steps_list[j].parallel:
                group.append(steps_list[j])
                j += 1

            # Snapshot for parallel evaluation: steps/vars before the group starts.
            steps_snapshot = dict(steps_out)
            vars_snapshot = dict(vars_out)
            cond_ctx = dict(ctx)
            cond_ctx["steps"] = steps_snapshot
            cond_ctx["vars"] = vars_snapshot

            # Pre-handle "when" for deterministic skips (evaluate against snapshot context).
            preset: dict[str, dict[str, Any]] = {}
            to_run: list[FlowStepSpec] = []
            for s in group:
                if _step_should_run(s, cond_ctx):
                    to_run.append(s)
                else:
                    preset[s.id] = {"ok": True, "status": 204, "data": None, "skipped": True}

            futures: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}
            if to_run:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(to_run)) as ex:
                    for s in to_run:
                        futures[s.id] = ex.submit(_run_step, s, steps_snapshot=steps_snapshot, vars_snapshot=vars_snapshot)

            # Merge results in step order (deterministic).
            for s in group:
                if s.id in futures:
                    try:
                        result = futures[s.id].result()
                    except Exception as exc:  # noqa: BLE001
                        result = {"ok": False, "status": 500, "data": {"error": str(exc)}}
                else:
                    result = preset.get(s.id) or {"ok": True, "status": 204, "data": None, "skipped": True}

                steps_out[s.id] = result
                last = result
                _apply_flow_set(s.id, s.set, ctx, vars_out)

                # Decide flow control after merge.
                if not result.get("ok"):
                    mode = (s.on_error or "stop").lower()
                    if mode == "continue":
                        continue
                    # stop/return: end the flow and return the failing result
                    return result

            i = j
            continue

        # Sequential step
        if not _step_should_run(step, ctx):
            steps_out[step.id] = {"ok": True, "status": 204, "data": None, "skipped": True}
            last = steps_out[step.id]  # type: ignore[assignment]
            _apply_flow_set(step.id, step.set, ctx, vars_out)
            i += 1
            continue

        result = _run_step(step)
        steps_out[step.id] = result
        last = result
        _apply_flow_set(step.id, step.set, ctx, vars_out)

        if not result.get("ok"):
            mode = (step.on_error or "stop").lower()
            if mode == "continue":
                i += 1
                continue
            return result

        i += 1

    if flow.return_step:
        picked = steps_out.get(flow.return_step)
        if isinstance(picked, dict):
            return picked  # type: ignore[return-value]
        return {"ok": False, "status": 500, "data": {"error": "flow return_step missing"}}
    if last is None:
        return {"ok": True, "status": 200, "data": None}
    return last


def execute_action(
    action: ActionSpec,
    *,
    input_data: Any,
    query: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "input": input_data,
        "query": query or {},
        "env": dict(os.environ),
    }
    if extra:
        ctx.update(extra)

    if action.kind == "http":
        if not action.http:
            raise ActionError("HTTP action missing 'http' config")
        return _execute_http(action.http, ctx, method_fallback=action.method)
    if action.kind == "llm":
        if not action.llm:
            raise ActionError("LLM action missing 'llm' config")
        return _execute_llm(action.llm, ctx)
    if action.kind == "db":
        if not action.db:
            raise ActionError("DB action missing 'db' config")
        return _execute_db(action.db, ctx)
    if action.kind == "value":
        if not action.value:
            raise ActionError("Value action missing 'value' config")
        return _execute_value(action.value, ctx)
    if action.kind == "flow":
        if not action.flow:
            raise ActionError("Flow action missing 'flow' config")
        return _execute_flow(action, action.flow, ctx)
    raise ActionError(f"Unknown action kind: {action.kind}")


def action_debug_dict(action: ActionSpec) -> dict[str, Any]:
    # Useful for /api/meta without leaking secrets.
    data = asdict(action)
    if data.get("http", {}).get("headers"):
        data["http"]["headers"] = {k: "***" for k in data["http"]["headers"].keys()}
    if data.get("llm", {}).get("api_key_env"):
        data["llm"]["api_key_env"] = str(data["llm"]["api_key_env"])
    return data

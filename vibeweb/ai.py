import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from vibeweb.spec import validate_spec

_SYSTEM_PROMPT = (
    "You generate VibeWeb app specs. "
    "Return ONLY valid JSON (no markdown, no comments, no code fences). "
    "Always set spec_version: 1. "
    "Spec format: {spec_version, name, db:{path, models:[{name, fields:{field:type}}]}, api:{crud:[Model...], actions:[...], hooks:[...]}, "
    "ui:{admin, admin_path, admin_auth:{type, username, password}, pages:[{path, model, title, "
    "default_query, default_sort, default_dir, default_filters, visible_fields, hidden_fields}]}}. "
    "Allowed field types: text, int, float, bool, datetime, json, ref:<Model>. "
    "Actions: api.actions is a list of custom endpoints. Each action: {name, kind:'http'|'llm'|'db'|'value'|'flow', method, path, auth:'api'|'none'|'admin', "
    "http:{url, method?, headers?, body?, timeout_s?, retries?, expect:'auto'|'json'|'text'}, "
    "llm:{provider:'openai'|'ollama', base_url?, model?, api_key_env?, messages:[{role, content}], temperature?, max_tokens?, timeout_s?, retries?, output:'text'|'json'}, "
    "db:{op:'get'|'list'|'insert'|'update'|'delete', model, id?, data?, patch?, limit?, offset?, order_by?}, "
    "value:{data, status?:int, ok?:bool}, "
    "flow:{vars?:{name:value}, steps:[{id, use, input?, when?, on_error?('stop'|'continue'|'return'), set?:{name:value}, retries?:int, timeout_s?:int, parallel?:bool}], return_step?}}. "
    "Hooks: api.hooks is a list of {model, event:'after_create'|'after_update'|'after_delete', action, mode:'sync'|'async', "
    "writeback?:[field...], when_changed?:[field...], when?:<condition>}. "
    "Condition format: either an equality map like {\"row.stage\":\"Closed Won\"} or an operator object like "
    "{\"$and\":[cond,cond]}, {$or:[...]}, {$not:cond}, {$eq:[\"expr\",value]}, {$ne:[\"expr\",value]}, "
    "{$gt:[\"expr\",number]}, {$gte:[\"expr\",number]}, {$lt:[\"expr\",number]}, {$lte:[\"expr\",number]}, "
    "{$in:[\"expr\",[values...]]}, {$contains:[\"expr\",value]}, {$startsWith:[\"expr\",\"prefix\"]}, {$endsWith:[\"expr\",\"suffix\"]}, "
    "{$regex:[\"expr\",\"pattern\"]}, {$any:[\"expr\",cond]}, {$all:[\"expr\",cond]}, "
    "{$exists:\"expr\"} or {$exists:[\"expr\",true|false]}, {$truthy:\"expr\"}. "
    "A list [cond, cond, ...] is treated as implicit AND. "
    "Templating: strings may include ${path}. If a value is exactly \"${path}\" it becomes a typed value (not a string). "
    "Include admin enabled with admin_path '/admin' and admin_auth default admin/admin unless prompt says otherwise."
)


class AIError(RuntimeError):
    pass


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()  # type: ignore[assignment]
        except Exception:
            raw = b""
        text = raw.decode("utf-8", errors="replace").strip()
        msg = text
        try:
            data = json.loads(text) if text else None
            if isinstance(data, dict) and "error" in data:
                msg = str(data["error"])
        except Exception:
            pass
        raise AIError(f"LLM endpoint returned HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise AIError(f"Failed to reach LLM endpoint: {exc}") from exc


def _openai_chat(base_url: str, api_key: str | None, model: str, messages: List[Dict[str, str]], temperature: float) -> str:
    url = _openai_url(base_url)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = _post_json(url, payload, headers=headers)
    try:
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"Unexpected OpenAI response: {data}") from exc


def _openai_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/v1/chat/completions"):
        return base
    return base + "/v1/chat/completions"


def _ollama_chat(base_url: str, model: str, messages: List[Dict[str, str]], temperature: float) -> str:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = _post_json(url, payload)
    try:
        return data["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"Unexpected Ollama response: {data}") from exc


def _extract_json(text: str) -> Dict[str, Any]:
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
    raise AIError("Model did not return JSON")


def generate_spec(
    prompt: str,
    *,
    provider: str = "openai",
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    provider = provider.lower()
    if provider == "deepseek":
        provider = "openai"
    base_url = base_url or os.environ.get("VIBEWEB_AI_BASE_URL", "https://api.deepseek.com/v1")
    model = model or os.environ.get("VIBEWEB_AI_MODEL", "deepseek-chat")
    api_key = api_key or os.environ.get("VIBEWEB_AI_API_KEY")

    if provider == "openai" and not api_key:
        host = (urlparse(base_url).hostname or "").lower()
        if "deepseek" in host:
            raise AIError("VIBEWEB_AI_API_KEY is required for DeepSeek.")

    max_repairs = int(os.environ.get("VIBEWEB_AI_REPAIR_TRIES", "2"))
    last_error: Exception | None = None
    for attempt in range(max_repairs + 1):
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        if attempt and last_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Fix the JSON to satisfy the VibeWeb spec. "
                        f"Validation error: {last_error}"
                    ),
                }
            )

        if provider == "openai":
            text = _openai_chat(base_url, api_key, model, messages, temperature)
        elif provider == "ollama":
            text = _ollama_chat(base_url, model, messages, temperature)
        else:
            raise AIError("provider must be openai or ollama")

        spec = _extract_json(text)
        spec = normalize_spec(spec)
        try:
            validate_spec(spec)
            return spec
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    raise AIError(f"Spec validation failed after {max_repairs + 1} attempts: {last_error}")


def normalize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    spec["spec_version"] = 1
    if "name" not in spec:
        spec["name"] = "VibeWeb App"
    if "db" not in spec:
        raise AIError("Spec missing 'db'")
    if "models" not in spec.get("db", {}):
        raise AIError("Spec missing 'db.models'")

    model_names = [m["name"] for m in spec["db"]["models"] if isinstance(m, dict) and m.get("name")]
    if "api" not in spec:
        spec["api"] = {}
    if "crud" not in spec["api"]:
        spec["api"]["crud"] = model_names
    if "actions" not in spec["api"]:
        spec["api"]["actions"] = []
    if "hooks" not in spec["api"]:
        spec["api"]["hooks"] = []

    if "ui" not in spec:
        spec["ui"] = {}
    if "pages" not in spec["ui"]:
        spec["ui"]["pages"] = [
            {"path": f"/{name.lower()}", "model": name, "title": f"{name} List"}
            for name in model_names
        ]
    if "admin" not in spec["ui"]:
        spec["ui"]["admin"] = True
    if "admin_path" not in spec["ui"]:
        spec["ui"]["admin_path"] = "/admin"
    if spec["ui"].get("admin") and "admin_auth" not in spec["ui"]:
        spec["ui"]["admin_auth"] = {"type": "basic", "username": "admin", "password": "admin"}

    return spec

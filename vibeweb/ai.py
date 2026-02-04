import json
import os
import urllib.request
from typing import Any, Dict, List, Tuple


_SYSTEM_PROMPT = (
    "You generate VibeWeb app specs. "
    "Return ONLY valid JSON (no markdown, no comments, no code fences). "
    "Spec format: {name, db:{path, models:[{name, fields:{field:type}}]}, api:{crud:[Model...]}, "
    "ui:{admin, admin_path, admin_auth:{type, username, password}, pages:[{path, model, title}]}}. "
    "Allowed field types: text, int, float, bool, datetime. "
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


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
    base_url = base_url or os.environ.get("VIBEWEB_AI_BASE_URL", "http://127.0.0.1:8080/v1")
    model = model or os.environ.get("VIBEWEB_AI_MODEL", "glm-4.7-flash")
    api_key = api_key or os.environ.get("VIBEWEB_AI_API_KEY")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    if provider == "openai":
        text = _openai_chat(base_url, api_key, model, messages, temperature)
    elif provider == "ollama":
        text = _ollama_chat(base_url, model, messages, temperature)
    else:
        raise AIError("provider must be openai or ollama")

    spec = _extract_json(text)
    return normalize_spec(spec)


def normalize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
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

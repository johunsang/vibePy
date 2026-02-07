import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

SPEC_VERSION = 1


ALLOWED_TYPES = {"text", "int", "float", "bool", "datetime", "json"}
ALLOWED_ACTION_KINDS = {"http", "llm", "db", "flow", "value"}
ALLOWED_ACTION_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_ACTION_AUTH = {"api", "none", "admin"}
ALLOWED_DB_OPS = {"get", "list", "insert", "update", "delete"}
ALLOWED_HOOK_EVENTS = {
    "after_create",
    "after_update",
    "after_delete",
}
ALLOWED_HOOK_MODES = {"sync", "async"}

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_ident(value: str, *, what: str) -> None:
    if not _SAFE_IDENT_RE.match(value):
        raise ValueError(f"{what} must match ^[A-Za-z_][A-Za-z0-9_]*$: {value!r}")


_ALLOWED_COND_OPS = {
    "$and",
    "$or",
    "$not",
    "$eq",
    "$ne",
    "$gt",
    "$gte",
    "$lt",
    "$lte",
    "$in",
    "$contains",
    "$startsWith",
    "$endsWith",
    "$regex",
    "$any",
    "$all",
    "$exists",
    "$truthy",
}


def _is_op_condition(value: dict[str, Any]) -> bool:
    return any(isinstance(k, str) and k.startswith("$") for k in value.keys())


def _validate_condition(value: Any, *, what: str) -> None:
    """
    Minimal validation for condition DSL objects (used by hook.when and flow step.when).

    Accepts:
      - Equality maps: {"row.stage": "Closed Won", "steps.invoice.ok": true}
      - Operator forms: {"$and": [...]}, {"$eq": ["expr", value]}, ...
      - List form (implicit AND): [cond, cond, ...]
    """
    if value is None:
        return
    if isinstance(value, bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_condition(item, what=what)
        return
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object or list")

    if not _is_op_condition(value):
        for key in value.keys():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{what} keys must be non-empty strings")
        return

    if len(value) != 1:
        raise ValueError(f"{what} operator form must have exactly one $operator key")

    op, arg = next(iter(value.items()))
    if not isinstance(op, str) or op not in _ALLOWED_COND_OPS:
        raise ValueError(f"{what} has unknown operator: {op!r}")

    if op in ("$and", "$or"):
        if not isinstance(arg, list) or not arg:
            raise ValueError(f"{what}.{op} must be a non-empty list")
        for item in arg:
            _validate_condition(item, what=what)
        return

    if op == "$not":
        _validate_condition(arg, what=what)
        return

    if op in (
        "$eq",
        "$ne",
        "$gt",
        "$gte",
        "$lt",
        "$lte",
        "$in",
        "$contains",
        "$startsWith",
        "$endsWith",
        "$regex",
        "$any",
        "$all",
    ):
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError(f"{what}.{op} must be [expr, value]")
        expr = arg[0]
        if not isinstance(expr, str) or not expr:
            raise ValueError(f"{what}.{op} expr must be a non-empty string")
        if op == "$regex" and not isinstance(arg[1], str):
            raise ValueError(f"{what}.$regex pattern must be a string")
        if op == "$in" and not isinstance(arg[1], list):
            raise ValueError(f"{what}.$in expects [expr, [values...]]")
        if op in ("$startsWith", "$endsWith") and not isinstance(arg[1], str):
            raise ValueError(f"{what}.{op} expects [expr, string]")
        if op in ("$any", "$all") and not isinstance(arg[1], dict):
            raise ValueError(f"{what}.{op} expects [expr, <condition_object>]")
        return

    if op == "$exists":
        if isinstance(arg, str) and arg:
            return
        if (
            isinstance(arg, list)
            and len(arg) == 2
            and isinstance(arg[0], str)
            and arg[0]
            and isinstance(arg[1], bool)
        ):
            return
        raise ValueError(f"{what}.$exists expects 'expr' or ['expr', bool]")

    if op == "$truthy":
        if not isinstance(arg, str) or not arg:
            raise ValueError(f"{what}.$truthy expects 'expr'")
        return

    raise ValueError(f"{what} has unsupported operator: {op!r}")


@dataclass
class ModelSpec:
    name: str
    fields: Dict[str, str]


@dataclass
class PageSpec:
    path: str
    model: str
    title: str | None = None
    fields: List[str] | None = None
    default_query: str | None = None
    default_sort: str | None = None
    default_dir: str | None = None
    default_filters: Dict[str, str] | None = None
    visible_fields: List[str] | None = None
    hidden_fields: List[str] | None = None


@dataclass
class HttpActionSpec:
    url: str
    method: str | None = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any | None = None
    timeout_s: int = 30
    retries: int = 0
    expect: str = "auto"  # auto|json|text


@dataclass
class LlmActionSpec:
    provider: str = "openai"  # openai|ollama
    base_url: str | None = None
    model: str | None = None
    api_key_env: str = "VIBEWEB_AI_API_KEY"
    messages: List[Dict[str, str]] = field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int | None = None
    timeout_s: int = 60
    retries: int = 0
    output: str = "text"  # text|json


@dataclass
class DbActionSpec:
    op: str  # get|list|insert|update|delete
    model: str
    id: Any | None = None
    data: Dict[str, Any] | None = None
    patch: Dict[str, Any] | None = None
    limit: int = 100
    offset: int = 0
    order_by: str | None = None


@dataclass
class ValueActionSpec:
    data: Any
    status: int = 200
    ok: bool = True


@dataclass
class FlowStepSpec:
    id: str
    use: str
    input: Any | None = None
    when: Any | None = None
    on_error: str | None = None  # stop|continue|return
    set: Dict[str, Any] | None = None
    retries: int = 0
    timeout_s: int | None = None
    parallel: bool = False


@dataclass
class FlowActionSpec:
    steps: List[FlowStepSpec] = field(default_factory=list)
    return_step: str | None = None
    vars: Dict[str, Any] | None = None


@dataclass
class ActionSpec:
    name: str
    kind: str = "http"
    method: str = "POST"
    path: str = ""
    auth: str = "api"  # api|none|admin
    http: HttpActionSpec | None = None
    llm: LlmActionSpec | None = None
    db: DbActionSpec | None = None
    value: ValueActionSpec | None = None
    flow: FlowActionSpec | None = None


@dataclass
class HookSpec:
    model: str
    event: str
    action: str
    mode: str = "async"  # sync|async
    writeback: List[str] | None = None
    when_changed: List[str] | None = None
    when: Any | None = None


@dataclass
class AppSpec:
    name: str
    spec_version: int = SPEC_VERSION
    db_path: str = "vibeweb.db"
    models: List[ModelSpec] = field(default_factory=list)
    api_crud: List[str] = field(default_factory=list)
    actions: List[ActionSpec] = field(default_factory=list)
    hooks: List[HookSpec] = field(default_factory=list)
    pages: List[PageSpec] = field(default_factory=list)
    admin_enabled: bool = False
    admin_path: str = "/admin"
    admin_auth_type: str | None = None
    admin_username: str | None = None
    admin_password: str | None = None
    theme_css_urls: List[str] = field(default_factory=list)
    theme_tailwind_config: Dict[str, Any] | None = None
    theme_classes: Dict[str, str] = field(default_factory=dict)


def load_spec(path: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Spec must be an object")
    return data


def _is_ref_type(field_type: str) -> bool:
    return field_type.startswith("ref:") and len(field_type.split(":", 1)[1]) > 0


def _ref_target(field_type: str) -> str:
    return field_type.split(":", 1)[1]


def validate_spec(spec: Dict[str, Any]) -> AppSpec:
    raw_version = spec.get("spec_version", SPEC_VERSION)
    if not isinstance(raw_version, int):
        raise ValueError("spec_version must be an int")
    if raw_version != SPEC_VERSION:
        raise ValueError(f"Unsupported spec_version: {raw_version} (expected {SPEC_VERSION})")

    name = spec.get("name") or "VibeWeb App"
    if not isinstance(name, str):
        raise ValueError("name must be a string")

    db = spec.get("db", {}) or {}
    if not isinstance(db, dict):
        raise ValueError("db must be an object")
    db_path = db.get("path") or "vibeweb.db"
    if not isinstance(db_path, str):
        raise ValueError("db.path must be a string")

    models_raw = db.get("models", []) or []
    if not isinstance(models_raw, list):
        raise ValueError("db.models must be a list")

    model_names: set[str] = set()
    for model in models_raw:
        if not isinstance(model, dict):
            raise ValueError("model must be an object")
        model_name = model.get("name")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError("model.name must be a string")
        _require_ident(model_name, what="model.name")
        if model_name in model_names:
            raise ValueError(f"duplicate model name: {model_name}")
        model_names.add(model_name)

    models: List[ModelSpec] = []
    for model in models_raw:
        if not isinstance(model, dict):
            raise ValueError("model must be an object")
        model_name = model.get("name")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError("model.name must be a string")
        _require_ident(model_name, what="model.name")

        fields = model.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"model.fields required for {model_name}")
        for field_name, field_type in fields.items():
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(f"invalid field name in {model_name}")
            _require_ident(field_name, what=f"field name in {model_name}")
            if not isinstance(field_type, str):
                raise ValueError(f"invalid field type in {model_name}.{field_name}")
            if field_type not in ALLOWED_TYPES and not _is_ref_type(field_type):
                raise ValueError(
                    f"invalid field type '{field_type}' in {model_name} (allowed: {sorted(ALLOWED_TYPES)} or ref:<Model>)"
                )
            if _is_ref_type(field_type):
                target = _ref_target(field_type)
                if target not in model_names:
                    raise ValueError(f"ref target '{target}' not found for {model_name}.{field_name}")
        models.append(ModelSpec(name=model_name, fields=fields))

    api = spec.get("api", {}) or {}
    if not isinstance(api, dict):
        raise ValueError("api must be an object")
    crud = api.get("crud", []) or []
    if not isinstance(crud, list) or not all(isinstance(c, str) for c in crud):
        raise ValueError("api.crud must be list of strings")
    for c in crud:
        if c not in model_names:
            raise ValueError(f"api.crud references unknown model: {c}")

    actions_raw = api.get("actions", []) or []
    if not isinstance(actions_raw, list):
        raise ValueError("api.actions must be a list")
    hooks_raw = api.get("hooks", []) or []
    if not isinstance(hooks_raw, list):
        raise ValueError("api.hooks must be a list")

    ui = spec.get("ui", {}) or {}
    if not isinstance(ui, dict):
        raise ValueError("ui must be an object")
    pages_raw = ui.get("pages", []) or []
    if not isinstance(pages_raw, list):
        raise ValueError("ui.pages must be a list")
    admin_enabled = bool(ui.get("admin", False))
    admin_path = ui.get("admin_path", "/admin")
    if not isinstance(admin_path, str) or not admin_path.startswith("/"):
        raise ValueError("ui.admin_path must be a string starting with /")
    admin_auth = ui.get("admin_auth")
    admin_auth_type = None
    admin_username = None
    admin_password = None
    if admin_auth is not None:
        if not isinstance(admin_auth, dict):
            raise ValueError("ui.admin_auth must be an object")
        admin_auth_type = admin_auth.get("type", "basic")
        if admin_auth_type != "basic":
            raise ValueError("ui.admin_auth.type must be 'basic'")
        admin_username = admin_auth.get("username")
        admin_password = admin_auth.get("password")
        if not isinstance(admin_username, str) or not admin_username:
            raise ValueError("ui.admin_auth.username must be a string")
        if not isinstance(admin_password, str) or not admin_password:
            raise ValueError("ui.admin_auth.password must be a string")
        admin_enabled = True

    theme_css_urls: List[str] = []
    theme_tailwind_config: Dict[str, Any] | None = None
    theme_classes: Dict[str, str] = {}
    theme = ui.get("theme")
    if theme is not None:
        if not isinstance(theme, dict):
            raise ValueError("ui.theme must be an object")
        css_urls = theme.get("css_urls", []) or []
        if not isinstance(css_urls, list) or not all(isinstance(u, str) for u in css_urls):
            raise ValueError("ui.theme.css_urls must be a list of strings")
        for raw_url in css_urls:
            url = raw_url.strip()
            if not url:
                continue
            if url.startswith("/"):
                theme_css_urls.append(url)
                continue
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("ui.theme.css_urls entries must be https://... or /path")
            theme_css_urls.append(url)

        tailwind = theme.get("tailwind_config")
        if tailwind is not None and not isinstance(tailwind, dict):
            raise ValueError("ui.theme.tailwind_config must be an object")
        theme_tailwind_config = tailwind

        classes = theme.get("classes", {}) or {}
        if not isinstance(classes, dict):
            raise ValueError("ui.theme.classes must be an object")
        for key, value in classes.items():
            if not isinstance(key, str) or not key:
                raise ValueError("ui.theme.classes keys must be non-empty strings")
            if not isinstance(value, str):
                raise ValueError("ui.theme.classes values must be strings")
        theme_classes = {str(k): str(v) for k, v in classes.items()}

    pages: List[PageSpec] = []
    for page in pages_raw:
        if not isinstance(page, dict):
            raise ValueError("page must be an object")
        path = page.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("page.path must be a string starting with /")
        model = page.get("model")
        if not isinstance(model, str) or model not in model_names:
            raise ValueError("page.model must reference a known model")
        title = page.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("page.title must be string")
        fields = page.get("fields")
        if fields is not None:
            if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
                raise ValueError("page.fields must be list of strings")
        default_query = page.get("default_query")
        if default_query is not None and not isinstance(default_query, str):
            raise ValueError("page.default_query must be a string")
        default_sort = page.get("default_sort")
        if default_sort is not None and not isinstance(default_sort, str):
            raise ValueError("page.default_sort must be a string")
        default_dir = page.get("default_dir")
        if default_dir is not None:
            if not isinstance(default_dir, str) or default_dir.lower() not in ("asc", "desc"):
                raise ValueError("page.default_dir must be 'asc' or 'desc'")
        default_filters = page.get("default_filters")
        if default_filters is not None:
            if not isinstance(default_filters, dict):
                raise ValueError("page.default_filters must be an object")
            for key, value in default_filters.items():
                if not isinstance(key, str):
                    raise ValueError("page.default_filters keys must be strings")
                if not isinstance(value, (str, int, float, bool)):
                    raise ValueError("page.default_filters values must be string/number/bool")
        visible_fields = page.get("visible_fields")
        if visible_fields is not None:
            if not isinstance(visible_fields, list) or not all(isinstance(f, str) for f in visible_fields):
                raise ValueError("page.visible_fields must be list of strings")
        hidden_fields = page.get("hidden_fields")
        if hidden_fields is not None:
            if not isinstance(hidden_fields, list) or not all(isinstance(f, str) for f in hidden_fields):
                raise ValueError("page.hidden_fields must be list of strings")

        # Validate per-model field references
        model_fields = None
        for m in models:
            if m.name == model:
                model_fields = set(m.fields.keys())
                break
        if model_fields:
            if fields:
                for field_name in fields:
                    if field_name not in model_fields:
                        raise ValueError(f"page.fields contains unknown field '{field_name}' for {model}")
            if default_sort and default_sort != "id" and default_sort not in model_fields:
                raise ValueError(f"page.default_sort unknown field '{default_sort}' for {model}")
            if default_filters:
                for field_name in default_filters.keys():
                    if field_name not in model_fields:
                        raise ValueError(f"page.default_filters unknown field '{field_name}' for {model}")
            if visible_fields:
                for field_name in visible_fields:
                    if field_name not in model_fields:
                        raise ValueError(f"page.visible_fields unknown field '{field_name}' for {model}")
            if hidden_fields:
                for field_name in hidden_fields:
                    if field_name not in model_fields:
                        raise ValueError(f"page.hidden_fields unknown field '{field_name}' for {model}")

        pages.append(
            PageSpec(
                path=path,
                model=model,
                title=title,
                fields=fields,
                default_query=default_query,
                default_sort=default_sort,
                default_dir=default_dir.lower() if isinstance(default_dir, str) else None,
                default_filters={k: str(v) for k, v in default_filters.items()} if default_filters else None,
                visible_fields=visible_fields,
                hidden_fields=hidden_fields,
            )
        )

    # Actions
    action_names: set[str] = set()
    for raw in actions_raw:
        if not isinstance(raw, dict):
            raise ValueError("action must be an object")
        action_name = raw.get("name")
        if not isinstance(action_name, str) or not action_name:
            raise ValueError("action.name must be a string")
        if action_name in action_names:
            raise ValueError(f"duplicate action name: {action_name}")
        action_names.add(action_name)

    actions: List[ActionSpec] = []
    for raw in actions_raw:
        if not isinstance(raw, dict):
            raise ValueError("action must be an object")
        action_name = raw.get("name")
        if not isinstance(action_name, str) or not action_name:
            raise ValueError("action.name must be a string")

        kind = raw.get("kind", "http")
        if not isinstance(kind, str) or kind not in ALLOWED_ACTION_KINDS:
            raise ValueError(f"action.kind must be one of {sorted(ALLOWED_ACTION_KINDS)}")
        method = raw.get("method", "POST")
        if not isinstance(method, str) or method.upper() not in ALLOWED_ACTION_METHODS:
            raise ValueError(f"action.method must be one of {sorted(ALLOWED_ACTION_METHODS)}")
        method = method.upper()
        path = raw.get("path") or f"/api/actions/{action_name}"
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("action.path must be a string starting with /")
        auth = raw.get("auth", "api")
        if not isinstance(auth, str) or auth not in ALLOWED_ACTION_AUTH:
            raise ValueError(f"action.auth must be one of {sorted(ALLOWED_ACTION_AUTH)}")

        # Avoid accidental collisions with admin/static and CRUD endpoints.
        if path.startswith("/static/"):
            raise ValueError("action.path cannot be under /static/")
        if admin_path and (path == admin_path or path.startswith(admin_path + "/")):
            raise ValueError("action.path cannot be under ui.admin_path")
        for model_name in model_names:
            base = f"/api/{model_name}"
            if path == base or path.startswith(base + "/"):
                raise ValueError(f"action.path collides with CRUD path for model '{model_name}': {path}")

        http_spec = None
        llm_spec = None
        db_spec = None
        value_spec = None
        flow_spec = None
        if kind == "http":
            http_raw = raw.get("http", raw.get("request")) or raw.get("http_request") or {}
            if not isinstance(http_raw, dict):
                raise ValueError("action.http must be an object")
            url = http_raw.get("url") or raw.get("url")
            if not isinstance(url, str) or not url:
                raise ValueError("action.http.url must be a string")
            headers = http_raw.get("headers") or {}
            if not isinstance(headers, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
            ):
                raise ValueError("action.http.headers must be an object of string:string")
            body = http_raw.get("body", None)
            timeout_s = http_raw.get("timeout_s", 30)
            retries = http_raw.get("retries", 0)
            expect = http_raw.get("expect", "auto")
            if not isinstance(timeout_s, int) or timeout_s < 1:
                raise ValueError("action.http.timeout_s must be an int >= 1")
            if not isinstance(retries, int) or retries < 0 or retries > 10:
                raise ValueError("action.http.retries must be an int between 0 and 10")
            if not isinstance(expect, str) or expect not in ("auto", "json", "text"):
                raise ValueError("action.http.expect must be 'auto', 'json', or 'text'")
            http_method = http_raw.get("method")
            if http_method is not None:
                if not isinstance(http_method, str) or http_method.upper() not in ALLOWED_ACTION_METHODS:
                    raise ValueError(f"action.http.method must be one of {sorted(ALLOWED_ACTION_METHODS)}")
                http_method = http_method.upper()
            http_spec = HttpActionSpec(
                url=url,
                method=http_method,
                headers=headers,
                body=body,
                timeout_s=timeout_s,
                retries=retries,
                expect=expect,
            )
        elif kind == "llm":
            llm_raw = raw.get("llm") or {}
            if not isinstance(llm_raw, dict):
                raise ValueError("action.llm must be an object")
            provider = llm_raw.get("provider", "openai")
            if not isinstance(provider, str) or provider.lower() not in ("openai", "ollama"):
                raise ValueError("action.llm.provider must be 'openai' or 'ollama'")
            base_url = llm_raw.get("base_url")
            if base_url is not None and not isinstance(base_url, str):
                raise ValueError("action.llm.base_url must be a string")
            model = llm_raw.get("model")
            if model is not None and not isinstance(model, str):
                raise ValueError("action.llm.model must be a string")
            api_key_env = llm_raw.get("api_key_env", "VIBEWEB_AI_API_KEY")
            if not isinstance(api_key_env, str) or not api_key_env:
                raise ValueError("action.llm.api_key_env must be a string")
            messages = llm_raw.get("messages") or []
            if not isinstance(messages, list):
                raise ValueError("action.llm.messages must be a list")
            for msg in messages:
                if not isinstance(msg, dict):
                    raise ValueError("action.llm.messages items must be objects")
                role = msg.get("role")
                content = msg.get("content")
                if role not in ("system", "user", "assistant"):
                    raise ValueError("action.llm.messages.role must be system|user|assistant")
                if not isinstance(content, str):
                    raise ValueError("action.llm.messages.content must be a string")
            temperature = llm_raw.get("temperature", 0.2)
            if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
                raise ValueError("action.llm.temperature must be between 0 and 2")
            max_tokens = llm_raw.get("max_tokens")
            if max_tokens is not None:
                if not isinstance(max_tokens, int) or max_tokens < 1:
                    raise ValueError("action.llm.max_tokens must be int >= 1")
            timeout_s = llm_raw.get("timeout_s", 60)
            retries = llm_raw.get("retries", 0)
            output = llm_raw.get("output", "text")
            if not isinstance(timeout_s, int) or timeout_s < 1:
                raise ValueError("action.llm.timeout_s must be an int >= 1")
            if not isinstance(retries, int) or retries < 0 or retries > 10:
                raise ValueError("action.llm.retries must be an int between 0 and 10")
            if not isinstance(output, str) or output not in ("text", "json"):
                raise ValueError("action.llm.output must be 'text' or 'json'")
            llm_spec = LlmActionSpec(
                provider=provider.lower(),
                base_url=base_url,
                model=model,
                api_key_env=api_key_env,
                messages=messages,
                temperature=float(temperature),
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                retries=retries,
                output=output,
            )
        elif kind == "db":
            db_raw = raw.get("db") or {}
            if not isinstance(db_raw, dict):
                raise ValueError("action.db must be an object")
            op = db_raw.get("op")
            if not isinstance(op, str) or op not in ALLOWED_DB_OPS:
                raise ValueError(f"action.db.op must be one of {sorted(ALLOWED_DB_OPS)}")
            db_model = db_raw.get("model")
            if not isinstance(db_model, str) or db_model not in model_names:
                raise ValueError("action.db.model must reference a known model")

            model_fields = None
            for m in models:
                if m.name == db_model:
                    model_fields = set(m.fields.keys())
                    break

            def _validate_field_dict(value: Any, label: str) -> Dict[str, Any]:
                if not isinstance(value, dict):
                    raise ValueError(f"action.db.{label} must be an object")
                if model_fields:
                    for key in value.keys():
                        if key not in model_fields:
                            raise ValueError(f"action.db.{label} contains unknown field '{key}' for {db_model}")
                return value  # type: ignore[return-value]

            row_id = db_raw.get("id")
            data = db_raw.get("data")
            patch = db_raw.get("patch")
            limit = int(db_raw.get("limit", 100))
            offset = int(db_raw.get("offset", 0))
            order_by = db_raw.get("order_by")
            if order_by is not None and not isinstance(order_by, str):
                raise ValueError("action.db.order_by must be a string")
            if limit < 1 or limit > 1000:
                raise ValueError("action.db.limit must be between 1 and 1000")
            if offset < 0:
                raise ValueError("action.db.offset must be >= 0")

            if op == "insert":
                if data is None:
                    raise ValueError("action.db.data is required for op=insert")
                data = _validate_field_dict(data, "data")
                if not data:
                    raise ValueError("action.db.data must include at least one field")
            elif op == "update":
                if row_id is None or not isinstance(row_id, (str, int)):
                    raise ValueError("action.db.id is required for op=update (string or int)")
                if patch is None:
                    raise ValueError("action.db.patch is required for op=update")
                patch = _validate_field_dict(patch, "patch")
            elif op in ("get", "delete"):
                if row_id is None or not isinstance(row_id, (str, int)):
                    raise ValueError(f"action.db.id is required for op={op} (string or int)")
            elif op == "list":
                pass

            db_spec = DbActionSpec(
                op=op,
                model=db_model,
                id=row_id,
                data=data if isinstance(data, dict) else None,
                patch=patch if isinstance(patch, dict) else None,
                limit=limit,
                offset=offset,
                order_by=order_by,
            )
        elif kind == "value":
            value_raw = raw.get("value")
            if not isinstance(value_raw, dict):
                raise ValueError("action.value must be an object")
            if "data" not in value_raw:
                raise ValueError("action.value.data is required (can be null)")
            status = value_raw.get("status", 200)
            ok = value_raw.get("ok", True)
            if not isinstance(status, int) or status < 100 or status > 599:
                raise ValueError("action.value.status must be an int between 100 and 599")
            if not isinstance(ok, bool):
                raise ValueError("action.value.ok must be a boolean")
            value_spec = ValueActionSpec(
                data=value_raw.get("data"),
                status=int(status),
                ok=bool(ok),
            )
        elif kind == "flow":
            flow_raw = raw.get("flow") or {}
            if not isinstance(flow_raw, dict):
                raise ValueError("action.flow must be an object")
            flow_vars = flow_raw.get("vars")
            if flow_vars is not None:
                if not isinstance(flow_vars, dict):
                    raise ValueError("action.flow.vars must be an object")
                for key in flow_vars.keys():
                    if not isinstance(key, str) or not key:
                        raise ValueError("action.flow.vars keys must be strings")
                    _require_ident(key, what="flow vars key")
            steps_raw = flow_raw.get("steps") or []
            if not isinstance(steps_raw, list) or not steps_raw:
                raise ValueError("action.flow.steps must be a non-empty list")
            steps: List[FlowStepSpec] = []
            step_ids: set[str] = set()
            for step_raw in steps_raw:
                if not isinstance(step_raw, dict):
                    raise ValueError("flow step must be an object")
                step_id = step_raw.get("id")
                if not isinstance(step_id, str) or not step_id:
                    raise ValueError("flow step.id must be a string")
                _require_ident(step_id, what="flow step.id")
                if step_id in step_ids:
                    raise ValueError(f"duplicate flow step id: {step_id}")
                step_ids.add(step_id)
                use = step_raw.get("use")
                if not isinstance(use, str) or not use:
                    raise ValueError("flow step.use must be a string")
                if use == action_name:
                    raise ValueError("flow step.use cannot reference the flow action itself")
                if use not in action_names:
                    raise ValueError(f"flow step.use references unknown action: {use}")
                when = step_raw.get("when")
                if when is not None:
                    _validate_condition(when, what="flow step.when")

                step_retries = step_raw.get("retries", 0)
                if not isinstance(step_retries, int) or step_retries < 0 or step_retries > 10:
                    raise ValueError("flow step.retries must be an int between 0 and 10")
                step_timeout = step_raw.get("timeout_s")
                if step_timeout is not None:
                    if not isinstance(step_timeout, int) or step_timeout < 1:
                        raise ValueError("flow step.timeout_s must be an int >= 1")
                step_parallel = step_raw.get("parallel", False)
                if not isinstance(step_parallel, bool):
                    raise ValueError("flow step.parallel must be a boolean")

                on_error = step_raw.get("on_error")
                if on_error is not None:
                    if not isinstance(on_error, str) or on_error not in ("stop", "continue", "return"):
                        raise ValueError("flow step.on_error must be one of: stop, continue, return")

                set_raw = step_raw.get("set")
                if set_raw is not None:
                    if not isinstance(set_raw, dict):
                        raise ValueError("flow step.set must be an object")
                    for key in set_raw.keys():
                        if not isinstance(key, str) or not key:
                            raise ValueError("flow step.set keys must be strings")
                        _require_ident(key, what="flow step.set key")
                steps.append(
                    FlowStepSpec(
                        id=step_id,
                        use=use,
                        input=step_raw.get("input"),
                        when=when,
                        on_error=on_error,
                        set=set_raw,
                        retries=int(step_retries),
                        timeout_s=int(step_timeout) if isinstance(step_timeout, int) else None,
                        parallel=bool(step_parallel),
                    )
                )
            return_step = flow_raw.get("return_step", flow_raw.get("return"))
            if return_step is not None:
                if not isinstance(return_step, str) or not return_step:
                    raise ValueError("action.flow.return_step must be a string")
                if return_step not in step_ids:
                    raise ValueError("action.flow.return_step must be one of flow step ids")
            flow_spec = FlowActionSpec(steps=steps, return_step=return_step, vars=flow_vars)

        actions.append(
            ActionSpec(
                name=action_name,
                kind=kind,
                method=method,
                path=path,
                auth=auth,
                http=http_spec,
                llm=llm_spec,
                db=db_spec,
                value=value_spec,
                flow=flow_spec,
            )
        )

    # Hooks
    hooks: List[HookSpec] = []
    for raw in hooks_raw:
        if not isinstance(raw, dict):
            raise ValueError("hook must be an object")
        hook_model = raw.get("model")
        if not isinstance(hook_model, str) or hook_model not in model_names:
            raise ValueError("hook.model must reference a known model")
        event = raw.get("event")
        if not isinstance(event, str) or event not in ALLOWED_HOOK_EVENTS:
            raise ValueError(f"hook.event must be one of {sorted(ALLOWED_HOOK_EVENTS)}")
        action_name = raw.get("action")
        if not isinstance(action_name, str) or action_name not in action_names:
            raise ValueError("hook.action must reference a known action")
        mode = raw.get("mode", "async")
        if not isinstance(mode, str) or mode not in ALLOWED_HOOK_MODES:
            raise ValueError(f"hook.mode must be one of {sorted(ALLOWED_HOOK_MODES)}")
        writeback = raw.get("writeback")
        if writeback is not None:
            if not isinstance(writeback, list) or not all(isinstance(f, str) for f in writeback):
                raise ValueError("hook.writeback must be list of strings")
            model_fields = None
            for m in models:
                if m.name == hook_model:
                    model_fields = set(m.fields.keys())
                    break
            if model_fields:
                for field_name in writeback:
                    if field_name not in model_fields:
                        raise ValueError(f"hook.writeback unknown field '{field_name}' for {hook_model}")

        when_changed = raw.get("when_changed")
        if when_changed is not None:
            if not isinstance(when_changed, list) or not all(isinstance(f, str) for f in when_changed):
                raise ValueError("hook.when_changed must be list of strings")
            model_fields = None
            for m in models:
                if m.name == hook_model:
                    model_fields = set(m.fields.keys())
                    break
            if model_fields:
                for field_name in when_changed:
                    if field_name not in model_fields:
                        raise ValueError(f"hook.when_changed unknown field '{field_name}' for {hook_model}")

        when = raw.get("when")
        if when is not None:
            model_fields = None
            for m in models:
                if m.name == hook_model:
                    model_fields = set(m.fields.keys())
                    break
            if isinstance(when, dict) and not _is_op_condition(when):
                for key in when.keys():
                    if not isinstance(key, str):
                        raise ValueError("hook.when keys must be strings")
                    # Backwards compatible: plain field names are validated against the model.
                    # When using dot-path expressions (e.g. row.stage, old.stage), skip field validation.
                    if model_fields and "." not in key and key not in model_fields:
                        raise ValueError(f"hook.when unknown field '{key}' for {hook_model}")
            else:
                _validate_condition(when, what="hook.when")
        hooks.append(
            HookSpec(
                model=hook_model,
                event=event,
                action=action_name,
                mode=mode,
                writeback=writeback,
                when_changed=when_changed,
                when=when,
            )
        )

    return AppSpec(
        name=name,
        spec_version=raw_version,
        db_path=db_path,
        models=models,
        api_crud=crud,
        actions=actions,
        hooks=hooks,
        pages=pages,
        admin_enabled=admin_enabled,
        admin_path=admin_path,
        admin_auth_type=admin_auth_type,
        admin_username=admin_username,
        admin_password=admin_password,
        theme_css_urls=theme_css_urls,
        theme_tailwind_config=theme_tailwind_config,
        theme_classes=theme_classes,
    )

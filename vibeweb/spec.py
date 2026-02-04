import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


ALLOWED_TYPES = {"text", "int", "float", "bool", "datetime", "json"}


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


@dataclass
class AppSpec:
    name: str
    db_path: str = "vibeweb.db"
    models: List[ModelSpec] = field(default_factory=list)
    api_crud: List[str] = field(default_factory=list)
    pages: List[PageSpec] = field(default_factory=list)
    admin_enabled: bool = False
    admin_path: str = "/admin"
    admin_auth_type: str | None = None
    admin_username: str | None = None
    admin_password: str | None = None


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

        fields = model.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"model.fields required for {model_name}")
        for field_name, field_type in fields.items():
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(f"invalid field name in {model_name}")
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
        pages.append(PageSpec(path=path, model=model, title=title, fields=fields))

    return AppSpec(
        name=name,
        db_path=db_path,
        models=models,
        api_crud=crud,
        pages=pages,
        admin_enabled=admin_enabled,
        admin_path=admin_path,
        admin_auth_type=admin_auth_type,
        admin_username=admin_username,
        admin_password=admin_password,
    )

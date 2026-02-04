import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List

from vibelang.runtime import log_event


def log(message: str, **fields: Any) -> None:
    log_event("log", message=message, **fields)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_json(data: Any, **kwargs: Any) -> str:
    return json.dumps(data, ensure_ascii=False, **kwargs)


def from_json(text: str) -> Any:
    return json.loads(text)


def ensure(condition: bool, message: str = "") -> None:
    if not condition:
        raise ValueError(message or "ensure() failed")


def safe_get(obj: Any, path: str | Iterable[Any], default: Any = None) -> Any:
    if isinstance(path, str):
        parts: List[Any] = [p for p in path.split(".") if p]
    else:
        parts = list(path)
    cur = obj
    for part in parts:
        try:
            if isinstance(cur, dict):
                cur = cur[part]
            else:
                cur = getattr(cur, part)
        except Exception:
            return default
    return cur


def env(name: str, default: Any = None) -> Any:
    return os.environ.get(name, default)


def validate_jsonschema(data: Any, schema: Any) -> Any:
    try:
        import jsonschema  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("jsonschema is not installed") from exc
    jsonschema.validate(data, schema)
    return data


def validate_pydantic(model: Any, data: Any) -> Any:
    try:
        # pydantic v1
        return model.parse_obj(data)
    except AttributeError:
        # pydantic v2
        return model.model_validate(data)


def parallel(tasks: Dict[str, Callable[[], Any]], max_workers: int | None = None) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            results[name] = future.result()
    return results

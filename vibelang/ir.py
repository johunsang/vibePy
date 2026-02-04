import json
import re
from pathlib import Path
from typing import Any, Dict, List

from vibelang.parser import parse_vbl

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.match(value))


def load_ir(path: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Top-level IR must be an object")
    return data


def load_program(path: str) -> Dict[str, Any]:
    if path.endswith(".vbl"):
        src = Path(path).read_text(encoding="utf-8")
        return parse_vbl(src)
    return load_ir(path)


def _validate_expr(expr: Any) -> None:
    if isinstance(expr, (str, int, float, bool)) or expr is None:
        return
    if not isinstance(expr, dict):
        raise ValueError(f"Expression must be literal or object: {expr}")
    # permissive: only check structure for known nodes
    if "call" in expr:
        if "args" in expr and not isinstance(expr["args"], list):
            raise ValueError("'call.args' must be list")
        if "kwargs" in expr and not isinstance(expr["kwargs"], dict):
            raise ValueError("'call.kwargs' must be object")
    if "attr" in expr:
        info = expr["attr"]
        if not isinstance(info, dict) or "attr" not in info:
            raise ValueError("'attr' must be object with 'attr'")
    if "index" in expr:
        info = expr["index"]
        if not isinstance(info, dict) or "base" not in info or "index" not in info:
            raise ValueError("'index' must be object with base/index")
    if "list" in expr and not isinstance(expr["list"], list):
        raise ValueError("'list' must be list")
    if "tuple" in expr and not isinstance(expr["tuple"], list):
        raise ValueError("'tuple' must be list")
    if "dict" in expr:
        if not isinstance(expr["dict"], (list, dict)):
            raise ValueError("'dict' must be list or object")
        if isinstance(expr["dict"], list):
            for item in expr["dict"]:
                if not isinstance(item, dict) or "key" not in item or "value" not in item:
                    raise ValueError("'dict' list items must be objects with key/value")
                _validate_expr(item["key"])
                _validate_expr(item["value"])
    if "validate" in expr and not isinstance(expr["validate"], dict):
        raise ValueError("'validate' must be object")
    if "parallel" in expr and not isinstance(expr["parallel"], list):
        raise ValueError("'parallel' must be list")


def _validate_stmt(stmt: Any) -> None:
    if not isinstance(stmt, dict):
        raise ValueError("Statement must be object")
    if "python" in stmt:
        if not isinstance(stmt["python"], (str, list)):
            raise ValueError("'python' statement must be string or list")
        return
    if "set" in stmt:
        info = stmt["set"]
        if not isinstance(info, dict) or "name" not in info or "value" not in info:
            raise ValueError("'set' statement requires name and value")
        _validate_expr(info["value"])
        return
    if "expr" in stmt:
        _validate_expr(stmt["expr"])
        return
    if "return" in stmt:
        _validate_expr(stmt["return"])
        return
    if "if" in stmt:
        info = stmt["if"]
        if not isinstance(info, dict) or "cond" not in info or "then" not in info:
            raise ValueError("'if' statement requires cond/then")
        _validate_expr(info["cond"])
        if not isinstance(info["then"], list):
            raise ValueError("'if.then' must be list")
        for item in info["then"]:
            _validate_stmt(item)
        if "else" in info:
            if not isinstance(info["else"], list):
                raise ValueError("'if.else' must be list")
            for item in info["else"]:
                _validate_stmt(item)
        return
    if "for" in stmt:
        info = stmt["for"]
        if not isinstance(info, dict) or "var" not in info or "iter" not in info or "body" not in info:
            raise ValueError("'for' statement requires var/iter/body")
        _validate_expr(info["iter"])
        if not isinstance(info["body"], list):
            raise ValueError("'for.body' must be list")
        for item in info["body"]:
            _validate_stmt(item)
        return
    if "while" in stmt:
        info = stmt["while"]
        if not isinstance(info, dict) or "cond" not in info or "body" not in info:
            raise ValueError("'while' statement requires cond/body")
        _validate_expr(info["cond"])
        if not isinstance(info["body"], list):
            raise ValueError("'while.body' must be list")
        for item in info["body"]:
            _validate_stmt(item)
        if "else" in info:
            if not isinstance(info["else"], list):
                raise ValueError("'while.else' must be list")
            for item in info["else"]:
                _validate_stmt(item)
        return
    if "break" in stmt:
        return
    if "continue" in stmt:
        return
    if "raise" in stmt:
        if stmt["raise"] is not None:
            _validate_expr(stmt["raise"])
        return
    if "with" in stmt:
        info = stmt["with"]
        if not isinstance(info, dict) or "items" not in info or "body" not in info:
            raise ValueError("'with' statement requires items/body")
        items = info["items"]
        if not isinstance(items, list) or not items:
            raise ValueError("'with.items' must be list")
        for item in items:
            if not isinstance(item, dict) or "context" not in item:
                raise ValueError("'with.items' entries require context")
            _validate_expr(item["context"])
            if "as" in item and not isinstance(item["as"], str):
                raise ValueError("'with.items.as' must be string")
        if not isinstance(info["body"], list):
            raise ValueError("'with.body' must be list")
        for item in info["body"]:
            _validate_stmt(item)
        return
    if "assert" in stmt:
        info = stmt["assert"]
        if not isinstance(info, dict) or "cond" not in info:
            raise ValueError("'assert' statement requires cond")
        _validate_expr(info["cond"])
        if "msg" in info:
            _validate_expr(info["msg"])
        return
    raise ValueError("Unknown statement type")


def validate_ir(ir: Dict[str, Any]) -> None:
    if "run" not in ir:
        raise ValueError("IR must include a 'run' entry")

    meta = ir.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("'meta' must be an object")

    imports = ir.get("imports", [])
    if not isinstance(imports, list):
        raise ValueError("'imports' must be a list")
    for item in imports:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            raise ValueError("Each import must be a string or object")
        if "from" in item:
            if not isinstance(item.get("from"), str):
                raise ValueError("'from' import must be a string")
            names = item.get("import")
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise ValueError("'import' in from-import must be list of strings")
        elif "import" in item:
            if not isinstance(item.get("import"), str):
                raise ValueError("'import' must be a string")
            if "as" in item and not isinstance(item.get("as"), str):
                raise ValueError("'as' must be a string")
        else:
            raise ValueError("Import objects require 'import' or 'from'")

    inputs = ir.get("inputs", {})
    if inputs is not None:
        if not isinstance(inputs, dict):
            raise ValueError("'inputs' must be an object")
        for key in inputs.keys():
            if not isinstance(key, str) or not _is_identifier(key):
                raise ValueError(f"Input name must be identifier: {key}")

    steps = ir.get("steps", [])
    if steps is not None:
        if not isinstance(steps, list):
            raise ValueError("'steps' must be a list")
        seen_names: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Step must be an object")
            name = step.get("name")
            if not isinstance(name, str) or not _is_identifier(name):
                raise ValueError("Step requires valid 'name'")
            if name in seen_names:
                raise ValueError(f"Duplicate step name: {name}")
            seen_names.add(name)
            params = step.get("params", [])
            if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
                raise ValueError("Step 'params' must be list of strings")
            if any(not _is_identifier(p) for p in params):
                raise ValueError("Step params must be identifiers")
            if "body" not in step and "return" not in step:
                raise ValueError(f"Step '{name}' must include 'body' or 'return'")
            if "body" in step:
                body = step["body"]
                if isinstance(body, dict) and "python" in body:
                    body = body["python"]
                if isinstance(body, dict) and "block" in body:
                    if not isinstance(body["block"], list):
                        raise ValueError(f"Step '{name}' body block must be list")
                    for stmt in body["block"]:
                        _validate_stmt(stmt)
                elif not (
                    isinstance(body, str)
                    or (isinstance(body, list) and all(isinstance(b, str) for b in body))
                ):
                    raise ValueError(f"Step '{name}' body must be string, list of strings, or block")
            if "guard" in step and not (isinstance(step["guard"], list) and all(isinstance(g, str) for g in step["guard"])):
                raise ValueError(f"Step '{name}' guard must be list of strings")
            if "retry" in step and not isinstance(step["retry"], int):
                raise ValueError(f"Step '{name}' retry must be integer")
            if "timeout" in step and not isinstance(step["timeout"], int):
                raise ValueError(f"Step '{name}' timeout must be integer seconds")

    run = ir.get("run")
    if isinstance(run, dict) and "block" in run:
        if not isinstance(run["block"], list):
            raise ValueError("'run.block' must be list")
        for stmt in run["block"]:
            _validate_stmt(stmt)
    elif run is not None:
        _validate_expr(run)

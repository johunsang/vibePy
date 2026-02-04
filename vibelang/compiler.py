import ast
from typing import Any, Dict, List, Tuple

from vibelang.ir import load_program, validate_ir
from vibelang.runtime import ExecutionReport, _clear_current_report, _set_current_report


def _format_import(item: Any) -> str:
    if isinstance(item, str):
        return f"import {item}"
    if "from" in item:
        names = ", ".join(item["import"])
        return f"from {item['from']} import {names}"
    module = item["import"]
    if "as" in item:
        return f"import {module} as {item['as']}"
    return f"import {module}"


def _expr_to_py(expr: Any) -> str:
    if isinstance(expr, dict):
        if "python" in expr:
            return expr["python"]
        if "name" in expr:
            return expr["name"]
        if "literal" in expr:
            return repr(expr["literal"])
        if "call" in expr:
            func = expr["call"]
            if isinstance(func, str):
                func_expr = func
            else:
                func_expr = _expr_to_py(func)
            args = [_expr_to_py(a) for a in expr.get("args", [])]
            kwargs = expr.get("kwargs", {})
            kw_parts = [f"{k}={_expr_to_py(v)}" for k, v in kwargs.items()]
            joined = ", ".join(args + kw_parts)
            return f"{func_expr}({joined})"
        if "validate" in expr:
            info = expr["validate"]
            data_expr = _expr_to_py(info["data"])
            if "schema" in info:
                schema_expr = _expr_to_py(info["schema"])
                return f"vbl.validate_jsonschema({data_expr}, {schema_expr})"
            if "model" in info:
                model_expr = _expr_to_py(info["model"])
                return f"vbl.validate_pydantic({model_expr}, {data_expr})"
        if "parallel" in expr:
            tasks = []
            for item in expr["parallel"]:
                name = item["name"]
                call_expr = _expr_to_py(item["call"])
                tasks.append(f"{name!r}: (lambda: {call_expr})")
            joined = ", ".join(tasks)
            return f"vbl.parallel({{{joined}}})"
        if "attr" in expr:
            info = expr["attr"]
            base = _expr_to_py(info.get("base") or info.get("object"))
            return f"{base}.{info['attr']}"
        if "index" in expr:
            info = expr["index"]
            base = _expr_to_py(info["base"])
            idx = _expr_to_py(info["index"])
            return f"{base}[{idx}]"
        if "list" in expr:
            items = ", ".join(_expr_to_py(v) for v in expr["list"])
            return f"[{items}]"
        if "tuple" in expr:
            items = ", ".join(_expr_to_py(v) for v in expr["tuple"])
            return f"({items}{',' if len(expr['tuple']) == 1 else ''})"
        if "dict" in expr:
            if isinstance(expr["dict"], dict):
                parts = [f"{repr(k)}: {_expr_to_py(v)}" for k, v in expr["dict"].items()]
            else:
                parts = [
                    f"{_expr_to_py(item['key'])}: {_expr_to_py(item['value'])}"
                    for item in expr["dict"]
                ]
            return "{" + ", ".join(parts) + "}"
        if "binop" in expr:
            info = expr["binop"]
            left = _expr_to_py(info["left"])
            right = _expr_to_py(info["right"])
            op = info["op"]
            return f"({left} {op} {right})"
    if isinstance(expr, str):
        return expr
    if expr is None or isinstance(expr, (int, float, bool)):
        return repr(expr)
    raise ValueError(f"Unsupported expression node: {expr}")


def _stmt_to_lines(stmt: Dict[str, Any], indent: int, *, in_step: bool) -> List[str]:
    prefix = " " * indent
    if "python" in stmt:
        block = stmt["python"]
        if isinstance(block, str):
            lines = block.splitlines() or ["pass"]
        else:
            lines = block or ["pass"]
        return [prefix + line for line in lines]
    if "set" in stmt:
        info = stmt["set"]
        name = info["name"]
        expr = _expr_to_py(info["value"])
        return [prefix + f"{name} = {expr}"]
    if "expr" in stmt:
        expr = _expr_to_py(stmt["expr"])
        return [prefix + expr]
    if "return" in stmt:
        expr = _expr_to_py(stmt["return"])
        if in_step:
            return [prefix + f"return {expr}"]
        return [prefix + f"__vbl_result__ = {expr}"]
    if "if" in stmt:
        info = stmt["if"]
        cond = _expr_to_py(info["cond"])
        lines = [prefix + f"if {cond}:"]
        then_body = info.get("then", [])
        if then_body:
            for item in then_body:
                lines.extend(_stmt_to_lines(item, indent + 4, in_step=in_step))
        else:
            lines.append(prefix + "    pass")
        else_body = info.get("else", [])
        if else_body:
            lines.append(prefix + "else:")
            for item in else_body:
                lines.extend(_stmt_to_lines(item, indent + 4, in_step=in_step))
        return lines
    if "for" in stmt:
        info = stmt["for"]
        var = info["var"]
        it = _expr_to_py(info["iter"])
        lines = [prefix + f"for {var} in {it}:"]
        body = info.get("body", [])
        if body:
            for item in body:
                lines.extend(_stmt_to_lines(item, indent + 4, in_step=in_step))
        else:
            lines.append(prefix + "    pass")
        return lines
    raise ValueError(f"Unsupported statement node: {stmt}")


def _render_block(stmts: List[Dict[str, Any]], indent: int, *, in_step: bool) -> List[str]:
    lines: List[str] = []
    if not stmts:
        return [" " * indent + "pass"]
    for stmt in stmts:
        lines.extend(_stmt_to_lines(stmt, indent, in_step=in_step))
    return lines


def _render_step(step: Dict[str, Any]) -> List[str]:
    decorator_args = []
    for key in ("retry", "timeout", "guard", "produces"):
        if key in step:
            decorator_args.append(f"{key}={repr(step[key])}")
    decorator = "@step(" + ", ".join(decorator_args) + ")"
    params = ", ".join(step.get("params", []))
    lines = [decorator, f"def {step['name']}({params}):"]
    body = step.get("body")
    if isinstance(body, dict) and "python" in body:
        body = body["python"]
    if body is not None:
        if isinstance(body, dict) and "block" in body:
            lines.extend(_render_block(body["block"], 4, in_step=True))
        else:
            if isinstance(body, str):
                body_lines = body.splitlines() or ["pass"]
            else:
                body_lines = body or ["pass"]
            for line in body_lines:
                lines.append("    " + line)
    elif "return" in step:
        expr = _expr_to_py(step["return"])
        lines.append(f"    return {expr}")
    else:
        lines.append("    pass")
    return lines


def compile_ir_to_source(ir: Dict[str, Any]) -> str:
    validate_ir(ir)

    lines: List[str] = []
    lines.append("from vibelang.runtime import step")
    lines.append("import vibelang.std as vbl")
    lines.append("")

    for item in ir.get("imports", []):
        lines.append(_format_import(item))
    if ir.get("imports"):
        lines.append("")

    inputs = ir.get("inputs", {}) or {}
    if inputs:
        for name in inputs.keys():
            lines.append(f"{name} = __vbl_inputs__.get({name!r})")
        lines.append("")

    for step in ir.get("steps", []) or []:
        lines.extend(_render_step(step))
        lines.append("")

    run = ir["run"]
    if isinstance(run, dict) and "python" in run:
        block = run["python"]
        if isinstance(block, str):
            block_lines = block.splitlines()
        else:
            block_lines = block
        lines.append("__vbl_result__ = None")
        if block_lines:
            lines.extend(block_lines)
    elif isinstance(run, dict) and "block" in run:
        lines.append("def __vbl_run__():")
        lines.extend(_render_block(run["block"], 4, in_step=True))
        lines.append("__vbl_result__ = __vbl_run__()")
    else:
        expr = _expr_to_py(run)
        lines.append(f"__vbl_result__ = {expr}")

    return "\n".join(lines).rstrip() + "\n"


def compile_ir(ir: Dict[str, Any], filename: str = "<vibelang>") -> Tuple[Any, str]:
    source = compile_ir_to_source(ir)
    tree = ast.parse(source, filename=filename)
    code = compile(tree, filename=filename, mode="exec")
    return code, source


def execute_ir(ir: Dict[str, Any], *, inputs: Dict[str, Any] | None = None) -> Tuple[Any, ExecutionReport, str]:
    inputs_data = dict(ir.get("inputs", {}) or {})
    if inputs:
        inputs_data.update(inputs)
    report = ExecutionReport(meta=ir.get("meta", {}) or {})
    _set_current_report(report)
    code, source = compile_ir(ir)
    globals_dict: Dict[str, Any] = {
        "__name__": "__vbl__",
        "__vbl_inputs__": inputs_data,
    }
    try:
        exec(code, globals_dict, globals_dict)
        result = globals_dict.get("__vbl_result__")
        report.finish(result)
        return result, report, source
    finally:
        _clear_current_report()


def compile_file(path: str) -> Tuple[Any, str, Dict[str, Any]]:
    ir = load_program(path)
    code, source = compile_ir(ir, filename=path)
    return code, source, ir


def run_file(path: str, *, inputs: Dict[str, Any] | None = None) -> Tuple[Any, ExecutionReport, str, Dict[str, Any]]:
    ir = load_program(path)
    result, report, source = execute_ir(ir, inputs=inputs)
    return result, report, source, ir

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class Symbol:
    name: str


_TOKEN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _read_string(src: str, i: int) -> Tuple[str, int]:
    out: List[str] = []
    i += 1  # skip opening quote
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 1
            if i >= len(src):
                break
            esc = src[i]
            if esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            elif esc == "r":
                out.append("\r")
            elif esc == '"':
                out.append('"')
            elif esc == "\\":
                out.append("\\")
            else:
                out.append(esc)
            i += 1
            continue
        if ch == '"':
            i += 1
            return "".join(out), i
        out.append(ch)
        i += 1
    raise ValueError("Unterminated string literal")


def tokenize(src: str) -> List[Any]:
    tokens: List[Any] = []
    i = 0
    while i < len(src):
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch in ("#", ";"):
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if ch == "(":
            tokens.append("(")
            i += 1
            continue
        if ch == ")":
            tokens.append(")")
            i += 1
            continue
        if ch == '"':
            value, i = _read_string(src, i)
            tokens.append(("string", value))
            continue
        # symbol/number
        start = i
        while i < len(src) and src[i] not in " \t\r\n()":
            i += 1
        raw = src[start:i]
        if _TOKEN_NUMBER.match(raw):
            if "." in raw:
                tokens.append(("number", float(raw)))
            else:
                tokens.append(("number", int(raw)))
        elif raw == "true":
            tokens.append(("literal", True))
        elif raw == "false":
            tokens.append(("literal", False))
        elif raw == "null":
            tokens.append(("literal", None))
        else:
            tokens.append(("symbol", raw))
    return tokens


def parse_tokens(tokens: List[Any]) -> List[Any]:
    pos = 0

    def parse_expr() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of input")
        tok = tokens[pos]
        if tok == "(":
            pos += 1
            items: List[Any] = []
            while pos < len(tokens) and tokens[pos] != ")":
                items.append(parse_expr())
            if pos >= len(tokens):
                raise ValueError("Missing closing parenthesis")
            pos += 1
            return items
        if tok == ")":
            raise ValueError("Unexpected ')' ")
        pos += 1
        kind, value = tok
        if kind == "symbol":
            return Symbol(value)
        return value

    forms: List[Any] = []
    while pos < len(tokens):
        forms.append(parse_expr())
    return forms


_BINOPS = {"+", "-", "*", "/", "//", "%", "**", "and", "or", "==", "!=", "<", ">", "<=", ">="}


def _sym(node: Any) -> str:
    if isinstance(node, Symbol):
        return node.name
    raise ValueError(f"Expected symbol, got: {node}")


def _expr(node: Any) -> Any:
    if isinstance(node, Symbol):
        return {"name": node.name}
    if isinstance(node, (str, int, float, bool)) or node is None:
        return {"literal": node}
    if not isinstance(node, list):
        raise ValueError(f"Unsupported expression node: {node}")
    if not node:
        raise ValueError("Empty expression list")
    head = node[0]
    if isinstance(head, Symbol) and head.name in _BINOPS:
        if len(node) < 3:
            raise ValueError(f"Operator {head.name} requires operands")
        left = _expr(node[1])
        right = _expr(node[2])
        expr = {"binop": {"op": head.name, "left": left, "right": right}}
        for extra in node[3:]:
            expr = {"binop": {"op": head.name, "left": expr, "right": _expr(extra)}}
        return expr
    if isinstance(head, Symbol) and head.name == "attr":
        if len(node) != 3:
            raise ValueError("attr requires base and attr name")
        return {"attr": {"base": _expr(node[1]), "attr": _sym(node[2])}}
    if isinstance(head, Symbol) and head.name == "index":
        if len(node) != 3:
            raise ValueError("index requires base and index")
        return {"index": {"base": _expr(node[1]), "index": _expr(node[2])}}
    if isinstance(head, Symbol) and head.name == "list":
        return {"list": [_expr(n) for n in node[1:]]}
    if isinstance(head, Symbol) and head.name == "tuple":
        return {"tuple": [_expr(n) for n in node[1:]]}
    if isinstance(head, Symbol) and head.name == "dict":
        entries = []
        for item in node[1:]:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("dict entries must be (key value)")
            entries.append({"key": _expr(item[0]), "value": _expr(item[1])})
        return {"dict": entries}
    if isinstance(head, Symbol) and head.name == "python":
        if len(node) != 2 or not isinstance(node[1], str):
            raise ValueError("python expression requires a string")
        return {"python": node[1]}
    if isinstance(head, Symbol) and head.name == "validate":
        if len(node) == 3:
            return {"validate": {"schema": _expr(node[1]), "data": _expr(node[2])}}
        schema = None
        data = None
        for item in node[1:]:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("validate entries must be (schema X) or (data X)")
            key = _sym(item[0])
            if key == "schema":
                schema = _expr(item[1])
            elif key == "data":
                data = _expr(item[1])
            elif key == "model":
                schema = {"model": _expr(item[1])}
            else:
                raise ValueError(f"Unknown validate key: {key}")
        if data is None:
            raise ValueError("validate requires data")
        if schema is None:
            raise ValueError("validate requires schema or model")
        if isinstance(schema, dict) and "model" in schema:
            return {"validate": {"model": schema["model"], "data": data}}
        return {"validate": {"schema": schema, "data": data}}
    if isinstance(head, Symbol) and head.name == "parallel":
        tasks = []
        for item in node[1:]:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("parallel tasks must be (name expr)")
            tasks.append({"name": _sym(item[0]), "call": _expr(item[1])})
        return {"parallel": tasks}
    if isinstance(head, Symbol) and head.name == "call":
        if len(node) < 2:
            raise ValueError("call requires function")
        func_expr = _expr(node[1])
        args: List[Any] = []
        kwargs: Dict[str, Any] = {}
        for arg in node[2:]:
            if isinstance(arg, list) and arg and isinstance(arg[0], Symbol) and arg[0].name == "kw":
                if len(arg) != 3:
                    raise ValueError("kw requires key and value")
                kwargs[_sym(arg[1])] = _expr(arg[2])
            else:
                args.append(_expr(arg))
        return {"call": func_expr, "args": args, "kwargs": kwargs}

    # default: call form
    func_expr = _expr(head) if not isinstance(head, Symbol) else head.name
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    for arg in node[1:]:
        if isinstance(arg, list) and arg and isinstance(arg[0], Symbol) and arg[0].name == "kw":
            if len(arg) != 3:
                raise ValueError("kw requires key and value")
            kwargs[_sym(arg[1])] = _expr(arg[2])
        else:
            args.append(_expr(arg))
    return {"call": func_expr, "args": args, "kwargs": kwargs}


def _stmt(node: Any) -> Dict[str, Any]:
    if not isinstance(node, list) or not node:
        return {"expr": _expr(node)}
    head = node[0]
    if isinstance(head, Symbol) and head.name == "set":
        if len(node) != 3:
            raise ValueError("set requires name and value")
        return {"set": {"name": _sym(node[1]), "value": _expr(node[2])}}
    if isinstance(head, Symbol) and head.name == "return":
        if len(node) != 2:
            raise ValueError("return requires value")
        return {"return": _expr(node[1])}
    if isinstance(head, Symbol) and head.name == "expr":
        if len(node) != 2:
            raise ValueError("expr requires expression")
        return {"expr": _expr(node[1])}
    if isinstance(head, Symbol) and head.name == "python":
        lines: List[str] = []
        for item in node[1:]:
            if not isinstance(item, str):
                raise ValueError("python statements must be strings")
            lines.append(item)
        return {"python": lines}
    if isinstance(head, Symbol) and head.name == "if":
        if len(node) < 3:
            raise ValueError("if requires condition and body")
        cond = _expr(node[1])
        then_block: List[Dict[str, Any]] = []
        else_block: List[Dict[str, Any]] = []
        for part in node[2:]:
            if not isinstance(part, list) or not part:
                raise ValueError("if body must be (then ...) or (else ...)")
            tag = _sym(part[0])
            if tag in ("then", "do"):
                then_block = [_stmt(p) for p in part[1:]]
            elif tag == "else":
                else_block = [_stmt(p) for p in part[1:]]
            else:
                raise ValueError("if body must be (then ...) or (else ...)")
        return {"if": {"cond": cond, "then": then_block, "else": else_block}}
    if isinstance(head, Symbol) and head.name == "for":
        if len(node) < 4:
            raise ValueError("for requires var, iter, and body")
        var = _sym(node[1])
        it = _expr(node[2])
        body_part = node[3]
        if not isinstance(body_part, list) or not body_part:
            raise ValueError("for body must be (do ...) ")
        if _sym(body_part[0]) != "do":
            raise ValueError("for body must be (do ...)")
        body = [_stmt(p) for p in body_part[1:]]
        return {"for": {"var": var, "iter": it, "body": body}}
    if isinstance(head, Symbol) and head.name == "while":
        if len(node) < 3:
            raise ValueError("while requires condition and body")
        cond = _expr(node[1])
        body_part = node[2]
        if not isinstance(body_part, list) or not body_part:
            raise ValueError("while body must be (do ...)")
        if _sym(body_part[0]) != "do":
            raise ValueError("while body must be (do ...)")
        body = [_stmt(p) for p in body_part[1:]]
        return {"while": {"cond": cond, "body": body}}
    if isinstance(head, Symbol) and head.name == "break":
        return {"break": True}
    if isinstance(head, Symbol) and head.name == "continue":
        return {"continue": True}
    if isinstance(head, Symbol) and head.name == "raise":
        if len(node) == 1:
            return {"raise": None}
        if len(node) == 2:
            return {"raise": _expr(node[1])}
        raise ValueError("raise takes zero or one argument")
    if isinstance(head, Symbol) and head.name == "assert":
        if len(node) < 2:
            raise ValueError("assert requires condition")
        cond = _expr(node[1])
        msg = _expr(node[2]) if len(node) > 2 else None
        return {"assert": {"cond": cond, "msg": msg} if msg is not None else {"cond": cond}}
    if isinstance(head, Symbol) and head.name == "with":
        if len(node) < 3:
            raise ValueError("with requires items and body")
        items_node = node[1]
        if not isinstance(items_node, list) or not items_node:
            raise ValueError("with items must be a list")
        items: List[Dict[str, Any]] = []
        if items_node and isinstance(items_node[0], list):
            for item in items_node:
                if not isinstance(item, list) or not item:
                    raise ValueError("with item must be (context var?)")
                context = _expr(item[0])
                if len(item) > 1:
                    items.append({"context": context, "as": _sym(item[1])})
                else:
                    items.append({"context": context})
        else:
            context = _expr(items_node[0])
            if len(items_node) > 1:
                items.append({"context": context, "as": _sym(items_node[1])})
            else:
                items.append({"context": context})
        body_part = node[2]
        if not isinstance(body_part, list) or not body_part or _sym(body_part[0]) != "do":
            raise ValueError("with body must be (do ...)")
        body = [_stmt(p) for p in body_part[1:]]
        return {"with": {"items": items, "body": body}}
    return {"expr": _expr(node)}


def parse_vbl(src: str) -> Dict[str, Any]:
    forms = parse_tokens(tokenize(src))
    ir: Dict[str, Any] = {
        "meta": {},
        "imports": [],
        "inputs": {},
        "steps": [],
        "run": None,
    }

    for form in forms:
        if not isinstance(form, list) or not form:
            raise ValueError("Top-level forms must be lists")
        head = form[0]
        if not isinstance(head, Symbol):
            raise ValueError("Top-level forms must start with a symbol")
        name = head.name
        if name == "meta":
            for item in form[1:]:
                if not isinstance(item, list) or len(item) != 2:
                    raise ValueError("meta entries must be (key value)")
                ir["meta"][_sym(item[0])] = item[1] if not isinstance(item[1], Symbol) else item[1].name
        elif name == "import":
            if len(form) == 2:
                ir["imports"].append(_sym(form[1]) if isinstance(form[1], Symbol) else form[1])
            elif len(form) == 4 and _sym(form[2]) == "as":
                ir["imports"].append({"import": _sym(form[1]), "as": _sym(form[3])})
            else:
                raise ValueError("import form: (import module) or (import module as alias)")
        elif name == "from":
            if len(form) < 4 or _sym(form[2]) != "import":
                raise ValueError("from form: (from module import name1 name2)")
            module = _sym(form[1])
            names = [_sym(n) for n in form[3:]]
            ir["imports"].append({"from": module, "import": names})
        elif name == "input":
            if len(form) != 3:
                raise ValueError("input form: (input name value)")
            ir["inputs"][_sym(form[1])] = form[2] if not isinstance(form[2], Symbol) else form[2].name
        elif name == "inputs":
            for item in form[1:]:
                if not isinstance(item, list) or len(item) != 2:
                    raise ValueError("inputs entries must be (name value)")
                ir["inputs"][_sym(item[0])] = item[1] if not isinstance(item[1], Symbol) else item[1].name
        elif name == "step":
            if len(form) < 2:
                raise ValueError("step requires a name")
            step_name = _sym(form[1])
            step: Dict[str, Any] = {"name": step_name, "params": []}
            for part in form[2:]:
                if not isinstance(part, list) or not part:
                    raise ValueError("step options must be lists")
                key = _sym(part[0])
                if key == "params":
                    step["params"] = [_sym(p) for p in part[1:]]
                elif key in ("retry", "timeout"):
                    if len(part) != 2 or not isinstance(part[1], int):
                        raise ValueError(f"{key} requires integer")
                    step[key] = part[1]
                elif key == "guard":
                    if not all(isinstance(p, str) for p in part[1:]):
                        raise ValueError("guard entries must be strings")
                    step["guard"] = list(part[1:])
                elif key == "produces":
                    if len(part) != 2:
                        raise ValueError("produces requires value")
                    step["produces"] = part[1] if not isinstance(part[1], Symbol) else part[1].name
                elif key == "body":
                    # body can be python lines (strings) or block statements
                    if not part[1:]:
                        step["body"] = []
                    elif all(isinstance(p, str) for p in part[1:]):
                        step["body"] = list(part[1:])
                    else:
                        if any(isinstance(p, str) for p in part[1:]):
                            raise ValueError("body must be all strings or all statements")
                        step["body"] = {"block": [_stmt(p) for p in part[1:]]}
                elif key == "return":
                    if len(part) != 2:
                        raise ValueError("return requires expression")
                    step["return"] = _expr(part[1])
                else:
                    raise ValueError(f"Unknown step attribute: {key}")
            ir["steps"].append(step)
        elif name == "run":
            if len(form) != 2:
                raise ValueError("run requires single expression or block")
            run_node = form[1]
            if isinstance(run_node, list) and run_node and isinstance(run_node[0], Symbol) and run_node[0].name == "block":
                ir["run"] = {"block": [_stmt(p) for p in run_node[1:]]}
            else:
                ir["run"] = _expr(run_node)
        else:
            raise ValueError(f"Unknown top-level form: {name}")

    if ir["run"] is None:
        raise ValueError("Program requires a run form")
    return ir

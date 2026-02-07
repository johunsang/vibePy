from __future__ import annotations

import re
from typing import Any


class ConditionError(ValueError):
    pass


_OP_RE = re.compile(r"^\$[a-zA-Z_][a-zA-Z0-9_]*$")


def lookup_path(expr: str, ctx: dict[str, Any]) -> Any:
    """
    Dot-path lookup used by conditions and flow 'when'.

    Examples:
      - "input.row.stage"
      - "row.amount"
      - "steps.invoice.ok"
      - "vars.invoice_number"

    Returns None if any segment is missing.
    """
    parts = [p for p in str(expr).strip().split(".") if p]
    if not parts:
        return None
    value: Any = ctx.get(parts[0])
    for key in parts[1:]:
        if isinstance(value, dict):
            value = value.get(key)
            continue
        if isinstance(value, list) and key.isdigit():
            idx = int(key)
            if 0 <= idx < len(value):
                value = value[idx]
                continue
            return None
        return None
    return value


def _is_op_dict(obj: dict[str, Any]) -> bool:
    for k in obj.keys():
        if isinstance(k, str) and k.startswith("$"):
            return True
    return False


def eval_condition(cond: Any, ctx: dict[str, Any]) -> bool:
    """
    Safe condition evaluation for VibeWeb.

    Supported forms:
      1) Equality map (AND):
         {"row.stage": "Closed Won", "steps.invoice.ok": True}

      2) Operators:
         {"$and": [cond, cond, ...]}
         {"$or": [cond, cond, ...]}
         {"$not": cond}
         {"$eq": ["expr", value]}
         {"$ne": ["expr", value]}
         {"$gt": ["expr", number]}
         {"$gte": ["expr", number]}
         {"$lt": ["expr", number]}
         {"$lte": ["expr", number]}
         {"$in": ["expr", [value, ...]]}
         {"$contains": ["expr", value]}
         {"$startsWith": ["expr", "prefix"]}
         {"$endsWith": ["expr", "suffix"]}
         {"$regex": ["expr", "pattern"]}
         {"$any": ["expr", <cond>]}  # expr resolves to list; bind each element to item
         {"$all": ["expr", <cond>]}  # expr resolves to list; bind each element to item
         {"$exists": "expr"} or {"$exists": ["expr", true|false]}
         {"$truthy": "expr"}
    """
    if cond is None:
        return True

    if isinstance(cond, bool):
        return cond

    if isinstance(cond, list):
        # Convenience: treat a list as implicit AND.
        return all(eval_condition(item, ctx) for item in cond)

    if not isinstance(cond, dict):
        return False

    if not _is_op_dict(cond):
        for expr, expected in cond.items():
            if not isinstance(expr, str) or not expr.strip():
                return False
            actual = lookup_path(expr, ctx)
            if actual != expected:
                return False
        return True

    if len(cond) != 1:
        raise ConditionError("Operator condition objects must have exactly one $operator key")

    op, arg = next(iter(cond.items()))
    if not isinstance(op, str) or not _OP_RE.match(op):
        raise ConditionError("Invalid $operator key")

    if op == "$and":
        if not isinstance(arg, list):
            raise ConditionError("$and expects a list")
        return all(eval_condition(item, ctx) for item in arg)

    if op == "$or":
        if not isinstance(arg, list):
            raise ConditionError("$or expects a list")
        return any(eval_condition(item, ctx) for item in arg)

    if op == "$not":
        return not eval_condition(arg, ctx)

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
            raise ConditionError(f"{op} expects [expr, value]")
        expr, expected = arg
        if not isinstance(expr, str) or not expr.strip():
            raise ConditionError(f"{op} expr must be a non-empty string")
        actual = lookup_path(expr, ctx)

        if op == "$eq":
            return actual == expected
        if op == "$ne":
            return actual != expected

        if op in ("$gt", "$gte", "$lt", "$lte"):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                return False
            if not isinstance(expected, (int, float)) or isinstance(expected, bool):
                return False
            if op == "$gt":
                return float(actual) > float(expected)
            if op == "$gte":
                return float(actual) >= float(expected)
            if op == "$lt":
                return float(actual) < float(expected)
            if op == "$lte":
                return float(actual) <= float(expected)

        if op == "$in":
            if not isinstance(expected, list):
                raise ConditionError("$in expects [expr, [values...]]")
            return actual in expected

        if op == "$contains":
            hay = actual
            needle = expected
            if isinstance(hay, str) and isinstance(needle, str):
                return needle in hay
            if isinstance(hay, list):
                return needle in hay
            if isinstance(hay, dict) and isinstance(needle, str):
                return needle in hay
            return False

        if op == "$startsWith":
            if not isinstance(expected, str):
                raise ConditionError("$startsWith expects [expr, prefix_string]")
            if not isinstance(actual, str):
                return False
            return actual.startswith(expected)

        if op == "$endsWith":
            if not isinstance(expected, str):
                raise ConditionError("$endsWith expects [expr, suffix_string]")
            if not isinstance(actual, str):
                return False
            return actual.endswith(expected)

        if op == "$regex":
            if not isinstance(expected, str):
                raise ConditionError("$regex expects [expr, pattern_string]")
            if not isinstance(actual, str):
                return False
            try:
                return re.search(expected, actual) is not None
            except re.error as exc:
                raise ConditionError(f"Invalid regex: {exc}") from exc

        if op in ("$any", "$all"):
            if not isinstance(expected, dict):
                raise ConditionError(f"{op} expects [expr, <condition_object>]")
            if actual is None:
                items: list[Any] = []
            elif isinstance(actual, list):
                items = actual
            else:
                return False
            if op == "$any":
                for item in items:
                    item_ctx = dict(ctx)
                    item_ctx["item"] = item
                    if eval_condition(expected, item_ctx):
                        return True
                return False
            # Vacuous truth: $all over an empty list returns true.
            for item in items:
                item_ctx = dict(ctx)
                item_ctx["item"] = item
                if not eval_condition(expected, item_ctx):
                    return False
            return True

    if op == "$exists":
        expr = arg
        expected_bool: bool | None = None
        if isinstance(arg, list):
            if len(arg) != 2:
                raise ConditionError("$exists expects 'expr' or ['expr', bool]")
            expr, expected_bool = arg
        if not isinstance(expr, str) or not expr.strip():
            raise ConditionError("$exists expr must be a non-empty string")
        exists = lookup_path(expr, ctx) is not None
        return exists if expected_bool is None else (exists == bool(expected_bool))

    if op == "$truthy":
        if not isinstance(arg, str) or not arg.strip():
            raise ConditionError("$truthy expects 'expr'")
        return bool(lookup_path(arg, ctx))

    raise ConditionError(f"Unknown operator: {op}")

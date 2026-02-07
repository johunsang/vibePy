import json
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Tuple

from vibeweb.spec import ModelSpec


_SQL_TYPES = {
    "text": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "datetime": "TEXT",
    "json": "TEXT",
}

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_safe_ident(value: str, *, what: str) -> None:
    # Keep SQLite identifiers simple and safe, since we build SQL strings.
    if not _SAFE_IDENT_RE.match(value):
        raise ValueError(f"Invalid {what} identifier: {value!r}")


def _sql_type(field_type: str) -> str:
    if field_type.startswith("ref:"):
        return "INTEGER"
    return _SQL_TYPES[field_type]


def connect(path: str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection, models: Iterable[ModelSpec]) -> None:
    for model in models:
        _require_safe_ident(model.name, what="model")
        fields_sql = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for name, ftype in model.fields.items():
            _require_safe_ident(name, what=f"field in {model.name}")
            sql_type = _sql_type(ftype)
            fields_sql.append(f"{name} {sql_type}")
        sql = f"CREATE TABLE IF NOT EXISTS {model.name} (" + ", ".join(fields_sql) + ")"
        conn.execute(sql)

        # Lightweight additive migration: add missing columns when the spec evolves.
        existing: set[str] = set()
        try:
            cur = conn.execute(f"PRAGMA table_info({model.name})")
            existing = {str(row["name"]) for row in cur.fetchall() if row["name"] is not None}
        except Exception:
            existing = set()
        for name, ftype in model.fields.items():
            if name in existing:
                continue
            sql_type = _sql_type(ftype)
            conn.execute(f"ALTER TABLE {model.name} ADD COLUMN {name} {sql_type}")
    conn.commit()


def normalize_row(model: ModelSpec, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize DB row values into JSON-friendly types.

    - bool fields become Python bool (or None)
    - json fields are parsed back into objects when possible
    - everything else is passed through
    """
    normalized: Dict[str, Any] = {"id": row.get("id")}
    for field, ftype in model.fields.items():
        value = row.get(field)
        if ftype == "bool":
            if value is None:
                normalized[field] = None
            else:
                try:
                    normalized[field] = bool(int(value))
                except Exception:
                    normalized[field] = bool(value)
        elif ftype == "json":
            if isinstance(value, str):
                try:
                    normalized[field] = json.loads(value)
                except Exception:
                    normalized[field] = value
            else:
                normalized[field] = value
        else:
            normalized[field] = value
    return normalized


def normalize_rows(model: ModelSpec, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_row(model, row) for row in rows]


def list_rows(
    conn: sqlite3.Connection,
    model: ModelSpec,
    *,
    limit: int = 100,
    offset: int = 0,
    where: str = "",
    params: tuple[Any, ...] = (),
    order_by: str = "id DESC",
) -> List[Dict[str, Any]]:
    sql = f"SELECT * FROM {model.name}"
    if where:
        sql += " WHERE " + where
    sql += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
    cursor = conn.execute(sql, params + (limit, offset))
    return [dict(row) for row in cursor.fetchall()]


def count_rows(
    conn: sqlite3.Connection,
    model: ModelSpec,
    *,
    where: str = "",
    params: tuple[Any, ...] = (),
) -> int:
    sql = f"SELECT COUNT(*) as count FROM {model.name}"
    if where:
        sql += " WHERE " + where
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    return int(row["count"]) if row else 0


def get_row(conn: sqlite3.Connection, model: ModelSpec, row_id: int) -> Dict[str, Any] | None:
    cursor = conn.execute(f"SELECT * FROM {model.name} WHERE id = ?", (row_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def insert_row(conn: sqlite3.Connection, model: ModelSpec, data: Dict[str, Any]) -> Dict[str, Any]:
    fields: List[str] = []
    values: List[Any] = []
    for name in model.fields.keys():
        if name in data:
            fields.append(name)
            values.append(_coerce_value(model.fields[name], data[name]))
    if not fields:
        raise ValueError("No fields provided")
    placeholders = ", ".join(["?"] * len(fields))
    sql = f"INSERT INTO {model.name} (" + ", ".join(fields) + ") VALUES (" + placeholders + ")"
    cur = conn.execute(sql, tuple(values))
    conn.commit()
    return get_row(conn, model, cur.lastrowid) or {}


def update_row(conn: sqlite3.Connection, model: ModelSpec, row_id: int, data: Dict[str, Any]) -> Dict[str, Any] | None:
    fields: List[str] = []
    values: List[Any] = []
    for name in model.fields.keys():
        if name in data:
            fields.append(f"{name} = ?")
            values.append(_coerce_value(model.fields[name], data[name]))
    if not fields:
        return get_row(conn, model, row_id)
    values.append(row_id)
    sql = f"UPDATE {model.name} SET " + ", ".join(fields) + " WHERE id = ?"
    conn.execute(sql, tuple(values))
    conn.commit()
    return get_row(conn, model, row_id)


def delete_row(conn: sqlite3.Connection, model: ModelSpec, row_id: int) -> bool:
    cur = conn.execute(f"DELETE FROM {model.name} WHERE id = ?", (row_id,))
    conn.commit()
    return cur.rowcount > 0


def _coerce_value(field_type: str, value: Any) -> Any:
    if value is None:
        return None
    if field_type.startswith("ref:"):
        if value == "":
            return None
        return int(value)
    if field_type == "json":
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if not isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return value
    if field_type == "bool":
        if isinstance(value, str):
            return 1 if value.lower() in ("1", "true", "yes", "on") else 0
        return 1 if bool(value) else 0
    if field_type == "int":
        return int(value)
    if field_type == "float":
        return float(value)
    return value

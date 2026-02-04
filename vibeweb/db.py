import sqlite3
from typing import Any, Dict, Iterable, List, Tuple

from vibeweb.spec import ModelSpec


_SQL_TYPES = {
    "text": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "datetime": "TEXT",
}


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection, models: Iterable[ModelSpec]) -> None:
    for model in models:
        fields_sql = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for name, ftype in model.fields.items():
            sql_type = _SQL_TYPES[ftype]
            fields_sql.append(f"{name} {sql_type}")
        sql = f"CREATE TABLE IF NOT EXISTS {model.name} (" + ", ".join(fields_sql) + ")"
        conn.execute(sql)
    conn.commit()


def list_rows(
    conn: sqlite3.Connection,
    model: ModelSpec,
    *,
    limit: int = 100,
    where: str = "",
    params: tuple[Any, ...] = (),
    order_by: str = "id DESC",
) -> List[Dict[str, Any]]:
    sql = f"SELECT * FROM {model.name}"
    if where:
        sql += " WHERE " + where
    sql += f" ORDER BY {order_by} LIMIT ?"
    cursor = conn.execute(sql, params + (limit,))
    return [dict(row) for row in cursor.fetchall()]


def count_rows(conn: sqlite3.Connection, model: ModelSpec) -> int:
    cursor = conn.execute(f"SELECT COUNT(*) as count FROM {model.name}")
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
    if field_type == "bool":
        if isinstance(value, str):
            return 1 if value.lower() in ("1", "true", "yes", "on") else 0
        return 1 if bool(value) else 0
    if field_type == "int":
        return int(value)
    if field_type == "float":
        return float(value)
    return value

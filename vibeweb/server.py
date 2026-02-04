from __future__ import annotations

import base64
import html
import hmac
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, Optional

from vibeweb.db import (
    connect,
    count_rows,
    delete_row,
    ensure_schema,
    get_row,
    insert_row,
    list_rows,
    update_row,
)
from vibeweb.spec import AppSpec, ModelSpec

STATIC_DIR = Path(__file__).with_name("static")

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://cdn.tailwindcss.com; "
    "frame-ancestors 'none'"
)

TAILWIND_HEAD = (
    "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
    "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
    "<link href=\"https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap\" rel=\"stylesheet\">"
    "<script src=\"https://cdn.tailwindcss.com\"></script>"
    "<script>"
    "tailwind.config = {"
    "theme: {"
    "extend: {"
    "fontFamily: { display: ['Bricolage Grotesque', 'sans-serif'], mono: ['Space Mono', 'monospace'] },"
    "colors: { brand: { 50: '#f3ffe3', 400: '#b7ff5a', 600: '#7ed957' } }"
    "}"
    "}"
    "}"
    "</script>"
)

THEME = {
    "body": "min-h-screen font-display text-slate-950 bg-gradient-to-br from-stone-50 via-lime-50 to-emerald-100",
    "grid_overlay": "fixed inset-0 -z-10 opacity-40 "
    "bg-[linear-gradient(120deg,rgba(15,23,42,0.07)_1px,transparent_1px)] "
    "[background-size:36px_36px]",
    "shell": "px-6 py-8 lg:px-10",
    "container": "mx-auto flex max-w-6xl flex-col gap-6",
    "topbar": "flex items-center justify-between rounded-[26px] border-2 border-slate-900 bg-white px-6 py-4 shadow-[10px_10px_0_rgba(15,23,42,0.15)]",
    "brand": "text-lg font-semibold tracking-wide",
    "nav": "flex items-center gap-2",
    "nav_link": "rounded-full border border-slate-900 px-3 py-1 text-sm font-medium text-slate-900 transition hover:-translate-y-0.5 hover:bg-brand-400",
    "surface": "rounded-[30px] border-2 border-slate-900 bg-white p-6 shadow-[14px_14px_0_rgba(15,23,42,0.12)]",
    "header": "flex flex-wrap items-center justify-between gap-4",
    "header_title": "text-2xl font-semibold",
    "header_subtitle": "text-sm text-slate-600",
    "header_tag": "rounded-full border border-slate-900 bg-brand-400 px-3 py-1 text-xs font-semibold text-slate-900",
    "panel": "rounded-2xl border border-slate-200 bg-slate-50 p-5 shadow-sm",
    "panel_title": "text-lg font-semibold",
    "form_grid": "mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-3",
    "label": "flex flex-col gap-2 text-[11px] uppercase tracking-[0.2em] text-slate-500",
    "input": "rounded-xl border-2 border-slate-200 bg-white px-3 py-2 text-sm focus:border-slate-900 focus:outline-none",
    "btn_primary": "rounded-xl bg-brand-400 px-4 py-2 text-sm font-semibold text-slate-900 shadow-[3px_3px_0_rgba(15,23,42,0.2)]",
    "btn_dark": "rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-[3px_3px_0_rgba(15,23,42,0.2)]",
    "btn_outline": "ml-2 rounded-full border-2 border-slate-900 px-3 py-1 text-xs font-semibold text-slate-900",
    "table_wrap": "mt-4 overflow-x-auto",
    "table": "min-w-full text-sm",
    "thead": "bg-lime-50 text-xs uppercase tracking-widest text-slate-600",
    "tbody": "divide-y divide-slate-100",
    "row": "hover:bg-lime-50/60",
    "cell": "px-4 py-3",
    "grid": "grid gap-4 md:grid-cols-2",
    "card": "rounded-2xl border-2 border-slate-900 bg-white p-5 shadow-[6px_6px_0_rgba(15,23,42,0.12)]",
    "card_title": "text-lg font-semibold",
    "badge": "rounded-full border border-slate-900 bg-brand-400 px-3 py-1 text-xs font-semibold text-slate-900",
    "link": "text-slate-900 font-semibold underline decoration-brand-400 decoration-4 underline-offset-4",
    "link_muted": "text-slate-600",
    "stack": "flex flex-col gap-6",
}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _csrf_field(token: str) -> str:
    return f"<input type=\"hidden\" name=\"csrf_token\" value=\"{_esc(token)}\"/>"


class VibeWebServer:
    def __init__(self, spec: AppSpec) -> None:
        self.spec = spec
        self.conn = connect(spec.db_path)
        ensure_schema(self.conn, spec.models)
        self.model_map = {m.name: m for m in spec.models}
        self.page_map = {p.path: p for p in spec.pages}
        self.csrf_token = secrets.token_urlsafe(32)

    def close(self) -> None:
        self.conn.close()


class Handler(BaseHTTPRequestHandler):
    server_ctx: VibeWebServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/static/"):
            self._serve_static(parsed.path)
            return
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed.path, parsed.query)
            return
        if self.server_ctx.spec.admin_enabled and (
            parsed.path == self.server_ctx.spec.admin_path
            or parsed.path.startswith(self.server_ctx.spec.admin_path + "/")
        ):
            if not self._check_admin_auth():
                return
            self._handle_admin(parsed.path)
            return
        if parsed.path in self.server_ctx.page_map or parsed.path == "/":
            self._handle_ui(parsed.path)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_post(parsed.path)
            return
        if self.server_ctx.spec.admin_enabled and (
            parsed.path == self.server_ctx.spec.admin_path
            or parsed.path.startswith(self.server_ctx.spec.admin_path + "/")
        ):
            if not self._check_admin_auth():
                return
            self._handle_admin_post(parsed.path)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_put(parsed.path)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_PUT()

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_delete(parsed.path)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _handle_api_get(self, path: str, query: str) -> None:
        model, row_id = self._parse_api_path(path)
        if not model:
            return
        if row_id is None:
            params = parse_qs(query)
            limit = int(params.get("limit", ["100"])[0])
            q = params.get("q", [""])[0].strip()
            sort = params.get("sort", ["id"])[0]
            direction = params.get("dir", ["desc"])[0]
            rows = self._query_rows(model, q=q, sort=sort, direction=direction, limit=limit)
            self._send_json(rows)
            return
        row = get_row(self.server_ctx.conn, model, row_id)
        if not row:
            self._send_error(HTTPStatus.NOT_FOUND, "Row not found")
            return
        self._send_json(row)

    def _handle_api_post(self, path: str) -> None:
        model, row_id = self._parse_api_path(path)
        if not model or row_id is not None:
            return
        payload = self._read_payload()
        try:
            row = insert_row(self.server_ctx.conn, model, payload)
        except Exception as exc:  # noqa: BLE001
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json(row, status=HTTPStatus.CREATED)

    def _handle_api_put(self, path: str) -> None:
        model, row_id = self._parse_api_path(path)
        if not model or row_id is None:
            return
        payload = self._read_payload()
        row = update_row(self.server_ctx.conn, model, row_id, payload)
        if not row:
            self._send_error(HTTPStatus.NOT_FOUND, "Row not found")
            return
        self._send_json(row)

    def _handle_api_delete(self, path: str) -> None:
        model, row_id = self._parse_api_path(path)
        if not model or row_id is None:
            return
        if delete_row(self.server_ctx.conn, model, row_id):
            self._send_json({"ok": True})
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Row not found")

    def _handle_ui(self, path: str) -> None:
        pages = self.server_ctx.spec.pages
        page = self.server_ctx.page_map.get(path) or (pages[0] if pages else None)
        if not page:
            self._send_error(HTTPStatus.NOT_FOUND, "No pages configured")
            return
        model = self.server_ctx.model_map[page.model]
        rows = list_rows(self.server_ctx.conn, model, limit=100)
        html = render_page(self.server_ctx.spec, model, page, rows)
        self._send_html(html)

    def _handle_admin_post(self, path: str) -> None:
        base = self.server_ctx.spec.admin_path
        suffix = path[len(base) :].lstrip("/")
        parts = [p for p in suffix.split("/") if p]
        if not parts:
            self._send_error(HTTPStatus.NOT_FOUND, "Invalid admin path")
            return
        model_name = parts[0]
        if model_name not in self.server_ctx.model_map:
            self._send_error(HTTPStatus.NOT_FOUND, "Unknown model")
            return
        model = self.server_ctx.model_map[model_name]
        payload = self._read_payload()
        if not self._require_csrf(payload):
            return
        payload.pop("csrf_token", None)
        if len(parts) == 2 and parts[1] == "create":
            try:
                insert_row(self.server_ctx.conn, model, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._redirect(f"{base}/{model_name}")
            return
        if len(parts) == 3 and parts[2] in ("update", "delete"):
            try:
                row_id = int(parts[1])
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "Invalid row id")
                return
            if parts[2] == "update":
                row = update_row(self.server_ctx.conn, model, row_id, payload)
                if not row:
                    self._send_error(HTTPStatus.NOT_FOUND, "Row not found")
                    return
                self._redirect(f"{base}/{model_name}/{row_id}")
                return
            if parts[2] == "delete":
                if delete_row(self.server_ctx.conn, model, row_id):
                    self._redirect(f"{base}/{model_name}")
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "Row not found")
                return
        self._send_error(HTTPStatus.NOT_FOUND, "Unknown admin action")

    def _handle_admin(self, path: str) -> None:
        base = self.server_ctx.spec.admin_path
        if path == base or path == base + "/":
            html = render_admin_home(self.server_ctx.spec, self.server_ctx.model_map)
            self._send_html(html)
            return
        suffix = path[len(base) :].lstrip("/")
        parts = [p for p in suffix.split("/") if p]
        model_name = parts[0] if parts else ""
        if not model_name or model_name not in self.server_ctx.model_map:
            self._send_error(HTTPStatus.NOT_FOUND, "Unknown model")
            return
        model = self.server_ctx.model_map[model_name]
        if len(parts) == 2:
            try:
                row_id = int(parts[1])
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "Invalid row id")
                return
            row = get_row(self.server_ctx.conn, model, row_id)
            if not row:
                self._send_error(HTTPStatus.NOT_FOUND, "Row not found")
                return
            html = render_admin_edit(self.server_ctx.spec, model, row, csrf_token=self.server_ctx.csrf_token)
        else:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            q = params.get("q", [""])[0].strip()
            sort = params.get("sort", ["id"])[0]
            direction = params.get("dir", ["desc"])[0]
            limit = int(params.get("limit", ["200"])[0])
            rows = self._query_rows(model, q=q, sort=sort, direction=direction, limit=limit)
            html = render_admin_model(
                self.server_ctx.spec,
                model,
                rows,
                q=q,
                sort=sort,
                direction=direction,
                csrf_token=self.server_ctx.csrf_token,
            )
        self._send_html(html)

    def _read_payload(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0]
        if content_type == "application/json":
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
        if content_type == "application/x-www-form-urlencoded":
            data = parse_qs(raw.decode("utf-8"))
            return {k: v[0] if len(v) == 1 else v for k, v in data.items()}
        return {}

    def _parse_api_path(self, path: str) -> tuple[Optional[ModelSpec], Optional[int]]:
        parts = path.split("/")
        if len(parts) < 3:
            self._send_error(HTTPStatus.NOT_FOUND, "Invalid API path")
            return None, None
        model_name = parts[2]
        if model_name not in self.server_ctx.model_map:
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown model: {model_name}")
            return None, None
        if model_name not in self.server_ctx.spec.api_crud:
            self._send_error(HTTPStatus.FORBIDDEN, f"CRUD disabled for {model_name}")
            return None, None
        row_id = None
        if len(parts) >= 4 and parts[3]:
            try:
                row_id = int(parts[3])
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "Invalid row id")
                return None, None
        return self.server_ctx.model_map[model_name], row_id

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._apply_security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self._apply_security_headers(is_html=True)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _serve_static(self, path: str) -> None:
        rel = path[len("/static/") :].lstrip("/")
        if not rel or ".." in rel:
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        base = STATIC_DIR.resolve()
        file_path = (base / rel).resolve()
        if not str(file_path).startswith(str(base)) or not file_path.exists():
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = "text/css; charset=utf-8" if file_path.suffix == ".css" else "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self._apply_security_headers()
        self.send_header("Location", location)
        self.end_headers()

    def _check_admin_auth(self) -> bool:
        auth_type, expected_user, expected_pass = self._admin_credentials()
        if not auth_type:
            return True
        auth = self.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return self._send_auth_required()
        try:
            raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        except Exception:
            return self._send_auth_required()
        if ":" not in raw:
            return self._send_auth_required()
        username, password = raw.split(":", 1)
        if not expected_user or not expected_pass:
            return self._send_auth_required()
        if not (hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pass)):
            return self._send_auth_required()
        return True

    def _admin_credentials(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        env_user = os.environ.get("VIBEWEB_ADMIN_USER")
        env_pass = os.environ.get("VIBEWEB_ADMIN_PASSWORD")
        if env_user and env_pass:
            return "basic", env_user, env_pass
        spec = self.server_ctx.spec
        if not spec.admin_auth_type:
            return None, None, None
        return spec.admin_auth_type, spec.admin_username, spec.admin_password

    def _require_csrf(self, payload: dict[str, Any]) -> bool:
        token = payload.get("csrf_token", "")
        if not token:
            self._send_error(HTTPStatus.FORBIDDEN, "Missing CSRF token")
            return False
        if not hmac.compare_digest(str(token), self.server_ctx.csrf_token):
            self._send_error(HTTPStatus.FORBIDDEN, "Invalid CSRF token")
            return False
        return True

    def _send_auth_required(self) -> bool:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self._apply_security_headers()
        self.send_header("WWW-Authenticate", "Basic realm=\"VibeWeb Admin\"")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authentication required")
        return False

    def _apply_security_headers(self, *, is_html: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "interest-cohort=()")
        if is_html:
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")

    def _query_rows(
        self,
        model: ModelSpec,
        *,
        q: str,
        sort: str,
        direction: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        allowed_fields = {"id"} | set(model.fields.keys())
        if sort not in allowed_fields:
            sort = "id"
        direction = "asc" if direction.lower() == "asc" else "desc"
        order_by = f"{sort} {direction}"
        where = ""
        params: tuple[Any, ...] = ()
        if q:
            text_fields = [f for f, t in model.fields.items() if t == "text"]
            if text_fields:
                where = " OR ".join([f"{f} LIKE ?" for f in text_fields])
                like = f"%{q}%"
                params = tuple([like] * len(text_fields))
        return list_rows(self.server_ctx.conn, model, limit=limit, where=where, params=params, order_by=order_by)


def render_shell(app: AppSpec, title: str, body: str, nav_links: list[tuple[str, str]] | None = None) -> str:
    links = nav_links or []
    nav = "".join(
        [
            f"<a class=\"{THEME['nav_link']}\" href=\"{_esc(href)}\">{_esc(label)}</a>"
            for label, href in links
        ]
    )
    safe_title = _esc(title)
    safe_name = _esc(app.name)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"/>"
        f"<title>{safe_title}</title>"
        f"{TAILWIND_HEAD}"
        "</head>"
        f"<body class=\"{THEME['body']}\">"
        f"<div class=\"{THEME['grid_overlay']}\"></div>"
        f"<div class=\"{THEME['shell']}\">"
        f"<div class=\"{THEME['container']}\">"
        f"<div class=\"{THEME['topbar']}\">"
        f"<div class=\"{THEME['brand']}\">{safe_name}</div>"
        f"<nav class=\"{THEME['nav']}\">{nav}</nav>"
        "</div>"
        f"<main class=\"{THEME['surface']}\">"
        f"{body}</main>"
        "</div></div></body></html>"
    )


def render_page(app: AppSpec, model: ModelSpec, page, rows: list[dict[str, Any]]) -> str:
    fields = page.fields or list(model.fields.keys())
    title = page.title or f"{model.name}"
    safe_title = _esc(title)
    safe_model = _esc(model.name)
    header = (
        f"<header class=\"{THEME['header']}\">"
        f"<div><h1 class=\"{THEME['header_title']}\">{safe_title}</h1>"
        f"<p class=\"{THEME['header_subtitle']}\">Auto-generated from {safe_model}</p></div>"
        f"<span class=\"{THEME['header_tag']}\">{safe_model}</span>"
        "</header>"
    )

    form_inputs = []
    for field in fields:
        ftype = model.fields[field]
        input_html = _input_for(field, ftype)
        form_inputs.append(input_html)
    form = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Create</h2>"
        f"<form method=\"post\" action=\"/api/{safe_model}\" "
        f"enctype=\"application/x-www-form-urlencoded\">"
        f"<div class=\"{THEME['form_grid']}\">"
        + "".join(form_inputs)
        + "</div><div class=\"mt-4 flex justify-end\">"
        f"<button class=\"{THEME['btn_primary']}\" "
        "type=\"submit\">Create</button></div></form></div>"
    )

    header_row = "".join(
        [f"<th class=\"{THEME['cell']} text-left\">{_esc(f)}</th>" for f in ["id"] + fields]
    )
    body_rows = []
    for row in rows:
        cells = [f"<td class=\"{THEME['cell']}\">{_esc(row.get('id'))}</td>"]
        for field in fields:
            cells.append(f"<td class=\"{THEME['cell']}\">{_esc(row.get(field, ''))}</td>")
        body_rows.append(f"<tr class=\"{THEME['row']}\">" + "".join(cells) + "</tr>")
    table = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Entries</h2>"
        f"<div class=\"{THEME['table_wrap']}\">"
        f"<table class=\"{THEME['table']}\">"
        f"<thead class=\"{THEME['thead']}\"><tr>"
        + header_row
        + f"</tr></thead><tbody class=\"{THEME['tbody']}\">"
        + "".join(body_rows)
        + "</tbody></table></div></div>"
    )

    nav_links = []
    if app.admin_enabled:
        nav_links.append(("Admin", app.admin_path))
    nav_links.append(("API", f"/api/{model.name}"))
    body = f"<div class=\"{THEME['stack']}\">" + header + form + table + "</div>"
    return render_shell(app, title, body, nav_links=nav_links)

def render_admin_home(app: AppSpec, models: dict[str, ModelSpec]) -> str:
    conn = connect(app.db_path)
    cards = []
    for model in models.values():
        count = count_rows(conn, model)
        safe_model = _esc(model.name)
        cards.append(
            f"<div class=\"{THEME['card']}\">"
            f"<h3 class=\"{THEME['card_title']}\">{safe_model}</h3>"
            f"<p class=\"mt-2\"><span class=\"{THEME['badge']}\">{count} rows</span></p>"
            f"<p class=\"mt-4 flex gap-3 text-sm font-semibold\">"
            f"<a class=\"{THEME['link']}\" href=\"{_esc(app.admin_path)}/{safe_model}\">Manage</a>"
            f"<a class=\"{THEME['link_muted']}\" href=\"/api/{safe_model}\">API</a></p>"
            "</div>"
        )
    conn.close()
    header = (
        f"<header class=\"{THEME['header']}\">"
        f"<div><h1 class=\"{THEME['header_title']}\">Admin</h1>"
        f"<p class=\"{THEME['header_subtitle']}\">System overview</p></div>"
        f"<span class=\"{THEME['header_tag']}\">Dashboard</span></header>"
    )
    body = header + f"<div class=\"{THEME['grid']}\">" + "".join(cards) + "</div>"
    nav_links = [("Home", "/")]
    return render_shell(app, "Admin", body, nav_links=nav_links)


def render_admin_model(
    app: AppSpec,
    model: ModelSpec,
    rows: list[dict[str, Any]],
    *,
    q: str,
    sort: str,
    direction: str,
    csrf_token: str,
) -> str:
    safe_model = _esc(model.name)
    safe_q = _esc(q)
    title = f"{model.name} Admin"
    header = (
        f"<header class=\"{THEME['header']}\">"
        f"<div><h1 class=\"{THEME['header_title']}\">{safe_model}</h1>"
        f"<p class=\"text-xs uppercase tracking-[0.3em] text-slate-500\">/{safe_model}</p></div>"
        f"<span class=\"{THEME['header_tag']}\">{len(rows)} rows</span></header>"
    )
    fields = list(model.fields.keys())
    form_inputs = [_input_for(field, model.fields[field]) for field in fields]
    form = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Create</h2>"
        f"<form method=\"post\" action=\"{_esc(app.admin_path)}/{safe_model}/create\" "
        f"enctype=\"application/x-www-form-urlencoded\">"
        f"{_csrf_field(csrf_token)}"
        f"<div class=\"{THEME['form_grid']}\">"
        + "".join(form_inputs)
        + "</div><div class=\"mt-4 flex justify-end\">"
        f"<button class=\"{THEME['btn_primary']}\" "
        "type=\"submit\">Create</button></div></form></div>"
    )
    search = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Filter</h2>"
        "<form method=\"get\" action=\"\">"
        "<div class=\"mt-4 flex flex-wrap items-end gap-4\">"
        f"<label class=\"{THEME['label']}\">"
        f"Query<input class=\"{THEME['input']}\" "
        f"name=\"q\" value=\"{safe_q}\" placeholder=\"Search\"/></label>"
        + _sort_select(model, sort, direction)
        + f"<button class=\"{THEME['btn_dark']}\" "
        "type=\"submit\">Apply</button>"
        + "</div></form></div>"
    )
    header_row = "".join([f"<th class=\"{THEME['cell']} text-left\">{f}</th>" for f in ["id"] + fields])
    header_row += f"<th class=\"{THEME['cell']} text-left\">Actions</th>"
    body_rows = []
    for row in rows:
        row_id = _esc(row.get("id"))
        cells = [f"<td class=\"{THEME['cell']}\">{row_id}</td>"]
        for field in fields:
            cells.append(f"<td class=\"{THEME['cell']}\">{_esc(row.get(field, ''))}</td>")
        actions = (
            f"<td class=\"{THEME['cell']}\"><a class=\"{THEME['link']}\" "
            f"href=\"{_esc(app.admin_path)}/{safe_model}/{row_id}\">Edit</a>"
            f" <form method=\"post\" action=\"{_esc(app.admin_path)}/{safe_model}/{row_id}/delete\""
            " style=\"display:inline\">"
            f"{_csrf_field(csrf_token)}"
            f"<button class=\"{THEME['btn_outline']}\" type=\"submit\">Delete</button></form></td>"
        )
        body_rows.append(f"<tr class=\"{THEME['row']}\">" + "".join(cells) + actions + "</tr>")
    table = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Rows</h2>"
        f"<div class=\"{THEME['table_wrap']}\">"
        f"<table class=\"{THEME['table']}\"><thead "
        f"class=\"{THEME['thead']}\"><tr>"
        + header_row
        + f"</tr></thead><tbody class=\"{THEME['tbody']}\">"
        + "".join(body_rows)
        + "</tbody></table></div></div>"
    )
    nav_links = [("Admin", app.admin_path), ("API", f"/api/{model.name}")]
    body = f"<div class=\"{THEME['stack']}\">" + header + form + search + table + "</div>"
    return render_shell(app, title, body, nav_links=nav_links)


def render_admin_edit(app: AppSpec, model: ModelSpec, row: dict[str, Any], *, csrf_token: str) -> str:
    safe_model = _esc(model.name)
    safe_id = _esc(row.get("id"))
    title = f"Edit {model.name}"
    header = (
        f"<header class=\"{THEME['header']}\">"
        f"<div><h1 class=\"{THEME['header_title']}\">{safe_model} #{safe_id}</h1>"
        f"<p class=\"{THEME['header_subtitle']}\">Edit entry</p></div>"
        f"<span class=\"{THEME['header_tag']}\">Edit</span></header>"
    )
    inputs = []
    for field, ftype in model.fields.items():
        value = row.get(field, "")
        inputs.append(_input_for(field, ftype, value=value))
    form = (
        f"<div class=\"{THEME['panel']}\">"
        f"<h2 class=\"{THEME['panel_title']}\">Update</h2>"
        f"<form method=\"post\" action=\"{_esc(app.admin_path)}/{safe_model}/{safe_id}/update\" "
        f"enctype=\"application/x-www-form-urlencoded\">"
        f"{_csrf_field(csrf_token)}"
        f"<div class=\"{THEME['form_grid']}\">"
        + "".join(inputs)
        + "</div><div class=\"mt-4 flex justify-end\">"
        f"<button class=\"{THEME['btn_dark']}\" "
        "type=\"submit\">Update</button></div></form></div>"
    )
    nav_links = [("Admin", app.admin_path), ("Back", f"{app.admin_path}/{model.name}")]
    body = f"<div class=\"{THEME['stack']}\">" + header + form + "</div>"
    return render_shell(app, title, body, nav_links=nav_links)

def _input_for(name: str, field_type: str, *, value: Any = "") -> str:
    if field_type == "bool":
        selected = "selected" if str(value) in ("1", "true", "True") else ""
        selected_false = "" if selected else "selected"
        return (
            f"<label class=\"{THEME['label']}\">"
            f"{_esc(name)}<select class=\"{THEME['input']}\" name=\"{_esc(name)}\">"
            f"<option value=\"0\" {selected_false}>false</option>"
            f"<option value=\"1\" {selected}>true</option>"
            "</select></label>"
        )
    input_type = "text"
    if field_type in ("int", "float"):
        input_type = "number"
    if field_type == "datetime":
        input_type = "datetime-local"
    safe_value = _esc(value)
    value_attr = f"value=\"{safe_value}\"" if safe_value != "" else ""
    return f"<label class=\"{THEME['label']}\">{_esc(name)}<input class=\"{THEME['input']}\" name=\"{_esc(name)}\" type=\"{input_type}\" {value_attr}/></label>"


def _sort_select(model: ModelSpec, sort: str, direction: str) -> str:
    fields = ["id"] + list(model.fields.keys())
    options = []
    for field in fields:
        selected = "selected" if field == sort else ""
        options.append(f"<option value=\"{_esc(field)}\" {selected}>{_esc(field)}</option>")
    dir_selected = "selected" if direction == "desc" else ""
    dir_selected_asc = "selected" if direction == "asc" else ""
    return (
        f"<label class=\"{THEME['label']}\">Sort"
        "<div class=\"flex gap-2\">"
        + f"<select class=\"{THEME['input']}\" name=\"sort\">{''.join(options)}</select>"
        + f"<select class=\"{THEME['input']}\" name=\"dir\"><option value=\"asc\" {dir_selected_asc}>asc</option>"
        + f"<option value=\"desc\" {dir_selected}>desc</option></select>"
        + "</div></label>"
    )


def run_server(spec: AppSpec, host: str = "127.0.0.1", port: int = 8000) -> None:
    ctx = VibeWebServer(spec)
    try:
        Handler.server_ctx = ctx
        httpd = HTTPServer((host, port), Handler)
        print(f"VibeWeb running on http://{host}:{port}")
        httpd.serve_forever()
    finally:
        ctx.close()

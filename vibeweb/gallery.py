from __future__ import annotations

import io
import json
import os
import re
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs, urlparse

from vibeweb.ai import AIError, generate_spec

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://cdn.tailwindcss.com; "
    "frame-ancestors 'none'"
)

MAX_PROMPT_CHARS = int(os.environ.get("VIBEWEB_AI_MAX_PROMPT", "2000"))


_CONTENT_TYPES: Dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


class GalleryHandler(BaseHTTPRequestHandler):
    root_dir: Path

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        if not rel or ".." in Path(rel).parts:
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        file_path = (self.root_dir / rel).resolve()
        if not str(file_path).startswith(str(self.root_dir)):
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        if not file_path.exists() or file_path.is_dir():
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = _CONTENT_TYPES.get(file_path.suffix, "application/octet-stream")
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers(is_html=content_type.startswith("text/html"))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/generate":
            self._handle_generate()
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        payload = f"{status.value} {message}".encode("utf-8")
        self.send_response(status)
        self._apply_security_headers()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_generate(self) -> None:
        try:
            data = self._read_form()
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._send_error(HTTPStatus.BAD_REQUEST, "Prompt is required")
                return
            if len(prompt) > MAX_PROMPT_CHARS:
                self._send_error(HTTPStatus.BAD_REQUEST, "Prompt too long")
                return

            provider = os.environ.get("VIBEWEB_AI_PROVIDER", "openai")
            base_url = os.environ.get("VIBEWEB_AI_BASE_URL", "http://127.0.0.1:8080/v1")
            model = os.environ.get("VIBEWEB_AI_MODEL", "glm-4.8")
            api_key = os.environ.get("VIBEWEB_AI_API_KEY")
            temperature = float(os.environ.get("VIBEWEB_AI_TEMPERATURE", "0.2"))

            spec = generate_spec(
                prompt,
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
                temperature=temperature,
            )
        except AIError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        zip_bytes, filename = _build_zip(spec)
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers()
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename={filename}")
        self.send_header("Content-Length", str(len(zip_bytes)))
        self.end_headers()
        self.wfile.write(zip_bytes)

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0]
        if content_type == "application/x-www-form-urlencoded":
            parsed = parse_qs(raw.decode("utf-8"))
            return {k: v[0] if v else "" for k, v in parsed.items()}
        if content_type == "application/json":
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
        return {}

    def _apply_security_headers(self, *, is_html: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "interest-cohort=()")
        if is_html:
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")


def run_gallery(root: str, host: str = "127.0.0.1", port: int = 9000) -> None:
    root_dir = Path(root).resolve()
    if not root_dir.exists() or not root_dir.is_dir():
        raise SystemExit(f"Gallery root not found: {root_dir}")
    GalleryHandler.root_dir = root_dir
    httpd = HTTPServer((host, port), GalleryHandler)
    print(f"VibeWeb gallery on http://{host}:{port}")
    httpd.serve_forever()


def _build_zip(spec: dict) -> tuple[bytes, str]:
    name = spec.get("name", "vibeweb_app")
    slug = _slugify(name)
    spec_json = json.dumps(spec, ensure_ascii=False, indent=2)
    readme = (
        f"# {name}\\n\\n"
        "Generated by VibeWeb Gallery.\\n\\n"
        "Run:\\n"
        f"```bash\\npython3 -m vibeweb run {slug}/app.vweb.json\\n```\\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}/app.vweb.json", spec_json)
        zf.writestr(f"{slug}/README.md", readme)
    return buffer.getvalue(), f"{slug}.zip"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "vibeweb_app"

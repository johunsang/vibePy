from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs, urlparse

from vibeweb.ai import AIError, generate_spec
from vibeweb.spec import validate_spec

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://cdn.tailwindcss.com; "
    "frame-src 'self' http://127.0.0.1:* http://localhost:*; "
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
    preview_manager: "PreviewManager"

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
        if path == "/preview":
            self._handle_preview()
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
            base_url = os.environ.get("VIBEWEB_AI_BASE_URL", "https://api.deepseek.com/v1")
            model = os.environ.get("VIBEWEB_AI_MODEL", "deepseek-chat")
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

    def _handle_preview(self) -> None:
        try:
            payload = self._read_json()
            if "spec" not in payload:
                self._send_error(HTTPStatus.BAD_REQUEST, "Missing spec")
                return
            spec = payload["spec"]
            if isinstance(spec, str):
                spec = json.loads(spec)
            if not isinstance(spec, dict):
                self._send_error(HTTPStatus.BAD_REQUEST, "Spec must be an object")
                return
            validate_spec(spec)
            host = self.server.server_address[0]
            port = self.server.server_address[1]
            preview = self.preview_manager.start(spec, host=host, port=port)
        except Exception as exc:  # noqa: BLE001
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        data = json.dumps(preview, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

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
    GalleryHandler.preview_manager = PreviewManager(root_dir)
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


class PreviewManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.spec_path: Path | None = None

    def start(self, spec: dict, *, host: str, port: int) -> dict:
        self._stop()
        preview_dir = self.root_dir / ".preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_spec = json.loads(json.dumps(spec))
        if preview_spec.get("ui", {}).get("admin_auth") and os.environ.get("VIBEWEB_PREVIEW_KEEP_AUTH") != "1":
            preview_spec["ui"].pop("admin_auth", None)
        if "db" in preview_spec and isinstance(preview_spec["db"], dict):
            preview_spec["db"]["path"] = str(preview_dir / "preview.db")
        self.spec_path = preview_dir / "app.vweb.json"
        self.spec_path.write_text(json.dumps(preview_spec, ensure_ascii=False, indent=2), encoding="utf-8")

        base_port = int(os.environ.get("VIBEWEB_PREVIEW_PORT", "8010"))
        self.port = _find_open_port(base_port)
        env = os.environ.copy()
        env["VIBEWEB_ALLOW_IFRAME"] = "1"
        env["VIBEWEB_FRAME_ANCESTORS"] = f"http://127.0.0.1:{port} http://localhost:{port}"
        cmd = [
            "python3",
            "-m",
            "vibeweb",
            "run",
            str(self.spec_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]
        project_root = self.root_dir.parent
        self.proc = subprocess.Popen(cmd, cwd=str(project_root), env=env)
        base_url = f"http://127.0.0.1:{self.port}"
        return {
            "url": base_url + "/",
            "admin_url": base_url + "/admin",
            "api_url": base_url + "/api",
            "port": self.port,
        }

    def _stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def _find_open_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No open preview port available")

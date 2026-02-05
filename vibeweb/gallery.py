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

from email.parser import BytesParser
from email.policy import default as email_default_policy

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

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0]
        full_content_type = self.headers.get("Content-Type") or ""
        if full_content_type.startswith("multipart/form-data"):
            parsed = self._parse_multipart(raw, full_content_type)
            if parsed:
                return parsed
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

    def _parse_multipart(self, raw: bytes, content_type: str) -> dict[str, str]:
        if not raw:
            return {}
        # Parse multipart without deprecated cgi module (removed in Python 3.13).
        msg = BytesParser(policy=email_default_policy).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + raw
        )
        if not msg.is_multipart():
            return {}
        result: dict[str, str] = {}
        for part in msg.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            value = part.get_content()
            result[str(name)] = str(value)
        return result

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
        f"# {name}\n\n"
        "Generated by VibeWeb Gallery.\n\n"
        "One-command run:\n"
        "```bash\n"
        "bash run.sh\n"
        "```\n"
        "\n"
        "macOS double-click:\n"
        "- `run.command`\n"
        "\n"
        "Security (recommended):\n"
        "- Copy `.env.example` to `.env` and set strong values.\n"
    )
    run_sh = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "APP_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "cd \"$APP_DIR\"\n"
        "if [ -f .env ]; then\n"
        "  set -a\n"
        "  . .env\n"
        "  set +a\n"
        "fi\n"
        "if [ -n \"${VIBEWEB_AUDIT_LOG:-}\" ]; then\n"
        "  mkdir -p \"$(dirname \"$VIBEWEB_AUDIT_LOG\")\"\n"
        "fi\n"
        "if [ ! -d .venv ]; then\n"
        "  python3 -m venv .venv\n"
        "fi\n"
        "source .venv/bin/activate\n"
        "python3 -m pip install --upgrade pip\n"
        "python3 -m pip install -r requirements.txt\n"
        "python3 -m vibeweb run app.vweb.json --host 127.0.0.1 --port 8000\n"
    )
    run_command = (
        "#!/usr/bin/env bash\n"
        "cd \"$(dirname \"$0\")\"\n"
        "bash run.sh\n"
    )
    run_bat = (
        "@echo off\\r\\n"
        "if not exist .venv (python -m venv .venv)\\r\\n"
        "call .venv\\Scripts\\activate\\r\\n"
        "python -m pip install --upgrade pip\\r\\n"
        "python -m pip install -r requirements.txt\\r\\n"
        "python -m vibeweb run app.vweb.json --host 127.0.0.1 --port 8000\\r\\n"
    )
    requirements = "git+https://github.com/johunsang/vibePy\n"
    env_example = (
        "VIBEWEB_ADMIN_USER=admin\n"
        "VIBEWEB_ADMIN_PASSWORD=change_me\n"
        "VIBEWEB_API_KEY=change_me\n"
        "VIBEWEB_RATE_LIMIT=120\n"
        "VIBEWEB_MAX_BODY_BYTES=1048576\n"
        "VIBEWEB_AUDIT_LOG=.logs/vibeweb-audit.log\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}/app.vweb.json", spec_json)
        zf.writestr(f"{slug}/README.md", readme)
        zf.writestr(f"{slug}/run.sh", run_sh)
        zf.writestr(f"{slug}/run.command", run_command)
        zf.writestr(f"{slug}/run.bat", run_bat)
        zf.writestr(f"{slug}/requirements.txt", requirements)
        zf.writestr(f"{slug}/.env.example", env_example)
    return buffer.getvalue(), f"{slug}.zip"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "vibeweb_app"

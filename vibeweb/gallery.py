from __future__ import annotations

import io
import json
import os
import re
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs, urlparse

from email.parser import BytesParser
from email.policy import default as email_default_policy

from vibeweb.ai import AIError, generate_spec
from vibeweb.version import get_version

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
MAX_BODY_BYTES = int(os.environ.get("VIBEWEB_GALLERY_MAX_BODY_BYTES", "1048576"))


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
        if path == "/healthz":
            payload = b"ok"
            self.send_response(HTTPStatus.OK)
            self._apply_security_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
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
            prompt = self._extract_prompt(data)
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

    @staticmethod
    def _extract_prompt(data: dict[str, str]) -> str:
        # Be forgiving: different clients may send the same user intent under
        # different keys. This keeps the /generate endpoint resilient.
        lowered = {str(k).lower(): str(v) for k, v in (data or {}).items()}
        for key in ("prompt", "description", "text", "message", "query", "input"):
            value = (lowered.get(key) or "").strip()
            if value:
                return value
        if len(lowered) == 1:
            only_value = next(iter(lowered.values()), "").strip()
            if only_value:
                return only_value
        return ""

    def _read_form(self) -> dict[str, str]:
        raw = self._read_body()
        full_content_type = (self.headers.get("Content-Type") or "").strip()
        full_lower = full_content_type.lower()

        if "multipart/form-data" in full_lower:
            parsed = self._parse_multipart(raw, full_content_type)
            if parsed:
                return parsed

        if "application/x-www-form-urlencoded" in full_lower:
            parsed = parse_qs(raw.decode("utf-8", errors="replace"))
            return {k: v[0] if v else "" for k, v in parsed.items()}

        if "application/json" in full_lower:
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                data = None
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
            return {}

        # Some browsers send JSON without a Content-Type header or as text/plain.
        if "text/plain" in full_lower or not full_lower:
            if not raw:
                return {}
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                return {}
            if text.startswith("{") and text.endswith("}"):
                try:
                    data = json.loads(text)
                except Exception:
                    data = None
                if isinstance(data, dict):
                    return {k: str(v) for k, v in data.items()}
            return {"prompt": text}
        return {}

    def _read_chunked_body(self, *, max_bytes: int) -> bytes:
        body = bytearray()
        while True:
            line = self.rfile.readline(64 * 1024)
            if not line:
                raise ValueError("Invalid chunked encoding")
            line = line.strip()
            if b";" in line:
                line = line.split(b";", 1)[0]
            try:
                size = int(line.decode("ascii"), 16)
            except Exception as exc:  # noqa: BLE001
                raise ValueError("Invalid chunk size") from exc
            if size == 0:
                while True:
                    trailer = self.rfile.readline(64 * 1024)
                    if trailer in (b"\r\n", b"\n", b""):
                        break
                return bytes(body)
            if len(body) + size > max_bytes:
                raise ValueError("Payload too large")
            chunk = self.rfile.read(size)
            if len(chunk) != size:
                raise ValueError("Invalid chunked encoding")
            body.extend(chunk)
            end = self.rfile.read(1)
            if end == b"\r":
                lf = self.rfile.read(1)
                if lf != b"\n":
                    raise ValueError("Invalid chunked encoding")
            elif end != b"\n":
                raise ValueError("Invalid chunked encoding")

    def _read_body(self) -> bytes:
        raw_len = self.headers.get("Content-Length")
        if raw_len is not None:
            try:
                length = int(raw_len)
            except ValueError:
                return b""
            if length > MAX_BODY_BYTES:
                return b""
            return self.rfile.read(length) if length > 0 else b""

        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            try:
                return self._read_chunked_body(max_bytes=MAX_BODY_BYTES)
            except Exception:
                return b""
        return b""

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
    httpd = ThreadingHTTPServer((host, port), GalleryHandler)
    print(f"VibeWeb gallery on http://{host}:{port}")
    httpd.serve_forever()


def _build_zip(spec: dict) -> tuple[bytes, str]:
    name = spec.get("name", "vibeweb_app")
    slug = _slugify(name)
    spec_json = json.dumps(spec, ensure_ascii=False, indent=2)
    version = get_version()
    pinned_ref = os.environ.get("VIBEWEB_ZIP_VIBEPY_REF", "").strip()
    if not pinned_ref:
        # Prefer tag pinning when we're on a clean semver version.
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            pinned_ref = f"v{version}"
        else:
            pinned_ref = "main"
    readme = (
        f"# {name}\n\n"
        f"Generated by VibeWeb Gallery (VibePy {version}).\n\n"
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
        "@echo off\r\n"
        "if not exist .venv (python -m venv .venv)\r\n"
        "call .venv\\Scripts\\activate\r\n"
        "python -m pip install --upgrade pip\r\n"
        "python -m pip install -r requirements.txt\r\n"
        "python -m vibeweb run app.vweb.json --host 127.0.0.1 --port 8000\r\n"
    )
    # Pin the generated app to a deterministic VibePy ref (tag/commit).
    # Override with VIBEWEB_ZIP_VIBEPY_REF if you want to ship ZIPs from a branch/commit.
    requirements = f"vibepy @ git+https://github.com/johunsang/vibePy@{pinned_ref}\n"
    env_example = (
        "VIBEWEB_ADMIN_USER=admin\n"
        "VIBEWEB_ADMIN_PASSWORD=change_me\n"
        "VIBEWEB_API_KEY=change_me\n"
        "VIBEWEB_RATE_LIMIT=120\n"
        "VIBEWEB_MAX_BODY_BYTES=1048576\n"
        "VIBEWEB_AUDIT_LOG=.logs/vibeweb-audit.log\n"
    )

    def _writestr(path: str, text: str, *, executable: bool = False) -> None:
        info = zipfile.ZipInfo(path)
        info.create_system = 3  # Unix
        perms = 0o755 if executable else 0o644
        info.external_attr = (perms & 0xFFFF) << 16
        zf.writestr(info, text)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _writestr(f"{slug}/app.vweb.json", spec_json)
        _writestr(f"{slug}/README.md", readme)
        _writestr(f"{slug}/run.sh", run_sh, executable=True)
        _writestr(f"{slug}/run.command", run_command, executable=True)
        _writestr(f"{slug}/run.bat", run_bat)
        _writestr(f"{slug}/requirements.txt", requirements)
        _writestr(f"{slug}/.env.example", env_example)
        _writestr(f"{slug}/VIBEPY_REF.txt", pinned_ref + "\n")
    return buffer.getvalue(), f"{slug}.zip"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "vibeweb_app"

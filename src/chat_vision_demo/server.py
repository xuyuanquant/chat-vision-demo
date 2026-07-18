from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .models import ApiError
from .runner import DemoRunner
from .state import RuntimeState, lan_addresses


STATIC = Path(__file__).parent / "static"


class DemoRequestHandler(BaseHTTPRequestHandler):
    state: RuntimeState
    runner: DemoRunner

    def log_message(self, format: str, *args: object) -> None:
        self.state.log("debug", format % args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
        if parsed.path == "/mobile":
            return self._send_file(STATIC / "mobile.html", "text/html; charset=utf-8")
        if parsed.path == "/app.js":
            return self._send_file(STATIC / "app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/style.css":
            return self._send_file(STATIC / "style.css", "text/css; charset=utf-8")
        if parsed.path == "/api/state":
            return self._json(self.state.snapshot())
        if parsed.path == "/api/events":
            return self._sse()
        if parsed.path == "/api/download":
            body = self.state.public_json().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=chat-vision-demo-state.json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/screenshots/"):
            return self._screenshot(parsed.path.removeprefix("/api/screenshots/"))
        if parsed.path.startswith("/api/qr"):
            return self._qr()
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._control_allowed():
            self.state.log("warning", "Control request rejected from read-only client", path=parsed.path, client=self.client_address[0])
            return self._json({"error": {"code": "remote_control_disabled", "message": "Phone/LAN clients are read-only by default."}}, 403)
        try:
            if parsed.path == "/api/start/screen":
                self.runner.start("screen")
                return self._json({"ok": True})
            if parsed.path == "/api/screen/detect":
                return self._json(self.runner.detect_window())
            if parsed.path == "/api/screen/auto":
                self.runner.start_screen_auto(interval=5.0)
                return self._json({"ok": True})
            if parsed.path == "/api/screen/once":
                return self._json(self.runner.capture_screen_once())
            if parsed.path == "/api/new-demo":
                return self._json(self.runner.new_demo())
            if parsed.path == "/api/pause":
                self.runner.pause()
                return self._json({"ok": True})
            if parsed.path == "/api/resume":
                self.runner.resume()
                return self._json({"ok": True})
            if parsed.path == "/api/close":
                return self._json(self.runner.close())
            if parsed.path == "/api/delete":
                return self._json(self.runner.delete())
        except ApiError as exc:
            self.state.log("error", "API request failed", path=parsed.path, error=exc.to_dict())
            return self._json({"error": exc.to_dict()}, 400)
        except Exception as exc:
            self.state.log("error", "Local request failed", path=parsed.path, error={"code": "local_error", "message": str(exc)})
            return self._json({"error": {"code": "local_error", "message": str(exc)}}, 500)
        self.send_error(404)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _screenshot(self, name: str) -> None:
        filename = Path(unquote(name)).name
        if not filename.startswith("screen-") or not filename.endswith(".png"):
            self.send_error(404)
            return
        path = self.runner.temp_dir / filename
        if not path.is_file():
            self.send_error(404)
            return
        return self._send_file(path, "image/png")

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        for _ in range(3600):
            try:
                payload = json.dumps(self.state.snapshot(), ensure_ascii=False)
                self.wfile.write(f"event: state\ndata: {payload}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            time.sleep(1)

    def _qr(self) -> None:
        url = mobile_viewer_url(self.state.viewer_urls)
        try:
            import qrcode
        except ModuleNotFoundError:
            return self._json({"error": {"code": "qr_dependency_missing", "message": "Install optional dependency: pip install '.[qr]'"}, "url": url}, 501)
        img = qrcode.make(url)
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        body = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _control_allowed(self) -> bool:
        return control_allowed(self.client_address[0], self.state.viewer_urls, self.state.config.allow_remote_control)


def control_allowed(client: str, viewer_urls: dict, allow_remote_control: bool) -> bool:
    if allow_remote_control:
        return True
    allowed = {"127.0.0.1", "::1"}
    for key in ("local", "public"):
        url = viewer_urls.get(key)
        if isinstance(url, str):
            host = urlparse(url).hostname
            if host:
                allowed.add(host)
    for url in viewer_urls.get("lan", []):
        host = urlparse(url).hostname
        if host:
            allowed.add(host)
    return client in allowed


def mobile_viewer_url(viewer_urls: dict) -> str:
    base = viewer_urls.get("public") or (viewer_urls.get("lan") or [None])[0] or viewer_urls.get("local", "")
    return f"{str(base).rstrip('/')}/mobile" if base else ""


def serve(state: RuntimeState, runner: DemoRunner) -> ThreadingHTTPServer:
    state.viewer_urls = lan_addresses(state.config.port, state.config.public_url, state.config.bind)
    handler = type("BoundDemoRequestHandler", (DemoRequestHandler,), {"state": state, "runner": runner})
    server = ThreadingHTTPServer((state.config.bind, state.config.port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

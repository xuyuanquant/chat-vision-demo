from __future__ import annotations

import ipaddress
import json
import socket
import threading
from dataclasses import dataclass, field
from typing import Any

from .models import FrameRecord, SessionInfo, mask_key, now_iso
from .sync import MessageStore


@dataclass
class DemoConfig:
    api_base: str
    api_key: str | None
    driver: str
    bind: str = "127.0.0.1"
    port: int = 8080
    public_url: str | None = None
    interval: float = 2.0
    change_threshold: float = 1.0
    allow_remote_control: bool = False
    screen_rect: tuple[int, int, int, int] | None = None
    windows_window_process: str | None = None
    windows_window_title: str | None = None
    foreground_window: bool = False


@dataclass
class RuntimeState:
    config: DemoConfig
    lock: threading.RLock = field(default_factory=threading.RLock)
    api_ready: dict[str, Any] | None = None
    sdk_error: str | None = None
    input_mode: str = "screen"
    capture_status: str = "idle"
    session: SessionInfo = field(default_factory=SessionInfo)
    frames: list[FrameRecord] = field(default_factory=list)
    messages: MessageStore = field(default_factory=MessageStore)
    counters: dict[str, int] = field(default_factory=lambda: {"screenshots": 0, "skipped_unchanged": 0, "pushed": 0})
    last_capture_at: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    last_frame_response: dict[str, Any] | None = None
    window: dict[str, Any] | None = None
    viewer_urls: dict[str, Any] = field(default_factory=dict)

    def log(self, level: str, message: str, **extra: Any) -> None:
        with self.lock:
            self.logs.append({"ts": now_iso(), "level": level, "message": message, **extra})
            self.logs = self.logs[-200:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "api": {
                    "base": self.config.api_base,
                    "ready": self.api_ready,
                    "key_configured": bool(self.config.api_key),
                    "key_hint": mask_key(self.config.api_key),
                    "sdk_error": self.sdk_error,
                },
                "driver": "Python SDK" if self.config.driver == "sdk" else "Raw HTTP",
                "driver_key": self.config.driver,
                "input_mode": self.input_mode,
                "capture_status": self.capture_status,
                "session": self.session.to_dict(),
                "frames": [f.to_dict() for f in self.frames[-30:]],
                "messages": self.messages.to_dict(),
                "counters": self.counters.copy(),
                "last_capture_at": self.last_capture_at,
                "last_frame_response": self.last_frame_response,
                "window": self.window,
                "logs": list(self.logs[-100:]),
                "viewer_urls": self.viewer_urls,
                "remote_control": self.config.allow_remote_control,
            }

    def public_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False, indent=2)


def lan_addresses(port: int, public_url: str | None = None, bind: str = "127.0.0.1") -> dict[str, Any]:
    candidates: list[str] = []
    if bind not in {"127.0.0.1", "localhost", "::1"}:
        seen = set()
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                addr = info[4][0]
                if addr in seen or addr.startswith("127."):
                    continue
                seen.add(addr)
                ip = ipaddress.ip_address(addr)
                if ip.is_private:
                    candidates.append(addr)
        except OSError:
            pass
    result = {
        "local": f"http://127.0.0.1:{port}",
        "lan": [f"http://{addr}:{port}" for addr in candidates],
    }
    if public_url:
        result["public"] = public_url.rstrip("/")
    return result

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .capture import ScreenCaptureSource, cleanup_temp_dir, enough_change
from .clients import ChatVisionClient, SdkUnavailable, make_client
from .models import ApiError, FrameRecord, SessionInfo
from .openapi_contract import FRAME_TERMINAL_STATUSES
from .state import RuntimeState
from .sync import MessageStore


class DemoRunner:
    def __init__(self, state: RuntimeState):
        self.state = state
        self.client: ChatVisionClient | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.message_worker: threading.Thread | None = None
        self.frame_workers: dict[str, threading.Thread] = {}
        self.previous_digest: str | None = None
        self.temp_dir = Path(tempfile.gettempdir()) / "chat-vision-demo"
        self.screen_source: ScreenCaptureSource | None = None
        self.screen_lock = threading.Lock()

    def build_client(self) -> ChatVisionClient:
        return make_client(self.state.config.driver, self.state.config.api_base, self.state.config.api_key)

    def check_ready(self) -> bool:
        client = self.client or self.build_client()
        ready = client.ready()
        with self.state.lock:
            self.state.api_ready = ready
        return bool(ready.get("ok"))

    def start(self, mode: str) -> None:
        self._open_session(mode, start_worker=True)

    def _open_session(self, mode: str, start_worker: bool) -> None:
        with self.state.lock:
            if self.state.capture_status in {"running", "paused"}:
                raise ApiError("Demo is already running", code="already_running")
            if not self.state.config.api_key:
                raise ApiError("CHAT_VISION_API_KEY is not configured", code="api_key_missing")
            self.state.input_mode = mode
            self.state.capture_status = "starting"
        try:
            self.client = self.build_client()
            if not self.check_ready():
                raise ApiError("Cloud API is not ready", code="api_not_ready")
            created = self.client.create_session()
        except SdkUnavailable as exc:
            self.state.sdk_error = exc.message
            self.state.capture_status = "idle"
            raise
        except Exception:
            with self.state.lock:
                self.state.capture_status = "idle"
            raise

        with self.state.lock:
            self.state.session = SessionInfo(
                session_id=created["session_id"],
                status=created["status"],
                created_at=created.get("created_at"),
                expires_at=created.get("expires_at"),
                retention=created.get("retention"),
                request_id=created.get("request_id"),
            )
            self.state.capture_status = "running"
        self.stop_event.clear()
        self.pause_event.clear()
        self.message_worker = threading.Thread(target=self._message_loop, daemon=True)
        self.message_worker.start()
        if start_worker:
            self.worker = threading.Thread(target=self._capture_loop, args=(mode,), daemon=True)
            self.worker.start()
        else:
            with self.state.lock:
                self.state.capture_status = "idle"
        self.state.log("info", "Session started", session_id=created["session_id"])

    def ensure_session(self, mode: str) -> None:
        if self.state.session.session_id and self.state.session.status == "open":
            return
        self._open_session(mode, start_worker=False)

    def new_demo(self) -> dict[str, Any]:
        with self.screen_lock:
            self.stop_event.set()
            self.pause_event.clear()
            for thread in (self.worker, self.message_worker):
                if thread and thread.is_alive():
                    thread.join(timeout=2)
            session_id = self.state.session.session_id
            delete_resp: dict[str, Any] | None = None
            if session_id:
                client = self.client or self.build_client()
                self.client = client
                try:
                    delete_resp = client.delete_session(session_id)
                    self.state.log("info", "Previous session deleted", request_id=delete_resp.get("request_id"))
                except ApiError as exc:
                    self.state.log("error", "Previous session delete failed", error=exc.to_dict())
                    raise
            self._clear_demo_state()
            self._open_session("screen", start_worker=False)
            return {
                "ok": True,
                "deleted": bool(session_id),
                "delete_response": delete_resp,
                "session": self.state.session.to_dict(),
            }

    def detect_window(self) -> dict[str, Any]:
        source = self._source("screen")
        if not isinstance(source, ScreenCaptureSource):
            raise ApiError("Screen source is not available", code="screen_source_unavailable")
        return self.state.window or {}



    def capture_screen_once(self) -> dict[str, Any]:
        self.ensure_session("screen")
        source = self._screen_source()
        with self.screen_lock:
            item = source.capture()
            self._consider_push(item.path, item.frame_id, item.digest, item.captured_at, str(item.path.name))
        return {"ok": True, "captured_at": item.captured_at, "frame_id": item.frame_id}

    def start_screen_auto(self, interval: float = 5.0) -> None:
        self.state.config.interval = interval
        with self.state.lock:
            if self.state.capture_status == "running" and self.state.input_mode == "screen":
                return
            has_open_session = bool(self.state.session.session_id and self.state.session.status == "open")
        if has_open_session:
            self._screen_source()
            self.stop_event.clear()
            self.pause_event.clear()
            with self.state.lock:
                self.state.input_mode = "screen"
                self.state.capture_status = "running"
            if not self.message_worker or not self.message_worker.is_alive():
                self.message_worker = threading.Thread(target=self._message_loop, daemon=True)
                self.message_worker.start()
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._capture_loop, args=("screen",), daemon=True)
                self.worker.start()
            return
        self.start("screen")

    def pause(self) -> None:
        self.pause_event.set()
        with self.state.lock:
            self.state.capture_status = "paused"

    def resume(self) -> None:
        self.pause_event.clear()
        with self.state.lock:
            self.state.capture_status = "running"

    def close(self) -> dict[str, Any]:
        self.stop_event.set()
        session_id = self.state.session.session_id
        if not self.client or not session_id:
            raise ApiError("No active session", code="no_session")
        resp = self.client.close_session(session_id)
        with self.state.lock:
            self.state.session.status = resp.get("status", "closed")
            self.state.session.request_id = resp.get("request_id")
            self.state.capture_status = "stopped"
        self.state.log("info", "Session closed", request_id=resp.get("request_id"))
        return resp

    def delete(self) -> dict[str, Any]:
        self.stop_event.set()
        session_id = self.state.session.session_id
        if not self.client or not session_id:
            raise ApiError("No active session", code="no_session")
        resp = self.client.delete_session(session_id)
        with self.state.lock:
            self.state.session = SessionInfo(status="deleted")
            self.state.capture_status = "idle"
            self.state.frames.clear()
            self.state.messages.messages.clear()
            self.state.messages.cursor = None
        cleanup_temp_dir(self.temp_dir)
        self.screen_source = None
        self.previous_digest = None
        self.state.log("info", "Session deleted", request_id=resp.get("request_id"))
        return resp

    def _clear_demo_state(self) -> None:
        with self.state.lock:
            self.state.session = SessionInfo(status="none")
            self.state.capture_status = "idle"
            self.state.frames.clear()
            self.state.messages = MessageStore()
            self.state.counters = {"screenshots": 0, "skipped_unchanged": 0, "pushed": 0}
            self.state.last_capture_at = None
            self.state.last_frame_response = None
        cleanup_temp_dir(self.temp_dir)
        self.screen_source = None
        self.previous_digest = None

    def _source(self, mode: str) -> ScreenCaptureSource:
        if mode != "screen":
            raise ApiError(f"Unsupported mode: {mode}", code="unsupported_mode")
        rect = self.state.config.screen_rect
        foreground_hwnd = None
        if rect is None:
            from .windows_window import bring_to_foreground, find_window, get_window_info
            win = find_window(
                process_name=self.state.config.windows_window_process,
                title_contains=self.state.config.windows_window_title,
            )
            foreground_success = None
            if self.state.config.foreground_window:
                foreground_success = bring_to_foreground(win.hwnd)
                time.sleep(0.2)
                win = get_window_info(win.hwnd)
            rect = win.capture_rect
            foreground_hwnd = win.hwnd if self.state.config.foreground_window else None
            with self.state.lock:
                self.state.window = {
                    "hwnd": win.hwnd,
                    "title": win.title,
                    "process_id": win.process_id,
                    "process_path": win.process_path,
                    "rect": win.rect,
                    "capture_rect": rect,
                    "foreground_enabled": self.state.config.foreground_window,
                    "foreground_success": foreground_success,
                }
            self.state.log("info", "Windows window selected", title=win.title, process_path=win.process_path, rect=rect)
        if not rect:
            raise ApiError("Screen rect is not configured. Use --screen-rect x,y,w,h.", code="screen_rect_missing")
        source = ScreenCaptureSource(rect, self.temp_dir, foreground_hwnd=foreground_hwnd)
        self.screen_source = source
        return source

    def _screen_source(self) -> ScreenCaptureSource:
        source = self.screen_source
        if source is None:
            source = self._source("screen")
            if not isinstance(source, ScreenCaptureSource):
                raise ApiError("Screen source is not available", code="screen_source_unavailable")
        return source

    def _capture_loop(self, mode: str) -> None:
        try:
            source = self._source(mode)
        except Exception as exc:
            self.state.log("error", str(exc))
            with self.state.lock:
                self.state.capture_status = "idle"
            return
        while not self.stop_event.is_set():
            if self.pause_event.is_set():
                time.sleep(0.2)
                continue
            with self.screen_lock:
                if self.stop_event.is_set():
                    break
                item = source.capture()
                self._consider_push(item.path, item.frame_id, item.digest, item.captured_at, str(item.path.name))
            time.sleep(max(0.1, self.state.config.interval))

    def _consider_push(self, path: Path, frame_id: str, digest: str, captured_at: str, source_label: str) -> None:
        with self.state.lock:
            self.state.counters["screenshots"] += 1
            self.state.last_capture_at = captured_at
        if not enough_change(self.previous_digest, digest, self.state.config.change_threshold):
            with self.state.lock:
                self.state.counters["skipped_unchanged"] += 1
            return
        self.previous_digest = digest
        self._push_frame(path, frame_id, digest, captured_at, source_label)

    def _push_frame(self, path: Path, frame_id: str, digest: str, captured_at: str, source_label: str) -> None:
        session_id = self.state.session.session_id
        if not self.client or not session_id:
            return
        api_path = f"/v1/sessions/{session_id}/frames"
        record = FrameRecord(
            frame_id=frame_id,
            source=source_label,
            captured_at=captured_at,
            digest=digest,
            api_path=api_path,
            request_params={
                "session_id": session_id,
                "frame_id": frame_id,
                "captured_at": captured_at,
                "file": source_label,
            },
            thumbnail_url=f"/api/screenshots/{path.name}" if path.name == source_label else None,
            status="queued",
        )
        with self.state.lock:
            self.state.frames.append(record)
        try:
            resp = self.client.push_frame(session_id, frame_id, path, captured_at)
            record.status = resp.get("status", "queued")
            record.submitted_at = resp.get("accepted_at")
            record.request_id = resp.get("request_id")
            record.raw_response = resp
            with self.state.lock:
                self.state.counters["pushed"] += 1
                self.state.last_frame_response = resp
        except ApiError as exc:
            record.status = "network_error" if exc.code in {"network_timeout", "connection_failed"} else "failed"
            record.error_code = exc.code
            record.error_message = exc.message
            record.request_id = exc.request_id
            self.state.log("error", "Frame push failed", frame_id=frame_id, error=exc.to_dict())
            return
        t = threading.Thread(target=self._poll_frame, args=(record,), daemon=True)
        self.frame_workers[frame_id] = t
        t.start()

    def _poll_frame(self, record: FrameRecord) -> None:
        deadline = time.time() + 90
        session_id = self.state.session.session_id
        while session_id and time.time() < deadline and record.status not in FRAME_TERMINAL_STATUSES:
            time.sleep(1.5)
            try:
                resp = self.client.get_frame(session_id, record.frame_id) if self.client else {}
            except ApiError as exc:
                record.error_code = exc.code
                record.error_message = exc.message
                record.request_id = exc.request_id
                continue
            record.raw_response = resp
            record.status = resp.get("status", record.status)
            record.completed_at = resp.get("completed_at")
            record.error_code = resp.get("error_code")
            record.error_message = resp.get("error_message")
            record.summary = resp.get("summary") or {}
            record.request_id = resp.get("request_id")
        if record.status not in FRAME_TERMINAL_STATUSES:
            record.status = "local_timeout"
            record.error_code = "local_timeout"
            record.error_message = "Local display timeout while waiting for terminal frame status."

    def _message_loop(self) -> None:
        while not self.stop_event.is_set():
            session_id = self.state.session.session_id
            if not self.client or not session_id:
                time.sleep(0.5)
                continue
            try:
                while True:
                    page = self.client.get_messages(session_id, self.state.messages.cursor, limit=50)
                    self.state.messages.apply_page(page)
                    if not page.get("has_more"):
                        break
            except ApiError as exc:
                if exc.status_code in {400, 404, 409, 422}:
                    self.state.messages.cursor_error = f"{exc.code}: {exc.message}"
                self.state.log("error", "Message polling failed", error=exc.to_dict())
            time.sleep(1.5)

from pathlib import Path
from types import SimpleNamespace

import pytest

from chat_vision_demo import clients
from chat_vision_demo.clients import ChatVisionClient, HttpChatVisionClient, SdkChatVisionClient, SdkUnavailable


def contract(client: ChatVisionClient, tmp_path: Path) -> None:
    assert client.ready()["ok"] is True
    created = client.create_session()
    sid = created["session_id"]
    image = tmp_path / "1.png"
    image.write_bytes(b"png")
    pushed = client.push_frame(sid, "frame-1", image, "2026-07-15T00:00:00Z")
    assert pushed["status"] in {"queued", "processing", "completed", "failed"}
    assert client.get_frame(sid, "frame-1")["frame_id"] == "frame-1"
    assert "next_cursor" in client.get_messages(sid, None)
    assert client.close_session(sid)["status"] in {"closing", "closed", "open"}
    assert client.delete_session(sid)["deleted"] is True


class FakeClient(ChatVisionClient):
    label = "fake"
    def ready(self): return {"ok": True}
    def create_session(self): return {"session_id": "s1", "status": "open"}
    def push_frame(self, session_id, frame_id, image_path, captured_at): return {"session_id": session_id, "frame_id": frame_id, "status": "queued"}
    def get_frame(self, session_id, frame_id): return {"session_id": session_id, "frame_id": frame_id, "status": "completed"}
    def get_messages(self, session_id, cursor, limit=50): return {"session_id": session_id, "items": [], "next_cursor": "c1", "has_more": False}
    def close_session(self, session_id): return {"session_id": session_id, "status": "closed"}
    def delete_session(self, session_id): return {"deleted": True}


def test_contract_shared_with_fake_client(tmp_path: Path) -> None:
    contract(FakeClient(), tmp_path)


class FakeSdkChatVision:
    def __init__(self, api_key=None, *, base_url="https://x"):
        self.api_key = api_key
        self.base_url = base_url
        self.sessions = FakeSessions()

    def ready(self):
        return {"ok": True}


class FakeSessions:
    def create(self, *, platform="unknown", retention_mode="temporary"):
        return FakeSession()


class FakeSession:
    session_id = "s1"
    info = {
        "session_id": "s1",
        "status": "open",
        "created_at": "2026-07-15T00:00:00Z",
        "expires_at": "2026-07-16T00:00:00Z",
        "retention": {"mode": "temporary", "ttl_seconds": 86400},
        "request_id": "r-create",
    }

    def __init__(self):
        self.messages = FakeMessages()

    def push(self, file, *, frame_id=None, captured_at=None):
        return SimpleNamespace(frame={"session_id": "s1", "frame_id": frame_id, "status": "queued", "accepted_at": captured_at, "request_id": "r-push"})

    def get_frame(self, frame_id):
        return {"session_id": "s1", "frame_id": frame_id, "status": "completed", "accepted_at": "2026-07-15T00:00:00Z", "request_id": "r-frame"}

    def close(self):
        return {"session_id": "s1", "status": "closed", "request_id": "r-close"}

    def delete(self):
        return {"deleted": True, "request_id": "r-delete"}


class FakeMessages:
    def list(self, *, cursor=None, limit=50):
        return {"session_id": "s1", "items": [], "next_cursor": "c1", "has_more": False, "request_id": "r-msg"}


def test_sdk_contract_with_fake_sdk(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(clients.importlib, "import_module", lambda name: SimpleNamespace(ChatVision=FakeSdkChatVision))
    contract(SdkChatVisionClient(api_key="x"), tmp_path)


def test_sdk_unavailable_when_package_missing(monkeypatch) -> None:
    def missing(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(clients.importlib, "import_module", missing)
    with pytest.raises(SdkUnavailable) as exc:
        SdkChatVisionClient(api_key="x")
    assert "chat-vision-sdk is not installed" in exc.value.message


def test_http_client_error_parsing(monkeypatch) -> None:
    client = HttpChatVisionClient("https://example.test", "secret")

    class Response:
        status_code = 401
        content = b"{}"
        headers = {"X-Request-ID": "r1"}
        def json(self):
            return {"error": {"code": "unauthorized", "message": "bad key"}, "request_id": "r1"}

    monkeypatch.setattr(client.session, "request", lambda *a, **k: Response())
    with pytest.raises(Exception) as exc:
        client.create_session()
    assert "bad key" in str(exc.value)

from pathlib import Path

import pytest

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


def test_sdk_contract_skipped_when_unavailable() -> None:
    with pytest.raises(SdkUnavailable) as exc:
        SdkChatVisionClient(api_key="x")
    assert "No official Chat Vision Python SDK module" in exc.value.message or "no verified adapter" in exc.value.message


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

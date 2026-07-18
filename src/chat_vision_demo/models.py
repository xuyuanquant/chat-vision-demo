from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


@dataclass
class ApiError(Exception):
    message: str
    code: str = "api_error"
    status_code: int | None = None
    request_id: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "request_id": self.request_id,
            "details": self.details,
        }


@dataclass
class FrameRecord:
    frame_id: str
    source: str
    captured_at: str
    digest: str
    api_method: str = "POST"
    api_path: str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    thumbnail_url: str | None = None
    submitted_at: str | None = None
    status: str = "local"
    error_code: str | None = None
    error_message: str | None = None
    completed_at: str | None = None
    request_id: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SessionInfo:
    session_id: str | None = None
    status: str = "none"
    created_at: str | None = None
    expires_at: str | None = None
    retention: dict[str, Any] | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

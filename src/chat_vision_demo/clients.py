from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from .models import ApiError
from .openapi_contract import API_BASE_DEFAULT, CREATE_SESSION_DEFAULT, PATHS


class ChatVisionClient(ABC):
    label = "abstract"

    @abstractmethod
    def ready(self) -> dict[str, Any]: ...

    @abstractmethod
    def create_session(self) -> dict[str, Any]: ...

    @abstractmethod
    def push_frame(self, session_id: str, frame_id: str, image_path: Path, captured_at: str | None) -> dict[str, Any]: ...

    @abstractmethod
    def get_frame(self, session_id: str, frame_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_messages(self, session_id: str, cursor: str | None, limit: int = 50) -> dict[str, Any]: ...

    @abstractmethod
    def close_session(self, session_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def delete_session(self, session_id: str) -> dict[str, Any]: ...


class HttpChatVisionClient(ChatVisionClient):
    label = "Raw HTTP"

    def __init__(self, base_url: str = API_BASE_DEFAULT, api_key: str | None = None, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _url(self, path: str, **params: str) -> str:
        return self.base_url + path.format(**params)

    def _request(self, method: str, path: str, *, expected: set[int], path_params: dict[str, str] | None = None, **kwargs: Any) -> dict[str, Any]:
        path_params = path_params or {}
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            resp = self.session.request(
                method,
                self._url(path, **path_params),
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiError("Network timeout", code="network_timeout") from exc
        except requests.ConnectionError as exc:
            raise ApiError("Connection failed", code="connection_failed") from exc
        except requests.RequestException as exc:
            raise ApiError(str(exc), code="request_error") from exc

        request_id = resp.headers.get("X-Request-ID")
        try:
            data = resp.json() if resp.content else {}
        except json.JSONDecodeError as exc:
            raise ApiError("Non-JSON response", code="bad_response", status_code=resp.status_code, request_id=request_id) from exc

        request_id = data.get("request_id") or request_id
        if resp.status_code not in expected:
            err = data.get("error") if isinstance(data, dict) else None
            raise ApiError(
                (err or {}).get("message", f"HTTP {resp.status_code}"),
                code=(err or {}).get("code", "http_error"),
                status_code=resp.status_code,
                request_id=request_id,
                details=(err or {}).get("details"),
            )
        return data

    def ready(self) -> dict[str, Any]:
        return self._request("GET", PATHS["ready"], expected={200, 503})

    def create_session(self) -> dict[str, Any]:
        return self._request("POST", PATHS["create_session"], expected={201}, json=CREATE_SESSION_DEFAULT)

    def push_frame(self, session_id: str, frame_id: str, image_path: Path, captured_at: str | None) -> dict[str, Any]:
        data = {"frame_id": frame_id}
        if captured_at:
            data["captured_at"] = captured_at
        with image_path.open("rb") as fh:
            files = {"file": (image_path.name, fh, _guess_content_type(image_path))}
            return self._request(
                "POST",
                PATHS["push_frame"],
                path_params={"session_id": session_id},
                expected={200, 202},
                data=data,
                files=files,
            )

    def get_frame(self, session_id: str, frame_id: str) -> dict[str, Any]:
        return self._request("GET", PATHS["frame_status"], path_params={"session_id": session_id, "frame_id": frame_id}, expected={200})

    def get_messages(self, session_id: str, cursor: str | None, limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", PATHS["messages"], path_params={"session_id": session_id}, expected={200}, params=params)

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", PATHS["close_session"], path_params={"session_id": session_id}, expected={200})

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self._request("DELETE", PATHS["delete_session"], path_params={"session_id": session_id}, expected={200})


class SdkUnavailable(ApiError):
    pass


class SdkChatVisionClient(ChatVisionClient):
    label = "Python SDK"
    candidate_modules = ("chat_vision", "chat_vision_struct", "chatvision")

    def __init__(self, base_url: str = API_BASE_DEFAULT, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self.reason = self._detect_reason()
        raise SdkUnavailable(self.reason, code="sdk_unavailable")

    def _detect_reason(self) -> str:
        missing = []
        for name in self.candidate_modules:
            try:
                importlib.import_module(name)
                return f"Installed module {name!r} was found, but no verified adapter mapping is implemented yet."
            except ModuleNotFoundError:
                missing.append(name)
        return "No official Chat Vision Python SDK module was found. Tried: " + ", ".join(missing)

    def ready(self) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def create_session(self) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def push_frame(self, session_id: str, frame_id: str, image_path: Path, captured_at: str | None) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def get_frame(self, session_id: str, frame_id: str) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def get_messages(self, session_id: str, cursor: str | None, limit: int = 50) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def close_session(self, session_id: str) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")
    def delete_session(self, session_id: str) -> dict[str, Any]: raise SdkUnavailable(self.reason, code="sdk_unavailable")


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def make_client(driver: str, base_url: str, api_key: str | None) -> ChatVisionClient:
    if driver == "http":
        return HttpChatVisionClient(base_url, api_key)
    if driver == "sdk":
        return SdkChatVisionClient(base_url, api_key)
    raise ValueError(f"Unknown driver: {driver}")

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
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
    sdk_module_name = "chat_vision"

    def __init__(self, base_url: str = API_BASE_DEFAULT, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self.sdk = self._load_sdk()
        self.client = self.sdk.ChatVision(api_key=api_key, base_url=base_url)
        self.sessions: dict[str, Any] = {}

    def _load_sdk(self) -> Any:
        try:
            sdk = importlib.import_module(self.sdk_module_name)
        except ModuleNotFoundError as exc:
            raise SdkUnavailable(
                "chat-vision-sdk is not installed. Install with: pip install -e '.[sdk]'",
                code="sdk_unavailable",
            ) from exc
        if not hasattr(sdk, "ChatVision"):
            raise SdkUnavailable(
                "Installed chat-vision-sdk does not expose ChatVision.",
                code="sdk_unavailable",
            )
        return sdk

    def _call(self, func: Any) -> dict[str, Any]:
        try:
            return _model_to_dict(func())
        except ApiError:
            raise
        except Exception as exc:
            raise _sdk_error_to_api_error(self.sdk, exc) from exc

    def _session(self, session_id: str) -> Any:
        session = self.sessions.get(session_id)
        if session is None:
            raise ApiError(
                "SDK session handle is not available in this process.",
                code="sdk_session_not_found",
            )
        return session

    def ready(self) -> dict[str, Any]:
        return self._call(self.client.ready)

    def create_session(self) -> dict[str, Any]:
        def create() -> Any:
            session = self.client.sessions.create(
                platform=CREATE_SESSION_DEFAULT["platform"],
                retention_mode=CREATE_SESSION_DEFAULT["retention_mode"],
            )
            self.sessions[session.session_id] = session
            return session.info
        return self._call(create)

    def push_frame(self, session_id: str, frame_id: str, image_path: Path, captured_at: str | None) -> dict[str, Any]:
        def push() -> Any:
            handle = self._session(session_id).push(
                image_path,
                frame_id=frame_id,
                captured_at=captured_at,
            )
            return handle.frame
        return self._call(push)

    def get_frame(self, session_id: str, frame_id: str) -> dict[str, Any]:
        return self._call(lambda: self._session(session_id).get_frame(frame_id))

    def get_messages(self, session_id: str, cursor: str | None, limit: int = 50) -> dict[str, Any]:
        return self._call(lambda: self._session(session_id).messages.list(cursor=cursor, limit=limit))

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._call(lambda: self._session(session_id).close())

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self._call(lambda: self._session(session_id).delete())


def _sdk_error_to_api_error(sdk: Any, exc: Exception) -> ApiError:
    api_error_type = getattr(sdk, "APIError", None)
    network_error_type = getattr(sdk, "NetworkError", None)
    chat_vision_error_type = getattr(sdk, "ChatVisionError", None)
    if api_error_type and isinstance(exc, api_error_type):
        return ApiError(
            str(exc),
            code=getattr(exc, "code", None) or "sdk_api_error",
            status_code=getattr(exc, "status_code", None),
            request_id=getattr(exc, "request_id", None),
            details=getattr(exc, "details", None),
        )
    if network_error_type and isinstance(exc, network_error_type):
        return ApiError(
            str(exc),
            code="connection_failed",
            request_id=getattr(exc, "request_id", None),
        )
    if chat_vision_error_type and isinstance(exc, chat_vision_error_type):
        return ApiError(str(exc), code="sdk_error")
    return ApiError(str(exc), code="sdk_error")


def _model_to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        data = asdict(value)
    elif isinstance(value, dict):
        data = dict(value)
    else:
        data = dict(getattr(value, "__dict__", {}))
    return _jsonable(data)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


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

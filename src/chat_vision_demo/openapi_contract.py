from __future__ import annotations

API_BASE_DEFAULT = "https://chat.trendflowing.com"

PATHS = {
    "ready": "/ready",
    "create_session": "/v1/sessions",
    "push_frame": "/v1/sessions/{session_id}/frames",
    "frame_status": "/v1/sessions/{session_id}/frames/{frame_id}",
    "messages": "/v1/sessions/{session_id}/messages",
    "close_session": "/v1/sessions/{session_id}/close",
    "delete_session": "/v1/sessions/{session_id}",
}

CREATE_SESSION_DEFAULT = {
    "platform": "desktop_chat_client",
    "retention_mode": "temporary",
}

MESSAGE_ROLES = {"self", "peer", "unknown"}
MESSAGE_TYPES = {"text", "image", "voice", "file", "system", "unknown"}
FRAME_TERMINAL_STATUSES = {"completed", "failed"}

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessageStore:
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    cursor: str | None = None
    last_event: dict[str, Any] | None = None
    cursor_error: str | None = None

    def apply_page(self, page: dict[str, Any]) -> tuple[int, int]:
        added = 0
        updated = 0
        for event in page.get("items", []):
            if event.get("operation", "upsert") != "upsert":
                continue
            msg = event.get("message", {})
            msg_id = msg.get("id")
            if not msg_id:
                continue
            incoming_revision = int(event.get("revision", msg.get("revision", 0)))
            current = self.messages.get(msg_id)
            if current is None:
                self.messages[msg_id] = msg
                added += 1
            elif incoming_revision >= int(current.get("revision", -1)):
                self.messages[msg_id] = msg
                updated += 1
            self.last_event = event
        self.cursor = page.get("next_cursor", self.cursor)
        self.cursor_error = None
        return added, updated

    def ordered(self) -> list[dict[str, Any]]:
        return sorted(self.messages.values(), key=lambda m: (m.get("order", 0), m.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "cursor_error": self.cursor_error,
            "messages": self.ordered(),
            "last_event": self.last_event,
        }

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .clients import HttpChatVisionClient
from .openapi_contract import API_BASE_DEFAULT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit real cloud smoke test. Consumes API quota.")
    parser.add_argument("--api-base", default=os.getenv("CHAT_VISION_API_BASE", API_BASE_DEFAULT))
    parser.add_argument("--api-key", default=os.getenv("CHAT_VISION_API_KEY"))
    parser.add_argument("--images", type=Path, required=True, help="Directory containing at least two PNG/JPEG screenshots.")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args(argv)
    if not args.api_key:
        print("CHAT_VISION_API_KEY is required", file=sys.stderr)
        return 2
    images = sorted([p for p in args.images.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}])[:2]
    if len(images) < 2:
        print("--images must contain at least two PNG/JPEG files", file=sys.stderr)
        return 2
    client = HttpChatVisionClient(args.api_base, args.api_key, timeout=30)
    ready = client.ready()
    print("ready:", ready)
    if not ready.get("ok"):
        return 1
    created = client.create_session()
    sid = created["session_id"]
    print("session:", sid)
    try:
        for idx, image in enumerate(images, 1):
            frame_id = f"smoke-{idx}-{int(time.time())}"
            print("push:", image.name, frame_id, client.push_frame(sid, frame_id, image, None))
            deadline = time.time() + 90
            status = {}
            while time.time() < deadline:
                status = client.get_frame(sid, frame_id)
                if status.get("status") in {"completed", "failed"}:
                    break
                time.sleep(2)
            print("frame:", status)
        cursor = None
        all_items = []
        while True:
            page = client.get_messages(sid, cursor)
            all_items.extend(page.get("items", []))
            cursor = page.get("next_cursor")
            if not page.get("has_more"):
                break
        print("message_events:", len(all_items))
        assert all("message" in item and "revision" in item for item in all_items)
        client.close_session(sid)
        if args.delete:
            client.delete_session(sid)
    finally:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from chat_vision_demo.sync import MessageStore


def event(msg_id: str, order: int, revision: int, text: str) -> dict:
    return {
        "operation": "upsert",
        "revision": revision,
        "message": {
            "id": msg_id,
            "role": "peer",
            "message_type": "text",
            "text": text,
            "order": order,
            "revision": revision,
            "first_seen_frame_id": "f1",
            "last_seen_frame_id": "f1",
        },
    }


def test_append_upsert_revision_and_order() -> None:
    store = MessageStore()
    added, updated = store.apply_page({"items": [event("b", 2, 1, "two"), event("a", 1, 1, "one")], "next_cursor": "c1"})
    assert (added, updated) == (2, 0)
    added, updated = store.apply_page({"items": [event("a", 1, 2, "one updated")], "next_cursor": "c2"})
    assert (added, updated) == (0, 1)
    assert [m["id"] for m in store.ordered()] == ["a", "b"]
    assert store.messages["a"]["text"] == "one updated"
    assert store.cursor == "c2"


def test_duplicate_cursor_page_does_not_duplicate_messages() -> None:
    store = MessageStore()
    page = {"items": [event("a", 1, 1, "one")], "next_cursor": "same"}
    store.apply_page(page)
    store.apply_page(page)
    assert len(store.ordered()) == 1

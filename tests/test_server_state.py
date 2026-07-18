import json
from chat_vision_demo.server import control_allowed
from chat_vision_demo.state import DemoConfig, RuntimeState, lan_addresses


def test_state_does_not_leak_api_key() -> None:
    state = RuntimeState(DemoConfig(api_base="https://x", api_key="secret-key-1234", driver="http"))
    payload = state.snapshot()
    text = json.dumps(payload)
    assert "secret-key-1234" not in text
    assert payload["api"]["key_configured"] is True


def test_lan_addresses_do_not_show_zero_bind() -> None:
    urls = lan_addresses(8080)
    assert urls["local"] == "http://127.0.0.1:8080"
    assert urls["lan"] == []
    assert "0.0.0.0" not in json.dumps(urls)


def test_lan_addresses_include_public_url() -> None:
    urls = lan_addresses(8080, "http://192.168.1.23:8080/")
    assert urls["public"] == "http://192.168.1.23:8080"


def test_control_allowed_for_local_lan_url() -> None:
    urls = {"local": "http://127.0.0.1:8080", "public": "http://192.168.1.23:8080", "lan": ["http://192.168.1.23:8080"]}
    assert control_allowed("127.0.0.1", urls, False)
    assert control_allowed("192.168.1.23", urls, False)
    assert not control_allowed("192.168.1.50", urls, False)
    assert control_allowed("192.168.1.50", urls, True)

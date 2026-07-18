from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from .clients import SdkUnavailable
from .openapi_contract import API_BASE_DEFAULT
from .runner import DemoRunner
from .server import serve
from .state import DemoConfig, RuntimeState


def parse_rect(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--screen-rect must be x,y,width,height")
    return tuple(parts)  # type: ignore[return-value]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chat Vision local demo")
    parser.add_argument("--api-base", default=os.getenv("CHAT_VISION_API_BASE", API_BASE_DEFAULT))
    parser.add_argument("--api-key", default=os.getenv("CHAT_VISION_API_KEY"))
    parser.add_argument("--driver", choices=["http", "sdk"], default=os.getenv("CHAT_VISION_DRIVER", "http"))
    parser.add_argument("--bind", default=os.getenv("CHAT_VISION_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CHAT_VISION_PORT", "8080")))
    parser.add_argument("--public-url", default=os.getenv("CHAT_VISION_PUBLIC_URL") or None)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--change-threshold", type=float, default=1.0)
    parser.add_argument("--screen-rect", type=parse_rect, default=parse_rect(os.getenv("CHAT_VISION_SCREEN_RECT")))
    parser.add_argument("--windows-window-process", default=os.getenv("CHAT_VISION_WINDOWS_WINDOW_PROCESS") or None)
    parser.add_argument("--windows-window-title", default=os.getenv("CHAT_VISION_WINDOWS_WINDOW_TITLE") or None)
    parser.add_argument("--foreground-window", action="store_true")
    parser.add_argument("--allow-remote-control", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        from .windows_window import enable_dpi_awareness
        enable_dpi_awareness()
    load_dotenv(Path(".env"))
    args = build_parser().parse_args(argv)
    config = DemoConfig(
        api_base=args.api_base,
        api_key=args.api_key,
        driver=args.driver,
        bind=args.bind,
        port=args.port,
        public_url=args.public_url,
        interval=args.interval,
        change_threshold=args.change_threshold,
        allow_remote_control=args.allow_remote_control,
        screen_rect=args.screen_rect,
        windows_window_process=args.windows_window_process,
        windows_window_title=args.windows_window_title,
        foreground_window=args.foreground_window,
    )
    state = RuntimeState(config)
    if args.bind in {"0.0.0.0", "::"}:
        state.log(
            "warning",
            "Demo bound to all network interfaces; use only on a trusted LAN and never expose it to the public internet.",
            bind=args.bind,
            port=args.port,
        )
    runner = DemoRunner(state)
    try:
        runner.client = runner.build_client()
        runner.check_ready()
    except SdkUnavailable as exc:
        state.sdk_error = exc.message
        state.log("warning", "SDK driver unavailable", reason=exc.message)
    except Exception as exc:
        state.log("warning", "Initial ready check failed", error=str(exc))

    server = serve(state, runner)
    print("Chat Vision Demo")
    print(f"Driver: {'Python SDK' if args.driver == 'sdk' else 'Raw HTTP'}")
    print(f"Local: {state.viewer_urls['local']}")
    if state.viewer_urls.get("public"):
        print(f"Public: {state.viewer_urls['public']}")
    for url in state.viewer_urls.get("lan", []):
        print(f"LAN:   {url}")
    if not state.viewer_urls.get("lan"):
        print("LAN:   no private IPv4 address detected")
    qr_content = state.viewer_urls.get("public") or (state.viewer_urls.get("lan") or [state.viewer_urls["local"]])[0]
    print(f"QR content: {qr_content}")
    print(f"QR image:   {state.viewer_urls['local']}/api/qr")
    if args.bind in {"0.0.0.0", "::"}:
        print("WARNING: This demo is bound to all network interfaces. Use only on a trusted LAN and never expose it to the public internet.")
    print("Note: Default binding is localhost. LAN access requires an explicit bind/public URL and may require a local firewall rule.")
    print("Press Ctrl+C to stop.")

    stop = False

    def handle_stop(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal stop
        stop = True
        runner.stop_event.set()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)
    while not stop:
        time.sleep(0.3)
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

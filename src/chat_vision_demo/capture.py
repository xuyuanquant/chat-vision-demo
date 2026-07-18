from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .models import now_iso


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enough_change(previous_digest: str | None, digest: str, threshold: float) -> bool:
    if not previous_digest:
        return True
    if threshold <= 0:
        return True
    return previous_digest != digest


@dataclass
class CaptureItem:
    path: Path
    frame_id: str
    digest: str
    captured_at: str


class ScreenCaptureSource:
    def __init__(
        self,
        rect: tuple[int, int, int, int],
        temp_dir: Path | None = None,
        foreground_hwnd: int | None = None,
    ):
        self.rect = rect
        self.foreground_hwnd = foreground_hwnd
        self.temp_dir = temp_dir or Path(tempfile.gettempdir()) / "chat-vision-demo"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def capture(self) -> CaptureItem:
        try:
            import mss
        except ModuleNotFoundError as exc:
            raise RuntimeError("Screen capture requires optional dependency: pip install '.[screen]'") from exc
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        if self.foreground_hwnd is not None:
            from .windows_window import bring_to_foreground, get_window_info, set_window_topmost
            bring_to_foreground(self.foreground_hwnd)
            info = get_window_info(self.foreground_hwnd)
            self.rect = info.capture_rect
        x, y, width, height = self.rect
        target = self.temp_dir / f"screen-{now_iso().replace(':', '-')}.png"
        if self.foreground_hwnd is not None:
            set_window_topmost(self.foreground_hwnd, True)
            time.sleep(0.35)
        try:
            with mss.mss() as sct:
                img = sct.grab({"left": x, "top": y, "width": width, "height": height})
                mss.tools.to_png(img.rgb, img.size, output=str(target))
        finally:
            if self.foreground_hwnd is not None:
                set_window_topmost(self.foreground_hwnd, False)
        digest = sha256_file(target)
        return CaptureItem(path=target, frame_id=f"screen-{digest[:16]}", digest=digest, captured_at=now_iso())


def cleanup_temp_dir(temp_dir: Path) -> None:
    if temp_dir.exists() and temp_dir.name == "chat-vision-demo":
        shutil.rmtree(temp_dir, ignore_errors=True)

from __future__ import annotations

import ctypes
import time
import sys
from ctypes import wintypes
from dataclasses import dataclass

WECHAT_PROCESS_CANDIDATES = (
    "WeChat.exe",
    "WeChatStore.exe",
)
WECHAT_TITLE_CANDIDATES = ("微信", "WeChat")
_DPI_AWARENESS_SET = False


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_id: int
    process_path: str | None
    rect: tuple[int, int, int, int]

    @property
    def capture_rect(self) -> tuple[int, int, int, int]:
        left, top, right, bottom = self.rect
        return (left, top, max(1, right - left), max(1, bottom - top))


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows window capture is only available when running Python on Windows.")
    enable_dpi_awareness()


def enable_dpi_awareness() -> None:
    global _DPI_AWARENESS_SET
    if _DPI_AWARENESS_SET or sys.platform != "win32":
        return
    _DPI_AWARENESS_SET = True
    try:
        # PER_MONITOR_AWARE_V2 keeps Win32 window coordinates aligned with mss screen pixels.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def find_window(process_name: str | None = None, title_contains: str | None = None) -> WindowInfo:
    require_windows()
    if not process_name and not title_contains:
        matches = list_wechat_windows()
    else:
        matches = [win for win in list_windows(process_name=process_name, title_contains=title_contains) if _usable_rect(win.rect)]
    if not matches:
        criteria = []
        if process_name:
            criteria.append(f"process={process_name}")
        if title_contains:
            criteria.append(f"title contains {title_contains!r}")
        if not criteria:
            criteria.append("WeChat process/title candidates")
        raise RuntimeError("No visible window found for " + ", ".join(criteria))
    return matches[0]


def list_wechat_windows() -> list[WindowInfo]:
    windows = list_windows()
    result = []
    for win in windows:
        exe = _basename(win.process_path).lower() if win.process_path else ""
        title = win.title.lower()
        if exe in {name.lower() for name in WECHAT_PROCESS_CANDIDATES}:
            result.append(win)
            continue
        if any(token.lower() in title for token in WECHAT_TITLE_CANDIDATES):
            result.append(win)
    return sorted(result, key=_wechat_rank)


def foreground(hwnd: int) -> None:
    bring_to_foreground(hwnd)


def set_window_topmost(hwnd: int, enabled: bool) -> None:
    require_windows()
    user32 = ctypes.windll.user32
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST if enabled else HWND_NOTOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
    )


def bring_to_foreground(hwnd: int) -> bool:
    require_windows()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE = 9
    SW_SHOW = 5
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002

    if user32.IsIconic(hwnd):
        user32.ShowWindowAsync(hwnd, SW_RESTORE)
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindowAsync(hwnd, SW_SHOW)
        user32.ShowWindow(hwnd, SW_SHOW)

    foreground_hwnd = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0

    attached_target = False
    attached_foreground = False
    try:
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))

        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)

        # Windows may deny focus stealing unless the caller appears to have recent input.
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.SetForegroundWindow(hwnd)

        if hasattr(user32, "SwitchToThisWindow"):
            user32.SwitchToThisWindow(hwnd, True)

        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        time.sleep(0.2)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)

    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def get_window_info(hwnd: int) -> WindowInfo:
    require_windows()
    title = _window_title(hwnd)
    pid = _window_pid(hwnd)
    return WindowInfo(hwnd=hwnd, title=title, process_id=pid, process_path=_process_path(pid), rect=_window_rect(hwnd))


def list_windows(process_name: str | None = None, title_contains: str | None = None) -> list[WindowInfo]:
    require_windows()
    user32 = ctypes.windll.user32
    result: list[WindowInfo] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        pid = _window_pid(hwnd)
        path = _process_path(pid)
        if process_name and not _process_matches(path, process_name):
            return True
        if title_contains and title_contains.lower() not in title.lower():
            return True
        rect = _window_rect(hwnd)
        result.append(WindowInfo(hwnd=hwnd, title=title, process_id=pid, process_path=path, rect=rect))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return result


def _window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_pid(hwnd: int) -> int:
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def _process_path(pid: int) -> str | None:
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def _process_matches(path: str | None, process_name: str) -> bool:
    if not path:
        return False
    return _basename(path).lower() == process_name.lower()


def _basename(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1]


def _usable_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    return width >= 200 and height >= 200 and left > -1000 and top > -1000


def _wechat_rank(win: WindowInfo) -> tuple[int, int]:
    title = win.title.strip().lower()
    left, top, right, bottom = win.rect
    area = max(0, right - left) * max(0, bottom - top)
    usable_rank = 0 if _usable_rect(win.rect) else 1
    title_rank = 0 if title in {"微信", "wechat"} else 1
    return (usable_rank, title_rank, -area)

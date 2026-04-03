import ctypes
import ctypes.wintypes
from typing import NamedTuple

import psutil
import win32gui
import win32process


class WindowInfo(NamedTuple):
    hwnd: int
    title: str
    process_name: str
    pid: int
    rect: tuple[int, int, int, int]  # left, top, right, bottom


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get the accurate window rect using DWM extended frame bounds.
    Falls back to GetWindowRect if DWM call fails.
    """
    rect = ctypes.wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect), ctypes.sizeof(rect),
    )
    if hr == 0:
        return (rect.left, rect.top, rect.right, rect.bottom)
    return win32gui.GetWindowRect(hwnd)


def get_foreground_window() -> WindowInfo | None:
    """Get info about the currently focused window."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    title = win32gui.GetWindowText(hwnd)
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    rect = get_window_rect(hwnd)
    return WindowInfo(hwnd=hwnd, title=title, process_name=process_name, pid=pid, rect=rect)


def is_window_visible(hwnd: int) -> bool:
    return (win32gui.IsWindow(hwnd)
            and win32gui.IsWindowVisible(hwnd)
            and not win32gui.IsIconic(hwnd))


def find_windows_by_process(process_name: str) -> list[WindowInfo]:
    """Find all visible top-level windows belonging to a process name."""
    results = []

    def _enum_callback(hwnd, _):
        if not is_window_visible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pname = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        if pname.lower() == process_name.lower():
            rect = get_window_rect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w > 0 and h > 0:
                title = win32gui.GetWindowText(hwnd)
                results.append(WindowInfo(hwnd=hwnd, title=title, process_name=pname, pid=pid, rect=rect))
        return True

    win32gui.EnumWindows(_enum_callback, None)
    results.sort(key=lambda w: (w.rect[2] - w.rect[0]) * (w.rect[3] - w.rect[1]), reverse=True)
    return results


class WindowTracker:
    """Tracks a target window by process name, surviving focus loss."""

    def __init__(self, target: WindowInfo):
        self._process_name = target.process_name
        self._hwnd = target.hwnd
        self._last_rect = target.rect

    @property
    def process_name(self) -> str:
        return self._process_name

    def update(self) -> tuple[int, int, int, int] | None:
        """Returns current rect of tracked window, or None if not found.
        Fast path: check known HWND. Slow path: re-find by process name.
        """
        # Fast path
        if is_window_visible(self._hwnd):
            self._last_rect = get_window_rect(self._hwnd)
            return self._last_rect

        # Slow path: re-find by process name
        windows = find_windows_by_process(self._process_name)
        if windows:
            best = windows[0]
            self._hwnd = best.hwnd
            self._last_rect = best.rect
            return self._last_rect

        return None

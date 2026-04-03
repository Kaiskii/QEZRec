import ctypes
import ctypes.wintypes
import threading
import time
from collections.abc import Callable

# Win32 constants
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_P = 0x50
VK_R = 0x52
VK_Q = 0x51
WM_HOTKEY = 0x0312
HOTKEY_TOGGLE = 1
HOTKEY_CANCEL = 2
HOTKEY_PAUSE  = 3

user32 = ctypes.windll.user32


class HotkeyListener:
    """Uses Win32 RegisterHotKey for OS-level hotkeys that work even in fullscreen games."""

    def __init__(self, on_toggle: Callable[[], None], on_cancel: Callable[[], None] | None = None, on_pause: Callable[[], None] | None = None):
        self._on_toggle = on_toggle
        self._on_cancel = on_cancel
        self._on_pause = on_pause
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        ok_r = user32.RegisterHotKey(
            None, HOTKEY_TOGGLE, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_R,
        )
        if not ok_r:
            print("Warning: Failed to register Ctrl+Shift+R hotkey (may be in use by another app)")

        ok_q = user32.RegisterHotKey(
            None, HOTKEY_CANCEL, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_Q,
        )
        if not ok_q:
            print("Warning: Failed to register Ctrl+Shift+Q hotkey (may be in use by another app)")

        ok_p = user32.RegisterHotKey(
            None, HOTKEY_PAUSE, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_P,
        )
        if not ok_p:
            print("Warning: Failed to register Ctrl+Shift+P hotkey (may be in use by another app)")

        msg = ctypes.wintypes.MSG()
        while self._running.is_set():
            # Use GetMessage with a timeout via MsgWaitForMultipleObjects
            # This properly yields to the OS and doesn't clog the queue
            result = user32.MsgWaitForMultipleObjects(
                0, None, False, 100, 0x04FF  # QS_ALLINPUT
            )
            # Drain ALL pending messages each wakeup
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_TOGGLE:
                        threading.Thread(target=self._on_toggle, daemon=True).start()
                    elif msg.wParam == HOTKEY_CANCEL and self._on_cancel:
                        threading.Thread(target=self._on_cancel, daemon=True).start()
                    elif msg.wParam == HOTKEY_PAUSE and self._on_pause:
                        threading.Thread(target=self._on_pause, daemon=True).start()
                # Dispatch all other messages so they don't pile up and block
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, HOTKEY_TOGGLE)
        user32.UnregisterHotKey(None, HOTKEY_CANCEL)
        user32.UnregisterHotKey(None, HOTKEY_PAUSE)

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

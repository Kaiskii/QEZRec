import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable

# Win32 constants
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_TOGGLE = 1
HOTKEY_CANCEL = 2
HOTKEY_PAUSE  = 3

user32 = ctypes.windll.user32


class HotkeyListener:
    """Uses Win32 RegisterHotKey for OS-level hotkeys that work even in fullscreen games."""

    def __init__(self, on_toggle: Callable[[], None],
                 on_cancel: Callable[[], None] | None = None,
                 on_pause: Callable[[], None] | None = None,
                 keybinds: dict[str, tuple[int, int]] | None = None,
                 is_recording: Callable[[], bool] | None = None):
        self._on_toggle = on_toggle
        self._on_cancel = on_cancel
        self._on_pause = on_pause
        self._keybinds = keybinds
        self._is_recording = is_recording or (lambda: True)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

    def restart(self, keybinds: dict[str, tuple[int, int]]) -> None:
        """Stop and restart the listener with new keybinds."""
        self._keybinds = keybinds
        self.stop()
        self.start()

    def _listen(self):
        from .settings import DEFAULTS
        binds = self._keybinds or DEFAULTS

        toggle_mods, toggle_vk = binds.get("toggle", (0x0006, 0x52))
        cancel_mods, cancel_vk = binds.get("cancel", (0x0006, 0x51))
        pause_mods,  pause_vk  = binds.get("pause",  (0x0006, 0x50))

        ok_toggle = user32.RegisterHotKey(None, HOTKEY_TOGGLE, toggle_mods | MOD_NOREPEAT, toggle_vk)
        if not ok_toggle:
            print("Warning: Failed to register Toggle hotkey (may be in use by another app)")

        cancel_registered = False
        pause_registered = False
        cancel_failed = False
        pause_failed = False

        def update_action_hotkeys():
            nonlocal cancel_registered, pause_registered, cancel_failed, pause_failed

            should_register = self._is_recording()
            if should_register and self._on_cancel and not cancel_registered and not cancel_failed:
                ok_cancel = user32.RegisterHotKey(None, HOTKEY_CANCEL, cancel_mods | MOD_NOREPEAT, cancel_vk)
                if ok_cancel:
                    cancel_registered = True
                else:
                    cancel_failed = True
                    print("Warning: Failed to register Cancel hotkey (may be in use by another app)")
            elif not should_register and cancel_registered:
                user32.UnregisterHotKey(None, HOTKEY_CANCEL)
                cancel_registered = False
            elif not should_register:
                cancel_failed = False

            if should_register and self._on_pause and not pause_registered and not pause_failed:
                ok_pause = user32.RegisterHotKey(None, HOTKEY_PAUSE, pause_mods | MOD_NOREPEAT, pause_vk)
                if ok_pause:
                    pause_registered = True
                else:
                    pause_failed = True
                    print("Warning: Failed to register Pause hotkey (may be in use by another app)")
            elif not should_register and pause_registered:
                user32.UnregisterHotKey(None, HOTKEY_PAUSE)
                pause_registered = False
            elif not should_register:
                pause_failed = False

        msg = ctypes.wintypes.MSG()
        while self._running.is_set():
            update_action_hotkeys()
            user32.MsgWaitForMultipleObjects(0, None, False, 100, 0x04FF)
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_TOGGLE:
                        threading.Thread(target=self._on_toggle, daemon=True).start()
                    elif msg.wParam == HOTKEY_CANCEL and self._on_cancel:
                        threading.Thread(target=self._on_cancel, daemon=True).start()
                    elif msg.wParam == HOTKEY_PAUSE and self._on_pause:
                        threading.Thread(target=self._on_pause, daemon=True).start()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, HOTKEY_TOGGLE)
        if cancel_registered:
            user32.UnregisterHotKey(None, HOTKEY_CANCEL)
        if pause_registered:
            user32.UnregisterHotKey(None, HOTKEY_PAUSE)

"""Keybind detection, VK mappings, CLI setup flow, and Tkinter dialog."""
import ctypes
import ctypes.wintypes
import threading
import tkinter as tk
from collections.abc import Callable

# Win32 modifier constants (RegisterHotKey flags)
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000

# Virtual key code ↔ name mappings
VK_TO_NAME: dict[int, str] = {
    # Letters
    **{0x41 + i: chr(ord('a') + i) for i in range(26)},
    # Digits
    **{0x30 + i: str(i) for i in range(10)},
    # Function keys
    **{0x70 + i: f"f{i + 1}" for i in range(12)},
    # Specials
    0x20: "space",
    0x09: "tab",
    0x0D: "enter",
    0x08: "backspace",
    0x2E: "delete",
    0x2D: "insert",
    0x24: "home",
    0x23: "end",
    0x21: "pageup",
    0x22: "pagedown",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0xBB: "equals",
    0xBD: "minus",
    0xDB: "lbracket",
    0xDD: "rbracket",
    0xBA: "semicolon",
    0xDE: "quote",
    0xBC: "comma",
    0xBE: "period",
    0xBF: "slash",
    0xDC: "backslash",
    0xC0: "tilde",
}

NAME_TO_VK: dict[str, int] = {v: k for k, v in VK_TO_NAME.items()}

# Tk modifier state bits → MOD_ flags
_TK_STATE_CTRL = 0x0004
_TK_STATE_SHIFT = 0x0001
_TK_STATE_ALT = 0x0008

# VK codes that are modifier keys (skip these as the "main" key)
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def combo_to_string(modifiers: int, vk_code: int) -> str:
    """Convert (modifiers, vk_code) to a human-readable string like 'ctrl+shift+r'."""
    parts = []
    if modifiers & MOD_CONTROL:
        parts.append("ctrl")
    if modifiers & MOD_SHIFT:
        parts.append("shift")
    if modifiers & MOD_ALT:
        parts.append("alt")
    parts.append(VK_TO_NAME.get(vk_code, f"vk{vk_code:02x}"))
    return "+".join(parts)


def combo_to_display(modifiers: int, vk_code: int) -> str:
    """Like combo_to_string but title-cased for display, e.g. 'Ctrl+Shift+R'."""
    return "+".join(p.capitalize() if len(p) <= 3 else p.upper() if p.startswith('f') and p[1:].isdigit() else p.capitalize()
                    for p in combo_to_string(modifiers, vk_code).split("+"))


def string_to_combo(s: str) -> tuple[int, int] | None:
    """Parse 'ctrl+shift+r' → (MOD_CONTROL | MOD_SHIFT, VK_R). Returns None if invalid."""
    parts = [p.strip().lower() for p in s.split("+")]
    modifiers = 0
    vk_code = None
    for part in parts:
        if part == "ctrl":
            modifiers |= MOD_CONTROL
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part in NAME_TO_VK:
            vk_code = NAME_TO_VK[part]
        elif part.startswith("vk") and part[2:].isalnum():
            try:
                vk_code = int(part[2:], 16)
            except ValueError:
                return None
        else:
            return None
    if vk_code is None:
        return None
    return (modifiers, vk_code)


# ---------------------------------------------------------------------------
# CLI detection via WH_KEYBOARD_LL
# ---------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_ESCAPE = 0x1B

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)


def detect_combo_cli() -> tuple[int, int] | None:
    """
    Install a low-level keyboard hook, block until user presses a key combo.
    Returns (modifiers, vk_code) or None if Escape was pressed.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    result: list[tuple[int, int] | None] = [None]
    done = threading.Event()
    hook_handle: list[int] = [0]

    def hook_callback(n_code, w_param, l_param):
        if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            vk = ctypes.cast(l_param, ctypes.POINTER(ctypes.c_ulong))[0]
            if vk == VK_ESCAPE:
                result[0] = None
                done.set()
            elif vk not in _MODIFIER_VKS:
                mods = 0
                if user32.GetAsyncKeyState(0x11) & 0x8000:  # VK_CONTROL
                    mods |= MOD_CONTROL
                if user32.GetAsyncKeyState(0x10) & 0x8000:  # VK_SHIFT
                    mods |= MOD_SHIFT
                if user32.GetAsyncKeyState(0x12) & 0x8000:  # VK_MENU (Alt)
                    mods |= MOD_ALT
                result[0] = (mods, vk)
                done.set()
        return user32.CallNextHookEx(hook_handle[0], n_code, w_param, l_param)

    cb = HOOKPROC(hook_callback)
    hook_handle[0] = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, kernel32.GetModuleHandleW(None), 0)

    msg = ctypes.wintypes.MSG()
    while not done.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    user32.UnhookWindowsHookEx(hook_handle[0])
    return result[0]


def run_keybind_setup_cli() -> None:
    """Interactive console flow to set keybinds and save to ~/.qez."""
    from .settings import load_keybinds, save_keybinds

    actions = [
        ("toggle", "Start/Stop Recording"),
        ("cancel", "Cancel Recording"),
        ("pause",  "Pause/Resume Recording"),
    ]

    current = load_keybinds()
    new_binds: dict[str, tuple[int, int]] = dict(current)

    print("\nQEZRec Keybind Setup")
    print("Press a key combination for each action. Press Escape to keep the current binding.\n")

    for key, label in actions:
        current_str = combo_to_display(*current[key])
        print(f"  {label} [current: {current_str}]: ", end="", flush=True)
        combo = detect_combo_cli()
        if combo is None:
            print("(kept)")
        else:
            new_binds[key] = combo
            print(combo_to_display(*combo))

    save_keybinds(new_binds)
    print(f"\nSaved to ~/.qez")


# ---------------------------------------------------------------------------
# Tkinter dialog for tray mode
# ---------------------------------------------------------------------------

ACTION_LABELS = {
    "toggle": "Start/Stop Recording",
    "cancel": "Cancel Recording",
    "pause":  "Pause/Resume Recording",
}

ACTION_ORDER = ["toggle", "cancel", "pause"]


class KeybindDialog:
    """
    Tkinter dialog for setting keybinds. Must be created and shown from the Tk thread
    via overlay._root.after(0, ...).
    """

    def __init__(self, root: tk.Tk, current_binds: dict[str, tuple[int, int]],
                 on_save: Callable[[dict[str, tuple[int, int]]], None]):
        self._root = root
        self._on_save = on_save
        self._binds: dict[str, tuple[int, int]] = dict(current_binds)
        self._capturing: str | None = None  # which action is currently being captured
        self._top: tk.Toplevel | None = None
        self._labels: dict[str, tk.Label] = {}

    def show(self) -> None:
        top = tk.Toplevel(self._root)
        self._top = top
        top.title("Set Keybinds — QEZRec")
        top.configure(bg="#1a1a1a")
        top.resizable(False, False)
        top.attributes("-topmost", True)

        pad = {"padx": 14, "pady": 6}

        for action in ACTION_ORDER:
            row = tk.Frame(top, bg="#1a1a1a")
            row.pack(fill=tk.X, **pad)

            tk.Label(row, text=ACTION_LABELS[action], fg="white", bg="#1a1a1a",
                     font=("Segoe UI", 10), width=22, anchor="w").pack(side=tk.LEFT)

            lbl = tk.Label(row, text=combo_to_display(*self._binds[action]),
                           fg="#a0aec0", bg="#2d2d2d", font=("Segoe UI", 10),
                           width=18, relief="flat", padx=6, pady=3)
            lbl.pack(side=tk.LEFT, padx=(0, 8))
            self._labels[action] = lbl

            btn = tk.Button(row, text="Set", bg="#3182ce", fg="white",
                            font=("Segoe UI", 9), relief="flat", padx=8,
                            command=lambda a=action: self._start_capture(a))
            btn.pack(side=tk.LEFT)

        tk.Frame(top, bg="#333", height=1).pack(fill=tk.X, padx=14, pady=6)

        btn_row = tk.Frame(top, bg="#1a1a1a")
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 12))

        tk.Button(btn_row, text="Reset to Defaults", bg="#4a5568", fg="white",
                  font=("Segoe UI", 9), relief="flat", padx=10,
                  command=self._reset_defaults).pack(side=tk.LEFT)

        tk.Button(btn_row, text="Save", bg="#38a169", fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=16,
                  command=self._save).pack(side=tk.RIGHT)

        tk.Button(btn_row, text="Cancel", bg="#4a5568", fg="white",
                  font=("Segoe UI", 9), relief="flat", padx=10,
                  command=top.destroy).pack(side=tk.RIGHT, padx=(0, 8))

        top.bind("<KeyPress>", self._on_keypress)
        top.bind("<Escape>", lambda e: self._cancel_capture())

        # Center on screen
        top.update_idletasks()
        w, h = top.winfo_width(), top.winfo_height()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _start_capture(self, action: str) -> None:
        self._capturing = action
        self._labels[action].config(text="Press a key combo...", fg="#f6e05e")
        self._top.focus_force()

    def _cancel_capture(self) -> None:
        if self._capturing:
            action = self._capturing
            self._capturing = None
            self._labels[action].config(text=combo_to_display(*self._binds[action]), fg="#a0aec0")

    def _on_keypress(self, event: tk.Event) -> None:
        if self._capturing is None:
            return
        # Skip pure modifier keypresses
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                            "Alt_L", "Alt_R", "Super_L", "Super_R"):
            return

        mods = 0
        if event.state & _TK_STATE_CTRL:
            mods |= MOD_CONTROL
        if event.state & _TK_STATE_SHIFT:
            mods |= MOD_SHIFT
        if event.state & _TK_STATE_ALT:
            mods |= MOD_ALT

        # Map Tk keycode to VK — on Windows, Tk keycodes match VK codes
        vk = event.keycode
        if vk == 0:
            return

        action = self._capturing
        self._capturing = None
        self._binds[action] = (mods, vk)
        self._labels[action].config(text=combo_to_display(mods, vk), fg="#a0aec0")

    def _reset_defaults(self) -> None:
        from .settings import DEFAULTS
        self._capturing = None
        self._binds = dict(DEFAULTS)
        for action in ACTION_ORDER:
            self._labels[action].config(text=combo_to_display(*self._binds[action]), fg="#a0aec0")

    def _save(self) -> None:
        from .settings import save_keybinds
        save_keybinds(self._binds)
        self._on_save(dict(self._binds))
        if self._top:
            self._top.destroy()


def open_keybind_dialog(current_binds: dict[str, tuple[int, int]],
                        on_save: Callable[[dict[str, tuple[int, int]]], None]) -> None:
    """Open the keybind dialog on the Tk thread. Call from any thread."""
    from .overlay import _ensure_tk_thread, _root
    _ensure_tk_thread()

    def _create():
        dlg = KeybindDialog(_root, current_binds, on_save)
        dlg.show()

    _root.after(0, _create)

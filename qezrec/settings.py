"""Read/write user settings from ~/.qez (TOML format)."""
import os
import tomllib

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".qez")

# Win32 modifier constants
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_ALT = 0x0001

DEFAULTS: dict[str, tuple[int, int]] = {
    "toggle": (MOD_CONTROL | MOD_SHIFT, 0x52),  # Ctrl+Shift+R
    "cancel": (MOD_CONTROL | MOD_SHIFT, 0x51),  # Ctrl+Shift+Q
    "pause":  (MOD_CONTROL | MOD_SHIFT, 0x50),  # Ctrl+Shift+P
}


def load_keybinds() -> dict[str, tuple[int, int]]:
    """Load keybinds from ~/.qez. Returns defaults if file is missing or malformed."""
    from .keybind_setup import string_to_combo
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        binds = data.get("keybinds", {})
        result = dict(DEFAULTS)
        for action in ("toggle", "cancel", "pause"):
            if action in binds:
                combo = string_to_combo(binds[action])
                if combo is not None:
                    result[action] = combo
        return result
    except Exception:
        return dict(DEFAULTS)


def save_keybinds(binds: dict[str, tuple[int, int]]) -> None:
    """Write keybinds to ~/.qez in TOML format."""
    from .keybind_setup import combo_to_string
    lines = ["[keybinds]\n"]
    for action in ("toggle", "cancel", "pause"):
        if action in binds:
            s = combo_to_string(*binds[action])
            lines.append(f'{action} = "{s}"\n')
    with open(CONFIG_PATH, "w") as f:
        f.writelines(lines)

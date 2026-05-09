import logging
import os
import sys
import threading
from collections.abc import Callable

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from .recorder import State

log = logging.getLogger(__name__)

SIZE = 64


def _find_icon_path() -> str | None:
    """Find qezico.png - works both from source and PyInstaller bundle."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(sys._MEIPASS, "qezico.png"))
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(pkg_dir, "..", "assets", "qezico.png"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _create_icon_image(recording: bool = False) -> Image.Image:
    """Generate tray icon - grey Q when idle, red circle when recording."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if recording:
        draw.ellipse([4, 4, SIZE - 4, SIZE - 4], fill=(220, 38, 38), outline=(255, 255, 255), width=2)
    else:
        draw.ellipse([4, 4, SIZE - 4, SIZE - 4], fill=(100, 100, 100), outline=(200, 200, 200), width=2)
        from PIL import ImageFont
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except OSError:
            font = ImageFont.load_default()
        draw.text((SIZE // 2, SIZE // 2), "Q", fill=(255, 255, 255), font=font, anchor="mm")
    return img


class TrayApp:
    """System tray icon for QEZRec."""

    def __init__(self, recorder, hotkey, config):
        self._recorder = recorder
        self._hotkey = hotkey
        self._config = config
        self._icon: Icon | None = None
        from .settings import load_keybinds
        self._keybinds = load_keybinds()

    def _build_menu(self) -> Menu:
        is_rec = self._recorder.state == State.RECORDING
        return Menu(
            MenuItem(
                "Stop Recording" if is_rec else "Start Recording (Ctrl+Shift+R)",
                self._on_toggle,
            ),
            MenuItem(
                "Cancel Recording (Ctrl+Shift+Q)",
                self._on_cancel,
                enabled=lambda _: self._recorder.state == State.RECORDING,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Open Recordings Folder",
                self._on_open_folder,
            ),
            MenuItem(
                "Set Keybinds",
                self._on_set_keybinds,
            ),
            Menu.SEPARATOR,
            MenuItem(
                f"Audio: {'ON' if self._config.audio else 'OFF'}",
                None,
                enabled=False,
            ),
            MenuItem(
                f"{self._config.fps} FPS | {self._config.encoder}",
                None,
                enabled=False,
            ),
            Menu.SEPARATOR,
            MenuItem("Quit", self._on_quit),
        )

    def _on_toggle(self, icon=None, item=None):
        threading.Thread(target=self._recorder.toggle, daemon=True).start()
        self._schedule_icon_update()

    def _on_cancel(self, icon=None, item=None):
        threading.Thread(target=self._recorder.cancel, daemon=True).start()
        self._schedule_icon_update()

    def _on_open_folder(self, icon=None, item=None):
        folder = self._config.output_dir
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def _on_set_keybinds(self, icon=None, item=None):
        from .keybind_setup import open_keybind_dialog
        def _on_save(new_binds):
            self._keybinds = new_binds
            self._hotkey.restart(new_binds)
        open_keybind_dialog(self._keybinds, _on_save)

    def _on_quit(self, icon=None, item=None):
        self._recorder.cleanup()
        self._hotkey.stop()
        if self._icon:
            self._icon.stop()

    def _schedule_icon_update(self):
        """Update icon after a short delay to let state change propagate."""
        def _update():
            import time
            time.sleep(0.3)
            self._update_icon()
        threading.Thread(target=_update, daemon=True).start()

    def _update_icon(self):
        if self._icon:
            is_rec = self._recorder.state == State.RECORDING
            self._icon.icon = _create_icon_image(recording=is_rec)
            self._icon.title = "QEZRec - Recording..." if is_rec else "QEZRec - Ready"
            self._icon.menu = self._build_menu()

    def run(self):
        """Run the tray icon (blocks the calling thread)."""
        self._icon = Icon(
            name="QEZRec",
            icon=_create_icon_image(recording=False),
            title="QEZRec - Ready",
            menu=self._build_menu(),
        )

        # Monitor recorder state changes to update the icon
        self._monitor_thread = threading.Thread(target=self._state_monitor, daemon=True)
        self._monitor_thread.start()

        self._icon.run()

    def _state_monitor(self):
        """Poll recorder state and update icon when it changes."""
        import time
        last_state = None
        while True:
            time.sleep(0.5)
            current = self._recorder.state
            if current != last_state:
                last_state = current
                self._update_icon()

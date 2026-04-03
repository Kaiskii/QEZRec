import threading
import time
import tkinter as tk

# ---------------------------------------------------------------------------
# Single persistent Tk root — all Tkinter calls must happen on this thread.
# ---------------------------------------------------------------------------
_root: tk.Tk | None = None
_root_lock = threading.Lock()
_root_ready = threading.Event()
_tk_thread: threading.Thread | None = None

_overlay_lock = threading.Lock()
_active_overlays: int = 0


def _run_tk_loop():
    global _root
    _root = tk.Tk()
    _root.withdraw()  # invisible root — overlays use Toplevel
    _root_ready.set()
    _root.mainloop()


def _ensure_tk_thread():
    global _tk_thread
    with _root_lock:
        if _tk_thread is None or not _tk_thread.is_alive():
            _root_ready.clear()
            _tk_thread = threading.Thread(target=_run_tk_loop, daemon=True)
            _tk_thread.start()
    _root_ready.wait(timeout=3)


def _inc_overlay():
    global _active_overlays
    with _overlay_lock:
        _active_overlays += 1


def _dec_overlay():
    global _active_overlays
    with _overlay_lock:
        _active_overlays -= 1


def any_overlay_visible() -> bool:
    """Returns True if any QEZRec overlay is currently on screen."""
    with _overlay_lock:
        return _active_overlays > 0


def warm_up():
    """Start the Tk thread eagerly at app launch so the first overlay has no init delay."""
    _ensure_tk_thread()


# ---------------------------------------------------------------------------
# Temporary notification popup
# ---------------------------------------------------------------------------

def show_overlay(text: str, duration: float = 2.0, color: str = "#e53e3e"):
    """Show a temporary popup in the top-right corner. Auto-dismisses after duration."""
    _ensure_tk_thread()
    _inc_overlay()
    _root.after(0, lambda: _create_temp_overlay(text, duration, color))


def _create_temp_overlay(text: str, duration: float, color: str):
    top = tk.Toplevel(_root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.9)
    top.configure(bg="#1a1a1a")

    frame = tk.Frame(top, bg="#1a1a1a", padx=14, pady=8)
    frame.pack()

    dot = tk.Canvas(frame, width=12, height=12, bg="#1a1a1a", highlightthickness=0)
    dot.create_oval(2, 2, 10, 10, fill=color, outline="")
    dot.pack(side=tk.LEFT, padx=(0, 8))

    label = tk.Label(frame, text=text, fg="white", bg="#1a1a1a", font=("Segoe UI", 11))
    label.pack(side=tk.LEFT)

    top.update_idletasks()
    w = top.winfo_width()
    screen_w = top.winfo_screenwidth()
    top.geometry(f"+{screen_w - w - 20}+{20}")

    def _destroy():
        top.destroy()
        _dec_overlay()

    top.after(int(duration * 1000), _destroy)


# ---------------------------------------------------------------------------
# Persistent recording indicator
# ---------------------------------------------------------------------------

class RecordingOverlay:
    def __init__(self):
        self._top: tk.Toplevel | None = None
        self._dismiss = threading.Event()
        self._ready = threading.Event()
        self._start_time: float = 0
        self._elapsed_var: tk.StringVar | None = None
        self._dot = None
        self._dot_visible = True

    def show(self, process_name: str):
        self._dismiss.clear()
        self._ready.clear()
        self._start_time = time.perf_counter()
        _ensure_tk_thread()
        _inc_overlay()
        _root.after(0, lambda: self._create(process_name))
        self._ready.wait(timeout=2)

    def _create(self, process_name: str):
        top = tk.Toplevel(_root)
        self._top = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.85)
        top.configure(bg="#1a1a1a")

        frame = tk.Frame(top, bg="#1a1a1a", padx=14, pady=8)
        frame.pack()

        dot = tk.Canvas(frame, width=12, height=12, bg="#1a1a1a", highlightthickness=0)
        dot.create_oval(2, 2, 10, 10, fill="#e53e3e", outline="")
        dot.pack(side=tk.LEFT, padx=(0, 8))
        self._dot = dot
        self._dot_visible = True

        label = tk.Label(frame, text=f"REC  {process_name}", fg="white", bg="#1a1a1a",
                         font=("Segoe UI", 11))
        label.pack(side=tk.LEFT)

        self._elapsed_var = tk.StringVar(value="  00:00")
        time_label = tk.Label(frame, textvariable=self._elapsed_var, fg="#a0a0a0",
                              bg="#1a1a1a", font=("Segoe UI", 11))
        time_label.pack(side=tk.LEFT)

        top.update_idletasks()
        w = top.winfo_width()
        screen_w = top.winfo_screenwidth()
        top.geometry(f"+{screen_w - w - 20}+{20}")

        self._ready.set()
        self._update_timer()
        self._blink_dot()
        self._check_dismiss()

    def _update_timer(self):
        if self._top and not self._dismiss.is_set():
            elapsed = time.perf_counter() - self._start_time
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            self._elapsed_var.set(f"  {mins:02d}:{secs:02d}")
            self._top.after(1000, self._update_timer)

    def _blink_dot(self):
        if self._top and not self._dismiss.is_set():
            if self._dot_visible:
                self._dot.itemconfigure(1, fill="#1a1a1a")
            else:
                self._dot.itemconfigure(1, fill="#e53e3e")
            self._dot_visible = not self._dot_visible
            self._top.after(800, self._blink_dot)

    def _check_dismiss(self):
        if self._dismiss.is_set():
            self._elapsed_var = None  # release on Tk thread before destroy
            self._top.destroy()
            self._top = None
            _dec_overlay()
        elif self._top:
            self._top.after(100, self._check_dismiss)

    def dismiss(self):
        self._dismiss.set()

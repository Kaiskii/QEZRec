import threading
import time
import tkinter as tk


def show_overlay(text: str, duration: float = 2.0, color: str = "#e53e3e"):
    """Show a temporary popup in the top-right corner. Auto-dismisses after duration."""
    threading.Thread(target=_show_temp, args=(text, duration, color), daemon=True).start()


class RecordingOverlay:
    """Persistent recording indicator that stays on screen until dismissed."""

    def __init__(self):
        self._root: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._dismiss = threading.Event()
        self._ready = threading.Event()
        self._elapsed_var = None
        self._start_time: float = 0

    def show(self, process_name: str):
        self._dismiss.clear()
        self._ready.clear()
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(
            target=self._run, args=(process_name,), daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2)

    def _run(self, process_name: str):
        root = tk.Tk()
        self._root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.85)
        root.configure(bg="#1a1a1a")

        frame = tk.Frame(root, bg="#1a1a1a", padx=14, pady=8)
        frame.pack()

        # Red recording dot
        dot = tk.Canvas(frame, width=12, height=12, bg="#1a1a1a", highlightthickness=0)
        dot.create_oval(2, 2, 10, 10, fill="#e53e3e", outline="")
        dot.pack(side=tk.LEFT, padx=(0, 8))
        self._dot = dot
        self._dot_visible = True

        # "REC  processname  00:00"
        label = tk.Label(frame, text=f"REC  {process_name}", fg="white", bg="#1a1a1a",
                         font=("Segoe UI", 11))
        label.pack(side=tk.LEFT)

        self._elapsed_var = tk.StringVar(value="  00:00")
        time_label = tk.Label(frame, textvariable=self._elapsed_var, fg="#a0a0a0",
                              bg="#1a1a1a", font=("Segoe UI", 11))
        time_label.pack(side=tk.LEFT)

        root.update_idletasks()
        w = root.winfo_width()
        screen_w = root.winfo_screenwidth()
        root.geometry(f"+{screen_w - w - 20}+{20}")

        self._ready.set()
        self._update_timer()
        self._blink_dot()
        self._check_dismiss()
        root.mainloop()

    def _update_timer(self):
        if self._root and not self._dismiss.is_set():
            elapsed = time.perf_counter() - self._start_time
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            self._elapsed_var.set(f"  {mins:02d}:{secs:02d}")
            self._root.after(1000, self._update_timer)

    def _blink_dot(self):
        if self._root and not self._dismiss.is_set():
            if self._dot_visible:
                self._dot.itemconfigure(1, fill="#1a1a1a")
            else:
                self._dot.itemconfigure(1, fill="#e53e3e")
            self._dot_visible = not self._dot_visible
            self._root.after(800, self._blink_dot)

    def _check_dismiss(self):
        if self._dismiss.is_set():
            self._root.destroy()
            self._root = None
        elif self._root:
            self._root.after(100, self._check_dismiss)

    def dismiss(self):
        self._dismiss.set()


def _show_temp(text: str, duration: float, color: str):
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.9)
    root.configure(bg="#1a1a1a")

    frame = tk.Frame(root, bg="#1a1a1a", padx=14, pady=8)
    frame.pack()

    dot = tk.Canvas(frame, width=12, height=12, bg="#1a1a1a", highlightthickness=0)
    dot.create_oval(2, 2, 10, 10, fill=color, outline="")
    dot.pack(side=tk.LEFT, padx=(0, 8))

    label = tk.Label(frame, text=text, fg="white", bg="#1a1a1a",
                     font=("Segoe UI", 11))
    label.pack(side=tk.LEFT)

    root.update_idletasks()
    w = root.winfo_width()
    screen_w = root.winfo_screenwidth()
    root.geometry(f"+{screen_w - w - 20}+{20}")

    root.after(int(duration * 1000), root.destroy)
    root.mainloop()

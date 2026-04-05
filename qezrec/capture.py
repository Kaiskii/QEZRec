import logging
import queue
import threading
import time

import numpy as np
from windows_capture import WindowsCapture, Frame, InternalCaptureControl, CaptureControl

log = logging.getLogger(__name__)


class ScreenCapture:
    """Captures a specific window using Windows Graphics Capture API.
    Captures the window content directly - works even when occluded or alt-tabbed.
    Always produces frames at the target FPS for sync with audio.
    """

    def __init__(self, window_title: str, fps: int = 30, on_closed: callable = None):
        self._window_title = window_title
        self._fps = fps
        self._frame_interval = 1.0 / fps
        self._running = threading.Event()
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=fps * 4)
        self._fps_thread: threading.Thread | None = None
        self._capture_control: CaptureControl | None = None
        self._last_frame: np.ndarray | None = None
        self._last_frame_lock = threading.Lock()
        self._frame_count = 0
        self._capture_ready = threading.Event()
        self._capture_error: str | None = None
        self._on_closed = on_closed

    def start(self):
        self._running.set()

        try:
            capture = WindowsCapture(
                cursor_capture=False,
                draw_border=False,
                window_name=self._window_title,
            )
        except Exception as e:
            log.error(f"[CAPTURE] Failed to create WindowsCapture: {e}")
            self._capture_error = str(e)
            self._capture_ready.set()
            return

        log.debug("[CAPTURE] WindowsCapture created, registering callbacks")

        @capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            if not self._running.is_set():
                capture_control.stop()
                return
            try:
                buf = frame.frame_buffer
                bgr = np.ascontiguousarray(buf[:, :, :3])
                with self._last_frame_lock:
                    self._last_frame = bgr
                self._frame_count += 1
                if self._frame_count == 1:
                    h, w = bgr.shape[:2]
                    log.debug(f"[CAPTURE] First frame received: {w}x{h}")
                    self._capture_ready.set()
            except Exception as e:
                log.error(f"[CAPTURE] Frame processing error: {e}")

        @capture.event
        def on_closed():
            log.debug("[CAPTURE] on_closed callback fired (window closed)")
            self._running.clear()
            self._capture_ready.set()
            if self._on_closed:
                self._on_closed()

        log.debug("[CAPTURE] Starting capture (free-threaded)")
        self._capture_control = capture.start_free_threaded()

        self._fps_thread = threading.Thread(target=self._fps_loop, daemon=True)
        self._fps_thread.start()

    def wait_for_first_frame(self, timeout: float = 5.0) -> bool:
        """Wait until the first frame is captured or an error occurs."""
        return self._capture_ready.wait(timeout=timeout)

    def _fps_loop(self):
        """Emit frames at constant FPS from the latest captured frame."""
        next_frame_time = time.perf_counter()
        while self._running.is_set():
            now = time.perf_counter()
            if now >= next_frame_time:
                with self._last_frame_lock:
                    frame = self._last_frame
                if frame is not None:
                    while next_frame_time <= now:
                        try:
                            self._frame_queue.put_nowait(frame)
                        except queue.Full:
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            self._frame_queue.put_nowait(frame)
                        next_frame_time += self._frame_interval
                else:
                    next_frame_time += self._frame_interval

            sleep_time = next_frame_time - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)

    def update_region(self, region: tuple[int, int, int, int]):
        """No-op - kept for API compatibility."""
        pass

    def get_frame(self, timeout: float = 0.1) -> np.ndarray | None:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def error(self) -> str | None:
        return self._capture_error

    def stop(self):
        self._running.clear()
        if self._capture_control:
            self._capture_control.stop()
            self._capture_control = None
        if self._fps_thread:
            self._fps_thread.join(timeout=3)

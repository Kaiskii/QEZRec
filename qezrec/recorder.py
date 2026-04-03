import logging
import os
import re
import threading
import time
from datetime import datetime
from enum import Enum, auto

import cv2
import numpy as np

from .audio import AudioCapture
from .capture import ScreenCapture
from .config import RecordingConfig, detect_encoder
from .encoder import VideoEncoder, mux_audio_video
from .overlay import RecordingOverlay, show_overlay
from .window import find_windows_by_process, get_foreground_window

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    RECORDING = auto()


class Recorder:
    def __init__(self, config: RecordingConfig):
        self._config = config
        self._state = State.IDLE
        self._lock = threading.Lock()
        self._running = threading.Event()

        self._capture: ScreenCapture | None = None
        self._encoder: VideoEncoder | None = None
        self._audio: AudioCapture | None = None

        self._encode_thread: threading.Thread | None = None
        self._overlay = RecordingOverlay()
        self._start_time: float = 0
        self._locked_width: int = 0
        self._locked_height: int = 0
        self._frame_count: int = 0
        self._crashed: bool = False

    @property
    def state(self) -> State:
        return self._state

    def toggle(self):
        with self._lock:
            if self._state == State.IDLE:
                self._start_recording()
            else:
                self._stop_recording()

    def _on_window_closed(self):
        """Called by the capture when the target window is closed."""
        log.info("Target window closed. Auto-stopping recording.")
        threading.Thread(target=self.toggle, daemon=True).start()

    def _start_recording(self):
        window = get_foreground_window()
        if window is None:
            log.error("No active window found.")
            return

        # Find the main window for this process (title may differ from foreground)
        process_windows = find_windows_by_process(window.process_name)
        target = process_windows[0] if process_windows else window

        if not target.title:
            log.error("Window has no title - cannot capture.")
            return

        # Output path
        os.makedirs(self._config.output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\-.]', '_', window.process_name.replace('.exe', ''))
        base_name = f"{safe_name}_{timestamp}"

        if self._config.audio:
            video_path = os.path.join(self._config.output_dir, f"{base_name}_temp.mp4")
            audio_path = os.path.join(self._config.output_dir, f"{base_name}_temp.wav")
            self._final_path = os.path.join(self._config.output_dir, f"{base_name}.mp4")
            self._temp_video_path = video_path
            self._temp_audio_path = audio_path
        else:
            video_path = os.path.join(self._config.output_dir, f"{base_name}.mp4")
            self._final_path = video_path
            self._temp_video_path = None
            self._temp_audio_path = None

        # Detect encoder
        encoder = detect_encoder(self._config.encoder)

        # Start window capture (captures the window directly by its title)
        log.info(f"Capturing window: '{target.title}' (process: {window.process_name})")
        self._capture = ScreenCapture(target.title, self._config.fps, on_closed=self._on_window_closed)
        self._capture.start()

        # Wait for the first frame to determine dimensions
        self._running.set()
        self._capture.wait_for_first_frame(timeout=5.0)

        if self._capture.error:
            log.error(f"Capture failed: {self._capture.error}")
            self._capture.stop()
            self._capture = None
            self._running.clear()
            return

        first_frame = self._capture.get_frame(timeout=1.0)
        if first_frame is None:
            log.error("Failed to capture first frame from window (timed out).")
            self._capture.stop()
            self._capture = None
            self._running.clear()
            return

        height, width = first_frame.shape[:2]
        self._locked_width = width & ~1
        self._locked_height = height & ~1
        log.info(f"Recording: {window.process_name} - '{target.title}' ({self._locked_width}x{self._locked_height}) encoder={encoder}")

        # Start encoder with actual frame dimensions
        self._encoder = VideoEncoder(video_path, self._locked_width, self._locked_height, self._config.fps, encoder)
        self._encoder.start()

        # Write the first frame
        self._frame_count = 0
        if self._locked_width != width or self._locked_height != height:
            first_frame = cv2.resize(first_frame, (self._locked_width, self._locked_height), interpolation=cv2.INTER_AREA)
        self._encoder.write_frame(first_frame)
        self._frame_count += 1

        # Start encode thread
        self._encode_thread = threading.Thread(target=self._encode_loop, daemon=True)
        self._encode_thread.start()

        # Start audio if enabled - capture from the target process
        if self._config.audio:
            self._audio = AudioCapture()
            self._audio.start(audio_path, pid=window.pid)

        self._start_time = time.perf_counter()
        self._state = State.RECORDING
        print(f"\r[REC] Recording {window.process_name} - '{target.title}' | Press Ctrl+Shift+R to stop")
        self._overlay.show(window.process_name.replace(".exe", ""))

    def _encode_loop(self):
        try:
            while self._running.is_set():
                capture = self._capture
                if capture is None:
                    break
                frame = capture.get_frame(timeout=0.1)
                if frame is None:
                    continue
                h, w = frame.shape[:2]
                if w != self._locked_width or h != self._locked_height:
                    frame = cv2.resize(frame, (self._locked_width, self._locked_height), interpolation=cv2.INTER_AREA)
                self._encoder.write_frame(frame)
                self._frame_count += 1
        except Exception as e:
            log.error(f"Encode loop crashed: {e}")
            self._crashed = True
            threading.Thread(target=self.cancel, daemon=True).start()

    def _stop_recording(self):
        elapsed = time.perf_counter() - self._start_time
        self._running.clear()

        print(f"\r[STOP] Stopping recording... ({elapsed:.1f}s, {self._frame_count} frames)")
        self._overlay.dismiss()
        show_overlay(f"Saved  {elapsed:.1f}s", duration=2.0, color="#38a169")

        # Wait for encode thread to exit
        if self._encode_thread:
            self._encode_thread.join(timeout=3)

        # Now safe to tear down capture - no threads are using it
        if self._capture:
            self._capture.stop()
            self._capture = None

        # Finalize encoder (closes FFmpeg stdin, waits for it to write trailer)
        err = None
        if self._encoder:
            err = self._encoder.stop()
            self._encoder = None

        if err:
            log.error(f"Encoder error: {err[:200]}")

        # Stop audio
        needs_mux = False
        if self._audio:
            self._audio.stop()
            self._audio = None
            needs_mux = bool(self._temp_video_path and self._temp_audio_path)

        self._state = State.IDLE

        # Mux audio+video in background so the tool is immediately ready for the next recording
        if needs_mux:
            print(f"\r[MUX] Muxing audio+video in background...")
            threading.Thread(
                target=self._background_mux,
                args=(self._temp_video_path, self._temp_audio_path, self._final_path),
                daemon=True,
            ).start()
        else:
            print(f"\r[DONE] Saved: {self._final_path}")

    def _background_mux(self, video_path: str, audio_path: str, output_path: str):
        mux_err = mux_audio_video(video_path, audio_path, output_path)
        if mux_err:
            log.error(f"Audio mux failed: {mux_err}")
            print(f"\r[ERROR] Mux failed, raw video kept at: {video_path}")
        else:
            for p in [video_path, audio_path]:
                try:
                    os.remove(p)
                except OSError:
                    pass
            print(f"\r[DONE] Saved: {output_path}")

    def cancel(self):
        """Force-cancel recording and discard the output file."""
        with self._lock:
            if self._state != State.RECORDING:
                print("\r[INFO] Not recording, nothing to cancel.")
                return
            print("\r[CANCEL] Aborting recording, discarding file...")
            self._running.clear()

            # Kill threads
            if self._encode_thread:
                self._encode_thread.join(timeout=3)

            # Tear down capture
            if self._capture:
                self._capture.stop()
                self._capture = None

            # Kill encoder (don't care about errors)
            if self._encoder:
                self._encoder.stop()
                self._encoder = None

            # Kill audio
            if self._audio:
                self._audio.stop()
                self._audio = None

            # Delete output files
            for path in [self._final_path,
                         getattr(self, "_temp_video_path", None),
                         getattr(self, "_temp_audio_path", None)]:
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

            self._state = State.IDLE
            print("\r[CANCEL] Recording discarded.")
            self._overlay.dismiss()
            show_overlay("Recording cancelled", duration=2.0, color="#718096")

    def cleanup(self):
        if self._state == State.RECORDING:
            self._running.clear()
            if self._capture:
                self._capture.stop()
            if self._encoder:
                self._encoder.stop()
            if self._audio:
                self._audio.stop()

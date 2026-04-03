import subprocess

import numpy as np

from .config import ENCODER_FLAGS, find_ffmpeg


class VideoEncoder:
    """Manages an FFmpeg subprocess for encoding raw video frames to MP4."""

    def __init__(self, output_path: str, width: int, height: int, fps: int, encoder: str):
        self._output_path = output_path
        self._width = width
        self._height = height
        self._fps = fps
        self._encoder = encoder
        self._proc: subprocess.Popen | None = None

    def _build_cmd(self) -> list[str]:
        ffmpeg = find_ffmpeg()
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self._width}x{self._height}",
            "-r", str(self._fps),
            "-i", "pipe:0",
            "-c:v", self._encoder,
            "-pix_fmt", "yuv420p",
        ]
        cmd.extend(ENCODER_FLAGS.get(self._encoder, []))
        cmd.extend(["-movflags", "+faststart", self._output_path])
        return cmd

    def start(self):
        cmd = self._build_cmd()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def write_frame(self, frame: np.ndarray):
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                pass

    def stop(self) -> str | None:
        """Stop encoder and return any error message."""
        if not self._proc:
            return None
        if self._proc.stdin:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
            return "FFmpeg timed out and was killed"
        rc = self._proc.returncode
        self._proc = None
        if rc != 0:
            return f"FFmpeg exited with code {rc}"
        return None

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


def mux_audio_video(video_path: str, audio_path: str, output_path: str) -> str | None:
    """Mux separate video and audio files into a single MP4. Returns error or None."""
    ffmpeg = find_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-y",
         "-i", video_path,
         "-i", audio_path,
         "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k",
         "-shortest",
         output_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=120,
    )
    if result.returncode != 0:
        return f"FFmpeg mux exited with code {result.returncode}"
    return None

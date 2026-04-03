import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Videos", "QEZRec")


@dataclass
class RecordingConfig:
    fps: int = 60
    output_dir: str = DEFAULT_OUTPUT_DIR
    encoder: str = "auto"
    audio: bool = True


ENCODER_PRIORITY = ["h264_nvenc", "h264_amf", "libx264"]

ENCODER_FLAGS = {
    "h264_nvenc": ["-preset", "p4", "-tune", "ll", "-rc", "vbr", "-cq", "23", "-b:v", "0"],
    "h264_amf": ["-quality", "speed", "-rc", "vbr_latency", "-qp_i", "23", "-qp_p", "23"],
    "libx264": ["-preset", "veryfast", "-crf", "23"],
}


def find_ffmpeg() -> str:
    # 1. Check bundled inside PyInstaller bundle
    import sys
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled

    # 2. System PATH
    path = shutil.which("ffmpeg")
    if path:
        return path

    # 3. Common install locations on Windows
    for candidate in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.isfile(candidate):
            return candidate

    raise FileNotFoundError("FFmpeg not found. Install it and add to PATH.")


@lru_cache(maxsize=1)
def _get_available_encoders() -> set[str]:
    ffmpeg = find_ffmpeg()
    try:
        result = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {line.split()[1] for line in result.stdout.splitlines() if line.startswith(" V")}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def detect_encoder(preference: str = "auto") -> str:
    if preference != "auto":
        return preference
    available = _get_available_encoders()
    for enc in ENCODER_PRIORITY:
        if enc in available:
            return enc
    raise RuntimeError("No H.264 encoder found. Install FFmpeg with libx264 at minimum.")

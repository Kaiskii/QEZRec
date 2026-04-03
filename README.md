# QEZRec

Quick & Ez Recording Tool. Because Game Bar doesn't always work, and opening OBS just to record something is a hassle.

## Features

- **Window capture** - records the target window directly, not a screen region. Alt-tab freely.
- **Per-process audio** - captures audio only from the recorded application via WASAPI Process Loopback.
- **Hardware-accelerated encoding** - uses NVENC (NVIDIA), AMF (AMD), or falls back to libx264.

## Requirements

- Windows 10 2004+ (Build 19041+)
- Python 3.10+ (for running from source)
- [FFmpeg](https://ffmpeg.org/download.html) in PATH (or bundled with the .exe)

## Install

**From source:**
```bash
pip install -r requirements.txt
python -m qezrec
```

**Standalone .exe:** Download from [Releases](../../releases)

## Usage

```
python -m qezrec [options]
```

| Option | Description |
|---|---|
| `--no-audio` | Disable per-process audio capture |
| `--fps 60` | Recording framerate (default: 60) |
| `--encoder auto` | Video encoder: `auto`, `h264_nvenc`, `h264_amf`, `libx264` |
| `--output-dir PATH` | Output directory (default: `~/Videos/QEZRec`) |
| `--no-tray` | Run in CLI mode without system tray |
| `--verbose` | Debug logging |

## Hotkeys

| Shortcut | Action |
|---|---|
| **Ctrl+Shift+R** | Start / stop recording |
| **Ctrl+Shift+Q** | Cancel recording (discard file) |
| **Ctrl+C** | Exit (CLI mode) |

## How it works

1. Press **Ctrl+Shift+R** with the target window focused.
2. QEZRec identifies the window by process name and starts capturing using the [Windows Graphics Capture API](https://learn.microsoft.com/en-us/windows/uwp/audio-video-camera/screen-capture).
3. Video frames are piped to FFmpeg for hardware-accelerated H.264 encoding.
4. Audio is captured from the target process only via [WASAPI Process Loopback](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-capture-activation), then muxed into the final MP4. Use `--no-audio` to disable.
5. Press **Ctrl+Shift+R** again to stop. The recording is saved to `~/Videos/QEZRec/`.

## Building the .exe

```bash
pip install pyinstaller

# Lightweight (~80MB) - users need FFmpeg in PATH
python build.py

# Full bundle (~130MB) - includes FFmpeg
python build.py --bundle-ffmpeg
```

## License

MIT

The bundled .exe release includes [FFmpeg](https://ffmpeg.org/) which is licensed under the [GNU General Public License v2+](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html). FFmpeg source code is available at https://github.com/FFmpeg/FFmpeg.

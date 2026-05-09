import argparse
import atexit
import ctypes
import logging
import os
import signal
import sys
import time

# DPI awareness MUST be set before any GUI/DXcam calls
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from .config import DEFAULT_OUTPUT_DIR, RecordingConfig, detect_encoder, find_ffmpeg
from .hotkey import HotkeyListener
from .recorder import Recorder, State


def validate_environment():
    try:
        ffmpeg = find_ffmpeg()
        logging.info(f"FFmpeg: {ffmpeg}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        encoder = detect_encoder("auto")
        logging.info(f"Encoder: {encoder}")
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        import windows_capture
    except ImportError:
        print("Error: windows-capture not installed. Run: pip install windows-capture")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="qezrec",
        description="QEZRec - Quick and Ez window recording",
    )
    parser.add_argument("--fps", type=int, default=60, help="Recording framerate (default: 60)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, metavar="PATH", help="Output directory (default: ~/Videos/QEZRec)")
    parser.add_argument("--encoder", default="auto", metavar="", help="Video encoder (auto/h264_nvenc/h264_amf/libx264)")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio capture")
    parser.add_argument("--no-tray", action="store_true", help="Run in CLI mode without system tray icon")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--set-keybinds", action="store_true", help="Interactively configure keybinds and save to ~/.qez")
    args = parser.parse_args()

    if args.fps < 1:
        parser.error("--fps must be at least 1")

    # Set up logging - console + log file
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = "%(asctime)s %(levelname)s %(message)s"
    log_datefmt = "%H:%M:%S"

    log_dir = os.path.join(args.output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    from datetime import datetime
    log_file = os.path.join(log_dir, f"qezrec_{datetime.now().strftime('%Y%m%d')}.log")

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=log_datefmt,
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    if args.set_keybinds:
        from .keybind_setup import run_keybind_setup_cli
        run_keybind_setup_cli()
        sys.exit(0)

    validate_environment()

    from .overlay import warm_up as warm_up_overlay
    warm_up_overlay()

    encoder_name = detect_encoder(args.encoder)

    config = RecordingConfig(
        fps=args.fps,
        output_dir=args.output_dir,
        encoder=encoder_name,
        audio=not args.no_audio,
    )

    recorder = Recorder(config)
    atexit.register(recorder.cleanup)

    from .settings import load_keybinds
    from .keybind_setup import combo_to_display
    keybinds = load_keybinds()

    hotkey = HotkeyListener(
        on_toggle=recorder.toggle,
        on_cancel=recorder.cancel,
        on_pause=recorder.toggle_pause,
        keybinds=keybinds,
        is_recording=lambda: recorder.state == State.RECORDING,
    )
    hotkey.start()

    audio_str = " + audio" if config.audio else ""
    print(f"QEZRec ready | {config.fps}fps, {encoder_name}{audio_str}")
    print(f"  {combo_to_display(*keybinds['toggle']):20s}  Start/stop recording")
    print(f"  {combo_to_display(*keybinds['cancel']):20s}  Cancel recording (discard file)")
    print(f"  {combo_to_display(*keybinds['pause']):20s}  Pause/resume recording")

    if args.no_tray:
        print(f"  Ctrl+C        Exit")

        def on_sigint(sig, frame):
            print("\nShutting down...")
            recorder.cleanup()
            hotkey.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, on_sigint)

        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            on_sigint(None, None)
    else:
        print(f"  Running in system tray...")
        from .tray import TrayApp
        tray = TrayApp(recorder, hotkey, config)
        tray.run()  # Blocks until Quit


if __name__ == "__main__":
    main()

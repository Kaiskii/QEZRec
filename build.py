"""Build QEZRec into a single .exe using PyInstaller.

Usage:
    python build.py              Build without bundled FFmpeg (users need FFmpeg in PATH)
    python build.py --bundle-ffmpeg   Bundle ffmpeg.exe into the .exe (~130MB total)
"""
import argparse
import os
import shutil
import subprocess
import sys


def find_ffmpeg() -> str | None:
    path = shutil.which("ffmpeg")
    if path:
        return path
    for candidate in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="Build QEZRec .exe")
    parser.add_argument("--bundle-ffmpeg", action="store_true",
                        help="Bundle ffmpeg.exe into the output (adds ~120MB)")
    args = parser.parse_args()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "QEZRec",
        "--icon", "assets/qezico.ico",
        "--noconsole",
        "--hidden-import", "comtypes.stream",
        "--hidden-import", "pyaudiowpatch",
        "--collect-all", "windows_capture",
        "--collect-all", "pyaudiowpatch",
        "--add-data", "assets/qezico.png;.",
    ]

    if args.bundle_ffmpeg:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            print("Error: FFmpeg not found. Install it first or add to PATH.")
            sys.exit(1)
        print(f"Bundling FFmpeg from: {ffmpeg}")
        cmd.extend(["--add-binary", f"{ffmpeg};."])

    cmd.append("run.py")

    subprocess.run(cmd, check=True)

    exe_path = "dist/QEZRec.exe"
    size_mb = os.path.getsize(exe_path) / (1024 * 1024)

    import hashlib
    sha256 = hashlib.sha256(open(exe_path, "rb").read()).hexdigest()

    print(f"\nBuild complete: {exe_path} ({size_mb:.0f}MB)")
    print(f"SHA256: {sha256}")
    if not args.bundle_ffmpeg:
        print("Note: FFmpeg not bundled. Users need FFmpeg in PATH.")

    # Write checksum file
    with open("dist/QEZRec.exe.sha256", "w") as f:
        f.write(f"{sha256}  QEZRec.exe\n")


if __name__ == "__main__":
    main()

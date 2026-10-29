"""One requested screenshot of the main Mac display, with temporary-file cleanup."""

import platform
import subprocess
import tempfile
from pathlib import Path
from threading import Lock

_capture_lock = Lock()


def capture_main_display():
    if platform.system() != "Darwin":
        raise RuntimeError("Native screenshots require macOS.")
    if not _capture_lock.acquire(blocking=False):
        raise RuntimeError("A screenshot is already being captured. Try again shortly.")
    try:
        with tempfile.TemporaryDirectory(prefix="aura-screen-") as directory:
            image = Path(directory) / "capture.jpg"
            capture = subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-m", "-t", "jpg", str(image)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
                check=False,
            )
            if capture.returncode or not image.is_file():
                raise RuntimeError(
                    "Could not capture the main display. Allow Aura in macOS Screen Recording settings, then restart Aura."
                )
            resize = subprocess.run(
                ["/usr/bin/sips", "-Z", "2560", str(image)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
                check=False,
            )
            if resize.returncode or not 0 < image.stat().st_size <= 16 * 1024 * 1024:
                raise RuntimeError("Could not prepare the screenshot. Retry capture.")
            return image.read_bytes()
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "Screenshot capture timed out. Check Aura's capture permission and retry."
        ) from error
    except OSError as error:
        raise RuntimeError(
            "The Mac screenshot tools are unavailable. Restart Aura and retry."
        ) from error
    finally:
        _capture_lock.release()

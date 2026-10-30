"""Build the small system-audio helper using Apple's local Swift toolchain."""

import platform
import shutil
import subprocess
from pathlib import Path


def build_audio_helper():
    root = Path(__file__).resolve().parent.parent
    compiler = shutil.which("swiftc")
    if platform.system() != "Darwin" or compiler is None:
        raise RuntimeError(
            "Building native Mac audio requires macOS and the Xcode Command Line Tools (swiftc)."
        )
    output = root / "build" / "AuraSystemAudio"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            compiler,
            "-O",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-module-cache-path",
            str(root / "build" / "SwiftModuleCache"),
            "-target",
            f"{platform.machine()}-apple-macosx13.0",
            "-framework",
            "ScreenCaptureKit",
            "-framework",
            "CoreMedia",
            "-framework",
            "AudioToolbox",
            str(root / "native" / "SystemAudio.swift"),
            "-o",
            str(output),
        ],
        check=True,
    )
    return output


if __name__ == "__main__":
    print(build_audio_helper())

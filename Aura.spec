# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for packaging Aura as a macOS .app bundle.

Build:   pyinstaller --noconfirm Aura.spec
Output:  dist/Aura.app
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules
import runpy
from pathlib import Path

web_root = Path(SPECPATH) / "web"
datas = [
    (str(path), str(Path("web") / path.parent.relative_to(web_root)))
    for path in web_root.rglob("*")
    if path.is_file() and path.name != "dev.js" and not path.name.startswith(".")
] + [
    ("ai_providers.example.json", "."),
    (".env.example", "."),
]
audio_builder = runpy.run_path(str(Path(SPECPATH) / "native" / "build_audio.py"))
binaries = [(str(audio_builder["build_audio_helper"]()), "native")]
hiddenimports = []

# pywebview (Cocoa/WKWebView backend) + pyobjc frameworks it drives.
for pkg in ("webview", "deepgram", "objc", "Foundation", "AppKit", "WebKit", "Quartz"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# uvicorn[standard] pulls protocol/loop implementations lazily.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.loops.uvloop",
    "uvicorn.loops.asyncio",
    "websockets.legacy",
    "anyio._backends._asyncio",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aura",
    console=False,          # windowed / GUI app
    disable_windowed_traceback=False,
    argv_emulation=True,    # macOS: forward file-open/args to the app
    target_arch=None,
    codesign_identity=None, # ad-hoc signed after build
    entitlements_file="Aura.entitlements",
    icon="build/Aura.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Aura",
)

app = BUNDLE(
    coll,
    name="Aura.app",
    icon="build/Aura.icns",
    bundle_identifier="com.bhavit.aura",
    info_plist={
        "CFBundleName": "Aura",
        "CFBundleDisplayName": "Aura",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        # TCC usage strings — required for the OS mic prompt to appear at all.
        "NSMicrophoneUsageDescription":
            "Aura uses the microphone to transcribe interview audio in real time.",
        "NSAudioCaptureUsageDescription":
            "Aura transcribes Mac playback audio from apps using your speakers or headphones.",
        "NSScreenCaptureUsageDescription":
            "Aura captures system playback audio for transcription and screenshots only when requested.",
        "NSCameraUsageDescription":
            "Aura may access the camera for video capture during interviews.",
        # Not a background agent — show a normal app so the window activates and
        # the mic prompt is presented reliably.
        "LSUIElement": False,
        "LSMinimumSystemVersion": "11.0",
    },
)

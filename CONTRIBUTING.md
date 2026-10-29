# Contributing to Aura on macOS

This repository's default branch is `macos`. Its window management uses
Cocoa/AppKit and pywebview's WKWebView backend. Start with the
[README](README.md) for installation and provider setup, then use
[DESKTOP-SYNC.md](DESKTOP-SYNC.md) to exercise the shared Chrome session.
For direct desktop playback capture, see [SYSTEM-AUDIO.md](SYSTEM-AUDIO.md).

## Development setup

Use macOS, Python 3.10+ and Node.js with the built-in `node --test` runner.
The packaged build was validated with Python 3.12 on Apple Silicon. Install
runtime dependencies and copy configuration templates as shown in the README.
Run source commands from the repository root:

```sh
.venv/bin/python main.py
```

Native playback requires macOS 13+ and a helper compiled with Xcode Command
Line Tools. Build it with `.venv/bin/python native/build_audio.py` before a
source run; packaging builds it automatically. No compiler is needed by users
of the packaged app.

To enable development logging and disable capture protection, set
`DEV_MODE=true` in the local `.env` and restart. The `.env` setting takes
precedence over the same setting in the shell environment.

Source configuration lives in the project root; packaged configuration lives
in `~/Library/Application Support/Aura/`. Never commit `.env`,
`ai_providers.json`, `profile.json`, `web/js/dev.js`, credentials, resumes or
captured conversations. Share only redacted logs and example configuration.

## Project structure

| Path | Responsibility |
| --- | --- |
| `main.py` | FastAPI/backend lifecycle, native window and command monitor |
| `window_manager.py` | AppKit window appearance, full-screen collection behavior and native Option shortcuts |
| `api/websocket.py` | Browser session connection and separate desktop display connection |
| `api/session_manager.py` | Audio/session lifecycle, question processing and command routing |
| `api/config_api.py` | Setup/configuration, readiness and desktop-control endpoints |
| `core/shortcuts.py` | Allowed session commands and labels |
| `core/paths.py` | Source and packaged resource/data paths |
| `services/desktop_sync.py` | In-memory conversation/state snapshots for desktop viewers |
| `services/` | AI providers, context, transcription and vision processing |
| `web/js/audio_handler.js`, `audio_processor.js` | Browser media capture and 48 kHz audio mixing |
| `web/desktop.html`, `web/js/desktop*.js`, `web/css/desktop.css` | Floating conversation view and controls |
| `web/js/session-shortcuts.js` | Chrome command execution, deduplication, expiry and acknowledgements |
| `tests/` | Python integration tests and Node behavior tests |
| `Aura.spec`, `Aura.entitlements` | macOS app packaging |
| `native/`, `services/system_audio.py`, `api/system_audio.py` | Native playback helper and bounded local audio transport |
| `services/screen_capture.py`, `api/screen_capture.py` | Requested native main-display screenshots with temporary-file cleanup |

When adding a session control, update the command allowlist, API validation,
Chrome action map and desktop interface together. Preserve Chrome's ownership
of capture; the viewer must not replace its audio WebSocket. Keep the shortcut
table and user-facing labels consistent with the actual Option-key bindings.

## Validation

Run the relevant checks for your change. The current regression suite has 47
Python tests and 94 Node tests and does not require real API credentials.
The compiled-helper PCM test is skipped if the helper has not been built:

```sh
.venv/bin/python -m unittest discover -s tests -v
npm test
git diff --check
```

The tests mock AI, transcription, media and native-window boundaries. For
changes to session sync, capture, window behavior or shortcuts, also check on
the target Mac:

- Chrome sharing with **Share tab audio** selected; spoken browser audio appears
  in the transcript while Aura's microphone input is muted.
- Direct desktop capture with Aura's mic muted: spoken app audio transcribes
  through speakers and headphones, including after changing macOS's output.
  Check native permission denial/recovery, Pause and End cleanup. Native mode
  must work without an Aura Chrome tab or DevTools.
- In direct desktop mode, Option+F enables vision, Option+S queues the main
  display and Option+A analyses it. Check permission denial/recovery and confirm
  no screenshot is captured until requested.
- Desktop entry stays disabled until the browser, shared audio and transcription
  are connected, and reports the missing prerequisite.
- The desktop window remains visible above full-screen Chrome and incoming
  answers do not move keyboard focus. Test the actual Option shortcuts after
  granting Accessibility permission.
- Mute/unmute, pause/resume, model selection, vision capture/analysis/clear,
  typed questions and Reset affect the same browser session.
- Earlier questions remain in the continuous conversation; scrolling up holds
  the reading position, and reconnecting restores the full conversation.
- End session stops Chrome's capture and transcription, disables session
  controls and keeps the completed conversation visible. Starting another
  session clears the old conversation.
- Opacity, click-through, hide/show, movement and scrolling operate on the
  desktop window. Option+X and Option+Z restore clicking and visibility.

`npm test` runs both this fork's tests and the upstream Markdown/math tests.
The current automated suite and bundle checks passed. The real OS/media and
full-screen checks above remain manual validation items; do not report them as
passed based only on mocks. Documentation-only changes need link/content checks
and `git diff --check`, with no app rebuild unless bundled resources change.

## Build the macOS app

Install PyInstaller and Apple's Xcode Command Line Tools. `Aura.spec` compiles
the native audio helper using Swift and expects
`build/Aura.icns`; generate it from the tracked 1024×1024 `logo.png` using macOS
tools before building from a clean checkout:

```sh
.venv/bin/python -m pip install pyinstaller
mkdir -p build/Aura.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" logo.png --out "build/Aura.iconset/icon_${size}x${size}.png" >/dev/null
  double_size=$((size * 2))
  sips -z "$double_size" "$double_size" logo.png --out "build/Aura.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/Aura.iconset -o build/Aura.icns
.venv/bin/pyinstaller --noconfirm Aura.spec
codesign --verify --deep --strict dist/Aura.app
```

The output is `dist/Aura.app`, built for the current machine's architecture and
ad-hoc signed. This command does not produce a notarized distribution release.
The bundle includes web resources and example configuration; writable personal
configuration stays outside it. Check that no local credentials or profile data
are present before sharing a build. `build/` and `dist/` are ignored by Git.

After installing an updated app, fully quit and reopen Aura and hard-refresh its
Chrome page with Command+Shift+R. Preserve the existing runtime data directory
when replacing the bundle.

## Pull requests and reports

1. Create a focused branch from the current `macos` branch (or use a fork when
   you do not have push access).
2. Keep Python changes consistent with the surrounding code; use vanilla
   JavaScript/CSS, snake_case for Python and camelCase for JavaScript.
3. Add meaningful regression coverage for behavior changes and update the
   README, setup guide and unreleased changelog where relevant.
4. Run appropriate checks, push the feature branch and open a PR targeting
   `macos`. Describe the resulting behavior, configuration/migration steps,
   checks performed and any manual checks still outstanding.

For bugs, include reproduction steps, expected/actual behavior, macOS version,
source versus packaged run, browser version and redacted logs. For feature
requests, describe the use case and expected interaction. Avoid attaching
personal profiles, API keys or unredacted transcripts.

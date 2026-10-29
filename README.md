# Aura — macOS

This is the macOS working fork of [Rkcr7/Aura-AI](https://github.com/Rkcr7/Aura-AI).
See [fork maintenance](UPSTREAM.md) for upstream synchronization and migration
details, and [the upstream README](README-UPSTREAM.md) for Windows documentation.

Aura transcribes shared audio with Deepgram and generates answers using an
OpenAI-compatible AI provider. It also analyses screenshots on request. This
branch uses a native macOS desktop window with a local FastAPI backend.

Desktop Aura captures Mac playback directly with a native ScreenCaptureKit
helper on macOS 13+. It receives app audio independently of the WebView's
screen-sharing support, while you keep your normal speaker/headphone output.
No Aura tab or DevTools is needed in Chrome for this mode. The optional
Chrome-owned session and synced desktop view remain available too.

## Start here

- [Direct Mac playback setup and verification](SYSTEM-AUDIO.md)
- [Optional Chrome and desktop sync, controls and troubleshooting](DESKTOP-SYNC.md)
- [Development, tests and macOS packaging](CONTRIBUTING.md)
- [Changes on this branch](CHANGELOG.md)

### Run from source

Use macOS and Python 3.10 or newer; the current build was validated with Python
3.12. This fork is public; credentials and personal profiles stay local.

```sh
git clone --branch macos https://github.com/ChinmayaThakral/Aura-AI.git
cd Aura-AI
```

For a feature still under review, check out that PR's branch before installing
and running. Then run:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python native/build_audio.py
cp -n .env.example .env
cp -n ai_providers.example.json ai_providers.json
.venv/bin/python main.py
```

The source commands above use the project root as the working directory.
The native helper build requires Apple's Xcode Command Line Tools. Packaged
apps include the helper and do not need the compiler installed.

### Use a packaged app

Open `Aura.app` and keep it running: the desktop app also hosts the local
backend used by Chrome. Configure providers and the Deepgram key through Aura's
setup screen. After an app update, fully quit and reopen Aura, then hard-refresh
its Chrome page with **Command+Shift+R**.

## Configure transcription and AI

1. Set a Deepgram key in **Advanced Config**, save it, and run Device Setup to
   verify it. The key can also be set as `DEEPGRAM_API_KEY` in the local `.env`.
   A Deepgram account/key can be managed in the
   [Deepgram console](https://console.deepgram.com/).
2. Configure an OpenAI-compatible provider in **Advanced Config**, then select
   its text model in **AI Setup**. For screenshots, also select a vision provider
   and a model that accepts images.
3. The included [provider template](ai_providers.example.json) uses Quotio at
   `http://127.0.0.1:8317/v1`. If using it, keep Quotio running and enter the
   proxy key, port and model names from your own Quotio setup. The template's
   model names are examples; they must be available in that setup.
4. Complete your profile, resume/background, role and job description, then
   proceed to Device Setup. Fields loaded from a personal profile remain editable.

Source runs read `.env`, `ai_providers.json` and optional `profile.json` from the
project root. Packaged runs use `~/Library/Application Support/Aura/` instead.
These files are ignored by Git and are not shipped in the app bundle. Source
and packaged runs therefore have separate configuration unless you copy it.

Saving or externally editing the Deepgram key applies to verification and new
transcription connections. An existing connection keeps its key until the
session ends. Other environment-setting changes require an app restart.

## Direct desktop audio

Complete setup and start the session directly in Aura. Allow its macOS capture
permission and check **Mac playback connected**. With Aura's microphone muted,
play spoken audio from Chrome through headphones and confirm its transcript.
Repeat with the output devices you use; Aura does not change playback routing.
See [SYSTEM-AUDIO.md](SYSTEM-AUDIO.md) for permission recovery and verification.

**Mute mic** leaves app playback active; **Pause audio** pauses transcription
input. **End Interview** stops the native capture. If microphone permission is
missing, playback capture can still run. Screenshot capture/analysis remains
an explicit action and may request screen-sharing permission separately.

In desktop mode, **Option+F → Option+S → Option+A** enables vision, captures the
main Mac display and analyses the queue. Screen Recording permission is required;
no browser sharing picker is used. The native window also has a small shortcut
reference along its bottom edge. Chrome mode continues to capture the shared tab.

## Optional Chrome capture with the floating desktop window

1. Keep Aura open. In Chrome, open `http://127.0.0.1:8002`, or the actual local
   port printed by Aura if 8002 was busy. Use the same backend as the desktop app.
2. Complete setup in Chrome and start a session. In the sharing picker, choose
   the tab containing the audio and enable **Share tab audio**. Allow the
   requested microphone/capture permissions.
3. In desktop Aura, wait for the readiness check, then click **Show Chrome
   session in this window**. It requires an active Chrome session, live tab audio
   and connected speech transcription.
4. Check **Synced with Chrome** and test with spoken audio. Keep both the desktop
   app and Aura's Chrome tab open. Chrome can then display the shared tab full-screen.

All questions and answers appear in one chronological, scrollable conversation.
It follows new output when you are at the bottom and preserves your position
when you scroll up. The desktop toolbar includes mic mute, audio pause, Reset,
End session, model and vision controls, screenshot queue controls and a typed
question box. The **Window** menu contains opacity, click-through, hide and
movement controls. A small Option-key reference stays at the bottom.

The overlay starts with **click-through ON** when the global Option shortcut
is available, so clicks pass to the Chrome window underneath. Press **Option+X**
to switch click-through OFF and use Aura's controls, then press it again to
resume passing clicks through. The status line shows the actual native state.
Enable Aura in macOS **Privacy & Security → Accessibility** and restart it for
global shortcuts. Without the recovery shortcut, the overlay stays interactive
and explains the missing permission rather than trapping its controls.

**Mute mic** affects only the microphone input sent to Aura; it does not mute
your microphone in a call. Shared-tab audio continues. **Pause audio** pauses
audio processing for Aura. **End session** stops Chrome's capture and
transcription. **Reset** clears the conversation and model context without
ending capture. Conversation history stays in memory until reset, a new Chrome
session or backend shutdown; it remains visible after End session.

Screenshots are queued only when requested, with up to four images or the selected
provider's lower limit. The AI sees
them when you choose **Analyse**; it does not continuously analyse your screen.
See the [complete shortcut table](DESKTOP-SYNC.md#option-shortcuts) and
[troubleshooting guide](DESKTOP-SYNC.md#troubleshooting).

## Validation

The implementation passed 47 Python and 94 Node regression tests, Python/JS
syntax checks, scoped lint checks and macOS bundle/signature checks. Test commands
and a manual validation checklist are in [CONTRIBUTING.md](CONTRIBUTING.md#validation).
Physical global shortcuts, OS permission prompts, actual background capture and
placement above full-screen Chrome still need a check on the target Mac, as do
native capture permission and switching between physical output devices.

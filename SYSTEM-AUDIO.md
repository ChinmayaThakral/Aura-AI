# Direct Mac playback capture

On macOS 13 or newer, start the session in **desktop Aura** to capture app
playback with Apple's ScreenCaptureKit. Chrome does not need an Aura tab or
DevTools for this mode. Keep your normal speaker, wired headphone or Bluetooth
output selected in macOS; Aura does not install a virtual device or change
your playback routing.

## Start and verify

1. Quit and reopen the updated Aura app. Complete profile, AI and Device Setup
   in its own window, then press Start Interview.
2. Allow Aura's macOS capture request. If denied, enable Aura under **Privacy &
   Security → Screen & System Audio Recording**, then restart Aura and the
   session. The exact permission label varies with macOS version.
3. Look for **Mac playback connected** in the live window. This confirms capture
   startup; check the actual transcript to confirm the audio you need is arriving.
4. Mute Aura's microphone input, play a spoken video in Chrome through headphones
   and check its transcript. Repeat after switching your normal macOS output
   between the devices you plan to use. Other app playback is included too.
5. Keep desktop Aura open. Pause audio stops forwarding audio for transcription;
   End Interview stops the native capture and microphone streams.

Microphone mute affects only what Aura receives from your microphone, not the
microphone setting in a call. It leaves the system-playback stream active.
If microphone permission is unavailable, native playback can still work.
Capture permission errors appear in the audio status rather than silently
claiming system audio works. If a device change produces a format/disconnection
error, restart the session after checking the selected output and permissions.

Screenshots remain explicit: select a vision model, then press **Option+F** to
enable vision, **Option+S** to queue the main Mac display and **Option+A** to
analyse the queue. Desktop capture uses macOS's screenshot tools and Screen
Recording permission, without a browser picker. Images are resized to at most
2560 pixels on the longest edge; temporary capture files are removed before the
response returns. No images are sent to the AI until Analyse is requested.
The Chrome-owned audio/synced-view workflow remains available as an alternative:
see [DESKTOP-SYNC.md](DESKTOP-SYNC.md).

## Development and implementation

Packaged apps include the compiled helper. Source runs require Apple's Xcode
Command Line Tools and one build step after installing Python dependencies:

```sh
.venv/bin/python native/build_audio.py
```

`Aura.spec` also builds it automatically when packaging. Its build/cache files
stay under ignored `build/`; the installed app needs no Swift toolchain.

- `native/SystemAudio.swift` requests 48 kHz mono system audio, excludes Aura's
  own process and emits signed little-endian 16-bit PCM. No video output is
  registered and no audio recordings are written to disk.
- The local `/ws/system-audio` endpoint runs one capture helper at a time,
  validates its format and forwards PCM bytes to the desktop audio graph.
  Unrelated website origins cannot start capture. `/api/audio/system/status`
  reports OS/helper availability without starting recording.
- `native-system-audio.js` converts PCM to samples for the existing AudioWorklet.
  The worklet mixes native playback with the separately muted microphone and
  emits the same PCM format the Deepgram connection already expects. Its native
  queue is bounded to half a second and captured sound is never played back.
- POST `/api/screen/capture` performs one main-display screenshot for the desktop
  Capture control. It accepts local JSON requests, rejects unrelated origins and
  returns the resized JPEG with caching disabled. Browser sessions continue to
  capture their shared video track instead.
- Stopping, closing the audio connection or shutting down the backend terminates
  the helper. The helper also exits if its parent backend process disappears.
  Cancelling startup prevents a late permission response from restarting an
  ended session.

Apple documents the capture configuration and required consent in its
[ScreenCaptureKit sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
and [framework introduction](https://developer.apple.com/videos/play/wwdc2022/10156/).
Run the [regression suite](CONTRIBUTING.md#validation); the compiled helper's
`--self-test` validates PCM encoding without recording anything.

Live permission prompts, background transcription and physical output-device
switches still need checking on the target Mac. Automated tests mock capture;
a passing mock or a connected status alone does not prove an audible source
was transcribed.

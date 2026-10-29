# Chrome audio with desktop Aura

This is the optional browser-owned workflow. For native desktop playback
capture without an Aura Chrome tab, use [SYSTEM-AUDIO.md](SYSTEM-AUDIO.md).

See the [README](README.md) for installation and initial provider setup, and
[CONTRIBUTING.md](CONTRIBUTING.md) for tests and macOS packaging.

## Start the shared session

Keep the packaged Aura app open; it runs the local backend. After an update,
fully quit and reopen Aura, then hard-refresh its Chrome page with Command–Shift–R.

1. In Chrome, open `http://127.0.0.1:8002` (or the app's actual local port).
2. Complete Device Setup and start the Chrome session. In the sharing picker,
   select the interview tab and enable **Share tab audio**.
3. In desktop Aura, wait for the Chrome readiness check to pass. The
   **Show Chrome session in this window** button stays disabled until the
   browser session, tab audio and speech transcription are connected.
4. Click the button. A compact desktop window displays the same transcript
   and answers. Check that it says **Synced with Chrome**.
5. Test a spoken video and full-screen Chrome before the interview. Keep
   Aura's Chrome tab open in the background throughout the session.

The desktop display does not create another audio session or replace the
browser's connection. Native session shortcuts are sent to the browser that
owns the active session. Chrome acknowledges applied commands; the display
shows microphone, pause, vision and queue state as well as the last command's
result. An unavailable secondary model produces an error instead of a false
success. Reconnecting restores the full conversation for the selected session.

## Conversation and controls

All questions and answers appear in one chronological, scrollable conversation,
with no **Previous questions** section to open. New answers follow automatically
while you are at the bottom; scrolling up keeps your reading position. Reset
clears the conversation. Ending the session keeps it visible until you start
another Chrome session or quit the backend; history is held in memory only.

The floating window includes microphone mute/unmute, audio pause/resume, Reset,
End session, model selection, vision mode/model, Capture, Analyse and Clear queue.
The question box sends typed questions through the same Chrome session. **End
session** also stops Chrome's audio capture and transcription. Controls are
disabled after disconnect/end and cannot act on a different, newer session.
The **Window** menu contains opacity, click-through, hide and movement controls.
Option+Z shows a hidden window; Option+X restores clicking after click-through.

The floating view automatically starts **click-through ON** when Accessibility
permission and the global Option+X monitor are ready. Clicks then reach Chrome
underneath the entire window. To click Aura's buttons, type a question or drag
its scrollbar, press **Option+X** first: the status changes to **click-through
OFF**. Press Option+X again when finished. Option+Up/Down can scroll while
click-through stays ON. The indicator reads the native macOS state and updates
after either a button or keyboard toggle.

Without global shortcut recovery, the window stays interactive and the status
explains how to enable Accessibility and restart Aura. Returning to Setup always
turns click-through OFF so profile/setup fields remain clickable.

| Control | Effect on the Chrome session |
| --- | --- |
| Mute / Unmute mic | Changes microphone input to Aura; shared-tab audio and the call's own microphone setting are unaffected |
| Pause / Resume audio | Pauses or resumes audio processing for Aura |
| Reset | Clears the conversation and AI context; capture continues |
| End session | Stops capture and transcription; completed desktop history remains visible |
| AI model | Selects the configured primary, secondary or automatic mode |
| Vision / Vision model | Toggles screenshot mode or selects the configured vision model; vision mode pauses audio |
| Capture / Analyse / Clear queue | Queues a screenshot, analyses queued screenshots or removes them; up to four images or the provider's lower limit |
| Question box / Ask | Sends a typed question through the same Chrome-owned session |

Screenshots reuse the shared tab's video track when available. Capture does not
submit images to the AI until you choose Analyse. There is no continuous AI
screen analysis. Keep sharing active to avoid another capture-permission prompt.

## Option shortcuts

The shortcut reference is a small, wrapped strip along the bottom of the desktop
window, leaving more room for the conversation. Every listed key uses Option.
On a Mac, **⌥ is Option** and **⇧ is Shift**.

| Shortcut | Action |
| --- | --- |
| Option+Z | Show/hide desktop Aura |
| Option+X | Toggle desktop click-through |
| Option+1 / 2 / 3 | 100% / 70% / 40% opacity |
| Option+[ / ] | Decrease/increase opacity |
| Option+M | Mute/unmute the Chrome session's microphone input |
| Option+U | Pause/resume audio processing in that session |
| Option+Q / W / E | Primary / secondary / automatic AI model |
| Option+F | Toggle vision mode (pauses audio while enabled) |
| Option+V | Switch vision model, if a secondary is configured |
| Option+S | Capture the shared interview tab into the queue |
| Option+A | Analyse queued screenshots |
| Option+D | Clear the screenshot queue |
| Option+R | Clear that session's conversation and AI context |
| Option+Up / Down | Scroll the full desktop conversation |
| Option+Shift+Arrow | Move the desktop window |

## Permissions and full-screen use

For keys while Chrome is focused, enable **Aura** in **System Settings →
Privacy & Security → Accessibility**, then restart Aura. Also enable Input
Monitoring if macOS requests it. Setup displays the shortcut permission check.

The desktop window uses AppKit floating-window and full-screen collection
behaviors and does not activate when an answer updates. Verify its placement
and physical shortcuts on the actual Mac. Automated connection and dispatch
tests do not exercise the operating system's real keyboard permission flow.
Allow Chrome's requested microphone and capture permissions too. Verify the
actual background transcript, full-screen placement and global shortcuts on
the Mac before relying on the setup.

Returning to desktop **Setup** changes the view without ending Chrome's session.
Keep desktop Aura running: quitting the app also shuts down Chrome's local
backend. Keep Aura's Chrome tab open because it owns the media capture.

## Configuration and personal defaults

Run checks:

```sh
.venv/bin/python -m unittest discover -s tests -v
npm test
```

Optional personal defaults are read from `profile.json` in the runtime data
directory: the project root for source runs, or `~/Library/Application Support/Aura`
for the packaged app. This file is ignored by Git and stays outside the app
bundle. Supported fields are `name`, `company`, `role`, `resume`, `objectives`,
`focus` (a list of focus values) and `selectedLanguages` (a list of language names).
The loaded fields remain editable before a session starts.

`MAX_CONVERSATION_HISTORY` in `.env` limits recent exchanges supplied to the AI
context. It does not limit how many questions and answers the desktop displays.

For example, create `profile.json` in the appropriate runtime data directory:

```json
{
  "name": "Example Candidate",
  "company": "Example Company",
  "role": "Software Engineer",
  "resume": "Background you choose to supply",
  "objectives": "Role description and preparation goals",
  "focus": ["coding"],
  "selectedLanguages": ["python"]
}
```

Use your own content locally. The packaged app does not read the source
checkout's profile or credentials. The full desktop conversation is held in
memory rather than written to this profile file.

Deepgram verification and new sessions read the saved key again, so saving a
replacement key or editing the local `.env` takes effect without restarting
Aura. An already connected transcription stream continues until the session
ends. Verification distinguishes invalid credentials, permission errors,
rate limiting and network failures. Audio capture uses 48 kHz PCM to match
the transcription connection and mixes microphone and tab audio separately.

## Troubleshooting

| Symptom | Check or recovery |
| --- | --- |
| Proceed to Device Setup does not advance | Wait for setup loading to finish and read the inline validation error; complete the highlighted field/tab |
| Deepgram key rejected | Paste the key secret into Advanced Config, Save Key and rerun Device Setup. Distinguish invalid-key, permissions, rate-limit and network messages; use the saved key's account configuration to resolve them |
| Your voice transcribes but Chrome audio does not | Restart the Chrome session, select the tab containing the audio and enable Share tab audio. With headphones and Aura's mic muted, play spoken audio and look for its transcript |
| Show Chrome session stays disabled | Follow the readiness message: start Chrome's session, restore its connection, share tab audio or resolve transcription setup |
| Cannot reach Aura or wrong session appears | Keep the desktop backend running and use its actual port. Avoid starting a second source/packaged instance with a different configuration |
| Controls report a disconnected or expired command | Reconnect the same Chrome session and retry. Controls intentionally reject an old viewer's request targeting another session |
| Secondary or vision model unavailable | Configure and select that provider/model in AI Setup; screenshots require an image-capable model |
| No screenshot is captured | Enable vision, keep the shared video track live and check the four-image queue limit. Use Capture, then Analyse; clear the queue when needed |
| Floating window blocks clicks to Chrome | Check the click-through indicator and press Option+X to turn it ON. If the shortcut is unavailable, enable Accessibility for Aura, restart it and reopen the synced view |
| Aura's buttons cannot be clicked or the window is hidden | Option+X turns click-through OFF to use the controls; Option+Z restores visibility. Use Option+X again to pass clicks to Chrome |
| Option keys work only while Aura is focused | Grant Accessibility to Aura (or the launching terminal for source runs), then restart; enable Input Monitoring if requested |
| Old controls or layout after updating | Fully quit/reopen Aura and hard-refresh Aura's Chrome page with Command+Shift+R |
| Earlier answers disappeared | Reset, a new Chrome session and backend shutdown clear the in-memory conversation. Reconnecting a viewer to the same running session retains it |

## How synchronization works

- Chrome's `/ws?source=browser` connection owns the active audio/AI session.
- The desktop `/ws/desktop` connection receives complete conversation and
  control-state snapshots. It does not take over capture or accept commands.
- Desktop session buttons post validated JSON to `/api/desktop/command` with
  the displayed session ID. The backend forwards an allowlisted command to
  Chrome, which applies it and acknowledges the result. Native session shortcuts
  use the same route; window shortcuts remain local.
- POST `/api/desktop/appearance` changes the native window; GET on the same path
  reports its actual click-through state. `/api/desktop/status`
  reports capture/transcription readiness and shortcut permission status.
- Slow display connections keep only their latest pending snapshot, so dropped
  display updates do not lose answer chunks. Viewer reconnects receive the
  current full state while the backend session remains alive.

See [the validation checklist](CONTRIBUTING.md#validation) for automated coverage
and the real media/window checks that still require the target Mac.

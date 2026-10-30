# Changelog

## Unreleased — Mac playback capture and desktop session sync

### Added

- Direct Mac playback capture on macOS 13+ through a bundled ScreenCaptureKit
  helper, with no Aura Chrome tab or DevTools dependency. It uses the existing
  48 kHz microphone mixer and does not change the normal output device.
- Explicit native permission/connection status, bounded PCM transport,
  cancellation-safe capture cleanup and a compiled PCM self-test.
- Requested native main-display screenshots, capped at 2560 pixels on the
  longest edge with temporary-file cleanup; desktop vision no longer depends
  on the browser's screen-sharing API. The native live view has a compact
  Option-key reference too.
- A floating desktop view of the Chrome-owned audio session with live
  transcripts, streamed answers and reconnection snapshots.
- Readiness checks for an active Chrome session, live shared-tab audio,
  connected transcription and global-shortcut permission status.
- Synced desktop controls for microphone mute, audio pause, Reset, End session,
  AI model selection, vision mode/model, screenshot queues and typed questions.
- Desktop window controls for opacity, click-through, visibility and movement.
- Native Option shortcuts routed to Chrome with unique command IDs, expiry,
  duplicate prevention and acknowledgements.
- Optional editable profile defaults loaded from an ignored runtime
  `profile.json` outside the packaged app bundle.

### Changed

- Desktop questions and answers form one chronological, scrollable conversation.
  The full current-session conversation replaces the five-answer collapsed
  history. Reading position is preserved while scrolled up.
- The shortcut reference is a small wrapped strip pinned to the window bottom.
  Mac labels use Option/⌥ and match the actual shortcuts.
- The floating view starts click-through when the global Option+X recovery
  shortcut is ready. Its native state is displayed and follows keyboard toggles;
  returning to Setup restores normal clicking.
- End session stops browser capture and transcription while keeping the
  completed desktop conversation in memory. Reset, a new Chrome session or
  backend shutdown clears that history.
- Desktop session controls are disabled when disconnected/ended, validate their
  target session and reject requests from unrelated page origins.

### Fixed

- Setup initialization after late optional imports and missing-field errors
  previously hidden by native popup behavior.
- Deepgram verification using stale saved keys and misleading generic errors.
  Verification/new connections reread the saved key and distinguish rejection,
  permission, rate-limit and network failures.
- Browser audio mixing: separate mic/tab inputs at 48 kHz and a connected silent
  processor output to keep the audio graph processing in the background.
- The source launcher builds a missing audio helper, uses its own virtual
  environment's pip, and lets the backend choose a free port instead of killing
  whatever process is listening on port 8002.
- WebSocket URLs on fallback ports, old sockets clearing a reconnected browser's
  connection, and rapid native commands sharing an identifier.
- Click-through previously being off when opening the floating view, unreliable
  native window lookup while unfocused and appearance requests reporting success
  without a native change. State now uses the pywebview window handle and macOS
  readback, with missing-window and missing-recovery cases handled explicitly.

### Validation and documentation

- 47 Python and 94 Node regression tests passed, along with syntax, scoped lint,
  whitespace, macOS packaging and strict code-signature checks.
- Added the macOS README and current setup, troubleshooting, architecture,
  contribution and packaging instructions.
- Removed the tracked development autofill and exclude local `dev.js` from
  packaged apps; personal setup comes from ignored runtime files.
- Migrated the local macOS customizations onto the public fork, merging the
  latest upstream macOS and master branches while retaining MIT attribution,
  provider limits/key handling, base64 audio batching and Markdown/math fixes.
  Preserved Windows documentation separately and documented future upstream sync.
- Physical global shortcuts, permission prompts, actual background capture and
  full-screen window placement remain manual checks on the target Mac.

See [DESKTOP-SYNC.md](DESKTOP-SYNC.md) for usage and
[CONTRIBUTING.md](CONTRIBUTING.md#validation) for validation details.

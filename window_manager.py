# window_manager.py — macOS-native implementation for Aura AI
#
# Replaces the Windows ctypes/Win32 implementation entirely.
# Uses Apple's AppKit (via pyobjc) for all window management:
#   - Transparency       → NSWindow.setAlphaValue_()
#   - Always-on-top      → NSWindow.setLevel_(NSFloatingWindowLevel)
#   - Screen-capture     → NSWindow.setSharingType_(NSWindowSharingNone)
#   - Click-through      → NSWindow.setIgnoresMouseEvents_()
#   - Show/hide          → NSWindow.orderOut_() / orderFrontRegardless()
#   - Global hotkeys     → NSEvent (requires Accessibility permission for global keys)
#
# Public API is identical to the Windows version so main.py and api/ need no changes.

import os
import platform
import time
import tempfile
import uuid
from typing import Optional
from threading import Thread

import orjson
import webview
from pynput import keyboard

# ---------------------------------------------------------------------------
# Scroll configuration — read lazily so .env values are honoured
# (module-level os.environ reads happen before core.config loads .env)
# ---------------------------------------------------------------------------
def _get_scroll_amount_px() -> int:
    """Return SCROLL_SPEED_PX from settings, falling back to 200."""
    try:
        from core.env_utils import env_manager
        return max(1, int(os.environ.get("SCROLL_SPEED_PX") or env_manager.get_value("SCROLL_SPEED_PX") or 200))
    except (ValueError, TypeError):
        return 200


def _get_scroll_interval_ms() -> int:
    """Return SCROLL_INTERVAL_MS from settings, falling back to 50."""
    try:
        from core.env_utils import env_manager
        return max(10, int(os.environ.get("SCROLL_INTERVAL_MS") or env_manager.get_value("SCROLL_INTERVAL_MS") or 50))
    except (ValueError, TypeError):
        return 50

# ---------------------------------------------------------------------------
# macOS Accessibility permission check
# ---------------------------------------------------------------------------
def _has_accessibility_permission() -> bool:
    """Return True if the process has macOS Accessibility permission.

    Uses AXIsProcessTrustedWithOptions() from ApplicationServices.
    NSEvent global key monitoring requires Accessibility trust. macOS may
    also request Input Monitoring access for keyboard monitoring.
    """
    if not IS_MACOS:
        return True
    try:
        import ctypes
        import ctypes.util
        lib = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("ApplicationServices") or
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        return lib.AXIsProcessTrustedWithOptions(None)
    except Exception:
        return True

IS_MACOS = platform.system() == "Darwin"

if IS_MACOS:
    from AppKit import (
        NSApp,
        NSFloatingWindowLevel,
        NSNormalWindowLevel,
        NSWindowSharingNone,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorFullScreenPrimary,
        NSWindowCollectionBehaviorFullScreenNone,
        NSWindowCollectionBehaviorMoveToActiveSpace,
    )
    from Foundation import NSPoint, NSMakeRect, NSObject, NSThread
else:
    # Graceful degradation if somehow imported on another platform
    NSApp = None
    NSFloatingWindowLevel = 8
    NSNormalWindowLevel = 0
    NSWindowSharingNone = 0
    NSPoint = None


# ---------------------------------------------------------------------------
# Main-thread dispatch
# ---------------------------------------------------------------------------
# On macOS, every NSWindow mutation (level, sharing type, alpha, frame, etc.)
# MUST happen on the AppKit main thread. macOS 14+/26 hard-enforces this: an
# off-main-thread window change triggers NSWMWindowCoordinator on the calling
# thread and the process is killed with "Must only be used from the main
# thread". pywebview fires window events (and our hotkey actions) on background
# threads, so we marshal all window work onto the main thread synchronously.
if IS_MACOS:

    class _MainThreadBox:
        """Mutable, pass-by-reference carrier so results survive the ObjC hop."""
        __slots__ = ("fn", "result", "error")

        def __init__(self, fn):
            self.fn = fn
            self.result = None
            self.error = None

    class _MainThreadRunner(NSObject):
        def runBox_(self, box):
            try:
                box.result = box.fn()
            except Exception as exc:  # noqa: BLE001 — propagate to caller thread
                box.error = exc

    _mt_runner = _MainThreadRunner.alloc().init()

    def _run_on_main_thread(fn):
        """Run *fn* on the AppKit main thread synchronously; return its result."""
        if NSThread.isMainThread():
            return fn()
        box = _MainThreadBox(fn)
        # A custom instance bridges as an opaque object (by reference), so
        # box.result / box.error written on the main thread are visible here.
        _mt_runner.performSelectorOnMainThread_withObject_waitUntilDone_(
            "runBox:", box, True
        )
        if box.error is not None:
            raise box.error
        return box.result

else:

    def _run_on_main_thread(fn):
        return fn()


# ---------------------------------------------------------------------------
# Internal helper — locate the Aura NSWindow
# ---------------------------------------------------------------------------
def _get_aura_ns_window():
    """Resolve Aura's own native window even when Chrome has keyboard focus."""
    if not IS_MACOS or NSApp is None:
        return None

    def resolve():
        for window in webview.windows:
            native = getattr(window, "native", None)
            if native is not None:
                return native
        for window in NSApp.windows():
            if window.title() == "Aura":
                return window
        return None

    try:
        return _run_on_main_thread(resolve)
    except Exception as exc:
        print(f"⚠️  Could not locate Aura NSWindow: {exc}")
    return None


# ---------------------------------------------------------------------------
# WindowManager — core class
# ---------------------------------------------------------------------------
class WindowManager:
    """
    macOS-native window manager.
    Exposes the same public interface as the Windows version so that
    main.py and the REST API layer (api/config_api.py) work unchanged.
    """

    def __init__(self):
        """Initialise state for transparency, ghost mode, scrolling, and hotkey listeners."""
        self.is_macos = IS_MACOS
        self.current_transparency: float = 1.0
        self.is_ghost_mode: bool = False
        self.screen_share_monitor_active: bool = False
        self.hidden_screen_share_windows: set = set()

        # Continuous scroll state
        self.scrolling_up: bool = False
        self.scrolling_down: bool = False
        self.scroll_thread: Optional[Thread] = None

        # Hotkey listeners
        self.hotkey_listener = None
        self._scroll_listener = None
        self.command_callback = None
        self.is_desktop_display = False

    # ------------------------------------------------------------------ #
    # Transparency                                                         #
    # ------------------------------------------------------------------ #

    def _enable_transparency(self) -> bool:
        """macOS windows support transparency natively — always True."""
        return True

    def set_window_handle(self, handle) -> None:
        """No-op: macOS uses NSApp to locate the window directly."""
        pass

    def set_transparency(self, transparency: float) -> bool:
        """
        Set window alpha (0.0 = invisible, 1.0 = fully opaque).
        Uses NSWindow.setAlphaValue_ — true native macOS transparency.
        """
        transparency = max(0.0, min(1.0, transparency))
        self.current_transparency = transparency
        try:
            ns_win = _get_aura_ns_window()
            if ns_win:
                def _apply():
                    ns_win.setAlphaValue_(transparency)
                    ns_win.setOpaque_(transparency >= 1.0)
                _run_on_main_thread(_apply)
                print(f"✅ Window transparency set to {transparency * 100:.0f}%")
                return True
            print("⚠️  NSWindow not found for transparency change")
            return False
        except Exception as exc:
            print(f"❌ Error setting transparency: {exc}")
            return False

    def get_transparency(self) -> float:
        """Return the last-set alpha value (0.0 = invisible, 1.0 = opaque)."""
        return self.current_transparency

    def step_transparency(self, direction: int) -> bool:
        levels = [0.2, 0.4, 0.6, 0.8, 1.0]
        if direction > 0:
            target = next((level for level in levels if level > self.current_transparency + 0.01), 1.0)
        else:
            target = next((level for level in reversed(levels) if level < self.current_transparency - 0.01), 0.2)
        return self.set_transparency(target)

    def set_transparency_percent(self, percent: int) -> bool:
        """Set transparency from a 0–100 integer percentage."""
        return self.set_transparency(percent / 100.0)

    def make_transparent(self) -> bool:
        """40% opacity — ideal for stealth interview overlay."""
        return self.set_transparency(0.4)

    def make_semi_transparent(self) -> bool:
        """70% opacity."""
        return self.set_transparency(0.7)

    def make_opaque(self) -> bool:
        """Fully opaque."""
        return self.set_transparency(1.0)

    # ------------------------------------------------------------------ #
    # Always-on-top                                                        #
    # ------------------------------------------------------------------ #

    def set_always_on_top(self, on_top: bool) -> bool:
        """
        Float the window above all others using NSFloatingWindowLevel.
        This is the macOS equivalent of HWND_TOPMOST.
        """
        try:
            ns_win = _get_aura_ns_window()
            if ns_win:
                level = NSFloatingWindowLevel if on_top else NSNormalWindowLevel
                def apply():
                    ns_win.setLevel_(level)
                    if on_top:
                        import AppKit
                        behavior = int(ns_win.collectionBehavior())
                        behavior &= ~(NSWindowCollectionBehaviorFullScreenPrimary
                                      | NSWindowCollectionBehaviorFullScreenNone
                                      | NSWindowCollectionBehaviorMoveToActiveSpace)
                        behavior |= (NSWindowCollectionBehaviorCanJoinAllSpaces
                                     | NSWindowCollectionBehaviorFullScreenAuxiliary)
                        if hasattr(AppKit, 'NSWindowCollectionBehaviorCanJoinAllApplications'):
                            behavior &= ~(AppKit.NSWindowCollectionBehaviorPrimary
                                          | AppKit.NSWindowCollectionBehaviorAuxiliary)
                            behavior |= AppKit.NSWindowCollectionBehaviorCanJoinAllApplications
                        ns_win.setCollectionBehavior_(behavior)
                        ns_win.setHidesOnDeactivate_(False)
                _run_on_main_thread(apply)
                status = "always-on-top" if on_top else "normal stacking"
                print(f"📌 Window set to {status}")
                return True
            print("⚠️  NSWindow not found for always-on-top")
            return False
        except Exception as exc:
            print(f"❌ Error setting always-on-top: {exc}")
            return False

    def set_desktop_display(self, enabled: bool) -> bool:
        """Size the reader before the interview without activating the window."""
        entering = enabled and not self.is_desktop_display
        ns_win = _get_aura_ns_window()
        if not ns_win:
            return False

        def apply():
            if enabled:
                if not getattr(self, '_display_previous_frame', None):
                    self._display_previous_frame = ns_win.frame()
                visible = ns_win.screen().visibleFrame()
                width = min(480, visible.size.width - 32)
                height = min(640, visible.size.height - 32)
                ns_win.setFrame_display_(NSMakeRect(
                    visible.origin.x + visible.size.width - width - 16,
                    visible.origin.y + visible.size.height - height - 16,
                    width, height
                ), True)
            elif getattr(self, '_display_previous_frame', None):
                ns_win.setFrame_display_(self._display_previous_frame, True)
                self._display_previous_frame = None

        try:
            _run_on_main_thread(apply)
            success = self.set_always_on_top(True)
            if success:
                # Only start pass-through when Option+X can restore the controls
                # after a click sends keyboard focus back to Chrome.
                if entering:
                    success = self.set_ghost_mode(self.can_restore_click_through())
                elif not enabled:
                    success = self.set_ghost_mode(False)
                if success:
                    self.is_desktop_display = enabled
            return success
        except Exception as exc:
            print(f"Could not configure desktop display: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Screen-capture protection                                            #
    # ------------------------------------------------------------------ #

    def apply_capture_protection(self) -> bool:
        """
        Prevent this window from appearing in screen recordings and sharing.
        Uses NSWindowSharingNone — the macOS native equivalent of
        Windows' WDA_EXCLUDEFROMCAPTURE (SetWindowDisplayAffinity).

        Works with: QuickTime, screenshot tools, Zoom, Teams, Google Meet,
        OBS (when not using display capture), and most capture APIs that
        respect NSWindowSharingType.
        """
        try:
            ns_win = _get_aura_ns_window()
            if ns_win:
                _run_on_main_thread(lambda: ns_win.setSharingType_(NSWindowSharingNone))
                print("🛡️  Screen capture protection applied (NSWindowSharingNone)")
                return True
            print("⚠️  NSWindow not found for capture protection")
            return False
        except Exception as exc:
            print(f"❌ Error applying capture protection: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Ghost / click-through mode                                           #
    # ------------------------------------------------------------------ #

    def can_restore_click_through(self) -> bool:
        """The global Option+X monitor must work before clicks can be ignored."""
        return getattr(self, "_key_down_monitor", None) is not None and _has_accessibility_permission()

    def get_click_through_state(self) -> dict:
        def read():
            ns_win = _get_aura_ns_window()
            available = ns_win is not None
            if available:
                self.is_ghost_mode = bool(ns_win.ignoresMouseEvents())
            return {
                "available": available,
                "click_through": self.is_ghost_mode if available else False,
                "shortcuts_ready": self.can_restore_click_through(),
            }

        return _run_on_main_thread(read)

    def set_ghost_mode(self, enabled: bool) -> bool:
        """
        Enable or disable click-through mode.
        Uses NSWindow.setIgnoresMouseEvents_ — native macOS pass-through.
        """
        if enabled and not self.can_restore_click_through():
            print("Click-through requires Accessibility and the global Option+X monitor. Restart Aura after granting access.")
            return False

        def apply():
            ns_win = _get_aura_ns_window()
            if ns_win is None:
                return False
            ns_win.setIgnoresMouseEvents_(enabled)
            self.is_ghost_mode = bool(ns_win.ignoresMouseEvents())
            return self.is_ghost_mode == enabled

        try:
            return _run_on_main_thread(apply)
        except Exception as exc:
            print(f"❌ Error setting ghost mode: {exc}")
            return False

    def toggle_ghost_mode(self) -> bool:
        """Flip ghost/click-through mode between enabled and disabled."""
        def apply():
            ns_win = _get_aura_ns_window()
            if ns_win is None:
                return False
            return self.set_ghost_mode(not bool(ns_win.ignoresMouseEvents()))

        try:
            return _run_on_main_thread(apply)
        except Exception as exc:
            print(f"❌ Error toggling ghost mode: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Visibility (show / hide)                                             #
    # ------------------------------------------------------------------ #

    def toggle_visibility(self) -> None:
        """Toggle window visibility without changing focus order."""
        try:
            ns_win = _get_aura_ns_window()
            if ns_win:
                if ns_win.isVisible():
                    _run_on_main_thread(lambda: ns_win.orderOut_(None))
                    print("🕵️  Window hidden (stealth)")
                else:
                    _run_on_main_thread(ns_win.orderFrontRegardless)
                    self.set_always_on_top(True)
                    print("✨ Window shown (stealth — no focus steal)")
        except Exception as exc:
            print(f"❌ Error toggling visibility: {exc}")

    def hide_from_taskbar(self) -> bool:
        """
        macOS: Dock entries are controlled by the Info.plist LSUIElement key,
        not at runtime. pywebview sets this correctly by default.
        This is a deliberate no-op — the app already won't show in the Dock
        during stealth mode (window level handles that).
        """
        print("ℹ️  hide_from_taskbar: macOS handles this via window level (no-op)")
        return True

    # ------------------------------------------------------------------ #
    # Window movement                                                      #
    # ------------------------------------------------------------------ #

    def move_window(self, dx: int, dy: int) -> bool:
        """Move the window by (dx, dy) pixels without activating it."""
        try:
            ns_win = _get_aura_ns_window()
            if ns_win:
                frame = ns_win.frame()
                # macOS origin is bottom-left; dy is intentionally inverted
                new_x = frame.origin.x + dx
                new_y = frame.origin.y - dy
                _run_on_main_thread(lambda: ns_win.setFrameOrigin_(NSPoint(new_x, new_y)))
                print(f"🎯 Window moved ({dx:+d}px, {dy:+d}px)")
                return True
            return False
        except Exception as exc:
            print(f"❌ Error moving window: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Proctoring stealth mode                                              #
    # ------------------------------------------------------------------ #

    def enable_proctoring_stealth_mode(self) -> bool:
        """Combine ghost mode + capture protection + always-on-top + 70% opacity."""
        try:
            print("🎯 Enabling PROCTORING STEALTH MODE…")
            self.set_ghost_mode(True)
            self.apply_capture_protection()
            self.set_always_on_top(True)
            self.set_transparency(0.7)
            print("✅ PROCTORING STEALTH MODE ENABLED")
            print("   📌 Option+Z  — Toggle visibility")
            print("   📌 Option+X  — Toggle ghost mode")
            print("   📌 Option+1/2/3 — Transparency presets")
            print("   ⚠️  DO NOT click the window — focus change may be detected!")
            return True
        except Exception as exc:
            print(f"❌ Error enabling proctoring stealth mode: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Window info                                                          #
    # ------------------------------------------------------------------ #

    def get_window_info(self) -> dict:
        """Return a snapshot of the current window state as a plain dict."""
        return {
            "transparency": self.current_transparency,
            "transparency_percent": int(self.current_transparency * 100),
            "is_transparent": self.current_transparency < 1.0,
            "platform_supported": self.is_macos,
            "window_handle": None,
            "screen_share_monitor_active": self.screen_share_monitor_active,
            "hidden_screen_share_windows": len(self.hidden_screen_share_windows),
        }

    # ------------------------------------------------------------------ #
    # Continuous scrolling (key-held)                                      #
    # ------------------------------------------------------------------ #

    def _continuous_scroll_loop(self) -> None:
        """Background thread — smooth scroll while key is held."""
        interval = _get_scroll_interval_ms() / 1000.0
        while self.scrolling_up or self.scrolling_down:
            try:
                amount = _get_scroll_amount_px()
                if webview.windows:
                    win = webview.windows[0]
                    if self.scrolling_up:
                        win.evaluate_js(
                            f'(document.getElementById("conversation-stream") || document.getElementById("answer"))'
                            f'?.scrollBy({{top:-{amount},behavior:"smooth"}})'
                        )
                    elif self.scrolling_down:
                        win.evaluate_js(
                            f'(document.getElementById("conversation-stream") || document.getElementById("answer"))'
                            f'?.scrollBy({{top:{amount},behavior:"smooth"}})'
                        )
            except Exception:
                pass
            time.sleep(interval)

    def _start_scroll(self, direction: str) -> None:
        """Begin continuous scrolling in *direction* ('up' or 'down') on a daemon thread."""
        self.scrolling_up = direction == "up"
        self.scrolling_down = direction == "down"
        if not self.scroll_thread or not self.scroll_thread.is_alive():
            self.scroll_thread = Thread(
                target=self._continuous_scroll_loop, daemon=True
            )
            self.scroll_thread.start()

    def _stop_scroll(self) -> None:
        """Signal the scroll thread to stop at the next iteration."""
        self.scrolling_up = False
        self.scrolling_down = False

    # ------------------------------------------------------------------ #
    # Global hotkey listener                                               #
    # ------------------------------------------------------------------ #

    def start_hotkey_listener(self) -> None:
        """Start global keyboard shortcuts using AppKit NSEvent monitors.

        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_ is the native
        macOS API for system-wide key monitoring.  It runs inside the existing
        NSApplication run loop (started by pywebview) so there is no CFRunLoop
        conflict and no SIGTRAP.

        event.Physical key codes keep Option shortcuts stable when macOS generates
        symbols such as µ or ß for modified letters.

        Global key monitoring requires Aura to be trusted in
        System Settings → Privacy & Security → Accessibility.
        Enable Input Monitoring too if macOS requests it.
        """
        print("⌨️  Starting global hotkey listener (NSEvent)…")
        if _has_accessibility_permission():
            print("   ✅ Accessibility permission OK")
        print("   ℹ️  Global hotkeys require Accessibility permission:")
        print("      System Settings → Privacy & Security → Accessibility")
        print("      Add Aura.app (or the launching terminal for a source run), enable it, then restart Aura.")

        # ── Command file bridge ──────────────────────────────────────────
        def _send_command(data: dict) -> None:
            """Atomically write a command to the temp file (tmp → os.replace).
            Prevents main.py's polling reader from seeing a half-written JSON blob.
            """
            try:
                data["event_id"] = uuid.uuid4().hex
                if self.command_callback:
                    self.command_callback(data)
                    return
                cmd_file = os.path.join(tempfile.gettempdir(), "aura_command.json")
                tmp_file = f"{cmd_file}.tmp"
                data["source"] = "global_hotkey"
                with open(tmp_file, "wb") as fh:
                    fh.write(orjson.dumps(data))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_file, cmd_file)
            except Exception as exc:
                print(f"⚠️  Could not write hotkey command: {exc}")

        # ── Action map keyed by base character ───────────────────────────
        _HOTKEY_ACTIONS: dict = {
            'z': lambda: self.toggle_visibility(),
            'x': lambda: self.toggle_ghost_mode(),
            '1': lambda: self.set_transparency(1.0),
            '2': lambda: self.set_transparency(0.7),
            '3': lambda: self.set_transparency(0.4),
            '[': lambda: self.step_transparency(-1),
            ']': lambda: self.step_transparency(1),
            'm': lambda: _send_command({"command": "toggle_mic_mute"}),
            'u': lambda: _send_command({"command": "toggle_universal_mute"}),
            'q': lambda: _send_command({"command": "switch_preset", "preset_key": "primary"}),
            'w': lambda: _send_command({"command": "switch_preset", "preset_key": "secondary"}),
            'e': lambda: _send_command({"command": "switch_preset", "preset_key": "auto"}),
            'f': lambda: _send_command({"command": "toggle_vision_mode"}),
            'v': lambda: _send_command({"command": "switch_vision_model"}),
            's': lambda: _send_command({"command": "capture_screenshot"}),
            'a': lambda: _send_command({"command": "process_screenshots"}),
            'd': lambda: _send_command({"command": "reset_screenshot_queue"}),
            'r': lambda: _send_command({"command": "reset_interview"}),
        }

        # ── NSEvent mask constants ────────────────────────────────────────
        _NSKeyDownMask    = 1 << 10   # 1024
        _NSKeyUpMask      = 1 << 11   # 2048
        _NSAltKeyMask     = 1 << 19   # NSAlternateKeyMask
        _NSShiftKeyMask   = 1 << 17
        _NSCommandOrControl = (1 << 20) | (1 << 18)
        _KEY_ARROW_UP     = 126       # kVK_UpArrow
        _KEY_ARROW_DOWN   = 125       # kVK_DownArrow
        _ARROW_MOVES = {123: (-20, 0), 124: (20, 0), 125: (0, 20), 126: (0, -20)}
        _KEY_NAMES = {0: 'a', 1: 's', 2: 'd', 3: 'f', 6: 'z', 7: 'x',
                      9: 'v', 12: 'q', 13: 'w', 14: 'e', 15: 'r',
                      18: '1', 19: '2', 20: '3', 30: ']', 33: '[', 32: 'u', 46: 'm'}

        # ── Key-down handler ─────────────────────────────────────────────
        def _on_key_down(event) -> None:
            """Dispatch hotkeys and start scroll on ⌥↑ / ⌥↓."""
            flags = event.modifierFlags()
            if not (flags & _NSAltKeyMask) or flags & _NSCommandOrControl:
                return False

            key_code = event.keyCode()

            if flags & _NSShiftKeyMask:
                if key_code in _ARROW_MOVES:
                    self.move_window(*_ARROW_MOVES[key_code])
                    return True
                return False

            # Scroll ─────────────────────────────────────────────────────
            if key_code == _KEY_ARROW_UP:
                self._start_scroll("up")
                return True
            if key_code == _KEY_ARROW_DOWN:
                self._start_scroll("down")
                return True

            # Hotkey ─────────────────────────────────────────────────────
            # Use physical key codes rather than Option-modified characters.
            chars = _KEY_NAMES.get(key_code)
            if chars:
                action = _HOTKEY_ACTIONS.get(chars.lower())
                if action:
                    if not event.isARepeat():
                        action()
                    return True
            return False

        # ── Key-up handler ───────────────────────────────────────────────
        def _on_key_up(event) -> None:
            """Stop scroll when ↑/↓ or Option is released."""
            key_code = event.keyCode()
            flags    = event.modifierFlags()

            if key_code in (_KEY_ARROW_UP, _KEY_ARROW_DOWN):
                self._stop_scroll()
            # Option released → stop any ongoing scroll
            if not (flags & _NSAltKeyMask):
                self._stop_scroll()

        # Local-monitor wrappers: these fire only while the Aura window is the
        # focused app, and — unlike global monitors — need NO Input Monitoring
        # permission. A local handler must return the event to let it through,
        # or None to consume it. We consume Option-modified key-downs (our
        # hotkeys) so they don't type stray characters into a focused field.
        def _on_key_down_local(event):
            try:
                if _on_key_down(event):
                    return None  # consume handled ⌥-combos
            except Exception:
                pass
            return event

        def _on_key_up_local(event):
            try:
                _on_key_up(event)
            except Exception:
                pass
            return event

        # ── Register monitors ────────────────────────────────────────────
        # Global monitors fire when Aura is NOT focused (need Accessibility
        # permission); local monitors fire when it IS focused (no permission).
        # Registering both means hotkeys work in the common focused case even
        # if the permission hasn't been granted.
        try:
            from AppKit import NSEvent  # already imported at module level; re-bind locally

            self._key_down_local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                _NSKeyDownMask, _on_key_down_local
            )
            self._key_up_local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                _NSKeyUpMask | (1 << 12), _on_key_up_local
            )
            print("✅ Local hotkey listener active (works when Aura is focused — no permission needed)")

            global_ok = False
            try:
                self._key_down_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    _NSKeyDownMask, _on_key_down
                )
                self._key_up_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    _NSKeyUpMask | (1 << 12), _on_key_up
                )
                # A global monitor registers even without permission; it just
                # never fires. We can't detect that here, so we advise either way.
                global_ok = self._key_down_monitor is not None
            except Exception as gexc:
                print(f"⚠️ Global (unfocused) hotkeys unavailable: {gexc}")

            if global_ok:
                print("✅ Global hotkey monitor registered (needs Accessibility permission when Aura is unfocused)")
            print("   ⌥Z=hide  ⌥X=ghost  ⌥1-3=opacity  ⌥M=mute  ⌥S=screenshot  ⌥A=analyze")
            print("   ℹ️ For hotkeys while Aura is NOT focused: grant Accessibility permission to Aura")
            print("      (System Settings → Privacy & Security → Accessibility) and restart.")
        except Exception as exc:
            print(f"❌ Failed to register NSEvent monitors: {exc}")
            print("   💡 Grant Input Monitoring permission and restart the app.")
            print("      System Settings → Privacy & Security → Accessibility")

    # ------------------------------------------------------------------ #
    # Screen-share indicator stubs (Windows-only feature — not on macOS)  #
    # ------------------------------------------------------------------ #

    def find_window_by_title(self, title: str):
        """Stub — Windows-only feature, not applicable on macOS."""
        return None

    def find_screen_share_indicators(self) -> list:
        """Stub — screen-share indicator detection is Windows-only."""
        return []

    def hide_screen_share_indicator(self, hwnd) -> bool:
        """Stub — hiding screen-share indicators is Windows-only."""
        return False

    def hide_all_screen_share_indicators(self) -> int:
        """Stub — hiding all screen-share indicators is Windows-only."""
        return 0

    def start_screen_share_monitor(self) -> None:
        """Stub — screen-share indicator monitor is Windows-only; prints a notice on macOS."""
        print("ℹ️  Screen-share indicator monitor: not applicable on macOS")

    def stop_screen_share_monitor(self) -> None:
        """Stub — screen-share monitor is Windows-only; no-op on macOS."""
        pass


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
window_manager = WindowManager()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# Identical public interface as the Windows version — main.py / config_api.py
# call these without any modification.
# ---------------------------------------------------------------------------

def apply_capture_protection(pywebview_window=None) -> bool:
    """Apply macOS-native screen-capture protection (NSWindowSharingNone)."""
    return window_manager.apply_capture_protection()


def find_aura_window() -> bool:
    """Confirm the Aura NSWindow is reachable via NSApp."""
    ns_win = _get_aura_ns_window()
    if ns_win:
        print(f"🔍 Aura NSWindow located: '{ns_win.title()}'")
        return True
    print("⚠️  Aura NSWindow not yet available")
    return False


def set_app_always_on_top(on_top: bool) -> bool:
    """Module-level alias: set or clear the always-on-top window level."""
    return window_manager.set_always_on_top(on_top)


def set_app_transparency(transparency: float) -> bool:
    """Module-level alias: set window alpha (0.0–1.0)."""
    return window_manager.set_transparency(transparency)


def set_app_transparency_percent(percent: int) -> bool:
    """Module-level alias: set window transparency from a 0–100 integer."""
    return window_manager.set_transparency_percent(percent)


def make_app_transparent() -> bool:
    """Module-level alias: set window to 40% opacity (stealth overlay)."""
    return window_manager.make_transparent()


def make_app_semi_transparent() -> bool:
    """Module-level alias: set window to 70% opacity."""
    return window_manager.make_semi_transparent()


def make_app_opaque() -> bool:
    """Module-level alias: set window to fully opaque (100%)."""
    return window_manager.make_opaque()


def get_transparency_info() -> dict:
    """Module-level alias: return the current window state snapshot."""
    return window_manager.get_window_info()

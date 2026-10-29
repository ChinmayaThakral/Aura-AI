import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import window_manager as wm


class ClickThroughTests(unittest.TestCase):
    def setUp(self):
        self.manager = wm.WindowManager()
        self.manager._key_down_monitor = object()
        self.native = Mock()
        self.ignored = False
        self.native.setIgnoresMouseEvents_.side_effect = self.set_ignored
        self.native.ignoresMouseEvents.side_effect = lambda: self.ignored
        self.native.frame.return_value = "original frame"
        self.native.screen.return_value.visibleFrame.return_value = SimpleNamespace(
            origin=SimpleNamespace(x=0, y=0),
            size=SimpleNamespace(width=1440, height=900),
        )
        for target, options in [
            ("_run_on_main_thread", {"side_effect": lambda fn: fn()}),
            ("_get_aura_ns_window", {"return_value": self.native}),
            ("_has_accessibility_permission", {"return_value": True}),
        ]:
            patcher = patch.object(wm, target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_ignored(self, enabled):
        self.ignored = enabled

    def test_native_mouse_passthrough_and_toggle_use_the_actual_window_state(self):
        self.assertTrue(self.manager.set_ghost_mode(True))
        self.assertTrue(self.ignored)
        self.assertTrue(self.manager.get_click_through_state()["click_through"])
        self.manager.is_ghost_mode = False  # A stale cache must not invert the toggle.
        self.assertTrue(self.manager.toggle_ghost_mode())
        self.assertFalse(self.ignored)
        self.assertFalse(self.manager.get_click_through_state()["click_through"])

    def test_opening_display_starts_passthrough_and_setup_restores_clicks(self):
        with patch.object(self.manager, "set_always_on_top", return_value=True):
            self.assertTrue(self.manager.set_desktop_display(True))
            self.assertTrue(self.ignored)
            self.assertTrue(self.manager.toggle_ghost_mode())
            self.assertFalse(self.ignored)
            # Reconfiguring the same view must preserve a user's interactive mode.
            self.assertTrue(self.manager.set_desktop_display(True))
            self.assertFalse(self.ignored)
            self.assertTrue(self.manager.set_ghost_mode(True))
            self.assertTrue(self.manager.set_desktop_display(False))
            self.assertFalse(self.ignored)
            self.native.setFrame_display_.assert_called_with("original frame", True)

    def test_missing_global_shortcut_recovery_keeps_the_window_clickable(self):
        for monitor, trusted in [(None, True), (object(), False)]:
            with (
                self.subTest(trusted=trusted),
                patch.object(self.manager, "_key_down_monitor", monitor),
                patch.object(wm, "_has_accessibility_permission", return_value=trusted),
                patch.object(self.manager, "set_always_on_top", return_value=True),
            ):
                self.assertFalse(self.manager.set_ghost_mode(True))
                self.assertTrue(self.manager.set_desktop_display(True))
                self.assertFalse(self.ignored)
                self.manager.is_desktop_display = False

    def test_missing_native_window_reports_failure_instead_of_success(self):
        with patch.object(wm, "_get_aura_ns_window", return_value=None):
            self.assertFalse(self.manager.set_ghost_mode(True))
            self.assertFalse(self.manager.toggle_ghost_mode())
            self.assertFalse(self.manager.get_click_through_state()["available"])
        self.native.setIgnoresMouseEvents_.assert_not_called()

    def test_native_readback_must_confirm_passthrough_was_applied(self):
        self.native.setIgnoresMouseEvents_.side_effect = None
        self.assertFalse(self.manager.set_ghost_mode(True))
        self.assertFalse(self.manager.is_ghost_mode)


class NativeWindowLookupTests(unittest.TestCase):
    def test_lookup_uses_pywebview_native_handle_without_a_key_window_or_fixed_title(
        self,
    ):
        native = object()
        app = Mock()
        app.mainWindow.return_value = None
        with (
            patch.object(wm, "IS_MACOS", True),
            patch.object(wm, "NSApp", app),
            patch.object(wm.webview, "windows", [SimpleNamespace(native=native)]),
            patch.object(
                wm, "_run_on_main_thread", side_effect=lambda fn: fn()
            ) as dispatch,
        ):
            self.assertIs(wm._get_aura_ns_window(), native)
            dispatch.assert_called_once()
            app.mainWindow.assert_not_called()

    def test_lookup_does_not_change_an_unrelated_dialog_if_aura_is_missing(self):
        dialog = Mock()
        dialog.title.return_value = "Choose a file"
        app = Mock()
        app.windows.return_value = [dialog]
        app.mainWindow.return_value = dialog
        with (
            patch.object(wm, "IS_MACOS", True),
            patch.object(wm, "NSApp", app),
            patch.object(wm.webview, "windows", []),
            patch.object(wm, "_run_on_main_thread", side_effect=lambda fn: fn()),
        ):
            self.assertIsNone(wm._get_aura_ns_window())
            app.mainWindow.assert_not_called()

import unittest
from unittest.mock import Mock, patch

import window_manager as wm


class Event:
    def __init__(self, code, flags=1 << 19, repeat=False):
        self.code, self.flags, self.repeat = code, flags, repeat

    def keyCode(self):
        return self.code

    def modifierFlags(self):
        return self.flags

    def isARepeat(self):
        return self.repeat


class NativeShortcutTests(unittest.TestCase):
    def setUp(self):
        self.handlers = {}

        def register(mask, callback):
            self.handlers[mask] = callback
            return object()

        facade = Mock()
        facade.addLocalMonitorForEventsMatchingMask_handler_.side_effect = register
        facade.addGlobalMonitorForEventsMatchingMask_handler_.return_value = object()
        self.manager = wm.WindowManager()
        self.commands = []
        self.manager.command_callback = self.commands.append
        for method in [
            "toggle_visibility",
            "toggle_ghost_mode",
            "set_transparency",
            "step_transparency",
            "move_window",
            "_start_scroll",
            "_stop_scroll",
        ]:
            setattr(self.manager, method, Mock())
        with (
            patch("AppKit.NSEvent", facade),
            patch.object(wm, "_has_accessibility_permission", return_value=True),
        ):
            self.manager.start_hotkey_listener()
        self.key_down = self.handlers[1 << 10]

    def test_scroll_settings_read_saved_values_and_tolerate_invalid_input(self):
        from core.env_utils import env_manager

        with (
            patch.dict(
                wm.os.environ, {"SCROLL_SPEED_PX": "", "SCROLL_INTERVAL_MS": ""}
            ),
            patch.object(
                env_manager,
                "get_value",
                side_effect=lambda key: {
                    "SCROLL_SPEED_PX": "350",
                    "SCROLL_INTERVAL_MS": "25",
                }[key],
            ),
        ):
            self.assertEqual(wm._get_scroll_amount_px(), 350)
            self.assertEqual(wm._get_scroll_interval_ms(), 25)
        with patch.dict(
            wm.os.environ, {"SCROLL_SPEED_PX": "invalid", "SCROLL_INTERVAL_MS": "1"}
        ):
            self.assertEqual(wm._get_scroll_amount_px(), 200)
            self.assertEqual(wm._get_scroll_interval_ms(), 10)

    def test_every_session_key_uses_the_ordered_native_command_queue(self):
        bindings = {
            46: "toggle_mic_mute",
            32: "toggle_universal_mute",
            12: "switch_preset",
            13: "switch_preset",
            14: "switch_preset",
            3: "toggle_vision_mode",
            9: "switch_vision_model",
            1: "capture_screenshot",
            0: "process_screenshots",
            2: "reset_screenshot_queue",
            15: "reset_interview",
        }
        for code in bindings:
            self.assertIsNone(self.key_down(Event(code)))
        self.assertEqual(
            [item["command"] for item in self.commands], list(bindings.values())
        )
        self.assertEqual(
            [item.get("preset_key") for item in self.commands[2:5]],
            ["primary", "secondary", "auto"],
        )
        self.assertEqual(
            len({item["event_id"] for item in self.commands}), len(bindings)
        )

    def test_appearance_and_utilities_stay_local_to_the_desktop_window(self):
        for code in [6, 7, 18, 19, 20, 33, 30, 126, 125]:
            self.key_down(Event(code))
        self.manager.toggle_visibility.assert_called_once()
        self.manager.toggle_ghost_mode.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in self.manager.set_transparency.call_args_list],
            [1.0, 0.7, 0.4],
        )
        self.assertEqual(
            [call.args[0] for call in self.manager.step_transparency.call_args_list],
            [-1, 1],
        )
        self.assertEqual(
            [call.args[0] for call in self.manager._start_scroll.call_args_list],
            ["up", "down"],
        )
        for code in [123, 124, 125, 126]:
            self.key_down(Event(code, flags=(1 << 19) | (1 << 17)))
        self.assertEqual(self.manager.move_window.call_count, 4)
        self.assertEqual(self.commands, [])

    def test_repeat_and_unrelated_option_combinations_do_not_toggle_or_get_swallowed(
        self,
    ):
        self.key_down(Event(46, repeat=True))
        self.assertEqual(self.commands, [])
        for event in [
            Event(46, flags=0),
            Event(46, flags=(1 << 19) | (1 << 20)),
            Event(40),
        ]:
            self.assertIs(self.key_down(event), event)

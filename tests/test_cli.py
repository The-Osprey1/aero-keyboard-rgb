import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import cli, keyboard_led


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, AERO_RGB_CONFIG_DIR=directory.name)
        env.start()
        self.addCleanup(env.stop)
        self.baseline = dict(pattern="Static", color="#123456", brightness=4, speed=5)
        cli.save_profile(self.baseline)

    def test_profile_roundtrip(self):
        self.assertEqual(cli.load_profile(), self.baseline)

    def test_invalid_save_preserves_profile(self):
        for field, value in [("color", "1234567"), ("brightness", -1), ("speed", True)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                cli.save_profile(dict(self.baseline, **{field: value}))
        self.assertEqual(cli.load_profile(), self.baseline)

    def test_corrupt_profile_never_starts_task(self):
        cli.profile_path().write_text("{bad", encoding="utf-8")
        with patch.object(cli.subprocess, "call") as child:
            self.assertEqual(cli.main(["run", "--", "program"]), 1)
            child.assert_not_called()

    def test_missing_baseline_never_changes_hardware(self):
        cli.profile_path().unlink()
        with patch.object(cli, "set_status") as status:
            self.assertEqual(cli.main(["run", "--", "program"]), 1)
            status.assert_not_called()

    def test_task_results_and_restore(self):
        for code in (0, 7):
            with self.subTest(code=code), patch.object(cli, "set_status", return_value=True) as status, patch.object(cli, "set_keyboard_led", return_value=True) as restore, patch.object(cli.subprocess, "call", return_value=code) as child:
                self.assertEqual(cli.main(["run", "--seconds", "0", "--", "program", "a b"]), code)
                child.assert_called_once_with(["program", "a b"])
                self.assertEqual([c.args[0] for c in status.call_args_list], ["busy", "success" if code == 0 else "error"])
                restore.assert_called_once_with(**self.baseline)

    def test_cancel_and_launch_failure_restore(self):
        for error, expected in [(KeyboardInterrupt(), 130), (FileNotFoundError(), 127)]:
            with self.subTest(error=error), patch.object(cli, "set_status", return_value=True), patch.object(cli, "set_keyboard_led", return_value=True) as restore, patch.object(cli.subprocess, "call", side_effect=error):
                self.assertEqual(cli.run_task(["program"], 0), expected)
                restore.assert_called_once_with(**self.baseline)

    def test_initial_controller_failure_does_not_launch(self):
        with patch.object(cli, "set_status", return_value=False), patch.object(cli, "set_keyboard_led", return_value=True), patch.object(cli.subprocess, "call") as child:
            self.assertEqual(cli.run_task(["program"], 0), 1)
            child.assert_not_called()

    def test_restore_failure_preserves_task_exit(self):
        with patch.object(cli, "set_status", return_value=True), patch.object(cli, "set_keyboard_led", return_value=False), patch.object(cli.subprocess, "call", return_value=9):
            self.assertEqual(cli.run_task(["program"], 0), 9)

    def test_invalid_duration(self):
        for value in ("nan", "inf", "-1", "61"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                cli.main(["run", "--seconds", value, "--", "program"])

    def test_controller_errors(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("powershell", 20)):
            with patch.object(keyboard_led.subprocess, "run", side_effect=error):
                self.assertFalse(keyboard_led.set_status("busy"))

    def test_legacy_cli_propagates_failure(self):
        with patch.object(keyboard_led, "set_keyboard_led", return_value=False):
            self.assertEqual(cli.main(["--status", "busy"]), 1)

    def test_real_child_exit_code(self):
        with patch.object(cli, "set_status", return_value=True), patch.object(cli, "set_keyboard_led", return_value=True) as restore:
            self.assertEqual(cli.run_task([sys.executable, "-c", "raise SystemExit(23)"], 0), 23)
            restore.assert_called_once_with(**self.baseline)


if __name__ == "__main__":
    unittest.main()

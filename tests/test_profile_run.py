"""Saved profiles, `aero-rgb run`, and the older flag style.

These carry over every scenario from the tests that came with the earlier profile/run command.
"""

import subprocess
import sys

import pytest

import aero_rgb
from aero_rgb import cli
from aero_rgb.backends import BackendError, DryRunBackend, PowerShellBackend
from aero_rgb.config import load_config
from aero_rgb.profile import load_profile, profile_path, save_profile
from aero_rgb.state import LightState

BASELINE = dict(pattern="Static", color="#123456", brightness=4, speed=5)
BASELINE_STATE = LightState("static", (0x12, 0x34, 0x56), 4, 5)


class RecordingBackend(DryRunBackend):
    """Records what was shown; can be told to fail on chosen calls (1-based)."""

    def __init__(self, fail_on=()):
        super().__init__(echo=None)
        self.fail_on = set(fail_on)
        self.calls = 0

    def apply(self, state):
        self.calls += 1
        if self.calls in self.fail_on:
            raise BackendError("controller unavailable")
        super().apply(state)


@pytest.fixture
def hardware(monkeypatch):
    """No background program; every command talks to one recording backend."""
    holder = {"backend": RecordingBackend()}
    monkeypatch.setattr(cli, "daemon_running", lambda port: False)
    monkeypatch.setattr(cli, "create_backend", lambda *a, **k: holder["backend"])
    return holder


@pytest.fixture
def baseline():
    save_profile(dict(BASELINE))
    return BASELINE


def shown(holder):
    return [s.color for s in holder["backend"].states]


BUSY, SUCCESS, ERROR = ((0, 255, 255), (0, 255, 0), (255, 0, 0))


# --- profiles ---------------------------------------------------------------

def test_profile_round_trip(baseline):
    assert load_profile() == BASELINE
    assert load_config().base_state() == BASELINE_STATE


def test_invalid_save_keeps_the_old_profile(baseline):
    for field, value in [("color", "1234567"), ("brightness", -1), ("speed", True), ("pattern", "disco")]:
        with pytest.raises(ValueError):
            save_profile(dict(BASELINE, **{field: value}))
    assert load_profile() == BASELINE
    assert list(profile_path().parent.glob("*.tmp")) == []  # no half-written files left behind


def test_profile_commands(hardware, capsys):
    assert cli.main(["profile", "show"]) == 1
    assert "profile save" in capsys.readouterr().err
    assert cli.main(["profile", "save", "--color", "#123456", "--brightness", "4", "--speed", "5"]) == 0
    assert hardware["backend"].states == []  # saving never touches the keyboard
    assert cli.main(["profile", "show"]) == 0
    assert '"#123456"' in capsys.readouterr().out
    assert cli.main(["profile", "apply"]) == 0
    assert hardware["backend"].states == [BASELINE_STATE]


def test_profile_save_rejects_bad_values(hardware, capsys):
    assert cli.main(["profile", "save", "--color", "notacolor"]) == 1
    assert not profile_path().exists()


def test_profile_is_the_base_unless_settings_name_one(baseline, tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('[base]\npreset = "focus"\n')
    assert load_config(settings).base_state() == load_config(settings).preset("focus")
    assert load_config(settings).preset("profile") == BASELINE_STATE


def test_profile_saved_by_the_earlier_version_still_loads(tmp_path, monkeypatch):
    folder = tmp_path / "appdata" / "aero-keyboard-rgb"
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text('{\n  "pattern": "Breathe",\n  "color": "Cyan",\n  "brightness": 8,\n  "speed": 3\n}')
    monkeypatch.delenv("AERO_RGB_CONFIG_DIR")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "appdata"))
    assert load_config().base_state() == LightState("breathe", (0, 255, 255), 8, 3)


# --- run --------------------------------------------------------------------

@pytest.mark.parametrize("code", [0, 7])
def test_run_signals_result_then_restores(hardware, baseline, monkeypatch, code):
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or code)
    assert cli.main(["run", "--seconds", "0", "--", "program", "a b"]) == code
    assert calls == [["program", "a b"]]  # passed through exactly, no shell
    assert shown(hardware) == [BUSY, SUCCESS if code == 0 else ERROR, BASELINE_STATE.color]


@pytest.mark.parametrize("error,expected", [(KeyboardInterrupt(), 130), (FileNotFoundError(), 127),
                                            (PermissionError("denied"), 126)])
def test_run_cancel_and_launch_failures_restore(hardware, baseline, monkeypatch, error, expected):
    def call(cmd):
        raise error

    monkeypatch.setattr(cli.subprocess, "call", call)
    assert cli.main(["run", "--seconds", "0", "--", "program"]) == expected
    colors = shown(hardware)
    assert colors[0] == BUSY and colors[-1] == BASELINE_STATE.color
    if expected == 130:
        assert colors == [BUSY, BASELINE_STATE.color]  # no result signal after Ctrl+C


def test_run_never_starts_if_first_lighting_update_fails(hardware, baseline, monkeypatch):
    hardware["backend"] = RecordingBackend(fail_on={1})
    started = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: started.append(cmd) or 0)
    assert cli.main(["run", "--", "program"]) == 1
    assert started == []


def test_run_never_starts_with_a_damaged_profile(hardware, baseline, monkeypatch):
    profile_path().write_text("{bad", encoding="utf-8")
    started = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: started.append(cmd) or 0)
    assert cli.main(["run", "--", "program"]) == 1
    assert started == [] and hardware["backend"].states == []


def test_run_without_a_profile_restores_the_default_base(hardware, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 0)
    assert cli.main(["run", "--seconds", "0", "--", "program"]) == 0
    assert hardware["backend"].states[-1] == load_config().preset("normal")


def test_run_keeps_exit_code_when_restore_fails(hardware, baseline, monkeypatch, capsys):
    hardware["backend"] = RecordingBackend(fail_on={3})
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 9)
    assert cli.main(["run", "--seconds", "0", "--", "program"]) == 9
    assert "profile apply" in capsys.readouterr().err


def test_run_keeps_exit_code_when_result_signal_fails(hardware, baseline, monkeypatch):
    hardware["backend"] = RecordingBackend(fail_on={2})
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 5)
    assert cli.main(["run", "--seconds", "0", "--", "program"]) == 5
    assert shown(hardware)[-1] == BASELINE_STATE.color


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "61", "soon"])
def test_run_rejects_bad_durations(value):
    with pytest.raises(SystemExit):
        cli.main(["run", "--seconds", value, "--", "program"])


def test_run_real_child_exit_code(hardware, baseline):
    assert cli.main(["run", "--seconds", "0", "--", sys.executable, "-c", "raise SystemExit(23)"]) == 23
    assert shown(hardware)[-1] == BASELINE_STATE.color


# --- Gigabyte route and the older interfaces ---------------------------------

@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("powershell", 20)])
def test_powershell_route_errors_become_backend_errors(error):
    def runner(*args, **kwargs):
        assert kwargs["timeout"] == 20
        raise error

    with pytest.raises(BackendError, match="unavailable"):
        PowerShellBackend(runner=runner).apply(LightState())


def test_older_flag_style(hardware):
    assert cli.main(["--status", "busy"]) == 0
    assert cli.main(["--pattern", "Breathe", "--color", "Cyan", "--brightness", "5", "--speed", "8"]) == 0
    assert hardware["backend"].states == [load_config().preset("busy"), LightState("breathe", (0, 255, 255), 5, 8)]


def test_older_flag_style_reports_failure(hardware):
    hardware["backend"] = RecordingBackend(fail_on={1})
    assert cli.main(["--status", "busy"]) == 1


def test_python_functions_return_true_or_false(monkeypatch):
    backend = RecordingBackend(fail_on={2})
    monkeypatch.setattr("aero_rgb.backends.create_backend", lambda *a, **k: backend)
    assert aero_rgb.set_status("busy") is True
    assert aero_rgb.set_keyboard_led(pattern="Static", color="#00FFCC", brightness=5) is False
    assert aero_rgb.set_keyboard_led(color="notacolor") is False

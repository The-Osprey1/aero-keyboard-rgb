import io
import json
import sys
import tempfile
import threading

import pytest

from aero_rgb import hooks
from aero_rgb.backends import DryRunBackend
from aero_rgb.cli import main
from aero_rgb.config import config_from_dict
from aero_rgb.daemon import Daemon
from aero_rgb.engine import PRIORITY_ALERT, PRIORITY_TASK, PRIORITY_WARNING
from aero_rgb.ipc import IpcServer
from aero_rgb.protocol import color_packet, mode_packet
from aero_rgb.state import BUILTIN_PRESETS


@pytest.fixture(autouse=True)
def private_temp(tmp_path, monkeypatch):
    # SessionMemory writes to the temp folder; keep each test's files separate.
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))


def feed(monkeypatch, **payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


def shown(preset):
    """The dry-run text for both packets of a built-in preset."""
    state = BUILTIN_PRESETS[preset]
    return [f"[{p.hex(' ').upper()}]" for p in (color_packet(state.color),
                                               mode_packet(state.pattern, state.speed, state.brightness))]


def assert_shows(text, preset):
    for packet in shown(preset):
        assert packet in text, f"{preset} not shown"


# --------------------------------------------------------------------------- decisions

@pytest.mark.parametrize("event, payload, last, expected", [
    ("UserPromptSubmit", {}, None, ("show", "busy", PRIORITY_TASK)),
    ("Notification", {}, None, ("show", "attention", PRIORITY_WARNING)),
    ("Notification", {"notification_type": "permission_prompt"}, "busy", ("show", "attention", PRIORITY_WARNING)),
    ("Notification", {"notification_type": "idle_prompt"}, "success", ("show", "attention", PRIORITY_WARNING)),
    ("Notification", {"notification_type": "auth_success"}, "busy", ("ignore", None, PRIORITY_TASK)),
    ("Notification", {"notification_type": "plugin_notification"}, None, ("ignore", None, PRIORITY_TASK)),
    ("PostToolUse", {}, "attention", ("show", "busy", PRIORITY_TASK)),
    ("PostToolUse", {}, "busy", ("ignore", None, PRIORITY_TASK)),
    ("PostToolUse", {}, None, ("ignore", None, PRIORITY_TASK)),
    ("Stop", {}, "busy", ("show", "success", PRIORITY_ALERT)),
    ("SessionEnd", {}, "busy", ("clear", None, PRIORITY_TASK)),
    ("PreToolUse", {}, None, ("ignore", None, PRIORITY_TASK)),
    (None, {}, None, ("ignore", None, PRIORITY_TASK)),
])
def test_decide(event, payload, last, expected):
    decision = hooks.decide(event, payload, last)
    assert (decision.action, decision.preset, decision.priority) == expected


def test_success_is_shown_for_a_limited_time():
    assert hooks.decide("Stop", {}, None, result_seconds=7).duration == 7
    assert hooks.decide("UserPromptSubmit", {}, None).duration is None


def test_session_key_is_safe_as_a_file_name():
    assert hooks.session_key({"session_id": "../../etc/passwd"}) == "etcpasswd"
    assert hooks.session_key({}) == "default"
    assert hooks.session_key({"session_id": "///"}) == "default"
    assert hooks.layer_name({"session_id": "abc-123"}) == "claude-abc-123"


def test_session_memory(tmp_path):
    memory = hooks.SessionMemory(tmp_path / "mem")
    assert memory.get("s1") is None
    memory.set("s1", "attention")
    assert memory.get("s1") == "attention"
    memory.forget("s1")
    assert memory.get("s1") is None
    memory.forget("s1")  # forgetting twice is fine


# --------------------------------------------------------------------------- the command

def test_hook_never_writes_to_standard_output(monkeypatch, capsys):
    # Claude Code adds a UserPromptSubmit hook's standard output to Claude's context.
    feed(monkeypatch, session_id="s", hook_event_name="UserPromptSubmit")
    assert main(["hook", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert_shows(err, "busy")


def test_permission_prompt_flow(monkeypatch, capsys):
    events = [
        ("UserPromptSubmit", {}, "busy"),
        ("Notification", {"notification_type": "permission_prompt"}, "attention"),
        ("PostToolUse", {"tool_name": "Bash"}, "busy"),  # you approved; Claude is working again
        ("PostToolUse", {"tool_name": "Edit"}, None),  # already busy: no new write
        ("Stop", {}, "success"),
    ]
    for event, extra, preset in events:
        feed(monkeypatch, session_id="flow", hook_event_name=event, **extra)
        assert main(["hook", "--dry-run"]) == 0
        out, err = capsys.readouterr()
        assert out == ""
        if preset:
            assert_shows(err, preset)
        else:
            assert err == ""


def test_notifications_that_do_not_need_you_change_nothing(monkeypatch, capsys):
    feed(monkeypatch, session_id="s", hook_event_name="Notification", notification_type="auth_success")
    assert main(["hook", "--dry-run"]) == 0
    assert capsys.readouterr() == ("", "")


def test_session_end_returns_to_the_base_preset(monkeypatch, capsys):
    feed(monkeypatch, session_id="s", hook_event_name="SessionEnd", reason="exit")
    assert main(["hook", "--dry-run"]) == 0
    assert_shows(capsys.readouterr().err, "normal")


def test_event_can_be_given_as_an_argument(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["hook", "Stop", "--dry-run"]) == 0
    assert_shows(capsys.readouterr().err, "success")


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", ""])
def test_unreadable_input_is_ignored(monkeypatch, capsys, stdin):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert main(["hook", "--dry-run"]) == 0
    assert capsys.readouterr() == ("", "")


def test_broken_settings_file_does_not_fail_the_hook(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("this is [not valid", encoding="utf-8")
    feed(monkeypatch, session_id="s", hook_event_name="Stop")
    assert main(["hook", "--dry-run", "--config", str(bad)]) == 0
    out, err = capsys.readouterr()
    assert out == "" and "aero-rgb hook:" in err


def test_no_keyboard_reachable_does_not_fail_the_hook(monkeypatch, capsys):
    from aero_rgb import backends, cli

    def no_device(*args, **kwargs):
        raise backends.BackendError("no device")

    monkeypatch.setattr(cli, "daemon_running", lambda port: False)
    monkeypatch.setattr(backends.HidBackend, "open", no_device)
    monkeypatch.setattr(backends.PowerShellBackend, "available", staticmethod(lambda: False))
    feed(monkeypatch, session_id="s", hook_event_name="Stop")
    assert main(["hook"]) == 0
    out, err = capsys.readouterr()
    assert out == "" and "No way to reach the keyboard" in err


def test_attention_can_be_restyled_in_settings(tmp_path, monkeypatch, capsys):
    settings = tmp_path / "settings.toml"
    settings.write_text('[presets.attention]\npattern = "breathe"\ncolor = "magenta"\nbrightness = 10\nspeed = 9\n',
                        encoding="utf-8")
    feed(monkeypatch, session_id="s", hook_event_name="Notification", notification_type="permission_prompt")
    assert main(["hook", "--dry-run", "--config", str(settings)]) == 0
    assert "rgb=#FF00FF" in capsys.readouterr().err


# --------------------------------------------------------------------------- with the background program

def test_hook_uses_a_layer_per_session_in_the_background_program(tmp_path, monkeypatch, clock):
    server = IpcServer(0)
    settings = tmp_path / "settings.toml"
    settings.write_text(f"[ipc]\nport = {server.port}\n", encoding="utf-8")
    daemon = Daemon(config_from_dict({"ipc": {"port": server.port}}), DryRunBackend(echo=None),
                    monitors=[], ipc=server, clock=clock, log=lambda message: None)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            daemon.tick()
            stop.wait(0.01)

    thread = threading.Thread(target=loop)
    thread.start()

    def hook(session, event, **extra):
        feed(monkeypatch, session_id=session, hook_event_name=event, **extra)
        assert main(["hook", "--config", str(settings)]) == 0

    def layers():
        return {layer.name: layer for layer in daemon.engine.layers()}

    try:
        hook("one", "UserPromptSubmit")
        hook("two", "Notification", notification_type="permission_prompt")
        current = layers()
        assert current["client:claude-one"].priority == PRIORITY_TASK
        assert current["client:claude-two"].priority == PRIORITY_WARNING
        # The session that needs you wins over the one that is busy.
        assert daemon.engine.top().name == "client:claude-two"
        assert daemon.engine.current() == BUILTIN_PRESETS["attention"]

        hook("two", "Stop")
        assert layers()["client:claude-two"].priority == PRIORITY_ALERT
        clock.advance(11)  # "done" is shown for 10 seconds, then the layer goes away
        daemon.engine.update()
        assert "client:claude-two" not in layers()

        hook("one", "SessionEnd")
        assert "client:claude-one" not in layers()
        assert daemon.engine.top().name == "base"
    finally:
        stop.set()
        thread.join()
        server.close()

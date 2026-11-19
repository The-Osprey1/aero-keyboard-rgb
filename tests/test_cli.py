import io
import json
import sys

import pytest

from aero_rgb import cli
from aero_rgb.protocol import format_packet, build_packets, resolve_preset


def packet_line(preset):
    """The dry-run 'color packet' line for a preset."""
    return format_packet(build_packets(resolve_preset(preset))[0])


@pytest.fixture(autouse=True)
def no_backend_env(monkeypatch):
    monkeypatch.delenv("AERO_RGB_BACKEND", raising=False)


def test_presets_lists_everything(capsys):
    assert cli.main(["presets"]) == 0
    out = capsys.readouterr().out
    for name in ("normal", "busy", "success", "attention", "error", "restore"):
        assert name in out


def test_status_dry_run_prints_packets(capsys):
    assert cli.main(["status", "busy", "--dry-run"]) == 0
    assert packet_line("busy") in capsys.readouterr().out


def test_backend_can_come_from_environment(monkeypatch, capsys):
    monkeypatch.setenv("AERO_RGB_BACKEND", "dry-run")
    assert cli.main(["status", "error"]) == 0
    assert packet_line("error") in capsys.readouterr().out


def test_set_dry_run(capsys):
    assert cli.main(["set", "-p", "breathe", "-c", "#00FFCC", "-b", "8", "-s", "8", "--dry-run"]) == 0
    assert "00 14 00 01 00 FF CC 00" in capsys.readouterr().out


def test_set_rejects_bad_color(capsys):
    assert cli.main(["set", "-c", "notacolor", "--dry-run"]) == 1
    assert "unknown color" in capsys.readouterr().err


def test_no_backend_gives_a_clear_error(capsys):
    if sys.platform == "win32":
        pytest.skip("Control Center may be installed on a Windows machine")
    assert cli.main(["status", "busy"]) == 1
    assert "--dry-run" in capsys.readouterr().err


def test_run_success_shows_busy_then_success(capsys):
    code = cli.main(["run", "--dry-run", "--", sys.executable, "-c", "pass"])
    err = capsys.readouterr().err
    assert code == 0
    assert err.index(packet_line("busy")) < err.index(packet_line("success"))


def test_run_failure_returns_the_exit_code_and_shows_error(capsys):
    code = cli.main(["run", "--dry-run", "--", sys.executable, "-c", "raise SystemExit(3)"])
    err = capsys.readouterr().err
    assert code == 3
    assert packet_line("error") in err
    assert packet_line("success") not in err


def test_run_works_without_the_double_dash(capsys):
    assert cli.main(["run", "--dry-run", sys.executable, "-c", "pass"]) == 0


def test_run_custom_presets(capsys):
    cli.main(["run", "--dry-run", "--busy", "focus", "--success", "rainbow", "--", sys.executable, "-c", "pass"])
    err = capsys.readouterr().err
    assert packet_line("focus") in err and packet_line("rainbow") in err


def test_run_missing_command(capsys):
    assert cli.main(["run", "--dry-run", "--", "definitely-not-a-real-command-xyz"]) == 127
    assert "command not found" in capsys.readouterr().err


def test_run_needs_a_command(capsys):
    assert cli.main(["run", "--dry-run"]) == 2


def test_run_still_runs_the_command_when_lighting_fails(monkeypatch, capsys):
    # Force the Control Center backend; on a machine without it, every apply() fails.
    monkeypatch.setenv("AERO_RGB_BACKEND", "control-center")
    monkeypatch.setattr(
        "aero_rgb.backends.ControlCenterBackend.command",
        lambda self, state: ["definitely-not-powershell-xyz"],
    )
    code = cli.main(["run", "--", sys.executable, "-c", "raise SystemExit(4)"])
    assert code == 4
    assert "warning" in capsys.readouterr().err


@pytest.mark.parametrize(
    "event, preset",
    [("UserPromptSubmit", "busy"), ("Notification", "attention"), ("Stop", "success"), ("SessionEnd", "normal")],
)
def test_hook_reads_event_from_stdin(monkeypatch, capsys, event, preset):
    payload = {"session_id": "abc", "hook_event_name": event}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "--dry-run"]) == 0
    assert packet_line(preset) in capsys.readouterr().err


def test_hook_event_argument(capsys):
    assert cli.main(["hook", "Stop", "--dry-run"]) == 0
    assert packet_line("success") in capsys.readouterr().err


def test_hook_writes_nothing_to_stdout(monkeypatch, capsys):
    # Claude Code adds a UserPromptSubmit hook's standard output to Claude's context.
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit"})))
    cli.main(["hook", "--dry-run"])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("kind", ["permission_prompt", "idle_prompt", "agent_needs_input", None])
def test_hook_notifications_that_need_you(monkeypatch, capsys, kind):
    payload = {"hook_event_name": "Notification", "message": "Claude needs your permission"}
    if kind:
        payload["notification_type"] = kind
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "--dry-run"]) == 0
    assert packet_line("attention") in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["auth_success", "plugin_notification", "quota_auto_resume_fired"])
def test_hook_ignores_notifications_that_do_not_need_you(monkeypatch, capsys, kind):
    payload = {"hook_event_name": "Notification", "notification_type": kind}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "--dry-run"]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("stdin", ["not json", "[]", json.dumps({"hook_event_name": "PreToolUse"}), ""])
def test_hook_ignores_unknown_or_garbage_input(monkeypatch, capsys, stdin):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert cli.main(["hook", "--dry-run"]) == 0
    assert capsys.readouterr().err == ""


def test_hook_never_fails_even_without_a_backend(monkeypatch, capsys):
    if sys.platform == "win32":
        pytest.skip("Control Center may be installed on a Windows machine")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop"})))
    assert cli.main(["hook"]) == 0


def test_decode(capsys):
    assert cli.main(["decode", "00", "14", "00", "01", "00", "FF", "FF", "00", "EC"]) == 0
    out = capsys.readouterr().out
    assert "set color" in out and "matches the spec formula" in out

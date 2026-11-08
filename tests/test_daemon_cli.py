from datetime import datetime

from aero_rgb.backends import DryRunBackend
from aero_rgb.cli import main
from aero_rgb.config import config_from_dict, default_config_path
from aero_rgb.daemon import Daemon, ScheduleMonitor
from aero_rgb.ipc import IpcServer, daemon_running, request
from aero_rgb.state import LightState


def make_daemon(clock, config=None, ipc=None):
    return Daemon(config or config_from_dict({}), DryRunBackend(echo=None), monitors=[], ipc=ipc, clock=clock,
                  log=lambda message: None)


def test_daemon_handles_client_messages(clock):
    daemon = make_daemon(clock)
    assert daemon.handle({"cmd": "ping"}) == {"ok": True}
    reply = daemon.handle({"cmd": "show", "layer": "run-1", "state": {"pattern": "breathe", "color": "cyan"},
                           "priority": 999, "duration": 5})
    assert reply["ok"]
    top = daemon.engine.top()
    assert top.name == "client:run-1" and top.priority == 100  # priority capped
    assert daemon.handle({"cmd": "clear", "layer": "run-1"})["ok"]
    assert daemon.engine.top().name == "base"
    assert daemon.handle({"cmd": "base", "state": {"color": "pink"}})["ok"]
    assert daemon.engine.current().color == (255, 105, 180)
    assert not daemon.handle({"cmd": "show", "layer": "x", "state": {"color": "nope"}})["ok"]
    assert not daemon.handle({"cmd": "explode"})["ok"]


def test_client_layers_cannot_live_forever(clock):
    daemon = make_daemon(clock)
    daemon.handle({"cmd": "show", "layer": "stuck", "state": {"color": "red"}})
    clock.advance(6 * 60 * 60 + 1)
    assert daemon.engine.top().name == "base"


def test_ipc_round_trip(clock):
    server = IpcServer(0)  # any free port
    port = server.port
    daemon = make_daemon(clock, ipc=server)
    try:
        import threading

        stop = threading.Event()

        def loop():
            while not stop.is_set():
                daemon.tick()
                stop.wait(0.01)

        thread = threading.Thread(target=loop)
        thread.start()
        try:
            assert daemon_running(port)
            reply = request({"cmd": "status"}, port)
            assert reply["layers"][0]["name"] == "base"
        finally:
            stop.set()
            thread.join()
    finally:
        server.close()
    assert not daemon_running(port)


def test_schedule_switches_base_but_keeps_manual_choice(clock):
    config = config_from_dict({"schedule": [{"from": "22:00", "to": "07:00", "preset": "focus"}]})
    daemon = make_daemon(clock, config)
    now = [datetime(2026, 1, 1, 21, 0)]
    schedule = ScheduleMonitor(daemon.engine, config, wall_clock=lambda: now[0])
    schedule.tick(clock())
    manual = LightState("static", (1, 2, 3))
    daemon.engine.set_base(manual)
    clock.advance(31)
    schedule.tick(clock())
    assert daemon.engine.current() == manual  # no schedule change yet: manual choice stays
    now[0] = datetime(2026, 1, 1, 22, 1)
    clock.advance(31)
    schedule.tick(clock())
    assert daemon.engine.current() == config.preset("focus")


def test_cli_set_dry_run(capsys):
    assert main(["set", "--dry-run", "-p", "breathe", "-c", "#00FFCC", "-b", "8", "-z", "2=red"]) == 0
    out = capsys.readouterr().out
    assert "[00 14 00 01 00 FF CC 00 1F]" in out
    assert "zone=2 rgb=#FF0000" in out


def test_cli_bad_color_is_a_friendly_error(capsys):
    assert main(["--dry-run", "set", "-c", "blurple"]) == 1
    assert "Unknown color" in capsys.readouterr().err


def test_cli_config_init_and_custom_preset(capsys):
    assert main(["config", "init"]) == 0
    assert default_config_path().exists()
    assert main(["config", "init"]) == 1  # won't overwrite
    assert main(["preset", "--dry-run", "gaming"]) == 0
    assert "#8A2BE2" in capsys.readouterr().out


def test_cli_run_reports_exit_code(capsys):
    import sys

    assert main(["run", "--dry-run", "--", sys.executable, "-c", "raise SystemExit(4)"]) == 4
    out = capsys.readouterr().out
    assert "#00FFFF" in out and "#FF0000" in out  # busy, then error


def test_cli_copy(tmp_path, capsys):
    src = tmp_path / "file.bin"
    src.write_bytes(b"z" * 5000)
    assert main(["copy", "--dry-run", str(src), str(tmp_path / "out.bin")]) == 0
    assert (tmp_path / "out.bin").read_bytes() == b"z" * 5000

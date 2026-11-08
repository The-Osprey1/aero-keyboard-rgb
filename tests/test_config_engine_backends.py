from datetime import time
from types import SimpleNamespace

import pytest

from aero_rgb.backends import (BackendError, DryRunBackend, HidInterfaceInfo, PowerShellBackend, choose_interface,
                               create_backend)
from aero_rgb.config import EXAMPLE_CONFIG, config_from_dict, load_config
from aero_rgb.engine import PRIORITY_ALERT, PRIORITY_TASK, LightEngine
from aero_rgb.state import LightState


# --- config -----------------------------------------------------------------

def test_missing_config_file_uses_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.base_state() == cfg.preset("normal")
    assert cfg.battery.mode == "warning"


def test_example_config_is_valid():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg.preset("gaming").color == (0x8A, 0x2B, 0xE2)
    assert cfg.preset("late-night").brightness == 2
    assert cfg.usb.kind_colors["storage"] == (0, 255, 255)


def test_custom_colors_presets_and_schedule():
    cfg = config_from_dict({
        "colors": {"night": "#331100"},
        "presets": {"Cozy": {"color": "night", "brightness": 2}},
        "base": {"preset": "normal"},
        "schedule": [{"from": "22:00", "to": "07:00", "preset": "cozy"}],
        "battery": {"mode": "always", "gradient": [[0, "night"], [1, "white"]]},
        "usb": {"kind_colors": {"storage": "night"}},
    })
    assert cfg.preset("cozy").color == (0x33, 0x11, 0x00)
    assert cfg.base_state(time(23, 30)) == cfg.preset("cozy")
    assert cfg.base_state(time(6, 59)) == cfg.preset("cozy")
    assert cfg.base_state(time(12, 0)) == cfg.preset("normal")
    assert cfg.battery.gradient[0] == (0.0, (0x33, 0x11, 0x00))
    assert cfg.usb.kind_colors["storage"] == (0x33, 0x11, 0x00)
    assert cfg.usb.kind_colors["phone"] == (0x8A, 0x2B, 0xE2)  # defaults kept


@pytest.mark.parametrize("data,message", [
    ({"devise": {}}, "devise"),
    ({"battery": {"mood": "always"}}, "mood"),
    ({"battery": {"mode": "sometimes"}}, "mode"),
    ({"base": {"preset": "nonexistent"}}, "Unknown preset"),
    ({"device": {"backend": "magic"}}, "backend"),
    ({"colors": {"x": "not a color"}}, "Unknown color"),
])
def test_config_mistakes_are_reported(data, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict(data)


def test_bad_toml_names_the_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[device\nbackend = 1")
    with pytest.raises(ValueError, match="config.toml"):
        load_config(path)


# --- engine -----------------------------------------------------------------

RED = LightState("static", (255, 0, 0))
BLUE = LightState("static", (0, 0, 255))
GREEN = LightState("static", (0, 255, 0))


def test_highest_priority_wins_and_falls_back(engine, backend):
    engine.update()
    engine.set_layer("task", RED, PRIORITY_TASK)
    engine.set_layer("alert", BLUE, PRIORITY_ALERT)
    engine.update()
    assert backend.states[-1] == BLUE
    engine.clear("alert")
    engine.update()
    assert backend.states[-1] == RED
    engine.clear("task")
    engine.update()
    assert backend.states[-1] == engine.layers()[0].state  # base again


def test_timed_layers_expire(engine, backend, clock):
    engine.set_layer("pulse", BLUE, PRIORITY_ALERT, duration=3)
    engine.update()
    assert backend.states[-1] == BLUE
    clock.advance(3.1)
    engine.update()
    assert backend.states[-1].color == (255, 255, 255)


def test_no_write_when_nothing_changed(engine, backend):
    engine.update()
    engine.update()
    engine.set_layer("same", engine.current(), PRIORITY_TASK)
    engine.update()
    assert len(backend.states) == 1


def test_writes_are_rate_limited(backend, clock):
    engine = LightEngine(backend, RED, min_interval=0.5, clock=clock)
    assert engine.update()
    engine.set_base(BLUE)
    assert not engine.update()  # too soon
    clock.advance(0.6)
    assert engine.update()
    assert backend.states == [RED, BLUE]


def test_equal_priority_most_recent_wins_and_unchanged_reset_keeps_order(engine):
    engine.set_layer("a", RED, PRIORITY_TASK)
    engine.set_layer("b", BLUE, PRIORITY_TASK)
    engine.set_layer("a", RED, PRIORITY_TASK)  # unchanged: must not jump ahead of b
    assert engine.current() == BLUE
    engine.set_layer("a", GREEN, PRIORITY_TASK)  # changed: now newest
    assert engine.current() == GREEN


def test_backend_errors_are_logged_not_raised(clock):
    class Broken(DryRunBackend):
        def apply(self, state):
            raise BackendError("unplugged")

    messages = []
    engine = LightEngine(Broken(echo=None), RED, clock=clock, log=messages.append)
    assert not engine.update()
    assert "unplugged" in messages[0]


# --- backends ---------------------------------------------------------------

def test_dry_run_backend_records_packets():
    backend = DryRunBackend(echo=None)
    backend.apply(LightState("breathe", (0, 255, 255), 8, 8, ((2, (1, 2, 3)),)))
    assert len(backend.packets) == 3


def test_powershell_backend_builds_command_per_zone():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    backend = PowerShellBackend(runner=runner)
    backend.apply(LightState("rainbow", (0, 255, 204), 8, 6, ((2, (255, 0, 0)),)))
    assert len(calls) == 2
    first = calls[0]
    assert first[first.index("-Pattern") + 1] == "cycle"
    assert first[first.index("-Color") + 1] == "#00FFCC"
    assert calls[1][calls[1].index("-Zone") + 1] == "2"


def test_powershell_backend_reports_failure():
    backend = PowerShellBackend(runner=lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no dll"))
    with pytest.raises(BackendError, match="no dll"):
        backend.apply(LightState())


def info(interface, page):
    return HidInterfaceInfo(b"path%d" % interface, interface, page, 1, "")


def test_choose_interface_prefers_vendor_pages_and_honors_settings():
    interfaces = [info(0, 0x01), info(1, 0xFF01), info(3, 0xFF02)]
    assert choose_interface(interfaces).interface_number == 1
    assert choose_interface(interfaces, interface=3).interface_number == 3
    assert choose_interface(interfaces, usage_page=0x01).interface_number == 0
    with pytest.raises(BackendError):
        choose_interface(interfaces, interface=9)


def test_create_backend_dry_run_and_unknown():
    assert isinstance(create_backend("dry-run", echo=None), DryRunBackend)
    with pytest.raises(BackendError):
        create_backend("telepathy")

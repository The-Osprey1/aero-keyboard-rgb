import sys
from pathlib import Path

import pytest

from aero_rgb.config import BatteryConfig, TransferConfig, UsbConfig
from aero_rgb.monitors.battery import (LAYER, LAYER_FLASH, LAYER_LOW_PULSE, LAYER_WARNING, BatteryMonitor,
                                       BatteryReading, battery_color, battery_state)
from aero_rgb.monitors.transfer import (LAYER as T_LAYER, LAYER_DONE, TransferMonitor, activity_state,
                                        copy_with_progress, find_progress, progress_state)
from aero_rgb.monitors.usb import (PortMap, UsbDevice, UsbMonitor, build_windows_snapshot, diff, linux_snapshot,
                                   path_matches)


# --- battery ----------------------------------------------------------------

def test_battery_colors():
    cfg = BatteryConfig()
    assert battery_color(100, cfg) == (0, 255, 0)
    assert battery_color(0, cfg) == (255, 0, 0)
    assert battery_color(52, cfg) == battery_color(50, cfg) == (255, 255, 0)  # 5% steps
    assert battery_state(BatteryReading(60, True), cfg).pattern == "breathe"  # charging
    assert battery_state(BatteryReading(100, True), cfg).pattern == "static"  # full
    assert battery_state(BatteryReading(60, False), cfg).pattern == "static"


def run_battery(engine, clock, mode, readings, **extra):
    cfg = BatteryConfig(mode=mode, **extra)
    values = iter(readings)
    monitor = BatteryMonitor(engine, cfg, reader=lambda: next(values))
    for _ in readings:
        monitor.tick(clock())
        clock.advance(cfg.poll_seconds)
    return monitor


def test_battery_always_mode(engine, clock):
    run_battery(engine, clock, "always", [BatteryReading(100, False)])
    assert engine.top().name == LAYER
    assert engine.current().color == (0, 255, 0)


def test_battery_on_change_only_flashes_when_charger_changes(engine, clock):
    run_battery(engine, clock, "on_change", [BatteryReading(70, False), BatteryReading(70, False)])
    assert not engine.has_layer(LAYER_FLASH)
    run_battery(engine, clock, "on_change", [BatteryReading(70, False), BatteryReading(70, True)])
    assert engine.has_layer(LAYER_FLASH)
    clock.advance(10)
    assert not engine.has_layer(LAYER_FLASH)


def test_battery_low_pulses_once_and_critical_stays(engine, clock):
    monitor = run_battery(engine, clock, "warning", [BatteryReading(19, False)])
    assert engine.has_layer(LAYER_LOW_PULSE)
    clock.advance(10)
    monitor.reader = lambda: BatteryReading(18, False)
    monitor.tick(clock())
    assert not engine.has_layer(LAYER_LOW_PULSE)  # only once per crossing
    monitor.reader = lambda: BatteryReading(9, False)
    clock.advance(3)
    monitor.tick(clock())
    assert engine.has_layer(LAYER_WARNING)
    monitor.reader = lambda: BatteryReading(9, True)  # plugged in -> warning goes away
    clock.advance(3)
    monitor.tick(clock())
    assert not engine.has_layer(LAYER_WARNING)


def test_battery_off_and_missing_battery(engine, clock):
    run_battery(engine, clock, "off", [BatteryReading(5, False)])
    BatteryMonitor(engine, BatteryConfig(mode="always"), reader=lambda: None).tick(clock())
    assert [l.name for l in engine.layers()] == ["base"]


# --- usb --------------------------------------------------------------------

def make_sysfs(root: Path) -> None:
    def device(name, cls, product, interfaces=(), vendor="abcd", prod="1234"):
        d = root / name
        d.mkdir(parents=True)
        (d / "bDeviceClass").write_text(cls + "\n")
        (d / "product").write_text(product + "\n")
        (d / "idVendor").write_text(vendor)
        (d / "idProduct").write_text(prod)
        for index, iface in enumerate(interfaces):
            i = root / f"{name}:1.{index}"
            i.mkdir()
            (i / "bInterfaceClass").write_text(iface)

    device("1-2", "00", "Flash Drive", ["08"])
    device("1-3", "09", "USB Hub")
    device("1-3.1", "00", "Pixel", ["06", "ff"])
    device("2-1", "00", "Mouse", ["03"])
    (root / "usb1").mkdir()  # root hub: ignored


@pytest.mark.skipif(sys.platform == "win32",
                    reason="the fake device folders use Linux names like '1-2:1.0', which Windows can't create; "
                           "linux_snapshot only runs on Linux, where this test does run")
def test_linux_snapshot(tmp_path):
    make_sysfs(tmp_path)
    devices = {d.name: d for d in linux_snapshot(tmp_path).values()}
    assert set(devices) == {"Flash Drive", "USB Hub", "Pixel", "Mouse"}
    assert devices["Flash Drive"].kind == "storage"
    assert devices["Pixel"].kind == "phone"
    assert devices["Pixel"].paths == ("1-3.1",)
    assert devices["Mouse"].kind == "input"
    assert devices["USB Hub"].kind == "hub"


def test_windows_snapshot_folds_child_functions_into_parent():
    records = [
        {"instance_id": r"USB\ROOT_HUB30\4&1", "name": "Root hub", "service": "USBHUB3", "class": "USB", "paths": []},
        {"instance_id": r"USB\VID_04E8&PID_6860\R58M", "name": "Galaxy", "service": "usbccgp", "class": "USB",
         "paths": ["PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(2)"]},
        {"instance_id": r"USB\VID_04E8&PID_6860&MI_00\6&2B", "name": "MTP", "service": "WUDFWpdMtp",
         "class": "WPD", "paths": ["PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(2)#USBMI(0)"]},
        {"instance_id": r"USB\VID_0781&PID_5581\4C53", "name": "SanDisk", "service": "USBSTOR", "class": "USB",
         "paths": ["PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(5)", "ACPI(_SB_)#ACPI(PCI0)#ACPI(XHC_)#ACPI(RHUB)#ACPI(SS01)"]},
    ]
    devices = build_windows_snapshot(records)
    assert set(devices) == {r"USB\VID_04E8&PID_6860\R58M", r"USB\VID_0781&PID_5581\4C53"}
    assert devices[r"USB\VID_04E8&PID_6860\R58M"].kind == "phone"
    assert devices[r"USB\VID_0781&PID_5581\4C53"].kind == "storage"
    assert len(devices[r"USB\VID_0781&PID_5581\4C53"].paths) == 2


def test_path_matching_respects_boundaries():
    assert path_matches("1-2", "1-2")
    assert path_matches("1-2.3", "1-2")
    assert not path_matches("1-20", "1-2")
    assert path_matches("PCIROOT(0)#USB(2)#USB(1)", "PCIROOT(0)#USB(2)")
    assert not path_matches("PCIROOT(0)#USB(20)", "PCIROOT(0)#USB(2)")


def dev(path, kind="storage", name="Thing", id_=None):
    return UsbDevice(id_ or path, name, kind, (path,))


def test_port_map_learn_save_load_and_match(tmp_path):
    ports = PortMap(path=tmp_path / "ports.json")
    ports.learn("left", dev("1-2"), "Left side", (0, 0, 255))
    ports.learn("left", dev("2-2"))  # USB 3 location of the same port
    ports.learn("hub-port", dev("1-2.4"), zone=3)
    ports.save()
    loaded = PortMap.load(tmp_path / "ports.json")
    assert loaded.ports["left"].paths == ["1-2", "2-2"]
    assert loaded.ports["left"].color == (0, 0, 255)
    assert loaded.match(dev("2-2")).name == "left"
    assert loaded.match(dev("1-2.1")).name == "left"
    assert loaded.match(dev("1-2.4")).name == "hub-port"  # most specific wins
    assert loaded.match(dev("3-1")) is None


def test_usb_monitor_pulses_on_plug_in_not_at_startup(engine, clock):
    snapshots = iter([{"a": dev("1-1", "input")},
                      {"a": dev("1-1", "input"), "b": dev("1-2", "storage")},
                      {"a": dev("1-1", "input")}])
    ports = PortMap()
    ports.learn("left", dev("9-9"), color=(0, 0, 255))
    monitor = UsbMonitor(engine, UsbConfig(), ports, scanner=lambda: next(snapshots))
    monitor.tick(clock())
    assert not engine.has_layer("usb")  # startup devices don't pulse
    clock.advance(1)
    monitor.tick(clock())
    assert engine.current().color == UsbConfig().kind_colors["storage"]
    assert engine.current().pattern == "breathe"
    clock.advance(1)
    monitor.tick(clock())  # unplugged
    assert engine.current().color == UsbConfig().unplug_color


def test_usb_monitor_uses_port_color_and_zone(engine, clock):
    snapshots = iter([{}, {"b": dev("1-2")}])
    ports = PortMap()
    ports.learn("left", dev("1-2"), color=(0, 0, 255), zone=2)
    monitor = UsbMonitor(engine, UsbConfig(), ports, scanner=lambda: next(snapshots))
    monitor.tick(clock())
    clock.advance(1)
    monitor.tick(clock())
    state = engine.current()
    assert state.color == (255, 255, 255)  # zone 1 keeps the base color
    assert state.zones == ((2, (0, 0, 255)),)


def test_usb_monitor_survives_scanner_errors(engine, clock):
    def broken():
        raise OSError("access denied")

    messages = []
    monitor = UsbMonitor(engine, UsbConfig(), PortMap(), scanner=broken, log=messages.append)
    monitor.tick(clock())
    clock.advance(1)
    monitor.tick(clock())
    assert len(messages) == 1


def test_diff():
    added, removed = diff({"a": dev("1"), "b": dev("2")}, {"b": dev("2"), "c": dev("3")})
    assert [d.id for d in added] == ["3"] and [d.id for d in removed] == ["1"]


# --- transfer ---------------------------------------------------------------

PATTERN = TransferConfig().title_pattern


def test_find_progress():
    titles = ["Visual Studio Code", "45% complete", "Copying 1 item - 12 % Complete", "100% sure"]
    assert find_progress(titles, PATTERN) == 12
    assert find_progress(["Inbox"], PATTERN) is None
    assert find_progress(["45 % abgeschlossen"], r"(\d{1,3})\s*%\s*abgeschlossen") == 45


def test_progress_and_activity_states():
    cfg = TransferConfig()
    assert progress_state(0, cfg).color == cfg.start_color
    assert progress_state(100, cfg).color == cfg.end_color
    assert progress_state(51, cfg) == progress_state(54, cfg)  # 5% steps
    assert activity_state(600, cfg).speed < activity_state(150_000, cfg).speed


def test_transfer_monitor_uses_window_percentage_then_flashes_done(engine, clock):
    titles = [["37% complete"]]
    monitor = TransferMonitor(engine, TransferConfig(), titles=lambda: titles[0], disk_counters=dict)
    monitor.tick(clock())
    assert engine.top().name == T_LAYER
    assert engine.current() == progress_state(37, TransferConfig())
    titles[0] = []
    clock.advance(1)
    monitor.tick(clock())
    assert engine.has_layer(T_LAYER)  # waits idle_seconds before calling it done
    clock.advance(5)
    monitor.tick(clock())
    assert not engine.has_layer(T_LAYER)
    assert engine.top().name == LAYER_DONE


def test_transfer_monitor_watches_only_new_drives(engine, clock):
    counters = {"sda": 0}
    monitor = TransferMonitor(engine, TransferConfig(), titles=list, disk_counters=lambda: dict(counters))
    monitor.tick(clock())
    counters["sda"] = 500 * 1024 * 1024  # internal drive busy: ignored
    counters["sdb"] = 0  # USB drive appears
    clock.advance(1)
    monitor.tick(clock())
    assert not engine.has_layer(T_LAYER)
    counters["sdb"] = 20 * 1024 * 1024  # 20 MB in 1 s
    clock.advance(1)
    monitor.tick(clock())
    assert engine.current().pattern == "breathe"


def test_copy_with_progress(tmp_path):
    src = tmp_path / "photos"
    (src / "2026").mkdir(parents=True)
    (src / "a.jpg").write_bytes(b"x" * 3000)
    (src / "2026" / "b.jpg").write_bytes(b"y" * 1000)
    single = tmp_path / "notes.txt"
    single.write_text("hello")
    dest = tmp_path / "usb"
    seen = []
    copied = copy_with_progress([src, single], dest, seen.append, chunk_size=1000)
    assert copied == 4005
    assert (dest / "photos" / "2026" / "b.jpg").read_bytes() == b"y" * 1000
    assert (dest / "notes.txt").read_text() == "hello"
    assert seen[0] == 0 and seen[-1] == 100 and seen == sorted(seen)

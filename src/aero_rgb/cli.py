"""The ``aero-rgb`` command."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from . import __version__
from .backends import Backend, BackendError, DryRunBackend, HidBackend, choose_interface, create_backend, list_hid_interfaces
from .colors import NAMED_COLORS, parse_color, to_hex
from .config import EXAMPLE_CONFIG, Config, default_config_path, load_config
from .engine import PRIORITY_ALERT, PRIORITY_TASK
from .ipc import daemon_running, request
from .protocol import PATTERN_ALIASES, PATTERNS, build_packet, CMD_SET_COLOR, decode_packet, mode_packet
from .state import LightState


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


# ---------------------------------------------------------------------------
# Output: talk to the background program if it's running, otherwise to the keyboard
# ---------------------------------------------------------------------------

class Output:
    def __init__(self, args: argparse.Namespace, config: Config):
        self.config = config
        self.backend: Optional[Backend] = None
        forced = args.dry_run or args.backend is not None
        self.via_daemon = not forced and daemon_running(config.ipc_port)
        if not self.via_daemon:
            name = "dry-run" if args.dry_run else (args.backend or config.device.backend)
            self.backend = create_backend(name, config.device)

    def _send(self, message: dict) -> None:
        reply = request(message, self.config.ipc_port, timeout=1.0)
        if not reply:
            raise BackendError("The background program did not answer.")
        if not reply.get("ok"):
            raise BackendError(f"The background program refused the request: {reply.get('error')}")

    def base(self, state: LightState) -> None:
        if self.via_daemon:
            self._send({"cmd": "base", "state": state.to_dict()})
        else:
            assert self.backend
            self.backend.apply(state)

    def show(self, layer: str, state: LightState, priority: int = PRIORITY_TASK, duration: Optional[float] = None) -> None:
        if self.via_daemon:
            self._send({"cmd": "show", "layer": layer, "state": state.to_dict(), "priority": priority, "duration": duration})
        else:
            assert self.backend
            self.backend.apply(state)

    def clear(self, layer: str) -> None:
        if self.via_daemon:
            self._send({"cmd": "clear", "layer": layer})
        else:
            assert self.backend
            self.backend.apply(self.config.base_state())

    def close(self) -> None:
        if self.backend:
            self.backend.close()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def parse_zone(text: str, config: Config) -> tuple:
    if "=" not in text:
        raise argparse.ArgumentTypeError("use ZONE=COLOR, for example 2=red")
    zone, color = text.split("=", 1)
    return int(zone), config.color(color)


def cmd_set(args: argparse.Namespace, config: Config) -> int:
    state = LightState(args.pattern, config.color(args.color), args.brightness, args.speed,
                       tuple(parse_zone(z, config) for z in args.zone or []))
    out = Output(args, config)
    try:
        out.base(state)
    finally:
        out.close()
    print(f"Keyboard set: {state.describe()}" + (" (via background program)" if out.via_daemon else ""))
    return 0


def cmd_preset(args: argparse.Namespace, config: Config) -> int:
    state = config.preset(args.name)
    out = Output(args, config)
    try:
        out.base(state)
    finally:
        out.close()
    print(f"Preset '{args.name}': {state.describe()}" + (" (via background program)" if out.via_daemon else ""))
    return 0


def cmd_list(args: argparse.Namespace, config: Config) -> int:
    print("Presets:")
    for name in config.preset_names():
        try:
            print(f"  {name:<12} {config.preset(name).describe()}")
        except ValueError:
            pass
    print("\nPatterns:", ", ".join(sorted(PATTERNS)), f"(also: {', '.join(sorted(PATTERN_ALIASES))})")
    print("\nColors:")
    for name, rgb in sorted(NAMED_COLORS.items()):
        print(f"  {name:<12} {to_hex(rgb)}")
    for name in sorted(config.colors):
        print(f"  {name:<12} {to_hex(config.color(name))}  (yours)")
    return 0


def ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_probe(args: argparse.Namespace, config: Config) -> int:
    if args.dry_run:
        print("Dry run: these are the packets a probe would send for cyan.")
        backend = DryRunBackend(config.device.protocol_options())
        backend.apply(LightState("static", parse_color("cyan"), 10))
        return 0
    try:
        interfaces = list_hid_interfaces()
    except BackendError as exc:
        eprint(exc)
        return 1
    if not interfaces:
        eprint("The lighting device (USB 0414:8104) was not found.")
        return 1
    print("Lighting device interfaces found:")
    for info in interfaces:
        vendor = "  <- vendor-defined, likely candidate" if info.usage_page >= 0xFF00 else ""
        print(f"  {info.describe()}{vendor}")

    options = config.device.protocol_options()
    test_state = LightState("static", parse_color("cyan"), 10)

    if args.find_interface:
        candidates = [i for i in interfaces if i.usage_page >= 0xFF00] + [i for i in interfaces if i.usage_page < 0xFF00]
        for info in candidates:
            print(f"\nSending bright cyan to {info.describe()} ...")
            try:
                with HidBackend(info, options) as backend:
                    backend.apply(test_state)
            except BackendError as exc:
                print(f"  failed: {exc}")
                continue
            if ask("Did the keyboard turn cyan?"):
                print("\nAdd these lines under [device] in your settings file "
                      f"({config.path or default_config_path()}):")
                print("  backend = \"hid\"")
                print(f"  hid_interface = {info.interface_number}")
                print(f"  hid_usage_page = 0x{info.usage_page:04X}")
                return 0
        print("\nNo interface changed the color. Try 'aero-rgb probe --checksum' next, and see docs/HARDWARE_TESTING.md.")
        return 1

    try:
        info = choose_interface(interfaces, config.device.hid_interface, config.device.hid_usage_page)
    except BackendError as exc:
        eprint(exc)
        return 1

    if args.checksum:
        with HidBackend(info, options) as backend:
            body = [0x00, CMD_SET_COLOR, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0x00]
            variants = [("formula (255 - sum)", (255 - sum(body[1:8])) & 0xFF),
                        ("worked example (254 - sum)", (254 - sum(body[1:8])) & 0xFF)]
            for label, value in variants:
                packet = bytes(body + [value])
                print(f"\nTrying checksum {label}: {decode_packet(packet)}")
                backend.send(packet)
                time.sleep(options.latch_delay)
                backend.send(mode_packet("static", 1, 10, options))
                if ask("Did the keyboard turn cyan?"):
                    print(f"The {label} checksum works.")
                    return 0
        print("Neither checksum worked; the interface may be wrong. Try 'aero-rgb probe --find-interface'.")
        return 1

    if args.zones:
        colors = [(1, "red"), (2, "green"), (3, "blue"), (4, "magenta")]
        with HidBackend(info, options) as backend:
            for zone, name in colors:
                print(f"Zone {zone} -> {name}")
                backend.send(build_packet(CMD_SET_COLOR, 0x00, zone, *parse_color(name)))
                time.sleep(options.latch_delay)
            backend.send(mode_packet("static", 1, 10, options))
        print("\nWhat do you see?")
        print("  - Whole keyboard one color: the keyboard is single-zone (normal for the AERO X16).")
        print("  - Different areas in red / green / blue / magenta: it has zones! Note which area is which,")
        print("    then give ports a zone with: aero-rgb ports calibrate <name> --zone <number>")
        return 0

    print(f"\nUsing {info.describe()}. Sending bright cyan...")
    with HidBackend(info, options) as backend:
        backend.apply(test_state)
    print("If the keyboard turned cyan, direct control works. If not, run: aero-rgb probe --find-interface")
    return 0


def cmd_daemon(args: argparse.Namespace, config: Config) -> int:
    from .daemon import Daemon
    from .ipc import IpcServer

    if daemon_running(config.ipc_port):
        eprint("The background program is already running.")
        return 1
    name = "dry-run" if args.dry_run else (args.backend or config.device.backend)
    backend = create_backend(name, config.device)
    try:
        ipc = IpcServer(config.ipc_port)
    except OSError as exc:
        eprint(f"Could not open local port {config.ipc_port} ({exc}); 'run' and 'copy' won't reach the background program.")
        ipc = None
    print(f"Using {backend.name} route. Settings: {config.path if config.path and config.path.exists() else 'defaults'}")
    Daemon(config, backend, ipc=ipc).run()
    return 0


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    reply = request({"cmd": "status"}, config.ipc_port)
    if not reply:
        print("The background program is not running. Start it with: aero-rgb daemon")
        return 1
    print("Background program is running. Lighting layers (top one is showing):")
    for layer in reply.get("layers", []):
        state = LightState.from_dict(layer["state"])
        print(f"  {layer['name']:<24} priority {layer['priority']:<4} {state.describe()}")
    return 0


def _ports(config: Config):
    from .monitors.usb import PortMap
    return PortMap.load(config.ports_path, config.colors)


def cmd_ports(args: argparse.Namespace, config: Config) -> int:
    from .monitors.usb import diff, snapshot

    ports = _ports(config)
    if args.ports_cmd == "list":
        if not ports.ports:
            print("No ports named yet. Plug a device in with: aero-rgb ports calibrate left-usb-c")
        for port in ports.ports.values():
            color = to_hex(port.color) if port.color else "by device type"
            zone = f", zone {port.zone}" if port.zone else ""
            print(f"{port.name}: {port.label or '(no label)'} - color {color}{zone}")
            for path in port.paths:
                print(f"    {path}")
        print(f"\nSaved in {ports.path}")
        return 0
    if args.ports_cmd == "remove":
        if ports.ports.pop(args.name, None) is None:
            eprint(f"No port named {args.name!r}")
            return 1
        ports.save()
        print(f"Removed {args.name}")
        return 0

    # calibrate
    color = config.color(args.color) if args.color else None
    before = snapshot()
    print(f"Plug a device directly into the port you want to call '{args.name}' (not through a hub).")
    print(f"Waiting up to {args.timeout:.0f} seconds...")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        current = snapshot()
        added, _ = diff(before, current)
        added = [d for d in added if d.paths]
        if added:
            device = added[0]
            port = ports.learn(args.name, device, args.label or "", color, args.zone)
            ports.save()
            print(f"Learned '{args.name}' from {device.name}:")
            for path in device.paths:
                print(f"    {path}")
            print("Tip: USB-C and blue USB ports report different locations for fast (USB 3) and slow (USB 2) devices.")
            print(f"     Run this again with the other kind of device to teach '{port.name}' both.")
            return 0
        before = current
    eprint("No new device appeared. Nothing was saved.")
    return 1


def cmd_usb(args: argparse.Namespace, config: Config) -> int:
    from .monitors.usb import snapshot

    ports = _ports(config)
    devices = snapshot()
    if not devices:
        print("No USB devices found (or this system isn't supported).")
        return 0
    for device in sorted(devices.values(), key=lambda d: d.name.lower()):
        port = ports.match(device)
        where = f"  [port: {port.name}]" if port else ""
        print(f"{device.name} ({device.kind}){where}")
        for path in device.paths:
            print(f"    {path}")
    return 0


def cmd_battery(args: argparse.Namespace, config: Config) -> int:
    from .monitors.battery import battery_state, read_battery

    reading = read_battery()
    if reading is None:
        print("No battery found (or psutil isn't installed: pip install psutil).")
        return 1
    plugged = {True: "plugged in", False: "on battery", None: "charger state unknown"}[reading.plugged]
    state = battery_state(reading, config.battery)
    print(f"Battery {reading.percent:.0f}%, {plugged}. Keyboard color for this: {state.describe()}")
    if args.show:
        out = Output(args, config)
        try:
            out.show("battery-peek", state, PRIORITY_ALERT, config.battery.show_seconds)
        finally:
            out.close()
    return 0


def cmd_run(args: argparse.Namespace, config: Config) -> int:
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        eprint("Give a command to run, for example: aero-rgb run -- pytest")
        return 2
    layer = f"run-{os.getpid()}"
    out = Output(args, config)
    try:
        out.show(layer, config.preset("busy"))
        try:
            code = subprocess.call(command, shell=sys.platform == "win32" and len(command) == 1)
        except FileNotFoundError:
            eprint(f"Command not found: {command[0]}")
            code = 127
        except KeyboardInterrupt:
            code = 130
        result = config.preset("success" if code == 0 else "error")
        if out.via_daemon:
            out.clear(layer)
            out.show(layer + "-result", result, PRIORITY_ALERT, args.result_seconds)
        else:
            out.show(layer, result)
    finally:
        out.close()
    return code


def cmd_copy(args: argparse.Namespace, config: Config) -> int:
    from .monitors.transfer import copy_with_progress, done_state, progress_state

    layer = f"copy-{os.getpid()}"
    out = Output(args, config)
    last = {"step": -1}
    width = shutil.get_terminal_size((80, 20)).columns - 20

    def on_progress(percent: float) -> None:
        step = int(percent // 5)
        bar = int(width * percent / 100)
        sys.stdout.write(f"\r[{'#' * bar}{'.' * (width - bar)}] {percent:5.1f}%")
        sys.stdout.flush()
        if step != last["step"]:
            last["step"] = step
            out.show(layer, progress_state(percent, config.transfer), PRIORITY_TASK + 1)

    try:
        copied = copy_with_progress([Path(s) for s in args.sources], Path(args.destination), on_progress)
        print(f"\nCopied {copied / 1_048_576:.1f} MB")
        if out.via_daemon:
            out.clear(layer)
            out.show(layer + "-done", done_state(config.transfer), PRIORITY_ALERT, config.transfer.done_flash_seconds)
        else:
            out.show(layer, done_state(config.transfer))
        return 0
    except (OSError, KeyboardInterrupt) as exc:
        print()
        eprint(f"Copy failed: {exc or 'cancelled'}")
        out.show(layer + "-failed", config.preset("error"), PRIORITY_ALERT, 5)
        if out.via_daemon:
            out.clear(layer)
        return 1
    finally:
        out.close()


def cmd_config(args: argparse.Namespace, config: Config) -> int:
    path = Path(args.config) if args.config else default_config_path()
    if args.config_cmd == "path":
        print(path)
        return 0
    if args.config_cmd == "check":
        load_config(path)
        print(f"{path}: OK" if path.exists() else f"{path} doesn't exist yet; defaults are in use.")
        return 0
    if path.exists() and not args.force:
        eprint(f"{path} already exists. Use --force to replace it.")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_CONFIG, path)
    print(f"Created {path}. Open it in a text editor to personalize your keyboard.")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    def add_common(target: argparse.ArgumentParser, suppress: bool) -> None:
        # The same options work before or after the command name ("aero-rgb probe --dry-run").
        extra = {"default": argparse.SUPPRESS} if suppress else {}
        target.add_argument("--config", help="settings file to use", **({"default": None} if not suppress else extra))
        target.add_argument("--backend", choices=["auto", "hid", "powershell", "dry-run"],
                            help="how to reach the keyboard (skips the background program)", **extra)
        target.add_argument("--dry-run", action="store_true", help="print the bytes instead of sending them", **extra)

    common = argparse.ArgumentParser(add_help=False)
    add_common(common, suppress=True)
    parser = argparse.ArgumentParser(prog="aero-rgb", description="Keyboard lighting for GIGABYTE AERO / AORUS laptops.")
    parser.add_argument("--version", action="version", version=f"aero-rgb {__version__}")
    add_common(parser, suppress=False)
    sub = parser.add_subparsers(dest="command_name", required=True, metavar="COMMAND")
    original_add_parser = sub.add_parser

    def add_parser(*args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        kwargs.setdefault("parents", [common])
        return original_add_parser(*args, **kwargs)

    sub.add_parser = add_parser  # type: ignore[method-assign]

    p = sub.add_parser("set", help="set a pattern and color")
    p.add_argument("--pattern", "-p", default="static", help="static, breathe, cycle, rgbpulse, cyclepulse")
    p.add_argument("--color", "-c", default="white", help="color name or hex code (#RRGGBB)")
    p.add_argument("--brightness", "-b", type=int, default=7, help="0-10")
    p.add_argument("--speed", "-s", type=int, default=5, help="1-10")
    p.add_argument("--zone", "-z", action="append", metavar="N=COLOR", help="extra zone color (multi-zone keyboards)")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("preset", aliases=["status"], help="apply a preset (busy, success, focus, your own...)")
    p.add_argument("name")
    p.set_defaults(func=cmd_preset)

    sub.add_parser("list", help="show presets, patterns and colors").set_defaults(func=cmd_list)

    p = sub.add_parser("probe", help="test the direct USB route on this laptop")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--find-interface", action="store_true", help="try each interface and ask which one works")
    group.add_argument("--checksum", action="store_true", help="find out which checksum the chip accepts")
    group.add_argument("--zones", action="store_true", help="check whether the keyboard has separate zones")
    p.set_defaults(func=cmd_probe)

    sub.add_parser("daemon", help="run the background program (battery, USB, transfers, schedule)").set_defaults(func=cmd_daemon)
    sub.add_parser("layers", help="show what the background program is displaying").set_defaults(func=cmd_status)

    p = sub.add_parser("ports", help="name your USB ports so each can have its own color")
    port_sub = p.add_subparsers(dest="ports_cmd", required=True)
    c = port_sub.add_parser("calibrate", help="learn a port by plugging something into it")
    c.add_argument("name", help="a name such as left-usb-c")
    c.add_argument("--label", help="description, such as 'Left side, front'")
    c.add_argument("--color", help="pulse color for this port (default: by device type)")
    c.add_argument("--zone", type=int, help="keyboard zone nearest this port (multi-zone keyboards only)")
    c.add_argument("--timeout", type=float, default=30.0)
    port_sub.add_parser("list", help="show named ports")
    r = port_sub.add_parser("remove", help="forget a port")
    r.add_argument("name")
    p.set_defaults(func=cmd_ports)

    sub.add_parser("usb", help="list plugged-in USB devices and their locations").set_defaults(func=cmd_usb)

    p = sub.add_parser("battery", help="show the battery level and its color")
    p.add_argument("--show", action="store_true", help="also show the color on the keyboard for a few seconds")
    p.set_defaults(func=cmd_battery)

    p = sub.add_parser("run", help="run a command: cyan while running, then green (passed) or red (failed)")
    p.add_argument("--result-seconds", type=float, default=10.0, help="how long to show the result (background program only)")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("copy", help="copy files with progress shown on the keyboard")
    p.add_argument("sources", nargs="+")
    p.add_argument("destination")
    p.set_defaults(func=cmd_copy)

    p = sub.add_parser("config", help="create or check your settings file")
    config_sub = p.add_subparsers(dest="config_cmd", required=True)
    i = config_sub.add_parser("init", help="create a settings file with every option explained")
    i.add_argument("--force", action="store_true")
    config_sub.add_parser("path", help="print where the settings file lives")
    config_sub.add_parser("check", help="check the settings file for mistakes")
    p.set_defaults(func=cmd_config)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(Path(args.config) if args.config else None)
        return int(args.func(args, config) or 0)
    except (ValueError, BackendError) as exc:
        eprint(f"Error: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # output piped into a program that stopped reading
        return 0


if __name__ == "__main__":
    sys.exit(main())

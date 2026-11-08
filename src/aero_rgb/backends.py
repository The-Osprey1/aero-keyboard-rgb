"""Ways of sending a lighting state to the keyboard.

* :class:`HidBackend` sends the 9-byte commands straight to the lighting chip over USB
  (needs the ``hidapi`` package; works without Gigabyte's software, on Windows or Linux).
* :class:`PowerShellBackend` drives Gigabyte Control Center's own files through
  ``keyboard_led.ps1`` (Windows only, Control Center must be installed).
* :class:`DryRunBackend` records and prints the bytes instead of sending them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .colors import to_hex
from .protocol import (PRODUCT_ID, VENDOR_ID, ProtocolOptions, decode_packet, software_pattern_id,
                       state_packets)
from .state import LightState

POWERSHELL_SCRIPT = Path(__file__).parent / "keyboard_led.ps1"
GIGABYTE_LIBRARY = Path(r"C:\Program Files\GIGABYTE\Control Center\Lib\GBT_rgbLaptop_UC\RgbLaptop.dll")


class BackendError(RuntimeError):
    pass


class Backend(ABC):
    name = "base"

    @abstractmethod
    def apply(self, state: LightState) -> None:
        """Show ``state`` on the keyboard. Raises :class:`BackendError` on failure."""

    def close(self) -> None:
        pass

    def __enter__(self) -> "Backend":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class DryRunBackend(Backend):
    name = "dry-run"

    def __init__(self, options: ProtocolOptions = ProtocolOptions(), echo: Optional[Callable[[str], None]] = print):
        self.options = options
        self.echo = echo
        self.packets: List[bytes] = []
        self.states: List[LightState] = []

    def apply(self, state: LightState) -> None:
        self.states.append(state)
        packets = state_packets(state.zone_colors(), state.pattern, state.speed, state.brightness, self.options)
        self.packets.extend(packets)
        if self.echo:
            self.echo(f"[dry-run] {state.describe()}")
            for packet in packets:
                self.echo(f"           {decode_packet(packet)}")


@dataclass
class HidInterfaceInfo:
    path: bytes
    interface_number: int
    usage_page: int
    usage: int
    product: str

    def describe(self) -> str:
        return (f"interface {self.interface_number}, usage page 0x{self.usage_page:04X}, "
                f"usage 0x{self.usage:02X}, product {self.product!r}")


def _import_hid() -> Any:
    try:
        import hid  # type: ignore[import-not-found]
    except ImportError as exc:
        raise BackendError("The direct USB route needs the 'hidapi' package: pip install hidapi") from exc
    if not hasattr(hid, "enumerate"):
        raise BackendError("The installed 'hid' module is not hidapi. Run: pip uninstall hid && pip install hidapi")
    return hid


def list_hid_interfaces() -> List[HidInterfaceInfo]:
    hid = _import_hid()
    found = []
    for item in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        found.append(HidInterfaceInfo(
            path=item["path"],
            interface_number=int(item.get("interface_number", -1)),
            usage_page=int(item.get("usage_page", 0)),
            usage=int(item.get("usage", 0)),
            product=str(item.get("product_string") or ""),
        ))
    return sorted(found, key=lambda i: (i.interface_number, i.usage_page, i.usage))


def choose_interface(interfaces: List[HidInterfaceInfo], interface: Optional[int] = None,
                     usage_page: Optional[int] = None) -> HidInterfaceInfo:
    """Pick the interface that accepts lighting commands.

    With no settings, prefer vendor-defined usage pages (0xFF00 and up), which is where
    custom commands normally go. ``aero-rgb probe --find-interface`` confirms the right one.
    """
    candidates = interfaces
    if interface is not None:
        candidates = [i for i in candidates if i.interface_number == interface]
    if usage_page is not None:
        candidates = [i for i in candidates if i.usage_page == usage_page]
    if interface is None and usage_page is None:
        vendor = [i for i in candidates if i.usage_page >= 0xFF00]
        candidates = vendor or candidates
    if not candidates:
        raise BackendError(
            f"No matching lighting interface found for USB device {VENDOR_ID:04X}:{PRODUCT_ID:04X}. "
            "Run 'aero-rgb probe' to list what is available."
        )
    return candidates[0]


class HidBackend(Backend):
    name = "hid"

    def __init__(self, info: HidInterfaceInfo, options: ProtocolOptions = ProtocolOptions(),
                 sleep: Callable[[float], None] = time.sleep):
        hid = _import_hid()
        self.info = info
        self.options = options
        self._sleep = sleep
        self._device = hid.device()
        try:
            self._device.open_path(info.path)
        except (OSError, IOError) as exc:
            hint = " On Linux, see docs/HARDWARE_TESTING.md for the permission rule." if sys.platform.startswith("linux") else ""
            raise BackendError(f"Could not open the lighting interface ({info.describe()}): {exc}.{hint}") from exc

    @classmethod
    def open(cls, interface: Optional[int] = None, usage_page: Optional[int] = None,
             options: ProtocolOptions = ProtocolOptions()) -> "HidBackend":
        interfaces = list_hid_interfaces()
        if not interfaces:
            raise BackendError(f"USB device {VENDOR_ID:04X}:{PRODUCT_ID:04X} not found. Is this a GIGABYTE AERO/AORUS laptop?")
        return cls(choose_interface(interfaces, interface, usage_page), options)

    def send(self, packet: bytes) -> None:
        written = self._device.send_feature_report(list(packet))
        if written is not None and written < 0:
            raise BackendError(f"The lighting chip rejected a command: {decode_packet(packet)}")

    def apply(self, state: LightState) -> None:
        packets = state_packets(state.zone_colors(), state.pattern, state.speed, state.brightness, self.options)
        for index, packet in enumerate(packets):
            if index:
                self._sleep(self.options.latch_delay)
            self.send(packet)

    def close(self) -> None:
        try:
            self._device.close()
        except Exception:  # pragma: no cover - best effort
            pass


class PowerShellBackend(Backend):
    """Uses Gigabyte Control Center's own files. Slow (about half a second per change)."""

    name = "powershell"

    def __init__(self, script: Path = POWERSHELL_SCRIPT, runner: Callable[..., Any] = subprocess.run):
        self.script = script
        self._run = runner
        self.executable = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32" and GIGABYTE_LIBRARY.exists()

    def command(self, state: LightState, zone: int, rgb: Any) -> List[str]:
        software_pattern_id(state.pattern)  # validates the pattern name
        return [
            self.executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.script),
            "-Pattern", state.pattern, "-Color", to_hex(rgb), "-Brightness", str(state.brightness),
            "-Speed", str(state.speed), "-Zone", str(zone), "-Quiet",
        ]

    def apply(self, state: LightState) -> None:
        for zone, rgb in state.zone_colors():
            result = self._run(self.command(state, zone, rgb), capture_output=True, text=True)
            if result.returncode != 0:
                raise BackendError(f"keyboard_led.ps1 failed ({result.returncode}): {(result.stderr or result.stdout).strip()}")


def create_backend(name: str = "auto", device_config: Any = None, echo: Optional[Callable[[str], None]] = print) -> Backend:
    """Create the backend named in settings. ``auto`` tries direct USB, then PowerShell."""
    interface = getattr(device_config, "hid_interface", None)
    usage_page = getattr(device_config, "hid_usage_page", None)
    options = device_config.protocol_options() if device_config is not None else ProtocolOptions()
    if name == "dry-run":
        return DryRunBackend(options, echo)
    if name == "hid":
        return HidBackend.open(interface, usage_page, options)
    if name == "powershell":
        if sys.platform != "win32":
            raise BackendError("The PowerShell route only works on Windows.")
        return PowerShellBackend()
    if name != "auto":
        raise BackendError(f"Unknown backend {name!r}")

    errors: Dict[str, str] = {}
    try:
        return HidBackend.open(interface, usage_page, options)
    except BackendError as exc:
        errors["hid"] = str(exc)
    if PowerShellBackend.available():
        return PowerShellBackend()
    errors["powershell"] = "Gigabyte Control Center is not installed (or this is not Windows)."
    details = "\n".join(f"  - {key}: {value}" for key, value in errors.items())
    raise BackendError(f"No way to reach the keyboard was found:\n{details}\nUse --dry-run to test without hardware.")

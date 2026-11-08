"""Pulse the keyboard when a USB device is plugged in or removed.

Each physical port is recognised by its *location path*: a string the operating system
gives every USB device that describes the chain of controllers and ports it is attached
through. ``aero-rgb ports calibrate <name>`` records the path for each port once, after
which plug-ins can be matched to a named port with its own color (and zone, if the
keyboard has more than one).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..colors import RGB, parse_color, to_hex
from ..config import UsbConfig
from ..engine import PRIORITY_ALERT, LightEngine
from ..state import LightState

LAYER = "usb"
KIND_RANK = ["storage", "phone", "camera", "audio", "input", "hub", "other"]


@dataclass(frozen=True)
class UsbDevice:
    id: str
    name: str
    kind: str
    paths: Tuple[str, ...]


Snapshot = Dict[str, UsbDevice]


def best_kind(kinds: Iterable[str]) -> str:
    found = set(kinds)
    ranked = [k for k in KIND_RANK if k in found]
    return ranked[0] if ranked else "other"


# ---------------------------------------------------------------------------
# Linux: /sys/bus/usb/devices/<bus>-<port>[.<port>...]
# ---------------------------------------------------------------------------

LINUX_DEVICE_NAME = re.compile(r"^\d+-\d+(\.\d+)*$")
LINUX_CLASS_KINDS = {"01": "audio", "03": "input", "06": "phone", "08": "storage", "09": "hub", "0e": "camera"}


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def linux_snapshot(root: Path = Path("/sys/bus/usb/devices")) -> Snapshot:
    devices: Snapshot = {}
    if not root.exists():
        return devices
    for entry in root.iterdir():
        name = entry.name
        if not LINUX_DEVICE_NAME.match(name):
            continue  # skips root hubs ("usb1") and interfaces ("1-2:1.0")
        classes = [_read(entry / "bDeviceClass").lower()]
        for interface in root.glob(f"{name}:*"):
            classes.append(_read(interface / "bInterfaceClass").lower())
        kind = best_kind(LINUX_CLASS_KINDS.get(c, "other") for c in classes if c and c != "00")
        product = _read(entry / "product") or f"USB device {_read(entry / 'idVendor')}:{_read(entry / 'idProduct')}"
        manufacturer = _read(entry / "manufacturer")
        label = f"{manufacturer} {product}".strip() if manufacturer and manufacturer not in product else product
        device_id = f"{name}/{_read(entry / 'idVendor')}:{_read(entry / 'idProduct')}/{_read(entry / 'serial')}"
        devices[device_id] = UsbDevice(device_id, label, kind, (name,))
    return devices


# ---------------------------------------------------------------------------
# Windows: SetupAPI, through ctypes (no extra packages needed)
# ---------------------------------------------------------------------------

WINDOWS_SERVICE_KINDS = {"usbstor": "storage", "uaspstor": "storage", "hidusb": "input", "usbaudio": "audio",
                         "usbaudio2": "audio", "usbvideo": "camera", "wudfwpdmtp": "phone", "wpdupfltr": "phone",
                         "usbhub": "hub", "usbhub3": "hub"}
WINDOWS_CLASS_KINDS = {"wpd": "phone", "androidusbdevice": "phone", "applemobiledevice": "phone",
                       "media": "audio", "audioendpoint": "audio", "hidclass": "input", "keyboard": "input",
                       "mouse": "input", "camera": "camera", "image": "camera", "diskdrive": "storage"}
VID_PID = re.compile(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", re.IGNORECASE)


def windows_kind(service: str, device_class: str) -> str:
    return WINDOWS_SERVICE_KINDS.get(service.lower()) or WINDOWS_CLASS_KINDS.get(device_class.lower()) or "other"


def build_windows_snapshot(entries: Iterable[Dict[str, object]]) -> Snapshot:
    """Turn raw device records into a snapshot.

    Each record has ``instance_id``, ``name``, ``service``, ``class`` and ``paths``. Child
    functions of a multi-function device (instance ids containing ``&MI_``) are folded into
    their parent so the parent gets the most useful type (e.g. a phone's storage function).
    """
    records = list(entries)
    child_kinds: Dict[str, List[str]] = {}
    for record in records:
        instance = str(record["instance_id"]).upper()
        if "&MI_" in instance:
            match = VID_PID.search(instance)
            if match:
                child_kinds.setdefault(match.group(0), []).append(
                    windows_kind(str(record.get("service", "")), str(record.get("class", ""))))
    devices: Snapshot = {}
    for record in records:
        instance = str(record["instance_id"])
        upper = instance.upper()
        if "&MI_" in upper or upper.startswith("USB\\ROOT_HUB"):
            continue
        kinds = [windows_kind(str(record.get("service", "")), str(record.get("class", "")))]
        match = VID_PID.search(upper)
        if match:
            kinds.extend(child_kinds.get(match.group(0), []))
        paths = tuple(str(p) for p in record.get("paths", ()) if p)  # type: ignore[union-attr]
        devices[instance] = UsbDevice(instance, str(record.get("name") or instance), best_kind(kinds), paths)
    return devices


def _windows_records() -> List[Dict[str, object]]:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVINFO_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID), ("DevInst", wintypes.DWORD),
                    ("Reserved", ctypes.c_void_p)]

    HDEVINFO = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
    setupapi.SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
    setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [HDEVINFO, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
                                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [HDEVINFO, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
                                                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
    setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

    DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
    SPDRP_DEVICEDESC, SPDRP_SERVICE, SPDRP_CLASS = 0x00, 0x04, 0x07
    SPDRP_FRIENDLYNAME, SPDRP_LOCATION_PATHS = 0x0C, 0x23
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    handle = setupapi.SetupDiGetClassDevsW(None, "USB", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if handle in (None, INVALID_HANDLE):
        raise OSError(ctypes.get_last_error(), "SetupDiGetClassDevsW failed")

    def prop(data: SP_DEVINFO_DATA, key: int) -> List[str]:
        buffer = ctypes.create_string_buffer(4096)
        reg_type, needed = wintypes.DWORD(), wintypes.DWORD()
        ok = setupapi.SetupDiGetDeviceRegistryPropertyW(handle, ctypes.byref(data), key, ctypes.byref(reg_type),
                                                        buffer, ctypes.sizeof(buffer), ctypes.byref(needed))
        if not ok:
            return []
        text = buffer.raw[: needed.value].decode("utf-16-le", errors="replace")
        return [part for part in text.split("\x00") if part]

    records: List[Dict[str, object]] = []
    try:
        index = 0
        while True:
            data = SP_DEVINFO_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(data)):
                break  # ERROR_NO_MORE_ITEMS
            index += 1
            id_buffer = ctypes.create_unicode_buffer(512)
            if not setupapi.SetupDiGetDeviceInstanceIdW(handle, ctypes.byref(data), id_buffer, 512, None):
                continue
            name = (prop(data, SPDRP_FRIENDLYNAME) or prop(data, SPDRP_DEVICEDESC) or [""])[0]
            records.append({
                "instance_id": id_buffer.value,
                "name": name,
                "service": (prop(data, SPDRP_SERVICE) or [""])[0],
                "class": (prop(data, SPDRP_CLASS) or [""])[0],
                "paths": prop(data, SPDRP_LOCATION_PATHS),
            })
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)
    return records


def windows_snapshot() -> Snapshot:  # pragma: no cover - Windows only
    return build_windows_snapshot(_windows_records())


def snapshot() -> Snapshot:
    """Every USB device currently plugged in, keyed by a stable id."""
    if sys.platform == "win32":
        return windows_snapshot()
    if sys.platform.startswith("linux"):
        return linux_snapshot()
    return {}


def diff(old: Snapshot, new: Snapshot) -> Tuple[List[UsbDevice], List[UsbDevice]]:
    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    return added, removed


# ---------------------------------------------------------------------------
# Named ports
# ---------------------------------------------------------------------------

def path_matches(device_path: str, port_path: str) -> bool:
    """True if ``device_path`` is the port itself or something plugged in behind it (a hub)."""
    if device_path.lower() == port_path.lower():
        return True
    if not device_path.lower().startswith(port_path.lower()):
        return False
    return device_path[len(port_path)] in "#."


@dataclass
class Port:
    name: str
    paths: List[str] = field(default_factory=list)
    label: str = ""
    color: Optional[RGB] = None
    zone: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {"label": self.label, "color": to_hex(self.color) if self.color else None, "zone": self.zone,
                "paths": self.paths}


class PortMap:
    def __init__(self, ports: Optional[Dict[str, Port]] = None, path: Optional[Path] = None):
        self.ports: Dict[str, Port] = ports or {}
        self.path = path

    @classmethod
    def load(cls, path: Path, custom_colors: Optional[Dict[str, object]] = None) -> "PortMap":
        if not path.exists():
            return cls(path=path)
        data = json.loads(path.read_text())
        ports = {}
        for name, item in data.get("ports", {}).items():
            color = parse_color(item["color"], custom_colors) if item.get("color") else None  # type: ignore[arg-type]
            zone = int(item["zone"]) if item.get("zone") is not None else None
            ports[name] = Port(name, list(item.get("paths", [])), item.get("label", ""), color, zone)
        return cls(ports, path)

    def save(self) -> None:
        if self.path is None:
            raise ValueError("No file to save ports to")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"ports": {name: port.to_dict() for name, port in self.ports.items()}}
        self.path.write_text(json.dumps(data, indent=2) + "\n")

    def match(self, device: UsbDevice) -> Optional[Port]:
        """The named port the device is in. The longest (most specific) path wins."""
        best: Optional[Tuple[int, Port]] = None
        for port in self.ports.values():
            for port_path in port.paths:
                if any(path_matches(p, port_path) for p in device.paths):
                    if best is None or len(port_path) > best[0]:
                        best = (len(port_path), port)
        return best[1] if best else None

    def learn(self, name: str, device: UsbDevice, label: str = "", color: Optional[RGB] = None,
              zone: Optional[int] = None) -> Port:
        port = self.ports.setdefault(name, Port(name))
        for path in device.paths:
            if path not in port.paths:
                port.paths.append(path)
        if label:
            port.label = label
        if color is not None:
            port.color = color
        if zone is not None:
            port.zone = zone
        return port


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class UsbMonitor:
    def __init__(self, engine: LightEngine, cfg: UsbConfig, ports: PortMap,
                 scanner: Callable[[], Snapshot] = snapshot, log: Optional[Callable[[str], None]] = None):
        self.engine = engine
        self.cfg = cfg
        self.ports = ports
        self.scanner = scanner
        self.log = log
        self._known: Optional[Snapshot] = None
        self._next_poll = 0.0
        self._failed = False

    def color_for(self, device: UsbDevice, port: Optional[Port]) -> RGB:
        if port and port.color:
            return port.color
        return self.cfg.kind_colors.get(device.kind, self.cfg.default_color)

    def pulse_state(self, color: RGB, port: Optional[Port]) -> LightState:
        if port and port.zone and port.zone != 1:
            # Multi-zone keyboards: pulse only the zone nearest the port, keep the rest as they are.
            current = self.engine.current()
            return LightState("breathe", current.color, 10, 9, current.zones).with_zone(port.zone, color)
        return LightState("breathe", color, 10, 9)

    def tick(self, now: float) -> None:
        if not self.cfg.enabled or now < self._next_poll:
            return
        self._next_poll = now + self.cfg.poll_seconds
        try:
            current = self.scanner()
        except Exception as exc:  # keep the daemon alive if the device list can't be read
            if not self._failed and self.log:
                self.log(f"Could not read the USB device list: {exc}")
            self._failed = True
            return
        self._failed = False
        if self._known is None:
            self._known = current  # devices already plugged in at startup don't pulse
            return
        added, removed = diff(self._known, current)
        self._known = current
        for device in added:
            port = self.ports.match(device)
            if self.log:
                where = f" in port '{port.name}'" if port else ""
                self.log(f"USB plugged in: {device.name} ({device.kind}){where}")
            self.engine.set_layer(LAYER, self.pulse_state(self.color_for(device, port), port), PRIORITY_ALERT,
                                  duration=self.cfg.pulse_seconds)
        if removed and not added and self.cfg.pulse_on_unplug:
            device = removed[0]
            port = self.ports.match(device)
            if self.log:
                self.log(f"USB removed: {device.name}")
            self.engine.set_layer(LAYER, self.pulse_state(self.cfg.unplug_color, port), PRIORITY_ALERT,
                                  duration=self.cfg.pulse_seconds * 0.66)

"""Loading user settings from a TOML file."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .colors import RGB, ColorInput, parse_color
from .protocol import ProtocolOptions
from .state import BUILTIN_PRESETS, PRESET_ALIASES, LightState

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on older Pythons
    import tomli as tomllib

EXAMPLE_CONFIG = Path(__file__).parent / "data" / "config.example.toml"
APP_NAME = "aero-rgb"


def config_dir() -> Path:
    if os.environ.get("AERO_RGB_CONFIG_DIR"):
        return Path(os.environ["AERO_RGB_CONFIG_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def default_config_path() -> Path:
    if os.environ.get("AERO_RGB_CONFIG"):
        return Path(os.environ["AERO_RGB_CONFIG"])
    return config_dir() / "config.toml"


@dataclass
class DeviceConfig:
    backend: str = "auto"
    hid_interface: Optional[int] = None
    hid_usage_page: Optional[int] = None
    latch_delay_ms: int = 20
    min_write_interval_ms: int = 250
    static_speed: int = 2
    static_brightness_flag: int = 0

    def protocol_options(self) -> ProtocolOptions:
        return ProtocolOptions(
            static_speed=self.static_speed,
            static_brightness_flag=self.static_brightness_flag,
            latch_delay=self.latch_delay_ms / 1000.0,
        )


@dataclass
class ScheduleEntry:
    start: dtime
    end: dtime
    preset: str

    def contains(self, now: dtime) -> bool:
        if self.start <= self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end  # wraps past midnight


@dataclass
class BatteryConfig:
    mode: str = "warning"
    low_percent: int = 20
    critical_percent: int = 10
    show_seconds: float = 4.0
    brightness: int = 7
    gradient: List[Tuple[float, RGB]] = field(default_factory=lambda: [
        (0.0, parse_color("red")), (0.2, parse_color("orange")),
        (0.5, parse_color("yellow")), (1.0, parse_color("green")),
    ])
    poll_seconds: float = 2.0


@dataclass
class UsbConfig:
    enabled: bool = True
    pulse_seconds: float = 3.0
    pulse_on_unplug: bool = True
    unplug_color: RGB = parse_color("orange")
    default_color: RGB = parse_color("white")
    kind_colors: Dict[str, RGB] = field(default_factory=lambda: {
        "storage": parse_color("cyan"), "phone": parse_color("purple"), "input": parse_color("lime"),
        "audio": parse_color("gold"), "camera": parse_color("pink"),
    })
    poll_seconds: float = 1.0


@dataclass
class TransferConfig:
    enabled: bool = True
    title_pattern: str = r"(\d{1,3})\s*%\s*complete"
    start_color: RGB = parse_color("blue")
    end_color: RGB = parse_color("green")
    brightness: int = 8
    activity_threshold_kbps: float = 512.0
    idle_seconds: float = 4.0
    done_flash_seconds: float = 3.0
    only_new_drives: bool = True
    poll_seconds: float = 1.0


@dataclass
class Config:
    path: Optional[Path] = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    colors: Dict[str, ColorInput] = field(default_factory=dict)
    presets: Dict[str, LightState] = field(default_factory=dict)
    base_preset: str = "normal"
    on_exit: str = "restore"
    schedule: List[ScheduleEntry] = field(default_factory=list)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    usb: UsbConfig = field(default_factory=UsbConfig)
    transfer: TransferConfig = field(default_factory=TransferConfig)
    ipc_port: int = 47615

    def color(self, value: ColorInput) -> RGB:
        return parse_color(value, self.colors)

    def preset_names(self) -> List[str]:
        return sorted(set(BUILTIN_PRESETS) | set(PRESET_ALIASES) | set(self.presets))

    def preset(self, name: str) -> LightState:
        key = name.strip().lower()
        if key in self.presets:
            return self.presets[key]
        key = PRESET_ALIASES.get(key, key)
        if key in BUILTIN_PRESETS:
            return BUILTIN_PRESETS[key]
        raise ValueError(f"Unknown preset {name!r}. Available: {', '.join(self.preset_names())}")

    def base_state(self, now: Optional[dtime] = None) -> LightState:
        if now is not None:
            for entry in self.schedule:
                if entry.contains(now):
                    return self.preset(entry.preset)
        return self.preset(self.base_preset)

    @property
    def ports_path(self) -> Path:
        folder = self.path.parent if self.path else config_dir()
        return folder / "ports.json"


def _parse_time(value: Any) -> dtime:
    if isinstance(value, dtime):
        return value
    hours, minutes = str(value).strip().split(":")
    return dtime(int(hours), int(minutes))


def _check_keys(section: str, data: Mapping[str, Any], allowed: set) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown setting(s) in [{section}]: {', '.join(sorted(unknown))}")


def _apply_simple(section: str, target: Any, data: Mapping[str, Any], color_fields: Tuple[str, ...] = (),
                  config: Optional[Config] = None, skip: Tuple[str, ...] = ()) -> None:
    allowed = set(vars(target)) | set(skip)
    _check_keys(section, data, allowed)
    for key, value in data.items():
        if key in skip:
            continue
        if key in color_fields:
            value = config.color(value) if config else parse_color(value)
        else:
            current = getattr(target, key)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, float):
                value = float(value)
            elif isinstance(current, int) and not isinstance(value, bool):
                value = int(value)
        setattr(target, key, value)


def config_from_dict(data: Mapping[str, Any], path: Optional[Path] = None) -> Config:
    cfg = Config(path=path)
    _check_keys("top level", data, {"device", "colors", "presets", "base", "schedule", "battery", "usb", "transfer", "ipc"})

    _apply_simple("device", cfg.device, data.get("device", {}))
    if cfg.device.backend not in ("auto", "hid", "powershell", "dry-run"):
        raise ValueError(f"[device] backend must be auto, hid, powershell or dry-run, not {cfg.device.backend!r}")

    cfg.colors = {str(k).lower(): v for k, v in data.get("colors", {}).items()}
    for name, value in cfg.colors.items():
        cfg.color(name)  # validates every custom color early

    for name, preset in data.get("presets", {}).items():
        try:
            cfg.presets[str(name).lower()] = LightState.from_dict(preset, cfg.colors)
        except ValueError as exc:
            raise ValueError(f"[presets.{name}]: {exc}") from exc

    base = data.get("base", {})
    _check_keys("base", base, {"preset", "on_exit"})
    cfg.base_preset = str(base.get("preset", cfg.base_preset)).lower()
    cfg.on_exit = str(base.get("on_exit", cfg.on_exit)).lower()

    for index, entry in enumerate(data.get("schedule", [])):
        _check_keys(f"schedule #{index + 1}", entry, {"from", "to", "preset"})
        cfg.schedule.append(ScheduleEntry(_parse_time(entry["from"]), _parse_time(entry["to"]), str(entry["preset"]).lower()))

    battery = dict(data.get("battery", {}))
    gradient = battery.pop("gradient", None)
    _apply_simple("battery", cfg.battery, battery, config=cfg)
    if gradient is not None:
        cfg.battery.gradient = [(float(pos), cfg.color(col)) for pos, col in gradient]
    if cfg.battery.mode not in ("off", "warning", "on_change", "always"):
        raise ValueError(f"[battery] mode must be off, warning, on_change or always, not {cfg.battery.mode!r}")

    usb = dict(data.get("usb", {}))
    kind_colors = usb.pop("kind_colors", None)
    _apply_simple("usb", cfg.usb, usb, color_fields=("unplug_color", "default_color"), config=cfg)
    if kind_colors is not None:
        cfg.usb.kind_colors.update({str(k).lower(): cfg.color(v) for k, v in kind_colors.items()})

    _apply_simple("transfer", cfg.transfer, data.get("transfer", {}), color_fields=("start_color", "end_color"), config=cfg)

    ipc = data.get("ipc", {})
    _check_keys("ipc", ipc, {"port"})
    cfg.ipc_port = int(ipc.get("port", cfg.ipc_port))

    # Validate references to presets now rather than when the daemon is already running.
    cfg.preset(cfg.base_preset)
    if cfg.on_exit != "leave":
        cfg.preset(cfg.on_exit)
    for entry in cfg.schedule:
        cfg.preset(entry.preset)
    return cfg


def load_config(path: Optional[Path] = None) -> Config:
    """Load settings. A missing file is fine: every setting has a default."""
    path = Path(path) if path else default_config_path()
    if not path.exists():
        return Config(path=path)
    with open(path, "rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    try:
        return config_from_dict(data, path)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc

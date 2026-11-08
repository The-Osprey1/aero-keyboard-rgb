"""The lighting state model and built-in presets."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple

from .colors import RGB, ColorInput, parse_color, to_hex
from .protocol import SELF_COLORED_PATTERNS, clamp_brightness, clamp_speed, normalize_pattern


@dataclass(frozen=True)
class LightState:
    """What the keyboard should show.

    ``color`` is the main color (zone 1). ``zones`` optionally gives extra colors for other
    zones, as ``((zone, rgb), ...)``. Most AERO models have a single zone, so ``zones`` is
    usually empty.
    """

    pattern: str = "static"
    color: RGB = (255, 255, 255)
    brightness: int = 7
    speed: int = 5
    zones: Tuple[Tuple[int, RGB], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pattern", normalize_pattern(self.pattern))
        object.__setattr__(self, "color", parse_color(self.color))
        object.__setattr__(self, "brightness", clamp_brightness(self.brightness))
        object.__setattr__(self, "speed", clamp_speed(self.speed))
        zones = tuple(sorted((int(z), parse_color(c)) for z, c in dict(self.zones).items() if int(z) != 1))
        object.__setattr__(self, "zones", zones)

    def zone_colors(self) -> Tuple[Tuple[int, RGB], ...]:
        """Every zone with its color, zone 1 first."""
        return ((1, self.color),) + self.zones

    def with_zone(self, zone: int, color: RGB) -> "LightState":
        if zone == 1:
            return replace(self, color=color)
        zones = dict(self.zones)
        zones[zone] = color
        return replace(self, zones=tuple(zones.items()))

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "pattern": self.pattern,
            "color": to_hex(self.color),
            "brightness": self.brightness,
            "speed": self.speed,
        }
        if self.zones:
            data["zones"] = {str(z): to_hex(c) for z, c in self.zones}
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], custom_colors: Optional[Mapping[str, ColorInput]] = None,
                  base: Optional["LightState"] = None) -> "LightState":
        """Build a state from config/JSON data. Missing fields come from ``base``."""
        start = base or cls()
        known = {"pattern", "color", "brightness", "speed", "zones"}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown lighting setting(s): {', '.join(sorted(unknown))}")
        zones = start.zones
        if "zones" in data:
            zones = tuple((int(z), parse_color(c, custom_colors)) for z, c in dict(data["zones"]).items())
        return cls(
            pattern=data.get("pattern", start.pattern),
            color=parse_color(data["color"], custom_colors) if "color" in data else start.color,
            brightness=int(data.get("brightness", start.brightness)),
            speed=int(data.get("speed", start.speed)),
            zones=zones,
        )

    def describe(self) -> str:
        parts = [self.pattern]
        if self.pattern not in SELF_COLORED_PATTERNS:
            parts.append(to_hex(self.color))
        parts.append(f"brightness {self.brightness}/10")
        if self.pattern != "static":
            parts.append(f"speed {self.speed}/10")
        for zone, rgb in self.zones:
            parts.append(f"zone {zone} {to_hex(rgb)}")
        return ", ".join(parts)


OFF = LightState(pattern="static", color=(0, 0, 0), brightness=0)

BUILTIN_PRESETS: Dict[str, LightState] = {
    "normal": LightState("static", parse_color("white"), 6),
    "busy": LightState("breathe", parse_color("cyan"), 8, 8),
    "success": LightState("breathe", parse_color("green"), 9, 6),
    "warning": LightState("breathe", parse_color("amber"), 8, 7),
    "error": LightState("breathe", parse_color("red"), 10, 9),
    "focus": LightState("static", parse_color("warmwhite"), 3),
    "rainbow": LightState("cycle", parse_color("white"), 8, 6),
    "off": OFF,
    "restore": LightState("static", parse_color("white"), 7),
}

PRESET_ALIASES: Dict[str, str] = {
    "idle": "normal",
    "building": "busy",
    "pass": "success",
    "fail": "error",
}

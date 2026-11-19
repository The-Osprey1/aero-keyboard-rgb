"""Pure description of the keyboard lighting protocol: colors, patterns, presets, packets.

Nothing in this module touches hardware, so all of it can be tested on any machine.

The packet layout follows docs/PROTOCOL_SPEC.md. That spec has NOT yet been confirmed
against a USB capture from real hardware. Open questions are listed in the spec's
"Verification status" section; the code below marks each place it depends on one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- colors

NAMED_COLORS: dict[str, int] = {
    "black": 0x000000,
    "off": 0x000000,
    "white": 0xFFFFFF,
    "warmwhite": 0xFFE4B5,
    "red": 0xFF0000,
    "crimson": 0xDC143C,
    "green": 0x00FF00,
    "lime": 0x32CD32,
    "blue": 0x0066FF,
    "deepblue": 0x0000FF,
    "cyan": 0x00FFFF,
    "teal": 0x008080,
    "magenta": 0xFF00FF,
    "purple": 0x8A2BE2,
    "yellow": 0xFFFF00,
    "gold": 0xFFD700,
    "orange": 0xFF6600,
    "amber": 0xFFBF00,
    "pink": 0xFF69B4,
}

RGB = tuple[int, int, int]

_HEX_RE = re.compile(r"^(?:#|0x)?([0-9a-f]{6}|[0-9a-f]{3})$")


def parse_color(value: str | int | RGB) -> RGB:
    """Turn a color name, hex string (#RRGGBB, RRGGBB, 0xRRGGBB, #RGB), integer or tuple into (r, g, b)."""
    if isinstance(value, tuple):
        if len(value) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in value):
            raise ValueError(f"RGB tuple must be three integers from 0 to 255, got {value!r}")
        return value
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFF:
            raise ValueError(f"color integer must be between 0x000000 and 0xFFFFFF, got {value:#x}")
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)

    text = value.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if text in NAMED_COLORS:
        return parse_color(NAMED_COLORS[text])
    match = _HEX_RE.match(text)
    if not match:
        names = ", ".join(sorted(NAMED_COLORS))
        raise ValueError(f"unknown color {value!r}: use #RRGGBB or one of: {names}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    return parse_color(int(digits, 16))


def color_to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# --------------------------------------------------------------------------- patterns


@dataclass(frozen=True)
class Pattern:
    name: str
    hardware_id: int  # byte 3 of the 0x08 mode packet (spec section 5; unverified)
    control_center_id: int  # the ID Gigabyte Control Center's RgbLaptop.dll expects
    powershell_name: str  # the -Pattern value keyboard_led.ps1 accepts
    uses_color: bool
    uses_speed: bool


STATIC = Pattern("static", 0x01, 0, "Static", uses_color=True, uses_speed=False)
BREATHE = Pattern("breathe", 0x02, 1, "Breathe", uses_color=True, uses_speed=True)
CYCLE = Pattern("cycle", 0x03, 78, "Cycle", uses_color=False, uses_speed=True)
RGB_PULSE = Pattern("rgb-pulse", 0x04, 84, "RgbPulse", uses_color=False, uses_speed=True)
CYCLE_PULSE = Pattern("cycle-pulse", 0x05, 92, "CyclePulse", uses_color=False, uses_speed=True)

PATTERNS: dict[str, Pattern] = {p.name: p for p in (STATIC, BREATHE, CYCLE, RGB_PULSE, CYCLE_PULSE)}
_PATTERN_ALIASES = {"still": "static", "pulse": "breathe", "rainbow": "cycle"}


def parse_pattern(value: str | Pattern) -> Pattern:
    """Accept 'breathe', 'Breathe', 'RgbPulse', 'rgb-pulse', 'rgb_pulse', 'rainbow', ..."""
    if isinstance(value, Pattern):
        return value
    key = value.strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    key = _PATTERN_ALIASES.get(key, key)
    for pattern in PATTERNS.values():
        if key == pattern.name.replace("-", ""):
            return pattern
    choices = ", ".join(list(PATTERNS) + list(_PATTERN_ALIASES))
    raise ValueError(f"unknown pattern {value!r}: choose one of {choices}")


# --------------------------------------------------------------------------- lighting state

BRIGHTNESS_RANGE = range(0, 11)
SPEED_RANGE = range(1, 11)


@dataclass(frozen=True)
class LightingState:
    pattern: Pattern = STATIC
    color: RGB = (0xFF, 0xFF, 0xFF)
    brightness: int = 7
    speed: int = 8

    def __post_init__(self) -> None:
        if self.brightness not in BRIGHTNESS_RANGE:
            raise ValueError(f"brightness must be 0-10, got {self.brightness}")
        if self.speed not in SPEED_RANGE:
            raise ValueError(f"speed must be 1-10, got {self.speed}")
        parse_color(self.color)  # validates

    @classmethod
    def build(
        cls,
        pattern: str | Pattern = "static",
        color: str | int | RGB = "white",
        brightness: int = 7,
        speed: int = 8,
    ) -> LightingState:
        return cls(parse_pattern(pattern), parse_color(color), int(brightness), int(speed))

    def describe(self) -> str:
        parts = [self.pattern.name]
        if self.pattern.uses_color:
            parts.append(color_to_hex(self.color))
        parts.append(f"brightness {self.brightness}/10")
        if self.pattern.uses_speed:
            parts.append(f"speed {self.speed}/10")
        return ", ".join(parts)


# --------------------------------------------------------------------------- presets
# Keep in sync with the switch block in keyboard_led.ps1 (tests/test_powershell_sync.py checks).

PRESETS: dict[str, LightingState] = {
    "normal": LightingState.build("static", "white", brightness=6),
    "busy": LightingState.build("breathe", "cyan", brightness=8, speed=8),
    "success": LightingState.build("breathe", "green", brightness=9, speed=6),
    "warning": LightingState.build("breathe", "amber", brightness=8, speed=7),
    "attention": LightingState.build("breathe", "amber", brightness=10, speed=9),
    "error": LightingState.build("breathe", "red", brightness=10, speed=9),
    "focus": LightingState.build("static", "warmwhite", brightness=3),
    "rainbow": LightingState.build("cycle", "white", brightness=8, speed=6),
    "off": LightingState.build("static", "black", brightness=0),
    "restore": LightingState.build("static", "white", brightness=7),
}

PRESET_ALIASES: dict[str, str] = {"idle": "normal", "building": "busy", "pass": "success", "fail": "error"}

PRESET_DESCRIPTIONS: dict[str, str] = {
    "normal": "Everyday lighting",
    "busy": "Build, tests or an agent is running",
    "success": "Finished without errors",
    "warning": "Something needs a look soon",
    "attention": "Waiting on you (for example, an agent needs input)",
    "error": "Build or tests failed",
    "focus": "Dim warm light for night work",
    "rainbow": "Hardware color cycle",
    "off": "Lights off",
    "restore": "Gigabyte's factory baseline",
}


def resolve_preset(name: str) -> LightingState:
    key = name.strip().lower()
    key = PRESET_ALIASES.get(key, key)
    if key not in PRESETS:
        choices = ", ".join(list(PRESETS) + list(PRESET_ALIASES))
        raise ValueError(f"unknown preset {name!r}: choose one of {choices}")
    return PRESETS[key]


# --------------------------------------------------------------------------- packets (spec sections 2-4)

PACKET_LENGTH = 9
REPORT_ID = 0x00
CMD_SET_MODE = 0x08
CMD_SET_COLOR = 0x14
ALLOWED_COMMANDS = frozenset({CMD_SET_MODE, CMD_SET_COLOR})
COMMAND_NAMES = {CMD_SET_MODE: "set mode", CMD_SET_COLOR: "set color"}

# Delay between the color packet and the mode packet (spec section 4, step 2).
INTER_PACKET_DELAY_S = 0.020

# Spec section 5 note: static mode sends speed 0x02. Unverified.
STATIC_SPEED_BYTE = 0x02


def checksum(packet: bytes | list[int]) -> int:
    """Checksum over bytes 1-7: (255 - sum) mod 256 (spec section 3)."""
    if len(packet) < 8:
        raise ValueError("checksum needs at least bytes 0-7")
    return (255 - sum(packet[1:8])) & 0xFF


def build_packet(command: int, option: int, p1: int, p2: int, p3: int, p4: int, direction: int = 0) -> bytes:
    """Build one 9-byte feature report. Only the two documented commands are allowed."""
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"command {command:#04x} is not a known-safe command; allowed: 0x08, 0x14")
    body = [REPORT_ID, command, option, p1, p2, p3, p4, direction]
    if not all(0 <= b <= 0xFF for b in body):
        raise ValueError(f"packet bytes must be 0-255, got {body}")
    return bytes(body + [checksum(body)])


def build_color_packet(rgb: RGB, zone: int = 0x01) -> bytes:
    r, g, b = parse_color(rgb)
    return build_packet(CMD_SET_COLOR, 0x00, zone, r, g, b)


def build_mode_packet(pattern: Pattern, speed: int, brightness: int) -> bytes:
    speed_byte = STATIC_SPEED_BYTE if pattern is STATIC else speed
    # Unverified: the spec says static brightness may instead be 0x20 | brightness.
    return build_packet(CMD_SET_MODE, 0x00, pattern.hardware_id, speed_byte, brightness, 0x00)


def build_packets(state: LightingState) -> list[bytes]:
    """The two packets, in order, that apply a lighting state (spec section 4)."""
    return [build_color_packet(state.color), build_mode_packet(state.pattern, state.speed, state.brightness)]


def format_packet(packet: bytes) -> str:
    return " ".join(f"{b:02X}" for b in packet)


def parse_packet_text(text: str) -> bytes:
    """Parse '00 14 00 01 00 FF FF 00 EC', '0x00,0x14,...' or '00140001...' into bytes."""
    cleaned = re.sub(r"0x", "", text.lower())
    tokens = [t for t in re.split(r"[\s,:;\[\]]+", cleaned) if t]
    if len(tokens) == 1 and len(tokens[0]) > 2:
        token = tokens[0]
        if len(token) % 2:
            raise ValueError("hex string has an odd number of digits")
        tokens = [token[i : i + 2] for i in range(0, len(token), 2)]
    try:
        values = [int(t, 16) for t in tokens]
    except ValueError as exc:
        raise ValueError(f"could not read bytes from {text!r}") from exc
    if not all(0 <= v <= 0xFF for v in values):
        raise ValueError("every byte must be 00-FF")
    return bytes(values)


def decode_packet(packet: bytes) -> list[str]:
    """Explain a captured packet field by field, so captures can be compared with the spec."""
    lines: list[str] = []
    if len(packet) != PACKET_LENGTH:
        lines.append(f"warning: expected {PACKET_LENGTH} bytes, got {len(packet)}")
    if len(packet) < 8:
        return lines + ["too short to decode"]

    command = packet[1]
    lines.append(f"report ID  {packet[0]:02X}" + ("" if packet[0] == REPORT_ID else "  (spec expects 00)"))
    lines.append(f"command    {command:02X}  {COMMAND_NAMES.get(command, 'unknown to the spec')}")
    lines.append(f"option     {packet[2]:02X}")
    if command == CMD_SET_COLOR:
        r, g, b = packet[4], packet[5], packet[6]
        lines.append(f"zone       {packet[3]:02X}")
        lines.append(f"color      {color_to_hex((r, g, b))}  (red {r}, green {g}, blue {b})")
    elif command == CMD_SET_MODE:
        by_id = {p.hardware_id: p.name for p in PATTERNS.values()}
        lines.append(f"pattern    {packet[3]:02X}  {by_id.get(packet[3], 'unknown to the spec')}")
        lines.append(f"speed      {packet[4]:02X}  ({packet[4]})")
        lines.append(f"brightness {packet[5]:02X}  ({packet[5]})")
        lines.append(f"color idx  {packet[6]:02X}")
    else:
        lines.append(f"params     {format_packet(packet[3:7])}")
    lines.append(f"direction  {packet[7]:02X}")

    expected = checksum(packet)
    if len(packet) >= PACKET_LENGTH:
        ok = packet[8] == expected
        verdict = "matches the spec formula" if ok else f"does NOT match; the spec formula gives {expected:02X}"
        lines.append(f"checksum   {packet[8]:02X}  {verdict}")
    else:
        lines.append(f"checksum   missing; the spec formula gives {expected:02X}")
    return lines

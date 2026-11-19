"""Byte-level protocol for the ITE IT8298 lighting chip (see docs/PROTOCOL_SPEC.md).

Everything here is pure and has no hardware access, so it can be unit-tested anywhere.
Several details are still unconfirmed on real hardware; they are marked below and are
configurable through :class:`ProtocolOptions` so they can be adjusted without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .colors import RGB

VENDOR_ID = 0x0414
PRODUCT_ID = 0x8104
PACKET_LENGTH = 9
REPORT_ID = 0x00

CMD_SET_MODE = 0x08
CMD_SET_COLOR = 0x14

BRIGHTNESS_MAX = 10
SPEED_MIN = 1
SPEED_MAX = 10

# name -> (id used by Gigabyte's own software, id sent to the chip)
PATTERNS: Dict[str, Tuple[int, int]] = {
    "static": (0, 0x01),
    "breathe": (1, 0x02),
    "cycle": (78, 0x03),
    "rgbpulse": (84, 0x04),
    "cyclepulse": (92, 0x05),
}

PATTERN_ALIASES: Dict[str, str] = {
    "still": "static",
    "solid": "static",
    "pulse": "breathe",
    "breathing": "breathe",
    "rainbow": "cycle",
    "colorcycle": "cycle",
    "spectrum": "cycle",
}

# Patterns where the chip generates its own colors, so the chosen color is ignored.
SELF_COLORED_PATTERNS = {"cycle", "rgbpulse", "cyclepulse"}


@dataclass(frozen=True)
class ProtocolOptions:
    """Protocol details that still need confirming on real hardware.

    * ``static_speed``: the spec says static mode sends speed ``0x02``.
    * ``static_brightness_flag``: the spec says static brightness *may* be sent as
      ``0x20 | brightness``. Set to ``0x20`` to try that form.
    * ``latch_delay``: pause in seconds between the color and the mode packet.
    """

    static_speed: int = 0x02
    static_brightness_flag: int = 0x00
    latch_delay: float = 0.020


def normalize_pattern(name: str) -> str:
    key = "".join(ch for ch in name.strip().lower() if ch not in " _-")
    key = PATTERN_ALIASES.get(key, key)
    if key not in PATTERNS:
        valid = ", ".join(sorted(set(PATTERNS) | set(PATTERN_ALIASES)))
        raise ValueError(f"Unknown pattern {name!r}. Valid patterns: {valid}")
    return key


def software_pattern_id(name: str) -> int:
    """Pattern number understood by Gigabyte's RgbLaptop.dll (used by the PowerShell route)."""
    return PATTERNS[normalize_pattern(name)][0]


def hardware_pattern_id(name: str) -> int:
    """Pattern number sent directly to the lighting chip."""
    return PATTERNS[normalize_pattern(name)][1]


def checksum(packet: Sequence[int]) -> int:
    """8-bit checksum over bytes 1-7: ``(255 - sum) & 0xFF``.

    Note: the original spec's worked example gave 0xEB for cyan, but this formula
    gives 0xEC. The formula is used here; confirm on hardware with ``aero-rgb probe``.
    """
    return (255 - sum(packet[1:8])) & 0xFF


def build_packet(command: int, option: int, p1: int, p2: int, p3: int, p4: int, direction: int = 0) -> bytes:
    body = [REPORT_ID, command, option, p1, p2, p3, p4, direction]
    for index, value in enumerate(body):
        if not 0 <= value <= 0xFF:
            raise ValueError(f"Packet byte {index} out of range: {value}")
    return bytes(body + [checksum(body)])


def color_packet(rgb: RGB, zone: int = 1) -> bytes:
    """Command 0x14: load an RGB color into a zone (zone 1 is the main keyboard)."""
    r, g, b = rgb
    return build_packet(CMD_SET_COLOR, 0x00, zone, r, g, b)


def clamp_brightness(value: int) -> int:
    return max(0, min(BRIGHTNESS_MAX, int(value)))


def clamp_speed(value: int) -> int:
    return max(SPEED_MIN, min(SPEED_MAX, int(value)))


def mode_packet(pattern: str, speed: int, brightness: int, options: ProtocolOptions = ProtocolOptions()) -> bytes:
    """Command 0x08: start a pattern with a speed and brightness."""
    name = normalize_pattern(pattern)
    bri = clamp_brightness(brightness)
    if name == "static":
        spd = options.static_speed
        bri = options.static_brightness_flag | bri
    else:
        spd = clamp_speed(speed)
    return build_packet(CMD_SET_MODE, 0x00, hardware_pattern_id(name), spd, bri, 0x00)


def decode_packet(packet: bytes) -> str:
    """Human-readable description of a packet, for dry runs and debugging."""
    if len(packet) != PACKET_LENGTH:
        return f"<invalid length {len(packet)}: {packet.hex(' ')}>"
    ok = checksum(packet) == packet[8]
    hex_bytes = packet.hex(" ").upper()
    status = "ok" if ok else f"BAD (expected {checksum(packet):02X})"
    if packet[1] == CMD_SET_COLOR:
        what = f"color zone={packet[3]} rgb=#{packet[4]:02X}{packet[5]:02X}{packet[6]:02X}"
    elif packet[1] == CMD_SET_MODE:
        names = {hw: n for n, (_, hw) in PATTERNS.items()}
        what = f"mode pattern={names.get(packet[3], hex(packet[3]))} speed={packet[4]} brightness=0x{packet[5]:02X}"
    else:
        what = f"command 0x{packet[1]:02X}"
    return f"[{hex_bytes}] {what} checksum {status}"


def state_packets(colors: Sequence[Tuple[int, RGB]], pattern: str, speed: int, brightness: int,
                  options: ProtocolOptions = ProtocolOptions()) -> List[bytes]:
    """All packets needed to show a lighting state: one color packet per zone, then the mode."""
    packets = [color_packet(rgb, zone) for zone, rgb in colors]
    packets.append(mode_packet(pattern, speed, brightness, options))
    return packets

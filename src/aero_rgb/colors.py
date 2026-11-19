"""Color names, parsing, and blending helpers."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

RGB = Tuple[int, int, int]
ColorInput = Union[str, Sequence[int]]

NAMED_COLORS: Dict[str, RGB] = {
    "black": (0x00, 0x00, 0x00),
    "off": (0x00, 0x00, 0x00),
    "white": (0xFF, 0xFF, 0xFF),
    "softwhite": (0xFF, 0xF4, 0xE5),
    "warmwhite": (0xFF, 0xE4, 0xB5),
    "red": (0xFF, 0x00, 0x00),
    "crimson": (0xDC, 0x14, 0x3C),
    "green": (0x00, 0xFF, 0x00),
    "lime": (0x32, 0xCD, 0x32),
    "mint": (0x3E, 0xB4, 0x89),
    "blue": (0x00, 0x66, 0xFF),
    "deepblue": (0x00, 0x00, 0xFF),
    "skyblue": (0x87, 0xCE, 0xEB),
    "cyan": (0x00, 0xFF, 0xFF),
    "teal": (0x00, 0x80, 0x80),
    "magenta": (0xFF, 0x00, 0xFF),
    "purple": (0x8A, 0x2B, 0xE2),
    "violet": (0xEE, 0x82, 0xEE),
    "yellow": (0xFF, 0xFF, 0x00),
    "gold": (0xFF, 0xD7, 0x00),
    "orange": (0xFF, 0x66, 0x00),
    "amber": (0xFF, 0xBF, 0x00),
    "pink": (0xFF, 0x69, 0xB4),
}


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in name.strip().lower() if ch not in " _-")


def parse_color(value: ColorInput, custom: Optional[Mapping[str, ColorInput]] = None) -> RGB:
    """Turn a color name, hex string, or (r, g, b) sequence into an RGB tuple.

    Accepted forms: ``"cyan"``, ``"Warm White"``, ``"#00FFCC"``, ``"00ffcc"``,
    ``"0x00FFCC"``, ``"#0fc"`` and ``[0, 255, 204]``. Names in ``custom`` win over
    the built-in names, and a custom name may point at another name.
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 3:
            raise ValueError(f"Expected 3 color channels, got {len(value)}: {value!r}")
        r, g, b = (int(c) for c in value)
        for channel in (r, g, b):
            if not 0 <= channel <= 255:
                raise ValueError(f"Color channel out of range 0-255: {value!r}")
        return (r, g, b)

    if not isinstance(value, str):
        raise ValueError(f"Unsupported color value: {value!r}")

    key = _normalize_name(value)
    if custom:
        normalized_custom = {_normalize_name(k): v for k, v in custom.items()}
        if key in normalized_custom:
            target = normalized_custom[key]
            # Avoid infinite loops if a custom color refers to itself.
            if isinstance(target, str) and _normalize_name(target) == key:
                return parse_color(target)
            rest = {k: v for k, v in custom.items() if _normalize_name(k) != key}
            return parse_color(target, rest)
    if key in NAMED_COLORS:
        return NAMED_COLORS[key]

    text = value.strip().lower()
    if text.startswith("#"):
        text = text[1:]
    elif text.startswith("0x"):
        text = text[2:]
    if len(text) == 3 and all(ch in "0123456789abcdef" for ch in text):
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6 and all(ch in "0123456789abcdef" for ch in text):
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    raise ValueError(f"Unknown color {value!r}. Use a name like 'cyan' or a hex code like '#00FFCC'.")


def to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def to_int(rgb: RGB) -> int:
    return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def clamp01(t: float) -> float:
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    """Blend two colors. ``t=0`` gives ``a`` and ``t=1`` gives ``b``."""
    t = clamp01(t)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def gradient(stops: Iterable[Tuple[float, RGB]], t: float) -> RGB:
    """Pick a color along a multi-stop gradient. Stop positions run from 0 to 1."""
    ordered = sorted(stops, key=lambda s: s[0])
    if not ordered:
        raise ValueError("A gradient needs at least one stop")
    t = clamp01(t)
    if t <= ordered[0][0]:
        return ordered[0][1]
    for (pos_a, col_a), (pos_b, col_b) in zip(ordered, ordered[1:]):
        if t <= pos_b:
            span = pos_b - pos_a
            return lerp(col_a, col_b, 0.0 if span == 0 else (t - pos_a) / span)
    return ordered[-1][1]

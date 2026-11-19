"""Your saved "normal" backlight: what the keyboard goes back to after alerts and tasks.

Stored as ``profile.json`` in the settings folder, in the same format the earlier
``aero-rgb profile`` command used, so existing saved profiles keep working::

    {"pattern": "Static", "color": "#123456", "brightness": 4, "speed": 5}
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .colors import ColorInput, parse_color
from .protocol import normalize_pattern
from .state import LightState

PROFILE_KEYS = ("pattern", "color", "brightness", "speed")
SAVE_HINT = "Save your normal backlight first: aero-rgb profile save --color White --brightness 6"


def profile_path() -> Path:
    from .config import config_dir

    return config_dir() / "profile.json"


def validate(profile: Any, custom_colors: Optional[Mapping[str, ColorInput]] = None) -> Dict[str, Any]:
    """Check a profile strictly. Raises ValueError explaining the first problem found."""
    if not isinstance(profile, dict) or set(profile) != set(PROFILE_KEYS):
        raise ValueError("A profile must contain exactly: pattern, color, brightness and speed.")
    if not isinstance(profile["pattern"], str):
        raise ValueError("Invalid pattern.")
    normalize_pattern(profile["pattern"])
    if not isinstance(profile["color"], str):
        raise ValueError("Use a supported color name or six-digit RGB hex.")
    parse_color(profile["color"], custom_colors)
    for key, low, high in (("brightness", 0, 10), ("speed", 1, 10)):
        value = profile[key]
        if type(value) is not int or not low <= value <= high:  # rejects True/False and floats
            raise ValueError(f"{key} must be a whole number from {low} to {high}.")
    return profile


def load_profile(custom_colors: Optional[Mapping[str, ColorInput]] = None) -> Optional[Dict[str, Any]]:
    """The saved profile, or None if none was saved. A damaged file raises ValueError."""
    path = profile_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return validate(json.loads(text), custom_colors)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"The saved profile at {path} is damaged ({exc}). Save it again with: aero-rgb profile save") from exc


def save_profile(profile: Dict[str, Any], custom_colors: Optional[Mapping[str, ColorInput]] = None) -> Path:
    """Validate, then write atomically so a crash never leaves a half-written file."""
    validate(profile, custom_colors)
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            json.dump(profile, stream, indent=2)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def profile_state(profile: Mapping[str, Any], custom_colors: Optional[Mapping[str, ColorInput]] = None) -> LightState:
    return LightState(profile["pattern"], parse_color(profile["color"], custom_colors),
                      profile["brightness"], profile["speed"])

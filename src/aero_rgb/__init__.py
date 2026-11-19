"""Keyboard lighting control for GIGABYTE AERO / AORUS laptops."""

__version__ = "0.2.0"

import sys  # noqa: E402

from .colors import parse_color  # noqa: E402
from .state import BUILTIN_PRESETS, LightState  # noqa: E402


def _apply(make_state, backend: str) -> bool:
    from .backends import BackendError, create_backend
    from .config import load_config

    try:
        config = load_config()
        with create_backend(backend if backend != "auto" else config.device.backend, config.device, echo=None) as device:
            device.apply(make_state(config))
        return True
    except (BackendError, ValueError, OSError) as exc:
        print(f"Lighting update failed: {exc}", file=sys.stderr)
        return False


def set_keyboard_led(pattern: str = "static", color: str = "white", brightness: int = 7, speed: int = 5,
                     backend: str = "auto") -> bool:
    """Set the keyboard lighting directly. Returns True on success, False (with a message) on failure."""
    return _apply(lambda config: LightState(pattern, config.color(color), brightness, speed), backend)


def set_status(preset: str, backend: str = "auto") -> bool:
    """Apply a preset such as 'busy', 'success', 'profile' or one of your own. Returns True on success."""
    return _apply(lambda config: config.preset(preset), backend)


__all__ = ["LightState", "BUILTIN_PRESETS", "parse_color", "set_keyboard_led", "set_status", "__version__"]

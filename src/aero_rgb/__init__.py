"""Keyboard lighting control for GIGABYTE AERO / AORUS laptops."""

__version__ = "0.2.0"

from .colors import parse_color  # noqa: E402
from .state import BUILTIN_PRESETS, LightState  # noqa: E402


def set_keyboard_led(pattern: str = "static", color: str = "white", brightness: int = 7, speed: int = 5,
                     backend: str = "auto") -> None:
    """Set the keyboard lighting directly (simple scripting helper)."""
    from .backends import create_backend
    from .config import load_config

    config = load_config()
    state = LightState(pattern, config.color(color), brightness, speed)
    with create_backend(backend if backend != "auto" else config.device.backend, config.device) as device:
        device.apply(state)


def set_status(preset: str, backend: str = "auto") -> None:
    """Apply a preset such as 'busy', 'success' or one of your own."""
    from .backends import create_backend
    from .config import load_config

    config = load_config()
    with create_backend(backend if backend != "auto" else config.device.backend, config.device) as device:
        device.apply(config.preset(preset))


__all__ = ["LightState", "BUILTIN_PRESETS", "parse_color", "set_keyboard_led", "set_status", "__version__"]

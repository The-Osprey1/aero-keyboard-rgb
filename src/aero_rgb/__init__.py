"""Keyboard lighting control for GIGABYTE AERO and AORUS laptops.

    from aero_rgb import set_status, set_keyboard_led

    set_status("busy")
    set_keyboard_led(pattern="breathe", color="#00FFCC", speed=8, brightness=8)

Both raise BackendError if the lighting can't be applied, and ValueError on bad input.
Set AERO_RGB_BACKEND=dry-run to print packets instead of touching hardware.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .backends import BackendError, get_backend
from .protocol import PRESETS, LightingState, resolve_preset


def set_keyboard_led(
    pattern: str = "static",
    color: str | int | tuple[int, int, int] = "white",
    brightness: int = 7,
    speed: int = 8,
    backend: str | None = None,
) -> LightingState:
    """Set a pattern, color, brightness (0-10) and speed (1-10). Returns the applied state."""
    state = LightingState.build(pattern, color, brightness, speed)
    get_backend(backend).apply(state)
    return state


def set_status(preset: str, backend: str | None = None) -> LightingState:
    """Apply a named preset such as 'busy', 'success' or 'error'. Returns the applied state."""
    state = resolve_preset(preset)
    get_backend(backend).apply(state)
    return state


__all__ = [
    "PRESETS",
    "BackendError",
    "LightingState",
    "set_keyboard_led",
    "set_status",
    "__version__",
]

"""Decides what the keyboard shows when several things want the light at once.

Every source (battery, USB alerts, file copies, build status...) puts its request on a
named *layer* with a priority. The highest-priority layer wins; when it ends, the light
falls back to whatever is underneath. Writes to the chip are skipped when nothing changed
and are rate-limited, to keep chip traffic (and any wear on its memory) low.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .backends import Backend, BackendError
from .state import LightState

PRIORITY_BASE = 0
PRIORITY_AMBIENT = 10   # e.g. battery color in "always" mode
PRIORITY_TASK = 50      # file copies, builds, commands
PRIORITY_WARNING = 70   # critical battery
PRIORITY_ALERT = 100    # short pulses such as a USB plug-in


@dataclass
class Layer:
    name: str
    state: LightState
    priority: int
    expires_at: Optional[float]
    order: int


class LightEngine:
    def __init__(self, backend: Backend, base: LightState, min_interval: float = 0.25,
                 clock: Callable[[], float] = time.monotonic, log: Optional[Callable[[str], None]] = None):
        self.backend = backend
        self.min_interval = min_interval
        self.clock = clock
        self.log = log
        self._layers: Dict[str, Layer] = {}
        self._order = 0
        self._last_sent: Optional[LightState] = None
        self._last_write: Optional[float] = None
        self.set_layer("base", base, PRIORITY_BASE)

    def set_layer(self, name: str, state: LightState, priority: int, duration: Optional[float] = None) -> None:
        """Add or replace a layer. With ``duration`` (seconds) it removes itself afterwards."""
        existing = self._layers.get(name)
        if existing and existing.state == state and existing.priority == priority and duration is None and existing.expires_at is None:
            return  # unchanged; keep its position so it doesn't jump ahead of equal-priority layers
        self._order += 1
        expires = self.clock() + duration if duration is not None else None
        self._layers[name] = Layer(name, state, priority, expires, self._order)

    def set_base(self, state: LightState) -> None:
        self.set_layer("base", state, PRIORITY_BASE)

    def clear(self, name: str) -> None:
        if name != "base":
            self._layers.pop(name, None)

    def has_layer(self, name: str) -> bool:
        self._expire()
        return name in self._layers

    def layers(self) -> List[Layer]:
        self._expire()
        return sorted(self._layers.values(), key=lambda l: (l.priority, l.order), reverse=True)

    def _expire(self) -> None:
        now = self.clock()
        for name in [n for n, l in self._layers.items() if l.expires_at is not None and l.expires_at <= now]:
            del self._layers[name]

    def top(self) -> Layer:
        return self.layers()[0]

    def current(self) -> LightState:
        return self.top().state

    def update(self, force: bool = False) -> bool:
        """Send the winning state to the keyboard if it changed. Returns True if it wrote."""
        layer = self.top()
        if not force and layer.state == self._last_sent:
            return False
        now = self.clock()
        if not force and self._last_write is not None and now - self._last_write < self.min_interval:
            return False  # try again on the next update
        try:
            self.backend.apply(layer.state)
        except BackendError as exc:
            if self.log:
                self.log(f"Could not update the keyboard: {exc}")
            self._last_write = now
            return False
        self._last_sent = layer.state
        self._last_write = now
        if self.log:
            self.log(f"[{layer.name}] {layer.state.describe()}")
        return True

"""Show the battery level as the keyboard color."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..colors import RGB, gradient
from ..config import BatteryConfig
from ..engine import PRIORITY_ALERT, PRIORITY_AMBIENT, PRIORITY_WARNING, LightEngine
from ..state import LightState

LAYER = "battery"
LAYER_FLASH = "battery-change"
LAYER_WARNING = "battery-warning"
LAYER_LOW_PULSE = "battery-low"


@dataclass(frozen=True)
class BatteryReading:
    percent: float
    plugged: Optional[bool]


def read_battery() -> Optional[BatteryReading]:
    """Current battery level, or None if there is no battery (or psutil is missing)."""
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.sensors_battery()
    if info is None:
        return None
    return BatteryReading(float(info.percent), info.power_plugged)


def battery_color(percent: float, cfg: BatteryConfig) -> RGB:
    # Round to 5% steps so the color (and the chip) doesn't change on every 1% tick.
    stepped = round(percent / 5.0) * 5.0
    return gradient(cfg.gradient, stepped / 100.0)


def battery_state(reading: BatteryReading, cfg: BatteryConfig) -> LightState:
    """Static color for the charge level; a slow breathe while charging."""
    color = battery_color(reading.percent, cfg)
    if reading.plugged and reading.percent < 99:
        return LightState("breathe", color, cfg.brightness, 3)
    return LightState("static", color, cfg.brightness)


class BatteryMonitor:
    def __init__(self, engine: LightEngine, cfg: BatteryConfig,
                 reader: Callable[[], Optional[BatteryReading]] = read_battery):
        self.engine = engine
        self.cfg = cfg
        self.reader = reader
        self._last: Optional[BatteryReading] = None
        self._next_poll = 0.0
        self._warned_low = False

    def tick(self, now: float) -> None:
        if self.cfg.mode == "off" or now < self._next_poll:
            return
        self._next_poll = now + self.cfg.poll_seconds
        reading = self.reader()
        if reading is None:
            return
        previous, self._last = self._last, reading
        state = battery_state(reading, self.cfg)

        if self.cfg.mode == "always":
            self.engine.set_layer(LAYER, state, PRIORITY_AMBIENT)
        elif self.cfg.mode == "on_change" and previous is not None and previous.plugged != reading.plugged:
            self.engine.set_layer(LAYER_FLASH, state, PRIORITY_ALERT, duration=self.cfg.show_seconds)

        self._warnings(reading)

    def _warnings(self, reading: BatteryReading) -> None:
        on_battery = reading.plugged is False
        if on_battery and reading.percent <= self.cfg.critical_percent:
            red = gradient(self.cfg.gradient, 0.0)
            self.engine.set_layer(LAYER_WARNING, LightState("breathe", red, 10, 9), PRIORITY_WARNING)
        else:
            self.engine.clear(LAYER_WARNING)

        if on_battery and reading.percent <= self.cfg.low_percent:
            if not self._warned_low:  # one pulse when crossing the "low" line
                self._warned_low = True
                color = gradient(self.cfg.gradient, reading.percent / 100.0)
                self.engine.set_layer(LAYER_LOW_PULSE, LightState("breathe", color, 9, 8), PRIORITY_ALERT,
                                      duration=self.cfg.show_seconds)
        else:
            self._warned_low = False

"""Mirror CPU load and battery state on the keyboard lighting.

Needs psutil:  pip install "aero-keyboard-rgb[daemon]"
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from .backends import Backend, BackendError
from .protocol import LightingState, resolve_preset

HIGH_CPU = 80.0
ACTIVE_CPU = 40.0
LOW_BATTERY = 20.0
# Once in a state, CPU must drop this far below the threshold before leaving it,
# so load hovering around 40% or 80% doesn't make the lighting flicker.
HYSTERESIS = 5.0

LEVEL_STATES: dict[str, LightingState] = {
    "low-battery": LightingState.build("breathe", "orange", brightness=8, speed=8),
    "high": LightingState.build("breathe", "red", brightness=9, speed=9),
    "active": LightingState.build("breathe", "cyan", brightness=7, speed=7),
    "idle": LightingState.build("static", "teal", brightness=5),
}


@dataclass(frozen=True)
class Reading:
    cpu_percent: float
    battery_percent: float | None  # None when there is no battery
    plugged_in: bool


def choose_level(reading: Reading, previous: str | None = None) -> str:
    if reading.battery_percent is not None and reading.battery_percent < LOW_BATTERY and not reading.plugged_in:
        return "low-battery"
    high = HIGH_CPU - (HYSTERESIS if previous == "high" else 0)
    active = ACTIVE_CPU - (HYSTERESIS if previous in ("high", "active") else 0)
    if reading.cpu_percent >= high:
        return "high"
    if reading.cpu_percent >= active:
        return "active"
    return "idle"


def describe(level: str, reading: Reading) -> str:
    if level == "low-battery":
        return f"Low battery ({reading.battery_percent:.0f}%, not plugged in)"
    labels = {"high": "High CPU load", "active": "Active CPU load", "idle": "Idle"}
    return f"{labels[level]} ({reading.cpu_percent:.0f}%)"


def _psutil():
    try:
        import psutil
    except ImportError as exc:
        raise SystemExit('The daemon needs psutil. Install it with:  pip install "aero-keyboard-rgb[daemon]"') from exc
    return psutil


def read_system(psutil) -> Reading:
    cpu = psutil.cpu_percent(interval=None)
    battery = psutil.sensors_battery()
    if battery is None:
        return Reading(cpu, None, True)
    return Reading(cpu, float(battery.percent), bool(battery.power_plugged))


def run(backend: Backend, interval: float = 3.0) -> int:
    psutil = _psutil()
    psutil.cpu_percent(interval=None)  # first call only primes the counter
    print("AERO keyboard daemon running (Ctrl+C to stop).", file=sys.stderr)
    level: str | None = None
    try:
        while True:
            time.sleep(interval)
            reading = read_system(psutil)
            new_level = choose_level(reading, level)
            if new_level != level:
                print(f"[daemon] {describe(new_level, reading)}", file=sys.stderr)
                try:
                    backend.apply(LEVEL_STATES[new_level])
                    level = new_level
                except BackendError as exc:
                    print(f"[daemon] could not update lighting: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nStopping; restoring the factory lighting.", file=sys.stderr)
        try:
            backend.apply(resolve_preset("restore"))
        except BackendError as exc:
            print(f"[daemon] could not restore lighting: {exc}", file=sys.stderr)
    return 0

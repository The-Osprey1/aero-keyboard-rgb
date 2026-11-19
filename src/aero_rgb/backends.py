"""Ways of getting a LightingState onto the keyboard.

- ControlCenterBackend: drives Gigabyte Control Center's installed .NET libraries through
  keyboard_led.ps1. Works today on Windows, but needs Control Center installed and is slow:
  every change starts PowerShell and loads Control Center's libraries.
- DryRunBackend: prints the packets the protocol spec says to send. Touches no hardware.

A direct-USB backend (no Control Center, works on Linux too) is the next step, once the
spec is confirmed against a USB capture.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol, TextIO

from .protocol import LightingState, build_packets, color_to_hex, format_packet

POWERSHELL_SCRIPT = Path(__file__).with_name("keyboard_led.ps1")
CONTROL_CENTER_LIB_DIRS = (
    Path(r"C:\Program Files\GIGABYTE\Control Center\Lib\COMMDLL"),
    Path(r"C:\Program Files\GIGABYTE\Control Center\Lib\GBT_rgbLaptop_UC"),
)
BACKEND_ENV_VAR = "AERO_RGB_BACKEND"
BACKEND_NAMES = ("auto", "control-center", "dry-run")


class BackendError(RuntimeError):
    """The lighting could not be applied."""


class Backend(Protocol):
    name: str

    def apply(self, state: LightingState) -> None: ...


class DryRunBackend:
    name = "dry-run"

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream

    def apply(self, state: LightingState) -> None:
        out = self.stream or sys.stdout
        color_packet, mode_packet = build_packets(state)
        print(f"[dry-run] {state.describe()}", file=out)
        print(f"  color packet: {format_packet(color_packet)}", file=out)
        print(f"  mode packet:  {format_packet(mode_packet)}", file=out)


class ControlCenterBackend:
    name = "control-center"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32" and all(d.is_dir() for d in CONTROL_CENTER_LIB_DIRS)

    def command(self, state: LightingState) -> list[str]:
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(POWERSHELL_SCRIPT),
            "-Pattern",
            state.pattern.powershell_name,
            "-Color",
            color_to_hex(state.color),
            "-Brightness",
            str(state.brightness),
            "-Speed",
            str(state.speed),
        ]

    def apply(self, state: LightingState) -> None:
        try:
            result = subprocess.run(
                self.command(state), capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as exc:
            raise BackendError("powershell.exe not found; the Control Center backend only works on Windows") from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"Control Center did not respond within {self.timeout:.0f} seconds") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
            raise BackendError(f"Control Center backend failed: {detail}")


def get_backend(name: str | None = None, stream: TextIO | None = None) -> Backend:
    """Pick a backend by name, by the AERO_RGB_BACKEND variable, or automatically."""
    choice = (name or os.environ.get(BACKEND_ENV_VAR) or "auto").strip().lower()
    if choice == "dry-run":
        return DryRunBackend(stream)
    if choice == "control-center":
        return ControlCenterBackend()
    if choice != "auto":
        raise BackendError(f"unknown backend {choice!r}; choose one of: {', '.join(BACKEND_NAMES)}")
    if ControlCenterBackend.available():
        return ControlCenterBackend()
    raise BackendError(
        "no lighting backend available: Gigabyte Control Center's libraries were not found, "
        "and direct USB control is not built yet. Use --dry-run to see the packets instead."
    )

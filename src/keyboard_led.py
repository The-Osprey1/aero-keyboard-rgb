#!/usr/bin/env python3
"""
GIGABYTE AERO X16 Keyboard LED & Status Indicator Controller (Python Wrapper)
"""

import sys
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "keyboard_led.ps1"

def set_keyboard_led(
    pattern: str = "Static",
    color: str = "White",
    brightness: int = 7,
    speed: int = 8,
    status: str = None
) -> bool:
    """
    Update the keyboard LED lighting pattern or status indicator.
    
    :param pattern: 'Static', 'Breathe' / 'Pulse', 'Cycle' / 'Rainbow', 'RgbPulse', 'CyclePulse'
    :param color: Named color ('Cyan', 'Red', 'Green', etc.) or Hex string ('#00FFCC')
    :param brightness: Integer 0 to 10
    :param speed: Integer 1 to 10
    :param status: Preset status string ('normal', 'busy', 'success', 'warning', 'error', 'focus', 'rainbow', 'off', 'restore')
    """
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT_PATH)
    ]
    if status:
        cmd.extend(["-Status", status])
    else:
        cmd.extend([
            "-Pattern", pattern,
            "-Color", color,
            "-Brightness", str(brightness),
            "-Speed", str(speed)
        ])
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Lighting controller unavailable: {exc}", file=sys.stderr)
        return False
    if res.returncode == 0:
        print(res.stdout.strip())
        return True
    else:
        print(f"Error ({res.returncode}): {res.stderr.strip()}", file=sys.stderr)
        return False

def set_status(status_preset: str) -> bool:
    """Set a quick status indicator preset."""
    return set_keyboard_led(status=status_preset)

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Control GIGABYTE AERO X16 keyboard LED array.")
    parser.add_argument(
        "--pattern", "-p",
        default="Static",
        choices=["Static", "Breathe", "Pulse", "Cycle", "Rainbow", "RgbPulse", "CyclePulse"]
    )
    parser.add_argument("--color", "-c", default="White", help="Color name or hex code (#RRGGBB)")
    parser.add_argument("--brightness", "-b", type=int, default=7, help="Brightness level (0-10)")
    parser.add_argument("--speed", "-s", type=int, default=8, help="Animation speed (1-10)")
    parser.add_argument(
        "--status",
        choices=["normal", "idle", "busy", "building", "success", "pass", "warning", "error", "fail", "focus", "rainbow", "off", "restore"],
        help="Quick status preset"
    )
    args = parser.parse_args(argv)

    ok = set_keyboard_led(
        pattern=args.pattern,
        color=args.color,
        brightness=args.brightness,
        speed=args.speed,
        status=args.status
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


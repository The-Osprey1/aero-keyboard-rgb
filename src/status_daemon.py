#!/usr/bin/env python3
"""
Telemetry & Workflow Status Daemon for GIGABYTE AERO Laptops.
Monitors CPU load, thermals, and battery levels, mapping them to the keyboard LED array.
"""

import time
import argparse
import subprocess
from keyboard_led import set_keyboard_led, set_status

def get_battery_info():
    """Query battery percent and AC line status via PowerShell / WMI."""
    ps_cmd = "Get-CimInstance -ClassName Win32_Battery | Select-Object EstimatedChargeRemaining, BatteryStatus"
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    if len(lines) >= 3:
        parts = lines[-1].split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    return 100, 2

def get_cpu_load():
    """Query average CPU load percentage."""
    ps_cmd = "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0

def run_telemetry_loop(interval: float = 3.0):
    print("Starting AERO Keyboard Telemetry Daemon (Press Ctrl+C to stop)...")
    last_state = None
    try:
        while True:
            cpu = get_cpu_load()
            charge, status = get_battery_info()

            # State Logic:
            # 1. Low battery (< 20% and not charging) -> Pulsing Amber/Red
            # 2. High CPU (> 80%) -> Pulsing Crimson
            # 3. Moderate CPU (40-80%) -> Breathing Cyan
            # 4. Idle (< 40%) -> Static Soft White/Teal
            if charge < 20 and status != 2:
                state = ("Breathe", "Orange", 8, 8, f"Low Battery ({charge}%)")
            elif cpu >= 80:
                state = ("Breathe", "Red", 9, 9, f"High CPU Load ({cpu:.0f}%)")
            elif cpu >= 40:
                state = ("Breathe", "Cyan", 7, 7, f"Active Load ({cpu:.0f}%)")
            else:
                state = ("Static", "Teal", 5, 5, f"Normal / Idle ({cpu:.0f}%)")

            if state[:4] != (last_state[:4] if last_state else None):
                pattern, color, speed, bri, desc = state
                print(f"[Telemetry] Status Change: {desc} -> {pattern} {color}")
                set_keyboard_led(pattern=pattern, color=color, speed=speed, brightness=bri)
                last_state = state

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopping daemon. Restoring factory lighting...")
        set_status("restore")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AERO Keyboard Telemetry Daemon")
    parser.add_argument("--interval", "-i", type=float, default=3.0, help="Poll interval in seconds")
    args = parser.parse_args()
    run_telemetry_loop(interval=args.interval)

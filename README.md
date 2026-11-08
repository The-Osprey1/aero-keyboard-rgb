# AERO-Keyboard-RGB

> Reverse-engineered keyboard RGB lighting and status indicator controller for **GIGABYTE AERO & AORUS** laptops.

[![Platform](https://img.shields.io/badge/platform-Windows%2011-blue.svg)](https://microsoft.com/windows)
[![Hardware](https://img.shields.io/badge/hardware-ITE%20IT8298%20MCU-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Overview

Modern GIGABYTE laptops (such as the **GIGABYTE AERO X16 1WH**) control their keyboard backlighting and chassis status indicators through an internal **ITE IT8298 MCU** exposed over USB HID (`VID_0414&PID_8104`). 

Historically, controlling the lighting required running the heavy Gigabyte Control Center (GCC) / GiMATE software. This project documents the reverse-engineered hardware protocol and provides lightweight **PowerShell** and **Python** CLI/APIs to directly interface with the lighting controller, enabling:

- **Custom Lighting Animations:** Solid Static, Breathing/Pulse, Spectrum Color Cycle, RGB Pulse, and Multi-phase Cycle Pulse.
- **Developer Status Indicators:** Automated lighting signals for CI/CD, test runners (`pytest`, `npm test`), build passes/failures, and agent tasks.
- **Hardware Telemetry Sync:** Dynamic ambient color shifts based on CPU/GPU temperatures, memory utilization, or battery state.
- **Zero-GUI Overhead:** Operates via direct HID feature reports and local hardware library calls without GCC running.

---

## Project Structure

```text
aero-keyboard-rgb/
├── README.md                      # Project documentation and quickstart
├── LICENSE                        # MIT License
├── pyproject.toml                 # Python package metadata
├── docs/
│   └── PROTOCOL_SPEC.md          # Exhaustive hardware reverse-engineering teardown
└── src/
    ├── keyboard_led.ps1           # Standalone PowerShell controller
    ├── keyboard_led.py            # Python SDK and CLI tool
    └── status_daemon.py           # Background system telemetry & status monitor
```

---

## Quickstart

### 1. PowerShell CLI

No external dependencies required on Windows 11 with the OEM lighting driver installed.

```powershell
# Set status indicator preset
.\src\keyboard_led.ps1 -Status busy
.\src\keyboard_led.ps1 -Status success
.\src\keyboard_led.ps1 -Status restore

# Set a custom pattern and color
.\src\keyboard_led.ps1 -Pattern Breathe -Color Cyan -Speed 8 -Brightness 8
.\src\keyboard_led.ps1 -Pattern Static -Color "#FF5500" -Brightness 5
.\src\keyboard_led.ps1 -Pattern Rainbow -Speed 6
```

### 2. Python API

```python
from src.keyboard_led import set_status, set_keyboard_led

# Trigger a developer status indicator
set_status("busy")     # Breathing Cyan
set_status("success")  # Breathing Green
set_status("error")    # Rapid Red Pulse

# Set custom colors and patterns
set_keyboard_led(pattern="Breathe", color="#00FFCC", speed=8, brightness=8)
```

### 3. Background Telemetry Daemon

Run the daemon to mirror live hardware metrics (CPU load/temperature and battery status) to the keyboard array:

```bash
python src/status_daemon.py --mode thermals
```

---

## Built-in Status Presets

| Status Preset | Animation / Color | Suggested Use Case |
| :--- | :--- | :--- |
| `busy` / `building` | **Breathing Cyan** (Speed 8, Bri 8) | Compiling, running tests, or background agent processing |
| `success` / `pass` | **Breathing Green** (Speed 6, Bri 9) | Build succeeded, all tests passed |
| `warning` | **Breathing Amber** (Speed 7, Bri 8) | High memory, elevated thermals (>70°C), low battery |
| `error` / `fail` | **Pulsing Crimson** (Speed 9, Bri 10) | Build failed, test assertion failed, or unhandled exception |
| `focus` | **Static Warm Amber** (Bri 3) | Low eyestrain coding / night reading mode |
| `normal` / `idle` | **Static Soft White** (Bri 6) | Normal desktop operation |
| `rainbow` | **Color Cycle** (Speed 6, Bri 8) | Ambient spectrum cycling |
| `off` | **Off** (Brightness 0) | Stealth / display-off mode |
| `restore` | **Factory Baseline** (Bri 7, White) | Reset to OEM startup profile |

---

## Hardware Specifications

| Property | Value |
| :--- | :--- |
| **Target Host** | GIGABYTE AERO X16 1WH / AORUS Laptop Series |
| **USB Vendor ID (VID)** | `0x0414` (Giga-Byte Technology Co., Ltd.) |
| **USB Product ID (PID)** | `0x8104` |
| **Embedded Controller (EC)** | ITE IT8298 / IT8233 MCU |
| **Keyboard Array Topology** | Single-Zone Full RGB (`iRgbZone: 1`) |
| **Auxiliary Endpoint** | Windows Dynamic Lighting `LampArray` Notification device on `MI_04` |
| **HID Report Type** | 9-byte HID Feature Report |

For full protocol analysis, packet structures, and checksum formulas, see [docs/PROTOCOL_SPEC.md](docs/PROTOCOL_SPEC.md).

---

## License

This project is licensed under the [MIT License](LICENSE).

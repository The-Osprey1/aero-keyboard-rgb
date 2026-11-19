# AERO-Keyboard-RGB

> Keyboard lighting control for **GIGABYTE AERO & AORUS** laptops, built for developers: make the keyboard show when your build is running, when tests fail, and when your coding agent is waiting on you.

[![tests](https://github.com/The-Osprey1/aero-keyboard-rgb/actions/workflows/tests.yml/badge.svg)](https://github.com/The-Osprey1/aero-keyboard-rgb/actions/workflows/tests.yml)
[![Platform](https://img.shields.io/badge/platform-Windows%2011-blue.svg)](https://microsoft.com/windows)
[![Hardware](https://img.shields.io/badge/hardware-ITE%20IT8298-orange.svg)](docs/PROTOCOL_SPEC.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Not affiliated with or endorsed by GIGABYTE. This tool sends commands to your laptop's lighting controller; use it at your own risk.

---

## What it does

```text
aero-rgb run -- pytest      keyboard breathes cyan while tests run, then green or red
aero-rgb hook               Claude Code hooks: cyan while working, amber when it needs you, green when done
aero-rgb daemon             lighting follows CPU load, warns on low battery
aero-rgb status focus       named presets for everyday use
```

### How it reaches the keyboard today

| Backend | Status | Needs |
| :--- | :--- | :--- |
| `control-center` | **Works** on Windows | Gigabyte Control Center installed. Slow: each change starts PowerShell and loads Control Center's libraries. |
| `dry-run` | Works everywhere | Nothing. Prints the USB packets instead of sending them. |
| Direct USB | **Planned** | Nothing extra; would also work on Linux. Waiting on a USB capture to confirm [the protocol spec](docs/PROTOCOL_SPEC.md#verification-status). |

The backend is chosen automatically. Override it with `--backend`, `--dry-run`, or the `AERO_RGB_BACKEND` environment variable.

---

## Install

From a clone of this repository (Python 3.10 or newer):

```bash
pip install .              # the aero-rgb command
pip install ".[daemon]"    # also the CPU and battery daemon (adds psutil)
```

Try it without touching hardware:

```bash
aero-rgb status busy --dry-run
```

---

## Usage

### Presets and custom lighting

```bash
aero-rgb status busy
aero-rgb status success
aero-rgb presets                                   # list them all

aero-rgb set --pattern breathe --color cyan --speed 8 --brightness 8
aero-rgb set --pattern static --color "#FF5500" --brightness 5
aero-rgb set --pattern rainbow --speed 6
```

Patterns: `static`, `breathe` (or `pulse`), `cycle` (or `rainbow`), `rgb-pulse`, `cycle-pulse`.
Colors: `#RRGGBB` or a name such as `cyan`, `amber`, `warmwhite`, `crimson`.

### Wrap any command

```bash
aero-rgb run -- pytest -x
aero-rgb run -- npm test
aero-rgb run --success rainbow -- cargo build --release
```

The keyboard shows `busy` while the command runs, then `success` or `error`. `aero-rgb run` exits with the command's own exit code, so it is safe in scripts. If the lighting fails, the command still runs.

### Claude Code hooks

Your keyboard can tell you when Claude needs you. Merge [`examples/claude-code-hooks.json`](examples/claude-code-hooks.json) into `~/.claude/settings.json` (all projects) or `.claude/settings.json` (one project):

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "aero-rgb hook", "async": true }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "aero-rgb hook", "async": true }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "aero-rgb hook", "async": true }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "aero-rgb hook", "timeout": 10 }] }]
  }
}
```

| Claude Code event | Lighting |
| :--- | :--- |
| You send a prompt (`UserPromptSubmit`) | `busy`: breathing cyan |
| Claude needs permission or input (`Notification`) | `attention`: fast amber pulse |
| Claude finishes its turn (`Stop`) | `success`: breathing green |
| Session ends (`SessionEnd`) | `normal` |

`aero-rgb hook` reads the event from the JSON Claude Code sends, ignores notifications that don't need you (such as sign-in messages), writes nothing to standard output, and always exits 0 so it can never block Claude. `"async": true` keeps the slow Control Center backend from delaying your prompts. To choose your own colors, call `aero-rgb status <preset>` from each hook instead.

### CPU and battery daemon

```bash
aero-rgb daemon --interval 3
```

| Condition | Lighting |
| :--- | :--- |
| Battery under 20% and not plugged in | Breathing orange |
| CPU at 80% or more | Breathing red |
| CPU at 40% or more | Breathing cyan |
| Otherwise | Static teal |

Each level has a 5-point buffer before it switches back down, so load near a threshold doesn't make the lighting flicker. Ctrl+C restores the factory lighting.

### Python

```python
from aero_rgb import set_status, set_keyboard_led

set_status("busy")
set_keyboard_led(pattern="breathe", color="#00FFCC", speed=8, brightness=8)
```

Both raise `aero_rgb.BackendError` if the lighting can't be applied and `ValueError` on bad input.

### PowerShell, without Python

`src/aero_rgb/keyboard_led.ps1` also works on its own (needs Gigabyte Control Center):

```powershell
.\src\aero_rgb\keyboard_led.ps1 -Status busy
.\src\aero_rgb\keyboard_led.ps1 -Pattern Breathe -Color Cyan -Speed 8 -Brightness 8
.\src\aero_rgb\keyboard_led.ps1 -Pattern Static -Color "#FF5500" -Brightness 5
```

---

## Presets

| Preset | Lighting | Use it for |
| :--- | :--- | :--- |
| `normal` (also `idle`) | Static white, brightness 6 | Everyday lighting |
| `busy` (also `building`) | Breathing cyan, speed 8, brightness 8 | Build, tests or an agent is running |
| `success` (also `pass`) | Breathing green, speed 6, brightness 9 | Finished without errors |
| `warning` | Breathing amber, speed 7, brightness 8 | Something needs a look soon |
| `attention` | Breathing amber, speed 9, brightness 10 | Waiting on you |
| `error` (also `fail`) | Breathing red, speed 9, brightness 10 | Build or tests failed |
| `focus` | Static warm white, brightness 3 | Dim light for night work |
| `rainbow` | Color cycle, speed 6, brightness 8 | Ambient color cycle |
| `off` | Brightness 0 | Lights off |
| `restore` | Static white, brightness 7 | Gigabyte's factory baseline |

---

## Help confirm the protocol

[`docs/PROTOCOL_SPEC.md`](docs/PROTOCOL_SPEC.md) describes the USB packets the lighting controller expects, but it hasn't been checked against real traffic yet. If you have an AERO or AORUS laptop:

1. Install [USBPcap](https://desowin.org/usbpcap/) and [Wireshark](https://www.wireshark.org/).
2. Record while Gigabyte Control Center changes the color and pattern.
3. Compare what you captured with what this tool would send:

```bash
aero-rgb set --pattern breathe --color cyan --dry-run
aero-rgb decode 00 14 00 01 00 FF FF 00 EC      # explains each byte and checks the checksum
```

Open an issue with your laptop model, the captured bytes, and what Control Center was set to.

---

## Hardware

| Property | Value |
| :--- | :--- |
| **Target laptop** | GIGABYTE AERO X16 1WH / AORUS laptop series |
| **USB vendor ID** | `0x0414` (Giga-Byte Technology Co., Ltd.) |
| **USB product ID** | `0x8104` |
| **Lighting controller** | ITE IT8298 / IT8233 |
| **Keyboard lighting** | Single zone, full RGB |
| **Extra interface** | Windows Dynamic Lighting `LampArray` notification lamp on `MI_04` |
| **Packet format** | 9-byte USB HID feature report |

---

## Project structure

```text
aero-keyboard-rgb/
├── docs/PROTOCOL_SPEC.md           # Reverse-engineered packet format and open questions
├── examples/claude-code-hooks.json # Ready-to-merge Claude Code hooks
├── src/aero_rgb/
│   ├── protocol.py                 # Colors, patterns, presets, packet building (no hardware access)
│   ├── backends.py                 # Control Center and dry-run backends
│   ├── cli.py                      # The aero-rgb command
│   ├── daemon.py                   # CPU and battery daemon
│   └── keyboard_led.ps1            # PowerShell script that drives Gigabyte Control Center
└── tests/                          # Run anywhere: no hardware needed
```

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests also check that the PowerShell script's presets and colors match the Python ones.

## License

[MIT](LICENSE)

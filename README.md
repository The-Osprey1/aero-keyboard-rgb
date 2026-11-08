# AERO-Keyboard-RGB

> Keyboard lighting control, status signals, and personalization for **GIGABYTE AERO & AORUS** laptops.

[![Platform](https://img.shields.io/badge/platform-Windows%2011%20%7C%20Linux-blue.svg)]()
[![Hardware](https://img.shields.io/badge/hardware-ITE%20IT8298-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## What it does

- **Set any color and pattern**: static, breathing, rainbow, RGB pulse, cycle pulse.
- **Your own colors and presets** in a settings file, plus a **time-of-day schedule**
  (for example, warm and dim after 10 pm).
- **Battery level as the keyboard color**: green when full, through yellow, to red when empty.
  It breathes while charging and warns when low.
- **USB plug-in pulses**: the keyboard pulses when you plug something in, with a color for each
  device type (drive, phone, mouse...) or for each port you name.
- **File transfer progress**: the color moves from blue to green as a File Explorer copy
  progresses, then flashes when it's done.
- **Build and command signals**: `aero-rgb run -- pytest` breathes cyan while it runs, then turns
  green (passed) or red (failed).

All of these share the light sensibly. A background program decides what shows. Short alerts
(USB pulses, low battery) take over for a few seconds, then the light goes back to whatever was
underneath.

The GIGABYTE AERO X16 1WH has a **single-zone** keyboard: the whole keyboard shows one color at a
time, in any of 16.7 million colors. If your model has zones, `aero-rgb probe --zones` finds them,
and USB pulses can then light only the area nearest the port.

## Status

The code is tested automatically on Windows and Linux, but **it hasn't been run on the laptop
yet**. Some protocol details still need confirming on real hardware:

| Part | State |
| :--- | :--- |
| Gigabyte Control Center route (`--backend powershell`) | Same method as the original script |
| Direct USB route (`--backend hid`), no Gigabyte software needed | Needs the [hardware test](docs/HARDWARE_TESTING.md) |
| Battery, USB detection, transfers, schedule, presets | Tested with simulated input; needs a real-world try |

**Start with [docs/HARDWARE_TESTING.md](docs/HARDWARE_TESTING.md).** It takes about 10 minutes.

---

## Install

Requires Python 3.9 or newer.

```powershell
git clone https://github.com/The-Osprey1/aero-keyboard-rgb
cd aero-keyboard-rgb
python -m pip install -e ".[hid]"
```

The `[hid]` part adds the direct USB route. Without it, the tool uses Gigabyte Control Center's
files, so Control Center must be installed (it doesn't need to be running).

## Everyday use

```powershell
aero-rgb set -p breathe -c "#00FFCC" -b 8 -s 6   # pattern, color, brightness 0-10, speed 1-10
aero-rgb set -c mint                             # static mint
aero-rgb preset focus                            # built-in or your own presets
aero-rgb list                                    # every preset, pattern and color name
aero-rgb battery --show                          # flash the battery color
aero-rgb --dry-run preset busy                   # show the bytes without touching the keyboard
```

Built-in presets:

| Preset | Look | Use |
| :--- | :--- | :--- |
| `normal` / `idle` | Static soft white | Everyday |
| `busy` / `building` | Breathing cyan | Something running |
| `success` / `pass` | Breathing green | It worked |
| `warning` | Breathing amber | Needs attention |
| `error` / `fail` | Fast red pulse | It failed |
| `focus` | Dim warm white | Night / low eye strain |
| `rainbow` | Color cycle | Ambient |
| `off` | Off | Stealth |
| `restore` | White, brightness 7 | Factory-like default |

## The background program

```powershell
aero-rgb daemon      # runs battery, USB, transfer and schedule features
aero-rgb layers      # in another terminal: what it's showing and why
```

While it runs, `set`, `preset`, `run` and `copy` send their requests to it instead of the keyboard,
so nothing fights over the light.

### USB ports

```powershell
aero-rgb ports calibrate left-usb-c --color blue --label "Left side"
aero-rgb ports list
aero-rgb usb          # every plugged-in device, its type and location
```

`calibrate` waits for you to plug something into that port. Do it twice per port: once with a fast
device (flash drive) and once with a slow one (mouse). Fast and slow devices report different
locations for the same physical port. Ports you haven't named still pulse, using the device-type
color.

### File transfers

There are 3 sources of progress:

1. **File Explorer copies (Windows)**: the exact percentage, read from the copy window's title.
2. **Any program writing to a USB drive**: the keyboard breathes faster the faster it writes.
   This only covers drives plugged in after the background program started.
3. **`aero-rgb copy <from...> <to>`**: copies files itself, so it always knows the exact progress.

### Developer signals

```powershell
aero-rgb run -- pytest
aero-rgb run -- npm test
aero-rgb run -- cargo build --release
```

The command's exit code is passed through, so `run` works in scripts and git hooks. From Python:

```python
from aero_rgb import set_status, set_keyboard_led

set_status("busy")
set_keyboard_led(pattern="breathe", color="#00FFCC", speed=8, brightness=8)
```

## Personalize

```powershell
aero-rgb config init    # creates a settings file with every option explained
aero-rgb config path    # where it is
aero-rgb config check   # checks it for mistakes
```

Example:

```toml
[colors]
brand = "#7B2FF7"

[presets.gaming]
pattern = "breathe"
color = "brand"
brightness = 9
speed = 5

[base]
preset = "gaming"

[[schedule]]
from = "22:00"
to = "07:00"
preset = "focus"

[battery]
mode = "on_change"   # off | warning | on_change | always

[usb.kind_colors]
storage = "cyan"
phone = "purple"
```

See [src/aero_rgb/data/config.example.toml](src/aero_rgb/data/config.example.toml) for every setting.

## Start automatically at login

**Windows**: open Command Prompt and run (`pythonw` runs it without a window):

```bat
schtasks /Create /SC ONLOGON /TN "aero-rgb" /TR "pythonw -m aero_rgb daemon" /RL LIMITED
```

Remove it with `schtasks /Delete /TN "aero-rgb"`.

**Linux** (systemd): save as `~/.config/systemd/user/aero-rgb.service`, then run
`systemctl --user enable --now aero-rgb`:

```ini
[Unit]
Description=aero-rgb keyboard lighting

[Service]
ExecStart=%h/.local/bin/aero-rgb daemon
Restart=on-failure

[Install]
WantedBy=default.target
```

---

## Project structure

```text
aero-keyboard-rgb/
├── docs/
│   ├── PROTOCOL_SPEC.md        # The lighting chip's command format
│   └── HARDWARE_TESTING.md     # Checklist for confirming everything on the laptop
├── src/aero_rgb/
│   ├── cli.py                  # The aero-rgb command
│   ├── protocol.py             # Builds the 9-byte commands and checksums
│   ├── backends.py             # Direct USB / Gigabyte Control Center / dry run
│   ├── engine.py               # Decides which request controls the light
│   ├── daemon.py               # The background program
│   ├── config.py               # Settings file
│   ├── state.py, colors.py     # Lighting state, presets and color helpers
│   ├── ipc.py                  # Local messages between commands and the background program
│   ├── keyboard_led.ps1        # Gigabyte Control Center route (also works on its own)
│   └── monitors/
│       ├── battery.py
│       ├── usb.py
│       └── transfer.py
└── tests/
```

Run the tests with `python -m pip install -e ".[dev]"` then `python -m pytest`.

## Hardware details

| Property | Value |
| :--- | :--- |
| **Target** | GIGABYTE AERO X16 1WH / AORUS laptops |
| **USB vendor / product** | `0x0414` (Giga-Byte) / `0x8104` |
| **Lighting chip** | ITE IT8298 / IT8233 |
| **Keyboard lighting** | Single-zone full RGB on the AERO X16 1WH |
| **Extra endpoint** | Windows Dynamic Lighting `LampArray` notification light on `MI_04` |
| **Command format** | 9-byte USB HID (Human Interface Device) feature reports |

Full details, including open questions, are in [docs/PROTOCOL_SPEC.md](docs/PROTOCOL_SPEC.md).

## License

[MIT](LICENSE)

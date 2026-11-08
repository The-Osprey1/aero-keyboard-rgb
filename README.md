# AERO Keyboard RGB

Windows keyboard lighting control, saved profiles and task-completion notifications for compatible Gigabyte laptops.

The backend loads installed Gigabyte Control Center DLLs. GCC need not be running, but its libraries must remain installed. This is not yet an independent HID driver. Existing protocol notes target the AERO X16 1WH; other models need verification.

## Install

Requires Windows, Python 3.8+ and compatible GCC libraries.

```powershell
python -m pip install .
aero-rgb --help
```

From a checkout, `python -m src.cli` also works without installing.

## Save your normal backlight

```powershell
aero-rgb profile save --color White --brightness 6
aero-rgb profile show
aero-rgb profile apply
```

Save writes one baseline without changing hardware. Apply sends it to the controller. Profiles live in `%APPDATA%\aero-keyboard-rgb`; `AERO_RGB_CONFIG_DIR` overrides that directory. This release does not read the keyboard's current state.

## Task notifications

```powershell
aero-rgb run -- python analysis.py
aero-rgb run --seconds 5 -- python -m pytest
```

Signals busy, then success or failure (three seconds by default), then restores your baseline. The child inherits the terminal and its exit code is preserved even if a final lighting update fails. Ctrl+C returns 130 and attempts restoration; a missing command returns 127.

The task is not launched if the initial lighting update fails or no valid baseline exists. Arguments pass directly without shell interpolation. Invoke a shell explicitly for shell syntax or batch commands, e.g. `cmd /c`.

Use commands that remain running until their work is complete. Launching a detached GUI does not establish when its simulation or export ends. Force-killing the wrapper cannot guarantee restoration; use `aero-rgb profile apply` to recover.

**Run only one lighting controller/task wrapper at a time.** The legacy daemon, GCC, Windows Dynamic Lighting and other wrappers may compete. Concurrent task arbitration is not implemented yet.

## Existing controls

```powershell
aero-rgb --status busy
aero-rgb --pattern Breathe --color Cyan --brightness 5 --speed 8
.\src\keyboard_led.ps1 -Status focus
```

Patterns: Static, Breathe/Pulse, Cycle/Rainbow, RgbPulse, CyclePulse. Colors accept supported names or six-digit RGB hex. Brightness: 0-10; speed: 1-10. Invalid colors and controller failures report errors.

```python
from src.keyboard_led import set_keyboard_led, set_status
ok = set_status("busy")
ok = set_keyboard_led(pattern="Static", color="#00FFCC", brightness=5)
```

Legacy `--status restore` means fixed white at brightness 7. Use `profile apply` to restore the saved baseline.

## Legacy telemetry

```powershell
python src/status_daemon.py --interval 3
```

This experimental script reads CPU utilization and battery information, not temperatures. There is no `--mode thermals` option. It still restores fixed white when stopped. Do not run it alongside task alerts.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

Tests mock hardware and cover profiles, task outcomes, cancellation, restoration and controller failures. Actual keyboard behavior requires testing on compatible hardware.

See [protocol notes](docs/PROTOCOL_SPEC.md) and [backend research](docs/HARDWARE_BACKEND_RESEARCH.md).

Follow-up: compatibility diagnostics, a validated independent HID backend, event arbitration, idle/wake handling and a tray UI.

MIT license. Not affiliated with Gigabyte.

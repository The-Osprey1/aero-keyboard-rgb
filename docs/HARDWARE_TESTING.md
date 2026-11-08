# Testing on the laptop

The code was written and tested without access to the keyboard, so a few protocol details
must be confirmed on a real GIGABYTE AERO / AORUS laptop. This page walks through it. It
takes about 10 minutes. None of these tests change permanent settings: the worst case is a
command the chip ignores.

Write down what you see at each step. If anything differs from what's described, open an
issue with your notes.

## 0. Install

```powershell
git clone https://github.com/The-Osprey1/aero-keyboard-rgb
cd aero-keyboard-rgb
python -m pip install -e ".[hid]"
```

`[hid]` installs `hidapi`, which the direct USB route needs.

## 1. Does the old route still work?

If Gigabyte Control Center is installed:

```powershell
aero-rgb --backend powershell preset busy
```

The keyboard should breathe cyan. This uses Gigabyte's own files, so it's the known-good
baseline. If it fails, the problem is with the Control Center install, not this project.

## 2. Find the lighting interface

The lighting chip shows up as one USB device (`0414:8104`) with several interfaces. The
protocol document doesn't say which one takes lighting commands. This finds out:

```powershell
aero-rgb probe                   # lists the interfaces
aero-rgb probe --find-interface  # tries each one and asks if the keyboard turned cyan
```

When you answer "y", it prints 3 lines (`backend`, `hid_interface`, `hid_usage_page`).
Run `aero-rgb config init` if you haven't yet, open the file shown by
`aero-rgb config path`, and paste the lines under `[device]`.

**If no interface works**, go to step 3. The checksum may be the problem.

## 3. Confirm the checksum

The original protocol document has a worked example that disagrees with its own formula by
one (`0xEB` vs `0xEC` for cyan). This project uses the formula. To check:

```powershell
aero-rgb probe --checksum
```

It sends cyan with the formula first, then with the worked example's value, and asks after
each. If only the second works, open an issue: `protocol.checksum` needs changing.

## 4. Check the patterns and brightness

```powershell
aero-rgb set --backend hid -p static  -c red    -b 10
aero-rgb set --backend hid -p static  -c red    -b 2     # should be clearly dimmer
aero-rgb set --backend hid -p breathe -c green  -s 3
aero-rgb set --backend hid -p breathe -c green  -s 10    # should breathe faster
aero-rgb set --backend hid -p rainbow
aero-rgb set --backend hid -p rgbpulse
aero-rgb set --backend hid -p cyclepulse
```

If static brightness has no effect, add `static_brightness_flag = 0x20` under `[device]`
and try again (the protocol document mentions this alternative form).

## 5. Does the keyboard have zones?

```powershell
aero-rgb probe --zones
```

This sends red, green, blue and magenta to zones 1-4.

- **The whole keyboard is one color:** single-zone, as every spec sheet for the AERO X16 1WH
  says. Everything still works; USB pulses just light the whole keyboard.
- **Different areas light differently:** it has zones. Note which area is which number, and
  use `--zone` when naming ports (step 7) so a plug-in pulses the area nearest the port.

## 6. Does the color survive a restart?

Set a color, restart the laptop, and see if it comes back before Windows starts.

- **It comes back:** the chip probably saves each change to permanent memory. That memory
  wears out after many writes, so keep `min_write_interval_ms` at 250 or higher (the
  default), and avoid scripts that change the color many times a second.
- **It doesn't:** changes only live in temporary memory, and wear isn't a concern.

## 7. Background program and USB ports

```powershell
aero-rgb daemon
```

Leave it running and open a second terminal:

```powershell
aero-rgb layers                           # what it's showing and why
aero-rgb ports calibrate left-usb-c --color blue --label "Left side USB-C"
aero-rgb ports calibrate right-usb-a --color purple
aero-rgb ports list
```

`calibrate` waits for you to plug something in. USB-C and blue USB-A ports report a
different location for fast (USB 3) and slow (USB 2) devices, so calibrate each port twice:
once with a flash drive and once with a mouse or keyboard.

Then plug things in and watch the keyboard pulse.

## 8. File transfers

With the background program running, copy a large file (1 GB or more) to a USB drive in
File Explorer. The keyboard should move from blue toward green as the copy progresses, then
flash green when it finishes.

- If nothing happens, check the copy window's title. If it doesn't say "NN% complete"
  (for example, Windows isn't in English), change `title_pattern` under `[transfer]`.
- The keyboard should also breathe while *any* program writes to a USB drive plugged in
  after the background program started.

## 9. Battery

```powershell
aero-rgb battery --show
```

Shows the color for your current charge level for a few seconds. Set `mode = "always"`
under `[battery]` to make it permanent.

## Linux notes

The direct route works on Linux too (Gigabyte's software isn't needed). Normal users can't
open the device without a permission rule. Create `/etc/udev/rules.d/70-aero-rgb.rules`
containing:

```text
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0414", ATTRS{idProduct}=="8104", TAG+="uaccess"
```

Then run `sudo udevadm control --reload && sudo udevadm trigger` and unplug or reboot.

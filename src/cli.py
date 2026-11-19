"""Saved backlight profiles and foreground command notifications."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from .keyboard_led import set_keyboard_led, set_status, main as legacy_main

PATTERNS = ["Static", "Breathe", "Pulse", "Cycle", "Rainbow", "RgbPulse", "CyclePulse"]
COLORS = set("black off white warmwhite red crimson green lime blue deepblue cyan teal magenta purple yellow gold orange amber pink".split())


def profile_path():
    root = os.environ.get("AERO_RGB_CONFIG_DIR")
    if root:
        return Path(root) / "profile.json"
    return Path(os.environ.get("APPDATA", Path.home() / ".config")) / "aero-keyboard-rgb" / "profile.json"


def validate(profile):
    if not isinstance(profile, dict) or set(profile) != {"pattern", "color", "brightness", "speed"}:
        raise ValueError("Profile must contain pattern, color, brightness and speed.")
    if profile["pattern"] not in PATTERNS:
        raise ValueError("Invalid pattern.")
    color = profile["color"]
    if not isinstance(color, str) or not (color.lower() in COLORS or re.fullmatch(r"(?:#|0x)?[0-9a-fA-F]{6}", color)):
        raise ValueError("Use a supported color name or six-digit RGB hex.")
    for key, low, high in [("brightness", 0, 10), ("speed", 1, 10)]:
        if type(profile[key]) is not int or not low <= profile[key] <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}.")
    return profile


def load_profile():
    try:
        return validate(json.loads(profile_path().read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise ValueError("Save your normal backlight first: aero-rgb profile save --color White --brightness 6")


def save_profile(profile):
    validate(profile)
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(profile, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_task(command, seconds):
    baseline = load_profile()
    if not set_status("busy"):
        set_keyboard_led(**baseline)
        return 1
    result = 1
    try:
        try:
            result = subprocess.call(command)  # Inherit terminal; no shell interpolation.
        except FileNotFoundError:
            print(f"Command not found: {command[0]}", file=sys.stderr)
            result = 127
        except OSError as exc:
            print(f"Cannot start task: {exc}", file=sys.stderr)
            result = 126
        except KeyboardInterrupt:
            result = 130
        if result != 130:
            if not set_status("success" if result == 0 else "error"):
                print("Task finished, but its lighting notification failed.", file=sys.stderr)
            time.sleep(seconds)
    except KeyboardInterrupt:
        result = 130
    finally:
        if not set_keyboard_led(**baseline):
            print("Could not restore lighting. Retry: aero-rgb profile apply", file=sys.stderr)
    # Preserve the task result even if a later lighting update fails.
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        return legacy_main(argv)
    parser = argparse.ArgumentParser(description="AERO backlight profiles and task notifications")
    subs = parser.add_subparsers(dest="action", required=True)
    profile = subs.add_parser("profile", help="Save, show or apply your normal backlight")
    actions = profile.add_subparsers(dest="profile_action", required=True)
    save = actions.add_parser("save", help="Save a baseline without changing hardware")
    save.add_argument("--color", default="White")
    save.add_argument("--pattern", choices=PATTERNS, default="Static")
    save.add_argument("--brightness", type=int, default=6)
    save.add_argument("--speed", type=int, default=8)
    actions.add_parser("show")
    actions.add_parser("apply")
    run = subs.add_parser("run", help="Run a command, signal its result, then restore your profile")
    run.add_argument("--seconds", type=float, default=3, help="Result display duration (0-60 seconds)")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "profile":
            if args.profile_action == "save":
                save_profile({k: getattr(args, k) for k in ("pattern", "color", "brightness", "speed")})
                print(f"Saved baseline: {profile_path()}")
                return 0
            profile = load_profile()
            if args.profile_action == "show":
                print(json.dumps(profile, indent=2))
                return 0
            return 0 if set_keyboard_led(**profile) else 1
        command = args.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("run requires a command after --")
        if not math.isfinite(args.seconds) or not 0 <= args.seconds <= 60:
            parser.error("--seconds must be between 0 and 60")
        return run_task(command, args.seconds)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

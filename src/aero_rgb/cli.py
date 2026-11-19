"""aero-rgb command-line tool."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Sequence, TextIO

from . import __version__
from .backends import BACKEND_NAMES, Backend, BackendError, get_backend
from .protocol import (
    PATTERNS,
    PRESET_ALIASES,
    PRESET_DESCRIPTIONS,
    PRESETS,
    LightingState,
    decode_packet,
    parse_packet_text,
    resolve_preset,
)

# Claude Code hook event -> preset. See examples/claude-code-hooks.json.
HOOK_PRESETS = {
    "UserPromptSubmit": "busy",  # agent is working
    "Notification": "attention",  # agent is waiting on you
    "Stop": "success",  # agent finished its turn
    "SessionEnd": "normal",
}
# Notification also fires for things that don't need you (sign-in success, quota notices,
# plugin messages). Only these types mean "come back to the keyboard".
ATTENTION_NOTIFICATIONS = frozenset(
    {"permission_prompt", "idle_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"}
)


def _backend_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    group = common.add_mutually_exclusive_group()
    group.add_argument(
        "--backend",
        choices=BACKEND_NAMES,
        help="how to reach the keyboard (default: the AERO_RGB_BACKEND variable, else auto)",
    )
    group.add_argument(
        "--dry-run",
        action="store_const",
        const="dry-run",
        dest="backend",
        help="print the packets instead of touching hardware",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aero-rgb",
        description="Keyboard lighting control for GIGABYTE AERO and AORUS laptops.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    common = _backend_options()

    p = sub.add_parser("set", parents=[common], help="set a pattern, color, brightness and speed")
    p.add_argument("--pattern", "-p", default="static", help=f"one of: {', '.join(PATTERNS)} (default: static)")
    p.add_argument("--color", "-c", default="white", help="color name or #RRGGBB (default: white)")
    p.add_argument("--brightness", "-b", type=int, default=7, help="0-10 (default: 7)")
    p.add_argument("--speed", "-s", type=int, default=8, help="1-10, for animated patterns (default: 8)")

    p = sub.add_parser("status", parents=[common], help="apply a named preset such as busy, success or error")
    p.add_argument("preset", help="preset name; run 'aero-rgb presets' to list them")

    sub.add_parser("presets", help="list the presets")

    p = sub.add_parser(
        "run",
        parents=[common],
        help="run a command with busy lighting, then show success or failure",
        description=(
            "Run COMMAND with 'busy' lighting, then switch to 'success' or 'error' based on its exit code. "
            "Exits with the command's exit code, so it works in scripts. Example: aero-rgb run -- pytest -x"
        ),
    )
    p.add_argument("--busy", default="busy", metavar="PRESET", help="preset while running (default: busy)")
    p.add_argument("--success", default="success", metavar="PRESET", help="preset on exit code 0 (default: success)")
    p.add_argument("--failure", default="error", metavar="PRESET", help="preset on failure (default: error)")
    p.add_argument("cmd", nargs=argparse.REMAINDER, metavar="COMMAND", help="the command to run, after --")

    p = sub.add_parser(
        "hook",
        parents=[common],
        help="Claude Code hook: set lighting from the hook event",
        description=(
            "For Claude Code hooks. Reads the hook event from standard input (or EVENT) and applies a preset: "
            + ", ".join(f"{event} -> {preset}" for event, preset in HOOK_PRESETS.items())
            + ". Always exits 0 so it never blocks Claude."
        ),
    )
    p.add_argument("event", nargs="?", help="hook event name, if not reading it from standard input")

    p = sub.add_parser("daemon", parents=[common], help="mirror CPU load and battery on the lighting")
    p.add_argument("--interval", "-i", type=float, default=3.0, help="seconds between checks (default: 3)")

    p = sub.add_parser(
        "decode",
        help="explain a packet byte by byte (for checking USB captures against the spec)",
        description="Example: aero-rgb decode 00 14 00 01 00 FF FF 00 EC",
    )
    p.add_argument("bytes", nargs="+", help="packet bytes in hex")

    return parser


def _apply(backend: Backend, state: LightingState) -> None:
    backend.apply(state)
    if backend.name != "dry-run":
        print(f"Lighting set: {state.describe()}")


def _try_apply(backend: Backend, preset: str, err: TextIO) -> None:
    """Apply a preset, but only warn on failure: lighting must never break the wrapped command."""
    try:
        backend.apply(resolve_preset(preset))
    except BackendError as exc:
        print(f"aero-rgb: warning: {exc}", file=err)


def cmd_run(args: argparse.Namespace) -> int:
    command = list(args.cmd)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("aero-rgb: error: give a command to run, for example: aero-rgb run -- pytest", file=sys.stderr)
        return 2
    for preset in (args.busy, args.success, args.failure):
        resolve_preset(preset)  # fail early on a typo, before running anything

    try:
        backend = get_backend(args.backend, stream=sys.stderr)
    except BackendError as exc:
        print(f"aero-rgb: warning: {exc}", file=sys.stderr)
        backend = None

    # shutil.which honors PATHEXT on Windows, so "npm" finds npm.cmd.
    executable = shutil.which(command[0])
    if executable is None:
        print(f"aero-rgb: error: command not found: {command[0]}", file=sys.stderr)
        if backend:
            _try_apply(backend, args.failure, sys.stderr)
        return 127
    command[0] = executable

    if backend:
        _try_apply(backend, args.busy, sys.stderr)
    process = subprocess.Popen(command)
    try:
        code = process.wait()
    except KeyboardInterrupt:
        # The child got the same Ctrl+C; let it finish, then show neutral lighting.
        process.wait()
        if backend:
            _try_apply(backend, "normal", sys.stderr)
        return 130
    if backend:
        _try_apply(backend, args.success if code == 0 else args.failure, sys.stderr)
    return code


def _read_hook_payload(stdin: TextIO | None) -> dict:
    if stdin is None or stdin.isatty():
        return {}
    try:
        payload = json.loads(stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def hook_preset(event: str | None, payload: dict) -> str | None:
    """Which preset a Claude Code hook event should show, or None to leave the lighting alone."""
    preset = HOOK_PRESETS.get(event or "")
    if event == "Notification":
        kind = payload.get("notification_type")
        if kind is not None and kind not in ATTENTION_NOTIFICATIONS:
            return None
    return preset


def cmd_hook(args: argparse.Namespace) -> int:
    # Writes nothing to standard output: Claude Code adds a hook's standard output to its context.
    payload = _read_hook_payload(sys.stdin)
    event = args.event or payload.get("hook_event_name")
    preset = hook_preset(event if isinstance(event, str) else None, payload)
    if preset is None:
        return 0
    try:
        get_backend(args.backend, stream=sys.stderr).apply(resolve_preset(preset))
    except Exception as exc:  # a lighting problem must never block Claude Code
        print(f"aero-rgb hook: {exc}", file=sys.stderr)
    return 0


def cmd_presets() -> int:
    aliases: dict[str, list[str]] = {}
    for alias, target in PRESET_ALIASES.items():
        aliases.setdefault(target, []).append(alias)
    name_width = max(len(name) for name in PRESETS)
    state_width = max(len(state.describe()) for state in PRESETS.values())
    for name, state in PRESETS.items():
        also = f"  (also: {', '.join(aliases[name])})" if name in aliases else ""
        print(f"{name:<{name_width}}  {state.describe():<{state_width}}  {PRESET_DESCRIPTIONS[name]}{also}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "presets":
            return cmd_presets()
        if args.command == "decode":
            for line in decode_packet(parse_packet_text(" ".join(args.bytes))):
                print(line)
            return 0
        if args.command == "hook":
            return cmd_hook(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "set":
            state = LightingState.build(args.pattern, args.color, args.brightness, args.speed)
            _apply(get_backend(args.backend), state)
            return 0
        if args.command == "status":
            _apply(get_backend(args.backend), resolve_preset(args.preset))
            return 0
        if args.command == "daemon":
            from . import daemon

            return daemon.run(get_backend(args.backend, stream=sys.stderr), interval=args.interval)
    except (ValueError, BackendError) as exc:
        print(f"aero-rgb: error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

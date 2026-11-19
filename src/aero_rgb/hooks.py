"""Claude Code hooks: show on the keyboard what a Claude Code session is doing.

Claude Code runs ``aero-rgb hook`` and sends a JSON description of the event on standard
input. This module decides what to show; the command in cli.py applies it through the
background program (as a layer, so it shares the light with everything else) or directly.

Each Claude Code session gets its own layer, so two sessions can't wipe out each other's
"needs you" signal: the higher priority wins.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, TextIO

from .engine import PRIORITY_ALERT, PRIORITY_TASK, PRIORITY_WARNING

# Notification also fires for things that don't need you (sign-in success, quota notices,
# plugin messages). Only these mean "come back to the keyboard".
ATTENTION_NOTIFICATIONS = frozenset({
    "permission_prompt",
    "idle_prompt",
    "elicitation_dialog",
    "elicitation_url_dialog",
    "agent_needs_input",
})

HANDLED_EVENTS = ("UserPromptSubmit", "Notification", "PostToolUse", "Stop", "SessionEnd")


@dataclass(frozen=True)
class HookDecision:
    action: str  # "show", "clear" or "ignore"
    preset: Optional[str] = None
    priority: int = PRIORITY_TASK
    duration: Optional[float] = None  # seconds; only the background program honors it


IGNORE = HookDecision("ignore")


def decide(event: Optional[str], payload: Mapping[str, Any], last_preset: Optional[str],
           result_seconds: float = 10.0) -> HookDecision:
    """What to show for one Claude Code hook event."""
    if event == "UserPromptSubmit":
        return HookDecision("show", "busy", PRIORITY_TASK)
    if event == "Notification":
        kind = payload.get("notification_type")
        if kind is not None and kind not in ATTENTION_NOTIFICATIONS:
            return IGNORE
        return HookDecision("show", "attention", PRIORITY_WARNING)
    if event == "PostToolUse":
        # After you approve a permission prompt, Claude carries on working, but no
        # dedicated event says so. The next finished tool call means it's busy again.
        return HookDecision("show", "busy", PRIORITY_TASK) if last_preset == "attention" else IGNORE
    if event == "Stop":
        return HookDecision("show", "success", PRIORITY_ALERT, result_seconds)
    if event == "SessionEnd":
        return HookDecision("clear")
    return IGNORE


def read_payload(stream: Optional[TextIO]) -> dict:
    """The JSON Claude Code sends on standard input, or {} if there is none or it's unreadable."""
    if stream is None or stream.isatty():
        return {}
    try:
        payload = json.loads(stream.read() or "{}")
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def session_key(payload: Mapping[str, Any]) -> str:
    raw = str(payload.get("session_id") or "default")
    return re.sub(r"[^A-Za-z0-9_-]", "", raw)[:64] or "default"


def layer_name(payload: Mapping[str, Any]) -> str:
    return f"claude-{session_key(payload)}"


class SessionMemory:
    """Remembers the last preset shown for each session, in a small file in the temp folder."""

    def __init__(self, folder: Optional[Path] = None):
        self.folder = folder or Path(tempfile.gettempdir()) / "aero-rgb-hooks"

    def _path(self, key: str) -> Path:
        return self.folder / key

    def get(self, key: str) -> Optional[str]:
        try:
            return self._path(key).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def set(self, key: str, preset: str) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(preset, encoding="utf-8")
        except OSError:
            pass  # remembering is a nicety; never fail the hook over it

    def forget(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except OSError:
            pass

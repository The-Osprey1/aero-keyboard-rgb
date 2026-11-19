"""Show file transfer progress on the keyboard.

Two sources, used together:

1. **Copy-window titles (Windows).** File Explorer's copy window title contains text like
   "45% complete". Reading window titles gives the exact percentage.
2. **Drive write activity (any system).** For drives plugged in after startup (normally USB
   drives), the write speed is measured. This shows *that* a transfer is happening, not how
   far along it is.

``aero-rgb copy`` is a third, fully reliable source: it does the copying itself and reports
exact progress to the background program.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..colors import lerp
from ..config import TransferConfig
from ..engine import PRIORITY_ALERT, PRIORITY_TASK, LightEngine
from ..state import LightState

LAYER = "transfer"
LAYER_DONE = "transfer-done"


def progress_state(percent: float, cfg: TransferConfig) -> LightState:
    """Color shifts from start_color to end_color as the transfer goes; 5% steps."""
    stepped = max(0, min(100, int(percent // 5 * 5)))
    return LightState("static", lerp(cfg.start_color, cfg.end_color, stepped / 100.0), cfg.brightness)


def activity_state(kilobytes_per_second: float, cfg: TransferConfig) -> LightState:
    """Breathing start_color; faster breathing for faster writes (about 0.5 MB/s up to 200 MB/s)."""
    import math
    low = max(cfg.activity_threshold_kbps, 1.0)
    span = math.log10(200_000 / low) if low < 200_000 else 1.0
    level = (math.log10(max(kilobytes_per_second, low) / low) / span) if span else 1.0
    speed = 3 + round(min(1.0, max(0.0, level)) * 6)
    return LightState("breathe", cfg.start_color, cfg.brightness, speed)


def done_state(cfg: TransferConfig) -> LightState:
    return LightState("breathe", cfg.end_color, 10, 9)


def find_progress(titles: Iterable[str], pattern: str) -> Optional[int]:
    """Lowest percentage found in any window title (the transfer furthest from done)."""
    regex = re.compile(pattern, re.IGNORECASE)
    found = []
    for title in titles:
        match = regex.search(title)
        if match:
            value = int(match.group(1))
            if 0 <= value <= 100:
                found.append(value)
    return min(found) if found else None


def windows_window_titles() -> List[str]:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    titles: List[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    def callback(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return titles


def window_titles() -> List[str]:
    return windows_window_titles() if sys.platform == "win32" else []


def disk_write_bytes() -> Dict[str, int]:
    try:
        import psutil
    except ImportError:
        return {}
    counters = psutil.disk_io_counters(perdisk=True) or {}
    return {name: c.write_bytes for name, c in counters.items()}


class TransferMonitor:
    def __init__(self, engine: LightEngine, cfg: TransferConfig,
                 titles: Callable[[], List[str]] = window_titles,
                 disk_counters: Callable[[], Dict[str, int]] = disk_write_bytes,
                 log: Optional[Callable[[str], None]] = None):
        self.engine = engine
        self.cfg = cfg
        self.titles = titles
        self.disk_counters = disk_counters
        self.log = log
        self._startup_disks: Optional[set] = None
        self._last_counts: Optional[Tuple[float, Dict[str, int]]] = None
        self._active = False
        self._last_busy = 0.0
        self._next_poll = 0.0

    def _drive_rate(self, now: float) -> float:
        """Combined write speed (KB/s) of the watched drives."""
        counts = self.disk_counters()
        if self._startup_disks is None:
            self._startup_disks = set(counts)
        watched = {k: v for k, v in counts.items() if not self.cfg.only_new_drives or k not in self._startup_disks}
        previous, self._last_counts = self._last_counts, (now, counts)
        if previous is None or now <= previous[0]:
            return 0.0
        before = previous[1]
        written = sum(max(0, v - before[k]) for k, v in watched.items() if k in before)
        return written / 1024.0 / (now - previous[0])

    def tick(self, now: float) -> None:
        if not self.cfg.enabled or now < self._next_poll:
            return
        self._next_poll = now + self.cfg.poll_seconds
        percent = find_progress(self.titles(), self.cfg.title_pattern)
        rate = self._drive_rate(now)

        if percent is not None:
            self._show(progress_state(percent, self.cfg), now)
        elif rate >= self.cfg.activity_threshold_kbps:
            self._show(activity_state(rate, self.cfg), now)
        elif self._active and now - self._last_busy >= self.cfg.idle_seconds:
            self._active = False
            self.engine.clear(LAYER)
            self.engine.set_layer(LAYER_DONE, done_state(self.cfg), PRIORITY_ALERT, duration=self.cfg.done_flash_seconds)
            if self.log:
                self.log("Transfer finished")

    def _show(self, state: LightState, now: float) -> None:
        if not self._active and self.log:
            self.log("Transfer started")
        self._active = True
        self._last_busy = now
        self.engine.set_layer(LAYER, state, PRIORITY_TASK)


# ---------------------------------------------------------------------------
# aero-rgb copy: a copy that knows its own progress
# ---------------------------------------------------------------------------

def _files_to_copy(source: Path, destination: Path) -> List[Tuple[Path, Path]]:
    if source.is_dir():
        target_root = destination / source.name if destination.exists() else destination
        pairs = []
        for folder, _, files in os.walk(source):
            for name in files:
                src = Path(folder) / name
                pairs.append((src, target_root / src.relative_to(source)))
        return pairs
    target = destination / source.name if destination.is_dir() else destination
    return [(source, target)]


def copy_with_progress(sources: List[Path], destination: Path, on_progress: Callable[[float], None],
                       chunk_size: int = 1024 * 1024) -> int:
    """Copy files or folders into ``destination``, calling ``on_progress(percent)`` as it goes.

    Returns the number of bytes copied.
    """
    if len(sources) > 1:
        destination.mkdir(parents=True, exist_ok=True)
    pairs: List[Tuple[Path, Path]] = []
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(source)
        pairs.extend(_files_to_copy(source, destination))
    total = sum(src.stat().st_size for src, _ in pairs) or 1
    done = 0
    on_progress(0.0)
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as reader, open(dst, "wb") as writer:
            while True:
                chunk = reader.read(chunk_size)
                if not chunk:
                    break
                writer.write(chunk)
                done += len(chunk)
                on_progress(min(100.0, done * 100.0 / total))
        shutil.copystat(src, dst)
    on_progress(100.0)
    return done

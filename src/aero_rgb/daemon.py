"""The background program: owns the keyboard light and runs every watcher."""

from __future__ import annotations

import signal
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from .backends import Backend
from .config import Config
from .engine import PRIORITY_ALERT, LightEngine
from .ipc import IpcServer
from .monitors.battery import BatteryMonitor
from .monitors.transfer import TransferMonitor
from .monitors.usb import PortMap, UsbMonitor
from .state import LightState

CLIENT_LAYER_PREFIX = "client:"
MAX_CLIENT_DURATION = 6 * 60 * 60  # a crashed client's layer never sticks around longer than this


class Monitor(Protocol):
    def tick(self, now: float) -> None: ...


def log_line(message: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)


class ScheduleMonitor:
    """Switches the base preset by time of day."""

    def __init__(self, engine: LightEngine, config: Config, wall_clock: Callable[[], datetime] = datetime.now):
        self.engine = engine
        self.config = config
        self.wall_clock = wall_clock
        self._next = 0.0
        self._scheduled: Optional[LightState] = None

    def tick(self, now: float) -> None:
        if now < self._next:
            return
        self._next = now + 30
        scheduled = self.config.base_state(self.wall_clock().time())
        # Only act when the schedule moves to a new preset, so a preset chosen by hand
        # ("aero-rgb preset gaming") stays until the next scheduled switch.
        if scheduled != self._scheduled:
            if self._scheduled is not None:
                self.engine.set_base(scheduled)
            self._scheduled = scheduled


class Daemon:
    def __init__(self, config: Config, backend: Backend, monitors: Optional[List[Monitor]] = None,
                 ipc: Optional[IpcServer] = None, clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = log_line):
        self.config = config
        self.clock = clock
        self.log = log
        self.engine = LightEngine(backend, config.base_state(datetime.now().time()),
                                  config.device.min_write_interval_ms / 1000.0, clock, log)
        self.ipc = ipc
        if monitors is None:
            ports = PortMap.load(config.ports_path, config.colors)
            monitors = [
                ScheduleMonitor(self.engine, config),
                BatteryMonitor(self.engine, config.battery),
                UsbMonitor(self.engine, config.usb, ports, log=log),
                TransferMonitor(self.engine, config.transfer, log=log),
            ]
        self.monitors = monitors

    def handle(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process one message from a local command. Returns the reply."""
        cmd = message.get("cmd")
        try:
            if cmd == "ping":
                return {"ok": True}
            if cmd == "status":
                return {"ok": True, "layers": [
                    {"name": l.name, "priority": l.priority, "state": l.state.to_dict()} for l in self.engine.layers()]}
            if cmd == "base":
                self.engine.set_base(LightState.from_dict(message["state"], self.config.colors))
                return {"ok": True}
            if cmd == "show":
                layer = CLIENT_LAYER_PREFIX + str(message["layer"])
                priority = min(int(message.get("priority", PRIORITY_ALERT)), PRIORITY_ALERT)
                duration = message.get("duration")
                duration = MAX_CLIENT_DURATION if duration is None else min(float(duration), MAX_CLIENT_DURATION)
                state = LightState.from_dict(message["state"], self.config.colors)
                self.engine.set_layer(layer, state, priority, duration)
                return {"ok": True}
            if cmd == "clear":
                self.engine.clear(CLIENT_LAYER_PREFIX + str(message["layer"]))
                return {"ok": True}
        except (KeyError, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    def tick(self) -> None:
        now = self.clock()
        if self.ipc:
            for message, address in self.ipc.poll():
                self.ipc.reply(address, self.handle(message))
        for monitor in self.monitors:
            try:
                monitor.tick(now)
            except Exception as exc:  # one broken watcher shouldn't take the light down
                self.log(f"{type(monitor).__name__} error: {exc}")
        self.engine.update()

    def run(self, interval: float = 0.1) -> None:
        self.log("aero-rgb background program started (Ctrl+C to stop)")

        def stop(signum: int, frame: Any) -> None:
            raise KeyboardInterrupt

        for name in ("SIGTERM", "SIGBREAK", "SIGHUP"):  # stopped by Task Scheduler, a service manager, etc.
            if hasattr(signal, name):
                try:
                    signal.signal(getattr(signal, name), stop)
                except (ValueError, OSError):
                    pass
        self.engine.update(force=True)
        try:
            while True:
                self.tick()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            if self.config.on_exit != "leave":
                try:
                    self.engine.backend.apply(self.config.preset(self.config.on_exit))
                except Exception as exc:
                    self.log(f"Could not restore lighting on exit: {exc}")
            if self.ipc:
                self.ipc.close()
            self.engine.backend.close()
            self.log("Stopped")

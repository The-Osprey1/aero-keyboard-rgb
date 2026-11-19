"""Tiny local messaging so commands like ``aero-rgb run`` can talk to the background program.

Messages are JSON over UDP on 127.0.0.1 only, so nothing outside this computer can reach it.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, List, Optional, Tuple

Address = Tuple[str, int]
HOST = "127.0.0.1"
MAX_MESSAGE = 8192


class IpcServer:
    def __init__(self, port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST, port))
        self.sock.setblocking(False)

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def poll(self) -> List[Tuple[Dict[str, Any], Address]]:
        messages = []
        while True:
            try:
                data, address = self.sock.recvfrom(MAX_MESSAGE)
            except (BlockingIOError, InterruptedError):
                break
            except ConnectionResetError:  # Windows reports earlier failed replies this way
                continue
            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(message, dict):
                messages.append((message, address))
        return messages

    def reply(self, address: Address, message: Dict[str, Any]) -> None:
        try:
            self.sock.sendto(json.dumps(message).encode("utf-8"), address)
        except OSError:
            pass

    def close(self) -> None:
        self.sock.close()


def request(message: Dict[str, Any], port: int, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
    """Send a message and wait for the reply. Returns None if nothing is listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(json.dumps(message).encode("utf-8"), (HOST, port))
        data, _ = sock.recvfrom(MAX_MESSAGE)
        reply = json.loads(data.decode("utf-8"))
        return reply if isinstance(reply, dict) else None
    except (socket.timeout, ConnectionResetError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    finally:
        sock.close()


def daemon_running(port: int) -> bool:
    reply = request({"cmd": "ping"}, port, timeout=0.3)
    return bool(reply and reply.get("ok"))

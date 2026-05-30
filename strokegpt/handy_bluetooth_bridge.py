import time
import threading
from collections import deque


BLUETOOTH_COMMAND_TIMEOUT_SECONDS = 8.0
BLUETOOTH_CLIENT_STALE_SECONDS = 6.0
BLUETOOTH_COMMAND_QUEUE_LIMIT = 120
BLUETOOTH_COMMAND_BATCH_LIMIT = 24


class HandyBluetoothBridge:
    """Synchronous server-side bridge for a browser-owned Handy BLE link."""

    def __init__(self):
        self._condition = threading.Condition()
        self._next_command_id = 1
        self._active_client_id = ""
        self._connected = False
        self._device_name = ""
        self._status = "disconnected"
        self._message = "Bluetooth not connected."
        self._last_seen_at = 0.0
        self._last_error = ""
        self._last_ack = None
        self._pending = deque()
        self._inflight = {}
        self._acks = {}

    def _now(self):
        return time.monotonic()

    def _is_current_client_locked(self, client_id):
        return bool(client_id) and str(client_id) == self._active_client_id

    def _is_stale_locked(self):
        return (
            self._connected
            and bool(self._active_client_id)
            and self._now() - float(self._last_seen_at or 0.0) > BLUETOOTH_CLIENT_STALE_SECONDS
        )

    def _is_ready_locked(self):
        return (
            self._connected
            and bool(self._active_client_id)
            and not self._is_stale_locked()
        )

    def is_ready(self):
        with self._condition:
            return self._is_ready_locked()

    def connect_client(self, client_id, *, device_name="", message=""):
        client_id = str(client_id or "").strip()
        if not client_id:
            return self.snapshot()
        with self._condition:
            now = self._now()
            if self._active_client_id and client_id != self._active_client_id:
                self._fail_all_locked("Bluetooth client changed.")
            self._active_client_id = client_id
            self._connected = True
            self._device_name = str(device_name or "")[:80]
            self._status = "connected"
            self._message = str(message or "Handy Bluetooth connected.")[:180]
            self._last_seen_at = now
            self._last_error = ""
            self._condition.notify_all()
            return self._snapshot_locked()

    def update_client(self, client_id, *, connected=None, status="", message="", device_name="", error=""):
        client_id = str(client_id or "").strip()
        with self._condition:
            if client_id:
                if self._active_client_id and client_id != self._active_client_id and self._connected:
                    return self._snapshot_locked()
                self._active_client_id = client_id
            if device_name:
                self._device_name = str(device_name)[:80]
            if connected is not None:
                self._connected = bool(connected)
            if status:
                self._status = str(status)[:40]
            else:
                self._status = "connected" if self._connected else "disconnected"
            if message:
                self._message = str(message)[:180]
            elif self._connected:
                self._message = "Handy Bluetooth connected."
            if error:
                self._last_error = str(error)[:180]
                self._message = self._last_error
            self._last_seen_at = self._now()
            if not self._connected:
                self._fail_all_locked(self._message or "Bluetooth disconnected.")
            self._condition.notify_all()
            return self._snapshot_locked()

    def disconnect_client(self, client_id="", *, message="Bluetooth disconnected."):
        with self._condition:
            if client_id and self._active_client_id and str(client_id) != self._active_client_id:
                return self._snapshot_locked()
            self._connected = False
            self._status = "disconnected"
            self._message = str(message or "Bluetooth disconnected.")[:180]
            self._last_seen_at = self._now()
            self._fail_all_locked(self._message)
            self._condition.notify_all()
            return self._snapshot_locked()

    def send_command(self, path, body=None, *, timeout=BLUETOOTH_COMMAND_TIMEOUT_SECONDS):
        path = str(path or "").strip()
        if not path:
            return {"ok": False, "error": "missing Bluetooth command path"}
        with self._condition:
            if not self._is_ready_locked():
                return {
                    "ok": False,
                    "error": (
                        "Bluetooth browser bridge is stale."
                        if self._is_stale_locked()
                        else self._message or "Handy Bluetooth is not connected."
                    ),
                    "transport": "browser_bluetooth",
                }
            command_id = self._next_command_id
            self._next_command_id += 1
            command = {
                "id": command_id,
                "path": path,
                "body": dict(body or {}) if isinstance(body, dict) else {},
                "created_at": round(time.time(), 3),
            }
            if len(self._pending) >= BLUETOOTH_COMMAND_QUEUE_LIMIT:
                dropped = self._pending.popleft()
                self._acks[int(dropped["id"])] = {
                    "ok": False,
                    "error": "Bluetooth command queue overflow; dropped pending command.",
                    "transport": "browser_bluetooth",
                }
            self._pending.append(command)
            self._condition.notify_all()
            deadline = self._now() + max(0.1, float(timeout or BLUETOOTH_COMMAND_TIMEOUT_SECONDS))
            while command_id not in self._acks:
                remaining = deadline - self._now()
                if remaining <= 0:
                    self._remove_command_locked(command_id)
                    ack = {
                        "ok": False,
                        "error": "Timed out waiting for browser Bluetooth command acknowledgement.",
                        "transport": "browser_bluetooth",
                    }
                    self._last_ack = ack
                    return ack
                self._condition.wait(timeout=min(remaining, 0.25))
            ack = self._acks.pop(command_id)
            self._last_ack = ack
            return dict(ack)

    def next_commands(self, client_id, *, wait_seconds=4.0):
        client_id = str(client_id or "").strip()
        deadline = self._now() + max(0.0, float(wait_seconds or 0.0))
        with self._condition:
            while not self._pending:
                if not self._is_current_client_locked(client_id) or not self._connected:
                    return []
                self._last_seen_at = self._now()
                remaining = deadline - self._now()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=min(remaining, 0.25))
            if not self._is_current_client_locked(client_id) or not self._connected:
                return []
            commands = []
            while self._pending and len(commands) < BLUETOOTH_COMMAND_BATCH_LIMIT:
                command = self._pending.popleft()
                self._inflight[int(command["id"])] = command
                commands.append(command)
            self._last_seen_at = self._now()
            return commands

    def acknowledge(self, client_id, command_id, *, ok, elapsed_ms=None, error="", response=None):
        with self._condition:
            if not self._is_current_client_locked(str(client_id or "")):
                return self._snapshot_locked()
            try:
                command_id = int(command_id)
            except (TypeError, ValueError):
                return self._snapshot_locked()
            self._inflight.pop(command_id, None)
            ack = {
                "ok": bool(ok),
                "transport": "browser_bluetooth",
            }
            if elapsed_ms is not None:
                try:
                    ack["elapsed_ms"] = round(float(elapsed_ms), 1)
                except (TypeError, ValueError):
                    pass
            if error:
                ack["error"] = str(error)[:180]
                self._last_error = ack["error"]
            if isinstance(response, dict) and response:
                ack["response"] = response
            self._acks[command_id] = ack
            self._last_ack = dict(ack)
            self._last_seen_at = self._now()
            self._condition.notify_all()
            return self._snapshot_locked()

    def _remove_command_locked(self, command_id):
        self._pending = deque(command for command in self._pending if int(command.get("id", 0)) != command_id)
        self._inflight.pop(command_id, None)

    def _fail_all_locked(self, error):
        for command in list(self._pending):
            self._acks[int(command.get("id", 0))] = {
                "ok": False,
                "error": error,
                "transport": "browser_bluetooth",
            }
        self._pending.clear()
        for command_id in list(self._inflight):
            self._acks[int(command_id)] = {
                "ok": False,
                "error": error,
                "transport": "browser_bluetooth",
            }
            self._inflight.pop(command_id, None)

    def _snapshot_locked(self):
        stale = self._is_stale_locked()
        status = "stale" if stale else self._status
        connected = bool(self._connected and not stale)
        return {
            "transport": "browser_bluetooth",
            "connected": connected,
            "status": status,
            "message": "Bluetooth browser bridge is stale." if stale else self._message,
            "device_name": self._device_name,
            "client_id": self._active_client_id,
            "pending": len(self._pending),
            "inflight": len(self._inflight),
            "last_seen_age_ms": (
                round(max(0.0, self._now() - float(self._last_seen_at or 0.0)) * 1000.0, 1)
                if self._last_seen_at
                else None
            ),
            "last_error": self._last_error,
            "last_ack": dict(self._last_ack) if isinstance(self._last_ack, dict) else None,
        }

    def snapshot(self):
        with self._condition:
            return self._snapshot_locked()

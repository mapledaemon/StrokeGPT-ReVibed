import threading
import time
import unittest
from unittest import mock

from strokegpt.handy_bluetooth_bridge import HandyBluetoothBridge


class HandyBluetoothBridgeTests(unittest.TestCase):
    def wait_for_pending(self, bridge, expected=1, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if bridge.snapshot()["pending"] == expected:
                return
            time.sleep(0.01)
        self.fail(f"Timed out waiting for {expected} pending Bluetooth command(s).")

    def test_command_waits_for_browser_ack(self):
        bridge = HandyBluetoothBridge()
        bridge.connect_client("client-1", device_name="Handy")
        result_holder = {}

        def send_command():
            result_holder["result"] = bridge.send_command("hsp/setup", {"stream_id": 12}, timeout=2.0)

        thread = threading.Thread(target=send_command)
        thread.start()

        commands = bridge.next_commands("client-1", wait_seconds=1.0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["path"], "hsp/setup")
        self.assertEqual(commands[0]["body"], {"stream_id": 12})

        bridge.acknowledge(
            "client-1",
            commands[0]["id"],
            ok=True,
            elapsed_ms=12.5,
            response={"hsp_state": {"play_state": "stopped", "stream_id": 12}},
        )
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder["result"]["ok"], True)
        self.assertEqual(result_holder["result"]["elapsed_ms"], 12.5)
        self.assertEqual(result_holder["result"]["response"]["hsp_state"]["stream_id"], 12)

    def test_send_fails_when_bluetooth_is_not_connected(self):
        bridge = HandyBluetoothBridge()
        result = bridge.send_command("hsp/setup", {"stream_id": 1}, timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertIn("not connected", result["error"].lower())

    def test_disconnect_fails_pending_command(self):
        bridge = HandyBluetoothBridge()
        bridge.connect_client("client-1", device_name="Handy")
        result_holder = {}

        def send_command():
            result_holder["result"] = bridge.send_command("hsp/play", {"start_time": 0}, timeout=2.0)

        thread = threading.Thread(target=send_command)
        thread.start()
        commands = bridge.next_commands("client-1", wait_seconds=1.0)
        self.assertEqual(len(commands), 1)

        bridge.disconnect_client("client-1", message="Device disconnected.")
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result_holder["result"]["ok"])
        self.assertEqual(result_holder["result"]["error"], "Device disconnected.")

    def test_active_long_poll_keeps_client_fresh(self):
        bridge = HandyBluetoothBridge()
        bridge.connect_client("client-1", device_name="Handy")
        command_holder = {}
        result_holder = {}

        def poll_commands():
            command_holder["commands"] = bridge.next_commands("client-1", wait_seconds=1.0)

        def send_command():
            result_holder["result"] = bridge.send_command("hsp/setup", {"stream_id": 99}, timeout=1.0)

        with mock.patch("strokegpt.handy_bluetooth_bridge.BLUETOOTH_CLIENT_STALE_SECONDS", 0.2):
            poll_thread = threading.Thread(target=poll_commands)
            poll_thread.start()
            time.sleep(0.35)

            send_thread = threading.Thread(target=send_command)
            send_thread.start()
            poll_thread.join(timeout=1.0)

        self.assertFalse(poll_thread.is_alive())
        self.assertEqual(len(command_holder["commands"]), 1)
        self.assertEqual(command_holder["commands"][0]["path"], "hsp/setup")

        bridge.acknowledge("client-1", command_holder["commands"][0]["id"], ok=True)
        send_thread.join(timeout=1.0)
        self.assertFalse(send_thread.is_alive())
        self.assertTrue(result_holder["result"]["ok"])

    def test_client_change_fails_pending_command_before_new_client_can_drain_it(self):
        bridge = HandyBluetoothBridge()
        bridge.connect_client("client-1", device_name="First Handy")
        result_holder = {}

        def send_command():
            result_holder["result"] = bridge.send_command("hsp/play", {"start_time": 0}, timeout=1.0)

        thread = threading.Thread(target=send_command)
        thread.start()
        self.wait_for_pending(bridge)

        bridge.connect_client("client-2", device_name="Second Handy")
        commands = bridge.next_commands("client-2", wait_seconds=0)
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(commands, [])
        self.assertFalse(result_holder["result"]["ok"])
        self.assertEqual(result_holder["result"]["error"], "Bluetooth client changed.")


if __name__ == "__main__":
    unittest.main()

import threading
import unittest

from strokegpt.handy_bluetooth_bridge import HandyBluetoothBridge


class HandyBluetoothBridgeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FrontendChatStatusTests(unittest.TestCase):
    def test_send_message_handles_action_statuses_as_successes(self):
        script = (PROJECT_ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

        self.assertIn("const actionStatusMessages", script)
        for status in (
            "stopped",
            "auto_started",
            "auto_stopped",
            "freestyle_started",
            "edging_started",
            "milking_started",
            "move_applied",
            "konami_code_activated",
        ):
            with self.subTest(status=status):
                self.assertIn(f"{status}:", script)
        self.assertIn("if (actionStatusMessages[data.status])", script)
        self.assertIn("clearTypingIndicator(data.message || actionStatusMessages[data.status]);", script)
        self.assertIn("if (handleSendMessageStatus(data)) await pollChatUpdates();", script)


if __name__ == "__main__":
    unittest.main()

"""Exercise the chat-emit / TTS-enqueue divergence diagnostic.

Spec (KNOWN_PROBLEMS.md "Local LLM Chat Text Sometimes Missing While Voice
Plays"): when a TTS payload is enqueued without a matching chat-emit (or
with empty chat text), the chat panel and the voice output drift apart and
the user-visible divergence is hard to reproduce. The diagnostic in
``strokegpt.web.add_message_to_queue`` logs a ``[WARN]`` line on those
divergence shapes so a reproduction attempt can be confirmed from the
backend log without needing to instrument the frontend.

The first slice added OBSERVABILITY. The frontend now also renders normal
``/send_message`` replies directly from the response and skips the queued echo
on the next update poll, while this diagnostic remains for future callers that
try to enqueue TTS without a visible chat emit.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests._web_support import WebTestCase


class ChatTtsDivergenceBehavioralTests(WebTestCase):
    """Drive ``add_message_to_queue`` directly and confirm the diagnostic
    actually fires (or stays silent) for the right shapes.

    Patches ``audio.generate_audio_for_text`` so the test never spawns a
    real TTS thread. Captures stdout to read the ``[WARN]`` lines."""

    def _run_add_message(self, **kwargs):
        from strokegpt.web import add_message_to_queue, app_state, audio

        captured = io.StringIO()
        app_state.messages_for_ui.clear()
        with mock.patch.object(audio, "generate_audio_for_text", return_value=None) as gen:
            with redirect_stdout(captured):
                add_message_to_queue(**kwargs)
        return captured.getvalue(), gen

    def test_normal_call_does_not_warn(self):
        """A normal user-visible reply (text + queue + tts) is the
        non-divergent baseline. The diagnostic must stay silent."""
        out, gen = self._run_add_message(
            text="hello there",
            add_to_history=True,
            queue_message=True,
            generate_audio=True,
        )
        self.assertNotIn("[WARN] TTS enqueued without chat-emit", out)
        self.assertNotIn("[WARN] TTS enqueued with empty chat text", out)
        gen.assert_called_once()

    def test_warns_when_queue_message_false_but_tts_on(self):
        """queue_message=False + generate_audio=True is the regression
        shape: TTS speaks while the chat panel never receives the bubble."""
        out, gen = self._run_add_message(
            text="hidden audio reply",
            add_to_history=False,
            queue_message=False,
            generate_audio=True,
        )
        self.assertIn("[WARN] TTS enqueued without chat-emit", out)
        self.assertIn("text_len=", out)
        self.assertIn("'hidden audio reply'", out)
        gen.assert_called_once()

    def test_warns_when_chat_text_is_empty_but_tts_on(self):
        """Whitespace-only or HTML-only text would render as a blank bubble
        and the front-end may drop it. Warn so the case is visible."""
        out, gen = self._run_add_message(
            text="   ",
            add_to_history=False,
            queue_message=True,
            generate_audio=True,
        )
        self.assertIn("[WARN] TTS enqueued with empty chat text", out)
        gen.assert_called_once()

    def test_warns_when_only_html_tags_so_visible_text_is_empty(self):
        """The chat-history strip uses ``re.sub(r'<[^>]+>', '', text)``;
        the diagnostic must use the same definition of "empty" so a
        markup-only message is flagged consistently."""
        out, gen = self._run_add_message(
            text="<i></i>",
            add_to_history=False,
            queue_message=True,
            generate_audio=True,
        )
        self.assertIn("[WARN] TTS enqueued with empty chat text", out)
        gen.assert_called_once()

    def test_does_not_warn_when_tts_disabled(self):
        """Chat-only emits (transport-error fallback, mode narration with
        TTS disabled) should never trigger the diagnostic regardless of
        whether ``queue_message`` was true or false."""
        for queue_message in (True, False):
            with self.subTest(queue_message=queue_message):
                out, gen = self._run_add_message(
                    text="diagnostic body",
                    add_to_history=False,
                    queue_message=queue_message,
                    generate_audio=False,
                )
                self.assertNotIn("[WARN] TTS enqueued without chat-emit", out)
                self.assertNotIn("[WARN] TTS enqueued with empty chat text", out)
                gen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

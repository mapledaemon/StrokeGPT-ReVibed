import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOTION_CONTROL_JS = PROJECT_ROOT / "static" / "js" / "motion-control.js"
SEQUENCE_LOG_JS = PROJECT_ROOT / "static" / "js" / "motion" / "sequence-log.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body(source, signature_prefix):
    """Return the brace-matched body of the first function whose declaration
    starts with ``signature_prefix``. Used to scope assertions to a single
    function so unrelated module text cannot satisfy them."""
    start = source.find(signature_prefix)
    if start < 0:
        raise AssertionError(f"declaration {signature_prefix!r} not found")
    open_brace = source.find("{", start)
    if open_brace < 0:
        raise AssertionError(f"opening brace not found after {signature_prefix!r}")
    depth = 0
    for index in range(open_brace, len(source)):
        ch = source[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : index + 1]
    raise AssertionError(f"unbalanced braces in body of {signature_prefix!r}")


class MotionStatusLogTimecodeTests(unittest.TestCase):
    """Pin the contract for the motion-status-log timecode reset bug.

    Spec (KNOWN_PROBLEMS.md): on stop the most recent log entry must NOT be
    rewritten to ``00:00``. Log timecodes stay frozen at their recorded
    elapsed time, and both the active-mode timer and the log only reset to
    ``00:00`` when a new mode is started.
    """

    def setUp(self):
        self.motion_control = _read(MOTION_CONTROL_JS)
        self.sequence_log = _read(SEQUENCE_LOG_JS)
        self.update_timer_body = _function_body(
            self.motion_control, "function updateActiveModeTimer("
        )

    def test_stop_branch_does_not_null_active_mode_elapsed(self):
        """The ``!normalizedMode`` (stop) branch in updateActiveModeTimer must
        not zero ``state.activeModeElapsedSeconds``. If it did, the next
        sequence-log entry would render with timestamp ``00:00`` because
        ``motionSequenceLogTime()`` reads that value via ``?? 0``.
        """
        stop_branch_match = re.search(
            r"if \(!normalizedMode\)\s*\{(?P<body>.*?)\}",
            self.update_timer_body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            stop_branch_match,
            "expected an 'if (!normalizedMode)' early-return branch in updateActiveModeTimer",
        )
        stop_branch = stop_branch_match.group("body")

        self.assertNotIn(
            "state.activeModeElapsedSeconds = null",
            stop_branch,
            "stop branch must not reset state.activeModeElapsedSeconds to null; "
            "doing so causes the sequence log to emit 00:00 on stop instead of "
            "preserving the elapsed timecode of the prior entry.",
        )
        self.assertNotIn(
            "state.activeModeElapsedSeconds = 0",
            stop_branch,
            "stop branch must not reset state.activeModeElapsedSeconds to 0 either.",
        )

        # The branch should still hide the timer UI; the value just stays cached.
        self.assertIn("el.edgingTimer.style.display = 'none'", stop_branch)

    def test_active_mode_elapsed_assigned_only_when_mode_active(self):
        """The elapsed counter should only be (re)assigned when a mode is
        actually active. Combined with the stop-branch check above, this means
        starting a new mode is the only path that updates the elapsed value
        the sequence log reads.
        """
        assignments = [
            line.strip()
            for line in self.update_timer_body.splitlines()
            if "state.activeModeElapsedSeconds" in line and "=" in line and "==" not in line
        ]
        # We expect exactly one write: the non-stop assignment after the early
        # return. Any reads (e.g. previousElapsed = state.activeModeElapsedSeconds)
        # are filtered out below.
        writes = [
            line
            for line in assignments
            if re.match(r"state\.activeModeElapsedSeconds\s*=", line)
        ]
        self.assertEqual(
            len(writes),
            1,
            f"expected a single write to state.activeModeElapsedSeconds in "
            f"updateActiveModeTimer; got: {writes!r}",
        )
        self.assertIn("nextElapsed", writes[0])

    def test_log_reset_gated_on_timer_started(self):
        """``resetMotionSequenceLog()`` must only fire when ``timerStarted`` is
        true (a new mode is starting), so existing entries keep their times
        across stop and across non-transition polls.
        """
        self.assertIn(
            "if (timerStarted) resetMotionSequenceLog();",
            self.update_timer_body,
            "log reset must be gated on timerStarted",
        )
        # And the stop branch must not call resetMotionSequenceLog directly.
        stop_branch_match = re.search(
            r"if \(!normalizedMode\)\s*\{(?P<body>.*?)\}",
            self.update_timer_body,
            flags=re.DOTALL,
        )
        self.assertNotIn(
            "resetMotionSequenceLog",
            stop_branch_match.group("body"),
            "stop branch must not reset the sequence log; reset only on new mode start",
        )

    def test_timer_started_detects_transition_from_no_mode(self):
        """``timerStarted`` must trigger when transitioning from no mode to a
        mode. This is what makes 'start a new mode after stop' reset the log
        and timer to 00:00. Without this, the frozen-elapsed fix above would
        leak the prior session's elapsed time into the new mode.
        """
        self.assertRegex(
            self.update_timer_body,
            r"normalizedMode\s*!==\s*previousMode",
            "timerStarted must detect mode-name transitions (covers '' -> mode)",
        )
        self.assertIn(
            "Boolean(normalizedMode)",
            self.update_timer_body,
            "timerStarted must require an active mode name",
        )

    def test_sequence_log_time_reads_active_mode_elapsed(self):
        """The per-entry timecode source remains
        ``state.activeModeElapsedSeconds``. Combined with the frozen-on-stop
        contract, this means each appended entry's timecode is the true
        elapsed-at-record time, not 00:00.
        """
        self.assertIn(
            "state.activeModeElapsedSeconds",
            self.sequence_log,
            "sequence-log timecode source must read state.activeModeElapsedSeconds",
        )
        self.assertRegex(
            self.sequence_log,
            r"function\s+motionSequenceLogTime\s*\(\s*\)\s*\{[^}]*activeModeElapsedSeconds",
            "motionSequenceLogTime must derive its time from activeModeElapsedSeconds",
        )


if __name__ == "__main__":
    unittest.main()

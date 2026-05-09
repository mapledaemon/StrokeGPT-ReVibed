"""Backlog #13 frontend test runner integration.

Drives Node's stdlib ``node:test`` runner against the ``.test.mjs`` files
under ``tests/js/``, with ``tests/js/_harness.mjs`` preloaded via
``--import`` so the production browser modules can evaluate without a
real browser DOM. Skips cleanly when Node 20+ is not on PATH so the
existing ``python -m unittest discover -s tests`` workflow stays portable
for developers who only have Python installed.

Why this shape:

- Zero new repo dependencies. No ``package.json``, no ``node_modules``,
  no extra ``requirements.txt`` entry. Tests rely on Node's built-in
  ``node:test`` and ``node:assert``, which are stable since Node 20.
- Single suite preserved. ``python -m unittest discover -s tests`` is
  still the canonical entry point per ``AGENTS.md``; the Node tests run
  through this Python wrapper as part of the same invocation.
- Skip-if-missing matches the existing Flask-gated test pattern in
  ``tests/_web_support.py`` so the suite stays green on lean dev
  environments.
- CI exercises the full suite because ``.github/workflows/tests.yml``
  installs Node alongside Python.

When extending: add new ``*.test.mjs`` files under ``tests/js/``. They
will be picked up automatically by ``node --test``. Helpers that should
NOT be discovered as tests must use a leading underscore in the
filename (e.g. ``_harness.mjs``).
"""

import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JS_TEST_DIR = PROJECT_ROOT / "tests" / "js"
HARNESS_PATH = JS_TEST_DIR / "_harness.mjs"
MIN_NODE_MAJOR = 20


def _detect_node():
    """Return ``(ok, skip_reason)`` for the current Node toolchain."""
    if shutil.which("node") is None:
        return False, "Node.js not on PATH; behavioral frontend tests skipped"
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"node --version failed: {exc}"
    if result.returncode != 0:
        return False, f"node --version exited {result.returncode}"
    raw = result.stdout.strip().lstrip("v")
    try:
        major = int(raw.split(".")[0])
    except (ValueError, IndexError):
        return False, f"could not parse Node version {raw!r}"
    if major < MIN_NODE_MAJOR:
        return False, (
            f"Node {raw} is below the required {MIN_NODE_MAJOR}.x for the "
            f"stdlib node:test runner; behavioral frontend tests skipped"
        )
    return True, None


_NODE_OK, _NODE_SKIP_REASON = _detect_node()


@unittest.skipUnless(
    _NODE_OK,
    _NODE_SKIP_REASON or f"Node {MIN_NODE_MAJOR}+ unavailable",
)
class FrontendRuntimeTests(unittest.TestCase):
    """Run the Node ``node:test`` JS behavior suite as a single subtest.

    The Node runner reports per-test results in TAP/JUnit on stdout. We
    surface those on failure so the diagnostic line is right there in
    the unittest output without forcing the developer to re-run Node by
    hand.
    """

    def test_node_behavioral_suite_passes(self):
        # ``--import`` accepts a relative path or a file:// URL; the
        # POSIX path form is portable across Linux and Windows Node
        # builds. ``--test <dir>`` discovers ``*.test.{js,cjs,mjs}`` per
        # Node's default pattern; ``_harness.mjs`` is excluded by the
        # leading underscore.
        cmd = [
            "node",
            "--import",
            HARNESS_PATH.as_posix(),
            "--test",
            str(JS_TEST_DIR),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            self.fail(
                "node --test failed (exit code "
                f"{result.returncode})\n--- cmd ---\n{' '.join(cmd)}\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}"
            )


if __name__ == "__main__":
    unittest.main()

"""Shared fixtures for the Flask-gated web test files.

The leading underscore keeps :mod:`unittest` discovery from picking this
module up as a test file. Test modules under ``tests/`` import the symbols
they need from here so the per-file boilerplate stays small while every
``WebTestCase`` subclass keeps the same skip behavior, Flask app
attachment, and frontend-script aggregation helper that previously lived
on the monolithic :class:`WebStaticAssetTests`.
"""

import importlib.util
import mimetypes
import unittest


REQUIRED_MODULES = ("flask", "requests", "elevenlabs")

# Keep JavaScript response assertions stable across Windows MIME registry
# defaults and Werkzeug/Python mimetype table differences.
mimetypes.add_type("text/javascript", ".js")


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


MISSING_MODULES = [name for name in REQUIRED_MODULES if not module_available(name)]
WEB_DEPENDENCY_SKIP_REASON = f"missing app dependencies: {', '.join(MISSING_MODULES)}"


FRONTEND_SCRIPT_PATHS = (
    "/static/app.js",
    "/static/js/context.js",
    "/static/js/settings.js",
    "/static/js/chat.js",
    "/static/js/audio.js",
    "/static/js/device-control.js",
    "/static/js/motion-control.js",
    "/static/js/motion/feedback-controls.js",
    "/static/js/motion/pause-controls.js",
    "/static/js/motion/pattern-list.js",
    "/static/js/motion/sequence-log.js",
    "/static/js/motion/training-editor.js",
    "/static/js/setup.js",
)


@unittest.skipIf(MISSING_MODULES, WEB_DEPENDENCY_SKIP_REASON)
class WebTestCase(unittest.TestCase):
    """Base case that boots the Flask test client once per class.

    Mirrors the previous ``WebStaticAssetTests.setUpClass`` so every
    seam-specific subclass keeps the same fixture without repeating the
    import or the test-client wiring.
    """

    @classmethod
    def setUpClass(cls):
        from strokegpt.web import app

        cls.app = app
        cls.client = app.test_client()

    def frontend_scripts(self):
        scripts = []
        for path in FRONTEND_SCRIPT_PATHS:
            response = self.client.get(path)
            try:
                self.assertEqual(response.status_code, 200, path)
                scripts.append(response.get_data(as_text=True))
            finally:
                response.close()
        return "\n".join(scripts)

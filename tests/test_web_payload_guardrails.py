import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_PATH = PROJECT_ROOT / "strokegpt" / "web.py"

ALLOWED_PAYLOAD_BINDING_FUNCTIONS = {
    "_append_motion_feedback_history",
    "_diagnostics_level_options",
    "_format_bytes",
    "_motion_pattern_catalog_payload",
    "_motion_pattern_summary",
    "_motion_preference_payload",
    "_ollama_status_payload",
    "get_ollama_models_for_ui",
    "get_persona_prompts_for_ui",
    "settings_payload",
}


def _function_references_payloads(function_node):
    for node in ast.walk(function_node):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "payloads"
        ):
            return True
    return False


class WebPayloadGuardrailTests(unittest.TestCase):
    def test_web_payload_bindings_stay_explicitly_allowlisted(self):
        tree = ast.parse(WEB_PATH.read_text(encoding="utf-8"), filename=str(WEB_PATH))
        payload_functions = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and _function_references_payloads(node)
        }

        self.assertEqual(payload_functions, ALLOWED_PAYLOAD_BINDING_FUNCTIONS)


if __name__ == "__main__":
    unittest.main()

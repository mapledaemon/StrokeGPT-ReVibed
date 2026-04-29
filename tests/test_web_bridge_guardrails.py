import ast
import unittest
from pathlib import Path

from strokegpt.app_state import APP_STATE_EXPORTS


TESTS_DIR = Path(__file__).resolve().parent
ALLOWED_BRIDGE_TESTS = {
    "test_web_runtime_state.py",
}


def _target_parts(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return _target_parts(node.value) + [node.attr]
    return []


def _targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        for child in node.elts:
            yield from _targets(child)
    else:
        yield node


def _is_web_module_target(parts):
    return parts == ["web"] or parts == ["self", "web"]


def _bridge_assignment_name(target):
    parts = _target_parts(target)
    if len(parts) >= 2 and _is_web_module_target(parts[:-1]):
        export_name = parts[-1]
        if export_name in APP_STATE_EXPORTS:
            return export_name
    return ""


class _BridgeAssignmentVisitor(ast.NodeVisitor):
    def __init__(self):
        self.violations = []

    def visit_Assign(self, node):
        for target in node.targets:
            for nested_target in _targets(target):
                self._record_bridge_target(nested_target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._record_bridge_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._record_bridge_target(node.target)
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in APP_STATE_EXPORTS
            and _is_web_module_target(_target_parts(node.args[0]))
        ):
            self.violations.append((node.lineno, node.args[1].value))
        self.generic_visit(node)

    def _record_bridge_target(self, target):
        export_name = _bridge_assignment_name(target)
        if export_name:
            self.violations.append((target.lineno, export_name))


class WebBridgeGuardrailTests(unittest.TestCase):
    def test_routine_tests_do_not_write_through_web_runtime_state_bridge(self):
        violations = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            if path.name in ALLOWED_BRIDGE_TESTS or path.name == Path(__file__).name:
                continue
            visitor = _BridgeAssignmentVisitor()
            visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            for line_number, export_name in visitor.violations:
                violations.append(f"{path.name}:{line_number} writes web.{export_name}")

        self.assertEqual(
            violations,
            [],
            "Routine tests should use web.app_state.<name>; direct web.<name> writes belong "
            "only in the dedicated compatibility bridge tests.",
        )


if __name__ == "__main__":
    unittest.main()

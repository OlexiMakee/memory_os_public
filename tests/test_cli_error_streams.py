import ast
from pathlib import Path


def _literal_prefix(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return ""


def test_error_prints_are_routed_to_stderr():
    cli_path = Path(__file__).parents[1] / "src" / "memory_os" / "cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"))
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "print" or not node.args:
            continue
        if not _literal_prefix(node.args[0]).startswith("Error"):
            continue
        if not any(keyword.arg == "file" for keyword in node.keywords):
            violations.append(node.lineno)

    assert violations == []

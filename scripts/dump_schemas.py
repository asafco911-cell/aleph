"""Print every Pydantic model definition found in experiments/, using AST.

Regex cannot reliably find class bodies. AST gives exact source segments.
"""
import ast
from pathlib import Path

for path in sorted(Path("experiments").rglob("*.py")):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        continue

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        if "BaseModel" not in bases:
            continue
        print(f"\n{'=' * 70}")
        print(f"# {path.as_posix()}  line {node.lineno}")
        print("=" * 70)
        print(ast.get_source_segment(source, node))
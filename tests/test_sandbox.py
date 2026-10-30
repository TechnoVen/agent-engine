import ast

from tools.dev_dashboard import auto_repair_naked_return, extract_code_block


def test_extract_code_block_markdown_fences():
    raw = """Here is the solution:
```python
def optimize_data(data):
    return sorted(list(set(data)))

data = [3, 1, 2]
print(optimize_data(data))
```
Hope this helps!"""

    clean = extract_code_block(raw)
    assert "Here is the solution" not in clean
    assert "Hope this helps" not in clean
    assert "```" not in clean
    assert "def optimize_data(data):" in clean
    # Verify AST can parse it
    ast.parse(clean)


def test_extract_code_block_residual_backticks():
    raw = """def hello():
    return 'world'
```"""
    clean = extract_code_block(raw)
    assert "```" not in clean
    assert clean == "def hello():\n    return 'world'"
    ast.parse(clean)


def test_auto_repair_naked_return():
    broken_code = """return optimized_data

# Example usage
data = [1, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8, 9, 9]
optimized_data = optimize_data(data)
print(optimized_data)"""

    repaired = auto_repair_naked_return(broken_code)
    assert "def optimize_data(data):" in repaired
    assert "return optimized_data" in repaired
    # Verify it parses cleanly with ast
    parsed = ast.parse(repaired)
    assert isinstance(parsed, ast.Module)


def test_sandboxed_execution_repaired_code():
    broken_code = """return sorted(list(set(data)))

# Example usage
data = [5, 2, 2, 1]
optimized_data = optimize_data(data)
print(optimized_data)"""

    repaired = auto_repair_naked_return(broken_code)
    clean = extract_code_block(repaired)

    import tempfile
    from pathlib import Path

    from core.sandbox import SandboxService

    svc = SandboxService()
    if svc.is_available():
        with tempfile.TemporaryDirectory() as td:
            res = svc.run_code(clean, workspace_dir=Path(td))
            assert "[1, 2, 5]" in res.stdout
            assert res.exit_code == 0

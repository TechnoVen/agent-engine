import ast
import builtins
import contextlib
import io

from server.dashboard import auto_repair_naked_return, extract_code_block


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

    safe_builtins = {
        name: getattr(builtins, name)
        for name in [
            "abs",
            "all",
            "any",
            "ascii",
            "bin",
            "bool",
            "bytearray",
            "bytes",
            "chr",
            "complex",
            "dict",
            "divmod",
            "enumerate",
            "filter",
            "float",
            "format",
            "frozenset",
            "getattr",
            "hasattr",
            "hash",
            "hex",
            "int",
            "isinstance",
            "issubclass",
            "iter",
            "len",
            "list",
            "map",
            "max",
            "min",
            "next",
            "oct",
            "ord",
            "pow",
            "print",
            "range",
            "repr",
            "reversed",
            "round",
            "set",
            "slice",
            "sorted",
            "str",
            "sum",
            "tuple",
            "type",
            "zip",
            "open",
            "Exception",
            "ValueError",
            "TypeError",
            "RuntimeError",
            "KeyError",
            "IndexError",
            "AttributeError",
            "ImportError",
            "ZeroDivisionError",
            "OverflowError",
            "StopIteration",
            "AssertionError",
            "SyntaxError",
            "NameError",
        ]
        if hasattr(builtins, name)
    }
    safe_builtins["__import__"] = __import__

    safe_globals = {
        "__builtins__": safe_builtins,
        "__name__": "__sandbox__",
        "__doc__": None,
    }

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exec(clean, safe_globals)

    assert "[1, 2, 5]" in out.getvalue()
    assert err.getvalue() == ""

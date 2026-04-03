# memory-neo/memory_neo/core/extractor.py
# Path: memory_neo/core/extractor.py
# Purpose: AST-based Python function extractor — pulls name, lines, docstring, code
# Called by: memory_neo/core/scanner.py for .py files only

import ast


def extract_functions(source_code: str) -> list[dict]:
    """
    Parse Python source with AST and extract all function definitions.

    Returns:
    [
      {
        "name": "parse_directory",
        "start_line": 30,
        "end_line": 72,
        "docstring": "Walk a directory...",   ← first string literal if present
        "args": ["directory_path", "ignore_file"],
        "code": "def parse_directory(...):\n    ..."
      }
    ]
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    lines = source_code.splitlines()
    functions = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Extract docstring
        docstring = None
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            docstring = node.body[0].value.value.strip()

        # Extract argument names
        args = [arg.arg for arg in node.args.args]

        # Slice source lines for this function
        start = node.lineno - 1
        end = node.end_lineno
        code = "\n".join(lines[start:end])

        functions.append({
            "name": node.name,
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "docstring": docstring,
            "args": args,
            "code": code,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        })

    return functions

# memory-neo/memory_neo/core/extractor_js.py
# Path: memory_neo/core/extractor_js.py
# Purpose: AST-based function extractor for JS, TS, JSX, TSX using tree-sitter
# Called by: memory_neo/core/scanner.py for .js/.jsx/.ts/.tsx files

from __future__ import annotations

try:
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as _tsjs
    import tree_sitter_typescript as _tsts

    _JS_LANG  = Language(_tsjs.language())
    _TS_LANG  = Language(_tsts.language_typescript())
    _TSX_LANG = Language(_tsts.language_tsx())
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# Node types that represent function-like constructs
_FUNC_TYPES = {
    "function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
    "generator_function_declaration",
    "generator_function",
}

# Node types to skip traversal into (avoid double-counting nested functions)
_SKIP_BODY = {
    "statement_block",
    "class_body",
}


def _get_language(extension: str):
    """Return the correct tree-sitter Language for the given file extension."""
    if extension in (".ts",):
        return _TS_LANG
    if extension in (".tsx",):
        return _TSX_LANG
    return _JS_LANG   # .js, .jsx


def _find_name_for_expr(node) -> str | None:
    """
    For arrow_function / function_expression:
    Look at the parent variable_declarator to get the assigned variable name.
    e.g.  const greet = (name) => `Hello ${name}`;
          export const fetchUser = async (id) => { ... };
    Also handles named function_expression: const add = function myAdd() {}
    """
    # Named function expression: function foo() {}
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode(errors="replace")

    # Arrow / anonymous expression assigned to a variable
    parent = node.parent
    if parent and parent.type == "variable_declarator":
        n = parent.child_by_field_name("name")
        if n:
            return n.text.decode(errors="replace")

    # export const foo = () => {}  →  parent chain: export → lexical_decl → var_declarator
    if parent and parent.type in ("lexical_declaration", "variable_declaration"):
        for child in parent.named_children:
            if child.type == "variable_declarator":
                n = child.child_by_field_name("name")
                if n:
                    return n.text.decode(errors="replace")

    return None


def _extract_params(node) -> list[str]:
    """Extract parameter names from a function node."""
    params_node = (
        node.child_by_field_name("parameters")
        or node.child_by_field_name("parameter")
    )
    if not params_node:
        return []

    result = []
    for child in params_node.named_children:
        if child.type == "identifier":
            result.append(child.text.decode(errors="replace"))
        elif child.type in (
            "required_parameter",
            "optional_parameter",
            "assignment_pattern",
            "rest_element",
            "rest_pattern",
        ):
            # First named child is usually the identifier
            if child.named_children:
                first = child.named_children[0]
                if first.type == "identifier":
                    result.append(first.text.decode(errors="replace"))
        elif child.type == "shorthand_property_identifier_pattern":
            result.append(child.text.decode(errors="replace"))
    return result


def _is_async(node) -> bool:
    return any(c.type == "async" for c in node.children)


def _walk(node, lines: list[str], results: list[dict], depth: int = 0) -> None:
    """
    Recursively walk the tree and extract function nodes.
    depth is used to avoid extracting deeply nested anonymous functions
    that have no meaningful name (e.g. callbacks inside forEach).
    """
    if node.type not in _FUNC_TYPES:
        for child in node.children:
            _walk(child, lines, results, depth)
        return

    # ── Extract name ──────────────────────────────────────────────────────────
    if node.type == "function_declaration" or node.type == "generator_function_declaration":
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode(errors="replace") if name_node else None
    elif node.type == "method_definition":
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode(errors="replace") if name_node else None
    else:
        name = _find_name_for_expr(node)

    # Skip anonymous callbacks with no meaningful name at depth > 1
    if not name and depth > 0:
        for child in node.children:
            _walk(child, lines, results, depth + 1)
        return

    # ── Extract metadata ──────────────────────────────────────────────────────
    start_line = node.start_point[0] + 1   # 1-indexed
    end_line   = node.end_point[0]   + 1

    args     = _extract_params(node)
    is_async = _is_async(node)
    code     = "\n".join(lines[start_line - 1 : end_line])

    results.append({
        "name":       name or "<anonymous>",
        "start_line": start_line,
        "end_line":   end_line,
        "docstring":  None,       # JSDoc extraction is a future enhancement
        "args":       args,
        "code":       code,
        "is_async":   is_async,
    })

    # Recurse into body for nested named functions (e.g. class methods)
    for child in node.children:
        _walk(child, lines, results, depth + 1)


def extract_js_functions(source_code: str, extension: str = ".js") -> list[dict]:
    """
    Parse a JS/TS/JSX/TSX source file with tree-sitter and extract functions.

    Returns same shape as Python extractor:
    [
      {
        "name": "fetchUser",
        "start_line": 7,
        "end_line": 9,
        "docstring": None,
        "args": ["id"],
        "code": "export async function fetchUser...",
        "is_async": True,
      },
      ...
    ]

    Falls back to empty list if tree-sitter is not installed.
    """
    if not _AVAILABLE:
        return []

    lang = _get_language(extension)
    parser = Parser(lang)

    source_bytes = source_code.encode(errors="replace")
    tree = parser.parse(source_bytes)

    lines = source_code.splitlines()
    results: list[dict] = []

    _walk(tree.root_node, lines, results, depth=0)

    # De-duplicate by (name, start_line) — tree-sitter can visit some nodes twice
    seen: set[tuple] = set()
    unique: list[dict] = []
    for fn in results:
        key = (fn["name"], fn["start_line"])
        if key not in seen:
            seen.add(key)
            unique.append(fn)

    return unique
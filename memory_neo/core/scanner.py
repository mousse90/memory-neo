# memory-neo/memory_neo/core/scanner.py
# Path: memory_neo/core/scanner.py
# Purpose: Directory walker — ignore patterns, file filtering, AST extraction
# Supports: Python (ast), JS/TS/JSX/TSX (tree-sitter)
# Called by: memory_neo/cli/push.py

import os
from memory_neo.core.ignore import load_ignore_patterns, is_ignored
from memory_neo.core.extractor import extract_functions as extract_py_functions
from memory_neo.core.extractor_js import extract_js_functions

ALLOWED_EXTENSIONS = {
    ".py",
    ".js", ".jsx",
    ".ts", ".tsx",
    ".html", ".md", ".txt",
}

# Extensions that support function extraction
_PY_EXTS = {".py"}
_JS_EXTS = {".js", ".jsx", ".ts", ".tsx"}


def scan_directory(directory: str, ignore_file: str = "memIgnore") -> list[dict]:
    """
    Walk a directory, filter by allowed extensions and ignore patterns,
    extract function metadata from Python/JS/TS files.

    Returns a list of file dicts:
    [
      {
        "file_name":  "main.py",
        "file_path":  "memory_neo/main.py",   ← relative from scanned root
        "extension":  ".py",
        "lines":      42,
        "content":    "...",
        "functions": [
          {
            "name":       "main",
            "start_line": 10,
            "end_line":   28,
            "docstring":  "...",
            "args":       ["argv"],
            "code":       "def main(argv):...",
            "is_async":   False,
          }
        ]
      },
      ...
    ]
    """
    ignore_patterns = load_ignore_patterns(ignore_file)
    results: list[dict] = []

    for root, dirs, files in os.walk(directory, topdown=True):
        # Prune ignored directories
        dirs[:] = [
            d for d in dirs
            if not is_ignored(
                os.path.relpath(os.path.join(root, d), start=directory) + "/",
                ignore_patterns,
            )
        ]

        for file in files:
            full_path = os.path.join(root, file)
            rel_path  = os.path.normpath(os.path.relpath(full_path, start=directory))
            _, ext    = os.path.splitext(file)

            if is_ignored(rel_path, ignore_patterns):
                continue
            if ext not in ALLOWED_EXTENSIONS:
                continue

            file_data: dict = {
                "file_name": file,
                "file_path": rel_path,
                "extension": ext,
                "lines":     0,
                "content":   None,
                "functions": [],
            }

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                file_data["content"] = content
                file_data["lines"]   = content.count("\n") + 1

                if ext in _PY_EXTS:
                    file_data["functions"] = extract_py_functions(content)
                elif ext in _JS_EXTS:
                    file_data["functions"] = extract_js_functions(content, ext)
                # .html / .md / .txt → no function extraction

            except Exception as e:
                file_data["content"] = f"# Error reading file: {e}"

            results.append(file_data)

    return results

# # memory-neo/memory_neo/core/scanner.py
# # Path: memory_neo/core/scanner.py
# # Purpose: Main directory walker — orchestrates ignore loading, file filtering, extraction
# # Called by: memory_neo/cli/push.py

# import os
# from memory_neo.core.ignore import load_ignore_patterns, is_ignored
# from memory_neo.core.extractor import extract_functions

# ALLOWED_EXTENSIONS = {
#     ".py", ".js", ".jsx", ".ts", ".tsx",
#     ".html", ".md", ".txt",
# }


# def scan_directory(directory: str, ignore_file: str = "memIgnore") -> list[dict]:
#     """
#     Walk a directory, filter by allowed extensions and ignore patterns,
#     extract function metadata from Python files via AST.

#     Returns a list of file dicts:
#     [
#       {
#         "file_name": "main.py",
#         "file_path": "memory_neo/main.py",   ← relative path from scanned root
#         "extension": ".py",
#         "lines": 42,
#         "content": "...",
#         "functions": [
#           {
#             "name": "main",
#             "start_line": 10,
#             "end_line": 28,
#             "code": "def main():..."
#           }
#         ]
#       },
#       ...
#     ]
#     """
#     ignore_patterns = load_ignore_patterns(ignore_file)
#     results = []

#     for root, dirs, files in os.walk(directory, topdown=True):
#         # Prune ignored directories in-place to avoid descending into them
#         dirs[:] = [
#             d for d in dirs
#             if not is_ignored(
#                 os.path.relpath(os.path.join(root, d), start=directory) + "/",
#                 ignore_patterns,
#             )
#         ]

#         for file in files:
#             full_path = os.path.join(root, file)
#             rel_path = os.path.normpath(os.path.relpath(full_path, start=directory))
#             _, ext = os.path.splitext(file)

#             if is_ignored(rel_path, ignore_patterns):
#                 continue
#             if ext not in ALLOWED_EXTENSIONS:
#                 continue

#             file_data = {
#                 "file_name": file,
#                 "file_path": rel_path,
#                 "extension": ext,
#                 "lines": 0,
#                 "content": None,
#                 "functions": [],
#             }

#             try:
#                 with open(full_path, "r", encoding="utf-8", errors="replace") as f:
#                     content = f.read()
#                 file_data["content"] = content
#                 file_data["lines"] = content.count("\n") + 1

#                 if ext == ".py":
#                     file_data["functions"] = extract_functions(content)

#             except Exception as e:
#                 file_data["content"] = f"# Error reading file: {e}"

#             results.append(file_data)

#     return results

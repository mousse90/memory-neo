# memory-neo/memory_neo/core/ignore.py
# Path: memory_neo/core/ignore.py
# Purpose: Load and evaluate memIgnore patterns (gitignore-style)
# Called by: memory_neo/core/scanner.py

import os
import fnmatch


def load_ignore_patterns(ignore_file: str) -> list[str]:
    """
    Load ignore patterns from a memIgnore file.
    Lines starting with # are comments and are skipped.
    Returns empty list if file not found.
    """
    if not os.path.exists(ignore_file):
        return []

    with open(ignore_file, "r") as f:
        patterns = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]
    return patterns


def is_ignored(path: str, patterns: list[str]) -> bool:
    """
    Check if a relative file or directory path matches any ignore pattern.

    Pattern types:
    - "folder/"       → matches any path segment named "folder"
    - "*.pyc"         → wildcard match on filename
    - ".env"          → exact filename match
    - "some/path"     → exact relative path match
    """
    for pattern in patterns:
        if pattern.endswith("/"):
            # Folder match — check if pattern folder name appears anywhere in path
            folder_name = pattern.rstrip("/")
            parts = path.replace("\\", "/").split("/")
            if folder_name in parts:
                return True
        elif "*" in pattern:
            # Wildcard — match against filename only
            if fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        else:
            # Exact: match against full relative path OR just filename
            if path == pattern or os.path.basename(path) == pattern:
                return True

    return False

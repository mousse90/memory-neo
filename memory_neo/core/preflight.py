# memory-neo/memory_neo/core/preflight.py
# Path: memory_neo/core/preflight.py
# Purpose: Pre-scan analysis — detect suspicious dirs, missing memIgnore, warn user
# Called by: memory_neo/cli/push.py before scan_directory

import os
import click
from rich.console import Console
from rich.table import Table

console = Console()

# Dossiers qui ne devraient presque jamais être indexés
SUSPECT_DIRS = {
    "node_modules":   "JS dependencies (~thousands of files)",
    "__pycache__":    "Python bytecode cache",
    ".git":           "Git history",
    ".next":          "Next.js build cache",
    "dist":           "Build output",
    "build":          "Build output",
    "out":            "Build output",
    "venv":           "Python virtual environment",
    ".venv":          "Python virtual environment",
    "env":            "Python virtual environment",
    ".env":           "Python virtual environment",
    "coverage":       "Test coverage reports",
    ".nyc_output":    "NYC coverage output",
    "storybook-static": "Storybook build",
    ".storybook":     "Storybook config (rarely useful)",
    "cypress":        "E2E test artifacts",
    ".pytest_cache":  "Pytest cache",
    "htmlcov":        "HTML coverage report",
    ".mypy_cache":    "Mypy cache",
    ".ruff_cache":    "Ruff cache",
    ".VSCodeCounter": "VSCode extension output",
    ".vscode":        "VSCode config (rarely useful)",
    ".idea":          "JetBrains IDE config",
    "vendor":         "Vendored dependencies",
    "Pods":           "iOS CocoaPods dependencies",
    ".gradle":        "Gradle build cache",
    "target":         "Rust/Java build output",
}

# Patterns par défaut selon le type de projet détecté
_PYTHON_IGNORE = """\
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
dist/
build/
*.egg-info/
venv/
.venv/
env/
.git/
.DS_Store
"""

_JS_IGNORE = """\
# JavaScript / TypeScript
node_modules/
.next/
dist/
build/
out/
coverage/
.nyc_output/
storybook-static/
.git/
.DS_Store
*.min.js
*.map
"""

_GENERIC_IGNORE = """\
# Generic
.git/
.DS_Store
dist/
build/
"""


def _detect_project_type(directory: str) -> str:
    files = os.listdir(directory)
    if "package.json" in files:
        return "js"
    if any(f.endswith(".py") for f in files) or "pyproject.toml" in files or "setup.py" in files:
        return "python"
    return "generic"


def _generate_memignore(directory: str) -> str:
    kind = _detect_project_type(directory)
    if kind == "js":
        return _JS_IGNORE
    if kind == "python":
        return _PYTHON_IGNORE
    return _GENERIC_IGNORE


def _scan_top_dirs(directory: str) -> list[str]:
    """Return top-level directory names."""
    try:
        return [
            d for d in os.listdir(directory)
            if os.path.isdir(os.path.join(directory, d))
        ]
    except Exception:
        return []


def run_preflight(directory: str, ignore_file: str) -> bool:
    """
    Analyse the directory before scanning.
    Returns True if OK to proceed, False if user aborted.

    Steps:
    1. Check memIgnore exists — offer to create if missing
    2. Detect suspect directories not covered by ignore patterns
    3. Show summary and ask confirmation if issues found
    """
    from memory_neo.core.ignore import load_ignore_patterns, is_ignored
    from memory_neo.utils.display import warn, info, success, error

    issues_found = False

    # ── 1. memIgnore missing ──────────────────────────────────────────────────
    if not os.path.exists(ignore_file):
        warn(f"No [bold]memIgnore[/bold] file found in [dim]{directory}[/dim]")
        console.print()

        if click.confirm("  → Create a memIgnore automatically?", default=True):
            content = _generate_memignore(directory)
            with open(ignore_file, "w") as f:
                f.write(content)
            success(f"Created [bold]{ignore_file}[/bold]")
            console.print(f"  [dim]{content.strip()}[/dim]")
            console.print()
        else:
            warn("Proceeding without memIgnore — this may index unwanted files.")
            issues_found = True

    # ── 2. Detect suspect dirs not excluded ───────────────────────────────────
    patterns = load_ignore_patterns(ignore_file)
    top_dirs = _scan_top_dirs(directory)

    unexcluded_suspects = []
    for d in top_dirs:
        rel = d + "/"
        if d in SUSPECT_DIRS and not is_ignored(rel, patterns):
            unexcluded_suspects.append((d, SUSPECT_DIRS[d]))

    if unexcluded_suspects:
        console.print()
        warn("Detected directories that are usually excluded:")
        console.print()

        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
        table.add_column("Directory", style="yellow")
        table.add_column("Why exclude?", style="dim")
        for d, reason in unexcluded_suspects:
            table.add_row(d + "/", reason)
        console.print(table)
        console.print()

        if click.confirm("  → Add these to memIgnore?", default=True):
            with open(ignore_file, "a") as f:
                f.write("\n# Auto-added by memory-neo preflight\n")
                for d, _ in unexcluded_suspects:
                    f.write(f"{d}/\n")
            success(f"Added {len(unexcluded_suspects)} pattern(s) to memIgnore")
        else:
            warn("Keeping these directories — scan may be slow or noisy.")
        issues_found = True

    # ── 3. Quick file count estimate ──────────────────────────────────────────
    # Count files quickly (no content reading) to warn if huge
    from memory_neo.core.ignore import load_ignore_patterns as _lp, is_ignored as _ii
    patterns2 = _lp(ignore_file)
    count = 0
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [
            d for d in dirs
            if not _ii(
                os.path.relpath(os.path.join(root, d), start=directory) + "/",
                patterns2,
            )
        ]
        count += len(files)
        if count > 2000:
            break

    if count > 2000:
        console.print()
        warn(f"Large project detected (~{count}+ files).")
        warn("Consider narrowing your memIgnore to speed up the push.")
        if not click.confirm("  → Continue anyway?", default=True):
            error("Push aborted.")
            return False

    return True
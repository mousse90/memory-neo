# memory-neo/memory_neo/utils/display.py
# Path: memory_neo/utils/display.py
# Purpose: Rich terminal output helpers — consistent styling across all CLI commands
# Called by: all CLI commands

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

theme = Theme({
    "success": "bold green",
    "error": "bold red",
    "warn": "bold yellow",
    "info": "dim white",
    "accent": "bold cyan",
    "muted": "dim",
})

console = Console(theme=theme)


def panel(title: str, subtitle: str = "") -> None:
    t = Text(title, style="bold cyan")
    console.print(Panel(t, subtitle=subtitle, border_style="dim cyan", padding=(0, 2)))


def success(msg: str) -> None:
    console.print(f"  [success]✓[/success] {msg}")


def error(msg: str) -> None:
    console.print(f"  [error]✗[/error] {msg}")


def warn(msg: str) -> None:
    console.print(f"  [warn]![/warn] {msg}")


def info(msg: str) -> None:
    console.print(f"  [info]{msg}[/info]")


def print_results(results: list[dict]) -> None:
    """Generic tabular result printer for query output."""
    if not results:
        warn("No results found.")
        return
    for i, row in enumerate(results, 1):
        console.print(f"  [accent]{i}.[/accent]", end=" ")
        for k, v in row.items():
            console.print(f"[muted]{k}:[/muted] {v}", end="  ")
        console.print()

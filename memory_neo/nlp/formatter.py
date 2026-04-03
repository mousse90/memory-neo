# memory-neo/memory_neo/nlp/formatter.py
# Path: memory_neo/nlp/formatter.py
# Purpose: Format NLP query results for terminal display — code blocks, tables, context dump
# Called by: memory_neo/cli/query.py

import pyperclip
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.rule import Rule
from rich.text import Text

console = Console()


def format_query_results(
    question: str,
    cypher: str | None,
    results: list[dict],
    context_mode: bool = False,
) -> None:
    """
    Pretty-print query results to terminal.

    Handles 3 result shapes:
    - Function results  → syntax-highlighted code block
    - File results      → compact table with path + line count
    - Generic results   → key-value table
    """
    console.print()
    console.print(Rule(f"[dim]Results for:[/dim] [bold]{question}[/bold]", style="dim"))

    # Show generated Cypher (collapsed by default, shown in dim)
    if cypher:
        console.print(f"  [dim]↳ Cypher:[/dim] [dim cyan]{cypher}[/dim cyan]")
    console.print()

    if not results:
        console.print("  [yellow]No results.[/yellow] Try rephrasing or run [bold]memory-neo push[/bold] first.")
        return

    # Detect result shape
    first = results[0]

    if "code" in first:
        _render_function_results(results)
    elif "file_path" in first or "path" in first:
        _render_file_results(results)
    else:
        _render_generic_results(results)

    console.print()
    console.print(f"  [dim]{len(results)} result(s)[/dim]")

    # Context mode: dump all code to stdout as a prompt-ready block
    if context_mode and any("code" in r for r in results):
        console.print()
        console.print(Rule("[dim]Context block (paste into your LLM prompt)[/dim]", style="dim"))
        for r in results:
            if "code" in r:
                console.print(f"# {r.get('file', '')} — {r.get('name', '')}")
                console.print(r["code"])
                console.print()


def _render_function_results(results: list[dict]) -> None:
    for r in results:
        label = Text()
        label.append(f"  fn ", style="dim")
        label.append(r.get("name", "?"), style="bold cyan")
        if r.get("file"):
            label.append(f"  ← {r['file']}", style="dim")
        if r.get("start_line"):
            label.append(f"  L{r['start_line']}–{r.get('end_line', '?')}", style="dim")
        console.print(label)
        if r.get("code"):
            console.print(Syntax(r["code"], "python", theme="monokai", line_numbers=True, start_line=r.get("start_line", 1)))
        console.print()


def _render_file_results(results: list[dict]) -> None:
    table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    table.add_column("File", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Lines", justify="right", style="dim")
    table.add_column("Functions", justify="right", style="yellow")

    for r in results:
        table.add_row(
            r.get("name", r.get("file_name", "?")),
            r.get("path", r.get("file_path", "?")),
            str(r.get("lines", "?")),
            str(r.get("function_count", "?")),
        )
    console.print(table)


def _render_generic_results(results: list[dict]) -> None:
    table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    if results:
        for col in results[0].keys():
            table.add_column(col, style="cyan")
        for r in results:
            table.add_row(*[str(v) for v in r.values()])
    console.print(table)

# memory-neo/memory_neo/cli/context.py
# Path: memory_neo/cli/context.py
# Purpose: `memory-neo context <fn_or_file>` — fetch code from Memgraph, print prompt-ready
# Flow: user names a function or file → GET /context → returns raw code block

import click
import httpx

from memory_neo.utils.config import require_auth
from memory_neo.utils.display import error, info, panel
from rich.syntax import Syntax
from rich.console import Console

console = Console()


@click.command()
@click.argument("target")
@click.option("--project", "-p", default=None, help="Project name (default: current dir name)")
@click.option("--type", "-t", "target_type", default="auto",
              type=click.Choice(["auto", "function", "file"]),
              help="Whether target is a function or file (default: auto-detect)")
@click.option("--copy", "-c", is_flag=True, help="Copy result to clipboard")
def context(target, project, target_type, copy):
    """Fetch a function or file as prompt-ready context.

    \b
    Examples:
      memory-neo context parse_directory
      memory-neo context memory_neo/main.py
      memory-neo context login --type function
      memory-neo context --copy parse_directory
    """
    cfg = require_auth()

    if not project:
        import os
        project = os.path.basename(os.path.abspath("."))

    panel("memory-neo context", subtitle=f"Fetching: {target}")

    try:
        resp = httpx.get(
            f"{cfg['api_url']}/context/{target}",
            headers={"X-API-Key": cfg["api_key"]},
            params={
                "project_name": project,
                "user_id": cfg["user_id"],
                "target_type": target_type,
            },
            timeout=15,
        )

        if resp.status_code == 404:
            error(f"Not found: [bold]{target}[/bold] in project [bold]{project}[/bold]")
            info("Tip: run `memory-neo push` first to index your code.")
            raise SystemExit(1)

        if resp.status_code != 200:
            error(f"Context fetch failed (HTTP {resp.status_code}): {resp.text}")
            raise SystemExit(1)

        data = resp.json()
        code = data.get("code", "")
        source = data.get("source", target)
        lang = data.get("language", "python")

        info(f"  Source   : [dim]{source}[/dim]")
        info(f"  Type     : {data.get('type', '?')}")
        if data.get("start_line"):
            info(f"  Lines    : {data['start_line']}–{data['end_line']}")

        console.print()
        console.print(Syntax(code, lang, theme="monokai", line_numbers=True))

        if copy:
            try:
                import subprocess
                subprocess.run("pbcopy", input=code.encode(), check=True)
                info("Copied to clipboard.")
            except Exception:
                error("Could not copy — install pbcopy (macOS) or xclip (Linux).")

    except httpx.ConnectError:
        error(f"Could not reach {cfg['api_url']}.")
        raise SystemExit(1)

# memory-neo/memory_neo/cli/query.py
# Path: memory_neo/cli/query.py
# Purpose: `memory-neo query "..."` — NLP question → Claude → Cypher → Memgraph → results
# Flow: user types NL question → POST /query → backend calls Claude → runs Cypher → returns nodes

import click
import httpx
import json

from memory_neo.utils.config import require_auth
from memory_neo.utils.display import success, error, info, warn, panel, print_results
from memory_neo.nlp.formatter import format_query_results


@click.command()
@click.argument("question", required=False)
@click.option("--project", "-p", default=None, help="Project name to query (default: current dir name)")
@click.option("--raw", is_flag=True, help="Print raw JSON response")
@click.option("--context", "-c", is_flag=True, help="Auto-copy result as prompt context")
def query(question, project, raw, context):
    """Ask a natural language question about your codebase.

    \b
    Examples:
      memory-neo query "show all auth functions"
      memory-neo query "which files import neo4j"
      memory-neo query "list all classes in src/"
      memory-neo query  ← interactive mode
    """
    cfg = require_auth()

    if not question:
        panel("memory-neo query", subtitle="Interactive mode — type your question")
        question = click.prompt("  Ask")

    if not project:
        import os
        project = os.path.basename(os.path.abspath("."))
        info(f"Querying project: [bold]{project}[/bold]")

    info(f"  Question : [dim]{question}[/dim]")

    try:
        resp = httpx.post(
            f"{cfg['api_url']}/query",
            headers={"X-API-Key": cfg["api_key"]},
            json={
                "question": question,
                "project_name": project,
                "user_id": cfg["user_id"],
            },
            timeout=30,
        )

        if resp.status_code != 200:
            error(f"Query failed (HTTP {resp.status_code}): {resp.text}")
            raise SystemExit(1)

        data = resp.json()

        if raw:
            click.echo(json.dumps(data, indent=2))
            return

        # Pretty print results
        format_query_results(
            question=question,
            cypher=data.get("cypher"),
            results=data.get("results", []),
            context_mode=context,
        )

    except httpx.ConnectError:
        error(f"Could not reach {cfg['api_url']}.")
        raise SystemExit(1)

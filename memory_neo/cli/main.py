# memory-neo/memory_neo/cli/main.py
# Path: memory_neo/cli/main.py
# Purpose: CLI entrypoint — registers all commands under `memory-neo` binary
# Registered via pyproject.toml [project.scripts]: memory-neo = "memory_neo.cli.main:cli"


import click
from memory_neo import __version__
from memory_neo.cli.login import login
from memory_neo.cli.push import push
from memory_neo.cli.query import query
from memory_neo.cli.context import context


@click.group()
@click.version_option(__version__, prog_name="memory-neo")
def cli():
    """
    \b
    memory-neo — push your codebase to a graph, query it with language.

    \b
    Commands:
      login    Authenticate with your API key
      push     Scan current directory and push to Memgraph
      query    Ask a natural language question about your code
      context  Fetch a file or function as prompt-ready context
    """
    pass


cli.add_command(login)
cli.add_command(push)
cli.add_command(query)
cli.add_command(context)

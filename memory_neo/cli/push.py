# memory-neo/memory_neo/cli/push.py
# Path: memory_neo/cli/push.py
# Purpose: `memory-neo push` — smart scan with preflight agent, then POST /push

import os
import click
import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from memory_neo.core.scanner import scan_directory
from memory_neo.core.preflight import run_preflight
from memory_neo.utils.config import load_config, require_auth
from memory_neo.utils.display import success, error, info, warn, panel

# Warn if more functions than this — likely something was missed in memIgnore
FN_COUNT_WARNING = 500


@click.command()
@click.argument("project_name", required=False)
@click.option("--dir", "-d", "directory", default=".", help="Directory to scan (default: current)")
@click.option("--dry-run", is_flag=True, help="Scan only, do not push")
@click.option("--ignore", "-i", "ignore_file", default=None, help="Path to custom memIgnore file")
@click.option("--skip-preflight", is_flag=True, help="Skip the pre-scan checks")
def push(project_name, directory, dry_run, ignore_file, skip_preflight):
    """Scan current directory and push structure to Memgraph.

    \b
    Examples:
      memory-neo push
      memory-neo push my-project
      memory-neo push --dir ./src --dry-run
    """
    cfg = load_config() if dry_run else require_auth()

    # Resolve project name
    if not project_name:
        project_name = os.path.basename(os.path.abspath(directory))
        info(f"No project name given — using directory name: [bold]{project_name}[/bold]")

    panel("memory-neo push", subtitle=f"Scanning {os.path.abspath(directory)}")

    # Resolve ignore file
    if not ignore_file:
        local_ignore = os.path.join(directory, "memIgnore")
        pkg_ignore   = os.path.join(os.path.dirname(__file__), "..", "..", "memIgnore")
        ignore_file  = local_ignore if os.path.exists(local_ignore) else local_ignore
        # Use pkg default only if local doesn't exist AND we're not creating one
        _pkg_default = pkg_ignore

    # ── Preflight ─────────────────────────────────────────────────────────────
    if not skip_preflight:
        ok = run_preflight(directory=directory, ignore_file=ignore_file)
        if not ok:
            raise SystemExit(1)

    # ── Scan ──────────────────────────────────────────────────────────────────
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning files...", total=None)
        structure = scan_directory(directory, ignore_file=ignore_file)
        progress.update(task, description=f"Found {len(structure)} files")

    file_count = len(structure)
    fn_count   = sum(len(f.get("functions", [])) for f in structure)

    info(f"  Files     : [bold]{file_count}[/bold]")
    info(f"  Functions : [bold]{fn_count}[/bold]")

    # Warn if suspiciously high function count
    if fn_count > FN_COUNT_WARNING:
        warn(f"  [yellow]{fn_count} functions detected — this seems high.[/yellow]")
        warn("  Check your memIgnore — you may be indexing dependencies.")
        if not click.confirm("  → Continue anyway?", default=False):
            error("Push aborted.")
            raise SystemExit(1)

    if dry_run:
        warn("Dry run — not pushing.")
        return

    # ── Push ──────────────────────────────────────────────────────────────────
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        task = progress.add_task("Pushing to Memgraph...", total=file_count)

        try:
            resp = httpx.post(
                f"{cfg['api_url']}/push",
                headers={"X-API-Key": cfg["api_key"]},
                json={
                    "project_name": project_name,
                    "user_id":      cfg["user_id"],
                    "files":        structure,
                },
                timeout=120,  # increased from 60s for large projects
            )
            progress.update(task, completed=file_count)

            if resp.status_code == 200:
                data = resp.json()
                success("Push complete.")
                info(f"  Project  : [bold]{project_name}[/bold]")
                info(f"  Namespace: [dim]{cfg['user_id']}::{project_name}[/dim]")
                info(f"  Nodes    : {data.get('nodes_created', '?')} created, {data.get('nodes_merged', '?')} merged")
            else:
                error(f"Push failed (HTTP {resp.status_code}): {resp.text}")
                raise SystemExit(1)

        except httpx.WriteTimeout:
            error("Push timed out — project may be too large.")
            warn("Try narrowing your memIgnore and run again.")
            raise SystemExit(1)
        except httpx.ConnectError:
            error(f"Could not reach {cfg['api_url']}.")
            raise SystemExit(1)
        
# # memory-neo/memory_neo/cli/push.py
# # Path: memory_neo/cli/push.py
# # Purpose: `memory-neo push` — scans current directory, sends parsed structure to backend
# # Flow: scan dir → extract files/functions → POST /push → Memgraph stores graph

# import os
# import click
# import httpx
# from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

# from memory_neo.core.scanner import scan_directory
# from memory_neo.utils.config import load_config, require_auth
# from memory_neo.utils.display import success, error, info, warn, panel


# @click.command()
# @click.argument("project_name", required=False)
# @click.option("--dir", "-d", "directory", default=".", help="Directory to scan (default: current)")
# @click.option("--dry-run", is_flag=True, help="Scan only, do not push")
# @click.option("--ignore", "-i", "ignore_file", default=None, help="Path to custom memIgnore file")
# def push(project_name, directory, dry_run, ignore_file):
#     """Scan current directory and push structure to Memgraph.

#     \b
#     Examples:
#       memory-neo push
#       memory-neo push my-project
#       memory-neo push --dir ./src --dry-run
#     """
#     cfg = load_config() if dry_run else require_auth()

#     # Resolve project name
#     if not project_name:
#         project_name = os.path.basename(os.path.abspath(directory))
#         info(f"No project name given — using directory name: [bold]{project_name}[/bold]")

#     panel("memory-neo push", subtitle=f"Scanning {os.path.abspath(directory)}")

#     # Resolve ignore file: project root → package default
#     if not ignore_file:
#         local_ignore = os.path.join(directory, "memIgnore")
#         pkg_ignore = os.path.join(os.path.dirname(__file__), "..", "..", "memIgnore")
#         ignore_file = local_ignore if os.path.exists(local_ignore) else pkg_ignore

#     # Scan
#     with Progress(
#         SpinnerColumn(),
#         TextColumn("[progress.description]{task.description}"),
#         transient=True,
#     ) as progress:
#         task = progress.add_task("Scanning files...", total=None)
#         structure = scan_directory(directory, ignore_file=ignore_file)
#         progress.update(task, description=f"Found {len(structure)} files")

#     file_count = len(structure)
#     fn_count = sum(len(f.get("functions", [])) for f in structure)

#     info(f"  Files : [bold]{file_count}[/bold]")
#     info(f"  Functions: [bold]{fn_count}[/bold]")

#     if dry_run:
#         warn("Dry run — not pushing.")
#         return

#     # Push
#     with Progress(
#         SpinnerColumn(),
#         TextColumn("[progress.description]{task.description}"),
#         BarColumn(),
#         TaskProgressColumn(),
#     ) as progress:
#         task = progress.add_task("Pushing to Memgraph...", total=file_count)

#         try:
#             resp = httpx.post(
#                 f"{cfg['api_url']}/push",
#                 headers={"X-API-Key": cfg["api_key"]},
#                 json={
#                     "project_name": project_name,
#                     "user_id": cfg["user_id"],
#                     "files": structure,
#                 },
#                 timeout=60,
#             )
#             progress.update(task, completed=file_count)

#             if resp.status_code == 200:
#                 data = resp.json()
#                 success(f"Push complete.")
#                 info(f"  Project  : [bold]{project_name}[/bold]")
#                 info(f"  Namespace: [dim]{cfg['user_id']}::{project_name}[/dim]")
#                 info(f"  Nodes    : {data.get('nodes_created', '?')} created, {data.get('nodes_merged', '?')} merged")
#             else:
#                 error(f"Push failed (HTTP {resp.status_code}): {resp.text}")
#                 raise SystemExit(1)

#         except httpx.ConnectError:
#             error(f"Could not reach {cfg['api_url']}.")
#             raise SystemExit(1)

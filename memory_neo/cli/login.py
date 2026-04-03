# memory-neo/memory_neo/cli/login.py
# Path: memory_neo/cli/login.py
# Purpose: `memory-neo login` — stores API key in ~/.memoryneo/config.json
# Flow: user pastes API key → validated against backend → saved locally

import click
import httpx
from memory_neo.utils.config import save_config, load_config
from memory_neo.utils.display import success, error, info, panel


@click.command()
@click.option("--key", "-k", default=None, help="API key (skip interactive prompt)")
@click.option("--api-url", default=None, help="Override API base URL (for self-hosting)")
def login(key, api_url):
    """Authenticate with your memory-neo API key."""

    panel("memory-neo login", subtitle="Authenticate to push and query your repos")

    if not key:
        info("Get your API key at https://memory-neo.dev or run your own backend.")
        key = click.prompt("  Paste your API key", hide_input=True)

    base_url = api_url or "https://api.memory-neo.dev"

    info(f"Validating key against {base_url} ...")

    try:
        resp = httpx.post(
            f"{base_url}/auth/validate",
            headers={"X-API-Key": key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            save_config({
                "api_key": key,
                "api_url": base_url,
                "user_id": data.get("user_id"),
                "email": data.get("email"),
            })
            success(f"Logged in as {data.get('email', 'unknown')}.")
            success("Config saved to ~/.memoryneo/config.json")
        else:
            error(f"Invalid API key (HTTP {resp.status_code}).")
            raise SystemExit(1)
    except httpx.ConnectError:
        error(f"Could not reach {base_url}. Check your internet or --api-url.")
        raise SystemExit(1)

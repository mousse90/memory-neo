# memory-neo/memory_neo/utils/config.py
# Path: memory_neo/utils/config.py
# Purpose: Read/write ~/.memoryneo/config.json — API key, user_id, api_url
# Called by: all CLI commands that need auth

import os
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".memoryneo"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API_URL = "https://api.memory-neo.dev"
LOCAL_API_URL   = "http://localhost:8080"


def load_config() -> dict:
    """Load config from ~/.memoryneo/config.json. Returns empty dict if not found."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> None:
    """Write config to ~/.memoryneo/config.json, merging with existing values."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_config()
    existing.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(existing, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def require_auth() -> dict:
    """
    Load config and return auth dict.
    Dev mode: if no config found, auto-inject local defaults from .env — no login needed.
    Production: abort if not logged in.
    """
    from memory_neo.utils.display import error, info, warn

    cfg = load_config()

    if not cfg.get("api_key"):
        if os.getenv("ENVIRONMENT", "development") == "development":
            warn("No config found — using local dev defaults (ENVIRONMENT=development).")
            return {
                "api_key": os.getenv("DEV_API_KEY", "local-dev-key"),
                "api_url": LOCAL_API_URL,
                "user_id": os.getenv("DEV_USER_ID", "usr_local"),
                "email":   os.getenv("DEV_EMAIL", "dev@local.dev"),
            }
        error("Not authenticated. Run:")
        info("  memory-neo login")
        raise SystemExit(1)

    cfg.setdefault("api_url", DEFAULT_API_URL)
    return cfg


def clear_config() -> None:
    """Remove saved config (logout)."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        
        
# # memory-neo/memory_neo/utils/config.py
# # Path: memory_neo/utils/config.py
# # Purpose: Read/write ~/.memoryneo/config.json — API key, user_id, api_url
# # Called by: all CLI commands that need auth

# import os
# import json
# from pathlib import Path

# CONFIG_DIR = Path.home() / ".memoryneo"
# CONFIG_FILE = CONFIG_DIR / "config.json"

# DEFAULT_API_URL = "https://api.memory-neo.dev"


# def load_config() -> dict:
#     """Load config from ~/.memoryneo/config.json. Returns empty dict if not found."""
#     if not CONFIG_FILE.exists():
#         return {}
#     try:
#         with open(CONFIG_FILE, "r") as f:
#             return json.load(f)
#     except Exception:
#         return {}


# def save_config(data: dict) -> None:
#     """Write config to ~/.memoryneo/config.json, merging with existing values."""
#     CONFIG_DIR.mkdir(parents=True, exist_ok=True)
#     existing = load_config()
#     existing.update(data)
#     with open(CONFIG_FILE, "w") as f:
#         json.dump(existing, f, indent=2)
#     # Restrict permissions: owner read/write only
#     os.chmod(CONFIG_FILE, 0o600)


# def require_auth() -> dict:
#     """
#     Load config and abort with helpful message if not logged in.
#     Returns config dict with api_key, api_url, user_id guaranteed present.
#     """
#     from memory_neo.utils.display import error, info

#     cfg = load_config()

#     if not cfg.get("api_key"):
#         error("Not authenticated. Run:")
#         info("  memory-neo login")
#         raise SystemExit(1)

#     cfg.setdefault("api_url", DEFAULT_API_URL)
#     return cfg


# def clear_config() -> None:
#     """Remove saved config (logout)."""
#     if CONFIG_FILE.exists():
#         CONFIG_FILE.unlink()

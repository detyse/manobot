"""Auto-initialization for manobot.

Ensures that when manobot starts, the default configuration
is automatically registered as the default agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mano.core.scope import (
    DEFAULT_AGENT_ID,
    list_agent_ids,
    normalize_agent_id,
    resolve_default_agent_id,
)

if TYPE_CHECKING:
    from agent.config.schema import Config


def get_manobot_state_dir() -> Path:
    """Get the manobot state directory."""
    return Path.home() / ".manobot"


def _get_config_path() -> Path:
    """Get the config file path (delegates to agent.config.loader)."""
    from agent.config.loader import get_config_path
    return get_config_path()


def ensure_default_agent(config: Config) -> bool:
    """Ensure a default agent exists in the configuration.

    If no agents are configured, creates a default agent entry
    based on the existing defaults configuration.

    Args:
        config: Current application configuration

    Returns:
        True if a default agent was created or already exists
    """
    agent_ids = list_agent_ids(config)

    # If agents are already configured, nothing to do
    if agent_ids and agent_ids != [DEFAULT_AGENT_ID]:
        logger.debug("Agents already configured: {}", agent_ids)
        return True

    # Check if we need to auto-create the default agent
    if config.agents.agent_list:
        # Already has explicit agent list
        return True

    logger.info("No agents configured, auto-creating default agent")

    # Create default agent entry from defaults
    default_agent = {
        "id": "assistant",
        "default": True,
        "name": "Assistant (Default)",
        "workspace": config.agents.defaults.workspace,
        "model": config.agents.defaults.model,
    }

    # Try to update config file
    try:
        config_path = _get_config_path()
        if not config_path.exists():
            # Create config file with default agent on first run
            logger.info("Config file not found, creating new config at {}", config_path)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_data = {
                "agents": {
                    "defaults": {
                        "workspace": config.agents.defaults.workspace,
                        "model": config.agents.defaults.model,
                    },
                    "list": [default_agent],
                }
            }
            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=2)
            logger.info("Created new config with default agent 'assistant'")
            return True

        with open(config_path, "r") as f:
            config_data = json.load(f)

        # Add default agent to list
        if "agents" not in config_data:
            config_data["agents"] = {}

        if "list" not in config_data["agents"]:
            config_data["agents"]["list"] = []

        # Check if already has a default agent
        has_default = any(
            a.get("default", False)
            for a in config_data["agents"]["list"]
        )

        if not has_default:
            config_data["agents"]["list"].insert(0, default_agent)

            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=2)

            logger.info("Created default agent 'assistant' from existing configuration")

        return True

    except Exception as e:
        logger.error("Failed to create default agent: {}", e)
        return False


def migrate_config() -> str:
    """Migrate existing configuration to manobot multi-agent format.

    Creates the manobot state directory and ensures the config
    is compatible with multi-agent setup.

    Returns:
        "migrated" if actual migration was performed,
        "already" if config was already in multi-agent format,
        "none" if no config exists,
        "error" on failure.
    """
    config_path = _get_config_path()
    manobot_state = get_manobot_state_dir()

    # Ensure manobot state directory exists
    manobot_state.mkdir(parents=True, exist_ok=True)
    (manobot_state / "agents").mkdir(exist_ok=True)

    if not config_path.exists():
        logger.info("No existing config found")
        return "none"

    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)

        # Check if already migrated
        if config_data.get("agents", {}).get("list"):
            logger.debug("Config already has agent list")
            return "already"

        # Add default agent from existing config
        default_agent = {
            "id": "assistant",
            "default": True,
            "name": "Assistant (Migrated)",
        }

        if "agents" not in config_data:
            config_data["agents"] = {}

        config_data["agents"]["list"] = [default_agent]

        # Write updated config
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info("Migrated config to multi-agent format")
        return "migrated"

    except Exception as e:
        logger.error("Migration failed: {}", e)
        return "error"


def initialize_manobot() -> dict:
    """Initialize manobot environment.

    Called on first run or when 'manobot init' is executed.

    Returns:
        Dict with initialization status and details
    """
    result = {
        "success": True,
        "state_dir": str(get_manobot_state_dir()),
        "config_path": str(_get_config_path()),
        "migrated": False,
        "default_agent": None,
        "errors": [],
    }

    # Create state directory
    state_dir = get_manobot_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "agents").mkdir(exist_ok=True)

    # Migrate config if needed
    migration_result = migrate_config()
    if migration_result == "error":
        result["errors"].append("Config migration failed")
        result["success"] = False
    elif migration_result == "migrated":
        result["migrated"] = True

    # Load and check config
    try:
        from agent.config.loader import load_config
        config = load_config()

        # Ensure default agent
        if ensure_default_agent(config):
            # Reload config after potential modifications by ensure_default_agent
            config = load_config()
            result["default_agent"] = resolve_default_agent_id(config)
        else:
            result["errors"].append("Failed to ensure default agent")
            result["success"] = False

    except Exception as e:
        result["errors"].append(f"Config load failed: {e}")
        result["success"] = False

    return result


def setup_agent_directories(agent_id: str) -> Path:
    """Setup directories for a new agent.

    Creates the required directory structure for agent-specific
    storage (memory, sessions, etc.).

    Args:
        agent_id: Agent ID

    Returns:
        Path to agent's root directory
    """
    normalized_id = normalize_agent_id(agent_id)
    agent_dir = get_manobot_state_dir() / "agents" / normalized_id

    # Create directory structure
    (agent_dir / "memory").mkdir(parents=True, exist_ok=True)
    (agent_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (agent_dir / "workspace").mkdir(parents=True, exist_ok=True)

    logger.debug("Created directories for agent: {}", normalized_id)
    return agent_dir

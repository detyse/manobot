"""Configuration loading utilities."""

from __future__ import annotations

import json
from pathlib import Path

from agent.config.schema import Config
from agent.utils.helpers import ensure_dir

_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the active configuration file path for this process."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the active configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def get_agent_config_path(agent_id: str) -> Path:
    """Get the per-agent configuration file path.
    
    Args:
        agent_id: The agent identifier.
        
    Returns:
        Path to the agent's config.json in its directory.
    """
    return Path.home() / ".manobot" / "agents" / agent_id / "config.json"


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    return ensure_dir(get_config_path().parent)


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()
    if config_path is not None:
        set_config_path(path)

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    if config_path is not None:
        set_config_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries. Override values take precedence.
    
    Args:
        base: The base dictionary.
        override: The override dictionary.
        
    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_agent_config(agent_id: str, global_config_path: Path | None = None) -> Config:
    """Load configuration for a specific agent with fallback to global config.
    
    This implements a hierarchical configuration system where:
    1. First loads the global config (~/.nanobot/config.json or specified path)
    2. Then checks for agent-specific config (~/.manobot/agents/{agent_id}/config.json)
    3. If agent config exists, it deep-merges with global config (agent values take precedence)
    4. If agent config doesn't exist, returns global config unchanged
    
    Args:
        agent_id: The agent identifier.
        global_config_path: Optional path to global config file.
        
    Returns:
        Loaded and merged configuration object.
    """
    # Load global config first
    global_config = load_config(global_config_path)
    
    # Check for agent-specific config
    agent_config_path = get_agent_config_path(agent_id)
    
    if not agent_config_path.exists():
        # No agent-specific config, return global config
        return global_config
    
    # Load agent-specific config
    try:
        with open(agent_config_path, encoding="utf-8") as f:
            agent_data = json.load(f)
        agent_data = _migrate_config(agent_data)
        
        # Get global config as dict
        global_data = global_config.model_dump(by_alias=True)
        
        # Deep merge: agent config overrides global config
        merged_data = _deep_merge(global_data, agent_data)
        
        return Config.model_validate(merged_data)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: Failed to load agent config from {agent_config_path}: {e}")
        print("Falling back to global configuration.")
        return global_config


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Clean up removed bindings field from old configs
    data.pop("bindings", None)
    agents = data.get("agents", {})
    agents.pop("bindings", None)

    return data

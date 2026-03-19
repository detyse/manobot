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

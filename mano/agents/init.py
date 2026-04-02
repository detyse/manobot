"""Auto-initialization helpers for isolated manobot agents."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from mano.agents.registry import (
    get_agents_root,
    get_registry_path,
    list_registered_agent_ids,
    register_agent,
    resolve_default_registered_agent_id,
    scan_registered_agent_ids_on_disk,
    set_default_registered_agent,
)
from mano.core.scope import normalize_agent_id


def get_manobot_state_dir() -> Path:
    """Get the manobot state directory."""
    return Path.home() / ".manobot"


def ensure_default_agent() -> bool:
    """Ensure the registry has at least one agent and a default selection."""
    agent_ids = list_registered_agent_ids()
    if not agent_ids:
        return False

    default_id = resolve_default_registered_agent_id()
    if default_id in agent_ids:
        return True

    set_default_registered_agent(agent_ids[0])
    return True


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pick_default_from_disk(agent_ids: list[str]) -> str | None:
    """Pick a default agent by inspecting isolated agent config files."""
    for agent_id in agent_ids:
        config_path = get_agents_root() / agent_id / "config.json"
        if not config_path.exists():
            continue
        try:
            agent_list = _load_json(config_path).get("agents", {}).get("list", [])
        except (OSError, json.JSONDecodeError):
            continue
        if agent_list and agent_list[0].get("default"):
            return normalize_agent_id(agent_list[0].get("id") or agent_id)
    return agent_ids[0] if agent_ids else None


def bootstrap_registry() -> str:
    """Ensure the registry matches isolated agent configs on disk."""
    from mano.agents.onboard import onboard_agent

    state_dir = get_manobot_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    get_agents_root().mkdir(parents=True, exist_ok=True)

    if list_registered_agent_ids():
        logger.debug("Agent registry already initialized")
        return "already"

    disk_agents = scan_registered_agent_ids_on_disk()
    if disk_agents:
        default_id = _pick_default_from_disk(disk_agents)
        for agent_id in disk_agents:
            register_agent(agent_id, default=agent_id == default_id)
        logger.info("Bootstrapped registry from {} isolated agent config(s)", len(disk_agents))
        return "already"

    onboard_agent("assistant", mode="refresh", set_default=True)
    logger.info("Created default isolated agent 'assistant'")
    return "created"


def initialize_manobot() -> dict:
    """Initialize the manobot state directory and isolated-agent registry."""
    result = {
        "success": True,
        "state_dir": str(get_manobot_state_dir()),
        "registry_path": str(get_registry_path()),
        "created_default_agent": False,
        "default_agent": None,
        "errors": [],
    }

    state_dir = get_manobot_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    get_agents_root().mkdir(parents=True, exist_ok=True)

    try:
        bootstrap_result = bootstrap_registry()
        if bootstrap_result == "created":
            result["created_default_agent"] = True

        if ensure_default_agent():
            result["default_agent"] = resolve_default_registered_agent_id()
        else:
            result["errors"].append("Failed to ensure default agent")
            result["success"] = False
    except Exception as e:
        result["errors"].append(f"Initialization failed: {e}")
        result["success"] = False

    return result

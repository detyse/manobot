"""Thin registry for independent manobot agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mano.core.scope import normalize_agent_id


def get_agents_root() -> Path:
    """Return the root directory that stores all agent data."""
    return Path.home() / ".manobot" / "agents"


def get_registry_path() -> Path:
    """Return the registry file path."""
    return get_agents_root() / "registry.json"


def get_agent_root(agent_id: str) -> Path:
    """Return one agent's root directory."""
    return get_agents_root() / normalize_agent_id(agent_id)


def get_agent_config_path(agent_id: str) -> Path:
    """Return one agent's standalone config path."""
    return get_agent_root(agent_id) / "config.json"


def _normalize_registry(data: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize registry content to the current schema."""
    raw = data or {}
    raw_agents = raw.get("agents", [])

    ids: list[str] = []
    seen: set[str] = set()
    for item in raw_agents:
        if isinstance(item, str):
            agent_id = normalize_agent_id(item)
        elif isinstance(item, dict):
            agent_id = normalize_agent_id(item.get("id"))
        else:
            continue
        if agent_id and agent_id not in seen:
            ids.append(agent_id)
            seen.add(agent_id)

    default_agent = normalize_agent_id(raw.get("defaultAgent"))
    if default_agent not in seen:
        default_agent = ids[0] if ids else None

    return {
        "defaultAgent": default_agent,
        "agents": ids,
    }


def load_registry() -> dict[str, Any]:
    """Load registry content from disk."""
    path = get_registry_path()
    if not path.exists():
        return _normalize_registry(None)

    try:
        with open(path, encoding="utf-8") as f:
            return _normalize_registry(json.load(f))
    except (OSError, json.JSONDecodeError):
        return _normalize_registry(None)


def save_registry(data: dict[str, Any]) -> None:
    """Persist registry content to disk."""
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_registry(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)


def list_registered_agent_ids() -> list[str]:
    """Return all registered agent IDs."""
    return list(load_registry()["agents"])


def resolve_default_registered_agent_id() -> str | None:
    """Return the default registered agent ID."""
    return load_registry()["defaultAgent"]


def is_registered(agent_id: str) -> bool:
    """Return whether an agent is present in the registry."""
    normalized = normalize_agent_id(agent_id)
    return normalized in set(list_registered_agent_ids())


def register_agent(agent_id: str, *, default: bool | None = None) -> dict[str, Any]:
    """Add an agent to the registry."""
    normalized = normalize_agent_id(agent_id)
    data = load_registry()
    if normalized not in data["agents"]:
        data["agents"].append(normalized)
    if default or not data["defaultAgent"]:
        data["defaultAgent"] = normalized
    save_registry(data)
    sync_agent_default_flags()
    return load_registry()


def set_default_registered_agent(agent_id: str) -> dict[str, Any]:
    """Set the default agent in the registry."""
    normalized = normalize_agent_id(agent_id)
    data = load_registry()
    if normalized not in data["agents"]:
        data["agents"].append(normalized)
    data["defaultAgent"] = normalized
    save_registry(data)
    sync_agent_default_flags()
    return load_registry()


def unregister_agent(agent_id: str) -> dict[str, Any]:
    """Remove an agent from the registry."""
    normalized = normalize_agent_id(agent_id)
    data = load_registry()
    data["agents"] = [item for item in data["agents"] if item != normalized]
    if data["defaultAgent"] == normalized:
        data["defaultAgent"] = data["agents"][0] if data["agents"] else None
    save_registry(data)
    sync_agent_default_flags()
    return load_registry()


def sync_agent_default_flags() -> None:
    """Keep each standalone config's `default` flag aligned with the registry."""
    data = load_registry()
    default_agent = data["defaultAgent"]
    for agent_id in data["agents"]:
        config_path = get_agent_config_path(agent_id)
        if not config_path.exists():
            continue
        try:
            with open(config_path, encoding="utf-8") as f:
                config_data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        agents = config_data.setdefault("agents", {})
        agent_list = agents.setdefault("list", [{"id": agent_id}])
        if not agent_list:
            agent_list.append({"id": agent_id})

        agent_list[0]["id"] = normalize_agent_id(agent_list[0].get("id") or agent_id)
        agent_list[0]["default"] = agent_id == default_agent

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)


def scan_registered_agent_ids_on_disk() -> list[str]:
    """Discover standalone agent configs from the filesystem."""
    agents_root = get_agents_root()
    if not agents_root.exists():
        return []

    ids: list[str] = []
    for child in sorted(agents_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "config.json").exists():
            ids.append(normalize_agent_id(child.name))
    return ids


def load_registered_agent_config(agent_id: str):
    """Load one registered agent's standalone config."""
    from agent.config.loader import load_config

    return load_config(get_agent_config_path(agent_id))

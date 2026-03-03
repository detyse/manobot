"""Agent scope management for multi-agent support.

This module provides functions to resolve agent configurations, workspaces,
and session routing in a multi-agent environment.

Reference: OpenClaw agent-scope.ts
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import AgentEntryConfig, AgentsConfig, Config

# Default agent ID when no agents are configured
DEFAULT_AGENT_ID = "default"

# Warn only once about multiple default agents
_default_agent_warned = False


def normalize_agent_id(agent_id: str | None) -> str:
    """Normalize agent ID to lowercase alphanumeric with hyphens.
    
    Args:
        agent_id: Raw agent ID string
        
    Returns:
        Normalized agent ID or DEFAULT_AGENT_ID if empty
    """
    if not agent_id:
        return DEFAULT_AGENT_ID
    
    # Convert to lowercase, replace non-alphanumeric with hyphens
    normalized = re.sub(r"[^a-z0-9-]", "-", agent_id.lower().strip())
    # Remove consecutive hyphens
    normalized = re.sub(r"-+", "-", normalized)
    # Remove leading/trailing hyphens
    normalized = normalized.strip("-")
    
    return normalized or DEFAULT_AGENT_ID


def list_agent_entries(config: Config) -> list[AgentEntryConfig]:
    """List all configured agent entries.
    
    Args:
        config: Application configuration
        
    Returns:
        List of agent entry configurations
    """
    agents_list = config.agents.list
    if not agents_list:
        return []
    return [entry for entry in agents_list if entry and entry.id]


def list_agent_ids(config: Config) -> list[str]:
    """List all configured agent IDs.
    
    Args:
        config: Application configuration
        
    Returns:
        List of normalized agent IDs, or [DEFAULT_AGENT_ID] if none configured
    """
    entries = list_agent_entries(config)
    if not entries:
        return [DEFAULT_AGENT_ID]
    
    seen: set[str] = set()
    ids: list[str] = []
    
    for entry in entries:
        agent_id = normalize_agent_id(entry.id)
        if agent_id not in seen:
            seen.add(agent_id)
            ids.append(agent_id)
    
    return ids if ids else [DEFAULT_AGENT_ID]


def resolve_default_agent_id(config: Config) -> str:
    """Resolve the default agent ID.
    
    Args:
        config: Application configuration
        
    Returns:
        The default agent ID
    """
    global _default_agent_warned
    
    entries = list_agent_entries(config)
    if not entries:
        return DEFAULT_AGENT_ID
    
    # Find entries marked as default
    defaults = [e for e in entries if e.default]
    
    if len(defaults) > 1 and not _default_agent_warned:
        _default_agent_warned = True
        logger.warning("Multiple agents marked default=true; using the first entry as default.")
    
    # Use first default, or first entry if no defaults
    chosen = defaults[0] if defaults else entries[0]
    return normalize_agent_id(chosen.id)


def resolve_agent_entry(config: Config, agent_id: str) -> AgentEntryConfig | None:
    """Find an agent entry by ID.
    
    Args:
        config: Application configuration
        agent_id: Agent ID to look up
        
    Returns:
        The agent entry configuration, or None if not found
    """
    normalized_id = normalize_agent_id(agent_id)
    for entry in list_agent_entries(config):
        if normalize_agent_id(entry.id) == normalized_id:
            return entry
    return None


def resolve_agent_config(config: Config, agent_id: str) -> dict[str, Any] | None:
    """Resolve the effective configuration for an agent.
    
    Merges agent-specific settings with defaults.
    
    Args:
        config: Application configuration
        agent_id: Agent ID
        
    Returns:
        Merged agent configuration dict, or None if agent not found
    """
    entry = resolve_agent_entry(config, agent_id)
    if not entry:
        # If no specific agent found but ID is default, return defaults
        if normalize_agent_id(agent_id) == resolve_default_agent_id(config):
            return {
                "id": DEFAULT_AGENT_ID,
                "workspace": config.agents.defaults.workspace,
                "model": config.agents.defaults.model,
                "provider": config.agents.defaults.provider,
                "max_tokens": config.agents.defaults.max_tokens,
                "temperature": config.agents.defaults.temperature,
            }
        return None
    
    defaults = config.agents.defaults
    
    return {
        "id": normalize_agent_id(entry.id),
        "name": entry.name,
        "default": entry.default,
        "workspace": entry.workspace or defaults.workspace,
        "model": entry.model or defaults.model,
        "provider": entry.provider or defaults.provider,
        "max_tokens": entry.max_tokens if entry.max_tokens is not None else defaults.max_tokens,
        "temperature": entry.temperature if entry.temperature is not None else defaults.temperature,
        "skills": entry.skills,
        "identity": entry.identity.model_dump() if entry.identity else None,
        "subagents": entry.subagents.model_dump() if entry.subagents else None,
    }


def resolve_agent_workspace(config: Config, agent_id: str) -> Path:
    """Resolve the workspace path for an agent.
    
    Args:
        config: Application configuration
        agent_id: Agent ID
        
    Returns:
        Expanded workspace path
    """
    normalized_id = normalize_agent_id(agent_id)
    entry = resolve_agent_entry(config, normalized_id)
    
    if entry and entry.workspace:
        return Path(entry.workspace).expanduser()
    
    # Use default workspace for default agent
    default_agent_id = resolve_default_agent_id(config)
    if normalized_id == default_agent_id:
        return Path(config.agents.defaults.workspace).expanduser()
    
    # Create agent-specific workspace under state directory
    state_dir = Path.home() / ".manobot"
    return state_dir / "agents" / normalized_id / "workspace"


def resolve_agent_memory_dir(config: Config, agent_id: str) -> Path:
    """Resolve the memory directory for an agent.
    
    Each agent has isolated memory storage.
    
    Args:
        config: Application configuration
        agent_id: Agent ID
        
    Returns:
        Memory directory path
    """
    normalized_id = normalize_agent_id(agent_id)
    state_dir = Path.home() / ".manobot"
    return state_dir / "agents" / normalized_id / "memory"


def resolve_agent_sessions_dir(config: Config, agent_id: str) -> Path:
    """Resolve the sessions directory for an agent.
    
    Each agent has isolated session storage.
    
    Args:
        config: Application configuration
        agent_id: Agent ID
        
    Returns:
        Sessions directory path
    """
    normalized_id = normalize_agent_id(agent_id)
    state_dir = Path.home() / ".manobot"
    return state_dir / "agents" / normalized_id / "sessions"


def parse_session_key(session_key: str) -> dict[str, str | None]:
    """Parse a session key into components.
    
    Session key formats:
    - "channel:chat_id" - legacy format
    - "agent:channel:chat_id" - multi-agent format
    
    Args:
        session_key: Session key string
        
    Returns:
        Dict with agent_id, channel, and chat_id
    """
    parts = session_key.split(":", 2)
    
    if len(parts) == 3:
        # Multi-agent format: agent:channel:chat_id
        return {
            "agent_id": parts[0] or None,
            "channel": parts[1],
            "chat_id": parts[2],
        }
    elif len(parts) == 2:
        # Legacy format: channel:chat_id
        return {
            "agent_id": None,
            "channel": parts[0],
            "chat_id": parts[1],
        }
    else:
        return {
            "agent_id": None,
            "channel": session_key,
            "chat_id": "",
        }


def resolve_session_agent_id(config: Config, session_key: str | None) -> str:
    """Resolve the agent ID from a session key.
    
    Args:
        config: Application configuration
        session_key: Session key (may contain agent ID prefix)
        
    Returns:
        Resolved agent ID
    """
    if not session_key:
        return resolve_default_agent_id(config)
    
    parsed = parse_session_key(session_key)
    if parsed["agent_id"]:
        return normalize_agent_id(parsed["agent_id"])
    
    return resolve_default_agent_id(config)


def build_session_key(agent_id: str, channel: str, chat_id: str) -> str:
    """Build a session key for multi-agent routing.
    
    Args:
        agent_id: Agent ID
        channel: Channel name
        chat_id: Chat ID
        
    Returns:
        Session key in format "agent:channel:chat_id"
    """
    normalized_id = normalize_agent_id(agent_id)
    return f"{normalized_id}:{channel}:{chat_id}"

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

from manobot.agents.scope_model import AgentScope

if TYPE_CHECKING:
    from nanobot.config.schema import AgentEntryConfig, Config

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
    agents_list = config.agents.agent_list
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
    normalized_id = normalize_agent_id(agent_id)
    entry = resolve_agent_entry(config, normalized_id)
    if not entry:
        # If no specific agent found but ID is default, return defaults
        if normalized_id == resolve_default_agent_id(config):
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
    default_agent_id = resolve_default_agent_id(config)

    # Workspace resolution: only default agent can use defaults.workspace
    # Non-default agents get isolated workspace if not explicitly specified
    if entry.workspace:
        workspace = entry.workspace
    elif normalized_id == default_agent_id:
        # Default agent uses the shared defaults.workspace
        workspace = defaults.workspace
    else:
        # Non-default agents get isolated workspace
        state_dir = Path.home() / ".manobot"
        workspace = str(state_dir / "agents" / normalized_id / "workspace")

    return {
        "id": normalize_agent_id(entry.id),
        "name": entry.name,
        "default": entry.default,
        "workspace": workspace,
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

    Session key formats (newest first):
    - "agent:{agent_id}:{account_id}:{channel}:{peer_id}[:{thread_id}]" - v2 (with account)
    - "agent:{agent_id}:{channel}:{peer_id}[:{thread_id}]" - v1 (no account)
    - "{agent_id}:{channel}:{chat_id}" - legacy multi-agent format
    - "{channel}:{chat_id}" - ancient format

    Args:
        session_key: Session key string

    Returns:
        Dict with agent_id, channel, chat_id, and thread_id
    """
    # New format with "agent:" prefix
    if session_key.startswith("agent:"):
        rest = session_key[len("agent:"):]
        parts = rest.split(":")
        if len(parts) >= 4:
            # v2: agent:{agent_id}:{account_id}:{channel}:{peer_id}[:{thread_id}]
            return {
                "agent_id": parts[0] or None,
                "channel": parts[2],
                "chat_id": parts[3],
                "thread_id": parts[4] if len(parts) > 4 else None,
            }
        elif len(parts) == 3:
            # v1: agent:{agent_id}:{channel}:{peer_id}
            return {
                "agent_id": parts[0] or None,
                "channel": parts[1],
                "chat_id": parts[2],
                "thread_id": None,
            }

    parts = session_key.split(":", 2)

    if len(parts) == 3:
        # Legacy multi-agent format: agent_id:channel:chat_id
        return {
            "agent_id": parts[0] or None,
            "channel": parts[1],
            "chat_id": parts[2],
            "thread_id": None,
        }
    elif len(parts) == 2:
        # Ancient format: channel:chat_id
        return {
            "agent_id": None,
            "channel": parts[0],
            "chat_id": parts[1],
            "thread_id": None,
        }
    else:
        return {
            "agent_id": None,
            "channel": session_key,
            "chat_id": "",
            "thread_id": None,
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


# ---------------------------------------------------------------------------
# Fallback agent resolution (replaces "default" concept)
# ---------------------------------------------------------------------------

def resolve_fallback_agent_id(config: Config) -> str:
    """Resolve the fallback agent ID.

    Prefers the explicit ``agents.fallback`` field; falls back to the old
    ``default=True`` logic for backwards compatibility.

    Args:
        config: Application configuration

    Returns:
        The fallback agent ID
    """
    # Prefer explicit fallback field
    if config.agents.fallback:
        normalized = normalize_agent_id(config.agents.fallback)
        # Verify it actually exists
        entry = resolve_agent_entry(config, normalized)
        if entry:
            return normalized
        logger.warning(
            "agents.fallback='{}' is not a configured agent; "
            "falling back to default=True logic.",
            config.agents.fallback,
        )

    # Fall back to old default=True logic
    return resolve_default_agent_id(config)


# ---------------------------------------------------------------------------
# AgentScope factory
# ---------------------------------------------------------------------------

def _resolve_state_dir() -> Path:
    """Return the manobot state directory (~/.manobot)."""
    return Path.home() / ".manobot"


def build_agent_scope(config: Config, agent_id: str) -> AgentScope | None:
    """Build a complete AgentScope for a given agent.

    Merges per-agent overrides with defaults into a single object that
    contains every path and setting the agent needs.

    Args:
        config: Application configuration
        agent_id: Agent ID

    Returns:
        Fully resolved AgentScope, or None if the agent is not found
    """
    normalized_id = normalize_agent_id(agent_id)
    entry = resolve_agent_entry(config, normalized_id)
    defaults = config.agents.defaults
    fallback_id = resolve_fallback_agent_id(config)
    state_dir = _resolve_state_dir()

    if not entry:
        # If this is the fallback agent with no explicit entry, build from defaults
        if normalized_id == fallback_id:
            workspace = Path(defaults.workspace).expanduser()
            agent_dir = state_dir / "agents" / normalized_id
            return AgentScope(
                agent_id=normalized_id,
                name=None,
                is_fallback=True,
                workspace=workspace,
                agent_dir=agent_dir,
                sessions_dir=agent_dir / "sessions",
                memory_dir=agent_dir / "memory",
                skills_dir=None,
                model=defaults.model,
                provider=defaults.provider,
                max_tokens=defaults.max_tokens,
                temperature=defaults.temperature,
                max_tool_iterations=defaults.max_tool_iterations,
                memory_window=defaults.memory_window,
                reasoning_effort=defaults.reasoning_effort,
            )
        return None

    is_fallback = normalized_id == fallback_id

    # --- Paths ---
    # agent_dir
    if entry.agent_dir:
        agent_dir = Path(entry.agent_dir).expanduser()
    else:
        agent_dir = state_dir / "agents" / normalized_id

    # workspace
    if entry.workspace:
        workspace = Path(entry.workspace).expanduser()
    elif is_fallback:
        workspace = Path(defaults.workspace).expanduser()
    else:
        workspace = agent_dir / "workspace"

    # sessions_dir
    if entry.sessions_dir:
        sessions_dir = Path(entry.sessions_dir).expanduser()
    else:
        sessions_dir = agent_dir / "sessions"

    # memory_dir
    if entry.memory_dir:
        memory_dir = Path(entry.memory_dir).expanduser()
    else:
        memory_dir = agent_dir / "memory"

    return AgentScope(
        agent_id=normalized_id,
        name=entry.name,
        is_fallback=is_fallback,
        workspace=workspace,
        agent_dir=agent_dir,
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        skills_dir=agent_dir / "skills" if agent_dir else None,
        model=entry.model or defaults.model,
        provider=entry.provider or defaults.provider,
        max_tokens=entry.max_tokens if entry.max_tokens is not None else defaults.max_tokens,
        temperature=entry.temperature if entry.temperature is not None else defaults.temperature,
        max_tool_iterations=defaults.max_tool_iterations,
        memory_window=defaults.memory_window,
        reasoning_effort=defaults.reasoning_effort,
        skills=entry.skills,
        identity=entry.identity.model_dump() if entry.identity else None,
        subagents=entry.subagents.model_dump() if entry.subagents else None,
    )


def build_all_scopes(config: Config) -> dict[str, AgentScope]:
    """Build AgentScope objects for all configured agents.

    Args:
        config: Application configuration

    Returns:
        Dict mapping agent_id -> AgentScope
    """
    scopes: dict[str, AgentScope] = {}
    for agent_id in list_agent_ids(config):
        scope = build_agent_scope(config, agent_id)
        if scope:
            scopes[scope.agent_id] = scope
    return scopes

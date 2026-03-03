"""Multi-agent management module."""

from manobot.agents.init import (
    ensure_default_agent,
    initialize_manobot,
    migrate_nanobot_config,
    setup_agent_directories,
)
from manobot.agents.pool import AgentPool
from manobot.agents.registry import AgentRegistry
from manobot.agents.scope import (
    DEFAULT_AGENT_ID,
    list_agent_entries,
    list_agent_ids,
    normalize_agent_id,
    resolve_agent_config,
    resolve_agent_workspace,
    resolve_default_agent_id,
    resolve_session_agent_id,
)

__all__ = [
    "AgentPool",
    "AgentRegistry",
    "DEFAULT_AGENT_ID",
    "ensure_default_agent",
    "initialize_manobot",
    "list_agent_entries",
    "list_agent_ids",
    "migrate_nanobot_config",
    "normalize_agent_id",
    "resolve_agent_config",
    "resolve_agent_workspace",
    "resolve_default_agent_id",
    "resolve_session_agent_id",
    "setup_agent_directories",
]

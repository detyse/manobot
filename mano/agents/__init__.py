"""Multi-agent management module."""

from mano.agents.init import (
    ensure_default_agent,
    initialize_manobot,
    migrate_nanobot_config,
    setup_agent_directories,
)
from mano.agents.pool import AgentPool
from mano.agents.registry import AgentRegistry
from mano.agents.scope import (
    DEFAULT_AGENT_ID,
    build_agent_scope,
    build_all_scopes,
    list_agent_entries,
    list_agent_ids,
    normalize_agent_id,
    resolve_agent_config,
    resolve_agent_workspace,
    resolve_default_agent_id,
    resolve_fallback_agent_id,
    resolve_session_agent_id,
)
from mano.agents.scope_model import AgentScope

__all__ = [
    "AgentPool",
    "AgentRegistry",
    "AgentScope",
    "DEFAULT_AGENT_ID",
    "build_agent_scope",
    "build_all_scopes",
    "ensure_default_agent",
    "initialize_manobot",
    "list_agent_entries",
    "list_agent_ids",
    "migrate_nanobot_config",
    "normalize_agent_id",
    "resolve_agent_config",
    "resolve_agent_workspace",
    "resolve_default_agent_id",
    "resolve_fallback_agent_id",
    "resolve_session_agent_id",
    "setup_agent_directories",
]

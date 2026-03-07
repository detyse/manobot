"""Manobot - Multi-Agent management layer for Nanobot."""

__version__ = "0.1.0"
__logo__ = "🤖"

from mano.agents.scope import (
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
    "DEFAULT_AGENT_ID",
    "list_agent_entries",
    "list_agent_ids",
    "normalize_agent_id",
    "resolve_agent_config",
    "resolve_agent_workspace",
    "resolve_default_agent_id",
    "resolve_session_agent_id",
]

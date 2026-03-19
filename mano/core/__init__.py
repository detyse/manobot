"""Core multi-agent components for manobot."""

from mano.core.process_manager import ProcessManager
from mano.core.scope import (
    AgentScope,
    build_agent_scope,
    build_session_key,
    list_agent_ids,
    normalize_agent_id,
    parse_session_key,
    resolve_agent_entry,
    resolve_default_agent_id,
)
from mano.core.state import AgentProcessState

__all__ = [
    "AgentProcessState",
    "AgentScope",
    "ProcessManager",
    "build_agent_scope",
    "build_session_key",
    "list_agent_ids",
    "normalize_agent_id",
    "parse_session_key",
    "resolve_agent_entry",
    "resolve_default_agent_id",
]

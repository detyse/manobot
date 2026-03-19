"""Manobot - Multi-Agent management layer for Nanobot."""

__version__ = "0.1.0"
__logo__ = "🤖"

from mano.core.scope import (
    DEFAULT_AGENT_ID,
    build_session_key,
    list_agent_ids,
    normalize_agent_id,
    parse_session_key,
    resolve_default_agent_id,
)

__all__ = [
    "DEFAULT_AGENT_ID",
    "build_session_key",
    "list_agent_ids",
    "normalize_agent_id",
    "parse_session_key",
    "resolve_default_agent_id",
]

"""Multi-agent management module."""

from mano.agents.init import (
    ensure_default_agent,
    initialize_manobot,
    migrate_config,
    setup_agent_directories,
)

__all__ = [
    "ensure_default_agent",
    "initialize_manobot",
    "migrate_config",
    "setup_agent_directories",
]

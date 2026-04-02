"""Multi-agent management module."""

from mano.agents.init import (
    bootstrap_registry,
    ensure_default_agent,
    initialize_manobot,
)
from mano.agents.onboard import onboard_agent
from mano.agents.registry import (
    get_agent_config_path,
    get_registry_path,
    list_registered_agent_ids,
    resolve_default_registered_agent_id,
)

__all__ = [
    "bootstrap_registry",
    "ensure_default_agent",
    "get_agent_config_path",
    "get_registry_path",
    "initialize_manobot",
    "list_registered_agent_ids",
    "onboard_agent",
    "resolve_default_registered_agent_id",
]

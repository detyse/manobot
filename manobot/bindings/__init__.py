"""Message routing and bindings module."""

from manobot.bindings.router import MessageRouter, resolve_agent_for_message

__all__ = [
    "MessageRouter",
    "resolve_agent_for_message",
]

"""Message bus module for decoupled channel-agent communication."""

from agent.bus.events import InboundMessage, OutboundMessage
from agent.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

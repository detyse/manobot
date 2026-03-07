"""Chat channels module with plugin architecture."""

from agent.channels.base import BaseChannel
from agent.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]

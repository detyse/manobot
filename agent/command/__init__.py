"""Slash command routing and built-in handlers."""

from agent.command.builtin import register_builtin_commands
from agent.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]

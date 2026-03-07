"""CLI module for manobot."""

from manobot.cli.agents import agents_app
from manobot.cli.channels import channels_app
from manobot.cli.providers import provider_app

__all__ = ["agents_app", "channels_app", "provider_app"]

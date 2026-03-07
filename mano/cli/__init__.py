"""CLI module for manobot."""

from mano.cli.agents import agents_app
from mano.cli.channels import channels_app
from mano.cli.providers import provider_app

__all__ = ["agents_app", "channels_app", "provider_app"]

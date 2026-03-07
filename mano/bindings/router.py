"""Message router for multi-agent routing.

This module routes incoming messages to the appropriate agent
based on bindings configuration.  Internally delegates to the
deterministic ``BindingResolver`` (most-specific-wins).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from mano.agents.scope import list_agent_ids, normalize_agent_id, resolve_fallback_agent_id
from mano.bindings.resolver import BindingResolver, InboundContext, RouteDecision, RouteTier

if TYPE_CHECKING:
    from agent.config.schema import Config


# Backwards-compatible alias
@dataclass
class RouteMatch:
    """Result of a route matching operation (legacy compat)."""

    agent_id: str
    binding_index: int | None = None
    comment: str | None = None


class MessageRouter:
    """Message router for multi-agent message handling.

    Wraps ``BindingResolver`` and provides caching and management APIs.
    """

    def __init__(self, config: Config):
        """Initialize the message router.

        Args:
            config: Application configuration
        """
        self.config = config
        self._fallback_id = resolve_fallback_agent_id(config)
        self._resolver = BindingResolver(
            bindings=config.agents.bindings,
            fallback_agent_id=self._fallback_id,
        )
        self._route_cache: dict[str, RouteDecision] = {}

    def route(
        self,
        channel: str,
        chat_id: str | None = None,
        sender_id: str | None = None,
        peer_type: str | None = None,
        guild_id: str | None = None,
        team_id: str | None = None,
        account_id: str = "default",
        parent_peer_id: str | None = None,
        use_cache: bool = True,
    ) -> RouteDecision:
        """Route a message to an agent using the tiered resolver.

        Args:
            channel: Channel name
            chat_id: Chat/conversation ID (used as peer_id)
            sender_id: Sender user ID
            peer_type: Chat type
            guild_id: Discord guild ID
            team_id: Slack team ID
            account_id: Channel account identifier
            parent_peer_id: Parent peer ID (e.g. thread parent)
            use_cache: Whether to use cached routes

        Returns:
            RouteDecision with agent_id, tier, and explanation
        """
        cache_key = (
            f"{channel}:{account_id}:{chat_id}:{sender_id}:"
            f"{peer_type}:{guild_id}:{team_id}:{parent_peer_id}"
        )

        if use_cache and cache_key in self._route_cache:
            return self._route_cache[cache_key]

        ctx = InboundContext(
            channel=channel,
            account_id=account_id,
            peer_id=chat_id,
            parent_peer_id=parent_peer_id,
            sender_id=sender_id,
            peer_type=peer_type,
            guild_id=guild_id,
            team_id=team_id,
        )

        # Validate that resolved agent actually exists in config
        decision = self._resolver.resolve(ctx)
        configured_ids = set(normalize_agent_id(i) for i in list_agent_ids(self.config))

        if decision.tier != RouteTier.SYSTEM_FALLBACK and decision.agent_id not in configured_ids:
            logger.warning(
                "Binding #{} resolved to agent '{}' which is not configured; "
                "routing to fallback agent '{}'.",
                decision.binding_index,
                decision.agent_id,
                self._fallback_id,
            )
            decision = RouteDecision(
                agent_id=self._fallback_id,
                tier=RouteTier.SYSTEM_FALLBACK,
                binding_index=decision.binding_index,
                reason=f"Agent '{decision.agent_id}' not configured; fallback to '{self._fallback_id}'",
            )

        if use_cache:
            self._route_cache[cache_key] = decision

        return decision

    def clear_cache(self) -> None:
        """Clear the routing cache."""
        self._route_cache.clear()

    def invalidate_route(self, channel: str, chat_id: str | None = None) -> None:
        """Invalidate cached route for a specific channel/chat.

        Args:
            channel: Channel name
            chat_id: Chat ID (if None, invalidates all for channel)
        """
        if chat_id:
            prefix = f"{channel}:"
            # Need to match keys that contain this chat_id
            keys_to_remove = [
                k for k in self._route_cache
                if k.startswith(prefix) and f":{chat_id}:" in k
            ]
        else:
            prefix = f"{channel}:"
            keys_to_remove = [k for k in self._route_cache if k.startswith(prefix)]

        for key in keys_to_remove:
            del self._route_cache[key]

    def list_bindings(self) -> list[dict]:
        """List all configured bindings.

        Returns:
            List of binding configurations as dicts
        """
        return [
            {
                "index": idx,
                "id": b.id,
                "agent_id": normalize_agent_id(b.agent_id),
                "channel": b.match.channel,
                "account_id": b.match.account_id,
                "peer_type": b.match.peer_type,
                "peer_id": b.match.peer_id,
                "parent_peer_id": b.match.parent_peer_id,
                "guild_id": b.match.guild_id,
                "team_id": b.match.team_id,
                "comment": b.comment,
            }
            for idx, b in enumerate(self.config.agents.bindings)
        ]

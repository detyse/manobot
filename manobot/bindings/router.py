"""Message router for multi-agent routing.

This module routes incoming messages to the appropriate agent
based on bindings configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from manobot.agents.scope import normalize_agent_id, resolve_default_agent_id

if TYPE_CHECKING:
    from nanobot.config.schema import AgentBindingConfig, Config


@dataclass
class RouteMatch:
    """Result of a route matching operation."""
    
    agent_id: str
    binding_index: int | None = None  # Index of matched binding, None if default
    comment: str | None = None  # Binding comment if any


def matches_binding(
    binding: AgentBindingConfig,
    channel: str,
    chat_id: str | None = None,
    sender_id: str | None = None,
    peer_type: str | None = None,
    guild_id: str | None = None,
    team_id: str | None = None,
) -> bool:
    """Check if a message matches a binding configuration.
    
    Args:
        binding: Binding configuration to match against
        channel: Channel name (telegram, discord, etc.)
        chat_id: Chat/conversation ID
        sender_id: Sender user ID
        peer_type: Chat type (direct, group, channel)
        guild_id: Discord guild ID
        team_id: Slack team ID
        
    Returns:
        True if the message matches the binding
    """
    match = binding.match
    
    # Channel must match
    if match.channel.lower() != channel.lower():
        return False
    
    # Check optional peer_type
    if match.peer_type and peer_type:
        if match.peer_type.lower() != peer_type.lower():
            return False
    
    # Check optional peer_id (chat_id)
    if match.peer_id and chat_id:
        if match.peer_id != chat_id:
            return False
    
    # Check optional account_id (sender_id)
    if match.account_id and sender_id:
        if match.account_id != sender_id:
            return False
    
    # Check optional guild_id (Discord)
    if match.guild_id and guild_id:
        if match.guild_id != guild_id:
            return False
    
    # Check optional team_id (Slack)
    if match.team_id and team_id:
        if match.team_id != team_id:
            return False
    
    return True


def resolve_agent_for_message(
    config: Config,
    channel: str,
    chat_id: str | None = None,
    sender_id: str | None = None,
    peer_type: str | None = None,
    guild_id: str | None = None,
    team_id: str | None = None,
) -> RouteMatch:
    """Resolve which agent should handle a message.
    
    Iterates through bindings in order and returns the first match.
    Falls back to the default agent if no bindings match.
    
    Args:
        config: Application configuration
        channel: Channel name
        chat_id: Chat/conversation ID
        sender_id: Sender user ID
        peer_type: Chat type
        guild_id: Discord guild ID
        team_id: Slack team ID
        
    Returns:
        RouteMatch with the target agent ID
    """
    bindings = config.agents.bindings
    
    for idx, binding in enumerate(bindings):
        if matches_binding(
            binding,
            channel=channel,
            chat_id=chat_id,
            sender_id=sender_id,
            peer_type=peer_type,
            guild_id=guild_id,
            team_id=team_id,
        ):
            agent_id = normalize_agent_id(binding.agent_id)
            logger.debug(
                "Route matched: {} -> {} (binding #{})",
                f"{channel}:{chat_id}",
                agent_id,
                idx,
            )
            return RouteMatch(
                agent_id=agent_id,
                binding_index=idx,
                comment=binding.comment,
            )
    
    # Fall back to default agent
    default_id = resolve_default_agent_id(config)
    logger.debug(
        "Route default: {} -> {}",
        f"{channel}:{chat_id}",
        default_id,
    )
    return RouteMatch(agent_id=default_id)


class MessageRouter:
    """Message router for multi-agent message handling.
    
    Provides methods to route incoming messages to appropriate agents
    and manage routing state.
    """
    
    def __init__(self, config: Config):
        """Initialize the message router.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self._route_cache: dict[str, RouteMatch] = {}
    
    def route(
        self,
        channel: str,
        chat_id: str | None = None,
        sender_id: str | None = None,
        peer_type: str | None = None,
        guild_id: str | None = None,
        team_id: str | None = None,
        use_cache: bool = True,
    ) -> RouteMatch:
        """Route a message to an agent.
        
        Args:
            channel: Channel name
            chat_id: Chat/conversation ID
            sender_id: Sender user ID
            peer_type: Chat type
            guild_id: Discord guild ID
            team_id: Slack team ID
            use_cache: Whether to use cached routes
            
        Returns:
            RouteMatch with the target agent ID
        """
        # Build cache key
        cache_key = f"{channel}:{chat_id}:{peer_type}:{guild_id}:{team_id}"
        
        if use_cache and cache_key in self._route_cache:
            return self._route_cache[cache_key]
        
        result = resolve_agent_for_message(
            self.config,
            channel=channel,
            chat_id=chat_id,
            sender_id=sender_id,
            peer_type=peer_type,
            guild_id=guild_id,
            team_id=team_id,
        )
        
        if use_cache:
            self._route_cache[cache_key] = result
        
        return result
    
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
            prefix = f"{channel}:{chat_id}:"
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
                "agent_id": normalize_agent_id(b.agent_id),
                "channel": b.match.channel,
                "peer_type": b.match.peer_type,
                "peer_id": b.match.peer_id,
                "comment": b.comment,
            }
            for idx, b in enumerate(self.config.agents.bindings)
        ]

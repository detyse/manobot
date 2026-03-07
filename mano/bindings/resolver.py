"""Deterministic binding resolver with tiered priority.

Replaces the old first-match routing with a most-specific-wins algorithm.
Each inbound message is matched against all bindings, and the binding
with the highest specificity tier wins.

Priority tiers (lower number = more specific = higher priority):
  1. EXACT_PEER    — channel + account_id + peer_id
  2. PARENT_PEER   — channel + account_id + parent_peer_id
  3. GUILD_TEAM    — channel + account_id + guild_id or team_id
  4. ACCOUNT       — channel + account_id
  5. CHANNEL       — channel only
  6. SYSTEM_FALLBACK — no binding matched, use fallback agent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import AgentBindingConfig

from manobot.agents.scope import normalize_agent_id


class RouteTier(IntEnum):
    """Binding match specificity tiers (lower = more specific)."""

    EXACT_PEER = 1
    PARENT_PEER = 2
    GUILD_TEAM = 3
    ACCOUNT = 4
    CHANNEL = 5
    SYSTEM_FALLBACK = 6


@dataclass
class InboundContext:
    """Extracted context from an inbound message for routing."""

    channel: str
    account_id: str = "default"
    peer_id: str | None = None
    parent_peer_id: str | None = None
    sender_id: str | None = None
    peer_type: str | None = None
    guild_id: str | None = None
    team_id: str | None = None


@dataclass
class RouteDecision:
    """Result of the binding resolver — includes match explanation."""

    agent_id: str
    tier: RouteTier
    binding_index: int | None = None
    reason: str = ""
    matched_fields: list[str] = field(default_factory=list)


class BindingResolver:
    """Deterministic most-specific-wins binding resolver.

    Given a list of bindings and a fallback agent ID, resolves which
    agent should handle a given inbound message context.
    """

    def __init__(
        self,
        bindings: list[AgentBindingConfig],
        fallback_agent_id: str,
    ):
        self._bindings = bindings
        self._fallback_agent_id = normalize_agent_id(fallback_agent_id)

    def resolve(self, ctx: InboundContext) -> RouteDecision:
        """Resolve the best-matching binding for an inbound context.

        Algorithm:
        1. For each binding, check if all its match fields are satisfied.
        2. Compute the tier based on which fields participated.
        3. Collect all matching (binding_index, tier, agent_id, matched_fields).
        4. Sort by tier ASC, then by binding_index ASC (config order).
        5. Return the most-specific match, or SYSTEM_FALLBACK.

        Args:
            ctx: Inbound message context

        Returns:
            RouteDecision with agent_id, tier, and explanation
        """
        candidates: list[tuple[int, RouteTier, str, list[str]]] = []

        for idx, binding in enumerate(self._bindings):
            result = self._match_binding(binding, ctx)
            if result is not None:
                tier, matched_fields = result
                agent_id = normalize_agent_id(binding.agent_id)
                candidates.append((idx, tier, agent_id, matched_fields))

        if not candidates:
            return RouteDecision(
                agent_id=self._fallback_agent_id,
                tier=RouteTier.SYSTEM_FALLBACK,
                binding_index=None,
                reason=f"No binding matched; fallback to agent '{self._fallback_agent_id}'",
                matched_fields=[],
            )

        # Sort: lowest tier first (most specific), then by config order
        candidates.sort(key=lambda c: (c[1], c[0]))
        best_idx, best_tier, best_agent, best_fields = candidates[0]

        binding = self._bindings[best_idx]
        binding_label = binding.id or f"#{best_idx}"

        reason = (
            f"Matched binding {binding_label} at tier {best_tier.name} "
            f"on fields [{', '.join(best_fields)}]"
        )

        logger.debug(
            "Route resolved: {}:{} -> agent '{}' ({})",
            ctx.channel,
            ctx.peer_id or "*",
            best_agent,
            reason,
        )

        return RouteDecision(
            agent_id=best_agent,
            tier=best_tier,
            binding_index=best_idx,
            reason=reason,
            matched_fields=best_fields,
        )

    def _match_binding(
        self,
        binding: AgentBindingConfig,
        ctx: InboundContext,
    ) -> tuple[RouteTier, list[str]] | None:
        """Check if a binding matches the context and compute its tier.

        Returns:
            (tier, matched_fields) if the binding matches, or None.
        """
        match = binding.match
        matched_fields: list[str] = []

        # Channel MUST match (case-insensitive)
        if match.channel.lower() != ctx.channel.lower():
            return None
        matched_fields.append("channel")

        # Check peer_type constraint (if binding specifies it, context must satisfy)
        if match.peer_type:
            if not ctx.peer_type or match.peer_type.lower() != ctx.peer_type.lower():
                return None
            matched_fields.append("peer_type")

        # Check account_id
        account_matched = False
        if match.account_id:
            if match.account_id != ctx.account_id:
                return None
            matched_fields.append("account_id")
            account_matched = True

        # Check peer_id (exact peer match)
        if match.peer_id:
            if not ctx.peer_id or match.peer_id != ctx.peer_id:
                return None
            matched_fields.append("peer_id")
            return (RouteTier.EXACT_PEER, matched_fields)

        # Check parent_peer_id
        if match.parent_peer_id:
            if not ctx.parent_peer_id or match.parent_peer_id != ctx.parent_peer_id:
                return None
            matched_fields.append("parent_peer_id")
            return (RouteTier.PARENT_PEER, matched_fields)

        # Check guild_id / team_id
        if match.guild_id:
            if not ctx.guild_id or match.guild_id != ctx.guild_id:
                return None
            matched_fields.append("guild_id")
            return (RouteTier.GUILD_TEAM, matched_fields)

        if match.team_id:
            if not ctx.team_id or match.team_id != ctx.team_id:
                return None
            matched_fields.append("team_id")
            return (RouteTier.GUILD_TEAM, matched_fields)

        # If account matched but nothing more specific
        if account_matched:
            return (RouteTier.ACCOUNT, matched_fields)

        # Only channel matched
        return (RouteTier.CHANNEL, matched_fields)

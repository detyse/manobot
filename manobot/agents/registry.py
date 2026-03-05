"""Agent registry for tracking and managing agent instances.

This module provides a centralized registry for agent metadata,
running status, and lifecycle management.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    pass


class AgentStatus(Enum):
    """Agent lifecycle status."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentInfo:
    """Runtime information about an agent."""

    agent_id: str
    name: str | None = None
    status: AgentStatus = AgentStatus.IDLE
    model: str | None = None
    workspace: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime | None = None
    message_count: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """Central registry for managing agent instances.

    Tracks agent metadata, status, and provides lookup functionality.
    Thread-safe for concurrent access.
    """

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        agent_id: str,
        name: str | None = None,
        model: str | None = None,
        workspace: str | None = None,
        **metadata: Any,
    ) -> AgentInfo:
        """Register a new agent or update existing registration.

        Args:
            agent_id: Unique agent identifier
            name: Display name
            model: LLM model being used
            workspace: Workspace directory path
            **metadata: Additional metadata

        Returns:
            AgentInfo for the registered agent
        """
        async with self._lock:
            if agent_id in self._agents:
                # Update existing
                info = self._agents[agent_id]
                if name:
                    info.name = name
                if model:
                    info.model = model
                if workspace:
                    info.workspace = workspace
                info.metadata.update(metadata)
                logger.debug("Updated agent registration: {}", agent_id)
            else:
                # Create new
                info = AgentInfo(
                    agent_id=agent_id,
                    name=name,
                    model=model,
                    workspace=workspace,
                    metadata=metadata,
                )
                self._agents[agent_id] = info
                logger.info("Registered agent: {} ({})", agent_id, name or "unnamed")

            return info

    async def unregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Args:
            agent_id: Agent ID to remove

        Returns:
            True if agent was removed, False if not found
        """
        async with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                logger.info("Unregistered agent: {}", agent_id)
                return True
            return False

    async def get(self, agent_id: str) -> AgentInfo | None:
        """Get agent info by ID.

        Args:
            agent_id: Agent ID to look up

        Returns:
            AgentInfo or None if not found
        """
        async with self._lock:
            return self._agents.get(agent_id)

    async def list_all(self) -> list[AgentInfo]:
        """List all registered agents.

        Returns:
            List of all AgentInfo objects
        """
        async with self._lock:
            return list(self._agents.values())

    async def list_by_status(self, status: AgentStatus) -> list[AgentInfo]:
        """List agents with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of matching AgentInfo objects
        """
        async with self._lock:
            return [a for a in self._agents.values() if a.status == status]

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus,
        error_message: str | None = None,
    ) -> bool:
        """Update an agent's status.

        Args:
            agent_id: Agent ID
            status: New status
            error_message: Error message if status is ERROR

        Returns:
            True if updated, False if agent not found
        """
        async with self._lock:
            if agent_id not in self._agents:
                return False

            info = self._agents[agent_id]
            info.status = status
            info.error_message = error_message

            if status == AgentStatus.RUNNING:
                info.last_active = datetime.now()

            logger.debug("Agent {} status: {}", agent_id, status.value)
            return True

    async def record_activity(self, agent_id: str) -> bool:
        """Record agent activity (message processed).

        Args:
            agent_id: Agent ID

        Returns:
            True if recorded, False if agent not found
        """
        async with self._lock:
            if agent_id not in self._agents:
                return False

            info = self._agents[agent_id]
            info.last_active = datetime.now()
            info.message_count += 1
            return True

    def get_sync(self, agent_id: str) -> AgentInfo | None:
        """Synchronous get for non-async contexts.

        Args:
            agent_id: Agent ID to look up

        Returns:
            AgentInfo or None if not found
        """
        return self._agents.get(agent_id)

    def list_all_sync(self) -> list[AgentInfo]:
        """Synchronous list for non-async contexts.

        Returns:
            List of all AgentInfo objects
        """
        return list(self._agents.values())

    def count(self) -> int:
        """Get the number of registered agents.

        Returns:
            Number of agents in registry
        """
        return len(self._agents)


# Global registry instance
_global_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry instance.

    Returns:
        Global AgentRegistry singleton
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry()
    return _global_registry

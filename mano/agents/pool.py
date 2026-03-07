"""Agent pool for managing multiple agent instances.

This module provides a pool manager that creates, caches, and routes
messages to the appropriate agent based on configuration.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

from loguru import logger

from manobot.agents.registry import AgentStatus, get_registry
from manobot.agents.scope import (
    build_agent_scope,
    list_agent_ids,
    normalize_agent_id,
    resolve_fallback_agent_id,
)
from manobot.agents.scope_model import AgentScope

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.memory import MemoryStore
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import SessionManager


class AgentPool:
    """Pool manager for multiple agent instances.

    Creates and manages AgentLoop instances on demand, routing messages
    to the appropriate agent based on bindings configuration.
    """

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        provider_factory: Callable[..., LLMProvider],
        cron_service: CronService | None = None,
    ):
        """Initialize the agent pool.

        Args:
            config: Application configuration
            bus: Message bus for agent communication
            provider_factory: Factory function to create LLM providers
            cron_service: Optional cron service for scheduled tasks
        """
        self.config = config
        self.bus = bus
        self.provider_factory = provider_factory
        self.cron_service = cron_service
        self.registry = get_registry()

        self._agents: dict[str, AgentLoop] = {}
        self._scopes: dict[str, AgentScope] = {}
        self._session_managers: dict[str, SessionManager] = {}
        self._memory_stores: dict[str, MemoryStore] = {}
        self._lock = asyncio.Lock()

        self._fallback_agent_id = resolve_fallback_agent_id(config)
        logger.info("Agent pool initialized, fallback agent: {}", self._fallback_agent_id)

    @property
    def default_agent_id(self) -> str:
        """Get the fallback (default) agent ID."""
        return self._fallback_agent_id

    @property
    def fallback_agent_id(self) -> str:
        """Get the fallback agent ID."""
        return self._fallback_agent_id

    def get_scope(self, agent_id: str) -> AgentScope | None:
        """Get the cached AgentScope for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            AgentScope or None if not yet created
        """
        return self._scopes.get(normalize_agent_id(agent_id))

    async def get_or_create_agent(self, agent_id: str) -> AgentLoop:
        """Get an existing agent or create a new one.

        Only agents defined in the configuration (or the fallback agent)
        will be created.  If *agent_id* is unknown, a warning is logged
        and the fallback agent is returned instead — this prevents typos
        in bindings from silently spawning "ghost" agents with default
        config and isolated workspaces.

        Args:
            agent_id: Agent ID to get or create

        Returns:
            AgentLoop instance for the agent
        """
        normalized_id = normalize_agent_id(agent_id)

        async with self._lock:
            if normalized_id in self._agents:
                return self._agents[normalized_id]

            # Guard: refuse to auto-create agents not present in config
            configured_ids = set(normalize_agent_id(i) for i in list_agent_ids(self.config))
            if normalized_id not in configured_ids:
                logger.warning(
                    "Agent '{}' is not defined in config — routing to fallback agent '{}'. "
                    "Check your bindings for typos.",
                    normalized_id,
                    self._fallback_agent_id,
                )
                # Ensure the fallback agent exists, then return it
                if self._fallback_agent_id not in self._agents:
                    agent = await self._create_agent(self._fallback_agent_id)
                    self._agents[self._fallback_agent_id] = agent
                return self._agents[self._fallback_agent_id]

            agent = await self._create_agent(normalized_id)
            self._agents[normalized_id] = agent
            return agent

    async def _create_agent(self, agent_id: str) -> AgentLoop:
        """Create a new agent instance from its AgentScope.

        Args:
            agent_id: Agent ID

        Returns:
            New AgentLoop instance
        """
        from nanobot.agent.loop import AgentLoop
        from nanobot.agent.memory import MemoryStore
        from nanobot.session.manager import SessionManager

        # Build scope (single source of truth)
        scope = build_agent_scope(self.config, agent_id)
        if not scope:
            # Fallback: build minimal scope from defaults
            scope = build_agent_scope(self.config, self._fallback_agent_id)
            if not scope:
                raise RuntimeError(f"Cannot resolve scope for agent '{agent_id}' or fallback")

        self._scopes[scope.agent_id] = scope

        # Ensure directories exist
        scope.workspace.mkdir(parents=True, exist_ok=True)
        scope.memory_dir.mkdir(parents=True, exist_ok=True)
        scope.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Create session manager for this agent
        session_manager = SessionManager(scope.workspace)
        # Override sessions dir to agent-specific location
        session_manager.sessions_dir = scope.sessions_dir
        self._session_managers[scope.agent_id] = session_manager

        # Create memory store for this agent with isolated memory directory
        memory_store = MemoryStore(scope.workspace, memory_dir=scope.memory_dir)
        self._memory_stores[scope.agent_id] = memory_store

        # Create provider (respect agent-level provider override)
        provider = self.provider_factory(scope.model, provider_override=scope.provider)

        # Create agent loop with agent-specific memory store
        agent = AgentLoop(
            bus=self.bus,
            provider=provider,
            workspace=scope.workspace,
            model=scope.model,
            temperature=scope.temperature,
            max_tokens=scope.max_tokens,
            max_iterations=scope.max_tool_iterations,
            memory_window=scope.memory_window,
            reasoning_effort=scope.reasoning_effort,
            brave_api_key=self.config.tools.web.search.api_key or None,
            web_proxy=self.config.tools.web.proxy or None,
            exec_config=self.config.tools.exec,
            restrict_to_workspace=self.config.tools.restrict_to_workspace,
            session_manager=session_manager,
            mcp_servers=self.config.tools.mcp_servers,
            channels_config=self.config.channels,
            memory_store=memory_store,
            cron_service=self.cron_service,
        )

        # Register in global registry
        await self.registry.register(
            agent_id=scope.agent_id,
            name=scope.name,
            model=scope.model,
            workspace=str(scope.workspace),
        )
        await self.registry.update_status(scope.agent_id, AgentStatus.RUNNING)

        logger.info(
            "Created agent: {} (model={}, workspace={})",
            scope.agent_id,
            scope.model,
            scope.workspace,
        )

        return agent

    def get_agent_sync(self, agent_id: str) -> AgentLoop | None:
        """Synchronously get an agent if it exists.

        Args:
            agent_id: Agent ID

        Returns:
            AgentLoop instance or None
        """
        normalized_id = normalize_agent_id(agent_id)
        return self._agents.get(normalized_id)

    def get_session_manager(self, agent_id: str) -> SessionManager | None:
        """Get the session manager for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            SessionManager or None
        """
        normalized_id = normalize_agent_id(agent_id)
        return self._session_managers.get(normalized_id)

    def get_memory_store(self, agent_id: str) -> MemoryStore | None:
        """Get the memory store for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            MemoryStore or None
        """
        normalized_id = normalize_agent_id(agent_id)
        return self._memory_stores.get(normalized_id)

    def list_active_agents(self) -> list[str]:
        """List all active agent IDs.

        Returns:
            List of active agent IDs
        """
        return list(self._agents.keys())

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop and remove an agent from the pool.

        Args:
            agent_id: Agent ID to stop

        Returns:
            True if stopped, False if not found
        """
        normalized_id = normalize_agent_id(agent_id)

        async with self._lock:
            if normalized_id not in self._agents:
                return False

            agent = self._agents.pop(normalized_id)
            agent.stop()
            await agent.close_mcp()

            # Clean up associated resources
            self._session_managers.pop(normalized_id, None)
            self._memory_stores.pop(normalized_id, None)

            # Update registry
            await self.registry.update_status(normalized_id, AgentStatus.STOPPED)

            logger.info("Stopped agent: {}", normalized_id)
            return True

    async def stop_all(self) -> None:
        """Stop all agents in the pool."""
        agent_ids = list(self._agents.keys())
        for agent_id in agent_ids:
            await self.stop_agent(agent_id)
        logger.info("All agents stopped")

    async def initialize_configured_agents(self) -> None:
        """Pre-initialize all agents defined in configuration.

        This creates agent instances for all configured agents at startup.
        """
        agent_ids = list_agent_ids(self.config)

        for agent_id in agent_ids:
            try:
                await self.get_or_create_agent(agent_id)
            except Exception as e:
                logger.error("Failed to initialize agent {}: {}", agent_id, e)
                await self.registry.update_status(
                    agent_id,
                    AgentStatus.ERROR,
                    str(e),
                )

        logger.info("Initialized {} configured agents", len(agent_ids))

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
    list_agent_ids,
    normalize_agent_id,
    resolve_agent_config,
    resolve_agent_memory_dir,
    resolve_agent_sessions_dir,
    resolve_agent_workspace,
    resolve_default_agent_id,
)

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
        self._session_managers: dict[str, SessionManager] = {}
        self._memory_stores: dict[str, MemoryStore] = {}
        self._lock = asyncio.Lock()

        self._default_agent_id = resolve_default_agent_id(config)
        logger.info("Agent pool initialized, default agent: {}", self._default_agent_id)

    @property
    def default_agent_id(self) -> str:
        """Get the default agent ID."""
        return self._default_agent_id

    async def get_or_create_agent(self, agent_id: str) -> AgentLoop:
        """Get an existing agent or create a new one.

        Only agents defined in the configuration (or the default agent)
        will be created.  If *agent_id* is unknown, a warning is logged
        and the default agent is returned instead — this prevents typos
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
                    "Agent '{}' is not defined in config — routing to default agent '{}'. "
                    "Check your bindings for typos.",
                    normalized_id,
                    self._default_agent_id,
                )
                # Ensure the default agent exists, then return it
                if self._default_agent_id not in self._agents:
                    agent = await self._create_agent(self._default_agent_id)
                    self._agents[self._default_agent_id] = agent
                return self._agents[self._default_agent_id]

            agent = await self._create_agent(normalized_id)
            self._agents[normalized_id] = agent
            return agent

    async def _create_agent(self, agent_id: str) -> AgentLoop:
        """Create a new agent instance.

        Args:
            agent_id: Agent ID

        Returns:
            New AgentLoop instance
        """
        from nanobot.agent.loop import AgentLoop
        from nanobot.agent.memory import MemoryStore
        from nanobot.session.manager import SessionManager

        # Resolve agent configuration
        agent_config = resolve_agent_config(self.config, agent_id)
        if not agent_config:
            # Use defaults for unknown agents
            agent_config = {
                "id": agent_id,
                "model": self.config.agents.defaults.model,
                "workspace": str(resolve_agent_workspace(self.config, agent_id)),
                "max_tokens": self.config.agents.defaults.max_tokens,
                "temperature": self.config.agents.defaults.temperature,
            }

        # Setup paths
        workspace = resolve_agent_workspace(self.config, agent_id)
        memory_dir = resolve_agent_memory_dir(self.config, agent_id)
        sessions_dir = resolve_agent_sessions_dir(self.config, agent_id)

        # Ensure directories exist
        workspace.mkdir(parents=True, exist_ok=True)
        memory_dir.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Create session manager for this agent
        session_manager = SessionManager(workspace)
        # Override sessions dir to agent-specific location
        session_manager.sessions_dir = sessions_dir
        self._session_managers[agent_id] = session_manager

        # Create memory store for this agent with isolated memory directory
        memory_store = MemoryStore(workspace, memory_dir=memory_dir)
        self._memory_stores[agent_id] = memory_store

        # Get model and create provider (respect agent-level provider override)
        model = agent_config.get("model") or self.config.agents.defaults.model
        provider_name = agent_config.get("provider")
        provider = self.provider_factory(model, provider_override=provider_name)

        # Create agent loop with agent-specific memory store
        agent = AgentLoop(
            bus=self.bus,
            provider=provider,
            workspace=workspace,
            model=model,
            temperature=agent_config.get("temperature", self.config.agents.defaults.temperature),
            max_tokens=agent_config.get("max_tokens", self.config.agents.defaults.max_tokens),
            max_iterations=self.config.agents.defaults.max_tool_iterations,
            memory_window=self.config.agents.defaults.memory_window,
            reasoning_effort=self.config.agents.defaults.reasoning_effort,
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
            agent_id=agent_id,
            name=agent_config.get("name"),
            model=model,
            workspace=str(workspace),
        )
        await self.registry.update_status(agent_id, AgentStatus.RUNNING)

        logger.info(
            "Created agent: {} (model={}, workspace={})",
            agent_id,
            model,
            workspace,
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

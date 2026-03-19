"""Health monitor — watches agent subprocesses and auto-restarts failures.

Runs as a background task in the supervisor process, periodically polling
each agent's /api/health endpoint.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from mano.core.process_manager import ProcessManager

# Backoff parameters
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0
_BACKOFF_FACTOR = 2.0
_MAX_RESTART_ATTEMPTS = 5


class HealthMonitor:
    """Periodically checks agent health and restarts crashed agents."""

    def __init__(
        self,
        manager: ProcessManager,
        check_interval: float = 10.0,
    ):
        self.manager = manager
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._restart_counts: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}

    async def start(self) -> None:
        """Start the health monitor loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Health monitor started (interval={}s)", self.check_interval)

    def stop(self) -> None:
        """Stop the health monitor."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("Health monitor stopped")

    async def _loop(self) -> None:
        """Main monitoring loop."""
        try:
            while True:
                await asyncio.sleep(self.check_interval)
                await self._check_all()
        except asyncio.CancelledError:
            pass

    async def _check_all(self) -> None:
        """Check health of all agents that should be running."""
        state = self.manager._state
        now = asyncio.get_event_loop().time()

        for agent_id, agent_state in list(state.agents.items()):
            if agent_state.status != "running":
                continue

            # Skip if in backoff period
            backoff_until = self._backoff_until.get(agent_id, 0)
            if now < backoff_until:
                continue

            healthy = await self._check_one(agent_id, agent_state.port)
            if not healthy:
                await self._handle_failure(agent_id)

    async def _check_one(self, agent_id: str, port: int) -> bool:
        """Check if a single agent is healthy."""
        url = f"http://127.0.0.1:{port}/api/health"
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    # Reset restart count on successful health check
                    self._restart_counts.pop(agent_id, None)
                    self._backoff_until.pop(agent_id, None)
                    return True
        except Exception:
            pass
        return False

    async def _handle_failure(self, agent_id: str) -> None:
        """Handle a failed health check — restart with backoff."""
        count = self._restart_counts.get(agent_id, 0) + 1
        self._restart_counts[agent_id] = count

        if count > _MAX_RESTART_ATTEMPTS:
            logger.error(
                "Agent '{}' exceeded max restart attempts ({}), giving up",
                agent_id,
                _MAX_RESTART_ATTEMPTS,
            )
            # Mark as crashed in state
            agent_state = self.manager._state.agents.get(agent_id)
            if agent_state:
                agent_state.status = "crashed"
                agent_state.error_message = f"Exceeded {_MAX_RESTART_ATTEMPTS} restart attempts"
                from mano.core.state import save_state
                save_state(self.manager._state)
            return

        # Calculate backoff
        backoff = min(
            _INITIAL_BACKOFF_S * (_BACKOFF_FACTOR ** (count - 1)),
            _MAX_BACKOFF_S,
        )

        logger.warning(
            "Agent '{}' unhealthy, restarting (attempt {}/{}, backoff={:.1f}s)",
            agent_id,
            count,
            _MAX_RESTART_ATTEMPTS,
            backoff,
        )

        # Set backoff deadline
        now = asyncio.get_event_loop().time()
        self._backoff_until[agent_id] = now + backoff

        try:
            await self.manager.restart_agent(agent_id)
        except Exception as e:
            logger.error("Failed to restart agent '{}': {}", agent_id, e)

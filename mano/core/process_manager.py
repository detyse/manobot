"""Process manager — spawns and manages agent subprocesses.

Replaces the old in-process AgentPool with true subprocess isolation.
Each agent runs as ``python -m mano.core.runner`` with its own config.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from mano.core.config_gen import generate_agent_config
from mano.core.scope import list_agent_ids, normalize_agent_id
from mano.core.state import (
    AgentProcessState,
    cleanup_stale,
    load_state,
    save_state,
)

if TYPE_CHECKING:
    from agent.config.schema import Config


def _port_in_use(port: int) -> bool:
    """Check if a TCP port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class ProcessManager:
    """Manages agent subprocesses."""

    def __init__(self, config: Config, base_port: int = 18791):
        self.config = config
        self.base_port = base_port
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._state = load_state()
        cleanup_stale(self._state)

    def _allocate_port(self, agent_id: str) -> int:
        """Allocate an available port for an agent.

        Re-uses the previously assigned port if still free, otherwise
        scans from base_port upward.
        """
        # Re-use existing port if available
        existing = self._state.agents.get(agent_id)
        if existing and not _port_in_use(existing.port):
            return existing.port

        # Find next free port
        used_ports = {a.port for a in self._state.agents.values()}
        port = self.base_port
        while port < self.base_port + 100:
            if port not in used_ports and not _port_in_use(port):
                return port
            port += 1

        raise RuntimeError(f"No available port in range {self.base_port}-{self.base_port + 99}")

    async def start_agent(self, agent_id: str) -> AgentProcessState:
        """Start a single agent subprocess."""
        agent_id = normalize_agent_id(agent_id)

        # Check if already running
        existing = self._state.agents.get(agent_id)
        if existing and existing.status == "running":
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.get(f"http://127.0.0.1:{existing.port}/api/health")
                    if resp.status_code == 200:
                        logger.info("Agent '{}' already running on port {}", agent_id, existing.port)
                        return existing
            except Exception:
                pass  # Not actually running, continue with start

        # Generate per-agent config
        config_path = generate_agent_config(self.config, agent_id)

        # Allocate port
        port = self._allocate_port(agent_id)

        # Spawn subprocess
        cmd = [
            sys.executable, "-m", "mano.core.runner",
            "--agent-id", agent_id,
            "--port", str(port),
            "--config", str(config_path),
        ]

        logger.info("Starting agent '{}' on port {}...", agent_id, port)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "MANOBOT_AGENT_ID": agent_id, "MANOBOT_AGENT_PORT": str(port)},
        )

        self._processes[agent_id] = process

        # Update state
        state_entry = AgentProcessState(
            agent_id=agent_id,
            pid=process.pid,
            port=port,
            status="starting",
            config_path=str(config_path),
        )
        self._state.agents[agent_id] = state_entry
        save_state(self._state)

        # Wait for health check
        healthy = await self._wait_for_health(agent_id, port, timeout=30)
        if healthy:
            state_entry.status = "running"
            logger.info("Agent '{}' started (pid={}, port={})", agent_id, process.pid, port)
        else:
            state_entry.status = "crashed"
            state_entry.error_message = "Health check timeout"
            logger.error("Agent '{}' failed to start (health check timeout)", agent_id)

        save_state(self._state)

        # Launch background watcher for restart-on-exit-code-75
        asyncio.create_task(self._watch_subprocess(agent_id, process))

        return state_entry

    async def _watch_subprocess(self, agent_id: str, process) -> None:
        """Monitor subprocess; auto-restart on exit code 75 (restart requested)."""
        exit_code = await process.wait()
        if exit_code == 75:
            logger.info("Agent '{}' requested restart (exit code 75)", agent_id)
            state = self._state.agents.get(agent_id)
            if state:
                state.status = "stopped"
                save_state(self._state)
            self._processes.pop(agent_id, None)
            await self.start_agent(agent_id)
        elif exit_code not in (0, None):
            logger.warning("Agent '{}' exited with code {}", agent_id, exit_code)

    async def _wait_for_health(self, agent_id: str, port: int, timeout: float = 30) -> bool:
        """Poll /api/health until success or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        url = f"http://127.0.0.1:{port}/api/health"

        while asyncio.get_event_loop().time() < deadline:
            # Check if process died
            proc = self._processes.get(agent_id)
            if proc and proc.returncode is not None:
                return False

            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
            except Exception:
                pass

            await asyncio.sleep(0.5)

        return False

    async def stop_agent(self, agent_id: str, timeout: float = 10) -> bool:
        """Stop an agent subprocess gracefully."""
        agent_id = normalize_agent_id(agent_id)
        state_entry = self._state.agents.get(agent_id)
        if not state_entry:
            return False

        state_entry.status = "stopping"
        save_state(self._state)

        # Try HTTP stop first
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(f"http://127.0.0.1:{state_entry.port}/api/stop")
        except Exception:
            pass

        # Wait for process to exit
        proc = self._processes.get(agent_id)
        if proc:
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Agent '{}' did not stop gracefully, terminating", agent_id)
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()

            self._processes.pop(agent_id, None)
        elif state_entry.pid:
            # No local proc handle (e.g. CLI invoked separately from supervisor).
            # Poll the recorded PID to confirm the process actually exited.
            exited = await self._wait_for_pid_exit(state_entry.pid, timeout=timeout)
            if not exited:
                try:
                    os.kill(state_entry.pid, 15)  # SIGTERM
                except OSError:
                    pass  # Already gone
                exited = await self._wait_for_pid_exit(state_entry.pid, timeout=5)
                if not exited:
                    logger.warning(
                        "Agent '{}' (pid={}) did not exit after SIGTERM",
                        agent_id,
                        state_entry.pid,
                    )

        state_entry.status = "stopped"
        save_state(self._state)
        logger.info("Agent '{}' stopped", agent_id)
        return True

    @staticmethod
    async def _wait_for_pid_exit(pid: int, timeout: float = 10) -> bool:
        """Poll os.kill(pid, 0) until the process is gone or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            await asyncio.sleep(0.3)
        return False

    async def restart_agent(self, agent_id: str) -> AgentProcessState:
        """Restart an agent subprocess."""
        await self.stop_agent(agent_id)
        return await self.start_agent(agent_id)

    async def start_all(self) -> dict[str, AgentProcessState]:
        """Start all configured agents in parallel."""
        agent_ids = list_agent_ids(self.config)
        tasks = [self.start_agent(aid) for aid in agent_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        started: dict[str, AgentProcessState] = {}
        for aid, result in zip(agent_ids, results):
            if isinstance(result, Exception):
                logger.error("Failed to start agent '{}': {}", aid, result)
            else:
                started[aid] = result
        return started

    async def stop_all(self, timeout: float = 15) -> None:
        """Stop all running agents in parallel."""
        running = [
            aid for aid, s in self._state.agents.items() if s.status in ("running", "starting")
        ]
        if not running:
            return

        tasks = [self.stop_agent(aid, timeout=timeout) for aid in running]
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_agent_url(self, agent_id: str) -> str | None:
        """Get the HTTP URL for a running agent."""
        agent_id = normalize_agent_id(agent_id)
        state_entry = self._state.agents.get(agent_id)
        if state_entry and state_entry.status == "running":
            return f"http://127.0.0.1:{state_entry.port}"
        return None

    def get_status(self) -> dict[str, AgentProcessState]:
        """Get current state of all agents (refreshed from state file)."""
        self._state = load_state()
        cleanup_stale(self._state)
        save_state(self._state)
        return dict(self._state.agents)

    def set_supervisor_pid(self) -> None:
        """Record the current process as the supervisor."""
        self._state.supervisor_pid = os.getpid()
        save_state(self._state)

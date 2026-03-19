"""Process state persistence for manobot.

Tracks agent subprocess metadata (PID, port, status) in a JSON file
so that CLI commands can query process state without the supervisor.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


def _get_state_path() -> Path:
    """Get the default state file path."""
    return Path.home() / ".manobot" / "state" / "processes.json"


@dataclass
class AgentProcessState:
    """Runtime state of a single agent subprocess."""

    agent_id: str
    pid: int
    port: int
    status: str = "starting"  # starting | running | stopping | stopped | crashed
    started_at: str = ""  # ISO format
    config_path: str = ""
    restart_count: int = 0
    error_message: str | None = None

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


@dataclass
class StateFile:
    """Top-level state file for all agent processes."""

    version: int = 1
    updated_at: str = ""
    supervisor_pid: int | None = None
    agents: dict[str, AgentProcessState] = field(default_factory=dict)


def _pid_exists(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True  # exists but we can't signal it
    except OSError:
        return False


def load_state(path: Path | None = None) -> StateFile:
    """Load process state from disk.

    Returns an empty StateFile if the file doesn't exist or is corrupted.
    """
    state_path = path or _get_state_path()

    if not state_path.exists():
        return StateFile()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        agents = {}
        for agent_id, agent_data in data.get("agents", {}).items():
            agents[agent_id] = AgentProcessState(**agent_data)
        return StateFile(
            version=data.get("version", 1),
            updated_at=data.get("updated_at", ""),
            supervisor_pid=data.get("supervisor_pid"),
            agents=agents,
        )
    except Exception as e:
        logger.warning("Failed to load state file, starting fresh: {}", e)
        return StateFile()


def save_state(state: StateFile, path: Path | None = None) -> None:
    """Atomically write state to disk (write tmp + rename)."""
    state_path = path or _get_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state.updated_at = datetime.now(timezone.utc).isoformat()

    data: dict[str, Any] = {
        "version": state.version,
        "updated_at": state.updated_at,
        "supervisor_pid": state.supervisor_pid,
        "agents": {aid: asdict(s) for aid, s in state.agents.items()},
    }

    # Atomic write: tmp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(state_path.parent), suffix=".tmp", prefix="state_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(state_path))
    except Exception:
        # Clean up tmp on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update_agent_state(
    agent_id: str, path: Path | None = None, **fields: Any
) -> None:
    """Convenience: update specific fields of one agent's state."""
    state = load_state(path)
    if agent_id not in state.agents:
        return
    agent = state.agents[agent_id]
    for key, value in fields.items():
        if hasattr(agent, key):
            setattr(agent, key, value)
    save_state(state, path)


def remove_agent_state(agent_id: str, path: Path | None = None) -> None:
    """Remove an agent from the state file."""
    state = load_state(path)
    if agent_id in state.agents:
        del state.agents[agent_id]
        save_state(state, path)


def cleanup_stale(state: StateFile) -> StateFile:
    """Mark agents whose PID no longer exists as crashed."""
    for agent_id, agent in list(state.agents.items()):
        if agent.status in ("running", "starting"):
            if not _pid_exists(agent.pid):
                logger.warning(
                    "Agent '{}' (pid={}) is no longer alive, marking as crashed",
                    agent_id,
                    agent.pid,
                )
                agent.status = "crashed"
                agent.error_message = "Process disappeared"

    # Check supervisor
    if state.supervisor_pid and not _pid_exists(state.supervisor_pid):
        state.supervisor_pid = None

    return state


def is_supervisor_alive(path: Path | None = None) -> bool:
    """Check if the supervisor process is running."""
    state = load_state(path)
    if state.supervisor_pid is None:
        return False
    return _pid_exists(state.supervisor_pid)

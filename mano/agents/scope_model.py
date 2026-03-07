"""AgentScope model — single source of truth for an agent's full configuration.

An AgentScope represents a complete, isolated agent boundary: all paths,
model settings, and extension config merged from defaults + per-agent overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from agent.config.schema import IdentityConfig, SubagentsConfig


class AgentScope(BaseModel):
    """Complete resolved scope for a single agent."""

    # Identity
    agent_id: str
    name: str | None = None
    is_fallback: bool = False

    # Paths (all fully resolved)
    workspace: Path
    agent_dir: Path  # ~/.manobot/agents/{id}/
    sessions_dir: Path
    memory_dir: Path
    skills_dir: Path | None = None

    # Model config (merged with defaults)
    model: str
    provider: str
    max_tokens: int
    temperature: float
    max_tool_iterations: int
    memory_window: int
    reasoning_effort: str | None = None

    # Extensions
    skills: list[str] | None = None
    identity: dict[str, Any] | None = None
    subagents: dict[str, Any] | None = None

    class Config:
        arbitrary_types_allowed = True

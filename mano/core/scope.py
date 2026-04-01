"""Simplified agent scope and session helpers.

`mano.core` is the single source of truth for multi-agent configuration
resolution. Older `mano.agents.*` and `mano.sessions.*` modules should
delegate here instead of carrying parallel implementations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from agent.config.schema import AgentEntryConfig, ChannelsConfig, Config, ProvidersConfig


DEFAULT_AGENT_ID = "default"
_default_warned = False


@dataclass
class AgentScope:
    """Complete resolved configuration for a single agent."""

    agent_id: str
    name: str | None
    is_default: bool
    workspace: Path
    agent_dir: Path
    sessions_dir: Path
    memory_dir: Path
    model: str
    provider: str
    max_tokens: int
    context_window_tokens: int
    temperature: float
    max_tool_iterations: int
    timezone: str | None = None
    reasoning_effort: str | None = None
    skills_dir: Path | None = None
    skills: list[str] | None = None
    identity: dict[str, Any] | None = None
    subagents: dict[str, Any] | None = None


def normalize_agent_id(agent_id: str | None) -> str:
    """Normalize agent IDs to lowercase slugs."""
    if not agent_id:
        return DEFAULT_AGENT_ID
    normalized = re.sub(r"[^a-z0-9-]", "-", agent_id.lower().strip())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or DEFAULT_AGENT_ID


def list_agent_entries(config: Config) -> list[AgentEntryConfig]:
    """List explicit agent entries from config."""
    return [entry for entry in config.agents.agent_list if entry and entry.id]


def list_agent_ids(config: Config) -> list[str]:
    """List normalized configured agent IDs."""
    entries = list_agent_entries(config)
    if not entries:
        return [DEFAULT_AGENT_ID]

    seen: set[str] = set()
    agent_ids: list[str] = []
    for entry in entries:
        agent_id = normalize_agent_id(entry.id)
        if agent_id not in seen:
            seen.add(agent_id)
            agent_ids.append(agent_id)
    return agent_ids or [DEFAULT_AGENT_ID]


def resolve_default_agent_id(config: Config) -> str:
    """Resolve the default agent ID."""
    global _default_warned

    entries = list_agent_entries(config)
    if not entries:
        return DEFAULT_AGENT_ID

    defaults = [entry for entry in entries if entry.default]
    if len(defaults) > 1 and not _default_warned:
        _default_warned = True
        logger.warning("Multiple agents marked default=true; using the first entry.")

    chosen = defaults[0] if defaults else entries[0]
    return normalize_agent_id(chosen.id)


def resolve_agent_entry(config: Config, agent_id: str) -> AgentEntryConfig | None:
    """Resolve one configured agent entry."""
    normalized = normalize_agent_id(agent_id)
    for entry in list_agent_entries(config):
        if normalize_agent_id(entry.id) == normalized:
            return entry
    return None


def resolve_agent_channels(config: Config, agent_id: str) -> ChannelsConfig:
    """Return the per-agent channels config, falling back to global."""
    entry = resolve_agent_entry(config, agent_id)
    if entry and entry.channels is not None:
        return entry.channels
    return config.channels


def resolve_agent_providers(config: Config, agent_id: str) -> ProvidersConfig:
    """Return the per-agent providers config, falling back to global."""
    entry = resolve_agent_entry(config, agent_id)
    if entry and entry.providers is not None:
        return entry.providers
    return config.providers


def _get_state_dir() -> Path:
    """Return the manobot state directory."""
    return Path.home() / ".manobot"


def build_agent_scope(config: Config, agent_id: str) -> AgentScope | None:
    """Build a resolved runtime scope for one agent."""
    normalized = normalize_agent_id(agent_id)
    entry = resolve_agent_entry(config, normalized)
    defaults = config.agents.defaults
    default_id = resolve_default_agent_id(config)
    state_dir = _get_state_dir()
    is_default = normalized == default_id

    if not entry:
        if not is_default:
            return None

        workspace = Path(defaults.workspace).expanduser()
        agent_dir = state_dir / "agents" / normalized
        return AgentScope(
            agent_id=normalized,
            name=None,
            is_default=True,
            workspace=workspace,
            agent_dir=agent_dir,
            sessions_dir=agent_dir / "sessions",
            memory_dir=agent_dir / "memory",
            model=defaults.model,
            provider=defaults.provider,
            max_tokens=defaults.max_tokens,
            context_window_tokens=defaults.context_window_tokens,
            temperature=defaults.temperature,
            max_tool_iterations=defaults.max_tool_iterations,
            timezone=defaults.timezone,
            memory_window=defaults.memory_window,
            reasoning_effort=defaults.reasoning_effort,
        )

    agent_dir = Path(entry.agent_dir).expanduser() if entry.agent_dir else state_dir / "agents" / normalized
    if entry.workspace:
        workspace = Path(entry.workspace).expanduser()
    elif is_default:
        workspace = Path(defaults.workspace).expanduser()
    else:
        workspace = agent_dir / "workspace"

    sessions_dir = (
        Path(entry.sessions_dir).expanduser() if entry.sessions_dir else agent_dir / "sessions"
    )
    memory_dir = Path(entry.memory_dir).expanduser() if entry.memory_dir else agent_dir / "memory"

    return AgentScope(
        agent_id=normalized,
        name=entry.name,
        is_default=is_default,
        workspace=workspace,
        agent_dir=agent_dir,
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        skills_dir=agent_dir / "skills",
        model=entry.model or defaults.model,
        provider=entry.provider or defaults.provider,
        max_tokens=entry.max_tokens if entry.max_tokens is not None else defaults.max_tokens,
        context_window_tokens=(
            entry.context_window_tokens
            if entry.context_window_tokens is not None
            else defaults.context_window_tokens
        ),
        temperature=entry.temperature if entry.temperature is not None else defaults.temperature,
        max_tool_iterations=(
            entry.max_tool_iterations
            if entry.max_tool_iterations is not None
            else defaults.max_tool_iterations
        ),
        timezone=entry.timezone or defaults.timezone,
        memory_window=defaults.memory_window,
        reasoning_effort=entry.reasoning_effort or defaults.reasoning_effort,
        skills=entry.skills,
        identity=entry.identity.model_dump() if entry.identity else None,
        subagents=entry.subagents.model_dump() if entry.subagents else None,
    )


def build_session_key(
    agent_id: str,
    channel: str,
    peer_id: str,
    account_id: str = "default",
    thread_id: str | None = None,
) -> str:
    """Build a deterministic multi-agent session key."""
    key = f"agent:{normalize_agent_id(agent_id)}:{account_id}:{channel}:{peer_id}"
    if thread_id:
        key = f"{key}:{thread_id}"
    return key


def parse_session_key(session_key: str) -> dict[str, str | None]:
    """Parse multi-agent and legacy session keys."""
    if session_key.startswith("agent:"):
        parts = session_key[len("agent:"):].split(":")
        if len(parts) >= 4:
            return {
                "agent_id": parts[0] or None,
                "account_id": parts[1],
                "channel": parts[2],
                "peer_id": parts[3],
                "thread_id": parts[4] if len(parts) > 4 else None,
            }
        if len(parts) == 3:
            return {
                "agent_id": parts[0] or None,
                "account_id": "default",
                "channel": parts[1],
                "peer_id": parts[2],
                "thread_id": None,
            }

    parts = session_key.split(":", 2)
    if len(parts) == 3:
        return {
            "agent_id": parts[0] or None,
            "account_id": "default",
            "channel": parts[1],
            "peer_id": parts[2],
            "thread_id": None,
        }
    if len(parts) == 2:
        return {
            "agent_id": None,
            "account_id": "default",
            "channel": parts[0],
            "peer_id": parts[1],
            "thread_id": None,
        }
    return {
        "agent_id": None,
        "account_id": "default",
        "channel": session_key,
        "peer_id": "",
        "thread_id": None,
    }

"""Per-agent config generator.

Generates a standalone agent-format config.json for each agent,
so it can run as an independent process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mano.core.scope import (
    build_agent_scope,
    list_agent_ids,
    resolve_agent_channels,
    resolve_agent_providers,
)

if TYPE_CHECKING:
    from agent.config.schema import Config


def _build_channels_dict(config: Config, agent_id: str) -> dict:
    """Build the channels section for one agent's config.

    If the agent has its own channels config, use it directly.
    Otherwise inherit the global channels config.
    """
    return resolve_agent_channels(config, agent_id).model_dump(by_alias=True)


def generate_agent_config(config: Config, agent_id: str) -> Path:
    """Generate a standalone agent config for one agent.

    Returns:
        Path to the generated config file.
    """
    scope = build_agent_scope(config, agent_id)
    if scope is None:
        raise ValueError(f"Agent '{agent_id}' is not configured")

    # Agent defaults from scope
    defaults = {
        "workspace": str(scope.workspace),
        "model": scope.model,
        "provider": scope.provider,
        "maxTokens": scope.max_tokens,
        "contextWindowTokens": scope.context_window_tokens,
        "temperature": scope.temperature,
        "maxToolIterations": scope.max_tool_iterations,
    }
    if scope.memory_window is not None:
        defaults["memoryWindow"] = scope.memory_window
    if scope.reasoning_effort:
        defaults["reasoningEffort"] = scope.reasoning_effort

    # Single-agent list with just this agent
    agent_entry: dict = {"id": scope.agent_id, "default": True}
    if scope.name:
        agent_entry["name"] = scope.name
    agent_entry["workspace"] = str(scope.workspace)
    agent_entry["agentDir"] = str(scope.agent_dir)
    agent_entry["sessionsDir"] = str(scope.sessions_dir)
    agent_entry["memoryDir"] = str(scope.memory_dir)
    agent_entry["provider"] = scope.provider
    agent_entry["maxTokens"] = scope.max_tokens
    agent_entry["contextWindowTokens"] = scope.context_window_tokens
    agent_entry["temperature"] = scope.temperature
    agent_entry["maxToolIterations"] = scope.max_tool_iterations
    if scope.reasoning_effort:
        agent_entry["reasoningEffort"] = scope.reasoning_effort

    # Pass through per-agent settings so the runtime can consume them
    if scope.skills is not None:
        agent_entry["skills"] = scope.skills
    if scope.identity:
        agent_entry["identity"] = scope.identity
    if scope.subagents:
        agent_entry["subagents"] = scope.subagents

    agents_section = {
        "defaults": defaults,
        "list": [agent_entry],
    }

    # Providers: per-agent or inherited from global
    providers = resolve_agent_providers(config, agent_id).model_dump(by_alias=True)

    # Channels: per-agent or inherited from global
    channels = _build_channels_dict(config, agent_id)

    # Tools: copy verbatim
    tools = config.tools.model_dump(by_alias=True)

    # Gateway: not used by runner but keep for compat
    gateway = config.gateway.model_dump(by_alias=True)

    config_data = {
        "agents": agents_section,
        "providers": providers,
        "channels": channels,
        "tools": tools,
        "gateway": gateway,
    }

    # Write to agent dir
    config_path = scope.agent_dir / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Generated config for agent '{}': {}", agent_id, config_path)
    return config_path


def generate_all_configs(config: Config) -> dict[str, Path]:
    """Generate configs for all configured agents.

    Returns:
        Dict mapping agent_id to config file path.
    """
    result: dict[str, Path] = {}
    for agent_id in list_agent_ids(config):
        try:
            result[agent_id] = generate_agent_config(config, agent_id)
        except Exception as e:
            logger.error("Failed to generate config for '{}': {}", agent_id, e)
    return result

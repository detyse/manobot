"""Agent-specific onboarding helpers for manobot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent.config.loader import load_config
from agent.config.schema import Config
from agent.utils.helpers import sync_workspace_templates
from mano.agents.registry import (
    get_agent_config_path,
    get_agent_root,
    get_registry_path,
    list_registered_agent_ids,
    register_agent,
    resolve_default_registered_agent_id,
    set_default_registered_agent,
    sync_agent_default_flags,
)
from mano.core.scope import build_agent_scope, normalize_agent_id


OnboardMode = Literal["refresh", "reset"]
OnboardAction = Literal["created", "refreshed", "reset"]


@dataclass
class AgentOnboardResult:
    """Result of onboarding one agent."""

    agent_id: str
    action: OnboardAction
    scope: Any
    registry_path: Path
    agent_config_path: Path
    templates_added: list[str]


def _default_config_data() -> dict[str, Any]:
    """Build a default config payload."""
    return Config().model_dump(by_alias=True)


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively merge missing default fields into existing config values."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing if existing is not None else defaults

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def inject_channel_plugin_defaults(config_path: Path) -> None:
    """Inject default config for all discovered channels into a config file."""
    from agent.channels.registry import discover_all

    if not config_path.exists():
        return

    all_channels = discover_all()
    if not all_channels:
        return

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    channels = data.setdefault("channels", {})
    for name, cls in all_channels.items():
        defaults = cls.default_config()
        if name not in channels:
            channels[name] = defaults
        else:
            channels[name] = _merge_missing_defaults(channels[name], defaults)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_config_data(config_path: Path) -> dict[str, Any]:
    """Load raw config JSON from disk."""
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _save_config_data(config_path: Path, config_data: dict[str, Any]) -> None:
    """Save raw config JSON to disk."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)


def _make_new_agent_base(agent_id: str) -> dict[str, Any]:
    """Create a new standalone config payload with agent-local defaults."""
    data = _default_config_data()
    agent_root = get_agent_root(agent_id)
    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(agent_root / "workspace")
    return data


def _find_source_agent_entry(config_data: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    """Resolve the source agent entry from a config payload."""
    agent_list = config_data.get("agents", {}).get("list", [])
    for entry in agent_list:
        if normalize_agent_id(entry.get("id")) == agent_id:
            return dict(entry)
    if len(agent_list) == 1:
        return dict(agent_list[0])
    return None


def _resolve_source_config_data(agent_id: str) -> dict[str, Any]:
    """Pick the best available source config for one agent."""
    local_config_path = get_agent_config_path(agent_id)
    if local_config_path.exists():
        return _load_config_data(local_config_path)
    return _make_new_agent_base(agent_id)


def _build_standalone_config_data(
    agent_id: str,
    source_data: dict[str, Any],
    *,
    workspace: str | None,
    mode: OnboardMode,
    name: str | None,
    model: str | None,
    is_default: bool,
) -> dict[str, Any]:
    """Build a standalone config payload for a single agent."""
    default_data = _default_config_data()
    config_data = _merge_missing_defaults(source_data, default_data)

    agent_root = get_agent_root(agent_id)
    source_entry = _find_source_agent_entry(config_data, agent_id)

    agents = config_data.setdefault("agents", {})
    defaults = agents.setdefault("defaults", default_data["agents"]["defaults"])
    if mode == "reset":
        defaults["workspace"] = str(agent_root / "workspace")

    if mode == "reset":
        entry: dict[str, Any] = {}
    else:
        entry = dict(source_entry or {})

    entry["id"] = agent_id
    entry["default"] = is_default
    entry["agentDir"] = str(agent_root)
    entry["sessionsDir"] = str(agent_root / "sessions")
    entry["memoryDir"] = str(agent_root / "memory")

    if mode == "reset":
        for key in (
            "name",
            "workspace",
            "model",
            "provider",
            "maxTokens",
            "contextWindowTokens",
            "temperature",
            "maxToolIterations",
            "reasoningEffort",
            "timezone",
            "skills",
            "identity",
            "subagents",
            "channels",
            "providers",
        ):
            entry.pop(key, None)

    if name is not None:
        entry["name"] = name

    if workspace is not None:
        entry["workspace"] = workspace

    if model is not None:
        entry["model"] = model

    runtime_defaults = {
        "workspace": entry.get("workspace") or defaults.get("workspace") or str(agent_root / "workspace"),
        "model": entry.get("model") or defaults.get("model"),
        "provider": entry.get("provider") or defaults.get("provider"),
        "maxTokens": entry.get("maxTokens", defaults.get("maxTokens")),
        "contextWindowTokens": entry.get("contextWindowTokens", defaults.get("contextWindowTokens")),
        "temperature": entry.get("temperature", defaults.get("temperature")),
        "maxToolIterations": entry.get("maxToolIterations", defaults.get("maxToolIterations")),
        "reasoningEffort": entry.get("reasoningEffort") or defaults.get("reasoningEffort"),
        "timezone": entry.get("timezone") or defaults.get("timezone"),
    }

    for key, value in runtime_defaults.items():
        if value is not None:
            defaults[key] = value

    if "workspace" not in entry:
        entry["workspace"] = defaults["workspace"]

    agents["list"] = [entry]
    return config_data


def _ensure_agent_directories(scope: Any) -> None:
    """Create the directory layout needed for one agent."""
    for path in (scope.agent_dir, scope.workspace, scope.memory_dir, scope.sessions_dir):
        path.mkdir(parents=True, exist_ok=True)


def onboard_agent(
    agent_id: str,
    *,
    workspace: str | None = None,
    mode: OnboardMode = "refresh",
    name: str | None = None,
    model: str | None = None,
    set_default: bool | None = None,
) -> AgentOnboardResult:
    """Initialize or refresh one fully independent manobot agent."""
    normalized_id = normalize_agent_id(agent_id)
    agent_config_path = get_agent_config_path(normalized_id)
    existing_local_config = agent_config_path.exists()
    existing_ids = set(list_registered_agent_ids())

    if set_default:
        set_default_registered_agent(normalized_id)
    else:
        register_agent(normalized_id, default=not existing_ids)

    is_default = resolve_default_registered_agent_id() == normalized_id
    source_data = _resolve_source_config_data(normalized_id)
    config_data = _build_standalone_config_data(
        normalized_id,
        source_data,
        workspace=workspace,
        mode=mode,
        name=name,
        model=model,
        is_default=is_default,
    )

    _save_config_data(agent_config_path, config_data)
    inject_channel_plugin_defaults(agent_config_path)
    sync_agent_default_flags()

    config = load_config(agent_config_path)
    scope = build_agent_scope(config, normalized_id)
    if scope is None:
        raise RuntimeError(f"Cannot resolve scope for agent '{normalized_id}'")

    _ensure_agent_directories(scope)
    templates_added = sync_workspace_templates(scope.workspace, silent=True)

    action: OnboardAction
    if not existing_local_config:
        action = "created"
    elif mode == "reset":
        action = "reset"
    else:
        action = "refreshed"

    return AgentOnboardResult(
        agent_id=normalized_id,
        action=action,
        scope=scope,
        registry_path=get_registry_path(),
        agent_config_path=agent_config_path,
        templates_added=templates_added,
    )

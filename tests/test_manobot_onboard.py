import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.config import loader as config_loader
from mano.cli.main import app

runner = CliRunner()


class _FakeChannel:
    @classmethod
    def default_config(cls):
        return {"enabled": False, "token": "fake-token"}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_loader, "_current_config_path", None)
    yield tmp_path
    monkeypatch.setattr(config_loader, "_current_config_path", None)


def _seed_registered_agent(
    isolated_home: Path,
    agent_id: str,
    *,
    default: bool = True,
    name: str | None = None,
    model: str | None = None,
    workspace: str | None = None,
    channels: dict | None = None,
) -> Path:
    registry_path = isolated_home / ".manobot" / "agents" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "defaultAgent": agent_id if default else None,
                "agents": [agent_id],
            }
        ),
        encoding="utf-8",
    )

    config_path = isolated_home / ".manobot" / "agents" / agent_id / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_data = {
        "agents": {
            "list": [
                {
                    "id": agent_id,
                    "default": default,
                }
            ]
        },
        "channels": channels or {},
    }
    if name is not None:
        config_data["agents"]["list"][0]["name"] = name
    if model is not None:
        config_data["agents"]["list"][0]["model"] = model
    if workspace is not None:
        config_data["agents"]["list"][0]["workspace"] = workspace

    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    return config_path


def test_manobot_onboard_creates_agent_files_and_plugin_defaults(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    result = runner.invoke(app, ["onboard", "coder"])

    assert result.exit_code == 0
    assert "Onboarded agent 'coder'" in result.stdout

    agent_config_path = isolated_home / ".manobot" / "agents" / "coder" / "config.json"
    workspace_path = isolated_home / ".manobot" / "agents" / "coder" / "workspace"

    agent_config = json.loads(agent_config_path.read_text(encoding="utf-8"))

    assert not (isolated_home / ".nanobot" / "config.json").exists()
    assert any(agent["id"] == "coder" for agent in agent_config["agents"]["list"])
    assert agent_config["channels"]["fake"] == {"enabled": False, "token": "fake-token"}
    assert (workspace_path / "AGENTS.md").exists()
    assert (workspace_path / "memory" / "MEMORY.md").exists()
    assert (isolated_home / ".manobot" / "agents" / "coder" / "memory").exists()
    assert (isolated_home / ".manobot" / "agents" / "coder" / "sessions").exists()


def test_manobot_top_level_list_alias_returns_agents(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    onboard_result = runner.invoke(app, ["onboard", "coder"])
    assert onboard_result.exit_code == 0

    list_result = runner.invoke(app, ["list", "--json"])

    assert list_result.exit_code == 0
    listed = json.loads(list_result.stdout)
    assert any(agent["id"] == "coder" for agent in listed)


def test_manobot_list_shows_full_config_path(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    agent_id = "coder-with-a-very-long-agent-id-for-config-path"
    config_path = _seed_registered_agent(isolated_home, agent_id)

    result = runner.invoke(app, ["list"], terminal_width=200)

    assert result.exit_code == 0
    assert str(config_path) in result.stdout


def test_manobot_onboard_assistant_first_run_does_not_prompt_overwrite(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    result = runner.invoke(app, ["onboard", "assistant"])

    assert result.exit_code == 0
    assert "already exists" not in result.stdout
    assert "Onboarded agent 'assistant'" in result.stdout


def test_manobot_onboard_refresh_preserves_existing_agent_values(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    config_path = _seed_registered_agent(
        isolated_home,
        "coder",
        name="Code Assistant",
        model="deepseek/deepseek-coder",
        channels={},
    )

    result = runner.invoke(app, ["onboard", "coder", "-w", "~/code"], input="n\n")

    assert result.exit_code == 0
    assert "Refreshed agent 'coder'" in result.stdout

    agent_config = json.loads(config_path.read_text(encoding="utf-8"))
    coder = next(agent for agent in agent_config["agents"]["list"] if agent["id"] == "coder")

    assert coder["name"] == "Code Assistant"
    assert coder["model"] == "deepseek/deepseek-coder"
    assert coder["workspace"] == "~/code"
    assert agent_config["channels"]["fake"] == {"enabled": False, "token": "fake-token"}
    assert not (isolated_home / ".nanobot" / "config.json").exists()


def test_manobot_onboard_reset_replaces_existing_agent_values(monkeypatch, isolated_home):
    monkeypatch.setattr("agent.channels.registry.discover_all", lambda: {"fake": _FakeChannel})

    config_path = _seed_registered_agent(
        isolated_home,
        "coder",
        name="Code Assistant",
        model="deepseek/deepseek-coder",
        workspace="~/old-code",
    )

    result = runner.invoke(app, ["onboard", "coder"], input="y\n")

    assert result.exit_code == 0
    assert "Reset agent 'coder'" in result.stdout

    agent_config = json.loads(config_path.read_text(encoding="utf-8"))
    coder = next(agent for agent in agent_config["agents"]["list"] if agent["id"] == "coder")

    assert coder["id"] == "coder"
    assert coder["default"] is True
    assert "name" not in coder
    assert "model" not in coder
    assert coder["workspace"] == str(isolated_home / ".manobot" / "agents" / "coder" / "workspace")
    assert not (isolated_home / ".nanobot" / "config.json").exists()

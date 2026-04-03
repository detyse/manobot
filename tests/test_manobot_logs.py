from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.config import loader as config_loader
from mano.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_loader, "_current_config_path", None)
    yield tmp_path
    monkeypatch.setattr(config_loader, "_current_config_path", None)


def _seed_registered_agent(home_dir: Path, agent_id: str) -> Path:
    registry_path = home_dir / ".manobot" / "agents" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        f'{{"defaultAgent": "{agent_id}", "agents": ["{agent_id}"]}}',
        encoding="utf-8",
    )

    config_path = home_dir / ".manobot" / "agents" / agent_id / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f'{{"agents": {{"list": [{{"id": "{agent_id}", "default": true}}]}}}}',
        encoding="utf-8",
    )
    return config_path


def test_logs_command_reads_agent_runner_log(isolated_home):
    config_path = _seed_registered_agent(isolated_home, "coder")
    log_path = config_path.parent / "logs" / "runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("line 1\nline 2\n", encoding="utf-8")

    result = runner.invoke(app, ["logs", "coder"])

    assert result.exit_code == 0
    assert str(log_path) in result.stdout
    assert "line 1" in result.stdout
    assert "line 2" in result.stdout


def test_logs_command_with_follow_uses_follow_helper(isolated_home, monkeypatch):
    config_path = _seed_registered_agent(isolated_home, "coder")
    log_path = config_path.parent / "logs" / "runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("line 1\n", encoding="utf-8")

    calls: list[Path] = []

    def fake_follow(path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr("mano.cli.agents._follow_log_file", fake_follow)

    result = runner.invoke(app, ["logs", "coder", "-f"])

    assert result.exit_code == 0
    assert calls == [log_path]


def test_logs_command_reports_missing_log_file(isolated_home):
    _seed_registered_agent(isolated_home, "coder")

    result = runner.invoke(app, ["logs", "coder"])

    assert result.exit_code == 1
    assert "Log file not found" in result.stdout
    assert "Start the agent first" in result.stdout

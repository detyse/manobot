from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from mano.cli.main import app
from mano.core import process_manager as process_manager_mod
from mano.core.state import AgentProcessState, StateFile

runner = CliRunner()


class _FakeStderr:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, *, pid: int, returncode: int, stderr_lines: list[bytes]):
        self.pid = pid
        self.returncode = returncode
        self.stderr = _FakeStderr(stderr_lines)

    async def wait(self) -> int:
        return self.returncode


def test_start_agent_surfaces_stderr_and_writes_runner_log(tmp_path, monkeypatch):
    config_path = tmp_path / "agents" / "zabot" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}", encoding="utf-8")

    fake_process = _FakeProcess(
        pid=4321,
        returncode=1,
        stderr_lines=[
            b"bootstrap warning\n",
            b'Error: "feishu" has empty allowFrom (denies all).\n',
        ],
    )

    async def fake_spawn(*args, **kwargs):
        return fake_process

    monkeypatch.setattr(process_manager_mod, "load_state", lambda: StateFile())
    monkeypatch.setattr(process_manager_mod, "save_state", lambda state: None)
    monkeypatch.setattr(process_manager_mod, "cleanup_stale", lambda state: state)
    monkeypatch.setattr(process_manager_mod, "get_agent_config_path", lambda agent_id: config_path)
    monkeypatch.setattr(process_manager_mod.asyncio, "create_subprocess_exec", fake_spawn)

    manager = process_manager_mod.ProcessManager(base_port=18791)

    result = asyncio.run(manager.start_agent("zabot"))

    assert result.status == "crashed"
    assert result.error_message == 'Error: "feishu" has empty allowFrom (denies all).'
    assert result.log_path == str(config_path.parent / "logs" / "runner.log")

    log_text = Path(result.log_path).read_text(encoding="utf-8")
    assert f"starting agent 'zabot' on port {result.port}" in log_text
    assert 'Error: "feishu" has empty allowFrom (denies all).' in log_text


def test_status_shows_agent_log_paths(monkeypatch):
    state = StateFile(
        supervisor_pid=9999,
        agents={
            "zabot": AgentProcessState(
                agent_id="zabot",
                pid=4321,
                port=18794,
                status="crashed",
                error_message="config validation failed",
                log_path="/tmp/zabot-runner.log",
                config_path="/tmp/zabot-config.json",
            )
        },
    )

    monkeypatch.setattr("mano.agents.init.initialize_manobot", lambda: {"success": True})
    monkeypatch.setattr("mano.agents.registry.list_registered_agent_ids", lambda: ["zabot"])
    monkeypatch.setattr("mano.agents.registry.resolve_default_registered_agent_id", lambda: "zabot")
    monkeypatch.setattr("mano.core.state.load_state", lambda: state)
    monkeypatch.setattr("mano.core.state.cleanup_stale", lambda loaded: loaded)
    monkeypatch.setattr("mano.core.state.save_state", lambda loaded: None)
    monkeypatch.setattr("mano.core.state.is_supervisor_alive", lambda: True)

    result = runner.invoke(app, ["status"], terminal_width=160)

    assert result.exit_code == 0
    assert "config validation failed" in result.stdout
    assert "/tmp/zabot-runner.log" in result.stdout

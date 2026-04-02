from types import SimpleNamespace

from typer.testing import CliRunner

from mano.cli import main as cli_main

runner = CliRunner()


def test_build_agent_shortcut_argv_for_named_agent():
    assert cli_main._build_agent_shortcut_argv(["zabot", "-m", "hi"]) == [
        "agent",
        "--agent",
        "zabot",
        "-m",
        "hi",
    ]


def test_build_agent_shortcut_argv_for_default_agent():
    assert cli_main._build_agent_shortcut_argv(["-m", "hi"]) == [
        "agent",
        "-m",
        "hi",
    ]


def test_build_agent_shortcut_argv_for_agent_channels_status():
    assert cli_main._build_agent_shortcut_argv(["zabot", "channels", "status"]) == [
        "channels",
        "status",
        "--agent",
        "zabot",
    ]


def test_build_agent_shortcut_argv_for_agent_channels_help():
    assert cli_main._build_agent_shortcut_argv(["zabot", "channels", "--help"]) == [
        "channels",
        "--help",
    ]


def test_root_shortcut_delegates_to_agent_command(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, check=False):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    result = runner.invoke(cli_main.app, ["zabot", "-m", "hi"])

    assert result.exit_code == 0
    assert calls
    assert calls[0][1:] == ["agent", "--agent", "zabot", "-m", "hi"]


def test_root_shortcut_delegates_to_default_agent_command(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, check=False):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    result = runner.invoke(cli_main.app, ["-m", "hi"])

    assert result.exit_code == 0
    assert calls
    assert calls[0][1:] == ["agent", "-m", "hi"]


def test_root_shortcut_delegates_to_agent_channels_command(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, check=False):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    result = runner.invoke(cli_main.app, ["zabot", "channels", "status"])

    assert result.exit_code == 0
    assert calls
    assert calls[0][1:] == ["channels", "status", "--agent", "zabot"]


def test_root_shortcut_delegates_to_agent_channels_help(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, check=False):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    result = runner.invoke(cli_main.app, ["zabot", "channels", "--help"])

    assert result.exit_code == 0
    assert calls
    assert calls[0][1:] == ["channels", "--help"]


def test_known_subcommand_is_not_shortcut_delegated(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, check=False):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    result = runner.invoke(cli_main.app, ["list", "--help"])

    assert result.exit_code == 0
    assert not calls


def test_tui_help_renders():
    result = runner.invoke(cli_main.app, ["tui", "--help"])

    assert result.exit_code == 0
    assert "prompt_toolkit-based chat UI" in result.stdout

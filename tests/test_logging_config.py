from __future__ import annotations

import logging
import sys

from agent.config.schema import LoggingConfig
from agent.utils import logging_config as logging_config_mod


class FakeLogger:
    def __init__(self) -> None:
        self.remove_calls = 0
        self.enable_calls: list[str] = []
        self.add_calls: list[tuple[tuple, dict]] = []
        self.debug_calls: list[tuple[tuple, dict]] = []

    def remove(self) -> None:
        self.remove_calls += 1

    def enable(self, name: str) -> None:
        self.enable_calls.append(name)

    def add(self, *args, **kwargs) -> int:
        self.add_calls.append((args, kwargs))
        return len(self.add_calls)

    def debug(self, *args, **kwargs) -> None:
        self.debug_calls.append((args, kwargs))


def test_resolve_level_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("MANOBOT_LOG_LEVEL", "error")
    config = LoggingConfig(level="INFO")
    assert logging_config_mod._resolve_level(config) == "ERROR"


def test_make_module_filter_honors_tagged_level() -> None:
    filter_fn = logging_config_mod._make_module_filter({"channel": "ERROR"})
    assert filter_fn is not None

    tagged_info = {"message": "[Feishu] info", "level": type("L", (), {"no": logging.INFO})()}
    tagged_error = {"message": "[Feishu] error", "level": type("L", (), {"no": logging.ERROR})()}
    untagged_info = {"message": "plain info", "level": type("L", (), {"no": logging.INFO})()}

    assert filter_fn(tagged_info) is False
    assert filter_fn(tagged_error) is True
    assert filter_fn(untagged_info) is True


def test_setup_logging_configures_console_and_file(tmp_path, monkeypatch) -> None:
    fake_logger = FakeLogger()
    monkeypatch.setattr(logging_config_mod, "logger", fake_logger)

    log_path = tmp_path / "logs" / "app.log"
    config = LoggingConfig(
        level="WARNING",
        format="json",
        file=str(log_path),
        modules={"api": "ERROR"},
    )

    logging_config_mod.setup_logging(config)

    assert fake_logger.remove_calls == 1
    assert fake_logger.enable_calls == ["agent"]
    assert len(fake_logger.add_calls) == 2

    console_args, console_kwargs = fake_logger.add_calls[0]
    assert console_args[0] is sys.stderr
    assert console_kwargs["level"] == "WARNING"
    assert console_kwargs["serialize"] is True

    file_args, file_kwargs = fake_logger.add_calls[1]
    assert file_args[0] == str(log_path)
    assert file_kwargs["serialize"] is True
    assert log_path.parent.exists()


def test_setup_logging_verbose_forces_debug(monkeypatch) -> None:
    fake_logger = FakeLogger()
    monkeypatch.setattr(logging_config_mod, "logger", fake_logger)

    logging_config_mod.setup_logging(LoggingConfig(level="ERROR"), verbose=True)

    console_args, console_kwargs = fake_logger.add_calls[0]
    assert console_args[0] is sys.stderr
    assert console_kwargs["level"] == "DEBUG"


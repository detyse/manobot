"""Unified logging configuration for manobot.

Supports:
- Console and file output
- Log level per module (channel, provider, api, loop)
- JSON format for structured logging
- File rotation by size and retention by days
- Environment variable override: MANOBOT_LOG_LEVEL
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from agent.config.schema import LoggingConfig

# Module-level filter tags used in log messages, e.g. "[Feishu]", "[Provider]"
_MODULE_TAGS = {
    "channel": ("[Channel:", "[Feishu]", "[Telegram]", "[Discord]", "[Slack]", "[Dingtalk]", "[Wecom]", "[Email]", "[Matrix]", "[QQ]", "[Mochat]", "[WhatsApp]"),
    "provider": ("[Provider]",),
    "api": ("[API]",),
    "loop": ("[Loop]",),
}


def _resolve_level(config: LoggingConfig) -> str:
    """Resolve effective log level: env > config > default."""
    env_level = os.environ.get("MANOBOT_LOG_LEVEL", "").upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return env_level
    return config.level.upper()


def _make_module_filter(module_levels: dict[str, str]):
    """Create a loguru filter that applies per-module log levels.

    Messages tagged with module prefixes (e.g. ``[Feishu]``) are checked
    against the module-specific level.  Untagged messages use the global level.
    """
    # Pre-compute numeric levels for each module tag
    import logging as _logging
    tag_levels: dict[str, int] = {}
    for module_name, tags in _MODULE_TAGS.items():
        level_str = module_levels.get(module_name, "").upper()
        if level_str:
            numeric = getattr(_logging, level_str, None)
            if numeric is not None:
                for tag in tags:
                    tag_levels[tag] = numeric

    if not tag_levels:
        return None  # No module-level filtering needed

    def _filter(record):
        msg = record["message"]
        for tag, required_level in tag_levels.items():
            if tag in msg:
                return record["level"].no >= required_level
        return True  # Allow untagged messages through

    return _filter


def setup_logging(config: LoggingConfig | None = None, *, verbose: bool = False) -> None:
    """Configure loguru based on LoggingConfig.

    Args:
        config: Logging configuration. Uses defaults if None.
        verbose: If True, force DEBUG level regardless of config.
    """
    if config is None:
        from agent.config.schema import LoggingConfig
        config = LoggingConfig()

    # Remove all existing handlers
    logger.remove()

    # Re-enable agent module logging (runner.py previously disabled it)
    logger.enable("agent")

    level = "DEBUG" if verbose else _resolve_level(config)

    # Build filter for per-module levels
    module_filter = _make_module_filter(config.modules) if config.modules else None

    # Console handler
    if config.format == "json":
        logger.add(
            sys.stderr,
            level=level,
            format="{message}",
            serialize=True,
            filter=module_filter,
        )
    else:
        logger.add(
            sys.stderr,
            level=level,
            format="<level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            filter=module_filter,
        )

    # File handler (optional)
    if config.file:
        from pathlib import Path
        log_path = Path(config.file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            level=level,
            rotation=f"{config.max_size_mb} MB",
            retention=f"{config.retention_days} days",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            filter=module_filter,
            serialize=(config.format == "json"),
        )

    logger.debug("Logging configured: level={}, format={}, file={}", level, config.format, config.file)

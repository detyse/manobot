"""Multi-account channel instance factory.

Creates channel instances for each (channel, account_id) pair,
supporting multiple bot accounts on the same platform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel
    from nanobot.config.schema import Config

    from manobot.accounts.registry import AccountRegistry


# Mapping of channel names to (module_path, class_name, config_attr)
_CHANNEL_REGISTRY: dict[str, tuple[str, str, str]] = {
    "telegram": ("nanobot.channels.telegram", "TelegramChannel", "telegram"),
    "whatsapp": ("nanobot.channels.whatsapp", "WhatsAppChannel", "whatsapp"),
    "discord": ("nanobot.channels.discord", "DiscordChannel", "discord"),
    "feishu": ("nanobot.channels.feishu", "FeishuChannel", "feishu"),
    "mochat": ("nanobot.channels.mochat", "MochatChannel", "mochat"),
    "dingtalk": ("nanobot.channels.dingtalk", "DingTalkChannel", "dingtalk"),
    "email": ("nanobot.channels.email", "EmailChannel", "email"),
    "slack": ("nanobot.channels.slack", "SlackChannel", "slack"),
    "qq": ("nanobot.channels.qq", "QQChannel", "qq"),
    "matrix": ("nanobot.channels.matrix", "MatrixChannel", "matrix"),
}

# Channels that accept a groq_api_key kwarg
_CHANNELS_WITH_GROQ = {"telegram"}


def _import_channel_class(module_path: str, class_name: str):
    """Dynamically import a channel class."""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _get_channel_config(config: Config, config_attr: str):
    """Get the channel-specific config object."""
    return getattr(config.channels, config_attr, None)


def build_channels(
    config: Config,
    bus: MessageBus,
    account_registry: AccountRegistry,
) -> dict[str, BaseChannel]:
    """Build channel instances for all configured accounts.

    For each enabled channel platform, creates one instance per registered
    account. The dict key is ``"{channel}:{account_id}"`` for multi-account
    channels, or just ``"{channel}"`` for single-account channels (backwards
    compatible).

    When a channel has only a single "default" account, the key is the bare
    channel name (e.g. ``"telegram"``) to maintain compatibility with the
    existing ``ChannelManager`` dispatch logic.

    Args:
        config: Application configuration
        bus: Message bus
        account_registry: Account registry with resolved accounts

    Returns:
        Dict mapping channel key to BaseChannel instance
    """
    channels: dict[str, BaseChannel] = {}

    for channel_name, (module_path, class_name, config_attr) in _CHANNEL_REGISTRY.items():
        channel_config = _get_channel_config(config, config_attr)
        if not channel_config or not channel_config.enabled:
            continue

        account_ids = account_registry.list_accounts_for_channel(channel_name)
        if not account_ids:
            # No accounts but channel is enabled — use default
            account_ids = ["default"]

        try:
            channel_cls = _import_channel_class(module_path, class_name)
        except ImportError as e:
            logger.warning("{} channel not available: {}", channel_name, e)
            continue

        for account_id in account_ids:
            # Build kwargs for channel constructor
            kwargs: dict = {}

            # Some channels accept extra kwargs
            if channel_name in _CHANNELS_WITH_GROQ:
                kwargs["groq_api_key"] = config.providers.groq.api_key

            try:
                instance = channel_cls(channel_config, bus, account_id=account_id, **kwargs)
            except TypeError:
                # Channel class doesn't accept account_id yet — fall back
                # to the old signature (config, bus)
                try:
                    instance = channel_cls(channel_config, bus, **kwargs)
                except TypeError:
                    instance = channel_cls(channel_config, bus)

            # Use simple key for single default account, compound key otherwise
            if len(account_ids) == 1 and account_id == "default":
                key = channel_name
            else:
                key = f"{channel_name}:{account_id}"

            channels[key] = instance
            logger.info(
                "Created channel instance: {} (account={})", key, account_id,
            )

    return channels

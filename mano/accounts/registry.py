"""Account registry for multi-account channel management.

Manages channel account configurations, resolving tokens from direct
values or environment variables, and providing fallback generation
from legacy single-account channel configs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import AccountEntryConfig, Config


class AccountRegistry:
    """Registry for channel account configurations.

    Supports multiple accounts per channel platform (e.g. two Discord bots,
    three Telegram bots) each identified by a unique account_id.
    """

    def __init__(self, config: Config):
        """Initialize the account registry.

        Args:
            config: Application configuration
        """
        # _entries: { channel_name: { account_id: AccountEntryConfig } }
        self._entries: dict[str, dict[str, AccountEntryConfig]] = {}
        self._load_from_config(config)

    def _load_from_config(self, config: Config) -> None:
        """Load accounts from config.accounts, then fill gaps from channels config."""
        # Load explicit accounts
        if config.accounts:
            for channel_name, accounts_map in config.accounts.items():
                self._entries[channel_name] = dict(accounts_map)
                logger.debug(
                    "Loaded {} account(s) for channel '{}'",
                    len(accounts_map),
                    channel_name,
                )

        # Build fallback entries from channels config for any channel
        # that has no explicit accounts defined
        self._build_fallback_from_channels(config)

    def _build_fallback_from_channels(self, config: Config) -> None:
        """Generate default account entries from legacy channel configs.

        For each enabled channel that has no explicit account entries,
        creates a single "default" account using the token from the
        channel config.
        """
        from nanobot.config.schema import AccountEntryConfig

        channel_token_map = {
            "telegram": getattr(config.channels.telegram, "token", None),
            "discord": getattr(config.channels.discord, "token", None),
            "whatsapp": getattr(config.channels.whatsapp, "bridge_token", None),
            "feishu": None,  # Uses app_id/app_secret, not a simple token
            "dingtalk": None,  # Uses client_id/client_secret
            "slack": getattr(config.channels.slack, "bot_token", None),
            "qq": None,  # Uses app_id/secret
            "matrix": getattr(config.channels.matrix, "access_token", None),
            "email": None,  # Uses imap/smtp credentials
            "mochat": getattr(config.channels.mochat, "claw_token", None),
        }

        for channel_name, token in channel_token_map.items():
            if channel_name in self._entries:
                continue  # Already has explicit accounts
            if token:
                self._entries[channel_name] = {
                    "default": AccountEntryConfig(token=token),
                }

    def list_all(self) -> dict[str, list[str]]:
        """Return all registered accounts grouped by channel.

        Returns:
            Dict mapping channel name to list of account IDs.
        """
        return {
            channel: list(accounts.keys())
            for channel, accounts in self._entries.items()
        }

    def get_config(self, channel: str, account_id: str) -> AccountEntryConfig | None:
        """Get account configuration.

        Args:
            channel: Channel platform name
            account_id: Account identifier

        Returns:
            AccountEntryConfig or None if not found
        """
        channel_accounts = self._entries.get(channel)
        if not channel_accounts:
            return None
        return channel_accounts.get(account_id)

    def get_token(self, channel: str, account_id: str) -> str | None:
        """Resolve the token for an account.

        Checks direct token value first, then environment variable.

        Args:
            channel: Channel platform name
            account_id: Account identifier

        Returns:
            Resolved token string, or None
        """
        entry = self.get_config(channel, account_id)
        if not entry:
            return None

        # Direct token takes precedence
        if entry.token:
            return entry.token

        # Try environment variable
        if entry.token_env:
            token = os.environ.get(entry.token_env)
            if token:
                return token
            logger.warning(
                "Account {}/{}: token_env='{}' not found in environment",
                channel,
                account_id,
                entry.token_env,
            )

        return None

    def list_accounts_for_channel(self, channel: str) -> list[str]:
        """List all account IDs for a given channel.

        Args:
            channel: Channel platform name

        Returns:
            List of account IDs, or empty list
        """
        channel_accounts = self._entries.get(channel)
        if not channel_accounts:
            return []
        return list(channel_accounts.keys())

    def has_multi_accounts(self, channel: str) -> bool:
        """Check if a channel has more than one account configured.

        Args:
            channel: Channel platform name

        Returns:
            True if multiple accounts exist
        """
        return len(self.list_accounts_for_channel(channel)) > 1

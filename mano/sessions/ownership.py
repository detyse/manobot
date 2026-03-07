"""Session ownership store — hard constraint on session-to-agent mapping.

Every session belongs to exactly one agent.  The ownership is determined
by the route decision (which agent?) and the peer fingerprint (which
conversation?).  Session keys carry an ``agent:`` prefix so ownership
is always unambiguous.

Session key formats:
  - New:    ``"agent:{agent_id}:{channel}:{peer_id}"``
  - New (threaded): ``"agent:{agent_id}:{channel}:{peer_id}:{thread_id}"``
  - Legacy: ``"{agent_id}:{channel}:{chat_id}"``   (no ``agent:`` prefix)
  - Ancient: ``"{channel}:{chat_id}"``              (no agent at all)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from mano.agents.scope import normalize_agent_id


@dataclass(frozen=True)
class PeerFingerprint:
    """Uniquely identifies a conversation endpoint."""

    channel: str
    account_id: str = "default"
    peer_id: str = ""
    thread_id: str | None = None

    @property
    def cache_key(self) -> str:
        """Deterministic string used as dict key."""
        parts = [self.channel, self.account_id, self.peer_id]
        if self.thread_id:
            parts.append(self.thread_id)
        return ":".join(parts)


@dataclass
class SessionOwnership:
    """Records which agent owns a session for a given peer."""

    agent_id: str
    session_key: str
    fingerprint: PeerFingerprint
    created_at: datetime = field(default_factory=datetime.now)


class SessionOwnershipStore:
    """Manages peer -> agent session ownership.

    The store ensures that:
    - Route decision is made BEFORE session key is computed.
    - Same peer + same agent = same session key (reuse).
    - If the agent changes (re-binding), a new session is created.
    - Session keys always carry a deterministic ``agent:`` prefix.
    """

    def __init__(self) -> None:
        # Maps fingerprint.cache_key -> SessionOwnership
        self._ownership: dict[str, SessionOwnership] = {}

    def resolve(
        self,
        agent_id: str,
        fingerprint: PeerFingerprint,
    ) -> SessionOwnership:
        """Resolve or create session ownership for a peer.

        If the peer already has an ownership record with the same agent,
        the existing session is reused.  If the agent changed (e.g. binding
        was updated), a new session is created.

        Args:
            agent_id: Agent ID from route decision
            fingerprint: Peer fingerprint identifying the conversation

        Returns:
            SessionOwnership with the deterministic session key
        """
        normalized_agent = normalize_agent_id(agent_id)
        cache_key = fingerprint.cache_key

        existing = self._ownership.get(cache_key)
        if existing and existing.agent_id == normalized_agent:
            return existing

        # Create new ownership (agent changed or first time)
        session_key = self.build_session_key(
            agent_id=normalized_agent,
            channel=fingerprint.channel,
            peer_id=fingerprint.peer_id,
            account_id=fingerprint.account_id,
            thread_id=fingerprint.thread_id,
        )
        ownership = SessionOwnership(
            agent_id=normalized_agent,
            session_key=session_key,
            fingerprint=fingerprint,
        )
        self._ownership[cache_key] = ownership
        return ownership

    @staticmethod
    def build_session_key(
        agent_id: str,
        channel: str,
        peer_id: str,
        account_id: str = "default",
        thread_id: str | None = None,
    ) -> str:
        """Build a session key with the ``agent:`` prefix.

        Format: ``agent:{agent_id}:{account_id}:{channel}:{peer_id}[:{thread_id}]``

        Args:
            agent_id: Normalized agent ID
            channel: Channel name
            peer_id: Peer/chat ID
            account_id: Account identifier (default: "default")
            thread_id: Optional thread ID for thread-scoped sessions

        Returns:
            Session key string
        """
        normalized = normalize_agent_id(agent_id)
        if thread_id:
            return f"agent:{normalized}:{account_id}:{channel}:{peer_id}:{thread_id}"
        return f"agent:{normalized}:{account_id}:{channel}:{peer_id}"

    @staticmethod
    def parse_session_key(session_key: str) -> dict[str, str | None]:
        """Parse a session key into components.

        Supports four formats:
        - New:      ``"agent:{agent_id}:{account_id}:{channel}:{peer_id}[:{thread_id}]"``
        - V1 (no account): ``"agent:{agent_id}:{channel}:{peer_id}[:{thread_id}]"``
        - Legacy:   ``"{agent_id}:{channel}:{chat_id}"``
        - Ancient:  ``"{channel}:{chat_id}"``

        Args:
            session_key: Session key string

        Returns:
            Dict with agent_id, account_id, channel, peer_id, and thread_id
        """
        if session_key.startswith("agent:"):
            rest = session_key[len("agent:"):]
            parts = rest.split(":")
            if len(parts) >= 4:
                # New format: agent:{agent_id}:{account_id}:{channel}:{peer_id}[:{thread_id}]
                return {
                    "agent_id": parts[0] or None,
                    "account_id": parts[1],
                    "channel": parts[2],
                    "peer_id": parts[3],
                    "thread_id": parts[4] if len(parts) > 4 else None,
                }
            elif len(parts) == 3:
                # V1 format (no account): agent:{agent_id}:{channel}:{peer_id}
                return {
                    "agent_id": parts[0] or None,
                    "account_id": "default",
                    "channel": parts[1],
                    "peer_id": parts[2],
                    "thread_id": None,
                }

        # Legacy or ancient format
        parts = session_key.split(":", 2)
        if len(parts) == 3:
            # Legacy: agent_id:channel:chat_id
            return {
                "agent_id": parts[0] or None,
                "account_id": "default",
                "channel": parts[1],
                "peer_id": parts[2],
                "thread_id": None,
            }
        elif len(parts) == 2:
            # Ancient: channel:chat_id
            return {
                "agent_id": None,
                "account_id": "default",
                "channel": parts[0],
                "peer_id": parts[1],
                "thread_id": None,
            }
        else:
            return {
                "agent_id": None,
                "account_id": "default",
                "channel": session_key,
                "peer_id": "",
                "thread_id": None,
            }

    def get_agent_for_session(self, session_key: str) -> str | None:
        """Extract the agent ID from a session key.

        Args:
            session_key: Session key string

        Returns:
            Agent ID or None
        """
        parsed = self.parse_session_key(session_key)
        return parsed.get("agent_id")

    def list_all(self) -> list[SessionOwnership]:
        """List all session ownerships."""
        return list(self._ownership.values())

    def clear(self) -> None:
        """Clear all ownership records."""
        self._ownership.clear()

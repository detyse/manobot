import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.bus.events import OutboundMessage
from agent.bus.queue import MessageBus
from agent.channels.feishu import FeishuChannel, FeishuConfig, _FeishuStreamBuf
from agent.channels.manager import ChannelManager
from agent.config.schema import FeishuConfig as SchemaFeishuConfig


def _mock_create_card_response(card_id: str = "card_stream_001"):
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = SimpleNamespace(card_id=card_id)
    return resp


def _mock_send_response(message_id: str = "om_stream_001"):
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = SimpleNamespace(message_id=message_id)
    return resp


def _mock_content_response(success: bool = True):
    resp = MagicMock()
    resp.success.return_value = success
    resp.code = 0 if success else 99999
    resp.msg = "ok" if success else "error"
    return resp


def _make_channel(streaming: bool = True) -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        streaming=streaming,
    )
    ch = FeishuChannel(config, MessageBus())
    ch._client = MagicMock()
    ch._loop = None
    return ch


def test_feishu_channel_revalidates_schema_config_and_enables_streaming():
    bus = MessageBus()
    config = SchemaFeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        group_policy="open",
        reply_to_message=True,
        streaming=True,
    )

    ch = FeishuChannel(config, bus)

    assert ch.config.group_policy == "open"
    assert ch.config.reply_to_message is True
    assert ch.config.streaming is True
    assert ch.supports_streaming is True


def test_feishu_handle_message_marks_wants_stream():
    bus = MessageBus()
    ch = FeishuChannel(
        FeishuConfig(
            enabled=True,
            app_id="cli_test",
            app_secret="secret",
            allow_from=["*"],
            streaming=True,
        ),
        bus,
    )

    asyncio.run(
        ch._handle_message(
            sender_id="ou_user",
            chat_id="oc_chat",
            content="hello",
            metadata={"message_id": "om_1"},
        )
    )

    msg = bus.inbound.get_nowait()
    assert msg.metadata["_wants_stream"] is True
    assert msg.metadata["message_id"] == "om_1"


def test_feishu_send_delta_creates_card_and_updates():
    ch = _make_channel()
    ch._client.cardkit.v1.card.create.return_value = _mock_create_card_response("card_new")
    ch._client.im.v1.message.create.return_value = _mock_send_response("om_new")
    ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()

    asyncio.run(ch.send_delta("oc_chat1", "Hello "))

    buf = ch._stream_bufs["oc_chat1"]
    assert buf.text == "Hello "
    assert buf.card_id == "card_new"
    assert buf.sequence == 1
    ch._client.cardkit.v1.card.create.assert_called_once()
    ch._client.im.v1.message.create.assert_called_once()
    ch._client.cardkit.v1.card_element.content.assert_called_once()


def test_feishu_stream_end_closes_streaming_mode():
    ch = _make_channel()
    ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
        text="Final content",
        card_id="card_1",
        sequence=3,
        last_edit=0.0,
    )
    ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()
    ch._client.cardkit.v1.card.settings.return_value = _mock_content_response()

    asyncio.run(ch.send_delta("oc_chat1", "", metadata={"_stream_end": True}))

    assert "oc_chat1" not in ch._stream_bufs
    ch._client.cardkit.v1.card_element.content.assert_called_once()
    ch._client.cardkit.v1.card.settings.assert_called_once()


class _StreamingFakeChannel:
    def __init__(self):
        self.delta_calls = []
        self.send_calls = []

    async def send_delta(self, chat_id: str, delta: str, metadata=None):
        self.delta_calls.append((chat_id, delta, metadata))

    async def send(self, msg):
        self.send_calls.append(msg)


def test_channel_manager_routes_stream_delta_to_send_delta():
    manager = ChannelManager.__new__(ChannelManager)
    manager.config = SimpleNamespace(
        channels=SimpleNamespace(send_max_retries=3),
    )
    channel = _StreamingFakeChannel()
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_chat1",
        content="delta",
        metadata={"_stream_delta": True},
    )

    asyncio.run(manager._send_with_retry(channel, msg))

    assert channel.delta_calls == [("oc_chat1", "delta", {"_stream_delta": True})]
    assert channel.send_calls == []

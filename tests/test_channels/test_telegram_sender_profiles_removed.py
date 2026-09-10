"""Issue #1542: TelegramChannel._known_sender_profiles grew without bound
and was never read by anything in the codebase -- two writes (enqueue() via
_remember_sender(), and record_access_denial()), zero reads. Deleting the
field and its writers removes the leak entirely rather than just bounding
dead state, since there is no reader to preserve.
"""

from __future__ import annotations

from agentos.channels.telegram import TelegramChannel, TelegramChannelConfig
from agentos.channels.types import IncomingMessage


def _channel() -> TelegramChannel:
    return TelegramChannel(TelegramChannelConfig(token="token"))


def test_known_sender_profiles_field_no_longer_exists() -> None:
    channel = _channel()

    assert not hasattr(channel, "_known_sender_profiles")


def test_enqueue_still_queues_and_dedupes_without_the_removed_bookkeeping() -> None:
    channel = _channel()
    msg = IncomingMessage(
        sender_id="user-1",
        channel_id="chat-1",
        content="hello",
        metadata={"message_id": "m1", "update_id": 1},
    )

    channel.enqueue(msg)
    channel.enqueue(msg)

    assert channel._queue.qsize() == 1


def test_record_access_denial_still_creates_a_pairing_request() -> None:
    channel = _channel()
    msg = IncomingMessage(
        sender_id="user-1",
        channel_id="chat-1",
        content="hi",
        metadata={"sender_username": "someone", "is_group": False},
    )

    channel.record_access_denial(msg, "not_paired")

    snapshot = channel.pairing_store.snapshot(channel.config.name)
    assert any(entry["sender_id"] == "user-1" for entry in snapshot["pending"])

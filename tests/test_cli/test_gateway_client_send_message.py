"""Regression tests for GatewayClient.send_message()'s stale-event handling.

``_recv_queue`` is one connection-wide queue shared by every session this
client has ever subscribed to. Before the fix, a leftover event from an
earlier (e.g. aborted) turn could still be sitting in the queue when the next
``send_message()`` call started, and would be mistaken for that new call's
own completion -- see issue #1790.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.cli.gateway_client import GatewayClient

pytestmark = pytest.mark.asyncio


async def test_send_message_discards_a_stale_event_left_by_an_earlier_call() -> None:
    """A leftover ``session.event.done`` (reason="aborted") from a previous
    turn must not be mistaken for the new call's own completion, and the new
    turn's real output must not be lost."""
    client = GatewayClient()

    async def fake_call(method: str, params: dict | None = None) -> Any:
        if method == "sessions.send":
            # The server only starts emitting events for THIS message once it
            # actually receives it -- i.e. once this RPC is dispatched.
            await client._recv_queue.put(
                {
                    "type": "event",
                    "event": "session.event.text_delta",
                    "payload": {"text": "actual answer"},
                }
            )
            await client._recv_queue.put(
                {"type": "event", "event": "session.event.done", "payload": {"reason": "stop"}}
            )
        return {}

    client._call = fake_call  # type: ignore[method-assign]

    # Leftover terminal event from a prior (aborted) turn on the same
    # session, still queued when the next call starts.
    await client._recv_queue.put(
        {"type": "event", "event": "session.event.done", "payload": {"reason": "aborted"}}
    )

    events = [ev async for ev in client.send_message("session-key", "second message")]

    assert events == [
        {"event": "session.event.text_delta", "text": "actual answer"},
        {"event": "session.event.done", "reason": "stop"},
    ]


async def test_send_message_still_yields_normally_with_no_stale_events() -> None:
    """The drain must not disturb the ordinary happy path (nothing queued
    yet when the call starts)."""
    client = GatewayClient()

    async def fake_call(method: str, params: dict | None = None) -> Any:
        if method == "sessions.send":
            await client._recv_queue.put(
                {
                    "type": "event",
                    "event": "session.event.text_delta",
                    "payload": {"text": "hello"},
                }
            )
            await client._recv_queue.put(
                {"type": "event", "event": "session.event.done", "payload": {"reason": "stop"}}
            )
        return {}

    client._call = fake_call  # type: ignore[method-assign]

    events = [ev async for ev in client.send_message("session-key", "hi")]

    assert events == [
        {"event": "session.event.text_delta", "text": "hello"},
        {"event": "session.event.done", "reason": "stop"},
    ]
